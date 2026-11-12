"""A scripted fake of Discord webhooks and the Telegram Bot API (``httpx.MockTransport``) for the M5 push tests.

Requests are recorded (URL, JSON body); Discord answers ``discord_status`` (or the next scripted status), Telegram
answers the next scripted reply for a method (``ok`` by default; ``getUpdates`` returns the queued updates once).
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

from forliosa.services import pushers

TOKEN = "Tk" + "q7Rw" * 15 + "WXYZ"  # 66 characters; hint "WXYZ"
WEBHOOK = f"https://discord.com/api/webhooks/123456789012345678/{TOKEN}"
BOT_TOKEN = "1234567890:" + "AAH" + "x9Lm" * 9  # the shape of a Telegram bot token
BOT_USERNAME = "ForliosaBot"


@dataclass
class Sent:
    host: str
    path: str
    body: dict[str, Any]


@dataclass
class PushFake:
    discord_status: int = 204
    discord_script: deque = field(default_factory=deque)  # statuses (or exceptions) used before discord_status
    telegram_script: dict[str, deque] = field(default_factory=dict)  # method -> (status, body) replies
    updates: list[dict[str, Any]] = field(default_factory=list)
    sent: list[Sent] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.sent.append(Sent(request.url.host, request.url.path, body))
        if request.url.host in ("discord.com", "discordapp.com"):
            status = self.discord_script.popleft() if self.discord_script else self.discord_status
            if isinstance(status, Exception):
                raise status
            if status == 302:
                return httpx.Response(302, headers={"Location": "https://example.com/elsewhere"})
            if status == 429:
                return httpx.Response(429, json={"message": "rate limited", "retry_after": 3.5})
            return httpx.Response(status, json={} if status != 204 else None)
        if request.url.host == "api.telegram.org":
            method = request.url.path.rsplit("/", 1)[-1]
            script = self.telegram_script.get(method)
            if script:
                status, reply = script.popleft()
                return httpx.Response(status, json=reply)
            if method == "getUpdates":
                updates, self.updates = self.updates, []
                return httpx.Response(200, json={"ok": True, "result": updates})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.sent)}})
        return httpx.Response(599)

    def install(self) -> PushFake:
        pushers.set_transport(httpx.MockTransport(self.handler))
        return self

    @property
    def discord(self) -> list[Sent]:
        return [s for s in self.sent if s.host in ("discord.com", "discordapp.com")]

    def telegram(self, method: str = "sendMessage") -> list[Sent]:
        return [s for s in self.sent if s.host == "api.telegram.org" and s.path.endswith(f"/{method}")]


def tg_message(update_id: int, chat_id: int, text: str, *, title: str = "家族投資群", chat_type: str = "supergroup",
               date: int | None = None, **extra: Any) -> dict[str, Any]:
    import time

    msg = {"message_id": update_id, "date": int(time.time()) if date is None else date,
           "chat": {"id": chat_id, "type": chat_type, "title": title}, "text": text, **extra}
    return {"update_id": update_id, "message": msg}
