"""Taiwan stocks' stored headlines checked again when read (產品負責人 2026-11-17, 「好」): wrong matches stored before
the tightened rule went live are no longer shown (stock page /news, ``get_news``, ``search_news``, ``recent_count``,
``by_topic``) but stay in ``news_articles``.

Every headline here is real: stored by the GDELT bulk files of 2026-11-12 to 17 under these stocks by the old rule
(any name or code anywhere in the title), title as stored (cleaned), link as published; judged one by one for
``CONTRACT_NOTES.md`` 「2026-11-17 台股新聞比對收緊」. Only the times are set relative to the test's clock. A title
written by hand is marked ``synthetic``."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import CompanyProfile, MarketEvent, NewsArticle, NewsTag, NewsTagState, User
from forliosa.news import service, tags
from forliosa.news.normalize import Headline, url_key

# The stocks of these headlines (shioaji-data's cards of 2026-10-14: symbol, name, English short name); 2412 中華電
# and 2330 台積電 are in the built-in catalog already.
STOCKS = [
    ("2027.TW", "大成鋼", "TC"), ("1321.TW", "大洋", "OPC"), ("8261.TW", "富鼎", "APEC"),
    ("2646.TW", "星宇航空", "STARLUX AIR"), ("1905.TW", "華紙", "CHP"), ("2204.TW", "中華", "CMC"),
    ("2609.TW", "陽明", "YMTC"), ("2603.TW", "長榮", "EMC"), ("1216.TW", "統一", "UNI-PRESIDENT"),
    ("4743.TWO", "合一", "ONENESS BIOTECH"),
]


class Catalog(DemoProvider):
    """The built-in catalog plus :data:`STOCKS`."""

    def instruments(self) -> list[InstrumentInfo]:
        extra = [InstrumentInfo(s, s.split(".")[0], n, "TPEX" if s.endswith(".TWO") else "TWSE", "stock", "TWD",
                                aliases=(e,)) for s, n, e in STOCKS]
        return [*super().instruments(), *extra]


@pytest.fixture()
def catalog_md(market):
    md = MarketData([Catalog()], policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)


# (symbol, stored title, link, outlet, source); WRONG: matched only by the old rule, RIGHT: by the rule of today too
WRONG = [
    # a year taken for a code (2027 大成鋼); a finance site does not make it one; an English headline neither
    ("2027.TW", "2027台海不平靜？美軍前司令「希望自己預測錯誤」，籲華府加速交付對台軍售 | 李靖棠",
     "https://www.storm.mg/article/11181868", "風傳媒", "gdelt"),
    ("2027.TW", "美選後關稅不確定性降 紡纖業看好2027回溫", "https://news.ustv.com.tw/newsdetail/20261116A043",
     "非凡新聞", "gdelt"),
    ("2027.TW", "Budgets show effort to beat 2027 warning",
     "https://www.taipeitimes.com/News/taiwan/archives/2026/11/17/2003867877", "Taipei Times", "gdelt"),
    # a name inside a longer word (大洋洲, 九合一) or another company's name (中華電信 is 中華電's)
    ("1321.TW", "星宇航空進軍大洋洲！明年3月飛雪梨、奧克蘭", "https://ec.ltn.com.tw/article/breakingnews/5643289",
     "自由財經", "gdelt"),
    ("4743.TWO", "11/28九合一大選放假嗎？勞動部解答了 出勤「雙倍薪資」條件曝光", "https://www.setn.com/news/1939819",
     "三立新聞網", "gdelt"),
    ("2204.TW", "中華電信帳單一夕翻4倍！NCC證實74萬戶收錯簡訊 原因曝光",
     "https://newtalk.tw/news/view/2026-11-16/1071363", "新頭殼", "gdelt"),
    ("2609.TW", "陽明山山藥季11/21登場！攜手士林商圈推限定美食 山藥拿鐵、銅鑼燒搶攻味蕾 | 徐炳文 | 地方新聞",
     "https://www.storm.mg/article/11182056", "風傳媒", "gdelt"),
    # an English alias in a Chinese headline (APEC = 富鼎), also when the AI fallback stored it
    ("8261.TW", "APEC成員磋商聲明文件 為亞太自貿區打造務實框架", "https://www.cna.com.tw/news/acn/202611160287.aspx",
     "中央社", "gdelt"),
    ("8261.TW", "APEC深圳峰會將登場 維安升級民眾搶打卡", "https://www.cna.com.tw/news/acn/202611160243.aspx",
     "中央社", "ai_search"),
    # an everyday word
    ("1216.TW", "藍營大老拋「統一十年進程」民進黨：國民黨中央應說清楚是否認同",
     "https://udn.com/news/story/6656/9881950", "聯合新聞網", "gdelt"),
]
RIGHT = [
    ("2027.TW", "八大官股》台股大漲583點！官股買賣超出爐，狂買大成鋼2.3萬張、反手砍敬鵬逾5400張 | 下班經濟學",
     "https://www.storm.mg/article/11181371", "風傳媒", "gdelt"),
    ("2646.TW", "星宇航空進軍大洋洲！明年3月飛雪梨、奧克蘭", "https://ec.ltn.com.tw/article/breakingnews/5643289",
     "自由財經", "gdelt"),
    ("2412.TW", "中華電信帳單一夕翻4倍！NCC證實74萬戶收錯簡訊 原因曝光",
     "https://newtalk.tw/news/view/2026-11-16/1071363", "新頭殼", "gdelt"),
    ("2609.TW", "陽明Q3EPS5.32元較市場預估值高21% 有法人估Q4EPS4.15元", "https://finance.ettoday.net/news/3273311",
     "ETtoday財經雲", "gdelt"),
    ("1905.TW", "華紙法說會／大陸紙漿產能兩年暴增1,600萬噸 拚特殊紙、綠能雙轉型 | 個股情報",
     "https://udn.com/news/story/7252/9881833", "經濟日報", "gdelt"),
    # the AI fallback's row is checked like any other: this one names the stock on a finance page (中央社 產經)
    ("1905.TW", "華紙售觀音廠予元太科技 處分利益估13.3億元", "https://www.cna.com.tw/news/afe/202611130236.aspx",
     "中央社", "ai_search"),
    # the official name from the company profile counts (統一企業)
    ("1216.TW", "台南市長黃偉哲參訪統一企業智慧物流園區 探討未來發展需求", "https://n.yam.com/Article/20261113134393",
     "yam蕃薯藤", "gdelt"),
]


def _store(db: Session, now: datetime, rows=None, tag: dict[str, set[tuple[str, str]]] | None = None) -> None:
    """The rows as the old rule stored them (a day before ``now``, the newest first) and, for the links in ``tag``,
    their tags (tagging done)."""
    db.add(CompanyProfile(symbol="1216.TW", date=date(2026, 11, 11), source="twse-openapi",
                          values={"name": "統一企業股份有限公司", "short_name": "統一",
                                  "english_short_name": "UNI-PRESIDENT"}))
    db.commit()
    for i, (symbol, title, url, outlet, source) in enumerate(rows or [*WRONG, *RIGHT]):
        h = Headline(title=title, url=url, outlet=outlet, domain="", published_at=now - timedelta(hours=1 + i),
                     source=source)
        service.store(db, symbol, [h], now - timedelta(days=1))
    for url, values in (tag or {}).items():
        for kind, value in values:
            db.add(NewsTag(url_key=url_key(url), kind=kind, value=value))
        db.add(NewsTagState(url_key=url_key(url), status="done", model="m", taxonomy_version=1, attempts=1,
                            tagged_at=now, updated_at=now))
    db.commit()


def _media(items: list[dict]) -> list[str]:
    return [n["title"] for n in items if n["category"] == "media"]


def test_wrong_matches_stored_before_the_tighter_rule_are_hidden_but_kept(client, engine, catalog_md):
    from forliosa.services import stock as svc

    now = datetime.now(UTC)
    with Session(engine) as db:
        _store(db, now)
        db.add(MarketEvent(key="t-2027", symbol="2027.TW", date=date.today(), type="material_info",
                           title="公告本公司董事會決議", detail="", url=None, data={"time": "150210"},
                           source="twse-openapi"))
        db.commit()
        stored = db.scalar(select(func.count()).select_from(NewsArticle))
        assert stored == len(WRONG) + len(RIGHT)  # 17 rows; 15 links (two stored under two stocks)
        shown = {s: sorted(_media(svc.news(db, catalog_md, s.split(".")[0]))) for s, *_ in [*WRONG, *RIGHT]}
        assert shown == {
            "2027.TW": ["八大官股》台股大漲583點！官股買賣超出爐，狂買大成鋼2.3萬張、反手砍敬鵬逾5400張 | 下班經濟學"],
            "1321.TW": [], "4743.TWO": [], "2204.TW": [], "8261.TW": [],
            "2646.TW": ["星宇航空進軍大洋洲！明年3月飛雪梨、奧克蘭"],
            "2412.TW": ["中華電信帳單一夕翻4倍！NCC證實74萬戶收錯簡訊 原因曝光"],
            "2609.TW": ["陽明Q3EPS5.32元較市場預估值高21% 有法人估Q4EPS4.15元"],
            "1905.TW": ["華紙售觀音廠予元太科技 處分利益估13.3億元",
                        "華紙法說會／大陸紙漿產能兩年暴增1,600萬噸 拚特殊紙、綠能雙轉型 | 個股情報"],
            "1216.TW": ["台南市長黃偉哲參訪統一企業智慧物流園區 探討未來發展需求"],
        }
        # official announcements are never hidden and come first
        assert svc.news(db, catalog_md, "2027")[0]["title"] == "公告本公司董事會決議"
        # kept in the database
        assert db.scalar(select(func.count()).select_from(NewsArticle)) == stored
        # the AI fallback's counts: what the reading side shows (the refresh passes its ReadMatch)
        check = service.ReadMatch(db, catalog_md)
        since = now - timedelta(days=7)
        assert service.recent_count(db, "2027.TW", since) == 4
        assert service.recent_count(db, "2027.TW", since, check=check) == 1
        assert service.recent_count(db, "8261.TW", since, check=check) == 0
        assert service.recent_free_count(db, "8261.TW", now, check=check) == 0
        assert service.ai_window(db, "8261.TW", now, check=check) == service.AI_WINDOW_EMPTY
        assert service.ai_window(db, "8261.TW", now) == service.AI_WINDOW  # without the check: the APEC rows
    # the API's /news is the same list
    media = _media(client.get("/api/v1/instruments/2027/news").json())
    assert media == ["八大官股》台股大漲583點！官股買賣超出爐，狂買大成鋼2.3萬張、反手砍敬鵬逾5400張 | 下班經濟學"]
    assert _media(client.get("/api/v1/instruments/1321/news").json()) == []


def _ctx(db: Session, md):
    from forliosa.ai.tools import ToolContext

    return ToolContext(db=db, user=db.scalar(select(User).where(User.email == "demo@forliosa.local")), md=md)


def test_get_news_search_news_and_by_topic_hide_them_too(client, engine, catalog_md, settings, monkeypatch):
    from forliosa.ai import tools

    now = datetime.now(UTC)
    monkeypatch.setattr(tools, "now_utc", lambda: now)
    monkeypatch.setattr(tags, "now_utc", lambda: now)
    tagged = {
        "https://www.storm.mg/article/11181868": {("theme", "geopolitics")},  # 2027台海: only under 2027 (wrong)
        "https://www.cna.com.tw/news/acn/202611160287.aspx": {("theme", "geopolitics")},  # APEC: only under 富鼎
        "https://ec.ltn.com.tw/article/breakingnews/5643289": {("sector", "15")},  # 星宇: under 大洋 and 星宇航空
        "https://udn.com/news/story/7252/9881833": {("theme", "earnings"), ("sector", "09")},  # 華紙法說會
    }
    with Session(engine) as db:
        _store(db, now, tag=tagged)
        # get_news: the same list as the stock page
        out = tools.execute(_ctx(db, catalog_md), "get_news", {"symbol": "2027"})
        assert not out.is_error and [b["source"] for b in out.content] == ["https://www.storm.mg/article/11181371"]
        empty = tools.execute(_ctx(db, catalog_md), "get_news", {"symbol": "8261"})
        assert json.loads(empty.content)["headlines"] == []
        # search_news: a headline stored only under wrong stocks is not found; one also stored under the right stock
        # is, with that stock only
        found = tags.search(db, catalog_md, keyword="大洋洲", now=now, settings=settings)
        assert [(n["title"], n["stocks"]) for n in found] == [
            ("星宇航空進軍大洋洲！明年3月飛雪梨、奧克蘭", [{"symbol": "2646.TW", "name": "星宇航空"}])]
        assert tags.search(db, catalog_md, symbol="1321.TW", now=now, settings=settings) == []
        assert tags.search(db, catalog_md, keyword="APEC", now=now, settings=settings) == []
        assert tags.search(db, catalog_md, theme="geopolitics", now=now, settings=settings) == []
        assert [n["title"] for n in tags.search(db, catalog_md, symbol="2027.TW", now=now, settings=settings)] == [
            "八大官股》台股大漲583點！官股買賣超出爐，狂買大成鋼2.3萬張、反手砍敬鵬逾5400張 | 下班經濟學"]
        tool = tools.execute(_ctx(db, catalog_md), "search_news", {"theme": "", "sector": "", "symbol": "",
                                                                   "keyword": "APEC", "days": 7})
        assert json.loads(tool.content)["headlines"] == []
        # by_topic (the market reports): the geopolitics group is gone, the others count what is shown
        themes = tags.by_topic(db, catalog_md, "theme", now - timedelta(days=7), now, settings=settings)
        assert [(g["id"], g["count"]) for g in themes] == [("earnings", 1)]
        sectors = tags.by_topic(db, catalog_md, "sector", now - timedelta(days=7), now, settings=settings)
        assert [(g["id"], g["count"]) for g in sectors] == [("09", 1), ("15", 1)]
        assert sectors[1]["items"][0]["stocks"] == [{"symbol": "2646.TW", "name": "星宇航空"}]
        # kept in the database
        assert db.scalar(select(func.count()).select_from(NewsArticle)) == len(WRONG) + len(RIGHT)


def test_a_stock_with_many_wrong_rows_still_fills_its_list(engine, catalog_md, settings):
    """Rows are read in pages until enough of them still match: 統一's 30 newest rows are politics (real titles of
    2026-11-16, each stored under several links here), its two right ones older."""
    now = datetime.now(UTC)
    wrong = [
        "藍營大老喊「2032統一貨幣」綠點名蔣萬安、江啟臣：送花是認同嗎？",
        "邱進益拋兩岸統一貨幣 黃暐瀚：韓國瑜、盧秀燕、國民黨中央請跟國人說明",
        "統一發票中獎注意！國稅局示警1行為 獎金恐被全數追回",
        "火警警報、撒水系統怎麼查？南消第一大隊實作統一安檢尺度",
        "國民黨切割「統一10年計畫」指非黨中央政策：再傳錯誤訊息就告",
    ]
    rows = [("1216.TW", wrong[i % 5], f"https://news.example.tw/politics/{i}", "某報", "gdelt") for i in range(30)]
    rows += [("1216.TW", "台南市長黃偉哲參訪統一企業智慧物流園區 探討未來發展需求",
              "https://n.yam.com/Article/20261113134393", "yam蕃薯藤", "gdelt"),
             ("1216.TW", "兩岸統一貨幣！新台幣消失惹議 央行總裁妙回「英國拒歐元」",  # a finance page is not enough
              "https://finance.ettoday.net/news/3273117", "ETtoday財經雲", "gdelt")]
    with Session(engine) as db:
        _store(db, now, rows)
        info = catalog_md.instrument("1216")
        items = service.media_items(db, catalog_md, info, settings=settings, now=now, limit=3)
        assert [n["title"] for n in items] == ["台南市長黃偉哲參訪統一企業智慧物流園區 探討未來發展需求"]


def test_the_check_builds_each_stocks_terms_once_and_leaves_us_rows_alone(engine, catalog_md, monkeypatch):
    calls: list[str] = []
    real = service.query_terms

    def counting(db, info, md=None, english=None):
        calls.append(info.symbol)
        return real(db, info, md, english)

    monkeypatch.setattr(service, "query_terms", counting)
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as db:
            check = service.ReadMatch(db, catalog_md)
            check.prefetch([s for s, *_ in STOCKS])
            title, url = WRONG[0][1], WRONG[0][2]
            started = time.perf_counter()
            for _ in range(100):  # about a stock page's rows
                assert not check.keeps("2027.TW", title, url)
                assert check.keeps("2027.TW", RIGHT[0][1], RIGHT[0][2])
            took = time.perf_counter() - started
            for s, *_ in STOCKS:
                check.terms(s)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert calls.count("2027.TW") == 1 and len(calls) == len(STOCKS)
    assert took < 1.0  # ~25 µs a row measured; generous for a slow machine
    # the company profiles of all the stocks in one query, none one by one
    profile_reads = [s for s in statements if "company_profiles" in s]
    assert sum(" IN " in s.upper() for s in profile_reads) == 1
    assert not [s for s in profile_reads if "company_profiles.symbol = " in s]
    # US stocks (their own rule), the US market and symbols no longer in the catalog are not checked again
    with Session(engine) as db:
        check = service.ReadMatch(db, catalog_md)
        assert check.keeps("NVDA", "Jensen Huang steps down", "https://example.com/a")  # synthetic
        assert check.keeps("^US", "Stocks fall", "https://example.com/b")  # synthetic
        assert check.keeps("9999.TW", "2027台海不平靜？", "https://example.com/c")  # synthetic, unknown symbol
        assert check.terms("9999.TW") is None and check.terms("NVDA") is None


def _profile_reads(engine, run) -> tuple[int, int]:
    """(queries reading many company profiles at once, queries reading one stock's profile) while ``run()`` runs."""
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    reads = [s for s in statements if "company_profiles" in s]
    return sum(" IN " in s.upper() for s in reads), sum("company_profiles.symbol = " in s for s in reads)


def test_search_news_reads_its_stocks_profiles_in_one_query_per_page(engine, catalog_md, settings):
    """2026-11-17 review: ``search_news`` without a symbol (a theme, a sector, a keyword) read each stock's company
    profile on its own (60 to 100 round trips to Postgres for a list of 160 rows). The rows of a page read are
    prefetched in one query before they are checked; nothing is prefetched by hand here."""
    now = datetime.now(UTC)
    with Session(engine) as db:
        _store(db, now)
    found: list[list[dict]] = []

    def every_stock():
        with Session(engine) as db:
            found.append(tags.search(db, catalog_md, now=now, settings=settings))

    many, one = _profile_reads(engine, every_stock)
    assert (many, one) == (1, 0)  # the 10 stocks of the 17 rows: one page, one query
    assert {s["symbol"] for n in found[-1] for s in n["stocks"]} == {s for s, *_ in RIGHT}

    def keyword():  # 中華電信 is stored under 2204 中華 (wrong) and 2412 中華電 (right)
        with Session(engine) as db:
            found.append(tags.search(db, catalog_md, keyword="中華電信", now=now, settings=settings))

    assert _profile_reads(engine, keyword) == (1, 0)
    assert [n["stocks"] for n in found[-1]] == [[{"symbol": "2412.TW", "name": "中華電"}]]

    def short_list():  # pages of 8: the newest 8 rows are wrong ones, the next page fills the list
        with Session(engine) as db:
            found.append(tags.search(db, catalog_md, limit=1, now=now, settings=settings))

    many, one = _profile_reads(engine, short_list)
    assert (many, one) == (2, 0)  # 3 pages read; the third holds no stock not read yet
    assert [n["title"] for n in found[-1]] == [RIGHT[0][1]]


class _FindsNothing:
    """An AI fallback that finds nothing: what is counted is the refresh's own reading."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def run(self, q, now, blocked, record):
        self.asked.append(q.symbol)
        return []


def test_refresh_reads_its_batchs_profiles_in_one_query(engine, catalog_md, settings):
    """2026-11-17 review: the refresh counted each stock's stored rows (``_ai_due``, ``ai_window``) with a check that
    read the stock's company profile on its own, on top of ``build_query``'s read. The batch's profiles are read in one
    query when the check is made."""
    now = datetime.now(UTC)
    symbols = [s for s, *_ in STOCKS]
    runner = _FindsNothing()
    with Session(engine) as db:
        _store(db, now)

    def refresh():
        with Session(engine) as db:
            service.refresh(db, catalog_md, settings=settings, sources=[], ai=lambda _db: runner, symbols=symbols,
                            bulk=None, now_fn=lambda: now)

    many, one = _profile_reads(engine, refresh)
    # every stock holds fewer than NEWS_AI_MIN_ITEMS rows that still match: each was counted (and searched)
    assert runner.asked == symbols
    assert many == 1
    assert one == len(symbols)  # build_query's own read of each stock, none from the check
