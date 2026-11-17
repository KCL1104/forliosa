"""MarketData facade: asks providers in the configured order and falls back on failure.

* ``MARKET_DATA_PROVIDERS=shioaji_data,demo`` (comma-separated, highest priority first).
* Quotes are merged field by field: a real provider's price wins; fields it lacks (e.g.
  shioaji-data has no open/high/low/volume) are filled from the next providers and the quote is
  then flagged ``is_demo`` if any filled field came from the demo provider.
* A provider that raises is skipped for a cool-down period (simple circuit breaker).
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from forliosa.config import Settings
from forliosa.datapolicy import Policy, label, provider_allowed
from forliosa.domain.ticks import ex_rights_prices, is_fund_code, price_limits
from forliosa.marketdata.base import (
    BaseProvider,
    Candle,
    CorporateEvent,
    DividendEvent,
    HistoryResult,
    InstrumentInfo,
    InstrumentProfile,
    QuarterFundamentals,
    QuoteData,
    RevenueRow,
    ValuationInputs,
    code_of_symbol,
    market_of_symbol,
)
from forliosa.marketdata.catalog import KNOWN_SPLITS
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.http import HttpFetcher, SingleFlight
from forliosa.marketdata.indices import INDICES, resolve_index
from forliosa.timeutil import close_dt, last_tw_trading_day

INTERIM_CLOSE_SOURCE = "shioaji-data"  # forliosa.archive.INTERIM_CLOSE_SOURCE: the archive's interim evening closes

log = logging.getLogger(__name__)
T = TypeVar("T")

COOLDOWN_SECONDS = 300
MASTER_TTL_SECONDS = 3600
LISTINGS_RETRY_SECONDS = 60  # the master missed a provider's listings (database down): rebuild it this soon
QUOTE_TTL_SECONDS = 30
# Instruments only the archive's listings name (``InstrumentInfo.source`` -> the dataset their name comes from): every
# ETF in the official close files, SEC's US tickers.
LISTING_DATASETS = {"twse-openapi": "twse-openapi/price", "tpex-openapi": "tpex-openapi/price",
                    "sec-edgar": "sec-edgar/tickers"}
# Live ex-dividend notice files the worker also archives (TWT48U_ALL, tpex_exright_prepost) -> the ``dataset_status``
# row the same archive run writes: ``forliosa.archive`` groups ``twse`` / ``tpex`` store the closes, then the notices
# (which have no status row of their own). While that run is recent the archive's copy alone answers dividends and
# ex-rights, so a request never waits for the live file (2026-11-16: TWT48U_ALL took 0.3–3.8 s of an AI turn); a notice
# posted since shows up after the next run. No archive, no row or an older run (weekend, failed run): asked as before.
ARCHIVED_NOTICES = {"twse_openapi": "twse-openapi/price", "tpex_openapi": "tpex-openapi/price"}
# Trading days run both groups at 08:10, 14:40 and 21:40: the longest gap (21:40 → 08:10) is 10.5 h.
NOTICES_FRESH_SECONDS = 12 * 3600


@dataclass
class Answer[T]:
    value: T
    is_demo: bool
    source: str


class _Entry:
    """One instrument in the search index: upper-cased code and names computed once per master rebuild."""

    __slots__ = ("code", "info", "listing", "names", "symbol", "us_listing")

    def __init__(self, info: InstrumentInfo):
        self.info = info
        self.code = info.code.upper()
        self.symbol = info.symbol.upper()
        self.names = tuple((n, n.upper()) for n in (info.name, *info.aliases))
        self.listing = info.source in LISTING_DATASETS  # only the archive's listings know it
        self.us_listing = self.listing and info.market == "US"  # SEC's tickers: English names only


def listing_sources(info: InstrumentInfo) -> tuple[str, ...]:
    """Where an instrument's name and code come from, for a page that has no other profile source."""
    if info.source == "built-in":
        return ("內建商品清單",)
    key = LISTING_DATASETS.get(info.source)
    return (label(key),) if key else ()


class MarketData:
    """Under ``commercial`` the demo provider only contributes the static instrument master (names and
    codes): it never answers quotes, history, dividends, fundamentals or FX, so no synthetic number is
    ever served. Endpoints then return empty data with a 「資料累積中」 note instead."""

    def __init__(self, providers: list[BaseProvider], jitter: bool = False, policy: Policy = "commercial"):
        self.policy: Policy = policy
        self.providers = [p for p in providers if provider_allowed(p.name, policy)]
        self.demo: DemoProvider | None = next((p for p in self.providers if isinstance(p, DemoProvider)), None)
        if self.demo is not None:
            self.demo.anchor_fn = self._real_anchor
        self.jitter = jitter
        self._down_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._master: dict[str, InstrumentInfo] | None = None
        self._master_until = 0.0
        self._by_code: dict[str, list[str]] = {}
        self._index: list[_Entry] = []
        self._quote_cache: dict[str, tuple[float, QuoteData]] = {}
        self._flight = SingleFlight()

    # -- provider plumbing -----------------------------------------------------------------------
    @property
    def demo_data_allowed(self) -> bool:
        return self.policy == "personal"

    def _available(self, include_demo: bool | None = None) -> list[BaseProvider]:
        """Providers not cooling down. Demo providers only answer data calls under ``personal``."""
        now = time.monotonic()
        demo_ok = self.demo_data_allowed if include_demo is None else include_demo
        return [p for p in self.providers if self._down_until.get(p.name, 0) <= now and (demo_ok or not p.is_demo)]

    def _call(self, provider: BaseProvider, fn: Callable[[], T]) -> T | None:
        try:
            return fn()
        except Exception as exc:  # any upstream failure -> fall back to the next provider
            log.warning("market data provider %s failed: %s", provider.name, exc)
            cooldown = getattr(provider, "cooldown_seconds", COOLDOWN_SECONDS)
            with self._lock:
                self._down_until[provider.name] = time.monotonic() + cooldown
            return None

    def _first(self, method: str, *args: Any) -> Answer | None:
        for p in self._available():
            value = self._call(p, lambda p=p: getattr(p, method)(*args))
            if value is not None:
                return Answer(value, p.is_demo, p.name)
        return None

    def status(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        out = []
        for p in self.providers:
            available = self._down_until.get(p.name, 0) <= now
            backing_off = getattr(p, "backing_off", None)
            if callable(backing_off) and backing_off():
                available = False  # answers from its disk cache only
            # under commercial the demo provider only names instruments (catalog); it never serves data
            out.append({"name": p.name, "is_demo": p.is_demo, "available": available,
                        "serves_data": self.demo_data_allowed or not p.is_demo})
        return out

    def _archived_notices(self) -> set[str]:
        """Live notice providers (``ARCHIVED_NOTICES``) the archive has answered for: it comes before them, did not fail
        in this call (a failure puts it on cool-down) and the worker archived that market's notices recently."""
        names = [p.name for p in self.providers]
        if "archive" not in names or self._down_until.get("archive", 0) > time.monotonic():
            return set()
        first = names.index("archive")
        keys = {name: key for name, key in ARCHIVED_NOTICES.items() if name in names[first + 1:]}
        session_fn = getattr(self.providers[first], "session_fn", None)
        if not keys or session_fn is None:
            return set()
        from sqlalchemy import select

        from forliosa.models import DatasetStatus

        try:
            with session_fn() as db:
                rows = db.execute(select(DatasetStatus.key, DatasetStatus.fetched_at).where(
                    DatasetStatus.key.in_(list(keys.values())))).all()
            fetched = {key: at for key, at in rows}
        except Exception as exc:  # the live endpoints answer instead
            log.warning("archive status unavailable: %s", exc)
            return set()
        since = datetime.now(UTC) - timedelta(seconds=NOTICES_FRESH_SECONDS)
        return {name for name, key in keys.items() if (at := fetched.get(key)) is not None and at >= since}

    def _real_anchor(self, symbol: str) -> tuple[date, Decimal] | None:
        """Latest real close for the demo provider to anchor its synthetic path."""
        for p in self._available():
            if p.is_demo:
                continue
            latest = getattr(p, "latest_close", None)
            if latest is None:
                continue
            value = self._call(p, lambda latest=latest: latest(symbol))
            if value is not None:
                return value
        return None

    # -- instruments -----------------------------------------------------------------------------
    def master(self) -> dict[str, InstrumentInfo]:
        """Every known instrument by symbol, rebuilt at most hourly. Providers' own lists come first (shioaji-data's
        cards, then the built-in catalog of the demo provider: names, Chinese aliases); a provider's ``listings()``
        (the archive: every ETF in the official close files, SEC's US tickers) only adds symbols nobody else named.
        If a listing cannot be read (database down), the master is rebuilt again after ``LISTINGS_RETRY_SECONDS``."""
        with self._lock:
            if self._master is not None and time.monotonic() < self._master_until:
                return self._master
        # One rebuild at a time: requests that need the master meanwhile wait for it instead of each downloading
        # shioaji-data's cards (2.8 MB) and reading the listings again (2026-11-16: three at once on a cold start)
        return self._flight.do("master", self._rebuild_master)

    def _rebuild_master(self) -> dict[str, InstrumentInfo]:
        with self._lock:
            if self._master is not None and time.monotonic() < self._master_until:
                return self._master  # a rebuild that finished just before this one started
        started = time.monotonic()
        merged: dict[str, InstrumentInfo] = {}
        for p in self._available(include_demo=True):  # the built-in catalog is reference data, not prices
            items = self._call(p, p.instruments)
            for info in items or []:
                merged.setdefault(info.symbol, info)
        complete = True
        for p in self.providers:  # a database read: not subject to a network provider's cool-down
            fn = getattr(p, "listings", None)
            if fn is None:
                continue
            try:
                items = fn()
            except Exception as exc:  # the list still works without them; try again soon
                log.warning("instrument listings of %s unavailable: %s", p.name, exc)
                complete = False
                continue
            for info in items or []:
                merged.setdefault(info.symbol, info)
        by_code: dict[str, list[str]] = {}
        for sym, info in merged.items():
            by_code.setdefault(info.code.upper(), []).append(sym)
        index = [_Entry(info) for info in merged.values()]
        ttl = MASTER_TTL_SECONDS if complete else LISTINGS_RETRY_SECONDS
        with self._lock:
            self._master, self._by_code, self._index = merged, by_code, index
            self._master_until = time.monotonic() + ttl
        # hourly, inside whichever request needs it first: its time shows in that request (2026-11-16 AI latency)
        log.info("instrument master rebuilt: %d instruments in %.2f s", len(merged), time.monotonic() - started)
        return merged

    def resolve(self, text: str) -> str | None:
        """'2330' / '2330.tw' / 'aapl' / 'brk.b' -> canonical symbol, or None if unknown. A code that two markets
        share resolves to the Taiwan listing."""
        s = text.strip().upper()
        master = self.master()
        if s.endswith(".TWO"):
            s = s[:-4] + ".TWO"
        if s in master:
            return s
        syms = self._by_code.get(s)
        if not syms and "." in s and market_of_symbol(s) == "US":
            alt = s.replace(".", "-")  # BRK.B -> BRK-B (SEC's spelling)
            if alt in master:
                return alt
            syms = self._by_code.get(alt)
        if syms:
            return min(syms, key=lambda x: (market_of_symbol(x) == "US", x))
        return None

    def resolve_benchmark(self, text: str) -> str | None:
        """A benchmark is an index (``^TAIEXTR``) or any known instrument (``0050`` -> ``0050.TW``)."""
        return resolve_index(text) or self.resolve(text)

    def benchmark_name(self, symbol: str) -> str:
        if symbol in INDICES:
            return INDICES[symbol].name
        info = self.instrument(symbol)
        return info.name if info else symbol

    def instrument(self, symbol: str) -> InstrumentInfo | None:
        sym = self.resolve(symbol)
        return self.master().get(sym) if sym else None

    def search(self, q: str, limit: int = 20) -> list[InstrumentInfo]:
        """Code, name or alias matches, best first: exact code (or symbol, ``2330.TW``), code prefix, exact name, name
        prefix, name contains, code contains. Within a rank Taiwan comes before the US, shorter codes first (0050 before
        00500…), and the built-in / provider entries before the archive's listings of the same code length.

        SEC's US tickers (English names only) answer English queries only (ASCII with a letter; ``2330`` or 「台積」
        never reach them) and come after everything else unless the ticker matches exactly (``T``, ``MSFT``)."""
        q = q.strip()
        if not q:
            return []
        qu = q.upper()
        self.master()
        english = q.isascii() and any(c.isalpha() for c in q)
        alt = qu.replace(".", "-") if english else qu  # BRK.B -> BRK-B
        scored: list[tuple[tuple, InstrumentInfo]] = []
        for e in self._index:
            if e.us_listing and not english:
                continue
            code = e.code
            if code in (qu, alt) or e.symbol == qu:
                rank = 0
            elif code.startswith(qu) or code.startswith(alt):
                rank = 1
            elif any(n == q or nu == qu for n, nu in e.names):
                rank = 2
            elif any(n.startswith(q) or nu.startswith(qu) for n, nu in e.names):
                rank = 3
            elif any(q in n or qu in nu for n, nu in e.names):
                rank = 4
            elif qu in code:
                rank = 5
            else:
                continue
            info = e.info
            later = e.us_listing and rank > 0
            scored.append(((later, rank, info.market == "US", len(info.code), e.listing, info.code), info))
        scored.sort(key=lambda x: x[0])
        return [info for _, info in scored[:limit]]

    def has_quote(self, info: InstrumentInfo) -> bool:
        """Whether any quote source covers the instrument's market under the policy: US stocks have stored Databento
        closes while US_PRICE_SOURCE=databento (``forliosa.us_prices``); otherwise none under ``commercial``
        (personal mode fills them with demo prices)."""
        return info.market != "US" or self.demo_data_allowed or self.us_prices_served()

    def us_prices_served(self) -> bool:
        archive = next((p for p in self.providers if p.name == "archive"), None)
        fn = getattr(archive, "us_served", None)
        try:
            return bool(fn()) if fn is not None else False
        except Exception:  # pragma: no cover - settings unreadable
            return False

    def profile(self, symbol: str) -> InstrumentProfile:
        """Merged across real providers, highest priority first: the archive's official company data (issued
        shares, market cap, industry, listing date from t187ap03) wins; shioaji-data fills the rest."""
        merged: InstrumentProfile | None = None
        for p in self._available():
            if p.is_demo:
                continue
            prof = self._call(p, lambda p=p: p.profile(symbol))
            if prof is not None:
                merged = prof if merged is None else _merge_profiles(merged, prof)
        if merged is not None:
            return merged
        info = self.instrument(symbol)
        return InstrumentProfile(
            symbol=symbol, summary=info.summary if info else None, chain_stage=info.chain_stage if info else None,
            data_sources=listing_sources(info) if info else (),
        )

    # -- quotes ----------------------------------------------------------------------------------
    def forget_quotes(self) -> None:
        """Drop the 30-second quote cache (realtime: new closes were stored; the next read must see them)."""
        with self._lock:
            self._quote_cache.clear()

    def quotes(self, symbols: list[str], use_cache: bool = True) -> dict[str, QuoteData]:
        now = time.monotonic()
        out: dict[str, QuoteData] = {}
        pending: list[str] = []
        for s in dict.fromkeys(symbols):
            hit = self._quote_cache.get(s) if use_cache else None
            if hit and now - hit[0] < QUOTE_TTL_SECONDS:
                out[s] = hit[1]
            else:
                pending.append(s)
        if pending:
            partial: dict[str, QuoteData] = {}
            # The archive's interim evening close (forliosa.closes, close only by nature): nothing later in the chain
            # fills its open / high / low / volume (their files are an older session until the official one is
            # archived), so it is not asked — it downloaded a whole close file for nothing (2026-11-16 review).
            interim: set[str] = set()
            for p in self._available():
                need = [s for s in pending if s not in partial or (partial[s].missing() and s not in interim)
                        or (not p.is_demo and partial[s].is_demo)]
                if not need:
                    break
                got = self._call(p, lambda p=p, need=need: p.quotes(need)) or {}
                for s, q in got.items():
                    if q.price is None:
                        continue
                    if p.name == "archive" and q.source == INTERIM_CLOSE_SOURCE:
                        interim.add(s)
                    cur = partial.get(s)
                    if cur is None:
                        partial[s] = q
                    elif not p.is_demo and q.trade_date and cur.trade_date and q.trade_date > cur.trade_date:
                        partial[s] = _merge_quotes(q, cur)  # a newer real session wins (e.g. archive is a day old)
                    else:
                        partial[s] = _merge_quotes(cur, q)
            final: dict[str, QuoteData] = {}
            # Commercial mode only has after-close data: whatever a provider reports, a quote's time is the close of
            # the session its price belongs to (13:30 Taipei; 16:00 New York for a US close), and none is real-time.
            closes_only = self.policy == "commercial"
            for s, q in partial.items():
                if q.trade_date is not None and (q.as_of is None or closes_only):
                    q = replace(q, as_of=close_dt(s, q.trade_date))
                if closes_only and q.is_realtime:
                    q = replace(q, is_realtime=False)
                final[s] = q
            for s, q in self._with_references(final).items():
                self._quote_cache[s] = (now, q)
                out[s] = q
        return out

    # -- reference price (平盤) and limits ---------------------------------------------------------
    def _provider_map(self, method: str, symbols: list[str], d: date) -> dict[str, Any]:
        out: dict[str, Any] = {}
        archived = functools.cache(self._archived_notices)  # read once, after the archive has answered
        for p in self._available():
            fn = getattr(p, method, None)
            if fn is None:
                continue
            need = [s for s in symbols if s not in out]
            if not need:
                break
            if method == "ex_rights_on" and p.name in ARCHIVED_NOTICES and p.name in archived():
                continue  # the archive's copy of the same notices answered already
            got = self._call(p, lambda fn=fn, need=need: fn(need, d)) or {}
            for s, v in got.items():
                out.setdefault(s, v)
        return out

    def _with_references(self, quotes: dict[str, QuoteData]) -> dict[str, QuoteData]:
        """Attach reference price and limits; on ex-rights days the reference is not the previous close.

        Order: official archive (TWT84U / TPEx NextReferencePrice) → exchange limits on the quote (MIS
        u / w) checked against the ex-rights reference → computed: (prev close − cash) ÷ (1 + stock ratio)
        rounded to the tick, limits ±10 % rounded inward to the tick.
        """
        by_day: dict[date, list[str]] = {}
        for s, q in quotes.items():
            if market_of_symbol(s) != "US" and q.trade_date is not None:
                by_day.setdefault(q.trade_date, []).append(s)
        out = dict(quotes)
        for s, q in quotes.items():
            if market_of_symbol(s) == "US":  # the previous close, unless the archive found a split on that day
                ref = q.reference_price if q.reference_price is not None else q.prev_close
                out[s] = replace(q, reference_price=ref, limit_up=None, limit_down=None)
        for d, syms in by_day.items():
            official = self._provider_map("reference_prices", syms, d)
            ex = self._provider_map("ex_rights_on", [s for s in syms if s not in official], d)
            for s in syms:
                out[s] = _apply_reference(quotes[s], official.get(s), ex.get(s))
        return out

    def quote(self, symbol: str) -> QuoteData | None:
        return self.quotes([symbol]).get(symbol)

    def live_quotes(self, symbols: list[str]) -> dict[str, QuoteData]:
        """Quotes for the SSE stream; in dev, demo quotes get a small random jitter."""
        quotes = self.quotes(symbols)
        if self.jitter and self.demo is not None:
            return {s: (self.demo.jittered(q) if q.is_demo else q) for s, q in quotes.items()}
        return quotes

    # -- history & corporate data ------------------------------------------------------------------
    def history(self, symbol: str, start: date, end: date, backfill: bool = False) -> HistoryResult:
        """Daily candles. A partial provider (our archive) answers first; the next real provider fills
        the days it lacks. Demo data is only used when no real provider has anything.

        ``backfill=True`` — charts, technical indicators and sparklines only — also reads the days the history
        backfill stored (``PRICE_HISTORY_SOURCE``): they are split-adjusted and not official, so a caller that values
        holdings (portfolio, groups, recurring plans, position history) must leave it off."""
        collected: dict[date, Candle] = {}
        names: list[str] = []
        is_demo = False
        for p in self._available():
            if p.is_demo and collected:
                break
            wants = backfill and getattr(p, "accepts_backfill", False)
            value = self._call(p, lambda p=p, wants=wants: (p.history(symbol, start, end, backfill=True) if wants
                                                             else p.history(symbol, start, end)))
            if not value:
                continue
            added = False
            for c in value:
                if c.t not in collected:
                    collected[c.t] = c
                    added = True
            if added:
                names.extend(_row_sources(p, "history", symbol))
                is_demo |= p.is_demo
            if not getattr(p, "partial_history", False):
                break
        if not collected:
            return HistoryResult(symbol, [], False, "")
        candles = [collected[d] for d in sorted(collected)]
        if not is_demo:
            candles = self._with_today(symbol, candles, end)
        return HistoryResult(symbol, candles, is_demo, "+".join(dict.fromkeys(names)))

    def _with_today(self, symbol: str, candles: list[Candle], end: date) -> list[Candle]:
        """Daily sources publish after the close; append the latest day from a complete real quote."""
        q = self.quote(symbol)
        if q is None or q.is_demo or q.trade_date is None or q.trade_date > end:
            return candles
        if candles and q.trade_date <= candles[-1].t:
            return candles
        if None in (q.price, q.open, q.high, q.low) or q.volume is None:
            return candles
        assert q.price is not None and q.open is not None and q.high is not None and q.low is not None
        return [*candles, Candle(q.trade_date, q.open, q.high, q.low, q.price, q.volume)]

    def index_history(self, symbol: str, start: date, end: date) -> HistoryResult:
        """Daily levels of a benchmark index (``^TAIEXTR``) as close-only candles; empty when unavailable.

        There is no synthetic fallback: an index without real data yields no benchmark line.
        """
        idx = INDICES.get(symbol)
        if idx is None:
            return HistoryResult(symbol, [], False, "")
        collected: dict[date, Decimal] = {}
        names: list[str] = []
        for p in self._available():
            fn = getattr(p, "index_history", None)
            if fn is None or p.is_demo:
                continue
            value = self._call(p, lambda fn=fn: fn(idx.data_id, start, end))
            if value:
                before = len(collected)
                for d, v in value:
                    collected.setdefault(d, v)
                if len(collected) > before:
                    names.extend(_row_sources(p, "index_history", idx.data_id))
            if value and not getattr(p, "partial_history", False):
                break  # the archive only grows from its first day: a full provider (FinMind) fills older days
        candles = [Candle(d, v, v, v, v, 0) for d, v in sorted(collected.items())]
        return HistoryResult(symbol, candles, False, "+".join(dict.fromkeys(names)))

    def valuation_ratios(self, symbol: str, start: date, end: date) -> dict[date, dict] | None:
        """Real daily PER / PBR / dividend yield as published (archive first, FinMind fills older days)."""
        return self.valuation_ratios_with_source(symbol, start, end)[0]

    def valuation_ratios_with_source(self, symbol: str, start: date, end: date) -> tuple[dict[date, dict] | None,
                                                                                         list[str]]:
        merged: dict[date, dict] = {}
        names: list[str] = []
        for p in self._available():
            fn = getattr(p, "valuation_ratios", None)
            if fn is None or p.is_demo:
                continue
            value = self._call(p, lambda fn=fn: fn(symbol, start, end))
            if not value:
                continue
            before = len(merged)
            for d, v in value.items():
                merged.setdefault(d, v)
            if len(merged) > before:
                names.extend(_row_sources(p, "valuation_ratios", symbol))
            if not getattr(p, "partial_history", False):
                break
        return (merged or None), names

    def closes(self, symbol: str, start: date, end: date) -> tuple[dict[date, Decimal], bool]:
        h = self.history(symbol, start, end)
        return {c.t: c.c for c in h.candles}, h.is_demo

    def dividends(self, symbol: str) -> Answer[list[DividendEvent]]:
        """Dividends merged from every real provider (by ex-date); demo only when none has any."""
        merged: dict[Any, DividendEvent] = {}
        names: list[str] = []
        archived = functools.cache(self._archived_notices)  # read once, after the archive has answered
        for p in self._available():
            if p.is_demo:
                continue
            if p.name in ARCHIVED_NOTICES and p.name in archived():
                continue  # the archive's copy of the same notices answered already
            value = self._call(p, lambda p=p: p.dividends(symbol))
            if not value:
                continue
            names.extend(_row_sources(p, "dividends", symbol))
            for e in value:
                key = e.ex_dividend_date or (e.year, e.period)
                cur = merged.get(key)
                if cur is None or (not cur.cash_dividend and not cur.stock_dividend
                                   and (e.cash_dividend or e.stock_dividend)):
                    merged[key] = e if cur is None or e.payment_date else replace(e, payment_date=cur.payment_date)
                elif cur.payment_date is None and e.payment_date is not None:
                    merged[key] = replace(cur, payment_date=e.payment_date, period=e.period, year=e.year)
        if merged:
            from forliosa.marketdata.archive_provider import attach_resolutions

            events = sorted(attach_resolutions(list(merged.values())), key=dividend_sort_key, reverse=True)
            return Answer(events, False, "+".join(dict.fromkeys(names)))
        if self.demo is not None and self.demo in self._available():
            value = self._call(self.demo, lambda: self.demo.dividends(symbol))
            if value:
                return Answer(list(value), True, self.demo.name)
        return Answer([], False, "")

    def corporate_events(self, symbol: str) -> list[CorporateEvent]:
        """Known real splits (reference data) plus any a real provider reports."""
        events = [CorporateEvent(symbol, d, "split", r) for d, r in KNOWN_SPLITS.get(symbol, ())]
        for p in self._available():
            if p.is_demo:
                continue
            more = self._call(p, lambda p=p: p.corporate_events(symbol))
            for e in more or []:
                if all((e.date, e.kind) != (x.date, x.kind) for x in events):
                    events.append(e)
        return sorted(events, key=lambda e: e.date)

    def monthly_revenue(self, symbol: str) -> Answer[list[RevenueRow]]:
        ans = self._first("monthly_revenue", symbol)
        if ans is None:
            return Answer([], False, "")
        return ans

    def valuation_inputs(self, symbol: str) -> Answer[list[QuarterFundamentals]] | None:
        """Real quarters override demo quarters of the same period; demo fills the older past."""
        real: ValuationInputs | None = None
        demo: ValuationInputs | None = None
        for p in self._available():
            vi = self._call(p, lambda p=p: p.valuation_inputs(symbol))
            if vi is None:
                continue
            if p.is_demo:
                demo = demo or vi
            else:
                real = real or vi
        if real is None and demo is None:
            return None
        if real is None:
            assert demo is not None
            return Answer(list(demo.quarters), True, demo.source)
        first_real = min(q.period for q in real.quarters)
        # Demo quarters only fill the past before the first real one (never overwrite real data).
        by_period = {q.period: q for q in (demo.quarters if demo else ()) if q.period < first_real}
        used_demo = bool(by_period)
        for q in real.quarters:
            by_period[q.period] = q
        quarters = [by_period[k] for k in sorted(by_period)]
        sources = [real.source] + ([demo.source] if used_demo and demo else [])
        return Answer(quarters, used_demo, "+".join(sources))

    def statements(self, symbol: str) -> Answer[dict[str, Any]] | None:
        for p in self._available():
            fn = getattr(p, "statements", None)
            if fn is None or p.is_demo:
                continue
            value = self._call(p, lambda fn=fn: fn(symbol))
            if value:
                return Answer(value, False, p.name)
        return None

    def provider(self, name: str) -> BaseProvider | None:
        return next((p for p in self._available() if p.name == name), None)

    def backfill_until(self, symbol: str) -> date | None:
        """The last day of ``symbol`` taken from the history backfill, if charts use any."""
        archive = next((p for p in self.providers if p.name == "archive"), None)
        fn = getattr(archive, "backfill_until", None)
        if fn is None:
            return None
        try:
            return fn(symbol)
        except Exception:  # the archive is optional (e.g. no database yet)
            return None

    def archive_since(self, symbol: str | None = None) -> date | None:
        """First archived trading day of ``symbol`` usable under the policy; without one (or a Taiwan symbol with no
        row yet), where the Taiwan archive begins. A US symbol with no row has none: its closes come from a separate
        backfill, not from the archive's daily runs."""
        archive = next((p for p in self.providers if p.name == "archive"), None)
        fn = getattr(archive, "first_date", None)
        if fn is None:
            return None
        try:
            own = fn(symbol) if symbol else None
            if own is None and symbol and market_of_symbol(symbol) == "US":
                return None
            return own or fn(None)
        except Exception:  # the archive is optional (e.g. no database yet)
            return None

    def fx_series(self, pair: str, start: date, end: date) -> tuple[dict[date, Decimal], bool]:
        series, is_demo, _source = self.fx_series_with_source(pair, start, end)
        return series, is_demo

    def fx_series_with_source(self, pair: str, start: date, end: date) -> tuple[dict[date, Decimal], bool, str]:
        """FX series and the source keys behind it (archive: ``cbc-opendata``; empty when none answered)."""
        for p in self._available():
            value = self._call(p, lambda p=p: p.fx_history(pair, start, end))
            if value:
                return dict(value), p.is_demo, "+".join(_row_sources(p, "fx_history", pair))
        return {}, False, ""


def dividend_sort_key(e: DividendEvent) -> date:
    """Newest first by ex-date; a resolution without an ex-date sorts by its board date."""
    return e.ex_dividend_date or e.board_date or date.min


def _merge_profiles(a: InstrumentProfile, b: InstrumentProfile) -> InstrumentProfile:
    """Fill ``a``'s gaps from the lower-priority ``b``. A market cap is only borrowed together with the share
    count it was computed from (never mix the archive's official shares with another source's market cap)."""
    updates: dict[str, Any] = {}
    for f in ("summary", "chain_stage", "industry", "listed_date"):
        if getattr(a, f) is None and getattr(b, f) is not None:
            updates[f] = getattr(b, f)
    if not a.themes and b.themes:
        updates["themes"] = b.themes
    if a.shares_outstanding is None and b.shares_outstanding is not None:
        updates["shares_outstanding"], updates["market_cap"] = b.shares_outstanding, b.market_cap
    elif a.market_cap is None and a.shares_outstanding is None:
        updates["market_cap"] = b.market_cap
    updates["data_sources"] = tuple(dict.fromkeys((*a.data_sources, *b.data_sources)))
    updates["is_demo"] = a.is_demo or b.is_demo
    return replace(a, **updates)


def _previous_session(symbol: str, d: date) -> date:
    prev = d - timedelta(days=1)
    if market_of_symbol(symbol) == "US":
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        return prev
    return last_tw_trading_day(prev)


def _merge_quotes(base: QuoteData, other: QuoteData) -> QuoteData:
    """Fill ``base``'s gaps from ``other``; a close from the previous session becomes prev_close."""
    if (base.prev_close is None and other.price is not None and base.trade_date and other.trade_date
            and other.trade_date == _previous_session(base.symbol, base.trade_date)):
        sources = "+".join(dict.fromkeys(x for x in (base.source, other.source) if x))
        base = replace(base, prev_close=other.price, is_demo=base.is_demo or other.is_demo, source=sources)
    return base.merged_with(other)


def _row_sources(provider: BaseProvider, method: str, symbol: str) -> list[str]:
    """Source keys behind a provider's answer: the archive reports its rows' sources, others their name."""
    fn = getattr(provider, "sources_for", None)
    return (fn(method, symbol) or [provider.name]) if fn is not None else [provider.name]


def _apply_reference(q: QuoteData, official: tuple | None, ex: tuple[Decimal, Decimal] | None) -> QuoteData:
    is_fund = is_fund_code(code_of_symbol(q.symbol))
    if official is not None:
        ref, up, down, _source = official
        return replace(q, reference_price=ref, limit_up=up, limit_down=down)
    if q.prev_close is None:
        return q
    base = q.prev_close
    computed = price_limits(base, is_fund)
    if ex is not None:
        cash, ratio = ex
        base, up, down = ex_rights_prices(q.prev_close, cash, ratio, is_fund)
        computed = (up, down)
    published = (q.limit_up, q.limit_down)
    if published[0] is not None and published[1] is not None:
        if ex is not None and computed != published and price_limits(q.prev_close, is_fund) == published:
            # The quote's "previous close" already is the ex-rights reference price (MIS y on an ex-date).
            return replace(q, reference_price=q.prev_close)
        return replace(q, reference_price=base)
    return replace(q, reference_price=base, limit_up=computed[0], limit_down=computed[1])


def build_providers(settings: Settings) -> list[BaseProvider]:
    from forliosa.marketdata.archive_provider import ArchiveProvider
    from forliosa.marketdata.finmind import FinMindProvider
    from forliosa.marketdata.shioaji_data import ShioajiDataProvider
    from forliosa.marketdata.tpex import TpexOpenApiProvider
    from forliosa.marketdata.twse import TwseOpenApiProvider

    fetcher = HttpFetcher(timeout=settings.http_timeout_seconds, retries=1)
    factories: dict[str, Callable[[], BaseProvider]] = {
        "shioaji_data": lambda: ShioajiDataProvider(settings.shioaji_data_base_url, settings.cache_dir, fetcher),
        "twse_openapi": lambda: TwseOpenApiProvider(HttpFetcher(timeout=15, retries=1, backoff=0.5)),
        "tpex_openapi": lambda: TpexOpenApiProvider(HttpFetcher(timeout=15, retries=1, backoff=0.5)),
        "finmind": lambda: FinMindProvider(settings.finmind_token, HttpFetcher(timeout=20, retries=0),
                                           cache_dir=settings.cache_dir),
        "archive": lambda: ArchiveProvider(settings.data_policy,
                                           taifex_confirmed=settings.taifex_conditional_confirmed),
        "demo": lambda: DemoProvider(),
    }
    providers: list[BaseProvider] = []
    for name in settings.market_data_providers:
        key = name.strip().lower()
        factory = factories.get(key)
        if factory is None:
            log.warning("unknown or removed market data provider %r ignored", name)
            continue
        if not provider_allowed(key, settings.data_policy):
            log.info("DATA_POLICY=%s: provider %s is not commercially usable, skipped", settings.data_policy, key)
            continue
        providers.append(factory())
    return providers


_market: MarketData | None = None


def get_market_data() -> MarketData:
    global _market
    if _market is None:
        from forliosa.config import get_settings

        settings = get_settings()
        _market = MarketData(build_providers(settings), jitter=settings.jitter_enabled, policy=settings.data_policy)
    return _market


def set_market_data(md: MarketData | None) -> None:
    global _market
    _market = md


__all__ = ["Answer", "Candle", "MarketData", "build_providers", "code_of_symbol", "get_market_data",
           "market_of_symbol", "set_market_data"]
