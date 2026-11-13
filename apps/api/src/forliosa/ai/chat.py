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

Prompt caching: one breakpoint on the frozen system prompt (tools render before it, so tools + system are
cached together) plus top-level automatic caching for the growing conversation. Everything that changes per
turn (time, page, privacy) is a ``role: "system"`` message after the user's message.

深度搜尋 (``mode="deep"``, one turn): the same loop with ``web_search`` allowed ``AI_DEEP_SEARCH_MAX_USES`` times and
``AI_DEEP_MAX_TOOL_ROUNDS`` rounds; what to research and how to write it up is in that turn's page context
(``prompts.DEEP_SEARCH_NOTE``), never in the frozen system prompt. The tool list differs from an ordinary turn only
in ``max_uses``, so that turn (and the one after it) misses the prompt cache. The user's row stores ``mode`` and how
many questions the turn counts as (``store.messages_today``).

Events (``event: <name>`` / ``data: <json>``):

* ``thread``    ``{id, title, created}`` – always first
* ``text``      ``{delta}``
* ``tool``      ``{id, name, status: running|done|error, label}``
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
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import anthropic
from sqlalchemy.orm import Session

from forliosa.ai import grounding, scope, store
from forliosa.ai.keypool import Failure, KeyPool, KeysBusy, KeySlot, NoKeyAvailable, classify_failure
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import CHAT_SYSTEM, DISCLAIMER, OFF_TOPIC_REPLY, page_context
from forliosa.ai.tools import (
    ToolContext,
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

REFUSAL_MESSAGE = "這個問題我沒辦法回答。可以換個方式問，或問問你的持股與個股資料。"
_ERRORS = {
    "ai_busy": "AI 服務目前忙碌，請稍後再試。",
    "ai_unavailable": "AI 服務暫時無法使用。",
    "ai_unreachable": "暫時連不上 AI 服務，請稍後再試。",
    "ai_error": "這次沒有成功，請再試一次；如果一直失敗，請開新對話。",
    "too_many_steps": "這個問題需要查太多資料了，請把問題拆小一點再問。",
    "max_tokens": "回答太長被截斷了，請把問題拆小一點再問。",
    "truncated": "回答太長，後面的部分沒有顯示。",
    "interrupted": "回覆中斷了。",
    "internal_error": "發生錯誤，請稍後再試。",
}
WEB_TOOLS = ("web_search", "web_fetch")
_THINKING_REJECTED = re.compile(r"bound to a different conversation|invalid `?signature`? in `?thinking`? block",
                                re.IGNORECASE)
# Models that rejected mid-conversation system messages: the page context is sent as a user-turn reminder.
_NO_SYSTEM_ROLE: set[str] = set()


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
    context_tokens: int | None = None
    segments: list[grounding.Segment] = field(default_factory=list)  # text blocks of the answer (cited or not)
    round_start: int | None = None  # where this call's text starts in display.text
    used_web: bool = False

    def add_text(self, s: str) -> None:
        self.display.text += s


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
                 now_fn: Callable[[], datetime] = now_taipei):
        self.db, self.user, self.md, self.pool, self.settings, self.now_fn = db, user, md, pool, settings, now_fn
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

    # -- request building --------------------------------------------------------------------------------
    def tools(self) -> list[dict[str, Any]]:
        # 深度搜尋 only raises how often web_search may run; the tool list is otherwise the same
        max_uses = self.settings.ai_deep_search_max_uses if self.deep else None
        return client_tool_definitions(self.settings) + server_tools(self.settings, max_uses=max_uses)

    def params(self, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": model,
            "max_tokens": self.settings.ai_max_tokens_chat,
            "system": [{"type": "text", "text": CHAT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            "tools": self.tools(),
            "messages": render_messages(messages, model not in _NO_SYSTEM_ROLE),
            "output_config": {"effort": self.settings.ai_effort_chat},
            "cache_control": {"type": "ephemeral"},
        }

    def _context(self) -> str:
        route, sym, name, privacy = self._page
        moved = self.recap is not None and self.history is self.recap
        return page_context(self.now_fn(), route, sym, name, privacy, moved=moved, deep=self.deep)

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
        if route.wait > 0:
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
            self.pool.sleep(1.0)
            return True
        return False

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
            try:
                with slot.client.messages.stream(**params) as stream:
                    for ev in stream:
                        for out in self._translate(ev, state, first_text_of_round):
                            emitted = True
                            yield out
                    final = stream.get_final_message()
                    headers = stream.response.headers
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

    def _translate(self, ev: Any, state: TurnState, first_text_of_round: list[bool]) -> Iterator[Event]:
        t = getattr(ev, "type", None)
        if t == "text":
            if first_text_of_round[0] and state.display.text and not state.display.text.endswith("\n"):
                state.add_text("\n\n")
                yield "text", {"delta": "\n\n"}
            first_text_of_round[0] = False
            if state.round_start is None:
                state.round_start = len(state.display.text)
            state.add_text(ev.text)
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
        db, settings = self.db, self.settings
        self.deep = mode == "deep" and settings.ai_web_search
        created = thread_id is None
        thread = (store.create_thread(db, self.user, message, store.model_for("chat", settings)) if created
                  else store.owned_thread(db, self.user, thread_id))
        self.thread = thread
        yield "thread", {"id": thread.id, "title": thread.title, "created": created}

        turn_id = new_id("trn")
        sym, name = self._page_symbol(symbol)
        self._page = (route, sym, name, privacy)
        new: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": message}]},
                                     {"role": "system", "content": self._context()}]
        self._new = new
        state = TurnState()

        off_topic = scope.precheck(message) if settings.ai_scope_precheck else None
        if off_topic is not None:  # clearly not about investing: decline without a model call
            log.info("AI chat: off-topic request (%s) declined without a model call", off_topic)
            state.display.text, state.display.stop_reason = OFF_TOPIC_REPLY, "off_topic"
            yield "text", {"delta": OFF_TOPIC_REPLY}
            self._persist(thread, turn_id, new[:1], False, message, state)
            yield "done", self._done(thread, turn_id, state)
            return

        ctx = ToolContext(db=db, user=self.user, md=self.md, thread_id=thread.id)
        ok = False
        try:
            self.costs = store.slot_month_costs(db)
            self.stored = store.api_history(db, thread)
            self._route()
            ok = yield from self._loop(thread, new, state, ctx)
            if ok and state.used_web:
                flagged = grounding.check(state.display.text, state.segments)
                if flagged:
                    state.display.grounding = flagged
                    yield "grounding", {"items": flagged}
        except GeneratorExit:
            state.display.error = {"code": "interrupted", "message": _ERRORS["interrupted"]}
            raise
        except ChatFailure as exc:
            state.display.error = {"code": exc.code, "message": _ERRORS.get(exc.code, _ERRORS["ai_error"])}
            yield "error", state.display.error
        except Exception:
            log.exception("AI chat turn failed")
            state.display.error = {"code": "internal_error", "message": _ERRORS["internal_error"]}
            yield "error", state.display.error
        finally:
            self._persist(thread, turn_id, new, ok, message, state)
        yield "done", self._done(thread, turn_id, state)

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
                results = []
                for tu in tool_uses:
                    label = tool_label(tu.name, tu.input if isinstance(tu.input, dict) else {})
                    state.display.tools.append({"name": tu.name, "label": label})
                    yield "tool", {"id": tu.id, "name": tu.name, "status": "running", "label": label}
                    outcome = execute(ctx, tu.name, tu.input)
                    yield "tool", {"id": tu.id, "name": tu.name, "status": "error" if outcome.is_error else "done",
                                   "label": label}
                    if outcome.draft is not None:
                        state.display.draft_ids.append(outcome.draft["id"])
                        yield "draft", outcome.draft
                    if outcome.chart is not None:
                        state.display.charts.append(outcome.chart)
                        yield "chart", outcome.chart
                    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tu.id, "content": outcome.content}
                    if outcome.is_error:
                        result["is_error"] = True
                    results.append(result)
                new.append({"role": "user", "content": results})
                continue
            return True  # end_turn / stop_sequence
        raise ChatFailure("too_many_steps")

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
        if not self.deep:
            return {}
        return {"mode": "deep", "cost": self.settings.ai_deep_search_cost if self.served else 1}

    def _page_symbol(self, symbol: str | None) -> tuple[str | None, str | None]:
        if not symbol:
            return None, None
        try:
            info = self.md.instrument(symbol)
        except Exception:  # pragma: no cover - market data hiccup: keep the raw symbol
            info = None
        return (info.symbol, info.name) if info else (symbol.strip().upper()[:20], None)
