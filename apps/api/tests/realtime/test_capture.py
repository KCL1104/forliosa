"""Which writes announce what, to whom (``forliosa.realtime.capture``): through the real API routes on SQLite, the
events this process commits are collected (``rt``). The audience is resolved in the writing transaction."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.models import GroupChannel, MarketReport, MarketReportVersion, Transaction, User
from forliosa.realtime import capture
from forliosa.realtime.events import TOPICS, event
from forliosa.services import discussions as discussion_service
from forliosa.timeutil import now_utc, today_taipei
from tests.api.discussions import Clock, post_reply, post_topic, set_name
from tests.api.m5 import (
    API,
    SHARE_DEFAULT,
    SHARE_NONE,
    account,
    invite,
    join,
    login,
    make_group,
    me_id,
    set_share,
    token_of,
    trade,
    trading_day,
)

TAB = "t_tab12345"


def users_of(ev) -> set[str]:
    return {a[2:] for a in ev.to if a.startswith("u:")}


def assert_allowed(events) -> None:
    for e in events:
        if not e.is_op:
            assert set(e.data) <= TOPICS[e.topic], (e.topic, e.data)


@pytest.fixture()
def clock():
    c = Clock()
    discussion_service.set_clock(c)
    yield c
    discussion_service.set_clock(None)


@pytest.fixture()
def b(app):
    return login(app, "b@forliosa.local", "小明")


# -- groups ------------------------------------------------------------------------------------------------------
def test_accepting_an_invite_reaches_the_owner_and_the_joiner(client, b, rt):
    """The owner's report: a friend joined and the open group page did not change."""
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    inv = invite(client, g["id"])
    rt.clear()
    r = b.post(f"{API}/invites/{token_of(inv)}/accept", json={"share": SHARE_DEFAULT}, headers={"X-Forliosa-Tab": TAB})
    assert r.status_code == 200
    members = rt.one("group.members", group_id=g["id"])
    assert users_of(members) == {a_id, b_id}
    assert members.ou == b_id and members.o == TAB and members.echo  # the joiner's own tab skips it
    assert users_of(rt.one("groups.list")) == {b_id}
    assert_allowed(rt.events)


def test_a_refused_join_announces_nothing(client, b, rt):
    g = make_group(client)
    inv = invite(client, g["id"])
    join(client, b, g["id"])
    rt.clear()
    r = b.post(f"{API}/invites/{token_of(inv)}/accept", json={"share": SHARE_DEFAULT})
    assert r.status_code in (409, 410)
    assert rt.events == []


def test_a_rolled_back_write_announces_nothing(client, rt):
    acc = account(client)
    rt.clear()
    with session_factory()() as db:
        db.add(Transaction(id=new_id("txn"), user_id=me_id(client), account_id=acc["id"], symbol="2330.TW",
                           type="buy", trade_date=date(2025, 3, 4), quantity=1, price=1))
        db.flush()
        db.rollback()
        db.commit()
    assert rt.events == []


def test_leaving_tells_the_leaver_and_the_others(client, b, rt):
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    rt.clear()
    assert b.delete(f"{API}/groups/{g['id']}/members/{b_id}").status_code == 204
    assert users_of(rt.one("group.members", group_id=g["id"])) == {a_id, b_id}
    assert users_of(rt.one("groups.list")) == {b_id}


def test_removing_a_member_revokes_invites_for_managers_only(client, b, app, rt):
    a_id, b_id = me_id(client), me_id(b)
    c = login(app, "c@forliosa.local", "小華")
    g = make_group(client)
    join(client, b, g["id"])
    join(client, c, g["id"])
    invite(client, g["id"], multi_use=True)
    rt.clear()
    assert client.delete(f"{API}/groups/{g['id']}/members/{b_id}").status_code == 204
    assert users_of(rt.one("group.invites", group_id=g["id"])) == {a_id}  # owner and admins only
    assert users_of(rt.one("group.members", group_id=g["id"])) == {a_id, b_id, me_id(c)}


def test_roles_share_settings_and_names(client, b, rt):
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    rt.clear()
    assert client.patch(f"{API}/groups/{g['id']}/members/{b_id}", json={"role": "admin"}).status_code == 200
    assert users_of(rt.one("group.members", group_id=g["id"])) == {a_id, b_id}
    rt.clear()
    set_share(b, g["id"], returns=True, holdings=True)
    assert users_of(rt.one("group.members", group_id=g["id"])) == {a_id, b_id}
    rt.clear()
    assert b.patch(f"{API}/me", json={"display_name": "小明明"}).status_code == 200
    assert users_of(rt.one("me")) == {b_id}
    fan = rt.one("group.members", group_id=g["id"])
    assert users_of(fan) == {a_id, b_id} and not fan.echo
    rt.clear()
    assert client.patch(f"{API}/groups/{g['id']}", json={"name": "新名字"}).status_code == 200
    assert users_of(rt.one("group.meta", group_id=g["id"])) == {a_id, b_id}


def test_comments_and_reactions(client, b, rt):
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    target = f"leaderboard:{today_taipei().isoformat()}"
    rt.clear()
    r = b.post(f"{API}/groups/{g['id']}/comments", json={"target": target, "body": "大家好"})
    assert r.status_code == 201, r.text
    ev = rt.one("group.comments", group_id=g["id"], target=target)
    assert users_of(ev) == {a_id, b_id}
    rt.clear()
    assert b.put(f"{API}/groups/{g['id']}/reactions", json={"target": target, "emoji": "👍"}).status_code == 200
    assert rt.one("group.comments", target=target)
    rt.clear()
    r = b.delete(f"{API}/groups/{g['id']}/reactions", params={"target": target, "emoji": "👍"})
    assert r.status_code == 200
    assert users_of(rt.one("group.comments", target=target)) == {a_id, b_id}  # a Core delete, announced by hand
    rt.clear()
    b.delete(f"{API}/groups/{g['id']}/reactions", params={"target": target, "emoji": "👍"})
    assert rt.events == []  # nothing was there


def test_deleting_a_group_reaches_every_former_member(client, b, rt):
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    rt.clear()
    assert client.delete(f"{API}/groups/{g['id']}").status_code == 204
    assert users_of(rt.one("group.deleted", group_id=g["id"])) == {a_id, b_id}
    assert users_of(rt.one("groups.list")) == {a_id, b_id}


def test_channel_rows_reach_every_member(client, b, rt):
    """The 頻道 tab is every member's (GET /groups/{id}/channels needs membership only): a switch the owner turns
    reaches an ordinary member's open tab too (2026-11-17 review)."""
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    rt.clear()
    with session_factory()() as db:
        ch = GroupChannel(group_id=g["id"], kind="telegram", status="active", telegram_chat_id=-100,
                          chat_title="家族群")
        db.add(ch)
        db.commit()
        assert users_of(rt.one("group.channels", group_id=g["id"])) == {a_id, b_id}
        assert users_of(rt.one("group.meta", group_id=g["id"])) == {a_id, b_id}
        rt.clear()
        ch.notify_trades = not ch.notify_trades  # a switch only: no group.meta, but the member's tab still follows
        db.commit()
    assert users_of(rt.one("group.channels", group_id=g["id"])) == {a_id, b_id}
    assert rt.find("group.meta") == []


# -- ledger -----------------------------------------------------------------------------------------------------
def test_a_trade_reaches_my_devices_and_the_groups_i_share_with(client, b, rt):
    a_id, b_id = me_id(client), me_id(b)
    shared = make_group(client, "看得到")
    quiet = make_group(client, "看不到")
    join(client, b, shared["id"])
    join(client, b, quiet["id"])
    set_share(client, quiet["id"])  # shares nothing there
    acc = account(client)
    rt.clear()
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)
    ledger = rt.one("ledger", account_id=acc["id"])
    assert users_of(ledger) == {a_id}
    group_ledger = rt.find("group.ledger")
    assert [e.data for e in group_ledger] == [{"group_id": shared["id"]}]
    assert users_of(group_ledger[0]) == {a_id, b_id} and not group_ledger[0].echo
    assert "user_id" not in group_ledger[0].data  # never names the member


def _group_ledger(rt, gid) -> list:
    return rt.find("group.ledger", group_id=gid)


def test_a_trades_only_member_announces_only_what_the_feed_shows(client, b, rt):
    """A member who shares only trades: the group hears of a change only when its feed changes. A deposit, a dividend,
    an old trade or a note edit would otherwise tell the other members *when* the member did something the refetched
    feed does not show (2026-11-17 review)."""
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"], share={**SHARE_NONE, "trades": True})
    acc = account(b)
    old = trade(b, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)  # outside the 90-day feed window
    hidden = [
        lambda: b.post(f"{API}/transactions", json={"account_id": acc["id"], "type": "deposit",
                                                    "trade_date": trading_day(2).isoformat(), "amount": 100000}),
        lambda: b.post(f"{API}/transactions", json={"account_id": acc["id"], "type": "cash_dividend",
                                                    "symbol": "2330.TW", "trade_date": trading_day(2).isoformat(),
                                                    "amount": 4000}),
        lambda: b.patch(f"{API}/transactions/{old['id']}", json={"note": "備註"}),
        lambda: b.patch(f"{API}/transactions/{old['id']}", json={"quantity": 2000}),
        lambda: b.post(f"{API}/accounts", json={"name": "二", "broker": "", "currency": "TWD", "fee_discount": 0.28}),
    ]
    for write in hidden:
        rt.clear()
        r = write()
        assert r.status_code in (200, 201), r.text
        assert rt.find("ledger") and _group_ledger(rt, g["id"]) == [], r.request.url
    rt.clear()
    recent = trade(b, acc["id"], "2330.TW", "buy", trading_day(3), 1000, 600)  # the feed shows it
    assert users_of(_group_ledger(rt, g["id"])[0]) == {a_id, b_id}
    rt.clear()
    assert b.patch(f"{API}/transactions/{recent['id']}", json={"note": "只改備註"}).status_code == 200
    assert _group_ledger(rt, g["id"]) == []  # the feed item looks the same
    rt.clear()
    assert b.patch(f"{API}/transactions/{recent['id']}", json={"quantity": 2000}).status_code == 200
    assert len(_group_ledger(rt, g["id"])) == 1
    rt.clear()
    assert b.patch(f"{API}/transactions/{old['id']}", json={"trade_date": trading_day(4).isoformat()}).status_code \
        == 200
    assert len(_group_ledger(rt, g["id"])) == 1  # moved into the window: it appears
    rt.clear()
    assert b.delete(f"{API}/transactions/{recent['id']}").status_code == 204
    assert len(_group_ledger(rt, g["id"])) == 1


def test_a_returns_sharer_announces_position_changes_but_not_notes(client, b, rt):
    g = make_group(client)
    join(client, b, g["id"], share={**SHARE_NONE, "returns": True})
    acc = account(b)
    old = trade(b, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)
    rt.clear()
    assert b.patch(f"{API}/transactions/{old['id']}", json={"note": "備註"}).status_code == 200
    assert rt.find("ledger") and _group_ledger(rt, g["id"]) == []
    rt.clear()
    assert b.patch(f"{API}/transactions/{old['id']}", json={"price": 610}).status_code == 200
    assert len(_group_ledger(rt, g["id"])) == 1
    rt.clear()
    assert b.post(f"{API}/transactions", json={"account_id": acc["id"], "type": "deposit",
                                               "trade_date": "2025-03-01", "amount": 100000}).status_code == 201
    assert len(_group_ledger(rt, g["id"])) == 1  # cash and flows are part of the returns
    rt.clear()
    assert b.patch(f"{API}/accounts/{acc['id']}", json={"name": "改名"}).status_code == 200
    assert _group_ledger(rt, g["id"]) == []  # groups never show account names


def test_deleting_an_account_reaches_trades_only_groups_only_with_feed_trades(client, b, rt):
    g = make_group(client)
    join(client, b, g["id"], share={**SHARE_NONE, "trades": True})
    quiet, busy = account(b, "舊的"), account(b, "新的")
    trade(b, quiet["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)
    trade(b, busy["id"], "2330.TW", "buy", trading_day(3), 1000, 600)
    rt.clear()
    assert b.delete(f"{API}/accounts/{quiet['id']}").status_code == 204
    assert rt.find("ledger") and _group_ledger(rt, g["id"]) == []
    rt.clear()
    assert b.delete(f"{API}/accounts/{busy['id']}").status_code == 204
    assert len(_group_ledger(rt, g["id"])) == 1


def test_an_import_announces_once_per_account(client, rt):
    acc = account(client)
    rows = [{"symbol": "2330", "type": "buy", "trade_date": f"2025-03-0{d}", "quantity": 100, "price": 600}
            for d in range(3, 8)]
    rt.clear()
    r = client.post(f"{API}/transactions/batch",
                    json={"account_id": acc["id"], "origin": "import", "dry_run": False, "rows": rows})
    assert r.status_code == 201, r.text
    assert len(rt.find("ledger")) == 1
    rt.clear()
    assert client.post(f"{API}/transactions/batch", json={"account_id": acc["id"], "origin": "import",
                                                          "dry_run": True, "rows": rows}).status_code == 200
    assert rt.find("ledger") == []  # a dry run writes nothing


def test_delegation_viewers_follow_the_scope(client, b, rt):
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    acc1, acc2 = account(client, "一"), account(client, "二")
    rt.clear()
    r = client.post(f"{API}/delegations", json={"viewer_user_id": b_id, "scope": "accounts",
                                                "account_ids": [acc1["id"]]})
    assert r.status_code == 201, r.text
    dlg = r.json()["id"]
    assert users_of(rt.one("delegations")) == {a_id, b_id}
    rt.clear()
    trade(client, acc2["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)
    assert rt.find("ledger.viewas") == []  # not in the delegated scope
    trade(client, acc1["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)
    ev = rt.one("ledger.viewas", delegation_id=dlg)
    assert users_of(ev) == {b_id} and ev.data == {"delegation_id": dlg}  # no account id
    rt.clear()
    assert client.patch(f"{API}/me/preferences", json={"cost_method": "fifo"}).status_code == 200
    assert {"me", "ledger", "ledger.viewas"} <= set(rt.topics())
    rt.clear()
    assert client.delete(f"{API}/accounts/{acc1['id']}").status_code == 204
    assert users_of(rt.one("delegations")) == {a_id, b_id}


def test_a_new_name_reaches_the_other_side_of_each_delegation(client, b, rt):
    """The view-as banner and the delegation lists name the owner: a viewer who shares no group with the owner still
    hears of a new display name."""
    b_id = me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    assert client.post(f"{API}/delegations", json={"viewer_user_id": b_id, "scope": "all"}).status_code == 201
    assert b.delete(f"{API}/groups/{g['id']}/members/{b_id}").status_code == 204  # no longer co-members
    rt.clear()
    assert client.patch(f"{API}/me", json={"display_name": "新名字"}).status_code == 200
    dlg = rt.one("delegations")
    assert users_of(dlg) == {b_id} and not dlg.echo


def test_watchlist_recurring_and_preferences(client, rt):
    a_id = me_id(client)
    rt.clear()
    assert client.post(f"{API}/watchlist", json={"symbol": "2330"}).status_code in (200, 201)
    assert users_of(rt.one("watchlist")) == {a_id}
    rt.clear()
    assert client.patch(f"{API}/me/preferences", json={"daily_briefing": True}).status_code == 200
    assert {"me", "ai.briefings"} == set(rt.topics())


# -- discussions --------------------------------------------------------------------------------------------------
def test_public_and_group_discussions(client, b, rt, clock):
    a_id, b_id = me_id(client), me_id(b)
    set_name(client, "阿明")
    set_name(b, "小明")
    rt.clear()
    pub = post_topic(client, clock)
    ev = rt.one("discussions.list")
    assert ev.data == {"scope": "public"} and ev.to == ("all",)
    rt.clear()
    post_reply(b, clock, pub["id"])
    assert rt.one("discussions.topic", topic_id=pub["id"]).to == ("all",)
    assert rt.one("discussions.list", scope="public")
    g = make_group(client)
    join(client, b, g["id"])
    rt.clear()
    gt = post_topic(client, clock, scope="group", group_id=g["id"])
    assert users_of(rt.one("discussions.list", scope="group", group_id=g["id"])) == {a_id, b_id}
    rt.clear()
    assert b.put(f"{API}/discussions/reactions", json={"target": f"topic:{gt['id']}", "emoji": "👍"}).status_code \
        in (200, 204)
    assert users_of(rt.one("discussions.topic", topic_id=gt["id"])) == {a_id, b_id}
    assert rt.find("discussions.list") == []
    rt.clear()
    assert client.delete(f"{API}/discussions/topics/{gt['id']}").status_code == 204
    assert users_of(rt.one("discussions.topic", topic_id=gt["id"])) == {a_id, b_id}
    assert rt.one("discussions.list", scope="group")
    assert_allowed(rt.events)


# -- sessions, accounts, reports ---------------------------------------------------------------------------------
def test_logout_and_account_deletion_close_streams(client, b, rt):
    b_id = me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    rt.clear()
    assert b.post(f"{API}/auth/logout").status_code == 204
    op = rt.one("_session.gone")
    assert len(op.data["s"]) == 24 and op.to == ()
    b2 = login(b.app, "b@forliosa.local", "小明")
    rt.clear()
    r = b2.request("DELETE", f"{API}/me", json={"confirm": "刪除我的帳號"})
    assert r.status_code == 204, r.text
    assert rt.one("_user.gone").data == {"u": b_id}
    assert users_of(rt.one("group.members", group_id=g["id"])) == {me_id(client)}  # the ones who stay


def test_market_report_publication(rt, engine):
    rt.clear()
    with session_factory()() as db:
        rep = MarketReport(id=new_id("mrp"), kind="close", edition_date=date(2026, 11, 17),
                           period_start=date(2026, 11, 17), period_end=date(2026, 11, 17), visibility="public")
        db.add(rep)
        db.commit()
        assert rt.topics() == ["admin.reports"] and rt.events[0].to == ("admins",)
        rt.clear()
        rep.current_version_id, rep.state, rep.first_published_at = "mrv_1", "data", now_utc()
        db.commit()
    ev = rt.one("market.reports")
    assert ev.data == {"report_id": rep.id, "kind": "close"} and ev.to == ("all",)


def test_a_version_rebuilt_in_place_reaches_its_readers(rt, engine):
    """The close report's data edition is rebuilt in place until 15:40 (``reports.pipeline.build_data``): the readers
    of the report it serves refetch; a version the report does not serve stays with the admins."""
    with session_factory()() as db:
        rep = MarketReport(id=new_id("mrp"), kind="close", edition_date=date(2026, 11, 17),
                           period_start=date(2026, 11, 17), period_end=date(2026, 11, 17), visibility="public",
                           state="data", first_published_at=now_utc())
        cur = MarketReportVersion(id=new_id("mrv"), report_id=rep.id, version=1, edition="data", payload={"a": 1})
        other = MarketReportVersion(id=new_id("mrv"), report_id=rep.id, version=2, edition="data", payload={"a": 1})
        db.add_all([rep, cur, other])
        db.flush()
        rep.current_version_id = cur.id
        db.commit()
        rt.clear()
        cur.payload, rep.notes, rep.updated_at = {"a": 2}, ["refreshed"], now_utc()  # build_data's refresh branch
        db.commit()
        ev = rt.one("market.reports")
        assert ev.data == {"report_id": rep.id, "kind": "close"} and ev.to == ("all",)
        rt.clear()
        other.payload = {"a": 3}
        db.commit()
    assert rt.topics() == ["admin.reports"]


def test_trial_reports_stay_with_admins(rt, engine):
    with session_factory()() as db:
        rep = MarketReport(id=new_id("mrp"), kind="close", edition_date=date(2026, 11, 18),
                           period_start=date(2026, 11, 18), period_end=date(2026, 11, 18), visibility="admin")
        db.add(rep)
        db.commit()
        rt.clear()
        rep.current_version_id = "mrv_2"
        db.commit()
    assert rt.one("market.reports").to == ("admins",)


# -- mechanics ---------------------------------------------------------------------------------------------------
def test_setting_the_same_value_is_not_a_change(client, rt):
    uid = me_id(client)
    with session_factory()() as db:
        u = db.get(User, uid)
        rt.clear()
        u.display_name = u.display_name
        db.commit()
    assert rt.events == []


def test_unknown_payload_keys_are_dropped():
    ev = event("group.members", {"group_id": "grp_1", "user_id": "usr_secret"}, ("g:grp_1",))
    assert ev.data == {"group_id": "grp_1"}
    with pytest.raises(ValueError):
        event("no.such.topic")


def test_invalid_tab_ids_are_not_recorded(client, rt):
    acc = account(client)
    rt.clear()
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1, 600)
    assert rt.one("ledger", account_id=acc["id"]).o is None
    rt.clear()
    r = client.post(f"{API}/transactions", headers={"X-Forliosa-Tab": "<script>"},
                    json={"account_id": acc["id"], "symbol": "2330.TW", "type": "buy", "trade_date": "2025-03-05",
                          "quantity": 1, "price": 600})
    assert r.status_code == 201
    assert rt.one("ledger", account_id=acc["id"]).o is None


def test_switched_off(client, rt, monkeypatch):
    monkeypatch.setattr(get_settings(), "realtime_enabled", False)
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1, 600)
    assert rt.events == []


def test_notify_now_uses_its_own_transaction(engine, rt):
    capture.notify_now(event("market.closes", {"market": "TWSE", "date": "2026-11-17"}, ("all",)))
    assert rt.one("market.closes").data == {"market": "TWSE", "date": "2026-11-17"}


def test_nothing_is_left_over_for_the_next_commit(client, rt):
    with session_factory()() as db:
        db.scalars(select(User)).all()
        db.commit()
    assert rt.events == []


def test_share_none_member_gets_no_group_ledger(client, b, rt):
    g = make_group(client)
    join(client, b, g["id"], share=SHARE_NONE)
    acc = account(b)
    rt.clear()
    trade(b, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1, 600)
    assert rt.find("group.ledger") == []


def test_a_failure_while_announcing_never_fails_the_write(client, rt, monkeypatch):
    def broken(self, conn):
        raise RuntimeError("boom")

    monkeypatch.setattr(capture.LedgerFanout, "resolve", broken)
    acc = account(client)  # still created
    assert client.get(f"{API}/accounts").json()[0]["id"] == acc["id"]
    assert rt.find("ledger") == []  # the commit's events were dropped, not half sent
