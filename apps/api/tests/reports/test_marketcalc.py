"""Rule calculations (contract §7): market caps and estimated contributions, limits from the reference prices, the 32
sectors with their concentration, the rule-made lists and their exclusions, security classes, TPEx amounts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from forliosa.reports import marketcalc as mc
from forliosa.services.instruments import security_class
from forliosa.services.market_overview import SECTOR_COMPOSITES
from tests.reports.conftest import MON, ts

CUT = ts(MON, 15, 40)


def test_security_classes():
    cases = {"01007T.TW": "reit", "00679B.TWO": "bond_etf", "0050.TW": "etf", "00632R.TW": "etf",
             "006208.TW": "etf", "00981A.TW": "etf", "020011.TW": "etn", "2330.TW": "stock", "2881A.TW": "preferred",
             "6488.TWO": "stock", "24552.TWO": "other"}
    assert {s: security_class(s) for s in cases} == cases
    # four-digit codes are stocks whatever the name; preferred shares carry a letter
    assert [security_class(s, n) for s, n in (("2908.TW", "特力"), ("3051.TW", "力特"), ("4772.TWO", "台特化"))] \
        == ["stock", "stock", "stock"]
    assert security_class("2002A.TW", "中鋼特") == "preferred"
    assert mc.is_common("2908", "特力", None) and mc.is_common("6706", "惠特", None)
    assert security_class("SPY", instrument_type="etf") == "etf" and security_class("TSM") == "stock"


def test_load_day_moves_from_reference_prices_and_marks_commons(market_db):
    day = mc.load_day(market_db, "TWSE", MON, CUT)
    assert day is not None and day.prev_day == date(2026, 11, 13)
    q = day.quotes["2330.TW"]
    assert q.name == "台積電" and q.base == D("1500") and q.pct == (D("1430") - 1500) / 1500
    assert q.mcap == D(25_932_000_000) * 1430 and q.common and q.day == MON
    assert not day.quotes["0050.TW"].common and day.quotes["01007T.TW"].cls == "reit"
    assert not day.quotes["9110.TW"].common  # a depositary receipt
    # official limits first: 台玻 closed at its limit down
    assert day.quotes["1802.TW"].limit_hit() == -1 and day.quotes["2330.TW"].limit_hit() == 0
    # the profile's other fields never travel with a quote
    assert "不該出現" not in repr(day.quotes["2330.TW"])


def test_computed_limits_round_to_the_tick():
    up, down = mc.computed_limits(D("152"))
    assert (up, down) == (D("167"), D("137"))  # 167.2 -> 167.0 and 136.8 -> 137.0 (tick 0.5 from 100 to 500)
    up, down = mc.computed_limits(D("9.87"))
    assert (up, down) == (D("10.85"), D("8.89"))


def test_contributions_add_up_to_the_cap_weighted_change(market_db):
    day = mc.load_day(market_db, "TWSE", MON, CUT)
    prev_taiex = D("43675.12")
    contrib = mc.contributions(day, prev_taiex)
    commons = [q for q in day.commons() if q.mcap_prev is not None]
    now, before = sum(q.mcap for q in commons), sum(q.mcap_prev for q in commons)
    official_like = prev_taiex * (now / before - 1)  # every base is the previous close here
    assert abs(sum(contrib.values()) - official_like) < D("0.000001")
    assert contrib["2330.TW"] < 0 and "0050.TW" not in contrib


def test_sectors_are_32_without_composites_and_flag_concentration(market_db):
    assert {"電子工業", "機電", "塑膠化工", "水泥窯製", "化學生技醫療"} == set(SECTOR_COMPOSITES)
    assert len(mc.SECTOR_CODES) == 32 and not set(mc.SECTOR_CODES) & SECTOR_COMPOSITES
    day = mc.load_day(market_db, "TWSE", MON, CUT)
    secs = {s.name: s for s in mc.sectors(market_db, MON, CUT, day)}
    assert "電子工業" not in secs and "機電" not in secs and "半導體類報酬" not in secs
    glass = secs["玻璃陶瓷"]  # 台玻 is its only member here
    assert glass.concentrated and not glass.text_eligible
    assert mc.concentration_text(glass) == "主要由台玻構成（約 100%）"
    semi = secs["半導體"]
    assert semi.text_eligible and semi.concentrated  # 台積電 ≈ 94 % of the members' cap here
    ranked = [s for s in sorted(secs.values(), key=lambda s: -s.pct) if not s.concentrated]
    assert {s.name for s in ranked[:3]} | {s.name for s in ranked[-3:]} | {"半導體"} == \
        {s.name for s in secs.values() if s.text_eligible}


def test_rule_lists_scope_and_exclusions(market_db):
    day = mc.load_day(market_db, "TWSE", MON, CUT)
    lists = mc.rule_lists(market_db, day)
    assert [q.code for q in lists.top10][:3] == ["2330", "2317", "2454"]
    gainers = [q.code for q in lists.gainers]
    assert "4743" not in gainers  # innovation board
    assert "2455" not in gainers  # under disposition on 11/16
    assert "1213" not in gainers  # altered trading (the first run's backlog counts from any day)
    assert lists.excluded == {"innovation_board": 1, "disposition": 1, "altered_trading": 1}
    assert lists.losers[0].code == "1802" and lists.limit_down_many is None
    assert lists.value_column == "value" and lists.by_value[0].code == "2330"


def test_many_limit_downs_turn_the_losers_into_the_largest_limit_down_stocks(db):
    quotes = {}
    for i in range(12):
        code = f"{1100 + i}"
        quotes[f"{code}.TW"] = mc.Quote(f"{code}.TW", code, "TWSE", f"股{i}", D("90"), D("100"), D("100"), None, 10,
                                        1_000_000 * (i + 1), "01", D("110"), D("90"), "stock", True, "x",
                                        date(2026, 11, 16))
    quotes["2000.TW"] = mc.Quote("2000.TW", "2000", "TWSE", "跌最少", D("99"), D("100"), D("100"), None, 10, 1,
                                 "01", D("110"), D("90"), "stock", True, "x", date(2026, 11, 16))
    lists = mc.rule_lists(db, mc.Day("TWSE", date(2026, 11, 16), date(2026, 11, 13), quotes))
    assert lists.limit_down_many == 12
    assert [q.code for q in lists.losers] == ["1111", "1110", "1109", "1108", "1107"]  # the 5 largest of them
    assert lists.value_column == "volume"  # no 成交金額 in these rows: ranked by volume


def test_otc_amounts_are_shares_times_close_and_otc_sectors_need_three_members(market_db):
    day = mc.load_day(market_db, "TPEX", MON, ts(MON, 23, 45))
    sums, per = mc.otc_institutional(market_db, day, ts(MON, 23, 45))
    expected = sum(D(700_000) * q.close for q in day.quotes.values())
    assert sums["total"] == expected and len(per) == 3
    assert mc.otc_institutional(market_db, day, ts(MON, 15, 40)) is None  # not out before 23:40
    secs = mc.otc_sectors(day)
    assert secs == []  # 半導體 has two OTC members here, 光電 one: none is listed


@pytest.mark.parametrize(("d", "back"), [(date(2026, 12, 9), date(2026, 11, 9)),
                                         (date(2026, 3, 31), date(2026, 2, 28))])
def test_month_back(d, back):
    assert mc.month_back(d) == back
