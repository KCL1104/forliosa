"""Headline normalisation, outlet names, relevance, de-duplication and the blocklist match."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from forliosa.news.normalize import (
    Headline,
    clean_title,
    clean_url,
    dedupe,
    is_amp_or_mobile,
    is_blocked,
    is_relevant,
    is_search_redirect,
    make_terms,
    normalize_domain,
    normalize_url,
    similar_titles,
    strip_suffixes,
    tidy_spacing,
    url_key,
)
from forliosa.news.outlets import is_aggregator, outlet_name
from forliosa.news.service import to_headlines
from forliosa.news.sources import Query, RawItem, parse_gdelt
from tests.news.conftest import FETCHED_AT, fixture_bytes

TSMC = make_terms("台積電", "2330", ["TSMC"])


def test_gdelt_spacing_is_removed_but_phrase_separators_stay():
    assert tidy_spacing("台積電高層 ： AI需求呈拋物線式成長") == "台積電高層：AI需求呈拋物線式成長"
    assert tidy_spacing(" 【 台股盤中 】 台積電上攻 ！ 台股站回43K大關") == \
        "【台股盤中】台積電上攻！台股站回43K大關"
    assert tidy_spacing("網傳駭客販售台積電4 . 6萬筆資料") == "網傳駭客販售台積電4.6萬筆資料"
    assert tidy_spacing("輝達盤後暴跌逾8 ％！ 台積電領殺") == "輝達盤後暴跌逾8％！台積電領殺"
    assert tidy_spacing("還能買 「 這檔 」？") == "還能買「這檔」？"
    # a space between two phrases is part of Taiwanese headlines
    assert tidy_spacing("南華大學邀請台積公司辦說明會 攜手培育人才") == "南華大學邀請台積公司辦說明會 攜手培育人才"
    # a title spaced character by character is joined
    assert tidy_spacing("台 積 電 法 說 會 釋 利 多") == "台積電法說會釋利多"
    assert tidy_spacing("TSMC posts record   revenue") == "TSMC posts record revenue"  # English untouched


def test_outlet_and_section_suffixes_are_removed():
    setn = "https://www.setn.com/news/1937110"
    assert clean_title("台積電高層 ： AI需求呈拋物線式成長 | 財經 | 三立新聞網 SETN . COM", setn) == \
        "台積電高層：AI需求呈拋物線式成長"
    ettoday = "https://finance.ettoday.net/news/1"
    assert clean_title("台積電10月營收再創高 ！ 外資喊3300元 | ETtoday財經雲", ettoday) == \
        "台積電10月營收再創高！外資喊3300元"
    assert clean_title("網傳駭客販售台積電資料 民眾憂 ： 守不住 ？ - 生活", "https://news.ltn.com.tw/news/life/1") == \
        "網傳駭客販售台積電資料 民眾憂：守不住？"
    assert clean_title("台積電擴產 - 自由財經", "https://ec.ltn.com.tw/article/1") == "台積電擴產"
    # a column name is not the outlet: kept (like Google Finance), only the generic section is removed
    assert clean_title("可口可樂本益比竟比台積電高 | 台股雜談 | 股市", "https://udn.com/news/story/1/2") == \
        "可口可樂本益比竟比台積電高 | 台股雜談"
    assert strip_suffixes("TSMC sales jump - Reuters", "https://www.reuters.com/technology/x") == "TSMC sales jump"
    # never down to a stub
    assert strip_suffixes("快訊 | 財經", "https://www.setn.com/news/1") == "快訊 | 財經"
    # a dash inside a headline is not a suffix
    assert strip_suffixes("台積電 - 美國廠進度", "https://udn.com/news/story/1/2") == "台積電 - 美國廠進度"


def test_outlet_names_by_domain():
    cases = {
        "https://udn.com/news/story/12806/9874222": "聯合新聞網",
        "https://money.udn.com/money/story/5612/1": "經濟日報",
        "https://www.cna.com.tw:443/news/afe/202611120182.aspx": "中央社",
        "https://news.ltn.com.tw/news/life/breakingnews/1": "自由時報",
        "https://ec.ltn.com.tw/article/breakingnews/1": "自由時報",
        "https://www.chinatimes.com/realtimenews/1": "中時新聞網",
        "https://www.ctee.com.tw/news/1": "工商時報",
        "https://finance.ettoday.net/news/1": "ETtoday",
        "https://www.setn.com/news/1": "三立",
        "https://news.tvbs.com.tw/money/1": "TVBS",
        "https://newtalk.tw/news/view/1": "新頭殼",
        "https://n.yam.com/Article/1": "蕃薯藤",
        "https://news.ustv.com.tw/newsdetail/1": "非凡新聞",
        "https://www.reuters.com/a": "Reuters",
        "https://www.example-news.com.tw/a": "example-news.com.tw",  # unknown: the domain
    }
    for url, name in cases.items():
        assert outlet_name(url) == name, url
    assert outlet_name("https://udn.com.evil.example/x") == "udn.com.evil.example"
    assert is_aggregator("https://tw.stock.yahoo.com/news/1") and not is_aggregator("https://udn.com/x")


def test_urls_are_cleaned_and_keyed():
    assert clean_url("https://www.cna.com.tw:443/news/afe/1.aspx#top") == "https://www.cna.com.tw/news/afe/1.aspx"
    assert clean_url("javascript:alert(1)") is None and clean_url("ftp://x/1") is None
    a = normalize_url("https://www.udn.com/news/1/?utm_source=line&from=x#comments")
    assert a == normalize_url("http://udn.com/news/1") == "https://udn.com/news/1"
    assert url_key("https://udn.com/news/1?utm_medium=a") == url_key("https://www.udn.com/news/1/")
    assert normalize_url("https://x.tw/a?id=1") != normalize_url("https://x.tw/a?id=2")


def test_canonical_urls_fold_tracking_scheme_mobile_and_amp_variants():
    same = [
        "https://www.cna.com.tw/news/afe/202611120200.aspx",
        "http://www.cna.com.tw/news/afe/202611120200.aspx/",
        "https://cna.com.tw/news/afe/202611120200.aspx?utm_source=line&utm_campaign=x&fbclid=IwAR0&gclid=1",
        "https://www.cna.com.tw/amp/news/afe/202611120200.aspx",  # an /amp/ segment
        "https://m.cna.com.tw/news/afe/202611120200.aspx#top",  # a mobile host
        "https://www-cna-com-tw.cdn.ampproject.org/c/s/www.cna.com.tw/amp/news/afe/202611120200.aspx",  # AMP cache
        "https://www.google.com/amp/s/www.cna.com.tw/amp/news/afe/202611120200.aspx",
    ]
    assert {normalize_url(u) for u in same} == {"https://cna.com.tw/news/afe/202611120200.aspx"}
    assert normalize_url("https://udn.com/news/amp/story/7240/1") == normalize_url("https://udn.com/news/story/7240/1")
    assert normalize_url("https://x.tw/a/story.amp.html") == normalize_url("https://x.tw/a/story.html")
    assert normalize_url("https://x.tw/a?outputType=amp&id=1") == normalize_url("https://x.tw/a?id=1")
    assert normalize_url("https://x.tw/a?b=2&a=1") == normalize_url("https://x.tw/a?a=1&b=2")  # order does not matter
    # only what the URL itself makes unambiguous: a different path or id stays different
    assert normalize_url("https://www.ettoday.net/amp/amp_news.php7?news_id=1") != \
        normalize_url("https://www.ettoday.net/news/20261112/1.htm")
    assert normalize_url("https://x.tw/a?outputType=json") != normalize_url("https://x.tw/a")
    assert normalize_url("https://x.tw/ampere") == "https://x.tw/ampere" and normalize_url("https://m.tw/a") == \
        "https://m.tw/a"
    # the stored link: tracking parameters out, everything else as published
    assert clean_url("https://money.udn.com/money/story/5612/1?fbclid=IwAR0&utm_source=x") == \
        "https://money.udn.com/money/story/5612/1"
    assert clean_url("https://news.ustv.com.tw/newsdetail/1?newsall=true&type=144&from=rss") == \
        "https://news.ustv.com.tw/newsdetail/1?newsall=true&type=144&from=rss"
    assert clean_url("https://www-cnbc-com.cdn.ampproject.org/c/s/www.cnbc.com/amp/2026/11/12/x.html") == \
        "https://www.cnbc.com/amp/2026/11/12/x.html"
    assert is_amp_or_mobile("https://m.setn.com/News.aspx?NewsID=1") and is_amp_or_mobile("https://x.tw/amp/1")
    assert not is_amp_or_mobile("https://www.setn.com/News.aspx?NewsID=1")


def test_search_engine_redirects_are_dropped_not_resolved():
    redirects = [
        "https://news.google.com/articles/CBMiK2h0dHBzOi8vd3d3LmV0dG9kYXkubmV0?oc=5",
        "https://news.google.com/rss/articles/CBMi?oc=5",
        "https://www.google.com/url?q=https://www.cna.com.tw/news/1&sa=U",
        "https://www.bing.com/news/apiclick.aspx?ref=FexRss&url=https%3a%2f%2fwww.setn.com%2fnews%2f1",
        "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly93d3cuY25hLmNvbS50dw",
        "https://r.search.yahoo.com/_ylt=A/RV=2/RE=1/RO=10/RU=https%3a%2f%2fwww.cna.com.tw%2f/RK=2/RS=x-",
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.cna.com.tw%2Fnews%2F1",
        "https://t.co/AbCdEf",
    ]
    for u in redirects:
        assert is_search_redirect(u) and clean_url(u) is None, u
    for u in ("https://www.cna.com.tw/news/afe/1.aspx", "https://tw.news.yahoo.com/x-1.html",
              "https://finance.yahoo.com/news/x.html", "https://blog.google/technology/x/"):
        assert not is_search_redirect(u) and clean_url(u) == u, u
    raw = [RawItem("台積電法說會前瞻", redirects[3], FETCHED_AT - timedelta(hours=1)),
           RawItem("台積電2奈米進度超前", redirects[0], FETCHED_AT - timedelta(hours=1))]
    q = Query("2330.TW", "2330", "台積電", "TWSE", (), TSMC, FETCHED_AT - timedelta(days=1), FETCHED_AT)
    assert to_headlines(raw, q, "searxng", []) == []


def test_relevance_needs_the_name_code_or_english_short_name():
    assert is_relevant("台積電10月營收再創高", TSMC)
    assert is_relevant("外資賣超(2330)與聯發科", TSMC)
    assert is_relevant("TSMC's Arizona fab ramps", TSMC)
    assert not is_relevant("南華大學邀請台積公司辦說明會", TSMC)
    assert not is_relevant("台股暴跌1165點失守44000點", TSMC)
    assert not is_relevant("加權指數重挫2330點", TSMC) and not is_relevant("股價來到2330元", TSMC)
    assert not is_relevant("代號23301的新股", TSMC) and not is_relevant("TSMCX fund", TSMC)
    jf = make_terms("正峰", "1538", ["JF"])  # an English short name under 3 letters is not used
    assert jf.names == ("正峰",) and not is_relevant("JF Morgan report", jf)
    us = make_terms("NVIDIA", "NVDA", ["NVIDIA"], ["輝達"])
    assert is_relevant("輝達財報優於預期", us) and is_relevant("Why NVDA fell today", us)
    assert is_relevant("Nvidia shares slide", us)  # a single word as a proper noun, any case after the capital


def test_everyday_english_short_names_need_their_published_case():
    """穩懋 「WIN」, 台達電 「DELTA」, Apple: an everyday word is the company only as an acronym in capitals or a
    capitalised proper noun (review 2026-11-12)."""
    win = make_terms("穩懋", "3105", ["WIN"])
    assert is_relevant("WIN Semiconductors expands GaN capacity", win) and is_relevant("穩懋10月營收", win)
    assert not is_relevant("Taiwan clinches WBC win over Japan", win)
    assert not is_relevant("Lai says Taiwan will win trust of allies", win)
    assert not is_relevant("Taiwan Clinches WBC Win Over Japan", win)  # title case is not the acronym
    delta = make_terms("台達電", "2308", ["DELTA"])
    assert is_relevant("DELTA posts record October sales", delta) and is_relevant("台達電(2308)法說", delta)
    assert not is_relevant("Delta Air Lines adds Taipei route", delta)
    assert not is_relevant("Flood risk in Mekong delta", delta)
    apple = make_terms("Apple", "AAPL", ["Apple", "Apple Inc."], ["蘋果"])
    assert is_relevant("Apple unveils new MacBook", apple) and is_relevant("APPLE shares rise", apple)
    assert is_relevant("Why apple inc. stock rose", apple)  # the full name, any case
    assert not is_relevant("Washington apple harvest hit by early frost", apple)
    hon_hai = make_terms("鴻海", "2317", ["HON HAI"])
    assert is_relevant("Hon Hai Precision lifts outlook", hon_hai)  # several words: any case
    assert is_relevant("MediaTek unveils Dimensity", make_terms("聯發科", "2454", ["MediaTek"]))


def h(title: str, url: str, minutes: int, source: str = "gdelt") -> Headline:
    return Headline(title=title, url=url, outlet=outlet_name(url), domain="", source=source,
                    published_at=FETCHED_AT - timedelta(minutes=minutes))


def test_dedupe_by_url_and_near_identical_titles():
    items = [
        h("台積電上攻！台股站回43K大關", "https://news.ustv.com.tw/newsdetail/1", 30),
        h("台積電上攻！台股站回43K大關", "https://news.ustv.com.tw/newsdetail/1?newsall=", 30),
        h("台積電法說會：AI需求強勁", "https://udn.com/news/1?utm_source=x", 60),
        h("台積電法說會：AI需求強勁", "https://udn.com/news/1", 50),
        # a Yahoo copy of a CNA story (published later): the original outlet stays
        h("【台股盤後】台股震盪收跌 台積電守住", "https://tw.stock.yahoo.com/news/abc", 5, "yahoo_rss"),
        h("台股盤後：台股震盪收跌 台積電守住", "https://www.cna.com.tw/news/afe/1.aspx", 20),
        h("台積電熊本二廠導入3奈米", "https://www.setn.com/news/2", 90),
    ]
    out = dedupe(items)
    assert [x.url for x in out] == ["https://www.cna.com.tw/news/afe/1.aspx", "https://news.ustv.com.tw/newsdetail/1",
                                    "https://udn.com/news/1?utm_source=x", "https://www.setn.com/news/2"]
    assert similar_titles("台積電上攻！", "台積電上攻") and not similar_titles("台積電上攻", "聯發科下跌")


def test_blocklist_matches_domains_and_subdomains():
    assert normalize_domain("https://www.UDN.com/news") == "udn.com"
    assert normalize_domain("www.ltn.com.tw") == "ltn.com.tw"
    assert is_blocked("https://money.udn.com/x", ["udn.com"]) and is_blocked("udn.com", ["udn.com"])
    assert not is_blocked("https://udn.com.evil.tw/x", ["udn.com"]) and not is_blocked("https://cna.com.tw", [])


def test_gdelt_fixture_through_the_whole_pipeline():
    raw = parse_gdelt(fixture_bytes("gdelt_tsmc_taiwan_live_20261112.json"))
    q = Query("2330.TW", "2330", "台積電", "TWSE", ("TSMC",), TSMC, FETCHED_AT - timedelta(days=7), FETCHED_AT)
    heads = dedupe(to_headlines(raw, q, "gdelt", blocked=["setn.com"]))
    titles = [x.title for x in heads]
    assert titles == [
        "台積電CPO霸主地位穩了？法人看好2027年EPS估達151元",
        "部分員工資訊遭置外部網站 台積電：無證據顯示系統遭入侵",
        "台積電營運再傳捷報！看好AI商機又不想重押單一個股 還能買「這檔」？",
        "網傳駭客販售台積電4.6萬筆資料 民眾憂：連護國神山都守不住？",
        "輝達盤後暴跌逾8％！台積電領殺 指數跌逾300點失守4萬4",
        "【台股盤中】台積電上攻！台股站回43K大關 收復10日線",
        "可口可樂本益比竟比台積電高！高科技輸給「快樂水」股民揭估值差異 | 台股雜談",
        "台積電10月營收再創高！外資喊3300元 3奈米缺貨恐至2028年",
        "美股四指數全收黑不影響！台股開紅盤站回4萬3、台積電2325元",
        "台積電擴廠帶動置產話題 北屯區日吸6.2人遷入",
    ]
    assert not any("setn.com" in x.url for x in heads)  # blocked domain
    assert heads[1].outlet == "中央社" and heads[1].url.startswith("https://www.cna.com.tw/news/")  # no :443
    assert all(x.published_at.tzinfo is not None and x.source == "gdelt" for x in heads)


def test_english_gdelt_titles_and_syndicated_copies():
    assert tidy_spacing("Nvidia $1 . 7 trillion bloodbath : Buy the crash or brace for more pain ? ") == \
        "Nvidia $1.7 trillion bloodbath: Buy the crash or brace for more pain?"
    assert tidy_spacing("NVIDIA ( NVDA ) reportedly set to oust CEO , report") == \
        "NVIDIA (NVDA) reportedly set to oust CEO, report"
    raw = parse_gdelt(fixture_bytes("gdelt_nvda_english_live_20261112.json"))
    terms = make_terms("NVIDIA", "NVDA", ["NVIDIA"], ["輝達"])
    q = Query("NVDA", "NVDA", "NVIDIA", "US", ("NVIDIA",), terms, FETCHED_AT - timedelta(days=7), FETCHED_AT)
    heads = to_headlines(raw, q, "gdelt", [])
    assert len(raw) == 16 and len(heads) == 10  # Sensex, GQG, Anthropic IPO, the wardrobe column … are not about it
    out = dedupe(heads)
    titles = [x.title for x in out]
    assert titles.count("Nvidia CEO Faces Scrutiny After Second Affair Reported") == 1  # 4 radio-station copies
    assert len(out) == 6
    assert "Nvidia faces more risks in deal pace than Jensen Huang exit, says Bloomberg Intelligence" in titles
    assert {x.outlet for x in out} >= {"The Business Times", "Moneycontrol"}
    assert parse_gdelt(fixture_bytes("gdelt_gudeng_empty_live_20261112.json")) == []  # a real empty answer


def test_window_and_future_items_are_dropped():
    q = Query("2330.TW", "2330", "台積電", "TWSE", (), TSMC, FETCHED_AT - timedelta(days=1), FETCHED_AT)
    raw = [RawItem("台積電舊聞", "https://udn.com/1", FETCHED_AT - timedelta(days=2)),
           RawItem("台積電未來", "https://udn.com/2", FETCHED_AT + timedelta(hours=3)),
           RawItem("台積電今天", "https://udn.com/3", FETCHED_AT - timedelta(hours=1))]
    assert [x.title for x in to_headlines(raw, q, "gdelt", [])] == ["台積電今天"]
    assert datetime(2026, 1, 1, tzinfo=UTC) < FETCHED_AT
