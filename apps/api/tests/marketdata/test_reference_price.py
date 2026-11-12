"""Quote reference price (平盤) and limits; change on an ex-dividend day is measured from the reference."""

from datetime import date
from decimal import Decimal as D

from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import BaseProvider, QuoteData
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData
from forliosa.services.instruments import quote_out
from tests.archive.fakes import NOW, FakeFetcher

EX_DAY = date(2026, 11, 12)


class ExDayQuotes(BaseProvider):
    """3680 on its ex-dividend day: previous close 435.50, cash dividend 9.9147456."""

    name = "fake"

    def __init__(self, limits=(None, None), prev=D("435.50")):
        self.limits, self.prev = limits, prev

    def quotes(self, symbols):
        return {"3680.TWO": QuoteData("3680.TWO", price=D("430.00"), prev_close=self.prev, open=D(426), high=D(431),
                                      low=D(424), volume=1_000_000, trade_date=EX_DAY, source="fake",
                                      limit_up=self.limits[0], limit_down=self.limits[1])}

    def ex_rights_on(self, symbols, d):
        return {"3680.TWO": (D("9.9147456"), D(0))} if d == EX_DAY and "3680.TWO" in symbols else {}


def test_change_on_ex_dividend_day_is_against_the_reference_price():
    q = MarketData([ExDayQuotes()]).quote("3680.TWO")
    assert (q.reference_price, q.limit_up, q.limit_down) == (D("425.5"), D(468), D("383.5"))
    out = quote_out(q)
    # 430.00 − 425.50 = +4.50 (+1.06 %), not 430.00 − 435.50 = −5.50 vs the previous close
    assert out["change"] == 4.5 and out["change_pct"] == round(4.5 / 425.5, 6)
    assert out["prev_close"] == 435.5 and out["reference_price"] == 425.5


def test_quote_previous_close_that_already_is_the_reference_is_not_adjusted_twice():
    # MIS-style quote whose "previous close" (y) is already the ex-dividend reference, with published limits
    q = MarketData([ExDayQuotes(limits=(D("468.00"), D("383.00")), prev=D("425.50"))]).quote("3680.TWO")
    assert q.reference_price == D("425.50")
    assert quote_out(q)["change"] == 4.5


def test_official_archive_reference_wins(engine, market):
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "personal", now_fn=lambda: NOW).run(["tpex"])
    md = MarketData([ArchiveProvider("personal", session_fn=lambda: Session(engine)), ExDayQuotes()])
    q = md.quotes(["3680.TWO"])["3680.TWO"]
    # The archive's latest close (2026-11-11, 435.50) is older than the fake's 2026-11-12 quote: newer wins.
    assert q.trade_date == EX_DAY and q.price == D("430.00")
    assert (q.reference_price, q.limit_up, q.limit_down) == (D("425.50"), D("468.00"), D("383.50"))


def test_normal_day_reference_is_previous_close_and_us_has_no_limits():
    md = MarketData([DemoProvider()])
    q = md.quote("2330.TW")
    assert q.reference_price == q.prev_close and q.limit_up is not None and q.limit_up > q.prev_close
    us = md.quote("AAPL")
    assert us.reference_price == us.prev_close and us.limit_up is None and us.limit_down is None
