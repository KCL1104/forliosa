"""Instrument detail, quotes, history and valuation (PER/PBR river) assembly."""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import not_found, unprocessable
from forliosa.datapolicy import label, labels, source_clause, tagged
from forliosa.marketdata.base import DividendEvent, InstrumentInfo, QuoteData
from forliosa.marketdata.demo import report_publication_date
from forliosa.marketdata.service import MarketData, dividend_sort_key
from forliosa.models import PriceDaily
from forliosa.services.coverage import series_notes
from forliosa.services.portfolio import range_start
from forliosa.timeutil import iso_taipei, today_taipei

HISTORY_RANGES = ("5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX")
VALUATION_RANGES = ("1Y", "3Y", "5Y", "10Y", "MAX")


def instrument_out(info: InstrumentInfo, md: MarketData) -> dict[str, Any]:
    return {
        "symbol": info.symbol, "code": info.code, "name": info.name, "market": info.market, "type": info.type,
        "currency": info.currency, "industry": info.industry, "has_quote": md.has_quote(info),
    }


def require_instrument(md: MarketData, symbol: str) -> InstrumentInfo:
    info = md.instrument(symbol)
    if info is None:
        raise not_found("找不到商品")
    return info


def detail(md: MarketData, symbol: str) -> dict[str, Any]:
    """Instrument detail. Under ``commercial`` shioaji-data's AI-written research (business summary, chain
    stage, themes; licence 「待定」) is left out; the official fields (shares, market cap) stay."""
    from forliosa.marketdata.shioaji_data import SOURCE_FINANCIALS, SOURCE_OFFICIAL, SOURCE_RESEARCH

    info = require_instrument(md, symbol)
    prof = md.profile(info.symbol)
    # shioaji-data's summary / chain stage / themes (profile and instrument card alike) are the AI research
    research_ok = md.policy == "personal"
    card_ok = research_ok or info.source != "shioaji-data"
    summary = (prof.summary if research_ok else None) or (info.summary if card_ok else None)
    stage = (prof.chain_stage if research_ok else None) or (info.chain_stage if card_ok else None)
    return {
        **instrument_out(info, md),
        "industry": info.industry or prof.industry,
        "summary": summary,
        "chain_stage": stage,
        "themes": list(prof.themes) if research_ok else [],
        "shares_outstanding": prof.shares_outstanding,
        "market_cap": ser.money(prof.market_cap),
        "listed_date": prof.listed_date,
        "data_sources": [label("shioaji-data") if s in (SOURCE_OFFICIAL, SOURCE_FINANCIALS) else s
                         for s in prof.data_sources if research_ok or s != SOURCE_RESEARCH],
        "is_demo": prof.is_demo,
    }


def change_base(q: QuoteData) -> Decimal | None:
    """Taiwan change is measured from the reference price (平盤); on ex-rights days that is not the close."""
    return q.reference_price if q.reference_price is not None else q.prev_close


def quote_out(q: QuoteData) -> dict[str, Any]:
    base = change_base(q)
    change = q.price - base if q.price is not None and base is not None else None
    return {
        "symbol": q.symbol,
        "price": ser.price(q.price),
        "prev_close": ser.price(q.prev_close),
        "reference_price": ser.price(q.reference_price),
        "limit_up": ser.price(q.limit_up),
        "limit_down": ser.price(q.limit_down),
        "change": ser.price(change),
        "change_pct": ser.ratio(change / base) if change is not None and base else None,
        "open": ser.price(q.open),
        "high": ser.price(q.high),
        "low": ser.price(q.low),
        "volume": q.volume,
        "as_of": iso_taipei(q.as_of) if q.as_of else None,
        "is_realtime": q.is_realtime,
        "is_demo": q.is_demo,
        "source": q.source,
        "sources": labels(tagged(q.source, "price")),
    }


def history(md: MarketData, symbol: str, range_: str) -> dict[str, Any]:
    if range_ not in HISTORY_RANGES:
        raise unprocessable(f"不支援的區間：{range_}（可用 {'、'.join(HISTORY_RANGES)}）")
    info = require_instrument(md, symbol)
    today = today_taipei()
    start = range_start(range_, today, date(1990, 1, 1))
    h = md.history(info.symbol, start, today, backfill=True)  # a chart: may show the history backfill's days
    candles = h.candles
    notes = series_notes(md, info.symbol, start, candles[0].t if candles else None, backfill=True)
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
        "sources": labels(tagged(h.source, "price")),
        "notes": notes,
    }


def close_on(db: Session, md: MarketData, symbol: str, day: date) -> dict[str, Any]:
    """The official close of ``symbol`` on exactly ``day``, for the buy form's 「那天收盤」 hint.

    Read from our own archive (``prices_daily``) only, under the data policy like the ledger's valuation: never the
    history backfill's rows (``yahoo-history`` — product owner, 2026-11-13: Yahoo's data is for charts, technical
    indicators and sparklines, never the ledger) and never a live request upstream. ``close`` is None when the
    archive has no row for that very day (a weekend or holiday, before the archive began, a US stock).
    """
    if day > today_taipei():
        raise unprocessable("日期不能晚於今天")
    info = require_instrument(md, symbol)
    close = db.scalar(select(PriceDaily.close).where(
        PriceDaily.symbol == info.symbol, PriceDaily.date == day, source_clause(PriceDaily.source, md.policy)))
    return {"symbol": info.symbol, "date": day, "close": ser.price(close), "currency": info.currency}


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
    ratios, ratio_sources = (md.valuation_ratios_with_source(info.symbol, min(start, five_y), today)
                             if info.type == "stock" else (None, []))
    coverage = series_notes(md, info.symbol, start, hist.candles[0].t if hist.candles else None)
    if ratios:
        out = _valuation_from_ratios(info, hist.candles, ratios, start, five_y, hist.is_demo)
        out["sources"] = labels([*tagged(hist.source, "price"), *tagged(ratio_sources, "valuation")])
        out["notes"] = [*coverage, *out["notes"]]
        return out
    fundamentals = md.valuation_inputs(info.symbol) if info.type == "stock" else None
    divs = md.dividends(info.symbol)
    notes: list[str] = list(coverage)
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
        notes.append("ETF 沒有每股盈餘與每股淨值，所以沒有本益比與股價淨值比區間")
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
        "sources": labels([*tagged(hist.source, "price"),
                           *(["shioaji-data"] if fundamentals and not fundamentals.is_demo else []),
                           *(["demo"] if is_demo else [])]),
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
    notes = ["本益比、股價淨值比、殖利率為證交所／櫃買中心公布值；EPS = 收盤價 ÷ 本益比"]
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


def dividend_sources(ans_source: str, e: DividendEvent, is_demo: bool) -> list[str]:
    """Dataset keys behind one dividend: the ex-dividend notice and / or the board resolution (t187ap45_L)."""
    if is_demo:
        return ["demo"]
    keys = tagged(ans_source, "ex_dividend") if e.ex_dividend_date is not None else []
    if e.progress is not None:
        keys.append("twse-openapi/dividend_resolution")
    return keys


def dividend_status(e: DividendEvent) -> str:
    """``announced`` (an ex-dividend date is published) or ``resolved`` (board / AGM resolution only)."""
    return "announced" if e.ex_dividend_date is not None else "resolved"


# A resolution with no ex-dividend notice is listed only while its board date is this recent (product owner
# 2026-11-14, 2-6): annual dividends often go ex more than four months after the board meeting, and an older one
# without a notice most likely went ex before archiving started — listed, it would look like a pending dividend.
RESOLUTION_SHOWN_DAYS = 180


def resolution_shown(e: DividendEvent, today: date) -> bool:
    """Notices always; a resolution only when its board date (else its AGM date) is within
    :data:`RESOLUTION_SHOWN_DAYS` — one with neither date cannot be placed, so it is left out."""
    if e.ex_dividend_date is not None:
        return True
    resolved_on = e.board_date or e.meeting_date
    return resolved_on is not None and resolved_on >= today - timedelta(days=RESOLUTION_SHOWN_DAYS)


def dividends(md: MarketData, symbol: str, today: date | None = None) -> list[dict[str, Any]]:
    """Ex-dividend notices plus TWSE board / AGM resolutions (t187ap45_L) not yet in a notice. A resolution's
    ``ex_dividend_date`` is null until the notice appears; resolutions whose board date is older than
    :data:`RESOLUTION_SHOWN_DAYS` without a notice are left out (they went ex before archiving started).
    ``cash_sources`` splits the cash by source — 資本公積 cash is generally not dividend income."""
    info = require_instrument(md, symbol)
    ans = md.dividends(info.symbol)
    today = today or today_taipei()
    events = sorted((e for e in ans.value if resolution_shown(e, today)), key=dividend_sort_key, reverse=True)
    out = []
    for e in events:
        is_demo = e.is_demo or ans.is_demo
        cs = e.cash_sources
        out.append({
            "year": e.year, "period": e.period, "cash_dividend": ser.price(e.cash_dividend),
            "stock_dividend": ser.price(e.stock_dividend), "ex_dividend_date": e.ex_dividend_date,
            "payment_date": e.payment_date, "is_demo": is_demo, "status": dividend_status(e),
            "progress": e.progress, "board_date": e.board_date, "meeting_date": e.meeting_date,
            "cash_sources": ({"earnings": ser.price(cs[0]), "legal_reserve": ser.price(cs[1]),
                              "capital_surplus": ser.price(cs[2])} if cs else None),
            "sources": labels(dividend_sources(ans.source, e, is_demo)),
        })
    return out
