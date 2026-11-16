"""「X 今天為什麼漲／跌」 (產品負責人 2026-11-16: 「台達電今天為啥跌這麼多?」 got market-wide reasons only, and
never said the stock fell about 7 % while the TAIEX fell about 3 %). The prompt's 「為什麼漲跌」 section, the market
beside the stock in get_stock_overview, and get_news putting the last 48 hours first with their time."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai import tools
from forliosa.ai.prompts import CHAT_SYSTEM, EDITOR_SYSTEM, WHY_SYSTEM
from forliosa.ai.tools import ToolContext, execute, news_for_ai
from forliosa.marketdata.base import QuoteData
from forliosa.marketdata.service import get_market_data
from forliosa.models import IndexDaily, User
from forliosa.timeutil import TAIPEI

MON = datetime(2026, 11, 16, 10, 30, tzinfo=TAIPEI)  # a trading day, intraday


# -- prompt ---------------------------------------------------------------------------------------------------
def test_the_why_section_sits_between_the_tool_rules_and_the_intraday_rules():
    assert CHAT_SYSTEM.index("## 自己決定用哪些工具") < CHAT_SYSTEM.index("## 為什麼漲跌") \
        < CHAT_SYSTEM.index("## 技術分析與盤中價格") < CHAT_SYSTEM.index("## 圖表")
    assert CHAT_SYSTEM.count("## 為什麼漲跌") == 1
    # the tool rules send the question there instead of only ordering the tools
    assert "問某一檔為什麼漲跌、最近怎麼了：照下面「為什麼漲跌」做" in CHAT_SYSTEM
    assert "問某一檔為什麼漲跌、最近怎麼了、有什麼消息：先用 get_news" not in CHAT_SYSTEM


def test_the_why_section_compares_with_the_market_and_puts_the_company_first():
    section = CHAT_SYSTEM[CHAT_SYSTEM.index("## 為什麼漲跌"):CHAT_SYSTEM.index("## 技術分析與盤中價格")]
    for phrase in (
        "為什麼漲、為什麼跌", "大盤只當背景", "這三樣都查完才回答",
        # what to look up: the move, the TAIEX at the same time, the company's own news three ways
        "get_stock_overview", "why_signals", "market_context", "vs_taiex_pct_points", "intraday_note",
        "加權指數同一時間漲跌多少", "寫出來源的時間", "每一種各搜一次", "找價格與大盤的搜尋不算",
        "法說會", "目標價 調降", "english_name 加上 Taiwan、股票代號與 shares 或 stock", "Delta Taiwan 2308 shares",
        "大股東申報轉讓", "但它有 dates_differ 時（加權指數和這一檔的收盤不是同一天）也用 web_search 找",
        # how to answer
        "寫出這一檔和加權指數各漲跌多少，再說原因", "差 2 個百分點以上，就是這一檔自己的走勢",
        "不可以只寫大盤的原因，開頭也不寫大盤、美股或類股的原因",
        "也不寫「主要是大盤」「跟著大盤和權值股一起跌」這類說法",
        "兩者差不多時，才說主要是跟著大盤", "逆勢漲", "不要改說主要是大盤",
        "目前找不到大華今天自己的消息", "並寫出日期，當作背景", "不要把大盤的原因寫成這一檔漲跌的原因",
        "問的不是台積電，就不寫台積電 ADR", "搜尋結果把它們寫在同一篇報導裡也一樣", "條列最多四點",
        "公司自己的原因在前、背景在後", "放在最後一點",
    ):
        assert phrase in section, phrase
    # rating and target changes: which institution and what changed; a published target price may be quoted with a
    # citation (產品負責人 2026-11-16), never the AI's own target or an upside it computed
    assert "寫出是哪一家機構、調了什麼；來源寫了目標價就照寫" in section and "並附引用" in section
    assert "也不自己算上漲空間" in section
    assert "也不給你自己的目標價（轉述具名機構已發表的目標價可以，寫出機構並附引用）" in CHAT_SYSTEM


def test_the_intraday_rules_no_longer_lead_a_why_answer_with_the_close_or_with_an_adr():
    assert "先寫出最新的官方收盤價與日期" not in CHAT_SYSTEM
    assert "回答裡要寫出最新的官方收盤價與日期" in CHAT_SYSTEM
    assert "問價格時寫在最前面，問為什麼漲跌時放在最後一點" in CHAT_SYSTEM
    # an ADR only for a stock that has one (台積電); it is related information, not the stock's reason
    assert "大型權值股可以看前一晚 ADR 的表現" not in CHAT_SYSTEM
    assert "這一檔自己有在美國掛牌的 ADR 時（例如台積電），可以看前一晚 ADR 的表現" in CHAT_SYSTEM
    assert "不是這一檔的報價，也不是這一檔漲跌的原因" in CHAT_SYSTEM
    # Taiwan companies' foreign news: once more with the English name
    assert "台股公司在國外的消息（外電、海外客戶、外資報告）再用公司的英文名稱搜一次" in CHAT_SYSTEM


def test_the_editor_keeps_the_comparison_first():
    assert "開頭寫了這一檔和大盤的漲跌比較時保留在開頭，公司自己的原因放在大盤背景前面" in EDITOR_SYSTEM
    assert "不新增、不刪除任何事實" in EDITOR_SYSTEM


def test_the_editor_keeps_times_and_quote_figures_and_adds_no_month_heading_or_english():
    # 2026-11-16 review: with thinking off the editor merged repeated sentences and lost 09:59 / 11:31 (7 of 34
    # edits), dropped a quote line's 4.40 and volume, wrote 30日 as 11/30, added ### headings and wrote 「also」
    # (the headings it still adds are undone as the edit streams: test_chat_editor_stream)
    for phrase in ("保留每一個事實、數字、日期、時間（09:59）", "兩句裡的數字與時間都併進留下的那一句",
                   "表格或報價列殘留的數字（漲跌、成交張數）寫進句子裡，不要刪掉",
                   "只有日、沒有月份的日期（30 日）照原樣寫，不要自己補上月份", "原文是中文的字詞不要換成英文",
                   "不要把句子改成標題，也不新增原文沒有的標題", "原文有 ### 小標題才保留"):
        assert phrase in EDITOR_SYSTEM, phrase


def test_a_news_question_gets_no_price_or_market_and_no_source_vetting():
    """產品負責人 2026-11-16: 「禾榮科 最近有甚麼消息嗎? 機構給出的評級與目標價為何?」 ended with the 11/13 close, the
    TAIEX and 「今天（11/16）的收盤價尚未公布」, and said which source it had left out and why."""
    for phrase in (
        # a news question is answered with the news only
        "問某一檔有什麼消息、最近有什麼新聞：先用 get_news",
        "只寫消息本身，不寫股價、漲跌、和大盤的比較，也不說收盤價還沒公布（使用者同時問了價格或漲跌才寫）",
        "問評等、目標價，或券商、外資怎麼看：照下面「機構評等與目標價」做",
        "沒被問到的面向（股價與大盤漲跌、收盤價什麼時候公布、",
        # sources: a disagreement between credible ones is shown, a dropped one is never mentioned
        "可信的來源說法不一致時，兩種說法都寫出來並各自引用", "不可信、出處或日期不明的來源直接不用，回答裡也不提到它",
        "也不交代資料的篩選：不寫找到幾筆、「只找到一筆可引用的資料」、哪個來源不採用或為什麼不用",
        # dates
        "月和日不補 0（10/2，不是 10/02）", "不是今年的才寫年份（2025/10/2）", "「115 年第 3 季」寫「第 3 季」",
        "「今天（11/16）」",
    ):
        assert phrase in CHAT_SYSTEM, phrase
    assert "來源說法不一致時要說明" not in CHAT_SYSTEM and "目前查不到可靠來源" not in CHAT_SYSTEM


def test_the_editor_deletes_source_vetting_and_rewrites_table_labels():
    for phrase in ("不新增、不刪除任何事實（下面寫明要整句刪掉的除外）",
                   "交代資料篩選的句子整句刪掉，連同裡面的數字", "「目前只找到一筆可引用的資料」",
                   "「另有一則…說法，來源是…，因此不採用」",
                   "網站表格的欄位名稱（「多空評等」「預估 EPS」）不要照抄", "「多空評等為看多」寫成「評等看多」"):
        assert phrase in EDITOR_SYSTEM, phrase


def test_the_stock_page_one_liner_compares_with_the_market_too():
    for phrase in ("45 個字以內", "也查同一天加權指數漲跌多少", "差 2 個百分點以上", "這家公司自己的事",
                   "不可以只寫大盤的原因", "跟著大盤漲跌並寫出大盤的漲跌幅", "不寫別家公司的股價或 ADR",
                   "只輸出 NONE"):
        assert phrase in WHY_SYSTEM, phrase


# -- get_stock_overview -------------------------------------------------------------------------------------------
@pytest.fixture()
def ctx(client, engine):
    db = Session(engine)
    me = db.scalar(select(User).where(User.email == "demo@forliosa.local"))
    yield ToolContext(db=db, user=me, md=get_market_data())
    db.close()


def index(db: Session, name: str, day: date, close: str, change: str, pct: str, market: str = "TWSE") -> None:
    db.add(IndexDaily(name=name, date=day, market=market, close=D(close), change=D(change), change_pct=D(pct),
                      source="twse-openapi" if market == "TWSE" else "tpex-openapi"))


def quote(symbol: str, day: date, price: str, prev: str) -> QuoteData:
    return QuoteData(symbol=symbol, price=D(price), prev_close=D(prev), open=D(prev), high=D(prev), low=D(price),
                     volume=None, as_of=datetime.combine(day, datetime.min.time(), TAIPEI).replace(hour=13, minute=30),
                     trade_date=day, is_realtime=False, is_demo=True, source="demo")


def overview(ctx, monkeypatch, q: QuoteData, now: datetime, symbol: str = "2330") -> dict:
    import json

    monkeypatch.setattr(ctx.md, "quote", lambda s, *a, **k: q if s == q.symbol else None)
    monkeypatch.setattr(tools, "now_taipei", lambda: now)
    out = execute(ctx, "get_stock_overview", {"symbol": symbol})
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_overview_puts_the_taiex_and_the_sector_index_beside_the_stock(ctx, monkeypatch):
    fri = date(2026, 11, 13)
    index(ctx.db, "發行量加權股價指數", fri - timedelta(days=1), "43091.87", "-100", "-0.0023")
    index(ctx.db, "發行量加權股價指數", fri, "43675.12", "-583.25", "0.0135")  # TWSE publishes the % unsigned
    index(ctx.db, "半導體類指數", fri, "1480.33", "17.92", "0.0123")
    index(ctx.db, "半導體類報酬指數", fri, "2839.48", "34.38", "0.0123")
    ctx.db.commit()
    sat = datetime(2026, 11, 14, 11, 0, tzinfo=TAIPEI)
    res = overview(ctx, monkeypatch, quote("2330.TW", fri, "1000", "1050"), sat)

    assert res["english_name"] == "TSMC"  # the foreign-news search
    m = res["market_context"]
    assert m["taiex"] == {"name": "發行量加權股價指數", "date": "2026-11-13", "close": 43675.12, "change_pct": -0.0135}
    assert m["industry_index"]["name"] == "半導體類指數" and m["industry_index"]["change_pct"] == 0.0123
    # 2330 fell 4.76 %, the TAIEX 1.35 %: 3.41 percentage points more
    assert m["vs_taiex_pct_points"] == pytest.approx(-3.41, abs=0.01)
    assert "百分點" in m["note"] and "不是即時" in m["note"]
    # the rules of the stock page's 「為什麼」 for that session
    assert res["why_signals"] == ["11/13 下跌 4.8%"]
    assert "intraday_note" not in res  # a Saturday: Friday's close is the latest session


def test_overview_compares_only_closes_of_the_same_day(ctx, monkeypatch):
    index(ctx.db, "發行量加權股價指數", date(2026, 11, 16), "42000", "-1675.12", "0.0384")
    ctx.db.commit()
    res = overview(ctx, monkeypatch, quote("2330.TW", date(2026, 11, 13), "1050", "1050"), MON)
    assert res["market_context"]["taiex"]["date"] == "2026-11-16"
    assert "vs_taiex_pct_points" not in res["market_context"]
    assert res["market_context"]["dates_differ"].startswith(
        "加權指數是 11/16 的收盤，這一檔是 11/13 的收盤，不是同一天")
    assert res["why_signals"] == []  # flat: nothing to flag


def test_overview_says_so_when_the_evening_close_is_in_but_the_index_is_not(ctx, monkeypatch):
    # every trading evening the stock's close is archived from 13:35, MI_INDEX's TAIEX only after the 21:40 run
    fri, mon = date(2026, 11, 13), date(2026, 11, 16)
    index(ctx.db, "發行量加權股價指數", fri, "43675.12", "583.25", "0.0135")
    ctx.db.commit()
    res = overview(ctx, monkeypatch, quote("2330.TW", mon, "980", "1050"), MON.replace(hour=19))
    m = res["market_context"]
    assert m["taiex"]["date"] == "2026-11-13" and "vs_taiex_pct_points" not in m
    assert m["dates_differ"] == ("加權指數是 11/13 的收盤，這一檔是 11/16 的收盤，不是同一天，不能拿來比較；"
                                 "11/16 加權指數漲跌多少要用 web_search 找並寫出時間")
    assert "intraday_note" not in res  # today's close is in: the note about the index is all the model gets
    # the same day: nothing to say
    index(ctx.db, "發行量加權股價指數", mon, "41885.57", "-1789.55", "0.0410")
    ctx.db.commit()
    assert "dates_differ" not in overview(ctx, monkeypatch, quote("2330.TW", mon, "980", "1050"),
                                          MON.replace(hour=22))["market_context"]


def test_overview_without_index_rows_or_for_a_us_stock_has_no_market_context(ctx, monkeypatch):
    res = overview(ctx, monkeypatch, quote("2330.TW", date(2026, 11, 13), "1050", "1050"), MON)
    assert "market_context" not in res
    index(ctx.db, "發行量加權股價指數", date(2026, 11, 13), "43675.12", "583.25", "0.0135")
    ctx.db.commit()
    us = overview(ctx, monkeypatch, quote("AAPL", date(2026, 11, 13), "230", "231"), MON, symbol="AAPL")
    assert "market_context" not in us and "intraday_note" not in us


def test_overview_says_when_the_quote_is_the_previous_session(ctx, monkeypatch):
    res = overview(ctx, monkeypatch, quote("2330.TW", date(2026, 11, 13), "1050", "1050"), MON)
    note = res["intraday_note"]
    assert note.startswith("盤中：") and "11/13 的官方收盤資料，不是今天的" in note and "web_search" in note


@pytest.mark.parametrize(("now", "expected"), [
    (MON, "盤中"),
    (MON.replace(hour=14), "今天已收盤，但今天的官方收盤價還沒公布"),
    (MON.replace(hour=8, minute=40), None),  # before the open: Friday's close is the latest there is
    (datetime(2026, 11, 14, 11, 0, tzinfo=TAIPEI), None),  # Saturday
    (datetime(2026, 11, 13, 11, 0, tzinfo=TAIPEI), None),  # the quote is today's (a demo or a published close)
    (MON.astimezone(UTC), "盤中"),  # the same moment in UTC (02:30): read in Taipei time
])
def test_intraday_note_only_while_todays_close_is_not_out(now, expected):
    info = SimpleNamespace(market="TWSE")
    q = SimpleNamespace(trade_date=date(2026, 11, 13))
    note = tools._intraday_note(info, q, now)
    if expected is None:
        assert note is None
    else:
        assert note.startswith(f"{expected}：")
    assert tools._intraday_note(SimpleNamespace(market="US"), q, MON) is None
    assert tools._intraday_note(info, None, MON) is None


def test_intraday_note_after_midnight_and_with_the_expected_time():
    """Memo 2026-11-16: the note used to stop at midnight (and before 09:00) although Monday's close was still not in;
    with ``forliosa.closes``' window for the market, the model can say when it is expected."""
    info = SimpleNamespace(market="TWSE")
    friday = SimpleNamespace(trade_date=date(2026, 11, 13))
    tue_0030 = datetime(2026, 11, 17, 0, 30, tzinfo=TAIPEI)
    note = tools._intraday_note(info, friday, tue_0030)
    assert note.startswith("11/16 的官方收盤價還沒公布：") and "不是11/16的" in note and "11/16這一檔" in note
    close = {"market": "TWSE", "stored": False, "expected_from": "2026-11-17T05:20:00+08:00",
             "expected_to": "2026-11-17T05:45:00+08:00"}
    # the app's own words (12-hour, the part of the day), as the screen writes them (forliosa.closes.window_text)
    assert "這個市場的官方收盤價預計清晨 5:20–5:45 更新（畫面上也這樣寫）。" in tools._intraday_note(
        info, friday, tue_0030, close)
    close_1405 = {**close, "expected_from": "2026-11-16T14:00:00+08:00", "expected_to": "2026-11-16T14:30:00+08:00"}
    assert "預計下午 2:00–2:30 更新" in tools._intraday_note(info, friday, MON.replace(hour=13, minute=50), close_1405)
    note = tools._intraday_note(info, friday, MON.replace(hour=14, minute=5), close_1405)
    # inside the window: only its end
    assert note.startswith("今天已收盤，但今天的官方收盤價還沒公布：") and "預計下午 2:30 前更新" in note
    # Monday's close in (the same-day file or the evening interim close): no note
    assert tools._intraday_note(info, SimpleNamespace(trade_date=date(2026, 11, 16)), tue_0030) is None
    assert tools._intraday_note(info, friday, datetime(2026, 11, 16, 13, 29, tzinfo=TAIPEI)) is not None  # 盤中


def test_intraday_note_asks_for_the_move_only_when_the_user_asks_about_it():
    """2026-11-16, 禾榮科: the note asked for today's move and the TAIEX unconditionally, so a news-and-ratings
    answer ended with the close, the TAIEX and 「今天的收盤價尚未公布」."""
    info = SimpleNamespace(market="TWSE")
    friday = SimpleNamespace(trade_date=date(2026, 11, 13))
    after_close = tools._intraday_note(info, friday, MON.replace(hour=18))
    assert after_close.endswith("使用者問今天的價格或漲跌時，今天這一檔與加權指數漲跌多少要用 web_search 找可引用的來源"
                                "並寫出時間；只問消息、評等或財報時不用寫股價，也不用說收盤價還沒公布")
    after_midnight = tools._intraday_note(info, friday, datetime(2026, 11, 17, 0, 30, tzinfo=TAIPEI))
    assert "使用者問11/16的價格或漲跌時" in after_midnight and "只問消息、評等或財報時不用寫股價" in after_midnight


def test_the_page_context_says_where_each_markets_close_is():
    from forliosa.ai.prompts import closes_line, page_context

    now = datetime(2026, 11, 16, 21, 0, tzinfo=TAIPEI)
    closes = [
        {"market": "TWSE", "session": "2026-11-16", "stored": True, "latest": "2026-11-16", "interim": False,
         "expected_from": None, "expected_to": None},
        {"market": "TPEX", "session": "2026-11-16", "stored": False, "latest": "2026-11-13", "interim": False,
         "expected_from": "2026-11-16T20:30:00+08:00", "expected_to": "2026-11-16T23:45:00+08:00"},
    ]
    line = closes_line(closes, now)
    assert line == "上市 11/16 的收盤價已進來；上櫃 11/16 的收盤價還沒公布，預計今晚 11:45 前更新"
    ctx = page_context(now, "/", None, None, False, closes=closes)
    assert f"- 台股：已收盤\n- 台股收盤價：{line}\n- 美股：" in ctx
    # interim (no ETFs in it): the official file's window is still given (forliosa.closes.tw_closes)
    interim = [{**closes[1], "stored": True, "interim": True, "expected_from": "2026-11-16T23:15:00+08:00",
                "expected_to": "2026-11-16T23:45:00+08:00"}]
    assert closes_line(interim, now) == (
        "上櫃 11/16 的收盤價已進來（晚上先放的暫時資料：只有收盤價、沒有 ETF；官方檔案預計今晚 11:15–11:45 更新）")
    gone = [{**interim[0], "expected_from": None, "expected_to": None}]
    assert closes_line(gone, now).endswith("官方檔案還沒進來）")
    late = [{**closes[0], "stored": False, "expected_from": "2026-11-17T05:20:00+08:00",
             "expected_to": "2026-11-17T05:45:00+08:00"}]
    assert closes_line(late, now) == "上市 11/16 的收盤價還沒公布，預計明天清晨 5:20–5:45 更新"
    assert "台股收盤價" not in page_context(now, "/", None, None, False)  # no closes read: no line


def test_industry_names_map_to_the_twse_sector_index():
    assert tools._industry_index_name("電子零組件業") == "電子零組件類指數"
    assert tools._industry_index_name("水泥工業") == "水泥類指數"
    assert tools._industry_index_name("電腦及週邊設備業") == "電腦及週邊設備類指數"
    assert tools._industry_index_name("紡織纖維") == "紡織纖維類指數"
    assert tools._industry_index_name(None) is None and tools._industry_index_name("") is None


# -- get_news -------------------------------------------------------------------------------------------------------
NOW = datetime(2026, 11, 16, 10, 30, tzinfo=TAIPEI)


def item(category: str, at: str, title: str, date_only: bool = False) -> dict:
    return {"published_at": at, "title": title, "category": category, "date_only": date_only,
            "outlet": "鉅亨網" if category == "media" else None, "url": f"https://example.com/{title}",
            "source": "新聞" if category == "media" else "公告", "sources": []}


def test_news_puts_the_last_48_hours_first_and_caps_old_announcements():
    # the stock page's order: 公告 newest first (90 days), then media newest first
    notices = [item("material_info", "2026-11-15T17:30:00+08:00", "昨天的公告"),
               item("exchange_news", "2026-11-10T16:00:00+08:00", "上週的公告"),
               *[item("material_info", f"2026-10-{d:02d}T15:00:00+08:00", f"十月公告{d}") for d in range(25, 15, -1)]]
    media = [item("media", "2026-11-16T09:12:00+08:00", "今天早上的報導"),
             item("media", "2026-11-14T20:00:00+08:00", "週六晚上的報導"),
             item("media", "2026-11-12T08:00:00+08:00", "上週四的報導")]
    out = [n["title"] for n in news_for_ai([*notices, *media], NOW)]
    assert out[:3] == ["今天早上的報導", "昨天的公告", "週六晚上的報導"]  # 48 hours, newest first, of any kind
    assert out[3] == "上週的公告"  # 公告 of the last 14 days, all of them
    assert out[4:8] == ["十月公告25", "十月公告24", "十月公告23", "十月公告22"]  # older ones: at most 4
    assert out[8:] == ["上週四的報導"]  # older media last
    assert len(news_for_ai([item("media", f"2026-11-16T0{h}:00:00+08:00", f"m{h}") for h in range(10)] * 2, NOW)) \
        == tools.NEWS_TOOL_MAX


def test_news_items_say_today_or_yesterday_and_the_time(ctx, monkeypatch):
    from forliosa.services import stock as stock_svc

    news = [item("media", "2026-11-16T09:12:00+08:00", "今天早上的報導"),
            item("material_info", "2026-11-15T00:00:00+08:00", "沒有時間的公告"),
            item("media", "2026-11-13T08:00:00+08:00", "只有日期的報導", date_only=True),
            item("exchange_news", "2026-11-12T14:05:00+08:00", "交易所新聞")]
    monkeypatch.setattr(stock_svc, "news", lambda db, md, symbol: news)
    monkeypatch.setattr(tools, "now_utc", lambda: NOW)
    out = execute(ctx, "get_news", {"symbol": "2330"})
    texts = [b["content"][0]["text"] for b in out.content]
    assert texts == ["鉅亨網，今天 11/16 09:12：今天早上的報導", "公開資訊觀測站，昨天 11/15：沒有時間的公告",
                     "臺灣證券交易所，11/12 14:05：交易所新聞", "鉅亨網，11/13：只有日期的報導"]
