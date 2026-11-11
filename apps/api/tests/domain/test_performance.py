"""Hand-calculated performance checks: TWR with mid-period flows, XIRR, drawdown, volatility."""

import math
from datetime import date
from decimal import Decimal as D

import pytest

from forliosa.domain.ledger import LedgerTxn, OpeningPosition, TxnType
from forliosa.domain.performance import (
    annualized_volatility,
    benchmark_returns,
    daily_return,
    max_drawdown,
    simulate,
    twr,
    twr_index,
    xirr,
    xirr_flows,
)

DAYS = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9)]
CLOSES = {DAYS[0]: D(11), DAYS[1]: D(12), DAYS[2]: D("11.4"), DAYS[3]: D(12)}


def tx(id_, type_, d, qty, price, fee=0, tax=0, amount=0, nhi=0):
    return LedgerTxn(id_, "acc", "XYZ.TW", TxnType(type_), d, D(qty), D(price), D(amount), D(fee), D(tax),
                     D(nhi))


def price_fn(symbol, d):
    return CLOSES.get(d)


def fx_fn(currency, d):
    return D(1)


def test_contract_daily_return_formula():
    # r = (V_t + O_t) / (V_{t-1} + I_t) - 1
    assert daily_return(D(1000), D(1100), D(0), D(0)) == pytest.approx(0.1)
    assert daily_return(D(0), D(0), D(0), D(0)) == 0.0  # zero denominator


def test_twr_with_mid_period_buy_and_sell_matches_hand_calc():
    txns = [
        tx("t1", "buy", DAYS[0], 100, 10),  # I1 = 1,000 ; close 11 -> V1 = 1,100
        tx("t2", "buy", DAYS[2], 100, 12),  # I3 = 1,200 ; 200 sh × 11.4 -> V3 = 2,280
        tx("t3", "sell", DAYS[3], 50, 12),  # O4 = 600 ; 150 sh × 12 -> V4 = 1,800
    ]
    sim = simulate(txns, DAYS, price_fn, fx_fn)
    v = [p.value for p in sim.points]
    assert v == [D(1100), D(1200), D(2280), D(1800)]
    r = [p.daily_return for p in sim.points]
    # r1 = 1100/1000 - 1 = 0.10
    # r2 = 1200/1100 - 1 = 0.090909...
    # r3 = 2280/(1200 + 1200) - 1 = -0.05
    # r4 = (1800 + 600)/2280 - 1 = 0.0526315...
    assert r == pytest.approx([0.10, 1 / 11, -0.05, 2400 / 2280 - 1])
    # TWR = 1.1 × 1.090909 × 0.95 × 1.0526316 - 1 = 0.20 — equal to the price move 10 -> 12,
    # i.e. the timing/size of the buy and sell does not affect it.
    assert twr(r) == pytest.approx(0.20)
    idx = twr_index(r)
    assert idx == pytest.approx([1.1, 1.2, 1.14, 1.2])
    assert max_drawdown(idx) == pytest.approx(1.14 / 1.2 - 1)  # -0.05
    # net invested = 1,000 + 1,200 - 600 = 1,600
    assert sim.points[-1].net_invested == D(1600)


def test_twr_is_not_distorted_by_a_large_deposit():
    # Money-weighted results move with the deposit; TWR does not.
    days = DAYS[:2]
    closes = {days[0]: D(10), days[1]: D(11)}
    txns_small = [tx("a", "buy", days[0], 100, 10)]
    txns_big = [tx("a", "buy", days[0], 100, 10), tx("b", "buy", days[1], 10000, 10)]
    r_small = [p.daily_return for p in simulate(txns_small, days, lambda s, d: closes[d], fx_fn).points]
    r_big = [p.daily_return for p in simulate(txns_big, days, lambda s, d: closes[d], fx_fn).points]
    # Day 2 small: 1,100/1,000 - 1 = 10%. Day 2 big: 10,100 sh × 11 = 111,100 / (1,000 + 100,000) - 1 = 10%
    assert twr(r_small) == pytest.approx(0.10)
    assert twr(r_big) == pytest.approx(0.10)


def test_dividend_is_an_outflow_not_a_value_change():
    days = DAYS[:2]
    closes = {days[0]: D(100), days[1]: D(95)}  # ex-dividend drop of 5
    txns = [
        tx("a", "buy", days[0], 1000, 100),
        # 1,000 × 5 = 5,000 cash dividend recorded on the ex-date
        tx("b", "cash_dividend", days[1], 1000, 5, amount=5000),
    ]
    sim = simulate(txns, days, lambda s, d: closes[d], fx_fn)
    # r2 = (95,000 + 5,000) / 100,000 - 1 = 0
    assert sim.points[1].daily_return == pytest.approx(0.0)
    assert sim.points[1].dividends == D(5000)


def test_holdings_snapshot_starts_tracking_on_as_of():
    days = DAYS[:3]
    closes = {days[0]: D(20), days[1]: D(22), days[2]: D(21)}
    op = OpeningPosition("acc", "XYZ.TW", days[1], D(100), D(5))  # bought long ago at 5
    sim = simulate([], days, lambda s, d: closes[d], fx_fn, openings=[op])
    r = [p.daily_return for p in sim.points]
    # Day 1: nothing. Day 2: inflow at market (2,200), value 2,200 -> 0. Day 3: 2,100/2,200 - 1
    assert r == pytest.approx([0.0, 0.0, 2100 / 2200 - 1])


def test_xirr_matches_excel_textbook_example():
    # Microsoft Excel XIRR documentation example: result 0.373362535 (37.34%)
    flows = [
        (date(2008, 1, 1), -10000),
        (date(2008, 3, 1), 2750),
        (date(2008, 10, 30), 4250),
        (date(2009, 2, 15), 3250),
        (date(2009, 4, 1), 2750),
    ]
    assert xirr(flows) == pytest.approx(0.373362535, abs=1e-8)


def test_xirr_simple_one_year_and_edge_cases():
    # -1,000 then +1,100 exactly 365 days later -> 10%
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 1100)]) == pytest.approx(0.10)
    # Loss: -1,000 -> +500 after 365 days -> -50%
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 500)]) == pytest.approx(-0.5)
    assert xirr([(date(2025, 1, 1), -1000)]) is None
    assert xirr([(date(2025, 1, 1), 1000), (date(2026, 1, 1), 1000)]) is None


def test_xirr_bisection_fallback_for_extreme_rates():
    # Doubling in 10 days -> enormous annualized rate; Newton from 10% overshoots, bisection must solve.
    flows = [(date(2025, 1, 1), -1000), (date(2025, 1, 11), 2000)]
    r = xirr(flows)
    assert r is not None
    assert (1 + r) ** (10 / 365) == pytest.approx(2.0, rel=1e-6)


def test_xirr_flows_from_series():
    txns = [tx("t1", "buy", DAYS[0], 100, 10), tx("t2", "buy", DAYS[2], 100, 12), tx("t3", "sell", DAYS[3], 50, 12)]
    pts = simulate(txns, DAYS, price_fn, fx_fn).points
    flows = xirr_flows(pts, 0, 3)
    assert flows == [(DAYS[0], -1000.0), (DAYS[2], -1200.0), (DAYS[3], 600.0), (DAYS[3], 1800.0)]
    # Sub-range starting on day 3: opening value V2 = 1,200 paid in on day 2
    flows = xirr_flows(pts, 2, 3)
    assert flows[0] == (DAYS[1], -1200.0)


def test_volatility_hand_calc():
    # returns +1%, -1%: mean 0, sample variance (0.0001 + 0.0001)/1 = 0.0002 -> sd 0.0141421
    vol = annualized_volatility([0.01, -0.01])
    assert vol == pytest.approx(math.sqrt(0.0002) * math.sqrt(252))
    assert annualized_volatility([0.01]) is None


def test_benchmark_total_return_counts_dividends_and_splits():
    days = [date(2025, 6, 16), date(2025, 6, 17), date(2025, 6, 18), date(2025, 6, 19)]
    closes = {days[0]: D(100), days[1]: D(101), days[2]: D("25.25"), days[3]: D(24)}
    divs = {days[3]: D("1.25")}
    splits = {days[2]: D(4)}
    r = benchmark_returns(days, closes.get, lambda d: divs.get(d, D(0)), lambda d: splits.get(d, D(1)))
    # day2: 101/100 - 1 = 1% ; day3 (1-to-4 split): 25.25 × 4 / 101 - 1 = 0 ; day4: (24 + 1.25)/25.25 - 1 = 0
    assert r == pytest.approx([0.0, 0.01, 0.0, 0.0])
