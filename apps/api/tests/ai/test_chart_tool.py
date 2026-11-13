"""``draw_chart``: the model picks what to draw; every point comes from the server's own data. ``get_related_stocks``
lists who to look at when a stock has no news of its own. Both are plain tools: nothing here writes the ledger."""

from __future__ import annotations

import json
import math
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

import forliosa.ai.charts as charts_mod
import forliosa.services.instruments as instr_mod
import forliosa.services.stock as stock_svc
from forliosa.ai import charts
from forliosa.ai.prompts import CHAT_SYSTEM
from forliosa.ai.tools import TOOLS_BY_NAME, ToolContext, execute, tool_label
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import CorporateEvent, RevenueRow
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import Answer, MarketData, get_market_data, set_market_data
from forliosa.models import PriceDaily, User
from forliosa.timeutil import tw_trading_days
from tests.ai.conftest import API, buy, chat, make_account
from tests.ai.fake_anthropic import text, tool_use
from tests.ai.test_tools import user_by_email

FIRST, LAST_DAY, TODAY = date(2026, 6, 1), date(2026, 11, 12), date(2026, 11, 13)
DAYS = tw_trading_days(FIRST, LAST_DAY)
CLOSES = [round(1000 + 0.8 * i + 15 * math.sin(i / 6), 1) for i in range(len(DAYS))]


def rows(symbol: str, days: list[date], closes: list[float]) -> list[PriceDaily]:
    return [PriceDaily(symbol=symbol, date=d, open=D(str(c)), high=D(str(c)), low=D(str(c)), close=D(str(c)),
                       volume=1_000_000, source="twse-openapi") for d, c in zip(days, closes, strict=True)]


def run(ctx, **args):
    out = execute(ctx, "draw_chart", args)
    return out, (json.loads(out.content) if not out.is_error else out.content)


@pytest.fixture()
def arch(engine, market, monkeypatch):
    """A commercial facade over an archive that starts on 2026-06-01: 2330 has every close up to 11/12, 2454 only
    the last 12, 2317 none. "Today" is Friday 2026-11-13."""
    with Session(engine) as db:
        db.add_all(rows("2330.TW", DAYS, CLOSES))
        db.add_all(rows("2454.TW", DAYS[-12:], [500.0 + 5 * i for i in range(12)]))
        db.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    for mod in (charts_mod, instr_mod):
        monkeypatch.setattr(mod, "today_taipei", lambda: TODAY)
    db = Session(engine)
    yield ToolContext(db=db, user=None, md=md)  # type: ignore[arg-type]
    db.close()
    set_market_data(market)


def test_price_chart_reads_the_archived_closes(arch):
    out, res = run(arch, kind="price", symbols=["2330"], range="6M")
    assert not out.is_error and res["status"] == "chart_shown" and res["kind"] == "price"
    card = out.chart
    assert card is not None and arch.charts == [card] and card["id"] == res["chart_id"]
    assert card["title"] == "台積電 收盤價（近 6 個月）" and card["unit"] == "price" and card["currency"] == "TWD"
    assert card["x"] == "date" and card["range"] == "6M" and card["is_demo"] is False
    (line,) = card["series"]
    assert line["symbol"] == "2330.TW" and len(line["points"]) == len(DAYS)
    assert line["points"][0] == {"t": FIRST.isoformat(), "v": CLOSES[0]}
    assert line["points"][-1] == {"t": LAST_DAY.isoformat(), "v": CLOSES[-1]}
    assert "收盤價沒有還原權息，除權息日會有缺口" in card["notes"]
    assert card["sources"] and all(isinstance(s, str) for s in card["sources"])
    # the model reads a summary, never the points
    (s,) = res["series"]
    assert s["points"] == len(DAYS) and s["first"] == CLOSES[0] and s["last"] == CLOSES[-1]
    assert s["change_pct"] == round(CLOSES[-1] / CLOSES[0] - 1, 4)
    assert s["high"]["v"] == max(CLOSES) and s["low"]["v"] == min(CLOSES)
    assert "points" not in json.dumps(res["series"][0]["high"]) and len(out.content) < 2000
    assert res["instruction"] == charts.SHOWN


def test_a_short_archive_says_where_the_data_starts(arch):
    out, res = run(arch, kind="price", symbols=["2454"], range="1Y")
    assert res["status"] == "chart_shown" and len(out.chart["series"][0]["points"]) == 12
    assert f"資料從 {DAYS[-12]:%Y/%m/%d} 開始" in out.chart["notes"]


def test_nothing_is_drawn_without_two_closes(arch):
    out, res = run(arch, kind="price", symbols=["2317"], range="6M")
    assert not out.is_error and out.chart is None and arch.charts == []
    assert res["status"] == "no_data" and res["notes"] and res["instruction"] == charts.NOT_SHOWN
    # US stocks have no quotes under the commercial policy
    out, res = run(arch, kind="price", symbols=["AAPL"], range="6M")
    assert out.chart is None and res["status"] == "no_data" and any("美股沒有報價" in n for n in res["notes"])


def test_compare_starts_every_line_at_zero_on_the_first_common_day(arch):
    out, res = run(arch, kind="compare", symbols=["2330", "2454", "2317"], range="1Y")
    card = out.chart
    assert card["kind"] == "compare" and card["unit"] == "pct" and card["title"] == "台積電、聯發科 漲跌幅（近 1 年）"
    base = DAYS[-12]
    assert [s["symbol"] for s in card["series"]] == ["2330.TW", "2454.TW"]
    for s in card["series"]:
        assert s["points"][0] == {"t": base.isoformat(), "v": 0.0} and len(s["points"]) == 12
    tsmc, mtk = card["series"]
    assert tsmc["points"][-1]["v"] == pytest.approx(CLOSES[-1] / CLOSES[-12] - 1, abs=1e-6)
    assert mtk["points"][-1]["v"] == pytest.approx(555 / 500 - 1, abs=1e-6)
    notes = card["notes"]
    assert f"從 {base:%Y/%m/%d} 起算：聯發科 的資料從這天開始" in notes and charts.PRICE_ONLY_NOTE in notes
    assert any(n.startswith("鴻海：") and n.endswith("沒有畫") for n in notes)
    assert [s["name"] for s in res["series"]] == ["台積電", "聯發科"] and "change_pct" not in res["series"][0]
    # one usable line is not a comparison
    out, res = run(arch, kind="compare", symbols=["2330", "2317"], range="1Y")
    assert out.chart is None and res["status"] == "no_data"


def test_compare_stays_continuous_across_a_split(arch, monkeypatch):
    split_day = DAYS[-6]
    monkeypatch.setattr(arch.md, "corporate_events",
                        lambda s: [CorporateEvent(s, split_day, "split", D(4))] if s == "2454.TW" else [])
    with Session(arch.db.get_bind()) as db:  # after the 1:4 split the raw close is a quarter
        for r in db.query(PriceDaily).filter(PriceDaily.symbol == "2454.TW", PriceDaily.date >= split_day):
            r.close = r.close / 4
        db.commit()
    out, _ = run(arch, kind="compare", symbols=["2330", "2454"], range="1Y")
    mtk = next(s for s in out.chart["series"] if s["symbol"] == "2454.TW")
    assert mtk["points"][-1]["v"] == pytest.approx(555 / 500 - 1, abs=1e-6)  # not −72 %
    assert f"聯發科 {split_day:%Y/%m/%d} 股票分割，漲跌幅已調整" in out.chart["notes"]
    out, _ = run(arch, kind="price", symbols=["2454"], range="1Y")
    assert f"{split_day:%Y/%m/%d} 股票分割（1 股變 4 股），之前是當時的價格" in out.chart["notes"]


def test_charts_read_the_history_backfill_and_do_not_adjust_it_twice(arch, monkeypatch):
    """PRICE_HISTORY_SOURCE=yahoo: the days before the archive come split-adjusted. A chart reads them, says whose
    data they are, and a split inside them is neither adjusted again nor described as 「當時的價格」."""
    from forliosa.config import get_settings
    from forliosa.datapolicy import HISTORY_SOURCE

    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    get_settings.cache_clear()
    try:
        old_days = tw_trading_days(date(2026, 3, 2), date(2026, 5, 29))
        split_day = old_days[10]
        with Session(arch.db.get_bind()) as db:  # continuous across the split: the source already adjusted it
            db.add_all([PriceDaily(symbol="2454.TW", date=d, close=D("500"), source=HISTORY_SOURCE) for d in old_days])
            db.add_all(rows("2454.TW", DAYS[:-12], [500.0] * (len(DAYS) - 12)))
            db.add_all([PriceDaily(symbol="2330.TW", date=d, close=D("1000"), source=HISTORY_SOURCE)
                        for d in old_days])
            db.commit()
        monkeypatch.setattr(arch.md, "corporate_events",
                            lambda s: [CorporateEvent(s, split_day, "split", D(4))] if s == "2454.TW" else [])
        out, _ = run(arch, kind="price", symbols=["2454"], range="1Y")
        card = out.chart
        assert card["series"][0]["points"][0]["t"] == old_days[0].isoformat()
        assert any("Yahoo Finance" in n for n in card["notes"]) and any("Yahoo Finance" in s for s in card["sources"])
        assert not any("之前是當時的價格" in n for n in card["notes"])
        out, _ = run(arch, kind="compare", symbols=["2330", "2454"], range="1Y")
        mtk = next(s for s in out.chart["series"] if s["symbol"] == "2454.TW")
        assert max(abs(p["v"]) for p in mtk["points"]) < 0.2  # no ×4 jump on the split day
        assert not any("漲跌幅已調整" in n for n in out.chart["notes"])
    finally:
        monkeypatch.delenv("PRICE_HISTORY_SOURCE")
        get_settings.cache_clear()


def test_arguments_are_checked_and_cards_are_capped(arch):
    for args, hint in [
        ({"kind": "price", "symbols": ["2330", "2454"], "range": "6M"}, "price 一次畫一檔"),
        ({"kind": "compare", "symbols": ["2330"], "range": "6M"}, "compare 需要 2 到 5 檔"),
        ({"kind": "compare", "symbols": ["2330", "2454", "2317", "0050", "2412", "2308"], "range": "6M"}, "最多 5 檔"),
        ({"kind": "pie", "symbols": ["2330"], "range": "6M"}, "kind 必須是"),
        ({"kind": "price", "symbols": ["2330"], "range": "10Y"}, "range 必須是"),
        ({"kind": "price", "symbols": [], "range": "6M"}, "請在 symbols 填"),
        ({"kind": "price", "symbols": "2330", "range": "6M"}, "symbols 必須是"),
        ({"kind": "performance", "symbols": ["0050", "2330"], "range": "6M"}, "最多給一檔"),
        ({"kind": "price", "symbols": ["不存在的公司"], "range": "6M"}, "找不到商品"),
    ]:
        out, res = run(arch, **args)
        assert out.is_error and hint in res, (args, res)
    assert execute(arch, "draw_chart", {"kind": "price", "symbols": ["2330"]}).is_error  # range is required
    assert arch.charts == []
    # the same symbol twice is one line; a turn draws at most three cards
    out, res = run(arch, kind="compare", symbols=["2330", "2330.TW", "台積電", "2454"], range="6M")
    assert [s["symbol"] for s in out.chart["series"]] == ["2330.TW", "2454.TW"]
    run(arch, kind="price", symbols=["2330"], range="1M")
    run(arch, kind="price", symbols=["2330"], range="3M")
    assert len(arch.charts) == charts.MAX_PER_TURN
    out, res = run(arch, kind="price", symbols=["2330"], range="6M")
    assert out.is_error and "已經畫了 3 張圖" in res and len(arch.charts) == charts.MAX_PER_TURN


def test_long_series_are_sampled_not_truncated():
    pts = list(range(1300))
    kept = charts.sample(pts, 480)
    assert len(kept) <= 480 and kept[0] == 0 and kept[-1] == 1299 and kept == sorted(kept)
    assert charts.sample(pts[:10], 480) == pts[:10]
    card = charts._card("compare", "t", "pct", "date",
                        [{"name": str(i), "symbol": str(i), "points": [{"t": str(j), "v": 0.0} for j in range(1300)]}
                         for i in range(5)], ["a", "a"], [], False)
    assert all(len(s["points"]) <= charts.POINT_BUDGET // 5 for s in card["series"]) and card["notes"] == ["a"]
    assert sum(len(s["points"]) for s in card["series"]) <= charts.POINT_BUDGET


# -- with the app's own market data (demo provider) and a signed-in user ----------------------------------------
@pytest.fixture()
def mine(client, engine):
    acc = make_account(client, "我的帳戶")
    buy(client, acc, "2330", 1000, 600)
    db = Session(engine)
    me: User = user_by_email(db, "demo@forliosa.local")
    yield ToolContext(db=db, user=me, md=get_market_data())
    db.close()


def test_revenue_and_eps_bars(mine, monkeypatch):
    months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 11)]
    revenue = {"2330.TW": [RevenueRow(p, 200_000_000 + 1_000_000 * i, None, None, None, None)
                           for i, p in enumerate(reversed(months))]}  # newest first: the chart sorts by period
    monkeypatch.setattr(mine.md, "monthly_revenue",
                        lambda s: Answer(revenue.get(s, []), False, "twse-openapi"))
    out, res = run(mine, kind="revenue", symbols=["2330", "0050", "2317"], range="1Y")
    card = out.chart
    assert card["kind"] == "revenue" and card["unit"] == "amount_k" and card["x"] == "month"
    assert card["title"] == "台積電 月營收" and [s["symbol"] for s in card["series"]] == ["2330.TW"]
    pts = card["series"][0]["points"]
    assert [p["t"] for p in pts] == months and pts[-1]["v"] == 200_000_000.0 and card["currency"] == "TWD"
    assert card["notes"] == ["元大台灣50 沒有月營收資料", "鴻海 沒有月營收資料"] and card["is_demo"] is False
    assert res["units"] == "新台幣千元" and res["series"][0]["points"] == len(months)
    quarters = [f"{y}Q{q}" for y in (2024, 2025) for q in (1, 2, 3, 4)] + ["2026Q1", "2026Q2"]
    eps = {"2330.TW": [10.0 + i for i in range(10)], "2317.TW": [2.5, None, 2.7, 2.8, 2.9, 3.0, 3.1, 3.2, 3.3, 3.4]}

    def financials(_db, _md, symbol, period):
        assert period == "quarterly"
        if symbol not in eps:
            return {"periods": [], "income": {"eps": []}, "sources": [], "notes": ["沒有這檔股票的財務報表資料"]}
        return {"periods": quarters, "income": {"eps": eps[symbol]}, "sources": ["上市公司綜合損益表"], "notes": []}

    monkeypatch.setattr(stock_svc, "financials", financials)
    out, res = run(mine, kind="eps", symbols=["2330", "2317", "2454"], range="1Y")
    card = out.chart
    assert card["kind"] == "eps" and card["x"] == "quarter" and card["currency"] == "TWD" and card["unit"] == "eps"
    assert card["title"] == "台積電、鴻海 每季每股盈餘" and card["sources"] == ["上市公司綜合損益表"]
    tsmc, hon = card["series"]
    assert [p["t"] for p in tsmc["points"]] == quarters[-charts.EPS_QUARTERS:] and tsmc["points"][-1]["v"] == 19.0
    assert len(hon["points"]) == charts.EPS_QUARTERS and hon["points"][0] == {"t": "2024Q3", "v": 2.7}
    assert "聯發科 沒有每股盈餘資料" in card["notes"]
    # an ETF has neither; currencies are never mixed on one axis
    out, res = run(mine, kind="eps", symbols=["0050"], range="1Y")
    assert out.chart is None and res["status"] == "no_data" and res["notes"] == ["元大台灣50 沒有每股盈餘資料"]
    out, res = run(mine, kind="eps", symbols=["2330", "AAPL"], range="1Y")
    assert out.is_error and "幣別不同" in res


def test_performance_chart_is_percentages_only(mine):
    out, res = run(mine, kind="performance", symbols=[], range="6M")
    card = out.chart
    assert card["kind"] == "performance" and card["unit"] == "pct" and card["currency"] is None
    assert card["series"][0]["name"] == "我的報酬率" and card["series"][0]["symbol"] is None
    assert abs(card["series"][0]["points"][0]["v"]) < 0.2 and res["units"].startswith("分數")
    raw = json.dumps(card, ensure_ascii=False) + out.content
    # nothing private: no amounts, cost, quantity — whatever the privacy mode
    for key in ("market_value", "net_invested", "quantity", "cost", "600000"):
        assert key not in raw
    assert all(abs(p["v"]) < 5 for s in card["series"] for p in s["points"])
    assert all(set(p) == {"t", "v"} for s in card["series"] for p in s["points"])
    if len(card["series"]) == 2:
        assert card["title"].startswith("我的報酬率與") and card["series"][1]["symbol"]
    # a named benchmark
    out, res = run(mine, kind="performance", symbols=["0050"], range="1Y")
    assert out.chart["series"][-1]["symbol"] in (None, "0050.TW")
    out, res = run(mine, kind="performance", symbols=["不存在的公司"], range="1Y")
    assert out.is_error


def test_related_stocks_tool(mine):
    out = execute(mine, "get_related_stocks", {"symbol": "2330"})
    assert not out.is_error, out.content
    res = json.loads(out.content)
    assert res["symbol"] == "2330.TW" and res["name"] == "台積電" and isinstance(res["related"], list)
    assert all("sparkline" not in r and r["symbol"] != "2330.TW" for r in res["related"])
    assert "不是今天的即時價" in res["units"]
    assert tool_label("get_related_stocks", {"symbol": "2330"}) == "查看 2330 的相關股票"
    assert tool_label("draw_chart", {"kind": "compare"}) == "畫漲跌幅比較"
    assert "search the web" in TOOLS_BY_NAME["get_related_stocks"].description


def test_chart_event_is_streamed_and_kept_with_the_thread(client, other_client, pool, fake):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    fake.reply(tool_use("toolu_c", "draw_chart", {"kind": "compare", "symbols": ["2330", "2317"], "range": "6M"}),
               stop_reason="tool_use")
    fake.reply(text("台積電這半年漲得比鴻海多。"))
    _status, events = chat(client, "比較台積電和鴻海這半年的走勢")
    names = [n for n, _ in events]
    cards = [d for n, d in events if n == "chart"]
    assert len(cards) == 1 and names.index("chart") < names.index("done")
    card = cards[0]
    assert card["kind"] == "compare" and [s["symbol"] for s in card["series"]] == ["2330.TW", "2317.TW"]
    assert card["id"].startswith("cht_") and all(s["points"][0]["v"] == 0.0 for s in card["series"])
    tools = [d for n, d in events if n == "tool"]
    assert tools[0]["label"] == "畫漲跌幅比較" and tools[-1]["status"] == "done"
    # the model got the summary as its tool result, not the points
    result = fake.requests[-1]["body"]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and '"status":"chart_shown"' in result["content"]
    assert len(result["content"]) < 2500
    # reopened from the history: the card comes back with its points
    thread_id = events[0][1]["id"]
    detail = client.get(f"{API}/ai/threads/{thread_id}").json()
    assert detail["messages"][1]["charts"] == [card]
    assert other_client.get(f"{API}/ai/threads/{thread_id}").status_code == 404
    # a failed draw sends no card
    fake.reply(tool_use("toolu_e", "draw_chart", {"kind": "price", "symbols": ["2330", "2317"], "range": "6M"}),
               stop_reason="tool_use")
    fake.reply(text("一次只能畫一檔。"))
    _status, events = chat(client, "畫台積電和鴻海", thread_id=thread_id)
    assert not [d for n, d in events if n == "chart"]
    assert client.get(f"{API}/ai/threads/{thread_id}").json()["messages"][3]["charts"] == []


def test_system_prompt_says_when_to_draw_and_who_owns_the_numbers():
    for phrase in (
        "## 圖表", "呼叫 draw_chart", "compare 把 2 到 5 檔的漲跌幅放在同一張圖", "一般的問答不要主動畫圖",
        "一個問題最多畫兩張", "圖上的數字全部由工具從資料庫讀取", "不能提供或修改任何一個點",
        "不要逐點列出數字", "status 是 no_data 表示沒有畫圖",
        "要畫圖只能呼叫 draw_chart，不要用文字或符號拼出圖表",
    ):
        assert phrase in CHAT_SYSTEM, phrase
