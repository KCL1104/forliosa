"""Parser tests on trimmed copies of live upstream responses (fetched 2026-11-11; tests stay offline)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from forliosa.marketdata.base import ProviderUnavailable, QuoteData, parse_decimal, parse_tw_date
from forliosa.marketdata.finmind import (
    extract_rows,
    parse_dividends,
    parse_exchange_rate,
    parse_month_revenue,
    parse_per,
    parse_price,
    parse_roc_period,
)
from forliosa.marketdata.shioaji_data import (
    parse_cards,
    parse_daily,
    parse_monthly_revenue,
    parse_quarter_fundamentals,
)
from forliosa.marketdata.tpex import parse_daily_close_quotes, parse_pe_qry_date
from forliosa.marketdata.twse import (
    mis_channel,
    parse_bwibbu_all,
    parse_holiday_schedule,
    parse_mis,
    parse_stock_day_all,
    parse_twt48u_all,
)
from forliosa.timeutil import TAIPEI

FIX = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_parse_helpers():
    assert parse_decimal("2,440.00") == D("2440.00")
    assert parse_decimal("+35.00") == D("35.00")
    assert parse_decimal("----") is None and parse_decimal("N/A") is None and parse_decimal("") is None
    assert parse_tw_date("1150929") == date(2026, 9, 29)
    assert parse_tw_date("115/11/11") == date(2026, 11, 11)
    assert parse_tw_date("20261111") == date(2026, 11, 11)
    assert parse_tw_date("2026-11-11") == date(2026, 11, 11)


# -- TWSE MIS ------------------------------------------------------------------------------------
def test_mis_live_response():
    quotes = parse_mis(load("mis_live_20261111.json"))
    assert set(quotes) == {"2330.TW", "6488.TWO", "0050.TW"}
    q = quotes["2330.TW"]
    assert (q.price, q.prev_close, q.open, q.high, q.low) == (D("2395"), D("2285"), D("2330"), D("2395"), D("2305"))
    assert q.volume == 30370 * 1000  # MIS "v" is in lots
    assert q.trade_date == date(2026, 11, 11)
    assert q.as_of == datetime(2026, 11, 11, 13, 30, tzinfo=TAIPEI)
    assert quotes["6488.TWO"].price == D("635") and quotes["6488.TWO"].prev_close == D("612")
    assert quotes["0050.TW"].price == D("103.2")


def test_mis_without_trade_and_placeholder_rows():
    # twstock's recorded response: "z" is "-" (no trade at that snapshot), placeholder row with c=""
    quotes = parse_mis(load("mis_twstock_mock.json"))
    assert set(quotes) == {"2330.TW", "6488.TWO"}
    q = quotes["2330.TW"]
    assert q.price is None  # no z / pz: the facade falls back to another provider
    assert q.prev_close == D("839") and q.volume == 23_350_000
    assert quotes["6488.TWO"].price == D("945")


def test_mis_reference_price_before_first_trade():
    payload = {"msgArray": [{"c": "2330", "ex": "tse", "z": "-", "y": "2285.0000", "o": "-", "h": "-", "l": "-",
                             "v": "-", "tlong": "1794358800000", "d": "20261112"}], "rtcode": "0000"}
    q = parse_mis(payload)["2330.TW"]
    assert q.price == D("2285") and q.prev_close == D("2285")


def test_mis_channel():
    assert mis_channel("2330.TW") == "tse_2330.tw"
    assert mis_channel("6488.TWO") == "otc_6488.tw"


# -- TWSE OpenAPI --------------------------------------------------------------------------------
def test_stock_day_all_live():
    quotes = parse_stock_day_all(load("twse_stock_day_all_live.json"))
    assert "00625K.TW" not in quotes  # no trade: empty ClosingPrice
    q = quotes["2330.TW"]
    assert q.price == D("2285.00") and q.prev_close == D("2235.00")  # Change "50.0000" (unsigned = up)
    assert q.volume == 36575797 and q.trade_date == date(2026, 11, 10)
    down = quotes["0055.TW"]
    assert down.prev_close == down.price + D("0.2")  # Change "-0.2000"


def test_bwibbu_all_live():
    ratios = parse_bwibbu_all(load("twse_bwibbu_all_live.json"))
    assert ratios["2330"] == {"date": date(2026, 11, 10), "per": D("26.49"), "pbr": D("9.21"),
                              "dividend_yield": D("0.0096")}
    assert ratios["1101"]["per"] is None  # blank when EPS <= 0


def test_twt48u_live_announced_without_amount():
    events = parse_twt48u_all(load("twse_twt48u_all_live.json"))
    e = next(e for e in events if e.symbol == "00878.TW")
    assert e.ex_dividend_date == date(2026, 11, 17) and e.cash_dividend == 0


def test_holiday_schedule_live():
    days = parse_holiday_schedule(load("twse_holiday_schedule_live.json"))
    assert days[0] == (date(2026, 1, 1), "中華民國開國紀念日")


# -- TPEx ----------------------------------------------------------------------------------------
def test_tpex_daily_close_live():
    quotes = parse_daily_close_quotes(load("tpex_daily_close_quotes_live.json"))
    q = quotes["6488.TWO"]
    assert (q.price, q.prev_close, q.volume) == (D("635.00"), D("612.00"), 11401175)
    assert q.trade_date == date(2026, 11, 11)


def test_tpex_pe_qry_date_live():
    ratios = parse_pe_qry_date(load("tpex_pe_qry_date_live.json"))
    assert ratios["6488"] == {"date": date(2026, 11, 11), "per": D("35.75"), "pbr": D("2.30"),
                              "dividend_yield": D("0.0121")}
    assert ratios["1569"]["per"] is None  # "N/A"
    with pytest.raises(ProviderUnavailable):
        parse_pe_qry_date({"stat": "error"})


# -- FinMind -------------------------------------------------------------------------------------
def test_finmind_price_live():
    candles = parse_price(extract_rows(load("finmind_price_live.json")))
    assert [c.t for c in candles] == [date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)]
    assert candles[-1].c == D("2395.0") and candles[-1].v > 0


def test_finmind_quota_error_raises():
    with pytest.raises(ProviderUnavailable):
        extract_rows(load("finmind_quota_error_live.json"))


def test_finmind_per_live():
    ratios = parse_per(extract_rows(load("finmind_per_live.json")))
    r = ratios[date(2026, 11, 11)]
    assert r == {"per": D("27.76"), "pbr": D("9.66"), "dividend_yield": D("0.0092")}


def test_finmind_dividends_live():
    stock = parse_dividends(extract_rows(load("finmind_dividend_2330_live.json")), "2330.TW")
    assert stock[0].ex_dividend_date == date(2026, 9, 16)
    assert stock[0].cash_dividend == D("7.00000137")  # full precision; brokers pay shares × rate
    assert stock[0].payment_date == date(2026, 10, 8)
    assert (stock[0].year, stock[0].period) == (2026, "2026Q1")  # "115年第1季"
    etf = parse_dividends(extract_rows(load("finmind_dividend_00878_live.json")), "00878.TW")
    assert [e.period for e in etf] == ["2026Q3", "2026Q2", "2026Q1"]  # "115" repeated -> by ex-date
    assert etf[0].cash_dividend == D("1.01")


def test_roc_period():
    assert parse_roc_period("113年第3季", 0) == (2024, "2024Q3")
    assert parse_roc_period("113年", 0) == (2024, "2024")
    assert parse_roc_period("115", 0) == (2026, "2026")
    assert parse_roc_period("113年上半年", 0) == (2024, "2024H1")
    assert parse_roc_period("", 2025) == (2025, "2025")


def test_finmind_month_revenue_live():
    rows = parse_month_revenue(extract_rows(load("finmind_month_revenue_live.json")))
    last = rows[-1]
    assert last.period == "2026-10" and last.revenue == 586890319  # NT$ -> thousand NT$
    # 586,890,319 / 511,857,399 - 1
    assert float(last.mom_pct) == pytest.approx(586890319 / 511857399 - 1)


def test_finmind_exchange_rate_live():
    fx = parse_exchange_rate(extract_rows(load("finmind_exchange_rate_live.json")))
    # (spot_buy 32.825 + spot_sell 32.925) / 2 = 32.875
    assert fx[date(2026, 11, 10)] == D("32.8750")


# -- shioaji-data --------------------------------------------------------------------------------
def test_shioaji_data_parsers():
    cards = parse_cards([
        {"code": "2330", "market": "twse", "name": "台積電", "english_short": "TSMC",
         "industry": {"l0_name": "半導體業"}, "chain_stage": {"stage_name": "晶圓製造"},
         "summary_short": "以晶圓代工為主要收入。"},
        {"code": "6488", "market": "tpex", "name": "環球晶", "industry": {"l0_name": "半導體業"}, "chain_stage": None},
    ])
    assert [(c.symbol, c.market, c.type, c.industry) for c in cards] == [
        ("2330.TW", "TWSE", "stock", "半導體業"), ("6488.TWO", "TPEX", "stock", "半導體業")]
    assert cards[0].chain_stage == "晶圓製造" and cards[0].aliases == ("TSMC",)
    daily = parse_daily({"as_of": {"twse": "2026-11-11"}, "quotes": {
        "2330": {"close": 2395.0, "date": "2026-11-11", "market_cap_twd": 62108026310465, "shares": 25932370067}}})
    assert daily["2330"]["close"] == D("2395.0") and daily["2330"]["shares"] == 25932370067
    fin = {
        "monthly_revenue": [{"period": "2026-09", "revenue_thousand_twd": 511857399, "yoy_pct": 54.6486,
                             "mom_pct": -0.5726, "ytd_thousand_twd": 3898726974, "ytd_yoy_pct": 41.1067}],
        "statements": {"periods": ["2026Q1", "2026Q2"],
                       "income_quarter": {"基本每股盈餘（元）": [22.08, 27.25]},
                       "balance": {"每股參考淨值": [227.17, 248.05]}},
    }
    rev = parse_monthly_revenue(fin)[0]
    assert rev.revenue == 511857399 and rev.yoy_pct == D("0.546486") and rev.mom_pct == D("-0.005726")
    q = parse_quarter_fundamentals(fin)
    assert [(x.period, x.eps, x.bvps) for x in q] == [("2026Q1", D("22.08"), D("227.17")),
                                                      ("2026Q2", D("27.25"), D("248.05"))]


# -- quote merging -------------------------------------------------------------------------------
def test_quote_merge_fills_gaps_and_flags_demo():
    real = QuoteData("2330.TW", price=D("2395"), trade_date=date(2026, 11, 11), source="shioaji-data")
    demo = QuoteData("2330.TW", price=D("2390"), prev_close=D("2285"), open=D("2330"), high=D("2400"),
                     low=D("2300"), volume=1, trade_date=date(2026, 11, 11), is_demo=True, source="demo")
    merged = real.merged_with(demo)
    assert merged.price == D("2395") and merged.prev_close == D("2285") and merged.is_demo
    assert merged.source == "shioaji-data+demo"
    other_day = QuoteData("2330.TW", price=D("1"), prev_close=D("1"), trade_date=date(2026, 11, 10))
    assert real.merged_with(other_day).prev_close is None


def test_previous_session_close_becomes_prev_close():
    from forliosa.marketdata.service import _merge_quotes

    today = QuoteData("2330.TW", price=D("2395"), trade_date=date(2026, 11, 11), source="shioaji-data")
    yesterday = QuoteData("2330.TW", price=D("2285"), prev_close=D("2235"), trade_date=date(2026, 11, 10),
                          source="finmind")
    merged = _merge_quotes(today, yesterday)
    assert merged.prev_close == D("2285") and not merged.is_demo
