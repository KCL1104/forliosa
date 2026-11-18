"""Every write route has a realtime decision, and the decision is checked.

* ``ANNOUNCES``: endpoint (module.function) → the topics it announces. A new POST / PUT / PATCH / DELETE route fails
  :func:`test_every_write_route_has_a_realtime_decision` until someone writes down what it announces (most need
  nothing more than the ORM capture of the rows they write) or adds it to ``NO_EVENT``.
* :func:`test_the_route_announces_what_the_table_says` drives each route through the API (``SCENARIOS``) and asserts
  that every listed topic was committed. A route that cannot be driven here is in ``NOT_DRIVEN`` with the reason and
  the test that covers its rows instead; :func:`test_every_announcing_route_is_driven` keeps the three in step.
* Audiences (who receives each topic) are checked in ``test_capture.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from fastapi.routing import APIRoute

from forliosa.api.app import create_app
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.models import AiBriefing, AiDraft, AiThread
from forliosa.services import discussions as discussion_service
from forliosa.services import pushers
from forliosa.timeutil import today_taipei
from tests.api.discussions import Clock, post_reply, post_topic, set_name
from tests.api.m5 import API, SHARE_ALL, account, invite, join, login, make_group, me_id, token_of, trade
from tests.api.push_fake import WEBHOOK, PushFake


def T(*topics: str) -> frozenset[str]:
    return frozenset(topics)


ANNOUNCES: dict[str, frozenset[str]] = {
    "users.logout": T("_session.gone"),  # explicit: api.deps.destroy_session
    "users.patch_me": T("me", "group.members"),  # group.members: the display name in every group (+ delegations)
    "users.put_public_name": T("me"),
    "users.patch_preferences": T("me", "ledger", "ai.briefings"),  # ledger on cost_method, ai.briefings on the switch
    "users.delete_me": T("group.members", "delegations", "_user.gone"),  # explicit: services.account
    "users.accept_terms": T("me"),
    "accounts.create_account": T("ledger"),
    "accounts.update_account": T("ledger"),
    "accounts.delete_account": T("ledger", "delegations"),  # + the transactions' fan-out (explicit: Core delete)
    "accounts.delete_holding": T("ledger", "recurring"),  # recurring when plans are paused; ledger: explicit (Core)
    "market_reports.seen": T("reports.seen"),
    "transactions.create_transaction": T("ledger", "group.ledger", "ledger.viewas"),
    "transactions.create_batch": T("ledger"),  # once per account; none on a dry run
    "transactions.delete_batch": T("ledger"),
    "transactions.update_transaction": T("ledger"),
    "transactions.delete_transaction": T("ledger"),
    "watchlist.add_watchlist": T("watchlist"),
    "watchlist.remove_watchlist": T("watchlist"),
    "recurring.create_plan": T("recurring"),
    "recurring.update_plan": T("recurring"),
    "recurring.delete_plan": T("recurring"),
    "ai.chat": T("ai.usage", "ai.threads"),
    "ai.delete_all_threads": T("ai.threads"),  # explicit: ai.store (Core deletes)
    "ai.delete_thread": T("ai.threads"),
    "ai.update_draft": T("ai.threads"),
    "briefings.read": T("ai.briefings"),
    "delegations.create": T("delegations"),
    "delegations.update": T("delegations"),  # the account list is replaced (delete + insert)
    "delegations.remove": T("delegations"),
    "groups.create_group": T("groups.list"),
    "groups.patch_group": T("group.meta"),
    "groups.delete_group": T("group.deleted", "groups.list"),  # explicit: services.groups.purge
    "groups.transfer": T("group.members"),
    "groups.set_role": T("group.members"),
    "groups.remove_member": T("group.members", "groups.list", "group.invites"),  # invites: explicit (Core update)
    "groups.create_invite": T("group.invites"),
    "groups.revoke_invite": T("group.invites"),
    "groups.accept_invite": T("group.members", "groups.list"),
    "groups.put_share": T("group.members"),
    "groups.add_comment": T("group.comments"),
    "groups.delete_comment": T("group.comments"),
    "groups.put_reaction": T("group.comments"),
    "groups.delete_reaction": T("group.comments"),  # explicit (Core delete)
    "groups.attach_plan": T("group.meta", "me"),
    "groups.put_discord": T("group.channels", "group.meta", "group.members"),  # members: push switches reset (Core)
    "groups.patch_channel": T("group.channels"),
    "groups.delete_channel": T("group.channels", "group.meta"),
    "discussions.create_topic": T("discussions.list"),
    "discussions.delete_topic": T("discussions.topic", "discussions.list"),  # explicit (Core deletes)
    "discussions.create_reply": T("discussions.topic", "discussions.list"),
    "discussions.delete_reply": T("discussions.topic", "discussions.list"),
    "discussions.put_reaction": T("discussions.topic"),
    "discussions.delete_reaction": T("discussions.topic"),  # explicit (Core delete)
    "discussions.report": T("admin.discussions"),
    "discussions.moderate": T("discussions.topic", "discussions.list", "admin.discussions"),  # reports: explicit
    "discussions.create_suspension": T("admin.discussions", "me"),
    "discussions.lift_suspension": T("admin.discussions", "me"),
    "imports.read_statement": T("ai.usage"),  # the import itself is transactions.create_batch
    # batch 4 (2026-11-17 merge): 匯入庫存, 清除所有持倉, the blind test open to everyone
    "imports.read_positions": T("ai.usage"),  # reads only; its AiUsage row
    "imports.commit_positions": T("ledger", "group.ledger"),  # buys (capture) + 以券商為準's bulk delete (explicit)
    "portfolio.clear_records": T("ledger", "group.ledger", "recurring"),  # bulk delete (explicit) + paused plans
    "portfolio.put_allocation_limits": T("me", "ledger", "ledger.viewas"),  # users.preferences; viewers see them
    "market_reports.vote": T("admin.reports", "market.reports"),  # market.reports: the voter's own tabs only
    "admin.grant_member": T("me"),
    "admin.revoke_member": T("me"),
    "admin.grant_group_pass": T("me"),
    "admin.patch_group_pass": T("group.meta", "me"),
    "admin.revoke_group_pass": T("group.meta", "me"),
    "admin_reports.put_config": T("admin.reports", "market.reports"),  # market.reports when the mode changes
    "admin_reports.reveal": T("admin.reports", "market.reports"),  # market.reports: every reader of the open test
    "admin_reports.rebuild": T("market.reports", "admin.reports"),
    "admin_reports.vote": T("admin.reports"),
    "admin_reports.correction": T("market.reports", "admin.reports"),
}
# Deliberately silent.
NO_EVENT = {
    "users.dev_login",  # a new session; the user's other pages are not affected
    "transactions.preview_transaction",  # computes, writes nothing
    "recurring.draft",  # returns a draft; nothing is stored
    "stock.request_analyst_views",  # shared analyst views: the stock page asks again while it waits
    "groups.telegram_link",  # a one-time code; the channel appears when the bot sees /link (the worker's row)
    "admin.block_domain",  # news takedown: headlines are not pushed (stock pages refetch on their own)
    "admin.unblock_domain",
    "admin_reports.nyse_put",  # hand-kept calendar tables of the back office
    "admin_reports.nyse_delete",
    "admin_reports.macro_add",
    "admin_reports.macro_delete",
    "admin_reports.earnings_add",
    "admin_reports.earnings_delete",
}
# Routes this file cannot drive, with the test that covers the rows they write instead.
NOT_DRIVEN = {
    "ai.chat": "needs the Claude API; AiQuestion / AiUsage / AiMessage rows: test_ai_rows_announce_usage_and_threads",
    "imports.read_statement": "needs the Claude API; its AiUsage row: test_ai_rows_announce_usage_and_threads",
    "imports.read_positions": "needs the Claude API; its AiUsage row: test_ai_rows_announce_usage_and_threads",
    "admin_reports.rebuild": "needs the report pipeline's data; new version → test_capture.test_market_report_*",
    "admin_reports.correction": "needs a published report; new version → test_capture.test_market_report_*",
}


def write_routes() -> set[str]:
    def walk(routes):
        for r in routes:
            if isinstance(r, APIRoute):
                yield r
            elif hasattr(r, "original_router"):
                yield from walk(r.original_router.routes)
            elif hasattr(r, "routes"):
                yield from walk(r.routes)

    out = set()
    for r in walk(create_app().routes):
        if set(r.methods or ()) - {"GET", "HEAD", "OPTIONS"}:
            out.add(f"{r.endpoint.__module__.rsplit('.', 1)[-1]}.{r.endpoint.__name__}")
    return out


def test_every_write_route_has_a_realtime_decision():
    routes = write_routes()
    assert len(routes) > 60  # the walk found the routers
    undecided = routes - set(ANNOUNCES) - NO_EVENT
    assert not undecided, f"write routes without a realtime decision: {sorted(undecided)}"
    stale = (set(ANNOUNCES) | NO_EVENT) - routes
    assert not stale, f"listed routes that no longer exist: {sorted(stale)}"
    assert not set(ANNOUNCES) & NO_EVENT
    assert all(ANNOUNCES.values())  # a route that announces nothing belongs in NO_EVENT


def test_every_announcing_route_is_driven():
    covered = set(SCENARIOS) | set(NOT_DRIVEN)
    assert covered == set(ANNOUNCES), sorted(set(ANNOUNCES) ^ covered)
    assert not set(SCENARIOS) & set(NOT_DRIVEN)


# -- driving the routes ------------------------------------------------------------------------------------------
ADMIN = "boss@forliosa.local"


@dataclass
class W:
    """The world a scenario runs in: A (``a``, owner of group ``g``), B (``b``, a member who shares everything),
    a site admin, A's account ``acc``; ``act`` runs the route under test (the events before it are forgotten)."""

    a: object
    b: object
    admin: object
    a_id: str
    b_id: str
    g: dict
    acc: dict
    clock: Clock
    rt: object
    mp: pytest.MonkeyPatch

    def act(self, call: Callable[[], object]):
        self.rt.clear()
        r = call()
        assert r.status_code < 300, (r.status_code, r.text)
        return r


@pytest.fixture()
def w(app, client, rt, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", [ADMIN])
    monkeypatch.setattr(get_settings(), "terms_version", "2026-11-01")
    clock = Clock()
    discussion_service.set_clock(clock)
    PushFake().install()
    b = login(app, "b@forliosa.local", "小明")
    admin = login(app, ADMIN, "站長")
    g = make_group(client)
    join(client, b, g["id"], share=SHARE_ALL)
    set_name(client, "阿明")
    set_name(b, "小明明")
    yield W(client, b, admin, me_id(client), me_id(b), g, account(client), clock, rt, monkeypatch)
    discussion_service.set_clock(None)
    pushers.set_transport(None)


def _batch(w: W) -> dict:
    rows = [{"symbol": "2330", "type": "buy", "trade_date": f"2025-03-0{d}", "quantity": 100, "price": 600}
            for d in range(3, 5)]
    r = w.a.post(f"{API}/transactions/batch", json={"account_id": w.acc["id"], "origin": "import", "dry_run": False,
                                                    "rows": rows})
    assert r.status_code == 201, r.text
    return r.json()


def _plan(w: W, symbol: str = "0050.TW") -> dict:
    r = w.a.post(f"{API}/recurring", json={"account_id": w.acc["id"], "symbol": symbol, "amount": 5000,
                                            "day_of_month": [6]})
    assert r.status_code == 201, r.text
    return r.json()


def _delegation(w: W, **body) -> dict:
    r = w.a.post(f"{API}/delegations", json={"viewer_user_id": w.b_id, "scope": "all", **body})
    assert r.status_code == 201, r.text
    return r.json()


def _row(cls, **fields) -> str:
    with session_factory()() as db:
        row = cls(id=new_id("x"), **fields)
        db.add(row)
        db.commit()
        return row.id


def _group_pass(w: W) -> dict:
    until = (today_taipei() + timedelta(days=30)).isoformat()
    r = w.admin.post(f"{API}/admin/group-passes", json={"email": "demo@forliosa.local", "until": until})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _comment(w: W) -> dict:
    target = f"leaderboard:{today_taipei().isoformat()}"
    r = w.b.post(f"{API}/groups/{w.g['id']}/comments", json={"target": target, "body": "大家好"})
    assert r.status_code == 201, r.text
    return {**r.json(), "target": target}


def _discord(w: W, url: str = WEBHOOK):
    return w.a.put(f"{API}/groups/{w.g['id']}/channels/discord", json={"webhook_url": url})


def _draft(w: W) -> str:
    body = {"account_id": w.acc["id"], "symbol": "2330.TW", "type": "buy", "trade_date": "2025-03-04",
            "quantity": 1000, "price": 600, "source": "ai_draft"}
    preview = w.a.post(f"{API}/transactions/preview", json=body)
    assert preview.status_code == 200, preview.text
    return _row(AiDraft, user_id=w.a_id, payload=body, preview=preview.json(), notes=[])


def _suspension(w: W) -> dict:
    t = post_topic(w.b, w.clock)
    r = w.admin.post(f"{API}/admin/discussions/suspensions", json={"target": f"topic:{t['id']}", "days": 1})
    assert r.status_code in (200, 201), r.text
    return r.json()


def s_delete_me(w: W):
    _delegation(w)
    w.act(lambda: w.b.request("DELETE", f"{API}/me", json={"confirm": "刪除我的帳號"}))


def s_delete_account(w: W):
    _delegation(w, scope="accounts", account_ids=[w.acc["id"]])
    trade(w.a, w.acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)
    w.act(lambda: w.a.delete(f"{API}/accounts/{w.acc['id']}"))


def s_delete_holding(w: W):
    trade(w.a, w.acc["id"], "0050.TW", "buy", date(2025, 3, 4), 1000, 100)
    _plan(w)
    w.act(lambda: w.a.delete(f"{API}/accounts/{w.acc['id']}/holdings/0050.TW", params={"pause_plans": "true"}))


def s_create_transaction(w: W):
    _delegation(w)
    w.act(lambda: w.a.post(f"{API}/transactions", json={
        "account_id": w.acc["id"], "symbol": "2330.TW", "type": "buy", "trade_date": "2025-03-04", "quantity": 1000,
        "price": 600}))


def s_update_delegation(w: W):
    """A Core delete of the account list and a re-add: both parties hear of it."""
    other = account(w.a, "二")
    d = _delegation(w, scope="accounts", account_ids=[w.acc["id"]])
    w.act(lambda: w.a.patch(f"{API}/delegations/{d['id']}", json={"scope": "accounts", "account_ids": [other["id"]]}))
    assert {a[2:] for e in w.rt.find("delegations") for a in e.to} == {w.a_id, w.b_id}


def s_remove_member(w: W):
    invite(w.a, w.g["id"], multi_use=True)
    w.act(lambda: w.a.delete(f"{API}/groups/{w.g['id']}/members/{w.b_id}"))
    assert {a[2:] for a in w.rt.one("group.invites").to} == {w.a_id}  # managers only


def s_put_discord(w: W):
    """A first destination: the channels tab and the group header. Another destination later turns every other
    member's push switch off (a Core update, announced by hand)."""
    w.act(lambda: _discord(w))
    first = list(w.rt.events)
    assert w.b.put(f"{API}/groups/{w.g['id']}/share", json=SHARE_ALL).json()["push"] is True
    w.act(lambda: _discord(w, WEBHOOK.replace("123456789012345678", "223456789012345678")))
    assert {a[2:] for a in w.rt.one("group.members", group_id=w.g["id"]).to} == {w.a_id, w.b_id}
    w.rt.events[:0] = first


def s_moderate(w: W):
    t = post_topic(w.b, w.clock)
    assert w.a.post(f"{API}/discussions/reports", json={"target": f"topic:{t['id']}", "reason": "spam"}) \
        .status_code == 204
    w.act(lambda: w.admin.post(f"{API}/admin/discussions/moderation", json={"target": f"topic:{t['id']}",
                                                                             "action": "hide"}))


def _b_ledger(w: W) -> dict:
    """B (who shares everything with ``g``) with an account, a recent trade the feed shows and a running plan."""
    acc = account(w.b, "B 的帳戶")
    trade(w.b, acc["id"], "2330.TW", "buy", today_taipei() - timedelta(days=1), 1000, 600)
    r = w.b.post(f"{API}/recurring", json={"account_id": acc["id"], "symbol": "0050.TW", "amount": 5000,
                                           "day_of_month": [6]})
    assert r.status_code == 201, r.text
    return acc


def s_clear_records(w: W):
    """清除所有持倉 (a bulk delete): B's devices, the group B shares with (A and B), B's paused plan."""
    _b_ledger(w)
    w.act(lambda: w.b.delete(f"{API}/portfolio/records", params={"all_accounts": "true", "pause_plans": "true"}))
    assert {a[2:] for a in w.rt.one("group.ledger", group_id=w.g["id"]).to} == {w.a_id, w.b_id}
    assert all(e.to == (f"u:{w.b_id}",) for e in w.rt.find("ledger") + w.rt.find("recurring"))


def s_commit_positions(w: W):
    """匯入庫存 with 以券商為準: the replaced stock's bulk delete and the new buys, one ledger event per account."""
    acc = _b_ledger(w)
    w.act(lambda: w.b.post(f"{API}/imports/positions/commit", json={"account_id": acc["id"], "rows": [
        {"symbol": "2330", "quantity": 2000, "price": 590, "replace": True},
        {"symbol": "2317", "quantity": 1000, "price": 100}]}))
    assert w.rt.one("ledger").data == {"account_id": acc["id"]}
    assert {a[2:] for a in w.rt.one("group.ledger", group_id=w.g["id"]).to} == {w.a_id, w.b_id}


def _blind_test(w: W) -> str:
    """A blind-test close edition with A / B / C ready, the blind test open to every signed-in user."""
    from tests.api.test_market_report_trial_open import make_trial
    from tests.reports.conftest import seed_market

    w.mp.setattr(get_settings(), "market_reports_enabled", True)
    w.mp.setattr(get_settings(), "mreport_trial_audience", "all")
    with session_factory()() as db:
        seed_market(db)
    return make_trial()


def s_member_vote(w: W):
    rid = _blind_test(w)
    w.act(lambda: w.b.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "A"}))
    assert w.rt.one("market.reports").to == (f"u:{w.b_id}",)  # nobody else learns of a vote
    assert all(e.to == ("admins",) for e in w.rt.find("admin.reports"))


def s_admin_vote(w: W):
    rid = _blind_test(w)
    w.act(lambda: w.admin.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "B"}))


def s_reveal(w: W):
    _blind_test(w)
    w.act(lambda: w.admin.post(f"{API}/admin/market-reports/trial/reveal", json={"force": True}))
    assert w.rt.one("market.reports").to == ("all",)  # every reader of the open blind test sees the result


def s_allocation_limits(w: W):
    r = w.a.post(f"{API}/delegations", json={"viewer_user_id": w.b_id, "scope": "all"})
    assert r.status_code == 201, r.text
    w.act(lambda: w.a.put(f"{API}/portfolio/allocation/limits", json={"holding": 0.3, "industry": None}))
    assert w.rt.one("ledger.viewas").to == (f"u:{w.b_id}",)
    assert "group.ledger" not in w.rt.topics()  # no group sees the limits


SCENARIOS: dict[str, Callable[[W], None]] = {
    "users.logout": lambda w: w.act(lambda: w.b.post(f"{API}/auth/logout")),
    "users.patch_me": lambda w: w.act(lambda: w.a.patch(f"{API}/me", json={"display_name": "新名字"})),
    "users.put_public_name": lambda w: w.act(lambda: w.a.put(f"{API}/me/public-name", json={"public_name": "阿明二"})),
    "users.patch_preferences": lambda w: w.act(lambda: w.a.patch(f"{API}/me/preferences", json={
        "cost_method": "fifo", "daily_briefing": True})),
    "users.delete_me": s_delete_me,
    "users.accept_terms": lambda w: w.act(lambda: w.a.post(f"{API}/me/terms-accept", json={"version": "2026-11-01"})),
    "accounts.create_account": lambda w: (w.rt.clear(), account(w.a, "新帳戶")),
    "accounts.update_account": lambda w: w.act(lambda: w.a.patch(f"{API}/accounts/{w.acc['id']}", json={"name": "改"})),
    "accounts.delete_account": s_delete_account,
    "accounts.delete_holding": s_delete_holding,
    "market_reports.seen": lambda w: w.act(lambda: w.a.post(f"{API}/market/reports/seen")),
    "transactions.create_transaction": s_create_transaction,
    "transactions.create_batch": lambda w: (w.rt.clear(), _batch(w)),
    "transactions.delete_batch": lambda w: (lambda b: w.act(
        lambda: w.a.delete(f"{API}/transactions/batches/{b['batch_id']}")))(_batch(w)),
    "transactions.update_transaction": lambda w: (lambda t: w.act(
        lambda: w.a.patch(f"{API}/transactions/{t['id']}", json={"price": 610})))(
        trade(w.a, w.acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)),
    "transactions.delete_transaction": lambda w: (lambda t: w.act(
        lambda: w.a.delete(f"{API}/transactions/{t['id']}")))(
        trade(w.a, w.acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)),
    "watchlist.add_watchlist": lambda w: w.act(lambda: w.a.post(f"{API}/watchlist", json={"symbol": "2330"})),
    "watchlist.remove_watchlist": lambda w: (w.a.post(f"{API}/watchlist", json={"symbol": "2330"}), w.act(
        lambda: w.a.delete(f"{API}/watchlist/2330.TW"))),
    "recurring.create_plan": lambda w: (w.rt.clear(), _plan(w)),
    "recurring.update_plan": lambda w: (lambda p: w.act(
        lambda: w.a.patch(f"{API}/recurring/{p['id']}", json={"amount": 6000})))(_plan(w)),
    "recurring.delete_plan": lambda w: (lambda p: w.act(lambda: w.a.delete(f"{API}/recurring/{p['id']}")))(_plan(w)),
    "ai.delete_all_threads": lambda w: w.act(lambda: w.a.delete(f"{API}/ai/threads")),
    "ai.delete_thread": lambda w: (lambda tid: w.act(lambda: w.a.delete(f"{API}/ai/threads/{tid}")))(
        _row(AiThread, user_id=w.a_id, model="test")),
    "ai.update_draft": lambda w: (lambda did: w.act(lambda: w.a.patch(f"{API}/ai/drafts/{did}", json={
        "status": "discarded"})))(_draft(w)),
    "briefings.read": lambda w: (lambda bid: w.act(lambda: w.a.post(f"{API}/ai/briefings/{bid}/read")))(
        _row(AiBriefing, user_id=w.a_id, trading_day=today_taipei())),
    "delegations.create": lambda w: (w.rt.clear(), _delegation(w)),
    "delegations.update": s_update_delegation,
    "delegations.remove": lambda w: (lambda d: w.act(lambda: w.a.delete(f"{API}/delegations/{d['id']}")))(
        _delegation(w)),
    "groups.create_group": lambda w: (w.rt.clear(), make_group(w.a, "另一個")),
    "groups.patch_group": lambda w: w.act(lambda: w.a.patch(f"{API}/groups/{w.g['id']}", json={"name": "新"})),
    "groups.delete_group": lambda w: w.act(lambda: w.a.delete(f"{API}/groups/{w.g['id']}")),
    "groups.transfer": lambda w: w.act(lambda: w.a.post(f"{API}/groups/{w.g['id']}/transfer",
                                                        json={"user_id": w.b_id})),
    "groups.set_role": lambda w: w.act(lambda: w.a.patch(f"{API}/groups/{w.g['id']}/members/{w.b_id}",
                                                         json={"role": "admin"})),
    "groups.remove_member": s_remove_member,
    "groups.create_invite": lambda w: (w.rt.clear(), invite(w.a, w.g["id"])),
    "groups.revoke_invite": lambda w: (lambda i: w.act(
        lambda: w.a.delete(f"{API}/groups/{w.g['id']}/invites/{i['id']}")))(invite(w.a, w.g["id"])),
    "groups.accept_invite": lambda w: (lambda i, c: w.act(lambda: c.post(
        f"{API}/invites/{token_of(i)}/accept", json={"share": SHARE_ALL})))(
        invite(w.a, w.g["id"]), login(w.a.app, "c@forliosa.local", "小華")),
    "groups.put_share": lambda w: w.act(lambda: w.b.put(f"{API}/groups/{w.g['id']}/share",
                                                        json={**SHARE_ALL, "push": False})),
    "groups.add_comment": lambda w: (w.rt.clear(), _comment(w)),
    "groups.delete_comment": lambda w: (lambda c: w.act(
        lambda: w.b.delete(f"{API}/groups/{w.g['id']}/comments/{c['id']}")))(_comment(w)),
    "groups.put_reaction": lambda w: w.act(lambda: w.b.put(f"{API}/groups/{w.g['id']}/reactions", json={
        "target": f"leaderboard:{today_taipei().isoformat()}", "emoji": "👍"})),
    "groups.delete_reaction": lambda w: (w.b.put(f"{API}/groups/{w.g['id']}/reactions", json={
        "target": f"leaderboard:{today_taipei().isoformat()}", "emoji": "👍"}), w.act(lambda: w.b.delete(
            f"{API}/groups/{w.g['id']}/reactions",
            params={"target": f"leaderboard:{today_taipei().isoformat()}", "emoji": "👍"}))),
    "groups.attach_plan": lambda w: (lambda p: w.act(lambda: w.a.put(f"{API}/groups/{w.g['id']}/plan",
                                                                     json={"pass_id": p["id"]})))(_group_pass(w)),
    "groups.put_discord": s_put_discord,
    "groups.patch_channel": lambda w: (_discord(w), w.act(lambda: w.a.patch(
        f"{API}/groups/{w.g['id']}/channels/discord", json={"notify_trades": False}))),
    "groups.delete_channel": lambda w: (_discord(w), w.act(lambda: w.a.delete(
        f"{API}/groups/{w.g['id']}/channels/discord"))),
    "discussions.create_topic": lambda w: (w.rt.clear(), post_topic(w.a, w.clock)),
    "discussions.delete_topic": lambda w: (lambda t: w.act(lambda: w.a.delete(
        f"{API}/discussions/topics/{t['id']}")))(post_topic(w.a, w.clock)),
    "discussions.create_reply": lambda w: (lambda t: (w.rt.clear(), post_reply(w.b, w.clock, t["id"])))(
        post_topic(w.a, w.clock)),
    "discussions.delete_reply": lambda w: (lambda rp: w.act(lambda: w.b.delete(
        f"{API}/discussions/replies/{rp['id']}")))(post_reply(w.b, w.clock, post_topic(w.a, w.clock)["id"])),
    "discussions.put_reaction": lambda w: (lambda t: w.act(lambda: w.b.put(f"{API}/discussions/reactions", json={
        "target": f"topic:{t['id']}", "emoji": "👍"})))(post_topic(w.a, w.clock)),
    "discussions.delete_reaction": lambda w: (lambda t: (
        w.b.put(f"{API}/discussions/reactions", json={"target": f"topic:{t['id']}", "emoji": "👍"}),
        w.act(lambda: w.b.delete(f"{API}/discussions/reactions",
                                 params={"target": f"topic:{t['id']}", "emoji": "👍"}))))(post_topic(w.a, w.clock)),
    "discussions.report": lambda w: (lambda t: w.act(lambda: w.a.post(f"{API}/discussions/reports", json={
        "target": f"topic:{t['id']}", "reason": "spam"})))(post_topic(w.b, w.clock)),
    "discussions.moderate": s_moderate,
    "discussions.create_suspension": lambda w: (w.rt.clear(), _suspension(w)),
    "discussions.lift_suspension": lambda w: (lambda s: w.act(lambda: w.admin.delete(
        f"{API}/admin/discussions/suspensions/{s['id']}")))(_suspension(w)),
    "admin.grant_member": lambda w: w.act(lambda: w.admin.put(f"{API}/admin/members", json={
        "email": "demo@forliosa.local"})),
    "admin.revoke_member": lambda w: (w.admin.put(f"{API}/admin/members", json={"email": "demo@forliosa.local"}),
                                      w.act(lambda: w.admin.delete(f"{API}/admin/members/{w.a_id}"))),
    "admin.grant_group_pass": lambda w: (w.rt.clear(), _group_pass(w)),
    "admin.patch_group_pass": lambda w: (lambda p: (
        w.a.put(f"{API}/groups/{w.g['id']}/plan", json={"pass_id": p["id"]}),
        w.act(lambda: w.admin.patch(f"{API}/admin/group-passes/{p['id']}", json={
            "until": (today_taipei() + timedelta(days=60)).isoformat()}))))(_group_pass(w)),
    "admin.revoke_group_pass": lambda w: (lambda p: (
        w.a.put(f"{API}/groups/{w.g['id']}/plan", json={"pass_id": p["id"]}),
        w.act(lambda: w.admin.delete(f"{API}/admin/group-passes/{p['id']}"))))(_group_pass(w)),
    "admin_reports.put_config": lambda w: w.act(lambda: w.admin.put(f"{API}/admin/market-reports/config",
                                                                    json={"mode": "public"})),
    "admin_reports.vote": s_admin_vote,
    "admin_reports.reveal": s_reveal,
    "portfolio.clear_records": s_clear_records,
    "portfolio.put_allocation_limits": s_allocation_limits,
    "imports.commit_positions": s_commit_positions,
    "market_reports.vote": s_member_vote,
}


@pytest.mark.parametrize("route", sorted(SCENARIOS))
def test_the_route_announces_what_the_table_says(route, w):
    SCENARIOS[route](w)
    got = set(w.rt.topics())
    missing = ANNOUNCES[route] - got
    assert not missing, f"{route} did not announce {sorted(missing)} (got {sorted(got)})"


# -- rows of the routes this file cannot drive ---------------------------------------------------------------------
def test_ai_rows_announce_usage_and_threads(client, rt):
    """``POST /ai/chat`` and ``POST /imports/statement`` call the Claude API; the rows they write are what announce."""
    from forliosa.models import AiMessage, AiQuestion, AiUsage

    uid = me_id(client)
    tid = _row(AiThread, user_id=uid, model="test")
    rt.clear()
    with session_factory()() as db:
        db.add(AiMessage(thread_id=tid, user_id=uid, turn_id="turn_1", seq=1, role="user", content="hi"))
        db.add(AiQuestion(user_id=uid))
        db.add(AiUsage(user_id=uid, feature="chat", model="test", key_slot=1))
        db.commit()
    assert {"ai.threads", "ai.usage"} <= set(rt.topics())
    assert all(e.to == (f"u:{uid}",) for e in rt.events)


def test_report_rows_reach_admins(client, rt):
    from forliosa.models import MarketReport, MarketReportVote

    uid = me_id(client)
    with session_factory()() as db:
        rep = MarketReport(id=new_id("mrp"), kind="close", edition_date=date(2026, 11, 17),
                           period_start=date(2026, 11, 17), period_end=date(2026, 11, 17), trial=True)
        db.add(rep)
        db.commit()
        rt.clear()
        db.add(MarketReportVote(report_id=rep.id, user_id=uid, preferred="A"))
        db.commit()
    assert rt.one("admin.reports").to == ("admins",)
    # the voter's own other tabs (「你選了」); nobody else: the votes stay hidden until the reveal (2026-11-17 merge)
    assert rt.one("market.reports").to == (f"u:{uid}",) and sorted(rt.topics()) == ["admin.reports", "market.reports"]

