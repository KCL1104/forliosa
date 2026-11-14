"""Market data from our own archive (``prices_daily``, ``valuation_daily``, ``reference_prices`` …).

The archive is filled by ``forliosa.archive`` from official open data (and, under the personal policy,
by backfills from FinMind and the TWSE website). Rows keep their original ``source``; under
``DATA_POLICY=commercial`` rows from non-commercial sources are ignored.

History from the archive is usually *partial* (it only grows from the day archiving started), so the
facade keeps asking the next real provider for the days the archive does not have.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.datapolicy import DATASETS, Policy, attribution, dataset_served, source_clause
from forliosa.marketdata import cbc
from forliosa.marketdata.base import (
    BaseProvider,
    Candle,
    DividendEvent,
    InstrumentInfo,
    InstrumentProfile,
    QuoteData,
    market_of_symbol,
    tw_symbol,
)
from forliosa.marketdata.indices import index_by_data_id
from forliosa.timeutil import market_close_dt, today_taipei

# A listing nobody has named for this long (newest row minus this) is taken as delisted and leaves the instrument list.
LISTING_DAYS = 365
# SEC tickers as company_tickers.json spells them (BRK-B): a letter first, so never a Taiwan code.
_US_TICKER = re.compile(r"^[A-Z][A-Z0-9-]{0,9}$")


def _default_session() -> Session:
    from forliosa.db import session_factory

    return session_factory()()


class ArchiveProvider(BaseProvider):
    name = "archive"
    is_demo = False
    partial_history = True
    cooldown_seconds = 30

    def __init__(self, policy: Policy = "commercial", session_fn: Callable[[], Session] = _default_session,
                 taifex_confirmed: bool | None = None):
        self.policy = policy
        self.session_fn = session_fn
        # TAIFEX_CONDITIONAL_CONFIRMED (None: read the setting at call time) for ``served`` (conditional datasets).
        self.taifex_confirmed = taifex_confirmed
        # (method, symbol) -> source keys of the rows the last answer used (twse-openapi, finmind …),
        # so responses can list the real sources instead of "archive".
        self._last_sources: dict[tuple[str, str], list[str]] = {}

    def sources_for(self, method: str, symbol: str) -> list[str]:
        return self._last_sources.get((method, symbol), [])

    def _remember(self, method: str, symbol: str, rows: list[Any]) -> None:
        self._last_sources[(method, symbol)] = sorted({r.source for r in rows})

    def _filter(self, stmt, model, backfill: bool = False):
        return stmt.where(source_clause(model.source, self.policy, backfill))

    def served(self, key: str) -> bool:
        return dataset_served(key, self.policy, self.taifex_confirmed)

    def first_date(self, symbol: str | None = None, backfill: bool = False) -> date | None:
        """Earliest archived close (of ``symbol`` or of any symbol): where the archive's history begins.
        ``backfill=True`` counts the history backfill's days too (charts)."""
        from forliosa.models import PriceDaily

        with self.session_fn() as db:
            stmt = select(func.min(PriceDaily.date))
            if symbol:
                stmt = stmt.where(PriceDaily.symbol == symbol)
            return db.scalar(self._filter(stmt, PriceDaily, backfill))

    def backfill_until(self, symbol: str) -> date | None:
        """The last day of ``symbol`` that comes from the history backfill (``None``: none is used)."""
        from forliosa.datapolicy import HISTORY_SOURCE, history_backfill_enabled
        from forliosa.models import PriceDaily

        if not history_backfill_enabled():
            return None
        with self.session_fn() as db:
            return db.scalar(select(func.max(PriceDaily.date)).where(PriceDaily.symbol == symbol,
                                                                     PriceDaily.source == HISTORY_SOURCE))

    # -- prices ------------------------------------------------------------------------------------
    # ``backfill``: chart-like callers may also read the history backfill's days (split-adjusted, not official);
    # everything that values a ledger leaves it off.
    accepts_backfill = True

    def history(self, symbol: str, start: date, end: date, backfill: bool = False) -> list[Candle] | None:
        from forliosa.models import PriceDaily

        if market_of_symbol(symbol) == "US":
            return None
        with self.session_fn() as db:
            stmt = select(PriceDaily).where(PriceDaily.symbol == symbol, PriceDaily.date >= start,
                                            PriceDaily.date <= end).order_by(PriceDaily.date)
            rows = list(db.scalars(self._filter(stmt, PriceDaily, backfill)))
        self._remember("history", symbol, rows)
        out = []
        for r in rows:
            c = r.close
            out.append(Candle(r.date, r.open or c, r.high or c, r.low or c, c, r.volume or 0))
        return out or None

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        from forliosa.models import PriceDaily

        tw = [s for s in symbols if market_of_symbol(s) != "US"]
        if not tw:
            return {}
        since = today_taipei() - timedelta(days=21)
        with self.session_fn() as db:
            stmt = select(PriceDaily).where(PriceDaily.symbol.in_(tw), PriceDaily.date >= since)
            rows = list(db.scalars(self._filter(stmt, PriceDaily).order_by(PriceDaily.symbol, PriceDaily.date.desc())))
        by_sym: dict[str, list[Any]] = defaultdict(list)
        for r in rows:
            by_sym[r.symbol].append(r)
        out = {}
        for s, rs in by_sym.items():
            last = rs[0]
            prev = rs[1].close if len(rs) > 1 else None
            out[s] = QuoteData(symbol=s, price=last.close, prev_close=prev, open=last.open, high=last.high,
                               low=last.low, volume=last.volume, as_of=market_close_dt(last.date),
                               trade_date=last.date, source=last.source)
        return out

    def latest_close(self, symbol: str) -> tuple[date, Decimal] | None:
        q = (self.quotes([symbol]) or {}).get(symbol)
        return (q.trade_date, q.price) if q and q.trade_date and q.price is not None else None

    def valuation_ratios(self, symbol: str, start: date, end: date) -> dict[date, dict[str, Decimal | None]] | None:
        from forliosa.models import ValuationDaily

        with self.session_fn() as db:
            stmt = select(ValuationDaily).where(ValuationDaily.symbol == symbol, ValuationDaily.date >= start,
                                                ValuationDaily.date <= end)
            rows = list(db.scalars(self._filter(stmt, ValuationDaily)))
        self._remember("valuation_ratios", symbol, rows)
        return {r.date: {"per": r.per, "pbr": r.pbr, "dividend_yield": r.dividend_yield} for r in rows} or None

    # -- indices and FX ----------------------------------------------------------------------------
    def index_history(self, data_id: str, start: date, end: date) -> list[tuple[date, Decimal]] | None:
        """Archived closes of a benchmark index (``index_daily``; data_id as in ``marketdata.indices``)."""
        from forliosa.models import IndexDaily

        idx = index_by_data_id(data_id)
        if idx is None:
            return None
        with self.session_fn() as db:
            stmt = select(IndexDaily).where(IndexDaily.name == idx.archive_name, IndexDaily.date >= start,
                                            IndexDaily.date <= end).order_by(IndexDaily.date)
            rows = list(db.scalars(self._filter(stmt, IndexDaily)))
        self._remember("index_history", data_id, rows)
        return [(r.date, r.close) for r in rows] or None

    def fx_history(self, pair: str, start: date, end: date) -> dict[date, Decimal] | None:
        """USD/TWD from 中央銀行〈銀行間新臺幣對美元收盤匯率〉 only (``fx_rates`` rows with source ``cbc-opendata``,
        OGDL): the rows in [``start``, ``end``] plus the newest row before ``start``, so the first day has a rate
        however long ago the series last moved. An archive that stopped (worker down, renamed fields) thus carries
        its last rate forward for everyone instead of looking empty to a recent ``start`` (fixed 31.5). TAIFEX
        每日外幣參考匯率 rows in the same table are archived but never used for valuation (product owner
        2026-11-12)."""
        from forliosa.models import FxRate

        if pair != cbc.PAIR:
            return None
        series = self._filter(select(FxRate).where(FxRate.pair == pair, FxRate.source == cbc.SOURCE), FxRate)
        with self.session_fn() as db:
            rows = list(db.scalars(series.where(FxRate.date >= start, FxRate.date <= end).order_by(FxRate.date)))
            before = db.scalar(series.where(FxRate.date < start).order_by(FxRate.date.desc()).limit(1))
        if before is not None:
            rows.insert(0, before)
        self._remember("fx_history", pair, rows)
        return {r.date: r.rate for r in rows} or None

    # -- instrument listings -------------------------------------------------------------------------
    def listings(self) -> list[InstrumentInfo]:
        """Instruments only the archive knows. The facade adds them after every provider's own list, so a built-in or
        shioaji-data entry of the same symbol (Chinese aliases, industry) always wins.

        * Taiwan ETFs named in the official close files (``instruments`` rows of type ``etf`` that the price jobs
          write): type ``etf``, industry ``ETF``, NT$, source ``twse-openapi`` / ``tpex-openapi``.
        * SEC's ``company_tickers.json`` (``sec_tickers``): US, US$, type ``stock``, the English name as SEC spells it,
          source ``sec-edgar``. Tickers must start with a letter (``BRK-B`` keeps SEC's hyphen), so none can look like
          a Taiwan code.

        Rows the close files / SEC's file have not named within ``LISTING_DAYS`` of their newest row are left out
        (delisted). One read per master rebuild (hourly), never per search."""
        from forliosa.marketdata import opendata as od
        from forliosa.models import Instrument, SecTicker

        out: list[InstrumentInfo] = []
        window = timedelta(days=LISTING_DAYS)
        with self.session_fn() as db:
            etf = (Instrument.type == "etf", Instrument.market.in_(("TWSE", "TPEX")))
            newest = db.scalar(select(func.max(Instrument.updated_at)).where(*etf))
            if newest is not None:
                for r in db.scalars(select(Instrument).where(*etf, Instrument.updated_at >= newest - window)):
                    if od.is_listed_etf_code(r.code) and r.symbol == tw_symbol(r.code, r.market):
                        out.append(InstrumentInfo(r.symbol, r.code, r.name, r.market, "etf", "TWD", "ETF",
                                                  source="twse-openapi" if r.market == "TWSE" else "tpex-openapi"))
            newest = db.scalar(select(func.max(SecTicker.fetched_at)))
            if newest is not None:
                rows = db.execute(select(SecTicker.ticker, SecTicker.title)
                                  .where(SecTicker.fetched_at >= newest - window)).all()
                for ticker, title in rows:
                    if _US_TICKER.match(ticker):
                        out.append(InstrumentInfo(ticker, ticker, " ".join((title or "").split()) or ticker, "US",
                                                  "stock", "USD", None, source="sec-edgar"))
        return out

    # -- company profile ---------------------------------------------------------------------------
    def profile(self, symbol: str) -> InstrumentProfile | None:
        """Issued shares, market cap (shares × latest archived close), industry, listing date (t187ap03)."""
        from forliosa.models import CompanyProfile

        if market_of_symbol(symbol) == "US":
            return None
        with self.session_fn() as db:
            row = db.scalar(self._filter(select(CompanyProfile).where(CompanyProfile.symbol == symbol),
                                         CompanyProfile))
        if row is None:
            return None
        latest = self.latest_close(symbol) if row.shares_outstanding else None
        market_cap = Decimal(row.shares_outstanding) * latest[1] if latest and row.shares_outstanding else None
        key = f"{row.source}/company"
        ds = DATASETS.get(key)
        return InstrumentProfile(symbol=symbol, shares_outstanding=row.shares_outstanding, market_cap=market_cap,
                                 data_sources=(attribution(ds),) if ds else (), industry=row.industry,
                                 listed_date=row.listed_date)

    # -- reference prices and ex-rights ----------------------------------------------------------
    def reference_prices(self, symbols: list[str], d: date) -> dict[str, tuple[Decimal, Decimal | None,
                                                                              Decimal | None, str]]:
        """Official reference price and limits for ``d``: TPEx's ex-rights computation (tpex_exright_daily) on
        ex-dates first, then TWSE TWT84U / TPEx NextReferencePrice."""
        from forliosa.models import ExRightsResult, ReferencePrice

        with self.session_fn() as db:
            ex = list(db.scalars(self._filter(select(ExRightsResult).where(
                ExRightsResult.symbol.in_(symbols), ExRightsResult.date == d), ExRightsResult)))
            stmt = select(ReferencePrice).where(ReferencePrice.symbol.in_(symbols), ReferencePrice.date == d)
            rows = list(db.scalars(self._filter(stmt, ReferencePrice)))
        out = {r.symbol: (r.reference_price, r.limit_up, r.limit_down, r.source) for r in rows}
        for r in ex:
            out[r.symbol] = (r.reference_price, r.limit_up, r.limit_down, r.source)
        return out

    def ex_rights_on(self, symbols: list[str], d: date) -> dict[str, tuple[Decimal, Decimal]]:
        from forliosa.models import MarketEvent

        with self.session_fn() as db:
            stmt = select(MarketEvent).where(MarketEvent.symbol.in_(symbols), MarketEvent.date == d,
                                             MarketEvent.type == "ex_dividend")
            rows = list(db.scalars(self._filter(stmt, MarketEvent)))
        out = {}
        for r in rows:
            cash = Decimal(r.data.get("cash") or 0)
            ratio = Decimal(r.data.get("stock_ratio") or 0)
            if cash or ratio:
                out[r.symbol] = (cash, ratio)
        return out

    def dividends(self, symbol: str) -> list[DividendEvent] | None:
        """Ex-dividend notices (TWT48U_ALL, tpex_exright_prepost; a missing TPEx amount is filled from the official
        ex-rights computation) plus the board / AGM resolutions of TWSE t187ap45_L.

        A resolution is attached to the notice it belongs to (ex-date after the board date, same cash per share);
        resolutions without a notice yet are returned with ``ex_dividend_date=None``. TPEx has no resolution
        dataset (mopsfin_t187ap39_O stopped in 2021-08), so TPEx dividends only appear once the notice is out.
        """
        from forliosa.models import DividendResolution, ExRightsResult, MarketEvent

        if market_of_symbol(symbol) == "US":
            return None
        with self.session_fn() as db:
            stmt = select(MarketEvent).where(MarketEvent.symbol == symbol, MarketEvent.type == "ex_dividend")
            rows = list(db.scalars(self._filter(stmt, MarketEvent)))
            ex_rows = list(db.scalars(self._filter(select(ExRightsResult).where(ExRightsResult.symbol == symbol),
                                                   ExRightsResult)))
            resolutions = list(db.scalars(self._filter(
                select(DividendResolution).where(DividendResolution.symbol == symbol), DividendResolution)))
        self._remember("dividends", symbol, rows + ex_rows + resolutions)
        official_cash = {r.date: r.cash_dividend for r in ex_rows if r.cash_dividend}
        # Notices whose amount is not announced yet ("尚未公告", blank) are kept with zero amounts so the
        # ex-date still shows up; the facade prefers another provider's amounts for the same ex-date.
        out = []
        for r in rows:
            cash = Decimal(r.data.get("cash") or 0) or official_cash.get(r.date) or Decimal(0)
            pending = r.data.get("cash") in (None, "") and not cash and "息" in (r.title or "")
            out.append(DividendEvent(symbol, r.date.year, str(r.date.year), cash,
                                     Decimal(r.data.get("stock_ratio") or 0) * 10, r.date, None,
                                     amount_pending=pending))
        out.extend(resolution_event(symbol, r) for r in resolutions)
        return attach_resolutions(out) or None


def resolution_event(symbol: str, r: Any) -> DividendEvent:
    cash = r.cash_earnings + r.cash_legal_reserve + r.cash_capital_surplus
    stock = r.stock_earnings + r.stock_legal_reserve + r.stock_capital_surplus
    return DividendEvent(symbol, r.dividend_year, r.period, cash, stock, None, None, progress=r.progress,
                         board_date=r.board_date, meeting_date=r.meeting_date,
                         cash_sources=(r.cash_earnings, r.cash_legal_reserve, r.cash_capital_surplus))


# A board resolution's ex-date follows within this many days (TSMC quarterly ≈ 4 months; annual dividends are
# resolved in Feb–Mar and go ex in Jul–Aug). Older resolutions are not matched to a notice.
RESOLUTION_WINDOW_DAYS = 200


def attach_resolutions(events: list[DividendEvent]) -> list[DividendEvent]:
    """Merge each resolution (no ex-date) into the ex-dividend event it belongs to.

    Notices are taken in ex-date order; each gets the earliest unmatched resolution resolved before its ex-date
    (within ``RESOLUTION_WINDOW_DAYS``) with the same cash per share (±0.001) and stock dividend — dividends are
    paid in the order they were resolved, which keeps equal quarterly amounts (TSMC 2026Q1 = 2026Q2 = 7.0) apart.
    Unmatched resolutions stay as they are (ex-date not announced yet, or it was before archiving started).
    """
    dated = sorted((e for e in events if e.ex_dividend_date is not None), key=lambda e: e.ex_dividend_date)
    pending = sorted((e for e in events if e.ex_dividend_date is None and e.board_date is not None),
                     key=lambda e: e.board_date)
    others = [e for e in events if e.ex_dividend_date is None and e.board_date is None]
    tol = Decimal("0.001")
    for i, e in enumerate(dated):
        if e.progress is not None:
            continue
        for res in pending:
            if not res.board_date < e.ex_dividend_date <= res.board_date + timedelta(days=RESOLUTION_WINDOW_DAYS):
                continue
            if abs(e.cash_dividend - res.cash_dividend) <= tol and abs(e.stock_dividend - res.stock_dividend) <= tol:
                dated[i] = replace(e, year=res.year, period=res.period, progress=res.progress,
                                   board_date=res.board_date, meeting_date=res.meeting_date,
                                   cash_sources=res.cash_sources)
                pending.remove(res)
                break
    return [*dated, *pending, *others]
