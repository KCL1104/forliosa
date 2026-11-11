"""FinMind v4 provider: real daily history, PER/PBR/yield, dividends, monthly revenue, USD/TWD.

Request/response shape verified from FinMind/FinMind (``FinMind/data/finmind_api.py``) and from
live responses (2026-11-11; trimmed copies are the test fixtures):
``GET https://api.finmindtrade.com/api/v4/data?dataset=…&data_id=…&start_date=…&end_date=…``,
optional ``Authorization: Bearer <FINMIND_TOKEN>``; rows are under ``"data"``; quota errors come
back as ``{"msg": "Requests reach the upper limit…", "status": 402}``.

* TaiwanStockPrice: date, stock_id, Trading_Volume (shares), Trading_money, open, max, min, close,
  spread, Trading_turnover — unadjusted prices.
* TaiwanStockPER: date, stock_id, dividend_yield (percent), PER, PBR.
* TaiwanStockDividend: date, stock_id, year ("113年第3季" / "113年"), StockEarningsDistribution,
  StockStatutorySurplus, StockExDividendTradingDate, CashEarningsDistribution, CashStatutorySurplus,
  CashExDividendTradingDate, CashDividendPaymentDate, …
* TaiwanStockMonthRevenue: date, stock_id, country, revenue (NT$), revenue_month, revenue_year.
* TaiwanExchangeRate (data_id=USD): date, currency, cash_buy, cash_sell, spot_buy, spot_sell.
* TaiwanStockTotalReturnIndex (data_id=TAIEX | TPEx): date, stock_id, price — 發行量加權股價報酬指數
  （含息）／櫃買報酬指數, used as a performance benchmark (see ``marketdata/indices.py``).

Every response is cached on disk (``var/cache/finmind``) so the small anonymous quota is spent at
most once per dataset/symbol per TTL; a stale cached copy is used when FinMind is unreachable.
After a failed request (quota 402, network) the provider backs off by itself for a while and
answers from the disk cache only, so one exhausted quota does not hide data that is already cached
(the facade's per-provider circuit breaker is disabled for this provider: ``cooldown_seconds = 0``).

⚠ FinMind's free tier is non-commercial; commercial use needs the Sponsor Pro plan.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from forliosa.marketdata.base import (
    BaseProvider,
    Candle,
    DividendEvent,
    ProviderUnavailable,
    QuoteData,
    RevenueRow,
    code_of_symbol,
    market_of_symbol,
    parse_decimal,
    parse_int,
    parse_tw_date,
)
from forliosa.marketdata.http import DiskCache, HttpFetcher
from forliosa.timeutil import market_close_dt

log = logging.getLogger(__name__)

API_URL = "https://api.finmindtrade.com/api/v4/data"
HISTORY_START = date(2018, 1, 1)
TTL_PRICES = 3 * 3600
TTL_SLOW = 24 * 3600  # dividends, revenue
# After a failed request: no network calls for this long (the anonymous quota resets hourly).
BACKOFF_QUOTA_SECONDS = 15 * 60
BACKOFF_ERROR_SECONDS = 5 * 60


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or "data" not in payload:
        msg = payload.get("msg") if isinstance(payload, dict) else str(payload)[:120]
        raise ProviderUnavailable(f"FinMind 回應異常：{msg}")
    status = payload.get("status")
    if status not in (None, 200):
        raise ProviderUnavailable(f"FinMind 回應狀態 {status}：{payload.get('msg')}")
    return list(payload["data"])


def parse_price(rows: list[dict[str, Any]]) -> list[Candle]:
    out = []
    for r in rows:
        d = parse_tw_date(r.get("date"))
        o, h, low, c = (parse_decimal(r.get(k)) for k in ("open", "max", "min", "close"))
        if d is None or c is None or c == 0:
            continue  # FinMind prints 0 for days without a trade
        out.append(Candle(d, o or c, h or c, low or c, c, parse_int(r.get("Trading_Volume")) or 0))
    out.sort(key=lambda x: x.t)
    return out


def parse_per(rows: list[dict[str, Any]]) -> dict[date, dict[str, Decimal | None]]:
    out: dict[date, dict[str, Decimal | None]] = {}
    for r in rows:
        d = parse_tw_date(r.get("date"))
        if d is None:
            continue
        dy = parse_decimal(r.get("dividend_yield"))
        per = parse_decimal(r.get("PER"))
        pbr = parse_decimal(r.get("PBR"))
        out[d] = {
            "per": per if per and per > 0 else None,  # FinMind prints 0 when EPS <= 0
            "pbr": pbr if pbr and pbr > 0 else None,
            "dividend_yield": dy / 100 if dy is not None else None,
        }
    return out


_ROC_PERIOD = re.compile(r"^\s*(\d{2,3})\s*(?:年\s*(?:第\s*(\d)\s*季|(上|下)半年)?)?")


def parse_roc_period(value: Any, fallback_year: int) -> tuple[int, str]:
    """'113年第3季' -> (2024, '2024Q3'); '113年' / '113' (ETFs) -> (2024, '2024'); '113年上半年' -> '2024H1'."""
    m = _ROC_PERIOD.match(str(value or ""))
    if not m:
        return fallback_year, str(fallback_year)
    year = int(m.group(1)) + 1911
    if m.group(2):
        return year, f"{year}Q{m.group(2)}"
    if m.group(3):
        return year, f"{year}H{1 if m.group(3) == '上' else 2}"
    return year, str(year)


def parse_dividends(rows: list[dict[str, Any]], symbol: str) -> list[DividendEvent]:
    out = []
    for r in rows:
        cash = (parse_decimal(r.get("CashEarningsDistribution")) or Decimal(0)) + (
            parse_decimal(r.get("CashStatutorySurplus")) or Decimal(0))
        stock = (parse_decimal(r.get("StockEarningsDistribution")) or Decimal(0)) + (
            parse_decimal(r.get("StockStatutorySurplus")) or Decimal(0))
        if cash == 0 and stock == 0:
            continue
        ex = parse_tw_date(r.get("CashExDividendTradingDate")) or parse_tw_date(r.get("StockExDividendTradingDate"))
        fallback = ex.year if ex else (parse_tw_date(r.get("date")) or date.today()).year
        year, period = parse_roc_period(r.get("year"), fallback)
        out.append(DividendEvent(
            symbol=symbol, year=year, period=period, cash_dividend=cash, stock_dividend=stock,
            ex_dividend_date=ex, payment_date=parse_tw_date(r.get("CashDividendPaymentDate")),
        ))
    # ETFs label every distribution of a year with the same "115": tell them apart by ex-date quarter.
    labels = Counter(e.period for e in out)
    out = [
        replace(e, period=f"{e.ex_dividend_date.year}Q{(e.ex_dividend_date.month - 1) // 3 + 1}")
        if labels[e.period] > 1 and e.ex_dividend_date and e.period.isdigit() else e
        for e in out
    ]
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
        ytd = sum(v for v in ytd_months if v is not None) if None not in ytd_months else None
        ytd_last = sum(v for v in ytd_prev if v is not None) if None not in ytd_prev else None
        out.append(RevenueRow(
            period=f"{y}-{m:02d}", revenue=rev,
            yoy_pct=Decimal(rev) / last_year - 1 if last_year else None,
            mom_pct=Decimal(rev) / prev - 1 if prev else None,
            ytd=ytd,
            ytd_yoy_pct=Decimal(ytd) / ytd_last - 1 if ytd and ytd_last else None,
        ))
    return out


def parse_index(rows: list[dict[str, Any]]) -> list[tuple[date, Decimal]]:
    """TaiwanStockTotalReturnIndex rows -> [(date, index level)], oldest first."""
    out = []
    for r in rows:
        d = parse_tw_date(r.get("date"))
        v = parse_decimal(r.get("price"))
        if d is not None and v is not None and v > 0:
            out.append((d, v))
    out.sort()
    return out


def parse_exchange_rate(rows: list[dict[str, Any]]) -> dict[date, Decimal]:
    """Spot mid rate = (spot_buy + spot_sell) / 2, TWD per 1 USD."""
    out: dict[date, Decimal] = {}
    for r in rows:
        d = parse_tw_date(r.get("date"))
        buy, sell = parse_decimal(r.get("spot_buy")), parse_decimal(r.get("spot_sell"))
        if d is None or not buy or not sell or buy <= 0 or sell <= 0:
            continue
        out[d] = ((buy + sell) / 2).quantize(Decimal("0.0001"))
    return out


class FinMindProvider(BaseProvider):
    name = "finmind"
    is_demo = False
    # The facade must keep asking this provider while it backs off: cached answers stay valid.
    cooldown_seconds = 0

    def __init__(self, token: str | None = None, fetcher: HttpFetcher | None = None,
                 cache_dir: Path | None = None, today_fn=date.today):
        self.token = token
        self.fetcher = fetcher or HttpFetcher(timeout=20, retries=0)
        self.cache = DiskCache(Path(cache_dir) / "finmind") if cache_dir else None
        self.today_fn = today_fn
        self._mem: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._backoff_until = 0.0
        self._clock = time.time

    def backing_off(self) -> bool:
        return self._clock() < self._backoff_until

    def _rows(self, dataset: str, data_id: str, start: date, ttl: int) -> list[dict[str, Any]]:
        """Rows of ``dataset`` for ``data_id`` from ``start`` to today, cached (memory + disk)."""
        key = f"{dataset}-{data_id}-{start.isoformat()}"
        now = self._clock()
        with self._lock:
            hit = self._mem.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        cached = self.cache.read(dataset, f"{data_id}-{start.isoformat()}") if self.cache else None
        stale: list[dict[str, Any]] | None = None
        if cached:
            doc = json.loads(cached)
            if now - doc.get("fetched_at", 0) < ttl:
                with self._lock:
                    self._mem[key] = (doc["fetched_at"], doc["rows"])
                return doc["rows"]
            stale = doc["rows"]
        if now < self._backoff_until:
            if stale is not None:
                return stale
            raise ProviderUnavailable(f"FinMind 暫停呼叫（額度或連線問題），{dataset} {data_id} 沒有快取")
        params = {"dataset": dataset, "data_id": data_id, "start_date": start.isoformat()}
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        try:
            rows = extract_rows(self.fetcher.get_json(API_URL, params=params, headers=headers))
        except ProviderUnavailable as exc:
            quota = "402" in str(exc) or "upper limit" in str(exc)
            self._backoff_until = now + (BACKOFF_QUOTA_SECONDS if quota else BACKOFF_ERROR_SECONDS)
            if stale is not None:
                log.warning("FinMind %s %s unreachable; using stale cache", dataset, data_id)
                with self._lock:
                    self._mem[key] = (now - ttl + 300, stale)  # retry in 5 minutes
                return stale
            raise
        if self.cache:
            self.cache.write(dataset, f"{data_id}-{start.isoformat()}",
                             json.dumps({"fetched_at": now, "rows": rows}, ensure_ascii=False).encode())
        with self._lock:
            self._mem[key] = (now, rows)
        return rows

    def history(self, symbol: str, start: date, end: date) -> list[Candle] | None:
        if market_of_symbol(symbol) == "US":
            return None
        candles = parse_price(self._rows("TaiwanStockPrice", code_of_symbol(symbol), HISTORY_START, TTL_PRICES))
        if not candles:
            return None  # unknown to FinMind: let the next provider answer
        return [c for c in candles if start <= c.t <= end]

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        """End-of-day quotes from the (cached) daily history: last close and the one before it."""
        out: dict[str, QuoteData] = {}
        for s in symbols:
            if market_of_symbol(s) == "US":
                continue
            candles = parse_price(self._rows("TaiwanStockPrice", code_of_symbol(s), HISTORY_START, TTL_PRICES))
            if len(candles) < 2:
                continue
            last, prev = candles[-1], candles[-2]
            out[s] = QuoteData(
                symbol=s, price=last.c, prev_close=prev.c, open=last.o, high=last.h, low=last.l, volume=last.v,
                as_of=market_close_dt(last.t), trade_date=last.t, source="finmind",
            )
        return out

    def valuation_ratios(self, symbol: str, start: date, end: date) -> dict[date, dict[str, Decimal | None]] | None:
        if market_of_symbol(symbol) == "US":
            return None
        ratios = parse_per(self._rows("TaiwanStockPER", code_of_symbol(symbol), HISTORY_START, TTL_PRICES))
        if not ratios:
            return None
        return {d: v for d, v in ratios.items() if start <= d <= end}

    def dividends(self, symbol: str) -> list[DividendEvent] | None:
        if market_of_symbol(symbol) == "US":
            return None
        rows = self._rows("TaiwanStockDividend", code_of_symbol(symbol), date(2010, 1, 1), TTL_SLOW)
        return parse_dividends(rows, symbol)

    def monthly_revenue(self, symbol: str) -> list[RevenueRow] | None:
        if market_of_symbol(symbol) == "US":
            return None
        rows = self._rows("TaiwanStockMonthRevenue", code_of_symbol(symbol), date(2018, 1, 1), TTL_SLOW)
        return parse_month_revenue(rows) or None

    def index_history(self, index_id: str, start: date, end: date) -> list[tuple[date, Decimal]] | None:
        """Daily levels of a TWSE/TPEx total-return index (data_id ``TAIEX`` or ``TPEx``)."""
        series = parse_index(self._rows("TaiwanStockTotalReturnIndex", index_id, HISTORY_START, TTL_PRICES))
        return [(d, v) for d, v in series if start <= d <= end] or None

    def fx_history(self, pair: str, start: date, end: date) -> dict[date, Decimal] | None:
        if pair != "USDTWD":
            return None
        series = parse_exchange_rate(self._rows("TaiwanExchangeRate", "USD", HISTORY_START, TTL_PRICES))
        if not series:
            return None
        lo = start - timedelta(days=10)
        return {d: v for d, v in series.items() if lo <= d <= end}
