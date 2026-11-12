"""TAIFEX OpenAPI parsers on trimmed live responses (2026-11-12): the §12.3 traps plus the CSV variant."""

import csv
import io
import json
from datetime import date
from decimal import Decimal as D

import pytest

from forliosa.marketdata import taifex as tf
from forliosa.marketdata.base import ProviderUnavailable
from tests.archive.fakes import FIX


def rows(name: str) -> list[dict]:
    return tf.decode_rows((FIX / name).read_bytes())


def test_futures_sessions_null_and_dash():
    fut = tf.parse_futures_daily(rows("taifex_daily_market_report_fut_live_20261112.json"))
    tx = {r["session"]: r for r in fut if r["contract"] == "TX" and r["contract_month"] == "202611"}
    reg, night = tx["regular"], tx["after_hours"]
    assert reg["trade_date"] == date(2026, 11, 11)  # western YYYYMMDD
    assert (reg["last"], reg["change"], reg["change_pct"]) == (D("44091"), D("1445"), D("0.0339"))
    assert (reg["settlement_price"], reg["open_interest"], reg["volume"]) == (D("44136"), 122326, 81696)
    # the night session (15:00 the day before -> 05:00) is booked to 11-11; "NULL" / "-" -> None
    assert (night["last"], night["change"], night["settlement_price"], night["open_interest"]) == (
        D("42522"), D("-124"), None, None)
    # both sessions' change is measured from the previous settlement (42,646)
    assert reg["last"] - reg["change"] == night["last"] - night["change"] == D("42646")
    no_trade = next(r for r in fut if r["contract"] == "TF" and r["contract_month"] == "202612"
                    and r["session"] == "regular")
    assert no_trade["open"] is None and no_trade["volume"] == 0 and no_trade["settlement_price"] == D("3654.4")
    spread = next(r for r in fut if r["contract_month"] == "202611/202612" and r["contract"] == "MTX")
    assert spread["settlement_price"] is None and spread["spread_volume"] == 2879
    assert {r["contract_month"] for r in fut if r["contract"] == "MTX"} >= {"202611W2", "202611", "202612"}
    assert not tf.is_monthly("202611W2") and not tf.is_monthly("202611/202612") and tf.is_monthly("202611")


def test_options_keep_index_options_and_two_nearest_months_of_stock_options():
    opt = tf.parse_options_daily(rows("taifex_daily_market_report_opt_live_20261112.json"))
    cdo = {r["contract_month"] for r in opt if r["contract"] == "CDO"}
    assert cdo == {"202611", "202611W2", "202611W4", "202612"}  # 202703 dropped
    txo = [r for r in opt if r["contract"] == "TXO"]
    assert {r["call_put"] for r in txo} == {"C", "P"} and {r["strike"] for r in txo} == {D(44000), D(44100)}
    night = next(r for r in txo if r["session"] == "after_hours")
    assert night["settlement_price"] is None and night["open_interest"] is None


def test_institutional_units_and_scopes():
    general = {r["investor"]: r for r in tf.parse_institutional_general(
        rows("taifex_institutional_general_live_20261112.json"))}
    foreign = general["外資及陸資"]
    assert foreign["oi_net"] == -383572
    assert foreign["oi_net_value_k"] == -1_048_499_000  # published in millions, stored in thousands
    split = tf.parse_institutional_fut_opt(rows("taifex_institutional_fut_opt_live_20261112.json"))
    fut = next(r for r in split if r["investor"] == "外資及陸資" and r["contract_name"] == "期貨")
    opt = next(r for r in split if r["investor"] == "外資及陸資" and r["contract_name"] == "選擇權")
    assert fut["oi_net"] + opt["oi_net"] == foreign["oi_net"]  # -381,366 + -2,206
    contracts = tf.parse_institutional_contracts(rows("taifex_institutional_futures_live_20261112.json"), "futures")
    tx = {r["investor"]: r for r in contracts if r["contract_name"] == "臺股期貨"}
    assert tx["外資及陸資"]["contract_code"] == "TX" and tx["外資及陸資"]["oi_net"] == -104271
    assert next(r for r in contracts if r["contract_name"] == "股票期貨")["contract_code"] is None
    cp = tf.parse_institutional_contracts(rows("taifex_institutional_calls_puts_live_20261112.json"), "calls_puts")
    assert {r["call_put"] for r in cp} == {"C", "P"} and all(r["contract_code"] == "TXO" for r in cp)


def test_large_traders_sentinels_match_put_call_open_interest():
    lt = tf.parse_large_traders(rows("taifex_large_traders_options_live_20261112.json"), "options")
    pcr = tf.parse_put_call_ratio(rows("taifex_put_call_ratio_live_20261112.json"))
    latest = max(pcr, key=lambda r: r["trade_date"])
    allm = {(r["call_put"], r["trader_type"]): r for r in lt if r["settlement_month"] == tf.ALL_MONTHS}
    assert allm[("C", 0)]["market_oi"] == latest["call_oi"] == 88811  # 999912 = all months combined
    assert allm[("P", 0)]["market_oi"] == latest["put_oi"] == 57877
    assert all(allm[(cp, 1)]["top10_buy"] <= allm[(cp, 0)]["top10_buy"] for cp in "CP")  # 1 = 特定法人 subset
    fut = tf.parse_large_traders(rows("taifex_large_traders_futures_live_20261112.json"), "futures")
    tx = {(r["settlement_month"], r["trader_type"]): r for r in fut if r["contract"] == "TX"}
    assert tx[(tf.ALL_MONTHS, 0)]["top5_buy"] - tx[(tf.ALL_MONTHS, 0)]["top5_sell"] == 32312
    assert (tf.WEEKLY_MONTHS, 0) in tx and tx[(tf.ALL_MONTHS, 0)]["contract_name"] == "臺股期貨(TX+MTX/4)"


def test_put_call_ratio_percent_and_month_of_days():
    pcr = tf.parse_put_call_ratio(rows("taifex_put_call_ratio_live_20261112.json"))
    assert len(pcr) == 21 and min(r["trade_date"] for r in pcr) == date(2026, 10, 12)
    r = max(pcr, key=lambda r: r["trade_date"])
    assert (r["volume_ratio"], r["oi_ratio"]) == (D("1.0708"), D("0.6517"))  # "107.08" -> fraction


def test_fx_csv_as_served_and_json_variant():
    raw = (FIX / "taifex_fx_rates_live_20261112.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # Cloudflare served the CSV variant (UTF-8 BOM) to an Accept: json request
    fx = tf.parse_fx(tf.decode_rows(raw))
    usd = {r["date"]: r["rate"] for r in fx if r["pair"] == "USDTWD"}
    assert len(usd) == 27 and usd[date(2026, 11, 11)] == D("32.86") and min(usd) == date(2026, 10, 1)
    assert {r["pair"] for r in fx} == set(tf.FX_PAIRS.values())
    as_json = json.dumps([{"Date": "20261111", "USD/NTD": "32.86", "RMB/NTD": "NULL"}]).encode()
    assert tf.parse_fx(tf.decode_rows(as_json)) == [{"date": date(2026, 11, 11), "pair": "USDTWD", "rate": D("32.86")}]


def test_any_dataset_parses_from_its_csv_variant():
    """The cache can serve CSV for any endpoint: headers are the swagger descriptions (「／」 written as 「_」)."""
    data = rows("taifex_put_call_ratio_live_20261112.json")
    headers = {"Date": "日期", "PutVolume": "賣權成交量", "CallVolume": "買權成交量",
               "PutCallVolumeRatio%": "買賣權成交量比率%", "PutOI": "賣權未平倉量", "CallOI": "買權未平倉量",
               "PutCallOIRatio%": "買賣權未平倉量比率%"}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers.values())
    for r in data:
        w.writerow([r[k] for k in headers])
    as_csv = ("﻿" + buf.getvalue()).encode("utf-8")
    assert tf.parse_put_call_ratio(tf.decode_rows(as_csv)) == tf.parse_put_call_ratio(data)
    with pytest.raises(ProviderUnavailable):
        tf.decode_rows(b"<html>blocked</html>")


def test_weekly_datasets_and_contract_map():
    fs = tf.parse_final_settlement(rows("taifex_final_settlement_live_20261112.json"))
    assert max(r["settlement_day"] for r in fs) == date(2025, 12, 5)  # stale: nothing after 2025-12-05
    assert any(r["contract"] == "TX/MTX/TMF" for r in fs)
    idx = {r["contract"]: r for r in tf.parse_margins(rows("taifex_margins_index_live_20261112.json"), "index")}
    assert idx["臺股期貨"]["initial"] == D(701000) and not idx["臺股期貨"]["is_rate"]
    stock = {r["contract"]: r for r in tf.parse_margins(rows("taifex_margins_stock_live_20261112.json"), "stock")}
    assert stock["CDF"]["is_rate"] and stock["CDF"]["underlying_code"] == "2330"
    assert stock["CAF"]["initial"] == D("0.2025")  # "20.25%"
    ssf = tf.parse_underlyings(rows("taifex_ssf_lists_live_20261112.json"), "SSF")
    assert {(r["contract"], r["stock_code"]) for r in ssf} >= {("CDF", "2330"), ("QFF", "2330"), ("NYF", "0050")}
    lt = tf.parse_large_traders(rows("taifex_large_traders_futures_live_20261112.json"), "futures")
    cmap = {r["name_zh"]: r for r in tf.contract_map_rows(large_traders=lt, margins=stock.values())}
    assert cmap["臺股期貨"]["contract_code"] == "TX" and cmap["臺股期貨"]["source"] == "static"
    assert cmap["臺股期貨(TX+MTX/4)"]["contract_code"] == "TX"
    assert cmap["台積電期貨"]["contract_code"] in ("CD", "CDF") and cmap["股票期貨"]["contract_code"] is None
