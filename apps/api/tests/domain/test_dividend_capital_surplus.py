from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from forliosa.marketdata.base import DividendEvent
from forliosa.services.transactions import capital_surplus_part


def _md(events):
    return SimpleNamespace(dividends=lambda symbol: SimpleNamespace(value=events))


def _event(ex: date, cash: str, sources=None):
    return DividendEvent("1101.TW", ex.year, str(ex.year), D(cash), D(0), ex, None,
                         cash_sources=tuple(D(x) for x in sources) if sources else None)


TAIWAN_CEMENT = _event(date(2026, 7, 10), "0.8", ("0", "0", "0.8"))
MIXED = _event(date(2026, 7, 10), "2.0", ("1.5", "0", "0.5"))


def test_payment_matched_to_latest_ex_date_with_capital_surplus():
    md = _md([_event(date(2025, 7, 10), "1.0", ("1.0", "0", "0")), TAIWAN_CEMENT])
    # 40,000 shares × 0.8 = 32,000, all capital surplus
    assert capital_surplus_part(md, "1101.TW", date(2026, 8, 12), D(32000), D(40000), D("0.8")) == D(32000)
    # amount only: proportional split (0.5 / 2.0 of 50,000)
    assert capital_surplus_part(_md([MIXED]), "1101.TW", date(2026, 8, 1), D(50000), None, None) == D(12500)


def test_no_exclusion_when_nothing_matches():
    md = _md([TAIWAN_CEMENT])
    assert capital_surplus_part(md, "1101.TW", date(2026, 7, 1), D(32000), None, None) == 0  # before ex-date
    assert capital_surplus_part(md, "1101.TW", date(2027, 1, 30), D(32000), None, None) == 0  # too long after
    assert capital_surplus_part(md, "1101.TW", date(2026, 8, 1), D(32000), None, D("1.2")) == 0  # other amount
    no_sources = _md([_event(date(2026, 7, 10), "0.8")])
    assert capital_surplus_part(no_sources, "1101.TW", date(2026, 8, 1), D(32000), None, None) == 0


def test_latest_ex_date_wins_even_without_capital_surplus():
    md = _md([TAIWAN_CEMENT, _event(date(2026, 8, 20), "0.8", ("0.8", "0", "0"))])
    assert capital_surplus_part(md, "1101.TW", date(2026, 9, 5), D(32000), None, None) == 0


def test_market_data_failure_means_no_exclusion():
    def boom(symbol):
        raise RuntimeError("down")

    assert capital_surplus_part(SimpleNamespace(dividends=boom), "1101.TW", date(2026, 8, 1), D(1000), None,
                                None) == 0
