"""The writing call (contract §9.1): the data pack and the verified reports in, the report JSON out — streamed (up to
AI_MREPORT_TIMEOUT_SECONDS), structured output, server-side fallbacks, no tools, no ``thinking`` parameter.

* Stopped at ``max_tokens``: the same request once more at effort ``medium`` (not a new attempt).
* A refusal that the fallbacks did not turn into an answer: the attempt ends with the data edition (the category is
  kept; no retry).
* One revision (:func:`revise`): the whole assistant reply goes back as it came (thinking blocks untouched), then a
  user turn listing the problems; same slot, same model and effort.

``call(kw)`` runs one request on the attempt's key slot and returns a :class:`calls.CallResult`; the pipeline books
every reply it gets back (:attr:`Written.msgs`). A call that raises does not lose the replies before it: the error is
kept in :attr:`Written.exc` (the pipeline books the replies, then ends the attempt as failed).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from forliosa.reports import calls
from forliosa.reports.prompts import OUTPUT_KEYS, WRITER_SYSTEM, available_charts, kind_instructions, pack_json
from forliosa.reports.prompts import revise_message as _revise_text
from forliosa.reports.prompts import schema as _schema
from forliosa.reports.settings import Writer

log = logging.getLogger(__name__)

MAX_TOKENS = {"premarket": 64000, "close": 64000, "weekly": 128000}


@dataclass
class Written:
    output: dict[str, Any] | None = None
    msgs: list[tuple[str, str, str, Any, float]] = field(default_factory=list)  # (step, model, effort, msg, seconds)
    messages: list[dict[str, Any]] = field(default_factory=list)  # the conversation so far (for the revision)
    last: Any = None  # the reply the output came from
    refusal: str | None = None  # a refusal's category ("" when the API gave none)
    error: str | None = None  # a short label: parse | schema | max_tokens | exception name
    exc: BaseException | None = None  # a call that raised (after the replies in ``msgs``)


def system() -> list[dict[str, Any]]:
    return [{"type": "text", "text": WRITER_SYSTEM, "cache_control": {"type": "ephemeral"}}]


def first_messages(kind: str, pack: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"role": "user", "content": [
        {"type": "text", "text": pack_json(pack)},
        {"type": "text", "text": kind_instructions(kind, pack), "cache_control": {"type": "ephemeral"}},
    ]}]


def request(kind: str, pack: dict[str, Any], writer: Writer, messages: list[dict[str, Any]],
            settings: Any = None, effort: str | None = None) -> dict[str, Any]:
    return calls.request(model=writer.model, max_tokens=MAX_TOKENS[kind], effort=effort or writer.effort,
                         system=system(), messages=messages, schema=_schema(kind, available_charts(pack)),
                         settings=settings)


def conforms(output: Any, kind: str) -> bool:
    """The server's own check of the structured output: an object with every key of the kind, lists where lists
    are expected, sentences with ``text`` and ``refs``."""
    if not isinstance(output, dict) or any(k not in output for k in OUTPUT_KEYS[kind]):
        return False
    if not isinstance(output.get("title"), str):
        return False
    for k in OUTPUT_KEYS[kind]:
        if k in ("title", "summary", "chart_of_day"):
            continue
        if not isinstance(output[k], list):
            return False
    if kind == "weekly" and not isinstance(output.get("summary"), dict):
        return False
    return isinstance(output.get("chart_of_day"), dict)


def parse(msg: Any, kind: str) -> tuple[dict[str, Any] | None, str | None]:
    text = calls.text_of(msg).strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        out = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, "parse"
    if not conforms(out, kind):
        return None, "schema"
    return out, None


def _assistant(msg: Any) -> dict[str, Any]:
    return {"role": "assistant", "content": [b.to_dict(mode="json") if hasattr(b, "to_dict") else b
                                             for b in (getattr(msg, "content", None) or [])]}


def _run(w: Written, step: str, kind: str, pack: dict[str, Any], writer: Writer, messages: list[dict[str, Any]],
         call: Callable[[dict[str, Any]], calls.CallResult], settings: Any) -> None:
    effort = writer.effort
    for again in (False, True):
        try:
            res = call(request(kind, pack, writer, messages, settings, effort))
        except Exception as exc:  # the replies so far stay in ``w.msgs`` to be booked
            w.exc, w.error = exc, type(exc).__name__[:200]
            log.warning("market report %s: the %s call failed (%s)", kind, step, w.error)
            return
        w.msgs.append((step, writer.model, effort, res.msg, res.seconds))
        stop = getattr(res.msg, "stop_reason", None)
        if stop == "refusal":
            w.refusal = calls.stop_info(res.msg).get("refusal_category") or ""
            w.error = "refusal"
            return
        if stop == "max_tokens" and not again:
            effort = "medium"  # once more at medium in the same attempt
            continue
        if stop == "max_tokens":
            w.error = "max_tokens"
            return
        out, err = parse(res.msg, kind)
        w.messages, w.last = messages, res.msg
        if out is None:
            w.error = err
            return
        w.output, w.error = out, None
        return


def write(kind: str, pack: dict[str, Any], writer: Writer, call: Callable[[dict[str, Any]], calls.CallResult],
          settings: Any = None) -> Written:
    """The first draft."""
    w = Written()
    _run(w, "write", kind, pack, writer, first_messages(kind, pack), call, settings)
    return w


def revise(kind: str, pack: dict[str, Any], writer: Writer, call: Callable[[dict[str, Any]], calls.CallResult],
           draft: Written, problems: list[dict[str, Any]], settings: Any = None) -> Written:
    """One revision of ``draft``: its reply sent back unchanged, then the problems."""
    w = Written()
    messages = [*draft.messages, _assistant(draft.last), {"role": "user", "content": _revise_text(problems)}]
    _run(w, "revise", kind, pack, writer, messages, call, settings)
    return w
