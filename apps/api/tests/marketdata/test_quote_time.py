"""A quote's ``as_of`` is the close of the trading day its price belongs to, and commercial mode is never real-time
(docs/api-contract.md 「收盤價的標示與盤中狀態」)."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal as D

import pytest

from forliosa.marketdata.base import BaseProvider, QuoteData
from forliosa.marketdata.service import MarketData
from forliosa.marketdata.tpex import parse_daily_close_quotes
from forliosa.marketdata.twse import parse_stock_day_all
from forliosa.services.instruments import quote_out
from forliosa.timeutil import TAIPEI, market_close_dt

DAY = date(2026, 11, 12)
CLOSE = datetime(2026, 11, 12, 13, 30, tzinfo=TAIPEI)


class Provider(BaseProvider):
    """A real provider answering with whatever time and real-time flag it is given."""

    name = "fake"

    def __init__(self, as_of: datetime | None, is_realtime: bool):
        self.as_of, self.is_realtime = as_of, is_realtime

    def quotes(self, symbols):
        return {s: QuoteData(s, price=D("2400"), prev_close=D("2390"), open=D("2385"), high=D("2410"), low=D("2380"),
                             volume=30_000_000, as_of=self.as_of, trade_date=DAY, is_realtime=self.is_realtime,
                             source="fake") for s in symbols}


def test_market_close_dt_is_1330_taipei():
    assert market_close_dt(DAY) == CLOSE and CLOSE.utcoffset().total_seconds() == 8 * 3600


def test_the_exchange_parsers_stamp_the_close_of_the_row_date():
    twse = parse_stock_day_all([{"Date": "1151112", "Code": "2330", "ClosingPrice": "2400.00", "Change": "10.00"}])
    tpex = parse_daily_close_quotes([{"Date": "1151112", "SecuritiesCompanyCode": "6488", "Close": "450.00"}])
    for q in (twse["2330.TW"], tpex["6488.TWO"]):
        assert (q.trade_date, q.as_of, q.is_realtime) == (DAY, CLOSE, False)


@pytest.mark.parametrize(("as_of", "is_realtime"), [
    (None, False),  # a provider that gives no time
    (datetime(2026, 11, 12, 17, 45, tzinfo=TAIPEI), False),  # … or the time it produced the file
    (datetime(2026, 11, 13, 5, 20, tzinfo=TAIPEI), True),  # … or claims to be live
])
def test_commercial_quotes_are_the_close_of_their_day_and_never_realtime(as_of, is_realtime):
    md = MarketData([Provider(as_of, is_realtime)], policy="commercial")
    for q in (md.quote("2330.TW"), md.live_quotes(["2330.TW"])["2330.TW"]):  # the single quote and the SSE stream
        assert q is not None and (q.as_of, q.is_realtime, q.trade_date) == (CLOSE, False, DAY)
        out = quote_out(q)
        assert out["as_of"] == "2026-11-12T13:30:00+08:00" and out["is_realtime"] is False
    md_jitter = MarketData([Provider(as_of, is_realtime)], jitter=True, policy="commercial")
    assert md_jitter.live_quotes(["2330.TW"])["2330.TW"].is_realtime is False  # real quotes are never jittered


def test_a_missing_time_is_filled_in_every_mode():
    q = MarketData([Provider(None, False)], policy="personal").quote("6488.TWO")
    assert q is not None and q.as_of == datetime.combine(DAY, time(13, 30), TAIPEI)
