"""The chat turn behind ``POST /ai/chat``: a streaming tool loop that yields SSE events.

Why a manual loop rather than the SDK's beta tool runner: every turn must stream text to the browser, forward
citations and server-tool progress as they happen, emit a ``draft`` event when ``draft_transaction`` runs,
retry a request on another API key when it fails *before* anything was streamed, and persist the exact
content blocks for append-only replay. The loop follows the skill's manual-loop rules: append the full
``response.content``; answer every ``tool_use`` with a matching ``tool_result`` in one user message
(``is_error`` for failures); re-send on ``pause_turn`` without adding a message; never run tools of a
``refusal`` or of a ``max_tokens`` turn.

Prompt caching: one breakpoint on the frozen system prompt (tools render before it, so tools + system are
cached together) plus top-level automatic caching for the growing conversation. Everything that changes per
turn (time, page, privacy) is a ``role: "system"`` message after the user's message.

Events (``event: <name>`` / ``data: <json>``):

* ``thread``   ``{id, title, created}`` – always first
* ``text``     ``{delta}``
* ``tool``     ``{id, name, status: running|done|error, label}``
* ``citation`` ``{url, title, cited_text}``
* ``draft``    the draft card (see ``tools.draft_card``)
* ``error``    ``{code, message}``
* ``done``     ``{thread_id, turn_id, model, stop_reason, usage}`` – always last
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anthropic
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.keypool import KeyPool, NoKeyAvailable, is_failover_error
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import CHAT_SYSTEM, page_context
from forliosa.ai.tools import ToolContext, client_tool_definitions, execute, server_tools, tool_label
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

    def add_text(self, s: str) -> None:
        self.display.text += s


def _classify(exc: BaseException) -> str:
    if isinstance(exc, NoKeyAvailable | anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return "ai_unavailable"
    if isinstance(exc, anthropic.APIConnectionError):
        return "ai_unreachable"
    if isinstance(exc, anthropic.APIStatusError) and is_failover_error(exc):
        return "ai_busy"
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
        self.key_index: int | None = None  # the key serving this turn (sticky across its calls)

    # -- request building --------------------------------------------------------------------------------
    def tools(self) -> list[dict[str, Any]]:
        return client_tool_definitions(self.settings) + server_tools(self.settings)

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

    # -- one streamed API call with key failover -----------------------------------------------------------
    def _call(self, model: str, messages: list[dict[str, Any]], state: TurnState,
              first_text_of_round: list[bool]) -> Iterator[Event]:
        last: BaseException | None = None
        json_retries = 0
        system_retry = False
        try:
            order = self.pool.attempt_order(prefer=self.key_index)
        except NoKeyAvailable as exc:
            raise ChatFailure("ai_unavailable", "no usable API key") from exc
        i = 0
        while i < len(order):
            slot = order[i]
            if slot.disabled:
                i += 1
                continue
            if i > 0 and slot in order[:i]:
                self.pool.sleep(1.0)  # single key: brief pause before the one retry
            emitted = False
            try:
                with slot.client.messages.stream(**self.params(model, messages)) as stream:
                    for ev in stream:
                        for out in self._translate(ev, state, first_text_of_round):
                            emitted = True
                            yield out
                    final = stream.get_final_message()
                self.pool.mark_success(slot)
                self.key_index = slot.index
                return final, slot.index
            except ValueError as exc:  # tool input JSON the SDK could not parse at all
                if emitted or json_retries >= 2:
                    raise ChatFailure("ai_error", f"unparseable tool input: {exc}") from exc
                json_retries += 1
                continue
            except anthropic.BadRequestError as exc:
                msg = str(exc.api_message or exc)
                if not system_retry and not emitted and "role" in msg and "system" in msg:
                    log.warning("model %s rejects mid-conversation system messages; using a reminder", model)
                    _NO_SYSTEM_ROLE.add(model)
                    system_retry = True
                    continue
                log.error("AI request rejected (key #%d): %s", slot.index, msg)
                raise ChatFailure("ai_error", msg) from exc
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                if emitted or not is_failover_error(exc):
                    raise ChatFailure(_classify(exc), str(exc)) from exc
                self.pool.mark_failure(slot, exc)
                last = exc
                i += 1
                continue
        raise ChatFailure(_classify(last) if last else "ai_unavailable", str(last or "no key"))

    def _translate(self, ev: Any, state: TurnState, first_text_of_round: list[bool]) -> Iterator[Event]:
        t = getattr(ev, "type", None)
        if t == "text":
            if first_text_of_round[0] and state.display.text and not state.display.text.endswith("\n"):
                state.add_text("\n\n")
                yield "text", {"delta": "\n\n"}
            first_text_of_round[0] = False
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
                yield "tool", {"id": b.id, "name": b.name, "status": "running", "label": label}
        elif t == "content_block_start":
            b = ev.content_block
            bt = getattr(b, "type", None)
            if bt in ("web_search_tool_result", "web_fetch_tool_result"):
                name = "web_search" if bt == "web_search_tool_result" else "web_fetch"
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

    # -- the turn ------------------------------------------------------------------------------------------
    def run(self, *, thread_id: str | None, message: str, route: str | None, symbol: str | None,
            privacy: bool) -> Iterator[Event]:
        db, settings = self.db, self.settings
        created = thread_id is None
        thread = (store.create_thread(db, self.user, message, store.model_for("chat", settings)) if created
                  else store.owned_thread(db, self.user, thread_id))
        yield "thread", {"id": thread.id, "title": thread.title, "created": created}

        turn_id = new_id("trn")
        sym, name = self._page_symbol(symbol)
        context = page_context(self.now_fn(), route, sym, name, privacy)
        new: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": message}]},
                                     {"role": "system", "content": context}]
        history = store.api_history(db, thread)
        state = TurnState()
        ctx = ToolContext(db=db, user=self.user, md=self.md, thread_id=thread.id)
        ok = False
        try:
            ok = yield from self._loop(thread, history, new, state, ctx)
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
        yield "done", {"thread_id": thread.id, "turn_id": turn_id, "model": thread.model,
                       "stop_reason": state.display.stop_reason, "usage": state.usage.as_dict()}

    def _loop(self, thread: AiThread, history: list[dict[str, Any]], new: list[dict[str, Any]], state: TurnState,
              ctx: ToolContext):
        for _ in range(max(1, self.settings.ai_max_tool_rounds)):
            first_text = [True]
            final, key_index = yield from self._call(thread.model, history + new, state, first_text)
            usage = CallUsage.from_sdk(final.usage)
            state.usage.add(usage)
            state.context_tokens = usage.prompt_tokens + usage.output_tokens
            state.display.stop_reason = final.stop_reason
            store.record_usage(self.db, user_id=self.user.id, thread_id=thread.id, feature="chat",
                               model=final.model or thread.model, key_index=key_index, usage=usage,
                               stop_reason=final.stop_reason)
            if final.stop_reason == "refusal":
                # Classifier or model decline: no server-side fallback on this model. Never run the turn's tools;
                # drop the turn from the context and tell the user to rephrase.
                state.display.text = ""
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
        try:
            self.db.rollback()  # discard anything a failed tool left pending
            store.save_turn(self.db, thread, self.user, turn_id, new, in_context=ok, user_text=message,
                            display=state.display, context_tokens=state.context_tokens if ok else None)
        except Exception:  # pragma: no cover - persistence must never break the stream's shutdown
            log.exception("could not save AI turn %s", turn_id)

    def _page_symbol(self, symbol: str | None) -> tuple[str | None, str | None]:
        if not symbol:
            return None, None
        try:
            info = self.md.instrument(symbol)
        except Exception:  # pragma: no cover - market data hiccup: keep the raw symbol
            info = None
        return (info.symbol, info.name) if info else (symbol.strip().upper()[:20], None)
