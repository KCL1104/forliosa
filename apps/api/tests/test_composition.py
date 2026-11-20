"""資產組成原型 (``docs/proposals/asset-composition.md`` 附錄 B): ``GET /portfolio/performance``'s ``composition``.

* :func:`services.composition.monthly_breakdown` gives the front end's answers (``lib/asset-composition.ts``
  ``monthlyBreakdown`` wrote ``tests/fixtures/monthly_breakdown_parity.json``; regenerate it as its note says);
* the endpoint on a commercial archive (official closes for the last sessions, the history backfill before them):
  the estimated span, the months it leaves out, the provisional import-day months, the dividends by day, XIRR null
  over the estimated days, the months' base for each kind of range — and the months equal ``monthlyBreakdown`` run on
  the series as served;
* nothing is cached: changing a buy's date changes the next performance and the group board.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import Transaction
from forliosa.services import composition as comp
from forliosa.timeutil import last_tw_trading_day
from tests.composition_fixture import _txn, add_accounts, build_archive

API = "/api/v1"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "monthly_breakdown_parity.json"


def _point(x: dict | None) -> comp.MonthPoint | None:
    if x is None:
        return None
    return comp.MonthPoint(date.fromisoformat(x["t"]) if x["t"] else None, x["market_value"], x["net_invested"],
                           x["twr_index"], x["benchmark_index"])


def _months_out(months: list[dict]) -> list[dict]:
    return [{**m, "from": m["from"].isoformat(), "to": m["to"].isoformat()} for m in months]


# -- the same answers as the front end ------------------------------------------------------------------------------
def test_monthly_breakdown_gives_the_front_ends_answers():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(doc["cases"]) >= 8
    assert {"two_imports_middle", "bench_null_base"} <= {c["name"] for c in doc["cases"]}
    for case in doc["cases"]:
        spans = [comp.Span(date.fromisoformat(s["from"]), date.fromisoformat(s["until"])) for s in case["estimated"]]
        got = comp.monthly_breakdown(
            [_point(x) for x in case["points"]], _point(case["base"]), spans,
            [date.fromisoformat(d) for d in case["importDays"]])
        exp = case["expected"]
        assert _months_out(got.months) == exp["months"], case["name"]
        assert (got.skipped, got.skipped_import) == (exp["skipped"], exp["skippedImport"]), case["name"]


def test_js_round_rounds_halves_up_like_math_round():
    assert comp.js_round(0.125, 2) == 0.13 and round(0.125, 2) == 0.12  # Python's banker's rounding differs
    assert comp.js_round(-2.5, 0) == -2.0 and comp.js_round(2.5, 0) == 3.0


def _t(kind: str, d: date, basis: str | None = None, imported: date | None = None) -> Transaction:
    return Transaction(id="x", type=kind, trade_date=d, date_basis=basis, imported_on=imported)


def test_estimated_span_runs_from_the_earliest_estimate_to_the_trading_day_before_the_import():
    sat = date(2025, 11, 29)
    txns = [_t("buy", date(2025, 7, 2), "estimated", sat), _t("buy", date(2024, 7, 29), "estimated", sat),
            _t("buy", date(2024, 3, 11), "picked", sat), _t("buy", sat, "import_day", sat), _t("buy", date(2023, 1, 3))]
    spans = comp.estimated_spans(txns)
    assert spans == [comp.Span(date(2024, 7, 29), date(2025, 11, 28))]
    assert spans[0].out() == {"from": date(2024, 7, 29), "until": date(2025, 11, 28)}
    assert comp.import_days(txns) == [sat]
    # every estimate picked since: no span; an estimate on the import day itself: nothing before it either
    assert comp.estimated_spans([t for t in txns if t.date_basis != "estimated"]) == []
    assert comp.estimated_spans([_t("buy", date(2025, 12, 1), "estimated", date(2025, 12, 1))]) == []


def test_each_import_has_its_own_span_and_touching_ones_are_merged():
    first, second = date(2025, 11, 29), date(2026, 11, 19)  # a Saturday, a Thursday
    txns = [_t("buy", date(2024, 10, 28), "estimated", first), _t("buy", date(2025, 7, 2), "estimated", first),
            _t("buy", date(2026, 9, 1), "estimated", second), _t("buy", date(2026, 10, 5), "estimated", second),
            _t("buy", date(2025, 3, 3), "picked", second)]
    # the second import's estimates are recent: the year between the two imports is not estimated
    assert comp.estimated_spans(txns) == [comp.Span(date(2024, 10, 28), date(2025, 11, 28)),
                                          comp.Span(date(2026, 9, 1), date(2026, 11, 18))]
    # an estimate of the second import before the first import's end: one span
    overlap = [*txns, _t("buy", date(2025, 6, 2), "estimated", second)]
    assert comp.estimated_spans(overlap) == [comp.Span(date(2024, 10, 28), date(2026, 11, 18))]
    # touching: the second span starts on the next trading day after the first one ends (a weekend between)
    touch = [_t("buy", date(2025, 11, 3), "estimated", date(2025, 11, 22)),  # until Fri 2025-11-21
             _t("buy", date(2025, 11, 24), "estimated", date(2025, 12, 6))]  # from Mon 2025-11-24
    assert comp.estimated_spans(touch) == [comp.Span(date(2025, 11, 3), date(2025, 12, 5))]
    assert comp.in_spans(date(2026, 1, 5), comp.estimated_spans(txns)) is False
    assert comp.in_spans(date(2026, 9, 1), comp.estimated_spans(txns)) is True


# -- the endpoint -----------------------------------------------------------------------------------------------------
@pytest.fixture()
def arch(engine, market, monkeypatch):
    """Two years of synthetic bars: official closes for the last six sessions, the history backfill before them."""
    from forliosa.config import get_settings

    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    monkeypatch.setenv("US_PRICE_SOURCE", "databento")
    get_settings.cache_clear()
    archive = build_archive(engine, years=2, symbols=["2330.TW", "2317.TW", "2454.TW", "0050.TW", "VOO"])
    set_market_data(MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True),
                                DemoProvider()], policy="commercial"))
    yield archive
    set_market_data(market)
    get_settings.cache_clear()


def _saturday_after(d: date) -> date:
    return d + timedelta(days=(5 - d.weekday()) % 7 or 7)


@pytest.fixture()
def ledger(engine, client, arch):
    """An import on a Saturday ~3 months ago: 2330 estimated, 2317 picked by the user, 2454 found no crossing
    (import day); and normal records: a 2330 buy and sell, a 2317 cash dividend."""
    days = arch.days
    sat = _saturday_after(days[-70])
    me = client.get(f"{API}/me").json()["id"]
    with Session(engine) as db:
        tw, _ = add_accounts(db, me)
        db.commit()
    close = arch.close
    # the normal records come after the import's month (whose months the import day leaves out)
    monday = next(d for d in days if d > sat)
    later = [d for d in days if d.isoformat()[:7] > monday.isoformat()[:7]]
    buy2, div, sell = later[1], later[12], later[24]
    rows = [
        _txn(me, tw, "2330.TW", "buy", days[100], D(1000), close("2330.TW", days[100]), "TWD", 1, source="import",
             date_basis="estimated", estimated_date=days[100], imported_on=sat),
        _txn(me, tw, "2317.TW", "buy", days[50], D(2000), close("2317.TW", days[50]), "TWD", 2, source="import",
             date_basis="picked", estimated_date=days[300], imported_on=sat),
        _txn(me, tw, "2454.TW", "buy", sat, D(100), D(1), "TWD", 3, source="import", date_basis="import_day",
             imported_on=sat),
        _txn(me, tw, "2330.TW", "buy", buy2, D(1000), close("2330.TW", buy2), "TWD", 4, fee=D(500)),
        _txn(me, tw, "2330.TW", "sell", sell, D(500), close("2330.TW", sell), "TWD", 5, fee=D(300), tax=D(900)),
        _txn(me, tw, "2317.TW", "cash_dividend", div, D(2000), D("2.5"), "TWD", 6, amount=D(5000)),
    ]
    rows[5]["health_insurance"] = D(100)
    with Session(engine) as db:
        from sqlalchemy import insert

        db.execute(insert(Transaction), rows)
        db.commit()
    return {"days": days, "sat": sat, "rows": rows, "me": me, "account": tw, "div": div, "sell": sell,
            "close": close}


def _perf(client, range_: str) -> dict:
    r = client.get(f"{API}/portfolio/performance", params={"range": range_})
    assert r.status_code == 200, r.text
    return r.json()


def _series_points(perf: dict) -> list[comp.MonthPoint]:
    return [comp.MonthPoint(date.fromisoformat(p["t"]), p["market_value"], p["net_invested"], p["twr_index"],
                            p["benchmark_index"]) for p in perf["series"]]


def test_all_lists_the_real_months_and_leaves_out_the_estimated_and_the_import_day_ones(client, ledger):
    days, sat = ledger["days"], ledger["sat"]
    perf = _perf(client, "ALL")
    c = perf["composition"]
    until = last_tw_trading_day(sat - timedelta(days=1))
    assert c["estimated"] == [{"from": days[100].isoformat(), "until": until.isoformat()}]
    assert perf["xirr"] is None  # the window touches the estimated days: not annualized
    assert perf["fund_rank"] is None
    # the months: none inside the span; the import day's close (the Monday after) puts its month out
    listed = {m["month"] for m in c["months"]}
    monday = next(d for d in days if d > sat)
    assert monday.isoformat()[:7] not in listed and c["months_import_day"] == 1
    for m in c["months"]:
        assert not (days[100].isoformat() <= m["from"] <= until.isoformat())
        assert not (days[100].isoformat() <= m["to"] <= until.isoformat())
    span_months = {d.isoformat()[:7] for d in days if days[100] <= d <= until}
    real_months = {d.isoformat()[:7] for d in days if d >= days[50] and not days[100] <= d <= until}
    assert c["months_estimated"] == len(span_months - real_months) > 3
    assert [m["month"] for m in c["months"]] == sorted(listed, reverse=True)  # newest first
    # the same months as monthlyBreakdown on the series as served (the mock and a front end recomputing agree)
    ref = comp.monthly_breakdown(_series_points(perf), None, [comp.Span(days[100], until)], [sat])
    assert _months_out(ref.months) == c["months"]
    assert (ref.skipped, ref.skipped_import) == (c["months_estimated"], c["months_import_day"])
    # from the first record: the first month is not compared with the benchmark
    assert c["months"][-1]["month"] == days[50].isoformat()[:7] and c["months"][-1]["benchmark_twr"] is None
    assert c["months"][-1]["whole"] is False
    assert any(m["benchmark_twr"] is not None for m in c["months"][:-1])


def test_dividends_by_day_are_net_and_match_dividends_by_month(client, ledger):
    perf = _perf(client, "ALL")
    assert perf["composition"]["dividends"] == [{"t": ledger["div"].isoformat(), "amount": 4900.0}]
    by_month: dict[str, float] = {}
    for d in perf["composition"]["dividends"]:
        by_month[d["t"][:7]] = by_month.get(d["t"][:7], 0) + d["amount"]
    assert by_month == {m["month"]: m["amount"] for m in perf["dividends_by_month"]}


def test_months_flows_and_pnl_follow_the_series(client, ledger):
    """本金增減 is net_invested's change (buys up, sells down, dividends not), 損益 the change of market value minus
    net_invested; consecutive months chain from the previous month's last close."""
    perf = _perf(client, "ALL")
    pts = {p["t"]: p for p in perf["series"]}
    ts = [p["t"] for p in perf["series"]]
    for m in perf["composition"]["months"][:-1]:  # (the oldest one counts from zero)
        prev = pts[ts[ts.index(m["from"]) - 1]]
        last = pts[m["to"]]
        assert m["flows"] == pytest.approx(last["net_invested"] - prev["net_invested"], abs=0.006)
        profit = (last["market_value"] - last["net_invested"]) - (prev["market_value"] - prev["net_invested"])
        assert m["pnl"] == pytest.approx(profit, abs=0.006)
    sell_month = ledger["sell"].isoformat()[:7]
    sold = next(m for m in perf["composition"]["months"] if m["month"] == sell_month)
    assert sold["flows"] < 0  # a sell lowers 本金


def test_a_range_counts_its_first_month_from_the_close_before_it(client, ledger):
    perf = _perf(client, "1M")
    c = perf["composition"]
    first = c["months"][-1]
    assert first["from"] == perf["series"][0]["t"]
    # its base is the close before the window (index 1.0): the window's own first return is in it
    to = next(p for p in perf["series"] if p["t"] == first["to"])
    assert first["twr"] == pytest.approx(to["twr_index"] - 1, abs=2e-6)
    assert first["benchmark_twr"] is not None  # a base close exists: compared with the benchmark
    assert perf["xirr"] is not None  # after the estimated days: annualized as before


@pytest.mark.parametrize("range_", ["1Y", "6M", "3M"])
def test_a_long_range_leaves_out_its_estimated_months_too(client, ledger, range_):
    days, sat = ledger["days"], ledger["sat"]
    until = last_tw_trading_day(sat - timedelta(days=1))
    perf = _perf(client, range_)
    c = perf["composition"]
    whole = _perf(client, "ALL")["series"]
    prev = whole[[p["t"] for p in whole].index(perf["series"][0]["t"]) - 1]
    base = comp.MonthPoint(date.fromisoformat(prev["t"]), prev["market_value"], prev["net_invested"], 1.0, 1.0)
    ref = comp.monthly_breakdown(_series_points(perf), base, [comp.Span(days[100], until)], [sat])
    assert _months_out(ref.months) == c["months"]
    assert (ref.skipped, ref.skipped_import) == (c["months_estimated"], c["months_import_day"])
    assert perf["xirr"] is None if perf["start_date"] <= until.isoformat() else perf["xirr"] is not None


@pytest.mark.parametrize("range_", ["MTD", "5D", "1D"])
def test_a_based_range_counts_from_its_base_close(client, ledger, range_):
    perf = _perf(client, range_)
    c = perf["composition"]
    series = perf["series"]
    assert c["months"] and c["months"][-1]["from"] == series[1]["t"]
    total_flows = sum(m["flows"] for m in c["months"])
    assert total_flows == pytest.approx(series[-1]["net_invested"] - series[0]["net_invested"], abs=0.02)
    assert all(d["t"] > series[0]["t"] for d in c["dividends"])  # the base close's own day is before the window


def test_without_estimated_buys_nothing_is_left_out_and_xirr_stays(client, engine, arch):
    days = arch.days
    me = client.get(f"{API}/me").json()["id"]
    with Session(engine) as db:
        tw, _ = add_accounts(db, me)
        db.commit()
    from sqlalchemy import insert

    with Session(engine) as db:
        db.execute(insert(Transaction), [_txn(me, tw, "2330.TW", "buy", days[10], D(1000),
                                              arch.close("2330.TW", days[10]), "TWD", 1)])
        db.commit()
    perf = _perf(client, "ALL")
    c = perf["composition"]
    assert c["estimated"] == [] and c["months_estimated"] == 0 and c["months_import_day"] == 0
    assert perf["xirr"] is not None
    months = {d.isoformat()[:7] for d in days if d >= days[10]}
    assert {m["month"] for m in c["months"]} == months


def test_an_empty_ledger_has_an_empty_composition(client, arch):
    perf = _perf(client, "ALL")
    assert perf["series"] == [] and perf["composition"] == {
        "dividends": [], "estimated": [], "months": [], "months_estimated": 0, "months_import_day": 0}


def test_a_second_import_does_not_turn_the_months_between_into_estimates(client, engine, ledger):
    """The months between two imports, touched by no estimate, are listed: each import has its own span (before,
    one span ran from the earliest estimate to the latest import and left them all out)."""
    from sqlalchemy import insert

    days, sat = ledger["days"], ledger["sat"]
    second = days[-2]  # a second import, of a buy estimated a few days before it
    with Session(engine) as db:
        db.execute(insert(Transaction), [_txn(ledger["me"], ledger["account"], "2454.TW", "buy", days[-6], D(10),
                                              ledger["close"]("2454.TW", days[-6]), "TWD", 9, source="import",
                                              date_basis="estimated", estimated_date=days[-6], imported_on=second)])
        db.commit()
    perf = _perf(client, "ALL")
    c = perf["composition"]
    first_until = last_tw_trading_day(sat - timedelta(days=1))
    second_until = last_tw_trading_day(second - timedelta(days=1))
    assert c["estimated"] == [{"from": days[100].isoformat(), "until": first_until.isoformat()},
                              {"from": days[-6].isoformat(), "until": second_until.isoformat()}]
    listed = {m["month"] for m in c["months"]}
    import_month = next(d for d in days if d > sat).isoformat()[:7]  # left out for the import-day buy (provisional)
    between = {d.isoformat()[:7] for d in days if first_until < d < days[-6]} - {import_month, days[-6].isoformat()[:7]}
    assert between and between <= listed  # every month between the two imports is listed
    for m in c["months"]:
        assert not (days[-6].isoformat() <= m["from"] <= second_until.isoformat())
    spans = [comp.Span(days[100], first_until), comp.Span(days[-6], second_until)]
    ref = comp.monthly_breakdown(_series_points(perf), None, spans, [sat])
    assert _months_out(ref.months) == c["months"]
    assert perf["xirr"] is None
    # a range after the first span but touching the second: still not annualized
    assert _perf(client, "1M")["xirr"] is None


# -- nothing cached: a changed buy date shows at once ---------------------------------------------------------------
def test_picking_a_buy_date_changes_the_next_performance_and_the_group_board(client, other_client, ledger, engine):
    from tests.api.m5 import SHARE_DEFAULT, join, make_group

    days = ledger["days"]
    gid = make_group(client)["id"]
    join(client, other_client, gid, SHARE_DEFAULT)
    board = client.get(f"{API}/groups/{gid}/leaderboard", params={"period": "year"}).json()
    mine = next(e for e in board["entries"] if e["is_me"])
    before = _perf(client, "ALL")
    estimated = next(t for t in client.get(f"{API}/transactions", params={"limit": 200}).json()["items"]
                     if t["date_basis"] == "estimated")
    # the user picks a day this year, before the import (a later day is refused: test_buy_date_basis)
    day = next(d for d in days if d.year == days[-1].year and d.month >= 3)
    assert day < ledger["sat"]
    r = client.patch(f"{API}/transactions/{estimated['id']}", json={"trade_date": day.isoformat(),
                                                                   "date_basis": "picked"})
    assert r.status_code == 200, r.text
    assert r.json()["date_basis"] == "picked" and r.json()["estimated_date"] == days[100].isoformat()
    after = _perf(client, "ALL")
    assert after["composition"]["estimated"] == []  # no buy is still estimated
    assert after["series"] != before["series"]
    v_before = {p["t"]: p["market_value"] for p in before["series"]}
    v_after = {p["t"]: p["market_value"] for p in after["series"]}
    assert v_after[days[200].isoformat()] < v_before[days[200].isoformat()]  # 2330 no longer held then
    board2 = client.get(f"{API}/groups/{gid}/leaderboard", params={"period": "year"}).json()
    mine2 = next(e for e in board2["entries"] if e["is_me"])
    assert mine2["return_pct"] != mine["return_pct"]
