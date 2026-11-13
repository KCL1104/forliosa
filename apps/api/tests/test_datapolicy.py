"""DATA_POLICY: commercial uses only government open data; non-commercial sources are labelled."""

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.config import Settings
from forliosa.datapolicy import allowed, attributions, is_commercial_source, label, labels, provider_allowed, tagged
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
    # the TWSE website and MIS are never allowed, in any mode
    assert not allowed("twse-web", "personal") and not allowed("twse-mis+shioaji-data", "personal")
    assert not provider_allowed("finmind", "commercial") and provider_allowed("archive", "commercial")


def test_attribution_names_agency_dataset_year_and_licence(monkeypatch):
    import forliosa.timeutil as tu

    monkeypatch.setattr(tu, "today_taipei", lambda: date(2026, 11, 12))
    ogdl = "依政府資料開放授權條款第 1 版"
    assert label("twse-openapi/valuation") == f"臺灣證券交易所〈上市個股日本益比、殖利率及股價淨值比〉（2026），{ogdl}"
    assert labels(tagged("archive+tpex_openapi", "price")) == [
        "Forliosa 自建存檔（證交所、櫃買中心開放資料）", f"證券櫃檯買賣中心〈上櫃股票行情〉（2026），{ogdl}"]
    assert label("demo/price") == "示範資料（模擬）" and label("ledger") == "帳本紀錄"
    assert label("shioaji-data").startswith("永豐金證券 shioaji-data") and label("shioaji-data").endswith("第 1 版")
    meta = attributions("commercial")
    assert meta["notice"][1] == "政府資料開放授權條款：https://data.gov.tw/license"
    keys = {d["key"] for d in meta["datasets"]}
    assert {"tpex-openapi/institutional", "tpex-openapi/foreign_holding", "twse-openapi/news",
            "twse-openapi/fund", "tdcc-opendata/distribution"} <= keys
    assert all(d["commercial"] for d in meta["datasets"])
    assert any(d["key"] == "finmind" and not d["commercial"] for d in attributions("personal")["datasets"])


def test_fetcher_refuses_urls_outside_the_allowlist():
    from forliosa.marketdata.base import ProviderUnavailable
    from forliosa.marketdata.http import HttpFetcher, url_allowed

    assert url_allowed("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    assert url_allowed("https://www.tpex.org.tw/openapi/v1/tpex_3insti_qfii")
    for url in ("https://www.twse.com.tw/rwd/zh/fund/T86", "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
                "https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate", "https://mops.twse.com.tw/mops/"):
        assert not url_allowed(url)
        with pytest.raises(ProviderUnavailable, match="白名單"):
            HttpFetcher(retries=0).get_json(url)


def test_commercial_policy_builds_no_non_commercial_provider():
    every = "twse_mis,archive,twse_openapi,tpex_openapi,shioaji_data,finmind,demo"
    names = [p.name for p in build_providers(Settings(data_policy="commercial", market_data_providers=every))]
    assert "finmind" not in names and "twse_mis" not in names
    assert names[:3] == ["archive", "twse_openapi", "tpex_openapi"]
    # personal: FinMind only when listed explicitly; the MIS provider no longer exists in any mode
    personal = [p.name for p in build_providers(Settings(data_policy="personal", market_data_providers=every))]
    assert "finmind" in personal and "twse_mis" not in personal
    default = [p.name for p in build_providers(Settings(_env_file=None, data_policy="personal"))]
    assert "finmind" not in default
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


def test_conditional_taifex_datasets_are_gated_under_commercial():
    from forliosa.datapolicy import DATASETS, dataset_served

    conditional = {k for k, d in DATASETS.items() if d.license_status == "conditional"}
    assert {"taifex-openapi/futures_daily", "taifex-openapi/options_daily", "taifex-openapi/fx",
            "taifex-openapi/large_traders_options"} <= conditional
    assert all(k.startswith("taifex-openapi/") for k in conditional)
    for key in conditional:
        assert not dataset_served(key, "commercial", confirmed=False)
        assert dataset_served(key, "commercial", confirmed=True)
        assert dataset_served(key, "personal", confirmed=False)
    for key in ("taifex-openapi/put_call_ratio", "taifex-openapi/institutional_futures", "twse-openapi/index"):
        assert dataset_served(key, "commercial", confirmed=False)
    assert label("taifex-openapi/fx").startswith("臺灣期貨交易所〈每日外幣參考匯率〉（")
    assert is_commercial_source("taifex-openapi")


def test_central_bank_fx_is_open_data_with_its_attribution():
    from forliosa.datapolicy import DATASETS, allowed_sources, attribution, dataset_served

    ds = DATASETS["cbc-opendata/fx"]
    assert (ds.agency, ds.title, ds.license_status, ds.basis) == (
        "中央銀行", "銀行間新臺幣對美元收盤匯率", "ogdl", "data.gov.tw 7232")
    assert attribution(ds, 2026) == "中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版"
    assert label("cbc-opendata/fx") == attribution(ds)
    assert label("cbc-opendata").startswith("中央銀行〈開放資料〉（")
    assert is_commercial_source("cbc-opendata") and "cbc-opendata" in allowed_sources("commercial")
    assert dataset_served("cbc-opendata/fx", "commercial", confirmed=False)


def test_fetcher_allows_taifex_data_endpoints_only():
    from forliosa.marketdata.http import DEFAULT_LIMITER, url_allowed

    assert url_allowed("https://openapi.taifex.com.tw/v1/PutCallRatio")
    assert not url_allowed("https://openapi.taifex.com.tw/swagger.json")
    assert not url_allowed("https://www.taifex.com.tw/cht/3/futDailyMarketReport")
    assert DEFAULT_LIMITER.interval_for("openapi.taifex.com.tw") == 2.0
