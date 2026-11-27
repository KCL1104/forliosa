"""``get_market_trend`` — the chat's multi-session view of the market (owner 2026-11-27: 「改為分析趨勢並給予建議」;
the chat only had the latest session's sector ranking). Everything comes from the official archive, over sessions that
follow one another; a period the archive does not reach is left out and named, never worked out."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from forliosa.ai import market_tools
from forliosa.ai.tools import TOOLS_BY_NAME, ToolContext, execute
from forliosa.models import IndexDaily, MarketTurnoverDaily
from forliosa.timeutil import tw_trading_days
from tests.reports.conftest import FRI, MON

TAIEX = "發行量加權股價指數"
BASE5, BASE10 = date(2026, 11, 9), date(2026, 11, 2)  # 5 and 10 sessions before Monday 11/16
# sector: (close 10 sessions before, close 5 sessions before); Friday is 100 and Monday 100 × (1 + its move) in the
# conftest (水泥 102, 金融保險 101.1, 電腦及週邊設備 103.33, 通信網路 101, 半導體 95.5, 玻璃陶瓷 90.5 …)
SECTOR_HISTORY = {"水泥": ("100", "96"), "金融保險": ("95", "100"), "電腦及週邊設備": ("90", "95"),
                  "通信網路": ("104", "100"), "半導體": ("105", "110"), "玻璃陶瓷": ("110", "100"),
                  "其他電子": ("100", "100"), "電子零組件": ("100", "100"), "光電": ("100", "100"),
                  "電子工業": ("100", "100"), "機電": ("100", "100")}


def _history(db, sectors: bool = True) -> None:
    """Fourteen TAIEX sessions before the conftest's Friday (each 100 points above the next; the oldest lower than
    the one after it, so the run of falls has a known first day), and the sectors' closes 5 and 10 sessions back."""
    days = tw_trading_days(date(2026, 11, 12) - timedelta(days=40), date(2026, 11, 12))[-14:]
    for i, d in enumerate(reversed(days)):
        close = D("43775.12") + 100 * i - (150 if i == 13 else 0)
        db.add(IndexDaily(name=TAIEX, date=d, market="TWSE", close=close, change=D("-100"), change_pct=D("0.0023"),
                          source="twse-openapi"))
    if sectors:
        for name, (ten, five) in SECTOR_HISTORY.items():
            for d, close in ((BASE10, ten), (BASE5, five)):
                db.add(IndexDaily(name=f"{name}類指數", date=d, market="TWSE", close=D(close), change=D("0"),
                                  change_pct=D("0"), source="twse-openapi"))
    db.commit()


@pytest.fixture()
def ctx(market_db):
    market_tools.clear_cache()
    yield ToolContext(db=market_db, user=SimpleNamespace(id="usr_x"), md=SimpleNamespace(policy="commercial"))
    market_tools.clear_cache()


def _trend(ctx):
    out = execute(ctx, "get_market_trend", {})
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_the_tool_is_offered_to_the_chat():
    spec = TOOLS_BY_NAME["get_market_trend"]
    assert spec.label({}) == "查看市場趨勢" and not spec.required and "official archive only" in spec.description


def test_the_taiex_over_sessions_in_a_row(ctx):
    _history(ctx.db)
    res = _trend(ctx)
    taiex = res["taiex"]
    assert res["as_of"] == MON.isoformat() and taiex["close"] == "41,040.08" and taiex["change_1_day"] == "−6.03%"
    # 5 sessions back the index closed at 44,075.12, 10 back at 44,575.12
    assert taiex["periods"] == [
        {"period": "近 5 個交易日", "from_close_of": BASE5.isoformat(), "change": "−6.89%"},
        {"period": "近 10 個交易日", "from_close_of": BASE10.isoformat(), "change": "−7.93%"}]
    assert taiex["averages"] == [{"name": "5 日線", "value": "43,268.11", "close_is": "之下"},
                                 {"name": "10 日線", "value": "43,771.62", "close_is": "之下"}]
    assert taiex["streak"] == "連 14 日下跌"
    # sixteen sessions in a row: no 20-session move, no 20-session average — said, not worked out
    assert res["notes"] == ["存檔裡到 11/16 為止連續的交易日有 16 個：近 20 個交易日的漲跌還沒有，不要自己推算"]
    # the official turnover of the newest session that has one; an average needs five official sessions in a row
    assert res["listed_turnover"] == {"date": MON.isoformat(), "value": "9,031 億元"}
    assert [(x["name"], x["change_1_day"]) for x in res["other_indices"]] == [
        ("櫃買指數", "−6.80%"), ("臺灣50", "−5.80%"), ("中型100", "−4.00%"), ("小型股300", "−3.00%")]
    assert "不是支撐或壓力" in res["units"] and "不是挑選" in res["units"]


def test_sectors_are_ranked_over_five_sessions_with_their_largest_stocks(ctx):
    _history(ctx.db)
    sectors = _trend(ctx)["sectors"]
    assert sectors["ranked_by"] == "近 5 個交易日" and sectors["taiex_same_period"] == "−6.89%"
    names = [x["name"] for x in sectors["strongest"]]
    # 電腦及週邊設備 95 → 103.33, 水泥 96 → 102, 金融保險 100 → 101.1, 通信網路 100 → 101 …
    assert names[:4] == ["電腦及週邊設備", "水泥", "金融保險", "通信網路"] and len(names) == 6
    top = sectors["strongest"][0]
    assert top["change_1_day"] == "+3.33%" and top["近 5 個交易日"] == "+8.77%" and top["近 10 個交易日"] == "+14.81%"
    assert top["vs_taiex"] == "+15.66 個百分點" and top["also_strong_近 10 個交易日"] is True
    # the largest stocks of a strong sector, by market cap: a stated rule
    assert [s["name"] for s in top["largest_stocks"]] == ["緯穎"]
    assert top["largest_stocks"][0]["symbol"] == "6669.TW" and top["largest_stocks"][0]["change_1_day"] == "+3.33%"
    weakest = sectors["weakest"]
    assert weakest[0]["name"] == "半導體" and weakest[0]["近 5 個交易日"] == "−13.18%"
    # a sector one stock dominates says so (the reports' rule: 半導體 is never named without it)
    assert weakest[0]["note"].startswith("主要由台積電構成（約 ")
    assert "largest_stocks" not in weakest[0]
    assert not set(names) & {x["name"] for x in weakest}


def test_a_short_archive_ranks_by_the_day_and_says_what_is_missing(ctx):
    # the conftest's two sessions only: no multi-session move of anything
    res = _trend(ctx)
    assert res["taiex"]["periods"] == [] and "averages" not in res["taiex"] and "streak" not in res["taiex"]
    assert res["sectors"]["ranked_by"] == "1 日"
    assert [x["name"] for x in res["sectors"]["strongest"]][:2] == ["電腦及週邊設備", "水泥"]
    assert all(set(x) <= {"name", "change_1_day", "vs_taiex", "note", "largest_stocks"}
               for x in res["sectors"]["strongest"])
    assert res["notes"][0].startswith("存檔裡到 11/16 為止連續的交易日有 2 個：近 5 個交易日、近 10 個交易日、")


def test_turnover_against_its_average_needs_five_official_sessions(ctx):
    _history(ctx.db, sectors=False)
    for d, value in ((FRI, 1_000_000_000_000), (date(2026, 11, 12), 900_000_000_000),
                     (date(2026, 11, 11), 900_000_000_000), (date(2026, 11, 10), 800_000_000_000)):
        ctx.db.add(MarketTurnoverDaily(date=d, market="TWSE", trade_value=value, source="twse-openapi"))
    ctx.db.commit()
    # (9,031 + 10,000 + 9,000 + 9,000 + 8,000) / 5 = 9,006 億元
    assert _trend(ctx)["listed_turnover"] == {"date": MON.isoformat(), "value": "9,031 億元",
                                              "vs_5_session_average": "100%", "vs_previous_session": "少 969 億元"}


def test_nothing_archived(db):
    market_tools.clear_cache()
    c = ToolContext(db=db, user=SimpleNamespace(id="usr_x"), md=SimpleNamespace(policy="commercial"))
    assert json.loads(execute(c, "get_market_trend", {}).content) == {"status": "none",
                                                                     "note": "目前沒有加權指數的收盤資料"}
