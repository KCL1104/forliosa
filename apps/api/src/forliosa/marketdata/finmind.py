"""FinMind v4 provider (history, PER/PBR, dividends, monthly revenue).

Request/response shape verified from FinMind/FinMind (``FinMind/data/finmind_api.py``):
``GET https://api.finmindtrade.com/api/v4/data?dataset=…&data_id=…&start_date=…&end_date=…`` with
``Authorization: Bearer <token>``; the reply's rows are under ``"data"``. Column names come from the
SDK's docstrings and tests (``FinMind/data/data_loader.py``, ``tests/data/test_data_loader.py``):

* TaiwanStockPrice: date, stock_id, Trading_Volume, Trading_money, open, max, min, close, spread,
  Trading_turnover
* TaiwanStockPER: date, stock_id, dividend_yield, PER, PBR
* TaiwanStockDividend: date, stock_id, year, StockEarningsDistribution, StockStatutorySurplus,
  StockExDividendTradingDate, CashEarningsDistribution, CashStatutorySurplus,
  CashExDividendTradingDate, CashDividendPaymentDate, …
* TaiwanStockMonthRevenue: date, stock_id, country, revenue, revenue_month, revenue_year, create_time

⚠ FinMind's free tier is non-commercial; commercial use needs the Sponsor Pro plan.
Assumptions to verify with live data: ``revenue`` is in NT$ (converted to thousands here), and
``dividend_yield`` is in percent.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import (
    BaseProvider,
    Candle,
    DividendEvent,
    ProviderUnavailable,
    RevenueRow,
    code_of_symbol,
    market_of_symbol,
    parse_decimal,
    parse_int,
    parse_tw_date,
)
from forliosa.marketdata.http import HttpFetcher

API_URL = "https://api.finmindtrade.com/api/v4/data"


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or "data" not in payload:
        msg = payload.get("msg") if isinstance(payload, dict) else str(payload)[:120]
        raise ProviderUnavailable(f"FinMind 回應異常：{msg}")
    return list(payload["data"])


def parse_price(rows: list[dict[str, Any]]) -> list[Candle]:
    out = []
    for r in rows:
        d = parse_tw_date(r.get("date"))
        o, h, low, c = (parse_decimal(r.get(k)) for k in ("open", "max", "min", "close"))
        if d is None or c is None or c == 0:
            continue
        out.append(Candle(d, o or c, h or c, low or c, c, parse_int(r.get("Trading_Volume")) or 0))
    out.sort(key=lambda x: x.t)
    return out


def parse_per(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        d = parse_tw_date(r.get("date"))
        if d is None:
            continue
        dy = parse_decimal(r.get("dividend_yield"))
        out.append({"date": d, "per": parse_decimal(r.get("PER")), "pbr": parse_decimal(r.get("PBR")),
                    "dividend_yield": dy / 100 if dy is not None else None})
    return out


def _year(value: Any, fallback: int) -> int:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return fallback
    y = int(digits)
    return y + 1911 if y < 1911 else y


def parse_dividends(rows: list[dict[str, Any]], symbol: str) -> list[DividendEvent]:
    out = []
    for r in rows:
        cash = (parse_decimal(r.get("CashEarningsDistribution")) or Decimal(0)) + (
            parse_decimal(r.get("CashStatutorySurplus")) or Decimal(0))
        stock = (parse_decimal(r.get("StockEarningsDistribution")) or Decimal(0)) + (
            parse_decimal(r.get("StockStatutorySurplus")) or Decimal(0))
        ex = parse_tw_date(r.get("CashExDividendTradingDate")) or parse_tw_date(r.get("StockExDividendTradingDate"))
        if cash == 0 and stock == 0:
            continue
        year = _year(r.get("year"), ex.year if ex else 0)
        out.append(DividendEvent(
            symbol=symbol, year=year, period=str(year), cash_dividend=cash, stock_dividend=stock,
            ex_dividend_date=ex, payment_date=parse_tw_date(r.get("CashDividendPaymentDate")),
        ))
    out.sort(key=lambda e: (e.ex_dividend_date or date.min), reverse=True)
    return out


def parse_month_revenue(rows: list[dict[str, Any]]) -> list[RevenueRow]:
    by_period: dict[tuple[int, int], int] = {}
    for r in rows:
        y, m = parse_int(r.get("revenue_year")), parse_int(r.get("revenue_month"))
        rev = parse_decimal(r.get("revenue"))
        if y and m and rev is not None:
            by_period[(y, m)] = int(rev / 1000)  # NT$ -> thousand NT$
    out = []
    for (y, m) in sorted(by_period):
        rev = by_period[(y, m)]
        last_year = by_period.get((y - 1, m))
        prev = by_period.get((y, m - 1) if m > 1 else (y - 1, 12))
        ytd_months = [by_period.get((y, k)) for k in range(1, m + 1)]
        ytd_prev = [by_period.get((y - 1, k)) for k in range(1, m + 1)]
        ytd = sum(ytd_months) if None not in ytd_months else None
        ytd_last = sum(ytd_prev) if None not in ytd_prev else None  # type: ignore[arg-type]
        out.append(RevenueRow(
            period=f"{y}-{m:02d}", revenue=rev,
            yoy_pct=Decimal(rev) / last_year - 1 if last_year else None,
            mom_pct=Decimal(rev) / prev - 1 if prev else None,
            ytd=ytd,
            ytd_yoy_pct=Decimal(ytd) / ytd_last - 1 if ytd and ytd_last else None,
        ))
    return out


class FinMindProvider(BaseProvider):
    name = "finmind"
    is_demo = False

    def __init__(self, token: str | None = None, fetcher: HttpFetcher | None = None):
        self.token = token
        self.fetcher = fetcher or HttpFetcher()

    def _rows(self, dataset: str, data_id: str, start: date, end: date | None = None) -> list[dict[str, Any]]:
        params = {"dataset": dataset, "data_id": data_id, "start_date": start.isoformat()}
        if end:
            params["end_date"] = end.isoformat()
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        return extract_rows(self.fetcher.get_json(API_URL, params=params, headers=headers))

    def history(self, symbol: str, start: date, end: date) -> list[Candle] | None:
        if market_of_symbol(symbol) == "US":
            return None
        return parse_price(self._rows("TaiwanStockPrice", code_of_symbol(symbol), start, end))

    def dividends(self, symbol: str) -> list[DividendEvent] | None:
        if market_of_symbol(symbol) == "US":
            return None
        return parse_dividends(self._rows("TaiwanStockDividend", code_of_symbol(symbol), date(2005, 1, 1)), symbol)

    def monthly_revenue(self, symbol: str) -> list[RevenueRow] | None:
        if market_of_symbol(symbol) == "US":
            return None
        return parse_month_revenue(self._rows("TaiwanStockMonthRevenue", code_of_symbol(symbol), date(2015, 1, 1)))

    def per_history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        return parse_per(self._rows("TaiwanStockPER", code_of_symbol(symbol), start, end))
