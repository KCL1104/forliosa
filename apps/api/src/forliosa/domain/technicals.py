"""Technical indicators over daily bars (技術指標).

Pure functions over daily bars in date order: no I/O, no clock, no third-party dependency. Prices are used as given.
The archive stores **unadjusted** prices, so an ex-dividend day leaves a gap that nothing here removes.

Conventions
* MA n: simple average of the last n closes; bias (乖離率) = close ÷ MA − 1.
* RSI(14), Wilder: the first average gain / loss is the simple mean of the first 14 changes, then
  avg = (previous avg × 13 + today's) ÷ 14; RSI = 100 × gain ÷ (gain + loss). Undefined (``None``) while both
  averages are 0 (a flat series).
* KD(9,3,3), Taiwan convention: RSV = (close − lowest low of 9 bars) ÷ (highest high − lowest low of 9 bars) × 100;
  K = ⅔·K₋₁ + ⅓·RSV; D = ⅔·D₋₁ + ⅓·K; both start from 50 before the first RSV. RSV is 50 when the 9-bar range is 0.
* MACD(12,26,9) on closes: EMA with α = 2 ÷ (n + 1), seeded with the simple average of the first n values;
  DIF = EMA12 − EMA26; MACD (the signal line) = EMA9 of DIF; OSC (the histogram) = DIF − MACD.
* Bollinger(20, 2): middle = MA20; σ = population standard deviation of the same 20 closes; upper / lower = middle ±
  2σ; %b = (close − lower) ÷ (upper − lower); bandwidth = (upper − lower) ÷ middle.
* Volume ratio (量比): the latest volume ÷ the average volume of the n bars **before** it (n = 5, 20). A bar whose
  volume is missing or 0 has no volume; a window that contains one is not averaged.
* n-day high / low: the highest high and lowest low of the last n bars, the latest included (a bar without a high or
  low uses its close); a "new n-day high" is a bar whose high is above every high of the n − 1 bars before it.
* A cross is a change of sign of (fast − slow); bars where the two are equal keep the previous sign.

``analyze`` turns the series into one compact, rounded snapshot as of the last bar, with the facts of the last
``EVENT_WINDOW`` bars as dated events. Whatever needs more bars than there are is left out and named in ``notes``.
Ratios (``*_pct``, ``percent_b``, ``bandwidth``, ``ratio_*``) are fractions: 0.0123 = 1.23 %.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

MA_PERIODS = (5, 10, 20, 60, 120, 240)
RSI_PERIOD = 14
KD_PERIOD = 9
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BB_PERIOD, BB_WIDTH = 20, 2.0
VOLUME_PERIODS = (5, 20)
RANGE_PERIODS = (20, 60)
EVENT_WINDOW = 10
KD_HIGH, KD_LOW = 80.0, 20.0
# Recursive indicators (RSI, KD, MACD) still carry a trace of their seed with fewer bars than this.
SETTLED_BARS = 100


@dataclass(frozen=True)
class Bar:
    t: date
    c: float
    o: float | None = None
    h: float | None = None
    l: float | None = None  # noqa: E741 - the candle field name used everywhere else
    v: int | None = None


# -- series (aligned with the input; None where there are not enough values yet) ---------------------------------
def sma(xs: Sequence[float], n: int) -> list[float | None]:
    return [math.fsum(xs[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(len(xs))]


def ema(xs: Sequence[float], n: int) -> list[float | None]:
    if len(xs) < n:
        return [None] * len(xs)
    out: list[float | None] = [None] * (n - 1)
    e = math.fsum(xs[:n]) / n
    out.append(e)
    alpha = 2 / (n + 1)
    for x in xs[n:]:
        e += alpha * (x - e)
        out.append(e)
    return out


def rsi(closes: Sequence[float], n: int = RSI_PERIOD) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = math.fsum(max(c, 0.0) for c in changes[:n]) / n
    loss = math.fsum(max(-c, 0.0) for c in changes[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            gain = (gain * (n - 1) + max(changes[i - 1], 0.0)) / n
            loss = (loss * (n - 1) + max(-changes[i - 1], 0.0)) / n
        out[i] = 100 * gain / (gain + loss) if gain + loss > 0 else None
    return out


def stochastic_kd(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
                  n: int = KD_PERIOD) -> tuple[list[float | None], list[float | None]]:
    ks: list[float | None] = [None] * len(closes)
    ds: list[float | None] = [None] * len(closes)
    k = d = 50.0
    for i in range(n - 1, len(closes)):
        hi, lo = max(highs[i - n + 1:i + 1]), min(lows[i - n + 1:i + 1])
        rsv = (closes[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
        k = (2 * k + rsv) / 3
        d = (2 * d + k) / 3
        ks[i], ds[i] = k, d
    return ks, ds


def macd(closes: Sequence[float], fast: int = MACD_FAST, slow: int = MACD_SLOW, signal: int = MACD_SIGNAL
         ) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """(DIF, MACD signal line, OSC histogram)."""
    dif = [f - s if f is not None and s is not None else None
           for f, s in zip(ema(closes, fast), ema(closes, slow), strict=True)]
    known = [x for x in dif if x is not None]
    sig = [None] * (len(dif) - len(known)) + ema(known, signal)
    osc = [x - s if x is not None and s is not None else None for x, s in zip(dif, sig, strict=True)]
    return dif, sig, osc


def bollinger(closes: Sequence[float], n: int = BB_PERIOD, width: float = BB_WIDTH
              ) -> list[tuple[float, float, float] | None]:
    """(middle, upper, lower) per bar."""
    out: list[tuple[float, float, float] | None] = []
    for i in range(len(closes)):
        if i < n - 1:
            out.append(None)
            continue
        window = closes[i - n + 1:i + 1]
        mid = math.fsum(window) / n
        sd = math.sqrt(math.fsum((x - mid) ** 2 for x in window) / n)
        out.append((mid, mid + width * sd, mid - width * sd))
    return out


def crossings(diffs: Sequence[float | None]) -> list[tuple[int, int]]:
    """``(index, +1 | -1)`` wherever ``diffs`` changes sign; zeros and gaps keep the previous sign."""
    out, sign = [], 0
    for i, x in enumerate(diffs):
        if x is None or x == 0:
            continue
        s = 1 if x > 0 else -1
        if sign and s != sign:
            out.append((i, s))
        sign = s
    return out


# -- snapshot ----------------------------------------------------------------------------------------------------
def _px(x: float) -> float:
    return round(x, 2)


def _pct(x: float) -> float:
    return round(x, 4)


def _fmt(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _diff(a: Sequence[float | None], b: Sequence[float | None]) -> list[float | None]:
    return [x - y if x is not None and y is not None else None for x, y in zip(a, b, strict=True)]


def _volume(bars: Sequence[Bar], notes: list[str]) -> dict[str, Any] | None:
    vols = [b.v if b.v is not None and b.v > 0 else None for b in bars]
    latest = vols[-1]
    if latest is None:
        notes.append("最新一日沒有成交量資料，不提供量比")
        return None
    out: dict[str, Any] = {"latest": latest}
    for n in VOLUME_PERIODS:
        window = vols[-n - 1:-1]
        if len(window) < n:
            continue  # named with the other "not enough bars" items
        if any(v is None for v in window):
            notes.append(f"前 {n} 日有缺成交量的日子，不提供對 {n} 日均量的量比")
            continue
        avg = sum(v or 0 for v in window) / n
        out[f"prev{n}_avg"] = round(avg)
        out[f"ratio_prev{n}"] = round(latest / avg, 2)
    return out


def _events(bars: Sequence[Bar], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
            ma: dict[int, list[float | None]], ks: Sequence[float | None], ds: Sequence[float | None],
            osc: Sequence[float | None], bands: Sequence[tuple[float, float, float] | None],
            first: int, provisional: bool) -> list[dict[str, Any]]:
    """Facts of the bars from index ``first`` on, newest first. ``provisional``: the bars from ``first`` on are a
    price standing in for a day that has not closed, so the wording says "this price", not "the close"."""
    subject = "這個價格" if provisional else "收盤價"
    found: list[tuple[int, int, str, str]] = []  # (bar index, order within the day, type, text)

    def add(i: int, order: int, kind: str, text: str) -> None:
        if i >= first:
            found.append((i, order, kind, text))

    for order, (fast, slow) in enumerate(((5, 20), (20, 60))):
        for i, s in crossings(_diff(ma[fast], ma[slow])):
            add(i, order, f"ma{fast}_ma{slow}_cross_{'up' if s > 0 else 'down'}",
                f"{fast} 日均線由下往上穿越 {slow} 日均線（黃金交叉）" if s > 0
                else f"{fast} 日均線由上往下跌破 {slow} 日均線（死亡交叉）")
    for i, s in crossings(_diff(ks, ds)):
        k, d = ks[i] or 0.0, ds[i] or 0.0  # a cross only exists where both are known
        zone = ("80 以上的高檔區" if max(k, d) >= KD_HIGH else "20 以下的低檔區" if min(k, d) <= KD_LOW
                else "20 到 80 之間")
        add(i, 2, f"kd_cross_{'up' if s > 0 else 'down'}",
            f"K 值由{'下往上穿越' if s > 0 else '上往下跌破'} D 值（K {k:.1f}、D {d:.1f}，在 {zone}）")
    for i, s in crossings(osc):
        add(i, 3, f"macd_osc_turn_{'positive' if s > 0 else 'negative'}",
            f"MACD 柱狀體（OSC）由{'負轉正' if s > 0 else '正轉負'}")
    for i in range(first, len(bars)):
        band = bands[i]
        if band is not None and closes[i] > band[1]:
            add(i, 4, "close_above_bollinger_upper",
                f"{subject} {_fmt(closes[i])} 高於布林通道上軌 {_fmt(band[1])}")
        elif band is not None and closes[i] < band[2]:
            add(i, 4, "close_below_bollinger_lower",
                f"{subject} {_fmt(closes[i])} 低於布林通道下軌 {_fmt(band[2])}")
        for n in sorted(RANGE_PERIODS, reverse=True):  # a 60-day extreme is also a 20-day one: say the longer
            if i < n - 1:
                continue
            if highs[i] > max(highs[i - n + 1:i]):
                add(i, 5, f"new_high_{n}d",
                    f"{subject} {_fmt(highs[i])} 高於前 {n - 1} 個交易日的最高價（{n} 日新高）" if provisional
                    else f"最高價 {_fmt(highs[i])} 創 {n} 日新高")
                break
        for n in sorted(RANGE_PERIODS, reverse=True):
            if i < n - 1:
                continue
            if lows[i] < min(lows[i - n + 1:i]):
                add(i, 6, f"new_low_{n}d",
                    f"{subject} {_fmt(lows[i])} 低於前 {n - 1} 個交易日的最低價（{n} 日新低）" if provisional
                    else f"最低價 {_fmt(lows[i])} 創 {n} 日新低")
                break
    found.sort(key=lambda e: (-e[0], e[1]))
    return [{"date": bars[i].t, "type": kind, "text": text} for i, _order, kind, text in found]


def analyze(bars: Sequence[Bar], *, provisional: bool = False, window: int = EVENT_WINDOW) -> dict[str, Any]:
    """Indicators as of the last bar of ``bars`` (date order, at least one bar).

    ``provisional``: the last bar is a price for a day that has not closed (open / high / low unknown and equal to
    the price, no volume). Volume and the opening gap are left out, and ``events`` only holds what that bar itself
    would add; ``notes`` say what the stand-in values distort.
    """
    if not bars:
        raise ValueError("no bars")
    n = len(bars)
    last = bars[-1]
    closes = [b.c for b in bars]
    highs = [b.h if b.h is not None else b.c for b in bars]
    lows = [b.l if b.l is not None else b.c for b in bars]
    notes: list[str] = []
    short: list[str] = []  # what there are not enough bars for

    def need(count: int, name: str) -> bool:
        if n < count:
            short.append(f"{name}（需 {count} 根）")
            return False
        return True

    out: dict[str, Any] = {"date": last.t, "close": _px(last.c)}
    if n >= 2:
        prev = bars[-2]
        out["prev_close"] = {"date": prev.t, "close": _px(prev.c)}
        out["change"] = _px(last.c - prev.c)
        out["change_pct"] = _pct(last.c / prev.c - 1) if prev.c else None
        if not provisional:
            if last.o is not None and prev.c:
                out["open_gap_pct"] = _pct(last.o / prev.c - 1)
            if lows[-1] > highs[-2]:
                out["gap"] = "up"  # the whole bar is above the previous bar's high
            elif highs[-1] < lows[-2]:
                out["gap"] = "down"
        direction = _sign(closes[-1] - closes[-2])
        days = 1
        while days < n - 1 and _sign(closes[-days - 1] - closes[-days - 2]) == direction:
            days += 1
        out["streak"] = {"direction": {1: "up", -1: "down", 0: "flat"}[direction], "days": days}

    ma = {p: sma(closes, p) for p in MA_PERIODS}
    averages: dict[str, Any] = {}
    for p in MA_PERIODS:
        value = ma[p][-1]
        if need(p, f"MA{p}") and value is not None:
            averages[f"ma{p}"] = {"value": _px(value), "bias_pct": _pct(last.c / value - 1) if value else None}
    if averages:
        out["ma"] = averages

    if need(RSI_PERIOD + 1, f"RSI{RSI_PERIOD}"):
        value = rsi(closes)[-1]
        if value is None:
            notes.append(f"RSI{RSI_PERIOD} 無法計算：這段期間收盤價沒有變動")
        else:
            out[f"rsi{RSI_PERIOD}"] = round(value, 2)

    ks, ds = stochastic_kd(highs, lows, closes)
    k, d = ks[-1], ds[-1]
    if need(KD_PERIOD, "KD") and k is not None and d is not None:
        out["kd"] = {"k": round(k, 2), "d": round(d, 2)}
    if any(b.h is None or b.l is None for b in bars[-max(RANGE_PERIODS):]):
        notes.append("部分日子缺最高價或最低價，以收盤價代替（影響 KD 與區間高低點）")

    dif, sig, osc = macd(closes)
    if need(MACD_SLOW + MACD_SIGNAL - 1, "MACD"):
        out["macd"] = {name: round(series[-1] or 0.0, 3) for name, series in (("dif", dif), ("macd", sig),
                                                                              ("osc", osc))}

    bands = bollinger(closes)
    band = bands[-1]
    if need(BB_PERIOD, "布林通道") and band is not None:
        mid, upper, lower = band
        out["bollinger"] = {"upper": _px(upper), "mid": _px(mid), "lower": _px(lower),
                            "percent_b": _pct((last.c - lower) / (upper - lower)) if upper > lower else None,
                            "bandwidth": _pct((upper - lower) / mid) if mid else None}

    if not provisional:
        volume = _volume(bars, notes)
        if volume is not None:
            for p in VOLUME_PERIODS:
                need(p + 1, f"{p} 日量比")
            out["volume"] = volume

    ranges: dict[str, Any] = {}
    for p in RANGE_PERIODS:
        if not need(p, f"{p} 日高低點"):
            continue
        hi = max(range(n - p, n), key=lambda i: (highs[i], i))  # the latest day when equal
        lo = min(range(n - p, n), key=lambda i: (lows[i], -i))
        ranges[f"{p}d"] = {
            "high": _px(highs[hi]), "high_date": bars[hi].t, "low": _px(lows[lo]), "low_date": bars[lo].t,
            "close_vs_high_pct": _pct(last.c / highs[hi] - 1) if highs[hi] else None,
            "close_vs_low_pct": _pct(last.c / lows[lo] - 1) if lows[lo] else None,
        }
    if ranges:
        out["high_low"] = ranges

    first = n - 1 if provisional else max(0, n - window)
    out["events"] = _events(bars, highs, lows, closes, ma, ks, ds, osc, bands, first, provisional)

    if short:
        counted = f"{n} 根（含今天的暫定價；" if provisional else f"{n} 根（"
        notes.insert(0, f"日 K 只有 {counted}{bars[0].t.isoformat()} 起），不足以計算：{'、'.join(short)}")
    if KD_PERIOD <= n < SETTLED_BARS:
        notes.append(f"RSI、KD、MACD 是逐日遞迴計算的指標；目前只有 {n} 根日 K，"
                     "數值可能和用更長歷史計算的看盤軟體略有不同")
    if provisional:
        notes.append("今天的開盤、最高、最低價未知，都以這個價格代替：KD 與區間高低點只反映這個價格；"
                     "沒有今天的成交量，不提供量比")
    out["notes"] = notes
    return out
