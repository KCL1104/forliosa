"""Domain -> outlet name (媒體名稱) for the 「新聞報導」 list.

A host matches its longest listed suffix (``money.udn.com`` 經濟日報 before ``udn.com`` 聯合新聞網); an unknown
host is shown as its domain without ``www.``. ``aliases`` are the extra spellings an outlet uses in its own
``<title>`` suffix (「| 三立新聞網 SETN.COM」「| ETtoday財經雲」), so ``normalize.strip_suffixes`` can remove a tail
that only repeats the outlet.
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
}


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
