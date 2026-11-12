"""New archive jobs (2026-11-12): indices, dividend resolutions, company profiles, ex-rights results, TAIFEX."""

import json
from datetime import date
from decimal import Decimal as D

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.models import (
    CompanyProfile,
    DatasetStatus,
    DividendResolution,
    ExRightsResult,
    FinancialReport,
    FxRate,
    IndexDaily,
    TaifexContractMap,
    TaifexFinalSettlement,
    TaifexFuturesDaily,
    TaifexInstitutional,
    TaifexLargeTraders,
    TaifexMargin,
    TaifexOptionsDaily,
    TaifexPutCallRatio,
    TaifexUnderlying,
)
from tests.archive.fakes import FIX, NOW, TAIFEX_ROUTES, FakeFetcher, load

TAIFEX_TABLES = (TaifexFuturesDaily, TaifexOptionsDaily, TaifexInstitutional, TaifexLargeTraders, TaifexPutCallRatio,
                 TaifexContractMap, TaifexFinalSettlement, TaifexMargin, TaifexUnderlying, FxRate)


class Patched(FakeFetcher):
    """FakeFetcher whose JSON answers can be edited per URL suffix."""

    def __init__(self, edits):
        super().__init__()
        self.edits = edits

    def get_json(self, url, params=None, headers=None):
        data = super().get_json(url, params, headers)
        for suffix, fn in self.edits.items():
            if url.endswith(suffix):
                return fn(data)
        return data

    def get_bytes(self, url, params=None, headers=None):
        for suffix, fn in self.edits.items():
            if url.endswith(suffix) and suffix in TAIFEX_ROUTES:
                self.calls.append(url)
                return json.dumps(fn(load(TAIFEX_ROUTES[suffix])), ensure_ascii=False).encode()
        return super().get_bytes(url, params, headers)


def run(db, only, fetcher=None, policy="commercial"):
    return Archiver(db, fetcher or FakeFetcher(), policy, now_fn=lambda: NOW).run(only)


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_taifex_jobs_are_idempotent_and_backfill_multi_day_windows(engine):
    with Session(engine) as db:
        results = run(db, ["taifex", "weekly"])
        assert not [r for r in results if r.error], [r for r in results if r.error]
        first = {m.__tablename__: count(db, m) for m in TAIFEX_TABLES}
        assert all(first.values()), first
        run(db, ["taifex", "weekly"])
        assert {m.__tablename__: count(db, m) for m in TAIFEX_TABLES} == first

        # PutCallRatio and DailyForeignExchangeRates carry a month / six weeks: the first run backfills them
        assert first["taifex_put_call_ratio"] == 21
        usd = list(db.scalars(select(FxRate).where(FxRate.pair == "USDTWD").order_by(FxRate.date)))
        assert len(usd) == 27 and usd[-1].rate == D("32.86") and usd[-1].source == "taifex-openapi"
        tx = db.get(TaifexFuturesDaily, (date(2026, 11, 11), "regular", "TX", "202611"))
        assert (tx.last, tx.settlement_price, tx.open_interest) == (D("44091"), D("44136"), 122326)
        night = db.get(TaifexFuturesDaily, (date(2026, 11, 11), "after_hours", "TX", "202611"))
        assert night.last == D("42522") and night.settlement_price is None
        foreign = db.get(TaifexInstitutional, (date(2026, 11, 11), "futures", "臺股期貨", "", "外資及陸資"))
        assert foreign.contract_code == "TX" and foreign.oi_net == -104271
        assert db.get(TaifexContractMap, "臺股期貨").contract_code == "TX"
        assert db.get(TaifexUnderlying, ("SSF", "CDF")).stock_code == "2330"
        status = {s.key: s.data_date for s in db.scalars(select(DatasetStatus))}
        assert status["taifex-openapi/fx"] == date(2026, 11, 11)
        assert status["taifex-openapi/final_settlement"] == date(2025, 12, 5)  # stale upstream
        assert status["twse-openapi/breadth"] == date(2026, 6, 5) and status["twse-openapi/pledge"] == date(2026, 8, 19)


def test_margins_are_stored_only_when_they_change(engine):
    with Session(engine) as db:
        run(db, ["taifex"])
        before = count(db, TaifexMargin)
        run(db, ["taifex"])
        assert count(db, TaifexMargin) == before  # unchanged margins: no new rows

        def raise_cdf(rows):
            out = [dict(r) for r in rows]
            for r in out:
                r["Date"] = "20261112"
                if r["Contract"] == "CDF":
                    r["InitialMarginRate"] = "27.00%"
            return out

        run(db, ["taifex"], Patched({"/SingleStockFuturesMargining": raise_cdf}))
        assert count(db, TaifexMargin) == before + 1
        latest = db.get(TaifexMargin, ("stock", "CDF", date(2026, 11, 12)))
        assert latest.initial == D("0.27") and latest.is_rate


def test_indices_companies_dividends_and_exrights(engine):
    with Session(engine) as db:
        results = run(db, ["twse", "tpex", "companies"])
        assert not [r for r in results if r.error], [r for r in results if r.error]
        tr = list(db.scalars(select(IndexDaily).where(IndexDaily.name == "發行量加權股價報酬指數")
                             .order_by(IndexDaily.date)))
        # MFI94U backfills the month (8 days); MI_INDEX adds the official change of the latest day
        assert [r.date for r in tr][0] == date(2026, 11, 2) and len(tr) == 8
        assert (tr[-1].close, tr[-1].change) == (D("102340.20"), D("3573.19"))
        otc = db.get(IndexDaily, ("櫃買指數", date(2026, 11, 12)))
        assert (otc.open, otc.close) == (D("344.58"), D("335.73"))  # tpex_index's OHLC is not overwritten
        assert db.get(IndexDaily, ("櫃買報酬指數", date(2026, 11, 12))).close == D("624.57")
        tsmc = db.get(CompanyProfile, "2330.TW")
        assert tsmc.shares_outstanding == 25932370067 and tsmc.industry == "半導體業"
        assert "魏哲家" not in json.dumps(tsmc.values, ensure_ascii=False)
        assert db.get(CompanyProfile, "6488.TWO").listed_date == date(2015, 9, 25)
        tcc = db.get(DividendResolution, ("1101.TW", date(2025, 1, 1), 1))
        assert tcc.cash_capital_surplus == D("0.8") and tcc.cash_earnings == D(0)
        assert db.get(ExRightsResult, ("3680.TWO", date(2026, 11, 12))).reference_price == D("425.50")
        first = {m.__tablename__: count(db, m) for m in (IndexDaily, CompanyProfile, DividendResolution,
                                                          ExRightsResult)}
        run(db, ["twse", "tpex", "companies"])
        assert {m.__tablename__: count(db, m) for m in (IndexDaily, CompanyProfile, DividendResolution,
                                                         ExRightsResult)} == first


def test_statements_skip_blank_rows_and_never_erase_archived_values(engine):
    with Session(engine) as db:
        results = {r.name: r for r in run(db, ["financials"])}
        # industries with no TPEx company answer one blank row: nothing stored, no error
        assert results["tpex t187ap07_O_ins"].error is None and results["tpex t187ap07_O_ins"].rows == 0
        assert results["tpex t187ap06_O_bd"].rows == 2
        good = db.get(FinancialReport, ("6488.TWO", "2026Q3", "income_ytd")).values
        assert good["revenue"] is not None

        def blank_revenue(rows):
            return [{**r, "營業收入": ""} for r in rows]

        run(db, ["financials"], Patched({"/mopsfin_t187ap06_O_ci": blank_revenue}))
        db.expire_all()
        assert db.get(FinancialReport, ("6488.TWO", "2026Q3", "income_ytd")).values == good


def test_fixture_files_exist():
    assert all((FIX / name).exists() for name in TAIFEX_ROUTES.values())
