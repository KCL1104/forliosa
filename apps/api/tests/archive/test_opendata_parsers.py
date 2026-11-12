"""Parsers for the official datasets, on trimmed live responses (2026-11-12)."""

from datetime import date
from decimal import Decimal as D

from forliosa.marketdata import opendata as od
from forliosa.marketdata.finmind import parse_institutional, parse_margin, parse_news, parse_shareholding
from tests.archive.fakes import FIX, load


def test_twt84u_reference_and_limits():
    rows = {r["code"]: r for r in od.parse_twt84u(load("twse_twt84u_live_20261112.json"))}
    r = rows["2330"]
    assert (r["reference_price"], r["limit_up"], r["limit_down"]) == (D("2395.00"), D("2630.00"), D("2160.00"))
    assert r["last_trading_day"] == date(2026, 11, 11) and r["previous_close"] == D("2395.00")
    assert rows["1538"]["previous_close"] is None  # "0.00" = no trade on the last day


def test_mi_margn_lots():
    rows = {r["code"]: r for r in od.parse_mi_margn(load("twse_mi_margn_live_20261112.json"))}
    assert rows["2330"] == {"code": "2330", "margin_balance": 32523, "short_balance": 93, "margin_limit": 6483092}


def test_notice_placeholder_row_is_skipped_and_punish_period():
    assert od.parse_twse_notice(load("twse_notice_live_20261112.json")) == []
    ev = od.parse_twse_punish(load("twse_punish_live_20261112.json"))[0]
    assert ev["type"] == "disposition" and ev["date"] == date(2026, 11, 9) and ev["end_date"] == date(2026, 11, 13)
    assert ev["title"] == "處置股票（第一次處置）"


def test_material_info_key_with_trailing_space():
    events = od.parse_material_info(load("twse_t187ap04_l_live_20261112.json"), "TWSE")
    quanta = [e for e in events if e["code"] == "2382"]
    assert quanta and quanta[0]["title"] == "公告本公司董事會通過115年第三季財務報告"
    assert quanta[0]["date"] == date(2026, 11, 11)
    assert len({e["key"] for e in events}) == len(events)


def test_statements_are_year_to_date():
    inc = {r["code"]: r for r in od.parse_statements(load("tpex_t187ap06_o_ci_live_20261112.json"), "income_ytd")}
    r = inc["6488"]
    assert r["period"] == "2026Q3"
    # 6488 2026Q1–Q3 in shioaji-data: 13,984,798 + 15,214,310 + 14,870,753 = 44,069,861 (thousand NT$)
    assert D(r["values"]["revenue"]) == D("44069861.00") and D(r["values"]["eps"]) == D("15.00")
    bal = {r["code"]: r for r in od.parse_statements(load("twse_t187ap07_l_ci_live_20261112.json"), "balance")}
    assert bal["2382"]["period"] == "2026Q3" and bal["2382"]["values"]["total_assets"] is not None
    margins = {r["code"]: r for r in od.parse_profit_analysis(load("tpex_t187ap17_o_live_20261112.json"))}
    assert D(margins["6488"]["values"]["gross"]) == D("0.2048")


def test_tpex_datasets():
    ref = {r["code"]: r for r in od.parse_tpex_reference(load("tpex_daily_close_quotes_live_20261112.json"))}
    assert (ref["3680"]["reference_price"], ref["3680"]["limit_up"], ref["3680"]["limit_down"]) == (
        D("425.50"), D("468.00"), D("383.50"))  # ex-dividend on 2026-11-12
    inst = {r["code"]: r for r in od.parse_tpex_institutional(load("tpex_3insti_daily_trading_live_20261112.json"))}
    assert (inst["6488"]["foreign_net"], inst["6488"]["trust_net"], inst["6488"]["dealer_net"],
            inst["6488"]["total_net"]) == (1265318, -405182, 442393, 1302529)
    qfii = {r["code"]: r for r in od.parse_tpex_qfii(load("tpex_3insti_qfii_live_20261112.json"))}
    assert qfii["6488"]["pct"] == D("0.2949")
    per = {r["code"]: r for r in od.parse_tpex_peratio(load("tpex_peratio_analysis_live_20261112.json"))}
    assert (per["6488"]["per"], per["6488"]["pbr"], per["6488"]["dividend_yield"]) == (D("35.75"), D("2.30"),
                                                                                        D("0.0121"))
    margin = {r["code"]: r for r in od.parse_tpex_margin(load("tpex_margin_balance_live_20261112.json"))}
    assert (margin["6488"]["margin_balance"], margin["6488"]["short_balance"]) == (9653, 195)
    ex = {r["code"]: r for r in od.parse_tpex_exright_events(load("tpex_exright_prepost_live_20261112.json"))}
    assert ex["6488"]["date"] == date(2026, 12, 29) and ex["6488"]["data"]["cash"] == "6.00000000"
    assert ex["00844B"]["detail"] == "金額尚未公告"
    disp = od.parse_tpex_disposal(load("tpex_disposal_live_20261112.json"))[0]
    assert disp["date"] == date(2026, 11, 12) and disp["end_date"] == date(2026, 11, 18)


def test_tdcc_distribution():
    rows = od.parse_tdcc_distribution((FIX / "tdcc_1-5_live_20261106.csv").read_text(encoding="utf-8"))
    big = next(r for r in rows if r["code"] == "2330" and r["level"] == 15)
    assert big["date"] == date(2026, 11, 6) and big["holders"] == 1470 and big["pct"] == D("0.8424")
    total = next(r for r in rows if r["code"] == "2330" and r["level"] == 17)
    assert total["shares"] == 25932370067


def test_finmind_chip_and_news_parsers():
    # Live FinMind rows (2026-11-11/12; FinMind is a non-commercial personal opt-in only):
    # 22,452,348 + 0 + 4,440,000 + 11,197,808 = 38,090,156 shares.
    inst = parse_institutional(load("finmind_institutional_0050_live_20261112.json")["data"])
    assert inst == [{"date": date(2026, 11, 11), "foreign_net": 22452348, "trust_net": 4440000,
                     "dealer_net": 11197808, "total_net": 38090156}]
    assert parse_margin([{"date": "2026-11-10", "MarginPurchaseTodayBalance": 44241, "ShortSaleTodayBalance": 1,
                          "MarginPurchaseLimit": 6262000}])[0]["margin_balance"] == 44241
    assert parse_shareholding([{"date": "2026-11-10", "ForeignInvestmentSharesRatio": 2.6,
                                "ForeignInvestmentShares": 649672834}])[0]["pct"] == D("0.026")
    news = parse_news(load("finmind_news_2330_live_20261111.json")["data"])
    assert news[0] == {"published_at": "2026-11-11 00:34:44", "title": "台積電(2330) 個股概覽 | 個股 - 股市 - CMoney",
                       "source": "CMoney", "url": "https://www.cmoney.tw/finance/2330/f00025"}
    assert parse_news([{"date": "2026-11-11", "title": "no link", "link": ""}]) == []


def test_mi_index_and_mfi94u_total_return_agree():
    idx = {r["name"]: r for r in od.parse_mi_index(load("twse_mi_index_live_20261112.json"))}
    tr = idx[od.TAIEX_TR]
    assert (tr["date"], tr["close"], tr["change"], tr["change_pct"]) == (
        date(2026, 11, 11), D("102340.20"), D("3573.19"), D("0.0362"))
    assert idx["觀光餐旅類指數"]["change"] == D("-0.81")  # 漲跌點數 is unsigned; the sign is in 漲跌
    mfi = od.with_changes(od.parse_mfi94u(load("twse_mfi94u_live_20261112.json")))
    assert len(mfi) == 8 and mfi[0]["date"] == date(2026, 11, 2) and mfi[0]["change"] is None
    assert mfi[-1]["close"] == tr["close"] and mfi[-1]["change"] == D("102340.20") - D("98767.01")


def test_tpex_indices_mixed_date_formats():
    idx = od.parse_tpex_index(load("tpex_index_live_20261112.json"))  # Gregorian 20261102
    reward = od.parse_tpex_reward_index(load("tpex_reward_index_live_20261112.json"))  # ROC 1151102
    assert idx[-1]["date"] == date(2026, 11, 12) and idx[-1]["close"] == D("335.73")
    tr = {r["date"]: r["close"] for r in reward if r["name"] == od.TPEX_TR}
    plain = {r["date"]: r["close"] for r in reward if r["name"] == od.TPEX_INDEX}
    assert tr[date(2026, 11, 12)] == D("624.57") and plain[date(2026, 11, 12)] == idx[-1]["close"]


def test_dividend_resolutions_split_cash_by_source():
    rows = od.parse_dividend_resolutions(load("twse_t187ap45_l_live_20261112.json"))
    tcc = next(r for r in rows if r["code"] == "1101")
    # 台泥 FY2025: no dividend from earnings; NT$0.8 per share from capital surplus, confirmed by the AGM
    assert (tcc["period"], tcc["progress"], tcc["cash_earnings"], tcc["cash_capital_surplus"]) == (
        "2025", "股東會確認", D(0), D("0.80000000"))
    assert (tcc["board_date"], tcc["meeting_date"]) == (date(2026, 3, 11), date(2026, 5, 22))
    tsmc = {r["period"]: r for r in rows if r["code"] == "2330"}
    assert set(tsmc) == {"2025Q4", "2026Q1", "2026Q2", "2026Q3"}
    assert tsmc["2026Q3"]["cash_earnings"] == D("9.00000000") and tsmc["2026Q3"]["board_date"] == date(2026, 11, 10)
    assert tsmc["2026Q3"]["period_start"] == date(2026, 7, 1) and tsmc["2026Q3"]["meeting_date"] is None
    halves = {r["period"] for r in rows if r["code"] == "2382"}
    assert halves == {"2025H2", "2026H1"}  # 股利所屬年(季)度 上半年／下半年


def test_company_profiles_keep_company_facts_only():
    twse = {r["code"]: r for r in od.parse_company_profiles(load("twse_t187ap03_l_live_20261112.json"), "TWSE")}
    tsmc = twse["2330"]
    assert (tsmc["shares_outstanding"], tsmc["industry_code"], tsmc["industry"], tsmc["listed_date"]) == (
        25932370067, "24", "半導體業", date(1994, 9, 5))
    assert tsmc["values"]["short_name"] == "台積電" and tsmc["values"]["hq"] == "新竹科學園區"
    # decision 6: 董事長／總經理 exactly as published; spokespeople, CPAs, phones are not read
    assert (tsmc["values"]["chairman"], tsmc["values"]["president"]) == ("魏哲家", "總裁: 魏哲家")
    assert not any(x in str(tsmc["values"]) for x in ("黃仁昭", "高孟華", "吳世宗", "陳彥君", "03-5636688"))
    tpex = {r["code"]: r for r in od.parse_company_profiles(load("tpex_t187ap03_o_live_20261112.json"), "TPEX")}
    gw = tpex["6488"]
    assert gw["shares_outstanding"] == 528113725 and gw["listed_date"] == date(2015, 9, 25)
    assert (gw["values"]["chairman"], gw["values"]["president"]) == ("徐秀蘭", "Mark England")
    assert (gw["values"]["hq"], gw["values"]["website"]) == ("新竹科學園區", "https://www.sas-globalwafers.com")
    assert not any(x in str(gw["values"]) for x in ("彭欣瑜", "吳俊源", "03-5772255", "Industrial East Road"))
    # TPEx English addresses only when the city is certain: 家登 says "New Taipei County" -> 新北市
    assert tpex["3680"]["values"]["hq"] == "新北市" and tpex["8390"]["values"]["hq"] is None  # "Hsinchu" alone


def test_tpex_exright_official_reference():
    r = od.parse_tpex_exright_daily(load("tpex_exright_daily_live_20261112.json"))[0]
    assert (r["code"], r["date"], r["prev_close"], r["reference_price"], r["limit_up"], r["limit_down"]) == (
        "3680", date(2026, 11, 12), D("435.50"), D("425.50"), D("468.00"), D("383.50"))
    assert r["ex_quote"] == D("425.59") and r["cash_dividend"] == D("9.91474560")


def test_blank_industry_rows_and_securities_firm_spellings():
    assert od.parse_statements(load("tpex_t187ap07_o_ins_live_20261112.json"), "balance") == []
    assert od.parse_statements(load("tpex_t187ap07_o_mim_live_20261112.json"), "balance") == []
    bd = od.parse_statements(load("tpex_t187ap06_o_bd_live_20261112.json"), "income_ytd")[0]
    # 收益 / 營業利益 / 淨利（損）歸屬於母公司業主 (the securities-firm variant's spellings)
    assert (bd["values"]["revenue"], bd["values"]["operating_income"], bd["values"]["net_income_parent"]) == (
        "8046885.00", "3913370.00", "4120123.00")


def test_stale_endpoint_report_dates():
    assert od.report_date(load("twse_twtazu_od_live_20261112.json"), "出表日期") == date(2026, 6, 5)
    assert od.report_date(load("twse_t187ap09_l_live_20261112.json"), "出表日期") == date(2026, 8, 19)
