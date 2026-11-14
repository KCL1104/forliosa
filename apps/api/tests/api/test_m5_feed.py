"""M5 group feed (merge, window, sources, pagination), comments and reactions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.models import GroupComment, GroupDigest, GroupReaction, Transaction
from forliosa.timeutil import now_utc, today_taipei
from tests.api.m5 import API, account, join, login, make_group, me_id, set_share, trade, trading_day


@pytest.fixture()
def setup(app, client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    set_share(other_client, g["id"], trades=True, trade_prices=True)
    acc = account(other_client)
    return {"gid": g["id"], "acc": acc["id"], "uid": me_id(other_client)}


def items(client, gid, **params):
    r = client.get(f"{API}/groups/{gid}/feed", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_feed_merges_per_member_day_symbol_side(client, other_client, setup):
    gid, acc = setup["gid"], setup["acc"]
    d1, d2 = trading_day(10), trading_day(3)
    trade(other_client, acc, "2330.TW", "buy", d1, 1000, 100)
    trade(other_client, acc, "2330.TW", "buy", d1, 1000, 110)
    trade(other_client, acc, "2330.TW", "buy", d1, 2000, 120, source="ai_draft")
    trade(other_client, acc, "2330.TW", "sell", d1, 500, 130)
    trade(other_client, acc, "2330.TW", "buy", d2, 100, 140, source="import")
    other_client.post(f"{API}/transactions", json={"account_id": acc, "symbol": "2330.TW", "type": "cash_dividend",
                                                   "trade_date": d2.isoformat(), "quantity": 4000, "price": 1})
    trades = [i for i in items(client, gid)["items"] if i["type"] == "trade"]
    summary = [(i["trade_date"], i["side"], i["count"], i.get("price"), i.get("currency")) for i in trades]
    assert summary == [(d2.isoformat(), "buy", 1, 140.0, "TWD"),
                       (d1.isoformat(), "sell", 1, 130.0, "TWD"),
                       (d1.isoformat(), "buy", 3, 112.5, "TWD")] or summary == [
                       (d2.isoformat(), "buy", 1, 140.0, "TWD"),
                       (d1.isoformat(), "buy", 3, 112.5, "TWD"),
                       (d1.isoformat(), "sell", 1, 130.0, "TWD")]
    assert all(i["symbol"] == "2330.TW" and i["name"] == "台積電" and i["display_name"] == "別人" for i in trades)
    assert len({i["id"] for i in trades}) == 3 and all(i["id"].startswith("gfi_") for i in trades)
    # ids are stable across reads
    assert [i["id"] for i in trades] == [i["id"] for i in items(client, gid)["items"] if i["type"] == "trade"]


def test_feed_window_and_sources(client, other_client, setup):
    gid, acc, uid = setup["gid"], setup["acc"], setup["uid"]
    trade(other_client, acc, "2330.TW", "buy", trading_day(95), 1000, 100)  # older than 90 days
    trade(other_client, acc, "2317.TW", "buy", trading_day(5), 1000, 100)
    with session_factory()() as db:  # rows the feed must not show
        for source, d in (("auto", trading_day(4)), ("auto_edited", trading_day(4)), ("manual", today_taipei()
                                                                                         + timedelta(days=3))):
            db.add(Transaction(id=new_id("txn"), user_id=uid, account_id=acc, symbol="2454.TW", type="buy",
                               trade_date=d, quantity=1, price=1, amount=1, source=source))
        db.commit()
    trades = [i for i in items(client, gid)["items"] if i["type"] == "trade"]
    assert [i["symbol"] for i in trades] == ["2317.TW"]


def test_member_joined_items_pagination_and_filter(app, client, other_client, setup):
    gid, acc = setup["gid"], setup["acc"]
    for days in (2, 4, 6):
        trade(other_client, acc, "2330.TW", "buy", trading_day(days), 1000, 100)
    full = items(client, gid, limit=100)["items"]
    assert [i["type"] for i in full].count("member_joined") == 2
    seen, cursor = [], None
    while True:
        page = items(client, gid, limit=2, **({"cursor": cursor} if cursor else {}))
        seen += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert [i["id"] for i in seen] == [i["id"] for i in full]
    only = items(client, gid, user_id=me_id(client))["items"]
    assert [i["type"] for i in only] == ["member_joined"]
    assert client.get(f"{API}/groups/{gid}/feed", params={"cursor": "%%%"}).status_code == 422
    assert client.get(f"{API}/groups/{gid}/feed", params={"limit": 0}).status_code == 422


def test_comments_on_trades_leaderboard_and_digests(app, client, other_client, setup):
    gid, acc = setup["gid"], setup["acc"]
    t = trade(other_client, acc, "2330.TW", "buy", trading_day(3), 1000, 100)
    item = next(i for i in items(client, gid)["items"] if i["type"] == "trade")
    target = f"trade:{item['id']}"
    r = client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "  跟上  "})
    assert r.status_code == 201
    c = r.json()
    assert c["body"] == "跟上" and c["user_id"] == me_id(client) and c["can_delete"] is True
    assert c["id"].startswith("gcm_") and c["display_name"] == "示範使用者"
    assert next(i for i in items(client, gid)["items"] if i["type"] == "trade")["comment_count"] == 1
    other = other_client.get(f"{API}/groups/{gid}/comments", params={"target": target}).json()
    assert other["items"][0]["can_delete"] is False and other["next_cursor"] is None
    # validation
    for body in ("", "  ", "x" * 501):
        assert client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": body}).status_code == 422
    assert client.post(f"{API}/groups/{gid}/comments", json={"target": "post:1", "body": "x"}).status_code == 422
    # leaderboard thread of a day; future days and nonsense are 404 like unknown targets
    today = today_taipei().isoformat()
    assert client.post(f"{API}/groups/{gid}/comments",
                       json={"target": f"leaderboard:{today}", "body": "今天大家都紅"}).status_code == 201
    future = (today_taipei() + timedelta(days=1)).isoformat()
    for bad in (f"leaderboard:{future}", "leaderboard:2026-13-40", "digest:gdg_nope", "trade:gfi_nope"):
        r = client.post(f"{API}/groups/{gid}/comments", json={"target": bad, "body": "x"})
        assert r.status_code == 404 and r.json()["error"] == {"code": "not_found", "message": "找不到討論對象"}, bad
    # digests: only ready digests of this group
    with session_factory()() as db:
        db.add(GroupDigest(id="gdg_ready1", group_id=gid, week_start=today_taipei(), week_end=today_taipei(),
                           status="ready"))
        db.add(GroupDigest(id="gdg_pending1", group_id=gid, week_start=today_taipei() - timedelta(days=7),
                           week_end=today_taipei(), status="pending"))
        db.commit()
    assert client.post(f"{API}/groups/{gid}/comments", json={"target": "digest:gdg_ready1", "body": "讚"}
                       ).status_code == 201
    assert client.post(f"{API}/groups/{gid}/comments", json={"target": "digest:gdg_pending1", "body": "讚"}
                       ).status_code == 404
    # a target of another group is 404 too
    third = login(app, "third@forliosa.local", "老三")
    g2 = make_group(third, "別的群組")
    r = third.post(f"{API}/groups/{g2['id']}/comments", json={"target": target, "body": "偷看"})
    assert r.status_code == 404
    # deleting: author or manager only
    r = other_client.delete(f"{API}/groups/{gid}/comments/{c['id']}")
    assert r.status_code == 403
    mine = other_client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "謝謝"}).json()
    assert client.delete(f"{API}/groups/{gid}/comments/{mine['id']}").status_code == 204  # the owner manages
    assert client.delete(f"{API}/groups/{gid}/comments/{c['id']}").status_code == 204
    assert client.delete(f"{API}/groups/{gid}/comments/gcm_nope").status_code == 404
    assert t


def test_comment_pagination(client, other_client, setup):
    gid = setup["gid"]
    target = f"leaderboard:{today_taipei().isoformat()}"
    for n in range(5):
        client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": f"第{n}則"})
    first = client.get(f"{API}/groups/{gid}/comments", params={"target": target, "limit": 3}).json()
    rest = client.get(f"{API}/groups/{gid}/comments", params={"target": target, "limit": 3,
                                                              "cursor": first["next_cursor"]}).json()
    assert [c["body"] for c in first["items"] + rest["items"]] == [f"第{n}則" for n in range(5)]
    assert rest["next_cursor"] is None


def test_deleting_the_last_trade_deletes_its_thread(client, other_client, setup):
    gid, acc = setup["gid"], setup["acc"]
    d = trading_day(3)
    t1 = trade(other_client, acc, "2330.TW", "buy", d, 1000, 100)
    t2 = trade(other_client, acc, "2330.TW", "buy", d, 1000, 110)
    item = next(i for i in items(client, gid)["items"] if i["type"] == "trade")
    target = f"trade:{item['id']}"
    client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "跟上"})
    client.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": "👍"})

    def thread_rows() -> int:
        with session_factory()() as db:
            return (db.scalar(select(func.count()).select_from(GroupComment).where(GroupComment.target == target))
                    + db.scalar(select(func.count()).select_from(GroupReaction).where(GroupReaction.target == target)))

    assert other_client.delete(f"{API}/transactions/{t1['id']}").status_code == 204
    assert thread_rows() == 2  # the item still exists (one trade left)
    # Moving the last trade to another day empties the old item: its thread goes.
    r = other_client.patch(f"{API}/transactions/{t2['id']}", json={"trade_date": trading_day(5).isoformat()})
    assert r.status_code == 200
    assert thread_rows() == 0
    t3 = trade(other_client, acc, "2317.TW", "buy", d, 1000, 100)
    item = next(i for i in items(client, gid)["items"] if i.get("symbol") == "2317.TW")
    target = f"trade:{item['id']}"
    client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "鴻海"})
    assert thread_rows() == 1
    assert other_client.delete(f"{API}/accounts/{acc}").status_code == 204  # deleting the account deletes trades
    assert thread_rows() == 0
    assert t3


def test_departed_and_deleted_authors(app, client, other_client, setup):
    gid = setup["gid"]
    target = f"leaderboard:{today_taipei().isoformat()}"
    other_client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "我先走了"})
    third = login(app, "third@forliosa.local", "老三")
    join(client, third, gid)
    third.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "帳號要刪了"})
    other_client.delete(f"{API}/groups/{gid}/members/{setup['uid']}")
    with session_factory()() as db:  # account deletion (a later feature) nulls the author
        from forliosa.models import GroupMember, User

        db.delete(db.get(GroupMember, (gid, me_id(third))))
        db.delete(db.get(User, me_id(third)))
        db.commit()
    page = client.get(f"{API}/groups/{gid}/comments", params={"target": target}).json()["items"]
    assert [(c["display_name"], c["user_id"], c["avatar_url"]) for c in page] == [
        ("已離開的成員", None, None), ("已刪除的帳號", None, None)]
    assert all(c["can_delete"] for c in page)  # the owner manages


def test_reactions(client, other_client, setup):
    gid = setup["gid"]
    target = f"leaderboard:{today_taipei().isoformat()}"
    r = client.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": "👍"})
    assert r.status_code == 200 and r.json() == {"target": target,
                                                 "reactions": [{"emoji": "👍", "count": 1, "mine": True}]}
    client.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": "👍"})  # not counted twice
    r = other_client.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": "👍"})
    assert r.json()["reactions"] == [{"emoji": "👍", "count": 2, "mine": True}]
    other_client.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": "🔥"})
    r = client.delete(f"{API}/groups/{gid}/reactions", params={"target": target, "emoji": "👍"})
    assert r.json()["reactions"] == [{"emoji": "👍", "count": 1, "mine": False},
                                     {"emoji": "🔥", "count": 1, "mine": False}]
    for emoji in ("💩", "👍🏻", "x"):
        r = client.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": emoji})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert client.put(f"{API}/groups/{gid}/reactions", json={"target": "trade:gfi_nope", "emoji": "👍"}
                      ).status_code == 404
    assert len(["👍", "🎉", "🔥", "😮", "😢", "👀"]) == 6
    for emoji in ("🎉", "😮", "😢", "👀"):
        assert client.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": emoji}).status_code == 200


def test_latest_activity_ignores_hidden_items(client, other_client, setup):
    from forliosa.models import GroupMember

    gid, acc = setup["gid"], setup["acc"]
    with session_factory()() as db:  # both joined three days ago
        for m in db.scalars(select(GroupMember).where(GroupMember.group_id == gid)):
            m.joined_at = now_utc() - timedelta(days=3)
        db.commit()
    before = client.get(f"{API}/groups").json()[0]["latest_activity_at"]
    trade(other_client, acc, "2330.TW", "buy", today_taipei(), 1000, 100)
    after = client.get(f"{API}/groups").json()[0]["latest_activity_at"]
    assert after > before
    set_share(other_client, gid)  # trades off: the activity time does not reveal the hidden trade
    assert client.get(f"{API}/groups").json()[0]["latest_activity_at"] == before
