"""M5 leaderboard: periods with a common start date, TWR per member, ranking (ties, nulls, unranked), benchmarks;
``/portfolio/performance?range=MTD``; the crypto helpers behind invites, feed ids and webhook encryption."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from forliosa.marketdata.base import HistoryResult
from forliosa.services import sharing
from forliosa.timeutil import TAIPEI, last_tw_trading_day, today_taipei
from tests.api.m5 import API, account, join, login, make_group, me_id, set_share, trade


def test_rank_entries_ties_nulls_and_unranked():
    entries = [{"user_id": u, "return_pct": r} for u, r in
               (("a", 0.0123), ("b", None), ("c", 0.05), ("d", 0.0123), ("e", -0.01))]
    ranked = sharing.rank_entries(entries, ranked=True)
    assert [(e["user_id"], e["rank"]) for e in ranked] == [("c", 1), ("a", 2), ("d", 2), ("e", 4), ("b", None)]
    unranked = sharing.rank_entries(entries, ranked=False)
    assert [(e["user_id"], e["rank"]) for e in unranked] == [("a", None), ("b", None), ("c", None), ("d", None),
                                                             ("e", None)]
    assert sharing.pct(0.012345) == 0.0123 and sharing.pct(0.00005) == 0.0001 and sharing.weight(0.4249) == 0.42


def test_period_window_starts(market):
    end = date(2026, 11, 12)
    w = sharing.period_window(market, end)
    assert w.end == end
    assert w.starts == {"day": date(2026, 11, 11), "month": date(2026, 10, 30), "year": date(2025, 12, 31)}
    assert not w.clipped


def test_period_window_is_clipped_to_the_archive_under_commercial(monkeypatch, market):
    monkeypatch.setattr(market, "policy", "commercial")
    monkeypatch.setattr(market, "archive_since", lambda symbol=None: date(2026, 11, 3))
    w = sharing.period_window(market, date(2026, 11, 12))
    assert w.starts == {"day": date(2026, 11, 11), "month": date(2026, 11, 3), "year": date(2026, 11, 3)}
    assert w.clipped and w.archive_since == date(2026, 11, 3)


def test_latest_close_follows_the_clock(market):
    monday = datetime(2026, 11, 9, 10, 0, tzinfo=TAIPEI)  # before the close: Friday's close
    assert sharing.latest_close(market, monday) == date(2026, 11, 6)
    after = datetime(2026, 11, 9, 14, 0, tzinfo=TAIPEI)
    assert sharing.latest_close(market, after) <= date(2026, 11, 9)


@pytest.fixture()
def board(app, client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    third = login(app, "third@forliosa.local", "老三")
    join(client, third, g["id"])
    set_share(third, g["id"])  # shares nothing: not on the board
    a = account(client)
    b = account(other_client)
    trade(client, a["id"], "2330.TW", "buy", date(2024, 6, 3), 1000, 800)
    trade(other_client, b["id"], "0050.TW", "buy", date(2024, 6, 3), 1000, 150)
    return {"gid": g["id"], "a": me_id(client), "b": me_id(other_client), "c": me_id(third), "third": third}


def test_leaderboard_api(client, other_client, board, market):
    r = client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "month"})
    assert r.status_code == 200, r.text
    lb = r.json()
    w = sharing.period_window(market)
    assert lb["period"] == "month" and lb["date"] == w.end.isoformat()
    assert lb["start_date"] == w.starts["month"].isoformat() and lb["ranked"] is True
    assert lb["as_of"] == f"{w.end.isoformat()}T13:30:00+08:00"
    users = [e["user_id"] for e in lb["entries"]]
    assert set(users) == {board["a"], board["b"]} and board["c"] not in users
    assert sorted(e["rank"] for e in lb["entries"]) in ([1, 2], [1, 1])
    me = next(e for e in lb["entries"] if e["is_me"])
    assert me["user_id"] == board["a"] and me["total_return_pct"] is not None
    assert [b["symbol"] for b in lb["benchmarks"]] == ["^TAIEXTR", "0050.TW"]
    assert lb["benchmarks"][1]["name"] == "元大台灣50" and lb["benchmarks"][1]["return_pct"] is not None
    assert lb["sources"] and lb["is_demo"] is True
    # Member A's month return = the stock's close-to-close change (no flows in the month).
    closes = {c.t: c.c for c in market.history("2330.TW", w.starts["month"] - timedelta(days=14), w.end).candles}
    start = closes[max(d for d in closes if d <= w.starts["month"])]
    end = closes[max(d for d in closes if d <= w.end)]
    assert me["return_pct"] == sharing.pct(float(end / start) - 1)
    # B's 0050 month return equals the 0050 benchmark only without an ex-dividend in the month; check the day.
    day = client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "day"}).json()
    assert day["start_date"] == w.starts["day"].isoformat()
    assert client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "week"}).status_code == 422
    # SharedPortfolio.returns uses the same numbers.
    shared = other_client.get(f"{API}/groups/{board['gid']}/members/{board['a']}/shared").json()
    assert shared["returns"]["month"] == me["return_pct"] and shared["returns"]["total"] == me["total_return_pct"]


def test_leaderboard_carries_the_day_threads_reactions(client, other_client, board):
    """``reactions`` and ``comment_count`` of ``leaderboard:<date>`` (4-3), like feed items and digests: tallies
    only, the same for every period. The thread of the board's own date works even when the group was made after
    that close (a weekend, or before 13:30)."""
    gid = board["gid"]
    day = client.get(f"{API}/groups/{gid}/leaderboard", params={"period": "day"}).json()
    assert day["reactions"] == [] and day["comment_count"] == 0
    target = f"leaderboard:{day['date']}"
    for c, emoji in ((client, "🎉"), (other_client, "🎉"), (other_client, "👍"), (board["third"], "🎉")):
        r = c.put(f"{API}/groups/{gid}/reactions", json={"target": target, "emoji": emoji})
        assert r.status_code == 200, r.text
    assert client.post(f"{API}/groups/{gid}/comments", json={"target": target, "body": "大家都紅"}).status_code == 201
    month = client.get(f"{API}/groups/{gid}/leaderboard", params={"period": "month"}).json()
    assert month["date"] == day["date"] and month["comment_count"] == 1
    assert month["reactions"] == [{"emoji": "👍", "count": 1, "mine": False}, {"emoji": "🎉", "count": 3, "mine": True}]
    seen = other_client.get(f"{API}/groups/{gid}/leaderboard", params={"period": "year"}).json()
    assert seen["reactions"] == [{"emoji": "👍", "count": 1, "mine": True}, {"emoji": "🎉", "count": 3, "mine": True}]
    # counts only: nobody is named, and the member who shares nothing is still not on the board
    assert board["c"] not in str(seen) and {e["user_id"] for e in seen["entries"]} == {board["a"], board["b"]}
    assert client.delete(f"{API}/groups/{gid}/reactions", params={"target": target, "emoji": "🎉"}).status_code == 200
    again = client.get(f"{API}/groups/{gid}/leaderboard", params={"period": "day"}).json()
    assert again["reactions"][1] == {"emoji": "🎉", "count": 2, "mine": False}


def test_board_thread_of_the_close_before_the_group_was_made(board, market):
    """A group made on Saturday shows Friday's board: that day's thread (comments, reactions) is a valid target."""
    from forliosa.db import session_factory
    from forliosa.models import Group

    with session_factory()() as db:
        g = db.get(Group, board["gid"])
        g.created_at = datetime(2026, 11, 14, 10, 0, tzinfo=TAIPEI)  # a Saturday
        members = sharing.members_of(db, g.id)
        first = sharing.latest_close(market, g.created_at)
        assert first <= date(2026, 11, 13)
        assert sharing.target_visible(db, market, g, members, f"leaderboard:{first.isoformat()}")
        assert not sharing.target_visible(db, market, g, members, "leaderboard:2026-10-30")  # before the group


def test_unranked_board_keeps_join_order(client, other_client, board):
    client.patch(f"{API}/groups/{board['gid']}", json={"ranking_enabled": False})
    lb = other_client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "year"}).json()
    assert lb["ranked"] is False
    assert [(e["user_id"], e["rank"]) for e in lb["entries"]] == [(board["a"], None), (board["b"], None)]


def test_member_without_prices_has_no_periods_and_ranks_last(client, other_client, board, market, monkeypatch):
    real = market.history

    def no_tsmc(symbol, start, end):
        if symbol == "2330.TW":
            return HistoryResult(symbol, [], False, "")
        return real(symbol, start, end)

    monkeypatch.setattr(market, "history", no_tsmc)
    lb = other_client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "day"}).json()
    assert [(e["user_id"], e["rank"], e["return_pct"]) for e in lb["entries"]][-1] == (board["a"], None, None)
    assert lb["entries"][0]["rank"] == 1
    shared = other_client.get(f"{API}/groups/{board['gid']}/members/{board['a']}/shared").json()
    assert (shared["returns"]["day"], shared["returns"]["month"], shared["returns"]["year"]) == (None, None, None)


def test_holdings_without_closes_are_left_out_of_the_periods(client, other_client, board, market, monkeypatch):
    """A member who also holds something with no close (US stocks under commercial) still gets period returns — on
    the priced holdings only, like the ledger's 今日. Only the member's own row says so."""
    a2 = account(client)
    trade(client, a2["id"], "2317.TW", "buy", date(2024, 6, 3), 1000, 100)
    month = client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "month"}).json()
    before = next(e for e in month["entries"] if e["is_me"])["return_pct"]
    real = market.history

    def no_hon_hai(symbol, start, end):
        if symbol == "2317.TW":
            return HistoryResult(symbol, [], False, "")
        return real(symbol, start, end)

    monkeypatch.setattr(market, "history", no_hon_hai)
    lb = client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "month"}).json()
    me = next(e for e in lb["entries"] if e["is_me"])
    assert me["return_pct"] is not None and me["rank"] is not None and me["excludes_unpriced"] is True
    w = sharing.period_window(market)
    closes = {c.t: c.c for c in market.history("2330.TW", w.starts["month"] - timedelta(days=14), w.end).candles}
    start = closes[max(d for d in closes if d <= w.starts["month"])]
    end = closes[max(d for d in closes if d <= w.end)]
    assert me["return_pct"] == sharing.pct(float(end / start) - 1)  # 2330 alone
    assert before is not None
    # another member does not learn that A holds something without a close
    seen = other_client.get(f"{API}/groups/{board['gid']}/leaderboard", params={"period": "month"}).json()
    assert all(e["excludes_unpriced"] is False for e in seen["entries"])


def test_member_starting_mid_period_counts_from_the_first_holding(app, client, board, market):
    late = login(app, "late@forliosa.local", "新手")
    join(client, late, board["gid"])
    acc = account(late)
    w = sharing.period_window(market)
    buy_day = last_tw_trading_day(w.end - timedelta(days=1))
    if buy_day <= w.starts["month"]:
        pytest.skip("too early in the month for a mid-month start")
    trade(late, acc["id"], "2330.TW", "buy", buy_day, 1000, 1)  # an absurd price: the day's flow is the inflow
    r = sharing.member_period_returns(_db(), market, _user(me_id(late)), w)
    closes = {c.t: c.c for c in market.history("2330.TW", buy_day - timedelta(days=14), w.end).candles}
    c_buy = closes[max(d for d in closes if d <= buy_day)]
    c_end = closes[max(d for d in closes if d <= w.end)]
    fee = Decimal(0)  # no automatic commission (2026-11-14)
    expected = float((1000 * c_buy) / (Decimal(1000) + fee)) - 1 if buy_day == w.end else None
    assert r["month"] is not None and r["year"] == r["month"]
    if expected is None:  # bought before the last day: buy-day return × later days
        later = float(c_end / c_buy)
        assert r["month"] == pytest.approx((float(1000 * c_buy / (Decimal(1000) + fee))) * later - 1, rel=1e-9)


def _db():
    from forliosa.db import session_factory

    return session_factory()()


def _user(uid):
    from forliosa.models import User

    db = _db()
    return db.get(User, uid)


def test_performance_mtd_range(client):
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2024, 6, 3), 1000, 800)
    perf = client.get(f"{API}/portfolio/performance", params={"range": "MTD"}).json()
    end = date.fromisoformat(perf["end_date"])
    assert perf["range"] == "MTD"
    assert perf["start_date"] == last_tw_trading_day(end.replace(day=1) - timedelta(days=1)).isoformat()
    assert perf["series"][0]["twr_index"] == 1.0
    assert client.get(f"{API}/portfolio/performance", params={"range": "QTD"}).status_code == 422
    # A portfolio that starts this month starts on its first day (like the long ranges).
    # Use the latest day the server has a close for (``end``), not "today": before 13:30 on a trading day today's
    # close does not exist yet, and the test must not depend on the wall clock.
    fresh = account(client, "新帳戶")
    first = end
    if first.month == today_taipei().month:
        trade(client, fresh["id"], "2317.TW", "buy", first, 1000, 100)
        perf = client.get(f"{API}/portfolio/performance", params={"range": "MTD", "account_id": fresh["id"]}).json()
        assert perf["start_date"] == first.isoformat()


def test_crypto_helpers(monkeypatch):
    from forliosa.config import get_settings
    from forliosa.crypto import decrypt_secret, encrypt_secret, keyed_id, token_hash

    url = "https://discord.com/api/webhooks/123/abc"
    enc = encrypt_secret(url)
    assert url not in enc and decrypt_secret(enc) == url
    assert decrypt_secret(enc[:-2] + "xx") is None
    a = keyed_id("feed-item-id", "x")
    assert len(a) == 26 and a == keyed_id("feed-item-id", "x") and a != keyed_id("other", "x")
    assert len(token_hash("t")) == 64
    monkeypatch.setenv("SESSION_SECRET", "rotated-" + "z" * 40)
    get_settings.cache_clear()
    try:
        assert decrypt_secret(enc) is None  # a rotated SESSION_SECRET cannot read old ciphertexts
        assert keyed_id("feed-item-id", "x") != a
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
