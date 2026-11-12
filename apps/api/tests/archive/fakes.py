"""A fake HttpFetcher serving the trimmed live responses in tests/archive/fixtures (no network)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

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
    "/t187ap41_O": "tpex_t187ap41_o_live_20261112.json",
    "/mopsfin_t187ap06_O_ci": "tpex_t187ap06_o_ci_live_20261112.json",
    "/mopsfin_187ap17_O": "tpex_t187ap17_o_live_20261112.json",
    "/fund/T86": "twse_web_t86_live_20261111.json",
    "/fund/MI_QFIIS": "twse_web_mi_qfiis_live_20261111.json",
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
        raise ProviderUnavailable(f"no fixture for {url}")
