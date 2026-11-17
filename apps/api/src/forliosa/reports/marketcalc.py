"""Rule calculations for the market reports (contract §7): market caps, estimated index-point contributions, breadth,
limit moves, sectors with their member concentration, the rule-made stock lists, multi-period returns, TPEx sectors
and TPEx institutional amounts. Everything reads official archive rows only, through the data policy, and only rows
that existed at the pack's cut-off (``timing.usable``).

* Common stock: a four-digit code not starting with 00, ``security_class == "stock"``, not a depositary receipt
  (industry 91). Market cap = issued shares (``company_profiles``) × close; no shares, no market cap.
* The day's move is measured from the official reference price of the day (ex-rights days), else the previous close.
* Weight (previous day) = previous market cap ÷ all listed commons' previous market cap; the estimated contribution
  = previous TAIEX × weight × move (always labelled 估算). On 2026-11-16 the sum over every common was −2,634 points
  against the official −2,635.04.
* Sectors: TWSE's 「…類指數」 minus the composites (``market_overview.SECTOR_COMPOSITES``: four old groups and 電子工業)
  = 32; members by industry code (:data:`SECTOR_CODES`); a sector whose largest member weighs more than half is
  ``concentrated`` and never ranked in the text; text may discuss the 3 best, the 3 worst (concentrated ones left out)
  and 半導體 (always, with its concentration).
* Rankings: the 200 largest listed commons or NT$30 billion and up, without the innovation board (「-創」), stocks under
  altered trading (TWT85U) or disposition that day, or a move beyond ±11 % (bad data); ties by market cap.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.datapolicy import dataset_served
from forliosa.marketdata.opendata import INDUSTRY_CODES, TAIEX_TR
from forliosa.models import (
    CompanyProfile,
    FxRate,
    IndexDaily,
    InstitutionalDaily,
    Instrument,
    MarketEvent,
    PriceDaily,
    ReferencePrice,
    TaifexInstitutional,
    TaifexPutCallRatio,
)
from forliosa.reports.timing import usable
from forliosa.services.instruments import security_class
from forliosa.services.market_overview import MAX_MOVE, SECTOR_COMPOSITES, SECTOR_SUFFIX

log = logging.getLogger(__name__)

TAIEX = "發行量加權股價指數"
TW_SOURCES = {"TWSE": ("twse-openapi", "twse-opendata"), "TPEX": ("tpex-openapi",)}
US_SOURCE = "databento-equs"
CONCENTRATION = Decimal("0.5")
SCOPE_RANK = 200
SCOPE_MCAP = Decimal(30_000_000_000)  # NT$300 億
TOP_N = 10
MOVERS_N = 5
EVENT_RANK = 100
LIMIT_MANY = 10  # this many limit-down (or limit-up) stocks in scope: the list says so instead of a top 5
SEMICONDUCTOR = "半導體"
REFERENCE_SYMBOL = "0050.TW"  # 元大台灣50, the comparison line of the close edition
_COMMON = re.compile(r"^(?!00)\d{4}$")

# TWSE sector index (name without 「類指數」) -> industry codes (company_profiles.industry_code)
SECTOR_CODES: dict[str, list[str]] = {
    "水泥": ["01"], "食品": ["02"], "塑膠": ["03"], "紡織纖維": ["04"], "電機機械": ["05"], "電器電纜": ["06"],
    "化學": ["21"], "生技醫療": ["22"], "玻璃陶瓷": ["08"], "造紙": ["09"], "鋼鐵": ["10"], "橡膠": ["11"],
    "汽車": ["12"], "半導體": ["24"], "電腦及週邊設備": ["25"], "光電": ["26"], "通信網路": ["27"],
    "電子零組件": ["28"], "電子通路": ["29"], "資訊服務": ["30"], "其他電子": ["31"], "建材營造": ["14"],
    "航運": ["15"], "觀光餐旅": ["16"], "金融保險": ["17"], "貿易百貨": ["18"], "油電燃氣": ["23"],
    "綠能環保": ["35"], "數位雲端": ["36"], "運動休閒": ["37"], "居家生活": ["38"], "其他": ["20"],
}
SECTOR_NAMES = tuple(SECTOR_CODES)


# -- small helpers ---------------------------------------------------------------------------------------------------
def tick(price: Decimal) -> Decimal:
    """TWSE / TPEx stock tick size (升降單位) at ``price``."""
    if price < 10:
        return Decimal("0.01")
    if price < 50:
        return Decimal("0.05")
    if price < 100:
        return Decimal("0.1")
    if price < 500:
        return Decimal("0.5")
    if price < 1000:
        return Decimal("1")
    return Decimal("5")


def computed_limits(prev: Decimal) -> tuple[Decimal, Decimal]:
    """±10 % of the previous close, rounded inwards to the tick at the limit (used only without official limits)."""
    up, down = prev * Decimal("1.1"), prev * Decimal("0.9")
    tu, td = tick(up), tick(down)
    return (up / tu).to_integral_value(ROUND_FLOOR) * tu, (down / td).to_integral_value(ROUND_CEILING) * td


def signed_pct(change: Decimal | None, pct: Decimal | None, close: Decimal) -> Decimal | None:
    """An index's percentage with the sign of its change (MI_INDEX publishes some unsigned)."""
    if change is None:
        return pct
    if pct is None:
        base = close - change
        return change / base if base else None
    return -abs(pct) if change < 0 else abs(pct)


def is_common(code: str, name: str | None, industry_code: str | None) -> bool:
    return bool(_COMMON.match(code)) and security_class(f"{code}.TW", name) == "stock" and industry_code != "91"


# -- one market's session ------------------------------------------------------------------------------------------
@dataclass
class Quote:
    symbol: str
    code: str
    market: str
    name: str
    close: Decimal
    prev_close: Decimal | None
    base: Decimal | None  # reference price of the day, else the previous close
    value: int | None  # 成交金額 (NT$)
    volume: int | None
    shares: int | None
    industry_code: str | None
    limit_up: Decimal | None
    limit_down: Decimal | None
    cls: str
    common: bool
    dataset: str
    day: date | None = None  # the session of ``close``

    @property
    def pct(self) -> Decimal | None:
        return (self.close - self.base) / self.base if self.base else None

    @property
    def mcap(self) -> Decimal | None:
        return Decimal(self.shares) * self.close if self.shares else None

    @property
    def mcap_prev(self) -> Decimal | None:
        return Decimal(self.shares) * self.prev_close if self.shares and self.prev_close else None

    @property
    def industry(self) -> str | None:
        return INDUSTRY_CODES.get(self.industry_code or "")

    def limit_hit(self) -> int:
        """+1 at the limit up, −1 at the limit down, else 0 (official limits first, else computed)."""
        up, down = self.limit_up, self.limit_down
        if (up is None or down is None) and self.prev_close:
            cu, cd = computed_limits(self.prev_close)
            up, down = up or cu, down or cd
        if up is not None and self.close >= up:
            return 1
        if down is not None and self.close <= down:
            return -1
        return 0


@dataclass
class Day:
    market: str
    day: date
    prev_day: date | None
    quotes: dict[str, Quote]
    datasets: set[str] = field(default_factory=set)

    def commons(self) -> list[Quote]:
        return [q for q in self.quotes.values() if q.common]

    def by_mcap(self) -> list[Quote]:
        return sorted((q for q in self.commons() if q.mcap is not None), key=lambda q: (-q.mcap, q.symbol))


def _suffix(market: str) -> str:
    return ".TWO" if market == "TPEX" else ".TW"


def _sources(market: str, policy: str) -> list[str]:
    return [s for s in TW_SOURCES[market] if dataset_served(f"{s}/price", policy)]  # type: ignore[arg-type]


def session_dates(db: Session, market: str, upto: date, cutoff: datetime, policy: str = "commercial",
                  limit: int = 60) -> list[date]:
    """The newest ``limit`` session dates of ``market`` up to ``upto`` with official closes usable at ``cutoff``
    (newest last)."""
    rows = db.execute(select(PriceDaily.date, PriceDaily.source).where(
        PriceDaily.symbol.like(f"%{_suffix(market)}"), PriceDaily.date <= upto,
        PriceDaily.source.in_(_sources(market, policy))).group_by(PriceDaily.date, PriceDaily.source)
        .order_by(PriceDaily.date.desc()).limit(limit * 3)).all()
    days = sorted({d for d, src in rows if usable(f"{src}/price", d, cutoff)})
    return days[-limit:]


def names_for(db: Session, symbols: Iterable[str]) -> dict[str, str]:
    """Short names: the company profile's 公司簡稱, else the instrument list. Never any other profile field."""
    syms = list(dict.fromkeys(symbols))
    out: dict[str, str] = {}
    for i in range(0, len(syms), 500):
        chunk = syms[i:i + 500]
        for sym, values in db.execute(select(CompanyProfile.symbol, CompanyProfile.values)
                                      .where(CompanyProfile.symbol.in_(chunk))):
            short = (values or {}).get("short_name")
            if short:
                out[sym] = str(short)
        missing = [s for s in chunk if s not in out]
        if missing:
            for sym, name in db.execute(select(Instrument.symbol, Instrument.name).where(
                    Instrument.symbol.in_(missing))):
                if name:
                    out[sym] = name
    return out


def load_day(db: Session, market: str, day: date, cutoff: datetime, policy: str = "commercial") -> Day | None:
    """``market``'s official closes of ``day`` usable at ``cutoff`` (``None`` when there are none), with the previous
    session's closes, the day's reference prices and limits, issued shares and industry codes."""
    srcs = _sources(market, policy)
    suffix = _suffix(market)
    rows = [r for r in db.scalars(select(PriceDaily).where(PriceDaily.date == day, PriceDaily.source.in_(srcs),
                                                           PriceDaily.symbol.like(f"%{suffix}")))
            if usable(f"{r.source}/price", day, cutoff)]
    if not rows:
        return None
    prev_day = db.scalar(select(func.max(PriceDaily.date)).where(
        PriceDaily.date < day, PriceDaily.source.in_(srcs), PriceDaily.symbol.like(f"%{suffix}")))
    prev = dict(db.execute(select(PriceDaily.symbol, PriceDaily.close).where(
        PriceDaily.date == prev_day, PriceDaily.source.in_(srcs), PriceDaily.symbol.like(f"%{suffix}"))).all()) \
        if prev_day else {}
    ref_src = "twse-openapi" if market == "TWSE" else "tpex-openapi"
    refs = {}
    if usable(f"{ref_src}/reference", day, cutoff):
        refs = {r.symbol: r for r in db.scalars(select(ReferencePrice).where(
            ReferencePrice.date == day, ReferencePrice.source == ref_src, ReferencePrice.symbol.like(f"%{suffix}")))}
    symbols = [r.symbol for r in rows]
    profiles = {}
    for i in range(0, len(symbols), 500):
        for p in db.execute(select(CompanyProfile.symbol, CompanyProfile.shares_outstanding,
                                   CompanyProfile.industry_code).where(CompanyProfile.symbol.in_(symbols[i:i + 500]))):
            profiles[p[0]] = (p[1], p[2])
    names = names_for(db, symbols)
    quotes: dict[str, Quote] = {}
    datasets: set[str] = set()
    for r in rows:
        code = r.symbol.split(".")[0]
        shares, ind = profiles.get(r.symbol, (None, None))
        name = names.get(r.symbol) or code
        ref = refs.get(r.symbol)
        prev_close = prev.get(r.symbol)
        base = ref.reference_price if ref is not None and ref.reference_price else prev_close
        cls = security_class(r.symbol, name)
        quotes[r.symbol] = Quote(r.symbol, code, market, name, r.close, prev_close, base, r.value, r.volume, shares,
                                 ind, ref.limit_up if ref else None, ref.limit_down if ref else None, cls,
                                 is_common(code, name, ind), f"{r.source}/price", day)
        datasets.add(f"{r.source}/price")
    if refs:
        datasets.add(f"{ref_src}/reference")
    return Day(market, day, prev_day, quotes, datasets)


# -- breadth, totals, contributions -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Breadth:
    up: int
    flat: int
    down: int
    limit_up: int
    limit_down: int


def breadth(day: Day) -> Breadth:
    up = flat = down = lu = ld = 0
    for q in day.commons():
        if q.pct is None:
            continue
        if q.pct > 0:
            up += 1
        elif q.pct < 0:
            down += 1
        else:
            flat += 1
        hit = q.limit_hit()
        lu += hit == 1
        ld += hit == -1
    return Breadth(up, flat, down, lu, ld)


def turnover_sum(day: Day) -> int | None:
    """Sum of every listed security's 成交金額 in the close file (an estimate of the official FMTQIK value)."""
    vals = [q.value for q in day.quotes.values() if q.value is not None]
    return sum(vals) if vals else None


def total_mcap(day: Day) -> tuple[Decimal, Decimal]:
    """(today's, previous) market cap of the commons that have issued shares and both closes."""
    now = prev = Decimal(0)
    for q in day.commons():
        if q.mcap is not None and q.mcap_prev is not None:
            now += q.mcap
            prev += q.mcap_prev
    return now, prev


def contributions(day: Day, taiex_prev: Decimal | None) -> dict[str, Decimal]:
    """Estimated index points per listed common: previous TAIEX × previous weight × the day's move."""
    if not taiex_prev:
        return {}
    commons = [q for q in day.commons() if q.mcap_prev is not None and q.pct is not None]
    total = sum((q.mcap_prev for q in commons), Decimal(0))
    if not total:
        return {}
    return {q.symbol: taiex_prev * (q.mcap_prev / total) * q.pct for q in commons}


# -- rule-made lists -------------------------------------------------------------------------------------------------
def in_effect(db: Session, kind: str, day: date) -> set[str]:
    """Symbols with an ``altered_trading`` or ``disposition`` row in effect on ``day``. Altered-trading rows run from
    the first day seen (any earlier day too for the first run's backlog) until ``end_date`` (exclusive); disposition
    rows from ``date`` to ``end_date`` inclusive."""
    out = set()
    stmt = select(MarketEvent).where(MarketEvent.type == kind)
    if kind == "disposition":
        stmt = stmt.where(MarketEvent.date <= day)
    for e in db.scalars(stmt):
        if kind == "altered_trading":
            started = e.date <= day or bool((e.data or {}).get("backlog"))
            if started and (e.end_date is None or e.end_date > day):
                out.add(e.symbol)
        elif e.date <= day <= (e.end_date or e.date):
            out.add(e.symbol)
    return out


@dataclass
class Lists:
    top10: list[Quote]
    gainers: list[Quote]
    losers: list[Quote]
    by_value: list[Quote]
    value_column: str  # "value" | "volume" (no 成交金額 in the rows: ranked by volume, the table says so)
    limit_down_many: int | None  # limit-down count in scope when ≥ LIMIT_MANY (losers then = the 5 largest of them)
    limit_up_many: int | None
    scope_rule: str
    excluded: dict[str, int]  # reason -> count


SCOPE_RULE = "範圍：市值前 200 名或 300 億元以上；排除創新板、全額交割（變更交易）、處置股"


def rule_lists(db: Session, day: Day, limits: bool = True) -> Lists:
    """The rule-made lists of a session (or of a synthetic week: ``limits=False``, no limit-move rewrite)."""
    ranked = day.by_mcap()
    top10 = ranked[:TOP_N]
    altered = in_effect(db, "altered_trading", day.day)
    disposed = in_effect(db, "disposition", day.day)
    excluded: dict[str, int] = defaultdict(int)
    scope: list[Quote] = []
    for i, q in enumerate(ranked):
        if i >= SCOPE_RANK and (q.mcap or 0) < SCOPE_MCAP:
            continue
        if "-創" in q.name:
            excluded["innovation_board"] += 1
        elif q.symbol in altered:
            excluded["altered_trading"] += 1
        elif q.symbol in disposed:
            excluded["disposition"] += 1
        elif q.pct is None or abs(q.pct) > MAX_MOVE:
            excluded["bad_move"] += 1
        else:
            scope.append(q)
    order = {q.symbol: i for i, q in enumerate(ranked)}  # market-cap rank breaks ties
    up = sorted((q for q in scope if q.pct > 0), key=lambda q: (-q.pct, order[q.symbol]))
    down = sorted((q for q in scope if q.pct < 0), key=lambda q: (q.pct, order[q.symbol]))
    ld = [q for q in scope if q.limit_hit() == -1] if limits else []
    lu = [q for q in scope if q.limit_hit() == 1] if limits else []
    losers = sorted(ld, key=lambda q: order[q.symbol])[:MOVERS_N] if len(ld) >= LIMIT_MANY else down[:MOVERS_N]
    gainers = sorted(lu, key=lambda q: order[q.symbol])[:MOVERS_N] if len(lu) >= LIMIT_MANY else up[:MOVERS_N]
    commons = day.commons()
    has_value = any(q.value for q in commons)
    col = "value" if has_value else "volume"
    by_value = sorted((q for q in commons if getattr(q, col)), key=lambda q: (-(getattr(q, col) or 0),
                                                                               order.get(q.symbol, 10**6)))[:TOP_N]
    return Lists(top10, gainers, losers, by_value, col, len(ld) if len(ld) >= LIMIT_MANY else None,
                 len(lu) if len(lu) >= LIMIT_MANY else None, SCOPE_RULE, dict(excluded))


def top_by_mcap(days: Iterable[Day | None], n: int = EVENT_RANK) -> list[str]:
    """The ``n`` largest commons over listed and OTC together (each market's newest usable day)."""
    pool = [q for d in days if d is not None for q in d.commons() if q.mcap is not None]
    return [q.symbol for q in sorted(pool, key=lambda q: (-q.mcap, q.symbol))[:n]]


# -- indices ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class IndexPoint:
    name: str
    day: date
    close: Decimal
    change: Decimal | None
    pct: Decimal | None
    dataset: str
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None


def _index_dataset(row: IndexDaily) -> str:
    if row.market == "TPEX":
        return "tpex-openapi/total_return" if "報酬" in row.name else "tpex-openapi/index"
    if row.source == "twse-opendata":
        return "twse-opendata/index"
    return "twse-openapi/total_return" if row.name == TAIEX_TR and row.change is None else "twse-openapi/index"


def index_points(db: Session, name: str, cutoff: datetime, upto: date | None = None, since: date | None = None,
                 policy: str = "commercial", limit: int = 400) -> list[IndexPoint]:
    """An index's closes usable at ``cutoff`` (oldest first), from ``since`` to ``upto``."""
    stmt = select(IndexDaily).where(IndexDaily.name == name)
    if upto:
        stmt = stmt.where(IndexDaily.date <= upto)
    if since:
        stmt = stmt.where(IndexDaily.date >= since)
    out = []
    for r in db.scalars(stmt.order_by(IndexDaily.date.desc()).limit(limit)):
        ds = _index_dataset(r)
        if r.source not in ("twse-openapi", "twse-opendata", "tpex-openapi") or not dataset_served(ds, policy):
            continue
        if not usable(ds, r.date, cutoff):
            continue
        out.append(IndexPoint(r.name, r.date, r.close, r.change, signed_pct(r.change, r.change_pct, r.close), ds,
                              r.open, r.high, r.low))
    out.reverse()
    # fill a missing change from the previous close (multi-day series)
    filled = []
    for i, p in enumerate(out):
        if p.change is None and i > 0:
            ch = p.close - out[i - 1].close
            p = IndexPoint(p.name, p.day, p.close, ch, ch / out[i - 1].close, p.dataset, p.open, p.high, p.low)
        filled.append(p)
    return filled


def index_on(db: Session, name: str, day: date, cutoff: datetime, policy: str = "commercial") -> IndexPoint | None:
    pts = index_points(db, name, cutoff, upto=day, since=day - timedelta(days=20), policy=policy)
    return pts[-1] if pts and pts[-1].day == day else None


# -- sectors ---------------------------------------------------------------------------------------------------------
@dataclass
class Sector:
    name: str
    pct: Decimal
    close: Decimal
    dataset: str
    members: int | None = None
    top_symbol: str | None = None
    top_name: str | None = None
    top_weight: Decimal | None = None
    concentrated: bool = False
    text_eligible: bool = False
    rank: str | None = None  # "top" | "bottom" | "fixed" (半導體)


def sector_names_on(db: Session, day: date) -> list[str]:
    names = db.scalars(select(IndexDaily.name).where(IndexDaily.date == day, IndexDaily.market == "TWSE",
                                                     IndexDaily.name.like(f"%{SECTOR_SUFFIX}")))
    return [n.removesuffix(SECTOR_SUFFIX) for n in names
            if "報酬" not in n and n.removesuffix(SECTOR_SUFFIX) not in SECTOR_COMPOSITES]


def concentration(day: Day | None, sector: str) -> tuple[int | None, Quote | None, Decimal | None]:
    """(members, largest member, its weight) of a sector by its industry codes, from the day's market caps."""
    codes = SECTOR_CODES.get(sector)
    if day is None or not codes:
        return None, None, None
    members = [q for q in day.commons() if q.industry_code in codes and q.mcap is not None]
    if not members:
        return 0, None, None
    total = sum((q.mcap for q in members), Decimal(0))
    top = max(members, key=lambda q: q.mcap)
    return len(members), top, (top.mcap / total) if total else None


def sectors(db: Session, day: date, cutoff: datetime, twse_day: Day | None, policy: str = "commercial",
            since: date | None = None) -> list[Sector]:
    """The 32 listed sectors' moves on ``day`` (or from the close before ``since`` to ``day`` for a week), best first,
    with concentration and which ones the text may discuss."""
    out: list[Sector] = []
    for short in sector_names_on(db, day):
        name = f"{short}{SECTOR_SUFFIX}"
        pts = index_points(db, name, cutoff, upto=day, since=(since - timedelta(days=20)) if since else
                           day - timedelta(days=20), policy=policy)
        if not pts or pts[-1].day != day:
            continue
        last = pts[-1]
        if since is None:
            pct = last.pct
        else:
            base = [p for p in pts if p.day < since]
            pct = (last.close - base[-1].close) / base[-1].close if base else None
        if pct is None:
            continue
        if short not in SECTOR_CODES:
            log.warning("market reports: sector %s has no industry codes (update SECTOR_CODES)", short)
        n, top, weight = concentration(twse_day, short)
        out.append(Sector(short, pct, last.close, last.dataset, n, top.symbol if top else None,
                          top.name if top else None, weight, bool(weight is not None and weight > CONCENTRATION)))
    out.sort(key=lambda s: (-s.pct, s.name))
    ranked = [s for s in out if not s.concentrated]
    for s in ranked[:3]:
        s.text_eligible, s.rank = True, "top"
    for s in ranked[-3:] if len(ranked) > 3 else []:
        s.text_eligible, s.rank = True, "bottom"
    for s in out:
        if s.name == SEMICONDUCTOR:
            s.text_eligible, s.rank = True, s.rank or "fixed"
    return out


def concentration_text(s: Sector) -> str | None:
    if not s.concentrated or not s.top_name or s.top_weight is None:
        return None
    return f"主要由{s.top_name}構成（約 {int((s.top_weight * 100).to_integral_value())}%）"


# -- multi-period returns --------------------------------------------------------------------------------------------
def period_return(points: list[IndexPoint], end: date, base_before: date) -> Decimal | None:
    """Close on ``end`` against the last close before ``base_before``; ``None`` when the archive does not reach back."""
    last = next((p for p in reversed(points) if p.day <= end), None)
    base = next((p for p in reversed(points) if p.day < base_before), None)
    if last is None or base is None or not base.close:
        return None
    return (last.close - base.close) / base.close


def since_start_return(points: list[IndexPoint], end: date) -> tuple[Decimal | None, date | None]:
    """From the first archived close to ``end`` (the 「11/12 起」 column)."""
    pts = [p for p in points if p.day <= end]
    if len(pts) < 2:
        return None, pts[0].day if pts else None
    return (pts[-1].close - pts[0].close) / pts[0].close, pts[0].day


def month_back(d: date) -> date:
    """The same day a month earlier (the last day of that month when it is shorter)."""
    y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


# -- TPEx ------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class OtcSector:
    code: str
    name: str
    pct: Decimal
    members: int


def otc_sectors(day: Day) -> list[OtcSector]:
    """TPEx commons grouped by industry code, market-cap weighted moves (Forliosa's own; no official index). Two or
    fewer members are left out."""
    groups: dict[str, list[Quote]] = defaultdict(list)
    for q in day.commons():
        if q.industry_code and q.mcap_prev is not None and q.pct is not None:
            groups[q.industry_code].append(q)
    out = []
    for code, qs in groups.items():
        if len(qs) <= 2:
            continue
        weight = sum((q.mcap_prev for q in qs), Decimal(0))
        if not weight:
            continue
        pct = sum((q.mcap_prev * q.pct for q in qs), Decimal(0)) / weight
        out.append(OtcSector(code, INDUSTRY_CODES.get(code, code), pct, len(qs)))
    out.sort(key=lambda s: (-s.pct, s.code))
    return out


@dataclass(frozen=True)
class FlowAmount:
    symbol: str
    name: str
    amount: Decimal  # NT$ estimate: net shares × close


def otc_institutional(db: Session, day: Day, cutoff: datetime) -> tuple[dict[str, Decimal], list[FlowAmount]] | None:
    """TPEx three institutional investors on ``day``: estimated amounts (net shares × close; never a cross-stock sum
    of shares). Returns ({"foreign", "trust", "dealer", "total"}: NT$, per-stock totals) or ``None``."""
    if not usable("tpex-openapi/institutional", day.day, cutoff):
        return None
    rows = list(db.scalars(select(InstitutionalDaily).where(InstitutionalDaily.date == day.day,
                                                            InstitutionalDaily.source == "tpex-openapi")))
    if not rows:
        return None
    sums = {"foreign": Decimal(0), "trust": Decimal(0), "dealer": Decimal(0), "total": Decimal(0)}
    per: list[FlowAmount] = []
    for r in rows:
        q = day.quotes.get(r.symbol)
        if q is None:
            continue
        for k, v in (("foreign", r.foreign_net), ("trust", r.trust_net), ("dealer", r.dealer_net),
                     ("total", r.total_net)):
            sums[k] += Decimal(v or 0) * q.close
        per.append(FlowAmount(r.symbol, q.name, Decimal(r.total_net or 0) * q.close))
    return sums, per


# -- TAIFEX, FX, US ----------------------------------------------------------------------------------------------
FOREIGN = "外資及陸資"
INVESTORS = ("外資及陸資", "投信", "自營商")


def futures_oi_series(db: Session, upto: date, cutoff: datetime, investor: str = FOREIGN,
                      limit: int = 21) -> list[tuple[date, int]]:
    """TAIEX futures (TX) net open interest of ``investor`` (contracts), oldest first, usable at ``cutoff``."""
    rows = db.execute(select(TaifexInstitutional.trade_date, TaifexInstitutional.oi_net).where(
        TaifexInstitutional.scope == "futures", TaifexInstitutional.investor == investor,
        (TaifexInstitutional.contract_code == "TX") | (TaifexInstitutional.contract_name == "臺股期貨"),
        TaifexInstitutional.trade_date <= upto).order_by(TaifexInstitutional.trade_date.desc()).limit(limit * 2)).all()
    seen: dict[date, int] = {}
    for d, oi in rows:
        if oi is not None and d not in seen and usable("taifex-openapi/institutional_futures", d, cutoff):
            seen[d] = int(oi)
    return sorted(seen.items())[-limit:]


def put_call(db: Session, upto: date, cutoff: datetime) -> TaifexPutCallRatio | None:
    for r in db.scalars(select(TaifexPutCallRatio).where(TaifexPutCallRatio.trade_date <= upto)
                        .order_by(TaifexPutCallRatio.trade_date.desc()).limit(5)):
        if usable("taifex-openapi/put_call_ratio", r.trade_date, cutoff):
            return r
    return None


def usd_twd(db: Session, upto: date, cutoff: datetime, limit: int = 10) -> list[tuple[date, Decimal]]:
    """The central bank's USD/TWD closes (never TAIFEX's conditional rates), oldest first."""
    rows = db.execute(select(FxRate.date, FxRate.rate).where(
        FxRate.pair == "USDTWD", FxRate.source == "cbc-opendata", FxRate.date <= upto)
        .order_by(FxRate.date.desc()).limit(limit)).all()
    return sorted((d, r) for d, r in rows if usable("cbc-opendata/fx", d, cutoff))


@dataclass(frozen=True)
class UsMove:
    symbol: str
    session: date
    close: Decimal
    prev_session: date | None
    prev_close: Decimal | None

    @property
    def pct(self) -> Decimal | None:
        return (self.close - self.prev_close) / self.prev_close if self.prev_close else None


def us_closes(db: Session, symbol: str, upto: date, cutoff: datetime, limit: int = 30) -> list[tuple[date, Decimal]]:
    rows = db.execute(select(PriceDaily.date, PriceDaily.close).where(
        PriceDaily.symbol == symbol, PriceDaily.source == US_SOURCE, PriceDaily.date <= upto)
        .order_by(PriceDaily.date.desc()).limit(limit)).all()
    return sorted((d, c) for d, c in rows if usable(f"{US_SOURCE}/price", d, cutoff))


def us_move(db: Session, symbol: str, session: date, cutoff: datetime, since: date | None = None) -> UsMove | None:
    """``symbol``'s close of US ``session`` against the previous stored close (or the last close before ``since``)."""
    closes = us_closes(db, symbol, session, cutoff)
    if not closes or closes[-1][0] != session:
        return None
    before = [x for x in closes if x[0] < (since or session)]
    prev = before[-1] if before else None
    return UsMove(symbol, session, closes[-1][1], prev[0] if prev else None, prev[1] if prev else None)


def as_float(x: Any, nd: int = 6) -> float | None:
    return None if x is None else round(float(x), nd)
