"""Client tools: always scoped to the signed-in user; draft_transaction never writes the ledger; schemas stay
inside the strict-tool limits."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai.tools import TOOLS, ToolContext, client_tool_definitions, execute, server_tools
from forliosa.config import get_settings
from forliosa.marketdata.service import get_market_data
from forliosa.models import AiDraft, Transaction, User
from tests.ai.conftest import API, buy, chat, make_account
from tests.ai.fake_anthropic import text, tool_use


def user_by_email(db: Session, email: str) -> User:
    return db.scalar(select(User).where(User.email == email))


def txn_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Transaction))


@pytest.fixture()
def two_users(client, other_client, engine):
    """demo user holds 2330 in one account; the other user holds 0050 in their own account."""
    mine = make_account(client, "我的帳戶")
    buy(client, mine, "2330", 1000, 600)
    theirs = make_account(other_client, "別人的帳戶")
    buy(other_client, theirs, "0050", 3000, 150)
    db = Session(engine)
    me = user_by_email(db, "demo@forliosa.local")
    yield db, ToolContext(db=db, user=me, md=get_market_data()), mine, theirs
    db.close()


def run(ctx, name, **args):
    out = execute(ctx, name, args)
    return out, (json.loads(out.content) if not out.is_error else out.content)


def test_schemas_are_strict_and_within_limits():
    s = get_settings()
    defs = client_tool_definitions(s)
    assert len(defs) <= 20  # strict tools per request
    optional = sum(len(d["input_schema"]["properties"]) - len(d["input_schema"]["required"]) for d in defs)
    assert optional <= 24  # optional parameters across all strict schemas
    for d in defs:
        schema = d["input_schema"]
        assert d["strict"] is True and schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        assert "user_id" not in schema["properties"]
        for p in schema["properties"].values():
            assert not {"minimum", "maximum", "minLength", "maxLength", "anyOf"} & set(p)
    assert [d["name"] for d in defs] == sorted(d["name"] for d in defs)  # deterministic order for caching
    names = {t.name for t in TOOLS}
    assert names == {"get_portfolio_summary", "get_holdings", "get_transactions", "get_upcoming",
                     "get_stock_overview", "get_stock_history", "get_valuation", "get_chips", "get_financials",
                     "get_events", "get_news", "get_position", "search_instruments", "draft_transaction"}
    st = server_tools(s)
    assert [t["name"] for t in st] == ["web_search", "web_fetch"]
    assert st[1]["citations"] == {"enabled": True}


def test_portfolio_tools_only_see_own_data(two_users):
    _db, ctx, mine, theirs = two_users
    _, holdings = run(ctx, "get_holdings")
    assert [h["symbol"] for h in holdings["holdings"]] == ["2330.TW"]
    _, summary = run(ctx, "get_portfolio_summary")
    assert [a["id"] for a in summary["accounts"]] == [mine]
    _, txns = run(ctx, "get_transactions")
    assert [t["symbol"] for t in txns["transactions"]] == ["2330.TW"]
    _, txns = run(ctx, "get_transactions", symbol="0050")
    assert txns["transactions"] == []
    _, pos = run(ctx, "get_position", symbol="0050")
    assert pos["held"] is False
    # another user's account id is rejected, not used as a filter
    for name in ("get_holdings", "get_portfolio_summary", "get_transactions"):
        out, msg = run(ctx, name, account_id=theirs)
        assert out.is_error and "找不到" in msg
    out, msg = run(ctx, "draft_transaction", type="sell", symbol="0050", account_id=theirs, quantity=1000, price=150)
    assert out.is_error and "找不到這個帳戶" in msg


def test_unknown_arguments_are_rejected(two_users):
    _db, ctx, *_ = two_users
    out = execute(ctx, "get_holdings", {"user_id": "usr_other"})
    assert out.is_error and "user_id" in out.content
    out = execute(ctx, "no_such_tool", {})
    assert out.is_error
    out = execute(ctx, "get_holdings", "not-an-object")
    assert out.is_error and "INVALID_JSON" in out.content


def test_draft_transaction_never_writes(two_users):
    db, ctx, mine, _ = two_users
    before = txn_count(db)
    out, res = run(ctx, "draft_transaction", type="buy", symbol="0050", quantity=2000, price=52.4)
    assert not out.is_error
    assert res["status"] == "pending_signature" and res["draft_id"].startswith("drf_")
    assert res["preview"]["gross"] == 104800 and res["preview"]["fee"] == 41  # 104,800 × 0.1425% × 0.28
    assert txn_count(db) == before
    card = out.draft
    assert card["input"] == {"account_id": mine, "symbol": "0050.TW", "type": "buy", "trade_date": card["input"]
                             ["trade_date"], "quantity": 2000, "price": 52.4, "amount": None, "currency": "TWD",
                             "is_day_trade": False, "note": "", "source": "ai_draft"}
    assert card["instrument"]["name"] == "元大台灣50" and card["account"] == {"id": mine, "name": "我的帳戶"}
    d = db.get(AiDraft, res["draft_id"])
    assert d.status == "pending" and d.user_id == ctx.user.id
    # no price: estimated from the latest close and explained in notes
    out, res = run(ctx, "draft_transaction", type="buy", symbol="台積電", quantity=1000)
    assert not out.is_error and "收盤價" in out.draft["notes"][0]
    assert txn_count(db) == before


def test_draft_rejects_inconsistent_ledger(two_users):
    db, ctx, *_ = two_users
    before = (txn_count(db), db.scalar(select(func.count()).select_from(AiDraft)))
    out, _msg = run(ctx, "draft_transaction", type="sell", symbol="2330", quantity=5000, price=700)
    assert out.is_error and out.draft is None
    assert (txn_count(db), db.scalar(select(func.count()).select_from(AiDraft))) == before


def test_draft_asks_for_account_when_ambiguous(client, two_users):
    _db, ctx, mine, _ = two_users
    second = make_account(client, "國泰")
    _, res = run(ctx, "draft_transaction", type="buy", symbol="0050", quantity=1000, price=150)
    assert res["status"] == "need_account" and {a["id"] for a in res["accounts"]} == {mine, second}
    # selling a stock held in exactly one account picks that account
    out, res = run(ctx, "draft_transaction", type="sell", symbol="2330", quantity=1000, price=700)
    assert not out.is_error and out.draft["account"]["id"] == mine


def test_stock_tools_return_compact_json(two_users):
    _db, ctx, *_ = two_users
    for name, args in [("get_stock_overview", {"symbol": "2330"}),
                       ("get_stock_history", {"symbol": "2330", "range": "1Y"}),
                       ("get_valuation", {"symbol": "2330"}),
                       ("get_chips", {"symbol": "2330", "range": "3M"}),
                       ("get_financials", {"symbol": "2330", "period": "quarterly"}),
                       ("get_events", {"symbol": "2330", "mine_only": False}),
                       ("get_news", {"symbol": "2330"}),
                       ("get_upcoming", {"days": 30}),
                       ("search_instruments", {"query": "台積"})]:
        out = execute(ctx, name, args)
        assert not out.is_error, (name, out.content)
        assert len(out.content) < 14_100
        json.loads(out.content)
    _, hist = run(ctx, "get_stock_history", symbol="2330", range="1Y")
    assert len(hist["closes"]) <= 31 and hist["stats"]["days"] > 100


def test_draft_event_and_signature_flow(client, pool, fake, engine):
    acc = make_account(client)
    fake.reply(tool_use("toolu_d", "draft_transaction", {"type": "buy", "symbol": "0050", "quantity": 2000,
                                                         "price": 52.4}), stop_reason="tool_use")
    fake.reply(text("草稿已準備好，請確認。\n僅供參考，非投資建議。"))
    with Session(engine) as db:
        before = txn_count(db)
    _status, events = chat(client, "買 0050 2 張 52.4")
    drafts = [d for n, d in events if n == "draft"]
    assert len(drafts) == 1 and drafts[0]["status"] == "pending" and drafts[0]["preview"]["gross"] == 104800
    with Session(engine) as db:
        assert txn_count(db) == before  # the AI never writes the ledger
    # the user signs: the frontend posts the draft input to the normal endpoint, then marks the draft signed
    r = client.post(f"{API}/transactions", json=drafts[0]["input"])
    assert r.status_code == 201 and r.json()["source"] == "ai_draft" and r.json()["account_id"] == acc
    pending = client.get(f"{API}/ai/drafts").json()
    assert [d["id"] for d in pending] == [drafts[0]["id"]]
    r2 = client.patch(f"{API}/ai/drafts/{drafts[0]['id']}", json={"status": "signed", "transaction_id": r.json()["id"]})
    assert r2.status_code == 200 and r2.json()["status"] == "signed"
    assert client.get(f"{API}/ai/drafts").json() == []
    # undo: the transaction is deleted and the draft waits for a signature again
    assert client.delete(f"{API}/transactions/{r.json()['id']}").status_code == 204
    back = client.patch(f"{API}/ai/drafts/{drafts[0]['id']}", json={"status": "pending"}).json()
    assert back["status"] == "pending" and back["transaction_id"] is None
    r = client.post(f"{API}/transactions", json=drafts[0]["input"])
    client.patch(f"{API}/ai/drafts/{drafts[0]['id']}", json={"status": "signed", "transaction_id": r.json()["id"]})
    detail = client.get(f"{API}/ai/threads/{events[0][1]['id']}").json()
    assert detail["messages"][1]["drafts"][0]["status"] == "signed"


def test_drafts_are_private(client, other_client, pool, fake):
    make_account(client)
    fake.reply(tool_use("toolu_d", "draft_transaction", {"type": "deposit", "symbol": "", "amount": 10000}),
               stop_reason="tool_use").reply(text("好"))
    _, events = chat(client, "存入 1 萬")
    draft_id = next(d for n, d in events if n == "draft")["id"]
    assert other_client.get(f"{API}/ai/drafts").json() == []
    assert other_client.patch(f"{API}/ai/drafts/{draft_id}", json={"status": "discarded"}).status_code == 404
    other_acc = make_account(other_client, "別人")
    txn = other_client.post(f"{API}/transactions", json={"account_id": other_acc, "type": "deposit",
                                                        "trade_date": "2026-01-02", "amount": 1}).json()
    r = client.patch(f"{API}/ai/drafts/{draft_id}", json={"status": "signed", "transaction_id": txn["id"]})
    assert r.status_code == 404  # cannot attach someone else's transaction
    assert client.patch(f"{API}/ai/drafts/{draft_id}", json={"status": "discarded"}).json()["status"] == "discarded"
