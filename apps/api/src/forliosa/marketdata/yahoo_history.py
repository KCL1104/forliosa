"""Daily candles from Yahoo Finance's chart endpoint, for the history backfill only.

Not a licensed source: Yahoo's terms do not allow redistribution and the prices belong to the exchanges. The
product owner chose it on 2026-11-13 to fill the years before our own archive began, with the rows kept apart
(``datapolicy.HISTORY_SOURCE``) so they can be deleted together. Nothing here runs unless PRICE_HISTORY_SOURCE=yahoo.

What the endpoint returns (checked 2026-11-13 with 2330.TW, 0050.TW and 6488.TWO):

* one bar per trading day, timestamps at the market open; ``meta.gmtoffset`` turns them into Taipei dates;
* ``open`` / ``high`` / ``low`` / ``close`` are **split-adjusted** (0050 before its 2025 split reads a quarter of the
  price it traded at) and *not* dividend-adjusted; no split list is returned for Taiwan symbols, so the original
  prices cannot be rebuilt. That is why only chart-like reads use these rows;
* the newest bar can be today's unfinished session — the backfill keeps nothing from the first official day on;
* a bar of a day without trades has ``null`` values;
* the newest bar of TPEx symbols (``.TWO``) can have its open, high and low but a ``null`` close for hours after the
  session ended (00679B.TWO on 2026-11-13, read at 00:40 the next day). Such a bar is never stored, but its range is
  still evidence that the ticker is the right one (``history_backfill``).

The request uses our normal honest User-Agent — never a browser disguise. Yahoo limits requests per address and
answers 429 now and then even at this pace (seen 2026-11-13); the backfill then waits and asks again, and stops when
that does not help (``history_backfill.run_batch``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import ProviderUnavailable, market_of_symbol
from forliosa.marketdata.http import HttpFetcher, RateLimiter

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
HOST = "query1.finance.yahoo.com"
# One request per symbol; at this spacing a full run (about 2,400 symbols) takes an hour and a half.
REQUEST_INTERVAL_SECONDS = 2.0
_QUANT = Decimal("0.0001")


@dataclass(frozen=True)
class Bar:
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None  # missing on the newest day of some symbols for hours after the close (see module docstring)
    volume: int | None


def fetcher(timeout: float = 30.0) -> HttpFetcher:
    """The chart endpoint is outside the default allowlist: only this fetcher may ask it."""
    return HttpFetcher(timeout=timeout, retries=0, extra_allowed=(CHART_URL,),
                       limiter=RateLimiter(per_host={HOST: REQUEST_INTERVAL_SECONDS}))


def ticker(symbol: str) -> str | None:
    """Our Taiwan symbols are already Yahoo's tickers (``2330.TW``, ``6488.TWO``); anything else is not asked."""
    return symbol if market_of_symbol(symbol) in ("TWSE", "TPEX") else None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value)).quantize(_QUANT)
    except (ArithmeticError, ValueError):
        return None
    return d if d > 0 else None


def parse_chart(doc: Any) -> list[Bar]:
    """The ``chart.result[0]`` of a response as bars in date order. A day with neither a close nor a high–low range is
    left out; one with a range but no close is kept with ``close=None``."""
    try:
        result = doc["chart"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderUnavailable("Yahoo Finance 回傳的格式不對") from exc
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    offset = int((result.get("meta") or {}).get("gmtoffset") or 0)
    cols = {k: quote.get(k) or [] for k in ("open", "high", "low", "close", "volume")}
    bars: dict[date, Bar] = {}
    for i, ts in enumerate(stamps):
        close = _dec(cols["close"][i] if i < len(cols["close"]) else None)
        o, h, lo = (_dec(cols[k][i] if i < len(cols[k]) else None) for k in ("open", "high", "low"))
        if close is None and (h is None or lo is None):
            continue
        day = datetime.fromtimestamp(int(ts) + offset, UTC).date()
        vol = cols["volume"][i] if i < len(cols["volume"]) else None
        bars[day] = Bar(day, o, h, lo, close, int(vol) if isinstance(vol, (int, float)) and vol >= 0 else None)
    return [bars[d] for d in sorted(bars)]


def daily_bars(http: HttpFetcher, symbol: str, start: date, end: date) -> list[Bar]:
    """Bars of ``symbol`` from ``start`` to ``end`` (inclusive). Raises ``HttpStatusError`` on a refusal (404: Yahoo
    does not know the symbol; 429 and the like: stop asking) and ``ProviderUnavailable`` on anything else."""
    name = ticker(symbol)
    if name is None:
        raise ProviderUnavailable(f"{symbol} 不是台股代號")
    period1 = int(datetime.combine(start, time.min, UTC).timestamp())
    period2 = int(datetime.combine(end + timedelta(days=1), time.min, UTC).timestamp())
    doc = http.get_json(f"{CHART_URL}{name}", params={"period1": period1, "period2": period2, "interval": "1d"})
    return [b for b in parse_chart(doc) if start <= b.date <= end]
