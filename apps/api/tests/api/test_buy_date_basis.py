"""資產組成原型 (``docs/proposals/asset-composition.md`` 附錄 B): a 匯入庫存 buy's date and how it came about.

* migration 0029 (``date_basis``, ``estimated_date``, ``imported_on``) both ways, keeping every row;
* the transaction API shows the three fields (null for every normal row); ``PATCH`` makes an imported buy ``picked``
  when its date changes, refuses a date after its import day and leaves the other fields alone;
* ``POST /imports/positions`` estimates each row's buy date from the prices as traded (the history backfill's days
  multiplied back for a known split) and says why when it cannot; ``…/commit`` stores the basis; without the new
  fields both are as before;
* ``GET /instruments/{symbol}/history?prices=as_traded``: the same shape at the prices as traded, the Yahoo note and
  source; without the parameter unchanged.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from forliosa.ai.keypool import KeyPool, set_key_pool
from forliosa.config import get_settings
from forliosa.db import make_engine
from forliosa.domain.buy_date import estimate_buy_date
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import Candle
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import MarketEvent, Transaction
from forliosa.timeutil import today_taipei
from tests.ai.fake_anthropic import FakeAnthropic
from tests.api.m5 import API, account, trade, trading_day
from tests.api.test_positions_import import answer, doc, p, read
from tests.composition_fixture import build_archive
from tests.test_migrations import _config, _insert

COMMIT = f"{API}/imports/positions/commit"
SPLIT_0050 = date(2025, 6, 18)  # catalog.KNOWN_SPLITS: 1 -> 4


# -- migration 0029 ---------------------------------------------------------------------------------------------------
def test_buy_date_columns_keep_every_row_both_ways(tmp_path):
    url = f"sqlite:///{tmp_path / 'basis.db'}"
    command.upgrade(_config(url), "0028_remove_blind_test")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            _insert(conn, "users", {"id": "usr_1", "email": "a@b.c"})
            _insert(conn, "broker_accounts", {"id": "acc_1", "user_id": "usr_1"})
            _insert(conn, "transactions", {"id": "txn_1", "user_id": "usr_1", "account_id": "acc_1", "type": "buy"})
        command.upgrade(_config(url), "0029_buy_date_basis")
        cols = {c["name"] for c in inspect(engine).get_columns("transactions")}
        assert {"date_basis", "estimated_date", "imported_on"} <= cols
        with engine.begin() as conn:
            assert conn.execute(text("SELECT date_basis, estimated_date, imported_on FROM transactions")).one() == (
                None, None, None)
            conn.execute(text("UPDATE transactions SET date_basis = 'estimated', estimated_date = '2025-07-02', "
                              "imported_on = '2025-11-29'"))
        command.downgrade(_config(url), "0028_remove_blind_test")
        cols = {c["name"] for c in inspect(engine).get_columns("transactions")}
        assert not {"date_basis", "estimated_date", "imported_on"} & cols
        with engine.begin() as conn:
            assert conn.execute(text("SELECT id FROM transactions")).scalars().all() == ["txn_1"]
    finally:
        engine.dispose()


# -- the transaction API and PATCH ------------------------------------------------------------------------------------
def _imported(engine, txn_id: str, basis: str | None, estimated: date | None, imported_on: date) -> None:
    with Session(engine) as db:
        t = db.get(Transaction, txn_id)
        t.date_basis, t.estimated_date, t.imported_on, t.source = basis, estimated, imported_on, "import"
        db.commit()


def test_a_normal_row_shows_the_fields_as_null(client):
    acc = account(client)["id"]
    t = trade(client, acc, "2330", "buy", trading_day(30), 1000, 500)
    assert (t["date_basis"], t["estimated_date"], t["imported_on"]) == (None, None, None)
    listed = client.get(f"{API}/transactions").json()["items"][0]
    assert {k: listed[k] for k in ("date_basis", "estimated_date", "imported_on")} == dict.fromkeys(
        ("date_basis", "estimated_date", "imported_on"))


def test_changing_an_estimated_buys_date_makes_it_picked_and_leaves_the_rest(client, engine):
    acc = account(client)["id"]
    est, imported = trading_day(200), trading_day(20)
    t = trade(client, acc, "2330", "buy", est, 1000, 512.5, fee=0)
    _imported(engine, t["id"], "estimated", est, imported)
    got = client.get(f"{API}/transactions/{t['id']}").json()
    assert (got["date_basis"], got["estimated_date"], got["imported_on"]) == ("estimated", est.isoformat(),
                                                                              imported.isoformat())
    # the full form sends the whole row back with the same date: still estimated
    same = client.patch(f"{API}/transactions/{t['id']}", json={"trade_date": est.isoformat(), "note": "備註"})
    assert same.status_code == 200 and same.json()["date_basis"] == "estimated"
    # a date-only change (no fee sent): picked, the estimate kept, price / shares / fee untouched
    day = trading_day(150)
    r = client.patch(f"{API}/transactions/{t['id']}", json={"trade_date": day.isoformat()})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["date_basis"] == "picked" and out["trade_date"] == day.isoformat()
    assert out["estimated_date"] == est.isoformat() and out["imported_on"] == imported.isoformat()
    assert (out["quantity"], out["price"], out["fee"], out["tax"], out["source"]) == (1000, 512.5, 0, 0, "import")
    # a hint other than picked does not turn it back
    back = client.patch(f"{API}/transactions/{t['id']}", json={"date_basis": "estimated"})
    assert back.status_code == 200 and back.json()["date_basis"] == "picked"


def test_a_date_after_the_import_day_is_refused(client, engine):
    acc = account(client)["id"]
    imported = trading_day(20)
    t = trade(client, acc, "2330", "buy", trading_day(100), 1000, 500)
    _imported(engine, t["id"], "estimated", trading_day(100), imported)
    r = client.patch(f"{API}/transactions/{t['id']}", json={"trade_date": (imported + timedelta(days=1)).isoformat(),
                                                            "date_basis": "picked"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "after_import_day"
    assert imported.strftime("%Y/%m/%d") in r.json()["error"]["message"]
    assert client.get(f"{API}/transactions/{t['id']}").json()["date_basis"] == "estimated"  # nothing changed
    ok = client.patch(f"{API}/transactions/{t['id']}", json={"trade_date": imported.isoformat()})  # the day itself
    assert ok.status_code == 200 and ok.json()["date_basis"] == "picked"


def test_picked_without_a_date_change_and_import_day_rows(client, engine):
    acc = account(client)["id"]
    a = trade(client, acc, "2330", "buy", trading_day(60), 1000, 500)
    _imported(engine, a["id"], "estimated", trading_day(60), trading_day(10))
    r = client.patch(f"{API}/transactions/{a['id']}", json={"date_basis": "picked"})  # the user confirms the day
    assert r.status_code == 200 and r.json()["date_basis"] == "picked"
    b = trade(client, acc, "2317", "buy", trading_day(10), 1000, 100)
    _imported(engine, b["id"], "import_day", None, trading_day(10))
    r = client.patch(f"{API}/transactions/{b['id']}", json={"trade_date": trading_day(40).isoformat(), "fee": 0,
                                                            "tax": 0, "date_basis": "picked"})
    assert r.status_code == 200 and r.json()["date_basis"] == "picked" and r.json()["estimated_date"] is None


def test_a_normal_row_ignores_date_basis(client):
    acc = account(client)["id"]
    t = trade(client, acc, "2330", "buy", trading_day(30), 1000, 500, fee=20)
    r = client.patch(f"{API}/transactions/{t['id']}", json={"trade_date": trading_day(40).isoformat(),
                                                            "date_basis": "picked"})
    assert r.status_code == 200 and r.json()["date_basis"] is None
    # a normal row's date change re-derives the fee it was not sent, as before (0 for a buy)
    assert r.json()["fee"] == 0
    assert client.patch(f"{API}/transactions/{t['id']}", json={"date_basis": "guessed"}).status_code == 422


# -- the commercial archive: prices as traded ------------------------------------------------------------------------
@pytest.fixture()
def arch(engine, market, monkeypatch):
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    monkeypatch.setenv("US_PRICE_SOURCE", "databento")
    monkeypatch.setenv("IMPORT_STATEMENTS", "all")
    monkeypatch.setenv("AI_MODEL_IMPORT_RETRY", "")
    get_settings.cache_clear()
    archive = build_archive(engine, years=5, symbols=["2330.TW", "2317.TW", "0050.TW", "6488.TWO", "VOO"])
    set_market_data(MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True),
                                DemoProvider()], policy="commercial"))
    yield archive
    set_market_data(market)
    get_settings.cache_clear()


def _as_traded_0050(archive) -> list[Candle]:
    """0050 as it traded: the synthetic bars are split-adjusted (like Yahoo's) — ×4 before 2025-06-18."""
    out = []
    for d, (o, h, lo, c) in sorted(archive.bars["0050.TW"].items()):
        f = D(4) if d < SPLIT_0050 else D(1)
        out.append(Candle(d, o * f, h * f, lo * f, c * f, 0))
    return out


@pytest.fixture()
def fake():
    f = FakeAnthropic()
    set_key_pool(KeyPool.from_keys(["sk-test-key-one"], client_factory=f.client, sleep=lambda _s: None))
    yield f
    set_key_pool(None)


def test_reading_holdings_estimates_each_buy_date(client, arch, fake):
    acc = account(client)["id"]
    days = arch.days
    traded = _as_traded_0050(arch)
    # 0050 bought before its 2025 1-to-4 split: the broker shows the cost in today's shares (a quarter); between the
    # old and the new price, the split day's drop would read as a gap «over» it
    before_split = next(c for c in reversed(traded) if c.t < SPLIT_0050 - timedelta(days=30))
    cost_old = before_split.c
    after_split = next(c for c in traded if c.t > SPLIT_0050 + timedelta(days=60))
    cost_new = after_split.c
    cost_2330 = arch.close("2330.TW", days[-200])
    answer(fake, doc([
        p("2330", "台積電", "1000", avg=str(cost_2330)),
        p("0050", "元大台灣50", "1000", avg=str(cost_old)),
        p("0050", "元大台灣50", "4000", avg=str(cost_new)),
        p("2317", "鴻海", "1000", avg="1"),  # below every price in five years
        p("VOO", "Vanguard S&P 500", "10", avg="0.5", currency="USD"),
        p("2317", "鴻海", "1000", avg="100", kind="short"),  # 融券: never imported, not estimated
        p("9999", "不存在", "1000", avg="10"),  # no such stock
    ]))
    r = read(client, account_id=acc)
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    today = today_taipei()
    tw_bars = [Candle(d, *arch.bars["2330.TW"][d], 0) for d in days]
    assert rows[0]["estimated_date"] == estimate_buy_date(tw_bars, cost_2330, today).isoformat()
    assert rows[0]["estimated_date"] >= days[-200].isoformat()  # the most recent crossing, not the first
    # the rule alone would take the split day (the drop from ~4× to ~1× "crosses" the cost): the search stops there
    assert estimate_buy_date(traded, cost_old, today) == SPLIT_0050
    assert rows[1]["estimated_date"] is None
    assert next(f["message"] for f in rows[1]["flags"] if f["code"] == "no_crossing") == (
        f"2025/6/18 以後的股價都沒有經過均價 {cost_old.normalize():,f}，沒辦法估買入日（那天股票分割，"
        "之前的股價和現在的均價比不起來）。")
    # a cost after the split: found on the prices as traded
    want = estimate_buy_date([c for c in traded if c.t >= SPLIT_0050], cost_new, today)
    assert want is not None and rows[2]["estimated_date"] == want.isoformat()
    # no crossing: null and the sentence, still ticked (a warning)
    assert rows[3]["estimated_date"] is None and rows[3]["include"] is True
    flag = next(f for f in rows[3]["flags"] if f["code"] == "no_crossing")
    assert flag == {"code": "no_crossing", "severity": "warning",
                    "message": "五年內的股價都沒有經過均價 1，沒辦法估買入日。"}
    us = next(f for f in rows[4]["flags"] if f["code"] == "no_crossing")
    assert rows[4]["estimated_date"] is None
    assert us["message"] == "美股的股價只有 2024/7/1 以後的，都沒有經過均價 US$0.5，沒辦法估買入日。"
    assert "estimated_date" not in rows[5] and "estimated_date" not in rows[6]  # short sale, unknown stock
    assert all(f["code"] != "no_crossing" for row in rows[5:] for f in row["flags"])


def test_with_the_backfill_off_the_sentence_says_where_the_prices_begin(client, arch, fake, monkeypatch):
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "")
    get_settings.cache_clear()
    acc = account(client)["id"]
    answer(fake, doc([p("2317", "鴻海", "1000", avg="1")]))
    row = read(client, account_id=acc).json()["rows"][0]
    first = arch.archive_start
    assert row["estimated_date"] is None
    assert next(f["message"] for f in row["flags"] if f["code"] == "no_crossing") == (
        f"{first.year}/{first.month}/{first.day} 以後的股價都沒有經過均價 1，沒辦法估買入日。")


def _commit(client, acc, rows, **body):
    return client.post(COMMIT, json={"account_id": acc, "rows": rows, **body})


def test_commit_stores_how_each_date_came_about(client, arch, engine):
    acc = account(client)["id"]
    days, today = arch.days, today_taipei()
    est = days[-300]
    rows = [
        {"symbol": "2330", "quantity": 1000, "price": 500, "trade_date": est.isoformat(), "date_basis": "estimated",
         "estimated_date": est.isoformat()},
        # the review table said estimated, but the date is not the estimate: the user changed it
        {"symbol": "2317", "quantity": 1000, "price": 100, "trade_date": days[-250].isoformat(),
         "date_basis": "estimated", "estimated_date": days[-260].isoformat()},
        # no crossing, the batch's date (today) left alone
        {"symbol": "0050", "quantity": 1000, "price": 50, "date_basis": "import_day", "estimated_date": None},
        {"symbol": "VOO", "quantity": 5, "price": 400, "trade_date": days[-100].isoformat(), "date_basis": "picked",
         "estimated_date": days[-90].isoformat(), "currency": "USD"},
    ]
    dry = _commit(client, acc, rows, dry_run=True)
    assert dry.status_code == 200 and dry.json()["ok"] is True, dry.text
    r = _commit(client, acc, rows)
    assert r.status_code == 201, r.text
    got = {t["symbol"]: t for t in client.get(f"{API}/transactions", params={"limit": 50}).json()["items"]}
    assert (got["2330.TW"]["date_basis"], got["2330.TW"]["estimated_date"]) == ("estimated", est.isoformat())
    assert (got["2317.TW"]["date_basis"], got["2317.TW"]["estimated_date"]) == ("picked", days[-260].isoformat())
    assert (got["0050.TW"]["date_basis"], got["0050.TW"]["estimated_date"]) == ("import_day", None)
    assert got["0050.TW"]["trade_date"] == today.isoformat()
    assert got["VOO"]["date_basis"] == "picked"
    assert {t["imported_on"] for t in got.values()} == {today.isoformat()}
    assert all(t["fee"] == 0 and t["source"] == "import" for t in got.values())
    assert got["2330.TW"]["price"] == 500  # the broker's cost, only the date is estimated


def test_commit_without_the_new_fields_is_as_before(client, arch):
    acc = account(client)["id"]
    r = _commit(client, acc, [{"symbol": "2330", "quantity": 1000, "price": 500}])
    assert r.status_code == 201, r.text
    t = client.get(f"{API}/transactions").json()["items"][0]
    assert (t["date_basis"], t["estimated_date"], t["imported_on"]) == (None, None, None)
    assert t["trade_date"] == today_taipei().isoformat()


def test_an_import_day_row_moved_with_the_batch_date_is_picked(client, arch):
    acc = account(client)["id"]
    day = arch.days[-30]
    r = _commit(client, acc, [{"symbol": "2330", "quantity": 1000, "price": 1, "date_basis": "import_day"}],
                trade_date=day.isoformat())
    assert r.status_code == 201, r.text
    t = client.get(f"{API}/transactions").json()["items"][0]
    assert (t["date_basis"], t["trade_date"], t["imported_on"]) == ("picked", day.isoformat(),
                                                                    today_taipei().isoformat())


# -- GET /instruments/{symbol}/history?prices=as_traded --------------------------------------------------------------
def test_history_as_traded_multiplies_the_backfill_back_for_a_split(client, arch):
    r = client.get(f"{API}/instruments/0050/history", params={"range": "5Y", "prices": "as_traded"})
    assert r.status_code == 200, r.text
    h = r.json()
    by_day = {c["t"]: c for c in h["candles"]}
    traded = {c.t.isoformat(): c for c in _as_traded_0050(arch)}
    pre = next(d for d in sorted(by_day) if d < SPLIT_0050.isoformat())
    post = next(d for d in sorted(by_day) if d >= SPLIT_0050.isoformat())
    for d in (pre, post, arch.days[-1].isoformat()):
        assert by_day[d]["c"] == pytest.approx(float(traded[d].c), abs=1e-4)
        assert by_day[d]["h"] == pytest.approx(float(traded[d].h), abs=1e-4)
    last_yahoo = arch.days[arch.days.index(arch.archive_start) - 1]
    # the split is the earliest day a buy imported today may have (``pick_from``): the picker says so itself, the
    # notes leave the split out
    assert h["pick_from"] == {"date": SPLIT_0050.isoformat(), "reason": "split"}
    assert h["notes"] == [f"{last_yahoo.strftime('%Y/%m/%d')} 以前的股價來自 Yahoo Finance，不是官方資料"]
    assert any("Yahoo Finance" in s for s in h["sources"]) and any("證券交易所" in s for s in h["sources"])
    assert h["symbol"] == "0050.TW" and h["interval"] == "1d" and h["is_demo"] is False
    # a buy imported before the split: no limit, and the split note is back (the picker shows days before it)
    before = client.get(f"{API}/instruments/0050/history",
                        params={"range": "5Y", "prices": "as_traded", "until": "2025-06-01"}).json()
    assert before["pick_from"] is None
    assert "2025/06/18 股票分割（1 股拆成 4 股），之前是當時的成交價，沒有換算" in before["notes"]
    # without the parameter: the chart as before (Yahoo's split-adjusted rows, its own note)
    plain = client.get(f"{API}/instruments/0050/history", params={"range": "5Y"}).json()
    plain_pre = next(c for c in plain["candles"] if c["t"] == pre)
    assert plain_pre["c"] == pytest.approx(by_day[pre]["c"] / 4, abs=1e-3)
    assert "股票分割前的價格已經換算" in plain["notes"][0]
    assert plain["pick_from"] is None


def test_history_as_traded_5d_says_yahoo_only_when_a_returned_bar_is_from_it(client, arch):
    """5D reads 30 days and returns the last 5: the official archive covers them, so neither the note nor the
    sources name Yahoo (they did, from the bars read before slicing)."""
    h = client.get(f"{API}/instruments/2330/history", params={"range": "5D", "prices": "as_traded"}).json()
    assert len(h["candles"]) == 5 and h["candles"][0]["t"] >= arch.archive_start.isoformat()
    assert not any("Yahoo" in n for n in h["notes"]) and not any("Yahoo" in s for s in h["sources"])
    month = client.get(f"{API}/instruments/2330/history", params={"range": "1M", "prices": "as_traded"}).json()
    assert any("Yahoo" in n for n in month["notes"]) and any("Yahoo" in s for s in month["sources"])


def test_history_as_traded_of_a_us_stock_and_with_the_backfill_off(client, arch, monkeypatch):
    us = client.get(f"{API}/instruments/VOO/history", params={"range": "5Y", "prices": "as_traded"}).json()
    assert us["candles"][0]["t"] == "2024-07-01" and us["notes"] == ["資料從 2024/07/01 開始"]
    assert not any("Yahoo" in s for s in us["sources"])
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "")
    get_settings.cache_clear()
    off = client.get(f"{API}/instruments/2330/history", params={"range": "5Y", "prices": "as_traded"}).json()
    assert off["candles"][0]["t"] == arch.archive_start.isoformat()
    assert off["notes"] == [f"資料從 {arch.archive_start.strftime('%Y/%m/%d')} 開始"]
    assert client.get(f"{API}/instruments/2330/history", params={"range": "5Y", "prices": "x"}).status_code == 422
    assert json.loads(client.get(f"{API}/instruments/^TAIEXTR/history",
                                 params={"range": "1M", "prices": "as_traded"}).text)["symbol"] == "^TAIEXTR"


# -- the share-count limit: splits, capital reductions, stock dividends -----------------------------------------------
def _stock_dividend(engine, symbol: str, ex: date, ratio: str = "0.05") -> None:
    """An archived ex-rights notice (配股 ``ratio`` new shares per share), as TWT48U / tpex_exright_prepost store it."""
    source = "tpex-openapi" if symbol.endswith(".TWO") else "twse-openapi"
    with Session(engine) as db:
        db.add(MarketEvent(key=f"ex-{symbol}-{ex.isoformat()}", symbol=symbol, date=ex, type="ex_dividend",
                           title="除權", detail="", data={"cash": None, "stock_ratio": ratio}, source=source))
        db.commit()


def _shares(client, acc: str, symbol: str) -> D:
    items = client.get(f"{API}/transactions", params={"account_id": acc, "limit": 200}).json()["items"]
    return sum((D(str(t["quantity"])) for t in items
                if t["symbol"] == symbol and t["type"] in ("buy", "stock_dividend")), D(0))


def _ymd(d: date) -> str:
    return f"{d.year}/{d.month}/{d.day}"


def test_an_imported_buy_before_a_stock_dividend_is_refused_not_booked_twice(client, arch, engine):
    """The review's reproduction: a 5% stock dividend (配股) on an in-archive ex-date, then a holdings row dated before
    it. The broker's 1,050 shares already include the stock dividend; booked before it, the ledger added it again
    (1,102 shares). Now the commit refuses the row; on the ex-date itself the buy is written and stays 1,050."""
    days = arch.days
    ex = days[-3]
    _stock_dividend(engine, "6488.TWO", ex)
    acc = account(client)["id"]
    early = days[-7]
    row = {"symbol": "6488", "quantity": 1050, "price": 500, "trade_date": early.isoformat(),
           "date_basis": "estimated", "estimated_date": early.isoformat()}
    dry = _commit(client, acc, [row], dry_run=True)
    assert dry.status_code == 200 and dry.json()["ok"] is False
    codes = {f["code"]: f["message"] for f in dry.json()["rows"][0]["flags"]}
    assert codes["before_share_change"] == f"{_ymd(ex)} 配股，買進日期不能早於這一天。"
    assert codes["bad_estimated_date"].startswith(f"估計的買入日 {_ymd(early)} 不在估得到的期間（{_ymd(ex)} – ")
    r = _commit(client, acc, [row])
    assert r.status_code == 422 and r.json()["error"]["code"] == "batch_rejected", r.text
    assert {e["code"] for e in r.json()["error"]["rows"]} == {"before_share_change", "bad_estimated_date"}
    assert _shares(client, acc, "6488.TWO") == 0  # nothing written
    # picked (the batch's date moved) before the ex-date: refused too
    picked = {**row, "date_basis": "picked", "estimated_date": ex.isoformat()}
    codes = {f["code"] for f in _commit(client, acc, [picked], dry_run=True).json()["rows"][0]["flags"]}
    assert codes == {"before_share_change"}
    # the ex-date itself is allowed: written, and no stock dividend booked on top of the broker's shares
    ok = _commit(client, acc, [{**row, "trade_date": ex.isoformat(), "estimated_date": ex.isoformat()}])
    assert ok.status_code == 201, ok.text
    assert _shares(client, acc, "6488.TWO") == 1050
    # an ordinary buy before the ex-date (another account) is untouched: the stock dividend is booked as before
    other = client.post(f"{API}/accounts", json={"name": "另一個", "broker": "", "currency": "TWD"}).json()["id"]
    trade(client, other, "6488", "buy", early, 1050, 500)
    assert _shares(client, other, "6488.TWO") == 1102


def test_the_estimate_stops_at_a_stock_dividend(client, arch, engine, fake):
    """A cost the price crossed only before the ex-date: no estimate, and the sentence names the 配股."""
    days = arch.days
    ex = days[-40]
    _stock_dividend(engine, "6488.TWO", ex)
    bars = [Candle(d, *arch.bars["6488.TWO"][d], 0) for d in days]
    after = [b for b in bars if b.t >= ex]
    lo, hi = min(b.l for b in after), max(b.h for b in after)
    before = next(b for b in reversed(bars) if b.t < ex and (b.l > hi or b.h < lo))
    cost = before.c
    assert estimate_buy_date(bars, cost, today_taipei()) is not None  # the rule alone finds a day before it
    answer(fake, doc([p("6488", "環球晶", "1000", avg=str(cost))]))
    row = read(client, account_id=account(client)["id"]).json()["rows"][0]
    assert row["estimated_date"] is None
    assert next(f["message"] for f in row["flags"] if f["code"] == "no_crossing") == (
        f"{_ymd(ex)} 以後的股價都沒有經過均價 {cost.normalize():,f}，沒辦法估買入日（那天配股，"
        "之前的股價和現在的均價比不起來）。")
    # the picker gets the same limit
    h = client.get(f"{API}/instruments/6488/history", params={"range": "5Y", "prices": "as_traded"}).json()
    assert h["pick_from"] == {"date": ex.isoformat(), "reason": "stock_dividend"}
    assert client.get(f"{API}/instruments/6488/history",
                      params={"range": "5Y", "prices": "as_traded",
                              "until": (ex - timedelta(days=1)).isoformat()}).json()["pick_from"] is None


def test_patch_refuses_a_date_before_the_share_count_limit(client, arch, engine):
    days = arch.days
    ex = days[-10]
    _stock_dividend(engine, "6488.TWO", ex)
    acc = account(client)["id"]
    t = trade(client, acc, "6488", "buy", ex, 1000, 500, fee=0)
    _imported(engine, t["id"], "estimated", ex, days[-1])
    r = client.patch(f"{API}/transactions/{t['id']}",
                     json={"trade_date": days[-12].isoformat(), "date_basis": "picked"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "before_share_change", r.text
    assert r.json()["error"]["message"] == f"{_ymd(ex)} 配股，買進日期不能早於這一天"
    assert client.get(f"{API}/transactions/{t['id']}").json()["trade_date"] == ex.isoformat()
    ok = client.patch(f"{API}/transactions/{t['id']}", json={"trade_date": days[-8].isoformat()})
    assert ok.status_code == 200 and ok.json()["date_basis"] == "picked"
    # a split counts too (0050, 2025-06-18), and a normal row is untouched
    s = trade(client, acc, "0050", "buy", days[-5], 1000, 50, fee=0)
    _imported(engine, s["id"], "estimated", days[-5], days[-1])
    r = client.patch(f"{API}/transactions/{s['id']}", json={"trade_date": "2025-06-17"})
    assert r.status_code == 422 and r.json()["error"]["message"] == "2025/6/18 股票分割，買進日期不能早於這一天"
    n = trade(client, acc, "2317", "buy", days[-5], 1000, 100)
    assert client.patch(f"{API}/transactions/{n['id']}",
                        json={"trade_date": days[-300].isoformat()}).status_code == 200


def test_an_imported_buy_turned_into_a_sell_or_another_stock_becomes_an_ordinary_row(client, engine):
    acc = account(client)["id"]
    trade(client, acc, "2330", "buy", trading_day(100), 2000, 480)
    a = trade(client, acc, "2330", "buy", trading_day(60), 500, 500, fee=0)
    _imported(engine, a["id"], "estimated", trading_day(60), trading_day(20))
    # price and quantity edits leave the basis alone
    r = client.patch(f"{API}/transactions/{a['id']}", json={"price": 505})
    assert r.status_code == 200 and (r.json()["date_basis"], r.json()["imported_on"]) == (
        "estimated", trading_day(20).isoformat())
    # a sell: an ordinary row — no estimate, no import day (a later date is no longer refused)
    r = client.patch(f"{API}/transactions/{a['id']}", json={"type": "sell"})
    assert r.status_code == 200, r.text
    assert (r.json()["date_basis"], r.json()["estimated_date"], r.json()["imported_on"]) == (None, None, None)
    assert client.patch(f"{API}/transactions/{a['id']}",
                        json={"trade_date": trading_day(5).isoformat()}).status_code == 200
    # another stock: the old stock's estimate does not follow it
    b = trade(client, acc, "2330", "buy", trading_day(50), 1000, 500, fee=0)
    _imported(engine, b["id"], "estimated", trading_day(50), trading_day(20))
    r = client.patch(f"{API}/transactions/{b['id']}", json={"symbol": "2317", "price": 100})
    assert r.status_code == 200, r.text
    assert (r.json()["symbol"], r.json()["date_basis"], r.json()["estimated_date"]) == ("2317.TW", None, None)


def test_commit_refuses_an_estimate_the_estimator_could_not_have_found(client, arch):
    acc = account(client)["id"]
    today = today_taipei()

    def flags(row: dict) -> set[str]:
        r = _commit(client, acc, [row], dry_run=True)
        assert r.status_code == 200, r.text
        return {f["code"] for f in r.json()["rows"][0]["flags"]}

    base = {"symbol": "2330", "quantity": 1000, "price": 500, "trade_date": arch.days[-100].isoformat(),
            "date_basis": "picked"}
    assert flags({**base, "estimated_date": arch.days[-100].isoformat()}) == set()
    assert flags({**base, "estimated_date": "2015-01-05"}) == {"bad_estimated_date"}  # before five years
    assert flags({**base, "estimated_date": (today + timedelta(days=3)).isoformat()}) == {"bad_estimated_date"}
    us = {"symbol": "VOO", "quantity": 5, "price": 400, "currency": "USD", "trade_date": arch.days[-100].isoformat(),
          "date_basis": "picked"}
    assert flags({**us, "estimated_date": "2024-06-28"}) == {"bad_estimated_date"}  # before US prices begin
    assert flags({**us, "estimated_date": "2024-07-01"}) == set()
    r = _commit(client, acc, [{**base, "estimated_date": "2015-01-05"}])
    assert r.status_code == 422 and r.json()["error"]["rows"][0]["code"] == "bad_estimated_date"


def test_an_import_day_row_read_before_midnight_stays_import_day(client, arch):
    """Read at 23:59, signed at 00:01 (Taipei): the row still carries the read's day. It is the import day, not a
    day the user picked; ``imported_on`` is the commit's day."""
    acc = account(client)["id"]
    today = today_taipei()
    yesterday = today - timedelta(days=1)
    r = _commit(client, acc, [{"symbol": "2330", "quantity": 1000, "price": 1, "date_basis": "import_day"}],
                trade_date=yesterday.isoformat())
    assert r.status_code == 201, r.text
    t = client.get(f"{API}/transactions").json()["items"][0]
    assert (t["date_basis"], t["trade_date"], t["imported_on"]) == ("import_day", yesterday.isoformat(),
                                                                    today.isoformat())


def test_a_failed_estimate_keeps_the_paid_reading(client, arch, fake, monkeypatch):
    """A database error while estimating: the reading comes back (200) as from a server that does not estimate —
    no ``estimated_date``, no ``no_crossing`` — instead of a 500 that throws the paid AI call away."""
    from sqlalchemy.exc import OperationalError

    from forliosa.services import buy_date

    def broken(*_a, **_k):
        raise OperationalError("SELECT …", {}, Exception("database is locked"))

    monkeypatch.setattr(buy_date, "estimate_rows", broken)
    answer(fake, doc([p("2330", "台積電", "1000", avg="500"), p("2317", "鴻海", "1000", avg="1")]))
    r = read(client, account_id=account(client)["id"])
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert len(rows) == 2
    assert all("estimated_date" not in row and all(f["code"] != "no_crossing" for f in row["flags"]) for row in rows)


def test_demo_prices_estimate_nothing(client, fake, monkeypatch):
    """Personal mode's demo data is synthetic: no buy date is estimated from it (the rows are as before)."""
    monkeypatch.setenv("IMPORT_STATEMENTS", "all")
    monkeypatch.setenv("AI_MODEL_IMPORT_RETRY", "")
    get_settings.cache_clear()
    acc = account(client)["id"]
    answer(fake, doc([p("2330", "台積電", "1000", avg="500"), p("2317", "鴻海", "1000", avg="1")]))
    rows = read(client, account_id=acc).json()["rows"]
    assert all("estimated_date" not in r and all(f["code"] != "no_crossing" for f in r["flags"]) for r in rows)
    get_settings.cache_clear()


def test_the_estimate_comes_after_an_earlier_round_trip_of_that_stock(client, arch, fake):
    # review 2026-11-21: the account bought and sold 2330 before; an imported buy estimated before that sell would be
    # the lot FIFO sells first (the old gain and today's cost both wrong)
    acc = account(client)["id"]
    days, today = arch.days, today_taipei()
    tw_bars = [Candle(d, *arch.bars["2330.TW"][d], 0) for d in days]
    cost = arch.close("2330.TW", days[-400])
    free = estimate_buy_date(tw_bars, cost, today)
    assert free is not None and free < days[-30]
    i = days.index(free)
    trade(client, acc, "2330", "buy", days[i + 1], 1000, 100)
    sold = days[i + 10]
    trade(client, acc, "2330", "sell", sold, 1000, 100)
    answer(fake, doc([p("2330", "台積電", "1000", avg=str(cost))]))
    r = read(client, account_id=acc)
    assert r.status_code == 200, r.text
    got = r.json()["rows"][0]["estimated_date"]
    want = estimate_buy_date(tw_bars, cost, today, start=sold + timedelta(days=1))
    assert got == (want.isoformat() if want else None)
    assert got is None or got > sold.isoformat()


def test_commit_refuses_an_estimated_date_before_the_accounts_last_record_of_that_stock(client, arch):
    acc = account(client)["id"]
    days = arch.days
    trade(client, acc, "2330", "buy", days[-50], 1000, 100)
    trade(client, acc, "2330", "sell", days[-40], 1000, 100)

    def flags(row: dict) -> set[str]:
        r = _commit(client, acc, [row], dry_run=True)
        assert r.status_code == 200, r.text
        return {f["code"] for f in r.json()["rows"][0]["flags"]}

    early = {"symbol": "2330", "quantity": 1000, "price": 500, "trade_date": days[-60].isoformat(),
             "date_basis": "estimated", "estimated_date": days[-60].isoformat()}
    assert flags(early) == {"before_earlier_records"}
    assert flags({**early, "trade_date": days[-30].isoformat(), "estimated_date": days[-30].isoformat()}) == set()
    assert flags({**early, "date_basis": "picked"}) == set()  # a date the user picked is theirs
    assert flags({**early, "replace": True}) == set()  # 以券商為準: the old records go
