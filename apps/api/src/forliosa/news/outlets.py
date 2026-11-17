"""Domain -> outlet name (媒體名稱) for the 「新聞報導」 list.

A host matches its longest listed suffix (``money.udn.com`` 經濟日報 before ``udn.com`` 聯合新聞網); an unknown
host is shown as its domain without ``www.``. ``aliases`` are the extra spellings an outlet uses in its own
``<title>`` suffix (「| 三立新聞網 SETN.COM」「| ETtoday財經雲」), so ``normalize.strip_suffixes`` can remove a tail
that only repeats the outlet.

Three lists sort sites for the 「新聞報導」 list (2026-11-16): :data:`TAIWAN_DOMAINS` (with every ``.tw`` host: what
GDELT's bulk files are filtered to for Taiwan stocks), :data:`REPUTABLE_DOMAINS` (preferred, never required) and
:data:`NOT_NEWS_DOMAINS` (quote pages, forums, blogs, AI-written pages: never a headline).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Outlet:
    name: str
    aliases: tuple[str, ...] = ()
    aggregator: bool = False  # republishes other outlets' stories (a duplicate from it loses to the original)


OUTLETS: dict[str, Outlet] = {
    # -- Taiwan
    "udn.com": Outlet("聯合新聞網", ("聯合新聞網", "聯合報", "udn")),
    "money.udn.com": Outlet("經濟日報", ("經濟日報", "經濟日報 money", "udn")),
    "cna.com.tw": Outlet("中央社", ("中央社", "中央通訊社", "cna")),
    "focustaiwan.tw": Outlet("Focus Taiwan", ("focus taiwan", "cna english news")),
    "ltn.com.tw": Outlet("自由時報", ("自由時報", "自由財經", "自由時報電子報", "ltn")),
    "ec.ltn.com.tw": Outlet("自由時報", ("自由財經", "自由時報", "ltn")),
    "chinatimes.com": Outlet("中時新聞網", ("中時新聞網", "中時", "中國時報", "chinatimes")),
    "ctee.com.tw": Outlet("工商時報", ("工商時報", "工商", "ctee")),
    "ettoday.net": Outlet("ETtoday", ("ettoday", "ettoday新聞雲", "ettoday財經雲", "ettoday房產雲")),
    "setn.com": Outlet("三立", ("三立新聞網", "三立", "setn", "setn.com")),
    "tvbs.com.tw": Outlet("TVBS", ("tvbs", "tvbs新聞網")),
    "newtalk.tw": Outlet("新頭殼", ("新頭殼", "newtalk")),
    "blocktempo.com": Outlet("動區動趨", ("動區動趨", "blocktempo")),
    "yam.com": Outlet("蕃薯藤", ("蕃薯藤", "yam", "yam蕃薯藤新聞")),
    "ustv.com.tw": Outlet("非凡新聞", ("非凡新聞", "非凡", "ustv")),
    "cnyes.com": Outlet("鉅亨網", ("鉅亨網", "鉅亨", "anue", "cnyes")),
    "moneydj.com": Outlet("MoneyDJ", ("moneydj", "moneydj理財網")),
    "storm.mg": Outlet("風傳媒", ("風傳媒", "storm")),
    "businesstoday.com.tw": Outlet("今周刊", ("今周刊", "businesstoday")),
    "wealth.com.tw": Outlet("財訊", ("財訊", "wealth")),
    "cw.com.tw": Outlet("天下雜誌", ("天下雜誌", "天下")),
    "gvm.com.tw": Outlet("遠見", ("遠見", "遠見雜誌")),
    "bnext.com.tw": Outlet("數位時代", ("數位時代", "bnext")),
    "technews.tw": Outlet("科技新報", ("科技新報", "technews")),
    "digitimes.com.tw": Outlet("DIGITIMES", ("digitimes",)),
    "digitimes.com": Outlet("DIGITIMES", ("digitimes",)),
    "mirrormedia.mg": Outlet("鏡週刊", ("鏡週刊", "鏡新聞", "mirror media")),
    "nownews.com": Outlet("NOWnews", ("nownews", "今日新聞")),
    "ebc.net.tw": Outlet("東森新聞", ("東森新聞", "ebc東森新聞", "ebc")),
    "ftnn.com.tw": Outlet("FTNN 新聞網", ("ftnn", "ftnn新聞網")),
    "taisounds.com": Outlet("太報", ("太報", "taisounds")),
    "upmedia.mg": Outlet("上報", ("上報", "upmedia")),
    "thenewslens.com": Outlet("關鍵評論網", ("關鍵評論網", "the news lens")),
    "ctwant.com": Outlet("CTWANT", ("ctwant",)),
    "rti.org.tw": Outlet("中央廣播電臺", ("中央廣播電臺", "央廣", "rti")),
    "pts.org.tw": Outlet("公視新聞網", ("公視新聞網", "公視", "pnn")),
    "cts.com.tw": Outlet("華視", ("華視", "華視新聞")),
    "ttv.com.tw": Outlet("台視", ("台視", "台視新聞")),
    "ftvnews.com.tw": Outlet("民視", ("民視", "民視新聞")),
    "ctinews.com": Outlet("中天新聞", ("中天新聞", "中天")),
    "voachinese.com": Outlet("美國之音", ("美國之音", "voa")),
    "rfi.fr": Outlet("法廣", ("法廣", "rfi")),
    "bbc.com": Outlet("BBC", ("bbc", "bbc news", "bbc news 中文")),
    "epochtimes.com": Outlet("大紀元", ("大紀元", "epoch times")),
    "ntdtv.com": Outlet("新唐人", ("新唐人",)),
    "taipeitimes.com": Outlet("Taipei Times", ("taipei times",)),
    "taiwannews.com.tw": Outlet("Taiwan News", ("taiwan news",)),
    "ithome.com.tw": Outlet("iThome", ("ithome",)),
    "cardu.com.tw": Outlet("卡優新聞網", ("卡優新聞網", "卡優", "cardu")),
    "line.me": Outlet("LINE TODAY", ("line today",), aggregator=True),
    "yahoo.com": Outlet("Yahoo新聞", ("yahoo新聞", "yahoo奇摩新聞", "yahoo"), aggregator=True),
    "tw.stock.yahoo.com": Outlet("Yahoo股市", ("yahoo股市", "yahoo財經", "yahoo"), aggregator=True),
    "finance.yahoo.com": Outlet("Yahoo Finance", ("yahoo finance", "yahoo"), aggregator=True),
    "msn.com": Outlet("MSN", ("msn",), aggregator=True),
    "pchome.com.tw": Outlet("PChome 新聞", ("pchome",), aggregator=True),
    "hinet.net": Outlet("HiNet 新聞", ("hinet",), aggregator=True),
    # -- US / international
    "reuters.com": Outlet("Reuters", ("reuters",)),
    "bloomberg.com": Outlet("Bloomberg", ("bloomberg",)),
    "cnbc.com": Outlet("CNBC", ("cnbc",)),
    "wsj.com": Outlet("The Wall Street Journal", ("wsj", "the wall street journal", "wall street journal")),
    "marketwatch.com": Outlet("MarketWatch", ("marketwatch",)),
    "barrons.com": Outlet("Barron's", ("barron's", "barrons")),
    "ft.com": Outlet("Financial Times", ("financial times", "ft")),
    "nytimes.com": Outlet("The New York Times", ("the new york times", "new york times", "nytimes")),
    "apnews.com": Outlet("AP", ("ap", "ap news", "associated press")),
    "forbes.com": Outlet("Forbes", ("forbes",)),
    "fortune.com": Outlet("Fortune", ("fortune",)),
    "businessinsider.com": Outlet("Business Insider", ("business insider", "insider")),
    "fool.com": Outlet("The Motley Fool", ("the motley fool", "motley fool")),
    "investing.com": Outlet("Investing.com", ("investing.com",)),
    "seekingalpha.com": Outlet("Seeking Alpha", ("seeking alpha",)),
    "theverge.com": Outlet("The Verge", ("the verge",)),
    "techcrunch.com": Outlet("TechCrunch", ("techcrunch",)),
    "cnn.com": Outlet("CNN", ("cnn", "cnn business")),
    "nikkei.com": Outlet("Nikkei Asia", ("nikkei asia", "nikkei")),
    "scmp.com": Outlet("South China Morning Post", ("south china morning post", "scmp")),
    "businesstimes.com.sg": Outlet("The Business Times", ("the business times", "business times")),
    "moneycontrol.com": Outlet("Moneycontrol", ("moneycontrol",)),
    "indiatimes.com": Outlet("The Times of India", ("the times of india", "times of india")),
    "hindustantimes.com": Outlet("Hindustan Times", ("hindustan times",)),
    "thehindu.com": Outlet("The Hindu", ("the hindu",)),
    "thehindubusinessline.com": Outlet("BusinessLine", ("businessline", "the hindu businessline")),
    "theglobeandmail.com": Outlet("The Globe and Mail", ("the globe and mail",)),
    "koreatimes.co.kr": Outlet("The Korea Times", ("the korea times", "korea times")),
    "afr.com": Outlet("Australian Financial Review", ("australian financial review", "afr")),
    "247wallst.com": Outlet("24/7 Wall St.", ("24/7 wall st", "247wallst")),
    "iheart.com": Outlet("iHeartRadio", ("iheartradio", "iheart"), aggregator=True),
    "aol.com": Outlet("AOL", ("aol",), aggregator=True),
    # -- US / UK outlets of US_NEWS_DOMAINS not named above (2026-11-17)
    "washingtonpost.com": Outlet("The Washington Post", ("the washington post", "washington post")),
    "bbc.co.uk": Outlet("BBC", ("bbc", "bbc news")),
    "theguardian.com": Outlet("The Guardian", ("the guardian", "guardian")),
    "foxbusiness.com": Outlet("Fox Business", ("fox business", "foxbusiness")),
    "foxnews.com": Outlet("Fox News", ("fox news",)),
    "investors.com": Outlet("Investor's Business Daily", ("investor's business daily", "investors business daily",
                                                          "ibd")),
    "axios.com": Outlet("Axios", ("axios",)),
    "latimes.com": Outlet("Los Angeles Times", ("los angeles times", "la times")),
    "npr.org": Outlet("NPR", ("npr",)),
    "cbsnews.com": Outlet("CBS News", ("cbs news",)),
    "nbcnews.com": Outlet("NBC News", ("nbc news",)),
    "abcnews.com": Outlet("ABC News", ("abc news",)),  # GDELT's English files: only this address (2026-11-17)
    "abcnews.go.com": Outlet("ABC News", ("abc news",)),
    "usatoday.com": Outlet("USA Today", ("usa today",)),
    "economist.com": Outlet("The Economist", ("the economist", "economist")),
    "politico.com": Outlet("Politico", ("politico",)),
    "time.com": Outlet("TIME", ("time",)),
    "newsweek.com": Outlet("Newsweek", ("newsweek",)),
    "wired.com": Outlet("WIRED", ("wired",)),
    "arstechnica.com": Outlet("Ars Technica", ("ars technica",)),
    "engadget.com": Outlet("Engadget", ("engadget",)),
    "cnet.com": Outlet("CNET", ("cnet",)),
    "zdnet.com": Outlet("ZDNET", ("zdnet",)),
    "morningstar.com": Outlet("Morningstar", ("morningstar",)),
    "kiplinger.com": Outlet("Kiplinger", ("kiplinger",)),
    "marketplace.org": Outlet("Marketplace", ("marketplace",)),
    "bostonglobe.com": Outlet("The Boston Globe", ("the boston globe", "boston globe")),
    "chicagotribune.com": Outlet("Chicago Tribune", ("chicago tribune",)),
    "independent.co.uk": Outlet("The Independent", ("the independent", "independent")),
    "standard.co.uk": Outlet("Evening Standard", ("evening standard", "the standard")),
    "cityam.com": Outlet("City A.M.", ("city a.m.", "city am", "cityam")),
    "telegraph.co.uk": Outlet("The Telegraph", ("the telegraph", "telegraph")),
    "thetimes.com": Outlet("The Times", ("the times",)),
    "thetimes.co.uk": Outlet("The Times", ("the times",)),
    "sky.com": Outlet("Sky News", ("sky news",)),
    "semafor.com": Outlet("Semafor", ("semafor",)),
}


# Taiwanese outlets outside the .tw top-level domain (a .tw host is Taiwanese by itself). GDELT's bulk files carry no
# source country, so this list stands in for the DOC API's ``sourcecountry:taiwan`` (which, by GDELT's 2018 domain
# list, also files cnyes.com and moneydj.com under China and storm.mg under Madagascar).
TAIWAN_DOMAINS = frozenset({
    "udn.com", "chinatimes.com", "ettoday.net", "setn.com", "storm.mg", "yam.com", "cnyes.com", "moneydj.com",
    "nownews.com", "mirrormedia.mg", "upmedia.mg", "thenewslens.com", "ctwant.com", "ctinews.com", "taisounds.com",
    "taipeitimes.com", "digitimes.com",
    "blocktempo.com",  # 動區動趨 (LangSearch recommendation 2026-11-17 §3.2)
})
# Reputable business news (產品負責人 2026-11-16, memo §2 item 5): preferred, never required — a story found in one
# of them wins over a copy elsewhere, and within a day they come first in the order the server returns.
# Taiwan: 經濟日報、工商時報、MoneyDJ、鉅亨、中央社（及 Focus Taiwan）、自由財經.
# US: Reuters, CNBC and the other wire services and business papers.
REPUTABLE_DOMAINS = frozenset({
    "money.udn.com", "ctee.com.tw", "moneydj.com", "cnyes.com", "cna.com.tw", "focustaiwan.tw", "ec.ltn.com.tw",
    "reuters.com", "cnbc.com", "bloomberg.com", "wsj.com", "ft.com", "apnews.com", "marketwatch.com", "barrons.com",
})
# Not news (memo 2026-11-16 §1, measured): quote and rating pages, forums and blogs, and AI-written "news" (CMoney's
# aigc-note Q&A and cmnews AI articles, Fugle's AI 法說會 notes and /ai pages). Never stored or shown as a headline,
# blocked in the AI news search, and the base of the chat's and the 法人觀點 card's web_search blocklist
# (``ai.tools.CHAT_BLOCKED_DOMAINS``: one list, 2026-11-16 review). A host matches with its subdomains;
# NOT_NEWS_PATHS only for path prefixes on one host.
NOT_NEWS_DOMAINS = (
    "cmoney.tw", "cmnews.com.tw", "goodinfo.tw", "wantgoo.com", "histock.tw", "istock.tw", "winvest.tw",
    "poorstock.com", "finlab.tw", "finlab.finance", "findbillion.com", "uc913.com", "nstock.tw", "myth-capital.com",
    "toalpha.tw", "fugle.tw", "treelazy.com", "stock.wearn.com", "vocus.cc", "gate.com", "finance.biggo.com",
    "finance.biggo.com.tw", "stock.pchome.com.tw", "agdstock.club", "fastbull.com", "stockopedia.com",
    "gurufocus.com", "ptt.cc", "dcard.tw", "mobile01.com", "pixnet.net", "blog.udn.com", "city.udn.com",
    "tradingview.com", "stockanalysis.com", "marketbeat.com", "tipranks.com",
)
NOT_NEWS_PATHS: dict[str, tuple[str, ...]] = {
    "pchome.megatime.com.tw": ("/stock", "/m/stock"),  # quote pages; its /news pages are real reprints
    "tw.stock.yahoo.com": ("/quote",),
    "money-link.com.tw": ("/twstock",),  # quote and per-stock list pages; /realtimenews/ are articles
    "ww2.money-link.com.tw": ("/twstock",),
}
# The same by a path pattern: Morningstar's quote and analysis pages (``/stocks/xnys/tu/quote``, 「TU Stock Price
# (XNYS) & Analyst Rating」, measured 2026-11-17 in GDELT's English files); its articles (``/stocks/7-new-4-star-…``,
# ``/news/…``) stay.
# ABC News' shopping pages sit under its Good Morning America section (``/GMA/Shop/gma-deals-steals-…``, measured
# 2026-11-17); GMA's other pages (``/GMA/Culture/…``) are stories.
_ABC_SHOP = re.compile(r"^/gma/(?:shop|deals)(?:/|$)", re.IGNORECASE)
NOT_NEWS_PATTERNS: dict[str, re.Pattern[str]] = {
    "morningstar.com": re.compile(r"^/(?:stocks|funds|etfs|cefs|indexes|bonds)/x[a-z]{3}/", re.IGNORECASE),
    "abcnews.com": _ABC_SHOP,
    "abcnews.go.com": _ABC_SHOP,
}

# US and UK news outlets (產品負責人 2026-11-17, option A): the only sites whose headlines in GDELT's English bulk files
# are matched to US stocks and to the US market's headlines — the bulk files carry no source country, so this list
# stands in for the DOC API's ``(sourcecountry:US OR sourcecountry:UK) sourcelang:english``, much stricter (no local TV
# sites, no syndication networks, no auto-written stock pages such as the MarketBeat network's). A host matches with its
# subdomains (``finance.yahoo.com`` only Yahoo's finance site, not Yahoo's other editions). It holds every US outlet of
# REPUTABLE_DOMAINS; none of NOT_NEWS_DOMAINS. Measured 2026-11-17 (48 English files, 12 h): Reuters, AP, MarketWatch,
# WSJ, Barron's, Bloomberg, FT, The Washington Post, Axios, USA Today, Politico, The Economist, Sky News, The Telegraph
# and Semafor are not in GDELT's English files at all, CNN only with its press room and Forbes only with its paid
# Councils posts (kept in the list in case GDELT reads them again); CNBC, The New York Times, BBC, The Guardian, CBS,
# NBC, ABC News (as ``abcnews.com``, 46 rows; no ``abcnews.go.com``; its ``/Business/wireStory/`` pages carry AP's
# business wire), Los Angeles Times, Business Insider, Fortune, Investor's Business Daily, Morningstar (which carries
# MarketWatch and Dow Jones Newswires), The Verge and TechCrunch are (``CONTRACT_NOTES.md``, 2026-11-17).
US_NEWS_DOMAINS = frozenset({
    # wire services, business papers and business TV
    "reuters.com", "apnews.com", "bloomberg.com", "wsj.com", "barrons.com", "marketwatch.com", "ft.com", "cnbc.com",
    "foxbusiness.com", "investors.com", "morningstar.com", "kiplinger.com", "fortune.com", "businessinsider.com",
    "forbes.com", "finance.yahoo.com", "economist.com", "marketplace.org", "cityam.com", "axios.com", "semafor.com",
    # national papers, networks and magazines
    "nytimes.com", "washingtonpost.com", "latimes.com", "usatoday.com", "bostonglobe.com", "chicagotribune.com",
    "cnn.com", "cbsnews.com", "nbcnews.com", "abcnews.com", "abcnews.go.com", "npr.org", "foxnews.com", "politico.com",
    "time.com", "newsweek.com", "bbc.com", "bbc.co.uk", "theguardian.com", "independent.co.uk", "standard.co.uk",
    "telegraph.co.uk", "thetimes.com", "thetimes.co.uk", "news.sky.com",
    # technology
    "techcrunch.com", "theverge.com", "wired.com", "arstechnica.com", "engadget.com", "cnet.com", "zdnet.com",
})
# Of those, the business and technology outlets: every story there is business context, so an everyday-word company
# name (Target, Visa) needs no other finance cue in a sentence-case title (:mod:`forliosa.news.us_match`).
US_BUSINESS_DOMAINS = frozenset({
    "reuters.com", "bloomberg.com", "wsj.com", "barrons.com", "marketwatch.com", "ft.com", "cnbc.com",
    "foxbusiness.com", "investors.com", "morningstar.com", "kiplinger.com", "fortune.com", "businessinsider.com",
    "forbes.com", "finance.yahoo.com", "economist.com", "marketplace.org", "cityam.com",
    "techcrunch.com", "theverge.com", "wired.com", "arstechnica.com", "engadget.com", "cnet.com", "zdnet.com",
})
# A business section of a general outlet (``latimes.com/business/…``, ``theguardian.com/technology/…``).
_BUSINESS_SECTION = re.compile(r"^/(?:[a-z]{2}/)?(?:business|markets?|money|moneywatch|finance|economy|investing|"
                               r"technology|tech|companies|stocks|earnings)(?:/|$)", re.IGNORECASE)
# Not news on those sites (measured 2026-11-17), by the URL's first path segment: shopping and reviews (Wirecutter, NBC
# Select, CNBC Select, CNN Underscored, The Guardian's Filter), paid posts (Forbes Councils, NYT paid posts, CNET paid
# content, Business Insider's ``/sc/``, The Guardian's partner pages, the Los Angeles Times' B2B and studio pages),
# recipes, audio and video players, press offices, events, weather, sport and betting.
US_NOT_NEWS_HOSTS = ("cooking.nytimes.com", "cnnpressroom.blogs.cnn.com")
_US_NOT_NEWS_SECTIONS = frozenset({
    "wirecutter", "paidpost", "recipes", "recipe", "select", "shopping", "deals", "coupons", "councils",
    "cnn-underscored", "underscored", "reviews", "sponsored", "partner", "brandvoice", "sounds", "iplayer", "sport",
    "athletic", "food", "games", "crosswords", "puzzles", "horoscopes", "paid-content", "thefilter", "thefilter-us",
    "quince", "worth-going-further", "b2b", "doctors-scientists", "sc", "mediacentre", "events", "app", "weather",
    "outkick", "outkick-betting", "outkick-culture",
})


def host_of(url: str) -> str:
    """``https://www.cna.com.tw:443/news/…`` -> ``cna.com.tw`` (lower case, no ``www.``, no port)."""
    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.").rstrip(".")


def on_domain(host: str, domain: str) -> bool:
    """``ec.ltn.com.tw`` is on ``ltn.com.tw``; ``udn.com.evil`` is not on ``udn.com``."""
    domain = domain.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def outlet_entry(host: str) -> tuple[str, Outlet] | None:
    """The longest listed domain the host is on."""
    best: tuple[str, Outlet] | None = None
    for domain, outlet in OUTLETS.items():
        if on_domain(host, domain) and (best is None or len(domain) > len(best[0])):
            best = (domain, outlet)
    return best


def outlet_name(url: str, domain_hint: str | None = None) -> str:
    """The outlet's Chinese (or usual) name; an unknown site is shown as its domain."""
    host = host_of(url) or (domain_hint or "").lower().removeprefix("www.")
    entry = outlet_entry(host)
    if entry is not None:
        return entry[1].name
    return (domain_hint or host or "").lower().removeprefix("www.")[:100] or "未知媒體"


def is_aggregator(url: str) -> bool:
    entry = outlet_entry(host_of(url))
    return bool(entry and entry[1].aggregator)


def _host(url_or_host: str) -> str:
    return host_of(url_or_host) if "://" in url_or_host else url_or_host.lower().removeprefix("www.").rstrip(".")


def is_taiwan_outlet(url_or_host: str) -> bool:
    """A Taiwanese news site: a ``.tw`` host, one of :data:`TAIWAN_DOMAINS`, or Yahoo's Taiwan edition."""
    host = _host(url_or_host)
    if not host:
        return False
    if host.endswith(".tw"):
        return True
    if host.startswith("tw.") and on_domain(host, "yahoo.com"):
        return True
    return any(on_domain(host, d) for d in TAIWAN_DOMAINS)


def _first_segment(url: str) -> str:
    try:
        path = urlsplit(url.strip()).path or "/"
    except ValueError:
        return ""
    return path.lstrip("/").split("/", 1)[0].lower()


def is_us_outlet(url: str) -> bool:
    """A page of a US or UK news outlet (:data:`US_NEWS_DOMAINS`, by the URL's host) that is news: not a shopping,
    paid, recipe, audio or sport page (``_US_NOT_NEWS_SECTIONS``, ``US_NOT_NEWS_HOSTS``) nor a quote page
    (:func:`is_not_news`)."""
    host = _host(url)
    if not host or not any(on_domain(host, d) for d in US_NEWS_DOMAINS):
        return False
    if any(on_domain(host, h) for h in US_NOT_NEWS_HOSTS) or is_not_news(url):
        return False
    return "://" not in url or _first_segment(url) not in _US_NOT_NEWS_SECTIONS


def us_outlet_site(domain: str) -> bool:
    """GDELT's site name (``SourceCommonName``) may hold a page of :data:`US_NEWS_DOMAINS`: the outlet's domain, a
    subdomain, or the site it is part of (``yahoo.com`` for ``finance.yahoo.com``, ``go.com`` for ``abcnews.go.com``).
    A cheap first filter; :func:`is_us_outlet` then checks the page's own URL."""
    host = _host(domain)
    return bool(host) and any(on_domain(host, d) or on_domain(d, host) for d in US_NEWS_DOMAINS)


def is_us_business_page(url: str) -> bool:
    """A page of a business or technology outlet (:data:`US_BUSINESS_DOMAINS`) or in a business / markets / technology
    section of another US outlet."""
    host = _host(url)
    if host and any(on_domain(host, d) for d in US_BUSINESS_DOMAINS):
        return True
    try:
        path = urlsplit(url.strip()).path or "/"
    except ValueError:
        return False
    return bool(_BUSINESS_SECTION.match(path))


def is_reputable(url_or_host: str) -> bool:
    host = _host(url_or_host)
    return bool(host) and any(on_domain(host, d) for d in REPUTABLE_DOMAINS)


def is_not_news(url: str) -> bool:
    """A quote / rating page, a forum or blog, or an AI-written page (:data:`NOT_NEWS_DOMAINS`)."""
    host = _host(url)
    if not host:
        return False
    if any(on_domain(host, d) for d in NOT_NEWS_DOMAINS):
        return True
    prefixes = NOT_NEWS_PATHS.get(host)
    pattern = NOT_NEWS_PATTERNS.get(host)
    if (prefixes or pattern) and "://" in url:
        try:
            path = (urlsplit(url.strip()).path or "/").lower()
        except ValueError:
            return False
        return bool(prefixes and path.startswith(prefixes)) or bool(pattern and pattern.match(path))
    return False


def _squash(text: str) -> str:
    return re.sub(r"[\s.·・_\-]+", "", text).casefold()


def outlet_aliases(url: str) -> list[str]:
    """Spellings that mean "this outlet" in a title suffix (squashed: no spaces or dots, case-folded)."""
    host = host_of(url)
    entry = outlet_entry(host)
    names: list[str] = []
    if entry is not None:
        names += [entry[1].name, *entry[1].aliases]
    # The site's own label: setn.com -> "setn", news.ltn.com.tw -> "ltn" (3+ characters).
    labels = [p for p in host.split(".") if p not in ("www", "news", "com", "tw", "net", "org", "co", "mg")]
    names += [p for p in labels if len(p) >= 3]
    if host:
        names.append(host)
    return list(dict.fromkeys(s for s in (_squash(n) for n in names) if s))
