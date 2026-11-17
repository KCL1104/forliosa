"""Realtime invalidation events: the catalog, the wire / NOTIFY encoding and the audience tokens.

An event says *that* something changed (a topic and a few ids the recipient can already see), never *what*: the
browser refetches through the normal endpoints, so every authorization rule and projection stays where it is.

Audience tokens (``Event.to``):

* ``u:<user id>`` — that user's connections.
* ``all`` — every signed-in connection; ``admins`` — connections of site admins (``ADMIN_EMAILS``).
* ``g:<group id>`` / ``gm:<group id>`` — the group's current members / its owner and admins. Symbolic: resolved to
  ``u:`` tokens in the writing transaction (``realtime.capture``), so the hub only ever sees concrete audiences.

Topics starting with ``_`` are hub operations (a session or an account is gone); they never reach a browser.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any

log = logging.getLogger(__name__)

CHANNEL = "forliosa_rt_v1"  # the Postgres NOTIFY channel (versioned: a format change can run side by side)
NOTIFY_LIMIT = 7000  # bytes; Postgres refuses payloads of 8000 or more

# Wire topics and the payload keys each may carry (an allow-list: anything else is dropped before it leaves).
TOPICS: dict[str, frozenset[str]] = {
    "ledger": frozenset({"account_id"}),
    "ledger.viewas": frozenset({"delegation_id"}),
    "recurring": frozenset(),
    "watchlist": frozenset(),
    "me": frozenset(),
    "delegations": frozenset(),
    "groups.list": frozenset(),
    "group.meta": frozenset({"group_id"}),
    "group.members": frozenset({"group_id"}),
    "group.ledger": frozenset({"group_id"}),
    "group.comments": frozenset({"group_id", "target"}),
    "group.reports": frozenset({"group_id"}),
    "group.channels": frozenset({"group_id"}),
    "group.invites": frozenset({"group_id"}),
    "group.deleted": frozenset({"group_id"}),
    "discussions.topic": frozenset({"topic_id"}),
    "discussions.list": frozenset({"scope", "group_id"}),
    "ai.usage": frozenset(),
    "ai.briefings": frozenset(),
    "ai.threads": frozenset(),
    "reports.seen": frozenset(),
    "market.closes": frozenset({"market", "date"}),
    "market.overview": frozenset(),
    "market.reports": frozenset({"report_id", "kind"}),
    "admin.reports": frozenset(),
    "admin.discussions": frozenset(),
}
# Hub operations (never sent): arguments in ``data``.
OPS: dict[str, frozenset[str]] = {
    "_session.gone": frozenset({"s"}),  # a login session ended (logout): its streams close
    "_user.gone": frozenset({"u"}),  # an account was deleted: its streams close
}
# Frames the hub writes itself (not events of the catalog).
CONTROL = frozenset({"hello", "resync", "bye"})
ALL = "all"
ADMINS = "admins"


@dataclass(slots=True)
class Event:
    """``echo``: the origin tab id may be attached for the origin user's own connections (the tab that made the change
    already invalidated the same keys). Derived fan-outs (``group.ledger``, ``ledger.viewas`` …) set it off: the
    origin tab's own mutation does not cover them. ``ou`` / ``o``: origin user and tab (internal, never on the wire
    except ``o`` to the origin user)."""

    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    to: tuple[str, ...] = ()
    echo: bool = True
    ou: str | None = None
    o: str | None = None

    @property
    def is_op(self) -> bool:
        return self.topic.startswith("_")

    def merge_key(self) -> tuple:
        """Events equal but for their audiences merge into one."""
        return self.topic, _canon(self.data), self.echo, self.ou, self.o

    def with_origin(self, ou: str | None, o: str | None) -> Event:
        return replace(self, ou=ou, o=o) if (ou or o) and self.ou is None and self.o is None else self


def _canon(d: dict[str, Any]) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def event(topic: str, data: dict[str, Any] | None = None, to: tuple[str, ...] | list[str] = (),
          echo: bool = True) -> Event:
    """Build an event; payload keys outside the topic's allow-list are dropped (and logged by name, never value)."""
    allowed = TOPICS.get(topic) if not topic.startswith("_") else OPS.get(topic)
    if allowed is None:
        raise ValueError(f"unknown realtime topic {topic!r}")
    data = {k: v for k, v in (data or {}).items() if v is not None}
    extra = set(data) - allowed
    if extra:
        log.error("realtime: dropped keys %s from topic %s (not in its allow-list)", sorted(extra), topic)
        data = {k: v for k, v in data.items() if k in allowed}
    return Event(topic, data, tuple(dict.fromkeys(to)), echo)


def user(uid: str | None) -> tuple[str, ...]:
    return (f"u:{uid}",) if uid else ()


def group(gid: str | None) -> tuple[str, ...]:
    return (f"g:{gid}",) if gid else ()


def managers(gid: str | None) -> tuple[str, ...]:
    return (f"gm:{gid}",) if gid else ()


def discussion_audience(scope: str | None, group_id: str | None) -> tuple[str, ...]:
    """Public topics: every signed-in connection; group topics: the group's members."""
    if scope == "group":
        return group(group_id)
    return (ALL,)


def wire_data(ev: Event) -> dict[str, Any]:
    """The payload a browser may see (allow-listed again here, the last gate before the wire)."""
    allowed = TOPICS.get(ev.topic, frozenset())
    return {k: v for k, v in ev.data.items() if k in allowed}


# -- NOTIFY encoding ---------------------------------------------------------------------------------------------
def encode(ev: Event) -> str:
    out: dict[str, Any] = {"t": ev.topic}
    if ev.data:
        out["d"] = ev.data
    if ev.to:
        out["a"] = list(ev.to)
    if not ev.echo:
        out["e"] = 0
    if ev.ou:
        out["ou"] = ev.ou
    if ev.o:
        out["o"] = ev.o
    return json.dumps(out, separators=(",", ":"), ensure_ascii=False, default=str)


def decode(payload: str) -> Event | None:
    """A NOTIFY payload back into an event; None for anything malformed or unknown (logged without the payload)."""
    try:
        raw = json.loads(payload)
        topic = raw["t"]
        if not isinstance(topic, str) or (topic not in TOPICS and topic not in OPS):
            raise ValueError("unknown topic")
        data = raw.get("d") or {}
        to = raw.get("a") or []
        if not isinstance(data, dict) or not isinstance(to, list) or not all(isinstance(a, str) for a in to):
            raise ValueError("bad shape")
        ou, o = raw.get("ou"), raw.get("o")
        return Event(topic, data, tuple(to), raw.get("e", 1) != 0, ou if isinstance(ou, str) else None,
                     o if isinstance(o, str) else None)
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("realtime: ignored a malformed notification (%s)", type(exc).__name__)
        return None


def split_for_notify(ev: Event, limit: int = NOTIFY_LIMIT) -> list[str]:
    """NOTIFY payloads for one event: a long audience list is split over several payloads of the same event."""
    whole = encode(ev)
    if len(whole.encode()) <= limit or len(ev.to) <= 1:
        return [whole] if len(whole.encode()) <= limit else []
    half = len(ev.to) // 2
    return (split_for_notify(replace(ev, to=ev.to[:half]), limit)
            + split_for_notify(replace(ev, to=ev.to[half:]), limit))
