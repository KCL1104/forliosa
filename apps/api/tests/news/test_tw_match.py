"""Taiwan stocks' headline matching, tightened (產品負責人 2026-11-17), and headlines tagged as not finance hidden.

``gdelt_gkg_tw_precision_live_20261117.csv.zip`` holds 38 real rows of the GDELT bulk files of 2026-11-16/17 (both
feeds, Taiwanese sites; the 24 h measured for ``CONTRACT_NOTES.md``), trimmed like the earlier fixtures (record id,
site, URL and ``<PAGE_TITLE>`` as published; the analysis columns emptied; every row moved to the 03:15 UTC slot):
headlines the old rule stored under the wrong stock (25 matches) and under the right ones. Titles written into a test
by hand are marked ``synthetic``."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.marketdata.base import InstrumentInfo
from forliosa.models import MarketEvent, NewsArticle, NewsTag, NewsTagState
from forliosa.news import gdelt_bulk as gb
from forliosa.news import service, tw_match
from forliosa.news.normalize import Headline, clean_title, is_relevant, make_terms, url_key
from forliosa.news.tags import search
from forliosa.news.tw_match import code_mentioned, headline, is_finance_page
from tests.news.conftest import fixture_bytes

FIXTURE = fixture_bytes("gdelt_gkg_tw_precision_live_20261117.csv.zip")
NOW = datetime(2026, 11, 17, 3, 40, tzinfo=UTC)
# The listed companies these headlines touch (shioaji-data's cards of 2026-10-14: name, English short name).
CATALOG = [
    ("2027", "大成鋼", "TC"), ("2022", "聚亨", "TYCOONS"), ("1259", "安心", "AN-SHIN"), ("1321", "大洋", "OPC"),
    ("2646", "星宇航空", "STARLUX AIR"), ("1303", "南亞", "NPC"), ("2408", "南亞科", "NTC"), ("4743", "合一", ""),
    ("4129", "聯合", "UOC"), ("3576", "聯合再生", "URE"), ("2455", "全新", "VPEC"), ("1473", "台南", "TAINAN"),
    ("8261", "富鼎", "APEC"), ("1519", "華城", ""), ("1314", "中石化", "CPDC"), ("2204", "中華", "CMC"),
    ("2412", "中華電", "CHT"), ("1459", "聯發", "LAN FA"), ("2454", "聯發科", "MediaTek"), ("6188", "廣明", "QSI"),
    ("6730", "常廣", "LAGIS"), ("1315", "達新", "TAH HSIN"), ("1216", "統一", "UNI-PRESIDENT"),
    ("9908", "大台北", "GTG"), ("2538", "基泰", "KeeTai"), ("5007", "三星", "SAN SHING"), ("4923", "力士", ""),
    ("2371", "大同", "TATUNG COMPANY"), ("3038", "全台", "EDT"), ("2330", "台積電", "TSMC"), ("8046", "南電", ""),
    ("3189", "景碩", "KINSUS"), ("2609", "陽明", "YMTC"), ("2603", "長榮", "EMC"), ("2615", "萬海", "WANHAI"),
    ("1905", "華紙", "CHP"), ("5274", "信驊", "ASPEED"), ("3443", "創意", "GUC"), ("2884", "玉山金", "E.S.F.H"),
    ("0050", "元大台灣50", ""), ("00878", "國泰永續高股息", ""),
]


def info(code: str, name: str, english: str) -> InstrumentInfo:
    etf = code.startswith("00")
    return InstrumentInfo(f"{code}.TW", code, name, "TWSE", "etf" if etf else "stock", "TWD",
                          aliases=(english,) if english else ())


class Master:
    """What build_query reads of MarketData: the instrument master."""

    def __init__(self):
        self._m = {f"{c}.TW": info(c, n, e) for c, n, e in CATALOG}
        self._m["NVDA"] = InstrumentInfo("NVDA", "NVDA", "NVIDIA", "US", "stock", "USD", aliases=("輝達", "NVIDIA"))

    def master(self):
        return self._m


def queries(db: Session) -> dict[str, service.Query]:
    md = Master()
    return {s: service.build_query(db, i, NOW - timedelta(days=7), NOW, md) for s, i in md.master().items()
            if i.market != "US"}


def stored(found: dict[str, list]) -> dict[str, set[str]]:
    """headline -> the stocks it is stored under."""
    out: dict[str, set[str]] = {}
    for sym, items in found.items():
        for it in items:
            out.setdefault(clean_title(it.title, it.url)[:14], set()).add(sym.split(".")[0])
    return out


# -- the real headlines ------------------------------------------------------------------------------------------
EXPECTED = {  # the first 14 characters of each headline -> the stocks it is stored under now
    "外資連3砍台積電！今賣超84": {"2330"},
    "焦點股》南亞：國家隊來了？股": {"1303"},  # a short everyday name with a finance word next to it
    "南電、景碩苦吞跌停 PCB族": {"8046", "3189"},
    "陽明Q3EPS5.32元較市": {"2609"},
    "長榮.陽明逆風大盤惜尾盤翻黑": {"2603", "2609", "2615"},
    "焦點股》0050：開盤重挫千": {"0050"},  # an ETF code, bare
    "00878配1.25元破紀錄": {"00878"},
    "華紙法說會／大陸紙漿產能兩年": {"1905"},
    "高價股崩！信驊、創意等逾10": {"5274", "3443"},  # 創意 listed next to 信驊
    "《鋼鐵股》三星前3季EPS升": {"5007"},
    "Approved FDI h": {"2330"},  # an English headline: TSMC
    "《金融股》玉山金10月賺進3": {"2884"},
    "焦點股》信驊：唯一「萬元股」": {"5274"},
    "京華城案燒到沈慶京長子！中石": {"1314"},  # not 華城 (京華城)
    "中華電信帳單一夕翻4倍！NC": {"2412"},  # 中華電, not 中華 (the longest name)
    "輝達接班不確定！郭明錤點2公": {"2454"},  # 聯發科, not 聯發
    "常廣明年營收拚雙位數成長 日": {"6730"},  # not 廣明 (straddles 明年)
    "星宇航空進軍大洋洲！明年3月": {"2646"},  # not 大洋 (大洋洲)
}


def pairs(found: dict[str, list]) -> set[tuple[str, str]]:
    return {(it.url, sym) for sym, items in found.items() for it in items}


def test_real_headlines_stored_under_the_right_stocks_only(engine):
    rows = list(gb.gkg_rows(FIXTURE))
    assert len(rows) == 38
    with Session(engine) as db:
        qs = queries(db)
    found = gb.match(rows, qs)
    assert stored(found) == EXPECTED
    # the old rule (any name or code anywhere in the title) on the same rows: 49 matches; the new rule keeps 22, all
    # right, and drops 27: 25 wrong ones and the two copies of 「基泰大直案 北市府：外界混淆施工圖…」 (基泰 is a
    # two-character name with no finance word near it on a politics page)
    old = gb.match(rows, {s: dataclass_replace(q) for s, q in qs.items()})
    assert len(pairs(old)) == 49 and len(pairs(found)) == 22 and pairs(found) <= pairs(old)
    before = stored(old)
    wrong = {(h, c) for h, cs in before.items() for c in cs} - {(h, c) for h, cs in EXPECTED.items() for c in cs}
    assert {("2027台海不平靜？美軍前司", "2027"), ("星宇航空進軍大洋洲！明年3月", "1321"),
            ("繞道東南亞租算力行不通了！美", "1303"), ("游盈隆視察高雄九合一選務 目", "4743"),
            ("全美航班大亂才剛落幕 聯合航", "4129"), ("台南市長候選人0政見「去看台", "1473"),
            ("川普APEC行程曝光 川習會", "8261"), ("中華電信帳單一夕翻4倍！NC", "2204"),
            ("兩岸統一貨幣！新台幣消失惹議", "1216"), ("基泰大直案 北市府：外界混淆", "9908"),
            ("2026新社花海接駁運能增近", "1259"), ("TVBS民調／沈伯洋、蔣萬安", "2022"),
            ("林國漳風雨無阻前進大同、三星", "2371"), ("林國漳風雨無阻前進大同、三星", "5007"),
            ("三星晶圓代工拚轉型！搶攻Sp", "5007"), ("SK海力士韓國新推晶片測試廠", "4923")} <= wrong


def dataclass_replace(q: service.Query) -> service.Query:
    """The same query with the old rule's terms (``taiwan`` off)."""
    from dataclasses import replace

    return replace(q, terms=make_terms(q.name, q.code, q.english))


# -- codes -------------------------------------------------------------------------------------------------------
def test_a_code_counts_only_with_stock_context():
    names = ["台積電"]
    # synthetic: with stock context
    for title in ("台積電(2330)法說會", "外資賣超（2330）", "【2330台積電】營收", "台積電 2330 漲停", "台積電2330",
                  "股票代號：2330", "(2330.TW) ADR", "2330.TW gains", "熱門股(2330、2317)", "(TW:2330)"):
        assert code_mentioned(title, "2330", names), title
    # synthetic: a year, an amount, a percentage, a date, a time, part of a longer number, a bare number
    for title in ("2330年的願景", "股價來到2330元", "加權指數重挫2330點", "營收2330億", "漲幅2330%", "代號23301的新股",
                  "12,330張", "2330.5元", "2026/2330", "2330-2335", "(2330年)", "2330台海", "股價2330 收高"):
        assert not code_mentioned(title, "2330", names), title
    # real (the fixture): years used bare, a count; an ETF code bare
    assert not code_mentioned("2027台海不平靜？美軍前司令「希望自己預測錯誤」", "2027", ["大成鋼"])
    assert not code_mentioned("2027最低工資再漲！好清潔解析駐點清潔預算的4項評估重點", "2027", ["大成鋼"])
    assert not code_mentioned("2026新社花海接駁運能增近2成！6條免費路線週末發出1259班次", "1259", ["安心"])
    assert code_mentioned("焦點股》0050：開盤重挫千點 散戶撿鑽石？", "0050", ["元大台灣50"])
    assert not code_mentioned("0050元的便當", "0050", [])  # synthetic: an ETF code followed by a unit
    assert is_relevant("2030半導體營收占比過半", make_terms("彰源", "2030", taiwan=True)) is False
    assert is_relevant("彰源(2030)前3季EPS", make_terms("彰源", "2030", taiwan=True))  # synthetic


# -- names -------------------------------------------------------------------------------------------------------
def test_short_and_everyday_names_need_a_finance_word_the_code_or_a_finance_page():
    nanya = make_terms("南亞", "1303", ["NPC"], taiwan=True, longer=["南亞科"])
    assert is_relevant("焦點股》南亞：國家隊來了？股價一度翻紅", nanya)
    assert is_relevant("南亞(1303)前3季獲利", nanya)  # synthetic: the code
    assert not is_relevant("繞道東南亞租算力行不通了！美祭新規封殺中國AI晶片漏洞", nanya)  # inside 東南亞
    assert not is_relevant("主動ETF大減碼南亞科、聯電 創意連三日獲加碼", nanya)  # 南亞科 is another stock
    # a two-character name that is not an everyday word: a finance word within 8 characters, or a finance page
    jingcai = make_terms("精材", "3374", ["Xintec"], taiwan=True)
    assert is_relevant("《半導體》精材反轉跌停 10月獲利雙增雙位數", jingcai)
    assert is_relevant("精材攜手客戶推新製程", jingcai, url="https://ec.ltn.com.tw/article/breakingnews/1")  # synthetic
    assert is_relevant("精材攜手客戶推新製程 | 科技產業 | 產經", jingcai)  # synthetic: udn's finance section tail
    assert not is_relevant("精材攜手客戶推新製程", jingcai, url="https://news.ltn.com.tw/news/life/breakingnews/1")
    # an everyday word: the code or a finance word right next to it; a finance page is not enough
    tongyi = make_terms("統一", "1216", ["UNI-PRESIDENT"], taiwan=True, longer=["統一超", "統一證", "統一實"])
    assert not is_relevant("兩岸統一貨幣！新台幣消失惹議 央行總裁妙回「英國拒歐元」", tongyi,
                           url="https://finance.ettoday.net/news/3273117",
                           raw_title="兩岸統一貨幣！新台幣消失惹議 央行總裁妙回「英國拒歐元」 | ETtoday財經雲")
    assert is_relevant("統一前3季EPS創新高", tongyi)  # synthetic
    assert not is_relevant("統一超10月營收創高", tongyi)  # synthetic: 統一超 is another stock


def test_embedded_words_and_the_longest_name():
    def t(name, code, longer=()):
        return make_terms(name, code, taiwan=True, longer=longer)

    assert not is_relevant("星宇航空進軍大洋洲！明年3月飛雪梨、奧克蘭", t("大洋", "1321"))
    assert not is_relevant("全美航班大亂才剛落幕 聯合航空又爆大規模系統故障", t("聯合", "4129", ["聯合再生"]))
    assert not is_relevant("聯合再生前3季虧損收斂", t("聯合", "4129", ["聯合再生"]))  # synthetic
    assert is_relevant("聯合再生前3季虧損收斂", t("聯合再生", "3576"))  # synthetic
    assert not is_relevant("游盈隆視察高雄九合一選務 目標11/28午夜12時前完成開票", t("合一", "4743"))
    assert not is_relevant("全新的一年 股市展望", t("全新", "2455"))  # synthetic: 全新 the word, even beside 股
    assert not is_relevant("常廣明年營收拚雙位數成長 日本轉單、新廠自動化助攻", t("廣明", "6188", ["廣明光"]))
    assert is_relevant("常廣明年營收拚雙位數成長 日本轉單、新廠自動化助攻", t("常廣", "6730"))
    assert not is_relevant("輝達新加坡營收說明4度調整？美國SEC前執法主管發萬言書追問", t("達新", "1315"))
    assert not is_relevant("中華電信帳單一夕翻4倍！NCC證實74萬戶收錯簡訊 原因曝光", t("中華", "2204", ["中華電"]))
    assert is_relevant("中華電信帳單一夕翻4倍！NCC證實74萬戶收錯簡訊 原因曝光", t("中華電", "2412"))
    # what follows 「 | 」 is a column, not the headline; a long part is a digest's story
    assert headline("基泰大直案 北市府：外界混淆施工圖與建照核准圖差異 | 大台北 | 地方") == \
        "基泰大直案 北市府：外界混淆施工圖與建照核准圖差異"
    assert not is_relevant("基泰大直案 北市府：外界混淆施工圖與建照核准圖差異 | 大台北", t("大台北", "9908"))
    digest = "DIGITIMES Today：超微擴大進攻量子混合運算 | 華為推全中製PC | 韓廠憂心南亞科、華邦電積極導入EUV"
    assert is_relevant(digest, t("華邦電", "2344")) and is_relevant(digest, t("南亞科", "2408"))
    assert not is_relevant(digest, t("南亞", "1303", ["南亞科"]))


def test_english_names_count_in_english_headlines_only():
    apec = make_terms("富鼎", "8261", ["APEC"], taiwan=True)
    assert not is_relevant("川普APEC行程曝光 川習會後再舉行美中俄領袖峰會", apec)
    tsmc = make_terms("台積電", "2330", ["TSMC"], taiwan=True)
    assert is_relevant("Approved FDI hits Jan.-Oct. high; TSMC boosts outbound investments", tsmc)
    assert not is_relevant("Mekong delta floods and the tsmc of it all", tsmc)  # synthetic: lower case


def test_finance_pages():
    assert is_finance_page("https://ec.ltn.com.tw/article/breakingnews/5643257")
    assert is_finance_page("https://finance.ettoday.net/news/3273311")
    assert is_finance_page("https://www.cna.com.tw/news/afe/202611160123.aspx")
    assert is_finance_page("https://news.tvbs.com.tw/money/4051265")
    assert is_finance_page("https://www.chinatimes.com/realtimenews/20261116003110-260410")
    assert is_finance_page("https://udn.com/news/story/7252/9881833")
    assert is_finance_page("", "南電、景碩苦吞跌停 | 財經 | 三立新聞網 SETN.COM")
    assert not is_finance_page("https://www.cna.com.tw/news/aipl/202611170042.aspx", "游盈隆視察 | 政治")
    assert not is_finance_page("https://speed.ettoday.net/news/3273352", "Nissan全新中型休旅接單 | ETtoday車雲")


def test_the_lists_hold_no_listed_companys_own_name():
    """A word of WORDS must not swallow a listed company's full name (中華電信 is 中華電's, 長榮航空 長榮航's)."""
    names = {n for _, n, _ in CATALOG} | {"長榮航", "中華電"}
    for w in tw_match.WORDS:
        for n in names:
            if n in w and w.startswith(n) and len(n) >= 3:
                pytest.fail(f"{w} would hide {n}")
    assert not tw_match.needs_context("台積電") and tw_match.needs_context("南亞") and tw_match.needs_context("永冠-KY")


def test_us_matching_is_unchanged():
    """US stocks keep the old title test (the US bulk matcher is us_match, untouched): a two-character Chinese alias
    and a bare ticker still count, as before 2026-11-17."""
    nvda = make_terms("NVIDIA", "NVDA", ["NVIDIA"], ["輝達"])
    assert not nvda.taiwan
    assert is_relevant("輝達財報優於預期", nvda) and is_relevant("Why NVDA fell today", nvda)
    assert is_relevant("Nvidia shares slide", nvda) and not is_relevant("NVDAX fund", nvda)
    rows = list(gb.gkg_rows(fixture_bytes("gdelt_gkg_english_us_live_20261117.csv.zip"),
                            keep_domain=gb.taiwan_or_us_site))
    assert rows  # the US fixture still parses; its matches are asserted in test_us_news_bulk.py, unchanged


# -- headlines tagged as not finance --------------------------------------------------------------------------------
def _store(db: Session, symbol: str, title: str, url: str, at: datetime, tags: set[tuple[str, str]] | None):
    """A headline and, unless ``tags`` is None, its finished tagging (``set()``: tagged with nothing)."""
    service.store(db, symbol, [Headline(title, url, "經濟日報", "money.udn.com", at, "gdelt")], at)
    if tags is not None:
        for kind, value in tags:
            db.add(NewsTag(url_key=url_key(url), kind=kind, value=value))
        db.add(NewsTagState(url_key=url_key(url), status="done", model="m", taxonomy_version=1, attempts=1,
                            tagged_at=at, updated_at=at))
    db.commit()


def test_headlines_tagged_without_finance_tags_are_hidden_but_kept(client, engine, commercial_md, settings):
    from forliosa.services import stock as svc

    now = datetime.now(UTC)
    with Session(engine) as db:
        _store(db, "2330.TW", "台積電法說會釋利多", "https://money.udn.com/h/1", now - timedelta(hours=1),
               {("theme", "earnings")})
        _store(db, "2330.TW", "台積電運動會熱鬧登場", "https://money.udn.com/h/2", now - timedelta(hours=2), set())
        _store(db, "2330.TW", "台積電還沒貼標籤", "https://money.udn.com/h/3", now - timedelta(hours=3), None)
        _store(db, "2330.TW", "台積電只有相關股票", "https://money.udn.com/h/4", now - timedelta(hours=4),
               {("symbol", "2317.TW")})
        db.add(MarketEvent(key="t-1", symbol="2330.TW", date=date.today(), type="material_info",
                           title="公告本公司董事會決議", detail="", url=None, data={"time": "150210"},
                           source="twse-openapi"))
        db.commit()
        items = svc.news(db, commercial_md, "2330")
        titles = [n["title"] for n in items]
        assert titles[0] == "公告本公司董事會決議"  # official announcements are never hidden
        assert set(titles[1:]) == {"台積電法說會釋利多", "台積電還沒貼標籤", "台積電只有相關股票"}
        assert db.scalar(select(NewsArticle).where(NewsArticle.url == "https://money.udn.com/h/2")) is not None
        assert service.recent_count(db, "2330.TW", now - timedelta(days=1)) == 3
        found = search(db, commercial_md, symbol="2330.TW", now=now, settings=settings)
        assert {n["title"] for n in found} == {"台積電法說會釋利多", "台積電還沒貼標籤", "台積電只有相關股票"}
        assert not search(db, commercial_md, keyword="運動會", now=now, settings=settings)
    # the API's /news is the same list
    media = [n["title"] for n in client.get("/api/v1/instruments/2330/news").json() if n["category"] == "media"]
    assert "台積電運動會熱鬧登場" not in media and "台積電還沒貼標籤" in media
