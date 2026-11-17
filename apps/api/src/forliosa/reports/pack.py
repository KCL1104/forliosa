"""The data pack of a market report (contract §6): every number, calendar row, filing and shared-research source the
writer may use, each with an id (F / C / N / W; X are the gathered reports, added by the gathering), plus the blocks
the page shows (charts G1–G7, tables, the number strip, the calendar) — built by the server from the archive only.

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
from forliosa.timeutil import TAIPEI, iso_taipei, next_tw_trading_day, now_taipei, tw_trading_days

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
    "week_pct", "week_points", "count",
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
        p.rules.append(f"類股文字只能談：{'、'.join(eligible)}（漲幅前 3、跌幅前 3，排除一檔占一半以上的類股；"
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
    return clip_chart(dict(card, id="G5", title=title, series=series), through)


def _g5(p: Pack, md_: Any, symbols: list[str], title: str) -> dict[str, Any] | None:
    return g5_card(md_, symbols, title, p.through)


def _top5_weight_symbols(day: mc.Day | None) -> list[str]:
    return [q.symbol for q in day.by_mcap()[:5]] if day else []


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
    # sectors
    secs = mc.sectors(p.db, d, p.cutoff, twse, p.policy)
    _sector_facts(p, secs, d, "today")
    sector_ds = sorted({s.dataset for s in secs})
    p.chart(B.g2_sector_bars(_sector_rows(secs), title=f"上市類股指數漲跌（{md(d)}）", sources=p.labels(sector_ds)))
    # stocks
    top100: list[str] = []
    names: dict[str, str] = {}
    contrib: dict[str, Decimal] = {}
    if twse is not None:
        taiex_prev = (taiex.close - taiex.change) if taiex is not None and taiex.change is not None else None
        if taiex_prev is None and twse.prev_day:
            prev = mc.index_on(p.db, mc.TAIEX, twse.prev_day, p.cutoff, p.policy)
            taiex_prev = prev.close if prev else None
        contrib = mc.contributions(twse, taiex_prev)
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
        _close_tables(p, twse, lists, contrib, d)
        # G3 contributions
        rows = [{"label": q.name, "symbol": q.symbol, "points": contrib[q.symbol]} for q in lists.top10
                if q.symbol in contrib]
        rest = sum(contrib.values(), Decimal(0)) - sum((r["points"] for r in rows), Decimal(0)) if contrib else None
        p.chart(B.g3_contribution_bars(rows, rest, taiex.change if taiex else None,
                                       title=f"市值前 10 大對加權指數的點數貢獻（估算，{md(d)}）",
                                       sources=p.labels([*twse.datasets, "rules:contribution"])))
        if any(q.pct is not None for q in twse.commons()):
            br = mc.breadth(twse)
            p.chart(B.g4_breadth_bars(br.up, br.flat, br.down, br.limit_up, br.limit_down,
                                      title=f"上市普通股漲跌家數（{md(d)}）", sources=p.labels(twse.datasets)))
        _research(p, list(p.stocks), d)
    # G1
    if taiex is not None:
        pts, ds = _taiex_series(p, d, limit=60)
        p.chart(B.g1_index_line(pts, sources=p.labels(ds), title=f"加權指數收盤（至 {md(d)}）"))
    else:
        p.blocks["notes"]["G1"] = "官方加權指數尚未取得"
    g5 = _g5(p, md_, _top5_weight_symbols(twse), f"權值前 5 檔一個月比較（至 {md(d)}）")
    p.chart(g5)
    _menu(p, "G4", twse is not None, ["day"])
    _menu(p, "G5", g5 is not None, ["day"], ["top5_weight", "gainers", "losers"] if g5 is not None else [])
    p.fixed = ["G1", "G2", "G3"]
    _filings(p, d, "14:00", set(top100), names)
    # tonight and the next session's scheduled events
    nxt = next_tw_trading_day(d + timedelta(days=1))
    _calendar(p, d, nxt, f"盤後與下個交易日行事曆（{md(d)}–{md(nxt)}）", top100=top100, names=names)
    _close_evening(p, d)


def _close_evening(p: Pack, d: date) -> None:
    """The tables the 23:45 and 06:40 runs add (contract §13.3): T5 上櫃排行, T6 上櫃類股 (Forliosa's own),
    T7 期貨三大法人, T8 上櫃三大法人 (estimated amounts). Each only once its data existed at the cut-off (TPEx closes
    about 23:30, TAIFEX about 21:45), so the 15:40 pack has none of them."""
    tpex = mc.load_day(p.db, "TPEX", d, p.cutoff, p.policy)
    if tpex is not None and tpex.day == d and any(q.pct is not None for q in tpex.commons()):
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
                        empty_text="範圍內沒有上漲的股票。", sources=srcs))
        p.table(B.table("T5_losers", f"上櫃跌幅前 5（{md(d)}）" if lists.limit_down_many is None
                        else f"上櫃{_many_title(lists.limit_down_many, '跌停')}（{md(d)}）", B.STOCK_COLUMNS,
                        [B.stock_row(q) for q in lists.losers], rule=lists.scope_rule,
                        empty_text="範圍內沒有下跌的股票。", sources=srcs))
        secs = mc.otc_sectors(tpex)
        p.table(B.table("T6", f"上櫃類股（Forliosa 依產業別計算，不是官方指數，{md(d)}）",
                        [("name", "產業", "left", False), ("pct", "漲跌幅", "right", True),
                         ("members", "家數", "right", True)],
                        [{"cells": {"name": B.cell(s.name), "pct": B.cell(B.pct_text(s.pct), B.tone(s.pct)),
                                    "members": B.cell(f"{s.members}")}} for s in secs],
                        rule="上櫃普通股依產業別分組，以前一日市值加權；2 家以下的產業不列", fold_after=10,
                        empty_text="上櫃類股還算不出來。", sources=[*srcs, label("rules")]))
        inst = mc.otc_institutional(p.db, tpex, p.cutoff)
        if inst is not None:
            sums, per = inst
            ds = p.labels(["tpex-openapi/institutional", *tpex.datasets])
            p.datasets.add("tpex-openapi/institutional")

            def amount(v: Decimal) -> dict[str, Any]:
                return B.cell(f"{'買超' if v >= 0 else '賣超'} {B.yi_text(abs(v), 1)}", B.tone(v))

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
    rows7 = []
    for investor in mc.INVESTORS:
        series = mc.futures_oi_series(p.db, d, p.cutoff, investor, limit=2)
        if not series or series[-1][0] != d:
            continue
        net = series[-1][1]
        ch = net - series[-2][1] if len(series) > 1 else None
        rows7.append({"cells": {"who": B.cell(investor),
                                "net": B.cell(f"{'淨多' if net > 0 else '淨空'} {abs(net):,} 口", B.tone(net)),
                                "change": B.cell(f"{ch:+,} 口" if ch is not None else "—", B.tone(ch))}})
    if rows7 and p.ok("taifex-openapi/institutional_futures"):
        p.datasets.add("taifex-openapi/institutional_futures")
        p.table(B.table("T7", f"期貨三大法人：台指期淨未平倉（{md(d)}）",
                        [("who", "法人", "left", False), ("net", "淨未平倉", "right", True),
                         ("change", "較前一日", "right", True)], rows7,
                        sources=p.labels(["taifex-openapi/institutional_futures"])))


def _taiex_series(p: Pack, upto: date, since: date | None = None,
                  limit: int = 60) -> tuple[list[tuple[date, Decimal]], set[str]]:
    """The TAIEX closes for G1: MI_INDEX rows, and FMTQIK's TAIEX column for the days the index archive lacks (the
    month FMTQIK carries; usable from its next-morning batch)."""
    pts = {x.day: (x.close, x.dataset) for x in mc.index_points(p.db, mc.TAIEX, p.cutoff, upto=upto, since=since,
                                                                 policy=p.policy, limit=limit)}
    stmt = select(MarketTurnoverDaily).where(MarketTurnoverDaily.market == "TWSE", MarketTurnoverDaily.date <= upto)
    if since:
        stmt = stmt.where(MarketTurnoverDaily.date >= since)
    if p.ok("twse-openapi/turnover"):
        for r in p.db.scalars(stmt):
            if r.taiex and r.date not in pts and usable("twse-openapi/turnover", r.date, p.cutoff):
                pts[r.date] = (r.taiex, "twse-openapi/turnover")
    days = sorted(pts)[-limit:]
    return [(d, pts[d][0]) for d in days], {pts[d][1] for d in days}


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


def _close_tables(p: Pack, day: mc.Day, lists: mc.Lists, contrib: dict[str, Decimal], d: date) -> None:
    srcs = p.labels([*day.datasets])
    top_rows = [B.stock_row(q, {"mcap": B.cell(B.zhao_text(q.mcap) if q.mcap else "—"),
                                "contrib": B.cell(B.signed_text(contrib[q.symbol], 0, " 點")
                                                  if q.symbol in contrib else "—", B.tone(contrib.get(q.symbol)))})
                for q in lists.top10]
    p.table(B.table("T2_top10", f"市值前 10（{md(d)}）",
                    [*B.STOCK_COLUMNS, ("mcap", "市值", "right", True), ("contrib", "點數貢獻（估算）", "right", True)],
                    top_rows, rule="上市普通股，依收盤市值（收盤 × 已發行股數）；點數貢獻是 Forliosa 估算",
                    sources=[*srcs, label("rules")]))
    up_title = f"漲幅前 5（{md(d)}）" if lists.limit_up_many is None else \
        f"{_many_title(lists.limit_up_many, '漲停')}（{md(d)}）"
    down_title = f"跌幅前 5（{md(d)}）" if lists.limit_down_many is None else \
        f"{_many_title(lists.limit_down_many, '跌停')}（{md(d)}）"
    if lists.limit_up_many is not None or lists.limit_down_many is not None:
        # the strip counts every listed common; the lists only their scope: both say which one they count
        for n in p.blocks["numbers"]:
            if n["key"] == "limits":
                n["note"] = LIMITS_NOTE
    p.table(B.table("T2_gainers", up_title, B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.gainers],
                    rule=lists.scope_rule, empty_text="範圍內沒有上漲的股票。", sources=srcs))
    p.table(B.table("T2_losers", down_title, B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.losers],
                    rule=lists.scope_rule, empty_text="範圍內沒有下跌的股票。", sources=srcs))
    col_label = "成交金額" if lists.value_column == "value" else "成交量（股）"
    value_rows = [B.stock_row(q, {"value": B.cell(B.yi_text(q.value, 1) if lists.value_column == "value" and q.value
                                                  else f"{q.volume or 0:,}")}) for q in lists.by_value]
    p.table(B.table("T2_value", f"{'成交值' if lists.value_column == 'value' else '成交量'}前 10（{md(d)}）",
                    [*B.STOCK_COLUMNS, ("value", col_label, "right", True)], value_rows,
                    rule=lists.scope_rule + ("" if lists.value_column == "value"
                                             else "；這天的資料沒有成交金額，改依成交量"),
                    sources=srcs))


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
    pc = mc.put_call(p.db, prev, p.cutoff)
    if pc is not None and pc.trade_date == prev and pc.oi_ratio is not None:
        fid = p.fact(f"台指選擇權 P/C 未平倉比 {md(prev)}", "P/C 比", "pc_ratio_oi", "evening", pc.oi_ratio,
                     f"{pc.oi_ratio * 100:.2f}%", unit="%", day=prev, dataset="taifex-openapi/put_call_ratio",
                     aliases=["P/C", "賣買權"])
        p.number(fid, B.number("pc", "P/C 未平倉比", f"{pc.oi_ratio * 100:.2f}%", date_label=md(prev)))
    # the previous session's TPEx data (published the evening before). The TPEx index closes at 14:30 and was in the
    # previous close report: a previous-session number (never the headline), not one of the evening's
    tpex = mc.load_day(p.db, "TPEX", prev, p.cutoff, p.policy)
    evening_rows: list[dict[str, Any]] = []
    o = mc.index_on(p.db, TPEX_INDEX, prev, p.cutoff, p.policy)
    if o is not None:
        p.fact(f"櫃買指數 {md(prev)} 收盤", "櫃買指數", "otc_close", "prev_session", o.close, B.number_text(o.close),
               unit="點", day=prev, dataset=o.dataset, aliases=OTC_ALIASES)
        if o.pct is not None:
            p.fact(f"櫃買指數 {md(prev)} 漲跌幅", "櫃買指數", "otc_pct", "prev_session", o.pct, B.pct_text(o.pct),
                   unit="%", day=prev, dataset=o.dataset, aliases=OTC_ALIASES)
    if tpex is not None:
        br = _breadth_facts(p, tpex, "evening", prefix="上櫃普通股")
        if br is not None:
            evening_rows.append({"cells": {"item": B.cell("上櫃漲跌家數"),
                                           "value": B.cell(f"{br.up:,}／{br.down:,} 家"), "change": B.cell("")}})
        inst = mc.otc_institutional(p.db, tpex, p.cutoff)
        if inst is not None:
            sums, _ = inst
            for key, who, metric in (("total", "上櫃三大法人", "otc_inst_total"),
                                     ("foreign", "上櫃外資", "otc_inst_foreign"),
                                     ("trust", "上櫃投信", "otc_inst_trust"),
                                     ("dealer", "上櫃自營商", "otc_inst_dealer")):
                v = sums[key]
                p.fact(f"{who}買賣超估算金額 {md(prev)}（股數 × 收盤價）", who, metric, "evening", v,
                       f"{'買超' if v >= 0 else '賣超'} {B.yi_text(abs(v), 1)}", unit="億元", precision=1, day=prev,
                       dataset="tpex-openapi/institutional", estimate=True, aliases=[who.removeprefix("上櫃")])
            v = sums["total"]
            evening_rows.append({"cells": {"item": B.cell("上櫃三大法人（估算金額）"),
                                           "value": B.cell(f"{'買超' if v >= 0 else '賣超'} {B.yi_text(abs(v), 1)}"),
                                           "change": B.cell("")}})
    if oi and oi[-1][0] == prev:
        evening_rows.append({"cells": {"item": B.cell("外資台指期淨未平倉"),
                                       "value": B.cell(f"{'淨多' if oi[-1][1] > 0 else '淨空'} {abs(oi[-1][1]):,} 口"),
                                       "change": B.cell(f"{oi[-1][1] - oi[-2][1]:+,} 口" if len(oi) > 1 else "")}})
    if pc is not None and pc.trade_date == prev and pc.oi_ratio is not None:
        evening_rows.append({"cells": {"item": B.cell("P/C 未平倉比"), "value": B.cell(f"{pc.oi_ratio * 100:.2f}%"),
                                       "change": B.cell("")}})
    if fx and fx[-1][0] == prev:
        # the same change as the number strip's (the second dry run had it there and an empty cell here)
        evening_rows.append({"cells": {"item": B.cell("美元兌新台幣（央行）"), "value": B.cell(f"{fx[-1][1]:.3f}"),
                                       "change": B.cell(f"{fx[-1][1] - fx[-2][1]:+.3f}" if len(fx) > 1 else "")}})
    p.table(B.table("T_evening", f"昨晚才到的資料（{md(prev)}）",
                    [("item", "項目", "left", False), ("value", "數字", "right", True),
                     ("change", "變化", "right", True)], evening_rows,
                    empty_text="前一個交易日晚上的資料還沒有進來。",
                    sources=p.labels(["tpex-openapi/price", "tpex-openapi/institutional",
                                      "taifex-openapi/institutional_futures", "taifex-openapi/put_call_ratio",
                                      "cbc-opendata/fx"])))
    # the previous session's listed numbers: reference only (never the headline: validator §10.2 item 16)
    _index_facts(p, prev, "prev_session", with_tr=False, with_otc=False)
    twse_prev = mc.load_day(p.db, "TWSE", prev, p.cutoff, p.policy)
    secs = mc.sectors(p.db, prev, p.cutoff, twse_prev, p.policy)
    _sector_facts(p, [s for s in secs if s.text_eligible], prev, "prev_session")
    p.chart(B.g2_sector_bars(_sector_rows(secs), title=f"上市類股指數漲跌（{md(prev)}）",
                             sources=p.labels({s.dataset for s in secs})), "G2_prev")
    if twse_prev is not None and any(q.pct is not None for q in twse_prev.commons()):
        br = mc.breadth(twse_prev)
        p.chart(B.g4_breadth_bars(br.up, br.flat, br.down, br.limit_up, br.limit_down,
                                  title=f"上市普通股漲跌家數（{md(prev)}）", sources=p.labels(twse_prev.datasets)),
                "G4_prev")
    g5 = _g5(p, md_, _top5_weight_symbols(twse_prev), f"權值前 5 檔一個月比較（至 {md(prev)}）")
    p.chart(g5)
    _menu(p, "G2", bool(secs), ["day"])
    _menu(p, "G4", twse_prev is not None, ["day"])
    _menu(p, "G5", g5 is not None, ["day"], ["top5_weight"] if g5 is not None else [])
    p.fixed = ["G6", "G7"]
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
        p.fixed = ["G6"]
        return
    archived = [d for d in mc.session_dates(p.db, "TWSE", end, p.cutoff, p.policy, 10) if d >= start]
    if not archived:
        p.notes.append("week_not_archived")
        p.miss("week_not_archived", f"{span(start, end)} 的上市收盤還沒有存檔，這份週報只有下週行事曆與國際段落。")
        _calendar(p, ed.next_period[0], ed.next_period[1], next_events_title)  # type: ignore[index]
        p.fixed = ["G6"]
        return
    first, last = days[0], archived[-1]
    twse_last = mc.load_day(p.db, "TWSE", last, p.cutoff, p.policy)
    # base: the session before the week (the last close before Monday)
    before = mc.session_dates(p.db, "TWSE", first - timedelta(days=1), p.cutoff, p.policy, 1)
    base_day = mc.load_day(p.db, "TWSE", before[-1], p.cutoff, p.policy) if before else None
    # indices: the week's change
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
    # sectors over the week
    secs = mc.sectors(p.db, last, p.cutoff, twse_last, p.policy, since=start)
    _sector_facts(p, secs, last, "week", period=span(start, end))
    p.chart(B.g2_sector_bars(_sector_rows(secs), title=f"上市類股指數週漲跌（{span(start, end)}）",
                             sources=p.labels({s.dataset for s in secs})))
    # stocks over the week: weights from the session before the week
    contrib: dict[str, Decimal] = {}
    if twse_last is not None and base_day is not None:
        week = _week_day(twse_last, base_day)
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
        official_week = None
        tpts = mc.index_points(p.db, mc.TAIEX, p.cutoff, upto=end, policy=p.policy)
        tw, tb = [x for x in tpts if start <= x.day <= end], [x for x in tpts if x.day < start]
        if tw and tb:
            official_week = tw[-1].close - tb[-1].close
        p.chart(B.g3_contribution_bars(rows3, rest, official_week,
                                       title=f"市值前 10 大對加權指數的週點數貢獻（估算，{span(start, end)}）",
                                       sources=p.labels([*twse_last.datasets, "rules:contribution"])))
        _week_tables(p, lists, contrib, start, end, p.labels(twse_last.datasets))
        tpex_last = _latest_day(p, "TPEX", last)
        top100 = mc.top_by_mcap([twse_last, tpex_last])
        if ed.next_period:
            _event_stocks(p, [twse_last, tpex_last], ed.next_period[0], ed.next_period[1], set(top100))
        p.rules.append(RULE_STOCKS)
        g5 = _g5(p, md_, _top5_weight_symbols(twse_last), f"權值前 5 檔一個月比較（至 {md(last)}）")
        p.chart(g5)
        _menu(p, "G5", g5 is not None, ["week"], ["gainers", "losers"] if g5 is not None else [])
    else:
        top100 = []
    br_week = None
    if twse_last is not None and base_day is not None:
        br_week = mc.breadth(_week_day(twse_last, base_day))
        p.chart(B.g4_breadth_bars(br_week.up, br_week.flat, br_week.down, 0, 0,
                                  title=f"上市普通股週漲跌家數（{span(start, end)}）",
                                  sources=p.labels(twse_last.datasets)))
    _menu(p, "G4", br_week is not None, ["week"])
    # G1: about a month of TAIEX closes
    pts, ds = _taiex_series(p, end, since=mc.month_back(end))
    p.chart(B.g1_index_line(pts, sources=p.labels(ds), title=f"加權指數收盤（至 {md(end)}）"))
    # chips: foreign futures net OI over the week, P/C, TPEx institutional sums of the week
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
    for d in days:
        tp = mc.load_day(p.db, "TPEX", d, p.cutoff, p.policy)
        inst = mc.otc_institutional(p.db, tp, p.cutoff) if tp else None
        if inst:
            otc_days += 1
            for k in otc_sum:
                otc_sum[k] += inst[0][k]
    if otc_days == len(days):
        v = otc_sum["total"]
        p.fact(f"上櫃三大法人 {span(start, end)} 買賣超估算金額（股數 × 收盤價）", "上櫃三大法人", "otc_inst_total",
               "week", v,
               f"{'買超' if v >= 0 else '賣超'} {B.yi_text(abs(v), 1)}", unit="億元", precision=1, day=last,
               dataset="tpex-openapi/institutional", estimate=True, aliases=["三大法人", "法人"])
    # T3 multi-period returns
    _returns_table(p, last, start, secs)
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
    _menu(p, "G2", bool(secs), ["week"])
    p.fixed = ["G1", "G2", "G3", "G5", "G6", "G7"]


def _week_tables(p: Pack, lists: mc.Lists, contrib: dict[str, Decimal], start: date, end: date,
                 srcs: list[str]) -> None:
    title = span(start, end)
    p.table(B.table("T2_top10", f"市值前 10（{title}）",
                    [*B.STOCK_COLUMNS, ("contrib", "週點數貢獻（估算）", "right", True)],
                    [B.stock_row(q, {"contrib": B.cell(B.signed_text(contrib[q.symbol], 0, " 點")
                                                       if q.symbol in contrib else "—", B.tone(contrib.get(q.symbol)))})
                     for q in lists.top10],
                    rule="上市普通股，依週末收盤市值；漲跌幅是整週（上週五收盤到本週最後一個交易日）", sources=srcs))
    p.table(B.table("T2_gainers", f"週漲幅前 5（{title}）", B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.gainers],
                    rule=lists.scope_rule, empty_text="範圍內沒有上漲的股票。", sources=srcs))
    p.table(B.table("T2_losers", f"週跌幅前 5（{title}）", B.STOCK_COLUMNS, [B.stock_row(q) for q in lists.losers],
                    rule=lists.scope_rule, empty_text="範圍內沒有下跌的股票。", sources=srcs))


def _returns_table(p: Pack, last: date, week_start: date, secs: list[mc.Sector]) -> None:
    """T3: 1 day, 1 week, 1 month and since the archive began, for the indices and the 32 sectors."""
    month_from = mc.month_back(last) + timedelta(days=1)
    names = [(mc.TAIEX, "加權指數"), (TAIEX_TR, "報酬指數"), (TPEX_INDEX, "櫃買指數")] + \
        [(f"{s.name}類指數", s.name) for s in secs]
    rows, short = [], False
    since_label = None
    for name, show in names:
        pts = mc.index_points(p.db, name, p.cutoff, upto=last, policy=p.policy)
        if not pts or pts[-1].day != last:
            continue
        one = pts[-1].pct
        wk = mc.period_return(pts, last, week_start)
        mo = mc.period_return(pts, last, month_from)
        since, first = mc.since_start_return(pts, last)
        since_label = since_label or (f"{md(first)} 起" if first else None)
        short |= mo is None

        def c(v: Decimal | None) -> dict[str, Any]:
            return B.cell(B.pct_text(v), B.tone(v)) if v is not None else B.cell("—")

        rows.append({"cells": {"name": B.cell(show), "d1": c(one), "w1": c(wk), "m1": c(mo), "since": c(since)}})
    p.table(B.table("T3", f"多期間報酬（至 {md(last)}）",
                    [("name", "指數／類股", "left", False), ("d1", "1 日", "right", True),
                     ("w1", "1 週", "right", True), ("m1", "1 個月", "right", True),
                     ("since", since_label or "存檔起", "right", True)], rows,
                    note="1 個月的比較約 12/9 以後才有" if short else None,
                    empty_text="指數資料還不夠。", sources=p.labels(["twse-openapi/index", "tpex-openapi/index"])))
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
