"""The chat turn behind ``POST /ai/chat``: a streaming tool loop that yields SSE events.

Why a manual loop rather than the SDK's beta tool runner: every turn must stream text to the browser, forward
citations and server-tool progress as they happen, emit a ``draft`` event when ``draft_transaction`` runs and a
``chart`` event when ``draw_chart`` drew one,
retry a request on another key slot when it fails *before* anything was streamed, and persist the exact
content blocks for append-only replay. The loop follows the skill's manual-loop rules: append the full
``response.content``; answer every ``tool_use`` with a matching ``tool_result`` in one user message
(``is_error`` for failures); re-send on ``pause_turn`` without adding a message; never run tools of a
``refusal`` or of a ``max_tokens`` turn.

Key slots (``keypool``): a thread is pinned to one slot (``ai_threads.key_slot``) and every call of every turn
goes there — prompt caches are per workspace, thinking blocks stay with the account that produced them, and
web-search ``encrypted_content`` must be passed back unchanged to the same account. New threads take the slot
with the most headroom. When the pinned slot is disabled, out of budget / spend limit, or cooling down for
longer than ``AI_KEY_STICKY_WAIT_SECONDS``, the turn (only before its first model call has produced anything)
moves to another slot and continues from a plain-text recap (``store.recap_messages``); the recap and the new
slot are stored once a call there succeeds. The same recap recovers a 400 that rejects replayed thinking blocks.

A server tool the API refuses (400 naming its ``type``) is left out for the rest of the process and the call is
retried without it (``tools.rejected_tool``).

The read-only client tools of one round run side by side, each on a session of its own; ``draft_transaction`` and
``draw_chart`` run after them on the turn's session (``ChatTurn._run_tools``). Every turn logs one line of timings
(setup, each model call, each tool, the editor, the first visible text, the total; ``TurnTiming``).

Prompt caching: one breakpoint on the frozen system prompt (tools render before it, so tools + system are
cached together) plus top-level automatic caching for the growing conversation. Everything that changes per
turn (time, page, privacy) is a ``role: "system"`` message after the user's message.

「X 今天為什麼漲／跌」 (``research``, 產品負責人 2026-11-16): the research of such a question is shared by every user
per stock and trading session. A fresh entry goes into the turn as citable ``search_result`` blocks before the user's
text, with its facts and a short rule in the system message; the turn is then held, edited and grounding-checked like
one that searched, and shows a ``shared_research`` step. A turn that searched stores what it found for the next asker.
深度搜尋 neither reads nor writes it.

深度搜尋 (``mode="deep"``, one turn): the same loop with ``web_search`` allowed ``AI_DEEP_SEARCH_MAX_USES`` times and
``AI_DEEP_MAX_TOOL_ROUNDS`` rounds; what to research and how to write it up is in that turn's page context
(``prompts.DEEP_SEARCH_NOTE``), never in the frozen system prompt. The tool list differs from an ordinary turn only
in ``max_uses``, so that turn (and the one after it) misses the prompt cache. The user's row stores ``mode`` and how
many questions the turn counts as (``store.messages_today``).

Events (``event: <name>`` / ``data: <json>``):

* ``thread``    ``{id, title, created}`` – always first
* ``text``      ``{delta}``
* ``text_reset`` ``{text}`` – the whole answer of this turn so far, shown instead of what the ``text`` deltas built:
  the edit of a held-back answer streams as it is written (``ChatTurn._edit``), and when it is dropped after part of
  it was shown (the editor failed, stopped early, ran long or lost a number) this brings back the answer as written;
  also after a complete edit whose dates or MOPS boilerplate were then fixed (``tidy_answer``)
* ``tool``      ``{id, name, status: running|done|error, label}`` (``shared_research``: 「沿用 10:05 查好的資料」)
* ``citation``  ``{url, title, cited_text}``
* ``draft``     the draft card (see ``tools.draft_card``)
* ``chart``     a chart card drawn by ``draw_chart`` (see ``charts``): every series with its points
* ``grounding`` ``{items: [{index, start, end, text, reason, signals}]}`` – uncited news-like sentences of a
  turn that used web search / fetch (``grounding``)
* ``error``     ``{code, message}``
* ``done``      ``{thread_id, turn_id, model, stop_reason, usage, disclaimer}`` – always last
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

import anthropic
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from forliosa import plans
from forliosa.ai import grounding, research, scope, store
from forliosa.ai.keypool import Failure, KeyPool, KeysBusy, KeySlot, NoKeyAvailable, classify_failure
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import CHAT_SYSTEM, DISCLAIMER, EDITOR_SYSTEM, OFF_TOPIC_REPLY, page_context
from forliosa.ai.tools import (
    CHAT_BLOCKED_DOMAINS,
    ToolContext,
    ToolOutcome,
    block_search,
    client_tool_definitions,
    exclude_tool,
    execute,
    rejected_tool,
    server_tools,
    tool_label,
)
from forliosa.config import Settings
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import AiThread, User
from forliosa.timeutil import now_taipei

log = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]

REFUSAL_MESSAGE = "這題沒辦法回答。換個問法，或問你的持股和個股。"
_ERRORS = {
    "ai_busy": "現在問的人太多，等一下再送一次。",
    "ai_unavailable": "AI 暫時不能用，晚一點再試。",
    "ai_unreachable": "連不上 AI，等一下再送一次。",
    "ai_error": "這次沒有回答完，再送一次。一直失敗的話，開一段新對話。",
    "too_many_steps": "這題要查的資料太多。拆成幾個小問題再問。",
    "max_tokens": "回答太長，被截斷了。拆成幾個小問題再問。",
    "truncated": "回答太長，後面的部分沒有顯示。",
    "interrupted": "回答中斷了，再送一次。",
    "internal_error": "伺服器出了問題，這題沒有回答。等一下再送一次。",
}
WEB_TOOLS = ("web_search", "web_fetch")
_THINKING_REJECTED = re.compile(r"bound to a different conversation|invalid `?signature`? in `?thinking`? block",
                                re.IGNORECASE)
# Models that rejected mid-conversation system messages: the page context is sent as a user-turn reminder.
_NO_SYSTEM_ROLE: set[str] = set()
# The answer editor streams (2026-11-16: the whole edit ran before its first word was shown, 1.4–3.1 s). Its first
# word must come within EDITOR_FIRST_TOKEN_SECONDS (also the connect and read timeout, so a silent connection is cut;
# checked again at every event) and the whole edit within EDITOR_TOTAL_SECONDS (checked at every event); otherwise
# the answer is shown as written.
EDITOR_FIRST_TOKEN_SECONDS = 4.0
EDITOR_TOTAL_SECONDS = 20.0
# Haiku 5.5 thinks by default and streams nothing while it does (display "omitted"): 3 of 16 live edits hit the
# first-word limit after 4.5 s of silence and the draft was shown (2026-11-16). With thinking off the first word came
# in 0.4–2.1 s in 141 calls; edits that lost a number: 4–7 of 33 against 4 of 33 with it on (where 4 more thought for
# 3.5–6.6 s), and the ### headings it adds are undone (``_HeadingFilter``). Haiku 5.5 accepts "disabled" at effort
# high or below; Opus 5.5, Sonnet 5.5 and Fable reject it (400), so other models keep their default.
EDITOR_NO_THINKING_MODELS = ("claude-haiku-5",)
# Tools that write (a draft) or add to the turn (a chart card) run one at a time on the turn's own session, after the
# read-only tools of the same round, which run side by side (``ChatTurn._run_tools``)
SEQUENTIAL_TOOLS = frozenset({"draft_transaction", "draw_chart"})
MAX_PARALLEL_TOOLS = 4
_clock = time.monotonic  # tests replace it


class ChatFailure(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass
class TurnState:
    display: store.TurnDisplay = field(default_factory=store.TurnDisplay)
    usage: CallUsage = field(default_factory=CallUsage)
    citation_keys: set[tuple[str | None, str]] = field(default_factory=set)
    tool_labels: dict[str, str] = field(default_factory=dict)
    fetched: list[dict[str, str | None]] = field(default_factory=list)
    outlets: dict[str, str] = field(default_factory=dict)  # url -> outlet of citable tool results (get_news)
    context_tokens: int | None = None
    segments: list[grounding.Segment] = field(default_factory=list)  # text blocks of the answer (cited or not)
    round_start: int | None = None  # where this call's text starts in display.text
    used_web: bool = False
    # Where the held-back answer starts in ``display.text``: after web search or the news tool the answer is not
    # streamed as it is written; ``ChatTurn._edit`` rewrites it once and streams the result (None: nothing held)
    held_from: int | None = None

    def add_text(self, s: str) -> None:
        self.display.text += s


def _s(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


@dataclass
class CallSpan:
    """One attempt of a model call, in seconds from the start of the turn."""

    n: int
    start: float
    headers: float | None = None  # the response headers came (the SDK returns from ``stream()``)
    first: float | None = None  # the first event
    end: float | None = None  # the final message


@dataclass
class TurnTiming:
    """Where the time of one turn went, logged as one line when it ends (2026-11-16: a 17–20 s answer could not be
    attributed from the access log). Offsets are seconds from the start of the turn; tools are durations. No user
    content goes into it."""

    start: float = field(default_factory=lambda: _clock())
    parts: list[str] = field(default_factory=list)
    calls: int = 0
    first_text: float | None = None  # the first visible word reached the browser

    def at(self) -> float:
        return _clock() - self.start

    def note(self, part: str) -> None:
        self.parts.append(part)

    def call(self) -> CallSpan:
        if not self.calls:  # everything before the first model call: thread, page symbol, history, key slot
            self.note(f"setup {self.at():.2f}")
        self.calls += 1
        return CallSpan(self.calls, self.at())

    def close(self, span: CallSpan) -> None:
        self.note(f"call{span.n} start {span.start:.2f} headers {_s(span.headers)} first {_s(span.first)} "
                  f"end {_s(span.end)}")

    def line(self) -> str:
        return "; ".join([*self.parts, f"first text {_s(self.first_text)}", f"total {self.at():.2f}"])


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMBER.finditer(text)}


# 「台積電(2330)」「聯發科（2454.TW）」, and cnyes's 「台達電(2308-TW)」 (2026-11-16: a clean edit was dropped for it)
_CODE_IN_PARENS = re.compile(r"[(（](\d{4,6})[A-Z]?(?:[.-]TWO?)?[)）]")
# Years the editor may drop when it rewrites a date as 11/13: 2026, 2026/11/04, 115年 (ROC), 2026年
_YEAR = re.compile(r"(?<!\d)(?:(?:19|20)\d\d(?=\s*[年/\-.])|1[01]\d(?=\s*(?:年|/\d)))")
# A date in parentheses, the way news copy writes it: 「今（16）日」「昨（15）日」「本（11）月」「今（2026）年」,
# 「週一（16日）」「（11月16日）」「（11/16）」. The editor rewrites these as 今天／昨天／11/16 (EDITOR_SYSTEM), so
# their numbers may go (2026-11-16: an edit that turned 「今（16）日」 into 「今天」 was dropped for the missing 16)
_DATE_IN_PARENS = re.compile(r"[今昨明前本上下去同當][（(]\s*\d{1,4}\s*[)）]\s*[日月年]"
                             r"|[（(]\s*(?:\d{1,2}\s*月\s*)?\d{1,2}\s*日\s*[)）]"
                             r"|[（(]\s*(?:1[0-2]|0?[1-9])\s*/\s*(?:3[01]|[12]\d|0?[1-9])\s*[)）]")
# Today's or yesterday's date written as a day, the way news flashes do (「台達電(2308-TW)16日09:59下跌120元」, not
# 「20日均線」), or as 11/16 or 11月16日: the editor may write it as 今天／昨天, so its numbers may go when the edit
# says so (2026-11-16: an edit that wrote 「台達電今天 09:59 跌 120 元」 was dropped for the 16)
_BARE_DAY = re.compile(r"(?<![\d/月.])(3[01]|[12]\d|0?[1-9])\s*日(?![均線內後前以來])")
_MONTH_DAY = re.compile(r"(?<![\d.])(1[0-2]|0?[1-9])\s*(?:/|月)\s*(3[01]|[12]\d|0?[1-9])(?:\s*日)?(?![\d/])")
_TODAY_WORDS = re.compile(r"今天|今日")
_YESTERDAY_WORDS = re.compile(r"昨天|昨日")
# A rounded restatement (「大盤約跌 4%」 beside 「跌 4.14%」): the editor keeps one of the two (EDITOR_SYSTEM says to
# write a thing once), so it may go when the draft's exact figure stays (2026-11-16: 「約 4%」 merged into 「4.14%」)
_APPROX = re.compile(r"(?:大約|約|將近|接近|近|逾|超過)\s*(?:下跌|上漲|跌|漲)?\s*(\d[\d,]*(?:\.\d+)?)")
# Not facts: digits inside a link (a pasted 「[新聞](https://…/2026/11/16/123456)」 the editor rightly removes) and a
# search-result index the model leaked (「8-1 來源」「來源 3」). Dropping them must not bring the draft back (2026-11-16
# effort A/B: 5 of 24 edits were reverted, 4 of them to a worse draft)
_URL = re.compile(r"\]\([^)\s]*\)|https?://[^\s)）\]」]+")
_SOURCE_INDEX = re.compile(r"(?<![\d.])\d{1,2}\s*-\s*\d{1,2}\s*(?=(?:號|筆)?\s*(?:來源|搜尋結果|結果))"
                           r"|(?:來源|搜尋結果)\s*\d{1,2}(?:\s*-\s*\d{1,2})?")
# A sentence about a source left out (「另有一則目標價 1,418 元的說法，來源是 AI 生成的整理頁面，因此不採用。」):
# EDITOR_SYSTEM deletes it whole, numbers and all (2026-11-16, 禾榮科: the one edit that did was dropped for
# the missing 1418 and the draft was shown)
_VETTING = re.compile(r"[^。！？\n]*(?:不採用|不予採用|不可信|出處(?:與日期)?都?不明|來源不明|日期不明"
                      r"|AI ?生成|AI ?整理的?頁|不列入|不計入|未具名|沒(?:有)?寫(?:出)?機構(?:的)?名稱"
                      r"|未(?:寫明|寫出|註明)機構(?:的)?名稱)[^。！？\n]*[。！？]?")
# The rating rule's own criteria written into the answer (「近 90 天內，具名外資的目標價…」,
# 「目前沒有近 90 天內具名機構的…資料」): EDITOR_SYSTEM takes those words out, the 90 with them
_CRITERIA = re.compile(r"(?:近|過去|最近)\s*90\s*天內?的?\s*[，、]?\s*(?=具名|的?(?:機構|外資|券商|投顧|評等|目標價))")
# A cited source repeated word for word (2026-11-16, 禾榮科: 6 of 10 drafts pasted the cited text after their own
# sentence, 「…法說會。公開資訊觀測站，11/10 15:02：本公司受邀參加…」, and an edit that rewrote it was dropped for the
# 15:02): at least this many characters in a row of a citation's cited_text or title
_MIN_COPY = 12
# 「第三季」「前十個月」 in the edit for the draft's 「第 3 季」「前 10 個月」 (2026-11-16: an edit was dropped for
# the 3)
_CN_DIGITS = {c: str(i) for i, c in enumerate("一二三四五六七八九十", 1)} | {"十一": "11", "十二": "12"}
_CN_COUNT = re.compile(r"([第前近])\s*(十[一二]|[一二三四五六七八九十])\s*(季|個月|個?年|週|名|大)")
_CLOCK = re.compile(r"(?<![\d:])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:])")
_OWN_WORD = re.compile(r"[\u4e00-\u9fffA-Za-z]")  # a Chinese character or a Latin letter


def copied_spans(text: str, sources: Iterable[str]) -> list[tuple[int, int]]:
    """Where ``text`` repeats a source word for word (at least ``_MIN_COPY`` characters, white space aside: the model
    copies 「第3季」 as 「第 3 季」), merged, in order."""
    where = [i for i, c in enumerate(text) if not c.isspace()]  # position in ``text`` of each character of ``dense``
    dense = "".join(text[i] for i in where)
    spans: list[tuple[int, int]] = []
    for src in dict.fromkeys("".join(s.split()) for s in sources if s):
        if len(src) < _MIN_COPY:
            continue
        for a, _, size in SequenceMatcher(None, dense, src, autojunk=False).get_matching_blocks():
            if size >= _MIN_COPY:
                spans.append((where[a], where[a + size - 1] + 1))
    merged: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _blank_copies(draft: str, sources: Iterable[str]) -> str:
    """``draft`` with the numbers of the source text it pasted blanked out (same length, positions kept). A paste
    beside the line's own words (「…法說會。公開資訊觀測站，11/10 15:02：…」) repeats what the line says: all of its
    numbers may go. A line that is nothing but a paste is the only place its facts are written: only its dates and
    clock times may go."""
    spans = copied_spans(draft, sources)
    if not spans:
        return draft
    out = list(draft)
    for a, b in spans:
        line_start = draft.rfind("\n", 0, a) + 1
        line_end = draft.find("\n", b)
        line_end = len(draft) if line_end < 0 else line_end
        own = draft[line_start:a] + draft[b:line_end]
        for x, y in spans:  # other pastes on the same line are not the line's own words either
            if (x, y) != (a, b) and line_start <= x < line_end:
                own = own.replace(draft[x:y], "")
        whole = len(_OWN_WORD.findall(own)) < 6
        piece = draft[a:b]
        if whole:
            piece = _CLOCK.sub(lambda m: " " * len(m.group(0)), _MONTH_DAY.sub(lambda m: " " * len(m.group(0)), piece))
        else:
            piece = _NUMBER.sub(lambda m: " " * len(m.group(0)), piece)
        out[a:b] = piece
    return "".join(out)


# What may follow a paste that goes (``strip_pastes``): the end of its sentence, nothing of the line's own
_PASTE_TAIL = re.compile(r"[\s。！？!?.，,、；;]*")


def strip_pastes(text: str, sources: Iterable[str]) -> str:
    """``text`` without the source text pasted after a line's own words, when the line already says every number of
    it (2026-11-16, 台積電: each item of a draft ended with get_analyst_views' wording, 「…目標價 3,300 元。小摩，
    11/12，維持，評等「優於大盤」，目標價 3,300 元」, and the answer was shown so when its edit was dropped). A line
    that is only a paste, or a paste with a number the line does not say, stays. So does a paste without a number
    (nothing shows the line says it) and one inside a sentence (2026-11-16 review: 「分析師指出，AI 需求強勁帶動
    先進製程產能滿載，公司對明年展望樂觀。」 had become 「分析師指出公司對明年展望樂觀。」): it goes only after the
    end of a sentence, with nothing but punctuation after it on its line."""
    spans = copied_spans(text, sources)
    cut: list[tuple[int, int]] = []
    for a, b in spans:
        line_start = text.rfind("\n", 0, a) + 1
        line_end = text.find("\n", b)
        line_end = len(text) if line_end < 0 else line_end
        own, after = text[line_start:a] + text[b:line_end], text[b:line_end]
        for x, y in spans:  # other pastes on the same line are not the line's own words either
            if (x, y) != (a, b) and line_start <= x < line_end:
                own, after = own.replace(text[x:y], ""), after.replace(text[x:y], "")
        nums = _numbers(_CLOCK.sub(" ", text[a:b]))  # its clock time (「15:02」) aside
        pasted = text[line_start:a].rstrip().endswith(("。", "！", "？", "!", "?")) and _PASTE_TAIL.fullmatch(after)
        if len(_OWN_WORD.findall(_ITEM.sub("", own, count=1))) >= 6 and nums and nums <= _numbers(own) and pasted:
            while a > max(line_start, cut[-1][1] if cut else 0) and text[a - 1] in " \t":  # the space that joined it
                a -= 1
            while b < line_end and _PASTE_TAIL.fullmatch(text[b]):  # its own full stop (the line has one)
                b += 1
            cut.append((a, b))
    for a, b in reversed(cut):
        text = text[:a] + text[b:]
    return text


def missing_numbers(draft: str, edited: str, today: date | None = None, sources: Iterable[str] = ()) -> list[str]:
    """The numbers of the draft that are not in the edited answer (thousands separators aside). The editor may drop
    a stock code in parentheses after a name (「台積電(2330)」, 「聯發科（2454.TW）」, 「台達電(2308-TW)」), the year
    of a date it rewrites as 11/13 (「2026年11月4日」, 「115 年」, 「2026/11/04」), a date in parentheses it rewrites as
    今天 or 11/16 (「今（16）日」, 「（16日）」) and, given ``today``, today's or yesterday's date when the edit says
    今天 or 昨天 (「16日09:59」, 「11/16 盤中」); also a rounded restatement of a figure the edit kept (「約 4%」 beside
    「4.14%」), digits inside a link, a leaked search-result index (「8-1 來源」), a sentence about a source left
    out (「…因此不採用」, 「…沒寫機構名稱，所以不列入」), the rating rule's criteria (「近 90 天內具名機構」) and the
    numbers of source text pasted beside the line's own words (``sources``: the turn's cited texts and titles;
    ``_blank_copies``). Only those spans: the same number elsewhere in the draft still counts."""
    codes = {m.group(1) for m in _CODE_IN_PARENS.finditer(draft)}
    years = {m.group(0) for m in _YEAR.finditer(draft)}
    rest = _blank_copies(draft, sources)
    rest = _SOURCE_INDEX.sub(" ", _URL.sub(" ", _DATE_IN_PARENS.sub(" ", _VETTING.sub(" ", _CRITERIA.sub(" ", rest)))))
    if today is not None:
        days = ([today] if _TODAY_WORDS.search(edited) else []) + \
            ([today - timedelta(days=1)] if _YESTERDAY_WORDS.search(edited) else [])
        rest = _MONTH_DAY.sub(lambda m: " " if any((d.month, d.day) == (int(m.group(1)), int(m.group(2)))
                                                   for d in days) else m.group(0), rest)
        rest = _BARE_DAY.sub(lambda m: " " if any(d.day == int(m.group(1)) for d in days) else m.group(0), rest)
    kept = _numbers(_CN_COUNT.sub(lambda m: f"{m.group(1)}{_CN_DIGITS[m.group(2)]}{m.group(3)}", edited))
    numbers = _numbers(rest)
    approx = {m.group(1).replace(",", "") for m in _APPROX.finditer(rest)}
    return sorted(x for x in numbers - codes - years
                  if not _covered(x, kept) and not (x in approx and any(y != x and y in kept and _rounds_to(y, x)
                                                                         for y in numbers)))


def _rounds_to(y: str, x: str) -> bool:
    """``y`` rounded to the decimals ``x`` has is ``x`` (4.14 -> 4, 9.68 -> 9.7)."""
    return round(float(y), len(x.partition(".")[2])) == float(x)


def keeps_numbers(draft: str, edited: str, today: date | None = None, sources: Iterable[str] = ()) -> bool:
    """Every number of the draft is still in the edited answer, but for the dates and codes ``missing_numbers``
    lets the editor rewrite."""
    return not missing_numbers(draft, edited, today, sources)


# A number with a scale (千, 萬, 億; 仟 is 千): 「6,806 千元」「13.8 億元」「1.2萬張」「197.7（萬元）」
_SCALED = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*[（(]?\s*([仟千萬億兆])")


def _scaled(text: str) -> set[tuple[float, str]]:
    return {(float(m.group(1).replace(",", "")), m.group(2).replace("仟", "千")) for m in _SCALED.finditer(text)}


def added_scales(draft: str, edited: str) -> list[str]:
    """Numbers of the draft the edit gave a scale the draft did not (2026-11-16, 禾榮科: 「本年累計6,806」 from a
    table in 仟元 became 「累計 6,806 萬元」, ten times too much, and the number check could not see it): the same
    number with 千, 萬 or 億 after it in the edit, never with that scale in the draft. A number of a draft table row
    (its unit is in the header) is left alone; a number the edit rescaled (6,806 千元 → 680.6 萬元) is a new number."""
    had = _scaled(draft)
    plain = {float(x) for line in draft.splitlines() if not line.lstrip().startswith("|") for x in _numbers(line)}
    return [m.group(0) for m in _SCALED.finditer(edited)
            if (v := float(m.group(1).replace(",", ""))) in plain
            and (v, m.group(2).replace("仟", "千")) not in had]


# A conversion the draft did not make (2026-11-16, 台積電: the draft's 「5,000新台幣／1,000美元」, two targets for two
# listings, became 「5,000 新台幣，相當於 1,000 美元」: every number was still there)
_CONVERSION = re.compile(r"相當於|約合|折合|換算")


def added_conversions(draft: str, edited: str) -> list[str]:
    """The conversion words (相當於, 約合, 折合, 換算) of the edit that the draft does not have."""
    return sorted({w for w in _CONVERSION.findall(edited) if w not in draft})


# Dates written the way CHAT_SYSTEM asks (11/13, a year only when it is not this year, no ROC year, no zero padding),
# fixed in the held-back draft before the editor sees it: the model copies them from MOPS titles and rating tables and
# the editor, which does not know this year, left them (2026-11-16, 禾榮科: 「115 年第 3 季」 in 7 and
# 「2026/10/02」 in 6 of 8 answers). Links are left as they are.
_AD_DATE = re.compile(r"(?<![\d/.])(20\d\d)(?:([/.-])(1[0-2]|0?[1-9])\2(3[01]|[12]\d|0?[1-9])"
                      r"|\s*年\s*(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]\d|0?[1-9])\s*日)(?![\d/])")
_ROC_DATE = re.compile(r"(?<![\d/.])(1[01]\d)(?:/(1[0-2]|0?[1-9])/(3[01]|[12]\d|0?[1-9])"
                       r"|\s*年\s*(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]\d|0?[1-9])\s*日)(?![\d/])")
_ROC_MONTH = re.compile(r"(?<![\d/.])(1[01]\d)\s*年\s*(1[0-2]|0?[1-9])\s*月(?!\s*\d)")
# with the space before it, which goes too when the year does (「通過 115 年第 3 季」 → 「通過第 3 季」, not
# 「通過 第 3 季」)
_ROC_PERIOD = re.compile(r"([ \t]*)(?<![\d/.])(1[01]\d)\s*年\s*度?\s*"
                         r"(第\s*[1-4一二三四]\s*季|前\s*[2-3二三]\s*季|[上下]\s*半\s*年)")
# 「10 月 15 日」 without a year (the editor wrote it so, 2026-11-16): this year's date, 10/15; not after a year
# (「1999 年 10 月 15 日」, 「每年 10 月 15 日」)
_BARE_MD = re.compile(r"(?<![\d/.年])(?<!年 )(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]\d|0?[1-9])\s*日(?!\d)")
_PADDED_MD = re.compile(r"(?<![\d/.:])(1[0-2]|0[1-9])/(3[01]|[12]\d|0[1-9])(?![\d/:])")
_CJK = re.compile(r"[\u4e00-\u9fff]")  # a Chinese character
_WIDE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")  # a Chinese character or full-width punctuation


def normalize_dates(text: str, today: date) -> str:
    """2026/10/02 → 10/2 (2025/10/02 → 2025/10/2), 2026年11月12日 → 11/12 (2025 年 10 月 15 日 → 2025/10/15), 10 月
    15 日 → 10/15, 115 年 12 月 21 日 → 12/21, 115 年 10 月 → 10 月, 115 年第 3 季 → 第 3 季 (114 年度第 4 季 → 2025
    年第 4 季), 10/02 → 10/2; ``today`` decides which year is this year. Text inside links is left as it is."""
    def md(m: re.Match[str], year: int, month: str, day: str) -> str:
        text = f"{int(month)}/{int(day)}" if year == today.year else f"{year}/{int(month)}/{int(day)}"
        # 「115年12月21日下市」 → 「12/21 下市」, 「10月6日至10月7日」 → 「10/6 至 10/7」, like the prompt's
        # 「11/13 收 30.5 元」
        before = " " if m.start() > 0 and _CJK.match(m.string, m.start() - 1) else ""
        return before + text + (" " if _CJK.match(m.string, m.end()) else "")

    def ad(m: re.Match[str]) -> str:
        return md(m, int(m.group(1)), m.group(3) or m.group(5), m.group(4) or m.group(6))

    def roc(m: re.Match[str]) -> str:
        return md(m, int(m.group(1)) + 1911, m.group(2) or m.group(4), m.group(3) or m.group(5))

    def year_of(roc_year: str) -> str:
        year = int(roc_year) + 1911
        return "" if year == today.year else f"{year} 年"

    def period(m: re.Match[str]) -> str:
        year, space = year_of(m.group(2)), m.group(1)
        if not year and space and m.start() > 0 and _WIDE.match(m.string, m.start() - 1):
            space = ""
        return space + year + m.group(3)

    def fix(part: str) -> str:
        part = _ROC_DATE.sub(roc, _AD_DATE.sub(ad, part))
        part = _ROC_MONTH.sub(lambda m: " ".join(x for x in (year_of(m.group(1)), f"{int(m.group(2))} 月") if x),
                              part)
        part = _ROC_PERIOD.sub(period, part)
        part = _BARE_MD.sub(lambda m: md(m, today.year, m.group(1), m.group(2)), part)
        return _PADDED_MD.sub(lambda m: f"{int(m.group(1))}/{int(m.group(2))}", part)

    out, pos = [], 0
    for link in _URL.finditer(text):
        out += [fix(text[pos:link.start()]), link.group(0)]
        pos = link.end()
    return "".join([*out, fix(text[pos:])])


# MOPS's footer, copied from 公告 reprints (2026-11-16, 禾榮科: 「完整財務業務資訊請至公開資訊觀測站之法人說明會一覽表
# 或法說會項目下查閱。」, kept by the editor): not a fact. The clause goes; after a comma, the sentence ends there.
_MOPS_FOOTER = re.compile(r"(^|[。！？，；])([^。！？，；\n]*請(?:至|到|上|參閱|詳見|見)\s*公開資訊觀測站"
                          r"[^。！？\n]*)([。！？]?)", re.MULTILINE)
# The site named as where a 公告 was made: 「共有四則公開資訊觀測站公告」 → 「共有四則公告」,
# 「公司在公開資訊觀測站公告」 → 「公司公告」 (CHAT_SYSTEM: no source names in sentences)
_MOPS_NAME = re.compile(r"(?:在|於)?公開資訊觀測站(?:上)?(?:的)?(?=公告|重大訊息)")
# The opening of a get_news 公告 item pasted into the answer (「…法說會。公開資訊觀測站，11/10 15:02：本公司受邀…」; the
# editor made it 「公開資訊觀測站 11/10 15:02 有此公告」): the tool's label for the model, not part of the answer. Its
# date stays unless the line has it already
_NOTICE_HEAD = re.compile(r"(?:公開資訊觀測站|臺灣證券交易所|公司公告|交易所公告)，(?P<when>(?:今天 |昨天 )?(?:\d{4}/)?"
                          r"(?P<md>(?:1[0-2]|0?[1-9])/(?:3[01]|[12]\d|0?[1-9]))(?: (?:[01]?\d|2[0-3]):[0-5]\d)?)：")
_EMPTY_ITEM = re.compile(r"\s*(?:[-*]|\d+\.)?\s*")


def _notice_heads(line: str) -> str:
    def head(m: re.Match[str]) -> str:
        rest = line[:m.start()] + line[m.end():]
        return "" if re.search(rf"(?<![\d/]){re.escape(m.group('md'))}(?![\d/])", rest) else m.group("when") + " "
    return _NOTICE_HEAD.sub(head, line)


def strip_boilerplate(text: str) -> str:
    """The MOPS footer, the site's name before 公告 and the label of a pasted 公告 item left out (``_MOPS_FOOTER``,
    ``_MOPS_NAME``, ``_NOTICE_HEAD``); a list item left empty goes with its line."""
    def footer(m: re.Match[str]) -> str:
        return m.group(3) if m.group(1) in "，；" and m.group(1) else m.group(1)

    lines = []
    for line in text.split("\n"):
        new = _notice_heads(_MOPS_NAME.sub("", _MOPS_FOOTER.sub(footer, line)))
        if new != line:
            if _EMPTY_ITEM.fullmatch(new):
                continue
            new = new.rstrip()
        lines.append(new)
    return "\n".join(lines)


# The rating rule's screening words left in an answer (2026-11-16, round 3: 「台積電最新的具名目標價是小摩的 3,300 元」
# in 2 of 3 target answers, kept by the editor): 「具名」 before 機構／外資／目標價…, with the 「近 90 天內」 before it.
# Not a period before anything else (「近 90 天外資買超」 stays), and not news wording about anonymity: 「未具名」
# 「不願具名的分析師」「非具名的法人」「不具名的券商主管」 stay (2026-11-16 review: 「不願具名的外資分析師」 had become
# 「不願外資分析師」; so had 「不便具名」「不肯具名」「拒絕具名」「婉拒具名」).
_SCREENING = re.compile(r"(?:(?:近|過去|最近)\s*(?:90|180)\s*天內?的?\s*[，、]?\s*)?"
                        r"(?<![未不非願意匿便肯絕拒想欲])具名的?"
                        r"(?=機構|外資|券商|投顧|投行|投資銀行|法人|分析師|目標價|評等|報告)"
                        r"|(?:近|過去|最近)\s*(?:90|180)\s*天內?的?\s*[，、]?\s*"
                        r"(?=的?(?:(?:機構|外資|券商|投顧)的?)?(?:評等|目標價))")
# 「沒有具名…」 followed in the same sentence by the broker it did not count (「目前沒有具名的機構評等，只有一家日系外資
# 調降目標價」): without 「具名」 the sentence says the opposite of its second half, so it stays as written
_NEGATED = re.compile(r"(?:沒有|並無|尚無|無)\s*$")
_UNNAMED_AFTER = re.compile(r"未具名|[美日歐英德法瑞港陸中韓星亞澳][系資]|(?:只|僅|但|另|不過)有")


def _unscreen(m: re.Match[str]) -> str:
    if "具名" in m.group(0) and _NEGATED.search(m.string, 0, m.start()):
        rest = re.split(r"[。！？\n]", m.string[m.end():], maxsplit=1)[0]
        if _UNNAMED_AFTER.search(rest):
            return m.group(0)
    return ""


def tidy_answer(text: str, today: date) -> str:
    """The fixed rewrites of an answer that is edited (``ChatTurn._edit``): its dates (``normalize_dates``), the MOPS
    boilerplate (``strip_boilerplate``) and the rating rule's screening words (``_SCREENING``: 「具名機構」 →
    「機構」). Run on the draft before the editor sees it and on the edit. A report's date in parentheses (「（11/15
    報導）」) is left to the editor (EDITOR_SYSTEM: write it into the sentence): moved to the start of its list item
    here, the editor made the answer's first sentence a list item in 3 of 3 edits (2026-11-16)."""
    out, pos = [], 0
    for link in _URL.finditer(text):  # never inside a link
        out += [_SCREENING.sub(_unscreen, text[pos:link.start()]), link.group(0)]
        pos = link.end()
    return strip_boilerplate(normalize_dates("".join([*out, _SCREENING.sub(_unscreen, text[pos:])]), today))


# A list item or a heading, not a sentence (the answer's first line must be a sentence: CHAT_SYSTEM, EDITOR_SYSTEM)
_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)])\s+")
_NOT_SENTENCE = re.compile(r"\s*(?:[-*+]\s|\d+[.)]\s|#|\|)")
_FIRST_SENTENCE = re.compile(r"[^。！？]+[。！？]")


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _share(a: str, b: str) -> float:
    """How much of ``a`` is ``b``'s words (its characters in the blocks it has in common with ``b``)."""
    same = sum(n for _, _, n in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return same / len(a) if a else 0.0


def keep_opening(draft: str, edited: str) -> str:
    """The draft's opening sentence back when the edit made it a list item or dropped it (2026-11-16, round 3: 3 of
    11 edits started with 「- 」 where the draft opened with a sentence). The edit's first item, when it is that
    sentence rewritten or its first part (closer to it, or to its first sentence, than to any item of the draft's
    list; or nearly all of it the opening's words: an opening of two sentences split into two items), becomes the
    opening line again; a line further down that rewrites the whole opening, not only its second sentence (the
    editor moved the opening to the end), moves to the top; otherwise the draft's first sentence goes before the
    list."""
    d_lines, e_lines = draft.strip().split("\n"), edited.split("\n")
    first = next((i for i, x in enumerate(e_lines) if x.strip()), None)
    opening = d_lines[0].strip()
    if first is None or not opening or _NOT_SENTENCE.match(opening) or not _ITEM.match(e_lines[first]):
        return edited
    d_items = [_ITEM.sub("", x, count=1).strip() for x in d_lines[1:] if _ITEM.match(x)]
    sentence = _FIRST_SENTENCE.match(opening)
    lead = sentence.group(0) if sentence else opening
    tail = opening[len(lead):].strip()

    def rewrites_opening(line: str, at_least: float, *parts: str) -> bool:
        r = max(_ratio(line, x) for x in (opening, *parts))
        return r >= at_least and all(r > _ratio(line, x) for x in d_items)

    def part_of_opening(line: str) -> bool:
        """The line is a piece of the opening (an opening of two sentences, or one long one, split into list
        items): nearly all of it is the opening's words, more than any item of the draft's list."""
        share = _share(line, opening)
        return share >= 0.8 and all(share > _share(line, x) for x in d_items)

    item = _ITEM.sub("", e_lines[first], count=1).strip()
    # 2026-11-16 review: 「大華今天跌 6.9%，大盤跌 2.1%。」 (half of a two-sentence opening split in two items) was not
    # taken for the opening, and the item with its other half was moved up instead
    if rewrites_opening(item, 0.5, lead) or part_of_opening(item):
        rest = "\n".join(e_lines[first + 1:]).lstrip("\n")
        return item + ("\n\n" + rest if rest else "")
    for i in range(first + 1, len(e_lines)):
        line = _ITEM.sub("", e_lines[i], count=1).strip()
        if line and not re.match(r"[#|]", line) and rewrites_opening(line, 0.6) \
                and not (tail and _ratio(line, tail) >= _ratio(line, opening)):  # not only its second sentence
            rest = re.sub(r"\n{3,}", "\n\n", "\n".join(e_lines[first:i] + e_lines[i + 1:])).strip("\n")
            return line + "\n\n" + rest
    return lead + "\n\n" + "\n".join(e_lines[first:])


def _editor_thinking(model: str) -> dict[str, Any]:
    """The editor call's ``thinking``: off where the model allows it (``EDITOR_NO_THINKING_MODELS``)."""
    return {"thinking": {"type": "disabled"}} if model.startswith(EDITOR_NO_THINKING_MODELS) else {}


def _covered(x: str, kept: set[str]) -> bool:
    """``x`` is still there: the same number, or the same quantity rounded or in another unit (7 -> 7.01%,
    3.51 萬張 -> 35,144 張, 46,736,664 千元 -> 467.37 億元): a power of ten apart within 0.6%."""
    if x in kept:
        return True
    xv = float(x)
    for y in kept:
        yv = float(y)
        if xv == 0 or yv == 0:
            continue
        ratio = xv / yv
        k = round(math.log10(ratio))
        if abs(k) <= 8 and abs(ratio / 10 ** k - 1) <= 0.006:
            return True
    return False


def remap_flags(flagged: list[dict[str, Any]], draft: str, final: str, start: int) -> list[dict[str, Any]]:
    """Grounding flags of the held-back draft, moved onto the edited text (positions in the whole answer)."""
    out = []
    targets = grounding.sentences(final)
    for f in flagged:
        a = f.get("start")
        if isinstance(a, int) and a < start:  # before the edited part: unchanged
            out.append(f)
            continue
        best, ratio = None, 0.0
        for x, y in targets:
            r = SequenceMatcher(None, f.get("text") or "", final[x:y], autojunk=False).ratio()
            if r > ratio:
                best, ratio = (x, y), r
        if best is not None and ratio >= 0.55:
            x, y = best
            out.append({**f, "start": start + x, "end": start + y, "text": final[x:y]})
    return out


def _stream(text: str, size: int = 24) -> Iterator[Event]:
    for i in range(0, len(text), size):
        yield "text", {"delta": text[i:i + size]}


class _EditorGaveUp(Exception):
    """The streamed edit is not used: its first word or its end came too late, it outgrew the draft, or it did not
    start in Chinese."""


# The edit's first characters, held back until they show it is written in Chinese: at least this many, and while
# none is Chinese, as many more as the draft has before its first Chinese character (2026-11-16 review: an edit
# starting 「NVIDIA（NVDA）11/13 收」 like its draft was dropped at 「NVIDIA（N」)
EDITOR_HEAD_CHARS = 8


def _chinese_head(head: str) -> str:
    if not _CJK.search(head):
        raise _EditorGaveUp("the edit does not start in Chinese")
    return head


_HEADING = re.compile(r"(?m)^ {0,3}#")


class _HeadingFilter:
    """Turns the Markdown headings (「### …」) of an edit whose draft had none back into plain lines: with thinking off
    the editor made the answer's first sentence a ### heading in 8 to 15 of 33 edits (2026-11-16), and EDITOR_SYSTEM
    saying not to did not stop it. Fed the edit as it streams: the #s at the start of a line and the spaces after
    them are left out (the line itself stays, so no number goes)."""

    def __init__(self) -> None:
        self.line_start, self.marker = True, False

    def feed(self, text: str) -> str:
        out = []
        for c in text:
            if self.line_start and c == "#":
                self.marker = True
            elif not (self.marker and c == " "):
                self.marker = False
                out.append(c)
                self.line_start = c == "\n" or (self.line_start and c == " ")
        return "".join(out)


def _run_here(ctx: ToolContext, name: str, args: Any) -> tuple[ToolOutcome, float]:
    t = _clock()
    return execute(ctx, name, args), _clock() - t


def _run_apart(sessions: Callable[[], Session], ctx: ToolContext, user_id: str, name: str,
               args: Any) -> tuple[ToolOutcome, float]:
    """A read-only tool on a worker thread, with a session and the user of its own: the turn's session (and the
    objects loaded through it) is never used off its thread; ``execute`` rolls back only this session on an error."""
    t = _clock()
    with sessions() as db:
        own = replace(ctx, db=db, user=db.get(User, user_id), drafts=[], charts=[], drafted={})
        return execute(own, name, args), _clock() - t


def _classify(exc: BaseException) -> str:
    if isinstance(exc, KeysBusy):
        return "ai_busy"
    if isinstance(exc, NoKeyAvailable | anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return "ai_unavailable"
    if isinstance(exc, anthropic.APIConnectionError):
        return "ai_unreachable"
    failure = classify_failure(exc)
    if failure is not None:
        return "ai_unavailable" if failure.kind in ("disable", "exhaust") else "ai_busy"
    return "ai_error"


def render_messages(messages: list[dict[str, Any]], system_role: bool) -> list[dict[str, Any]]:
    """Stored messages → request messages. Without system-role support, page context becomes a reminder in a
    user turn (deterministically, so the prefix stays stable across requests)."""
    if system_role:
        return messages
    out = []
    for m in messages:
        if m["role"] == "system":
            text = m["content"] if isinstance(m["content"], str) else str(m["content"])
            out.append({"role": "user", "content": [{"type": "text", "text": f"<system-reminder>\n{text}\n"
                                                                             "</system-reminder>"}]})
        else:
            out.append(m)
    return out


class ChatTurn:
    def __init__(self, db: Session, user: User, md: MarketData, pool: KeyPool, settings: Settings,
                 now_fn: Callable[[], datetime] = now_taipei, economy: bool = False,
                 sessions: Callable[[], Session] | None = None):
        self.db, self.user, self.md, self.pool, self.settings, self.now_fn = db, user, md, pool, settings, now_fn
        # Sessions for the read-only tools that run side by side (``_run_tools``); by default on the engine of ``db``
        self.sessions = sessions
        self.timing = TurnTiming()
        # 省錢模式 (``store.month_mode``): the month's budget is spent, so this turn has no web search or fetch. The
        # tool list differs from the thread's earlier turns, so replayed thinking is rejected once and the turn goes
        # on from the plain-text recap (``_THINKING_REJECTED``).
        self.economy = economy
        self.thread: AiThread | None = None
        self.slot: KeySlot | None = None  # the slot serving this turn (every call of the turn)
        self.costs: dict[int, Decimal] = {}  # estimated cost per slot this UTC month
        self.stored: list[dict[str, Any]] = []  # the thread's replay history (valid on its own slot)
        self.recap: list[dict[str, Any]] | None = None  # plain-text history, once this turn needs it
        self.history: list[dict[str, Any]] = []  # what precedes this turn's messages: ``stored`` or ``recap``
        self.served = False  # a call on ``self.slot`` succeeded
        self._page: tuple[str | None, str | None, str | None, bool] = (None, None, None, False)
        self._new: list[dict[str, Any]] = []
        self.deep = False  # 深度搜尋 (``mode: "deep"``): more searches, a longer write-up, counts as several questions
        # A why-question about one stock (``research``): its key, and the shared research this turn answers from
        self.why: research.Lookup | None = None

    # -- request building --------------------------------------------------------------------------------
    def tools(self) -> list[dict[str, Any]]:
        # 深度搜尋 only raises how often web_search may run; the tool list is otherwise the same. web_search always
        # blocks CHAT_BLOCKED_DOMAINS (rating aggregators, quote pages, AI-written pages, forums; the 2026-11-16 memo):
        # every turn, not only rating questions, since a tool list that changes between turns invalidates the cache
        # and the replayed thinking (see ``economy``). Rating sites that also publish news (Benzinga, Zacks) stay
        # searchable: the card's list blocks them, chat answers ratings from the card first.
        max_uses = self.settings.ai_deep_search_max_uses if self.deep else None
        web = [] if self.economy else block_search(server_tools(self.settings, max_uses=max_uses),
                                                   CHAT_BLOCKED_DOMAINS)
        return client_tool_definitions(self.settings) + web

    def params(self, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": model,
            # 深度搜尋 thinks and searches far more: at medium effort 8000 tokens ran out before the report (2026-11-15)
            "max_tokens": self.settings.ai_max_tokens_chat * (2 if self.deep else 1),
            "system": [{"type": "text", "text": CHAT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            "tools": self.tools(),
            "messages": render_messages(messages, model not in _NO_SYSTEM_ROLE),
            "output_config": {"effort": self.settings.ai_effort_chat},
            "cache_control": {"type": "ephemeral"},
        }

    def _context(self) -> str:
        route, sym, name, privacy = self._page
        moved = self.recap is not None and self.history is self.recap
        now = self.now_fn()
        text = page_context(now, route, sym, name, privacy, moved=moved, deep=self.deep, economy=self.economy,
                            closes=self._tw_closes(now))
        if self.why is not None and self.why.entry is not None:  # the shared research this turn answers from
            text += "\n" + research.note(self.why)
        return text

    def _find_research(self, message: str, symbol: str | None) -> research.Lookup | None:
        """The shared research of a why-question (not in 深度搜尋, which researches on its own); best effort."""
        if self.deep or not self.settings.ai_research_cache:
            return None
        try:
            found = research.lookup(self.db, self.md, message, symbol, self.now_fn())
        except Exception as exc:  # never fail a turn over it: the turn researches as before
            log.warning("AI why research not read: %s", exc)
            self.db.rollback()
            return None
        if found is not None:
            self.timing.note(f"research {'hit' if found.entry else 'miss'}")
        return found

    def _share_research(self, new: list[dict[str, Any]], state: TurnState, ok: bool) -> None:
        """Store what this why-turn's web search found, for the next asker (``research.remember``); best effort."""
        if self.why is None or not ok or self.deep:
            return
        try:
            research.remember(self.db, self.why, new, state.display.citations, state.outlets, self.now_fn(),
                              self.settings)
        except Exception:  # the answer is out already; sharing it is a nicety
            log.warning("AI why research not stored", exc_info=True)
            self.db.rollback()

    def _tw_closes(self, now: datetime) -> list[dict[str, Any]] | None:
        """Where each Taiwan market's close is (``forliosa.closes``), for the page context; best effort."""
        from forliosa.closes import tw_closes

        try:
            return tw_closes(self.db, now, self.settings)
        except Exception as exc:  # never fail a turn over this line
            log.warning("page context: closes not read: %s", exc)
            self.db.rollback()
            return None

    # -- key slots -------------------------------------------------------------------------------------------
    def _use_recap(self, needed: bool) -> None:
        assert self.thread is not None
        if needed:
            if self.recap is None:
                self.recap = store.recap_messages(self.db, self.thread)
            self.history = self.recap
        else:
            self.history = self.stored
        if len(self._new) >= 2 and self._new[1]["role"] == "system":
            self._new[1] = {"role": "system", "content": self._context()}

    def _route(self, exclude: set[int] | None = None) -> None:
        """Pick the slot for this turn (sticky, see ``KeyPool.route``) and the history that is valid there."""
        assert self.thread is not None
        try:
            route = self.pool.route(self.thread.key_slot, self.costs, self.settings.ai_key_sticky_wait_seconds,
                                    exclude or ())
        except (NoKeyAvailable, KeysBusy) as exc:
            raise ChatFailure(_classify(exc), str(exc)) from exc
        if route.wait > 0:  # the pinned slot cools down for a moment: wait for it rather than move the thread
            log.info("AI thread %s waits %.1fs for key #%d (sticky)", self._tid(), route.wait, route.slot.index)
            self.timing.note(f"wait {route.wait:.2f} key #{route.slot.index}")
            self.pool.sleep(route.wait)
        self.slot = route.slot
        moved = bool(self.stored) and route.slot.index != self.thread.key_slot
        if moved:
            log.info("AI thread %s continues on key #%d from a plain-text recap (pinned: #%s)",
                     self.thread.id, route.slot.index, self.thread.key_slot)
        self._use_recap(moved)

    def _recover(self, failure: Failure, tried: set[int], same: set[int], can_move: bool) -> bool:
        """After a failed call that streamed nothing: choose the next attempt (True) or give up (False)."""
        slot = self.slot
        assert slot is not None
        max_wait = self.settings.ai_key_sticky_wait_seconds
        transient = failure.kind in ("cool", "connection")
        wait = self.pool.wait_seconds(slot)
        if transient and wait <= max_wait and slot.index not in same:  # recovers within the short wait: stay
            same.add(slot.index)
            self.timing.note(f"retry wait {max(wait, 0.5):.2f} key #{slot.index}")
            self.pool.sleep(max(wait, 0.5))
            return True
        if can_move:  # nothing of this turn exists yet: another slot (and a recap) is safe
            try:
                self._route(tried)
            except ChatFailure:
                pass
            else:
                return True
        if transient and len(tried) == 1 and slot.index not in same:  # nothing else to try: once more
            same.add(slot.index)
            self.timing.note(f"retry wait 1.00 key #{slot.index}")
            self.pool.sleep(1.0)
            return True
        return False

    def _tid(self) -> str:
        """The thread in a timing log line: its id's prefix only."""
        return self.thread.id[:16] if self.thread is not None else "-"

    # -- one streamed API call -----------------------------------------------------------------------------
    def _call(self, model: str, new: list[dict[str, Any]], state: TurnState,
              first_text_of_round: list[bool]) -> Iterator[Event]:
        json_retries = tool_retries = 0
        system_retry = recap_retry = False
        tried: set[int] = set()
        same: set[int] = set()
        while True:
            slot = self.slot
            assert slot is not None
            params = self.params(model, self.history + new)
            emitted = False
            state.round_start = None
            span = self.timing.call()
            try:
                with slot.client.messages.stream(**params) as stream:
                    span.headers = self.timing.at()
                    try:
                        for ev in stream:
                            if span.first is None:
                                span.first = self.timing.at()
                            for out in self._translate(ev, state, first_text_of_round):
                                emitted = True
                                yield out
                    except BaseException:
                        # The browser went away (GeneratorExit) or the stream failed part-way: the call is billed
                        # all the same, so it counts toward the budgets (2026-11-14 review)
                        self._record_partial(stream, slot.index, model)
                        raise
                    final = stream.get_final_message()
                    headers = stream.response.headers
                span.end = self.timing.at()
                self.pool.observe(slot.index, headers)
                self.pool.mark_success(slot)
                self.served = True
                return final, slot.index
            except ValueError as exc:  # tool input JSON the SDK could not parse at all
                if emitted or json_retries >= 2:
                    raise ChatFailure("ai_error", f"unparseable tool input: {exc}") from exc
                json_retries += 1
                continue
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                failure = classify_failure(exc)
                if failure is None:
                    if emitted:
                        raise ChatFailure(_classify(exc), str(exc)) from exc
                    if isinstance(exc, anthropic.BadRequestError):
                        msg = str(exc.api_message or exc)
                        tool = rejected_tool(msg, params["tools"])
                        if tool is not None and tool_retries < 3:
                            exclude_tool(tool, msg)
                            tool_retries += 1
                            continue
                        if not system_retry and "role" in msg and "system" in msg:
                            log.warning("model %s rejects mid-conversation system messages; using a reminder", model)
                            _NO_SYSTEM_ROLE.add(model)
                            system_retry = True
                            continue
                        if (not recap_retry and self.stored and len(new) == 2 and self.history is self.stored
                                and _THINKING_REJECTED.search(msg)):
                            log.warning("AI thread %s: replayed thinking rejected on key #%d; continuing from a "
                                        "plain-text recap", self.thread.id if self.thread else "?", slot.index)
                            recap_retry = True
                            self._use_recap(True)
                            continue
                        log.error("AI request rejected (key #%d): %s", slot.index, msg)
                    raise ChatFailure(_classify(exc), str(exc)) from exc
                self.pool.mark_failure(slot, exc)
                if emitted:
                    raise ChatFailure(_classify(exc), str(exc)) from exc
                tried.add(slot.index)
                if not self._recover(failure, tried, same, can_move=len(new) == 2):
                    raise ChatFailure(_classify(exc), str(exc)) from exc
            finally:  # every attempt, also a failed or interrupted one (``end -``)
                self.timing.close(span)

    def _record_partial(self, stream: Any, slot_index: int, model: str) -> None:
        """Record what an interrupted streamed call has used so far (input from ``message_start``, the output
        streamed until then). Nothing is recorded when the stream never started a message."""
        try:
            snap = stream.current_message_snapshot
            usage = CallUsage.from_sdk(snap.usage)
        except Exception:  # no message started: nothing was billed that we can see
            return
        if not (usage.input_tokens or usage.output_tokens):
            return
        try:
            store.record_usage(self.db, user_id=self.user.id, thread_id=self.thread.id if self.thread else None,
                               feature="chat", model=getattr(snap, "model", None) or model, key_slot=slot_index,
                               usage=usage, stop_reason="interrupted")
        except Exception:  # accounting must not hide the original failure
            log.exception("could not record the usage of an interrupted AI call")

    def _translate(self, ev: Any, state: TurnState, first_text_of_round: list[bool]) -> Iterator[Event]:
        t = getattr(ev, "type", None)
        if t == "text":
            # after web search or the news tool the answer is held back and edited before it is shown (``_edit``)
            # (a 深度搜尋 searches the web anyway: held from its first word, a plan written before searching included)
            hold = self.settings.ai_answer_editor and (state.used_web or self.deep)
            if hold and state.held_from is None:
                state.held_from = len(state.display.text)
            if first_text_of_round[0] and state.display.text and not state.display.text.endswith("\n"):
                state.add_text("\n\n")
                if not hold:
                    yield "text", {"delta": "\n\n"}
            first_text_of_round[0] = False
            if state.round_start is None:
                state.round_start = len(state.display.text)
            state.add_text(ev.text)
            if not hold:
                yield "text", {"delta": ev.text}
        elif t == "citation":
            c = self._citation(ev.citation, state)
            if c is not None:
                yield "citation", c
        elif t == "content_block_stop":
            b = ev.content_block
            if getattr(b, "type", None) == "server_tool_use":
                args = b.input if isinstance(b.input, dict) else {}
                label = tool_label(b.name, args)
                state.tool_labels[b.id] = label
                state.display.tools.append({"name": b.name, "label": label})
                state.used_web = state.used_web or b.name in WEB_TOOLS
                yield "tool", {"id": b.id, "name": b.name, "status": "running", "label": label}
        elif t == "content_block_start":
            b = ev.content_block
            bt = getattr(b, "type", None)
            if bt in ("web_search_tool_result", "web_fetch_tool_result"):
                name = "web_search" if bt == "web_search_tool_result" else "web_fetch"
                state.used_web = True
                content = b.content
                ok = isinstance(content, list) if name == "web_search" else (
                    getattr(content, "type", None) == "web_fetch_result")
                if ok and name == "web_fetch":
                    doc = getattr(content, "content", None)
                    state.fetched.append({"url": getattr(content, "url", None),
                                          "title": getattr(doc, "title", None)})
                yield "tool", {"id": b.tool_use_id, "name": name, "status": "done" if ok else "error",
                               "label": state.tool_labels.get(b.tool_use_id, tool_label(name, {}))}

    def _citation(self, c: Any, state: TurnState) -> dict[str, Any] | None:
        ctype = getattr(c, "type", None)
        cited = getattr(c, "cited_text", "") or ""
        if ctype == "web_search_result_location":
            url, title = c.url, c.title
        elif ctype == "search_result_location":  # a citable tool result (get_news)
            url, title = getattr(c, "source", None), getattr(c, "title", None)
        elif ctype in ("char_location", "page_location", "content_block_location"):
            title = getattr(c, "document_title", None)
            match = next((f for f in state.fetched if title and f["title"] == title), None)
            if match is None:
                idx = getattr(c, "document_index", None)
                match = state.fetched[idx] if isinstance(idx, int) and 0 <= idx < len(state.fetched) else None
            url = match["url"] if match else None
            title = title or (match["title"] if match else None)
        else:
            return None
        key = (url, cited)
        if key in state.citation_keys:
            return None
        state.citation_keys.add(key)
        out = {"url": url, "title": title, "cited_text": cited}
        if url and state.outlets.get(url):
            out["outlet"] = state.outlets[url]
        state.display.citations.append(out)
        return out

    @staticmethod
    def _segments(final: Any, state: TurnState) -> None:
        """Where each text block of this call landed in the answer, and whether it carries citations."""
        if state.round_start is None:
            return
        pos = state.round_start
        for b in final.content:
            if getattr(b, "type", None) == "text":
                state.segments.append(grounding.Segment(pos, pos + len(b.text), bool(getattr(b, "citations", None))))
                pos += len(b.text)

    # -- the turn ------------------------------------------------------------------------------------------
    def run(self, *, thread_id: str | None, message: str, route: str | None, symbol: str | None,
            privacy: bool, mode: str | None = None) -> Iterator[Event]:
        """One turn (``_turn``), noting when its first word was shown and logging its timings when it ends (also when
        the browser went away: closing this closes the turn, which saves what it has)."""
        self.timing = timing = TurnTiming()
        events = self._turn(thread_id=thread_id, message=message, route=route, symbol=symbol, privacy=privacy,
                            mode=mode)
        try:
            for name, data in events:
                words = data.get("delta") if name == "text" else data.get("text") if name == "text_reset" else None
                if timing.first_text is None and isinstance(words, str) and words.strip():
                    timing.first_text = timing.at()
                yield name, data
        finally:
            events.close()
            log.info("AI turn %s timings (s): %s", self._tid(), timing.line())

    def _turn(self, *, thread_id: str | None, message: str, route: str | None, symbol: str | None,
              privacy: bool, mode: str | None) -> Iterator[Event]:
        db, settings = self.db, self.settings
        self.deep = mode == "deep" and settings.ai_web_search and not self.economy
        created = thread_id is None
        thread = (store.create_thread(db, self.user, message, store.model_for("chat", settings)) if created
                  else store.owned_thread(db, self.user, thread_id))
        self.thread = thread
        yield "thread", {"id": thread.id, "title": thread.title, "created": created}

        turn_id = new_id("trn")
        sym, name = self._page_symbol(symbol)
        self._page = (route, sym, name, privacy)
        off_topic = scope.precheck(message) if settings.ai_scope_precheck else None
        self.why = self._find_research(message, sym) if off_topic is None else None
        shared = self.why.entry if self.why is not None else None
        # the shared research goes before the user's text as citable search results (``research.blocks``); its rule
        # and facts are in the system message (``_context``)
        user: list[dict[str, Any]] = [*(research.blocks(shared) if shared else []), {"type": "text", "text": message}]
        new: list[dict[str, Any]] = [{"role": "user", "content": user},
                                     {"role": "system", "content": self._context()}]
        self._new = new
        state = TurnState()
        if shared is not None:  # answered from search results like a web search's: held, edited, grounding-checked
            state.used_web = True
            state.outlets.update(research.outlets(shared))
            step = {"id": "research", "name": "shared_research", "status": "done", "label": research.label(shared)}
            state.display.tools.append({"name": step["name"], "label": step["label"]})
            yield "tool", step

        if off_topic is not None:  # clearly not about investing: decline without a model call
            log.info("AI chat: off-topic request (%s) declined without a model call", off_topic)
            state.display.text, state.display.stop_reason = OFF_TOPIC_REPLY, "off_topic"
            yield "text", {"delta": OFF_TOPIC_REPLY}
            self._persist(thread, turn_id, new[:1], False, message, state)
            yield "done", self._done(thread, turn_id, state)
            return

        ctx = ToolContext(db=db, user=self.user, md=self.md, thread_id=thread.id, message=message)
        ok = False
        try:
            self.costs = store.slot_month_costs(db)
            self.stored = store.api_history(db, thread)
            self._route()
            ok = yield from self._loop(thread, new, state, ctx)
            flagged = grounding.check(state.display.text, state.segments) if ok and state.used_web else []
            if state.held_from is not None:
                flagged = yield from self._edit(thread, state, flagged, edit=ok and state.display.error is None)
            if flagged:
                state.display.grounding = flagged
                yield "grounding", {"items": flagged}
        except GeneratorExit:
            state.display.error = {"code": "interrupted", "message": _ERRORS["interrupted"]}
            raise
        except ChatFailure as exc:
            yield from self._release(state)  # what was held back is shown as written
            state.display.error = {"code": exc.code, "message": _ERRORS.get(exc.code, _ERRORS["ai_error"])}
            yield "error", state.display.error
        except Exception:
            log.exception("AI chat turn failed")
            yield from self._release(state)
            state.display.error = {"code": "internal_error", "message": _ERRORS["internal_error"]}
            yield "error", state.display.error
        finally:
            self._persist(thread, turn_id, new, ok, message, state)
        self._share_research(new, state, ok)
        yield "done", self._done(thread, turn_id, state)

    # -- the answer editor ------------------------------------------------------------------------------------
    def _release(self, state: TurnState) -> Iterator[Event]:
        """Show the held-back text as it was written (the turn failed, or editing is off for it)."""
        if state.held_from is None:
            return
        held, state.held_from = state.display.text[state.held_from:], None
        yield from _stream(held)

    def _edit(self, thread: AiThread, state: TurnState, flagged: list[dict[str, Any]], edit: bool):
        """Rewrite the held-back answer once (產品負責人 2026-11-15: answers built on search results copied source
        sentences and named outlets in the text), streaming the edit as it is written (2026-11-16: the first word
        came only after the whole edit). The edit is dropped, and the answer shown as written, when the call fails,
        is late, stops for anything but ``end_turn``, outgrows the draft or loses a number the draft had; when part of
        it was shown already, a ``text_reset`` brings back the answer as written. Flagged (uncited) sentences are
        moved onto the most similar sentence of the edited answer; one without a close match is left out.
        ``state.display.text`` keeps the draft until the edit is complete, so a turn cut off meanwhile saves it. The
        draft's dates are written the prompt's way and the MOPS boilerplate goes first (``tidy_answer``): the editor
        gets it so, and so does the answer shown as written. The edit gets the same once it is complete (2026-11-16:
        the editor wrote 「10 月 15 日」); when that changes it, a ``text_reset`` shows the result. An edit that gave a
        number a scale the draft did not (``added_scales``: 「6,806」 → 「6,806 萬元」) or made a conversion it did not
        (``added_conversions``: 「相當於 1,000 美元」) is dropped as well. An edit is held back until its first
        characters show it is in Chinese (``_chinese_head``); the answer shown as written leaves out the source
        text pasted after its own sentences (``strip_pastes``)."""
        start = state.held_from
        assert start is not None
        today = self.now_fn().date()
        held = state.display.text[start:]
        fixed = tidy_answer(held, today)
        if fixed != held:  # whether or not the editor runs, and also what is shown when its edit is dropped
            flagged = remap_flags(flagged, held, fixed, start)
            state.display.text = state.display.text[:start] + fixed
        if not edit or not state.display.text[start:].strip():
            yield from self._release(state)
            return flagged
        draft = state.display.text[start:]
        body = draft.lstrip()
        lead = draft[: len(draft) - len(body)]
        timing = self.timing
        began, first = timing.at(), None
        yield "tool", {"id": "edit", "name": "edit_answer", "status": "running", "label": "整理回答"}
        edited: str | None = None
        shown = ""  # the edit streamed so far (after ``lead``)
        pieces = self._editor_stream(thread, body)
        try:
            while True:
                try:
                    piece = next(pieces)
                except StopIteration as stop:
                    edited = stop.value
                    break
                if first is None:
                    first = timing.at()
                yield "text", {"delta": (lead if not shown else "") + piece}
                shown += piece
        except _EditorGaveUp as exc:
            log.warning("AI answer editor: %s; showing the answer as written", exc)
        except Exception:  # the answer as written is fine to show; editing is a nicety
            log.warning("AI answer editor failed; showing the answer as written", exc_info=True)
        finally:
            pieces.close()  # the browser went away: the editor call stops too (its usage is recorded)
        # the cited texts the draft may have pasted (their numbers need not stay; ``missing_numbers``)
        sources = [normalize_dates(x, today) for c in state.display.citations
                   for x in (c.get("cited_text"), c.get("title")) if x]
        if edited is not None:
            if missing := missing_numbers(body, edited, today, sources):
                # the count only: the numbers may be the user's own amounts
                log.warning("AI answer editor dropped %d number(s); showing the answer as written", len(missing))
                edited = None
            elif scaled := added_scales(body, edited):
                log.warning("AI answer editor gave %d number(s) a scale; showing the answer as written", len(scaled))
                edited = None
            elif added_conversions(body, edited):
                log.warning("AI answer editor added a conversion; showing the answer as written")
                edited = None
        timing.note(f"editor start {began:.2f} first {_s(first)} end {timing.at():.2f} "
                    f"{'edited' if edited is not None else 'as written'}")
        yield "tool", {"id": "edit", "name": "edit_answer", "status": "done", "label": "整理回答"}
        state.held_from = None
        if edited is None:
            # shown as written, but without the source text pasted after its own sentences (``strip_pastes``)
            bare = lead + strip_pastes(body, sources)
            if bare != draft:
                flagged = remap_flags(flagged, draft, bare, start)
                state.display.text = state.display.text[:start] + bare
                draft = bare
            if shown:  # part of the edit is on screen: the whole answer as written replaces it
                yield "text_reset", {"text": state.display.text}
            else:
                yield from _stream(draft)
            return flagged
        final = tidy_answer(lead + keep_opening(body, edited), today)
        state.display.text = state.display.text[:start] + final
        # the edit as streamed is not what is kept (its opening restored, a date or boilerplate fixed): show the kept
        if final != lead + edited:
            yield "text_reset", {"text": state.display.text}
        return remap_flags(flagged, draft, final, start)

    def _editor_stream(self, thread: AiThread, body: str) -> Iterator[str]:
        """The editor call, streamed: yields the edited answer as it is written, without leading or trailing white
        space (what it yields is exactly what it returns), and returns it, or None when the call stopped for anything
        but ``end_turn`` or wrote nothing. Raises ``_EditorGaveUp`` when no word came within
        ``EDITOR_FIRST_TOKEN_SECONDS``, the edit ran past ``EDITOR_TOTAL_SECONDS`` or outgrew the draft (twice its
        length, at least 200 characters), and the SDK's errors when the call fails; what a call cut short used is
        recorded all the same."""
        slot = self.slot
        if slot is None:
            return None
        model = thread.model
        limit = max(200, len(body) * 2)
        timeout = anthropic.Timeout(EDITOR_TOTAL_SECONDS, connect=EDITOR_FIRST_TOKEN_SECONDS,
                                    read=EDITOR_FIRST_TOKEN_SECONDS)
        client = slot.client.with_options(timeout=timeout, max_retries=0)
        t0 = _clock()
        out: list[str] = []
        size = 0
        pending = ""  # white space held back until a word follows it (none is shown at the start or the end)
        # the first words, held back until they show the edit is in Chinese like the draft (2026-11-16: an editor
        # call answered in English, 「I've got the new target price… Please paste the answer」, and it was on screen
        # for a second before the number check dropped it)
        first_cjk = _CJK.search(body)
        head: str | None = "" if first_cjk else None
        head_max = EDITOR_HEAD_CHARS + (first_cjk.start() if first_cjk else 0)
        headings = None if _HEADING.search(body) else _HeadingFilter()
        with client.messages.stream(model=model, max_tokens=4000, system=EDITOR_SYSTEM,
                                    output_config={"effort": "low"}, **_editor_thinking(model),
                                    messages=[{"role": "user", "content": body}]) as stream:
            try:
                for ev in stream:
                    t = getattr(ev, "type", None)
                    elapsed = _clock() - t0
                    if elapsed > EDITOR_TOTAL_SECONDS:
                        raise _EditorGaveUp(f"not done after {elapsed:.1f}s")
                    if not out and not head and t != "text" and elapsed > EDITOR_FIRST_TOKEN_SECONDS:
                        raise _EditorGaveUp(f"no word after {elapsed:.1f}s")
                    if t != "text" or not ev.text:
                        continue
                    piece = pending + (headings.feed(ev.text) if headings else ev.text)
                    if not out and not head:  # nothing accepted yet (held back or shown): no leading space
                        piece = piece.lstrip()
                    words = piece.rstrip()
                    pending = piece[len(words):]
                    if not words:
                        continue
                    size += len(words)
                    if size > limit:
                        raise _EditorGaveUp(f"longer than {limit} characters")
                    if head is not None:
                        head += words
                        if len(head) < EDITOR_HEAD_CHARS or (len(head) < head_max and not _CJK.search(head)):
                            continue
                        words, head = _chinese_head(head), None
                    out.append(words)
                    yield words
                if head:  # a short edit, all of it held back
                    out.append(_chinese_head(head))
                    yield out[-1]
            except BaseException:
                self._record_partial(stream, slot.index, model)
                raise
            msg = stream.get_final_message()
        usage = CallUsage.from_sdk(msg.usage)
        store.record_usage(self.db, user_id=self.user.id, thread_id=thread.id, feature="chat",
                           model=msg.model or model, key_slot=slot.index, usage=usage, stop_reason=msg.stop_reason)
        if msg.stop_reason != "end_turn":
            return None
        return "".join(out) or None

    @staticmethod
    def _done(thread: AiThread, turn_id: str, state: TurnState) -> dict[str, Any]:
        return {"thread_id": thread.id, "turn_id": turn_id, "model": thread.model,
                "stop_reason": state.display.stop_reason, "usage": state.usage.as_dict(), "disclaimer": DISCLAIMER}

    def _loop(self, thread: AiThread, new: list[dict[str, Any]], state: TurnState, ctx: ToolContext):
        rounds = self.settings.ai_deep_max_tool_rounds if self.deep else self.settings.ai_max_tool_rounds
        for _ in range(max(1, rounds)):
            first_text = [True]
            final, slot_index = yield from self._call(thread.model, new, state, first_text)
            self._segments(final, state)
            usage = CallUsage.from_sdk(final.usage)
            state.usage.add(usage)
            state.context_tokens = usage.prompt_tokens + usage.output_tokens
            state.display.stop_reason = final.stop_reason
            store.record_usage(self.db, user_id=self.user.id, thread_id=thread.id, feature="chat",
                               model=final.model or thread.model, key_slot=slot_index, usage=usage,
                               stop_reason=final.stop_reason)
            if final.stop_reason == "refusal":
                # Classifier or model decline: no server-side fallback on this model. Never run the turn's tools;
                # drop the turn from the context and tell the user to rephrase.
                state.display.text = ""
                state.held_from = None
                state.segments.clear()
                state.display.error = {"code": "refusal", "message": REFUSAL_MESSAGE}
                yield "error", state.display.error
                return False
            new.append({"role": "assistant", "content": [b.to_dict(mode="json") for b in final.content]})
            if final.stop_reason == "pause_turn":
                continue  # the server resumes from the trailing server_tool_use
            tool_uses = [b for b in final.content if b.type == "tool_use"]
            if final.stop_reason == "max_tokens":
                code = "max_tokens" if tool_uses else "truncated"
                state.display.error = {"code": code, "message": _ERRORS[code]}
                yield "error", state.display.error
                return not tool_uses  # a cut-off tool call cannot stay in the history
            if final.stop_reason == "tool_use" and tool_uses:
                results = yield from self._run_tools(tool_uses, state, ctx)
                new.append({"role": "user", "content": results})
                continue
            return True  # end_turn / stop_sequence
        raise ChatFailure("too_many_steps")

    def _run_tools(self, tool_uses: list[Any], state: TurnState, ctx: ToolContext):
        """Run one round's client tools; returns a ``tool_result`` for every ``tool_use``, in the model's order (one
        user message). The read-only tools of a round run side by side, each on a session of its own (2026-11-16: a
        why-question's overview and news lookups ran one after the other); ``SEQUENTIAL_TOOLS`` run after them, one at
        a time, on the turn's session. ``done`` events, and what each result adds to the turn (outlets, citable news,
        draft and chart cards), follow the model's order, so nothing depends on which tool finished first."""
        began = self.timing.at()
        labels = {tu.id: tool_label(tu.name, tu.input if isinstance(tu.input, dict) else {}) for tu in tool_uses}
        together = [tu for tu in tool_uses if tu.name not in SEQUENTIAL_TOOLS]
        sessions = self._tool_sessions() if len(together) > 1 else None
        if sessions is None:
            together = []
        outcomes: dict[str, ToolOutcome] = {}
        seconds: dict[str, float] = {}
        if together:
            for tu in together:
                yield from self._tool_running(tu, labels[tu.id], state)
            user_id = ctx.user.id  # read here: the turn's objects stay on this thread
            pool = ThreadPoolExecutor(max_workers=min(len(together), MAX_PARALLEL_TOOLS), thread_name_prefix="ai-tool")
            try:
                futures = [pool.submit(_run_apart, sessions, ctx, user_id, tu.name, tu.input) for tu in together]
                for tu, fut in zip(together, futures, strict=True):
                    try:
                        outcomes[tu.id], seconds[tu.id] = fut.result()
                    except Exception:  # it could not get a session of its own: run it here instead
                        log.warning("AI tool %s could not run on its own session; running it here", tu.name,
                                    exc_info=True)
                        outcomes[tu.id], seconds[tu.id] = _run_here(ctx, tu.name, tu.input)
                    yield from self._tool_done(tu, labels[tu.id], outcomes[tu.id], state)
            finally:  # the browser went away: tools still running finish on their own and close their sessions
                pool.shutdown(wait=False, cancel_futures=True)
        for tu in tool_uses:
            if tu.id in outcomes:
                continue
            yield from self._tool_running(tu, labels[tu.id], state)
            outcomes[tu.id], seconds[tu.id] = _run_here(ctx, tu.name, tu.input)
            yield from self._tool_done(tu, labels[tu.id], outcomes[tu.id], state)
        each = ", ".join(f"{tu.name} {seconds[tu.id]:.2f}" for tu in tool_uses)
        self.timing.note(f"tools {self.timing.at() - began:.2f}{' parallel' if together else ''} [{each}]")
        results: list[dict[str, Any]] = []
        for tu in tool_uses:
            outcome = outcomes[tu.id]
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tu.id, "content": outcome.content}
            if outcome.is_error:
                result["is_error"] = True
            results.append(result)
        return results

    def _tool_sessions(self) -> Callable[[], Session] | None:
        """Sessions for tools that run side by side: on the engine of the turn's session, so they see the same
        database. None (run them one at a time) when that session is not on an engine of its own."""
        if self.sessions is not None:
            return self.sessions
        try:
            bind = self.db.get_bind()
        except Exception:  # pragma: no cover - an unbound session
            return None
        return sessionmaker(bind, expire_on_commit=False) if isinstance(bind, Engine) else None

    @staticmethod
    def _tool_running(tu: Any, label: str, state: TurnState) -> Iterator[Event]:
        state.display.tools.append({"name": tu.name, "label": label})
        yield "tool", {"id": tu.id, "name": tu.name, "status": "running", "label": label}

    @staticmethod
    def _tool_done(tu: Any, label: str, outcome: ToolOutcome, state: TurnState) -> Iterator[Event]:
        if outcome.outlets:
            state.outlets.update(outcome.outlets)
        if isinstance(outcome.content, list):  # citable news: check the answer like a web search's
            state.used_web = True
        yield "tool", {"id": tu.id, "name": tu.name, "status": "error" if outcome.is_error else "done", "label": label}
        if outcome.draft is not None:
            state.display.draft_ids.append(outcome.draft["id"])
            yield "draft", outcome.draft
        if outcome.chart is not None:
            state.display.charts.append(outcome.chart)
            yield "chart", outcome.chart

    def _persist(self, thread: AiThread, turn_id: str, new: list[dict[str, Any]], ok: bool, message: str,
                 state: TurnState) -> None:
        served = self.served and self.slot is not None
        recap = self.recap if served and self.recap is not None and self.history is self.recap else None
        try:
            self.db.rollback()  # discard anything a failed tool left pending
            store.save_turn(self.db, thread, self.user, turn_id, new, in_context=ok, user_text=message,
                            display=state.display, context_tokens=state.context_tokens if ok else None,
                            key_slot=self.slot.index if served and self.slot is not None else None, recap=recap,
                            user_meta=self._user_meta())
        except Exception:  # pragma: no cover - persistence must never break the stream's shutdown
            log.exception("could not save AI turn %s", turn_id)

    def _user_meta(self) -> dict[str, Any]:
        """What the user's row remembers about the turn. A 深度搜尋 counts as ``AI_DEEP_SEARCH_COST`` questions once
        the model has answered a call of it; one that never reached the model (declined as off-topic, no key slot,
        a failure before anything came back) counts as an ordinary question."""
        if self.economy:
            return {"economy": True}
        if not self.deep:
            return {}
        plan = plans.plan_of(self.user, self.settings)
        return {"mode": "deep", "cost": store.deep_search_cost(self.settings, plan) if self.served else 1}

    def _page_symbol(self, symbol: str | None) -> tuple[str | None, str | None]:
        if not symbol:
            return None, None
        try:
            info = self.md.instrument(symbol)
        except Exception:  # pragma: no cover - market data hiccup: keep the raw symbol
            info = None
        return (info.symbol, info.name) if info else (symbol.strip().upper()[:20], None)
