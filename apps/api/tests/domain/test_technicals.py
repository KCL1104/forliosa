"""Technical indicators: worked examples checked by hand, closed-form series and independent re-computations."""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, pstdev

import pytest

from forliosa.domain import technicals as ta
from forliosa.domain.technicals import Bar, analyze

START = date(2026, 6, 1)


def day(i: int) -> date:
    return START + timedelta(days=i)


def bars(closes, highs=None, lows=None, opens=None, volumes=None) -> list[Bar]:
    return [Bar(t=day(i), c=c, o=opens[i] if opens else c, h=highs[i] if highs else c,
                l=lows[i] if lows else c, v=volumes[i] if volumes else 1000)
            for i, c in enumerate(closes)]


def approx(values, expected, tol=1e-9):
    assert len(values) == len(expected)
    for got, want in zip(values, expected, strict=True):
        assert (got is None) == (want is None), (got, want)
        if want is not None:
            assert got == pytest.approx(want, abs=tol), (got, want)


# -- moving averages ---------------------------------------------------------------------------------------------
def test_sma_ema_worked_examples():
    assert ta.sma([1, 2, 3, 4, 5, 6], 3) == [None, None, 2, 3, 4, 5]
    # EMA(3): seed = mean(10, 11, 12) = 11, α = 2 ÷ 4 = 0.5 → 11 + 0.5 × (13 − 11) = 12, 12, 11.5
    assert ta.ema([10, 11, 12, 13, 12, 11], 3) == [None, None, 11, 12, 12, 11.5]
    assert ta.ema([1, 2], 3) == [None, None]


def test_moving_averages_and_bias():
    out = analyze(bars([float(x) for x in range(1, 11)]))  # closes 1 … 10
    assert out["ma"] == {"ma5": {"value": 8.0, "bias_pct": 0.25}, "ma10": {"value": 5.5, "bias_pct": 0.8182}}
    note = out["notes"][0]
    assert note.startswith("日 K 只有 10 根（2026-06-01 起），不足以計算：")
    for name in ("MA20（需 20 根）", "MA60（需 60 根）", "MA120（需 120 根）", "MA240（需 240 根）",
                 "RSI14（需 15 根）", "MACD（需 34 根）", "布林通道（需 20 根）", "20 日高低點（需 20 根）",
                 "20 日量比（需 21 根）"):
        assert name in note, name
    assert "MA5" not in note and "KD（" not in note and "5 日量比" not in note
    full = analyze(bars([100.0 + (i % 7) for i in range(250)]))
    assert set(full["ma"]) == {"ma5", "ma10", "ma20", "ma60", "ma120", "ma240"} and full["notes"] == []
    closes = [100.0 + (i % 7) for i in range(250)]
    assert full["ma"]["ma240"]["value"] == round(mean(closes[-240:]), 2)
    assert full["ma"]["ma60"]["bias_pct"] == round(closes[-1] / mean(closes[-60:]) - 1, 4)


# -- RSI ---------------------------------------------------------------------------------------------------------
# The 33 closes of the RSI worksheet reproduced in many technical-analysis references (QQQQ, 2009-12 to 2010-02).
RSI_CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
              46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18,
              44.22, 44.57, 43.42, 42.66, 43.13]
# Wilder's formulas on those 2-decimal closes. The first value by hand: the 14 changes are −0.25 +0.06 −0.54 +0.72
# +0.50 +0.27 +0.32 +0.42 +0.24 −0.19 +0.14 −0.42 +0.67 0 → gains 3.34 (avg 0.238571), losses 1.40 (avg 0.1) →
# RS 2.3857 → RSI = 100 − 100 ÷ 3.3857 = 70.46.
RSI_EXPECTED = [70.46, 66.25, 66.48, 69.35, 66.29, 57.92, 62.88, 63.21, 56.01, 62.34, 54.67, 50.39, 40.02, 41.49,
                41.90, 45.50, 37.32, 33.09, 37.79]
# The worksheet's own column (computed from unrounded closes, so a few hundredths away).
RSI_WORKSHEET = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
                 41.87, 45.46, 37.30, 33.08, 37.77]


def reference_rsi(closes, n=14):
    """Wilder's RSI written the long way (RS, then 100 − 100 ÷ (1 + RS))."""
    out = [None] * len(closes)
    ups = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    downs = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    avg_up, avg_down = sum(ups[:n]) / n, sum(downs[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            avg_up = (avg_up * 13 + ups[i - 1]) / 14
            avg_down = (avg_down * 13 + downs[i - 1]) / 14
        out[i] = 100.0 if avg_down == 0 else 100 - 100 / (1 + avg_up / avg_down)
    return out


def test_rsi_textbook_example():
    got = ta.rsi(RSI_CLOSES)
    assert got[:14] == [None] * 14
    assert [round(x, 2) for x in got[14:]] == RSI_EXPECTED
    approx(got, reference_rsi(RSI_CLOSES))
    for mine, published in zip(got[14:], RSI_WORKSHEET, strict=True):
        assert mine == pytest.approx(published, abs=0.08)
    assert analyze(bars(RSI_CLOSES))["rsi14"] == 37.79


def test_rsi_edge_cases():
    assert ta.rsi([float(i) for i in range(20)])[-1] == 100  # only gains
    assert ta.rsi([float(-i) for i in range(20)])[-1] == 0  # only losses
    assert ta.rsi([100.0 + (i % 2) for i in range(15)])[14] == 50  # seven +1 and seven −1
    assert ta.rsi([5.0] * 14) == [None] * 14  # 14 closes are 13 changes: not enough
    flat = analyze(bars([50.0] * 40))
    assert "rsi14" not in flat and "RSI14 無法計算：這段期間收盤價沒有變動" in flat["notes"]


# -- KD (Taiwan convention) --------------------------------------------------------------------------------------
def test_kd_worked_example():
    highs = [104, 105, 106, 107, 108, 109, 110, 109, 109, 112, 111]
    lows = [100, 101, 102, 103, 104, 105, 106, 105, 106, 107, 104]
    closes = [102, 103, 104, 105, 106, 107, 108, 107, 108, 112, 104.3]
    ks, ds = ta.stochastic_kd(highs, lows, closes)
    assert ks[:8] == [None] * 8 and ds[:8] == [None] * 8
    # bar 9: 9-bar high 110, low 100, close 108 → RSV 80 → K = ⅔·50 + ⅓·80 = 60, D = ⅔·50 + ⅓·60 = 53.33
    assert ks[8] == pytest.approx(60) and ds[8] == pytest.approx(160 / 3)
    # bar 10: high 112, low 101, close 112 → RSV 100 → K = (120 + 100) ÷ 3 = 73.33, D = (106.67 + 73.33) ÷ 3 = 60
    assert ks[9] == pytest.approx(220 / 3) and ds[9] == pytest.approx(60)
    # bar 11: high 112, low 102, close 104.3 → RSV 23 → K = (146.67 + 23) ÷ 3 = 56.56, D = (120 + 56.56) ÷ 3 = 58.85
    assert ks[10] == pytest.approx(56.5556, abs=1e-4) and ds[10] == pytest.approx(58.8519, abs=1e-4)
    out = analyze(bars(closes, highs=highs, lows=lows))
    assert out["kd"] == {"k": 56.56, "d": 58.85}
    # K fell below D on bar 11 (73.3 > 60 the day before): a dated fact, with the zone it happened in
    assert out["events"][0] == {"date": day(10), "type": "kd_cross_down",
                                "text": "K 值由上往下跌破 D 值（K 56.6、D 58.9，在 20 到 80 之間）"}


def test_kd_flat_window_and_missing_high_low():
    ks, ds = ta.stochastic_kd([10.0] * 12, [10.0] * 12, [10.0] * 12)
    assert ks[-1] == 50 and ds[-1] == 50  # no range: RSV 50, so K and D stay at the seed
    closes = [100.0 - i for i in range(30)] + [71.5]
    no_hl = [Bar(t=day(i), c=c) for i, c in enumerate(closes)]
    out = analyze(no_hl)
    with_hl = analyze(bars(closes))  # high = low = close gives the same KD
    assert out["kd"] == with_hl["kd"]
    assert "部分日子缺最高價或最低價，以收盤價代替（影響 KD 與區間高低點）" in out["notes"]
    assert not any("缺最高價" in n for n in with_hl["notes"])
    # 30 falling closes push K and D to the floor; the first up day lifts K over D in the low zone
    cross = out["events"][0]
    assert cross["type"] == "kd_cross_up" and cross["date"] == day(30) and "在 20 以下的低檔區" in cross["text"]


# -- MACD --------------------------------------------------------------------------------------------------------
def reference_macd(closes):
    """DIF / signal / histogram from explicit EMA recursions (SMA seed)."""
    def ema_at(values, n):
        out = {}
        for i in range(n - 1, len(values)):
            out[i] = sum(values[:n]) / n if i == n - 1 else values[i] * 2 / (n + 1) + out[i - 1] * (1 - 2 / (n + 1))
        return out

    e12, e26 = ema_at(closes, 12), ema_at(closes, 26)
    dif = {i: e12[i] - e26[i] for i in e26}
    start = min(dif)
    sig = {start + i: v for i, v in ema_at([dif[i] for i in sorted(dif)], 9).items()}
    return ([dif.get(i) for i in range(len(closes))], [sig.get(i) for i in range(len(closes))],
            [dif[i] - sig[i] if i in sig else None for i in range(len(closes))])


def test_macd_closed_form_on_a_straight_line():
    # A line rising 2 a day: an SMA-seeded EMA(n) trails the price by exactly 2 × (n − 1) ÷ 2, so
    # DIF = (p − 11) − (p − 25) = 14 on every bar, the signal line is 14 and the histogram 0.
    dif, sig, osc = ta.macd([100.0 + 2 * i for i in range(60)])
    assert dif[:25] == [None] * 25 and sig[:33] == [None] * 33 and osc[:33] == [None] * 33
    approx(dif[25:], [14.0] * 35)
    approx(sig[33:], [14.0] * 27)
    approx(osc[33:], [0.0] * 27)


def test_macd_matches_an_independent_computation():
    closes = [100 + 10 * math.sin(i / 5) + 0.3 * i for i in range(90)]
    for got, want in zip(ta.macd(closes), reference_macd(closes), strict=True):
        approx(got, want)
    out = analyze(bars(closes))
    dif, sig, osc = reference_macd(closes)
    assert out["macd"] == {"dif": round(dif[-1], 3), "macd": round(sig[-1], 3), "osc": round(osc[-1], 3)}
    assert "MACD" in analyze(bars(closes[:33]))["notes"][0] and "macd" not in analyze(bars(closes[:33]))
    assert "macd" in analyze(bars(closes[:34]))


# -- Bollinger ---------------------------------------------------------------------------------------------------
def test_bollinger_worked_example():
    closes = [9.0] * 10 + [11.0] * 10  # mean 10, population σ 1 → bands 12 / 8
    assert ta.bollinger(closes)[-1] == (10.0, 12.0, 8.0) and ta.bollinger(closes)[18] is None
    out = analyze(bars(closes))
    assert out["bollinger"] == {"upper": 12.0, "mid": 10.0, "lower": 8.0, "percent_b": 0.75, "bandwidth": 0.4}
    wavy = [50 + 3 * math.sin(i) + i * 0.1 for i in range(45)]
    mid, upper, lower = ta.bollinger(wavy)[-1]
    assert mid == pytest.approx(mean(wavy[-20:])) and upper - mid == pytest.approx(2 * pstdev(wavy[-20:]))
    assert mid - lower == pytest.approx(upper - mid)


# -- volume ------------------------------------------------------------------------------------------------------
def test_volume_ratio_uses_the_bars_before_the_latest():
    volumes = [1000] * 15 + [2000] * 5 + [6000]
    out = analyze(bars([10.0] * 21, volumes=volumes))
    assert out["volume"] == {"latest": 6000, "prev5_avg": 2000, "ratio_prev5": 3.0,
                             "prev20_avg": 1250, "ratio_prev20": 4.8}


def test_volume_missing_or_zero_is_not_averaged():
    closes = [10.0] * 21
    latest_zero = analyze(bars(closes, volumes=[1000] * 20 + [0]))
    assert "volume" not in latest_zero and "最新一日沒有成交量資料，不提供量比" in latest_zero["notes"]
    latest_none = analyze([*bars(closes[:-1]), Bar(t=day(20), c=10.0)])
    assert "volume" not in latest_none
    # a zero-volume day among the 20 before, but not among the 5 before: only the 5-day ratio is given
    gap = analyze(bars(closes, volumes=[1000] * 3 + [0] + [1000] * 16 + [500]))
    assert gap["volume"] == {"latest": 500, "prev5_avg": 1000, "ratio_prev5": 0.5}
    assert "前 20 日有缺成交量的日子，不提供對 20 日均量的量比" in gap["notes"]


# -- range, streak, gap ------------------------------------------------------------------------------------------
def test_high_low_streak_and_gap():
    closes = [100.0] * 50 + [90.0, 95.0, 96.0, 97.0, 104.0, 99.0, 98.0, 99.0, 100.0, 103.0]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    highs[54], lows[51] = 108.0, 92.5
    lows[-1], opens = 102.0, [*closes[:-1], 102.5]  # the last bar never trades down to the previous high (101)
    out = analyze(bars(closes, highs=highs, lows=lows, opens=opens))
    assert out["date"] == day(59) and out["close"] == 103.0
    assert out["prev_close"] == {"date": day(58), "close": 100.0}
    assert (out["change"], out["change_pct"], out["open_gap_pct"], out["gap"]) == (3.0, 0.03, 0.025, "up")
    assert out["streak"] == {"direction": "up", "days": 3}  # 98 → 99 → 100 → 103
    assert out["high_low"]["20d"] == {"high": 108.0, "high_date": day(54), "low": 89.0, "low_date": day(50),
                                      "close_vs_high_pct": round(103 / 108 - 1, 4),
                                      "close_vs_low_pct": round(103 / 89 - 1, 4)}
    assert out["high_low"]["60d"]["low_date"] == day(50) and out["high_low"]["60d"]["high"] == 108.0
    down = analyze(bars([10.0, 11.0, 10.5, 10.0, 9.0]))
    assert down["streak"] == {"direction": "down", "days": 3} and "gap" in down  # high = low = close: every move gaps
    assert analyze(bars([10.0, 10.0, 10.0]))["streak"] == {"direction": "flat", "days": 2}
    # the latest of equal highs is reported
    same = analyze(bars([5.0] * 25))
    assert same["high_low"]["20d"]["high_date"] == day(24) and same["high_low"]["20d"]["low_date"] == day(24)


# -- events ------------------------------------------------------------------------------------------------------
SCENARIO = [100.0] * 40 + [90.0] * 5 + [110.0] * 3  # bars 0-39 flat, 40-44 down, 45-47 up


def brute_crosses(a, b):
    out, sign = [], 0
    for i, (x, y) in enumerate(zip(a, b, strict=True)):
        if x is None or y is None or x == y:
            continue
        s = 1 if x > y else -1
        if sign and s != sign:
            out.append((i, s))
        sign = s
    return out


def test_events_are_dated_facts_of_the_last_ten_bars():
    out = analyze(bars(SCENARIO))
    events = out["events"]
    assert all(e["date"] >= day(38) for e in events)  # the last 10 bars: 38-47
    assert [e["date"] for e in events] == sorted((e["date"] for e in events), reverse=True)  # newest first
    by_type: dict[str, list[date]] = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e["date"])
    # MA5 / MA20 by hand: bar 40 (first 90) MA5 98 < MA20 99.5; bar 46 MA5 98 < MA20 98.5; bar 47 MA5 102 > MA20 99
    assert by_type["ma5_ma20_cross_up"] == [day(47)] and "ma5_ma20_cross_down" not in by_type
    cross = next(e for e in events if e["type"] == "ma5_ma20_cross_up")
    assert cross["text"] == "5 日均線由下往上穿越 20 日均線（黃金交叉）"
    # Bollinger by hand: bar 40 mean 99.5 σ 2.18 lower 95.14; bar 41 mean 99 σ 3 lower 93; bar 42 lower 91.36;
    # bar 43 mean 98 σ 4 lower 90 (not below); bar 45 (first 110) mean 98 σ 5.10 upper 108.2; bar 46 mean 98.5
    # σ 5.72 upper 109.95; bar 47 mean 99 σ 6.24 upper 111.49 (not above)
    assert by_type["close_below_bollinger_lower"] == [day(42), day(41), day(40)]
    assert by_type["close_above_bollinger_upper"] == [day(46), day(45)]
    low = next(e for e in events if e["type"] == "close_below_bollinger_lower" and e["date"] == day(41))
    assert low["text"] == "收盤價 90 低於布林通道下軌 93"
    # new extremes: only the first 90 and the first 110 (equal to an earlier extreme is not "new"); 60 bars are
    # needed for a 60-day extreme, so these are 20-day ones
    assert by_type["new_low_20d"] == [day(40)] and by_type["new_high_20d"] == [day(45)]
    assert next(e for e in events if e["type"] == "new_high_20d")["text"] == "最高價 110 創 20 日新高"
    # KD and MACD turns against a brute-force scan of the (separately tested) series
    closes = SCENARIO
    ks, ds = ta.stochastic_kd(closes, closes, closes)
    kd = [(day(i), "kd_cross_up" if s > 0 else "kd_cross_down") for i, s in brute_crosses(ks, ds) if i >= 38]
    assert sorted(kd) == sorted((e["date"], e["type"]) for e in events if e["type"].startswith("kd_"))
    assert kd  # the scenario does contain one
    _dif, _sig, osc = ta.macd(closes)
    turns = [(day(i), "macd_osc_turn_positive" if s > 0 else "macd_osc_turn_negative")
             for i, s in brute_crosses(osc, [0.0 if x is not None else None for x in osc]) if i >= 38]
    assert sorted(turns) == sorted((e["date"], e["type"]) for e in events if e["type"].startswith("macd_"))
    # the histogram leaves 0 downwards on bar 40 (not a change of sign) and turns positive on the first 110
    assert turns == [(day(45), "macd_osc_turn_positive")]
    assert not any(w in e["text"] for e in events for w in ("買", "賣", "建議", "應該"))


def test_a_sixty_day_extreme_is_reported_once():
    closes = [100.0 + (i % 5) for i in range(70)] + [120.0]
    events = analyze(bars(closes))["events"]
    assert [e["type"] for e in events if e["date"] == day(70) and e["type"].startswith("new_")] == ["new_high_60d"]
    assert ta.crossings([None, 1.0, 0.0, 2.0, -1.0, 0.0, -2.0, 3.0]) == [(4, -1), (7, 1)]  # zeros keep the sign


def test_ma20_ma60_cross():
    closes = [100.0 + 0.5 * i for i in range(70)] + [80.0] * 12 + [150.0] * 30  # up, a drop, a jump
    events = analyze(bars(closes), window=len(closes))["events"]
    ma20, ma60 = ta.sma(closes, 20), ta.sma(closes, 60)
    want = [(day(i), f"ma20_ma60_cross_{'up' if s > 0 else 'down'}") for i, s in brute_crosses(ma20, ma60)]
    assert sorted(want) == sorted((e["date"], e["type"]) for e in events if e["type"].startswith("ma20_ma60"))
    assert {t for _d, t in want} == {"ma20_ma60_cross_down", "ma20_ma60_cross_up"}


# -- provisional bar, short and flat series ----------------------------------------------------------------------
def test_provisional_bar_has_no_volume_or_gap_and_only_its_own_events():
    history = bars(SCENARIO)
    price = 115.0
    out = analyze([*history, Bar(t=day(48), c=price, o=price, h=price, l=price)], provisional=True)
    assert out["date"] == day(48) and out["prev_close"] == {"date": day(47), "close": 110.0}
    assert out["change_pct"] == round(115 / 110 - 1, 4)
    assert "volume" not in out and "gap" not in out and "open_gap_pct" not in out
    assert {e["date"] for e in out["events"]} == {day(48)}
    assert {"type": "new_high_20d", "date": day(48),
            "text": "這個價格 115 高於前 19 個交易日的最高價（20 日新高）"} in out["events"]
    assert out["notes"][-1].startswith("今天的開盤、最高、最低價未知，都以這個價格代替")
    assert any(n.startswith("日 K 只有 49 根（含今天的暫定價；2026-06-01 起）") for n in out["notes"])
    # the official snapshot of the same history is untouched by the flag
    assert "volume" in analyze(history) and analyze(history)["date"] == day(47)


def test_too_few_bars():
    with pytest.raises(ValueError):
        analyze([])
    one = analyze(bars([42.0]))
    assert {k for k in one if k not in ("notes", "events")} == {"date", "close", "volume"}
    assert one["volume"] == {"latest": 1000} and one["events"] == []
    assert "KD（需 9 根）" in one["notes"][0] and "5 日量比（需 6 根）" in one["notes"][0]
    nine = analyze(bars([10.0 + i for i in range(9)]))
    assert nine["kd"]["k"] == pytest.approx(66.67) and set(nine["ma"]) == {"ma5"}
    assert any(n.startswith("RSI、KD、MACD 是逐日遞迴計算的指標；目前只有 9 根日 K") for n in nine["notes"])
    assert not any("逐日遞迴" in n for n in analyze(bars([10.0 + (i % 9) for i in range(100)]))["notes"])


def test_flat_series():
    out = analyze(bars([20.0] * 80))
    assert out["change"] == 0 and out["streak"] == {"direction": "flat", "days": 79}
    assert out["ma"]["ma60"] == {"value": 20.0, "bias_pct": 0.0}
    assert out["kd"] == {"k": 50.0, "d": 50.0} and out["macd"] == {"dif": 0.0, "macd": 0.0, "osc": 0.0}
    assert out["bollinger"] == {"upper": 20.0, "mid": 20.0, "lower": 20.0, "percent_b": None, "bandwidth": 0.0}
    assert out["volume"]["ratio_prev20"] == 1.0 and out["events"] == [] and "rsi14" not in out
