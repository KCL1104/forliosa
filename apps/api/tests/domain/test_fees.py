"""Hand-calculated checks for Taiwan fees, securities transaction tax and NHI premium."""

from datetime import date
from decimal import Decimal as D

from forliosa.domain.fees import (
    FeeSchedule,
    InstrumentRef,
    commission,
    dividend_cash_amount,
    is_etf,
    nhi_premium,
    preview_buy,
    preview_cash_dividend,
    preview_sell,
    stock_dividend_shares,
    transaction_tax,
)

TSMC = InstrumentRef("2330", "TWSE", "stock")
ETF_0050 = InstrumentRef("0050", "TWSE", "etf")
HONHAI = InstrumentRef("2317", "TWSE", "stock")
AAPL = InstrumentRef("AAPL", "US", "stock")
SINOPAC = FeeSchedule(fee_discount=D("0.28"), min_fee=D(20), min_fee_odd_lot=D(1))
NO_DISCOUNT = FeeSchedule()
TODAY = date(2026, 11, 11)


def test_minimum_fee_applies_to_small_board_lot_order():
    # 1,000 shares × NT$10 = 10,000; 10,000 × 0.1425% × 0.28 = 3.99 -> floor 3 -> below min 20 -> 20
    fee, rules = commission(D(10000), D(1000), SINOPAC, TSMC)
    assert fee == D(20)
    assert any("最低手續費" in r for r in rules)


def test_discount_is_truncated_not_rounded():
    # 1,070,000 × 0.001425 = 1,524.75; × 0.28 = 426.93 -> truncated to 426 (rounding would give 427)
    fee, _ = commission(D(1070000), D(1000), SINOPAC, TSMC)
    assert fee == D(426)
    # Without discount: 1,524.75 -> 1,524
    fee, _ = commission(D(1070000), D(1000), NO_DISCOUNT, TSMC)
    assert fee == D(1524)


def test_odd_lot_uses_odd_lot_minimum():
    # 35 shares × 1,085 = 37,975; × 0.001425 × 0.28 = 15.15... -> 15 (above odd-lot min 1)
    fee, _ = commission(D(37975), D(35), SINOPAC, TSMC)
    assert fee == D(15)
    # 1 share × 50 = 50; × 0.001425 × 0.28 = 0.01995 -> 0 -> odd-lot minimum NT$1
    fee, rules = commission(D(50), D(1), SINOPAC, TSMC)
    assert fee == D(1)
    assert any("零股最低手續費" in r for r in rules)
    # Same odd-lot order on an account without an odd-lot minimum -> the normal NT$20 minimum
    fee, _ = commission(D(50), D(1), NO_DISCOUNT, TSMC)
    assert fee == D(20)
    # 999 shares is still an odd lot; 1,000 shares is a board lot (min 20)
    fee, _ = commission(D(999), D(999), SINOPAC, TSMC)
    assert fee == D(1)
    fee, _ = commission(D(1000), D(1000), SINOPAC, TSMC)
    assert fee == D(20)


def test_stock_etf_and_day_trade_tax():
    # Stock: 1,070,000 × 0.3% = 3,210
    tax, rules = transaction_tax(D(1070000), TSMC, TODAY)
    assert tax == D(3210) and "股票 0.3%" in rules[0]
    # ETF: 2,000 × 23.45 = 46,900 × 0.1% = 46.9 -> 46
    tax, rules = transaction_tax(D(46900), ETF_0050, TODAY)
    assert tax == D(46) and "ETF 0.1%" in rules[0]
    # Day trade stock: 242,500 × 0.15% = 363.75 -> 363
    tax, rules = transaction_tax(D(242500), HONHAI, TODAY, is_day_trade=True)
    assert tax == D(363) and "當沖減半" in rules[0]
    # Day trade on the sunset date still enjoys 0.15%
    tax, _ = transaction_tax(D(242500), HONHAI, date(2027, 12, 31), is_day_trade=True)
    assert tax == D(363)
    # After 2027-12-31 the day-trade rate falls back to 0.3%: 242,500 × 0.3% = 727.5 -> 727
    tax, rules = transaction_tax(D(242500), HONHAI, date(2028, 1, 3), is_day_trade=True)
    assert tax == D(727) and "到期" in rules[0]
    # ETF day trade stays at 0.1%: 46,900 -> 46
    tax, _ = transaction_tax(D(46900), ETF_0050, TODAY, is_day_trade=True)
    assert tax == D(46)
    # US: no Taiwan tax
    tax, rules = transaction_tax(D(5000), AAPL, TODAY)
    assert tax == 0 and rules == ["美股無證交稅"]


def test_etf_heuristic_and_bond_etf_exemption():
    assert is_etf("00878") and is_etf("006208") and not is_etf("2330")
    assert is_etf("2330", "etf") is True and is_etf("0050", "stock") is False
    bond = InstrumentRef("00679B", "TPEX", None)
    tax, rules = transaction_tax(D(100000), bond, date(2026, 12, 31))
    assert tax == 0 and "債券 ETF 停徵" in rules[0]
    tax, _ = transaction_tax(D(100000), bond, date(2027, 1, 4))
    assert tax == D(100)  # 100,000 × 0.1%


def test_nhi_threshold_19999_vs_20000():
    assert nhi_premium(D(19999))[0] == 0
    # 20,000 × 2.11% = 422.0
    assert nhi_premium(D(20000))[0] == D(422)
    # 21,350 × 2.11% = 450.485 -> 450 ; 21,351 × 2.11% = 450.5061 -> 451 (half-up)
    assert nhi_premium(D(21350))[0] == D(450)
    assert nhi_premium(D(21351))[0] == D(451)
    # Base is capped at NT$10,000,000: 10,000,000 × 2.11% = 211,000
    assert nhi_premium(D(12_000_000))[0] == D(211000)
    # Foreign currency dividends are not subject to it
    assert nhi_premium(D(50000), "USD")[0] == 0


def test_preview_buy_matches_contract_shape():
    p = preview_buy(D(1000), D(1070), SINOPAC, TSMC, TODAY)
    assert p.gross == D(1070000)
    assert p.fee == D(426)
    assert p.tax == 0
    assert p.net_cash == D(-1070426)
    assert p.rules[0] == "手續費 0.1425% × 2.8 折，元以下捨去"
    assert p.rules[-1] == "證交稅：買進免稅"


def test_preview_sell_net_cash():
    # gross 1,070,000; fee 426; tax 3,210 -> net 1,066,364
    p = preview_sell(D(1000), D(1070), SINOPAC, TSMC, TODAY)
    assert (p.fee, p.tax, p.net_cash) == (D(426), D(3210), D(1066364))


def test_us_fees_default_zero_and_configurable():
    p = preview_buy(D(10), D("230.5"), FeeSchedule(fee_rate=D(0), min_fee=D(0)), AAPL, TODAY)
    assert p.fee == 0 and p.net_cash == D("-2305.0")
    # 0.1% of 2,305 = 2.305 -> 2.31 (cents, half-up); min US$3 -> 3
    fee, _ = commission(D("2305"), D(10), FeeSchedule(fee_rate=D("0.001"), min_fee=D(3)), AAPL)
    assert fee == D(3)
    fee, _ = commission(D("23050"), D(100), FeeSchedule(fee_rate=D("0.001"), min_fee=D(3)), AAPL)
    assert fee == D("23.05")


def test_cash_dividend_preview():
    p = preview_cash_dividend(D(25000), "TWD", TSMC)
    # 25,000 × 2.11% = 527.5 -> 528 ; net 24,472
    assert p.health_insurance == D(528) and p.net_cash == D(24472)
    us = preview_cash_dividend(D("26.00"), "USD", AAPL)
    # 30% withholding: 7.80 ; net 18.20
    assert us.tax == D("7.80") and us.net_cash == D("18.20") and us.health_insurance == 0


def test_dividend_cash_amount_truncates_twd():
    # 1,535 shares × 4.5 = 6,907.5 -> NT$6,907
    assert dividend_cash_amount(D(1535), D("4.5"), "TWD") == D(6907)
    # 15 shares × 0.26 = 3.90 USD
    assert dividend_cash_amount(D(15), D("0.26"), "USD") == D("3.90")


def test_stock_dividend_shares_and_cash_in_lieu():
    # 1,000 shares × 1.5 元 / 10 = 150 shares, no fraction
    assert stock_dividend_shares(D(1000), D("1.5")) == (D(150), D(0))
    # 1,234 shares × 0.5 元 / 10 = 61.7 -> 61 shares + 0.7 share × NT$10 = NT$7 cash
    assert stock_dividend_shares(D(1234), D("0.5")) == (D(61), D(7))


def test_capital_surplus_is_left_out_of_the_nhi_premium():
    # 台泥-like: NT$30,000 paid, all from 資本公積 -> no dividend income, no premium
    p = preview_cash_dividend(D(30000), "TWD", TSMC, capital_surplus=D(30000))
    assert p.health_insurance == 0 and p.net_cash == D(30000)
    assert any("資本公積" in r for r in p.rules)
    # NT$50,000 of which NT$20,000 is capital surplus: base 30,000 × 2.11% = 633
    p = preview_cash_dividend(D(50000), "TWD", TSMC, capital_surplus=D(20000))
    assert p.health_insurance == D(633)
    # income part below the NT$20,000 threshold once the surplus is excluded
    p = preview_cash_dividend(D(25000), "TWD", TSMC, capital_surplus=D(10000))
    assert p.health_insurance == 0 and any("股利所得未達" in r for r in p.rules)
