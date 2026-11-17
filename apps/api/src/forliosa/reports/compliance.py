"""The compliance read (contract §11): after every rule check passed, Claude Haiku 5.5 (effort low, no server-side
fallback) reads each AI sentence — without refs or the data pack — for recommendations, price levels, direction calls,
futures direction, personal advice, ratings and other advice. An issue whose ``quote`` is not a passage of that
sentence is ignored (the model made it up). A failed call is tried once more (on another slot when the pool has no
reserved one); failing twice, the attempt publishes the data edition — compliance first.

If the API refuses structured output for the check model (contract §21), the request is sent again asking for plain
JSON, and the reply is parsed and checked by the server; later checks skip the schema.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

from forliosa.reports import calls
from forliosa.reports.prompts import CHECK_CATEGORIES, CHECK_SYSTEM, check_schema
from forliosa.reports.validate import sentences

log = logging.getLogger(__name__)

MAX_TOKENS = 4000
_NO_SCHEMA: set[str] = set()  # check models that refused output_config.format in this process
PLAIN_JSON = ('\n\n只輸出一個 JSON 物件：{"issues": [{"path": "…", "category": "…", "quote": "…"}]}，'
              "不要其他文字。")


def reset_state() -> None:
    _NO_SCHEMA.clear()


@dataclass
class Checked:
    ok: bool  # the read happened (False: both calls failed)
    issues: list[dict[str, Any]] = field(default_factory=list)
    msgs: list[tuple[Any, float]] = field(default_factory=list)
    error: str | None = None


def items(output: dict[str, Any], kind: str) -> list[dict[str, str]]:
    """Every AI sentence (title included) as ``{"path", "text"}``."""
    out = [{"path": "title", "text": str(output.get("title") or "")}] if output.get("title") else []
    out += [{"path": s.path, "text": s.text} for s in sentences(output, kind) if s.text]
    return out


def request(model: str, effort: str, payload: list[dict[str, str]], settings: Any = None) -> dict[str, Any]:
    plain = model in _NO_SCHEMA
    return calls.request(model=model, max_tokens=MAX_TOKENS, effort=effort,
                         system=CHECK_SYSTEM + (PLAIN_JSON if plain else ""),
                         messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                         schema=None if plain else check_schema(), settings=settings)


def parse(msg: Any, payload: list[dict[str, str]]) -> list[dict[str, Any]] | None:
    text = calls.text_of(msg).strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        return None
    by_path = {p["path"]: p["text"] for p in payload}
    out = []
    for it in data["issues"]:
        if not isinstance(it, dict):
            continue
        path, quote, cat = str(it.get("path") or ""), str(it.get("quote") or ""), str(it.get("category") or "")
        if cat not in CHECK_CATEGORIES or not quote or quote not in by_path.get(path, ""):
            continue  # not a passage of that sentence: ignored
        out.append({"path": path, "category": cat, "quote": quote})
    return out


def _schema_refused(exc: BaseException) -> bool:
    if not isinstance(exc, anthropic.BadRequestError):
        return False
    text = f"{getattr(exc, 'message', '')} {getattr(exc, 'body', '')}".lower()
    return any(w in text for w in ("output_config", "json_schema", "structured", "format"))


def check(output: dict[str, Any], kind: str, model: str, effort: str,
          call: Callable[[dict[str, Any], int], calls.CallResult], settings: Any = None) -> Checked:
    """``call(kw, attempt)``: attempt 1, then 2 (the pipeline picks the slot of each)."""
    payload = items(output, kind)
    res = Checked(ok=False)
    if not payload:
        res.ok = True
        return res
    for attempt in (1, 2):
        try:
            out = call(request(model, effort, payload, settings), attempt)
        except Exception as exc:
            if _schema_refused(exc) and model not in _NO_SCHEMA:
                _NO_SCHEMA.add(model)
                log.warning("market reports: %s refused structured output; the check asks for plain JSON", model)
                continue
            res.error = type(exc).__name__
            continue
        res.msgs.append((out.msg, out.seconds))
        issues = parse(out.msg, payload)
        if issues is None:
            res.error = "parse"
            continue
        res.ok, res.issues, res.error = True, issues, None
        return res
    return res
