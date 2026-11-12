"""Deterministic synthetic market data (everything it returns is flagged ``is_demo``).

Daily closes are a seeded geometric random walk per symbol, generated sequentially from a fixed
start date so that the shape of the past never changes. The whole path is then scaled so that the
last close equals an *anchor*: the real latest close (from shioaji-data) when the facade can
supply one, otherwise a built-in value. Prices are unadjusted: they drop on synthetic ex-dividend
dates by the dividend, by the share ratio on stock dividends and splits — so a ledger that records
those dividends as transactions values consistently.
"""

from __future__ import annotations

import math
import random
import threading
import zlib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from forliosa.domain.ticks import tick_size
from forliosa.marketdata.base import (
    BaseProvider,
    Candle,
    CorporateEvent,
    DividendEvent,
    InstrumentInfo,
    InstrumentProfile,
    QuarterFundamentals,
    QuoteData,
    ValuationInputs,
    code_of_symbol,
    market_of_symbol,
)
from forliosa.marketdata.catalog import (
    DEMO_SPECS,
    ETF_CODES,
    FALLBACK_TW_STOCKS,
    TW_ETFS,
    US_TICKERS,
    DemoSpec,
    default_spec,
)
from forliosa.timeutil import (
    TAIPEI,
    is_tw_trading_day,
    last_tw_trading_day,
    market_close_dt,
    now_taipei,
    tw_trading_days,
)

DEMO_START = date(2018, 1, 2)
AnchorFn = Callable[[str], tuple[date, Decimal] | None]


def stable_seed(text: str) -> int:
    return zlib.crc32(text.encode("utf-8"))


def tw_tick(price: Decimal, is_etf: bool) -> Decimal:
    """Taiwan tick size (升降單位); see :mod:`forliosa.domain.ticks`."""
    return tick_size(price, is_etf)


def round_price(value: float, symbol: str) -> Decimal:
    d = Decimal(repr(value))
    if market_of_symbol(symbol) == "US":
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tick = tw_tick(d, code_of_symbol(symbol) in ETF_CODES or code_of_symbol(symbol).startswith("00"))
    return ((d / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick).normalize() + Decimal("0.00")


@dataclass
class _Path:
    symbol: str
    days: list[date]
    candles: list[Candle]
    dividends: list[DividendEvent]
    events: list[CorporateEvent]
    index: dict[date, int]


def _weekdays(start: date, end: date) -> list[date]:
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _on_or_after(d: date, cal_set: set[date], last: date) -> date | None:
    for _ in range(10):
        if d in cal_set:
            return d
        d += timedelta(days=1)
        if d > last:
            return None
    return None


class DemoProvider(BaseProvider):
    name = "demo"
    is_demo = True

    def __init__(self, anchor_fn: AnchorFn | None = None, today_fn: Callable[[], datetime] = now_taipei,
                 jitter: bool = False):
        self.anchor_fn = anchor_fn
        self.today_fn = today_fn
        self.jitter = jitter
        self._cache: OrderedDict[tuple, _Path] = OrderedDict()
        self._lock = threading.Lock()
        self._fx_cache: dict[date, Decimal] | None = None
        self._fx_end: date | None = None

    # -- instrument master -------------------------------------------------------------------
    def instruments(self) -> list[InstrumentInfo]:
        return [*FALLBACK_TW_STOCKS, *TW_ETFS, *US_TICKERS]

    def profile(self, symbol: str) -> InstrumentProfile | None:
        return InstrumentProfile(symbol=symbol, is_demo=True, data_sources=("示範資料（模擬）",))

    # -- prices ------------------------------------------------------------------------------
    def _spec(self, symbol: str) -> DemoSpec:
        spec = DEMO_SPECS.get(symbol)
        if spec is not None:
            return spec
        seed = stable_seed(symbol)
        base = Decimal(20 + seed % 480)
        return default_spec(symbol, base, seed)

    def _default_anchor_date(self, symbol: str) -> date:
        now = self.today_fn().astimezone(TAIPEI)
        if market_of_symbol(symbol) == "US":
            ny = now.astimezone(ZoneInfo("America/New_York"))
            d = ny.date() if ny.time() >= time(16, 0) else ny.date() - timedelta(days=1)
            while d.weekday() >= 5:  # latest completed US session (holidays ignored in demo data)
                d -= timedelta(days=1)
            return d
        d = now.date()
        if now.hour < 14:  # before the close is published, the last close is the previous day's
            d -= timedelta(days=1)
        return last_tw_trading_day(d)

    def _anchor(self, symbol: str) -> tuple[date, Decimal]:
        if self.anchor_fn is not None:
            try:
                real = self.anchor_fn(symbol)
            except Exception:  # anchors are best-effort
                real = None
            if real is not None:
                return real
        return self._default_anchor_date(symbol), self._spec(symbol).anchor

    def _path(self, symbol: str) -> _Path:
        anchor_date, anchor_price = self._anchor(symbol)
        key = (symbol, anchor_date, anchor_price)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        path = self._generate(symbol, self._spec(symbol), anchor_date, anchor_price)
        with self._lock:
            self._cache[key] = path
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
        return path

    def _generate(self, symbol: str, spec: DemoSpec, anchor_date: date, anchor_price: Decimal) -> _Path:
        is_us = market_of_symbol(symbol) == "US"
        horizon = anchor_date + timedelta(days=120)  # announced (future) dividends
        days = _weekdays(DEMO_START, anchor_date) if is_us else tw_trading_days(DEMO_START, anchor_date)
        future_days = _weekdays(anchor_date, horizon) if is_us else tw_trading_days(anchor_date, horizon)
        cal_set = set(days) | set(future_days)
        last_cal = future_days[-1] if future_days else anchor_date

        # Distribution and corporate-action dates.
        dist: dict[date, tuple[float, Decimal]] = {}
        for year in range(DEMO_START.year, horizon.year + 1):
            for i, month in enumerate(spec.div_months):
                d0 = date(year, month, min(spec.div_day, 28))
                ex = _on_or_after(d0, cal_set, last_cal)
                if ex is None or ex <= DEMO_START:
                    continue
                stock = spec.stock_dividends.get(year, Decimal(0)) if i == 0 else Decimal(0)
                dist[ex] = (spec.div_yield, stock)
        splits = {d: r for d, r in spec.splits if DEMO_START < d <= anchor_date}

        rng = random.Random(stable_seed(symbol))
        mu = spec.drift / 252.0
        sig = spec.vol / math.sqrt(252.0)
        raw: list[float] = []
        x = 100.0
        for i, d in enumerate(days):
            if i:
                x *= math.exp(mu - 0.5 * sig * sig + sig * rng.gauss(0.0, 1.0))
                if d in dist:
                    y, stock = dist[d]
                    x *= 1.0 - y
                    x /= 1.0 + float(stock) / 10.0
                if d in splits:
                    x /= float(splits[d])
            raw.append(x)
        raw = _bridge(raw, days, spec.waypoints, float(anchor_price))
        closes = [round_price(v, symbol) for v in raw]
        closes[-1] = anchor_price

        # OHLC + volume from an independent stream so closes never depend on it.
        orng = random.Random(stable_seed(symbol + "#ohlc"))
        candles: list[Candle] = []
        prev = closes[0]
        for i, d in enumerate(days):
            c = closes[i]
            ref = float(prev)
            if d in dist:
                y, stock = dist[d]
                ref = ref * (1.0 - y) / (1.0 + float(stock) / 10.0)
            if d in splits:
                ref = ref / float(splits[d])
            gap = orng.gauss(0.0, sig * 0.35)
            o = round_price(ref * math.exp(gap), symbol) if i else c
            hi_f = max(float(o), float(c)) * (1.0 + abs(orng.gauss(0.0, sig * 0.5)))
            lo_f = min(float(o), float(c)) * (1.0 - abs(orng.gauss(0.0, sig * 0.5)))
            h = max(round_price(hi_f, symbol), o, c)
            low = min(round_price(lo_f, symbol), o, c)
            v = int(spec.base_volume * math.exp(orng.gauss(0.0, 0.35)))
            if not is_us:
                v = max(1000, v // 1000 * 1000)
            candles.append(Candle(d, o, h, low, c, v))
            prev = c

        index = {d: i for i, d in enumerate(days)}
        dividends: list[DividendEvent] = []
        places = Decimal("0.01") if not code_of_symbol(symbol).startswith("00") else Decimal("0.001")
        if is_us:
            places = Decimal("0.0001")
        for ex in sorted(dist):
            y, stock = dist[ex]
            if ex in index:
                i = index[ex]
                prev_close = closes[i - 1] if i else closes[0]
            else:
                prev_close = closes[-1]  # announced, not yet ex
            cash = (prev_close * Decimal(repr(y))).quantize(places, rounding=ROUND_HALF_UP)
            pay = ex + timedelta(days=spec.pay_lag_days)
            n = len(spec.div_months)
            if n == 1:
                period = str(ex.year - 1) if ex.month <= 9 else str(ex.year)
            elif n == 2:
                period = f"{ex.year}H{1 if ex.month <= 6 else 2}"
            elif n == 4:
                period = f"{ex.year}Q{(ex.month - 1) // 3 + 1}"
            else:
                period = f"{ex.year}-{ex.month:02d}"
            dividends.append(DividendEvent(symbol, ex.year, period, cash, stock, ex, pay, is_demo=True))
        events = [CorporateEvent(symbol, d, "split", r) for d, r in sorted(splits.items())]
        return _Path(symbol, days, candles, dividends, events, index)

    def history(self, symbol: str, start: date, end: date) -> list[Candle]:
        path = self._path(symbol)
        return [c for c in path.candles if start <= c.t <= end]

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData]:
        out: dict[str, QuoteData] = {}
        for s in symbols:
            path = self._path(s)
            if not path.candles:
                continue
            last = path.candles[-1]
            prev = path.candles[-2].c if len(path.candles) > 1 else last.c
            # Undo ex-date / split drops for "prev_close" like exchanges do (參考價): keep it simple —
            # the previous close as published.
            out[s] = QuoteData(
                symbol=s, price=last.c, prev_close=prev, open=last.o, high=last.h, low=last.l, volume=last.v,
                as_of=_close_dt(s, last.t), trade_date=last.t, is_realtime=False, is_demo=True,
                source="demo",
            )
        return out

    def jittered(self, quote: QuoteData) -> QuoteData:
        """Dev-only: wiggle a quote a little so the SSE stream visibly updates (always is_demo)."""
        if quote.price is None:
            return quote
        rng = random.Random()
        drift = Decimal(repr(rng.gauss(0.0, 0.0015)))
        price = round_price(float(quote.price * (1 + drift)), quote.symbol)
        high = max(quote.high or price, price)
        low = min(quote.low or price, price)
        return replace(
            quote, price=price, high=high, low=low, volume=(quote.volume or 0) + rng.randint(0, 50) * 1000,
            as_of=self.today_fn(), is_realtime=True, is_demo=True, source=(quote.source or "demo") + "+jitter",
        )

    def dividends(self, symbol: str) -> list[DividendEvent]:
        return list(self._path(symbol).dividends)

    def ex_rights_on(self, symbols: list[str], d: date) -> dict[str, tuple[Decimal, Decimal]]:
        out = {}
        for s in symbols:
            for e in self._path(s).dividends:
                if e.ex_dividend_date == d and (e.cash_dividend or e.stock_dividend):
                    out[s] = (e.cash_dividend, e.stock_dividend / 10)
        return out

    def corporate_events(self, symbol: str) -> list[CorporateEvent]:
        return list(self._path(symbol).events)

    # -- fundamentals --------------------------------------------------------------------------
    def valuation_inputs(self, symbol: str) -> ValuationInputs | None:
        code = code_of_symbol(symbol)
        if code.startswith("00") or symbol in ("VOO", "QQQ"):
            return None  # ETFs have no EPS / book value
        spec = self._spec(symbol)
        _, anchor = self._anchor(symbol)
        today = self.today_fn().date()
        # Latest quarter whose report is out (Q1 by 5/15, Q2 by 8/14, Q3 by 11/14, Q4 by 3/31).
        latest_year, latest_q = _latest_reported_quarter(today)
        ttm_eps_now = float(anchor) / spec.target_per
        bvps_now = float(anchor) / spec.target_pbr
        rng = random.Random(stable_seed(symbol + "#fund"))
        quarters: list[QuarterFundamentals] = []
        n_quarters = (latest_year - DEMO_START.year + 1) * 4
        y, q = latest_year, latest_q
        raw: list[tuple[str, float, float]] = []
        for n in range(n_quarters):
            years_back = n / 4.0
            eps = ttm_eps_now / 4.0 / (1.0 + spec.eps_growth) ** years_back * (1.0 + rng.gauss(0.0, 0.06))
            bv = bvps_now / 1.08 ** years_back
            raw.append((f"{y}Q{q}", eps, bv))
            q -= 1
            if q == 0:
                y, q = y - 1, 4
        for period, eps, bv in reversed(raw):
            quarters.append(QuarterFundamentals(
                period,
                Decimal(repr(eps)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                Decimal(repr(bv)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            ))
        return ValuationInputs(symbol, tuple(quarters), is_demo=True, source="demo")

    # -- FX ------------------------------------------------------------------------------------
    def fx_history(self, pair: str, start: date, end: date) -> dict[date, Decimal] | None:
        if pair != "USDTWD":
            return None
        today = self.today_fn().date()
        with self._lock:
            if self._fx_cache is None or self._fx_end != today:
                rng = random.Random(stable_seed("USDTWD"))
                x = 31.5
                series: dict[date, Decimal] = {}
                for d in _weekdays(DEMO_START, today):
                    x += 0.02 * (31.5 - x) + rng.gauss(0.0, 0.08)
                    x = min(33.0, max(30.0, x))
                    series[d] = Decimal(repr(x)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                self._fx_cache, self._fx_end = series, today
            cache = self._fx_cache
        return {d: v for d, v in cache.items() if start <= d <= end}


def _bridge(raw: list[float], days: list[date], waypoints: tuple[tuple[str, str], ...],
            anchor: float) -> list[float]:
    """Bend the path (in log space, linearly between points) through the waypoints and the anchor."""
    idx_of = {d: i for i, d in enumerate(days)}
    targets: list[tuple[int, float]] = []
    for ds, px in waypoints:
        d = date.fromisoformat(ds)
        for _ in range(10):  # first trading day on/after the waypoint date
            if d in idx_of:
                break
            d += timedelta(days=1)
        i = idx_of.get(d)
        if i is not None and i < len(raw) - 1:
            targets.append((i, float(px)))
    targets.append((len(raw) - 1, anchor))
    corr = [math.log(px) - math.log(raw[i]) for i, px in targets]
    out = list(raw)
    j = 0
    for i in range(len(raw)):
        while j < len(targets) - 1 and i > targets[j][0]:
            j += 1
        i1, c1 = targets[j][0], corr[j]
        if j == 0 or i >= i1:
            c = c1
        else:
            i0, c0 = targets[j - 1][0], corr[j - 1]
            c = c0 + (c1 - c0) * (i - i0) / (i1 - i0)
        out[i] = raw[i] * math.exp(c)
    return out


def _close_dt(symbol: str, d: date) -> datetime:
    if market_of_symbol(symbol) == "US":
        return datetime.combine(d, time(16, 0), ZoneInfo("America/New_York"))
    return market_close_dt(d)


def _latest_reported_quarter(today: date) -> tuple[int, int]:
    y = today.year
    if today >= date(y, 11, 14):
        return y, 3
    if today >= date(y, 8, 14):
        return y, 2
    if today >= date(y, 5, 15):
        return y, 1
    if today >= date(y, 3, 31):
        return y - 1, 4
    return y - 1, 3


def report_publication_date(period: str) -> date:
    """Latest legal publication date of a quarterly report (台灣上市櫃一般業財報期限)."""
    year, q = int(period[:4]), int(period[-1])
    return {
        1: date(year, 5, 15),
        2: date(year, 8, 14),
        3: date(year, 11, 14),
        4: date(year + 1, 3, 31),
    }[q]


__all__ = ["DemoProvider", "is_tw_trading_day", "report_publication_date", "round_price", "tw_tick"]
