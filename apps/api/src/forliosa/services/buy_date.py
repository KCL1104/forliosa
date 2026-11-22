"""Daily prices as traded, and the estimated buy dates of 匯入庫存 (資產組成原型,
``docs/proposals/asset-composition.md``).

The prices a broker's average cost can be compared with (:func:`traded_history`): the archive's official closes and,
before a symbol's first official close, the history backfill's rows (``yahoo-history``, PRICE_HISTORY_SOURCE=yahoo)
converted back to the prices as traded — the known splits and capital reductions multiplied back where Yahoo folded
them in, exactly as the ledger's valuation before the archive does (``services.reference_close.valuation_prices``).
US stocks: Databento's closes, unadjusted already, from 2024-07-01.

Uses of the backfill here — the estimate (:func:`estimate_rows`) and the chart the user picks a buy date on
(``GET /instruments/{symbol}/history?prices=as_traded``) — are the proposal's owner decision 1 (pending): one more use
than PRODUCT.md allows today. Switched off or dropped, only the archive's own days are searched, and the message of a
holding that found no crossing says from which day the prices were searched.

The share-count limit (:func:`share_changes`): a broker's quantity and average cost are as of the import day, so they
already include every split, capital reduction and stock dividend (配股) before it. An imported buy dated before the
latest of them would be counted in today's shares at the old prices — and the ledger would book that stock dividend
(``services.auto_dividends``) a second time. So the earliest day an imported buy may have is the latest share-count
change on or before its import day (the ex-date itself is allowed: its prices are already after the change); the
estimate stops there, the commit and ``PATCH`` refuse earlier days, the picker's chart starts there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from sqlalchemy.orm import Session

from forliosa.domain.buy_date import US_HISTORY_FROM, estimate_buy_date, search_start
from forliosa.marketdata.base import Candle, market_of_symbol
from forliosa.marketdata.catalog import KNOWN_REDUCTIONS
from forliosa.marketdata.service import MarketData
from forliosa.services import auto_dividends
from forliosa.services.coverage import COVERAGE_GRACE_DAYS
from forliosa.services.reference_close import valuation_prices

NO_CROSSING = "no_crossing"
BEFORE_SHARE_CHANGE = "before_share_change"  # 422 / row error: an imported buy dated before the share-count limit
BAD_ESTIMATED_DATE = "bad_estimated_date"  # row error: an estimate the estimator could not have found
BEFORE_EARLIER_RECORDS = "before_earlier_records"  # row error: an estimated buy before the account's last record of it

ShareChangeReason = Literal["split", "reduction", "stock_dividend"]
# how a reason is written (the picker's line, the no_crossing sentence, the 422 message)
REASON_TEXT: dict[str, str] = {"split": "股票分割", "reduction": "減資", "stock_dividend": "配股"}


@dataclass(frozen=True)
class ShareChange:
    """The latest change of a stock's share count on or before a day: a split, a capital reduction or a stock
    dividend (配股) with a stock component. Days before ``date`` cannot be an imported buy's."""

    date: date
    reason: ShareChangeReason

    @property
    def text(self) -> str:
        return REASON_TEXT[self.reason]

    def out(self) -> dict[str, Any]:
        return {"date": self.date, "reason": self.reason}


@auto_dividends.shared_events
def share_changes(md: MarketData, symbols: Sequence[str], until: date) -> dict[str, ShareChange]:
    """symbol -> its latest share-count change on or before ``until`` (none: not in the answer). The same sources the
    ledger books them from: ``MarketData.corporate_events`` (the catalogue's known splits and capital reductions, the
    archive's US splits) and ``auto_dividends.ex_dividend_events`` (the archived ex-dividend notices; a stock dividend
    is one whose stock component is above 0). Notices that cannot be read are no limit (as the booking, which then
    leaves the rows alone). On the same day a split or reduction is named before a stock dividend."""
    syms = list(dict.fromkeys(symbols))
    if not syms:
        return {}
    out: dict[str, ShareChange] = {}

    def offer(s: str, change: ShareChange) -> None:
        cur = out.get(s)
        if cur is None or change.date > cur.date:
            out[s] = change

    for s, evs in md.corporate_events_many(syms).items():
        for e in evs:
            if e.kind in ("split", "capital_reduction") and e.ratio and e.date <= until:
                reduction = e.kind == "capital_reduction" or (s, e.date) in KNOWN_REDUCTIONS
                offer(s, ShareChange(e.date, "reduction" if reduction else "split"))
    auto_dividends.prefetch_events(md, syms)  # one read of every Taiwan stock's notices
    for s in syms:
        for n in auto_dividends.ex_dividend_events(md, s) or []:
            ex = n.ex_dividend_date
            if ex is not None and ex <= until and n.stock_dividend > 0:
                offer(s, ShareChange(ex, "stock_dividend"))
    return out


def ymd_text(d: date) -> str:
    """2025/6/18 (no leading zeros, as the import's and the picker's sentences write a day)."""
    return f"{d.year}/{d.month}/{d.day}"


def before_change_message(change: ShareChange) -> str:
    """The 422 / row error of an imported buy dated before ``change``:
    「2025/6/18 股票分割，買進日期不能早於這一天」."""
    return f"{ymd_text(change.date)} {change.text}，買進日期不能早於這一天"


def before_change_label(change: ShareChange) -> str:
    """The import row's ``before_share_change`` flag (a label, 2026-11-22): 「2025/6/18 股票分割・買入日不能更早」."""
    return f"{ymd_text(change.date)} {change.text}・買入日不能更早"


@dataclass
class TradedHistory:
    """One symbol's daily bars as traded (oldest first), and the last day taken from the history backfill (``None``:
    every bar is official)."""

    candles: list[Candle]
    reference_until: date | None
    official_source: str  # the archive's source keys of the official bars (``twse-openapi`` …)
    is_demo: bool = False


def traded_history(db: Session, md: MarketData, symbols: Sequence[str], start: date, end: date
                   ) -> dict[str, TradedHistory]:
    """Every symbol's bars from ``start`` to ``end`` as traded: one archive read for all of them and one more for the
    history backfill's rows (none when it is off, or the archive covers ``start``)."""
    syms = list(dict.fromkeys(symbols))
    histories = md.histories(syms, start, end)
    refs = valuation_prices(db, md, histories, start, start)
    out: dict[str, TradedHistory] = {}
    for s in syms:
        h = histories[s]
        ref = refs.reference.get(s, [])
        cut = refs.cutoff.get(s)
        early = [c for c in ref if cut is not None and c.t < cut]
        late = [c for c in h.candles if cut is None or c.t >= cut]
        out[s] = TradedHistory([*early, *late], early[-1].t if early else None, h.source, h.is_demo)
    return out


def cost_text(cost: Decimal, currency: str) -> str:
    """The cost as people write it (at most four decimals): 1,030.25, US$512.3."""
    d = cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize()
    text = f"{d:,f}"
    return f"US${text}" if currency == "USD" else text


_ymd = ymd_text


def no_crossing_message(cost: Decimal, currency: str, us: bool, first: date | None, start: date,
                        change: ShareChange | None = None) -> str:
    """Why there is no estimate (appendix B's reasons; short labels since 2026-11-22). The searched prices began
    later than the search's start (a stock listed later, a symbol the backfill has no rows of, the backfill switched
    off): that day is named instead of 「五年內」; the search stopped at a share-count change (``change``: a split, a
    capital reduction, a stock dividend): said so."""
    shown = cost_text(cost, currency)
    if first is None:
        return "沒有股價・估不到買入日"
    if change is not None and first >= change.date:
        return f"{_ymd(change.date)} {change.text}以後沒有經過均價 {shown}・估不到買入日"
    if (first - start).days > COVERAGE_GRACE_DAYS + 4:  # a weekend and a holiday after the start are no gap
        return f"{_ymd(first)} 以後沒有經過均價 {shown}・估不到買入日"
    if us:
        return f"{_ymd(US_HISTORY_FROM)} 以後沒有經過均價 {shown}・估不到買入日"
    return f"五年內沒有經過均價 {shown}・估不到買入日"


@dataclass(frozen=True)
class Estimate:
    estimated_date: date | None
    message: str | None  # the ``no_crossing`` warning when there is no estimate
    skipped: bool = False  # not estimated at all: the prices are demo data (personal mode)


def search_floor(symbol: str, until: date, change: ShareChange | None) -> date:
    """The first day the estimate of a ``symbol`` bought by ``until`` may take: five years back (a US stock: from
    2024-07-01), and never before the share-count limit ``change``."""
    lo = search_start(until, market_of_symbol(symbol) == "US")
    return max(lo, change.date) if change is not None else lo


def estimate_rows(db: Session, md: MarketData, rows: Sequence[tuple[str, Decimal, str]], today: date,
                  floors: Mapping[str, date] | None = None) -> list[Estimate]:
    """The estimated buy date of each ``(symbol, cost, currency)``, looking back from ``today`` (Taipei): one read of
    every symbol's prices together (:func:`traded_history`).

    The search stops at the symbol's share-count limit (:func:`share_changes`; deviation from the proposal's rule,
    appendix B): a broker restates the average cost of shares held through a split, reduction or stock dividend in
    today's shares (0050 bought at 188 before its 2025 1-to-4 split shows 47), so the prices as traded before it
    cannot be compared — and their drop on that day would otherwise read as a gap «over» every cost between the old
    and the new price. A buy dated before it would also be valued with today's share count at the old prices, and a
    stock dividend booked again.

    ``floors``: the earliest day per symbol on top of that (``positions_import.record_floors``: the day after the
    account's last record of a stock it no longer holds)."""
    if not rows:
        return []
    start = search_start(today, us=False)
    symbols = [s for s, _, _ in rows]
    hist = traded_history(db, md, symbols, start, today)
    changes = share_changes(md, symbols, today)
    out: list[Estimate] = []
    for symbol, cost, currency in rows:
        if hist[symbol].is_demo:  # synthetic prices (personal mode's demo data) date nothing: no estimate at all
            out.append(Estimate(None, None, skipped=True))
            continue
        us = market_of_symbol(symbol) == "US"
        change = changes.get(symbol)
        lo = search_floor(symbol, today, change)
        if floors and symbol in floors:
            lo = max(lo, floors[symbol])
        stopped = change if change is not None and change.date >= search_start(today, us) else None
        day = estimate_buy_date(hist[symbol].candles, cost, today, start=lo)
        if day is not None:
            out.append(Estimate(day, None))
        else:
            bars = [c for c in hist[symbol].candles if lo <= c.t <= today]
            first = bars[0].t if bars else None
            out.append(Estimate(None, no_crossing_message(cost, currency, us, first, lo, stopped)))
    return out
