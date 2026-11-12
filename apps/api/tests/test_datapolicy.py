"""DATA_POLICY: commercial uses only government open data; non-commercial sources are labelled."""

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.config import Settings
from forliosa.datapolicy import allowed, is_commercial_source, label, labels, provider_allowed
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, build_providers
from forliosa.models import PriceDaily


def test_labels_mark_non_commercial_sources():
    assert label("finmind").endswith("（非商用）")
    assert label("twse-mis").endswith("（非商用）") and label("twse-web").endswith("（非商用）")
    assert not label("twse-openapi").endswith("（非商用）")
    assert labels(["twse-mis+shioaji-data", "shioaji-data"]) == [label("twse-mis"), label("shioaji-data")]
    assert is_commercial_source("twse-openapi") and not is_commercial_source("twse-openapi+finmind")
    assert allowed("finmind", "personal") and not allowed("finmind", "commercial")
    assert not provider_allowed("twse_mis", "commercial") and provider_allowed("archive", "commercial")


def test_commercial_policy_builds_no_non_commercial_provider():
    every = "twse_mis,archive,twse_openapi,tpex_openapi,shioaji_data,finmind,demo"
    names = [p.name for p in build_providers(Settings(data_policy="commercial", market_data_providers=every))]
    assert "finmind" not in names and "twse_mis" not in names
    assert names[:3] == ["archive", "twse_openapi", "tpex_openapi"]
    personal = [p.name for p in build_providers(Settings(data_policy="personal", market_data_providers=every))]
    assert "finmind" in personal and "twse_mis" in personal
    # MarketData drops non-commercial providers too (defence in depth)
    from forliosa.marketdata.finmind import FinMindProvider

    md = MarketData([FinMindProvider(), DemoProvider()], policy="commercial")
    assert [p.name for p in md.providers] == ["demo"]


@pytest.mark.parametrize("value", ["COMMERCIAL", " commercial "])
def test_policy_setting_is_case_insensitive(value):
    assert Settings(data_policy=value).data_policy == "commercial"


def test_archive_ignores_non_commercial_rows_under_commercial(engine):
    with Session(engine) as db:
        db.add_all([
            PriceDaily(symbol="2330.TW", date=date(2026, 11, 10), close=D(2285), source="finmind"),
            PriceDaily(symbol="2330.TW", date=date(2026, 11, 11), close=D(2395), source="twse-openapi"),
        ])
        db.commit()
    commercial = ArchiveProvider("commercial", session_fn=lambda: Session(engine))
    personal = ArchiveProvider("personal", session_fn=lambda: Session(engine))
    assert [c.t for c in commercial.history("2330.TW", date(2026, 11, 1), date(2026, 11, 30))] == [date(2026, 11, 11)]
    assert len(personal.history("2330.TW", date(2026, 11, 1), date(2026, 11, 30))) == 2


def test_history_merges_partial_archive_with_the_next_real_provider(engine):
    with Session(engine) as db:
        db.add(PriceDaily(symbol="2330.TW", date=date(2026, 11, 11), close=D(2395), source="twse-openapi"))
        db.commit()

    class Older(DemoProvider):
        name, is_demo = "older", False

    md = MarketData([ArchiveProvider("personal", session_fn=lambda: Session(engine)), Older()], policy="personal")
    h = md.history("2330.TW", date(2026, 10, 1), date(2026, 11, 11))
    assert h.source == "twse-openapi+older" and not h.is_demo  # the archived rows' own source
    assert h.candles[-1].c == D(2395) and len(h.candles) > 20


def test_unannounced_ex_date_is_kept_and_real_amounts_win(engine):
    from forliosa.marketdata.base import BaseProvider, DividendEvent
    from forliosa.models import MarketEvent

    with Session(engine) as db:
        db.add(MarketEvent(key="k", symbol="00878.TW", date=date(2026, 11, 17), type="ex_dividend", title="除息",
                           detail="金額尚未公告", data={"cash": None, "stock_ratio": None}, source="twse-openapi"))
        db.commit()
    archive = ArchiveProvider("personal", session_fn=lambda: Session(engine))
    only = MarketData([archive, DemoProvider()], policy="personal").dividends("00878.TW")
    assert [(e.ex_dividend_date, e.cash_dividend) for e in only.value] == [(date(2026, 11, 17), D(0))]

    class Announced(BaseProvider):
        name = "finmind"

        def dividends(self, symbol):
            return [DividendEvent(symbol, 2026, "2026Q3", D("0.4"), D(0), date(2026, 11, 17), date(2026, 12, 12))]

    both = MarketData([archive, Announced(), DemoProvider()], policy="personal").dividends("00878.TW")
    assert [(e.cash_dividend, e.payment_date) for e in both.value] == [(D("0.4"), date(2026, 12, 12))]
