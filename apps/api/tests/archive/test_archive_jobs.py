"""Archive jobs: every dataset lands in its table, and re-running changes nothing (idempotent)."""

from datetime import date
from decimal import Decimal as D

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.marketdata.http import url_allowed
from forliosa.models import (
    FinancialReport,
    ForeignHoldingDaily,
    FundProfile,
    InstitutionalDaily,
    MarginDaily,
    MarketEvent,
    MarketHoliday,
    PriceDaily,
    ReferencePrice,
    ShareholdingDistribution,
    ValuationDaily,
)
from tests.archive.fakes import NOW, FakeFetcher

TABLES = (PriceDaily, ValuationDaily, ReferencePrice, MarginDaily, InstitutionalDaily, ForeignHoldingDaily,
          ShareholdingDistribution, MarketEvent, FinancialReport)


def counts(db: Session) -> dict[str, int]:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in TABLES}


def run(db: Session, policy: str = "personal"):
    return Archiver(db, FakeFetcher(), policy, now_fn=lambda: NOW).run()


def test_archive_run_is_idempotent(engine, market):
    with Session(engine) as db:
        results = run(db)
        errors = {r.name for r in results if r.error}
        # Only the industries without a fixture fail (each dataset is isolated).
        assert errors and all("t187ap0" in e for e in errors), errors
        first = counts(db)
        assert all(first[t] > 0 for t in first), first
        run(db)
        assert counts(db) == first

        assert db.get(PriceDaily, ("2330.TW", date(2026, 11, 11))).close == D("2395.00")
        assert db.get(PriceDaily, ("6488.TWO", date(2026, 11, 11))).source == "tpex-openapi"
        ref = db.get(ReferencePrice, ("2330.TW", date(2026, 11, 12)))
        assert (ref.reference_price, ref.limit_up, ref.limit_down) == (D(2395), D(2630), D(2160))
        assert db.get(ReferencePrice, ("3680.TWO", date(2026, 11, 12))).reference_price == D("425.5")
        # 2026-11-14 review: every TWSE row of the file is for the same coming session — a thinly traded stock
        # (1538, its own LastTradingDay 11/09) is not stamped with an earlier day
        twse_days = set(db.scalars(select(ReferencePrice.date).where(ReferencePrice.source == "twse-openapi")))
        assert twse_days == {date(2026, 11, 12)}
        assert db.get(MarginDaily, ("2330.TW", date(2026, 11, 11))).margin_balance == 32523  # stamped 11-11
        assert db.get(InstitutionalDaily, ("6488.TWO", date(2026, 11, 11))).total_net == 1302529
        assert db.get(InstitutionalDaily, ("2330.TW", date(2026, 11, 11))) is None  # TWSE website: never scraped
        assert db.get(ValuationDaily, ("6488.TWO", date(2026, 11, 11))).per == D("35.75")
        assert db.get(FinancialReport, ("6488.TWO", "2026Q3", "income_ytd")).values["eps"] == "15.00"
        assert db.get(ShareholdingDistribution, ("2330.TW", date(2026, 11, 6), 15)).holders == 1470
        ex = db.scalar(select(MarketEvent).where(MarketEvent.symbol == "6488.TWO",
                                                 MarketEvent.type == "ex_dividend"))
        assert ex.date == date(2026, 12, 29) and ex.data["cash"] == "6.00000000"


def test_only_open_data_endpoints_are_fetched(engine, market):
    fetcher = FakeFetcher()
    with Session(engine) as db:
        for policy in ("commercial", "personal"):
            Archiver(db, fetcher, policy, now_fn=lambda: NOW).run()
        assert fetcher.calls and all(url_allowed(u) for u in fetcher.calls)
        assert not any("www.twse.com.tw" in u or "mis.twse" in u for u in fetcher.calls)
        assert db.scalar(select(func.count()).select_from(InstitutionalDaily)
                         .where(InstitutionalDaily.source == "twse-web")) == 0
        # TPEx publishes per-stock institutional flows and foreign holdings in its OpenAPI.
        assert db.get(InstitutionalDaily, ("6488.TWO", date(2026, 11, 11))) is not None
        assert db.get(ForeignHoldingDaily, ("6488.TWO", date(2026, 11, 11))).pct == D("0.2949")
        # 證交所新聞: rows naming a company code are filed under it; ETF basics without people's names
        delisting = db.scalar(select(MarketEvent).where(MarketEvent.type == "exchange_news",
                                                        MarketEvent.symbol == "2314.TW").limit(1))
        assert delisting is not None and delisting.url.startswith("https://www.twse.com.tw/zh/about/news/")
        assert db.scalar(select(func.count()).select_from(MarketEvent).where(
            MarketEvent.type == "exchange_news", MarketEvent.symbol == "MARKET")) >= 2
        etf = db.get(FundProfile, "0050.TW")
        assert etf.values["index_name"] == "臺灣50指數" and etf.values["listed"] == "2003-06-30"
        assert etf.values["units"] == 25048000000 and "陳重銓" not in str(etf.values)
        assert db.get(MarketHoliday, date(2026, 12, 25)).name == "行憲紀念日"


def test_finmind_backfill_skips_listed_institutional_flows(engine, monkeypatch):
    """Personal opt-in only. Listed (TWSE) stocks get margin only: their 三大法人／外資持股 are never shown, so
    those FinMind datasets are not even requested (each dataset is one request against the small quota)."""
    import forliosa.archive as archive_mod
    import forliosa.marketdata.finmind as finmind_mod

    day = {"date": "2026-11-11"}
    payloads = {
        "TaiwanStockInstitutionalInvestorsBuySell": [{**day, "name": "Foreign_Investor", "buy": 5000, "sell": 4000}],
        "TaiwanStockMarginPurchaseShortSale": [{**day, "MarginPurchaseTodayBalance": 10, "ShortSaleTodayBalance": 2,
                                                "MarginPurchaseLimit": 100}],
        "TaiwanStockShareholding": [{**day, "ForeignInvestmentSharesRatio": 50, "ForeignInvestmentShares": 100}],
    }

    class RecordingFetcher:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def get_json(self, url, params=None, headers=None):
            self.calls.append((params["data_id"], params["dataset"]))
            return {"msg": "success", "status": 200, "data": payloads[params["dataset"]]}

    fetcher = RecordingFetcher()
    real = finmind_mod.FinMindProvider
    monkeypatch.setattr(finmind_mod, "FinMindProvider", lambda *a, **k: real(
        fetcher=fetcher, cache_dir=None, today_fn=lambda: date(2026, 11, 12)))
    monkeypatch.setattr(archive_mod._time, "sleep", lambda s: None)
    with Session(engine) as db:
        archive_mod.finmind_backfill(db, ["2330.TW", "6488.TWO", "AAPL"], date(2026, 11, 1))
        assert db.scalars(select(MarginDaily.symbol).order_by(MarginDaily.symbol)).all() == ["2330.TW", "6488.TWO"]
        assert db.scalars(select(InstitutionalDaily.symbol)).all() == ["6488.TWO"]
        assert db.scalars(select(ForeignHoldingDaily.symbol)).all() == ["6488.TWO"]
    assert sorted(fetcher.calls) == [
        ("2330", "TaiwanStockMarginPurchaseShortSale"),
        ("6488", "TaiwanStockInstitutionalInvestorsBuySell"),
        ("6488", "TaiwanStockMarginPurchaseShortSale"),
        ("6488", "TaiwanStockShareholding"),
    ]


def test_an_empty_answer_keeps_the_dataset_date(engine, market):
    """2026-11-14 review: a job whose upstream returned no dated rows (no ex-rights stocks today) wrote a null date,
    and the dataset looked stale."""
    from forliosa.models import DatasetStatus

    with Session(engine) as db:
        archiver = Archiver(db, FakeFetcher(), "personal", now_fn=lambda: NOW)
        archiver._status("tpex-openapi/exright", date(2026, 11, 11), 3)
        archiver._status("tpex-openapi/exright", None, 0)
        row = db.get(DatasetStatus, "tpex-openapi/exright")
        assert (row.data_date, row.rows) == (date(2026, 11, 11), 0)
