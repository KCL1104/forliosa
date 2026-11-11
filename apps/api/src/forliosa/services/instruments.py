"""Instrument detail, quotes, history and valuation (PER/PBR river) assembly."""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from forliosa.api import serialize as ser
from forliosa.api.errors import not_found, unprocessable
from forliosa.marketdata.base import InstrumentInfo, QuoteData
from forliosa.marketdata.demo import report_publication_date
from forliosa.marketdata.service import MarketData
from forliosa.services.portfolio import range_start
from forliosa.timeutil import iso_taipei, today_taipei

HISTORY_RANGES = ("5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX")
VALUATION_RANGES = ("1Y", "3Y", "5Y", "10Y", "MAX")


def instrument_out(info: InstrumentInfo) -> dict[str, Any]:
    return {
        "symbol": info.symbol, "code": info.code, "name": info.name, "market": info.market, "type": info.type,
        "currency": info.currency, "industry": info.industry,
    }


def require_instrument(md: MarketData, symbol: str) -> InstrumentInfo:
    info = md.instrument(symbol)
    if info is None:
        raise not_found("找不到商品")
    return info


def detail(md: MarketData, symbol: str) -> dict[str, Any]:
    info = require_instrument(md, symbol)
    prof = md.profile(info.symbol)
    return {
        **instrument_out(info),
        "summary": prof.summary or info.summary,
        "chain_stage": prof.chain_stage or info.chain_stage,
        "themes": list(prof.themes),
        "shares_outstanding": prof.shares_outstanding,
        "market_cap": ser.money(prof.market_cap),
        "data_sources": list(prof.data_sources),
        "is_demo": prof.is_demo,
    }


def quote_out(q: QuoteData) -> dict[str, Any]:
    change = q.price - q.prev_close if q.price is not None and q.prev_close is not None else None
    return {
        "symbol": q.symbol,
        "price": ser.price(q.price),
        "prev_close": ser.price(q.prev_close),
        "change": ser.price(change),
        "change_pct": ser.ratio(change / q.prev_close) if change is not None and q.prev_close else None,
        "open": ser.price(q.open),
        "high": ser.price(q.high),
        "low": ser.price(q.low),
        "volume": q.volume,
        "as_of": iso_taipei(q.as_of) if q.as_of else None,
        "is_realtime": q.is_realtime,
        "is_demo": q.is_demo,
        "source": q.source,
    }


def history(md: MarketData, symbol: str, range_: str) -> dict[str, Any]:
    if range_ not in HISTORY_RANGES:
        raise unprocessable(f"不支援的區間：{range_}（可用 {'、'.join(HISTORY_RANGES)}）")
    info = require_instrument(md, symbol)
    today = today_taipei()
    start = range_start(range_, today, date(1990, 1, 1))
    h = md.history(info.symbol, start, today)
    candles = h.candles
    if range_ == "5D":
        candles = candles[-5:]
    return {
        "symbol": info.symbol,
        "interval": "1d",
        "candles": [
            {"t": c.t, "o": ser.price(c.o), "h": ser.price(c.h), "l": ser.price(c.l), "c": ser.price(c.c), "v": c.v}
            for c in candles
        ],
        "is_demo": h.is_demo,
    }


_MANTISSAS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)


def nice_multiples(values: list[float], count: int = 5) -> list[float]:
    """``count`` evenly spaced round multiples covering the 5th–95th percentile of ``values``.

    The smallest "nice" step (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8 × 10ⁿ) whose band, starting at a multiple
    of the step at or below the low end, reaches the high end — e.g. PER 13.4–31.5 -> 12, 18 … 36.
    """
    vals = sorted(v for v in values if v is not None and v > 0 and math.isfinite(v))
    if len(vals) < 2:
        return []
    lo = vals[int(0.05 * (len(vals) - 1))]
    hi = vals[math.ceil(0.95 * (len(vals) - 1))]
    if hi <= lo:
        hi = lo * 1.2
    raw = (hi - lo) / (count - 1)
    mag = 10 ** math.floor(math.log10(raw))
    for step in [m * mag for m in _MANTISSAS] + [m * mag * 10 for m in _MANTISSAS]:
        if step < raw * 0.999:
            continue
        start = math.floor(lo / step) * step
        if start <= 0:
            start = step
        if start + step * (count - 1) >= hi:
            return [round(start + i * step, 2) for i in range(count)]
    return []


def valuation(md: MarketData, symbol: str, range_: str = "5Y") -> dict[str, Any]:
    if range_ not in VALUATION_RANGES:
        raise unprocessable(f"不支援的區間：{range_}（可用 {'、'.join(VALUATION_RANGES)}）")
    info = require_instrument(md, symbol)
    today = today_taipei()
    start = range_start(range_, today, date(1990, 1, 1))
    five_y = range_start("5Y", today, date(1990, 1, 1))
    hist = md.history(info.symbol, min(start, five_y), today)
    ratios = md.valuation_ratios(info.symbol, min(start, five_y), today) if info.type == "stock" else None
    if ratios:
        return _valuation_from_ratios(info, hist.candles, ratios, start, five_y, hist.is_demo)
    fundamentals = md.valuation_inputs(info.symbol) if info.type == "stock" else None
    divs = md.dividends(info.symbol)
    notes: list[str] = []
    is_demo = hist.is_demo or divs.is_demo

    quarters = fundamentals.value if fundamentals else []
    if fundamentals is not None:
        is_demo |= fundamentals.is_demo
    published = sorted((report_publication_date(q.period), i) for i, q in enumerate(quarters))
    pub_dates = [d for d, _ in published]
    div_events = sorted((e.ex_dividend_date, e.cash_dividend) for e in divs.value
                        if e.ex_dividend_date and e.cash_dividend > 0)
    div_dates = [d for d, _ in div_events]
    div_cum = [Decimal(0)]
    for _, amt in div_events:
        div_cum.append(div_cum[-1] + amt)

    def fundamentals_on(d: date) -> tuple[Decimal | None, Decimal | None]:
        k = bisect_right(pub_dates, d)
        if k == 0:
            return None, None
        idx = sorted(i for _, i in published[:k])
        last4 = [quarters[i] for i in idx[-4:]]
        eps_ttm = None
        if len(last4) == 4 and all(q.eps is not None for q in last4):
            eps_ttm = sum((q.eps for q in last4 if q.eps is not None), Decimal(0))
        return eps_ttm, quarters[idx[-1]].bvps

    def trailing_dividends(d: date) -> Decimal:
        hi = bisect_right(div_dates, d)
        lo = bisect_right(div_dates, d - timedelta(days=365))
        return div_cum[hi] - div_cum[lo]

    series = []
    per_5y: list[float] = []
    for c in hist.candles:
        eps, bvps = fundamentals_on(c.t)
        per = c.c / eps if eps is not None and eps > 0 else None
        pbr = c.c / bvps if bvps is not None and bvps > 0 else None
        dy = trailing_dividends(c.t) / c.c if c.c else None
        if c.t >= five_y and per is not None:
            per_5y.append(float(per))
        if c.t < start:
            continue
        series.append({
            "t": c.t, "close": ser.price(c.c), "eps_ttm": ser.price(eps), "bvps": ser.price(bvps),
            "per": ser.price(per), "pbr": ser.price(pbr), "dividend_yield": ser.ratio(dy),
        })

    per_vals = [p["per"] for p in series if p["per"] is not None]
    pbr_vals = [p["pbr"] for p in series if p["pbr"] is not None]
    if info.type != "stock":
        notes.append("ETF 沒有每股盈餘與淨值，不提供本益比與股價淨值比區間")
    elif not per_vals:
        notes.append("近四季 EPS 合計小於或等於 0，本益比無意義，區間留白")
    last = series[-1] if series else None
    current_per = last["per"] if last else None
    percentile = None
    if current_per is not None and per_5y:
        percentile = ser.ratio(Decimal(sum(1 for v in per_5y if v <= current_per)) / Decimal(len(per_5y)))
    if fundamentals is not None and fundamentals.is_demo:
        notes.append("較早期的 EPS／淨值為示範資料（shioaji-data 季報自 2023Q1 起）")
    return {
        "symbol": info.symbol,
        "per_multiples": nice_multiples(per_vals),
        "pbr_multiples": nice_multiples(pbr_vals),
        "series": series,
        "current": {
            "per": current_per,
            "pbr": last["pbr"] if last else None,
            "dividend_yield": last["dividend_yield"] if last else None,
            "per_percentile_5y": percentile,
        },
        "notes": notes,
        "is_demo": is_demo,
    }


def _valuation_from_ratios(info: InstrumentInfo, candles: list, ratios: dict, start: date, five_y: date,
                           is_demo: bool) -> dict[str, Any]:
    """Valuation from published daily PER / PBR / yield (e.g. TWSE via FinMind).

    eps_ttm = close / PER and bvps = close / PBR, so the river bands (eps_ttm × multiple) pass
    exactly through the published ratios. Days without a published ratio (e.g. today's close
    before the ratios are out) carry the previous EPS / BVPS / dividend forward.
    """
    series = []
    per_5y: list[float] = []
    eps = bvps = dps = None
    no_eps_days = 0
    for c in candles:
        r = ratios.get(c.t)
        if r is not None:
            per, pbr, dy = r.get("per"), r.get("pbr"), r.get("dividend_yield")
            eps = c.c / per if per else None
            bvps = c.c / pbr if pbr else bvps
            dps = dy * c.c if dy is not None else dps
            if per is None:
                no_eps_days += 1
        per_v = c.c / eps if eps else None
        pbr_v = c.c / bvps if bvps else None
        dy_v = dps / c.c if dps is not None and c.c else None
        if c.t >= five_y and per_v is not None:
            per_5y.append(float(per_v))
        if c.t < start:
            continue
        series.append({
            "t": c.t, "close": ser.price(c.c), "eps_ttm": ser.price(eps), "bvps": ser.price(bvps),
            "per": ser.price(per_v), "pbr": ser.price(pbr_v), "dividend_yield": ser.ratio(dy_v),
        })
    notes = ["本益比、股價淨值比、殖利率為證交所／櫃買中心公布值（經 FinMind 取得）；EPS = 收盤價 ÷ 本益比"]
    per_vals = [p["per"] for p in series if p["per"] is not None]
    if not per_vals or no_eps_days:
        notes.append("期間內有近四季 EPS 小於或等於 0 的日子，本益比無意義，該段區間留白")
    last = series[-1] if series else None
    current_per = last["per"] if last else None
    percentile = None
    if current_per is not None and per_5y:
        percentile = ser.ratio(Decimal(sum(1 for v in per_5y if v <= current_per)) / Decimal(len(per_5y)))
    return {
        "symbol": info.symbol,
        "per_multiples": nice_multiples(per_vals),
        "pbr_multiples": nice_multiples([p["pbr"] for p in series if p["pbr"] is not None]),
        "series": series,
        "current": {
            "per": current_per,
            "pbr": last["pbr"] if last else None,
            "dividend_yield": last["dividend_yield"] if last else None,
            "per_percentile_5y": percentile,
        },
        "notes": notes,
        "is_demo": is_demo,
    }


def revenue(md: MarketData, symbol: str) -> list[dict[str, Any]]:
    info = require_instrument(md, symbol)
    if info.type != "stock" or info.market == "US":
        return []  # ETFs have no revenue; US filings are not covered (saves upstream quota)
    ans = md.monthly_revenue(info.symbol)
    return [
        {"period": r.period, "revenue": r.revenue, "yoy_pct": ser.ratio(r.yoy_pct), "mom_pct": ser.ratio(r.mom_pct),
         "ytd": r.ytd, "ytd_yoy_pct": ser.ratio(r.ytd_yoy_pct)}
        for r in ans.value
    ]


def dividends(md: MarketData, symbol: str) -> list[dict[str, Any]]:
    info = require_instrument(md, symbol)
    ans = md.dividends(info.symbol)
    events = sorted(ans.value, key=lambda e: e.ex_dividend_date or date.min, reverse=True)
    return [
        {"year": e.year, "period": e.period, "cash_dividend": ser.price(e.cash_dividend),
         "stock_dividend": ser.price(e.stock_dividend), "ex_dividend_date": e.ex_dividend_date,
         "payment_date": e.payment_date, "is_demo": e.is_demo or ans.is_demo}
        for e in events
    ]
