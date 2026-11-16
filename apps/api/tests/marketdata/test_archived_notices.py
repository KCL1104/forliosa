"""2026-11-16: every AI turn about a stock downloaded TWT48U_ALL live (0.3–3.8 s) although the worker archives the same
notices three times a trading day. While the archive run is recent its copy alone answers dividends and ex-rights; with
no archive, no status row or an old run the live files are asked exactly as before."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import BaseProvider, DividendEvent
from forliosa.marketdata.service import NOTICES_FRESH_SECONDS, MarketData
from forliosa.models import DatasetStatus, MarketEvent, PriceDaily
from forliosa.timeutil import today_taipei

TODAY = today_taipei()
EX_ARCHIVED, EX_LIVE_ONLY = TODAY + timedelta(days=5), TODAY + timedelta(days=9)


class LiveNotices(BaseProvider):
    """Stands in for TwseOpenApiProvider / TpexOpenApiProvider: the live notice file, counted."""

    is_demo = False

    def __init__(self, name: str, market_suffix: str):
        self.name, self.suffix, self.calls = name, market_suffix, []

    def dividends(self, symbol: str) -> list[DividendEvent] | None:
        self.calls.append(("dividends", symbol))
        if not symbol.endswith(self.suffix):
            return None
        return [DividendEvent(symbol, EX_LIVE_ONLY.year, str(EX_LIVE_ONLY.year), D("3"), D("0"), EX_LIVE_ONLY, None)]

    def ex_rights_on(self, symbols, d):
        self.calls.append(("ex_rights_on", tuple(symbols)))
        return {}


class BrokenArchive(ArchiveProvider):
    def dividends(self, symbol):
        raise RuntimeError("database gone")


@pytest.fixture()
def archive_db(engine):
    with Session(engine) as db:
        db.add(MarketEvent(key="twt48u-2308", symbol="2308.TW", date=EX_ARCHIVED, type="ex_dividend", title="除息",
                           data={"cash": "5.0", "stock_ratio": "0"}, source="twse-openapi"))
        for i, close in ((3, 1240), (2, 1150)):
            for sym in ("2308.TW", "6488.TWO"):
                db.add(PriceDaily(symbol=sym, date=TODAY - timedelta(days=i), open=D(close), high=D(close),
                                  low=D(close), close=D(close), volume=1000,
                                  source="twse-openapi" if sym.endswith(".TW") else "tpex-openapi"))
        db.commit()
    return engine


def archived(engine, key: str, hours_ago: float) -> None:
    with Session(engine) as db:
        db.merge(DatasetStatus(key=key, data_date=TODAY, rows=1,
                               fetched_at=datetime.now(UTC) - timedelta(hours=hours_ago)))
        db.commit()


def facade(engine, archive_cls=ArchiveProvider, live_first: bool = False):
    twse, tpex = LiveNotices("twse_openapi", ".TW"), LiveNotices("tpex_openapi", ".TWO")
    archive = archive_cls("commercial", session_fn=lambda: Session(engine))
    providers = [twse, archive, tpex] if live_first else [archive, twse, tpex]
    return MarketData(providers, policy="commercial"), twse, tpex


def ex_dates(md, symbol="2308.TW") -> list:
    return sorted(e.ex_dividend_date for e in md.dividends(symbol).value)


def test_a_recent_archive_run_answers_dividends_without_the_live_file(archive_db):
    archived(archive_db, "twse-openapi/price", hours_ago=1)
    md, twse, _ = facade(archive_db)
    assert ex_dates(md) == [EX_ARCHIVED]
    assert md.dividends("2308.TW").source == "twse-openapi" and twse.calls == []


@pytest.mark.parametrize("hours_ago", [None, NOTICES_FRESH_SECONDS / 3600 + 1])
def test_without_a_recent_run_the_live_file_is_asked_as_before(archive_db, hours_ago):
    if hours_ago is not None:
        archived(archive_db, "twse-openapi/price", hours_ago=hours_ago)
    md, twse, _ = facade(archive_db)
    assert ex_dates(md) == [EX_ARCHIVED, EX_LIVE_ONLY] and twse.calls == [("dividends", "2308.TW")]


def test_the_live_file_answers_when_the_archive_fails_or_comes_later(archive_db):
    archived(archive_db, "twse-openapi/price", hours_ago=1)
    md, twse, _ = facade(archive_db, archive_cls=BrokenArchive)  # its own answer failed in this call
    assert ex_dates(md) == [EX_LIVE_ONLY] and twse.calls == [("dividends", "2308.TW")]
    md, twse, _ = facade(archive_db, live_first=True)  # a provider order where the live file is asked first
    assert ex_dates(md) == [EX_ARCHIVED, EX_LIVE_ONLY] and twse.calls == [("dividends", "2308.TW")]


def test_ex_rights_skip_only_the_market_whose_notices_are_archived(archive_db):
    archived(archive_db, "twse-openapi/price", hours_ago=1)
    archived(archive_db, "tpex-openapi/price", hours_ago=30)  # the TPEx run is old: its live file is asked
    md, twse, tpex = facade(archive_db)
    quotes = md.quotes(["2308.TW", "6488.TWO"])
    assert quotes["2308.TW"].reference_price == D(1240) and quotes["6488.TWO"].reference_price == D(1240)
    assert [c for c in twse.calls if c[0] == "ex_rights_on"] == []
    assert [c for c in tpex.calls if c[0] == "ex_rights_on"] == [("ex_rights_on", ("2308.TW", "6488.TWO"))]


def test_ex_rights_without_status_rows_ask_both_live_files(archive_db):
    md, twse, tpex = facade(archive_db)
    md.quotes(["2308.TW", "6488.TWO"])
    assert ("ex_rights_on", ("2308.TW", "6488.TWO")) in twse.calls
    assert ("ex_rights_on", ("2308.TW", "6488.TWO")) in tpex.calls
