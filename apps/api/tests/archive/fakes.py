"""A fake HttpFetcher serving the trimmed live responses in tests/archive/fixtures (no network)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from forliosa.marketdata.base import ProviderUnavailable
from forliosa.timeutil import TAIPEI

FIX = Path(__file__).parent / "fixtures"

ROUTES = {
    "/exchangeReport/STOCK_DAY_ALL": "twse_stock_day_all_live_20261112.json",
    "/exchangeReport/BWIBBU_ALL": "twse_bwibbu_all_live_20261112.json",
    "/exchangeReport/TWT84U": "twse_twt84u_live_20261112.json",
    "/exchangeReport/MI_MARGN": "twse_mi_margn_live_20261112.json",
    "/exchangeReport/TWT48U_ALL": "twse_twt48u_all_live_20261112.json",
    "/announcement/notice": "twse_notice_live_20261112.json",
    "/announcement/punish": "twse_punish_live_20261112.json",
    "/opendata/t187ap04_L": "twse_t187ap04_l_live_20261112.json",
    "/opendata/t187ap05_L": "twse_t187ap05_l_live_20261112.json",
    "/holidaySchedule/holidaySchedule": "twse_holiday_schedule_live_20261112.json",
    "/news/newsList": "twse_news_list_live_20261112.json",
    "/opendata/t187ap47_L": "twse_t187ap47_l_live_20261112.json",
    "/opendata/t187ap41_L": "twse_t187ap41_l_live_20261112.json",
    "/opendata/t187ap06_L_ci": "twse_t187ap06_l_ci_live_20261112.json",
    "/opendata/t187ap07_L_ci": "twse_t187ap07_l_ci_live_20261112.json",
    "/opendata/t187ap17_L": "twse_t187ap17_l_live_20261112.json",
    "/tpex_mainboard_daily_close_quotes": "tpex_daily_close_quotes_live_20261112.json",
    "/tpex_mainboard_peratio_analysis": "tpex_peratio_analysis_live_20261112.json",
    "/tpex_mainboard_margin_balance": "tpex_margin_balance_live_20261112.json",
    "/tpex_3insti_daily_trading": "tpex_3insti_daily_trading_live_20261112.json",
    "/tpex_3insti_qfii": "tpex_3insti_qfii_live_20261112.json",
    "/tpex_exright_prepost": "tpex_exright_prepost_live_20261112.json",
    "/tpex_trading_warning_information": "tpex_trading_warning_live_20261112.json",
    "/tpex_disposal_information": "tpex_disposal_live_20261112.json",
    "/mopsfin_t187ap04_O": "tpex_t187ap04_o_live_20261112.json",
    "/mopsfin_t187ap05_O": "tpex_t187ap05_o_live_20261112.json",
    "/t187ap41_O": "tpex_t187ap41_o_live_20261112.json",
    "/mopsfin_t187ap06_O_ci": "tpex_t187ap06_o_ci_live_20261112.json",
    "/mopsfin_187ap17_O": "tpex_t187ap17_o_live_20261112.json",
    "/exchangeReport/MI_INDEX": "twse_mi_index_live_20261112.json",
    "/indicesReport/MFI94U": "twse_mfi94u_live_20261112.json",
    "/opendata/t187ap45_L": "twse_t187ap45_l_live_20261112.json",
    "/opendata/t187ap03_L": "twse_t187ap03_l_live_20261112.json",
    "/opendata/twtazu_od": "twse_twtazu_od_live_20261112.json",
    "/opendata/t187ap09_L": "twse_t187ap09_l_live_20261112.json",
    "/tpex_exright_daily": "tpex_exright_daily_live_20261112.json",
    "/tpex_index": "tpex_index_live_20261112.json",
    "/tpex_reward_index": "tpex_reward_index_live_20261112.json",
    "/mopsfin_t187ap03_O": "tpex_t187ap03_o_live_20261112.json",
    "/mopsfin_t187ap07_O_ins": "tpex_t187ap07_o_ins_live_20261112.json",
    "/mopsfin_t187ap07_O_mim": "tpex_t187ap07_o_mim_live_20261112.json",
    "/mopsfin_t187ap06_O_bd": "tpex_t187ap06_o_bd_live_20261112.json",
}

# TAIFEX OpenAPI (fetched as bytes: JSON or CSV). DailyForeignExchangeRates is the CSV variant Cloudflare served.
TAIFEX_ROUTES = {
    "/DailyMarketReportFut": "taifex_daily_market_report_fut_live_20261112.json",
    "/DailyMarketReportOpt": "taifex_daily_market_report_opt_live_20261112.json",
    "/MarketDataOfMajorInstitutionalTradersGeneralBytheDate": "taifex_institutional_general_live_20261112.json",
    "/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate":
        "taifex_institutional_fut_opt_live_20261112.json",
    "/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate":
        "taifex_institutional_futures_live_20261112.json",
    "/MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheDate":
        "taifex_institutional_options_live_20261112.json",
    "/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate":
        "taifex_institutional_calls_puts_live_20261112.json",
    "/OpenInterestOfLargeTradersFutures": "taifex_large_traders_futures_live_20261112.json",
    "/OpenInterestOfLargeTradersOptions": "taifex_large_traders_options_live_20261112.json",
    "/PutCallRatio": "taifex_put_call_ratio_live_20261112.json",
    "/DailyForeignExchangeRates": "taifex_fx_rates_live_20261112.csv",
    "/FinalSettlementPrice": "taifex_final_settlement_live_20261112.json",
    "/IndexFuturesAndOptionsMargining": "taifex_margins_index_live_20261112.json",
    "/SingleStockFuturesMargining": "taifex_margins_stock_live_20261112.json",
    "/SingleStockFuturesETFMargining": "taifex_margins_etf_live_20261112.json",
    "/SSFLists": "taifex_ssf_lists_live_20261112.json",
    "/SSOLists": "taifex_sso_lists_live_20261112.json",
}

# Archive "now": 2026-11-12 10:00 Taipei (MI_MARGN then still holds 2026-11-11's balances).
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=TAIPEI)


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeFetcher:
    def __init__(self):
        self.calls: list[str] = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append(url)
        for suffix, name in ROUTES.items():
            if url.endswith(suffix):
                return load(name)
        raise ProviderUnavailable(f"no fixture for {url}")

    def get_bytes(self, url, params=None, headers=None):
        self.calls.append(url)
        if "tdcc" in url:
            return (FIX / "tdcc_1-5_live_20261106.csv").read_bytes()
        if "taifex" in url:
            for suffix, name in TAIFEX_ROUTES.items():
                if url.endswith(suffix):
                    return (FIX / name).read_bytes()
        raise ProviderUnavailable(f"no fixture for {url}")


# SEC EDGAR (trimmed live responses, 2026-11-12): AAPL companyfacts + submissions, NVDA companyfacts (with the
# EPS and share counts around its 2021 and 2024 stock splits), a ticker subset.
SEC_FACTS = {320193: "sec_companyfacts_aapl_live_20261112.json", 1045810: "sec_companyfacts_nvda_live_20261112.json"}
SEC_SUBMISSIONS = {320193: "sec_submissions_aapl_live_20261112.json"}


class FakeSecClient:
    """Stands in for ``forliosa.marketdata.sec.SecClient``: serves the fixtures, counts calls, can fail on demand.

    ``fail``: an exception raised by every call (e.g. ``HttpStatusError("data.sec.gov 回應 HTTP 403", 403)``).
    Companies without a fixture answer like SEC's 404 (``None``).
    """

    def __init__(self, fail: Exception | None = None, facts: dict[int, Any] | None = None):
        self.calls: list[str] = []
        self.fail = fail
        self.facts = facts or {}  # raw companyfacts by CIK, in place of the fixtures

    def _call(self, what: str) -> None:
        self.calls.append(what)
        if self.fail is not None:
            raise self.fail

    def tickers(self):
        self._call("tickers")
        return load("sec_company_tickers_live_20261112.json")

    def company_facts(self, cik: int):
        self._call(f"facts:{cik}")
        if cik in self.facts:
            return self.facts[cik]
        return load(SEC_FACTS[cik]) if cik in SEC_FACTS else None

    def submissions(self, cik: int):
        self._call(f"submissions:{cik}")
        return load(SEC_SUBMISSIONS[cik]) if cik in SEC_SUBMISSIONS else None
