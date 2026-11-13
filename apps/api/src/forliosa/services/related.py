"""「相關股票」 (product owner 2026-11-12, decision 4; rules in docs/research/news-and-external-sources.md §8).

Up to four cards, chosen by rules from government open data only (no AI, no other users' behaviour):

* **ETF／基準** — an OTC stock that is a 富櫃五十 constituent (TPEx ``tpex50_constituents``) → 006201 「富櫃五十成分股
  （櫃買中心公布）」; any other stock → the user's comparison benchmark (「你的比較基準」; an index such as ^TAIEXTR is
  shown as an index card, or left out when there is no archived level). The card never says that an ETF *holds*
  the stock: 臺灣50's constituent list belongs to TWSE / FTSE and may not be republished without consent.
* **關係企業** — TWSE ``t187ap11_L`` / TPEx ``mopsfin_t187ap11_O`` (董監事持股餘額明細): a listed company that is a
  法人董事 or 大股東 of this one, or the other way round (``board_links``; each dataset's own latest month, since
  TWSE and TPEx publish on different days; largest first).
* **同業** — same 產業別 (t187ap03), closest market cap (shares × latest archived close); the industry's largest
  company first when it is not this one. 其他業 (20) and 其他電子業 (31) are too broad: 31 uses the electronics
  industries (24–31) by market cap, 20 the user's own holdings. 存託憑證 (91) never appears.
* **ETF pages** — ETFs tracking the same index with the same fund type (t187ap47_L), then the same type with the
  most holders (TDCC 2-22 / 2-23 集保股東戶數, each market's latest month).

Each card: symbol, name, reason, ``reason_label``, the latest close and change, and ``sparkline`` (archived closes of
about a month). A candidate without a card (an index without archived levels, a company without archived closes) is
skipped and the next candidate takes its place. The frontend hides the row when fewer than two cards come back.
"""

from __future__ import annotations

import html
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.datapolicy import labels, source_clause, tagged
from forliosa.marketdata.base import InstrumentInfo, market_of_symbol
from forliosa.marketdata.indices import INDICES
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    BoardLink,
    CompanyProfile,
    FundProfile,
    HolderCountMonthly,
    IndexConstituent,
    PriceDaily,
    User,
)
from forliosa.services.instruments import change_base, require_instrument
from forliosa.timeutil import today_taipei

MAX_CARDS = 4
SPARK_DAYS = 35  # calendar days of closes (about a month of sessions)
TPEX50_ETF = "006201.TWO"
MISC_INDUSTRIES = ("20", "31")
ELECTRONICS = ("24", "25", "26", "27", "28", "29", "30", "31")
DEPOSITARY_RECEIPTS = "91"


@dataclass
class Candidate:
    symbol: str
    reason: str  # benchmark | constituent | affiliate | peer | leader | same_index | same_type | holding
    reason_label: str
    sources: list[str] = field(default_factory=list)
    is_index: bool = False
    name: str | None = None  # the official short name (company profile / fund profile) when known
    period: str | None = None  # affiliates: 資料年月 of the board_links row


@dataclass
class Company:
    symbol: str
    short_name: str
    industry_code: str | None
    industry: str | None
    shares: int | None
    source: str
    cap: Decimal | None = None


def _companies(db: Session, md: MarketData) -> dict[str, Company]:
    rows = db.scalars(select(CompanyProfile).where(source_clause(CompanyProfile.source, md.policy)))
    return {r.symbol: Company(r.symbol, str((r.values or {}).get("short_name") or r.symbol.split(".")[0]),
                              r.industry_code, r.industry, r.shares_outstanding, r.source) for r in rows}


def _with_caps(db: Session, md: MarketData, companies: Iterable[Company]) -> None:
    """Market cap = issued shares × the latest archived close (one query for the whole pool)."""
    pool = {c.symbol: c for c in companies if c.shares}
    if not pool:
        return
    clause = source_clause(PriceDaily.source, md.policy)
    latest = db.scalar(select(func.max(PriceDaily.date)).where(PriceDaily.symbol.in_(pool), clause))
    if latest is None:
        return
    closes: dict[str, Decimal] = {}
    for sym, close in db.execute(select(PriceDaily.symbol, PriceDaily.close).where(
            PriceDaily.symbol.in_(pool), PriceDaily.date >= latest - timedelta(days=14), clause)
            .order_by(PriceDaily.date)):
        closes[sym] = close
    for sym, c in pool.items():
        if sym in closes and c.shares:
            c.cap = Decimal(c.shares) * closes[sym]


def _distance(a: Decimal | None, b: Decimal | None) -> float:
    if not a or not b or a <= 0 or b <= 0:
        return math.inf
    return abs(math.log(float(a)) - math.log(float(b)))


def _roles_phrase(roles: str) -> str:
    director = "董事" in roles
    major = "大股東" in roles
    return "法人董事及大股東" if director and major else ("法人董事" if director else "大股東")


# -- benchmark / constituent -----------------------------------------------------------------------------------
def _benchmark(db: Session, md: MarketData, user: User, info: InstrumentInfo) -> Candidate | None:
    if info.market == "TPEX":
        latest = db.scalar(select(func.max(IndexConstituent.date)).where(
            IndexConstituent.index_code == "TPEX50", source_clause(IndexConstituent.source, md.policy)))
        if latest is not None and db.get(IndexConstituent, ("TPEX50", latest, info.symbol)) is not None:
            return Candidate(TPEX50_ETF, "constituent", "富櫃五十成分股（櫃買中心公布）", ["tpex-openapi/tpex50"],
                             name="元大富櫃50")
    from forliosa.services.ledger_io import preferences_of

    bench = md.resolve_benchmark(str(preferences_of(user).get("benchmark") or ""))
    if bench is None or bench == info.symbol:
        return None
    if bench in INDICES:
        return Candidate(bench, "benchmark", "你的比較基準（指數）", [INDICES[bench].source_key], is_index=True)
    return Candidate(bench, "benchmark", "你的比較基準")


# -- affiliates (board_links) ----------------------------------------------------------------------------------
def _affiliates(db: Session, md: MarketData, info: InstrumentInfo, companies: dict[str, Company],
                self_name: str) -> list[Candidate]:
    """Links of the latest month **of each dataset** (t187ap11_L and mopsfin_t187ap11_O are published on different
    days: one month-wide maximum would drop the other market's links until it catches up)."""
    clause = source_clause(BoardLink.source, md.policy)
    latest = list(db.execute(select(BoardLink.source, func.max(BoardLink.period)).where(clause)
                             .group_by(BoardLink.source)))
    if not latest:
        return []
    rows = list(db.scalars(select(BoardLink).where(
        clause, or_(*(and_(BoardLink.source == src, BoardLink.period == period) for src, period in latest)),
        (BoardLink.symbol == info.symbol) | (BoardLink.holder_symbol == info.symbol))))
    found: dict[str, Candidate] = {}
    for r in rows:
        if r.holder_symbol == info.symbol:  # this company sits on the other one's board / holds > 10 %
            other, label = r.symbol, f"{self_name}是其{_roles_phrase(r.roles)}"
        else:  # the other company sits on this one's board / holds > 10 %
            other, label = r.holder_symbol, f"{self_name}的{_roles_phrase(r.roles)}"
        comp = companies.get(other)
        if comp is None or comp.industry_code == DEPOSITARY_RECEIPTS or other == info.symbol:
            continue
        found.setdefault(other, Candidate(other, "affiliate", label, [f"{r.source}/board"], name=comp.short_name,
                                          period=r.period))
    return sorted(found.values(), key=lambda c: -(companies[c.symbol].cap or 0))


# -- peers -----------------------------------------------------------------------------------------------------
def _held_stocks(db: Session, md: MarketData, user: User) -> set[str]:
    from forliosa.services.portfolio import ledger_view

    try:
        ledger = ledger_view(db, user, md).ledger
    except Exception:  # an inconsistent ledger must not break the stock page
        return set()
    return {p.symbol for p in ledger.open_positions() if market_of_symbol(p.symbol) != "US"}


def _peers(db: Session, md: MarketData, user: User, info: InstrumentInfo, me: Company,
           companies: dict[str, Company]) -> list[Candidate]:
    code = me.industry_code
    if not code or code == DEPOSITARY_RECEIPTS:
        return []
    src = [f"{me.source}/company"]
    if code == "20":
        held = _held_stocks(db, md, user)
        pool = [c for s, c in companies.items() if s in held and s != me.symbol and c.industry_code != "91"]
        pool.sort(key=lambda c: _distance(c.cap, me.cap))
        return [Candidate(c.symbol, "holding", "你的持股、市值相近", src, name=c.short_name) for c in pool]
    if code == "31":
        pool = [c for c in companies.values() if c.industry_code in ELECTRONICS and c.symbol != me.symbol]
        pool.sort(key=lambda c: _distance(c.cap, me.cap))
        return [Candidate(c.symbol, "peer", "電子類、市值相近", src, name=c.short_name) for c in pool]
    pool = [c for c in companies.values() if c.industry_code == code and c.symbol != me.symbol]
    if not pool:
        return []
    out: list[Candidate] = []
    industry = me.industry or "同產業"
    everyone = [*pool, me]
    leader = max(everyone, key=lambda c: c.cap or 0)
    if leader.symbol != me.symbol and leader.cap:
        out.append(Candidate(leader.symbol, "leader", f"{industry}市值最大", src, name=leader.short_name))
    rest = sorted((c for c in pool if c.symbol != leader.symbol or not leader.cap),
                  key=lambda c: (_distance(c.cap, me.cap), -(c.cap or 0)))
    out += [Candidate(c.symbol, "peer", f"同為{industry}", src, name=c.short_name) for c in rest]
    return out


# -- ETF pages -------------------------------------------------------------------------------------------------
def _fund_kind(fund_type: str | None) -> str:
    t = fund_type or ""
    for needle, label in (("槓桿", "槓桿／反向型"), ("期貨", "期貨型"), ("債", "債券型"), ("主動", "主動式"),
                          ("國外", "海外股票型"), ("國內", "國內股票型")):
        if needle in t:
            return label
    return "同類型"


def _latest_holders(db: Session, md: MarketData, symbols: list[str]) -> dict[str, int]:
    """集保股東戶數 of ``symbols`` from the latest month of their own market's dataset (2-22 上市 / 2-23 上櫃 come
    out on different days: a month taken over both would leave one market without counts)."""
    if not symbols:
        return {}
    clause = source_clause(HolderCountMonthly.source, md.policy)
    rows = list(db.execute(select(HolderCountMonthly.symbol, HolderCountMonthly.period, HolderCountMonthly.holders)
                           .where(clause, HolderCountMonthly.symbol.in_(symbols))))
    latest: dict[str, str] = {}
    for sym, period, _ in rows:
        market = market_of_symbol(sym)
        latest[market] = max(latest.get(market, period), period)
    return {sym: n for sym, period, n in rows if period == latest[market_of_symbol(sym)]}


def _etf_candidates(db: Session, md: MarketData, info: InstrumentInfo) -> list[Candidate]:
    funds = {f.symbol: (f.values or {}) for f in db.scalars(select(FundProfile).where(
        source_clause(FundProfile.source, md.policy)))}
    me = funds.get(info.symbol)
    if me is None:
        return []
    index = (me.get("index_name") or "").strip()
    kind = me.get("fund_type")
    same_type = [s for s, v in funds.items() if s != info.symbol and v.get("fund_type") == kind]
    holders = _latest_holders(db, md, same_type)
    by_holders = sorted(same_type, key=lambda s: -(holders.get(s) or 0))
    src = ["twse-openapi/fund"]
    out = [Candidate(s, "same_index", "追蹤同一指數", src, name=funds[s].get("short_name")) for s in by_holders
           if index and index != "不適用" and (funds[s].get("index_name") or "").strip() == index]
    chosen = {c.symbol for c in out}
    hsrc = [*src, "tdcc-opendata/holders_twse"] if holders else src  # t187ap47_L lists TWSE ETFs only
    out += [Candidate(s, "same_type", f"同為{_fund_kind(kind)}、受益人數多", hsrc, name=funds[s].get("short_name"))
            for s in by_holders if s not in chosen and holders.get(s)]
    return out


# -- cards -----------------------------------------------------------------------------------------------------
def _card(md: MarketData, c: Candidate, quotes: dict, today: date) -> tuple[dict[str, Any], str] | None:
    """The card and the key of its price source (an index dataset key, or the history's provider keys)."""
    start = today - timedelta(days=SPARK_DAYS)
    if c.is_index:
        idx = INDICES[c.symbol]
        h = md.index_history(c.symbol, start, today)
        if not h.candles:
            return None
        last, prev = h.candles[-1], (h.candles[-2] if len(h.candles) > 1 else None)
        change = (last.c - prev.c) / prev.c if prev and prev.c else None
        return {"symbol": c.symbol, "name": idx.name, "reason": c.reason, "reason_label": c.reason_label,
                "close": ser.price(last.c), "change_pct": ser.ratio(change), "as_of": last.t,
                "sparkline": [{"t": x.t, "price": ser.price(x.c)} for x in h.candles], "is_index": True,
                "notes": ["指數不能直接買賣"], "is_demo": h.is_demo}, idx.source_key
    info = md.instrument(c.symbol)
    name = c.name or (info.name if info else None)
    if name is None:
        return None
    h = md.history(c.symbol, start, today)
    q = quotes.get(c.symbol)
    base = change_base(q) if q else None
    price = q.price if q and q.price is not None else (h.candles[-1].c if h.candles else None)
    change = (price - base) / base if price is not None and base else None
    if price is None and not h.candles:
        return None
    return {"symbol": c.symbol, "name": name, "reason": c.reason, "reason_label": c.reason_label,
            "close": ser.price(price), "change_pct": ser.ratio(change),
            "as_of": (q.trade_date if q and q.trade_date else (h.candles[-1].t if h.candles else None)),
            "sparkline": [{"t": x.t, "price": ser.price(x.c)} for x in h.candles], "is_index": False,
            "notes": [], "is_demo": h.is_demo or bool(q and q.is_demo)}, h.source


def related(db: Session, md: MarketData, user: User, symbol: str) -> dict[str, Any]:
    info = require_instrument(md, symbol)
    sym = info.symbol
    out: dict[str, Any] = {"symbol": sym, "items": [], "sources": [], "notes": []}
    if info.market == "US":
        out["notes"].append("美股沒有相關股票資料")
        return out
    today = today_taipei()
    built: dict[str, tuple[dict[str, Any], str] | None] = {}

    def card_of(c: Candidate) -> tuple[dict[str, Any], str] | None:
        """The candidate's card, or ``None`` when it has nothing to show (built once, quoted one by one: the peer
        pool can be a whole industry, and usually only the first few are needed)."""
        if c.symbol not in built:
            quotes = {} if c.is_index else md.quotes([c.symbol])
            built[c.symbol] = _card(md, c, quotes, today)
        return built[c.symbol]

    picked: list[Candidate] = []

    def take(items: Iterable[Candidate], n: int) -> None:
        """Up to ``n`` more cards from ``items`` in order; a candidate without a card is skipped (the next one
        takes its place), so a missing index level or a company without closes does not shrink the row."""
        for c in items:
            if len(picked) >= MAX_CARDS or n <= 0:
                return
            if c.symbol != sym and all(c.symbol != p.symbol for p in picked) and card_of(c) is not None:
                picked.append(c)
                n -= 1

    notes: list[str] = []
    if info.type == "etf":
        take(_etf_candidates(db, md, info), MAX_CARDS)
    else:
        companies = _companies(db, md)
        me = companies.get(sym)
        _with_caps(db, md, companies.values())
        bench = _benchmark(db, md, user, info)
        affiliates = _affiliates(db, md, info, companies, me.short_name if me else info.name) if me else []
        peers = _peers(db, md, user, info, me, companies) if me else []
        misc = bool(me and me.industry_code in MISC_INDUSTRIES)
        # the benchmark card goes first, then the affiliates, then the peers (as picked)
        if bench:
            take([bench], 1)
        take(affiliates, 2 if misc else 1)
        take(peers, MAX_CARDS)
        take(affiliates, MAX_CARDS)
        periods = sorted({c.period for c in picked if c.reason == "affiliate" and c.period})
        if periods:
            months = "、".join(f"{p[:4]} 年 {int(p[5:])} 月" for p in periods)
            notes.append(f"關係企業依董監事持股餘額明細（{months}）")
    sources: list[str] = []
    for c in picked:
        card, price_source = card_of(c)  # type: ignore[misc]  # picked only holds candidates with a card
        out["items"].append(card)
        sources += [*c.sources, *([price_source] if c.is_index else tagged(price_source, "price"))]
    out["sources"] = labels(sources)
    out["notes"] = notes
    for card in out["items"]:
        card["name"] = html.unescape(card["name"])
    return out
