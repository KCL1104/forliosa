"""US end-of-day prices from Databento's historical API (dataset EQUS.SUMMARY, schema ohlcv-1d).

產品負責人 2026-11-15: US closes come from Databento, chosen without asking Databento about display rights first (the
owner knows the licensing risk; docs/research/us-market-data.md). Nothing here runs unless US_PRICE_SOURCE=databento
and DATABENTO_API_KEY is set.

What the API returns (checked live 2026-11-15):

* ``EQUS.SUMMARY`` is the official consolidated daily summary (Nasdaq NLS Plus): one bar per US trading day, prices
  **not** adjusted for splits or dividends, ``ts_event`` at 00:00 UTC of the session's date (the New York date).
  ``metadata.get_dataset_range`` says the dataset starts 2024-07-01; a session's bar is there the next morning
  (Taipei), ``end`` of the range being exclusive.
* ``timeseries.get_range`` with ``encoding=csv&pretty_px=true&pretty_ts=true&map_symbols=true`` answers a CSV:
  ``ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol`` (prices with 9 decimals).
* Symbols are the listing's own spelling: ``BRK.B``. Ours is SEC's (``BRK-B``, ``MarketData.resolve``): requests
  use :func:`db_symbol`, and bars come back in ours (:func:`our_symbol`). A request where some
  symbols do not resolve answers 206 with an ``X-Warning`` header naming them; one where none resolve answers 422
  ``symbology_invalid_request``.
* Authentication is HTTP Basic with the API key as the user name and an empty password. Cost is metered by the
  bytes returned: six symbols over 2.4 years cost US$0.0056 (``metadata.get_cost``).
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from forliosa.marketdata.base import ProviderUnavailable, market_of_symbol
from forliosa.marketdata.http import USER_AGENT, HttpFetcher, HttpStatusError, RateLimiter

log = logging.getLogger(__name__)

API = "https://hist.databento.com/v0/"
HOST = "hist.databento.com"
DATASET = "EQUS.SUMMARY"
SCHEMA = "ohlcv-1d"
FIRST_DAY = date(2024, 7, 1)  # metadata.get_dataset_range of EQUS.SUMMARY (2026-11-15)
# The historical API's limit is generous (100 requests / s); one request a second is plenty for a daily job.
REQUEST_INTERVAL_SECONDS = 1.0
# Symbols per request: one URL stays short, and one bad symbol only costs a warning (206), not the batch.
BATCH = 100
_QUANT = Decimal("0.0001")


@dataclass(frozen=True)
class Bar:
    symbol: str
    date: date  # the New York session's date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None


@dataclass
class Result:
    bars: list[Bar]
    unresolved: list[str]  # symbols Databento did not know (from the X-Warning header or a 422)


def fetcher(api_key: str, timeout: float = 60.0) -> HttpFetcher:
    """The only fetcher allowed to ask Databento; it carries the key (Basic auth, empty password)."""
    client = httpx.Client(timeout=timeout, auth=(api_key, ""), follow_redirects=False,
                          headers={"User-Agent": USER_AGENT, "Accept": "text/csv, application/json"})
    return HttpFetcher(client=client, retries=1, extra_allowed=(API,),
                       limiter=RateLimiter(per_host={HOST: REQUEST_INTERVAL_SECONDS}))


def db_symbol(symbol: str) -> str:
    """Our (SEC) spelling -> Databento's: ``BRK-B`` -> ``BRK.B``."""
    return symbol.strip().upper().replace("-", ".")


def our_symbol(symbol: str) -> str:
    """Databento's spelling -> ours: ``BRK.B`` -> ``BRK-B``."""
    return symbol.strip().upper().replace(".", "-")


def us_symbols(symbols: list[str]) -> list[str]:
    """The US symbols among ``symbols`` in our spelling (upper case; ``BRK.B`` becomes ``BRK-B``), each once."""
    out: list[str] = []
    for raw in symbols:
        raw = (raw or "").strip().upper()
        if not raw or market_of_symbol(raw) != "US" or " " in raw:
            continue
        s = our_symbol(raw)
        if s not in out:
            out.append(s)
    return out


def _dec(raw: str | None) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(raw).quantize(_QUANT)
    except InvalidOperation:
        return None


def parse_csv(text: str) -> list[Bar]:
    """Bars of a ``timeseries.get_range`` CSV (``pretty_px``, ``pretty_ts``, ``map_symbols``); rows without a positive
    close are left out."""
    bars: list[Bar] = []
    for row in csv.DictReader(io.StringIO(text)):
        close = _dec(row.get("close"))
        if close is None or close <= 0:
            continue
        try:
            day = date.fromisoformat((row.get("ts_event") or "")[:10])
        except ValueError:
            continue
        vol = row.get("volume")
        bars.append(Bar(symbol=our_symbol(row.get("symbol") or ""), date=day, open=_dec(row.get("open")),
                        high=_dec(row.get("high")), low=_dec(row.get("low")), close=close,
                        volume=int(vol) if vol and vol.isdigit() else None))
    return bars


def unresolved_from_warning(header: str | None) -> list[str]:
    """Symbols named in an ``X-Warning`` like ``["Warning: … symbols which did not resolve: ZZZZQ, ABCD."]``."""
    if not header or "did not resolve" not in header:
        return []
    tail = header.split("did not resolve:", 1)[1]
    return [our_symbol(s.strip(" .\"'[]")) for s in tail.split(",") if s.strip(" .\"'[]")]


def last_available_day(http: HttpFetcher) -> date:
    """The newest session in EQUS.SUMMARY (``metadata.get_dataset_range``; free). Asking past it is a 422."""
    # through _get (not get_json): a 401 / 402 / 403 is an HttpStatusError here as on the bars request, so a bad key
    # or an empty credit pauses the jobs instead of being retried every run (2026-11-15 review)
    text, _ = _get(http, f"{API}metadata.get_dataset_range", {"dataset": DATASET})
    try:
        doc = json.loads(text)
        end = date.fromisoformat(str(doc["schema"][SCHEMA]["end"])[:10])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderUnavailable("Databento 的資料範圍格式不對") from exc
    return end - timedelta(days=1)  # ``end`` is exclusive


def daily_bars(http: HttpFetcher, symbols: list[str], start: date, end: date,
               available: date | None = None) -> Result:
    """Bars of ``symbols`` from ``start`` to ``end`` (inclusive, capped at the newest session Databento has), in
    batches. Raises ``HttpStatusError`` when Databento refuses (401/403: bad key; 402: no credit left) and
    ``ProviderUnavailable`` on anything else."""
    syms = us_symbols(symbols)
    start = max(start, FIRST_DAY)
    end = min(end, available if available is not None else last_available_day(http))
    if not syms or end < start:
        return Result([], [])
    bars: list[Bar] = []
    unresolved: list[str] = []
    for i in range(0, len(syms), BATCH):
        part = syms[i:i + BATCH]
        params = {"dataset": DATASET, "schema": SCHEMA, "symbols": ",".join(db_symbol(p) for p in part),
                  "stype_in": "raw_symbol",
                  "start": start.isoformat(), "end": (end + timedelta(days=1)).isoformat(), "encoding": "csv",
                  "pretty_px": "true", "pretty_ts": "true", "map_symbols": "true"}
        url = f"{API}timeseries.get_range"
        try:
            text, warning = _get(http, url, params)
        except HttpStatusError as exc:
            if exc.status == 422 and "symbology_invalid_request" in str(exc):  # none of this batch resolved
                unresolved += part
                continue
            raise
        bars += [b for b in parse_csv(text) if start <= b.date <= end]
        unresolved += unresolved_from_warning(warning)
    return Result(bars, unresolved)


def _get(http: HttpFetcher, url: str, params: dict[str, str]) -> tuple[str, str | None]:
    """One GET through the fetcher's allow-list and rate limit; returns the body and the ``X-Warning`` header."""
    http._require_allowed(url)
    http.limiter.wait(HOST)
    try:
        resp = http.client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"Databento 連不上：{type(exc).__name__}") from exc
    if resp.status_code not in (200, 206):
        case = ""
        with contextlib.suppress(ValueError, AttributeError):
            case = str((resp.json().get("detail") or {}).get("case") or "")
        raise HttpStatusError(f"Databento 回 {resp.status_code} {case}".strip(), resp.status_code)
    return resp.text, resp.headers.get("x-warning")
