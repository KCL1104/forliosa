"""Tick sizes and price limits, checked against official values published on 2026-11-12."""

from decimal import Decimal as D

import pytest

from forliosa.domain.ticks import ex_rights_prices, ex_rights_reference, is_fund_code, price_limits, tick_size


@pytest.mark.parametrize(("price", "fund", "tick"), [
    ("9.99", False, "0.01"), ("10", False, "0.05"), ("49.95", False, "0.05"), ("50", False, "0.1"),
    ("99.9", False, "0.1"), ("100", False, "0.5"), ("499.5", False, "0.5"), ("500", False, "1"),
    ("999", False, "1"), ("1000", False, "5"), ("2395", False, "5"),
    ("49.99", True, "0.01"), ("50", True, "0.05"), ("103.2", True, "0.05"),
])
def test_tick_table(price, fund, tick):
    assert tick_size(D(price), fund) == D(tick)


@pytest.mark.parametrize(("ref", "fund", "up", "down"), [
    # TWSE TWT84U 2026-11-12 (TodayOpeningRefPrice -> TodayLimitUp / TodayLimitDown)
    ("2395", False, "2630", "2160"),     # 2330: 2634.5 -> 2630 (tick 5), 2155.5 -> 2160
    ("103.20", True, "113.50", "92.90"),  # 0050 (ETF): 113.52 -> 113.50, 92.88 -> 92.90
    ("298", False, "327.5", "268.5"),     # 2382: 327.8 -> 327.5, 268.2 -> 268.5
    ("1295", False, "1420", "1170"),      # 2308: 1424.5 -> 1420, 1165.5 -> 1170
    ("159.5", False, "175", "144"),       # 2881: 175.45 -> 175, 143.55 -> 144
    ("33.50", True, "36.85", "30.15"),    # 00878
    ("7.24", False, "7.96", "6.52"),      # 1538
    # TPEx tpex_mainboard_daily_close_quotes 2026-11-11 (NextLimitUp / NextLimitDown)
    ("635", False, "698", "572"),         # 6488: 698.5 -> 698 (tick 1), 571.5 -> 572
    ("78.80", False, "86.6", "71"),       # 8390: 86.68 -> 86.6, 70.92 -> 71.0
])
def test_price_limits_match_exchange(ref, fund, up, down):
    assert price_limits(D(ref), fund) == (D(up), D(down))


def test_limit_crossing_a_tick_band_uses_the_band_of_the_limit():
    # 95 * 1.1 = 104.5 lies in the 100–500 band (tick 0.5); 92 * 1.1 = 101.2 -> 101.0
    assert price_limits(D(95))[0] == D("104.5")
    assert price_limits(D(92))[0] == D(101)
    # 111 * 0.9 = 99.9 lies in the 50–100 band (tick 0.1)
    assert price_limits(D(111))[1] == D("99.9")


def test_ex_dividend_reference_and_limits_tpex_3680():
    # 3680 goes ex on 2026-11-12: close 435.50, cash 9.9147456 -> raw 425.5852544.
    # Official (TPEx NextReferencePrice / NextLimitUp / NextLimitDown): 425.50 / 468.00 / 383.50.
    # The limits come from the unrounded price (from 425.50 the limit-down would be 383.00).
    assert ex_rights_prices(D("435.50"), D("9.9147456")) == (D("425.5"), D(468), D("383.5"))
    assert price_limits(D("425.5"))[1] == D(383)


def test_ex_rights_with_stock_dividend():
    # close 60, cash 1.5, 0.1 share per share: (60 - 1.5) / 1.1 = 53.1818… -> 53.2 (tick 0.1)
    assert ex_rights_reference(D(60), D("1.5"), D("0.1")) == D("53.2")


def test_fund_codes():
    assert is_fund_code("0050") and is_fund_code("00878") and is_fund_code("00400A")
    assert not is_fund_code("2330") and not is_fund_code("6488")
