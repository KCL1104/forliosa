"""「只記持股」 removed (product owner, 2026-11-14: every buy has a date): migration ``0018`` turns each holdings-only
account's snapshot into dated buys.

* the migration itself, on SQLite: which rows go, which come, which stay; downgrade and upgrade again;
* equivalence: an account the migration converted shows the same holdings, cost basis, realized P&L, closed rounds and
  automatic dividends as the holdings-only code did. The expected numbers were taken from the code before the mode was
  removed (the same snapshot, trades and ex-dividend notices through the API, 2026-11-14).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest
import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from forliosa.db import Money, TZDateTime, make_engine, set_engine
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import MarketEvent, Transaction, User
from forliosa.services.auto_dividends import sync_auto_dividends
from tests.test_migrations import _config

API = "/api/v1"
NOTE = "由「只記持股」轉入"
CREATED = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)

# The tables as they are at revision 0017 (typed like the app writes them).
USERS = sa.table("users", sa.column("id", sa.String), sa.column("email", sa.String),
                 sa.column("display_name", sa.String), sa.column("preferences", sa.JSON),
                 sa.column("created_at", TZDateTime()))
ACCOUNTS = sa.table("broker_accounts", sa.column("id", sa.String), sa.column("user_id", sa.String),
                    sa.column("name", sa.String), sa.column("broker", sa.String), sa.column("currency", sa.String),
                    sa.column("fee_rate", Money()), sa.column("fee_discount", Money()), sa.column("min_fee", Money()),
                    sa.column("min_fee_odd_lot", Money()), sa.column("tracking_mode", sa.String),
                    sa.column("created_at", TZDateTime()))
SNAPSHOTS = sa.table("holding_snapshots", sa.column("id", sa.String), sa.column("user_id", sa.String),
                     sa.column("account_id", sa.String), sa.column("as_of", sa.Date), sa.column("symbol", sa.String),
                     sa.column("quantity", Money()), sa.column("avg_cost", Money()),
                     sa.column("created_at", TZDateTime()))
TXNS = sa.table("transactions", *(sa.column(c, t) for c, t in (
    ("id", sa.String), ("user_id", sa.String), ("account_id", sa.String), ("symbol", sa.String), ("type", sa.String),
    ("trade_date", sa.Date), ("quantity", Money()), ("price", Money()), ("amount", Money()), ("fee", Money()),
    ("tax", Money()), ("health_insurance", Money()), ("currency", sa.String), ("is_day_trade", sa.Boolean),
    ("note", sa.Text), ("source", sa.String), ("created_at", TZDateTime()), ("updated_at", TZDateTime()))))

_n = iter(range(1000))


def user(uid: str, email: str) -> dict:
    return {"id": uid, "email": email, "display_name": uid, "preferences": {}, "created_at": CREATED}


def account(aid: str, uid: str, mode: str) -> dict:
    return {"id": aid, "user_id": uid, "name": aid, "broker": "永豐金證券", "currency": "TWD",
            "fee_rate": D("0.001425"), "fee_discount": D(1), "min_fee": D(20), "min_fee_odd_lot": D(1),
            "tracking_mode": mode, "created_at": CREATED}


def snap(aid: str, uid: str, as_of: date, symbol: str, qty: str, avg: str) -> dict:
    return {"id": f"hld_{next(_n)}", "user_id": uid, "account_id": aid, "as_of": as_of, "symbol": symbol,
            "quantity": D(qty), "avg_cost": D(avg), "created_at": CREATED}


def txn(aid: str, uid: str, type_: str, d: date, symbol: str | None = None, qty: str = "0", price: str = "0",
        amount: str = "0", fee: str = "0", tax: str = "0", note: str = "", source: str = "manual",
        tid: str | None = None) -> dict:
    return {"id": tid or f"txn_old{next(_n):04d}", "user_id": uid, "account_id": aid, "symbol": symbol, "type": type_,
            "trade_date": d, "quantity": D(qty), "price": D(price), "amount": D(amount), "fee": D(fee), "tax": D(tax),
            "health_insurance": D(0), "currency": "TWD", "is_day_trade": False, "note": note, "source": source,
            "created_at": CREATED, "updated_at": CREATED}


def at_0017(url: str, users: list[dict], accounts: list[dict], snapshots: list[dict], txns: list[dict]) -> None:
    command.upgrade(_config(url), "0017")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.insert(USERS), users)
            conn.execute(sa.insert(ACCOUNTS), accounts)
            if snapshots:
                conn.execute(sa.insert(SNAPSHOTS), snapshots)
            conn.execute(sa.insert(TXNS), txns)
    finally:
        engine.dispose()


# -- the migration ---------------------------------------------------------------------------------------------------
def test_migration_turns_snapshots_into_dated_buys(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    as_of = date(2026, 7, 1)
    u = "usr_a"
    at_0017(url, [user(u, "a@forliosa.local")], [
        account("acc_held", u, "holdings"),     # snapshot on 2026-07-01
        account("acc_empty", u, "holdings"),    # holdings-only, never saved a snapshot
        account("acc_txn", u, "transactions"),  # a snapshot left over from when it was holdings-only: never read
    ], [
        snap("acc_held", u, as_of, "2330.TW", "2000", "900"),
        snap("acc_held", u, as_of, "AAPL", "10.5", "150.1234"),
        snap("acc_txn", u, date(2026, 10, 1), "2317.TW", "1000", "100"),
    ], [
        txn("acc_held", u, "buy", date(2026, 5, 4), "2330.TW", "1000", "800", "800000", tid="txn_old_buy"),
        txn("acc_held", u, "cash_dividend", date(2026, 6, 11), "2330.TW", "1000", "5", "5000", source="auto",
            tid="txn_old_auto"),
        txn("acc_held", u, "buy", as_of, "2330.TW", "1000", "950", "950000", tid="txn_on_as_of"),
        txn("acc_held", u, "sell", date(2026, 8, 3), "2330.TW", "500", "1000", "500000", "712", "1500",
            tid="txn_later_sell"),
        txn("acc_empty", u, "buy", date(2026, 5, 4), "0050.TW", "100", "180", "18000", tid="txn_empty_buy"),
        txn("acc_txn", u, "buy", date(2026, 5, 4), "2317.TW", "1000", "100", "100000", tid="txn_txn_buy"),
    ])
    before = datetime.now(UTC)
    command.upgrade(_config(url), "head")
    engine = make_engine(url)
    try:
        insp = inspect(engine)
        assert "holding_snapshots" not in insp.get_table_names()
        assert "tracking_mode" not in {c["name"] for c in insp.get_columns("broker_accounts")}
        with Session(engine) as db:
            rows = {t.id: t for t in db.scalars(select(Transaction))}
        # on or before the snapshot date: gone (the snapshot already reflects them); later ones and other accounts stay
        assert {"txn_old_buy", "txn_old_auto", "txn_on_as_of"}.isdisjoint(rows)
        assert {"txn_later_sell", "txn_empty_buy", "txn_txn_buy"} <= set(rows)
        new = sorted((t for t in rows.values() if t.note == NOTE), key=lambda t: t.symbol)
        assert len(rows) == 5 and len(new) == 2
        for t, (symbol, qty, price, currency) in zip(new, [("2330.TW", "2000", "900", "TWD"),
                                                          ("AAPL", "10.5", "150.1234", "USD")], strict=True):
            assert (t.account_id, t.user_id, t.symbol, t.type, t.trade_date) == ("acc_held", u, symbol, "buy", as_of)
            assert (t.quantity, t.price, t.amount) == (D(qty), D(price), D(qty) * D(price))
            assert (t.fee, t.tax, t.health_insurance, t.currency, t.is_day_trade, t.source) == (
                0, 0, 0, currency, False, "manual")
            assert t.id.startswith("txn_") and len(t.id) == 30
            assert before <= t.created_at == t.updated_at <= datetime.now(UTC)
        assert new[1].amount == D("1576.2957")

        command.downgrade(_config(url), "0017")  # one-way: the column and an empty table come back
        insp = inspect(engine)
        assert "holding_snapshots" in insp.get_table_names()
        with engine.connect() as conn:
            assert set(conn.scalars(sa.text("SELECT tracking_mode FROM broker_accounts"))) == {"transactions"}
            assert conn.scalar(sa.text("SELECT count(*) FROM holding_snapshots")) == 0
            assert conn.scalar(sa.text("SELECT count(*) FROM transactions")) == 5
        command.upgrade(_config(url), "head")
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT count(*) FROM transactions")) == 5
            assert conn.scalar(sa.text("SELECT count(*) FROM broker_accounts")) == 3
    finally:
        engine.dispose()


# -- equivalence with the holdings-only ledger ------------------------------------------------------------------------
NOTICES = [  # (symbol, ex-date, cash per share, stock ratio)
    ("2330.TW", date(2026, 6, 11), "5.00000000", None),   # before the snapshot: never booked
    ("2330.TW", date(2026, 7, 1), "4.50000000", None),    # on the snapshot date: never booked
    ("2330.TW", date(2026, 9, 16), "5.00000000", None),   # after: 1,500 shares (after the sell)
    ("0056.TW", date(2026, 7, 16), "2.00000000", None),   # after: 5,000 (the 08-10 buy comes later)
    ("6488.TWO", date(2026, 8, 20), "3.00000000", "0.05000000"),  # cash and stock
]
# What the holdings-only code booked automatically for this account (all after the snapshot date).
AUTOS = [
    ("0056.TW", "2026-07-16", "cash_dividend", D(5000), D(2), D(10000), "5,000 股 × 每股 2 元"),
    ("6488.TWO", "2026-08-20", "cash_dividend", D(1000), D(3), D(3000), "1,000 股 × 每股 3 元"),
    ("6488.TWO", "2026-08-20", "stock_dividend", D(50), D("0.5"), D(0),
     "1,000 股 × 每股配股 0.5 元（面額 10 元），配發 50 股"),
    ("2330.TW", "2026-09-16", "cash_dividend", D(1500), D(5), D(7500), "1,500 股 × 每股 5 元"),
]


@pytest.fixture()
def converted(tmp_path, market):
    """A holdings-only account as the old code left it (snapshot, older trades it ignored, later trades, the automatic
    dividends it had booked), migrated to head; the app and an archive-backed market data point at that database."""
    url = f"sqlite:///{tmp_path / 'converted.db'}"
    u, a = "usr_held", "acc_held"
    as_of = date(2026, 7, 1)
    autos = [txn(a, u, t, date.fromisoformat(d), s, str(q), str(p), str(amt), note=note, source="auto")
             for s, d, t, q, p, amt, note in AUTOS]
    at_0017(url, [user(u, "demo@forliosa.local")], [account(a, u, "holdings")], [
        snap(a, u, as_of, "2330.TW", "2000", "900"),
        snap(a, u, as_of, "0056.TW", "5000", "30.5"),
        snap(a, u, as_of, "6488.TWO", "1000", "400.25"),
        snap(a, u, as_of, "AAPL", "10.5", "150.1234"),
    ], [
        txn(a, u, "deposit", date(2026, 4, 1), amount="2000000"),
        txn(a, u, "buy", date(2026, 5, 4), "2330.TW", "1000", "800", "800000"),
        txn(a, u, "buy", as_of, "2330.TW", "1000", "950", "950000"),
        txn(a, u, "sell", date(2026, 8, 3), "2330.TW", "500", "1000", "500000", "712", "1500"),
        txn(a, u, "buy", date(2026, 8, 10), "0056.TW", "1000", "32", "32000", "20"),
        txn(a, u, "sell", date(2026, 10, 5), "6488.TWO", "1050", "420", "441000"),
        *autos,
    ])
    command.upgrade(_config(url), "head")
    engine = make_engine(url)
    set_engine(engine)
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="personal")
    set_market_data(md)
    with Session(engine) as db:
        for symbol, ex, cash, ratio in NOTICES:
            source = "tpex-openapi" if symbol.endswith(".TWO") else "twse-openapi"
            db.add(MarketEvent(key=f"ex-{symbol}-{ex.isoformat()}", symbol=symbol, date=ex, type="ex_dividend",
                               title="除權息", detail="", source=source, data={"cash": cash, "stock_ratio": ratio}))
        db.commit()
    from forliosa.api.app import create_app

    client = TestClient(create_app())
    r = client.post(f"{API}/auth/dev-login", json={"email": "demo@forliosa.local"})
    assert r.status_code == 200 and r.json()["id"] == u
    yield client, engine, md, a
    set_market_data(market)
    engine.dispose()


def test_converted_account_keeps_its_holdings_and_dividends(converted):
    client, engine, md, acc = converted
    q = {"account_id": acc}
    held = {h["symbol"]: h for h in client.get(f"{API}/portfolio/holdings", params=q).json()}
    assert {s: (h["quantity"], h["avg_cost"], h["cost_basis"], h["currency"]) for s, h in held.items()} == {
        "2330.TW": (1500, 900, 1350000, "TWD"),
        "0056.TW": (6000, 30.7533, 184520, "TWD"),
        "AAPL": (10.5, 150.1234, 49856.66, "USD"),  # at the USD/TWD rate of the snapshot date
    }
    summary = client.get(f"{API}/portfolio/summary", params=q).json()
    assert (summary["cost_basis"], summary["realized_pnl"], summary["dividend_income"]) == (1584376.66, 88538, 20500)
    closed = client.get(f"{API}/portfolio/closed", params=q).json()
    assert [{k: c[k] for k in ("symbol", "opened_at", "closed_at", "total_bought_qty", "total_sold_qty", "cost_basis",
                               "realized_pnl", "dividends_received", "fees_and_taxes")} for c in closed] == [
        {"symbol": "6488.TWO", "opened_at": "2026-07-01", "closed_at": "2026-10-05", "total_bought_qty": 1000,
         "total_sold_qty": 1050, "cost_basis": 400250, "realized_pnl": 40750, "dividends_received": 3000,
         "fees_and_taxes": 0}]

    # the automatic dividends the holdings-only code booked are exactly what the sync wants now: nothing changes
    with Session(engine) as db:
        user = db.get(User, "usr_held")
        result = sync_auto_dividends(db, user, md, today=date(2026, 11, 14))
        assert not result.changed, result
        db.commit()
        autos = sorted((t.symbol, t.trade_date.isoformat(), t.type, t.quantity, t.price, t.amount, t.note)
                       for t in db.scalars(select(Transaction).where(Transaction.source == "auto")))
    assert autos == sorted(AUTOS)
