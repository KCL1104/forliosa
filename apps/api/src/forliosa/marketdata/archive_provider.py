"""Market data from our own archive (``prices_daily``, ``valuation_daily``, ``reference_prices`` …).

The archive is filled by ``forliosa.archive`` from official open data (and, under the personal policy,
by backfills from FinMind and the TWSE website). Rows keep their original ``source``; under
``DATA_POLICY=commercial`` rows from non-commercial sources are ignored.

History from the archive is usually *partial* (it only grows from the day archiving started), so the
facade keeps asking the next real provider for the days the archive does not have.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.datapolicy import Policy, allowed_sources
from forliosa.marketdata.base import BaseProvider, Candle, DividendEvent, QuoteData, market_of_symbol
from forliosa.timeutil import market_close_dt, today_taipei


def _default_session() -> Session:
    from forliosa.db import session_factory

    return session_factory()()


class ArchiveProvider(BaseProvider):
    name = "archive"
    is_demo = False
    partial_history = True
    cooldown_seconds = 30

    def __init__(self, policy: Policy = "personal", session_fn: Callable[[], Session] = _default_session):
        self.policy = policy
        self.session_fn = session_fn

    def _filter(self, stmt, model):
        allowed = allowed_sources(self.policy)
        return stmt.where(model.source.in_(allowed)) if allowed is not None else stmt

    # -- prices ------------------------------------------------------------------------------------
    def history(self, symbol: str, start: date, end: date) -> list[Candle] | None:
        from forliosa.models import PriceDaily

        if market_of_symbol(symbol) == "US":
            return None
        with self.session_fn() as db:
            stmt = select(PriceDaily).where(PriceDaily.symbol == symbol, PriceDaily.date >= start,
                                            PriceDaily.date <= end).order_by(PriceDaily.date)
            rows = list(db.scalars(self._filter(stmt, PriceDaily)))
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
        return {r.date: {"per": r.per, "pbr": r.pbr, "dividend_yield": r.dividend_yield} for r in rows} or None

    # -- reference prices and ex-rights ----------------------------------------------------------
    def reference_prices(self, symbols: list[str], d: date) -> dict[str, tuple[Decimal, Decimal | None,
                                                                              Decimal | None, str]]:
        from forliosa.models import ReferencePrice

        with self.session_fn() as db:
            stmt = select(ReferencePrice).where(ReferencePrice.symbol.in_(symbols), ReferencePrice.date == d)
            rows = list(db.scalars(self._filter(stmt, ReferencePrice)))
        return {r.symbol: (r.reference_price, r.limit_up, r.limit_down, r.source) for r in rows}

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
        """Announced ex-dividend dates from the archived notices (TWT48U_ALL, tpex_exright_prepost)."""
        from forliosa.models import MarketEvent

        if market_of_symbol(symbol) == "US":
            return None
        with self.session_fn() as db:
            stmt = select(MarketEvent).where(MarketEvent.symbol == symbol, MarketEvent.type == "ex_dividend")
            rows = list(db.scalars(self._filter(stmt, MarketEvent)))
        out = []
        for r in rows:
            cash = Decimal(r.data.get("cash") or 0)
            ratio = Decimal(r.data.get("stock_ratio") or 0)
            if not cash and not ratio:
                continue
            out.append(DividendEvent(symbol, r.date.year, str(r.date.year), cash, ratio * 10, r.date, None))
        return out or None
