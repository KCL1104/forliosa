"""Outbound pushes to group channels: Discord webhooks and the Telegram Bot API (docs/api-contract.md 「分享（M5）」→
「推播」).

Both URLs are secrets (the webhook token, the bot token), so: requests never follow redirects; nothing here logs a
URL, a response body or an exception message (failures become short labels such as ``http_404`` or ``timeout``, safe
to store in ``notification_outbox.last_error``); and ``logredact`` scrubs both kinds of URL from every log record.

* Discord: the webhook URL must parse to host ``discord.com`` or ``discordapp.com`` with no user info and no port, path
  ``/api/webhooks/{id}/{token}``, no query or fragment (:func:`parse_webhook_url`). Every message carries
  ``allowed_mentions: {"parse": []}`` (names and text can never ping @everyone, roles or users) and the
  ``SUPPRESS_EMBEDS`` flag (no link previews, as on Telegram). 401 / 404 → the channel is disabled
  (``webhook_invalid``).
* Telegram: plain text (no ``parse_mode``), link previews off. 403 → disabled (``bot_removed``), 400 "chat not found" →
  disabled (``chat_not_found``), ``parameters.migrate_to_chat_id`` → the caller moves the channel to the new chat id.
* 429 (with ``retry_after``), 5xx, timeouts and network errors are retryable; other failures are not.
* **Every value a user chose** (display names, group names) and every other dynamic value goes into a message through
  :func:`user_text`: one line (``textsafe.one_line``), on Discord with its markdown escaped, on Telegram with a
  full-width ＠ (a plain-text @name would mention someone).
* **Circuit breaker** (process-wide): Discord temporarily bans an IP address that makes 10,000 invalid requests (401 /
  403 / 429) in 10 minutes, and Discord login runs on the same API server. Once webhook requests got
  :data:`BREAKER_THRESHOLD` such answers within 10 minutes, no webhook request is made for 10 minutes
  (``paused``, retryable with ``retry_after``).

Tests replace the transport (:func:`set_transport`); the default test fixture refuses every request.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from forliosa.textsafe import discord_escape, one_line

log = logging.getLogger("forliosa.pushers")

DISCORD_HOSTS = ("discord.com", "discordapp.com")
WEBHOOK_PATH = re.compile(r"^/api/webhooks/(\d{15,25})/([A-Za-z0-9_\-]{30,100})$")
DISCORD_MAX_CHARS = 2000
SUPPRESS_EMBEDS = 1 << 2
DISCORD_INVALID = (401, 403, 429)  # what Discord counts towards its IP ban
BREAKER_THRESHOLD = 500  # a twentieth of Discord's 10,000 per 10 minutes
BREAKER_WINDOW_SECONDS = 600.0
BREAKER_PAUSE_SECONDS = 600.0
TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_MAX_CHARS = 4096
TIMEOUT_SECONDS = 10.0
USER_AGENT = "Forliosa (group push)"

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: route every Discord webhook / Telegram request through ``transport`` (e.g. ``httpx.MockTransport``)."""
    global _transport
    _transport = transport


class Breaker:
    """Counts Discord's invalid answers (401 / 403 / 429) in a sliding window; past the threshold, pauses."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._hits: deque[float] = deque()
        self._open_until = 0.0
        self._lock = threading.Lock()

    def remaining(self) -> float:
        """Seconds until webhook requests may be made again (0: they may)."""
        with self._lock:
            return max(0.0, self._open_until - self.clock())

    def record(self) -> None:
        with self._lock:
            now = self.clock()
            self._hits.append(now)
            while self._hits and self._hits[0] <= now - BREAKER_WINDOW_SECONDS:
                self._hits.popleft()
            if len(self._hits) >= BREAKER_THRESHOLD and self._open_until <= now:
                self._open_until = now + BREAKER_PAUSE_SECONDS
                self._hits.clear()
                log.warning("discord webhooks: %d invalid answers within %d minutes, pausing webhook requests "
                            "for %d minutes", BREAKER_THRESHOLD, BREAKER_WINDOW_SECONDS // 60,
                            BREAKER_PAUSE_SECONDS // 60)


discord_breaker = Breaker()


def reset_state() -> None:
    """Tests: a fresh circuit breaker."""
    global discord_breaker
    discord_breaker = Breaker()


def user_text(text: str, kind: str) -> str:
    """A dynamic value (above all a user-chosen name) for a ``kind`` message: one line; Discord markdown escaped;
    on Telegram ``@`` as a full-width ＠."""
    line = one_line(text)
    return discord_escape(line) if kind == "discord" else line.replace("@", "＠")


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None = None  # a short label (never a URL or response text)
    retry: bool = False
    retry_after: float | None = None
    disable: str | None = None  # the channel must be disabled, with this reason
    migrate_to: int | None = None  # Telegram: the group became a supergroup with this chat id
    data: Any = None  # Telegram ``result``


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=_transport,
                        headers={"User-Agent": USER_AGENT})


def _post(url: str, payload: dict[str, Any]) -> httpx.Response | SendResult:
    try:
        with _client() as client:
            return client.post(url, json=payload)
    except httpx.TimeoutException:
        return SendResult(False, "timeout", retry=True)
    except httpx.HTTPError:
        return SendResult(False, "network", retry=True)
    except Exception:  # anything else: its message or traceback could carry the secret URL, so only a label
        return SendResult(False, "error")


def _retry_after(response: httpx.Response, body: dict[str, Any] | None = None) -> float | None:
    for value in ((body or {}).get("retry_after"), ((body or {}).get("parameters") or {}).get("retry_after"),
                  response.headers.get("retry-after")):
        try:
            if value is not None:
                return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return None


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


# -- Discord ------------------------------------------------------------------------------------------------------
def parse_webhook_url(raw: str) -> str | None:
    """The canonical ``https://<host>/api/webhooks/<id>/<token>`` for a valid Discord webhook URL, else None."""
    if not raw or not raw.isascii() or any(c.isspace() or ord(c) < 32 for c in raw) or "\\" in raw:
        return None
    try:
        u = urlsplit(raw)
        port = u.port
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if (u.scheme != "https" or u.query or u.fragment or u.username is not None or u.password is not None
            or port is not None or u.netloc.lower() != host or host not in DISCORD_HOSTS):
        return None
    m = WEBHOOK_PATH.match(u.path)
    return f"https://{host}/api/webhooks/{m.group(1)}/{m.group(2)}" if m else None


def webhook_hint(url: str) -> str:
    """The last 4 characters of the webhook token (all a response ever shows)."""
    return url.rsplit("/", 1)[-1][-4:]


def webhook_id(url: str) -> str:
    """The webhook's id (the number before the token) of a canonical webhook URL."""
    return url.rsplit("/", 2)[-2]


def send_discord(url: str, content: str) -> SendResult:
    wait = discord_breaker.remaining()
    if wait > 0:
        return SendResult(False, "paused", retry=True, retry_after=wait)
    payload = {"content": content[:DISCORD_MAX_CHARS], "allowed_mentions": {"parse": []}, "flags": SUPPRESS_EMBEDS}
    r = _post(url, payload)
    if isinstance(r, SendResult):
        return r
    code = r.status_code
    if code in DISCORD_INVALID:
        discord_breaker.record()
    if 200 <= code < 300:
        return SendResult(True)
    if code in (401, 404):
        return SendResult(False, f"http_{code}", disable="webhook_invalid")
    if code == 429:
        return SendResult(False, "http_429", retry=True, retry_after=_retry_after(r, _json(r)))
    if code >= 500:
        return SendResult(False, f"http_{code}", retry=True)
    return SendResult(False, f"http_{code}")  # 3xx (redirects are never followed), 400, 403 …


# -- Telegram -------------------------------------------------------------------------------------------------------
def telegram_call(token: str, method: str, payload: dict[str, Any]) -> SendResult:
    r = _post(f"{TELEGRAM_API}/bot{token}/{method}", payload)
    if isinstance(r, SendResult):
        return r
    body = _json(r)
    code = r.status_code
    if code == 200 and body.get("ok"):
        return SendResult(True, data=body.get("result"))
    params = body.get("parameters") or {}
    migrate = params.get("migrate_to_chat_id")
    if migrate is not None:
        try:
            return SendResult(False, "migrated", retry=True, migrate_to=int(migrate))
        except (TypeError, ValueError):
            pass
    if code == 429:
        return SendResult(False, "http_429", retry=True, retry_after=_retry_after(r, body))
    if code == 403:
        return SendResult(False, "http_403", disable="bot_removed")
    if code == 400 and "chat not found" in str(body.get("description", "")).lower():
        return SendResult(False, "http_400", disable="chat_not_found")
    if code == 401 or code >= 500:  # 401: the bot token is wrong (server settings), not the channel
        return SendResult(False, f"http_{code}", retry=True)
    return SendResult(False, f"http_{code}")


def send_telegram(token: str, chat_id: int, text: str) -> SendResult:
    return telegram_call(token, "sendMessage", {"chat_id": chat_id, "text": text[:TELEGRAM_MAX_CHARS],
                                                "link_preview_options": {"is_disabled": True}})


TELEGRAM_UPDATES_LIMIT = 100  # the most getUpdates returns at once


def telegram_updates(token: str, offset: int | None) -> SendResult:
    payload: dict[str, Any] = {"timeout": 0, "limit": TELEGRAM_UPDATES_LIMIT,
                               "allowed_updates": ["message", "my_chat_member"]}
    if offset is not None:
        payload["offset"] = offset
    return telegram_call(token, "getUpdates", payload)
