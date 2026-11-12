"""Real data from Sinotrade/shioaji-data (raw.githubusercontent.com).

``v1/manifest.json`` is read first; every other path comes from it, and downloads are cached on
disk under their manifest sha256 (``var/cache/shioaji-data/files/<sha256>.json``).

Licensing: official fields (company basics, daily close & market cap, monthly revenue, quarterly
statements) are 政府資料開放授權條款第 1 版 — attribution required. AI-researched fields
(summary, chain stage, themes, relations) are "待定" (license pending): they are exposed with
an explicit source attribution string in ``data_sources``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from forliosa.marketdata.base import (
    BaseProvider,
    InstrumentInfo,
    InstrumentProfile,
    ProviderUnavailable,
    QuarterFundamentals,
    QuoteData,
    RevenueRow,
    ValuationInputs,
    code_of_symbol,
    market_of_symbol,
    parse_decimal,
    tw_symbol,
)
from forliosa.marketdata.catalog import ETF_CODES
from forliosa.marketdata.http import DiskCache, HttpFetcher, sha256_hex
from forliosa.timeutil import market_close_dt

log = logging.getLogger(__name__)

SOURCE_OFFICIAL = (
    "shioaji-data：公司基本資料、每日收盤與市值（臺灣證券交易所、證券櫃檯買賣中心；政府資料開放授權條款第 1 版）"
)
SOURCE_FINANCIALS = "shioaji-data：月營收、季財報（公開資訊觀測站；政府資料開放授權條款第 1 版）"
SOURCE_RESEARCH = "shioaji-data 公司研究：業務簡介、產業鏈位置、題材（AI 整理並交叉核對，授權待定）"

MANIFEST_TTL_SECONDS = 600


def pct_to_fraction(value: object) -> Decimal | None:
    """shioaji-data percentages are in percent units (34.79 -> 0.3479)."""
    d = parse_decimal(value)
    return None if d is None else d / Decimal(100)


def parse_cards(cards: list[dict[str, Any]]) -> list[InstrumentInfo]:
    out: list[InstrumentInfo] = []
    for c in cards:
        code = str(c.get("code") or "").strip()
        market_raw = str(c.get("market") or "").lower()
        if not code or market_raw not in ("twse", "tpex"):
            continue
        market = "TWSE" if market_raw == "twse" else "TPEX"
        industry = (c.get("industry") or {}).get("l0_name") if isinstance(c.get("industry"), dict) else None
        stage = c.get("chain_stage")
        stage_name = stage.get("stage_name") if isinstance(stage, dict) else None
        aliases = tuple(a for a in (c.get("english_short"),) if a)
        out.append(InstrumentInfo(
            symbol=tw_symbol(code, market), code=code, name=str(c.get("name") or code), market=market,
            type="etf" if code in ETF_CODES else "stock", currency="TWD", industry=industry,
            summary=c.get("summary_short"), chain_stage=stage_name, aliases=aliases, source="shioaji-data",
        ))
    return out


def parse_daily(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``market/daily.json`` -> {code: {"close": Decimal, "date": date, "market_cap": Decimal, "shares": int}}."""
    quotes = doc.get("quotes")
    if not isinstance(quotes, dict):
        raise ProviderUnavailable("shioaji-data market/daily.json 格式不符（缺少 quotes）")
    out: dict[str, dict[str, Any]] = {}
    for code, q in quotes.items():
        if not isinstance(q, dict):
            continue
        close = parse_decimal(q.get("close"))
        d = q.get("date")
        if close is None or not d:
            continue
        out[str(code)] = {
            "close": close,
            "date": date.fromisoformat(str(d)),
            "market_cap": parse_decimal(q.get("market_cap_twd")),
            "shares": int(q["shares"]) if isinstance(q.get("shares"), int | float) else None,
        }
    return out


def parse_monthly_revenue(doc: dict[str, Any]) -> list[RevenueRow]:
    rows = []
    for r in doc.get("monthly_revenue") or []:
        rev = parse_decimal(r.get("revenue_thousand_twd"))
        if rev is None or not r.get("period"):
            continue
        ytd = parse_decimal(r.get("ytd_thousand_twd"))
        rows.append(RevenueRow(
            period=str(r["period"]),
            revenue=int(rev),
            yoy_pct=pct_to_fraction(r.get("yoy_pct")),
            mom_pct=pct_to_fraction(r.get("mom_pct")),
            ytd=int(ytd) if ytd is not None else None,
            ytd_yoy_pct=pct_to_fraction(r.get("ytd_yoy_pct")),
        ))
    rows.sort(key=lambda r: r.period)
    return rows


def _column(table: dict[str, list], *needles: str) -> list | None:
    for key, values in table.items():
        if all(n in key for n in needles):
            return values
    return None


def parse_quarter_fundamentals(doc: dict[str, Any]) -> list[QuarterFundamentals]:
    """Quarterly basic EPS (income_quarter) and book value per share (balance) by period."""
    st = doc.get("statements") or {}
    periods = st.get("periods") or []
    income = st.get("income_quarter") or {}
    balance = st.get("balance") or {}
    eps_col = _column(income, "基本每股盈餘") or _column(income, "每股盈餘") or []
    bvps_col = _column(balance, "每股參考淨值") or []
    out = []
    for i, period in enumerate(periods):
        eps = parse_decimal(eps_col[i]) if i < len(eps_col) else None
        bvps = parse_decimal(bvps_col[i]) if i < len(bvps_col) else None
        if eps is None and bvps is None:
            continue
        out.append(QuarterFundamentals(str(period), eps, bvps))
    return out


def parse_theme_names(themes: list[dict[str, Any]]) -> dict[str, str]:
    return {t["id"]: t.get("name") or t["id"] for t in themes if isinstance(t, dict) and t.get("id")}


class ShioajiDataProvider(BaseProvider):
    name = "shioaji-data"
    is_demo = False

    def __init__(self, base_url: str, cache_dir: Path, fetcher: HttpFetcher | None = None):
        self.base_url = base_url.rstrip("/")
        self.cache = DiskCache(Path(cache_dir) / "shioaji-data")
        self.fetcher = fetcher or HttpFetcher()
        self._lock = threading.Lock()
        self._manifest: dict[str, Any] | None = None
        self._manifest_at = 0.0
        self._parsed: dict[str, Any] = {}  # sha256 -> parsed object

    # -- raw access ----------------------------------------------------------------------------
    def manifest(self) -> dict[str, Any]:
        with self._lock:
            if self._manifest is not None and time.monotonic() - self._manifest_at < MANIFEST_TTL_SECONDS:
                return self._manifest
        try:
            raw = self.fetcher.get_bytes(f"{self.base_url}/v1/manifest.json")
            doc = json.loads(raw)
            self.cache.write("meta", "manifest", raw)
        except (ProviderUnavailable, ValueError) as exc:
            cached = self.cache.read("meta", "manifest")
            if cached is None:
                raise ProviderUnavailable(f"shioaji-data manifest 無法取得：{exc}") from exc
            log.warning("shioaji-data manifest unreachable, using cached copy: %s", exc)
            doc = json.loads(cached)
        with self._lock:
            self._manifest, self._manifest_at = doc, time.monotonic()
        return doc

    def _load(self, path: str, sha: str | None) -> Any:
        """Fetch a manifest-listed file, using the sha256-keyed disk cache."""
        if sha and sha in self._parsed:
            return self._parsed[sha]
        raw = self.cache.read("files", sha) if sha else None
        if raw is None:
            raw = self.fetcher.get_bytes(f"{self.base_url}/{path}")
            actual = sha256_hex(raw)
            if sha and actual != sha:
                log.warning("shioaji-data %s sha256 mismatch (manifest %s, got %s)", path, sha, actual)
            self.cache.write("files", actual, raw)
            sha = sha or actual
        doc = json.loads(raw)
        if sha:
            with self._lock:
                if len(self._parsed) > 64:
                    self._parsed.clear()
                self._parsed[sha] = doc
        return doc

    def _file(self, key: str) -> Any:
        meta = (self.manifest().get("files") or {}).get(key)
        if not meta:
            raise ProviderUnavailable(f"shioaji-data manifest 沒有 {key}")
        return self._load(meta["path"], meta.get("sha256"))

    def _company(self, code: str) -> dict[str, Any] | None:
        meta = (self.manifest().get("companies") or {}).get(code)
        return self._load(meta["path"], meta.get("sha256")) if meta else None

    def _financials(self, code: str) -> dict[str, Any] | None:
        meta = (self.manifest().get("financials") or {}).get(code)
        return self._load(meta["path"], meta.get("sha256")) if meta else None

    def _daily(self) -> dict[str, dict[str, Any]]:
        meta = (self.manifest().get("files") or {}).get("tw/market") or {}
        sha = meta.get("sha256")
        key = f"daily:{sha}"
        if key in self._parsed:
            return self._parsed[key]
        parsed = parse_daily(self._file("tw/market"))
        self._remember_closes(parsed)
        self._parsed[key] = parsed
        return parsed

    # -- previous-close snapshots (daily.json only carries the latest close) --------------------
    def _remember_closes(self, parsed: dict[str, dict[str, Any]]) -> None:
        by_day: dict[date, dict[str, str]] = {}
        for code, q in parsed.items():
            by_day.setdefault(q["date"], {})[code] = str(q["close"])
        for d, closes in by_day.items():
            if self.cache.read("closes", d.isoformat()) is None:
                self.cache.write("closes", d.isoformat(), json.dumps(closes).encode())

    def _prev_close(self, code: str, before: date) -> Decimal | None:
        folder = self.cache.root / "closes"
        try:
            days = sorted((p.stem for p in folder.glob("*.json")), reverse=True)
        except OSError:
            return None
        for ds in days:
            if ds >= before.isoformat():
                continue
            raw = self.cache.read("closes", ds)
            if raw:
                v = json.loads(raw).get(code)
                if v is not None:
                    return Decimal(v)
        return None

    # -- provider API --------------------------------------------------------------------------
    def instruments(self) -> list[InstrumentInfo] | None:
        return parse_cards(self._file("tw/cards"))

    def _theme_names(self) -> dict[str, str]:
        key = "theme-names"
        if key not in self._parsed:
            self._parsed[key] = parse_theme_names(self._file("tw/themes"))
        return self._parsed[key]

    def profile(self, symbol: str) -> InstrumentProfile | None:
        if market_of_symbol(symbol) == "US":
            return None
        code = code_of_symbol(symbol)
        company = self._company(code)
        if company is None:
            return None
        names = self._theme_names()
        theme_ids = [t.get("theme") for t in company.get("themes") or [] if isinstance(t, dict)]
        themes = tuple(dict.fromkeys(names.get(t, t) for t in theme_ids if t))
        stage = company.get("chain_stage")
        daily = self._daily().get(code) or {}
        sources = [SOURCE_OFFICIAL]
        if company.get("summary_short") or company.get("summary_long") or themes or stage:
            sources.append(SOURCE_RESEARCH)
        return InstrumentProfile(
            symbol=symbol,
            summary=company.get("summary_long") or company.get("summary_short"),
            chain_stage=stage.get("stage_name") if isinstance(stage, dict) else None,
            themes=themes,
            shares_outstanding=daily.get("shares"),
            market_cap=daily.get("market_cap"),
            data_sources=tuple(sources),
        )

    def quotes(self, symbols: list[str]) -> dict[str, QuoteData] | None:
        tw = [s for s in symbols if market_of_symbol(s) != "US"]
        if not tw:
            return {}
        daily = self._daily()
        out = {}
        for s in tw:
            q = daily.get(code_of_symbol(s))
            if not q:
                continue
            out[s] = QuoteData(
                symbol=s, price=q["close"], prev_close=self._prev_close(code_of_symbol(s), q["date"]),
                as_of=market_close_dt(q["date"]), trade_date=q["date"], source="shioaji-data",
            )
        return out

    def latest_close(self, symbol: str) -> tuple[date, Decimal] | None:
        if market_of_symbol(symbol) == "US":
            return None
        q = self._daily().get(code_of_symbol(symbol))
        return (q["date"], q["close"]) if q else None

    def monthly_revenue(self, symbol: str) -> list[RevenueRow] | None:
        if market_of_symbol(symbol) == "US":
            return None
        doc = self._financials(code_of_symbol(symbol))
        return parse_monthly_revenue(doc) if doc else None

    def valuation_inputs(self, symbol: str) -> ValuationInputs | None:
        if market_of_symbol(symbol) == "US":
            return None
        doc = self._financials(code_of_symbol(symbol))
        if not doc:
            return None
        quarters = parse_quarter_fundamentals(doc)
        return ValuationInputs(symbol, tuple(quarters), is_demo=False, source="shioaji-data") if quarters else None

    def statements(self, symbol: str) -> dict[str, Any] | None:
        """Raw quarterly statements (``periods``, ``income_quarter``, ``income_ytd``, ``balance``,
        ``cash_flow_quarter`` …; thousand NT$), official MOPS data under the open-data licence."""
        if market_of_symbol(symbol) == "US":
            return None
        doc = self._financials(code_of_symbol(symbol))
        st = doc.get("statements") if doc else None
        return st if st and st.get("periods") else None

    def release_info(self) -> dict[str, Any]:
        m = self.manifest()
        return {"release_id": m.get("release_id"), "built_at": m.get("built_at"),
                "fetched": datetime.now().isoformat(timespec="seconds")}
