"""Realtime updates (2026-11-17): the server tells open pages *that* something changed, and they refetch.

* :mod:`forliosa.realtime.events` — the topic catalog, audience tokens, NOTIFY encoding.
* :mod:`forliosa.realtime.capture` — events from every database write (ORM rows, plus :func:`emit` for Core
  statements), resolved and sent with the commit (PostgreSQL ``NOTIFY``; SQLite: this process only).
* :mod:`forliosa.realtime.hub` / :mod:`forliosa.realtime.pg` — the API process's fan-out to ``GET /api/v1/events``.

The contract for the web app is in docs/api-contract.md 「即時更新（2026-11-17）」.
"""

from forliosa.realtime.capture import LedgerFanout, emit, feed_visible, notify_now, set_origin
from forliosa.realtime.events import ADMINS, ALL, Event, discussion_audience, event, group, managers, user

__all__ = ["ADMINS", "ALL", "Event", "LedgerFanout", "discussion_audience", "emit", "event", "feed_visible", "group",
           "managers", "notify_now", "set_origin", "user"]
