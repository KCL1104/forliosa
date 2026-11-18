"""The data pack of a market report (contract §6): every number, calendar row, filing and shared-research source the
writer may use, each with an id (F / C / N / W; X are the gathered reports, added by the gathering), plus the blocks
the page shows (charts G1–G17, tables, the number strip, the calendar) — built by the server from the archive only.

Rules every builder here keeps:

* Data policy first (``datapolicy.dataset_served``), then the reports' own exclusions (:data:`EXCLUDED_DATASETS`: TAIFEX
  futures / options quotes and the night session, even when the conditional licence is confirmed; the Yahoo history
  backfill — it may only draw G5's lines). US prices only from Databento, only while US_PRICE_SOURCE serves them; no
  US index points anywhere.
* A row is used only if it existed at the pack's cut-off (``timing.usable``): rebuilding a past day never pulls in
  what was published later (the sample's 15:55 report used the next morning's FMTQIK).
* ``display`` is the text the writer copies (▲▼, thousands separators, units); ``value`` the number (moves as
  fractions: −0.0603 is ▼6.03%). Every fact names its ``subject`` (and ``aliases``) so the validator can check that a
  number is said about the right thing, and its date.
* Moves of stocks are from the official reference price; contributions, market caps, sums and TPEx sectors are
  Forliosa's own and flagged ``estimate`` (估算).
* Names come from 公司簡稱 (or the instrument list) only; no other company-profile field ever enters a pack.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.config import get_settings
from forliosa.datapolicy import Policy, dataset_served, label
from forliosa.marketdata.opendata import INDUSTRY_CODES, TAIEX_TR, TPEX_INDEX
from forliosa.models import AiWhyResearch, MarketEvent, MarketReport, MarketReportVersion, MarketTurnoverDaily
from forliosa.reports import blocks as B
from forliosa.reports import calendars as cal
from forliosa.reports import marketcalc as mc
from forliosa.reports.schedule import Edition, edition_on, md, md_wd, span
from forliosa.reports.timing import usable
from forliosa.timeutil import (
    TAIPEI,
    iso_taipei,
    last_tw_trading_day,
    next_tw_trading_day,
    now_taipei,
    tw_trading_days,
)

log = logging.getLogger(__name__)

PACK_VERSION = 1
# The metrics a fact may carry (validators and the writer's rules refer to them)
METRICS = frozenset({
    "index_close", "index_change", "index_pct", "tr_close", "tr_pct", "otc_close", "otc_change", "otc_pct",
    "adv_up", "adv_flat", "adv_down", "limit_up", "limit_down", "turnover", "turnover_est", "mcap_total",
    "mcap_change_est", "sector_pct", "sector_concentration", "stock_close", "stock_pct", "stock_contrib",
    "stock_mcap", "stock_value", "reference_pct", "us_close", "us_pct", "us_holiday", "fx_close", "fx_change",
    "pc_ratio_oi", "pc_ratio_vol", "futures_oi_net", "futures_oi_change", "large_traders", "otc_inst_total",
    "otc_inst_foreign", "otc_inst_trust", "otc_inst_dealer", "otc_adv_up", "otc_adv_down", "industry_value",
    "week_pct", "week_points", "count", "sector_contrib_est",
})
# Position-type numbers: never a reason why something is watched (validator §10.2 item 15)
OPTION_METRICS = frozenset({"pc_ratio_oi", "pc_ratio_vol", "futures_oi_net", "futures_oi_change", "large_traders"})
EXCLUDED_DATASETS = frozenset({"taifex-openapi/futures_daily", "taifex-openapi/options_daily"})
EXCLUDED_PREFIXES = ("yahoo-history",)
US_ROW = (("SPY", "SPY"), ("DIA", "DIA"), ("ONEQ", "ONEQ"), ("SMH", "SMH"), ("TSM", "台積電 ADR"))
US_ALIASES = {"SPY": ["S&P 500 ETF", "標普 ETF"], "DIA": ["道瓊 ETF"], "ONEQ": ["那斯達克 ETF"],
              "SMH": ["半導體 ETF"], "TSM": ["台積電ADR", "TSM"]}
TAIEX_ALIASES = ["加權", "大盤", "集中市場", "台股", "上市"]
OTC_ALIASES = ["櫃買", "上櫃", "OTC"]

MISSING_TEXT = {
    "twse_institutional": "上市三大法人沒有開放資料，只能引用媒體報導。",
    "margin_amount": "融資餘額只有個股張數，跨股票加總沒有意義，暫不列。",
    "us_index_points": "美股指數點數需要授權，只列 ETF 與 ADR 的漲跌。",
    "tx_quotes": "台指期與夜盤行情的授權還沒確認，不列行情。",
    "history_short": "存檔從 2026-11-12 開始，類股 1 個月的比較約 12/9 以後才有。",
}
FIXED_MISSING = ("twse_institutional", "margin_amount", "us_index_points", "tx_quotes", "history_short")
ARCHIVE_START = date(2026, 11, 12)  # the index archive's first day (the 「11/12 起」 column)
HISTORY_ENOUGH = date(2026, 12, 12)  # from here a month back is inside the archive (``missing.history_short`` ends)
RULE_STOCKS = "股票只能寫 stocks 名單裡的公司（依規則挑選，規則寫在表頭）；名單外的股票不能出現。"
# premarket 「今天市場在看什麼」: real events only (the dry run of 11/17 made up 「台股 11/17（二）開盤」 items)
RULE_WATCH = ("watch 的每一項都要是行事曆（C）或報導（X）裡有日期的事件，refs 要有那個 C 或 X；開盤、收盤、"
              "前一個交易日的漲跌都不是事件。")
RULE_WATCH_EMPTY = ("今天的行事曆沒有已排定的事件：watch 只寫報導（X）裡寫明日期的事件；都沒有就給空陣列"
                    "（這時不受 2–4 項的限制），不要湊數。")
# the number strip's 漲停／跌停 when a movers table counts only its scope (「範圍內跌停 17 家」 beside 「6／30 家」)
LIMITS_NOTE = "全部上市普通股；排行表只算範圍內"


@dataclass
class Built:
    """A pack (what the writer reads) and the blocks the page shows."""

    pack: dict[str, Any]
    blocks: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)

    @property
    def facts(self) -> dict[str, dict[str, Any]]:
        return {f["id"]: f for f in self.pack["facts"]}


class Pack:
    """Collects the ids, the facts and the blocks of one pack."""

    def __init__(self, db: Session, edition: Edition, cutoff: datetime, policy: Policy, us_served: bool):
        self.db, self.ed, self.cutoff, self.policy, self.us_served = db, edition, cutoff, policy, us_served
        self.n: dict[str, int] = defaultdict(int)
        self.facts: list[dict[str, Any]] = []
        self.calendar: list[dict[str, Any]] = []
        self.filings: list[dict[str, Any]] = []
        self.research: list[dict[str, Any]] = []
        self.stocks: dict[str, dict[str, Any]] = {}
        self.sectors: list[dict[str, Any]] = []
        self.missing: list[dict[str, Any]] = []
        self.strip: list[str] = []
        self.rules: list[str] = []
        self.menu: list[dict[str, Any]] = []
        self.fixed: list[str] = []
        self.notes: list[str] = []
        self.datasets: set[str] = set()
        self.dates: dict[str, set[str]] = {"report": set(), "us_sessions": set(), "next_period": set(),
                                           "prev_session": set()}
        self.blocks: dict[str, Any] = {"charts": {}, "tables": {}, "numbers": [], "calendar": None, "notes": {}}
        self.already: list[dict[str, Any]] = []
        self.through = data_through(edition)

    # -- ids --------------------------------------------------------------------------------------------------------
    def _id(self, prefix: str) -> str:
        self.n[prefix] += 1
        return f"{prefix}{self.n[prefix]:03d}"

    def ok(self, dataset: str) -> bool:
        """The data policy and the reports' exclusions allow ``dataset``."""
        if dataset in EXCLUDED_DATASETS or dataset.startswith(EXCLUDED_PREFIXES):
            return False
        if dataset.startswith(("rules:", "manual-calendar")):
            return True
        return dataset_served(dataset, self.policy)

    def fact(self, label_: str, subject: str, metric: str, group: str, value: Any, display: str, *, unit: str = "",
             precision: int = 2, day: date | None, dataset: str, aliases: Iterable[str] = (), estimate: bool = False,
             note: str = "") -> str | None:
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric}")
        if not self.ok(dataset):
            return None
        fid = self._id("F")
        if isinstance(value, Decimal):
            value = float(value)
        self.facts.append({"id": fid, "label": label_, "subject": subject, "aliases": list(aliases),
                           "metric": metric, "group": group, "value": value, "display": display, "unit": unit,
                           "precision": precision, "date": day.isoformat() if day else None, "dataset": dataset,
                           "estimate": estimate, "note": note})
        self.datasets.add(dataset)
        return fid

    def miss(self, key: str, text: str | None = None, expected_at: datetime | None = None) -> None:
        if any(m["key"] == key for m in self.missing):
            return
        self.missing.append({"key": key, "text": text or MISSING_TEXT[key],
                             "expected_at": iso_taipei(expected_at) if expected_at else None})

    def number(self, fid: str | None, item: dict[str, Any]) -> None:
        if fid is None:
            return
        self.strip.append(fid)
        self.blocks["numbers"].append(item)

    def chart(self, c: dict[str, Any] | None, key: str | None = None) -> None:
        c = clip_chart(c, self.through)
        if c is not None:
            self.blocks["charts"][key or c["id"]] = c

    def table(self, t: dict[str, Any]) -> None:
        self.blocks["tables"][t["id"]] = t

    def labels(self, keys: Iterable[str]) -> list[str]:
        return [_label(k) for k in dict.fromkeys(keys)]

    # -- stocks -----------------------------------------------------------------------------------------------------
    def stock(self, q: mc.Quote, list_name: str, group: str = "today", *, contrib: Decimal | None = None,
              with_mcap: bool = False, with_value: bool = False, pct: Decimal | None = None,
              pct_label: str | None = None) -> None:
        """Add ``q`` to the stock list (the union of the rule lists) with its facts."""
        entry = self.stocks.get(q.symbol)
        if group == "today" and q.day is not None and q.day < self.ed.period[0]:
            group = "prev_session"  # e.g. an OTC event stock whose close of the day is not out yet
        name = B.stock_label(q.name, q.code)
        aliases = [q.name, q.code]
        day = self.ed.edition_date if group == "today" else self.ed.period[1]
        if entry is None:
            entry = {"symbol": q.symbol, "code": q.code, "name": q.name, "market": q.market, "class": q.cls,
                     "industry": q.industry, "lists": [], "facts": {}}
            self.stocks[q.symbol] = entry
            q_day = self._qday(q)
            entry["facts"]["close"] = self.fact(f"{name} {md(q_day)} 收盤", q.name, "stock_close", group, q.close,
                                                f"{B.price_text(q.close)} 元", unit="元", day=q_day,
                                                dataset=q.dataset, aliases=aliases)
            p = pct if pct is not None else q.pct
            if p is not None:
                entry["facts"]["pct"] = self.fact(pct_label or f"{name} {md(q_day)} 漲跌幅", q.name, "stock_pct",
                                                  group, p, B.pct_text(p), unit="%", day=q_day,
                                                  dataset=q.dataset, aliases=aliases)
        if list_name not in entry["lists"]:
            entry["lists"].append(list_name)
        if contrib is not None and "contrib" not in entry["facts"]:
            entry["facts"]["contrib"] = self.fact(f"{name} 對加權指數點數貢獻（估算）", q.name, "stock_contrib", group,
                                                  round(contrib, 1), B.signed_text(contrib, 0, " 點"), unit="點",
                                                  precision=0, day=day, dataset="rules:contribution",
                                                  aliases=aliases, estimate=True,
                                                  note="前一日加權指數 × 前一日市值權重 × 漲跌幅")
        if with_mcap and q.mcap is not None and "mcap" not in entry["facts"]:
            entry["facts"]["mcap"] = self.fact(f"{name} 市值（收盤 × 已發行股數）", q.name, "stock_mcap", group,
                                               q.mcap, B.zhao_text(q.mcap), unit="兆元", day=self._qday(q),
                                               dataset="rules:market_cap", aliases=aliases, estimate=True)
        if with_value and q.value and "value" not in entry["facts"]:
            entry["facts"]["value"] = self.fact(f"{name} {md(self._qday(q))} 成交金額", q.name, "stock_value",
                                                group, q.value, B.yi_text(q.value, 1), unit="億元", precision=1,
                                                day=self._qday(q), dataset=q.dataset, aliases=aliases)

    def _qday(self, q: mc.Quote) -> date:
        return q.day or self.ed.edition_date

    # -- output -----------------------------------------------------------------------------------------------------
    def build(self) -> Built:
        ed = self.ed
        pack = {
            "pack_version": PACK_VERSION, "kind": ed.kind, "kind_label": ed.kind_label,
            "edition_date": ed.edition_date.isoformat(), "edition_label": ed.label,
            "period": {"start": ed.period[0].isoformat(), "end": ed.period[1].isoformat()},
            "next_period": {"start": ed.next_period[0].isoformat(), "end": ed.next_period[1].isoformat()}
            if ed.next_period else None,
            "cutoff": iso_taipei(self.cutoff), "publish_target": iso_taipei(ed.publish_target),
            "data_through": self.through.isoformat(),
            # the gathering's window and the US sessions it covers (known even when no US close is stored)
            "web_window": {"from": iso_taipei(ed.web_from), "to": iso_taipei(ed.web_to),
                           "us_sessions": [d.isoformat() for d in ed.us_sessions]},
            "dates": {k: sorted(v) for k, v in self.dates.items()},
            "facts": self.facts, "calendar": self.calendar, "filings": self.filings, "research": self.research,
            "web": [], "stocks": list(self.stocks.values()), "sectors": self.sectors, "missing": self.missing,
            "strip": self.strip, "already_reported": self.already, "rules": self.rules, "charts_menu": self.menu,
            "fixed_charts": self.fixed, "notes": self.notes,
        }
        self.blocks["source_labels"] = self.labels(sorted(d for d in self.datasets if not d.startswith("rules:")))
        if any(d.startswith("rules:") for d in self.datasets):
            self.blocks["source_labels"].append(label("rules"))
        return Built(pack, self.blocks, list(self.notes), sorted(self.datasets))


def _label(key: str) -> str:
    if key.startswith("rules:"):
        return label("rules")
    return label(key)


def data_through(ed: Edition) -> date:
    """The last Taiwan session an edition's charts and tables may show: the previous session for the premarket (its
    cut-off comes before the day's close), the edition's day for the close, the week's end for the weekly. A rebuild,
    a rerun or a correction never draws a later day."""
    if ed.kind == "premarket" and ed.prev_session is not None:
        return ed.prev_session
    return ed.period[1]


def clip_chart(c: dict[str, Any] | None, through: date) -> dict[str, Any] | None:
    """``c`` without the points after ``through`` (every dated series); ``None`` when a line or a comparison keeps
    fewer than two points (nothing left to draw)."""
    if not isinstance(c, dict) or not c.get("series"):
        return c
    last = through.isoformat()
    series = []
    for s in c["series"]:
        pts = [pt for pt in s.get("points") or [] if str(pt.get("t"))[:10] <= last]
        if pts:
            series.append({**s, "points": pts})
    drawn = [s for s in series if not s.get("hidden")]
    if c.get("kind") in ("line", "compare", "price"):
        drawn = [s for s in drawn if len(s["points"]) >= 2]
    if len(drawn) < (2 if c.get("kind") == "compare" else 1):
        return None
    return {**c, "series": series}


# -- entry point -----------------------------------------------------------------------------------------------------
def build(db: Session, kind: str, edition_date: date, *, cutoff: datetime | None = None,
          policy: Policy | None = None, now: datetime | None = None, md_: Any = None) -> Built:
    """The pack and blocks of the ``kind`` edition dated ``edition_date``, from rows that existed at ``cutoff``
    (default: the edition's own cut-off, or ``now`` when that is earlier). Raises ``ValueError`` when there is no such
    edition (a closed day for a daily one, not a Sunday for the weekly)."""
    ed = edition_on(kind, edition_date)
    if ed is None:
        raise ValueError(f"no {kind} edition on {edition_date}")
    settings = get_settings()
    policy = policy or settings.data_policy
    now = now or now_taipei()
    if cutoff is None:
        cutoff = min(ed.cutoff, now)
    cal.load_us_calendar(db)
    p = Pack(db, ed, cutoff.astimezone(TAIPEI), policy, settings.us_prices_served)
    for key in FIXED_MISSING:
        if key != "history_short" or edition_date < HISTORY_ENOUGH:
            p.miss(key)
    p.dates["report"].add(edition_date.isoformat())
    if kind == "close":
        _close(p, md_)
    elif kind == "premarket":
        _premarket(p, md_)
    else:
        _weekly(p, md_)
    return p.build()


# -- shared pieces -----------------------------------------------------------------------------------------------------
def _index_facts(p: Pack, day: date, group: str, *, with_tr: bool = True, with_otc: bool = True,
                 strip: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    t = mc.index_on(p.db, mc.TAIEX, day, p.cutoff, p.policy)
    if t is not None:
        out["taiex"] = t
        f1 = p.fact(f"加權指數 {md(day)} 收盤", "加權指數", "index_close", group, t.close, B.number_text(t.close),
                    unit="點", day=day, dataset=t.dataset, aliases=TAIEX_ALIASES)
        if t.change is not None:
            out["taiex_change"] = p.fact(f"加權指數 {md(day)} 漲跌點數", "加權指數", "index_change", group, t.change,
                                         B.points_text(t.change), unit="點", day=day, dataset=t.dataset,
                                         aliases=TAIEX_ALIASES)
        if t.pct is not None:
            out["taiex_pct"] = p.fact(f"加權指數 {md(day)} 漲跌幅", "加權指數", "index_pct", group, t.pct,
                                      B.pct_text(t.pct), unit="%", day=day, dataset=t.dataset, aliases=TAIEX_ALIASES)
        out["taiex_close"] = f1
        if strip:
            p.strip.extend(x for x in (out.get("taiex_change"), out.get("taiex_pct")) if x)
            p.number(f1, B.number("taiex", "加權指數", B.number_text(t.close),
                                  change=f"{B.points_text(t.change)}（{B.pct_text(t.pct)}）" if t.change is not None
                                  and t.pct is not None else None, tone_=B.tone(t.change), date_label=md(day)))
    if with_tr:
        tr = mc.index_on(p.db, TAIEX_TR, day, p.cutoff, p.policy)
        if tr is not None:
            fid = p.fact(f"發行量加權股價報酬指數 {md(day)} 收盤", "報酬指數", "tr_close", group, tr.close,
                         B.number_text(tr.close), unit="點", day=day, dataset=tr.dataset, aliases=["加權報酬指數"])
            if tr.pct is not None:
                p.fact(f"發行量加權股價報酬指數 {md(day)} 漲跌幅", "報酬指數", "tr_pct", group, tr.pct,
                       B.pct_text(tr.pct), unit="%", day=day, dataset=tr.dataset, aliases=["加權報酬指數"])
            if strip:
                p.number(fid, B.number("tr", "報酬指數", B.number_text(tr.close),
                                       change=B.pct_text(tr.pct) if tr.pct is not None else None,
                                       tone_=B.tone(tr.pct), date_label=md(day)))
    if with_otc:
        o = mc.index_on(p.db, TPEX_INDEX, day, p.cutoff, p.policy)
        if o is not None:
            out["otc"] = o
            fid = p.fact(f"櫃買指數 {md(day)} 收盤", "櫃買指數", "otc_close", group, o.close, B.number_text(o.close),
                         unit="點", day=day, dataset=o.dataset, aliases=OTC_ALIASES)
            if o.change is not None:
                p.fact(f"櫃買指數 {md(day)} 漲跌點數", "櫃買指數", "otc_change", group, o.change,
                       B.points_text(o.change), unit="點", day=day, dataset=o.dataset, aliases=OTC_ALIASES)
            if o.pct is not None:
                p.fact(f"櫃買指數 {md(day)} 漲跌幅", "櫃買指數", "otc_pct", group, o.pct, B.pct_text(o.pct), unit="%",
                       day=day, dataset=o.dataset, aliases=OTC_ALIASES)
            if strip:
                p.number(fid, B.number("otc", "櫃買指數", B.number_text(o.close),
                                       change=f"{B.points_text(o.change)}（{B.pct_text(o.pct)}）"
                                       if o.change is not None and o.pct is not None else None,
                                       tone_=B.tone(o.change), date_label=md(day)))
        else:
            p.miss("otc_index", f"櫃買指數 {md(day)} 還沒有進來（櫃買中心約 14:30 公布）。",
                   datetime.combine(day, datetime.min.time(), TAIPEI) + timedelta(hours=14, minutes=30))
    return out


def _breadth_facts(p: Pack, day: mc.Day, group: str, strip: bool = False,
                   prefix: str = "上市普通股") -> mc.Breadth | None:
    """Advancers, decliners and limit moves; ``None`` (and a missing note) when no move can be measured (no previous
    close and no reference price in the archive)."""
    if not any(q.pct is not None for q in day.commons()):
        p.miss(f"breadth_{day.market.lower()}",
               f"{prefix} {md(day.day)} 的漲跌家數要有前一個交易日的收盤，存檔還沒有。")
        return None
    br = mc.breadth(day)
    d = day.day
    ds = "rules:breadth"
    ids = [p.fact(f"{prefix} {md(d)} 上漲家數", f"{prefix}上漲", "adv_up" if day.market == "TWSE" else "otc_adv_up",
                  group, br.up, f"{br.up:,} 家", unit="家", precision=0, day=d, dataset=ds,
                  aliases=["上漲", "漲"]),
           p.fact(f"{prefix} {md(d)} 下跌家數", f"{prefix}下跌", "adv_down" if day.market == "TWSE" else "otc_adv_down",
                  group, br.down, f"{br.down:,} 家", unit="家", precision=0, day=d, dataset=ds,
                  aliases=["下跌", "跌"])]
    if day.market == "TWSE":
        p.fact(f"{prefix} {md(d)} 平盤家數", f"{prefix}平盤", "adv_flat", group, br.flat, f"{br.flat:,} 家", unit="家",
               precision=0, day=d, dataset=ds, aliases=["平盤"])
        lu = p.fact(f"{prefix} {md(d)} 漲停家數", f"{prefix}漲停", "limit_up", group, br.limit_up,
                    f"{br.limit_up:,} 家", unit="家", precision=0, day=d, dataset=ds, aliases=["漲停"])
        ld = p.fact(f"{prefix} {md(d)} 跌停家數", f"{prefix}跌停", "limit_down", group, br.limit_down,
                    f"{br.limit_down:,} 家", unit="家", precision=0, day=d, dataset=ds, aliases=["跌停"])
        if strip:
            p.number(ids[0], B.number("breadth", "上漲／下跌", f"{br.up:,}／{br.down:,} 家", date_label=md(d)))
            p.number(lu, B.number("limits", "漲停／跌停", f"{br.limit_up:,}／{br.limit_down:,} 家",
                                  date_label=md(d)))
            p.strip.extend(x for x in (ids[1], ld) if x)
    return br


def _sector_facts(p: Pack, secs: list[mc.Sector], day: date, group: str, period: str = "") -> None:
    for s in secs:
        fid = p.fact(f"{s.name}類指數 {period or md(day)} 漲跌幅", s.name, "sector_pct", group, s.pct,
                     B.pct_text(s.pct), unit="%", day=day, dataset=s.dataset, aliases=[f"{s.name}類", f"{s.name}股"])
        conc = None
        text = mc.concentration_text(s)
        if s.top_weight is not None and (s.concentrated or s.name == mc.SEMICONDUCTOR):
            conc = p.fact(f"{s.name}類 最大成分股權重（{s.top_name}）", s.name, "sector_concentration", "structure",
                          round(s.top_weight, 4), f"約 {int((s.top_weight * 100).to_integral_value())}%", unit="%",
                          precision=0, day=day, dataset="rules:market_cap", aliases=[x for x in [s.top_name] if x],
                          estimate=True, note=text or "")
        p.sectors.append({"name": s.name, "fact": fid, "members": s.members,
                          "top": {"symbol": s.top_symbol, "name": s.top_name,
                                  "weight": round(float(s.top_weight), 4) if s.top_weight is not None else None}
                          if s.top_symbol else None,
                          "concentrated": s.concentrated, "text_eligible": s.text_eligible, "rank": s.rank,
                          "concentration_fact": conc, "concentration_text": text})
    eligible = [s.name for s in secs if s.text_eligible]
    if eligible:
        contrib = "、點數貢獻（估算）最大的 3 類與最小的 3 類" if any(s.rank == "contrib" for s in secs) else ""
        p.rules.append(f"類股文字只能談：{'、'.join(eligible)}（漲幅前 3、跌幅前 3{contrib}，排除一檔占一半以上的類股；"
                       "半導體固定談，同一段要帶它的集中度）。其他類股只出現在圖上。")


def _sector_rows(secs: list[mc.Sector]) -> list[dict[str, Any]]:
    return [{"name": s.name, "pct": s.pct, "sub": mc.concentration_text(s)} for s in secs]


def _us_facts(p: Pack, sessions: Iterable[date], group: str, *, since: date | None = None,
              strip: bool = False) -> list[dict[str, Any]]:
    """SPY, DIA, ONEQ, SMH and TSMC's ADR: the move of each US session (or of the week from ``since``)."""
    rows: list[dict[str, Any]] = []
    if not p.us_served or not p.ok(f"{mc.US_SOURCE}/price"):
        return rows
    sessions = list(sessions)
    if not sessions:
        return rows
    for sym, name in US_ROW:
        moves = []
        for s in sessions:
            mv = mc.us_move(p.db, sym, s, p.cutoff, since=since)
            if mv is not None and mv.pct is not None:
                moves.append(mv)
        if since:  # a week: from the close before it to its last stored session
            moves = moves[-1:]
        for mv in moves:
            s = mv.session
            what = f"美股 {md(since)}–{md(s)} 漲跌幅" if since else f"美股 {md(s)} 收盤漲跌幅"
            fid = p.fact(f"{name} {what}", name, "us_pct", group, mv.pct, B.pct_text(mv.pct), unit="%", day=s,
                         dataset=f"{mc.US_SOURCE}/price", aliases=US_ALIASES.get(sym, []))
            p.fact(f"{name} 美股 {md(s)} 收盤", name, "us_close", group, mv.close, f"{B.price_text(mv.close)} 美元",
                   unit="美元", day=s, dataset=f"{mc.US_SOURCE}/price", aliases=US_ALIASES.get(sym, []))
            p.dates["us_sessions"].add(s.isoformat())
            if mv is moves[-1]:
                rows.append({"label": name, "pct": mv.pct, "symbol": sym, "session": s})
                if strip:
                    p.number(fid, B.number(sym.lower(), name, B.pct_text(mv.pct), tone_=B.tone(mv.pct),
                                           date_label=f"美股 {md(s)}" if not since else f"美股 {span(since, s)}"))
    return rows


def _us_holidays(p: Pack, start: date, end: date) -> None:
    from forliosa.timeutil import is_us_trading_day

    d = start
    while d <= end:
        if d.weekday() < 5 and not is_us_trading_day(d):
            p.fact(f"美股 {md_wd(d)} 休市", "美股", "us_holiday", "overnight", None, f"美股 {md_wd(d)} 休市",
                   day=d, dataset="manual-calendar", note="依 NYSE 休市表")
            p.dates["us_sessions"].add(d.isoformat())
        d += timedelta(days=1)


def _calendar(p: Pack, start: date, end: date, title: str, *, top100: Iterable[str] = (),
              include_filings: bool = True, names: dict[str, str] | None = None) -> list[cal.CalEvent]:
    events = cal.events_between(p.db, start, end, cutoff=p.cutoff, policy=p.policy, top100=top100,
                                names=names or {}, include_filings=include_filings)
    events = [e for e in events if p.ok(e.source) or e.source.startswith("rules:")]
    for e in events:
        if e.fold == "other_filings":
            continue  # counted, not listed one by one
        cid = p._id("C")
        p.calendar.append({"id": cid, "date": e.date.isoformat(), "time_taipei": e.time_taipei, "title": e.title,
                           "kind": e.kind, "symbol": e.symbol, "sectors": e.sectors, "source": e.source,
                           "url": e.url, "fold": e.fold, "note": e.note})
        p.dates["next_period" if p.ed.next_period and e.date >= p.ed.next_period[0] else "report"].add(
            e.date.isoformat())
        p.datasets.add(e.source)
    others = sum(1 for e in events if e.fold == "other_filings")
    if others:
        p.fact(f"{span(start, end) if start != end else md(start)} 市值前 100 名以外的重大訊息與注意股", "重大訊息",
               "count", "today", others, f"{others} 則", unit="則", precision=0, day=end,
               dataset="rules:calendar_count")
    labels = {e.source: _label(e.source) if not e.source.startswith("rules:") else "Forliosa 依規則計算"
              for e in events}
    p.blocks["calendar"] = B.calendar_block(events, title=title, labels=labels)
    return events


def _filings(p: Pack, day: date, since_hhmm: str | None, top: set[str], names: dict[str, str]) -> None:
    """Material information of ``day`` (from ``since_hhmm``) of the 100 largest companies, as N rows."""
    for e in p.db.scalars(select(MarketEvent).where(MarketEvent.type == "material_info", MarketEvent.date == day)):
        if e.symbol not in top or not p.ok(f"{e.source}/material_info"):
            continue
        if e.created_at is not None and _aware(e.created_at) > p.cutoff:
            continue
        t = cal._clock((e.data or {}).get("time"))
        if since_hhmm and (t is None or t < since_hhmm):
            continue
        p.filings.append({"id": p._id("N"), "date": day.isoformat(), "time": t, "symbol": e.symbol,
                          "name": names.get(e.symbol), "title": e.title[:200], "dataset": f"{e.source}/material_info"})
        p.datasets.add(f"{e.source}/material_info")


RESEARCH_SOURCES = 4  # W entries per stock at most


def _research(p: Pack, symbols: Iterable[str], session: date) -> None:
    """The shared 「為什麼漲跌」 research of listed stocks: one W per source with that source's own snippets (a W's
    footnote is the page its text came from; snippets never reach a page). A source passes the gathering's checks
    first: an allowed domain, published inside the edition's window, and its snippets without ratings or target
    prices."""
    from forliosa.ai.analyst import date_from_url, datetime_from_page_age
    from forliosa.ai.research import AFTER_CLOSE, INTRADAY
    from forliosa.news.outlets import host_of, on_domain
    from forliosa.reports.calls import REPORT_SEARCH_DOMAINS
    from forliosa.reports.gather import RATING, Window, in_window

    syms = list(dict.fromkeys(symbols))
    if not syms:
        return
    rows = p.db.scalars(select(AiWhyResearch).where(AiWhyResearch.symbol.in_(syms), AiWhyResearch.session == session,
                                                    AiWhyResearch.phase.in_((AFTER_CLOSE, INTRADAY))))
    best: dict[str, AiWhyResearch] = {}
    for r in rows:
        if _aware(r.updated_at) > p.cutoff or not r.sources:
            continue
        if r.symbol not in best or r.phase == AFTER_CLOSE:
            best[r.symbol] = r
    for sym in syms:
        r = best.get(sym)
        if r is None:
            continue
        n = 0
        for s in (r.sources or [])[:8]:
            url = str(s.get("url") or "")
            if not url or not any(on_domain(host_of(url), d) for d in REPORT_SEARCH_DOMAINS):
                continue
            try:
                seen = _aware(datetime.fromisoformat(str(s.get("found_at"))) if s.get("found_at") else r.updated_at)
            except ValueError:
                seen = _aware(r.updated_at)
            pub = datetime_from_page_age(s.get("page_age"), seen) or date_from_url(url)
            if pub is None or not in_window(pub, Window(p.ed.web_from, p.ed.web_to, p.cutoff, set(), seen)):
                continue
            quotes = [str(q) for q in s.get("snippets") or [] if q and not RATING.search(str(q))][:3]
            if not quotes or RATING.search(str(s.get("title") or "")):
                continue
            p.research.append({"id": p._id("W"), "symbol": sym, "session": session.isoformat(),
                               "sources": [{"outlet": s.get("outlet"), "title": s.get("title"), "url": url,
                                            "published": s.get("page_age")}], "quotes": quotes})
            n += 1
            if n >= RESEARCH_SOURCES:
                break


def _aware(dt: datetime) -> datetime:
    from datetime import UTC

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _menu(p: Pack, code: str, available: bool, periods: list[str], sets: list[str] | None = None) -> None:
    p.menu.append({"code": code, "available": available, "periods": periods, "sets": sets or []})


G5_MONTH_POINTS = 10  # fewer sessions than this and G5's title names them instead of 「一個月」


def g5_card(md_: Any, symbols: list[str], title: str, through: date) -> dict[str, Any] | None:
    """G5 through the chat's compare chart (archive closes, the history backfill only for the lines): a month up to
    ``through`` (the edition's data day, never a later close, so a rebuild of a past edition draws what it saw)."""
    if md_ is None or len(symbols) < 2:
        return None
    from forliosa.ai.charts import compare_chart

    infos = [i for i in (md_.instrument(s) for s in symbols[:5]) if i is not None]
    card = compare_chart(md_, infos, "1M", until=through)
    if not isinstance(card, dict):
        return None
    series = [{**s, "name": mc.clean_name(str(s.get("name") or ""))} for s in card.get("series") or []]
    out = clip_chart(dict(card, id="G5", title=title, series=series), through)
    if out is not None:
        days = {str(pt.get("t"))[:10] for s in out["series"] if not s.get("hidden") for pt in s.get("points") or []}
        if len(days) < G5_MONTH_POINTS:  # a short archive: the title says how many sessions (audit §2.5-3)
            out = {**out, "title": out["title"].replace("一個月比較", f"近 {len(days)} 個交易日比較")}
    return out


def _g5(p: Pack, md_: Any, symbols: list[str], title: str) -> dict[str, Any] | None:
    return g5_card(md_, symbols, title, p.through)


def _top5_weight_symbols(day: mc.Day | None) -> list[str]:
    return [q.symbol for q in day.by_mcap()[:5]] if day else []


# -- v2 (2026-11-18): sectors and stocks in more depth -------------------------------------------------------------
# G17 sector points, G15 size and style, G2 v2 (baseline, in-sector breadth, periods), G8 turnover share, G2_otc,
# G16 TPEx institutional by industry, T2_top10 v2 (1 day / 1 week / 1 month with heat), T7, T10 margin, T9 (weekly).
CONTRIB_FACT_NOTE = "每檔前一日市值權重 × 前一日加權指數 × 漲跌幅，依產業別加總"
TOP10_RULE = ("上市普通股，依收盤市值；第一列是加權指數。近 1 週、近 1 月是每天對參考價的漲跌連乘（除權息不算成"
              "下跌），只用官方存檔")


def heat_rule(cols: Iterable[tuple[str, str]]) -> str:
    """「底色只分兩階（1 日：1%、3%；近 1 週：2%、5%；近 1 月：4%、10%）」 for a heat-tinted table's ``cols``
    ((label, period) pairs): the same tint means a different size in each column, so the rule says where each starts."""
    def pc(x: Decimal) -> str:
        return f"{(x * 100).normalize():f}%"

    return "底色只分兩階（" + "；".join(f"{lab}：{pc(B.HEAT_STEPS[per][0])}、{pc(B.HEAT_STEPS[per][1])}"
                                      for lab, per in cols) + "）"
MARGIN_RULE = ("範圍：{markets}，市值前 200 名或 300 億元以上；排除創新板、全額交割（變更交易）、處置股。"
               "依融資張數變化 × 收盤價排序")
MOVERS_TABS = (("T2_gainers", "漲幅"), ("T2_losers", "跌幅"), ("T2_value", "成交值"))
G8_TOP = 8


def _bench(pct: Decimal | None, prefix: str = "加權") -> dict[str, Any] | None:
    return B.bench(pct, f"{prefix} {B.pct_text(pct)}") if pct is not None else None


def _taiex_prev(p: Pack, taiex: mc.IndexPoint | None, day: mc.Day) -> Decimal | None:
    """The TAIEX close the day's contributions are weighted on (the official change's base, else the archive's)."""
    if taiex is not None and taiex.change is not None:
        return taiex.close - taiex.change
    if day.prev_day:
        prev = mc.index_on(p.db, mc.TAIEX, day.prev_day, p.cutoff, p.policy)
        return prev.close if prev else None
    return None


def _moves(day: mc.Day | None) -> bool:
    return day is not None and any(q.pct is not None for q in day.commons())


def _g17(p: Pack, contribs: list[mc.SectorContrib], secs: list[mc.Sector], official: Decimal | None, *, title: str,
         sources: Iterable[str], week: bool = False) -> None:
    """G17: the 5 sectors that pulled the TAIEX down most and the 5 that lifted it most (only those that moved it
    by half a point or more), the others summed; the official change beside the estimate's sum."""
    if not contribs:
        return
    by = {s.name: s for s in secs}
    named = [c for c in contribs if c.name != mc.UNMAPPED]
    drags = sorted((c for c in named if round(c.points) < 0), key=lambda c: (c.points, c.name))[:5]
    lifts = sorted((c for c in named if round(c.points) > 0), key=lambda c: (-c.points, c.name))[:5]
    total = sum((c.points for c in contribs), Decimal(0))
    shown = drags + lifts if total < 0 else lifts + drags
    rows = []
    for c in shown:
        s = by.get(c.name)
        sub = f"權重約 {c.weight * 100:.1f}%"
        if s is not None:
            sub += f"・類股{'週' if week else ''} {B.pct_text(s.pct)}"
        rows.append({"name": c.name, "points": c.points, "sub": sub})
    others = [c for c in contribs if c not in shown]
    rest = {"count": len(others), "points": sum((c.points for c in others), Decimal(0))} if others else None
    p.chart(B.g17_sector_contrib_bars(rows, rest, official, total, len(named), title=title, sources=sources))


def _contrib_facts(p: Pack, contribs: list[mc.SectorContrib], secs: list[mc.Sector], day: date, group: str,
                   period: str) -> None:
    """The 3 sectors that lifted the TAIEX most and the 3 that pulled it down most (estimates, for the sectors
    text): they join the sectors the text may discuss (a sector one stock dominates stays out, 半導體 excepted)."""
    by = {s.name: s for s in secs}

    def ok(c: mc.SectorContrib) -> bool:
        s = by.get(c.name)
        return s is not None and (c.name == mc.SEMICONDUCTOR or not s.concentrated)

    named = [c for c in contribs if c.name != mc.UNMAPPED and round(c.points) != 0 and ok(c)]
    lifts = sorted((c for c in named if c.points > 0), key=lambda c: (-c.points, c.name))[:3]
    drags = sorted((c for c in named if c.points < 0), key=lambda c: (c.points, c.name))[:3]
    for c in [*lifts, *drags]:
        p.fact(f"{c.name}類 {period} 對加權指數點數貢獻（估算）", c.name, "sector_contrib_est", group,
               round(c.points, 1), B.signed_text(c.points, 0, " 點"), unit="點", precision=0, day=day,
               dataset="rules:contribution", aliases=[f"{c.name}類", f"{c.name}股"], estimate=True,
               note=CONTRIB_FACT_NOTE)
        s = by[c.name]
        if not s.text_eligible:
            s.text_eligible, s.rank = True, "contrib"


def _g15(p: Pack, d: date, taiex_pct: Decimal | None) -> None:
    """G15: 臺灣50, 中型100, 小型股300 | 電子工業, 未含電子, 金融保險 | 臺灣高股息, 櫃買指數, on the TAIEX baseline."""
    moves = mc.style_moves(p.db, d, p.cutoff, p.policy)
    rows = [{"group": m.group, "label": m.label, "pct": m.point.pct} for m in moves]
    p.chart(B.g15_style_bars(rows, _bench(taiex_pct), title=f"規模與風格指數漲跌（{md(d)}）",
                             sources=p.labels(sorted({m.point.dataset for m in moves}))))


def _view_rows(view: mc.SectorView, by: dict[str, mc.Sector], inner: dict[str, mc.Breadth] | None) \
        -> list[dict[str, Any]]:
    rows = []
    for name, move in sorted(view.moves.items(), key=lambda kv: (-kv[1], kv[0])):
        parts = []
        br = (inner or {}).get(name)
        if br is not None:
            parts.append(f"漲 {br.up}・跌 {br.down}")
        s = by.get(name)
        if s is not None and (conc := mc.concentration_text(s)):
            parts.append(conc)
        rows.append({"name": name, "pct": move, "sub": "・".join(parts) or None})
    return rows


def _view_notes(view: mc.SectorView, breadth_line: bool) -> list[str]:
    out = []
    if view.bench is not None:
        above = sum(1 for m in view.moves.values() if m > view.bench)
        below = sum(1 for m in view.moves.values() if m < view.bench)
        out.append(f"虛線是加權指數同一期間的漲跌：{above} 類高於加權指數、{below} 類低於。")
    if breadth_line:
        out.append("每列第二行是這一類上市普通股的上漲、下跌家數。")
    return out


def _g2(p: Pack, d: date, secs: list[mc.Sector], inner: dict[str, mc.Breadth] | None, taiex_pct: Decimal | None, *,
        title: str, sources: Iterable[str], reference: dict[str, Any] | None = None,
        first: tuple[str, str, date | None] = ("1d", "1 日", None),
        periods: Iterable[tuple[str, str, date]] | None = None) -> None:
    """G2 v2: the 32 sectors best first with the TAIEX baseline, each one's advancers and decliners on its second
    line, the narrow-screen fold (5 best, 半導體, 5 worst) and the period chips (1 日｜近 1 週｜近 1 月, or 「11/12
    起」 while the archive is short). Each chip carries its own title with the period (「上市類股指數漲跌（11/10 收盤至
    11/17）」): the card swaps it, so a week's moves never sit under a one-day title."""
    if not secs:
        return
    by = {s.name: s for s in secs}
    if periods is None:
        periods = [("1w", "近 1 週", mc.sessions_back(d, 5)), ("1m", "近 1 月", mc.month_base(d))]
    periods = list(periods)
    oldest = min([b for _k, _l, b in periods] + [first[2] or d])
    closes = _taiex_closes(p, d, since=oldest - timedelta(days=10), limit=80)
    taiex_pts = [(day_, c) for day_, (c, _ds) in sorted(closes.items())]
    views = mc.sector_views(p.db, d, p.cutoff, taiex_pts, {s.name: s.pct for s in secs}, taiex_pct,
                            policy=p.policy, periods=periods, first=first)
    if not views:
        return

    def view_title(v: mc.SectorView) -> str:
        return title if v is views[0] or v.base is None else f"上市類股指數漲跌（{md(v.base)} 收盤至 {md(d)}）"

    chips = [B.sector_view(v.key, v.label, _view_rows(v, by, inner if v is views[0] else None), _bench(v.bench),
                           _view_notes(v, bool(inner) and v is views[0]), title=view_title(v)) for v in views]
    # the period chips' dashed lines: the TAIEX closes they were measured on (MI_INDEX, or FMTQIK where it is short)
    bench_ds = {closes[x][1] for v in views[1:] if v.bench is not None and v.base is not None for x in (v.base, d)
                if x in closes} if len(chips) > 1 else set()
    p.datasets |= bench_ds
    sources = [*sources, *p.labels(sorted(bench_ds))]
    main = views[0]
    p.chart(B.g2_sector_bars(_view_rows(main, by, inner), title=title, sources=sources,
                             notes=_view_notes(main, bool(inner)), bench_=_bench(main.bench),
                             views=chips if len(chips) > 1 else None, reference=reference, fold=B.SECTOR_FOLD))


def _breadth_reference(br: mc.Breadth, prefix: str, limits: bool = True) -> dict[str, Any]:
    text = f"上漲 {br.up:,}・下跌 {br.down:,}・平盤 {br.flat:,} 家"
    if limits:
        text += f"；漲停 {br.limit_up:,}・跌停 {br.limit_down:,} 家"
    return {"label": prefix, "display": text}


def _g8(p: Pack, now: dict[str, int], prev: dict[str, int] | None, in_range: list[mc.Quote], *, title: str,
        sources: Iterable[str], week: bool = False, values: dict[str, int] | None = None,
        pcts: dict[str, Decimal | None] | None = None) -> None:
    """G8: the 8 sectors with the largest share of the listed commons' traded value and the rest; the change in
    percentage points against the previous session (week); the largest value in the rankings' scope on the second
    line (「占這一類」 only above half)."""
    rows_all = mc.sector_turnover(now, prev, in_range, values)
    if not rows_all:
        return
    named = [t for t in rows_all if t.name != mc.UNMAPPED]
    top = named[:G8_TOP]
    rows = []
    for t in top:
        sub = None
        if t.top is not None and t.top_value:
            sub = f"成交值最大：{t.top.name} {B.yi_text(t.top_value)}"
            if t.top_share is not None and t.top_share > mc.CONCENTRATION:
                sub += f"，占這一類 {int((t.top_share * 100).to_integral_value())}%"
            move = (pcts or {}).get(t.top.symbol) if pcts is not None else t.top.pct
            if move is not None:
                sub += f"・{'週 ' if week else ''}{B.pct_text(move)}"
        rows.append({"name": t.name, "share": t.share, "change": t.change, "sub": sub})
    others = [t for t in rows_all if t not in top]
    rest = None
    if others:
        ch = [t.change for t in others]
        rest = {"count": len(others), "share": sum((t.share for t in others), Decimal(0)),
                "change": sum((c for c in ch if c is not None), Decimal(0)) if all(c is not None for c in ch) else None}
    total = sum(now.values())
    prev_total = sum(prev.values()) if prev else None
    what = "前一週" if week else "前一日"
    notes = [f"分母是上市普通股的{'全週' if week else ''}成交金額 {B.yi_text(total)}"
             + (f"（{what} {B.yi_text(prev_total)}）" if prev_total else "") + "，不含 ETF 等。"]
    if prev:
        notes.append(f"「較{what}」的單位是百分點。")
    notes.append("成交值最大的一檔只在市值前 200 名或 300 億元以上的範圍裡挑（同排行表）。")
    p.chart(B.g8_turnover_bars(rows, rest, title=title, notes=notes, aside_label=f"較{what}" if prev else None,
                               sources=sources))


def _g2_otc(p: Pack, tpex: mc.Day) -> None:
    """G2_otc (was the table T6): TPEx industries, Forliosa's market-cap weighted moves, as bars."""
    secs = mc.otc_sectors(tpex)
    rows = [{"name": s.name.removesuffix("業") or s.name, "pct": s.pct, "sub": f"{s.members} 家"} for s in secs]
    ref = _breadth_reference(mc.breadth(tpex), "上櫃普通股", limits=False) if _moves(tpex) else None
    p.chart(B.g2_sector_bars(rows, title=f"上櫃類股漲跌（Forliosa 計算，{md(tpex.day)}）",
                             sources=[*p.labels(tpex.datasets), label("rules")], cid="G2_otc", estimate=True,
                             notes=["上櫃普通股依產業別分組，以前一日市值加權；2 家以下的產業不列。不是官方指數。"],
                             reference=ref, fold=B.OTC_FOLD))


def _g16(p: Pack, flows: list[mc.IndustryFlow], total: Decimal | None, *, title: str, sources: Iterable[str]) -> None:
    """G16: the 5 industries TPEx's institutions bought most and the 5 they sold most (estimated NT$)."""
    buys = [f for f in flows if f.amount > 0][:5]
    sells = sorted((f for f in flows if f.amount < 0), key=lambda f: (f.amount, f.code))[:5]
    rows = [{"name": f.name, "amount": f.amount} for f in [*buys, *reversed(sells)]]
    p.chart(B.g16_otc_flow_bars(rows, total, title=title, sources=sources))


def _t7(p: Pack, d: date) -> None:
    """T7: the three investors' TAIEX futures net open interest on ``d`` and its change (ink: lots are not a price
    move, as G7 and G16)."""
    rows7 = []
    for investor in mc.INVESTORS:
        series = mc.futures_oi_series(p.db, d, p.cutoff, investor, limit=2)
        if not series or series[-1][0] != d:
            continue
        net = series[-1][1]
        ch = net - series[-2][1] if len(series) > 1 else None
        rows7.append({"cells": {"who": B.cell(investor),
                                "net": B.cell(f"{'淨多' if net > 0 else '淨空'} {abs(net):,} 口"),
                                "change": B.cell(f"{ch:+,} 口" if ch is not None else "—")}})
    if rows7 and p.ok("taifex-openapi/institutional_futures"):
        p.datasets.add("taifex-openapi/institutional_futures")
        p.table(B.table("T7", f"期貨三大法人：台指期淨未平倉（{md(d)}）",
                        [("who", "法人", "left", False), ("net", "淨未平倉", "right", True),
                         ("change", "較前一日", "right", True)], rows7,
                        sources=p.labels(["taifex-openapi/institutional_futures"])))


def _t10(p: Pack, days: list[mc.Day | None], end: date, *, since: date | None = None, title: str) -> None:
    """T10: the 5 largest margin purchase increases and decreases (lots × close) among the 200 largest listed and
    OTC commons (or NT$30 billion and up); two tabs, no price move."""
    pool = [q for day in days if day is not None for q in day.commons() if q.mcap is not None]
    if not pool:
        return
    pool = [q for q in pool if p.ok(f"{mc.MARGIN_SOURCES[q.market]}/margin")]
    ranked = sorted(pool, key=lambda q: (-q.mcap, q.symbol))  # type: ignore[operator]
    scope = mc.rule_scope(p.db, ranked, end)
    table = mc.margin_changes(p.db, scope.in_range, end, p.cutoff, since=since)
    if not table.markets:
        return
    for m in table.markets:
        p.datasets.add(f"{mc.MARGIN_SOURCES[m]}/margin")
    srcs = p.labels([f"{mc.MARGIN_SOURCES[m]}/margin" for m in table.markets])
    markets = "與".join({"TWSE": "上市", "TPEX": "上櫃"}[m] for m in table.markets)
    ups = sorted((r for r in table.rows if r.change > 0), key=lambda r: (-r.amount, r.quote.symbol))[:5]
    downs = sorted((r for r in table.rows if r.change < 0), key=lambda r: (r.amount, r.quote.symbol))[:5]
    change_label = "週增減（張）" if since else "較前一日（張）"
    cols = [("stock", "股票", "left", False), ("balance", "融資餘額（張）", "right", True),
            ("change", change_label, "right", True)]

    def rows(items: list[mc.MarginChange]) -> list[dict[str, Any]]:
        return [{"cells": {"stock": B.cell(B.stock_label(r.quote.name, r.quote.code)),
                           "balance": B.cell(f"{r.balance:,}"), "change": B.cell(B.signed_text(r.change, 0))},
                 "href": B.STOCK_HREF.format(symbol=r.quote.symbol)} for r in items]

    rule = MARGIN_RULE.format(markets=markets)
    short = [f"{'上市' if m == 'TWSE' else '上櫃'}到 {md(table.end[m])}" for m in table.markets if table.end[m] != end]
    if short:  # a week whose TWSE Friday file was not out yet
        rule += "；" + "、".join(short) + "（證交所的融資檔下一個交易日清晨才公布）"
    week = "週" if since else ""
    p.table(B.table("T10_up", f"融資{week}增加前 5（{title}）", cols, rows(ups), rule=rule,
                    empty_text="範圍內沒有融資增加的股票。", sources=srcs, tab_group="margin", tab_label="增加"))
    p.table(B.table("T10_down", f"融資{week}減少前 5（{title}）", cols, rows(downs), rule=rule,
                    empty_text="範圍內沒有融資減少的股票。", sources=srcs, tab_group="margin", tab_label="減少"))


def _taiex_moves(p: Pack, end: date, bases: dict[str, date]) -> tuple[dict[str, Decimal | None], set[str]]:
    """The TAIEX from each base session's close to ``end`` (MI_INDEX, FMTQIK where the index archive is short), and
    the datasets of the closes those moves used (the table's sources)."""
    closes = _taiex_closes(p, end, since=min(bases.values()) - timedelta(days=10), limit=80)
    ip = [mc.IndexPoint(mc.TAIEX, d, c, None, None, ds) for d, (c, ds) in sorted(closes.items())]
    moves = {k: mc.index_move(ip, end, b) for k, b in bases.items()}
    used = {closes[d][1] for k, b in bases.items() if moves[k] is not None for d in (b, end)}
    return moves, used


def _archive_note(p: Pack, end: date, short: set[str], labels_: dict[str, str],
                  bases: dict[str, date] | None = None) -> str | None:
    """「個股的近 1 週 11/19 起才有」: a short column says from when the listed closes' archive is long enough; a
    session missing from the archive inside a short column's period says so too (those cells are 「—」, never a move
    that skipped the day)."""
    if not short:
        return None
    days = mc.session_dates(p.db, "TWSE", end, p.cutoff, p.policy, limit=60)
    if not days:
        return None
    week_from, month_from = mc.archive_ready(days[0])
    parts = []
    if "1w" in short and week_from > end:
        parts.append(f"{labels_['1w']} {md(week_from)} 起才有")
    if "1m" in short and month_from > end:
        parts.append(f"{labels_['1m']} {md(month_from)} 起才有")
    out = [f"個股的{'、'.join(parts)}（存檔從 {md(days[0])} 開始）。"] if parts else []
    spans = [b for k, b in (bases or {}).items() if k in short]
    if spans:
        archived = set(days)
        gaps = [d for d in tw_trading_days(max(min(spans), days[0]) + timedelta(days=1), end) if d not in archived]
        if gaps:
            shown = "、".join(md(d) for d in gaps[:3]) + (" 等" if len(gaps) > 3 else "")
            out.append(f"存檔缺 {shown} 的收盤，跨過這{'一天' if len(gaps) == 1 else '幾天'}的格子不算（「—」）。")
    return "".join(out) or None


def _t2_top10_v2(p: Pack, top10: list[mc.Quote], end: date, taiex: mc.IndexPoint | None, *, title: str,
                 sources: list[str], week_base: date | None = None) -> None:
    """T2_top10 v2: the TAIEX, then the 10 largest listed commons, over 1 day, about a week and about a month
    (a week's edition: the week and about a month), each move chained from the official reference prices, heat-tinted
    cells; 「—」 where the archive is short. No contribution column (G3 has it)."""
    if not top10:
        return
    if week_base is None:
        bases = {"1w": mc.sessions_back(end, 5), "1m": mc.month_base(end)}
        cols = [("d1", "1 日", "1d"), ("w1", "近 1 週", "1w"), ("m1", "近 1 月", "1m")]
    else:
        bases = {"1w": week_base, "1m": mc.month_base(end)}
        cols = [("w1", "週漲跌", "1w"), ("m1", "近 1 月", "1m")]
    chained = mc.chained_returns(p.db, [q.symbol for q in top10], end, p.cutoff, bases, p.policy)
    tx, tx_ds = _taiex_moves(p, end, bases)
    taiex_ds = {*tx_ds, *([taiex.dataset] if taiex is not None and taiex.dataset else [])}
    p.datasets |= taiex_ds
    rows: list[dict[str, Any]] = []
    if taiex is not None:
        cells = {"stock": B.cell("加權指數", sub=B.number_text(taiex.close))}
        for key, _lab, period in cols:
            move = taiex.pct if period == "1d" else tx.get(period)
            cells[key] = B.move_cell(move, period)
        rows.append({"cells": cells, "href": None})
    short: set[str] = set()
    for q in top10:
        cells = {"stock": B.cell(B.stock_label(q.name, q.code), sub=B.price_text(q.close))}
        for key, _lab, period in cols:
            move = q.pct if period == "1d" else chained.get(q.symbol, {}).get(period)
            if move is None and period != "1d":
                short.add(period)
            cells[key] = B.move_cell(move, period)
        rows.append({"cells": cells, "href": B.STOCK_HREF.format(symbol=q.symbol)})
    note = _archive_note(p, end, short, {"1w": "近 1 週" if week_base is None else "週漲跌", "1m": "近 1 月"}, bases)
    rule = TOP10_RULE if week_base is None else TOP10_RULE.replace("近 1 週、", "")
    p.table(B.table("T2_top10", title, [("stock", "股票", "left", False),
                                        *((k, lab, "right", True) for k, lab, _per in cols)], rows,
                    rule=f"{rule}；{heat_rule((lab, per) for _k, lab, per in cols)}",
                    note=note, sources=[*sources, *p.labels(sorted(taiex_ds)), label("rules")]))


def _sector_blocks(p: Pack, d: date, twse: mc.Day | None, taiex: mc.IndexPoint | None, secs: list[mc.Sector],
                   contribs: list[mc.SectorContrib], *, reference: dict[str, Any] | None = None) -> None:
    """The listed session's sector charts (close: the sectors section; premarket: 「昨日台股全貌」): G17, G15, G2 v2,
    G8 — each only from rows usable at the cut-off."""
    sector_ds = sorted({s.dataset for s in secs})
    if contribs and twse is not None:
        _g17(p, contribs, secs, taiex.change if taiex else None,
             title=f"各類股對加權指數的點數貢獻（估算，{md(d)}）",
             sources=p.labels([*twse.datasets, *sector_ds, "rules:contribution"]))
    _g15(p, d, taiex.pct if taiex else None)
    inner = mc.sector_breadth(twse) if twse is not None and _moves(twse) else None
    _g2(p, d, secs, inner, taiex.pct if taiex else None, title=f"上市類股指數漲跌（{md(d)}）",
        sources=p.labels([*sector_ds, *([taiex.dataset] if taiex is not None and taiex.pct is not None else []),
                          *(twse.datasets if inner and twse else [])]), reference=reference)
    if twse is not None:
        before = mc.load_day(p.db, "TWSE", twse.prev_day, p.cutoff, p.policy) if twse.prev_day else None
        prev = mc.sector_values(before.quotes.values()) if before is not None else None
        _g8(p, mc.sector_values(twse.quotes.values()), prev or None,
            mc.rule_scope(p.db, twse.by_mcap(), d).in_range, title=f"上市類股成交金額比重（{md(d)}）",
            sources=p.labels([*twse.datasets, "rules:turnover_sum"]))


def _fixed(p: Pack, codes: Iterable[str]) -> list[str]:
    """The fixed charts the writer is told about: those the page really has."""
    return [c for c in codes if c in p.blocks["charts"]]


# -- 盤後重點 ---------------------------------------------------------------------------------------------------
def _close(p: Pack, md_: Any) -> None:
    d = p.ed.edition_date
    twse = mc.load_day(p.db, "TWSE", d, p.cutoff, p.policy)
    idx = _index_facts(p, d, "today", strip=True)
    taiex = idx.get("taiex")
    if twse is None:
        p.miss("twse_close", f"上市 {md(d)} 收盤還沒有進來。")
        p.notes.append("twse_close_missing")
    else:
        p.datasets |= twse.datasets
    if taiex is None:
        p.notes.append("official_index_missing")
        p.miss("official_index", "官方加權指數尚未取得。")
        if twse is not None:
            now_cap, prev_cap = mc.total_mcap(twse)
            if prev_cap:
                chg = (now_cap - prev_cap) / prev_cap
                fid = p.fact(f"上市市值變化 {md(d)}（Forliosa 估算）", "上市市值", "mcap_change_est", "today", chg,
                             B.pct_text(chg), unit="%", day=d, dataset="rules:market_cap", estimate=True,
                             aliases=["上市", "市值"])
                p.number(fid, B.number("mcap_change", "上市市值變化", B.pct_text(chg), tone_=B.tone(chg),
                                       date_label=md(d), estimate=True))
    if twse is not None:
        _breadth_facts(p, twse, "today", strip=True)
        # turnover: the official FMTQIK when it existed at the cut-off (the 06:40 tables), else our own sum
        official = p.db.get(MarketTurnoverDaily, (d, "TWSE"))
        if official is not None and official.trade_value and usable("twse-openapi/turnover", d, p.cutoff):
            fid = p.fact(f"上市成交金額 {md(d)}", "上市成交金額", "turnover", "today", official.trade_value,
                         B.yi_text(official.trade_value), unit="億元", precision=0, day=d,
                         dataset="twse-openapi/turnover", aliases=["成交金額", "成交值", "量能"])
            p.number(fid, B.number("turnover", "上市成交金額", B.yi_text(official.trade_value), date_label=md(d)))
        elif (total := mc.turnover_sum(twse)) is not None:
            fid = p.fact(f"上市成交金額（Forliosa 加總，估算）{md(d)}", "上市成交金額", "turnover_est", "today", total,
                         B.yi_text(total), unit="億元", precision=0, day=d, dataset="rules:turnover_sum",
                         estimate=True, aliases=["成交金額", "成交值", "量能"],
                         note="個股成交金額加總；證交所官方數字隔天清晨公布")
            p.number(fid, B.number("turnover", "上市成交金額", B.yi_text(total), date_label=md(d), estimate=True,
                                   note="隔天清晨換成證交所官方數字"))
        now_cap, _ = mc.total_mcap(twse)
        if now_cap:
            p.fact(f"上市普通股總市值 {md(d)}（Forliosa 估算）", "上市總市值", "mcap_total", "structure", now_cap,
                   B.zhao_text(now_cap), unit="兆元", day=d, dataset="rules:market_cap", estimate=True)
    # sectors: G17 (its 3 best and 3 worst also join the text's sectors), G15, G2 v2, G8; the strip has the breadth
    secs = mc.sectors(p.db, d, p.cutoff, twse, p.policy)
    contrib: dict[str, Decimal] = {}
    contribs: list[mc.SectorContrib] = []
    if twse is not None:
        taiex_prev = _taiex_prev(p, taiex, twse)
        contrib = mc.contributions(twse, taiex_prev)
        contribs = mc.sector_contributions(twse, taiex_prev)
    _contrib_facts(p, contribs, secs, d, "today", md(d))
    _sector_facts(p, secs, d, "today")
    _sector_blocks(p, d, twse, taiex, secs, contribs)
    # stocks
    top100: list[str] = []
    names: dict[str, str] = {}
    if twse is not None:
        lists = mc.rule_lists(p.db, twse)
        for q in lists.top10:
            p.stock(q, "市值前 10", contrib=contrib.get(q.symbol), with_mcap=True, with_value=True)
        for q in lists.gainers:
            p.stock(q, "漲幅前 5" if lists.limit_up_many is None else "漲停中市值最大 5 檔", with_value=True)
        for q in lists.losers:
            p.stock(q, "跌幅前 5" if lists.limit_down_many is None else "跌停中市值最大 5 檔", with_value=True)
        for q in lists.by_value:
            p.stock(q, "成交值前 10", with_value=True)
        ref = twse.quotes.get(mc.REFERENCE_SYMBOL)
        if ref is not None and ref.pct is not None:
            p.stock(ref, "對照基準")
        tpex_latest = _latest_day(p, "TPEX", d)
        top100 = mc.top_by_mcap([twse, tpex_latest])
        names = {q.symbol: q.name for day in (twse, tpex_latest) if day for q in day.quotes.values()}
        _event_stocks(p, [twse, tpex_latest], d, d, set(top100))
        p.rules.append(RULE_STOCKS)
        _close_tables(p, twse, lists, d, taiex)
        # G3 contributions
        rows = [{"label": q.name, "symbol": q.symbol, "points": contrib[q.symbol]} for q in lists.top10
                if q.symbol in contrib]
        rest = sum(contrib.values(), Decimal(0)) - sum((r["points"] for r in rows), Decimal(0)) if contrib else None
        p.chart(B.g3_contribution_bars(rows, rest, taiex.change if taiex else None,
                                       title=f"市值前 10 大對加權指數的點數貢獻（估算，{md(d)}）",
                                       sources=p.labels([*twse.datasets, "rules:contribution"])))
        _research(p, list(p.stocks), d)
    # G1
    if taiex is not None:
        pts, ds = _taiex_series(p, d, limit=60)
        p.chart(B.g1_index_line(pts, sources=p.labels(ds), title=f"加權指數收盤（至 {md(d)}）"))
    else:
        p.blocks["notes"]["G1"] = "官方加權指數尚未取得"
    g5 = _g5(p, md_, _top5_weight_symbols(twse), f"權值前 5 檔一個月比較（至 {md(d)}）")
    p.chart(g5)
    # the chart of the day: G5 (G4's advancers and decliners are the number strip's; v2 took it out)
    _menu(p, "G5", g5 is not None, ["day"], ["top5_weight", "gainers", "losers"] if g5 is not None else [])
    p.fixed = _fixed(p, ("G1", "G17", "G15", "G2", "G8", "G3"))
    _filings(p, d, "14:00", set(top100), names)
    # tonight and the next session's scheduled events
    nxt = next_tw_trading_day(d + timedelta(days=1))
    _calendar(p, d, nxt, f"盤後與下個交易日行事曆（{md(d)}–{md(nxt)}）", top100=top100, names=names)
    _close_evening(p, d)


def _close_evening(p: Pack, d: date) -> None:
    """The blocks the 23:45 and 06:40 runs add (contract §13.3): T5 上櫃排行, G2_otc 上櫃類股 (Forliosa's own; was
    the table T6), T7 期貨三大法人, T8 上櫃三大法人 and G16 by industry (estimated amounts). Each only once its data
    existed at the cut-off (TPEx closes about 23:30, TAIFEX about 21:45), so the 15:40 pack has none of them."""
    tpex = mc.load_day(p.db, "TPEX", d, p.cutoff, p.policy)
    if tpex is not None and tpex.day == d and _moves(tpex):
        p.datasets |= tpex.datasets
        srcs = p.labels(tpex.datasets)
        lists = mc.rule_lists(p.db, tpex)
        p.table(B.table("T5_top10", f"上櫃市值前 10（{md(d)}）",
                        [*B.STOCK_COLUMNS, ("mcap", "市值", "right", True)],
                        [B.stock_row(q, {"mcap": B.cell(B.zhao_text(q.mcap) if q.mcap else "—")}) for q in lists.top10],
                        rule="上櫃普通股，依收盤市值（收盤 × 已發行股數）", sources=[*srcs, label("rules")]))
        p.table(B.table("T5_gainers", f"上櫃漲幅前 5（{md(d)}）" if lists.limit_up_many is None
                        else f"上櫃{_many_title(lists.limit_up_many, '漲停')}（{md(d)}）", B.STOCK_COLUMNS,
                        [B.stock_row(q) for q in lists.gainers], rule=lists.scope_rule,
                        empty_text="範圍內沒有上漲的股票。", sources=srcs, tab_group="otc_movers", tab_label="漲幅"))
        p.table(B.table("T5_losers", f"上櫃跌幅前 5（{md(d)}）" if lists.limit_down_many is None
                        else f"上櫃{_many_title(lists.limit_down_many, '跌停')}（{md(d)}）", B.STOCK_COLUMNS,
                        [B.stock_row(q) for q in lists.losers], rule=lists.scope_rule,
                        empty_text="範圍內沒有下跌的股票。", sources=srcs, tab_group="otc_movers", tab_label="跌幅"))
        _g2_otc(p, tpex)
    if tpex is not None and tpex.day == d:
        inst = mc.otc_institutional(p.db, tpex, p.cutoff)
        if inst is not None:
            sums, per = inst
            ds = p.labels(["tpex-openapi/institutional", *tpex.datasets])
            p.datasets |= tpex.datasets
            p.datasets.add("tpex-openapi/institutional")

            def amount(v: Decimal) -> dict[str, Any]:  # ink: an institutional flow, not a price move (as G16)
                return B.cell(f"{'買超' if v >= 0 else '賣超'} {B.yi_text(abs(v), 1)}")

            p.table(B.table("T8", f"上櫃三大法人買賣超（估算金額，{md(d)}）",
                            [("who", "法人", "left", False), ("amount", "估算金額", "right", True)],
                            [{"cells": {"who": B.cell(name), "amount": amount(sums[k])}}
                             for k, name in (("foreign", "外資"), ("trust", "投信"), ("dealer", "自營商"),
                                             ("total", "合計"))],
                            rule="估算金額＝股數 × 收盤價；不是官方數字", sources=ds))
            buys = sorted((x for x in per if x.amount > 0), key=lambda x: -x.amount)[:10]
            sells = sorted((x for x in per if x.amount < 0), key=lambda x: x.amount)[:10]
            for tid, title, rows in (("T8_buy", "上櫃三大法人買超前 10（估算金額）", buys),
                                     ("T8_sell", "上櫃三大法人賣超前 10（估算金額）", sells)):
                p.table(B.table(tid, f"{title}（{md(d)}）",
                                [("stock", "股票", "left", False), ("amount", "估算金額", "right", True)],
                                [{"cells": {"stock": B.cell(B.stock_label(x.name, x.symbol.split('.')[0])),
                                            "amount": amount(x.amount)},
                                  "href": B.STOCK_HREF.format(symbol=x.symbol)} for x in rows],
                                rule="估算金額＝合計買賣超股數 × 收盤價", empty_text="沒有資料。", sources=ds))
            flows = mc.otc_flows_by_industry(per, {q.symbol: q.industry_code for q in tpex.quotes.values()})
            _g16(p, flows, sums["total"], title=f"上櫃三大法人買賣超，依產業別（估算，{md(d)}）",
                 sources=[*ds, label("rules")])
    _t7(p, d)


def _taiex_series(p: Pack, upto: date, since: date | None = None,
                  limit: int = 60) -> tuple[list[tuple[date, Decimal]], set[str]]:
    """The TAIEX closes for G1: MI_INDEX rows, and FMTQIK's TAIEX column for the days the index archive lacks (the
    month FMTQIK carries; usable from its next-morning batch)."""
    pts = _taiex_closes(p, upto, since, limit)
    days = sorted(pts)
    return [(d, pts[d][0]) for d in days], {pts[d][1] for d in days}


def _taiex_closes(p: Pack, upto: date, since: date | None = None,
                  limit: int = 60) -> dict[date, tuple[Decimal, str]]:
    """:func:`_taiex_series` with each close's dataset (day -> (close, dataset)), the newest ``limit`` days."""
    pts = {x.day: (x.close, x.dataset) for x in mc.index_points(p.db, mc.TAIEX, p.cutoff, upto=upto, since=since,
                                                                 policy=p.policy, limit=limit)}
    stmt = select(MarketTurnoverDaily).where(MarketTurnoverDaily.market == "TWSE", MarketTurnoverDaily.date <= upto)
    if since:
        stmt = stmt.where(MarketTurnoverDaily.date >= since)
    if p.ok("twse-openapi/turnover"):
        for r in p.db.scalars(stmt):
            if r.taiex and r.date not in pts and usable("twse-openapi/turnover", r.date, p.cutoff):
                pts[r.date] = (r.taiex, "twse-openapi/turnover")
    return {d: pts[d] for d in sorted(pts)[-limit:]}


def _latest_day(p: Pack, market: str, upto: date) -> mc.Day | None:
    for day in reversed(mc.session_dates(p.db, market, upto, p.cutoff, p.policy, limit=5)):
        loaded = mc.load_day(p.db, market, day, p.cutoff, p.policy)
        if loaded is not None:
            return loaded
    return None


def _event_stocks(p: Pack, days: list[mc.Day | None], start: date, end: date, top: set[str],
                  group: str = "today") -> None:
    """Companies with an investor conference, an ex-dividend date or material information from ``start`` to ``end``:
    the 100 largest by market cap (listed and OTC) are listed; the rest are counted in the calendar."""
    quotes = {q.symbol: q for d in days if d for q in d.quotes.values()}
    from forliosa.services.announcements import classify

    hit: set[str] = set()
    for e in p.db.scalars(select(MarketEvent).where(
            MarketEvent.type.in_(("ex_dividend", "material_info")), MarketEvent.symbol.in_(top),
            MarketEvent.date >= start - timedelta(days=60), MarketEvent.date <= end)):
        if e.created_at is not None and _aware(e.created_at) > p.cutoff:
            continue
        if e.type == "ex_dividend" and start <= e.date <= end:
            hit.add(e.symbol)
        elif e.type == "material_info":
            rel = classify(e.title, e.detail or "", e.data, e.date)
            if (rel is not None and rel.kind == "investor_conference" and start <= rel.date <= end) or \
                    (start <= e.date <= end):
                hit.add(e.symbol)
    for sym in sorted(hit, key=lambda s: -(quotes[s].mcap or 0) if s in quotes else 0):
        q = quotes.get(sym)
        if q is not None and q.common:
            p.stock(q, "事件股（市值前 100）", group)


def _many_title(n: int, what: str) -> str:
    """The movers table when ten or more stocks in its scope hit the limit: the count is the scope's (市值前 200 名或
    300 億元以上), not the market's — the number strip counts every listed common."""
    return f"範圍內{what} {n} 家，其中市值最大的 5 檔"


def _close_tables(p: Pack, day: mc.Day, lists: mc.Lists, d: date, taiex: mc.IndexPoint | None) -> None:
    """T2_top10 v2 (the direction over 1 day, a week, a month) and the movers as three tabs (漲幅｜跌幅｜成交值)."""
    srcs = p.labels([*day.datasets])
    _t2_top10_v2(p, lists.top10, d, taiex, title=f"市值前 10 的大方向（{md(d)}）", sources=srcs)
    up_title = f"漲幅前 5（{md(d)}）" if lists.limit_up_many is None else \
        f"{_many_title(lists.limit_up_many, '漲停')}（{md(d)}）"
    down_title = f"跌幅前 5（{md(d)}）" if lists.limit_down_many is None else \
        f"{_many_title(lists.limit_down_many, '跌停')}（{md(d)}）"
    if lists.limit_up_many is not None or lists.limit_down_many is not None:
        # the strip counts every listed common; the lists only their scope: both say which one they count
        for n in p.blocks["numbers"]:
            if n["key"] == "limits":
                n["note"] = LIMITS_NOTE
    tabs = dict(MOVERS_TABS)
    p.table(B.table("T2_gainers", up_title, B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.gainers],
                    rule=lists.scope_rule, empty_text="範圍內沒有上漲的股票。", sources=srcs,
                    tab_group="movers", tab_label=tabs["T2_gainers"]))
    p.table(B.table("T2_losers", down_title, B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.losers],
                    rule=lists.scope_rule, empty_text="範圍內沒有下跌的股票。", sources=srcs,
                    tab_group="movers", tab_label=tabs["T2_losers"]))
    col_label = "成交金額" if lists.value_column == "value" else "成交量（股）"
    value_rows = [B.stock_row(q, {"value": B.cell(B.yi_text(q.value, 1) if lists.value_column == "value" and q.value
                                                  else f"{q.volume or 0:,}")}) for q in lists.by_value]
    p.table(B.table("T2_value", f"{'成交值' if lists.value_column == 'value' else '成交量'}前 10（{md(d)}）",
                    [*B.STOCK_COLUMNS, ("value", col_label, "right", True)], value_rows,
                    rule=lists.scope_rule + ("" if lists.value_column == "value"
                                             else "；這天的資料沒有成交金額，改依成交量"),
                    sources=srcs, tab_group="movers",
                    tab_label=tabs["T2_value"] if lists.value_column == "value" else "成交量"))


# -- 盤前重點 ---------------------------------------------------------------------------------------------------
def _premarket(p: Pack, md_: Any) -> None:
    d = p.ed.edition_date
    prev = p.ed.prev_session
    assert prev is not None
    p.dates["prev_session"].add(prev.isoformat())
    # overnight: US ETFs and ADR for every US session since the previous Taiwan session
    rows = _us_facts(p, p.ed.us_sessions, "overnight", strip=True)
    _us_holidays(p, prev, d - timedelta(days=1))
    if p.us_served:
        for s_ in p.ed.us_sessions:
            if s_.isoformat() not in p.dates["us_sessions"]:
                p.miss(f"us_session_{s_.isoformat()}", f"美股 {md(s_)} 收盤還沒有進來。")
    if not p.us_served:
        p.miss("us_prices", "美股收盤價沒有開（US_PRICE_SOURCE），只列行事曆與國內資料。")
    last_us = p.ed.us_sessions[-1] if p.ed.us_sessions else None
    p.chart(B.g6_us_bars(rows, title=f"美股 ETF 與台積電 ADR（美股 {md(last_us)} 收盤）" if last_us else "美股 ETF",
                         sources=p.labels([f"{mc.US_SOURCE}/price"])))
    # USD/TWD (the central bank, previous session)
    fx = mc.usd_twd(p.db, prev, p.cutoff)
    if fx and fx[-1][0] == prev:
        rate = fx[-1][1]
        fid = p.fact(f"美元兌新台幣 {md(prev)} 收盤（央行）", "美元兌新台幣", "fx_close", "evening", rate,
                     f"{rate:.3f}", unit="元", precision=3, day=prev, dataset="cbc-opendata/fx",
                     aliases=["新台幣", "台幣", "匯率"])
        chg = rate - fx[-2][1] if len(fx) > 1 else None
        if chg is not None:
            p.fact(f"美元兌新台幣 {md(prev)} 較前一日", "美元兌新台幣", "fx_change", "evening", chg,
                   f"{'▲' if chg > 0 else '▼' if chg < 0 else ''}{abs(chg):.3f}", unit="元", precision=3, day=prev,
                   dataset="cbc-opendata/fx", aliases=["新台幣", "台幣", "匯率"])
        p.number(fid, B.number("usdtwd", "美元兌新台幣", f"{rate:.3f}",
                               change=f"{chg:+.3f}" if chg is not None else None, date_label=md(prev)))
    # futures and options positions of the previous session
    oi = mc.futures_oi_series(p.db, prev, p.cutoff)
    if oi and oi[-1][0] == prev:
        net = oi[-1][1]
        fid = p.fact(f"外資台指期淨未平倉 {md(prev)}", "外資台指期", "futures_oi_net", "evening", net,
                     f"{'淨多' if net > 0 else '淨空'} {abs(net):,} 口", unit="口", precision=0, day=prev,
                     dataset="taifex-openapi/institutional_futures", aliases=["外資", "台指期", "期貨"])
        change = net - oi[-2][1] if len(oi) > 1 else None
        if change is not None:
            p.fact(f"外資台指期淨未平倉 {md(prev)} 較前一日", "外資台指期", "futures_oi_change", "evening", change,
                   f"{'▲' if change > 0 else '▼' if change < 0 else ''}{abs(change):,} 口", unit="口", precision=0,
                   day=prev, dataset="taifex-openapi/institutional_futures", aliases=["外資", "台指期", "期貨"])
        p.number(fid, B.number("tx_oi", "外資台指期淨未平倉", f"{'淨多' if net > 0 else '淨空'} {abs(net):,} 口",
                               change=f"{change:+,} 口" if change is not None else None, date_label=md(prev)))
    p.chart(B.g7_futures_columns(oi, title=f"外資台指期淨未平倉（至 {md(prev)}）",
                                 sources=p.labels(["taifex-openapi/institutional_futures"])))
    _t7(p, prev)
    pc = mc.put_call(p.db, prev, p.cutoff)
    if pc is not None and pc.trade_date == prev and pc.oi_ratio is not None:
        fid = p.fact(f"台指選擇權 P/C 未平倉比 {md(prev)}", "P/C 比", "pc_ratio_oi", "evening", pc.oi_ratio,
                     f"{pc.oi_ratio * 100:.2f}%", unit="%", day=prev, dataset="taifex-openapi/put_call_ratio",
                     aliases=["P/C", "賣買權"])
        p.number(fid, B.number("pc", "P/C 未平倉比", f"{pc.oi_ratio * 100:.2f}%", date_label=md(prev)))
    # the previous session's TPEx data (published the evening before). The TPEx index closes at 14:30 and was in the
    # previous close report: a previous-session number (never the headline), not one of the evening's
    tpex = mc.load_day(p.db, "TPEX", prev, p.cutoff, p.policy)
    o = mc.index_on(p.db, TPEX_INDEX, prev, p.cutoff, p.policy)
    if o is not None:
        p.fact(f"櫃買指數 {md(prev)} 收盤", "櫃買指數", "otc_close", "prev_session", o.close, B.number_text(o.close),
               unit="點", day=prev, dataset=o.dataset, aliases=OTC_ALIASES)
        if o.pct is not None:
            p.fact(f"櫃買指數 {md(prev)} 漲跌幅", "櫃買指數", "otc_pct", "prev_session", o.pct, B.pct_text(o.pct),
                   unit="%", day=prev, dataset=o.dataset, aliases=OTC_ALIASES)
    if tpex is not None:
        p.datasets |= tpex.datasets
        _breadth_facts(p, tpex, "evening", prefix="上櫃普通股")
        inst = mc.otc_institutional(p.db, tpex, p.cutoff)
        if inst is not None:
            sums, per = inst
            p.datasets.add("tpex-openapi/institutional")
            for key, who, metric in (("total", "上櫃三大法人", "otc_inst_total"),
                                     ("foreign", "上櫃外資", "otc_inst_foreign"),
                                     ("trust", "上櫃投信", "otc_inst_trust"),
                                     ("dealer", "上櫃自營商", "otc_inst_dealer")):
                v = sums[key]
                p.fact(f"{who}買賣超估算金額 {md(prev)}（股數 × 收盤價）", who, metric, "evening", v,
                       f"{'買超' if v >= 0 else '賣超'} {B.yi_text(abs(v), 1)}", unit="億元", precision=1, day=prev,
                       dataset="tpex-openapi/institutional", estimate=True, aliases=[who.removeprefix("上櫃")])
            flows = mc.otc_flows_by_industry(per, {q.symbol: q.industry_code for q in tpex.quotes.values()})
            _g16(p, flows, sums["total"], title=f"上櫃三大法人買賣超，依產業別（估算，{md(prev)}）",
                 sources=[*p.labels(["tpex-openapi/institutional", *tpex.datasets]), label("rules")])
        if _moves(tpex):
            _g2_otc(p, tpex)
    # 昨日台股全貌 (data only: the AI text never retells the previous session; validator §10.2 item 16)
    idx_prev = _index_facts(p, prev, "prev_session", with_tr=False, with_otc=False)
    taiex_prev = idx_prev.get("taiex")
    twse_prev = mc.load_day(p.db, "TWSE", prev, p.cutoff, p.policy)
    if twse_prev is not None:
        p.datasets |= twse_prev.datasets
    secs = mc.sectors(p.db, prev, p.cutoff, twse_prev, p.policy)
    contribs = mc.sector_contributions(twse_prev, _taiex_prev(p, taiex_prev, twse_prev)) \
        if twse_prev is not None else []
    _contrib_facts(p, contribs, secs, prev, "prev_session", md(prev))
    _sector_facts(p, [s for s in secs if s.text_eligible], prev, "prev_session")
    ref = _breadth_reference(mc.breadth(twse_prev), "上市普通股") if _moves(twse_prev) else None
    _sector_blocks(p, prev, twse_prev, taiex_prev, secs, contribs, reference=ref)
    # 昨日籌碼: the margin's largest changes (TWSE's file of the previous session is out by 05:45, TPEx's by 23:40)
    _t10(p, [twse_prev, tpex], prev, title=md(prev))
    g5 = _g5(p, md_, _top5_weight_symbols(twse_prev), f"權值前 5 檔一個月比較（至 {md(prev)}）")
    p.chart(g5)
    # the chart of the day: G5 only (G2 is fixed now; G4's breadth is G2's reference line)
    _menu(p, "G5", g5 is not None, ["day"], ["top5_weight"] if g5 is not None else [])
    p.fixed = _fixed(p, ("G6", "G17", "G15", "G2", "G2_otc", "G8", "G7", "G16"))
    # today's calendar (until the next session), the filings since the previous session's close
    top100 = mc.top_by_mcap([twse_prev, tpex])
    names = {q.symbol: q.name for day in (twse_prev, tpex) if day for q in day.quotes.values()}
    nxt = next_tw_trading_day(d + timedelta(days=1))
    _calendar(p, d, nxt - timedelta(days=1), f"今日行事曆（{md_wd(d)}）", top100=top100, names=names)
    _filings(p, prev, "14:00", set(top100), names)
    _filings(p, d, None, set(top100), names)
    p.rules.append(RULE_STOCKS)
    p.rules.append(RULE_WATCH)
    if not p.calendar:  # a thin day: nothing scheduled, so nothing may be made up to fill the list
        p.rules.append(RULE_WATCH_EMPTY)
    # stocks the edition may name: today's events among the 100 largest (by the previous session's market caps)
    _event_stocks(p, [twse_prev, tpex], d, nxt - timedelta(days=1), set(top100), group="prev_session")
    # the previous close edition's title and highlights (not to be repeated)
    rep = p.db.scalar(select(MarketReport).where(MarketReport.kind == "close", MarketReport.edition_date == prev))
    if rep is not None and rep.current_version_id:
        v = p.db.get(MarketReportVersion, rep.current_version_id)
        payload = (v.payload or {}) if v else {}
        hl = [" ".join(s.get("text", "") for s in (h.get("sentences") or [])) for h in payload.get("highlights") or []]
        if payload.get("title") or hl:
            p.already.append({"kind": "close", "edition_date": prev.isoformat(), "title": payload.get("title"),
                              "highlights": hl})


# -- 市場週報 ---------------------------------------------------------------------------------------------------
def _week_day(day: mc.Day, base: mc.Day | None) -> mc.Day:
    """A synthetic session for the week: each quote's move from the close before the week to the week's last close
    (``base`` = the session before the week). Limits do not apply to a week."""
    quotes = {}
    for sym, q in day.quotes.items():
        b = base.quotes.get(sym) if base else None
        prev = b.close if b else None
        quotes[sym] = mc.Quote(q.symbol, q.code, q.market, q.name, q.close, prev, prev, q.value, q.volume, q.shares,
                               q.industry_code, None, None, q.cls, q.common, q.dataset, day.day)
    return mc.Day(day.market, day.day, base.day if base else None, quotes, set(day.datasets))


def _weekly(p: Pack, md_: Any) -> None:
    ed = p.ed
    start, end = ed.period
    days = tw_trading_days(start, end)
    for d in days:
        p.dates["report"].add(d.isoformat())
    if ed.next_period:
        for x in range((ed.next_period[1] - ed.next_period[0]).days + 1):
            p.dates["next_period"].add((ed.next_period[0] + timedelta(days=x)).isoformat())
    # international: US ETFs over the week's US sessions, USD/TWD
    rows = _us_facts(p, ed.us_sessions, "week", since=start, strip=False)
    p.chart(B.g6_us_bars(rows, title=f"美股 ETF 與台積電 ADR（美股 {span(start, end)}）",
                         sources=p.labels([f"{mc.US_SOURCE}/price"])))
    _us_holidays(p, start, end)
    fx = mc.usd_twd(p.db, end, p.cutoff, limit=15)
    week_fx = [x for x in fx if start <= x[0] <= end]
    before_fx = [x for x in fx if x[0] < start]
    if week_fx and before_fx:
        chg = week_fx[-1][1] - before_fx[-1][1]
        p.fact(f"美元兌新台幣 {span(start, end)} 週變化（央行）", "美元兌新台幣", "fx_change", "week", chg,
               f"{'▲' if chg > 0 else '▼' if chg < 0 else ''}{abs(chg):.3f}", unit="元", precision=3,
               day=week_fx[-1][0], dataset="cbc-opendata/fx", aliases=["新台幣", "台幣", "匯率"])
    next_events_title = f"下週行事曆 {span(*ed.next_period)}" if ed.next_period else "下週行事曆"
    if not days:  # the whole week was closed: a short edition (next week's calendar and the world)
        p.notes.append("week_closed")
        p.miss("week_closed", f"{span(start, end)} 台股整週休市，這份週報只有下週行事曆與國際段落。")
        _calendar(p, ed.next_period[0], ed.next_period[1], next_events_title)  # type: ignore[index]
        p.fixed = _fixed(p, ["G6"])
        return
    archived = [d for d in mc.session_dates(p.db, "TWSE", end, p.cutoff, p.policy, 10) if d >= start]
    if not archived:
        p.notes.append("week_not_archived")
        p.miss("week_not_archived", f"{span(start, end)} 的上市收盤還沒有存檔，這份週報只有下週行事曆與國際段落。")
        _calendar(p, ed.next_period[0], ed.next_period[1], next_events_title)  # type: ignore[index]
        p.fixed = _fixed(p, ["G6"])
        return
    first, last = days[0], archived[-1]
    twse_last = mc.load_day(p.db, "TWSE", last, p.cutoff, p.policy)
    # base: the session before the week (the last close before Monday)
    before = mc.session_dates(p.db, "TWSE", first - timedelta(days=1), p.cutoff, p.policy, 1)
    base_day = mc.load_day(p.db, "TWSE", before[-1], p.cutoff, p.policy) if before else None
    # indices: the week's change
    week_moves: dict[str, Decimal] = {}
    for name, subject, aliases, key in ((mc.TAIEX, "加權指數", TAIEX_ALIASES, "taiex"),
                                        (TAIEX_TR, "報酬指數", ["加權報酬指數"], "tr"),
                                        (TPEX_INDEX, "櫃買指數", OTC_ALIASES, "otc")):
        pts = mc.index_points(p.db, name, p.cutoff, upto=end, policy=p.policy)
        in_week = [x for x in pts if start <= x.day <= end]
        pre = [x for x in pts if x.day < start]
        if not in_week or not pre:
            continue
        pts_chg = in_week[-1].close - pre[-1].close
        pct = pts_chg / pre[-1].close
        week_moves[key] = pct
        p.fact(f"{subject} {span(start, end)} 週漲跌點數", subject, "week_points", "week", pts_chg,
               B.points_text(pts_chg), unit="點", day=in_week[-1].day, dataset=in_week[-1].dataset, aliases=aliases)
        fid = p.fact(f"{subject} {span(start, end)} 週漲跌幅", subject, "week_pct", "week", pct, B.pct_text(pct),
                     unit="%", day=in_week[-1].day, dataset=in_week[-1].dataset, aliases=aliases)
        if key in ("taiex", "otc"):
            p.number(fid, B.number(f"{key}_week", f"{subject}週漲跌", B.pct_text(pct), change=B.points_text(pts_chg),
                                   tone_=B.tone(pct), date_label=span(start, end)))
    # turnover: FMTQIK's official values of the week's sessions (all of them, or our own sum)
    official = {r.date: r.trade_value for r in p.db.scalars(select(MarketTurnoverDaily).where(
        MarketTurnoverDaily.market == "TWSE", MarketTurnoverDaily.date >= start, MarketTurnoverDaily.date <= end))
        if r.trade_value and usable("twse-openapi/turnover", r.date, p.cutoff)}
    loaded = {d: mc.load_day(p.db, "TWSE", d, p.cutoff, p.policy) for d in days}
    if all(d in official for d in days):
        total = sum(official[d] for d in days)
        fid = p.fact(f"上市全週成交金額 {span(start, end)}", "上市成交金額", "turnover", "week", total,
                     B.yi_text(total), unit="億元", precision=0, day=last, dataset="twse-openapi/turnover",
                     aliases=["成交金額", "成交值", "量能"])
        p.number(fid, B.number("turnover_week", "全週成交金額", B.yi_text(total), date_label=span(start, end)))
    else:
        sums = [mc.turnover_sum(x) if x is not None else None for x in loaded.values()]  # every session or none
        if sums and all(s is not None for s in sums):
            total = sum(sums)  # type: ignore[arg-type]
            fid = p.fact(f"上市全週成交金額（Forliosa 加總，估算）{span(start, end)}", "上市成交金額", "turnover_est",
                         "week", total, B.yi_text(total), unit="億元", precision=0, day=last,
                         dataset="rules:turnover_sum", estimate=True, aliases=["成交金額", "成交值", "量能"])
            p.number(fid, B.number("turnover_week", "全週成交金額", B.yi_text(total), date_label=span(start, end),
                                   estimate=True))
    # the three industries with the largest traded value (per-stock values summed by industry)
    by_ind: dict[str, int] = defaultdict(int)
    for x in loaded.values():
        for q in (x.commons() if x else []):
            if q.value and q.industry_code:
                by_ind[q.industry_code] += q.value
    if by_ind:
        top3 = sorted(by_ind.items(), key=lambda kv: -kv[1])[:3]
        names3 = []
        for code, v in top3:
            name = INDUSTRY_CODES.get(code, code)
            names3.append(name)
            p.fact(f"{name} {span(start, end)} 成交金額（Forliosa 依個股成交金額加總）", name, "industry_value", "week",
                   v, B.yi_text(v), unit="億元", precision=0, day=last, dataset="rules:turnover_sum",
                   aliases=[name.removesuffix("業").removesuffix("工業")])
        p.blocks["numbers"].append(B.number("top_industries", "成交金額前三產業", "、".join(names3),
                                            date_label=span(start, end)))
    if twse_last is not None:
        p.datasets |= twse_last.datasets
        now_cap, _ = mc.total_mcap(twse_last)
        if now_cap:
            fid = p.fact(f"上市普通股總市值 {md(last)}（Forliosa 估算）", "上市總市值", "mcap_total", "structure",
                         now_cap, B.zhao_text(now_cap), unit="兆元", day=last, dataset="rules:market_cap",
                         estimate=True)
            p.number(fid, B.number("mcap", "上市總市值", B.zhao_text(now_cap), date_label=md(last), estimate=True))
    # sectors over the week: G17 (each session's estimate summed), T3 (9 indices), G2 v2, G8
    secs = mc.sectors(p.db, last, p.cutoff, twse_last, p.policy, since=start)
    sessions = [loaded.get(d) for d in archived]
    daily: list[list[mc.SectorContrib]] = []
    for day in sessions:
        if day is None or not _moves(day):
            daily = []
            break
        t = mc.index_on(p.db, mc.TAIEX, day.day, p.cutoff, p.policy)
        one = mc.sector_contributions(day, _taiex_prev(p, t, day))
        if not one:
            daily = []
            break
        daily.append(one)
    week_contribs = mc.add_contributions(daily) if daily and len(daily) == len(days) else []
    _contrib_facts(p, week_contribs, secs, last, "week", span(start, end))
    _sector_facts(p, secs, last, "week", period=span(start, end))
    tpts = mc.index_points(p.db, mc.TAIEX, p.cutoff, upto=end, policy=p.policy)
    tw, tb = [x for x in tpts if start <= x.day <= end], [x for x in tpts if x.day < start]
    official_week = tw[-1].close - tb[-1].close if tw and tb else None
    sector_ds = sorted({s.dataset for s in secs})
    if week_contribs and twse_last is not None:
        _g17(p, week_contribs, secs, official_week, week=True,
             title=f"各類股對加權指數的週點數貢獻（估算，{span(start, end)}）",
             sources=p.labels([*twse_last.datasets, *sector_ds, "rules:contribution"]))
    _returns_table(p, last, start)
    week = _week_day(twse_last, base_day) if twse_last is not None and base_day is not None else None
    inner = mc.sector_breadth(week) if week is not None and _moves(week) else None
    week_base = before[-1] if before else last_tw_trading_day(first - timedelta(days=1))
    _g2(p, last, secs, inner, week_moves.get("taiex"), title=f"上市類股指數週漲跌（{span(start, end)}）",
        sources=p.labels([*sector_ds, *(twse_last.datasets if inner and twse_last else [])]),
        first=("1w", "近 1 週", week_base), periods=[("1m", "近 1 月", mc.month_base(last))])
    values = mc.week_values(loaded.values()) if all(x is not None for x in loaded.values()) else None
    if week is not None and values:
        prev_days = tw_trading_days(start - timedelta(days=7), start - timedelta(days=1))
        prev_loaded = [mc.load_day(p.db, "TWSE", d, p.cutoff, p.policy) for d in prev_days]
        prev = None
        if prev_days and all(x is not None for x in prev_loaded):
            prev_values = mc.week_values(prev_loaded)
            prev = mc.sector_values(prev_loaded[-1].quotes.values(), prev_values)  # type: ignore[union-attr]
        scope = mc.rule_scope(p.db, week.by_mcap(), last)
        _g8(p, mc.sector_values(week.quotes.values(), values), prev or None, scope.in_range, week=True,
            values=values, pcts={q.symbol: q.pct for q in week.commons()},
            title=f"上市類股成交金額比重（{span(start, end)}）",
            sources=p.labels([*twse_last.datasets, "rules:turnover_sum"]))  # type: ignore[union-attr]
    # stocks over the week: weights from the session before the week
    contrib: dict[str, Decimal] = {}
    tpex_last = _latest_day(p, "TPEX", last)
    if week is not None and base_day is not None and twse_last is not None:
        taiex_base = mc.index_on(p.db, mc.TAIEX, base_day.day, p.cutoff, p.policy)
        contrib = mc.contributions(week, taiex_base.close if taiex_base else None)
        lists = mc.rule_lists(p.db, week, limits=False)
        for q in lists.top10:
            p.stock(q, "市值前 10", "week", contrib=contrib.get(q.symbol), with_mcap=True,
                    pct_label=f"{B.stock_label(q.name, q.code)} {span(start, end)} 週漲跌幅")
        for q in lists.gainers:
            p.stock(q, "週漲幅前 5", "week", pct_label=f"{B.stock_label(q.name, q.code)} {span(start, end)} 週漲跌幅")
        for q in lists.losers:
            p.stock(q, "週跌幅前 5", "week", pct_label=f"{B.stock_label(q.name, q.code)} {span(start, end)} 週漲跌幅")
        rows3 = [{"label": q.name, "symbol": q.symbol, "points": contrib[q.symbol]} for q in lists.top10
                 if q.symbol in contrib]
        rest = sum(contrib.values(), Decimal(0)) - sum((r["points"] for r in rows3), Decimal(0)) if contrib else None
        p.chart(B.g3_contribution_bars(rows3, rest, official_week,
                                       title=f"市值前 10 大對加權指數的週點數貢獻（估算，{span(start, end)}）",
                                       sources=p.labels([*twse_last.datasets, "rules:contribution"])))
        taiex_last = mc.index_on(p.db, mc.TAIEX, last, p.cutoff, p.policy)
        _week_tables(p, lists, week, values, base_day.day, taiex_last, start, end, p.labels(twse_last.datasets))
        top100 = mc.top_by_mcap([twse_last, tpex_last])
        if ed.next_period:
            _event_stocks(p, [twse_last, tpex_last], ed.next_period[0], ed.next_period[1], set(top100))
        p.rules.append(RULE_STOCKS)
        g5 = _g5(p, md_, _top5_weight_symbols(twse_last), f"權值前 5 檔一個月比較（至 {md(last)}）")
        p.chart(g5)
        # G5 is the week's chart of the day now (three lists), no longer fixed; G4's breadth is gone (v2)
        _menu(p, "G5", g5 is not None, ["week"], ["top5_weight", "gainers", "losers"] if g5 is not None else [])
    else:
        top100 = []
    # G1: about a month of TAIEX closes
    pts, ds = _taiex_series(p, end, since=mc.month_back(end))
    p.chart(B.g1_index_line(pts, sources=p.labels(ds), title=f"加權指數收盤（至 {md(end)}）"))
    # chips: foreign futures net OI over the week, T9 (the three investors' week, P/C, TPEx institutions), G16, T10
    oi = mc.futures_oi_series(p.db, end, p.cutoff)
    wk, pre = [x for x in oi if start <= x[0] <= end], [x for x in oi if x[0] < start]
    if wk:
        p.fact(f"外資台指期淨未平倉 {md(wk[-1][0])}", "外資台指期", "futures_oi_net", "week", wk[-1][1],
               f"{'淨多' if wk[-1][1] > 0 else '淨空'} {abs(wk[-1][1]):,} 口", unit="口", precision=0, day=wk[-1][0],
               dataset="taifex-openapi/institutional_futures", aliases=["外資", "台指期", "期貨"])
        if pre:
            ch = wk[-1][1] - pre[-1][1]
            p.fact(f"外資台指期淨未平倉 {span(start, end)} 週變化", "外資台指期", "futures_oi_change", "week", ch,
                   f"{'▲' if ch > 0 else '▼' if ch < 0 else ''}{abs(ch):,} 口", unit="口", precision=0,
                   day=wk[-1][0], dataset="taifex-openapi/institutional_futures", aliases=["外資", "台指期", "期貨"])
    p.chart(B.g7_futures_columns(oi, title=f"外資台指期淨未平倉（至 {md(end)}）",
                                 sources=p.labels(["taifex-openapi/institutional_futures"])))
    pc = mc.put_call(p.db, end, p.cutoff)
    if pc is not None and pc.oi_ratio is not None and start <= pc.trade_date <= end:
        p.fact(f"台指選擇權 P/C 未平倉比 {md(pc.trade_date)}", "P/C 比", "pc_ratio_oi", "week", pc.oi_ratio,
               f"{pc.oi_ratio * 100:.2f}%", unit="%", day=pc.trade_date, dataset="taifex-openapi/put_call_ratio",
               aliases=["P/C", "賣買權"])
    otc_sum = {"foreign": Decimal(0), "trust": Decimal(0), "dealer": Decimal(0), "total": Decimal(0)}
    otc_days = 0
    per_week: list[mc.FlowAmount] = []
    industries: dict[str, str | None] = {}
    for d in days:
        tp = mc.load_day(p.db, "TPEX", d, p.cutoff, p.policy)
        inst = mc.otc_institutional(p.db, tp, p.cutoff) if tp else None
        if inst and tp is not None:
            otc_days += 1
            for k in otc_sum:
                otc_sum[k] += inst[0][k]
            per_week += inst[1]
            industries.update({q.symbol: q.industry_code for q in tp.quotes.values()})
    otc_week = otc_sum["total"] if otc_days == len(days) else None
    if otc_week is not None:
        v = otc_week
        p.datasets.add("tpex-openapi/institutional")
        p.fact(f"上櫃三大法人 {span(start, end)} 買賣超估算金額（股數 × 收盤價）", "上櫃三大法人", "otc_inst_total",
               "week", v,
               f"{'買超' if v >= 0 else '賣超'} {B.yi_text(abs(v), 1)}", unit="億元", precision=1, day=last,
               dataset="tpex-openapi/institutional", estimate=True, aliases=["三大法人", "法人"])
    _t9(p, start, end, pc if pc is not None and pc.oi_ratio is not None and start <= pc.trade_date <= end else None,
        otc_week)
    if otc_week is not None:
        _g16(p, mc.otc_flows_by_industry(per_week, industries), otc_week,
             title=f"上櫃三大法人週買賣超，依產業別（估算，{span(start, end)}）",
             sources=[*p.labels(["tpex-openapi/institutional", "tpex-openapi/price"]), label("rules")])
    _t10(p, [twse_last, tpex_last], last, since=start, title=span(start, end))
    # calendar: the review week and the next week
    names = {q.symbol: q.name for q in (twse_last.quotes.values() if twse_last else [])}
    review = cal.events_between(p.db, start, end, cutoff=p.cutoff, policy=p.policy, top100=top100, names=names,
                                include_filings=False)
    for e in review:
        if e.fold:
            continue
        cid = p._id("C")
        p.calendar.append({"id": cid, "date": e.date.isoformat(), "time_taipei": e.time_taipei, "title": e.title,
                           "kind": e.kind, "symbol": e.symbol, "sectors": e.sectors, "source": e.source, "url": e.url,
                           "fold": None, "note": e.note, "review": True})
        p.datasets.add(e.source)
    if ed.next_period:
        _calendar(p, ed.next_period[0], ed.next_period[1], next_events_title, top100=top100, names=names,
                  include_filings=False)
    p.fixed = _fixed(p, ("G1", "G17", "G2", "G8", "G3", "G16", "G7", "G6"))


def _t9(p: Pack, start: date, end: date, pc: Any, otc_week: Decimal | None) -> None:
    """T9: the week's chips in one table: the three investors' TAIEX futures net open interest at the week's end and
    its change over the week, P/C at the week's end, TPEx institutions' week (an estimate)."""
    rows: list[dict[str, Any]] = []
    ds: list[str] = []
    if p.ok("taifex-openapi/institutional_futures"):
        for investor in mc.INVESTORS:
            series = mc.futures_oi_series(p.db, end, p.cutoff, investor, limit=15)
            wk = [x for x in series if start <= x[0] <= end]
            pre = [x for x in series if x[0] < start]
            if not wk:
                continue
            net = wk[-1][1]
            ch = net - pre[-1][1] if pre else None
            rows.append({"cells": {"item": B.cell(f"{investor}台指期淨未平倉", sub=md(wk[-1][0])),
                                   "value": B.cell(f"{'淨多' if net > 0 else '淨空'} {abs(net):,} 口"),
                                   "change": B.cell(f"{ch:+,} 口" if ch is not None else "—")}})
            ds.append("taifex-openapi/institutional_futures")
    if pc is not None:
        rows.append({"cells": {"item": B.cell("台指選擇權 P/C 未平倉比", sub=md(pc.trade_date)),
                               "value": B.cell(f"{pc.oi_ratio * 100:.2f}%"), "change": B.cell("—")}})
        ds.append("taifex-openapi/put_call_ratio")
    if otc_week is not None:
        rows.append({"cells": {"item": B.cell("上櫃三大法人（估算金額）", sub="全週合計"),
                               "value": B.cell(f"{'買超' if otc_week >= 0 else '賣超'} {B.yi_text(abs(otc_week), 1)}"),
                               "change": B.cell("—")}})
        ds.append("tpex-openapi/institutional")
    if not rows:
        return
    p.datasets.update(ds)
    p.table(B.table("T9", f"籌碼一週（{span(start, end)}）",
                    [("item", "項目", "left", False), ("value", "本週收", "right", True),
                     ("change", "週變化", "right", True)], rows,
                    rule="期貨的週變化是本週最後一個交易日對上週最後一個交易日；上櫃法人是每天股數 × 收盤價的加總",
                    sources=p.labels(ds)))


def _week_tables(p: Pack, lists: mc.Lists, week: mc.Day, values: dict[str, int] | None, base: date,
                 taiex: mc.IndexPoint | None, start: date, end: date, srcs: list[str]) -> None:
    """T2_top10 v2 (the week and about a month), then three tabs: the week's gainers, losers and traded value."""
    title = span(start, end)
    _t2_top10_v2(p, lists.top10, week.day, taiex, title=f"市值前 10 的大方向（{title}）", sources=srcs,
                 week_base=base)
    p.table(B.table("T2_gainers", f"週漲幅前 5（{title}）", B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.gainers],
                    rule=lists.scope_rule, empty_text="範圍內沒有上漲的股票。", sources=srcs, tab_group="movers",
                    tab_label="週漲幅"))
    p.table(B.table("T2_losers", f"週跌幅前 5（{title}）", B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.losers],
                    rule=lists.scope_rule, empty_text="範圍內沒有下跌的股票。", sources=srcs, tab_group="movers",
                    tab_label="週跌幅"))
    if not values:
        return
    scope = mc.rule_scope(p.db, week.by_mcap(), week.day)
    order = {q.symbol: i for i, q in enumerate(scope.ranked)}
    top = sorted((q for q in scope.in_range if values.get(q.symbol)),
                 key=lambda q: (-values[q.symbol], order.get(q.symbol, 10**6)))[:mc.TOP_N]
    p.table(B.table("T2_value", f"週成交值前 10（{title}）", [*B.STOCK_COLUMNS, ("value", "週成交金額", "right", True)],
                    [B.stock_row(q, {"value": B.cell(B.yi_text(values[q.symbol], 1))}) for q in top],
                    rule=lists.scope_rule + "；漲跌幅是整週", sources=srcs, tab_group="movers", tab_label="週成交值"))


# T3 v2: the 9 indices of 「大方向」 (the 32 sectors are G2's period chips now)
WEEK_INDICES: tuple[tuple[str, str], ...] = (
    (mc.TAIEX, "加權指數"), (TAIEX_TR, "報酬指數"), (TPEX_INDEX, "櫃買指數"), ("臺灣50指數", "臺灣50"),
    ("臺灣中型100指數", "中型100"), ("小型股300指數", "小型股300"), ("電子工業類指數", "電子工業"),
    ("未含電子指數", "未含電子"), ("金融保險類指數", "金融保險"),
)


T3_RULE = "週漲跌是本週最後一個交易日對上週最後一個交易日；底色只分兩階（1 週：2%、5%；近 1 月：4%、10%）"


def _returns_table(p: Pack, last: date, week_start: date) -> None:
    """T3: the week and about a month (「11/12 起」 until the archive reaches a month back) of the 9 indices, with
    heat-tinted cells."""
    month_base = mc.month_base(last)
    rows: list[dict[str, Any]] = []
    month_short = False
    first_day: date | None = None
    series = {}
    for name, show in WEEK_INDICES:
        pts = mc.index_points(p.db, name, p.cutoff, upto=last, policy=p.policy)
        if pts and pts[-1].day == last:
            series[name] = (show, pts)
            month_short |= mc.index_move(pts, last, month_base) is None
    datasets = sorted({pts[-1].dataset for _show, pts in series.values()})
    if month_short:  # from the start of the TAIEX's MI_INDEX archive (the file every listed index comes in)
        anchor = series.get(mc.TAIEX) or next(iter(series.values()), None)
        first_day = anchor[1][0].day if anchor else None
    week_base = last_tw_trading_day(week_start - timedelta(days=1))
    for _name, (show, pts) in series.items():
        wk = mc.index_move(pts, last, week_base)
        if not month_short:
            mo = mc.index_move(pts, last, month_base)
        else:
            mo = mc.index_move(pts, last, first_day) if first_day is not None and first_day < last else None
        rows.append({"cells": {"name": B.cell(show), "w1": B.move_cell(wk, "1w"), "m1": B.move_cell(mo, "1m")}})
    m_label = "近 1 月" if not month_short else (f"{md(first_day)} 起" if first_day else "近 1 月")
    p.table(B.table("T3", f"主要指數的大方向（至 {md(last)}）",
                    [("name", "指數", "left", False), ("w1", "1 週", "right", True), ("m1", m_label, "right", True)],
                    rows, rule=T3_RULE,
                    note=f"近 1 月 {md(mc.archive_ready(first_day)[1])} 起才有；在那之前是存檔起的漲跌"
                    if month_short and first_day else None,
                    empty_text="指數資料還不夠。", sources=p.labels(datasets or ["twse-openapi/index"])))
    p.rules.append("多期間報酬表的空格表示存檔還不夠長，不能自己推算。")


# -- convenience ------------------------------------------------------------------------------------------------------
def summary(built: Built) -> dict[str, Any]:
    """Counts for the CLI and logs (no content)."""
    pk = built.pack
    return {"kind": pk["kind"], "edition_date": pk["edition_date"], "cutoff": pk["cutoff"],
            "facts": len(pk["facts"]), "calendar": len(pk["calendar"]), "filings": len(pk["filings"]),
            "research": len(pk["research"]), "stocks": len(pk["stocks"]), "sectors": len(pk["sectors"]),
            "charts": sorted(k for k, v in built.blocks["charts"].items() if isinstance(v, dict)),
            "tables": sorted(built.blocks["tables"]), "numbers": len(built.blocks["numbers"]),
            "missing": [m["key"] for m in pk["missing"]], "notes": built.notes}
