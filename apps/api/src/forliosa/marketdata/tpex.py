"""TPEx (上櫃) providers.

Field names verified from twjackysu/TWSEMCPServer:

* OpenAPI ``/openapi/v1/tpex_mainboard_daily_close_quotes`` (latest day) — keys ``Date`` (ROC
  "1150929"), ``SecuritiesCompanyCode``, ``CompanyName``, ``Close``, ``Change``, ``Open``, ``High``,
  ``Low``, ``Average``, ``TradingShares``, ``TransactionAmount``, ``TransactionNumber``
  (tests/contract/test_otc_api.py, tests/unit/test_free_sources_unit.py).

Only the OpenAPI (``www.tpex.org.tw/openapi``) is used: the TPEx website terms (§5) forbid automated
downloads from the website without consent, so the former ``peQryDate`` website call was removed.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from forliosa.marketdata.base import (
    BaseProvider,
    ProviderUnavailable,
    QuoteData,
    market_of_symbol,
    parse_decimal,
    parse_int,
    parse_tw_date,
    tw_symbol,
)
from forliosa.marketdata.http import HttpFetcher
from forliosa.timeutil import market_close_dt

OPENAPI_BASE = "https://www.tpex.org.tw/openapi/v1"


def parse_daily_close_quotes(rows: list[dict[str, Any]]) -> dict[str, QuoteData]:
    out: dict[str, QuoteData] = {}
    for r in rows:
        code = str(r.get("SecuritiesCompanyCode") or "").strip()
        close = parse_decimal(r.get("Close"))
        d = parse_tw_date(r.get("Date"))
        if not code or close is None or d is None:
            continue
        change = parse_decimal(r.get("Change"))
        symbol = tw_symbol(code, "TPEX")
        out[symbol] = QuoteData(
            symbol=symbol, price=close, prev_close=(close - change) if change is not None else None,
            open=parse_decimal(r.get("Open")), high=parse_decimal(r.get("High")), low=parse_decimal(r.get("Low")),
            volume=parse_int(r.get("TradingShares")), as_of=market_close_dt(d), trade_date=d,
            source="tpex-openapi",
        )
    return out


class TpexOpenApiProvider(BaseProvider):
    name = "tpex_openapi"
    is_demo = False
    CACHE_SECONDS = 600

    def __init__(self, fetcher: HttpFetcher | None = None):
        self.fetcher = fetcher or HttpFetcher()
        self._cache: dict[str, tuple[float, Any]] = {}

    def _daily(self) -> dict[str, QuoteData]:
        hit = self._cache.get("daily")
        if hit and time.monotonic() - hit[0] < self.CACHE_SECONDS:
            return hit[1]
        # tpex_mainboard_quotes (≈ 0.4 MB, stocks only) has the same keys as
        # tpex_mainboard_daily_close_quotes (≈ 5 MB incl. warrants, archived by forliosa.archive).
        rows = self.fetcher.get_json(f"{OPENAPI_BASE}/tpex_mainboard_quotes")
        if not isinstance(rows, list):
            raise ProviderUnavailable("TPEx daily close quotes 格式不符")
        parsed = parse_daily_close_quotes(rows)
        self._cache["daily"] = (time.monotonic(), parsed)
        return parsed

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        wanted = [s for s in symbols if market_of_symbol(s) == "TPEX"]
        if not wanted:
            return {}
        daily = self._daily()
        return {s: daily[s] for s in wanted if s in daily}

    def ex_rights_on(self, symbols: list[str], d) -> dict[str, tuple[Decimal, Decimal]]:
        """tpex_exright_prepost: ExRrightsExDividendDate, CashDividend ("尚未公告" when unknown), StockDividendRatio."""
        wanted = {s for s in symbols if market_of_symbol(s) == "TPEX"}
        if not wanted:
            return {}
        hit = self._cache.get("exright")
        if hit and time.monotonic() - hit[0] < self.CACHE_SECONDS:
            rows = hit[1]
        else:
            rows = self.fetcher.get_json(f"{OPENAPI_BASE}/tpex_exright_prepost")
            if not isinstance(rows, list):
                raise ProviderUnavailable("TPEx exright_prepost 格式不符")
            self._cache["exright"] = (time.monotonic(), rows)
        out = {}
        for r in rows:
            sym = tw_symbol(str(r.get("SecuritiesCompanyCode") or "").strip(), "TPEX")
            if sym in wanted and parse_tw_date(r.get("ExRrightsExDividendDate")) == d:
                cash = parse_decimal(r.get("CashDividend")) or Decimal(0)
                ratio = parse_decimal(r.get("StockDividendRatio")) or Decimal(0)
                if cash or ratio:
                    out[sym] = (cash, ratio)
        return out
