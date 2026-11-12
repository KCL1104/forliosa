"""SEC EDGAR: ticker -> CIK map, XBRL company facts and submissions (US fundamentals and filings).

Sources (US government public data: "All Government-created content on sec.gov and EDGAR public filing content
are free to access and reuse", SEC Webmaster FAQ):

* ``www.sec.gov/files/company_tickers.json`` — ``{"0": {"cik_str": 320193, "ticker": "AAPL", "title": …}, …}``
* ``data.sec.gov/api/xbrl/companyfacts/CIK##########.json`` — every XBRL fact a company filed, per taxonomy, tag
  and unit: ``{"start"?, "end", "val", "accn", "fy", "fp", "form", "filed", "frame"?}``. ``fy`` / ``fp`` are the
  *filing's* fiscal year and period, so a comparative figure in a later filing carries the later filing's labels.
* ``data.sec.gov/submissions/CIK##########.json`` — the filing index; ``filings.recent`` holds at least a year
  (or 1,000 filings) as parallel arrays (``form``, ``filingDate``, ``reportDate``, ``accessionNumber``, ``items``,
  ``primaryDocument`` …).

Fair access: ≤ 10 requests / s per requester and a declared User-Agent with a contact e-mail. Forliosa sends
``Forliosa/1.0 <SEC_CONTACT_EMAIL>`` (the address only ever comes from the environment) and shares one limiter
for all of sec.gov (``marketdata.http.DEFAULT_LIMITER``, ≤ 4 / s per process). A 403 / 429 / redirect is a
refusal: callers stop and never retry around it.

This module only fetches and parses (no database); ``forliosa.services.sec`` caches and serves.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from forliosa.marketdata.http import HttpFetcher, HttpStatusError

SOURCE = "sec-edgar"
USER_AGENT_PRODUCT = "Forliosa/1.0"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{doc}"

_EMAIL = re.compile(r"^[^\s@<>\"'(),;:]+@[^\s@<>\"'(),;:]+\.[^\s@<>\"'(),;:]+$")


def valid_contact(email: str | None) -> bool:
    """A plain address (no spaces, brackets or header separators): it goes into a request header."""
    return bool(email) and len(email or "") <= 254 and _EMAIL.match(email or "") is not None


def user_agent(email: str) -> str:
    return f"{USER_AGENT_PRODUCT} {email}"


def sec_ticker(symbol: str) -> str:
    """Forliosa symbol -> SEC ticker spelling (``BRK.B`` -> ``BRK-B``)."""
    return symbol.strip().upper().replace(".", "-")


class SecClient:
    """The three SEC datasets over HTTP. Never prints its User-Agent (it holds the contact e-mail)."""

    def __init__(self, email: str, timeout: float = 20.0, retries: int = 1, fetcher: HttpFetcher | None = None):
        if not valid_contact(email):
            raise ValueError("SEC_CONTACT_EMAIL 格式不符")
        self._fetcher = fetcher or HttpFetcher(timeout=timeout, retries=retries, user_agent=user_agent(email),
                                               backoff=1.0)

    def __repr__(self) -> str:  # keep the address out of logs and tracebacks
        return "SecClient()"

    def tickers(self) -> Any:
        return self._fetcher.get_json(TICKERS_URL)

    def company_facts(self, cik: int) -> dict[str, Any] | None:
        """``None`` when SEC has no XBRL facts for the company (HTTP 404)."""
        return self._optional(FACTS_URL.format(cik=cik))

    def submissions(self, cik: int) -> dict[str, Any] | None:
        return self._optional(SUBMISSIONS_URL.format(cik=cik))

    def _optional(self, url: str) -> dict[str, Any] | None:
        try:
            data = self._fetcher.get_json(url)
        except HttpStatusError as exc:
            if exc.status == 404:
                return None
            raise
        return data if isinstance(data, dict) else None


def is_refusal(exc: Exception) -> bool:
    """403 / 429 / a redirect from SEC: stop (fair-access block or undeclared tool), never work around it."""
    return isinstance(exc, HttpStatusError) and (exc.status in (403, 429) or 300 <= exc.status < 400)


# -- company_tickers.json ---------------------------------------------------------------------------------
def parse_tickers(raw: Any) -> list[dict[str, Any]]:
    rows = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        try:
            ticker = str(r["ticker"]).strip().upper()
            cik = int(r["cik_str"])
        except (KeyError, TypeError, ValueError):
            continue
        if ticker and ticker not in out:
            out[ticker] = {"ticker": ticker[:20], "cik": cik, "title": str(r.get("title") or "")[:200]}
    return list(out.values())


# -- companyfacts -----------------------------------------------------------------------------------------
# us-gaap tags per line item, highest priority first. A period takes the first tag that reports it, so a
# company that switched tags (Apple: SalesRevenueNet -> RevenueFromContractWithCustomerExcludingAssessedTax)
# still gets one continuous series.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"),
    "eps": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "liabilities_and_equity": ("LiabilitiesAndStockholdersEquity",),
    "equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "equity_total": ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"),
    "operating": ("NetCashProvidedByUsedInOperatingActivities",
                  "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    "investing": ("NetCashProvidedByUsedInInvestingActivities",
                  "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"),
    "financing": ("NetCashProvidedByUsedInFinancingActivities",
                  "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
}
INSTANT = frozenset({"total_assets", "total_liabilities", "liabilities_and_equity", "equity", "equity_total"})
# Flows whose quarterly value may be derived as a difference of year-to-date figures (cash flows in 10-Qs are
# year-to-date only; Q4 is the full year minus nine months). Per-share and average-share figures are not additive.
ADDITIVE = frozenset({"revenue", "gross_profit", "operating_income", "net_income", "operating", "investing",
                      "financing", "capex"})
UNIT = {"eps": "USD/shares", "diluted_shares": "shares"}
# Periodic reports only (8-Ks, registration statements and proxies also carry XBRL facts).
REPORT_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})
FACTS_YEARS = 12  # keep this many years of history
FACTS_VERSION = 1


def _tags() -> list[str]:
    return list(dict.fromkeys(t for tags in CONCEPTS.values() for t in tags))


def _unit_of(tag: str) -> str:
    for concept, tags in CONCEPTS.items():
        if tag in tags:
            return UNIT.get(concept, "USD")
    return "USD"


def trim_facts(raw: dict[str, Any], today: date) -> dict[str, Any]:
    """companyfacts -> the stored subset: our tags, periodic reports only, one row per period.

    Per period the **value** comes from the most recent filing (restatements win) and the **labels** (``fy``,
    ``fp``) from the earliest one, i.e. the report in which the period was the current period. Rows are
    ``[start | None, end, value, fy, fp, filed]`` (dates ISO; ``start`` is None for balance-sheet instants).
    """
    since = date(today.year - FACTS_YEARS, 1, 1).isoformat()
    gaap = ((raw.get("facts") or {}).get("us-gaap") or {}) if isinstance(raw, dict) else {}
    tags: dict[str, dict[str, list[list[Any]]]] = {}
    for tag in _tags():
        unit = _unit_of(tag)
        entries = ((gaap.get(tag) or {}).get("units") or {}).get(unit) or []
        latest: dict[tuple[str | None, str], dict[str, Any]] = {}
        first: dict[tuple[str | None, str], dict[str, Any]] = {}
        for e in entries:
            end, val = e.get("end"), e.get("val")
            if e.get("form") not in REPORT_FORMS or not end or end < since or not isinstance(val, int | float):
                continue
            key = (e.get("start"), end)
            filed = str(e.get("filed") or "")
            cur = latest.get(key)
            if cur is None or filed > str(cur.get("filed") or "") or (
                    filed == str(cur.get("filed") or "") and e.get("frame") and not cur.get("frame")):
                latest[key] = e
            old = first.get(key)
            if old is None or filed < str(old.get("filed") or ""):
                first[key] = e
        if latest:
            rows = [[k[0], k[1], latest[k]["val"], first[k].get("fy"), first[k].get("fp"),
                     latest[k].get("filed")] for k in sorted(latest, key=lambda k: (k[1], k[0] or ""))]
            tags[tag] = {unit: rows}
    return {"v": FACTS_VERSION, "tags": tags}


def shares_outstanding(raw: dict[str, Any]) -> tuple[int | None, date | None]:
    """The latest cover-page share count (dei:EntityCommonStockSharesOutstanding). Companies with several share
    classes report it per class (dimensional, so absent from companyfacts): then ``(None, None)``."""
    dei = ((raw.get("facts") or {}).get("dei") or {}) if isinstance(raw, dict) else {}
    rows = ((dei.get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}).get("shares") or []
    best = max((r for r in rows if r.get("end") and isinstance(r.get("val"), int | float)),
               key=lambda r: (r["end"], str(r.get("filed") or "")), default=None)
    if best is None:
        return None, None
    return int(best["val"]), date.fromisoformat(best["end"])


# -- summary: quarterly / annual tables -------------------------------------------------------------------
Key = tuple[date | None, date]


@dataclass
class _Series:
    values: dict[Key, Decimal] = field(default_factory=dict)
    labels: dict[Key, tuple[int | None, str | None]] = field(default_factory=dict)


@dataclass
class FiscalPeriod:
    """One column of the financials table: ``FY2026Q1`` (quarter) or ``FY2025`` (fiscal year)."""

    label: str
    fiscal_year: int
    quarter: int | None  # None for a fiscal year
    start: date
    end: date
    values: dict[str, Decimal | None]
    derived: set[str] = field(default_factory=set)  # line items computed from year-to-date differences


def _series(facts: dict[str, Any], concept: str) -> _Series:
    tags = facts.get("tags") or {}
    out = _Series()
    unit = UNIT.get(concept, "USD")
    for tag in CONCEPTS[concept]:
        for row in (tags.get(tag) or {}).get(unit) or []:
            try:
                start = date.fromisoformat(row[0]) if row[0] else None
                end = date.fromisoformat(row[1])
                val = Decimal(str(row[2]))
            except (TypeError, ValueError, IndexError, ArithmeticError):
                continue
            key = (start, end)
            if key not in out.values:  # a higher-priority tag already reported this period
                out.values[key] = val
                out.labels[key] = (row[3] if isinstance(row[3], int) else None, row[4] if len(row) > 4 else None)
    return out


def _fy_name(end: date, fy: int | None, fp: str | None) -> int:
    """The company's own fiscal-year number when the annual report gave one; otherwise the calendar year the fiscal
    year ends in (a 52/53-week year ending in the first days of January belongs to the previous year)."""
    if fy is not None and fp == "FY" and abs(fy - end.year) <= 1:
        return fy
    return end.year - 1 if end.month == 1 and end.day <= 7 else end.year


@dataclass
class _FiscalYear:
    start: date
    end: date | None  # None: the current fiscal year (no annual report yet)
    name: int


def _fiscal_years(series: dict[str, _Series]) -> list[_FiscalYear]:
    """Fiscal years from the 12-month durations. The name is the smallest ``fy`` any annual report gave the span:
    a tag first used in a later 10-K reaches back with that later report's ``fy`` (comparatives)."""
    years: dict[tuple[date, date], int | None] = {}
    for concept, s in series.items():
        if concept in INSTANT or concept in ("eps", "diluted_shares"):
            continue
        for key in s.values:
            start, end = key
            if start is None or not 350 <= (end - start).days <= 380:
                continue
            fy, fp = s.labels.get(key, (None, None))
            known = years.get((start, end))
            if fp == "FY" and fy is not None and (known is None or fy < known):
                years[(start, end)] = fy
            else:
                years.setdefault((start, end), None)
    out: list[_FiscalYear] = []
    for (start, end), fy in sorted(years.items(), key=lambda kv: kv[0][1]):
        if out and start <= (out[-1].end or start):  # overlapping 12-month spans: keep the first
            continue
        name = _fy_name(end, fy, "FY" if fy is not None else None)
        if out and name <= out[-1].name:
            name = out[-1].name + 1
        out.append(_FiscalYear(start, end, name))
    if out and out[-1].end is not None:
        out.append(_FiscalYear(out[-1].end + timedelta(days=1), None, out[-1].name + 1))
    return out


def _quarter_no(start: date, end: date) -> int:
    return round((end - start).days / 91.31)


def _fill(values: dict[str, Decimal | None]) -> dict[str, Decimal | None]:
    """Total liabilities when a company does not tag it: liabilities and equity − total equity (incl. NCI)."""
    le, eq = values.get("liabilities_and_equity"), values.get("equity_total")
    if values.get("total_liabilities") is None and le is not None and eq is not None:
        values["total_liabilities"] = le - eq
    return values


def summarize(facts: dict[str, Any], period: Literal["quarterly", "annual"]) -> list[FiscalPeriod]:
    """Trimmed company facts -> fiscal quarters (``FY2026Q1`` …) or fiscal years (``FY2025`` …), oldest first.

    Quarters: a reported three-month figure when there is one; otherwise the difference of year-to-date figures
    (10-Q cash flows are year-to-date; Q4 = fiscal year − nine months, since 10-Ks report the year only). Such
    values are listed in ``derived``. EPS for a derived quarter is an approximation (share counts change), and an
    average share count is never derived. Balance-sheet items are the instants at the period end.
    """
    series = {c: _series(facts, c) for c in CONCEPTS}
    years = _fiscal_years(series)
    instants = {c: {k[1]: v for k, v in series[c].values.items() if k[0] is None} for c in INSTANT}
    out: list[FiscalPeriod] = []
    for fy in years:
        limit = fy.end or fy.start + timedelta(days=380)
        if period == "annual":
            if fy.end is None:
                continue
            values: dict[str, Decimal | None] = {}
            for c in CONCEPTS:
                values[c] = instants[c].get(fy.end) if c in INSTANT else series[c].values.get((fy.start, fy.end))
            if any(v is not None for v in values.values()):
                out.append(FiscalPeriod(f"FY{fy.name}", fy.name, None, fy.start, fy.end, _fill(values)))
            continue
        ends: dict[int, date] = {}
        quarters: dict[int, dict[str, Decimal | None]] = {n: {} for n in (1, 2, 3, 4)}
        derived: dict[int, set[str]] = {n: set() for n in (1, 2, 3, 4)}
        for c in CONCEPTS:
            if c in INSTANT:
                continue
            cum: dict[int, Decimal] = {}
            direct: dict[int, Decimal] = {}
            for (start, end), val in series[c].values.items():
                if start is None or end > limit or start < fy.start:
                    continue
                n = _quarter_no(fy.start, end)
                if not 1 <= n <= 4:
                    continue
                if start == fy.start:
                    cum[n] = val
                    ends.setdefault(n, end)
                if 70 <= (end - start).days <= 110:
                    direct[n] = val
                    ends.setdefault(n, end)
            running: Decimal | None = Decimal(0)
            for n in (1, 2, 3, 4):
                value: Decimal | None = direct.get(n)
                if value is None and c != "diluted_shares" and n in cum and running is not None:
                    value = cum[n] - running
                    if n > 1:
                        derived[n].add(c)
                quarters[n][c] = value
                # year-to-date through quarter n, for the next difference
                if n in cum:
                    running = cum[n]
                elif running is not None and value is not None:
                    running = running + value
                else:
                    running = None
        if fy.end is not None:
            ends[4] = fy.end
        for n in (1, 2, 3, 4):
            end = ends.get(n)
            if end is None:
                continue
            values = quarters[n]
            for c in INSTANT:
                values[c] = instants[c].get(end)
            if any(v is not None for v in values.values()):
                start = ends[n - 1] + timedelta(days=1) if n > 1 and n - 1 in ends else fy.start
                out.append(FiscalPeriod(f"FY{fy.name}Q{n}", fy.name, n, start, end, _fill(values),
                                        derived[n] & (ADDITIVE | {"eps"})))
    out.sort(key=lambda p: p.end)
    return out


# -- submissions ------------------------------------------------------------------------------------------
FILING_FORMS = ("10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "8-K/A")


def parse_submissions(raw: dict[str, Any], since: date | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """-> (company meta ``{name, fiscal_year_end}``, 8-K / 10-Q / 10-K filings from ``filings.recent``)."""
    meta = {"name": str(raw.get("name") or "")[:200],
            "fiscal_year_end": (str(raw.get("fiscalYearEnd") or "")[:4] or None)}
    recent = ((raw.get("filings") or {}).get("recent") or {}) if isinstance(raw, dict) else {}
    forms = recent.get("form") or []

    def col(name: str, i: int) -> str:
        values = recent.get(name) or []
        return str(values[i] or "") if i < len(values) and values[i] is not None else ""

    rows: list[dict[str, Any]] = []
    for i, form in enumerate(forms):
        if form not in FILING_FORMS:
            continue
        try:
            filed = date.fromisoformat(col("filingDate", i))
        except ValueError:
            continue
        if since is not None and filed < since:
            continue
        accession = col("accessionNumber", i)
        if not accession:
            continue
        try:
            report = date.fromisoformat(col("reportDate", i)) if col("reportDate", i) else None
        except ValueError:
            report = None
        rows.append({"accession": accession[:24], "form": form, "filing_date": filed, "report_date": report,
                     "items": col("items", i)[:120], "primary_document": col("primaryDocument", i)[:200]})
    return meta, rows


def filing_url(cik: int, accession: str, primary_document: str) -> str:
    """The filing's primary document on sec.gov (or its index page when there is none)."""
    folder = accession.replace("-", "")
    doc = primary_document or f"{accession}-index.htm"
    return ARCHIVES_URL.format(cik=cik, folder=folder, doc=doc)


# 8-K items (Form 8-K General Instructions), in plain Traditional Chinese.
ITEM_LABELS = {
    "1.01": "簽訂重大協議", "1.02": "終止重大協議", "1.03": "破產或接管", "1.04": "礦場安全",
    "1.05": "重大資安事件", "2.01": "完成資產取得或處分", "2.02": "營運結果與財務狀況",
    "2.03": "產生直接財務義務", "2.04": "加速或增加財務義務的觸發事件", "2.05": "退出或處分活動的成本",
    "2.06": "重大減損", "3.01": "下市或不符上市規定", "3.02": "未登記的股權銷售",
    "3.03": "證券持有人權利重大變更", "4.01": "更換簽證會計師", "4.02": "先前財報不可再依賴",
    "5.01": "控制權變更", "5.02": "董事或高階主管異動、薪酬安排", "5.03": "章程修訂或會計年度變更",
    "5.04": "員工福利計畫暫停交易", "5.05": "道德守則修訂或豁免", "5.06": "空殼公司狀態變更",
    "5.07": "股東會表決結果", "5.08": "股東提名董事", "7.01": "Regulation FD 揭露", "8.01": "其他事件",
    "9.01": "財務報表與附件",
}
FORM_TITLES = {"10-K": "年度報告", "10-Q": "季度報告", "8-K": "重大事件報告"}


def _items(items: str) -> list[str]:
    return [i.strip() for i in (items or "").split(",") if i.strip()]


def filing_title(form: str, items: str) -> str:
    """「10-K 年度報告」「8-K 營運結果與財務狀況」「10-Q/A 季度報告（修正）」"""
    base = form.removesuffix("/A")
    amended = "（修正）" if form.endswith("/A") else ""
    if base == "8-K":
        codes = [i for i in _items(items) if i != "9.01"] or _items(items)
        main = next((ITEM_LABELS[i] for i in codes if i in ITEM_LABELS), None)
        return f"{form} {main or FORM_TITLES[base]}{amended}"
    return f"{form} {FORM_TITLES.get(base, '申報')}{amended}"


def filing_detail(form: str, report_date: date | None, items: str) -> str:
    base = form.removesuffix("/A")
    if base == "8-K":
        named = [f"{i} {ITEM_LABELS[i]}" if i in ITEM_LABELS else i for i in _items(items)]
        text = f"申報項目：{'、'.join(named)}" if named else ""
        if report_date is not None:
            text = f"{text}；事件日期 {report_date.isoformat()}" if text else f"事件日期 {report_date.isoformat()}"
        return text
    if report_date is None:
        return ""
    return f"會計年度截至 {report_date.isoformat()}" if base == "10-K" else f"季度截至 {report_date.isoformat()}"


def latest_filed(facts: dict[str, Any]) -> date | None:
    """The newest ``filed`` date among the stored facts (dataset status)."""
    newest: str | None = None
    for units in (facts.get("tags") or {}).values():
        for rows in units.values():
            for row in rows:
                if len(row) > 5 and row[5] and (newest is None or row[5] > newest):
                    newest = row[5]
    return date.fromisoformat(newest) if newest else None


def concepts_used(periods: Iterable[FiscalPeriod]) -> set[str]:
    return {c for p in periods for c, v in p.values.items() if v is not None}
