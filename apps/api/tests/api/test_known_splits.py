"""The verified Taiwan splits in ``catalog.KNOWN_SPLITS`` (product owner 2026-11-18), in 0050's convention: the date is
the first trading day at the new price, the ratio new shares per old share (a reverse split 1/n).

What they change, and what they must not: the Yahoo Finance history backfill's rows are split-adjusted, so a
*reference* close (the buy form's 「那天收盤」, the statement import's check) multiplies a known split back — where the
stored rows really fold it in (``reference_close._folded_in``); a chart draws the backfill as stored and describes a
split only where the line jumps; the ledger (market value, P&L, performance) never reads either, so a user who bought
after a split sees exactly the official closes."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

import forliosa.ai.charts as charts_mod
import forliosa.services.instruments as instr_mod
from forliosa.ai.tools import ToolContext, execute
from forliosa.config import get_settings
from forliosa.datapolicy import HISTORY_SOURCE
from forliosa.marketdata import service as md_service
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import BaseProvider, CorporateEvent
from forliosa.marketdata.catalog import KNOWN_REDUCTIONS, KNOWN_SPLITS, _tw
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import PriceDaily
from forliosa.services.instruments import reduction_how, split_how
from forliosa.timeutil import tw_trading_days

API = "/api/v1"
TODAY = date(2026, 11, 18)
ARCHIVE = tw_trading_days(date(2026, 11, 12), date(2026, 11, 17))  # 11/12, 11/13, 11/16, 11/17

# (first day at the new price, new shares per old share), as checked against two independent sources each
VERIFIED = {
    "00632R.TW": (date(2024, 12, 11), D(1) / 7),
    "00676R.TW": (date(2025, 2, 19), D(1) / 6),
    "00663L.TW": (date(2025, 6, 11), D(7)),
    "0050.TW": (date(2025, 6, 18), D(4)),
    "00673R.TW": (date(2025, 10, 22), D(1) / 4),
    "00706L.TW": (date(2025, 10, 22), D(1) / 4),
    "0052.TW": (date(2025, 11, 26), D(7)),
    "00715L.TW": (date(2025, 12, 10), D(1) / 2),
    "00662.TW": (date(2026, 11, 17), D(5)),
    "00685L.TW": (date(2026, 7, 7), D(24)),
    "2363.TW": (date(2024, 7, 29), D("0.65")),
    "2371.TW": (date(2025, 6, 23), D("0.95")),
    "2323.TW": (date(2026, 10, 12), D("0.9")),
    "9945.TW": (date(2023, 9, 25), D("0.9")),
    "4174.TWO": (date(2026, 2, 3), D("0.5")),
    # the second round (2026-11-18): an ETF split and reverse split, par value changes (面額變更), cash reductions
    "00631L.TW": (date(2026, 3, 31), D(22)),
    "00674R.TW": (date(2026, 4, 22), D(1) / 5),
    "6531.TW": (date(2021, 10, 18), D(2)),
    "6415.TW": (date(2022, 7, 13), D(4)),
    "6613.TWO": (date(2022, 8, 29), D(2)),
    "5536.TWO": (date(2022, 9, 19), D(2)),
    "8932.TWO": (date(2024, 9, 9), D(2)),
    "5314.TWO": (date(2025, 3, 31), D(20)),
    "4763.TW": (date(2025, 6, 30), D(10)),
    "2327.TW": (date(2025, 8, 25), D(4)),
    "8937.TWO": (date(2026, 4, 13), D(4)),
    "3086.TWO": (date(2026, 4, 20), D(10)),
    "5904.TWO": (date(2026, 8, 10), D(10)),
    "4747.TWO": (date(2026, 8, 31), D(2)),
    "6949.TW": (date(2026, 9, 7), D(20)),
    "2603.TW": (date(2022, 9, 19), D("0.4")),
    "2409.TW": (date(2022, 10, 11), D("0.8")),
    "3481.TW": (date(2022, 10, 11), D("0.905")),
}
# Candidates still not checked against two sources after two rounds (2026-11-18): none of them may slip in
REJECTED = ("6548", "3093", "6763", "8476", "6919", "2352")


class Listed(BaseProvider):
    """The instruments these tests use (shioaji-data's cards in production; offline the catalog lacks them)."""

    name = "listed"

    def instruments(self):
        return [_tw("0052", "富邦科技", "TWSE", "etf", "ETF"), _tw("00632R", "元大台灣50反1", "TWSE", "etf", "ETF"),
                _tw("00662", "富邦NASDAQ", "TWSE", "etf", "ETF"), _tw("2363", "矽統", "TWSE", "stock", "半導體業"),
                _tw("2323", "中環", "TWSE", "stock", "光電業"), _tw("00631L", "元大台灣50正2", "TWSE", "etf", "ETF"),
                _tw("00674R", "期元大S&P黃金反1", "TWSE", "etf", "ETF"),
                _tw("2327", "國巨", "TWSE", "stock", "電子零組件業"), _tw("2603", "長榮", "TWSE", "stock", "航運業"),
                _tw("3481", "群創", "TWSE", "stock", "光電業")]


def price(symbol: str, d: date, close: str | D, source: str = HISTORY_SOURCE, volume: int = 1_000_000) -> PriceDaily:
    c = D(close)
    return PriceDaily(symbol=symbol, date=d, open=c, high=c, low=c, close=c, volume=volume, source=source)


def series(symbol: str, start: date, end: date, first: str, last: str, source: str = HISTORY_SOURCE) -> list:
    """Closes from ``first`` to ``last`` in even steps over the trading days of ``start``..``end``."""
    days = tw_trading_days(start, end)
    a, b = D(first), D(last)
    step = (b - a) / max(1, len(days) - 1)
    return [price(symbol, d, (a + step * i).quantize(D("0.01")), source) for i, d in enumerate(days)]


def halted(symbol: str, start: date, end: date, close: str | D) -> list[PriceDaily]:
    """A halt as a vendor may store it: every trading day repeats a close and nothing traded. Which basis the repeated
    close is on is not known (a vendor that dates the split by the halt's first day leaves it as traded): the check
    of whether the rows fold a split in reads only days that traded (:func:`test_a_halt_on_the_old_basis_...`)."""
    return [price(symbol, d, close, volume=0) for d in tw_trading_days(start, end)]


def yahoo_0052() -> list[PriceDaily]:
    """0052 as Yahoo stores it: the days before 2025-11-26 divided by 7 (245.28 as traded on 11/18 -> 35.04), the halt
    (11/19–11/25) repeating it; the archive's official closes from 2026-11-12."""
    return [*series("0052.TW", date(2025, 11, 3), date(2025, 11, 18), "34.80", "35.04"),
            *halted("0052.TW", date(2025, 11, 19), date(2025, 11, 25), "35.04"),
            *series("0052.TW", date(2025, 11, 26), date(2026, 11, 11), "35.50", "40.80"),
            *[price("0052.TW", d, c, "twse-openapi")
              for d, c in zip(ARCHIVE, ("41", "41.5", "42", "42.3"), strict=True)]]


def rows_00662(folded: bool) -> list[PriceDaily]:
    """00662: last traded 2026-11-10, halted 11/11–11/16, back on 2026-11-17 at a fifth — the archive's first close of
    it. ``folded``: Yahoo already divided the days before by 5 when the backfill ran; otherwise they are still the
    prices as traded."""
    k = 1 if folded else 5
    last = D("23.6") * k
    return [*series("00662.TW", date(2025, 11, 18), date(2026, 11, 10), str(20 * k), str(last)),
            *halted("00662.TW", date(2026, 11, 11), date(2026, 11, 16), last),
            price("00662.TW", date(2026, 11, 17), "23.10", "twse-openapi")]


@pytest.fixture()
def backfill_on(monkeypatch):
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("PRICE_HISTORY_SOURCE", raising=False)
    get_settings.cache_clear()


@pytest.fixture()
def personal(market, backfill_on):
    md = MarketData([Listed(), DemoProvider()], policy="personal")
    set_market_data(md)
    yield md
    set_market_data(market)


@pytest.fixture()
def commercial(engine, market, backfill_on, monkeypatch):
    md = MarketData([Listed(), ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    for mod in (charts_mod, instr_mod):
        monkeypatch.setattr(mod, "today_taipei", lambda: TODAY)
    yield md
    set_market_data(market)


def add(engine, rows: list[PriceDaily]) -> None:
    with Session(engine) as db:
        db.add_all(rows)
        db.commit()


def close(client, symbol: str, day: date) -> tuple[float | None, bool]:
    r = client.get(f"{API}/instruments/{symbol}/close", params={"date": day.isoformat()})
    assert r.status_code == 200, r.text
    return r.json()["close"], r.json()["reference"]


# -- the catalogue ----------------------------------------------------------------------------------------------------
def test_the_catalogue_lists_the_verified_splits_in_0050s_convention():
    assert {s: ev for s, ev in KNOWN_SPLITS.items()} == {s: (v,) for s, v in VERIFIED.items()}
    for symbol, events in KNOWN_SPLITS.items():
        assert symbol.endswith((".TW", ".TWO"))
        for day, ratio in events:
            assert day.weekday() < 5 and ratio > 0, symbol
            if ratio < 1 and (1 / ratio).quantize(D("0.0001")) == (1 / ratio).quantize(D(1)):
                assert ratio == D(1) / int((1 / ratio).quantize(D(1))), symbol  # a reverse split is exactly 1/n
    assert not {s.split(".")[0] for s in KNOWN_SPLITS} & set(REJECTED)
    # the capital reductions among them, with the cash each returns per old share (none for 4174's, to offset losses)
    cash = {("2363.TW", date(2024, 7, 29)): D("3.5"), ("2371.TW", date(2025, 6, 23)): D("0.5"),
            ("2323.TW", date(2026, 10, 12)): D(1), ("9945.TW", date(2023, 9, 25)): D(1),
            ("4174.TWO", date(2026, 2, 3)): D(0), ("2603.TW", date(2022, 9, 19)): D(6),
            ("2409.TW", date(2022, 10, 11)): D(2), ("3481.TW", date(2022, 10, 11)): D("0.95")}
    assert cash == KNOWN_REDUCTIONS
    assert all(KNOWN_SPLITS[s] == ((when, KNOWN_SPLITS[s][0][1]),) and KNOWN_SPLITS[s][0][1] < 1
               for s, when in KNOWN_REDUCTIONS)
    md = MarketData([Listed(), DemoProvider()], policy="commercial")
    assert md.corporate_events("0052.TW") == [CorporateEvent("0052.TW", date(2025, 11, 26), "split", D(7))]
    assert md.corporate_events("00632R.TW") == [CorporateEvent("00632R.TW", date(2024, 12, 11), "split", D(1) / 7)]


def test_how_the_notes_say_each_ratio():
    assert [split_how(r) for _, r in (VERIFIED["0052.TW"], VERIFIED["00632R.TW"], VERIFIED["00715L.TW"])] == [
        "1 股拆成 7 股", "7 股合成 1 股", "2 股合成 1 股"]
    # a capital reduction listed by its share ratio: per thousand shares, as its notice says it
    assert [split_how(D(r)) for r in ("0.65", "0.95", "0.9")] == [
        "每 1,000 股換成 650 股", "每 1,000 股換成 950 股", "每 1,000 股換成 900 股"]
    assert split_how(D(2) / 3) == "1.5 股合成 1 股" and split_how(D("1.5")) == "1 股拆成 1.5 股"  # as before
    assert reduction_how(D("0.5")) == "每 1,000 股換成 500 股"  # 4174: a chart never says 「2 股合成 1 股」 of it
    # the second round: 00631L, 00674R, a par value change (2327 國巨, NT$10 -> 2.5), the three 2022 reductions
    assert [split_how(r) for r in (D(22), D(1) / 5, D(4), D("0.4"), D("0.8"), D("0.905"))] == [
        "1 股拆成 22 股", "5 股合成 1 股", "1 股拆成 4 股", "每 1,000 股換成 400 股", "每 1,000 股換成 800 股",
        "每 1,000 股換成 905 股"]


def test_the_demo_prices_drop_on_a_known_split_like_0050s():
    """Personal mode's synthetic prices drop by the ratio on a known split's day, so a benchmark or chart that applies
    the split there stays continuous (a ×7 benchmark jump otherwise)."""
    demo = DemoProvider()
    for symbol in ("0052.TW", "00632R.TW", "0050.TW", "00631L.TW", "00674R.TW", "2327.TW", "2603.TW"):
        (day, ratio), = KNOWN_SPLITS[symbol]
        candles = demo.history(symbol, day - timedelta(days=10), day + timedelta(days=10))
        i = next(i for i, c in enumerate(candles) if c.t == day)
        jump = candles[i - 1].c / candles[i].c
        assert abs(jump / ratio - 1) < D("0.2"), (symbol, jump)  # the ratio, give or take a day's move
        assert demo.corporate_events(symbol) == [CorporateEvent(symbol, day, "split", ratio)]


# -- reference closes -------------------------------------------------------------------------------------------------
def test_a_reference_before_a_split_is_the_price_as_traded(client, engine, personal):
    """As for 0050 (``test_day_close``): an ETF split (0052 1 -> 7), a reverse split (00632R 7 -> 1) and a stock's
    capital reduction (2363 矽統, 650 per 1,000) are multiplied back before their day and left alone after it."""
    add(engine, [
        *yahoo_0052(),
        price("00632R.TW", date(2024, 12, 3), "22.96"), price("00632R.TW", date(2024, 12, 10), "22.96"),
        price("00632R.TW", date(2024, 12, 11), "22.9"), price("00632R.TW", date(2026, 11, 12), "13.5", "twse-openapi"),
        price("2363.TW", date(2024, 7, 18), "90.2"), price("2363.TW", date(2024, 7, 26), "90.2"),
        price("2363.TW", date(2024, 7, 29), "76.3"), price("2363.TW", date(2026, 11, 12), "61", "twse-openapi"),
    ])
    assert close(client, "0052.TW", date(2025, 11, 18)) == (245.28, True)  # 35.04 × 7, as traded that day
    assert close(client, "0052.TW", date(2025, 11, 3)) == (243.6, True)  # 34.80 × 7
    assert close(client, "0052.TW", date(2025, 11, 26)) == (35.5, True)  # the first day at the new price: as stored
    assert close(client, "0052.TW", ARCHIVE[0]) == (41.0, False)  # the archive's day: official, never a reference
    assert close(client, "00632R.TW", date(2024, 12, 3)) == (3.28, True)  # 22.96 ÷ 7: 7 old units became 1
    assert close(client, "00632R.TW", date(2024, 12, 11)) == (22.9, True)
    assert close(client, "2363.TW", date(2024, 7, 18)) == (58.63, True)  # 90.2 × 0.65
    assert close(client, "2363.TW", date(2024, 7, 29)) == (76.3, True)


def test_a_split_on_the_archives_first_day_is_multiplied_back_only_if_yahoo_folded_it_in(client, engine, personal):
    """00662 came back on 2026-11-17 at a fifth of its price: that is its first official close, so the backfill holds
    every day before it. Whether those days are divided by 5 depends on whether Yahoo had applied the split when the
    backfill ran; the stored rows say which, and only folded-in rows are multiplied back."""
    add(engine, rows_00662(folded=True))
    assert close(client, "00662.TW", date(2026, 11, 10)) == (118.0, True)  # 23.6 × 5
    assert close(client, "00662.TW", date(2026, 11, 17)) == (23.1, False)
    with Session(engine) as db:
        db.query(PriceDaily).filter(PriceDaily.symbol == "00662.TW").delete()
        db.commit()
    add(engine, rows_00662(folded=False))
    assert close(client, "00662.TW", date(2026, 11, 10)) == (118.0, True)  # stored as traded: as stored, not × 5


def test_a_capital_reduction_yahoo_did_not_fold_in_is_left_as_traded(client, engine, personal):
    """Yahoo's treatment of a cash capital reduction is not known: if its rows were not scaled, the close before the
    day is already the price as traded and must not be multiplied by 0.65."""
    add(engine, [price("2363.TW", date(2024, 7, 18), "58.63"), price("2363.TW", date(2024, 7, 29), "76.3"),
                 price("2363.TW", date(2026, 11, 12), "61", "twse-openapi")])
    assert close(client, "2363.TW", date(2024, 7, 18)) == (58.63, True)


def test_a_halt_on_the_old_basis_does_not_hide_a_folded_split(client, engine, personal):
    """A vendor that dates 0050's split by the halt's first day (2025-06-11) leaves the halt's rows as traded (188.65,
    nothing traded) while the days before are divided by 4: the check reads the last day that traded (06-10), so the
    days before are still multiplied back, as they were before the check existed."""
    add(engine, [price("0050.TW", date(2024, 3, 1), "35.6875"), price("0050.TW", date(2025, 6, 10), "47.1625"),
                 *halted("0050.TW", date(2025, 6, 11), date(2025, 6, 17), "188.65"),
                 price("0050.TW", date(2025, 6, 18), "47.57"),
                 price("0050.TW", date(2026, 11, 12), "61", "twse-openapi")])
    assert close(client, "0050.TW", date(2024, 3, 1)) == (142.75, True)
    assert close(client, "0050.TW", date(2025, 6, 10)) == (188.65, True)
    assert close(client, "0050.TW", date(2025, 6, 18)) == (47.57, True)


@pytest.mark.parametrize("folded", [True, False])
def test_a_reduction_near_par_is_told_by_its_cash(client, engine, personal, folded):
    """2323 中環 traded at about NT$10.8 before its 2026 reduction (900 per 1,000, NT$1 back): the new shares start at
    (10.81 − 1) / 0.9 = 10.90, level with the old price, so only the cash tells rows Yahoo scaled by 0.9 (10.81 / 0.9)
    from rows as traded. Either way the reference for 9/30 is the price as traded."""
    before = D("12.1") if folded else D("10.81")  # 12.1 × 0.9 = 10.89
    add(engine, [price("2323.TW", date(2026, 9, 1), before), price("2323.TW", date(2026, 9, 30), before),
                 *halted("2323.TW", date(2026, 10, 1), date(2026, 10, 8), before),
                 price("2323.TW", date(2026, 10, 12), "10.90"),
                 price("2323.TW", date(2026, 11, 12), "11.2", "twse-openapi")])
    assert close(client, "2323.TW", date(2026, 9, 30)) == ((10.89 if folded else 10.81), True)
    assert close(client, "2323.TW", date(2026, 10, 12)) == (10.9, True)


# -- the second round (2026-11-18) ------------------------------------------------------------------------------------
def test_the_second_rounds_etf_split_and_reverse_split_are_multiplied_back(client, engine, personal):
    """00631L 元大台灣50正2 (1 -> 22: last traded 2026-03-24 at 443.15, back on 03-31 near 20.14) and 00674R
    期元大S&P黃金反1 (5 -> 1: last traded 04-14, back on 04-22), stored as Yahoo scales them. 00631L's halt repeats
    the old price with nothing traded (a vendor dating the split by the halt's first day): the check reads the last
    day that traded, so the days before are still multiplied back."""
    add(engine, [
        price("00631L.TW", date(2026, 3, 2), "19.5"), price("00631L.TW", date(2026, 3, 24), "20.143182"),
        *halted("00631L.TW", date(2026, 3, 25), date(2026, 3, 30), "443.15"),
        price("00631L.TW", date(2026, 3, 31), "19.67"),
        price("00631L.TW", date(2026, 11, 12), "25.1", "twse-openapi"),
        price("00674R.TW", date(2026, 4, 1), "28.3"), price("00674R.TW", date(2026, 4, 14), "28"),
        *halted("00674R.TW", date(2026, 4, 15), date(2026, 4, 21), "28"),
        price("00674R.TW", date(2026, 4, 22), "28.5"),
        price("00674R.TW", date(2026, 11, 12), "26.2", "twse-openapi"),
    ])
    assert close(client, "00631L.TW", date(2026, 3, 24)) == (443.15, True)  # 20.143182 × 22, as traded that day
    assert close(client, "00631L.TW", date(2026, 3, 2)) == (429.0, True)  # 19.5 × 22
    assert close(client, "00631L.TW", date(2026, 3, 31)) == (19.67, True)  # the first day at the new price
    assert close(client, "00674R.TW", date(2026, 4, 14)) == (5.6, True)  # 28 ÷ 5: 5 old units became 1
    assert close(client, "00674R.TW", date(2026, 4, 1)) == (5.66, True)
    assert close(client, "00674R.TW", date(2026, 4, 22)) == (28.5, True)


@pytest.mark.parametrize("folded", [True, False])
def test_a_par_value_change_is_a_split_of_old_par_over_new(client, engine, personal, folded):
    """2327 國巨 cut its par from NT$10 to NT$2.5 (one old share for four new): last traded 2025-08-13 at 546, halted
    08-14..08-22 (the halt's rows repeat 546, nothing traded), new shares from 08-25 at a reference of 136.5. Rows
    Yahoo scaled by 4 are multiplied back; rows as traded are left as they are."""
    k = 4 if folded else 1
    add(engine, [price("2327.TW", date(2025, 8, 1), D(520) / k), price("2327.TW", date(2025, 8, 13), D(546) / k),
                 *halted("2327.TW", date(2025, 8, 14), date(2025, 8, 22), "546"),
                 price("2327.TW", date(2025, 8, 25), "143"),
                 price("2327.TW", date(2026, 11, 12), "250", "twse-openapi")])
    assert close(client, "2327.TW", date(2025, 8, 13)) == (546.0, True)
    assert close(client, "2327.TW", date(2025, 8, 1)) == (520.0, True)
    assert close(client, "2327.TW", date(2025, 8, 25)) == (143.0, True)


@pytest.mark.parametrize("folded", [True, False])
def test_a_large_cash_reduction_is_multiplied_back_only_where_folded(client, engine, personal, folded):
    """2603 長榮 2022 (400 new per 1,000 old, NT$6 back): last traded 09-06 at 80.8, halted 09-07..09-16 (rows on the
    old price, nothing traded), new shares from 09-19 at (80.8 − 6) / 0.4 = 187."""
    before, earlier = (D("202"), D("187.5")) if folded else (D("80.8"), D("75"))  # Yahoo's: ÷ 0.4
    add(engine, [price("2603.TW", date(2022, 8, 1), earlier), price("2603.TW", date(2022, 9, 6), before),
                 *halted("2603.TW", date(2022, 9, 7), date(2022, 9, 16), "80.8"),
                 price("2603.TW", date(2022, 9, 19), "187"),
                 price("2603.TW", date(2026, 11, 12), "200", "twse-openapi")])
    assert close(client, "2603.TW", date(2022, 9, 6)) == (80.8, True)
    assert close(client, "2603.TW", date(2022, 8, 1)) == (75.0, True)
    assert close(client, "2603.TW", date(2022, 9, 19)) == (187.0, True)


@pytest.mark.parametrize(("folded", "first"), [(True, "10.50"), (False, "10.50"), (False, "11.45"), (True, "11.45")])
def test_a_second_reduction_near_par_is_never_worse_than_without_it(client, engine, personal, monkeypatch, folded,
                                                                   first):
    """3481 群創 2022 (905 new per 1,000 old, NT$0.95 back) traded at 10.45, near par: the new shares' reference was
    (10.45 − 0.95) / 0.905 = 10.50. On a level first day the check tells rows Yahoo scaled (10.45 / 0.905 ≈ 11.55)
    from rows as traded, as for 2323. The real first day closed 9.05 % up (11.45): rows as traded are still told (it
    takes a fall of some 5 % to fool the check), rows Yahoo scaled are not (a rise over some 5.6 % does) and are then
    left as stored — off by 1/0.905, exactly as without the entry, never worse."""
    before = D("11.55") if folded else D("10.45")
    add(engine, [price("3481.TW", date(2022, 9, 1), before), price("3481.TW", date(2022, 9, 28), before),
                 *halted("3481.TW", date(2022, 9, 29), date(2022, 10, 7), before),
                 price("3481.TW", date(2022, 10, 11), first),
                 price("3481.TW", date(2026, 11, 12), "15", "twse-openapi")])
    got = close(client, "3481.TW", date(2022, 9, 28))
    assert got[1] is True
    if folded and first == "11.45":
        assert got[0] == 11.55  # as stored: the known limit of the check
    else:
        assert got[0] == pytest.approx(10.45, abs=0.005)  # the price as traded (11.55 × 0.905 = 10.4528)
    monkeypatch.setattr(md_service, "KNOWN_SPLITS", {s: v for s, v in KNOWN_SPLITS.items() if s != "3481.TW"})
    without = close(client, "3481.TW", date(2022, 9, 28))
    assert without == (float(before), True)
    assert abs(got[0] - 10.45) <= abs(without[0] - 10.45)


# -- charts -----------------------------------------------------------------------------------------------------------
def draw(md: MarketData, engine, **args) -> dict:
    with Session(engine) as db:
        out = execute(ToolContext(db=db, user=None, md=md), "draw_chart", args)  # type: ignore[arg-type]
    assert not out.is_error, out.content
    assert json.loads(out.content)["status"] == "chart_shown", out.content
    return out.chart


def test_charts_draw_the_backfill_as_stored_like_0050(client, engine, commercial):
    """The stock page's chart and the AI's charts read the backfill as stored: a split inside it is already folded in,
    so nothing is adjusted twice, no 「之前是當時的價格」 and no 「漲跌幅已調整」 — as for 0050's 2025 split."""
    add(engine, [*yahoo_0052(), *series("00632R.TW", date(2024, 11, 1), date(2026, 11, 11), "22.96", "14.2"),
                 *[price("00632R.TW", d, "14", "twse-openapi") for d in ARCHIVE]])
    hist = client.get(f"{API}/instruments/0052.TW/history", params={"range": "1Y"}).json()
    by_day = {c["t"]: c["c"] for c in hist["candles"]}
    assert by_day["2025-11-25"] == 35.04 and by_day["2025-11-26"] == 35.5 and by_day[ARCHIVE[-1].isoformat()] == 42.3
    assert not any("股票分割（" in n for n in hist["notes"])
    card = draw(commercial, engine, kind="price", symbols=["0052"], range="1Y")
    assert not any("之前是當時的價格" in n for n in card["notes"])
    card = draw(commercial, engine, kind="compare", symbols=["0052", "00632R"], range="5Y")
    for s in card["series"]:
        assert max(abs(p["v"]) for p in s["points"]) < 1, s["symbol"]  # no ×7 or ÷7 step
    assert not any("漲跌幅已調整" in n for n in card["notes"])


@pytest.mark.parametrize("folded", [True, False])
def test_a_split_on_the_archives_first_day_is_described_only_where_the_line_jumps(engine, commercial, folded):
    add(engine, [*rows_00662(folded), *yahoo_0052()])
    card = draw(commercial, engine, kind="price", symbols=["00662"], range="1Y")
    note = "2026/11/17 股票分割（1 股拆成 5 股），之前是當時的價格"
    assert (note in card["notes"]) is not folded  # folded in: the line is level across the day, nothing to explain
    card = draw(commercial, engine, kind="compare", symbols=["00662", "0052"], range="1Y")
    line = next(s for s in card["series"] if s["symbol"] == "00662.TW")
    assert line["points"][-1]["v"] == pytest.approx(23.1 / 20 - 1, abs=1e-4)  # 20 -> 23.10, never −80 %
    assert ("富邦NASDAQ 2026/11/17 股票分割，漲跌幅已調整" in card["notes"]) is not folded


def test_a_capital_reduction_is_never_called_a_split(engine, commercial):
    """2363 矽統's 2024 reduction is a "split" of 0.65 to every calculation, but where the line jumps on it (Yahoo's
    rows as traded) the notes say 減資, with the ratio as its notice says it."""
    add(engine, [*series("2363.TW", date(2024, 6, 3), date(2024, 7, 18), "57", "58.63"),
                 *series("2363.TW", date(2024, 7, 29), date(2026, 11, 11), "76.3", "61"),
                 *[price("2363.TW", d, "61", "twse-openapi") for d in ARCHIVE],
                 *series("2323.TW", date(2024, 6, 3), date(2026, 11, 11), "10", "11")])
    card = draw(commercial, engine, kind="price", symbols=["2363"], range="5Y")
    assert "2024/07/29 減資（每 1,000 股換成 650 股），之前是當時的價格" in card["notes"]
    card = draw(commercial, engine, kind="compare", symbols=["2363", "2323"], range="5Y")
    assert "矽統 2024/07/29 減資，漲跌幅已調整" in card["notes"]
    assert not any("股票分割" in n for n in card["notes"])


def test_a_par_value_change_is_a_split_and_a_cash_reduction_a_reduction_on_the_charts(engine, commercial):
    """Where the line jumps (Yahoo's rows as traded): 2327 國巨's par value change is described as the split it is,
    2603 長榮's cash reduction as 減資 with its ratio per thousand shares."""
    add(engine, [*series("2327.TW", date(2024, 6, 3), date(2025, 8, 13), "500", "546"),
                 *series("2327.TW", date(2025, 8, 25), date(2026, 11, 11), "143", "250"),
                 *[price("2327.TW", d, "250", "twse-openapi") for d in ARCHIVE],
                 *series("2603.TW", date(2022, 6, 1), date(2022, 9, 6), "75", "80.8"),
                 *series("2603.TW", date(2022, 9, 19), date(2026, 11, 11), "187", "200"),
                 *[price("2603.TW", d, "200", "twse-openapi") for d in ARCHIVE]])
    card = draw(commercial, engine, kind="price", symbols=["2327"], range="5Y")
    assert "2025/08/25 股票分割（1 股拆成 4 股），之前是當時的價格" in card["notes"]
    card = draw(commercial, engine, kind="price", symbols=["2603"], range="5Y")
    assert "2022/09/19 減資（每 1,000 股換成 400 股），之前是當時的價格" in card["notes"]
    assert not any("股票分割（" in n for n in card["notes"])  # (the backfill's own note still says what Yahoo does)


# -- the ledger -------------------------------------------------------------------------------------------------------
def test_the_ledger_of_a_buyer_after_the_split_is_the_official_closes(client, engine, commercial, monkeypatch):
    """Bought after the split (0052 on the archive's first day, 00662 on its first day back): market value, P&L and
    performance are the official closes, with or without the new entries; a benchmark across a split stays level."""
    add(engine, [*yahoo_0052(), *rows_00662(folded=True)])
    acc = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD", "fee_discount": 0.28}).json()["id"]
    for symbol, day, px in (("0052.TW", ARCHIVE[0], 41), ("00662.TW", ARCHIVE[-1], "23.10")):
        r = client.post(f"{API}/transactions", json={"account_id": acc, "symbol": symbol, "type": "buy",
                                                     "trade_date": day.isoformat(), "quantity": 1000, "price": px})
        assert r.status_code == 201, r.text

    def ledger() -> tuple:
        holdings = {h["symbol"]: (h["price"], h["market_value"])
                    for h in client.get(f"{API}/portfolio/holdings").json()}
        summary = client.get(f"{API}/portfolio/summary").json()
        perf = {b: client.get(f"{API}/portfolio/performance", params={"range": "ALL", "benchmark": b}).json()
                for b in ("0052.TW", "00662.TW")}
        return holdings, summary["market_value"], summary["unrealized_pnl"], {
            b: ([(p["t"], p["market_value"]) for p in v["series"]], v["benchmark"]["twr"]) for b, v in perf.items()}

    now = ledger()
    holdings, value, pnl, perf = now
    assert holdings == {"0052.TW": (42.3, 42_300.0), "00662.TW": (23.1, 23_100.0)}
    assert value == pytest.approx(65_400.0)
    assert pnl == pytest.approx(65_400.0 - 41_000 - 23_100, abs=200)  # fees aside: the official closes, no ×5 / ÷7
    points, bench = perf["0052.TW"]
    assert points == [(ARCHIVE[0].isoformat(), 41_000.0), (ARCHIVE[1].isoformat(), 41_500.0),
                      (ARCHIVE[2].isoformat(), 42_000.0), (ARCHIVE[3].isoformat(), 65_400.0)]
    assert bench == pytest.approx(42.3 / 41 - 1, abs=1e-6)  # 0052's 2025 split is before the axis: plain change
    assert perf["00662.TW"][1] == pytest.approx(0.0)  # its first official close is the split day: no +400 % jump
    # the same with the catalogue as it was (0050 only)
    monkeypatch.setattr(md_service, "KNOWN_SPLITS", {"0050.TW": KNOWN_SPLITS["0050.TW"]})
    assert ledger() == now
