"""Keep credentials that travel in URLs out of the logs.

* The access log (uvicorn) would otherwise record the OAuth callback's ``code`` / ``state`` and invite tokens
  (``/invites/<token>``).
* Group push (M5) calls URLs that *are* secrets: a Discord webhook (``/api/webhooks/<id>/<token>``) and the Telegram
  Bot API (``/bot<token>/<method>``); httpx logs every request URL at INFO, and a traceback can carry one too.

:func:`redact_url` replaces all of them with ``***``; :func:`install` adds the filter to the uvicorn and httpx loggers
and to every handler of the root logger (so records propagated from any logger, tracebacks included, are scrubbed).
``create_app`` and the worker call it after configuring logging.
"""

from __future__ import annotations

import logging
import re

_QUERY = re.compile(r"(?i)([?&](?:code|state|token|error_description)=)[^&#\s\"]*")
_INVITE = re.compile(r"(/invites/)[^/?#\s\"]+")
_WEBHOOK = re.compile(r"(?i)(/api/(?:v\d+/)?webhooks/)[^\s\"'?#]+")
_BOT_PATH = re.compile(r"(/bot)[^/\s\"']+")
_BOT_TOKEN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{30,}\b")


def redact_url(text: str) -> str:
    text = _QUERY.sub(r"\1***", text)
    text = _INVITE.sub(r"\1***", text)
    text = _WEBHOOK.sub(r"\1***", text)
    text = _BOT_PATH.sub(r"\1***", text)
    return _BOT_TOKEN.sub("***", text)


def _redact_arg(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)  # httpx passes URL objects, not strings
    clean = redact_url(text)
    return clean if clean != text else value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_url(record.msg)
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(_redact_arg(a) for a in record.args)
        elif isinstance(record.args, dict) and record.args:
            record.args = {k: _redact_arg(v) for k, v in record.args.items()}
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_url(record.exc_text)
        return True


def _add(target: logging.Logger | logging.Handler) -> None:
    if not any(isinstance(f, RedactingFilter) for f in target.filters):
        target.addFilter(RedactingFilter())


def install() -> None:
    for name in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        _add(logging.getLogger(name))
    for handler in logging.getLogger().handlers:
        _add(handler)
