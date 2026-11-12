"""Headline normalisation, relevance, de-duplication and the takedown blocklist check (pure functions).

What GDELT does to Chinese headlines (live responses of 2026-11-12, ``tests/news/fixtures``): spaces around
full-width punctuation (「台積電 ： AI需求」「 【 台股盤中 】 」「4 . 6萬」「8 ％！」), and in some titles a space
between every character. A single space between two phrases is a real headline separator in Taiwanese media
(「…說明會 攜手培育…」), so spaces between ideographs are only removed when the whole title is spaced character
by character. The site's ``<title>`` suffix is kept by GDELT (「| 財經 | 三立新聞網 SETN . COM」「- 財經」); a tail
that only repeats the outlet or names a generic section (財經, 證券, 生活…) is removed, column names
(「| 台股雜談」) stay, as on Google Finance.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from forliosa.news.outlets import host_of, is_aggregator, on_domain, outlet_aliases


def _ranges(*pairs: tuple[int, int]) -> str:
    """A regex character-class body for code-point ranges (kept as numbers so the source stays ASCII)."""
    return "".join(chr(a) if a == b else f"{chr(a)}-{chr(b)}" for a, b in pairs)


# Ideographs plus the CJK symbol / full-width punctuation blocks.
_HAN = _ranges((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
_CJK_PUNCT = _ranges((0x3000, 0x303F), (0xFF01, 0xFF0F), (0xFF1A, 0xFF20), (0xFF3B, 0xFF40), (0xFF5B, 0xFF65),
                     (0x2018, 0x201F), (0x2026, 0x2026), (0x00B7, 0x00B7))
_HAS_HAN = re.compile(f"[{_HAN}]")
_SPACE_AROUND_PUNCT = re.compile(f"\\s+(?=[{_CJK_PUNCT}])|(?<=[{_CJK_PUNCT}])\\s+")
_SPACE_BETWEEN_HAN = re.compile(f"(?<=[{_HAN}])\\s(?=[{_HAN}])")
_SPACED_DOT = re.compile(r"(?<=[0-9])\s+([.:/,])\s*(?=[0-9])|(?<=[0-9])\s+(?=%)")  # 4 . 6 -> 4.6, 10 : 30, 1 , 165
_SPACE_BEFORE_ASCII_PUNCT = re.compile(r"(?<=\S)\s+([,.;:!?%)\]])(?=\s|$)")
_SPACE_AFTER_ASCII_OPEN = re.compile(r"([(\[])\s+")
_PIPE_SPLIT = re.compile("\\s*[|" + chr(0xFF5C) + "]\\s*")  # | and the full-width ｜
_DASH_SPLIT = re.compile("\\s+[-" + chr(0x2013) + chr(0x2014) + "]\\s+")  # - – — with spaces around
# Generic section names sites append to their <title> (「| 財經」「- 生活」). Column names are not in this list.
SECTION_WORDS = frozenset({
    "財經", "證券", "股市", "產經", "金融", "生活", "國際", "政治", "社會", "要聞", "產業", "科技", "娛樂", "體育",
    "地方", "兩岸", "全球", "焦點", "即時", "即時新聞", "新聞", "頭條", "理財", "房產", "健康", "綜合", "評論",
    "觀點", "論壇", "經濟", "財經新聞", "國際新聞", "台股", "美股", "基金", "期貨", "匯市", "科技新聞", "汽車",
    "旅遊", "消費", "市場", "商業", "business", "markets", "technology", "tech", "finance", "news", "world",
    "economy", "stocks", "investing",
})
MAX_TITLE_CHARS = 300
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|ocid$|from$|ref$|cid$|share$)", re.IGNORECASE)


def collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(chr(0x3000), " ")).strip()  # ideographic space too


def tidy_spacing(title: str) -> str:
    """Remove the spaces GDELT inserts around punctuation (「台積電 ： AI」「$17 . 7 Billion」「exit , says」
    「( NVDA )」) and, in Chinese headlines spaced character by character, between characters. A dash between
    spaces stays (「mid - life」 cannot be told from a real dash)."""
    t = collapse_spaces(title)
    t = _SPACED_DOT.sub(lambda m: m.group(1) or "", t)
    t = _SPACE_BEFORE_ASCII_PUNCT.sub(r"\1", t)
    t = _SPACE_AFTER_ASCII_OPEN.sub(r"\1", t)
    if not _HAS_HAN.search(t):
        return t.strip()
    t = _SPACE_AROUND_PUNCT.sub("", t)
    han = len(re.findall(f"[{_HAN}]", t))
    spaced = len(_SPACE_BETWEEN_HAN.findall(t))
    if han >= 4 and spaced >= 0.5 * (han - 1):  # spaced character by character
        t = _SPACE_BETWEEN_HAN.sub("", t)
    return t.strip()


def _squash(text: str) -> str:
    return re.sub(r"[\s.·・_\-]+", "", text).casefold()


def _is_outlet_tail(tail: str, aliases: Sequence[str], outlet: str | None) -> bool:
    t = _squash(tail)
    if not t:
        return True
    if t in SECTION_WORDS:
        return True
    names = [*aliases, *([_squash(outlet)] if outlet else [])]
    for a in names:
        if not a:
            continue
        if t == a or (len(a) >= (4 if a.isascii() else 2) and a in t) or (len(t) >= 3 and t in a):
            return True
    return False


def strip_suffixes(title: str, url: str = "", outlet: str | None = None, min_head: int = 4) -> str:
    """Remove trailing 「| 財經」「- 自由財經」「| ETtoday財經雲」 parts that repeat the outlet or name a generic
    section, right to left, while the headline that stays has at least ``min_head`` characters."""
    aliases = outlet_aliases(url) if url else []
    t = title.strip()
    for _ in range(4):
        best: tuple[int, int] | None = None
        for splitter in (_PIPE_SPLIT, _DASH_SPLIT):
            for m in splitter.finditer(t):
                if best is None or m.start() > best[0]:
                    best = (m.start(), m.end())
        if best is None:
            break
        head, tail = t[:best[0]].rstrip(), t[best[1]:].strip()
        if len(head) < min_head or not _is_outlet_tail(tail, aliases, outlet):
            break
        t = head
    return t


def clean_title(title: str, url: str = "", outlet: str | None = None) -> str:
    """GDELT spacing removed, outlet / section suffixes removed, whitespace collapsed, at most 300 characters."""
    # Suffixes first: GDELT's 「？ - 生活」 loses the space before the dash once the spacing is tidied.
    t = strip_suffixes(collapse_spaces(title), url, outlet)
    t = strip_suffixes(tidy_spacing(t), url, outlet)
    return collapse_spaces(t)[:MAX_TITLE_CHARS]


# -- URLs ---------------------------------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """For de-duplication: https, no ``www.``, no default port, no fragment, no tracking parameters, no trailing
    slash, percent-encoding decoded."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (parts.hostname or "").lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _TRACKING_PARAMS.match(k)])
    return urlunsplit(("https", host, unquote(parts.path).rstrip("/"), unquote(query), ""))


def clean_url(url: str) -> str | None:
    """The link we store and show: http(s) only, default ``:443`` / ``:80`` port removed. ``None`` otherwise."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    netloc = parts.netloc
    if (parts.scheme, parts.port) in (("https", 443), ("http", 80)):
        netloc = netloc.rsplit(":", 1)[0]
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))


def url_key(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


# -- relevance ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Terms:
    """What makes a headline about this company: its Chinese short name, its code and its English short name
    (台積電 / 2330 / TSMC; US: NVIDIA / NVDA / 輝達)."""

    names: tuple[str, ...]  # matched as substrings (Chinese names) or whole words (ASCII)
    codes: tuple[str, ...]  # matched with digit / letter boundaries

    def all(self) -> list[str]:
        return [*self.names, *self.codes]


def make_terms(name: str, code: str, english: Iterable[str] = (), extra_names: Iterable[str] = ()) -> Terms:
    names: list[str] = []
    for n in (name, *english, *extra_names):
        n = collapse_spaces(n or "")
        if not n:
            continue
        if n.isascii() and len(n) < 3:  # 「JF」 would match too much
            continue
        if not n.isascii() and len(n) < 2:
            continue
        names.append(n)
    codes = [c for c in (code or "",) if c]
    return Terms(tuple(dict.fromkeys(names)), tuple(dict.fromkeys(codes)))


_NUMBER_UNITS = "(?:\\s*(?:元|點|億|萬|張|股|倍|年|月|日|人|家|%|" + chr(0xFF05) + "))"


def is_relevant(title: str, terms: Terms) -> bool:
    """The headline (after ``clean_title``) names the company, its code or its English short name."""
    text = title.casefold()
    for n in terms.names:
        t = n.casefold()
        if n.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text):
                return True
        elif t in text:
            return True
    for c in terms.codes:
        # 2330 in 「台積電(2330)」「2330.TW」, not in 「23301」「2330點」「2330元」「$2330」「2026年」
        if re.search(rf"(?<![A-Za-z0-9.$]){re.escape(c)}(?![0-9A-Za-z]|{_NUMBER_UNITS})", title):
            return True
    return False


# -- de-duplication -----------------------------------------------------------------------------------------
_TITLE_NOISE = re.compile(r"[\W_]+", re.UNICODE)
SIMILAR_TITLE_RATIO = 0.88


def title_key(title: str) -> str:
    return _TITLE_NOISE.sub("", title).casefold()


def similar_titles(a: str, b: str) -> bool:
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    short, long_ = sorted((ka, kb), key=len)
    if len(short) >= 12 and short in long_ and len(short) >= 0.8 * len(long_):
        return True
    return difflib.SequenceMatcher(None, ka, kb, autojunk=False).ratio() >= SIMILAR_TITLE_RATIO


@dataclass(frozen=True)
class Headline:
    """One normalised media headline (what is stored and shown)."""

    title: str
    url: str
    outlet: str
    domain: str
    published_at: datetime
    source: str  # gdelt | ai_search | searxng | yahoo_rss | finmind
    date_only: bool = False


def dedupe(items: Iterable[Headline]) -> list[Headline]:
    """One headline per story: the same URL (normalised) or a near-identical title. The original outlet wins over
    an aggregator copy (Yahoo, LINE TODAY, MSN), then the earliest one. Returned newest first."""
    ordered = sorted(items, key=lambda h: (is_aggregator(h.url), h.published_at))
    kept: list[Headline] = []
    seen_urls: set[str] = set()
    for h in ordered:
        key = normalize_url(h.url)
        if key in seen_urls or any(similar_titles(h.title, k.title) for k in kept):
            seen_urls.add(key)
            continue
        seen_urls.add(key)
        kept.append(h)
    kept.sort(key=lambda h: h.published_at, reverse=True)
    return kept


# -- takedown blocklist -------------------------------------------------------------------------------------
def normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    if "://" in d:
        d = host_of(d)
    return d.removeprefix("www.").strip(".").split("/", 1)[0]


def is_blocked(url_or_host: str, blocked: Iterable[str]) -> bool:
    host = host_of(url_or_host) if "://" in url_or_host else normalize_domain(url_or_host)
    return any(on_domain(host, b) for b in blocked if b)
