"""TWSE OpenAPI provider (after-close, latest day only).

Field names are taken from sources, not guessed: ``/exchangeReport/STOCK_DAY_ALL``,
``/exchangeReport/BWIBBU_ALL``, ``/exchangeReport/TWT48U_ALL``, ``/holidaySchedule/holidaySchedule`` — the
swagger (https://openapi.twse.com.tw/v1/swagger.json) and live responses. Dates are ROC ("1150929").

Only ``openapi.twse.com.tw`` is used: TWSE's website terms forbid automated downloads from
``www.twse.com.tw`` and ``mis.twse.com.tw`` without written consent, and real-time / delayed quotes need a
paid licence, so the former MIS intraday provider was removed (2026-11-12; see CONTRACT_NOTES).
"""

from __future__ import annotations

import time as _time
from datetime import date
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import (
    BaseProvider,
    DividendEvent,
    ProviderUnavailable,
    QuoteData,
    market_of_symbol,
    parse_decimal,
    parse_int,
    parse_tw_date,
    tw_symbol,
)
from forliosa.marketdata.http import HttpFetcher
from forliosa.timeutil import market_close_dt

OPENAPI_BASE = "https://openapi.twse.com.tw/v1"


def parse_stock_day_all(rows: list[dict[str, Any]]) -> dict[str, QuoteData]:
    """STOCK_DAY_ALL: Date, Code, Name, TradeVolume (shares), OpeningPrice, HighestPrice,
    LowestPrice, ClosingPrice, Change (signed), Transaction."""
    out: dict[str, QuoteData] = {}
    for r in rows:
        code = str(r.get("Code") or "").strip()
        close = parse_decimal(r.get("ClosingPrice"))
        d = parse_tw_date(r.get("Date"))
        if not code or close is None or d is None:
            continue
        change = parse_decimal(r.get("Change"))
        symbol = tw_symbol(code, "TWSE")
        out[symbol] = QuoteData(
            symbol=symbol, price=close, prev_close=(close - change) if change is not None else None,
            open=parse_decimal(r.get("OpeningPrice")), high=parse_decimal(r.get("HighestPrice")),
            low=parse_decimal(r.get("LowestPrice")), volume=parse_int(r.get("TradeVolume")),
            as_of=market_close_dt(d), trade_date=d, source="twse-openapi",
        )
    return out


def parse_bwibbu_all(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """BWIBBU_ALL: Date, Code, Name, PEratio, DividendYield (%), PBratio -> fractions for yield."""
    out = {}
    for r in rows:
        code = str(r.get("Code") or "").strip()
        if not code:
            continue
        dy = parse_decimal(r.get("DividendYield"))
        out[code] = {
            "date": parse_tw_date(r.get("Date")),
            "per": parse_decimal(r.get("PEratio")),
            "pbr": parse_decimal(r.get("PBratio")),
            "dividend_yield": dy / 100 if dy is not None else None,
        }
    return out


def parse_twt48u_all(rows: list[dict[str, Any]]) -> list[DividendEvent]:
    """TWT48U_ALL (upcoming ex-rights/ex-dividend): Date (除權息日期), Code, Name, Exdividend,
    StockDividendRatio (無償配股率), CashDividend (現金股利).

    Assumption to verify against live data: 無償配股率 is shares per share, so NT$ per share
    (配股元, par NT$10) = ratio × 10.
    """
    out = []
    for r in rows:
        code = str(r.get("Code") or "").strip()
        ex = parse_tw_date(r.get("Date"))
        if not code or ex is None:
            continue
        cash = parse_decimal(r.get("CashDividend")) or Decimal(0)
        ratio = parse_decimal(r.get("StockDividendRatio")) or Decimal(0)
        out.append(DividendEvent(
            symbol=tw_symbol(code, "TWSE"), year=ex.year, period=str(ex.year), cash_dividend=cash,
            stock_dividend=ratio * 10, ex_dividend_date=ex, payment_date=None,
        ))
    return out


def parse_holiday_schedule(rows: list[dict[str, Any]]) -> list[tuple[date, str]]:
    """holidaySchedule: Name, Date, Weekday, Description."""
    out = []
    for r in rows:
        d = parse_tw_date(r.get("Date"))
        if d is not None:
            out.append((d, str(r.get("Name") or "")))
    return out


class TwseOpenApiProvider(BaseProvider):
    name = "twse_openapi"
    is_demo = False
    CACHE_SECONDS = 600

    def __init__(self, fetcher: HttpFetcher | None = None):
        self.fetcher = fetcher or HttpFetcher()
        self._cache: dict[str, tuple[float, Any]] = {}

    def _get(self, path: str) -> Any:
        hit = self._cache.get(path)
        if hit and _time.monotonic() - hit[0] < self.CACHE_SECONDS:
            return hit[1]
        data = self.fetcher.get_json(f"{OPENAPI_BASE}{path}")
        if not isinstance(data, list):
            raise ProviderUnavailable(f"TWSE OpenAPI {path} 格式不符")
        self._cache[path] = (_time.monotonic(), data)
        return data

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        wanted = [s for s in symbols if market_of_symbol(s) == "TWSE"]
        if not wanted:
            return {}
        all_quotes = parse_stock_day_all(self._get("/exchangeReport/STOCK_DAY_ALL"))
        return {s: all_quotes[s] for s in wanted if s in all_quotes}

    def market_valuation_ratios(self) -> dict[str, dict[str, Any]]:
        """Whole market, latest day (the archive stores it daily; not the per-symbol facade method)."""
        return parse_bwibbu_all(self._get("/exchangeReport/BWIBBU_ALL"))

    def dividends(self, symbol: str) -> list[DividendEvent] | None:
        if market_of_symbol(symbol) != "TWSE":
            return None
        events = parse_twt48u_all(self._get("/exchangeReport/TWT48U_ALL"))
        return [e for e in events if e.symbol == symbol]

    def ex_rights_on(self, symbols: list[str], d: date) -> dict[str, tuple[Decimal, Decimal]]:
        """Cash dividend and stock shares per share for symbols going ex on ``d`` (TWT48U_ALL)."""
        wanted = {s for s in symbols if market_of_symbol(s) == "TWSE"}
        if not wanted:
            return {}
        out = {}
        for r in self._get("/exchangeReport/TWT48U_ALL"):
            sym = tw_symbol(str(r.get("Code") or "").strip(), "TWSE")
            if sym in wanted and parse_tw_date(r.get("Date")) == d:
                cash = parse_decimal(r.get("CashDividend")) or Decimal(0)
                ratio = parse_decimal(r.get("StockDividendRatio")) or Decimal(0)
                if cash or ratio:
                    out[sym] = (cash, ratio)
        return out

    def holidays(self) -> list[tuple[date, str]]:
        return parse_holiday_schedule(self._get("/holidaySchedule/holidaySchedule"))
