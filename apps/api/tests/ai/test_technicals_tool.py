"""``get_technicals``: indicators from the archived daily closes; a price the user typed or the model found in a
cited web source is a clearly labelled provisional bar, never an official or real-time quote."""

from __future__ import annotations

import json
import math
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

import forliosa.ai.tools as tools_mod
import forliosa.services.instruments as instr_mod
from forliosa.ai import grounding
from forliosa.ai.prompts import CHAT_SYSTEM
from forliosa.ai.tools import TOOLS_BY_NAME, ToolContext, client_tool_definitions, execute, tool_label
from forliosa.config import get_settings
from forliosa.domain import technicals as ta
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import MarketEvent, PriceDaily
from forliosa.services.coverage import US_NOTE
from forliosa.timeutil import tw_trading_days
from tests.ai.conftest import chat
from tests.ai.fake_anthropic import search_citation, server_tool_use, text, tool_use, web_search_result

FIRST, LAST_DAY, TODAY = date(2026, 6, 1), date(2026, 11, 12), date(2026, 11, 13)  # the archive's range; a Friday
DAYS = tw_trading_days(FIRST, LAST_DAY)
CLOSES = [round(1000 + 0.8 * i + 15 * math.sin(i / 6), 1) for i in range(len(DAYS))]
LAST = CLOSES[-1]


def rows(symbol: str, days: list[date], closes: list[float]) -> list[PriceDaily]:
    return [PriceDaily(symbol=symbol, date=d, open=D(str(c - 1)), high=D(str(c + 5)), low=D(str(c - 5)),
                       close=D(str(c)), volume=20_000_000 + 100_000 * (i % 7), source="twse-openapi")
            for i, (d, c) in enumerate(zip(days, closes, strict=True))]


def freeze(monkeypatch, today: date) -> None:
    for mod in (tools_mod, instr_mod):
        monkeypatch.setattr(mod, "today_taipei", lambda: today)


@pytest.fixture()
def tech(engine, market, monkeypatch):
    """A commercial facade over an archive that starts on 2026-06-01: 2330 has every close up to 11/12, 2454 only
    the last 12, 2317 none. "Today" is Friday 2026-11-13, a trading day without an official close yet."""
    with Session(engine) as db:
        db.add_all(rows("2330.TW", DAYS, CLOSES))
        db.add_all(rows("2454.TW", DAYS[-12:], [500.0 + i for i in range(12)]))
        db.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    freeze(monkeypatch, TODAY)
    db = Session(engine)
    yield ToolContext(db=db, user=None, md=md)  # type: ignore[arg-type]
    db.close()
    set_market_data(market)


def run(ctx, **args):
    out = execute(ctx, "get_technicals", args)
    return out, (json.loads(out.content) if not out.is_error else out.content)


def test_official_block_only(tech):
    assert 110 < len(DAYS) < 120
    out, res = run(tech, symbol="2330")
    assert not out.is_error and len(out.content) < 3500
    assert (res["symbol"], res["name"], res["currency"], res["is_demo"]) == ("2330.TW", "台積電", "TWD", False)
    assert res["sources"] and not any("示範" in s for s in res["sources"])
    assert "with_provisional_price" not in res
    block = res["as_of_close"]
    assert block["official"] is True and block["date"] == "2026-11-12" and block["close"] == LAST
    assert block["prev_close"] == {"date": DAYS[-2].isoformat(), "close": CLOSES[-2]}
    # the same numbers as the pure module over the same bars
    bars = [ta.Bar(t=d, c=c, o=c - 1, h=c + 5, l=c - 5, v=20_000_000 + 100_000 * (i % 7))
            for i, (d, c) in enumerate(zip(DAYS, CLOSES, strict=True))]
    direct = json.loads(json.dumps(ta.analyze(bars), default=str))
    assert block == {"official": True, **direct}
    assert set(block["ma"]) == {"ma5", "ma10", "ma20", "ma60"}  # the archive is too short for 120 / 240
    assert {"rsi14", "kd", "macd", "bollinger", "volume", "high_low", "streak", "events"} <= set(block)
    short = f"日 K 只有 {len(DAYS)} 根（2026-06-01 起），不足以計算：MA120（需 120 根）、MA240（需 240 根）"
    assert short in block["notes"]
    assert res["notes"] == ["資料累積中：自 2026-06-01 起存檔"]  # the same note get_stock_history passes on
    assert "未還原權息" in res["units"] and "不是買賣建議" in res["units"]


def test_user_price_is_a_labelled_provisional_bar(tech):
    _, official = run(tech, symbol="2330")
    price = LAST + 12
    out, res = run(tech, symbol="2330", price=price, price_source="user", price_time="11/13 10:42")
    assert not out.is_error and len(out.content) < 6000
    assert res["as_of_close"] == official["as_of_close"]  # the official block does not move
    block = res["with_provisional_price"]
    assert block["official"] is False and block["date"] == "2026-11-13"
    assert (block["price"], block["price_source"], block["price_label"], block["price_time"]) == (
        price, "user", "你提供的價格", "11/13 10:42")
    assert "不是官方報價，也不是即時報價" in block["caveat"] and "2026-11-13" in block["caveat"]
    assert block["prev_close"] == {"date": "2026-11-12", "close": LAST}
    assert block["change"] == 12.0 and block["change_pct"] == round(price / LAST - 1, 4)
    for missing in ("close", "volume", "events", "gap", "open_gap_pct"):
        assert missing not in block
    assert {"ma", "rsi14", "kd", "macd", "bollinger", "high_low"} <= set(block)
    assert block["ma"]["ma5"]["value"] == round(sum([*CLOSES[-4:], price]) / 5, 2)
    assert all(e["date"] == "2026-11-13" for e in block["events_if_closed_at_price"])
    assert any("開盤、最高、最低價未知" in n and "不提供量比" in n for n in block["notes"])


def test_web_price_keeps_the_source_wording(tech):
    out, res = run(tech, symbol="台積電", price=LAST - 20, price_source="web", price_time="鉅亨網 11:05 報導")
    block = res["with_provisional_price"]
    assert not out.is_error and block["price_source"] == "web" and block["price_label"] == "網路來源報導的價格"
    assert block["price_time"] == "鉅亨網 11:05 報導" and block["official"] is False
    _, res = run(tech, symbol="2330", price=LAST, price_source="web")
    assert res["with_provisional_price"]["price_time"] == "未提供"


def test_prices_outside_the_daily_limit_or_not_positive_are_rejected(tech):
    out, msg = run(tech, symbol="2330", price=round(LAST * 1.2, 1), price_source="user")
    assert out.is_error and "超出台股單日漲跌幅限制" in msg and f"{LAST:g}（2026-11-12）" in msg and "+20.0%" in msg
    assert "請向使用者確認" in msg
    out, msg = run(tech, symbol="2330", price=round(LAST * 0.85, 1), price_source="web")
    assert out.is_error and "-15.0%" in msg
    for bad in (0, -5, -0.01):
        out, msg = run(tech, symbol="2330", price=bad, price_source="user")
        assert out.is_error and "大於 0" in msg
    out, msg = run(tech, symbol="2330", price=LAST)  # a price needs its source
    assert out.is_error and "price_source" in msg
    out = execute(tech, "get_technicals", {"symbol": "2330", "price": LAST, "price_source": "guess"})
    assert out.is_error
    # limit-up and limit-down themselves are prices
    for ok in (round(LAST * 1.10, 1), round(LAST * 0.90, 1)):
        out, res = run(tech, symbol="2330", price=ok, price_source="user")
        assert not out.is_error and res["with_provisional_price"]["price"] == ok


def test_short_history_says_what_is_missing(tech):
    out, res = run(tech, symbol="2454")
    block = res["as_of_close"]
    assert not out.is_error and set(block["ma"]) == {"ma5", "ma10"} and "kd" in block
    for absent in ("rsi14", "macd", "bollinger", "high_low"):
        assert absent not in block
    note = block["notes"][0]
    assert note.startswith(f"日 K 只有 12 根（{DAYS[-12].isoformat()} 起），不足以計算：")
    for name in ("MA20", "MA60", "MA120", "MA240", "RSI14", "MACD", "布林通道", "20 日高低點", "20 日量比"):
        assert name in note
    assert any(n.startswith("資料累積中：自 ") for n in res["notes"])
    # nothing archived at all: no numbers, and the supplied price is not used
    out, res = run(tech, symbol="2317", price=200, price_source="user")
    assert not out.is_error and res["as_of_close"] is None and "with_provisional_price" not in res
    assert res["notes"][0].startswith("資料累積中") and "沒有使用提供的價格" in res["notes"][-1]


def test_us_symbol_without_price_data(tech):
    out, res = run(tech, symbol="AAPL")
    assert not out.is_error and res["as_of_close"] is None and res["notes"] == [US_NOTE]
    assert res["is_demo"] is False and "with_provisional_price" not in res
    out, res = run(tech, symbol="AAPL", price=230.5, price_source="user")
    assert res["as_of_close"] is None and res["notes"][0] == US_NOTE and "with_provisional_price" not in res


def test_no_provisional_bar_once_the_official_close_is_in(tech, monkeypatch):
    freeze(monkeypatch, LAST_DAY)  # the evening of 11/12: that day's close is archived
    out, res = run(tech, symbol="2330", price=LAST + 3, price_source="user")
    assert not out.is_error and "with_provisional_price" not in res
    assert f"2026-11-12 的官方收盤價已經有了（{LAST:g}），沒有使用提供的價格" in res["notes"][-1]
    freeze(monkeypatch, date(2026, 11, 15))  # Sunday: the last session (Friday 11/13) has no official close yet
    _, res = run(tech, symbol="2330", price=LAST + 3, price_source="user")
    assert res["with_provisional_price"]["date"] == "2026-11-13"


def test_stale_archive_widens_the_check_and_says_so(tech, monkeypatch):
    freeze(monkeypatch, date(2026, 11, 17))  # Tuesday: 11/13 and 11/16 were never archived
    out, res = run(tech, symbol="2330", price=round(LAST * 1.25, 1), price_source="user")
    assert not out.is_error and res["with_provisional_price"]["date"] == "2026-11-17"
    assert any("還有 2 個交易日沒有資料" in n for n in res["notes"])
    out, _ = run(tech, symbol="2330", price=round(LAST * 1.4, 1), price_source="user")  # beyond three limit-ups
    assert out.is_error


def test_ex_dividend_days_are_named_and_not_limit_checked(tech, engine):
    with Session(engine) as db:
        db.add_all([MarketEvent(key=f"ex-{d}", symbol="2330.TW", date=d, type="ex_dividend", title="除息", detail="",
                                data={"cash": cash, "stock_ratio": None}, source="twse-openapi")
                    for d, cash in ((date(2026, 9, 17), "6.0"), (TODAY, "150.0"))])
        db.commit()
    out, res = run(tech, symbol="2330")
    assert any(n.startswith("近 60 個交易日內的除權息日：2026-09-17；價格未還原") for n in res["notes"])
    # going ex today: the reference price is far below yesterday's close, so the ±10 % check does not apply
    out, res = run(tech, symbol="2330", price=round(LAST * 0.86, 1), price_source="user")
    assert not out.is_error and "with_provisional_price" in res
    assert any(n.startswith("2026-11-13 是除權息日") and "沒有做漲跌幅檢查" in n for n in res["notes"])


def test_tool_is_registered_with_a_label_and_a_strict_schema():
    spec = TOOLS_BY_NAME["get_technicals"]
    assert tool_label("get_technicals", {"symbol": "2330"}) == "計算 2330 的技術指標"
    schema = spec.definition()["input_schema"]
    assert schema["required"] == ["symbol"] and set(schema["properties"]) == {"symbol", "price", "price_source",
                                                                              "price_time"}
    assert schema["properties"]["price_source"]["enum"] == ["user", "web"]
    assert schema["properties"]["price"]["type"] == "number"
    assert "get_technicals" in [d["name"] for d in client_tool_definitions(get_settings())]
    assert "not an official or real-time quote" in spec.description and "Never pass a guessed" in spec.description


def test_chat_turn_with_a_web_price(client, pool, fake, tech):
    """Market hours: the model searches, passes the price it found with its source time, and answers. The numbers
    from the tool carry no citation and are not marked 「無來源」."""
    price = LAST + 8
    cited = f"台積電盤中股價來到 {price:g} 元"
    answer_tool = (f"最新的官方收盤價是 11/12 的 {LAST:g} 元，今天的收盤價還沒公布。"
                   "MA5 在 11/10 由下往上穿越 MA20（黃金交叉成立），RSI 向上通過 50。"
                   "KD 在 11/11 於 80 以上的高檔區出現死亡交叉，MACD 柱狀體 11/12 由負轉正。")
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 股價 盤中"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨網",
                                                 "encrypted_content": "E"}]),
               tool_use("toolu_t", "get_technicals", {"symbol": "2330", "price": price, "price_source": "web",
                                                      "price_time": "鉅亨網 11/13 10:42"}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})
    fake.reply(text(answer_tool),
               text(f"鉅亨網 11/13 10:42 的報導寫到股價約 {price:g} 元。",
                    [search_citation("https://news.cnyes.com/a", "鉅亨網", cited)]),
               text("這個價格可能已經過時，不是即時報價。"))
    _status, events = chat(client, "台積電現在技術面怎麼樣？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})
    names = [n for n, _ in events]
    assert "error" not in names and "grounding" not in names  # nothing from the tool is flagged
    steps = [(d["name"], d["status"], d["label"]) for n, d in events if n == "tool"]
    assert ("get_technicals", "running", "計算 2330 的技術指標") in steps
    assert ("get_technicals", "done", "計算 2330 的技術指標") in steps
    assert [d["url"] for n, d in events if n == "citation"] == ["https://news.cnyes.com/a"]
    # the second request carries the tool result: both blocks, the provisional one labelled as a web price
    result = next(b for m in fake.requests[1]["body"]["messages"] if m["role"] == "user"
                  and isinstance(m["content"], list) for b in m["content"] if b.get("type") == "tool_result")
    payload = json.loads(result["content"])
    assert payload["as_of_close"]["official"] is True and payload["as_of_close"]["date"] == "2026-11-12"
    assert payload["with_provisional_price"]["price_source"] == "web"
    assert payload["with_provisional_price"]["price_time"] == "鉅亨網 11/13 10:42"
    tools = {t["name"] for t in fake.requests[0]["body"]["tools"]}
    assert {"get_technicals", "web_search"} <= tools
    assert "技術分析與盤中價格" in fake.requests[0]["body"]["system"][0]["text"]


def test_grounding_does_not_flag_technical_sentences():
    data = ("最新的官方收盤價是 11/12 的 1,085 元，今天的收盤價還沒公布。11/12 公布的官方收盤價是 1,085 元。"
            "MA5 在 11/10 由下往上穿越 MA20。黃金交叉在 11/10 成立。RSI 向上通過 50。MACD 柱狀體 11/12 由負轉正。"
            "KD 在 11/11 於高檔區死亡交叉。你提供的價格 1,090 元（11/13 10:42）不是官方報價。11/13 創 60 日新高。")
    assert grounding.check(data, []) == []
    # news claims are still flagged, with or without an indicator in the sentence
    news = "台積電 11/12 公布財報後，收盤價大漲。董事會 11/12 通過配息，MACD 同日轉正。NVIDIA 宣布投資。"
    assert [i["text"] for i in grounding.check(news, [])] == [
        "台積電 11/12 公布財報後，收盤價大漲。", "董事會 11/12 通過配息，MACD 同日轉正。", "NVIDIA 宣布投資。"]
    assert grounding.check("RSI 公布新版。", []) == []  # an indicator is not a named actor
    assert [i["signals"] for i in grounding.check("KDDI 公布新版。", [])] == [["verb:公布", "actor:KDDI"]]


def test_system_prompt_has_the_technical_and_intraday_price_rules():
    for phrase in (
        "## 技術分析與盤中價格", "呼叫 get_technicals", "寫出資料日期", "不說該買或該賣", "不給目標價",
        "未還原權息", "除權息日會留下缺口", "因為存檔天數不足而算不出來的項目", "不要自己補算或估計",
        "只有收盤後公布的官方收盤價，沒有即時報價", "先寫出最新的官方收盤價與日期",
        "price_source 填 user", "回答時稱為「你提供的價格」", "不是查證過的資料",
        "price_source 填 web", "price_time 填來源寫的時間", "一定要引用那個來源", "這個價格可能已經過時",
        "不可稱為「即時」或官方報價", "不要用 web_fetch 讀證交所網站或 MIS",
        "找不到可靠的價格：直接說查不到，用最新收盤價分析，並請使用者輸入現在看到的價格",
        "絕對不要猜測、估計或憑記憶寫現在的價格", "兩部分要分開說明",
        "或使用者在對話中自己提供的數字（要標明是使用者提供的）",
    ):
        assert phrase in CHAT_SYSTEM, phrase
    # the standing rules are still there
    for phrase in ("只做分析與整理，不保證報酬，不下買進或賣出的指令，也不給目標價", "不要憑記憶或推測寫數字",
                   "網路搜尋不是行情來源：股價、成交量、財報數字以工具資料為準", "只寫有根據的事實"):
        assert phrase in CHAT_SYSTEM, phrase
    assert CHAT_SYSTEM.index("## 資料從哪裡來") < CHAT_SYSTEM.index("## 技術分析與盤中價格") \
        < CHAT_SYSTEM.index("## 記帳一律先起草")
