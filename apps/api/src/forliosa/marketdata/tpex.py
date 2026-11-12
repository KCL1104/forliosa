"""TPEx (上櫃) providers.

Field names verified from twjackysu/TWSEMCPServer:

* OpenAPI ``/openapi/v1/tpex_mainboard_daily_close_quotes`` (latest day) — keys ``Date`` (ROC
  "1150929"), ``SecuritiesCompanyCode``, ``CompanyName``, ``Close``, ``Change``, ``Open``, ``High``,
  ``Low``, ``Average``, ``TradingShares``, ``TransactionAmount``, ``TransactionNumber``
  (tests/contract/test_otc_api.py, tests/unit/test_free_sources_unit.py).
* Website ``/www/zh-tw/afterTrading/peQryDate?response=json`` (P/E, yield, P/B; any date) —
  ``tables[0].fields`` = 股票代號, 公司名稱, 本益比, 每股股利, 股利年度, 殖利率(%), 股價淨值比,
  財報年/季 (from 2025-01-02); "N/A" when missing (sources/tpex/pe_qry_date.py). Live response
  (2026-11-11): top-level ``date`` "20261111"; the table also carries ``date`` "115/11/11".
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
PE_QRY_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate"


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


def parse_pe_qry_date(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise ProviderUnavailable("TPEx peQryDate 回應沒有 tables")
    if not tables or not tables[0].get("data"):
        return {}
    fields = [str(f).strip() for f in tables[0].get("fields") or []]
    try:
        col = {name: fields.index(name) for name in ("股票代號", "本益比", "殖利率(%)", "股價淨值比")}
    except ValueError as exc:
        raise ProviderUnavailable(f"TPEx peQryDate 欄位改變：{fields}") from exc
    served = parse_tw_date(payload.get("date")) or parse_tw_date(tables[0].get("date"))
    out = {}
    for row in tables[0]["data"]:
        code = str(row[col["股票代號"]]).strip()
        dy = parse_decimal(row[col["殖利率(%)"]])
        out[code] = {
            "date": served,
            "per": parse_decimal(row[col["本益比"]]),
            "pbr": parse_decimal(row[col["股價淨值比"]]),
            "dividend_yield": dy / 100 if dy is not None else None,
        }
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

    def market_valuation_ratios(self) -> dict[str, dict[str, Any]]:
        """Whole market, latest day (the archive stores it daily; not the per-symbol facade method)."""
        return parse_pe_qry_date(self.fetcher.get_json(PE_QRY_URL, params={"response": "json"}))
