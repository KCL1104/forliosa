"""中央銀行〈銀行間新臺幣對美元收盤匯率〉 (FTDOpenData_Day) on a trimmed live response (2026-11-12)."""

from datetime import date
from decimal import Decimal as D

import pytest

from forliosa.marketdata import cbc
from forliosa.marketdata import taifex as tf
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import DEFAULT_LIMITER, url_allowed
from tests.archive.fakes import FIX, load

FIXTURE = "cbc_ftd_day_live_20261112.json"


def test_parses_the_whole_history_oldest_first():
    raw = load(FIXTURE)
    assert raw[0] == {"日期": "20080102", "NTD_USD": "32.443"}  # the live shape, untouched
    rows = cbc.parse_fx_day(raw)
    assert len(rows) == len(raw) == 36
    assert rows[0] == {"date": date(2008, 1, 2), "pair": "USDTWD", "rate": D("32.443")}
    assert rows[-1] == {"date": date(2026, 11, 12), "pair": "USDTWD", "rate": D("32.889")}
    by = {r["date"]: r["rate"] for r in rows}
    assert by[date(2026, 11, 11)] == D("32.86")  # one or two decimals as published
    assert by[date(2025, 12, 31)] == D("31.438") and by[date(2026, 1, 2)] == D("31.419")  # across a year end
    assert [r["date"] for r in rows] == sorted(by)


def test_matches_the_taifex_reference_rate():
    """TAIFEX's 每日外幣參考匯率 USD/NTD is the same number on every day both fixtures have."""
    ours = {r["date"]: r["rate"] for r in cbc.parse_fx_day(load(FIXTURE))}
    taifex = {r["date"]: r["rate"] for r in tf.parse_fx(tf.decode_rows((FIX / "taifex_fx_rates_live_20261112.csv")
                                                                         .read_bytes())) if r["pair"] == "USDTWD"}
    assert len(taifex) == 27 and all(ours[d] == rate for d, rate in taifex.items())


def test_bad_rows_are_skipped_and_a_renamed_field_is_an_error():
    rows = cbc.parse_fx_day([{"日期": "20261111", "NTD_USD": "32.86"}, {"日期": "20261112", "NTD_USD": ""},
                             {"日期": "", "NTD_USD": "32.9"}, {"日期": "20261113", "NTD_USD": "0"}, "x",
                             {"日期": "20261111", "NTD_USD": "32.86"}])
    assert rows == [{"date": date(2026, 11, 11), "pair": "USDTWD", "rate": D("32.86")}]
    with pytest.raises(ProviderUnavailable, match="空的"):  # a valid answer is always the whole history
        cbc.parse_fx_day([])
    with pytest.raises(ProviderUnavailable, match="欄位不符"):  # only unusable rows
        cbc.parse_fx_day([{"日期": "20261112", "NTD_USD": ""}, "x"])
    with pytest.raises(ProviderUnavailable, match="欄位不符"):
        cbc.parse_fx_day([{"Date": "20261111", "USD": "32.86"}])
    with pytest.raises(ProviderUnavailable, match="格式不符"):
        cbc.parse_fx_day({"message": "error"})


def test_only_the_open_data_api_is_allowlisted():
    assert url_allowed(cbc.FX_DAY_URL) and url_allowed("https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Month")
    assert not url_allowed("https://cpx.cbc.gov.tw/Data/ExportToAPIInfo")
    assert not url_allowed("https://www.cbc.gov.tw/tw/cp-2151-188471-bc29b-1.html")
    assert DEFAULT_LIMITER.interval_for("cpx.cbc.gov.tw") == 2.0
