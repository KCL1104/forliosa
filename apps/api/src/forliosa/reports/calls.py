"""How the market reports call the Messages API (contract §4.3, §8.1, §9.1, §11): one place for the request shape.

Checked against the installed SDK (``anthropic`` 2.8.0): ``client.beta.messages.create`` / ``.stream`` take
``fallbacks`` (``"default"`` or a list), ``betas``, ``output_config`` (``effort`` and ``format``); the response's
``usage.iterations`` lists every attempt (``message``, ``fallback_message``, …) and ``stop_details`` carries a refusal's
category.

* Server-side fallbacks (``betas=["server-side-fallback-2026-07-01"]``, ``fallbacks="default"``) on the gathering and
  writing calls when AI_MREPORT_FALLBACKS is on; never on Claude Haiku 5.5 (it has none).
* No ``thinking`` parameter (adaptive by default on these models; Opus 5.5 rejects ``disabled``), no assistant prefill,
  no forced ``tool_choice``. Effort is always explicit in ``output_config`` (Opus 5.5 defaults to medium).
* Web search: the repo's ``web_search_20260318`` with ``allowed_callers: ["direct"]`` (dynamic filtering off) and one
  ``allowed_domains`` list (:data:`REPORT_SEARCH_DOMAINS`) — never ``blocked_domains``.
* Timeouts: the key pool's clients default to 120 s without SDK retries; a writing call gets
  AI_MREPORT_TIMEOUT_SECONDS (900) through ``client.with_options``.
* Fallback (§21): if the API refuses ``fallbacks`` together with structured output (a 400 naming fallbacks), the same
  request is sent once more without them, and later structured requests skip them (logged; never silently).
* The reports' own key slot (:func:`report_slot`): with ``CLAUDE_API_KEY_4`` configured the reports use only that slot
  (``pool.call(fn, only=slot)``) and never borrow a shared one; without it they share the pool.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from forliosa.ai.tools import USER_LOCATION
from forliosa.config import Settings, get_settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_SERVER_FALLBACK = frozenset({"claude-haiku-5-5"})
WEB_SEARCH_TYPE = "web_search_20260318"  # the repo's version (ai.tools.server_tools)

# allowed_domains for the gathering (one list; never blocked_domains)
REPORT_SEARCH_DOMAINS = (
    "money.udn.com", "ctee.com.tw", "moneydj.com", "cnyes.com", "cna.com.tw", "focustaiwan.tw", "ec.ltn.com.tw",
    "cnbc.com", "bloomberg.com", "technews.tw", "digitimes.com.tw", "digitimes.com", "businesstoday.com.tw",
    "wealth.com.tw", "cbc.gov.tw", "dgbas.gov.tw", "stat.gov.tw", "mof.gov.tw", "moea.gov.tw", "ndc.gov.tw",
    "fsc.gov.tw", "federalreserve.gov", "bls.gov", "bea.gov", "treasury.gov",
)
# Not in the list on purpose: the API answers 400 "not accessible to our user agent" when these are in
# allowed_domains (2026-11-17); and the exchanges' sites (their figures come from the archive, never from search).
EXCLUDED_SEARCH_DOMAINS = ("reuters.com", "wsj.com", "ft.com", "apnews.com", "marketwatch.com", "barrons.com",
                           "twse.com.tw", "tpex.org.tw", "taifex.com.tw")

# (model, structured) pairs the API refused fallbacks for in this process (§21)
_FALLBACKS_REFUSED: set[tuple[str, bool]] = set()


def reset_state() -> None:
    _FALLBACKS_REFUSED.clear()


def web_search_tool(max_uses: int) -> dict[str, Any]:
    """The gathering's web search tool: the repo's version, direct calls only (no dynamic filtering), the report's
    domain list, Taipei as the user location, and the per-topic quota."""
    return {"type": WEB_SEARCH_TYPE, "name": "web_search", "max_uses": int(max_uses),
            "allowed_domains": list(REPORT_SEARCH_DOMAINS), "user_location": USER_LOCATION,
            "allowed_callers": ["direct"]}


def fallback_params(model: str, settings: Settings | None = None, structured: bool = False) -> dict[str, Any]:
    """``betas`` + ``fallbacks="default"`` for a model with server-side fallbacks, when switched on."""
    s = settings or get_settings()
    if not s.ai_mreport_fallbacks or model in NO_SERVER_FALLBACK or (model, structured) in _FALLBACKS_REFUSED:
        return {}
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}


def output_config(effort: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"effort": effort}
    if schema is not None:
        cfg["format"] = {"type": "json_schema", "schema": schema}
    return cfg


def request(*, model: str, max_tokens: int, messages: list[dict[str, Any]], effort: str,
            system: Any = None, tools: list[dict[str, Any]] | None = None, schema: dict[str, Any] | None = None,
            settings: Settings | None = None) -> dict[str, Any]:
    """The keyword arguments of one ``beta.messages.create`` / ``.stream`` call (no ``thinking``, no prefill)."""
    if messages and messages[-1].get("role") == "assistant":
        raise ValueError("no assistant prefill: the last message must be the user's")
    kw: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages,
                          "output_config": output_config(effort, schema)}
    if system is not None:
        kw["system"] = system
    if tools:
        kw["tools"] = tools
    kw.update(fallback_params(model, settings, structured=schema is not None))
    return kw


@dataclass
class CallResult:
    msg: Any
    seconds: float
    fallbacks_dropped: bool = False


def _fallback_refusal(exc: BaseException) -> bool:
    if not isinstance(exc, anthropic.BadRequestError):
        return False
    text = f"{getattr(exc, 'message', '')} {getattr(exc, 'body', '')}".lower()
    return "fallback" in text


def _without_fallbacks(kw: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in kw.items() if k != "fallbacks"}
    betas = [b for b in out.pop("betas", []) if b != FALLBACK_BETA]
    if betas:
        out["betas"] = betas
    return out


def _send(fn: Callable[[dict[str, Any]], Any], kw: dict[str, Any]) -> CallResult:
    started = time.monotonic()
    try:
        return CallResult(fn(kw), time.monotonic() - started)
    except anthropic.BadRequestError as exc:
        if "fallbacks" not in kw or not _fallback_refusal(exc):
            raise
        structured = "format" in (kw.get("output_config") or {})
        _FALLBACKS_REFUSED.add((kw["model"], structured))
        log.warning("market reports: the API refused fallbacks with %s (structured=%s); sent again without them",
                    kw["model"], structured)
        return CallResult(fn(_without_fallbacks(kw)), time.monotonic() - started, fallbacks_dropped=True)


def create(client: Any, kw: dict[str, Any], timeout: float | None = None) -> CallResult:
    """A non-streamed call (gathering, compliance check)."""
    c = client.with_options(timeout=timeout) if timeout else client
    return _send(lambda k: c.beta.messages.create(**k), kw)


def stream(client: Any, kw: dict[str, Any], timeout: float | None = None) -> CallResult:
    """A streamed call (writing; up to 15 minutes): the final message once the stream ends."""
    c = client.with_options(timeout=timeout) if timeout else client

    def run(k: dict[str, Any]) -> Any:
        with c.beta.messages.stream(**k) as s:
            return s.get_final_message()

    return _send(run, kw)


def stop_info(msg: Any) -> dict[str, Any]:
    """``stop_reason``, a refusal's ``category``, whether a fallback model served, and which model answered."""
    from forliosa.reports.accounting import fallback_used

    details = getattr(msg, "stop_details", None)
    category = getattr(details, "category", None) if details is not None else None
    if isinstance(details, dict):
        category = details.get("category")
    return {"stop_reason": getattr(msg, "stop_reason", None),
            "refusal_category": category if getattr(msg, "stop_reason", None) == "refusal" else None,
            "fallback_used": fallback_used(msg), "served_model": getattr(msg, "model", None)}


def text_of(msg: Any) -> str:
    return "".join(getattr(b, "text", "") for b in (getattr(msg, "content", None) or [])
                   if getattr(b, "type", None) == "text")


# -- key slot ------------------------------------------------------------------------------------------------------
def report_slot(pool: Any) -> int | None:
    """The reports' own slot when it is usable; ``None`` otherwise. With a reserved slot that is disabled or out of
    credit the caller publishes the data edition instead of borrowing a shared slot; with no reserved slot at all the
    caller uses ``pool.call(fn)`` (the shared slots) — :func:`has_reserved_slot` tells the two apart."""
    for n in sorted(getattr(pool, "reserved", ()) or ()):
        slot = pool.get(n)
        if slot is None:
            continue
        if pool.state(slot) in ("disabled", "exhausted"):
            return None
        return n
    return None


def has_reserved_slot(pool: Any) -> bool:
    return bool(getattr(pool, "reserved", None))
