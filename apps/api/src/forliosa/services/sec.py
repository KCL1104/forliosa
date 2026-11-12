"""US stocks from SEC EDGAR: cached company facts and filings, refreshed when stale, served as financials / events.

Storage (``0008``): ``sec_tickers`` (company_tickers.json), ``sec_companies`` (trimmed XBRL company facts and fetch
times) and ``sec_filings`` (8-K / 10-Q / 10-K index rows). The worker (``forliosa.archive`` group ``sec``) refreshes
every tracked US stock once a day; a request for a symbol whose cache is older than ``SEC_STALE_HOURS`` (24) fetches
it on the spot with a short timeout and otherwise serves the cache. Failures are remembered for a few minutes per
company, and a refusal from SEC (403 / 429 / redirect) pauses every SEC request in this process for an hour: never
retried around.

Without ``SEC_CONTACT_EMAIL`` (SEC requires a declared User-Agent with a contact address) nothing is fetched and US
financials / filings are an empty state with a note. The address is read from the settings only when a client is
built, and is never logged or returned.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.datapolicy import labels
from forliosa.marketdata import sec
from forliosa.marketdata.base import InstrumentInfo, ProviderUnavailable, market_of_symbol
from forliosa.models import SecCompany, SecFiling, SecTicker
from forliosa.timeutil import TAIPEI, iso_taipei

log = logging.getLogger("forliosa.sec")

FAILURE_BACKOFF_SECONDS = 600.0  # after a failed fetch, serve the cache for this long before trying again
REFUSAL_BACKOFF_SECONDS = 3600.0  # after a 403 / 429 / redirect from SEC, no SEC request at all for this long
QUARTERS_SHOWN = 12
YEARS_SHOWN = 10
WORKER_STALE_HOURS = 12.0  # the daily job refreshes anything older than this
FILINGS_DAYS = 400

DISABLED_NOTE = ("SEC EDGAR 尚未啟用：伺服器沒有設定 SEC 要求的聯絡信箱（SEC_CONTACT_EMAIL），"
                 "目前沒有美股財報與申報資料")
UNAVAILABLE_NOTE = "SEC EDGAR 暫時無法連線，稍後再試"
REFUSED_NOTE = "SEC EDGAR 拒絕了這次連線（流量限制或封鎖），一小時內不再向 SEC 取資料"
NOT_LISTED_NOTE = "SEC EDGAR 找不到這個代號（ETF 與外國公司通常不在美國申報 10-K／10-Q）"
NO_FACTS_NOTE = "SEC EDGAR 沒有這家公司的 us-gaap 財報數據（外國公司以 20-F 申報，不在這裡）"

_UNSET: Any = object()
_override: Any = _UNSET
_clients: dict[bool, sec.SecClient | None] = {}
_state_lock = threading.Lock()
_fetch_locks: dict[str, threading.Lock] = {}
_retry_after: dict[str, float] = {}  # key -> monotonic time before which no new attempt is made
_refused_until = 0.0
_clock: Callable[[], float] = time.monotonic


# -- client -------------------------------------------------------------------------------------------------
def set_sec_client(client: Any) -> None:
    """Tests: install a fake client (``None`` = SEC disabled). ``reset_sec_state()`` removes it."""
    global _override
    _override = client


def reset_sec_state() -> None:
    global _override, _refused_until
    _override = _UNSET
    _clients.clear()
    _retry_after.clear()
    _refused_until = 0.0


def _contact() -> str | None:
    from forliosa.config import get_settings

    settings = get_settings()
    if not settings.sec_enabled or settings.forliosa_env == "test" or settings.sec_contact_email is None:
        return None
    email = settings.sec_contact_email.get_secret_value().strip()
    return email if sec.valid_contact(email) else None


def sec_client(on_demand: bool = True) -> Any:
    """The SEC client for requests (``on_demand``: short timeout, no retry) or the worker; ``None`` when disabled
    (no or malformed ``SEC_CONTACT_EMAIL``, ``SEC_ENABLED=false``, or ``FORLIOSA_ENV=test`` without a fake)."""
    if _override is not _UNSET:
        return _override
    with _state_lock:
        if on_demand not in _clients:
            email = _contact()
            if email is None:
                _clients[on_demand] = None
            else:
                from forliosa.config import get_settings

                timeout = get_settings().sec_on_demand_timeout_seconds if on_demand else 30.0
                _clients[on_demand] = sec.SecClient(email, timeout=timeout, retries=0 if on_demand else 1)
        return _clients[on_demand]


def _stale_after() -> timedelta:
    from forliosa.config import get_settings

    return timedelta(hours=get_settings().sec_stale_hours)


def _now() -> datetime:
    return datetime.now(TAIPEI)


def _is_stale(ts: datetime | None, after: timedelta) -> bool:
    return ts is None or _now() - ts > after


def _lock(key: str) -> threading.Lock:
    with _state_lock:
        return _fetch_locks.setdefault(key, threading.Lock())


def _attempt(key: str, fn: Callable[[], Any]) -> str | None:
    """Run one SEC fetch unless SEC refused us recently or ``key`` failed a moment ago; returns a note on failure."""
    global _refused_until
    now = _clock()
    if now < _refused_until:
        return REFUSED_NOTE
    if now < _retry_after.get(key, 0.0):
        return UNAVAILABLE_NOTE
    try:
        fn()
    except ProviderUnavailable as exc:
        if sec.is_refusal(exc):
            _refused_until = _clock() + REFUSAL_BACKOFF_SECONDS
            log.warning("SEC refused a request (%s): pausing SEC fetches for an hour", exc)
            return REFUSED_NOTE
        _retry_after[key] = _clock() + FAILURE_BACKOFF_SECONDS
        log.warning("SEC fetch %s failed: %s", key, exc)
        return UNAVAILABLE_NOTE
    _retry_after.pop(key, None)
    return None


# -- refresh (writes) ---------------------------------------------------------------------------------------
def refresh_tickers(db: Session, client: Any) -> int:
    from forliosa.archive import upsert

    now = _now()
    rows = [{**r, "fetched_at": now} for r in sec.parse_tickers(client.tickers())]
    if not rows:
        raise ProviderUnavailable("company_tickers.json 是空的或格式不符")
    return upsert(db, SecTicker, rows, ["ticker"], ["cik", "title", "fetched_at"])


def _company(db: Session, cik: int, **cols: Any) -> None:
    from forliosa.archive import upsert

    upsert(db, SecCompany, [{"cik": cik, **cols}], ["cik"], list(cols))


def refresh_facts(db: Session, client: Any, cik: int, name: str = "") -> int:
    """companyfacts -> ``sec_companies.facts`` (trimmed). A company SEC has no facts for is stored empty."""
    raw = client.company_facts(cik)
    today = _now().date()
    if raw is None:
        _company(db, cik, facts={"v": sec.FACTS_VERSION, "tags": {}}, facts_fetched_at=_now(), source=sec.SOURCE)
        return 0
    facts = sec.trim_facts(raw, today)
    shares, as_of = sec.shares_outstanding(raw)
    _company(db, cik, name=str(raw.get("entityName") or name)[:200], facts=facts, shares_outstanding=shares,
             shares_as_of=as_of, facts_fetched_at=_now(), source=sec.SOURCE)
    return len(facts["tags"])


def refresh_filings(db: Session, client: Any, cik: int) -> int:
    from forliosa.archive import upsert

    raw = client.submissions(cik)
    now = _now()
    if raw is None:
        _company(db, cik, filings_fetched_at=now, source=sec.SOURCE)
        return 0
    meta, rows = sec.parse_submissions(raw, since=now.date() - timedelta(days=FILINGS_DAYS))
    n = upsert(db, SecFiling, [{**r, "cik": cik, "source": sec.SOURCE, "fetched_at": now} for r in rows],
               ["cik", "accession"], ["form", "filing_date", "report_date", "items", "primary_document", "fetched_at"])
    cols: dict[str, Any] = {"filings_fetched_at": now, "source": sec.SOURCE}
    if meta["name"]:
        cols["name"] = meta["name"]
    if meta["fiscal_year_end"]:
        cols["fiscal_year_end"] = meta["fiscal_year_end"]
    if meta["profile"]:
        cols["profile"] = meta["profile"]
    _company(db, cik, **cols)
    return n


# -- lookups (on demand) ------------------------------------------------------------------------------------
def resolve_ticker(db: Session, symbol: str, client: Any) -> tuple[SecTicker | None, str | None]:
    """The CIK row for a US symbol. A missing or day-old ticker map is refreshed once when the symbol is unknown."""
    ticker = sec.sec_ticker(symbol)
    row = db.get(SecTicker, ticker)
    if row is not None or client is None:
        return row, None
    note = None
    with _lock("tickers"):
        newest = db.scalar(select(func.max(SecTicker.fetched_at)))
        if _is_stale(newest, _stale_after()):
            note = _attempt("tickers", lambda: refresh_tickers(db, client))
    return db.get(SecTicker, ticker), note


Need = Literal["facts", "filings"]


def _fetched(comp: SecCompany | None, need: Need) -> datetime | None:
    if comp is None:
        return None
    return comp.facts_fetched_at if need == "facts" else comp.filings_fetched_at


def _outdated(comp: SecCompany | None, need: Need) -> bool:
    """Facts trimmed by an older version (no split list, comparatives' ``fy`` not corrected): fetch again."""
    return need == "facts" and comp is not None and (comp.facts or {}).get("v") != sec.FACTS_VERSION


def _due(comp: SecCompany | None, need: Need, after: timedelta) -> bool:
    return _is_stale(_fetched(comp, need), after) or _outdated(comp, need)


def company_data(db: Session, symbol: str, need: Need) -> tuple[SecTicker | None, SecCompany | None, list[str]]:
    """Cached SEC data for ``symbol``, refreshed first when older than ``SEC_STALE_HOURS`` (and SEC is enabled)."""
    client = sec_client(on_demand=True)
    tick, note = resolve_ticker(db, symbol, client)
    if tick is None:
        if client is None and not db.scalar(select(func.count()).select_from(SecTicker)):
            return None, None, [DISABLED_NOTE]
        return None, None, [note or NOT_LISTED_NOTE]
    cik, title = tick.cik, tick.title
    comp = db.get(SecCompany, cik)
    notes: list[str] = []
    if not _due(comp, need, _stale_after()):
        return tick, comp, notes
    if client is None:
        fetched = _fetched(comp, need)
        notes.append(DISABLED_NOTE if fetched is None
                     else f"SEC EDGAR 尚未啟用，顯示 {fetched.astimezone(TAIPEI):%Y-%m-%d} 取得的資料")
        return tick, comp, notes
    err = None
    with _lock(f"{need}:{cik}"):
        comp = db.get(SecCompany, cik, populate_existing=True)
        if _due(comp, need, _stale_after()):  # another request may have refreshed it meanwhile
            if need == "facts":
                err = _attempt(f"facts:{cik}", lambda: refresh_facts(db, client, cik, title))
            else:
                err = _attempt(f"filings:{cik}", lambda: refresh_filings(db, client, cik))
            comp = db.get(SecCompany, cik, populate_existing=True)
    fetched = _fetched(comp, need)
    if err and fetched is not None:
        notes.append(f"{err}；顯示 {fetched.astimezone(TAIPEI):%Y-%m-%d %H:%M} 取得的資料")
    elif err:
        notes.append(err)
    return db.get(SecTicker, sec.sec_ticker(symbol)), comp, notes


# -- financials ---------------------------------------------------------------------------------------------
def _fye_note(periods: list[sec.FiscalPeriod]) -> str | None:
    q = next((p for p in reversed(periods) if p.quarter == 1), None)
    if q is None:
        y = next((p for p in reversed(periods) if p.quarter is None), None)
        if y is None:
            return None
        return f"美股依公司會計年度標示：{y.label} 是 {y.start.isoformat()} 至 {y.end.isoformat()}"
    return f"美股依公司會計年度標示：{q.label} 是 {q.start.isoformat()} 至 {q.end.isoformat()} 的季度"


def _split_words(ratio: Fraction) -> str:
    if ratio > 1:
        return f"{ratio.denominator} 股拆成 {ratio.numerator} 股"
    return f"{ratio.denominator} 股合併為 {ratio.numerator} 股"


def _splits_note(facts: dict[str, Any], periods: list[sec.FiscalPeriod]) -> str | None:
    """Splits after the first period shown: EPS and share counts are all on today's basis (``sec.summarize``)."""
    splits = [(d, r) for d, r in sec.stock_splits(facts) if periods and d > periods[0].end]
    if not splits:
        return None
    parts = "、".join(f"{d.isoformat()} 起申報的財報反映 {_split_words(r)}" for d, r in splits)
    return (f"EPS 與稀釋平均股數都以目前的股數為準：{parts}；"
            "更早申報、後來沒有重編的數字已依分割比例換算")


def financials(db: Session, info: InstrumentInfo, period: str, out: dict[str, Any]) -> dict[str, Any]:
    """``GET /instruments/{symbol}/financials`` for a US stock: the companyfacts summary in USD (``amount_unit`` 1)."""
    out.update(currency="USD", amount_unit=1)
    tick, comp, notes = company_data(db, info.symbol, "facts")
    out["notes"] = list(notes)
    if comp is None or not (comp.facts or {}).get("tags"):
        if tick is not None and comp is not None and comp.facts_fetched_at is not None:
            out["notes"].append(NO_FACTS_NOTE)
        return out
    periods = sec.summarize(comp.facts, "annual" if period == "annual" else "quarterly")
    periods = periods[-(YEARS_SHOWN if period == "annual" else QUARTERS_SHOWN):]
    if not periods:
        out["notes"].append(NO_FACTS_NOTE)
        return out

    def col(item: str) -> list[float | None]:
        return [(ser.price if item == "eps" else ser.money)(p.values.get(item)) for p in periods]

    out["periods"] = [p.label for p in periods]
    out["period_ends"] = [p.end for p in periods]
    for item in out["income"]:
        out["income"][item] = col(item)
    for item in out["balance"]:
        out["balance"][item] = col(item)
    for item in ("operating", "investing", "financing"):
        out["cashflow"][item] = col(item)
    fcf = []
    for p in periods:
        ocf, capex = p.values.get("operating"), p.values.get("capex")
        fcf.append(ser.money(ocf - capex) if ocf is not None and capex is not None else None)
    out["cashflow"]["free_cash_flow"] = fcf
    for name, item in (("gross", "gross_profit"), ("operating", "operating_income"), ("net", "net_income")):
        vals = []
        for p in periods:
            num, rev = p.values.get(item), p.values.get("revenue")
            vals.append(ser.ratio(num / rev) if num is not None and rev else None)
        out["margins"][name] = vals
    out["shares"] = {
        "outstanding": comp.shares_outstanding, "outstanding_as_of": comp.shares_as_of,
        "diluted_average": [int(v) if (v := p.values.get("diluted_shares")) is not None else None for p in periods],
    }
    out["as_of"] = iso_taipei(comp.facts_fetched_at) if comp.facts_fetched_at else None
    fye = _fye_note(periods)
    if fye:
        out["notes"].append(fye)
    out["notes"].append("金額單位：美元；EPS 為稀釋每股盈餘（美元）；"
                        "自由現金流量 = 營業活動現金流量 − 購置不動產、廠房及設備")
    derived = set().union(*(p.derived for p in periods))
    if derived - {"eps"}:
        out["notes"].append("10-Q 的現金流量是年初至今累計、10-K 只報全年：單季數字由累計數相減得出")
    if "eps" in derived:
        out["notes"].append("第四季（或只有累計數的季度）EPS 為累計 EPS 相減的近似值")
    split_note = _splits_note(comp.facts, periods)
    if split_note:
        out["notes"].append(split_note)
    out["sources"] = labels(["sec-edgar/companyfacts"])
    return out


def cached_key_data(db: Session, symbol: str) -> dict[str, Any]:
    """Overview fields from the cache only (no fetch, so the overview stays fast): diluted EPS of the last four
    quarters (``None`` unless all four are known) and the cover-page shares outstanding."""
    tick = db.get(SecTicker, sec.sec_ticker(symbol))
    comp = db.get(SecCompany, tick.cik) if tick else None
    if comp is None or not (comp.facts or {}).get("tags"):
        return {"eps_ttm": None, "shares_outstanding": None, "sources": []}
    quarters = sec.summarize(comp.facts, "quarterly")[-4:]
    last4 = [p.values.get("eps") for p in quarters]
    eps = (sum((v for v in last4 if v is not None), Decimal(0))
           if len(last4) == 4 and all(v is not None for v in last4) else None)
    if len(quarters) == 4 and quarters[-1].quarter == 4 and quarters[0].fiscal_year == quarters[-1].fiscal_year:
        # the last four quarters are one fiscal year: its reported EPS (per-quarter EPS do not add up exactly)
        year = next((p for p in sec.summarize(comp.facts, "annual") if p.end == quarters[-1].end), None)
        eps = year.values.get("eps") if year is not None and year.values.get("eps") is not None else eps
    used = eps is not None or comp.shares_outstanding is not None
    return {"eps_ttm": eps, "shares_outstanding": comp.shares_outstanding,
            "sources": ["sec-edgar/companyfacts"] if used else []}


# -- events ---------------------------------------------------------------------------------------------------
def filing_events(db: Session, info: InstrumentInfo, lo: date, hi: date, held: bool,
                  today: date) -> list[dict[str, Any]]:
    """8-K / 10-Q / 10-K filings as stock events (``type: "sec_filing"``, ``form``), newest first."""
    tick, _comp, _notes = company_data(db, info.symbol, "filings")
    if tick is None:
        return []
    stmt = (select(SecFiling).where(SecFiling.cik == tick.cik, SecFiling.filing_date >= lo,
                                    SecFiling.filing_date <= hi)
            .order_by(SecFiling.filing_date.desc(), SecFiling.accession.desc()))
    src = labels(["sec-edgar/submissions"])
    out = []
    for f in db.scalars(stmt):
        periodic = f.form.removesuffix("/A") in ("10-K", "10-Q")
        mine = held and (periodic or f.filing_date >= today - timedelta(days=7))
        out.append({"date": f.filing_date, "type": "sec_filing", "form": f.form,
                    "title": sec.filing_title(f.form, f.items),
                    "detail": sec.filing_detail(f.form, f.report_date, f.items),
                    "url": sec.filing_url(tick.cik, f.accession, f.primary_document),
                    "mine": mine, "amount_estimate": None, "estimated": False, "period": None, "sources": src})
    return out


# -- worker ---------------------------------------------------------------------------------------------------
def us_stock_symbols(symbols: list[str]) -> list[str]:
    """US stocks among ``symbols`` (ETFs have no 10-K / 10-Q of their own)."""
    from forliosa.marketdata.service import get_market_data

    out = []
    md = get_market_data()
    for s in symbols:
        if market_of_symbol(s) != "US":
            continue
        info = md.instrument(s)
        if info is None or info.type == "stock":
            out.append(info.symbol if info else s)
    return list(dict.fromkeys(out))


def sync_symbols(db: Session, client: Any, symbols: list[str],
                 stale: timedelta = timedelta(hours=WORKER_STALE_HOURS)) -> dict[str, int]:
    """Daily job: the ticker map, then company facts and filings of each symbol not refreshed within ``stale``.

    A refusal (403 / 429 / redirect) stops the job at once (raised as :class:`ProviderUnavailable`); other errors
    skip that company.
    """
    counts = {"tickers": 0, "companies": 0, "filings": 0, "failed": 0}
    newest = db.scalar(select(func.max(SecTicker.fetched_at)))
    if _is_stale(newest, stale) or (symbols and newest is None):
        counts["tickers"] = refresh_tickers(db, client)
    for sym in symbols:
        tick = db.get(SecTicker, sec.sec_ticker(sym))
        if tick is None:
            continue
        comp = db.get(SecCompany, tick.cik)
        try:
            if comp is None or _due(comp, "facts", stale):
                refresh_facts(db, client, tick.cik, tick.title)
                counts["companies"] += 1
            if comp is None or _is_stale(comp.filings_fetched_at, stale):
                counts["filings"] += refresh_filings(db, client, tick.cik)
        except ProviderUnavailable as exc:
            db.rollback()
            if sec.is_refusal(exc):
                raise
            counts["failed"] += 1
            log.warning("SEC %s (CIK %s) failed: %s", sym, tick.cik, exc)
    return counts


def latest_data_dates(db: Session) -> dict[str, date | None]:
    """Newest filed date in the stored facts and newest filing date (``dataset_status``)."""
    newest_facts: date | None = None
    for facts in db.scalars(select(SecCompany.facts)):
        d = sec.latest_filed(facts or {})
        if d is not None and (newest_facts is None or d > newest_facts):
            newest_facts = d
    return {"sec-edgar/companyfacts": newest_facts,
            "sec-edgar/submissions": db.scalar(select(func.max(SecFiling.filing_date)))}
