"""Daily archive of official open data (the OpenAPIs only serve the latest day, so we keep history).

Run once from the command line::

    uv run python -m forliosa.archive run                    # every job that applies to DATA_POLICY
    uv run python -m forliosa.archive run --only twse,tpex   # twse | tpex | companies | financials | taifex |
                                                             # tdcc | weekly | sec
    uv run python -m forliosa.archive backfill --days 90     # personal opt-in only, see "Backfill" below

The worker runs the same jobs on a schedule (``forliosa.worker``). Every write is an upsert keyed on
(symbol, date[, level]) or an announcement key, so running a job twice changes nothing.

What is archived, and from where (field names: ``forliosa.marketdata.opendata``):

==========================  =========================================================
table                       source (official open data, 政府資料開放授權條款第 1 版)
==========================  =========================================================
prices_daily                TWSE STOCK_DAY_ALL, TPEx daily_close_quotes
valuation_daily             TWSE BWIBBU_ALL, TPEx peratio_analysis
reference_prices            TWSE TWT84U, TPEx NextReferencePrice/NextLimit*
margin_daily                TWSE MI_MARGN, TPEx margin_balance
institutional_daily         TPEx 3insti_daily_trading (TWSE has no per-stock OpenAPI dataset)
foreign_holding_daily       TPEx 3insti_qfii (TWSE has no per-stock OpenAPI dataset)
shareholding_distribution   TDCC open data 1-5 (weekly, current week only)
market_events               TWT48U_ALL / exright_prepost (除權息), notice / warning (注意),
                            punish / disposal (處置), t187ap04 (重大訊息), t187ap41 (股東會),
                            t187ap05 (營收公布日: first seen), TWSE news/newsList (證交所新聞)
financial_reports           t187ap06 (income, YTD), t187ap07 (balance), t187ap17; blank rows are skipped and
                            a null value never overwrites an archived one
fund_profiles               TWSE t187ap47_L 基金基本資料彙總表 (ETF basics)
market_holidays             TWSE holidaySchedule (official calendar, current year)
index_daily                 TWSE MI_INDEX (all indices, daily) + MFI94U (current month of 發行量加權股價報酬指數),
                            TPEx tpex_index + tpex_reward_index (current month): benchmarks ^TAIEXTR / ^TPEXTR
dividend_resolutions        TWSE t187ap45_L 股利分派情形 (board / AGM resolutions; TPEx mopsfin_t187ap39_O is dead
                            since 2021-08, so TPEx dividends only come from the ex-dividend notices)
company_profiles            TWSE t187ap03_L, TPEx mopsfin_t187ap03_O (issued shares, industry, listing date)
ex_rights_results           TPEx tpex_exright_daily (official reference price and limits on ex-dates)
taifex_*                    TAIFEX OpenAPI (group ``taifex``, daily 21:40; ``weekly``: final settlement prices,
fx_rates                    SSF/SSO lists). DailyForeignExchangeRates -> fx_rates (USDTWD …, multi-day upsert)
dataset_status              newest data date per dataset (shown in /meta/attributions; ``weekly`` also checks the
                            stale endpoints twtazu_od and t187ap09_L)
sec_tickers, sec_companies, SEC EDGAR (group ``sec``, daily 07:50, US government public data): the ticker -> CIK
sec_filings                 map, trimmed XBRL company facts and 8-K / 10-Q / 10-K filings of every tracked US
                            stock (``forliosa.services.sec``; needs SEC_CONTACT_EMAIL, skipped without it)
==========================  =========================================================

Only ``openapi.twse.com.tw``, ``www.tpex.org.tw/openapi``, ``opendata.tdcc.com.tw``,
``openapi.taifex.com.tw/v1`` and the three SEC EDGAR JSON datasets are fetched (see the allowlist in
``marketdata/http.py``). The TWSE / TPEx / TAIFEX
**websites** forbid automated downloads without written consent, so the former T86 / MI_QFIIS website jobs and
the website backfill were removed (2026-11-12). There is no official per-stock history API: the archive only
grows from the day the worker starts. ``backfill`` remains only for FinMind under an explicit
``DATA_POLICY=personal`` opt-in with ``finmind`` listed in ``MARKET_DATA_PROVIDERS`` (non-commercial; never on by
default). Backfilled rows never overwrite official rows, and commercial queries skip them.
"""

from __future__ import annotations

import argparse
import logging
import time as _time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from forliosa.datapolicy import Policy
from forliosa.marketdata import opendata as od
from forliosa.marketdata import taifex as tf
from forliosa.marketdata.base import ProviderUnavailable, tw_symbol
from forliosa.marketdata.http import HttpFetcher
from forliosa.marketdata.twse import parse_bwibbu_all, parse_stock_day_all
from forliosa.models import (
    CompanyProfile,
    DatasetStatus,
    DividendResolution,
    ExRightsResult,
    FinancialReport,
    ForeignHoldingDaily,
    FundProfile,
    FxRate,
    HoldingSnapshot,
    IndexDaily,
    InstitutionalDaily,
    MarginDaily,
    MarketEvent,
    MarketHoliday,
    PriceDaily,
    ReferencePrice,
    ShareholdingDistribution,
    TaifexContractMap,
    TaifexFinalSettlement,
    TaifexFuturesDaily,
    TaifexInstitutional,
    TaifexLargeTraders,
    TaifexMargin,
    TaifexOptionsDaily,
    TaifexPutCallRatio,
    TaifexUnderlying,
    Transaction,
    ValuationDaily,
    WatchlistItem,
)
from forliosa.timeutil import TAIPEI, last_tw_trading_day, next_tw_trading_day, now_taipei

log = logging.getLogger("forliosa.archive")

TWSE_OPENAPI = "https://openapi.twse.com.tw/v1"
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1"
TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx"
TAIFEX_OPENAPI = tf.TAIFEX_OPENAPI
INDUSTRIES = ("ci", "basi", "bd", "fh", "ins", "mim")
# TWSE publishes the day's margin balances in the evening; before this time MI_MARGN is the previous day's.
MARGIN_READY = time(21, 0)

# twse / tpex: latest-day datasets (08:10, 14:40, 21:40); companies: slow-changing large files (21:40);
# taifex: TAIFEX daily datasets (21:40); weekly (Saturday): TAIFEX final settlement + SSF/SSO lists, and the
# stale-endpoint check; sec (07:50 daily): SEC EDGAR facts and filings of tracked US stocks.
JOB_GROUPS = ("twse", "tpex", "companies", "financials", "taifex", "tdcc", "weekly", "sec")
SEC_DISABLED = "sec edgar（未設定 SEC_CONTACT_EMAIL，略過）"


def upsert(db: Session, model: Any, rows: list[dict[str, Any]], keys: list[str],
           update: Iterable[str] | None = None) -> int:
    """INSERT … ON CONFLICT (keys) DO UPDATE (``update`` columns) or DO NOTHING (``update=()``)."""
    if not rows:
        return 0
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    total = 0
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        stmt = insert(model).values(chunk)
        cols = list(update) if update is not None else [k for k in chunk[0] if k not in keys]
        if cols:
            stmt = stmt.on_conflict_do_update(index_elements=keys, set_={c: stmt.excluded[c] for c in cols})
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=keys)
        db.execute(stmt)
        total += len(chunk)
    db.commit()
    return total


def tracked_symbols(db: Session) -> list[str]:
    """Symbols in any user's ledger, holdings snapshot or watchlist."""
    syms = set(db.scalars(select(Transaction.symbol).where(Transaction.symbol.is_not(None)).distinct()))
    syms |= set(db.scalars(select(HoldingSnapshot.symbol).distinct()))
    syms |= set(db.scalars(select(WatchlistItem.symbol).distinct()))
    return sorted(s for s in syms if s)


@dataclass
class JobResult:
    name: str
    rows: int = 0
    error: str | None = None


@dataclass
class Archiver:
    db: Session
    fetcher: HttpFetcher
    policy: Policy = "commercial"
    now_fn: Callable[[], datetime] = now_taipei
    results: list[JobResult] = field(default_factory=list)
    sec_client: Any = None  # SEC EDGAR client (tests inject a fake); None: built from SEC_CONTACT_EMAIL

    # -- plumbing ------------------------------------------------------------------------------
    def _json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self.fetcher.get_json(url, params=params)

    def _list(self, url: str) -> list[dict[str, Any]]:
        data = self._json(url)
        if not isinstance(data, list):
            raise ProviderUnavailable(f"{url} 格式不符")
        return data

    def _run(self, name: str, fn: Callable[[], int]) -> int:
        try:
            n = fn()
        except Exception as exc:  # one failing dataset must not stop the others
            log.warning("archive %s failed: %s", name, exc)
            self.db.rollback()
            self.results.append(JobResult(name, 0, str(exc)[:200]))
            return 0
        log.info("archive %s: %d rows", name, n)
        self.results.append(JobResult(name, n))
        return n

    def _status(self, key: str, data_date: date | None, rows: int) -> None:
        """Remember the newest data date seen for dataset ``key`` (``/meta/attributions`` shows it)."""
        upsert(self.db, DatasetStatus, [{"key": key, "data_date": data_date, "rows": rows,
                                         "fetched_at": datetime.now(TAIPEI)}], ["key"])

    def _taifex(self, path: str) -> list[dict[str, Any]]:
        """A TAIFEX OpenAPI dataset (JSON or CSV: the Cloudflare cache serves either, see marketdata/taifex.py)."""
        return tf.decode_rows(self.fetcher.get_bytes(f"{TAIFEX_OPENAPI}/{path}"))

    def _ex_dividend_notices(self, rows: list[dict[str, Any]], market: str, source: str) -> int:
        """Upsert a full TWT48U_ALL / tpex_exright_prepost snapshot and drop the archived future notices of that
        market it no longer lists (a moved or withdrawn ex-date: otherwise the old date would be booked as a second
        dividend). Past and today's notices are kept; an empty snapshot prunes nothing."""
        n = self._events(rows, source)
        if not rows:
            return n
        today = self.now_fn().astimezone(TAIPEI).date()
        listed = {r["key"] for r in rows}
        suffix = ".TWO" if market == "TPEX" else ".TW"
        stale = [e for e in self.db.scalars(select(MarketEvent).where(
            MarketEvent.type == "ex_dividend", MarketEvent.source == source, MarketEvent.date > today))
            if e.symbol.endswith(suffix) and e.key not in listed]
        for e in stale:
            self.db.delete(e)
        if stale:
            self.db.commit()
            log.info("%s: %d withdrawn ex-dividend notices removed", source, len(stale))
        return n

    def _events(self, rows: list[dict[str, Any]], source: str) -> int:
        out = [{"key": r["key"], "symbol": tw_symbol(r["code"], r["market"]), "date": r["date"],
                "end_date": r["end_date"], "type": r["type"], "title": r["title"][:500], "detail": r["detail"],
                "url": r.get("url"), "data": r["data"], "source": source} for r in rows]
        return upsert(self.db, MarketEvent, out, ["key"], ["end_date", "title", "detail", "data", "source"])

    # -- TWSE OpenAPI --------------------------------------------------------------------------
    def twse_prices(self) -> int:
        quotes = parse_stock_day_all(self._list(f"{TWSE_OPENAPI}/exchangeReport/STOCK_DAY_ALL"))
        rows = [{"symbol": s, "date": q.trade_date, "open": q.open, "high": q.high, "low": q.low, "close": q.price,
                 "volume": q.volume, "source": "twse-openapi"}
                for s, q in quotes.items() if od.is_listed_code(s.split(".")[0])]
        return upsert(self.db, PriceDaily, rows, ["symbol", "date"])

    def twse_valuation(self) -> int:
        ratios = parse_bwibbu_all(self._list(f"{TWSE_OPENAPI}/exchangeReport/BWIBBU_ALL"))
        rows = [{"symbol": tw_symbol(code, "TWSE"), "date": v["date"],
                 "per": v["per"] if v["per"] and v["per"] > 0 else None, "pbr": v["pbr"],
                 "dividend_yield": v["dividend_yield"], "source": "twse-openapi"}
                for code, v in ratios.items() if v["date"] and od.is_listed_code(code)]
        return upsert(self.db, ValuationDaily, rows, ["symbol", "date"])

    def twse_reference(self) -> int:
        rows = [{"symbol": tw_symbol(r["code"], "TWSE"),
                 "date": next_tw_trading_day(r["last_trading_day"] + timedelta(days=1)),
                 "reference_price": r["reference_price"], "limit_up": r["limit_up"], "limit_down": r["limit_down"],
                 "source": "twse-openapi"}
                for r in od.parse_twt84u(self._list(f"{TWSE_OPENAPI}/exchangeReport/TWT84U"))]
        return upsert(self.db, ReferencePrice, rows, ["symbol", "date"])

    def margin_date(self) -> date:
        """MI_MARGN has no date field: the evening's data belongs to today, before that to the last session."""
        now = self.now_fn().astimezone(TAIPEI)
        d = last_tw_trading_day(now.date())
        if d == now.date() and now.time() < MARGIN_READY:
            d = last_tw_trading_day(d - timedelta(days=1))
        return d

    def twse_margin(self) -> int:
        d = self.margin_date()
        rows = [{"symbol": tw_symbol(r["code"], "TWSE"), "date": d, "margin_balance": r["margin_balance"],
                 "short_balance": r["short_balance"], "margin_limit": r["margin_limit"], "source": "twse-openapi"}
                for r in od.parse_mi_margn(self._list(f"{TWSE_OPENAPI}/exchangeReport/MI_MARGN"))]
        return upsert(self.db, MarginDaily, rows, ["symbol", "date"])

    def twse_events(self) -> int:
        n = self._ex_dividend_notices(
            od.parse_twt48u_events(self._list(f"{TWSE_OPENAPI}/exchangeReport/TWT48U_ALL")), "TWSE", "twse-openapi")
        n += self._events(od.parse_twse_notice(self._list(f"{TWSE_OPENAPI}/announcement/notice")), "twse-openapi")
        n += self._events(od.parse_twse_punish(self._list(f"{TWSE_OPENAPI}/announcement/punish")), "twse-openapi")
        n += self._events(od.parse_material_info(self._list(f"{TWSE_OPENAPI}/opendata/t187ap04_L"), "TWSE"),
                          "twse-openapi")
        n += self._events(od.parse_shareholder_meetings(self._list(f"{TWSE_OPENAPI}/opendata/t187ap41_L"), "TWSE"),
                          "twse-openapi")
        return n

    def twse_holidays(self) -> int:
        """Official market calendar (current year); trading-day markers are kept with is_trading_day."""
        rows = [{**r, "source": "twse-openapi"}
                for r in od.parse_holidays(self._list(f"{TWSE_OPENAPI}/holidaySchedule/holidaySchedule"))]
        n = upsert(self.db, MarketHoliday, rows, ["date"])
        from forliosa.market_calendar import load_official_calendar

        load_official_calendar(self.db)
        return n

    def _revenue(self, rows: list[dict[str, Any]], source: str) -> int:
        """Monthly revenue release dates: the day a (company, month) row first appears in the dataset.

        Rows already present on the very first run of a dataset (nothing archived from it before) were
        filed before archiving started, so their date is unknown: they are stored with ``backlog: true`` and
        the events endpoint shows the legal deadline (``estimated: true``) for them instead. Later rows keep
        their first-seen date (``ON CONFLICT DO NOTHING``): the publisher's 出表日期 when it is not in the
        future, else the archive date.
        """
        today = self.now_fn().astimezone(TAIPEI).date()
        seen_before = self.db.scalar(select(MarketEvent.id).where(
            MarketEvent.type == "revenue_release", MarketEvent.source == source).limit(1)) is not None
        out = []
        for r in rows:
            first = r["published"] if r["published"] is not None and r["published"] <= today else today
            month = int(r["period"][5:])
            detail = f"{month} 月營收 {r['revenue']:,} 千元" if r["revenue"] is not None else f"{month} 月營收"
            if r["yoy_pct"] is not None:
                detail += f"，年增 {r['yoy_pct'] * 100:.1f}%"
            out.append({"key": od.event_key("revenue", r["market"], r["code"], r["period"]),
                        "symbol": tw_symbol(r["code"], r["market"]), "date": first, "end_date": None,
                        "type": "revenue_release", "title": f"{month} 月營收公布", "detail": detail, "url": None,
                        "data": {"period": r["period"], "revenue": r["revenue"],
                                 "yoy_pct": str(r["yoy_pct"]) if r["yoy_pct"] is not None else None,
                                 "mom_pct": str(r["mom_pct"]) if r["mom_pct"] is not None else None,
                                 "first_seen": today.isoformat(), "backlog": not seen_before},
                        "source": source})
        return upsert(self.db, MarketEvent, out, ["key"], ())

    def twse_news(self) -> int:
        """證交所新聞 (market announcements); rows naming a company code are filed under that symbol."""
        rows = [{"key": r["key"], "symbol": tw_symbol(r["code"], "TWSE") if r["code"] else "MARKET",
                 "date": r["date"], "end_date": None, "type": "exchange_news", "title": r["title"], "detail": "",
                 "url": r["url"], "data": {}, "source": "twse-openapi"}
                for r in od.parse_twse_news(self._list(f"{TWSE_OPENAPI}/news/newsList"))]
        return upsert(self.db, MarketEvent, rows, ["key"], ["title", "url"])

    def twse_funds(self) -> int:
        rows = [{"symbol": tw_symbol(r["code"], "TWSE"), "date": r["date"], "values": r["values"],
                 "source": "twse-openapi", "fetched_at": datetime.now(TAIPEI)}
                for r in od.parse_fund_profiles(self._list(f"{TWSE_OPENAPI}/opendata/t187ap47_L"))]
        return upsert(self.db, FundProfile, rows, ["symbol"])

    def twse_revenue(self) -> int:
        rows = od.parse_monthly_revenue(self._list(f"{TWSE_OPENAPI}/opendata/t187ap05_L"), "TWSE")
        return self._revenue(rows, "twse-openapi")

    def _indices(self, rows: list[dict[str, Any]], market: str, source: str,
                 update: Iterable[str] | None = None) -> int:
        out = [{"name": r["name"], "date": r["date"], "market": market, "open": r.get("open"), "high": r.get("high"),
                "low": r.get("low"), "close": r["close"], "change": r.get("change"),
                "change_pct": r.get("change_pct"), "source": source} for r in rows]
        return upsert(self.db, IndexDaily, out, ["name", "date"], update)

    def twse_total_return(self) -> int:
        """MFI94U (this month of 發行量加權股價報酬指數): the first run backfills the month of the ^TAIEXTR benchmark.
        On conflicts only the close is updated (MI_INDEX's official change is kept)."""
        mfi = od.with_changes(od.parse_mfi94u(self._list(f"{TWSE_OPENAPI}/indicesReport/MFI94U")))
        n = self._indices(mfi, "TWSE", "twse-openapi", ["close", "source"])
        self._status("twse-openapi/total_return", max((r["date"] for r in mfi), default=None), len(mfi))
        return n

    def twse_indices(self) -> int:
        """MI_INDEX: every index's close and change (the latest day), incl. 發行量加權股價報酬指數."""
        mi = od.parse_mi_index(self._list(f"{TWSE_OPENAPI}/exchangeReport/MI_INDEX"))
        n = self._indices(mi, "TWSE", "twse-openapi")
        self._status("twse-openapi/index", max((r["date"] for r in mi), default=None), len(mi))
        return n

    def twse_dividends(self) -> int:
        """t187ap45_L 股利分派情形: board / AGM resolutions with the cash split by source."""
        now = datetime.now(TAIPEI)
        rows = [{**{k: v for k, v in r.items() if k != "code"}, "symbol": tw_symbol(r["code"], "TWSE"),
                 "source": "twse-openapi", "fetched_at": now}
                for r in od.parse_dividend_resolutions(self._list(f"{TWSE_OPENAPI}/opendata/t187ap45_L"))]
        n = upsert(self.db, DividendResolution, rows, ["symbol", "period_start", "seq"])
        self._status("twse-openapi/dividend_resolution", max((r["published"] for r in rows), default=None), n)
        return n

    def _companies(self, rows: list[dict[str, Any]], market: str, source: str, key: str) -> int:
        now = datetime.now(TAIPEI)
        out = [{"symbol": tw_symbol(r["code"], market), "date": r["date"], "industry_code": r["industry_code"],
                "industry": r["industry"], "listed_date": r["listed_date"],
                "shares_outstanding": r["shares_outstanding"], "values": r["values"], "source": source,
                "fetched_at": now} for r in rows]
        n = upsert(self.db, CompanyProfile, out, ["symbol"])
        self._status(key, max((r["date"] for r in out), default=None), n)
        return n

    def twse_companies(self) -> int:
        rows = od.parse_company_profiles(self._list(f"{TWSE_OPENAPI}/opendata/t187ap03_L"), "TWSE")
        return self._companies(rows, "TWSE", "twse-openapi", "twse-openapi/company")

    def tpex_companies(self) -> int:
        rows = od.parse_company_profiles(self._list(f"{TPEX_OPENAPI}/mopsfin_t187ap03_O"), "TPEX")
        return self._companies(rows, "TPEX", "tpex-openapi", "tpex-openapi/company")

    def stale_check(self) -> int:
        """Endpoints that stopped updating (not used, tiny): record their newest 出表日期 for /meta/attributions."""
        n = 0
        for key, path in (("twse-openapi/breadth", "opendata/twtazu_od"),
                          ("twse-openapi/pledge", "opendata/t187ap09_L")):
            rows = self._list(f"{TWSE_OPENAPI}/{path}")
            self._status(key, od.report_date(rows, "出表日期"), len(rows))
            n += 1
        return n

    # -- TPEx OpenAPI --------------------------------------------------------------------------
    def tpex_indices(self) -> int:
        """tpex_index (櫃買指數 OHLC, this month) and tpex_reward_index (櫃買報酬指數 = ^TPEXTR, this month)."""
        idx = od.with_changes(od.parse_tpex_index(self._list(f"{TPEX_OPENAPI}/tpex_index")))
        n = self._indices(idx, "TPEX", "tpex-openapi")
        self._status("tpex-openapi/index", max((r["date"] for r in idx), default=None), len(idx))
        reward = od.parse_tpex_reward_index(self._list(f"{TPEX_OPENAPI}/tpex_reward_index"))
        tr = od.with_changes([r for r in reward if r["name"] == od.TPEX_TR])
        n += self._indices(tr, "TPEX", "tpex-openapi", ["close", "source"])
        # 櫃買指數 closes only fill days tpex_index did not have (it carries the OHLC)
        n += self._indices([r for r in reward if r["name"] == od.TPEX_INDEX], "TPEX", "tpex-openapi", ())
        self._status("tpex-openapi/total_return", max((r["date"] for r in tr), default=None), len(tr))
        return n

    def tpex_exright(self) -> int:
        """tpex_exright_daily: the official reference price and limits of today's ex-rights / ex-dividend stocks."""
        rows = [{"symbol": tw_symbol(r["code"], "TPEX"), "date": r["date"], "kind": r["kind"],
                 "prev_close": r["prev_close"], "ex_quote": r["ex_quote"], "reference_price": r["reference_price"],
                 "limit_up": r["limit_up"], "limit_down": r["limit_down"], "cash_dividend": r["cash_dividend"],
                 "stock_dividend": r["stock_dividend"], "source": "tpex-openapi"}
                for r in od.parse_tpex_exright_daily(self._list(f"{TPEX_OPENAPI}/tpex_exright_daily"))]
        n = upsert(self.db, ExRightsResult, rows, ["symbol", "date"])
        self._status("tpex-openapi/exright", max((r["date"] for r in rows), default=None), n)
        return n

    def tpex_revenue(self) -> int:
        rows = od.parse_monthly_revenue(self._list(f"{TPEX_OPENAPI}/mopsfin_t187ap05_O"), "TPEX")
        return self._revenue(rows, "tpex-openapi")

    def tpex_prices(self) -> int:
        from forliosa.marketdata.tpex import parse_daily_close_quotes

        raw = self._list(f"{TPEX_OPENAPI}/tpex_mainboard_daily_close_quotes")
        quotes = parse_daily_close_quotes(raw)
        rows = [{"symbol": s, "date": q.trade_date, "open": q.open, "high": q.high, "low": q.low, "close": q.price,
                 "volume": q.volume, "source": "tpex-openapi"}
                for s, q in quotes.items() if od.is_listed_code(s.split(".")[0])]
        n = upsert(self.db, PriceDaily, rows, ["symbol", "date"])
        refs = [{"symbol": tw_symbol(r["code"], "TPEX"),
                 "date": next_tw_trading_day(r["last_trading_day"] + timedelta(days=1)),
                 "reference_price": r["reference_price"], "limit_up": r["limit_up"], "limit_down": r["limit_down"],
                 "source": "tpex-openapi"} for r in od.parse_tpex_reference(raw)]
        return n + upsert(self.db, ReferencePrice, refs, ["symbol", "date"])

    def tpex_valuation(self) -> int:
        rows = [{"symbol": tw_symbol(r["code"], "TPEX"), "date": r["date"], "per": r["per"], "pbr": r["pbr"],
                 "dividend_yield": r["dividend_yield"], "source": "tpex-openapi"}
                for r in od.parse_tpex_peratio(self._list(f"{TPEX_OPENAPI}/tpex_mainboard_peratio_analysis"))]
        return upsert(self.db, ValuationDaily, rows, ["symbol", "date"])

    def tpex_chips(self) -> int:
        margin = [{"symbol": tw_symbol(r["code"], "TPEX"), "date": r["date"], "margin_balance": r["margin_balance"],
                   "short_balance": r["short_balance"], "margin_limit": r["margin_limit"], "source": "tpex-openapi"}
                  for r in od.parse_tpex_margin(self._list(f"{TPEX_OPENAPI}/tpex_mainboard_margin_balance"))]
        n = upsert(self.db, MarginDaily, margin, ["symbol", "date"])
        inst = [{"symbol": tw_symbol(r["code"], "TPEX"), "date": r["date"], "foreign_net": r["foreign_net"],
                 "trust_net": r["trust_net"], "dealer_net": r["dealer_net"], "total_net": r["total_net"],
                 "source": "tpex-openapi"}
                for r in od.parse_tpex_institutional(self._list(f"{TPEX_OPENAPI}/tpex_3insti_daily_trading"))]
        n += upsert(self.db, InstitutionalDaily, inst, ["symbol", "date"])
        qfii = [{"symbol": tw_symbol(r["code"], "TPEX"), "date": r["date"], "pct": r["pct"], "shares": r["shares"],
                 "source": "tpex-openapi"}
                for r in od.parse_tpex_qfii(self._list(f"{TPEX_OPENAPI}/tpex_3insti_qfii"))]
        return n + upsert(self.db, ForeignHoldingDaily, qfii, ["symbol", "date"])

    def tpex_events(self) -> int:
        n = self._ex_dividend_notices(
            od.parse_tpex_exright_events(self._list(f"{TPEX_OPENAPI}/tpex_exright_prepost")), "TPEX", "tpex-openapi")
        n += self._events(od.parse_tpex_warning(self._list(f"{TPEX_OPENAPI}/tpex_trading_warning_information")),
                          "tpex-openapi")
        n += self._events(od.parse_tpex_disposal(self._list(f"{TPEX_OPENAPI}/tpex_disposal_information")),
                          "tpex-openapi")
        n += self._events(od.parse_material_info(self._list(f"{TPEX_OPENAPI}/mopsfin_t187ap04_O"), "TPEX"),
                          "tpex-openapi")
        n += self._events(od.parse_shareholder_meetings(self._list(f"{TPEX_OPENAPI}/t187ap41_O"), "TPEX"),
                          "tpex-openapi")
        return n

    # -- financial statements (latest quarter) --------------------------------------------------
    def _reports(self, rows: list[dict[str, Any]], market: str, source: str) -> int:
        """Upsert statements; a value the new response leaves blank never erases an archived one.

        (Industries without TPEx companies return a single blank row: ``parse_statements`` skips it, so the job
        stores nothing and reports 0 rows instead of failing.)
        """
        out = [{"symbol": tw_symbol(r["code"], market), "period": r["period"], "kind": r["kind"],
                "values": r["values"], "source": source, "fetched_at": datetime.now(TAIPEI)} for r in rows]
        if not out:
            return 0
        symbols = {r["symbol"] for r in out}
        existing = {(f.symbol, f.period, f.kind): f.values for f in self.db.scalars(
            select(FinancialReport).where(FinancialReport.symbol.in_(symbols)))}
        for r in out:
            old = existing.get((r["symbol"], r["period"], r["kind"]))
            if old:
                r["values"] = {**old, **{k: v for k, v in r["values"].items() if v is not None}}
        return upsert(self.db, FinancialReport, out, ["symbol", "period", "kind"], ["values", "source", "fetched_at"])

    def financials(self) -> int:
        n = 0
        for ind in INDUSTRIES:
            n += self._run(f"twse t187ap06_L_{ind}", lambda ind=ind: self._reports(od.parse_statements(
                self._list(f"{TWSE_OPENAPI}/opendata/t187ap06_L_{ind}"), "income_ytd"), "TWSE", "twse-openapi"))
            n += self._run(f"twse t187ap07_L_{ind}", lambda ind=ind: self._reports(od.parse_statements(
                self._list(f"{TWSE_OPENAPI}/opendata/t187ap07_L_{ind}"), "balance"), "TWSE", "twse-openapi"))
            n += self._run(f"tpex t187ap06_O_{ind}", lambda ind=ind: self._reports(od.parse_statements(
                self._list(f"{TPEX_OPENAPI}/mopsfin_t187ap06_O_{ind}"), "income_ytd"), "TPEX", "tpex-openapi"))
            n += self._run(f"tpex t187ap07_O_{ind}", lambda ind=ind: self._reports(od.parse_statements(
                self._list(f"{TPEX_OPENAPI}/mopsfin_t187ap07_O_{ind}"), "balance"), "TPEX", "tpex-openapi"))
        n += self._run("twse t187ap17_L", lambda: self._reports(od.parse_profit_analysis(
            self._list(f"{TWSE_OPENAPI}/opendata/t187ap17_L")), "TWSE", "twse-openapi"))
        n += self._run("tpex 187ap17_O", lambda: self._reports(od.parse_profit_analysis(
            self._list(f"{TPEX_OPENAPI}/mopsfin_187ap17_O")), "TPEX", "tpex-openapi"))
        return n

    # -- TAIFEX OpenAPI (daily 21:40; open-data-inventory §12) -----------------------------------
    def taifex_futures(self) -> int:
        rows = [{**r, "source": tf.SOURCE} for r in tf.parse_futures_daily(self._taifex("DailyMarketReportFut"))]
        n = upsert(self.db, TaifexFuturesDaily, rows, ["trade_date", "session", "contract", "contract_month"])
        self._status("taifex-openapi/futures_daily", tf.latest_date(rows, "trade_date"), n)
        return n

    def taifex_options(self) -> int:
        rows = [{**r, "source": tf.SOURCE} for r in tf.parse_options_daily(self._taifex("DailyMarketReportOpt"))]
        n = upsert(self.db, TaifexOptionsDaily, rows,
                   ["trade_date", "session", "contract", "contract_month", "strike", "call_put"])
        self._status("taifex-openapi/options_daily", tf.latest_date(rows, "trade_date"), n)
        return n

    def taifex_institutional(self) -> int:
        n = 0
        for key, path, parse in (
            ("institutional_general", "MarketDataOfMajorInstitutionalTradersGeneralBytheDate",
             tf.parse_institutional_general),
            ("institutional_fut_opt", "MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate",
             tf.parse_institutional_fut_opt),
            ("institutional_futures", "MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate",
             lambda rows: tf.parse_institutional_contracts(rows, "futures")),
            ("institutional_options", "MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheDate",
             lambda rows: tf.parse_institutional_contracts(rows, "options")),
            ("institutional_calls_puts", "MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate",
             lambda rows: tf.parse_institutional_contracts(rows, "calls_puts")),
        ):
            rows = [{**r, "source": tf.SOURCE} for r in parse(self._taifex(path))]
            m = upsert(self.db, TaifexInstitutional, rows,
                       ["trade_date", "scope", "contract_name", "call_put", "investor"])
            self._status(f"taifex-openapi/{key}", tf.latest_date(rows, "trade_date"), m)
            n += m
        return n

    def taifex_large_traders(self) -> int:
        n = 0
        for kind, path in (("futures", "OpenInterestOfLargeTradersFutures"),
                           ("options", "OpenInterestOfLargeTradersOptions")):
            rows = [{**r, "source": tf.SOURCE} for r in tf.parse_large_traders(self._taifex(path), kind)]
            m = upsert(self.db, TaifexLargeTraders, rows,
                       ["trade_date", "kind", "contract", "call_put", "settlement_month", "trader_type"])
            self._status(f"taifex-openapi/large_traders_{kind}", tf.latest_date(rows, "trade_date"), m)
            if kind == "futures":
                n += upsert(self.db, TaifexContractMap, tf.contract_map_rows(large_traders=rows), ["name_zh"])
            n += m
        return n

    def taifex_put_call(self) -> int:
        """PutCallRatio carries about a month of days: upserted, so the first run backfills a month."""
        rows = [{**r, "source": tf.SOURCE} for r in tf.parse_put_call_ratio(self._taifex("PutCallRatio"))]
        n = upsert(self.db, TaifexPutCallRatio, rows, ["trade_date"])
        self._status("taifex-openapi/put_call_ratio", tf.latest_date(rows, "trade_date"), n)
        return n

    def taifex_fx(self) -> int:
        """DailyForeignExchangeRates (about six weeks per response) -> fx_rates (pair USDTWD …), upserted.
        Archived under every policy; served only when datapolicy.dataset_served("taifex-openapi/fx") allows."""
        rows = [{**r, "source": tf.SOURCE} for r in tf.parse_fx(self._taifex("DailyForeignExchangeRates"))]
        n = upsert(self.db, FxRate, rows, ["pair", "date"])
        self._status("taifex-openapi/fx", tf.latest_date(rows, "date"), n)
        return n

    def taifex_margins(self) -> int:
        """保證金一覽表: a row only when a contract's margins differ from the last archived ones."""
        n = 0
        for kind, key, path in (("index", "margins_index", "IndexFuturesAndOptionsMargining"),
                                ("stock", "margins_stock", "SingleStockFuturesMargining"),
                                ("etf", "margins_etf", "SingleStockFuturesETFMargining")):
            parsed = tf.parse_margins(self._taifex(path), kind)
            latest: dict[str, TaifexMargin] = {}
            for m in self.db.scalars(select(TaifexMargin).where(TaifexMargin.kind == kind)
                                     .order_by(TaifexMargin.date)):
                latest[m.contract] = m
            changed = []
            for r in parsed:
                old = latest.get(r["contract"])
                if old is not None and (old.clearing, old.maintenance, old.initial, old.group_level) == (
                        r["clearing"], r["maintenance"], r["initial"], r["group_level"]):
                    continue
                changed.append({**r, "source": tf.SOURCE})
            n += upsert(self.db, TaifexMargin, changed, ["kind", "contract", "date"])
            self._status(f"taifex-openapi/{key}", tf.latest_date(parsed, "date"), len(parsed))
            if kind == "stock":
                upsert(self.db, TaifexContractMap, tf.contract_map_rows(margins=parsed), ["name_zh"])
        return n

    def taifex_final_settlement(self) -> int:
        rows = [{**r, "source": tf.SOURCE} for r in tf.parse_final_settlement(self._taifex("FinalSettlementPrice"))]
        n = upsert(self.db, TaifexFinalSettlement, rows, ["contract", "delivery_month"])
        self._status("taifex-openapi/final_settlement", tf.latest_date(rows, "settlement_day"), n)
        return n

    def taifex_underlyings(self) -> int:
        today = self.now_fn().astimezone(TAIPEI).date()
        n = 0
        for kind, key, path in (("SSF", "ssf_list", "SSFLists"), ("SSO", "sso_list", "SSOLists")):
            rows = [{**r, "first_seen": today, "last_seen": today, "source": tf.SOURCE}
                    for r in tf.parse_underlyings(self._taifex(path), kind)]
            m = upsert(self.db, TaifexUnderlying, rows, ["kind", "contract"],
                       ["stock_code", "stock_name", "type", "last_seen", "source"])
            self._status(f"taifex-openapi/{key}", today if rows else None, m)
            n += m
        return n

    # -- TDCC (weekly) ---------------------------------------------------------------------------
    def tdcc(self) -> int:
        raw = self.fetcher.get_bytes(TDCC_URL, params={"id": "1-5"}).decode("utf-8-sig", errors="replace")
        parsed = od.parse_tdcc_distribution(raw)
        market = {}  # code -> market, from the instrument master when available
        try:
            from forliosa.marketdata.service import get_market_data

            for info in get_market_data().master().values():
                market[info.code] = info.market
        except Exception:  # pragma: no cover - master is best effort here
            market = {}
        rows = [{"symbol": tw_symbol(r["code"], market.get(r["code"], "TWSE")), "date": r["date"],
                 "level": r["level"], "holders": r["holders"], "shares": r["shares"], "pct": r["pct"],
                 "source": "tdcc-opendata"}
                for r in parsed if not market or r["code"] in market]
        return upsert(self.db, ShareholdingDistribution, rows, ["symbol", "date", "level"])

    # -- SEC EDGAR (US stocks) -------------------------------------------------------------------
    def sec_edgar(self, client: Any) -> int:
        """Ticker map, company facts and filings of every tracked US stock (forliosa.services.sec). A refusal from
        SEC (403 / 429 / redirect) ends the job with an error; it is not retried until the next run."""
        from forliosa.marketdata.base import market_of_symbol
        from forliosa.services import sec as sec_svc

        symbols = sec_svc.us_stock_symbols([s for s in tracked_symbols(self.db) if market_of_symbol(s) == "US"])
        counts = sec_svc.sync_symbols(self.db, client, symbols)
        for key, d in sec_svc.latest_data_dates(self.db).items():
            self._status(key, d, counts["companies"] if key.endswith("companyfacts") else counts["filings"])
        log.info("sec edgar: %s", counts)
        return counts["tickers"] + counts["companies"] + counts["filings"]

    # -- entry points ----------------------------------------------------------------------------
    def run(self, only: Iterable[str] | None = None) -> list[JobResult]:
        groups = set(only or JOB_GROUPS)
        if "twse" in groups:
            for name, fn in (("twse prices", self.twse_prices), ("twse valuation", self.twse_valuation),
                             ("twse reference", self.twse_reference), ("twse margin", self.twse_margin),
                             ("twse events", self.twse_events), ("twse revenue", self.twse_revenue),
                             ("twse news", self.twse_news), ("twse funds", self.twse_funds),
                             ("twse holidays", self.twse_holidays),
                             ("twse total return MFI94U", self.twse_total_return),
                             ("twse indices MI_INDEX", self.twse_indices)):
                self._run(name, fn)
        if "tpex" in groups:
            for name, fn in (("tpex prices", self.tpex_prices), ("tpex valuation", self.tpex_valuation),
                             ("tpex chips", self.tpex_chips), ("tpex events", self.tpex_events),
                             ("tpex revenue", self.tpex_revenue), ("tpex indices", self.tpex_indices),
                             ("tpex exright", self.tpex_exright)):
                self._run(name, fn)
        if "companies" in groups:
            for name, fn in (("twse dividends t187ap45_L", self.twse_dividends),
                             ("twse companies t187ap03_L", self.twse_companies),
                             ("tpex companies t187ap03_O", self.tpex_companies)):
                self._run(name, fn)
        if "financials" in groups:
            self.financials()
        if "taifex" in groups:
            for name, fn in (("taifex futures", self.taifex_futures), ("taifex options", self.taifex_options),
                             ("taifex institutional", self.taifex_institutional),
                             ("taifex large traders", self.taifex_large_traders),
                             ("taifex put/call", self.taifex_put_call), ("taifex fx", self.taifex_fx),
                             ("taifex margins", self.taifex_margins)):
                self._run(name, fn)
        if "tdcc" in groups:
            self._run("tdcc distribution", self.tdcc)
        if "weekly" in groups:
            for name, fn in (("taifex final settlement", self.taifex_final_settlement),
                             ("taifex SSF/SSO lists", self.taifex_underlyings),
                             ("stale endpoints check", self.stale_check)):
                self._run(name, fn)
        if "sec" in groups:
            from forliosa.services import sec as sec_svc

            client = self.sec_client or sec_svc.sec_client(on_demand=False)
            if client is None:
                self.results.append(JobResult(SEC_DISABLED))
            else:
                self._run("sec edgar", lambda: self.sec_edgar(client))
        return self.results

    def backfill(self, days: int = 90, symbols: list[str] | None = None,
                 providers: Iterable[str] = ()) -> list[JobResult]:
        """FinMind per symbol — only under an explicit personal opt-in (policy personal *and* ``finmind`` in
        MARKET_DATA_PROVIDERS). There is no commercially usable history source to backfill from."""
        if self.policy != "personal" or "finmind" not in {p.strip().lower() for p in providers}:
            log.info("backfill: needs DATA_POLICY=personal and finmind in MARKET_DATA_PROVIDERS "
                     "(non-commercial opt-in); nothing to do")
            return self.results
        today = self.now_fn().astimezone(TAIPEI).date()
        symbols = symbols if symbols is not None else tracked_symbols(self.db)
        start = today - timedelta(days=days)
        self._run("finmind chips", lambda: finmind_backfill(self.db, symbols, start))
        return self.results


def finmind_backfill(db: Session, symbols: list[str], start: date) -> int:
    """FinMind (personal only): margin, institutional, foreign holding, PER — only where nothing is archived."""
    from forliosa.config import get_settings
    from forliosa.marketdata.finmind import FinMindProvider

    settings = get_settings()
    fm = FinMindProvider(settings.finmind_token, HttpFetcher(timeout=20, retries=0), cache_dir=settings.cache_dir)
    n = 0
    for sym in symbols:
        if sym.endswith((".TW", ".TWO")) is False:
            continue
        try:
            chips = fm.chips(sym, start)
        except ProviderUnavailable as exc:
            log.warning("finmind backfill stopped at %s: %s", sym, exc)
            break
        n += upsert(db, MarginDaily, [{**r, "symbol": sym, "source": "finmind"} for r in chips["margin"]],
                    ["symbol", "date"], ())
        n += upsert(db, InstitutionalDaily, [{**r, "symbol": sym, "source": "finmind"} for r in chips["institutional"]],
                    ["symbol", "date"], ())
        n += upsert(db, ForeignHoldingDaily, [{**r, "symbol": sym, "source": "finmind"} for r in chips["foreign"]],
                    ["symbol", "date"], ())
        _time.sleep(0.3)
    return n


def default_fetcher() -> HttpFetcher:
    # Large files (TWT84U ≈ 12 MB, TPEx close quotes ≈ 5 MB); openapi.twse.com.tw resets connections
    # now and then, so retry. Requests to the same host stay ≥ 0.5 s apart (shared limiter).
    return HttpFetcher(timeout=90, retries=2, backoff=2.0)


def main(argv: list[str] | None = None) -> None:
    from forliosa.config import get_settings
    from forliosa.db import session_factory

    parser = argparse.ArgumentParser(description="官方開放資料存檔（證交所、櫃買中心、期交所、集保、SEC EDGAR）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="執行一次每日存檔")
    run_p.add_argument("--only", default="", help=f"逗號分隔：{','.join(JOB_GROUPS)}")
    back_p = sub.add_parser("backfill", help="FinMind 回補（非商用；僅 DATA_POLICY=personal 且明確列出 finmind）")
    back_p.add_argument("--days", type=int, default=90)
    back_p.add_argument("--symbols", default="", help="逗號分隔；預設為所有持股與自選")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    with session_factory()() as db:
        arch = Archiver(db, default_fetcher(), settings.data_policy)
        if args.cmd == "run":
            only = [s.strip() for s in args.only.split(",") if s.strip()] or None
            results = arch.run(only)
        else:
            syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
            results = arch.backfill(args.days, syms, settings.market_data_providers)
    for r in results:
        status = f"錯誤：{r.error}" if r.error else f"{r.rows} 筆"
        print(f"  {r.name:<28} {status}")


if __name__ == "__main__":
    main()
