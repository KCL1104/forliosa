"""TWSE OpenAPI (after-close, latest day only) and TWSE MIS (intraday) providers.

Field names are taken from sources, not guessed:

* OpenAPI ``/exchangeReport/STOCK_DAY_ALL``, ``/exchangeReport/BWIBBU_ALL``,
  ``/exchangeReport/TWT48U_ALL``, ``/holidaySchedule/holidaySchedule`` — the swagger bundled with
  twjackysu/TWSEMCPServer (``staticFiles/swagger_decoded.json``). Dates are ROC ("1150929").
* MIS ``getStockInfo.jsp`` ``msgArray`` keys — mlouielu/twstock ``realtime.py`` and its mock data
  (c, n, z, y, o, h, l, v, tlong, d, t, ex, b, a …). ``z`` is "-" when there was no trade yet;
  ``v`` (accumulated volume) is in lots of 1,000 shares.

⚠ MIS is *not* an official API (TWSE licenses real-time data separately). It must be replaced by
a licensed feed before any commercial use. Requests are spaced ≥ 0.5 s apart (shared limiter).
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import (
    BaseProvider,
    DividendEvent,
    ProviderUnavailable,
    QuoteData,
    code_of_symbol,
    market_of_symbol,
    parse_decimal,
    parse_int,
    parse_tw_date,
    tw_symbol,
)
from forliosa.marketdata.http import HttpFetcher
from forliosa.timeutil import TAIPEI, market_close_dt

OPENAPI_BASE = "https://openapi.twse.com.tw/v1"
MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIS_BATCH = 50  # symbols per MIS request


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


def mis_channel(symbol: str) -> str:
    """'2330.TW' -> 'tse_2330.tw'; '6488.TWO' -> 'otc_6488.tw'."""
    prefix = "otc" if market_of_symbol(symbol) == "TPEX" else "tse"
    return f"{prefix}_{code_of_symbol(symbol)}.tw"


def parse_mis(payload: dict[str, Any]) -> dict[str, QuoteData]:
    """MIS getStockInfo.jsp JSON -> quotes. Placeholder rows (empty ``c``) are skipped."""
    out: dict[str, QuoteData] = {}
    for item in payload.get("msgArray") or []:
        code = str(item.get("c") or "").strip()
        if not code:
            continue
        market = "TPEX" if item.get("ex") == "otc" else "TWSE"
        symbol = tw_symbol(code, market)
        tlong = parse_int(item.get("tlong"))
        as_of = datetime.fromtimestamp(tlong / 1000, tz=UTC).astimezone(TAIPEI) if tlong else None
        d = parse_tw_date(item.get("d")) or (as_of.date() if as_of else None)
        lots = parse_int(item.get("v"))
        out[symbol] = QuoteData(
            symbol=symbol,
            price=parse_decimal(item.get("z")),  # None when no trade yet ("-")
            prev_close=parse_decimal(item.get("y")),
            open=parse_decimal(item.get("o")),
            high=parse_decimal(item.get("h")),
            low=parse_decimal(item.get("l")),
            volume=lots * 1000 if lots is not None else None,
            as_of=as_of, trade_date=d, is_realtime=True, source="twse-mis",
        )
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
        if hit and time.monotonic() - hit[0] < self.CACHE_SECONDS:
            return hit[1]
        data = self.fetcher.get_json(f"{OPENAPI_BASE}{path}")
        if not isinstance(data, list):
            raise ProviderUnavailable(f"TWSE OpenAPI {path} 格式不符")
        self._cache[path] = (time.monotonic(), data)
        return data

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        wanted = [s for s in symbols if market_of_symbol(s) == "TWSE"]
        if not wanted:
            return {}
        all_quotes = parse_stock_day_all(self._get("/exchangeReport/STOCK_DAY_ALL"))
        return {s: all_quotes[s] for s in wanted if s in all_quotes}

    def valuation_ratios(self) -> dict[str, dict[str, Any]]:
        return parse_bwibbu_all(self._get("/exchangeReport/BWIBBU_ALL"))

    def dividends(self, symbol: str) -> list[DividendEvent] | None:
        if market_of_symbol(symbol) != "TWSE":
            return None
        events = parse_twt48u_all(self._get("/exchangeReport/TWT48U_ALL"))
        return [e for e in events if e.symbol == symbol]

    def holidays(self) -> list[tuple[date, str]]:
        return parse_holiday_schedule(self._get("/holidaySchedule/holidaySchedule"))


class TwseMisProvider(BaseProvider):
    """Intraday quotes (unofficial endpoint — see module docstring)."""

    name = "twse_mis"
    is_demo = False

    def __init__(self, fetcher: HttpFetcher | None = None):
        self.fetcher = fetcher or HttpFetcher(timeout=8.0)

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        tw = [s for s in symbols if market_of_symbol(s) != "US"]
        out: dict[str, QuoteData] = {}
        for i in range(0, len(tw), MIS_BATCH):
            batch = tw[i:i + MIS_BATCH]
            payload = self.fetcher.get_json(
                MIS_URL, params={"ex_ch": "|".join(mis_channel(s) for s in batch), "json": 1, "delay": 0}
            )
            if not isinstance(payload, dict) or payload.get("rtcode") not in (None, "0000"):
                raise ProviderUnavailable(f"MIS 回應異常：{str(payload)[:120]}")
            out.update({k: v for k, v in parse_mis(payload).items() if k in batch})
        return out
