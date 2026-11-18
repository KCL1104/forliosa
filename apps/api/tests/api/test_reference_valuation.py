"""Performance and group returns before the archive (產品負責人 2026-11-18，選 A).

The group board's 本月 and 今年 both read 「11/12 收盤 → 11/17 收盤」: nothing valued a ledger before the archive's
first day. Now the days before it are valued with the history backfill's closes (Yahoo, PRICE_HISTORY_SOURCE=yahoo)
converted back to the prices as traded (known splits and capital reductions multiplied back where Yahoo folded them
in), and every response that used them says so (``reference_until`` and one note). From the archive's first day on
nothing changes: the post-archive numbers are compared with a snapshot of the code before the change
(``fixtures/reference_valuation_golden.json``; ``UPDATE_GOLDEN=1`` writes it), and with the backfill switched off or
dropped every answer is the one before.

The fixture: official closes from 2026-11-12 (the archive's first day) to 11/17, Yahoo rows from 2024-05 to 11/11 —
0050 stored as Yahoo scales it (a quarter before its 2025-06-18 split), 2363 矽統 scaled by its 2024-07-29 capital
reduction (650 per 1,000, NT$3.5 back), 2330 plain; 2317 has no Yahoo rows; the total return index only from 11/12.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import forliosa.marketdata.archive_provider as archive_mod
import forliosa.services.portfolio as portfolio_mod
import forliosa.services.sharing as sharing_mod
from forliosa.config import get_settings
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import BaseProvider
from forliosa.marketdata.catalog import _tw
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import IndexDaily, PriceDaily
from forliosa.timeutil import TAIPEI, tw_trading_days
from tests.api.m5 import API, SHARE_DEFAULT, account, join, login, make_group, trade

TODAY = date(2026, 11, 18)
ARCHIVE = tw_trading_days(date(2026, 11, 12), date(2026, 11, 17))  # 11/12, 11/13, 11/16, 11/17
YAHOO_DAYS = tw_trading_days(date(2024, 5, 2), date(2026, 11, 11))
SPLIT_0050 = date(2025, 6, 18)
HALT_0050 = (date(2025, 6, 11), date(2025, 6, 17))
REDUCTION_2363 = date(2024, 7, 29)
NOTE = "2026/11/11 以前用 Yahoo 參考價計算，不是官方資料"
BENCH_NOTE = "元大台灣50在 2026/11/11 以前只算價格，不含股利"  # no ex-dividend dates before the archive
INDEX_LATE = "發行量加權股價報酬指數從 2026/11/12 收盤起算，之前沒有資料"
YAHOO_LABEL = "Yahoo Finance（歷史日線，非官方資料）"
GOLDEN = Path(__file__).parent / "fixtures" / "reference_valuation_golden.json"

OFFICIAL = {
    "2330.TW": ("1430", "1440", "1420", "1450"),
    "0050.TW": ("62", "62.5", "61.8", "63"),
    "2363.TW": ("85", "85.5", "86", "86.2"),
    "2317.TW": ("240", "242", "241", "245"),
}
INDEX = ("30000", "30100", "29900", "30300")


def y_2330(d: date) -> D:
    return D(800 + YAHOO_DAYS.index(d))


def traded_0050(d: date) -> D:
    """0050 as it traded: 4 × the Yahoo row before the split, the Yahoo row from it on."""
    return y_0050(d) * (4 if d < SPLIT_0050 else 1)


def y_0050(d: date) -> D:
    """0050 as Yahoo stores it: before the split a quarter of the price as traded."""
    last_pre = max(x for x in YAHOO_DAYS if x < HALT_0050[0])
    if d < SPLIT_0050:
        return D("37.50") + D("0.01") * YAHOO_DAYS.index(d)
    return y_0050(last_pre) + D("0.40") + D("0.06") * (YAHOO_DAYS.index(d) - YAHOO_DAYS.index(SPLIT_0050))


def y_2363(d: date) -> D:
    """2363 as Yahoo stores it: 90.20 before the reduction (58.63 as traded = 90.20 × 0.65), then (58.63 − 3.5) /
    0.65 = 84.82 as traded."""
    return D("90.20") if d < REDUCTION_2363 else D("84.82")


def price(symbol: str, d: date, close: D | str, source: str) -> PriceDaily:
    c = D(close)
    return PriceDaily(symbol=symbol, date=d, open=c, high=c, low=c, close=c, volume=1_000_000, source=source)


class Listed(BaseProvider):
    """2363 for the instrument master (offline the catalog lacks it)."""

    name = "listed"

    def instruments(self):
        return [_tw("2363", "矽統", "TWSE", "stock", "半導體業")]


@pytest.fixture()
def archive(engine, market, monkeypatch):
    """The commercial facade over the fixture's archive, today pinned to 2026-11-18 after the close."""
    with Session(engine) as db:
        for sym, closes in OFFICIAL.items():
            db.add_all(price(sym, d, c, "twse-openapi") for d, c in zip(ARCHIVE, closes, strict=True))
        db.add_all(IndexDaily(name="發行量加權股價報酬指數", date=d, market="TWSE", close=D(c), source="twse-openapi")
                   for d, c in zip(ARCHIVE, INDEX, strict=True))
        db.add_all(price("2330.TW", d, y_2330(d), "yahoo-history") for d in YAHOO_DAYS)
        db.add_all(price("0050.TW", d, y_0050(d), "yahoo-history") for d in YAHOO_DAYS
                   if not HALT_0050[0] <= d <= HALT_0050[1])
        db.add_all(price("2363.TW", d, y_2363(d), "yahoo-history") for d in YAHOO_DAYS)
        db.commit()
    md = MarketData([Listed(), ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    for mod in (portfolio_mod, archive_mod):
        monkeypatch.setattr(mod, "today_taipei", lambda: TODAY)
    monkeypatch.setattr(sharing_mod, "now_taipei", lambda: datetime(2026, 11, 18, 18, 0, tzinfo=TAIPEI))
    yield md
    set_market_data(market)


def switch(monkeypatch, on: bool) -> None:
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo" if on else "")
    get_settings.cache_clear()


@pytest.fixture()
def backfill_on(monkeypatch):
    switch(monkeypatch, True)
    yield
    monkeypatch.delenv("PRICE_HISTORY_SOURCE", raising=False)
    get_settings.cache_clear()


@pytest.fixture()
def ledgers(app, client, other_client, archive):
    """A (``client``) bought before the archive in three accounts: 0050 in 2024 (its split recorded, a dividend
    recorded), 2363 in 2024 (its capital reduction recorded), 2330 in 2025. B bought 2330 on the archive's first day.
    C holds 2317 (no Yahoo rows) and 2330 since 2025. A's group, B and C sharing returns."""
    a = {"0050": account(client, "0050")["id"], "2363": account(client, "2363")["id"],
         "2330": account(client, "2330")["id"]}
    bought = date(2024, 6, 3)
    trade(client, a["0050"], "0050.TW", "buy", bought, 1000, str(traded_0050(bought)))
    trade(client, a["0050"], "0050.TW", "split", SPLIT_0050, 4, None)
    r = client.post(f"{API}/transactions", json={"account_id": a["0050"], "symbol": "0050.TW", "type": "cash_dividend",
                                                 "trade_date": "2025-07-17", "amount": 4000})
    assert r.status_code == 201, r.text
    trade(client, a["2363"], "2363.TW", "buy", bought, 1000, "58.63")
    trade(client, a["2363"], "2363.TW", "capital_reduction", REDUCTION_2363, "0.35", "3.5")
    trade(client, a["2330"], "2330.TW", "buy", date(2025, 3, 3), 500, str(y_2330(date(2025, 3, 3))))
    trade(other_client, account(other_client)["id"], "2330.TW", "buy", ARCHIVE[0], 1000, 1430)
    third = login(app, "third@forliosa.local", "老三")
    c = account(third)["id"]
    trade(third, c, "2317.TW", "buy", date(2025, 2, 3), 1000, 230)
    trade(third, c, "2330.TW", "buy", date(2025, 2, 3), 100, str(y_2330(date(2025, 2, 3))))
    g = make_group(client)
    join(client, other_client, g["id"], SHARE_DEFAULT)
    join(client, third, g["id"], SHARE_DEFAULT)
    return {"a": a, "gid": g["id"], "third": third}


def perf(client, range_: str, account_id: str | None = None, benchmark: str | None = None) -> dict:
    params = {"range": range_, **({"account_id": account_id} if account_id else {}),
              **({"benchmark": benchmark} if benchmark else {})}
    r = client.get(f"{API}/portfolio/performance", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def board(client, gid: str, period: str) -> dict:
    r = client.get(f"{API}/groups/{gid}/leaderboard", params={"period": period})
    assert r.status_code == 200, r.text
    return r.json()


def by_name(b: dict) -> dict[str, float | None]:
    return {e["display_name"]: e["return_pct"] for e in b["entries"]}


def point(p: dict, d: date) -> dict:
    return next(x for x in p["series"] if x["t"] == d.isoformat())


def prev_point(p: dict, d: date) -> dict:
    i = next(i for i, x in enumerate(p["series"]) if x["t"] == d.isoformat())
    return p["series"][i - 1]


# -- the ledger's 績效 ----------------------------------------------------------------------------------------------
def test_a_split_before_the_archive_is_level_and_the_whole_history_is_valued(client, ledgers, backfill_on):
    """0050 bought in 2024: ALL starts on the buy (not on the archive's first day), the 2025 split (recorded in the
    ledger) is level — the Yahoo rows before it are multiplied by 4 — and the default benchmark (0050) across it too."""
    p = perf(client, "ALL", ledgers["a"]["0050"])
    assert p["start_date"] == "2024-06-03" and p["end_date"] == ARCHIVE[-1].isoformat()
    assert p["reference_until"] == "2026-11-11" and NOTE in p["notes"]
    assert not any(n.startswith("績效從") for n in p["notes"])
    last_pre = date(2025, 6, 10)
    assert prev_point(p, SPLIT_0050)["t"] == last_pre.isoformat()  # the halt has no closes
    assert point(p, last_pre)["market_value"] == pytest.approx(1000 * float(traded_0050(last_pre)))
    assert point(p, SPLIT_0050)["market_value"] == pytest.approx(4000 * float(y_0050(SPLIT_0050)))
    step = point(p, SPLIT_0050)["twr_index"] / point(p, last_pre)["twr_index"]
    assert step == pytest.approx(float(y_0050(SPLIT_0050) / traded_0050(last_pre) * 4), abs=1e-5)  # +1 %, not +300 %
    assert p["benchmark"]["symbol"] == "0050.TW" and p["benchmark"]["name"] == "元大台灣50"
    first = date(2024, 6, 3)
    # a price return before the archive (no ex-dividend dates there), and it says so
    assert p["benchmark"]["twr"] == pytest.approx(float(D(63) / y_0050(first)) - 1, abs=1e-5)
    assert BENCH_NOTE in p["notes"]
    assert all(x["benchmark_index"] is not None for x in p["series"])
    # the official days are the official closes
    assert [x["market_value"] for x in p["series"][-4:]] == [4000 * float(c) for c in OFFICIAL["0050.TW"]]


def test_a_dividend_recorded_in_the_ledger_counts_before_the_archive(client, ledgers, backfill_on):
    p = perf(client, "ALL", ledgers["a"]["0050"])
    assert {"month": "2025-07", "amount": 4000.0} in p["dividends_by_month"]
    day = date(2025, 7, 17)
    step = point(p, day)["twr_index"] / prev_point(p, day)["twr_index"]
    before = date.fromisoformat(prev_point(p, day)["t"])
    assert step == pytest.approx(float((4000 * y_0050(day) + 4000) / (4000 * y_0050(before))), abs=1e-6)


def test_a_capital_reduction_before_the_archive_is_level(client, ledgers, backfill_on):
    """2363 (650 per 1,000 and NT$3.5 back): Yahoo's rows before the day are scaled by 1/0.65, so they are multiplied
    back; the day's return is the move from 58.63 to 84.82 × 0.65 + 3.5, about 0 — not −35 %."""
    p = perf(client, "ALL", ledgers["a"]["2363"])
    before = prev_point(p, REDUCTION_2363)
    assert before["market_value"] == pytest.approx(58_630.0)
    assert point(p, REDUCTION_2363)["market_value"] == pytest.approx(650 * 84.82)
    assert point(p, REDUCTION_2363)["twr_index"] / before["twr_index"] == pytest.approx(1.0, abs=1e-4)


def test_a_ledger_from_2024_covers_its_ranges_and_says_where_yahoo_was_used(client, ledgers, backfill_on):
    for range_, start in (("1Y", "2025-11-17"), ("YTD", "2026-01-02"), ("MTD", "2026-10-30"), ("5D", "2026-11-10")):
        p = perf(client, range_)
        assert p["start_date"] == start, range_
        assert p["reference_until"] == "2026-11-11" and p["notes"][0] == NOTE, range_
    one = perf(client, "1D")  # after the archive began: no reference close in it
    assert one["start_date"] == ARCHIVE[-2].isoformat() and one["reference_until"] is None and one["notes"] == []


def test_an_index_benchmark_starts_at_its_first_close(client, ledgers, backfill_on):
    """The backfill has no index: across the archive's start the total return index starts at its first close."""
    p = perf(client, "MTD", benchmark="^TAIEXTR")
    assert p["start_date"] == "2026-10-30"
    assert p["benchmark"]["twr"] == pytest.approx(30300 / 30000 - 1, abs=1e-6)
    assert INDEX_LATE in p["notes"]
    assert not any("只算價格" in n for n in p["notes"])  # a total return index: dividends included
    assert [x["benchmark_index"] for x in p["series"] if x["t"] < ARCHIVE[0].isoformat()] == [None] * 9
    assert point(p, ARCHIVE[0])["benchmark_index"] == 1.0


def test_today_s_holdings_stay_official(client, ledgers, backfill_on):
    h = {x["symbol"]: x["price"] for x in client.get(f"{API}/portfolio/holdings").json()}
    assert h == {"0050.TW": 63.0, "2363.TW": 86.2, "2330.TW": 1450.0}


# -- the group board ------------------------------------------------------------------------------------------------
def test_month_and_year_boards_reach_back_and_say_so(client, ledgers, backfill_on):
    gid = ledgers["gid"]
    month, year, day = (board(client, gid, p) for p in ("month", "year", "day"))
    assert (month["start_date"], year["start_date"], day["start_date"]) == ("2026-10-30", "2025-12-31", "2026-11-16")
    for b in (month, year):
        assert b["reference_until"] == "2026-11-11"
        # the Yahoo line first, then that 0050 is a price return there, then the index's later start
        assert b["notes"] == [NOTE, BENCH_NOTE, INDEX_LATE], b["notes"]
        assert YAHOO_LABEL in b["sources"]
    assert day["reference_until"] is None and NOTE not in day["notes"] and BENCH_NOTE not in day["notes"]
    # the members' month and year are the ledger's 本月 and 今年 (the share card's numbers)
    assert by_name(month)["示範使用者"] == pytest.approx(perf(client, "MTD")["twr"], abs=1e-4)
    assert by_name(year)["示範使用者"] == pytest.approx(perf(client, "YTD")["twr"], abs=1e-4)
    # benchmarks: 0050 from Yahoo's 10/30 close, the index from its first close with a note
    bench = {x["symbol"]: x["return_pct"] for x in month["benchmarks"]}
    assert bench["0050.TW"] == pytest.approx(float(D(63) / y_0050(date(2026, 10, 30))) - 1, abs=1e-4)
    assert bench["^TAIEXTR"] == pytest.approx(0.01, abs=1e-4)
    shared = ledgers["third"].get(f"{API}/groups/{gid}/members/{client.get(f'{API}/me').json()['id']}/shared").json()
    assert shared["returns"]["month"] == by_name(month)["示範使用者"]
    assert shared["returns"]["reference_until"] == "2026-11-11"  # the member page says so too


def test_a_member_the_backfill_cannot_price_keeps_the_number_from_the_archive_start(client, ledgers, monkeypatch):
    """老三 holds 2317 (no Yahoo rows) since 2025: his month and year are computed as before the change — from the
    archive's first day, the rule of his own 績效 (「績效從 2026/11/12 收盤開始算」) — not left blank, so the board,
    his share card and the ledger say the same. Only his own row says where it begins (2026-11-18 review)."""
    third, gid = ledgers["third"], ledgers["gid"]
    switch(monkeypatch, False)
    before = {p: by_name(board(client, gid, p))["老三"] for p in ("day", "month", "year")}
    switch(monkeypatch, True)
    month, year, day = (board(client, gid, p) for p in ("month", "year", "day"))
    assert {p: by_name(b)["老三"] for p, b in (("day", day), ("month", month), ("year", year))} == before
    assert before["month"] is not None and before["month"] == before["year"]
    for range_, b in (("MTD", month), ("YTD", year)):
        mine = perf(third, range_)
        assert mine["start_date"] == "2026-11-12" and mine["reference_until"] is None
        assert by_name(b)["老三"] == pytest.approx(mine["twr"], abs=1e-4)  # = the share card's 本月
    # he is ranked again (the old board ranked him)
    assert next(e for e in month["entries"] if e["display_name"] == "老三")["rank"] is not None
    # where his period begins: on his own row only
    own = {e["display_name"]: e["own_start_date"] for e in board(third, gid, "month")["entries"]}
    assert own == {"示範使用者": None, "別人": None, "老三": "2026-11-12"}
    assert all(e["own_start_date"] is None for e in month["entries"])  # A's view of the same board
    assert all(e["own_start_date"] is None for e in board(third, gid, "day")["entries"])


def test_a_digest_week_before_the_archive_is_valued_and_says_so(engine, ledgers, archive, monkeypatch, backfill_on):
    def week():
        with Session(engine) as db:
            members = sharing_mod.members_of(db, ledgers["gid"])
            return sharing_mod.digest_week_facts(db, archive, members, date(2026, 11, 9), date(2026, 11, 13))

    facts, sources = week()
    assert facts["base_date"] == "2026-11-06" and facts["notes"][:2] == [NOTE, BENCH_NOTE] and YAHOO_LABEL in sources
    returns = {r["user_id"]: r["week_return_pct"] for r in facts["returns"]}
    assert len(returns) == 3 and all(v is not None for v in returns.values())
    # 老三's 2317 has no close before 11/12: his week is the one before the change (from 11/12), not blank
    switch(monkeypatch, False)
    old, _ = week()
    assert old["base_date"] == "2026-11-12"
    third = ledgers["third"].get(f"{API}/me").json()["id"]
    assert returns[third] == {r["user_id"]: r["week_return_pct"] for r in old["returns"]}[third]


def test_a_stock_benchmark_before_the_archive_is_a_price_return_and_says_so(client, ledgers, engine, archive,
                                                                            monkeypatch, backfill_on):
    """We have no ex-dividend dates before the archive (the archive keeps the notices from its first day on; the
    backfill stores closes only), so 0050 is a price return on those days — 0050 pays in January and July, both before
    11/12 this year. Said wherever it is compared (2026-11-18 review); the AI card then drops 「基準含股利」."""
    from forliosa.ai import charts as charts_mod
    from tests.ai.test_tools import user_by_email

    year = board(client, ledgers["gid"], "year")
    bench = {x["symbol"]: x["return_pct"] for x in year["benchmarks"]}
    assert bench["0050.TW"] == pytest.approx(float(D(63) / y_0050(date(2025, 12, 31))) - 1, abs=1e-4)
    assert BENCH_NOTE in year["notes"]
    ytd = perf(client, "YTD")
    # (YTD's first point is 1/2, its return from the 12/31 close counts: the same price ratio as the board's 今年)
    assert ytd["benchmark"]["twr"] == pytest.approx(float(D(63) / y_0050(date(2025, 12, 31))) - 1, abs=1e-5)
    assert BENCH_NOTE in ytd["notes"]
    assert not any("只算價格" in n for n in perf(client, "YTD", benchmark="^TAIEXTR")["notes"])  # index: no
    assert not any("只算價格" in n for n in perf(client, "1D")["notes"])  # after the archive began: no
    with Session(engine) as db:
        me = user_by_email(db, "demo@forliosa.local")
        card = charts_mod.performance_chart(db, archive, me, "1Y", None)
        assert BENCH_NOTE in card["notes"] and "報酬率是時間加權報酬率" in card["notes"]
        assert not any("基準含股利" in n for n in card["notes"])
        assert YAHOO_LABEL in card["sources"]
        switch(monkeypatch, False)
        off = charts_mod.performance_chart(db, archive, me, "1Y", None)
        assert "報酬率是時間加權報酬率；基準含股利" in off["notes"] and not any("Yahoo" in n for n in off["notes"])
        assert YAHOO_LABEL not in off["sources"]


def test_under_personal_the_board_does_not_claim_the_backfill(client, ledgers, engine, backfill_on):
    """Not commercial: other sources cover the years before the archive and nothing reads the backfill, so the board
    says nothing about Yahoo (as before the change); the ledger already said only what it used."""
    md = MarketData([Listed(), ArchiveProvider("personal", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="personal")
    set_market_data(md)
    window = sharing_mod.period_window(md, ARCHIVE[-1])
    assert window.reference_until is None and window.archive_since is None and not window.clipped
    for period in ("month", "year"):
        b = board(client, ledgers["gid"], period)
        assert b["reference_until"] is None and not any("Yahoo" in n for n in b["notes"]), b["notes"]
        assert YAHOO_LABEL not in b["sources"]


# -- switched off, dropped: as before ----------------------------------------------------------------------------------
@pytest.mark.parametrize("how", ["off", "dropped"])
def test_without_the_backfill_everything_is_as_before(client, ledgers, engine, monkeypatch, how):
    switch(monkeypatch, how == "dropped")
    if how == "dropped":
        from forliosa.history_backfill import drop

        with Session(engine) as db:
            assert drop(db) > 0
    month = board(client, ledgers["gid"], "month")
    assert month["start_date"] == "2026-11-12" and month["reference_until"] is None
    assert month["notes"][0] == "資料從 2026/11/12 開始，這段期間從 2026/11/12 收盤起算"
    assert not any("Yahoo" in n for n in month["notes"]) and YAHOO_LABEL not in month["sources"]
    p = perf(client, "ALL", ledgers["a"]["0050"])
    assert p["start_date"] == "2026-11-12" and p["reference_until"] is None
    assert p["notes"] == ["績效從 2026/11/12 收盤開始算，之前沒有資料"]


# -- after the archive began: byte for byte as before --------------------------------------------------------------
def snapshot(client, other_client, ledgers) -> dict:
    """What the change must not touch: B's performance (bought on the archive's first day) in every range, A's 1D,
    and the day board (every member, both benchmarks). ``reference_until`` is new (the old code has none)."""
    def strip(x: dict) -> dict:
        return {k: v for k, v in x.items() if k not in ("reference_until", "comment_count", "reactions")}

    out = {f"B {r}": strip(perf(other_client, r)) for r in ("ALL", "1M", "3M", "YTD", "MTD", "5D", "1D")}
    out["A 1D"] = strip(perf(client, "1D"))
    out["A 1D 0050 account"] = strip(perf(client, "1D", ledgers["a"]["0050"]))
    day = board(client, ledgers["gid"], "day")
    out["day board"] = {"start_date": day["start_date"], "date": day["date"], "returns": by_name(day),
                        "totals": {e["display_name"]: e["total_return_pct"] for e in day["entries"]},
                        "benchmarks": day["benchmarks"]}
    return out


@pytest.mark.parametrize("on", [True, False])
def test_after_the_archive_began_nothing_changes(client, other_client, ledgers, monkeypatch, on):
    switch(monkeypatch, on)
    got = snapshot(client, other_client, ledgers)
    if os.environ.get("UPDATE_GOLDEN") and not on:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    assert json.loads(json.dumps(got)) == json.loads(GOLDEN.read_text())
    assert perf(other_client, "ALL")["reference_until"] is None
    day = board(client, ledgers["gid"], "day")
    assert day["reference_until"] is None and YAHOO_LABEL not in day["sources"]
    # the day board's note: before, every period said where the clipped month and year began; now they are not
    # clipped and the day board has nothing to say
    clip = "資料從 2026/11/12 開始，這段期間從 2026/11/16 收盤起算"
    assert day["notes"] == ([] if on else [clip])


def test_the_reference_is_one_query_for_every_holding(client, ledgers, engine, backfill_on):
    """The holdings' and the benchmark's backfill rows are read in one statement (the speed work's batching), and the
    split and the reduction are checked on the rows already read."""
    from sqlalchemy import event

    seen: list[str] = []

    def count(_conn, _cursor, statement, parameters, *_a):
        if "yahoo-history" in str(parameters):
            seen.append(statement)

    perf(client, "ALL")  # warm (the archive's start is remembered)
    event.listen(engine, "before_cursor_execute", count)
    try:
        perf(client, "ALL")
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(seen) == 1 and " IN " in seen[0].upper(), seen
