"""Keep one-time credentials that travel in URLs out of the logs.

The access log (uvicorn) would otherwise record the OAuth callback's ``code`` / ``state`` and invite tokens
(``/invites/<token>``). :func:`redact_url` replaces them with ``***``; :func:`install` adds the filter to uvicorn's
access logger (``create_app`` calls it).
"""

from __future__ import annotations

import logging
import re

_QUERY = re.compile(r"(?i)([?&](?:code|state|token|error_description)=)[^&#\s\"]*")
_INVITE = re.compile(r"(/invites/)[^/?#\s\"]+")


def redact_url(text: str) -> str:
    return _INVITE.sub(r"\1***", _QUERY.sub(r"\1***", text))


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(redact_url(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact_url(record.msg)
        return True


def install() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(RedactingFilter())
