"""M5 privacy matrix: every combination of a member's share toggles, as seen by another member.

For each combination the projections (SharedPortfolio, leaderboard, holdings overlap, feed) must
* contain a block only when its toggle is on (absent keys — never ``null`` or 0 placeholders);
* never contain quantities, account names or ids, notes, fees, costs or transaction ids;
* contain amounts only with ``amounts`` and trade prices only with ``trades`` + ``trade_prices``.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from tests.api.m5 import API, SHARE_NONE, account, join, make_group, me_id, set_share, trade, trading_day

TOGGLES = ("returns", "holdings", "amounts", "trades", "trade_prices")
ACCOUNT_NAME = "秘密帳戶名稱"
NOTE = "私人備註內容"
QUANTITIES = {1357, 357, 2468, 1000}
PRICES = {987.65, 1011.5, 123.45}
FORBIDDEN_KEYS = {"quantity", "quantities", "avg_cost", "cost_basis", "cost", "account_id", "account_ids", "accounts",
                  "note", "notes_private", "fee", "tax", "health_insurance", "amount", "transaction_id",
                  "unrealized_pnl", "realized_pnl", "dividend_income", "source", "account_name"}


@pytest.fixture()
def sharer(client, other_client):
    """``client`` (the sharer) with distinctive data; ``other_client`` is the member who looks."""
    g = make_group(client)
    join(client, other_client, g["id"])
    acc = account(client, ACCOUNT_NAME)
    trade(client, acc["id"], "2330.TW", "buy", trading_day(40), 1357, 987.65, note=NOTE)
    trade(client, acc["id"], "2330.TW", "sell", trading_day(20), 357, 1011.5, note=NOTE)
    trade(client, acc["id"], "0050.TW", "buy", trading_day(10), 2468, 123.45, note=NOTE)
    summary = client.get(f"{API}/portfolio/summary").json()
    secret_amounts = {summary["market_value"], summary["total_pnl"], summary["day_change"], summary["cost_basis"]}
    return {"group": g["id"], "uid": me_id(client), "account_id": acc["id"], "amounts": secret_amounts - {0.0}}


def walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{path}.{k}", k, v
            yield from walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{path}[{i}]")


def assert_no_private_data(body: Any, sharer: dict, allow_prices: bool, allow_amounts: bool) -> None:
    text = str(body)
    assert ACCOUNT_NAME not in text and NOTE not in text and sharer["account_id"] not in text
    assert "txn_" not in text and "acc_" not in text
    for path, key, value in walk(body):
        assert key not in FORBIDDEN_KEYS, path
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            assert value not in QUANTITIES or key in ("count", "holder_count"), (path, value)
            if not allow_prices:
                assert value not in PRICES, (path, value)
            if not allow_amounts:
                assert value not in sharer["amounts"], (path, value)
            elif value in sharer["amounts"]:
                assert ".amounts." in path, path


def views(viewer, sharer: dict) -> dict[str, Any]:
    gid, uid = sharer["group"], sharer["uid"]
    out = {}
    for name, path, params in (("shared", f"/groups/{gid}/members/{uid}/shared", {}),
                               ("leaderboard", f"/groups/{gid}/leaderboard", {"period": "month"}),
                               ("holdings", f"/groups/{gid}/holdings", {}),
                               ("feed", f"/groups/{gid}/feed", {"user_id": uid})):
        r = viewer.get(f"{API}{path}", params=params)
        assert r.status_code == 200, (name, r.text)
        out[name] = r.json()
    return out


@pytest.mark.parametrize("bits", list(itertools.product((False, True), repeat=len(TOGGLES))),
                         ids=lambda b: "".join("1" if x else "0" for x in b))
def test_each_toggle_combination(client, other_client, sharer, bits):
    on = dict(zip(TOGGLES, bits, strict=True))
    set_share(client, sharer["group"], **on)
    v = views(other_client, sharer)
    uid = sharer["uid"]

    shared = v["shared"]
    expected = {"user_id", "display_name", "avatar_url"}
    blocks = {k for k in ("returns", "holdings", "amounts") if on[k]}
    expected |= blocks | ({"is_demo"} if blocks else set())
    assert set(shared) == expected
    if on["returns"]:
        assert set(shared["returns"]) == {"day", "month", "year", "total"}
        for x in shared["returns"].values():
            assert x is None or round(x, 4) == x
    if on["holdings"]:
        assert {h["symbol"] for h in shared["holdings"]} == {"2330.TW", "0050.TW"}
        for h in shared["holdings"]:
            assert set(h) == {"symbol", "name", "weight"} and round(h["weight"], 2) == h["weight"]
    if on["amounts"]:
        assert set(shared["amounts"]) == {"market_value", "day_change", "total_pnl"}

    entries = {e["user_id"]: e for e in v["leaderboard"]["entries"]}
    assert (uid in entries) == on["returns"]
    if on["returns"]:
        assert set(entries[uid]) == {"user_id", "display_name", "avatar_url", "return_pct", "total_return_pct",
                                     "rank", "is_me"}

    holders = {m["user_id"] for m in v["holdings"]["members"]}
    assert (uid in holders) == on["holdings"]
    if not on["holdings"]:
        assert v["holdings"]["common"] == [] and v["holdings"]["industries"] == []

    trades = [i for i in v["feed"]["items"] if i["type"] == "trade"]
    assert bool(trades) == on["trades"]
    for i in trades:
        has_price = on["trade_prices"]
        assert ("price" in i) == has_price and ("currency" in i) == has_price
        assert set(i) - {"price", "currency"} == {"id", "type", "user_id", "display_name", "avatar_url", "side",
                                                   "symbol", "name", "trade_date", "count", "created_at",
                                                   "comment_count", "reactions"}
    joined = [i for i in v["feed"]["items"] if i["type"] == "member_joined"]
    assert len(joined) == 1 and set(joined[0]) == {"id", "type", "user_id", "display_name", "avatar_url",
                                                    "created_at"}

    allow_prices = on["trades"] and on["trade_prices"]
    for name, body in v.items():
        assert_no_private_data(body, sharer, allow_prices=allow_prices and name == "feed",
                               allow_amounts=on["amounts"] and name == "shared")


def test_member_sharing_nothing_is_indistinguishable(client, other_client, sharer):
    """No 「未分享」 marker anywhere: a member who shares nothing looks like a member without data."""
    set_share(client, sharer["group"], **SHARE_NONE)
    v = views(other_client, sharer)
    assert set(v["shared"]) == {"user_id", "display_name", "avatar_url"}
    assert sharer["uid"] not in str(v["leaderboard"]["entries"]) and sharer["uid"] not in str(v["holdings"])
    assert [i["type"] for i in v["feed"]["items"]] == ["member_joined"]
    text = str(v)
    for word in ("未分享", "not_shared", "hidden", "private"):
        assert word not in text


def test_turning_off_and_leaving_take_effect_immediately(client, other_client, sharer):
    gid, uid = sharer["group"], sharer["uid"]
    set_share(client, gid, trades=True, returns=True, holdings=True)
    item = next(i for i in other_client.get(f"{API}/groups/{gid}/feed").json()["items"] if i["type"] == "trade")
    target = f"trade:{item['id']}"
    r = other_client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "跟上"})
    assert r.status_code == 201
    set_share(client, gid, returns=True)  # trades off
    assert not [i for i in other_client.get(f"{API}/groups/{gid}/feed").json()["items"] if i["type"] == "trade"]
    hidden = other_client.get(f"{API}/groups/{gid}/comments", params={"target": target})
    unknown = other_client.get(f"{API}/groups/{gid}/comments", params={"target": "trade:gfi_0000000000"})
    assert hidden.status_code == unknown.status_code == 404 and hidden.json() == unknown.json()
    set_share(client, gid, trades=True)  # back on: the thread is back
    page = other_client.get(f"{API}/groups/{gid}/comments", params={"target": target}).json()
    assert [c["body"] for c in page["items"]] == ["跟上"]
    # The sharer leaves: everything of theirs disappears from the group's projections.
    client.patch(f"{API}/groups/{gid}", json={})  # owner stays owner; transfer to leave
    client.post(f"{API}/groups/{gid}/transfer", json={"user_id": me_id(other_client)})
    assert client.delete(f"{API}/groups/{gid}/members/{uid}").status_code == 204
    v = other_client.get(f"{API}/groups/{gid}/feed").json()["items"]
    assert all(i["user_id"] != uid for i in v)
    assert other_client.get(f"{API}/groups/{gid}/members/{uid}/shared").status_code == 404
    assert all(e["user_id"] != uid for e in other_client.get(f"{API}/groups/{gid}/leaderboard").json()["entries"])
    assert other_client.get(f"{API}/groups/{gid}/comments", params={"target": target}).status_code == 404


def test_shared_view_of_myself_uses_the_same_projection(client, sharer):
    set_share(client, sharer["group"], holdings=True)
    mine = client.get(f"{API}/groups/{sharer['group']}/members/{sharer['uid']}/shared").json()
    assert set(mine) == {"user_id", "display_name", "avatar_url", "holdings", "is_demo"}


def test_non_member_user_ids_are_404(client, other_client, sharer):
    gid = sharer["group"]
    outsider = make_group(other_client, "別的群組")
    assert other_client.get(f"{API}/groups/{gid}/members/usr_nobody/shared").status_code == 404
    feed = other_client.get(f"{API}/groups/{gid}/feed", params={"user_id": "usr_nobody"}).json()
    assert feed == {"items": [], "next_cursor": None}
    assert outsider
