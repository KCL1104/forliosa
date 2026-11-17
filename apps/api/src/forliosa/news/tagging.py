"""Tag stored headlines with themes, sectors and related stocks.

產品負責人 2026-11-17: 「入庫時用 Haiku 貼主題與類股標籤」.

Why
---
The AI chat (``search_news``) and the market-first reports (盤前／盤後／週報, comparing sectors and themes) need to find
and group our own headlines by topic. Headlines are short and the vocabulary is fixed, so a cheap model call per batch
does it; no embeddings or retrieval index.

What is tagged
--------------
Every URL in ``news_articles`` (once per ``url_key``: a story stored for three symbols is tagged once), published in the
last ``NEWS_TAGGING_DAYS``, oldest first. Hidden rows are not sent: a blocked domain, a page that is not news, a robot
flash, a source the data policy does not serve (:func:`forliosa.news.service.shown`) — they are marked ``skipped``.
Only the headline, its outlet and the stocks it is stored under go to the model: we never store or send article text.

The job (worker ``news_tagging``, every ``NEWS_TAGGING_MINUTES``; ``python -m forliosa.news.tagging run``)
--------------------------------------------------------------------------------------------------------------
* Up to ``NEWS_TAGGING_MAX_BATCHES`` requests of up to ``NEWS_TAGGING_BATCH_SIZE`` (50) headlines, each answered in a
  JSON schema whose enums are the vocabulary of :mod:`forliosa.news.taxonomy` (structured outputs). The model is
  ``AI_MODEL_NEWS_TAGGING`` (default ``AI_MODEL``: Claude Haiku 5.5) at effort ``low``.
* Every request has a fixed cost (the ~5.9K-token system prompt and the model's thinking), so a trickle is batched:
  with fewer than ``NEWS_TAGGING_MIN_BATCH`` (20) headlines waiting, nothing is sent until the oldest of them was
  stored ``NEWS_TAGGING_MAX_WAIT_MINUTES`` (30) ago. The system prompt is cached for an hour (``ttl: 1h``: requests
  come up to 30 minutes apart, past the 5-minute cache) and every request goes to the key slot of the previous one
  while that slot is usable (caches are per workspace).
* The answer is checked again: unknown themes and sectors are dropped, at most 3 themes, 3 sectors and 5 related
  stocks; a sector of :data:`taxonomy.THEMES_OF_SECTOR` adds its industry theme (金融股 -> 金融). The prompt names
  each stored stock with its sector (Taiwan 產業別 from the company profile, a US company's :func:`taxonomy.us_sector`);
  the model decides whether the story is about it (ingestion matches names, so 「大洋洲」 can land under 大洋): the
  2026-11-17 live test showed that adding the stored stocks' sectors without the model mislabels those. A related
  stock must resolve to a catalog symbol whose name agrees with the name the model gave (a made-up or mismatched code
  is dropped; a name that is exactly another stock's name wins over a code whose stock only shares part of it:
  南亞科 with 1303 is 2408) and is never one of the symbols the headline is stored under.
* An unusable answer (refusal, cut off, not the schema) is about the headlines, not the request: a batch of several is
  split — its headlines go again at once, in batches of at most half as many (``status = "split"``,
  ``batch_limit``) — until the headline that causes it is sent alone; only a headline sent alone counts an attempt
  (asked again after ``RETRY_AFTER`` × attempts, at most ``MAX_ATTEMPTS`` times; a refusal of one headline alone gives
  up at once: the same request would be refused again). One bad headline never takes its batch down with it.
* An API error that no headline causes — a wrong model (404), a parameter or schema the model does not take (400) —
  stops the run without counting an attempt, like a busy, rate-limited or unreachable key; it is logged as a WARNING
  at most once an hour. ``python -m forliosa.news.tagging retry-failed`` gives every headline that failed its attempts
  back. Nothing here touches ingestion: a failure only leaves headlines untagged.
* Budget: the UTC month's cost of ``feature = "news_tagging"`` (``ai_usage``, nobody's quota). Once it reaches
  ``NEWS_TAGGING_MONTHLY_BUDGET_USD`` (US$3) the job stops until the 1st and says so in the log once.
* Each run also deletes tags whose headline is gone (30-day retention, takedowns).

Cost, measured 2026-11-17 (Claude Haiku 5.5, effort low, live headlines): a full request of about 50 headlines
US$0.003–0.006 (US$0.006–0.012 per 100), most of it output (adaptive thinking, 5K–9K tokens); small requests cost more
per headline (5–7 headlines: US$0.0008–0.0015). Turning thinking off saved about a third but mislabelled clearly more.
Monthly estimate and the numbers behind it: apps/api/CONTRACT_NOTES.md 「2026-11-17 新聞標籤」.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import anthropic
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.keypool import KeyPool, KeysBusy, NoKeyAvailable, get_key_pool, is_failover_error
from forliosa.ai.pricing import CallUsage
from forliosa.config import Settings, get_settings
from forliosa.marketdata.base import InstrumentInfo, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import AiUsage, CompanyProfile, NewsArticle, NewsTag, NewsTagState, SecCompany, SecTicker
from forliosa.news import taxonomy as tx
from forliosa.news.normalize import Headline
from forliosa.timeutil import now_utc

log = logging.getLogger(__name__)

FEATURE = "news_tagging"
EFFORT = "low"
MAX_TOKENS = 16000  # 50 headlines need about 3K output tokens; the rest is room for thinking
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=15)
# A request of 50 headlines measured US$0.004–0.006 (at most about US$0.009 with all 16K output tokens): one starts only
# while this much of the month's budget is left.
RESERVE_USD = Decimal("0.01")
MAX_TITLE_CHARS = 200
CACHE_CONTROL = {"type": "ephemeral", "ttl": "1h"}  # requests come up to NEWS_TAGGING_MAX_WAIT_MINUTES apart
WARN_EVERY = timedelta(hours=1)  # a request-level API error is logged at most this often
MARKET_KEYS = {"^US": "美股大盤"}  # news_articles.symbol values that are not stocks (news.service.US_MARKET_KEY)

SYSTEM = """你替 Forliosa 的新聞標題貼標籤。Forliosa 是以台股為主的投資帳本，標籤用來把新聞依主題、類股、相關股票分組與搜尋。你只看得到標題、媒體和這則新聞歸在哪幾檔股票底下（stocks），沒有內文，所以只依標題判斷，不要猜標題沒寫的事。

stocks 是程式依公司名稱或代號比對出來的，可能比錯（例如「大洋洲」被當成「大洋」、「2027年」被當成代號 2027）。以標題實際在講什麼為準。

## 每一則要回的
- id：照抄。
- themes：0 到 3 個主題，只能從下面的主題表選，最貼切的放前面。標題主要在講的才選，順帶提到的不選；照每個主題後面寫的範圍判斷，沒把握就少選。產業類的主題（AI 伺服器、金融、航運…）和事件類的主題（財報／法說、人事、個股異動…）可以一起選。
- sectors：0 到 3 個類股，只能從下面的台股產業別與美股類股選。講個別公司的新聞，選那家公司的類股：stocks 裡的公司括號寫著它的類股（台灣公司是台股產業別，美國公司是美股類股），照用；不在 stocks 裡的美國公司（例如 United Airlines）照下面美股類股的說明選，不選台股產業別。講一整個產業的新聞選那個產業。只講大盤、總經或政策、沒有特定產業的新聞不選。stocks 比錯、和標題無關的公司，不選它的類股。
- companies：標題點名、而且是台股或美股上市櫃公司的其他公司，最多 5 家，不含 stocks 裡的公司。
  - name：台灣公司寫股票簡稱（台積電、鴻海、南亞）；美國公司寫英文公司名（Nvidia、Advanced Micro Devices、Alphabet、Micron Technology、United Airlines）。
  - code：台股寫四到六碼的股票代號，美股寫代號（NVDA）。不確定就寫空字串，不要猜。
  - relation：標題裡出現的公司一律是 mentioned（寫的是中文名、英文名、代號或老闆的名字都算，例如「黃仁勳」指 Nvidia）。標題沒出現的公司，只有標題講的是訂單、供貨或競爭時才列：supply_chain＝它的供應商或客戶（例如標題講輝達擴大下單 CoWoS，台積電就是 supply_chain），peer＝做同樣產品的競爭對手（例如美光之於南亞科）。不確定就不列，大多數新聞只有 mentioned 或沒有。
  - 沒上市的公司（OpenAI、SpaceX 上市前）、政府機關、指數、ETF 都不列。

## 哪些算財經新聞
上市櫃公司本身的消息（營運、產品、訂單、事故、當機、勞資、訴訟、人事）、產業、市場、總經都算，照上面的規則貼標籤。政治、選舉、社會、娛樂、體育、生活、健康、旅遊、天氣、教育等新聞，除非標題講到對市場或產業的影響（例如國防預算對軍工股、戰爭對油價），themes、sectors、companies 都給空陣列。

## 主題
{themes}

## 台股產業別（台灣公司）
{tw_sectors}

## 美股類股（美國公司）
{us_sectors}
"""  # noqa: E501


def system_prompt() -> str:
    themes = "\n".join(f"- {t.label}：{t.hint}" for t in tx.THEMES)
    tw = "、".join(t.label for t in tx.TW_SECTORS)
    us = "\n".join(f"- {t.label}：{t.hint}" for t in tx.US_SECTORS)
    return SYSTEM.format(themes=themes, tw_sectors=tw, us_sectors=us)


def output_schema() -> dict[str, Any]:
    """The answer's JSON schema: the themes and sectors are enums of the vocabulary's labels."""
    company = {"type": "object", "properties": {
        "name": {"type": "string"}, "code": {"type": "string"},
        "relation": {"type": "string", "enum": list(tx.RELATIONS)}},
        "required": ["name", "code", "relation"], "additionalProperties": False}
    item = {"type": "object", "properties": {
        "id": {"type": "integer"},
        "themes": {"type": "array", "items": {"type": "string", "enum": [t.label for t in tx.THEMES]}},
        "sectors": {"type": "array", "items": {"type": "string", "enum": [t.label for t in tx.SECTORS]}},
        "companies": {"type": "array", "items": company}},
        "required": ["id", "themes", "sectors", "companies"], "additionalProperties": False}
    return {"type": "object", "properties": {"items": {"type": "array", "items": item}},
            "required": ["items"], "additionalProperties": False}


SYSTEM_PROMPT = system_prompt()
OUTPUT_SCHEMA = output_schema()


# -- what is pending ------------------------------------------------------------------------------------------
@dataclass
class Item:
    """One headline URL to tag: its title and outlet, and the symbols it is stored under."""

    url_key: str
    title: str
    outlet: str
    symbols: tuple[str, ...]  # stored under (market keys such as ^US included)
    stored_at: datetime | None = None  # when the URL was first stored (news_articles.fetched_at)
    fresh: bool = True  # never sent before (no news_tag_state row): only these wait for a fuller batch


@dataclass
class Tags:
    themes: list[str] = field(default_factory=list)  # theme ids
    sectors: list[str] = field(default_factory=list)  # sector ids
    symbols: list[tuple[str, str]] = field(default_factory=list)  # (symbol, relation)

    @property
    def empty(self) -> bool:
        return not (self.themes or self.sectors or self.symbols)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _due(now: datetime):
    """URLs to (re)tag: never looked at, split off a batch that got an unusable answer, failed and due again (fewer
    than MAX_ATTEMPTS tries), or tagged with an older vocabulary."""
    return or_(NewsTagState.url_key.is_(None), NewsTagState.status == "split",
               and_(NewsTagState.status == "failed", NewsTagState.attempts < MAX_ATTEMPTS,
                    or_(NewsTagState.retry_at.is_(None), NewsTagState.retry_at <= now)),
               and_(NewsTagState.status == "done", NewsTagState.taxonomy_version < tx.TAXONOMY_VERSION))


def pending(db: Session, md: MarketData, settings: Settings, now: datetime, limit: int) -> tuple[list[Item], int]:
    """Up to ``limit`` headline URLs to tag, oldest first, from the last ``NEWS_TAGGING_DAYS``, and how many hidden ones
    were found on the way (marked ``skipped`` and committed instead). A ``split`` URL's ``batch_limit`` caps the batch
    it joins (and the batch ends before a URL whose limit it would exceed)."""
    from forliosa.news.service import blocked_domains, shown

    since = now - timedelta(days=settings.news_tagging_days)
    first = func.min(NewsArticle.published_at)
    keys = [k for k, _ in db.execute(
        select(NewsArticle.url_key, first)
        .outerjoin(NewsTagState, NewsTagState.url_key == NewsArticle.url_key)
        .where(NewsArticle.published_at >= since, _due(now))
        .group_by(NewsArticle.url_key).order_by(first, NewsArticle.url_key).limit(limit * 3))]
    if not keys:
        return [], 0
    rows: dict[str, list[NewsArticle]] = {}
    for r in db.scalars(select(NewsArticle).where(NewsArticle.url_key.in_(keys)).order_by(NewsArticle.id)):
        rows.setdefault(r.url_key, []).append(r)
    states = {k: (st, cap) for k, st, cap in db.execute(
        select(NewsTagState.url_key, NewsTagState.status, NewsTagState.batch_limit)
        .where(NewsTagState.url_key.in_(keys)))}
    blocked = blocked_domains(db, settings)
    out: list[Item] = []
    hidden: list[str] = []
    full = False
    for key in keys:
        group = rows.get(key)
        if not group:
            continue
        r = group[0]
        h = Headline(title=r.title, url=r.url, outlet=r.outlet, domain=r.domain, published_at=_aware(r.published_at),
                     source=r.source, date_only=bool(r.date_only))
        if not shown(h, md.policy, blocked):
            hidden.append(key)
            continue
        if full:
            continue
        status, cap = states.get(key, (None, None))
        if status == "split" and cap:
            limit = min(limit, max(1, cap))
        if len(out) >= limit:
            full = True
            continue
        out.append(Item(url_key=key, title=r.title[:MAX_TITLE_CHARS], outlet=r.outlet or r.domain,
                        symbols=tuple(dict.fromkeys(x.symbol for x in group)),
                        stored_at=min((_aware(x.fetched_at) for x in group if x.fetched_at), default=None),
                        fresh=key not in states))
    if hidden:
        mark(db, hidden, "skipped", now)
    return out, len(hidden)


# -- the stocks' own sectors and names -------------------------------------------------------------------------
class Catalog:
    """Catalog lookups for one run (cached): a symbol's sector and the names a related stock may go by."""

    def __init__(self, db: Session, md: MarketData):
        self.db, self.md = db, md
        self._sectors: dict[str, str | None] = {}
        self._names: dict[str, set[str]] = {}
        self._master: Mapping[str, InstrumentInfo] | None = None

    @property
    def master(self) -> Mapping[str, InstrumentInfo]:
        if self._master is None:
            self._master = self.md.master()
        return self._master

    def info(self, symbol: str) -> InstrumentInfo | None:
        return self.master.get(symbol)

    def sector(self, symbol: str) -> str | None:
        """The sector id of a stock: a Taiwan company's 產業別 (company profile, else the catalog's industry name), a
        US company's :func:`taxonomy.us_sector` (the vocabulary's own list, else its SEC SIC code). None for ETFs,
        market keys and unknown symbols."""
        if symbol in self._sectors:
            return self._sectors[symbol]
        out: str | None = None
        info = self.info(symbol)
        if symbol in MARKET_KEYS or (info is not None and info.type == "etf"):
            out = None
        elif market_of_symbol(symbol) == "US":
            cik = self.db.scalar(select(SecTicker.cik).where(SecTicker.ticker == symbol))
            company = self.db.get(SecCompany, cik) if cik is not None else None
            out = tx.us_sector(symbol, (company.profile or {}).get("sic") if company is not None else None)
        else:
            prof = self.db.get(CompanyProfile, symbol)
            out = tx.tw_sector_for_industry(prof.industry_code if prof else None, info.industry if info else None)
        self._sectors[symbol] = out
        return out

    def describe(self, symbol: str) -> str:
        """「2330 台積電（半導體業）」 for the prompt."""
        if symbol in MARKET_KEYS:
            return MARKET_KEYS[symbol]
        info = self.info(symbol)
        text = f"{info.code} {info.name}" if info is not None else symbol
        sector = self.sector(symbol)
        label = tx.sector_label(sector) if sector else None
        return f"{text}（{label}）" if label else text

    def names(self, symbol: str) -> set[str]:
        """Comparable forms of every name the stock goes by: catalog name and aliases, the company profile's short
        and English short names (Taiwan), the SEC title (US)."""
        if symbol in self._names:
            return self._names[symbol]
        info = self.info(symbol)
        raw: list[str] = [info.name, *info.aliases] if info is not None else []
        if market_of_symbol(symbol) != "US":
            prof = self.db.get(CompanyProfile, symbol)
            values = (prof.values or {}) if prof is not None else {}
            raw += [str(values.get(k) or "") for k in ("short_name", "english_short_name", "name")]
        else:
            raw.append(self.db.scalar(select(SecTicker.title).where(SecTicker.ticker == symbol)) or "")
        out = {k for k in (name_key(n) for n in raw if n) if k}
        self._names[symbol] = out
        return out


_NAME_NOISE = re.compile(
    r"股份有限公司|有限公司|控股|集團|公司|-\s*ky\b|\b(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
    r"holdings?|group|the|class\s+[a-c]|common\s+stock|n\.?v|s\.?a|ag|se)\b|[\s.,&'’()（）\-]", re.IGNORECASE)


def name_key(name: str) -> str:
    """A company name without spacing, punctuation and legal suffixes, case-folded: 「Micron Technology, Inc.」 ->
    「microntechnology」, 「台積電」 stays."""
    return _NAME_NOISE.sub("", (name or "").casefold())


def names_agree(given: str, names: Iterable[str]) -> bool:
    """The model's name is one of the stock's names, or one contains the other (台積 / 台積電, Micron / Micron
    Technology). Two characters at least, so a stray letter never matches."""
    g = name_key(given)
    if len(g) < 2:
        return False
    return any(g == n or (len(n) >= 2 and (g in n or n in g)) for n in names)


def _by_exact_name(cat: Catalog, name: str, us_only: bool | None) -> str | None:
    """The one stock (in the US or the Taiwan market when ``us_only`` says which) one of whose names is exactly
    ``name``, else None."""
    key = name_key(name)
    if len(key) < 2:
        return None
    found = {info.symbol for info in cat.md.search(name, limit=10)
             if (us_only is None or (info.market == "US") == us_only)
             and (key in {name_key(n) for n in (info.name, *info.aliases)} or key in cat.names(info.symbol))}
    return found.pop() if len(found) == 1 else None


def _closer_name(cat: Catalog, name: str, sym: str, us_only: bool) -> str | None:
    """Another stock of the code's market that ``name`` fits better than ``sym``, when ``name`` only shares part of
    ``sym``'s names: one named exactly ``name`` (南亞科 vs 1303 南亞), else the one stock with the longest name that is
    part of ``name`` or contains it, longer than ``sym``'s (中華電信 vs 2204 中華: 2412 中華電)."""
    exact = _by_exact_name(cat, name, us_only)
    if exact is not None:
        return exact if exact != sym else None
    key = name_key(name)
    own = max((len(n) for n in cat.names(sym) if len(n) >= 2 and n in key), default=0)
    if not own or own >= len(key):
        return None  # the given name is part of sym's name (台積 / 台積電), not the other way round
    best: dict[str, int] = {}
    for info in cat.md.search(key[:own + 1], limit=20):
        if info.symbol == sym or (info.market == "US") != us_only:
            continue
        fit = max((len(key) if key in n else len(n) for n in cat.names(info.symbol) if n in key or key in n),
                  default=0)
        if fit > own:
            best[info.symbol] = fit
    top = max(best.values(), default=0)
    winners = [s for s, fit in best.items() if fit == top]
    return winners[0] if len(winners) == 1 else None


def resolve_company(cat: Catalog, name: str, code: str) -> str | None:
    """A catalog symbol for a company the model named, or None. The code must resolve to a stock whose names (or code)
    agree with ``name`` — exactly, or by containment when no other stock of that market fits ``name`` better
    (:func:`_closer_name`: 南亞科 with 1303 南亞 is 2408 南亞科, 中華電 with 2204 中華 is 2412: in Taiwan a family's
    companies share the start of their names); otherwise the name must equal exactly one stock's name — in the code's
    market when the code resolved (「聯合」 written for United Airlines with UAL must not become the Taiwan stock
    聯合)."""
    name, code = (name or "").strip(), (code or "").strip()
    if not name:
        return None
    us_only: bool | None = None
    if code:
        sym = cat.md.resolve(code)
        if sym and sym not in MARKET_KEYS:
            info = cat.info(sym)
            us_only = market_of_symbol(sym) == "US"
            names = cat.names(sym) | ({name_key(info.code)} if info else set())
            if name_key(name) in names:
                return sym
            if names_agree(name, names):
                other = _closer_name(cat, name, sym, us_only)
                return other if other is not None else sym
    return _by_exact_name(cat, name, us_only)


# -- the model call --------------------------------------------------------------------------------------------
def user_message(items: Sequence[Item], cat: Catalog) -> str:
    rows = [{"id": i, "title": it.title, "outlet": it.outlet, "stocks": [cat.describe(s) for s in it.symbols]}
            for i, it in enumerate(items, 1)]
    return ("替下面每一則新聞標題貼標籤（stocks 是這則新聞歸在哪幾檔股票底下）：\n[\n"
            + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]")


def request_params(items: Sequence[Item], cat: Catalog, settings: Settings) -> dict[str, Any]:
    return {
        "model": store.model_for(FEATURE, settings), "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": CACHE_CONTROL}],
        "messages": [{"role": "user", "content": user_message(items, cat)}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }


class BadAnswer(Exception):
    """The answer cannot be used (refused, cut off, not the schema)."""

    def __init__(self, reason: str, refused: bool = False):
        super().__init__(reason)
        self.refused = refused


def parse_answer(msg: Any) -> list[dict[str, Any]]:
    """The ``items`` of a structured answer; raises :class:`BadAnswer`."""
    stop = getattr(msg, "stop_reason", None)
    if stop in ("refusal", "max_tokens"):
        raise BadAnswer(f"stop_reason {stop}", refused=stop == "refusal")
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BadAnswer("not JSON") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise BadAnswer("no items")
    return [x for x in items if isinstance(x, dict)]


def _ids(values: Any, lookup: Callable[[str | None], str | None], cap: int) -> list[str]:
    out: list[str] = []
    for v in values if isinstance(values, list) else []:
        i = lookup(v) if isinstance(v, str) else None
        if i and i not in out:
            out.append(i)
    return out[:cap]


def validate(entry: Mapping[str, Any], item: Item, cat: Catalog) -> Tags:
    """One answer entry -> the tags kept (see the module docstring). A sector of :data:`taxonomy.THEMES_OF_SECTOR`
    adds its industry theme (on top of the model's three at most)."""
    themes = _ids(entry.get("themes"), tx.theme_id, tx.MAX_THEMES)
    sectors = _ids(entry.get("sectors"), tx.sector_id, tx.MAX_SECTORS)
    for sector in sectors:
        implied = tx.THEMES_OF_SECTOR.get(sector)
        if implied and implied not in themes:
            themes.append(implied)
    symbols: list[tuple[str, str]] = []
    for c in entry.get("companies") if isinstance(entry.get("companies"), list) else []:
        if not isinstance(c, dict) or len(symbols) >= tx.MAX_SYMBOLS:
            continue
        sym = resolve_company(cat, str(c.get("name") or ""), str(c.get("code") or ""))
        if sym is None or sym in item.symbols or any(sym == s for s, _ in symbols):
            continue
        relation = c.get("relation") if c.get("relation") in tx.RELATIONS else "mentioned"
        symbols.append((sym, str(relation)))
    return Tags(themes=themes, sectors=sectors, symbols=symbols)


# -- storing ---------------------------------------------------------------------------------------------------
def _state(db: Session, key: str) -> NewsTagState:
    st = db.get(NewsTagState, key)
    if st is None:
        st = NewsTagState(url_key=key, status="pending", model="", taxonomy_version=0, attempts=0)
        db.add(st)
    return st


def save(db: Session, item: Item, tags: Tags, model: str, now: datetime) -> None:
    """Replace the URL's tags and mark it done (not committed)."""
    db.execute(delete(NewsTag).where(NewsTag.url_key == item.url_key))
    db.add_all([NewsTag(url_key=item.url_key, kind="theme", value=t) for t in tags.themes]
               + [NewsTag(url_key=item.url_key, kind="sector", value=s) for s in tags.sectors]
               + [NewsTag(url_key=item.url_key, kind="symbol", value=s, relation=r) for s, r in tags.symbols])
    st = _state(db, item.url_key)
    st.status, st.model, st.taxonomy_version = "done", model[:64], tx.TAXONOMY_VERSION
    st.attempts, st.tagged_at, st.retry_at, st.updated_at = (st.attempts or 0) + 1, now, None, now
    st.batch_limit = None


def mark(db: Session, keys: Iterable[str], status: str, now: datetime, *, batch_limit: int | None = None,
         give_up: bool = False) -> None:
    """``skipped`` (hidden), ``split`` (asked again at once in batches of at most ``batch_limit``; no attempt counted)
    or ``failed`` (one more attempt — all of them with ``give_up`` —; asked again after RETRY_AFTER × attempts).
    Committed."""
    for key in keys:
        st = _state(db, key)
        st.status, st.updated_at = status, now
        if status == "split":
            st.batch_limit, st.retry_at = batch_limit, None
        elif status == "failed":
            st.attempts = MAX_ATTEMPTS if give_up else (st.attempts or 0) + 1
            st.retry_at = now + RETRY_AFTER * st.attempts if st.attempts < MAX_ATTEMPTS else None
    db.commit()


def retry_failed(db: Session) -> int:
    """Give every failed URL its attempts back (``retry-failed``: after an outage or a fix). It is asked again at the
    next run, alone if it failed alone. Returns how many."""
    rows = db.scalars(select(NewsTagState).where(NewsTagState.status == "failed")).all()
    for st in rows:
        st.attempts, st.retry_at = 0, None
    db.commit()
    return len(rows)


def purge_orphans(db: Session) -> int:
    """Delete tags and states whose URL is no longer stored (retention, takedowns)."""
    gone_tag = ~select(NewsArticle.id).where(NewsArticle.url_key == NewsTag.url_key).exists()
    gone_state = ~select(NewsArticle.id).where(NewsArticle.url_key == NewsTagState.url_key).exists()
    n = db.execute(delete(NewsTag).where(gone_tag).execution_options(synchronize_session=False)).rowcount or 0
    db.execute(delete(NewsTagState).where(gone_state).execution_options(synchronize_session=False))
    db.commit()
    return n


# -- budget ----------------------------------------------------------------------------------------------------
def month_spend(db: Session, now: datetime) -> Decimal:
    """This UTC month's estimated cost of ``feature = "news_tagging"`` calls (Anthropic bills by UTC month)."""
    costs = db.scalars(select(AiUsage.cost_usd).where(AiUsage.feature == FEATURE,
                                                      AiUsage.created_at >= store.utc_month_start(now)))
    return sum((Decimal(c or 0) for c in costs), Decimal(0))


_budget_logged: set[str] = set()
_budget_lock = threading.Lock()


def _log_budget_once(now: datetime, spent: Decimal, budget: Decimal) -> None:
    month = store.utc_month_start(now).strftime("%Y-%m")
    with _budget_lock:
        if month in _budget_logged:
            return
        _budget_logged.add(month)
    log.warning("news tagging stopped for %s: US$%s of the US$%s monthly budget spent "
                "(NEWS_TAGGING_MONTHLY_BUDGET_USD)", month, spent.quantize(Decimal("0.0001")), budget)


# -- the run ---------------------------------------------------------------------------------------------------
@dataclass
class RunResult:
    tagged: int = 0  # headlines tagged (with or without tags)
    untagged: int = 0  # of those: no tag at all (not financial news)
    skipped: int = 0  # hidden headlines marked skipped
    failed: int = 0  # headlines that counted a failed attempt
    split: int = 0  # headlines of a batch with an unusable answer, asked again at once in smaller batches
    calls: int = 0
    cost_usd: Decimal = Decimal(0)
    purged: int = 0
    stopped: str | None = None  # disabled | budget | waiting | no_key | busy | error
    slot: int | None = None  # the key slot of the run's first call: later batches stay on it (its prompt cache)


def _transient(exc: BaseException) -> bool:
    """A busy, rate-limited or unreachable key: try again next run without counting an attempt."""
    return isinstance(exc, (KeysBusy, NoKeyAvailable, anthropic.APIConnectionError,
                            anthropic.AuthenticationError, anthropic.PermissionDeniedError)) \
        or is_failover_error(exc)


def _error_label(exc: BaseException) -> str:
    """「404 not_found_error」 — status and error type only (safe to log: no key, no request)."""
    if isinstance(exc, anthropic.APIStatusError):
        return f"{exc.status_code} {getattr(exc, 'type', None) or type(exc).__name__}"
    return type(exc).__name__


_warned: dict[str, datetime] = {}
_warn_lock = threading.Lock()


def _warn_request_error(now: datetime, exc: BaseException, n: int) -> None:
    """A request-level error, logged at most once per WARN_EVERY per kind of error."""
    label = _error_label(exc)
    with _warn_lock:
        last = _warned.get(label)
        if last is not None and now - last < WARN_EVERY:
            return
        _warned[label] = now
    log.warning("news tagging stopped: the request was refused (%s) — the model setting (AI_MODEL_NEWS_TAGGING / "
                "AI_MODEL) or the request does not work; %d headlines wait, no attempt counted (logged at most "
                "hourly)", label, n)


def _first_slot(db: Session, pool: KeyPool, costs: Mapping[int, Decimal]) -> int | None:
    """The key slot of the last tagging request while it is usable: its workspace holds the cached prompt."""
    last = db.scalar(select(AiUsage.key_slot).where(AiUsage.feature == FEATURE, AiUsage.key_slot.is_not(None))
                     .order_by(AiUsage.created_at.desc(), AiUsage.id.desc()).limit(1))
    slot = pool.get(last)
    return last if slot is not None and pool.state(slot, costs.get(last, Decimal(0))) == "ok" else None


def tag_batch(db: Session, items: Sequence[Item], cat: Catalog, pool: KeyPool, settings: Settings,
              now: datetime, result: RunResult) -> None:
    """One request for ``items``; stores the tags, splits a batch whose answer cannot be used and marks what failed.
    Raises transient errors untouched; a request-level error sets ``result.stopped = "error"`` (nothing counted)."""
    params = request_params(items, cat, settings)
    model = params["model"]
    costs = store.slot_month_costs(db) if result.slot is None else None
    only = result.slot if result.slot is not None else _first_slot(db, pool, costs or {})
    try:
        raw, slot = pool.call(lambda client: client.messages.with_raw_response.create(**params), costs=costs,
                              only=only)
    except Exception as exc:
        db.rollback()
        if _transient(exc):
            raise
        _warn_request_error(now, exc, len(items))
        result.stopped = "error"
        return
    pool.observe(slot, raw.headers)
    result.slot = slot
    msg = raw.parse()
    usage = store.record_usage(db, user_id=None, thread_id=None, feature=FEATURE, model=msg.model or model,
                               key_slot=slot, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)
    result.calls += 1
    result.cost_usd += Decimal(usage.cost_usd or 0)
    try:
        entries = parse_answer(msg)
    except BadAnswer as exc:
        keys = [it.url_key for it in items]
        if len(items) > 1:
            half = (len(items) + 1) // 2
            log.warning("news tagging: unusable answer (%s) for %d headlines (key #%s): asked again in batches of %d",
                        exc, len(items), slot, half)
            mark(db, keys, "split", now, batch_limit=half)
            result.split += len(items)
        else:
            log.warning("news tagging: unusable answer (%s) for a headline sent alone (key #%s)%s", exc, slot,
                        ": given up" if exc.refused else "")
            mark(db, keys, "failed", now, give_up=exc.refused)
            result.failed += 1
        return
    by_id: dict[int, Mapping[str, Any]] = {}
    for e in entries:
        i = e.get("id")
        if isinstance(i, int) and 1 <= i <= len(items) and i not in by_id:
            by_id[i] = e
    missing: list[str] = []
    for i, it in enumerate(items, 1):
        entry = by_id.get(i)
        if entry is None:
            missing.append(it.url_key)
            continue
        tags = validate(entry, it, cat)
        save(db, it, tags, msg.model or model, now)
        result.tagged += 1
        result.untagged += tags.empty
    db.commit()
    if missing:
        mark(db, missing, "failed", now)
        result.failed += len(missing)


def run(db: Session, md: MarketData, *, settings: Settings | None = None, pool: KeyPool | None = None,
        now: datetime | None = None) -> RunResult:
    """One run of the tagging job (see the module docstring)."""
    settings = settings or get_settings()
    now = now or now_utc()
    result = RunResult()
    if not settings.news_tagging_enabled:
        result.stopped = "disabled"
        return result
    result.purged = purge_orphans(db)
    budget = Decimal(str(settings.news_tagging_monthly_budget_usd))
    cat = Catalog(db, md)
    min_batch = min(settings.news_tagging_min_batch, settings.news_tagging_batch_size)
    wait = timedelta(minutes=settings.news_tagging_max_wait_minutes)
    sent = 0
    for _ in range(settings.news_tagging_max_batches):
        spent = month_spend(db, now)
        if budget <= 0 or spent + RESERVE_USD > budget:
            if budget > 0:
                _log_budget_once(now, spent, budget)
            result.stopped = "budget"
            break
        items, hidden = pending(db, md, settings, now, settings.news_tagging_batch_size)
        result.skipped += hidden
        if not items:
            if hidden:
                continue  # a page of hidden rows: look again
            break
        if not sent and len(items) < min_batch and all(it.fresh for it in items) \
                and all(it.stored_at is not None and it.stored_at > now - wait for it in items):
            result.stopped = "waiting"  # a trickle: wait for more headlines (or for the oldest to wait long enough)
            break
        pool = pool or get_key_pool()
        if not pool.available:
            result.stopped = "no_key"
            break
        sent += 1
        try:
            tag_batch(db, items, cat, pool, settings, now, result)
        except Exception as exc:  # transient (tag_batch re-raises only those)
            log.info("news tagging paused: %s", type(exc).__name__)
            result.stopped = "busy"
            break
        if result.stopped == "error":
            break
    if result.calls or result.failed:
        log.info("news tagging: %d tagged (%d without tags), %d failed, %d split, %d skipped, %d calls, US$%s%s",
                 result.tagged, result.untagged, result.failed, result.split, result.skipped, result.calls,
                 result.cost_usd.quantize(Decimal("0.0001")), f", stopped: {result.stopped}" if result.stopped else "")
    return result


def status(db: Session, now: datetime | None = None, settings: Settings | None = None) -> dict[str, Any]:
    """Counts for the CLI: states by status, URLs still untagged in the window, this month's spend."""
    settings = settings or get_settings()
    now = now or now_utc()
    by_status = dict(db.execute(select(NewsTagState.status, func.count()).group_by(NewsTagState.status)).all())
    since = now - timedelta(days=settings.news_tagging_days)
    window = db.scalar(select(func.count(func.distinct(NewsArticle.url_key))).where(NewsArticle.published_at >= since))
    untagged = db.scalar(
        select(func.count(func.distinct(NewsArticle.url_key)))
        .outerjoin(NewsTagState, NewsTagState.url_key == NewsArticle.url_key)
        .where(NewsArticle.published_at >= since, NewsTagState.url_key.is_(None)))
    gave_up = db.scalar(select(func.count()).select_from(NewsTagState).where(
        NewsTagState.status == "failed", NewsTagState.attempts >= MAX_ATTEMPTS))
    tags = dict(db.execute(select(NewsTag.kind, func.count()).group_by(NewsTag.kind)).all())
    return {"taxonomy_version": tx.TAXONOMY_VERSION, "states": by_status, "window_days": settings.news_tagging_days,
            "urls_in_window": window or 0, "never_tagged_in_window": untagged or 0, "gave_up": gave_up or 0,
            "tags": tags, "month_spend_usd": float(month_spend(db, now)),
            "monthly_budget_usd": settings.news_tagging_monthly_budget_usd}


def main(argv: list[str] | None = None) -> int:
    """``python -m forliosa.news.tagging run|status|retry-failed``."""
    import argparse
    import sys

    from forliosa.db import session_factory
    from forliosa.marketdata.service import get_market_data

    p = argparse.ArgumentParser(prog="python -m forliosa.news.tagging", description="新聞標籤（主題、類股、相關股票）")
    p.add_argument("command", choices=["run", "status", "retry-failed"])
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with session_factory()() as db:
        if args.command == "status":
            print(json.dumps(status(db), ensure_ascii=False, indent=2))
            return 0
        if args.command == "retry-failed":
            print(json.dumps({"reset": retry_failed(db)}, ensure_ascii=False))
            return 0
        res = run(db, get_market_data())
        print(json.dumps({"tagged": res.tagged, "untagged": res.untagged, "failed": res.failed, "split": res.split,
                          "skipped": res.skipped, "calls": res.calls, "cost_usd": float(res.cost_usd),
                          "purged": res.purged, "stopped": res.stopped}, ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
