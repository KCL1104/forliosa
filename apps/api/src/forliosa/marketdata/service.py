"""MarketData facade: asks providers in the configured order and falls back on failure.

* ``MARKET_DATA_PROVIDERS=shioaji_data,demo`` (comma-separated, highest priority first).
* Quotes are merged field by field: a real provider's price wins; fields it lacks (e.g.
  shioaji-data has no open/high/low/volume) are filled from the next providers and the quote is
  then flagged ``is_demo`` if any filled field came from the demo provider.
* A provider that raises is skipped for a cool-down period (simple circuit breaker).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar

from forliosa.config import Settings
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
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.http import HttpFetcher

log = logging.getLogger(__name__)
T = TypeVar("T")

COOLDOWN_SECONDS = 300
MASTER_TTL_SECONDS = 3600
QUOTE_TTL_SECONDS = 30


@dataclass
class Answer[T]:
    value: T
    is_demo: bool
    source: str


class MarketData:
    def __init__(self, providers: list[BaseProvider], jitter: bool = False):
        self.providers = providers
        self.demo: DemoProvider | None = next((p for p in providers if isinstance(p, DemoProvider)), None)
        if self.demo is not None:
            self.demo.anchor_fn = self._real_anchor
        self.jitter = jitter
        self._down_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._master: dict[str, InstrumentInfo] | None = None
        self._master_at = 0.0
        self._by_code: dict[str, list[str]] = {}
        self._quote_cache: dict[str, tuple[float, QuoteData]] = {}

    # -- provider plumbing -----------------------------------------------------------------------
    def _available(self) -> list[BaseProvider]:
        now = time.monotonic()
        return [p for p in self.providers if self._down_until.get(p.name, 0) <= now]

    def _call(self, provider: BaseProvider, fn: Callable[[], T]) -> T | None:
        try:
            return fn()
        except Exception as exc:  # any upstream failure -> fall back to the next provider
            log.warning("market data provider %s failed: %s", provider.name, exc)
            with self._lock:
                self._down_until[provider.name] = time.monotonic() + COOLDOWN_SECONDS
            return None

    def _first(self, method: str, *args: Any) -> Answer | None:
        for p in self._available():
            value = self._call(p, lambda p=p: getattr(p, method)(*args))
            if value is not None:
                return Answer(value, p.is_demo, p.name)
        return None

    def status(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        return [{"name": p.name, "is_demo": p.is_demo, "available": self._down_until.get(p.name, 0) <= now}
                for p in self.providers]

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
        with self._lock:
            if self._master is not None and time.monotonic() - self._master_at < MASTER_TTL_SECONDS:
                return self._master
        merged: dict[str, InstrumentInfo] = {}
        for p in self._available():
            items = self._call(p, p.instruments)
            for info in items or []:
                merged.setdefault(info.symbol, info)
        by_code: dict[str, list[str]] = {}
        for sym, info in merged.items():
            by_code.setdefault(info.code.upper(), []).append(sym)
        with self._lock:
            self._master, self._master_at, self._by_code = merged, time.monotonic(), by_code
        return merged

    def resolve(self, text: str) -> str | None:
        """'2330' / '2330.tw' / 'aapl' -> canonical symbol, or None if unknown."""
        s = text.strip().upper()
        master = self.master()
        if s.endswith(".TWO"):
            s = s[:-4] + ".TWO"
        if s in master:
            return s
        syms = self._by_code.get(s)
        if syms:
            return sorted(syms)[0]
        return None

    def instrument(self, symbol: str) -> InstrumentInfo | None:
        sym = self.resolve(symbol)
        return self.master().get(sym) if sym else None

    def search(self, q: str, limit: int = 20) -> list[InstrumentInfo]:
        q = q.strip()
        if not q:
            return []
        qu = q.upper()
        scored: list[tuple[tuple, InstrumentInfo]] = []
        for info in self.master().values():
            code = info.code.upper()
            names = [info.name, *info.aliases]
            if code == qu:
                rank = 0
            elif code.startswith(qu):
                rank = 1
            elif any(n == q or n.upper() == qu for n in names):
                rank = 2
            elif any(n.startswith(q) or n.upper().startswith(qu) for n in names):
                rank = 3
            elif any(q in n or qu in n.upper() for n in names):
                rank = 4
            elif qu in code:
                rank = 5
            else:
                continue
            # Prefer Taiwan listings, then shorter codes (0050 before 00500…), then code order.
            scored.append(((rank, info.market == "US", len(info.code), info.code), info))
        scored.sort(key=lambda x: x[0])
        return [info for _, info in scored[:limit]]

    def profile(self, symbol: str) -> InstrumentProfile:
        for p in self._available():
            if p.is_demo:
                continue
            prof = self._call(p, lambda p=p: p.profile(symbol))
            if prof is not None:
                return prof
        info = self.instrument(symbol)
        return InstrumentProfile(
            symbol=symbol, summary=info.summary if info else None, chain_stage=info.chain_stage if info else None,
            data_sources=("內建商品清單",) if info and info.source == "built-in" else (),
        )

    # -- quotes ----------------------------------------------------------------------------------
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
            for p in self._available():
                need = [s for s in pending if s not in partial or partial[s].missing()]
                if not need:
                    break
                got = self._call(p, lambda p=p, need=need: p.quotes(need)) or {}
                for s, q in got.items():
                    partial[s] = partial[s].merged_with(q) if s in partial else q
            for s, q in partial.items():
                if q.price is None:
                    continue
                self._quote_cache[s] = (now, q)
                out[s] = q
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
    def history(self, symbol: str, start: date, end: date) -> HistoryResult:
        ans = self._first("history", symbol, start, end)
        if ans is None:
            return HistoryResult(symbol, [], False, "")
        return HistoryResult(symbol, list(ans.value), ans.is_demo, ans.source)

    def closes(self, symbol: str, start: date, end: date) -> tuple[dict[date, Decimal], bool]:
        h = self.history(symbol, start, end)
        return {c.t: c.c for c in h.candles}, h.is_demo

    def dividends(self, symbol: str) -> Answer[list[DividendEvent]]:
        ans = self._first("dividends", symbol)
        if ans is None:
            return Answer([], False, "")
        return ans

    def corporate_events(self, symbol: str) -> list[CorporateEvent]:
        ans = self._first("corporate_events", symbol)
        return list(ans.value) if ans else []

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

    def fx_series(self, pair: str, start: date, end: date) -> tuple[dict[date, Decimal], bool]:
        ans = self._first("fx_history", pair, start, end)
        if ans is None:
            return {}, False
        return dict(ans.value), ans.is_demo


def build_providers(settings: Settings) -> list[BaseProvider]:
    from forliosa.marketdata.finmind import FinMindProvider
    from forliosa.marketdata.shioaji_data import ShioajiDataProvider
    from forliosa.marketdata.tpex import TpexOpenApiProvider
    from forliosa.marketdata.twse import TwseMisProvider, TwseOpenApiProvider

    fetcher = HttpFetcher(timeout=settings.http_timeout_seconds, retries=1)
    factories: dict[str, Callable[[], BaseProvider]] = {
        "shioaji_data": lambda: ShioajiDataProvider(settings.shioaji_data_base_url, settings.cache_dir, fetcher),
        "twse_openapi": lambda: TwseOpenApiProvider(HttpFetcher(timeout=10, retries=0)),
        "tpex_openapi": lambda: TpexOpenApiProvider(HttpFetcher(timeout=10, retries=0)),
        "twse_mis": lambda: TwseMisProvider(HttpFetcher(timeout=8, retries=0)),
        "finmind": lambda: FinMindProvider(settings.finmind_token, HttpFetcher(timeout=10, retries=0)),
        "demo": lambda: DemoProvider(),
    }
    providers: list[BaseProvider] = []
    for name in settings.market_data_providers:
        factory = factories.get(name.strip().lower())
        if factory is None:
            log.warning("unknown market data provider %r ignored", name)
            continue
        providers.append(factory())
    return providers


_market: MarketData | None = None


def get_market_data() -> MarketData:
    global _market
    if _market is None:
        from forliosa.config import get_settings

        settings = get_settings()
        _market = MarketData(build_providers(settings), jitter=settings.jitter_enabled)
    return _market


def set_market_data(md: MarketData | None) -> None:
    global _market
    _market = md


__all__ = ["Answer", "Candle", "MarketData", "build_providers", "code_of_symbol", "get_market_data",
           "market_of_symbol", "set_market_data"]
