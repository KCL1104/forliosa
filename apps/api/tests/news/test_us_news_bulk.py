"""US stocks and the US market from GDELT's English bulk files (產品負責人 2026-11-17, option A): the US / UK outlet
allowlist, the title tests of :mod:`forliosa.news.us_match`, and the refresh using the English feed for US stocks and
``^US`` with the DOC API only as the fallback.

``gdelt_gkg_english_us_live_20261117.csv.zip`` holds 38 real rows of the English GKG files of 2026-11-16/17 (the 12 h
measured for ``CONTRACT_NOTES.md``), trimmed like the batch-3 fixtures (record id, site, URL and ``<PAGE_TITLE>`` as
published; the analysis columns emptied; every row moved to the 02:15 UTC slot): the true matches and the false
positives the measurement found. Titles written into a test by hand are marked ``synthetic``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.http import HttpStatusError
from forliosa.models import NewsArticle, NewsBlockedDomain, NewsFetchState, SecTicker
from forliosa.news import gdelt_bulk as gb
from forliosa.news import service
from forliosa.news.normalize import clean_title
from forliosa.news.outlets import (
    NOT_NEWS_DOMAINS,
    US_BUSINESS_DOMAINS,
    US_NEWS_DOMAINS,
    is_not_news,
    is_us_business_page,
    is_us_outlet,
    outlet_name,
    us_outlet_site,
)
from forliosa.news.us_match import EVERYDAY, PLAIN, STRICT, STRONG, market_matches, us_terms
from tests.news.conftest import FakeSource, fixture_bytes
from tests.news.test_gdelt_bulk import FakeFetcher, gkg_zip, index, index_url, url

SLOT = datetime(2026, 11, 17, 2, 15, tzinfo=UTC)
NOW = SLOT + timedelta(minutes=20)
US_FILE = fixture_bytes("gdelt_gkg_english_us_live_20261117.csv.zip")
# SEC's company_tickers.json titles (2026-11-17) of the companies the tests name
SEC = {
    "AAPL": (320193, "Apple Inc."), "APLE": (1418121, "Apple Hospitality REIT, Inc."),
    "AMZN": (1018724, "AMAZON COM INC"), "MSFT": (789019, "MICROSOFT CORP"), "NVDA": (1045810, "NVIDIA CORP"),
    "PLTR": (1321655, "Palantir Technologies Inc."), "TGT": (27419, "TARGET CORP"), "V": (1403161, "VISA INC."),
    "UBER": (1543151, "Uber Technologies, Inc"), "BRK-B": (1067983, "BERKSHIRE HATHAWAY INC"),
    "DOW": (1751788, "DOW INC."), "NDAQ": (1120193, "NASDAQ, INC."), "OTLK": (1649989, "Outlook Therapeutics, Inc."),
    "WMB": (107263, "WILLIAMS COMPANIES, INC."), "WSM": (719955, "WILLIAMS SONOMA INC"),
    "SNOA": (1367083, "Sonoma Pharmaceuticals, Inc."), "BILL": (1786352, "BILL Holdings, Inc."),
    "HERE": (1932770, "Here Group Ltd"), "RACE": (1648416, "Ferrari N.V."), "AI": (1577526, "C3.ai, Inc."),
    "NOV": (1021860, "NOV Inc."), "HUBG": (940942, "Hub Group, Inc."), "NAVN": (1639723, "Navan, Inc."),
    "F": (37996, "FORD MOTOR CO"), "META": (1326801, "Meta Platforms, Inc."),
    "MS": (895421, "MORGAN STANLEY"), "GS": (886982, "GOLDMAN SACHS GROUP INC"),
    "MFG": (1335730, "MIZUHO FINANCIAL GROUP INC"), "JPM": (19617, "JPMORGAN CHASE & CO"),
}


def add_sec(db: Session) -> None:
    for ticker, (cik, title) in SEC.items():
        db.merge(SecTicker(ticker=ticker, cik=cik, title=title))
    db.commit()


def info(code: str) -> InstrumentInfo:
    """A US listing as the catalog builds it from SEC's list (name = SEC's title)."""
    return InstrumentInfo(code, code, SEC[code][1], "US", "stock", "USD")


def us_rows() -> list[gb.GkgRow]:
    return list(gb.gkg_rows(US_FILE, gb.taiwan_or_us_site))


def titles_for(db: Session, code: str) -> list[str]:
    """The fixture's US-outlet headlines (cleaned) that ``code``'s terms match."""
    terms = us_terms(db, info(code))
    out = []
    for r in us_rows():
        if is_us_outlet(r.url):
            title = clean_title(r.title, r.url, outlet_name(r.url, r.domain))
            if terms.matches(title, r.url):
                out.append(title)
    return out


# -- outlets ----------------------------------------------------------------------------------------------------------
def test_the_us_outlet_allowlist():
    assert {"reuters.com", "apnews.com", "cnbc.com", "wsj.com", "bloomberg.com", "ft.com", "nytimes.com",
            "bbc.co.uk", "theguardian.com", "finance.yahoo.com"} <= US_NEWS_DOMAINS
    # every US outlet of the reputable list (outlets.REPUTABLE_DOMAINS), none of the not-news sites
    assert {"reuters.com", "cnbc.com", "bloomberg.com", "wsj.com", "ft.com", "apnews.com", "marketwatch.com",
            "barrons.com"} <= US_NEWS_DOMAINS
    assert not any(is_us_outlet(f"https://{d}/x") for d in NOT_NEWS_DOMAINS)
    assert US_BUSINESS_DOMAINS <= US_NEWS_DOMAINS
    assert is_us_outlet("https://www.cnbc.com/2026/11/16/a.html") and is_us_outlet("https://www.bbc.co.uk/news/x")
    assert is_us_outlet("https://finance.yahoo.com/markets/x") and not is_us_outlet("https://www.yahoo.com/news/x")
    assert not is_us_outlet("https://www.aol.com/articles/x") and not is_us_outlet("https://www.marketbeat.com/x")
    assert not is_us_outlet("https://www.taipeitimes.com/News/biz/x") and not is_us_outlet("https://local10.com/x")
    # not news on those sites: shopping, paid posts, quote pages
    for page in ("https://www.nytimes.com/wirecutter/reviews/x", "https://www.cnet.com/paid-content/x",
                 "https://www.theguardian.com/thefilter-us/best-pillows", "https://www.businessinsider.com/sc/x",
                 "https://www.morningstar.com/stocks/xnys/tu/quote", "https://cooking.nytimes.com/recipes/1"):
        assert not is_us_outlet(page), page
    assert is_not_news("https://www.morningstar.com/stocks/xnas/saia/analysis")  # hidden if stored before
    assert is_us_outlet("https://www.morningstar.com/stocks/7-new-4-star-stocks-this-week-2")  # an article
    # GDELT's site name may be the parent site of a listed outlet: a cheap first filter, the URL decides
    assert us_outlet_site("yahoo.com") and us_outlet_site("go.com") and not us_outlet_site("aol.com")
    assert is_us_business_page("https://www.latimes.com/business/story/x")
    assert is_us_business_page("https://techcrunch.com/2026/11/16/x")
    assert not is_us_business_page("https://www.nbcnews.com/news/us-news/x")


def test_rows_of_the_english_file_from_us_and_taiwanese_sites():
    rows = us_rows()
    assert len(rows) == 37  # AOL (an aggregator, not on the list) is left out at once
    assert {r.domain for r in rows} >= {"cnbc.com", "nytimes.com", "investors.com", "taipeitimes.com"}
    assert sum(1 for r in rows if is_us_outlet(r.url)) == 33  # less the quote page, the paid post, Taipei Times
    assert all(r.seen == SLOT for r in rows)


# -- the title tests --------------------------------------------------------------------------------------------------
def test_us_stocks_matched_in_the_english_file(engine):
    with Session(engine) as db:
        add_sec(db)
        assert titles_for(db, "NVDA") == [
            "Trump says Nvidia scandal did not put U.S. national security 'at risk'",
            "Trump Says He's Open to Reinstatement of Jensen Huang as Nvidia Chief",
            "Nasdaq Falls 626 Points to Start Nvidia-Anthropic Week: Stock Market Today",  # joined to another name
            "Nvidia Stock: Focus Shifts To China Chip Smuggling",
            "Stocks tumble on Wall St. as Nvidia leads another tech firm sell-off",
            "Dow Jones Top Company Headlines at 7 PM ET: Nvidia's Board Not Considering Reinstating Jensen Huang as "
            "CEO | United ...",
            "Bill Ackman on How Jensen Huang Could Be Restored As Nvidia CEO",
            "Dow Jones Futures: AMD, Nvidia, Micron Lead AI Trade Lower With Nvidia Earnings On Deck",
            "Stock Market Hit Again As Nvidia, Chip Stocks Cast Pall On Nasdaq, AI Trade",
        ]  # not Taipei Times' 「Nvidia's CEO search draws fire…」: a Taiwanese site
        assert titles_for(db, "AAPL") == ["Apple is adding face unlock to the iPhone Duo — without new hardware",
                                          "Apple reveals new Mac security controls as AI agents raise privacy risks"]
        assert titles_for(db, "AMZN") == [
            "Robert Pattinson is Amazon's first James Bond",  # The Verge: a business page, mid-sentence capital
            "Instagram now lets creators add Amazon affiliate links in reels and feed posts",
        ]  # not IBD's Title Case 「…ULA Loses Amazon Payload.」 (no company word: one story fewer, by design)
        assert titles_for(db, "MSFT") == ["Microsoft says hidden software bug caused Outlook outage last week"]
        # The Guardian's section tail stays, as it did from the DOC API (same page title)
        assert titles_for(db, "PLTR") == ["Ministers to end Palantir's contract with NHS in England in 2029 | NHS"]
        assert titles_for(db, "BRK-B") == ["Here's What Berkshire Hathaway Bought and Sold in Q3"]
        assert titles_for(db, "WSM") == ["Williams-Sonoma Stock Back In Buy Range In Sketchy Market"]
        assert titles_for(db, "NAVN") == ["Navan Breaks Out, Defies Software Industry Slump"]  # IBD's chart words


@pytest.mark.parametrize("code", ["TGT", "V", "UBER", "OTLK", "WMB", "SNOA", "BILL", "HERE", "RACE", "AI", "NOV",
                                  "HUBG", "DOW", "NDAQ", "MS"])
def test_the_false_positives_measured_are_left_out(engine, code):
    """Each of these names appears in the file but no headline is about the company: Target (「Cognition Target the
    ROI」「S&P 500 target」), Visa (「visa change」), Uber (「Uber driver left with…」), Outlook Therapeutics
    (「Outlook outage」), Williams (「Serena Williams」), Sonoma (「Williams-Sonoma」), BILL (「Bill Ackman」), HERE
    (「Here's What…」), Ferrari (「the Ferrari of AI」), C3.ai (「AI stock boom」), NOV (「Nov. 16」), Hub Group
    (「Smart Home Hub」), Dow Inc. and Nasdaq, Inc. (the indexes), Morgan Stanley (its strategists' 「S&P 500
    target」)."""
    with Session(engine) as db:
        add_sec(db)
        assert titles_for(db, code) == []


def test_name_kinds(engine):
    with Session(engine) as db:
        add_sec(db)
        kinds = {c: {n.text: n.kind for n in us_terms(db, info(c)).names} for c in
                 ("NVDA", "AAPL", "PLTR", "OTLK", "NAVN", "DOW", "TGT", "WMB")}
    assert kinds["NVDA"]["Nvidia"] == STRONG and kinds["PLTR"]["Palantir"] == STRONG
    assert kinds["AAPL"]["Apple"] == EVERYDAY and kinds["TGT"]["Target"] == EVERYDAY
    assert kinds["OTLK"] == {"Outlook Therapeutics": STRONG, "Outlook": STRICT}  # measured everyday word
    assert kinds["NAVN"]["Navan"] == PLAIN and kinds["WMB"]["Williams"] == PLAIN
    assert kinds["DOW"]["Dow"] == STRICT  # the market's name
    with Session(engine) as db:
        add_sec(db)
        apple = us_terms(db, info("AAPL"))
    assert "hospitality" in next(n for n in apple.names if n.text == "Apple").not_after  # Apple Hospitality REIT


def test_tickers_and_curated_phrases(engine):
    """synthetic titles: the ticker forms and the curated phrases of US_HINTS."""
    with Session(engine) as db:
        add_sec(db)
        nvda, aapl, amzn, f, v, ai = (us_terms(db, info(c)) for c in ("NVDA", "AAPL", "AMZN", "F", "V", "AI"))
    cnbc = "https://www.cnbc.com/2026/11/16/x.html"
    for t in ("Why $NVDA is moving", "Chipmaker (NASDAQ: NVDA) reports", "NVDA stock slides", "Results (NVDA)"):
        assert nvda.matches(t, cnbc), t
    assert not nvda.matches("NVDA", cnbc) and not nvda.matches("nvidia shares slide", cnbc)
    assert not nvda.matches("Nvidia-backed startup raises funds", cnbc)
    assert ai.matches("C3.ai (NYSE: AI) raises guidance", cnbc) and not ai.matches("Artificial intelligence (AI) "
                                                                                   "stocks rally", cnbc)
    assert aapl.matches("Apple shares fall after iPhone delay", cnbc)
    for t in ("The best apple pie recipes for Thanksgiving", "Big Apple tourism rebounds", "Apple Hospitality REIT "
              "raises dividend", "Washington Apple Pie Contest crowns a winner"):
        assert not aapl.matches(t, cnbc), t
    assert not amzn.matches("Amazon rainforest fires hit record as investors fret", cnbc)
    assert amzn.matches("Amazon Web Services outage hits websites", "https://www.nbcnews.com/news/x")
    assert not f.matches("Doug Ford says Ontario will retaliate against tariffs", cnbc)
    assert f.matches("Ford recalls 1 million F-150 pickups", "https://www.nbcnews.com/news/x")
    assert not v.matches("Trump's H-1B Visa fee faces court test as investors watch", cnbc)
    assert v.matches("Visa earnings beat as card spending holds up", cnbc)


def test_a_brokerages_research_call_is_not_news_about_the_brokerage(engine):
    """Measured 2026-11-17 (CNBC, Fortune): 「Morgan Stanley S&P 500 target」「Goldman says it's just delayed」「Viking
    Holdings gets double upgrade from Mizuho」 are research calls; the other titles are synthetic."""
    with Session(engine) as db:
        add_sec(db)
        gs, ms, mfg, jpm = (us_terms(db, info(c)) for c in ("GS", "MS", "MFG", "JPM"))
    cnbc = "https://www.cnbc.com/2026/11/16/x.html"
    assert not ms.matches("Morgan Stanley S&P 500 target: 8,700 for 2027", cnbc)
    assert not gs.matches("The AI layoff wave never arrived in 2026. Goldman says it's just delayed", cnbc)
    assert not mfg.matches("Viking Holdings gets double upgrade from Mizuho", cnbc)
    assert not gs.matches("Goldman Sachs raises its Nvidia price target to $250", cnbc)
    assert gs.matches("Goldman Sachs shares rise after trading revenue beats estimates", cnbc)
    assert ms.matches("Morgan Stanley to cut 2,000 jobs", cnbc)
    assert jpm.matches("JPMorgan Chase experiencing 'technical issue'", cnbc)


def test_us_market_headlines():
    rows = [r for r in us_rows() if is_us_outlet(r.url)]
    titles = [clean_title(r.title, r.url, outlet_name(r.url, r.domain)) for r in rows]
    assert [t for t, r in zip(titles, rows, strict=True) if market_matches(t, r.url)] == [
        "Nasdaq Falls 626 Points to Start Nvidia-Anthropic Week: Stock Market Today",
        "Stocks tumble on Wall St. as Nvidia leads another tech firm sell-off",
        "A Struggling AI Trade Is Dragging Stocks Lower Ahead of Anthropic's IPO",
        "Fed Chairman Highlights Economic Uncertainty of A.I. Boom",
        "Morgan Stanley S&P 500 target: 8,700 for 2027",
        "Defensive Stocks Tyson, Starbucks Lead The S&P 500, Nasdaq 100 As AI Sell-Off Deepens",
        "Dow Jones Futures: AMD, Nvidia, Micron Lead AI Trade Lower With Nvidia Earnings On Deck",
        "Stock Market Hit Again As Nvidia, Chip Stocks Cast Pall On Nasdaq, AI Trade",
    ]  # not Dow Jones Newswires' 「Top Company Headlines」, 「5 Stocks to Buy…」 or 「…these 2 stocks」
    # synthetic: a press release's listing and other markets
    assert not market_matches("Acme Corp (Nasdaq: ACME) announces third-quarter results")
    assert not market_matches("FTSE 100 slips as Bank of England holds rates")
    assert market_matches("FTSE slips as Wall Street sells off")
    assert not market_matches("The Wolf of Wall Street star joins new series")


# -- the refresh ------------------------------------------------------------------------------------------------------
def english_bulk(answers: dict | None = None, feeds=("english",)) -> tuple[gb.GdeltBulk, FakeFetcher]:
    f = FakeFetcher(answers or {index_url("english"): index(SLOT, "english"), url(SLOT, "english"): US_FILE})
    return gb.GdeltBulk(feeds=feeds, max_files=1, fetcher=f), f  # type: ignore[arg-type]


def test_refresh_reads_us_stocks_and_the_market_from_the_english_file(engine, commercial_md, settings):
    bulk, f = english_bulk()
    doc = FakeSource(items={})
    with Session(engine) as db:
        db.add(NewsBlockedDomain(domain="kiplinger.com", reason="測試"))
        db.commit()
        for sym in ("NVDA", "AAPL"):
            service.record_view(db, sym, NOW)
        rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                              now_fn=lambda: NOW)
        assert rep.bulk_us_ok and not rep.bulk_ok and rep.bulk_us_rows == 33
        assert doc.calls == []  # neither the stocks nor the market asked the DOC API
        assert rep.skipped == {"gdelt_bulk": 2} and f.urls == [index_url("english"), url(SLOT, "english")]
        rows = {s: sorted(r.title for r in db.scalars(select(NewsArticle).where(NewsArticle.symbol == s)))
                for s in ("NVDA", "AAPL", service.US_MARKET_KEY)}
        assert len(rows["NVDA"]) == 8  # the 9 of the file less the blocked Kiplinger page
        assert "Nasdaq Falls 626 Points to Start Nvidia-Anthropic Week: Stock Market Today" not in rows["NVDA"]
        assert rows["AAPL"] == ["Apple is adding face unlock to the iPhone Duo — without new hardware",
                                "Apple reveals new Mac security controls as AI agents raise privacy risks"]
        assert len(rows[service.US_MARKET_KEY]) == 7 and "Fed Chairman Highlights Economic Uncertainty of A.I. Boom" \
            in rows[service.US_MARKET_KEY]
        nvda = list(db.scalars(select(NewsArticle).where(NewsArticle.symbol == "NVDA")))
        assert {a.source for a in nvda} == {"gdelt"} and all(a.published_at.replace(tzinfo=UTC) == SLOT for a in nvda)
        assert "Nvidia Stock: Focus Shifts To China Chip Smuggling" in rows["NVDA"]  # the outlet's tail is cut
        for sym in ("NVDA", service.US_MARKET_KEY):  # booked as answered up to the file's end (the AI gate, the
            st = db.get(NewsFetchState, ("gdelt", sym))  # DOC fallback's window)
            assert st.last_success_at.replace(tzinfo=UTC) == SLOT + gb.SLOT, sym
        items = service.market_items(db, commercial_md, settings=settings, now=NOW)
        assert items and all(i["source"] == "GDELT" for i in items)
        # the same file again (a second run before the next one): nothing new, no duplicate
        rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                              now_fn=lambda: NOW + timedelta(minutes=5))
        assert rep.stored == 0 and doc.calls == []


def test_the_doc_api_is_the_fallback_once_the_english_feed_stalls(engine, commercial_md, settings):
    bulk, f = english_bulk()
    doc = FakeSource(items={})
    with Session(engine) as db:
        service.record_view(db, "NVDA", NOW)
        assert service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                               now_fn=lambda: NOW).bulk_us_ok
        f.answers[index_url("english")] = HttpStatusError("storage.googleapis.com 回應 HTTP 429", 429)
        rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                              now_fn=lambda: NOW + timedelta(minutes=45))
        assert rep.bulk_us_ok and doc.calls == []  # paused, but the last file is still within FRESH
        later = SLOT + gb.FRESH + timedelta(minutes=30)
        rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                              now_fn=lambda: later)
        assert not rep.bulk_us_ok
        assert sorted(q.symbol for q in doc.calls) == ["NVDA", service.US_MARKET_KEY]
        assert all(q.since == SLOT + gb.SLOT - service.OVERLAP for q in doc.calls)  # from where the files left it


def test_one_english_download_serves_taiwan_and_us_stocks(engine, commercial_md, settings):
    answers = {index_url("english"): index(SLOT, "english"), url(SLOT, "english"): US_FILE,
               index_url(): index(SLOT), url(SLOT): gkg_zip()}
    bulk, f = english_bulk(answers, feeds=("translation", "english"))
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[FakeSource(items={})], ai=None,
                              bulk=bulk, symbols=["2330.TW", "NVDA"], now_fn=lambda: NOW)
        assert rep.bulk_ok and rep.bulk_us_ok and f.urls.count(url(SLOT, "english")) == 1
        tw = [a.title for a in db.scalars(select(NewsArticle).where(NewsArticle.symbol == "2330.TW"))]
        assert tw == ["Approved FDI hits Jan.-Oct. high; TSMC boosts outbound investments"]  # Taipei Times
        nvda = [a.domain for a in db.scalars(select(NewsArticle).where(NewsArticle.symbol == "NVDA"))]
        assert "taipeitimes.com" not in nvda and len(nvda) == 9
    # only US stocks tracked (and the market): the translation feed is not downloaded at all
    bulk, f = english_bulk(dict(answers), feeds=("translation", "english"))
    with Session(engine) as db:
        service.refresh(db, commercial_md, settings=settings, sources=[FakeSource(items={})], ai=None, bulk=bulk,
                        symbols=["NVDA"], now_fn=lambda: NOW + timedelta(hours=1))
    assert index_url() not in f.urls


def test_without_the_english_feed_us_stocks_keep_the_doc_api(engine, commercial_md, settings):
    bulk, _ = english_bulk({index_url(): index(SLOT), url(SLOT): gkg_zip()}, feeds=("translation",))
    doc = FakeSource(items={})
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                              symbols=["NVDA"], now_fn=lambda: NOW)
    assert not rep.bulk_us_ok and [q.symbol for q in doc.calls] == ["NVDA"]
