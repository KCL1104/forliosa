"""Daily archive of official open data (the OpenAPIs only serve the latest day, so we keep history).

Run once from the command line::

    uv run python -m forliosa.archive run                    # every job that applies to DATA_POLICY
    uv run python -m forliosa.archive run --only twse,tpex   # twse | tpex | financials | tdcc | web
    uv run python -m forliosa.archive backfill --days 90     # see "Backfill" below

The worker runs the same jobs on a schedule (``forliosa.worker``). Every write is an upsert keyed on
(symbol, date[, level]) or an announcement key, so running a job twice changes nothing.

What is archived, and from where (field names: ``forliosa.marketdata.opendata``):

==========================  ===================================================  ==========================
table                       commercial-usable source                             personal-only extra
==========================  ===================================================  ==========================
prices_daily                TWSE STOCK_DAY_ALL, TPEx daily_close_quotes          FinMind TaiwanStockPrice
valuation_daily             TWSE BWIBBU_ALL, TPEx peratio_analysis               FinMind TaiwanStockPER
reference_prices            TWSE TWT84U, TPEx NextReferencePrice/NextLimit*      —
margin_daily                TWSE MI_MARGN, TPEx margin_balance                   FinMind margin (backfill)
institutional_daily         TPEx 3insti_daily_trading (no TWSE OpenAPI dataset)  TWSE website T86, FinMind
foreign_holding_daily       TPEx 3insti_qfii (no per-stock TWSE OpenAPI dataset) TWSE website MI_QFIIS
shareholding_distribution   TDCC open data 1-5 (weekly, current week only)       —
market_events               TWT48U_ALL / exright_prepost (除權息), notice / warning
                            (注意), punish / disposal (處置), t187ap04 (重大訊息),
                            t187ap41 (股東會)                                       —
financial_reports           t187ap06 (income, YTD), t187ap07 (balance), t187ap17  —
==========================  ===================================================  ==========================

Backfill: there is no official per-stock history API, so under ``commercial`` the archive only grows
from the day the worker starts. Under ``personal`` ``backfill`` fills the past from the TWSE website
(T86, MI_QFIIS by date — whole market per request) and FinMind (per symbol, tiny anonymous quota:
it stops at the first 402 and keeps what it has). Backfilled rows never overwrite official rows.
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
from forliosa.marketdata.base import ProviderUnavailable, tw_symbol
from forliosa.marketdata.http import HttpFetcher
from forliosa.marketdata.twse import parse_bwibbu_all, parse_stock_day_all
from forliosa.models import (
    FinancialReport,
    ForeignHoldingDaily,
    HoldingSnapshot,
    InstitutionalDaily,
    MarginDaily,
    MarketEvent,
    PriceDaily,
    ReferencePrice,
    ShareholdingDistribution,
    Transaction,
    ValuationDaily,
    WatchlistItem,
)
from forliosa.timeutil import TAIPEI, last_tw_trading_day, next_tw_trading_day, now_taipei, tw_trading_days

log = logging.getLogger("forliosa.archive")

TWSE_OPENAPI = "https://openapi.twse.com.tw/v1"
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1"
TWSE_WEB = "https://www.twse.com.tw/rwd/zh"
TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx"
INDUSTRIES = ("ci", "basi", "bd", "fh", "ins", "mim")
# TWSE publishes the day's margin balances in the evening; before this time MI_MARGN is the previous day's.
MARGIN_READY = time(21, 0)

JOB_GROUPS = ("twse", "tpex", "financials", "tdcc", "web")


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

    def _events(self, rows: list[dict[str, Any]], source: str) -> int:
        out = [{"key": r["key"], "symbol": tw_symbol(r["code"], r["market"]), "date": r["date"],
                "end_date": r["end_date"], "type": r["type"], "title": r["title"][:500], "detail": r["detail"],
                "url": None, "data": r["data"], "source": source} for r in rows]
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
        n = self._events(od.parse_twt48u_events(self._list(f"{TWSE_OPENAPI}/exchangeReport/TWT48U_ALL")),
                         "twse-openapi")
        n += self._events(od.parse_twse_notice(self._list(f"{TWSE_OPENAPI}/announcement/notice")), "twse-openapi")
        n += self._events(od.parse_twse_punish(self._list(f"{TWSE_OPENAPI}/announcement/punish")), "twse-openapi")
        n += self._events(od.parse_material_info(self._list(f"{TWSE_OPENAPI}/opendata/t187ap04_L"), "TWSE"),
                          "twse-openapi")
        n += self._events(od.parse_shareholder_meetings(self._list(f"{TWSE_OPENAPI}/opendata/t187ap41_L"), "TWSE"),
                          "twse-openapi")
        return n

    # -- TPEx OpenAPI --------------------------------------------------------------------------
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
        n = self._events(od.parse_tpex_exright_events(self._list(f"{TPEX_OPENAPI}/tpex_exright_prepost")),
                         "tpex-openapi")
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
        out = [{"symbol": tw_symbol(r["code"], market), "period": r["period"], "kind": r["kind"],
                "values": r["values"], "source": source, "fetched_at": datetime.now(TAIPEI)} for r in rows]
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

    # -- TWSE website (personal policy only) ----------------------------------------------------
    def twse_web_day(self, d: date, only_missing: bool = False) -> int:
        if self.policy != "personal":
            return 0
        ds = d.strftime("%Y%m%d")
        params = {"date": ds, "selectType": "ALLBUT0999", "response": "json"}
        inst = [{"symbol": tw_symbol(r["code"], "TWSE"), "date": r["date"], "foreign_net": r["foreign_net"],
                 "trust_net": r["trust_net"], "dealer_net": r["dealer_net"], "total_net": r["total_net"],
                 "source": "twse-web"} for r in od.parse_t86(self._json(f"{TWSE_WEB}/fund/T86", params))]
        n = upsert(self.db, InstitutionalDaily, inst, ["symbol", "date"], () if only_missing else None)
        qfii = [{"symbol": tw_symbol(r["code"], "TWSE"), "date": r["date"], "pct": r["pct"], "shares": r["shares"],
                 "source": "twse-web"} for r in od.parse_mi_qfiis(self._json(f"{TWSE_WEB}/fund/MI_QFIIS", params))]
        return n + upsert(self.db, ForeignHoldingDaily, qfii, ["symbol", "date"], () if only_missing else None)

    # -- entry points ----------------------------------------------------------------------------
    def run(self, only: Iterable[str] | None = None) -> list[JobResult]:
        groups = set(only or JOB_GROUPS)
        if "twse" in groups:
            for name, fn in (("twse prices", self.twse_prices), ("twse valuation", self.twse_valuation),
                             ("twse reference", self.twse_reference), ("twse margin", self.twse_margin),
                             ("twse events", self.twse_events)):
                self._run(name, fn)
        if "tpex" in groups:
            for name, fn in (("tpex prices", self.tpex_prices), ("tpex valuation", self.tpex_valuation),
                             ("tpex chips", self.tpex_chips), ("tpex events", self.tpex_events)):
                self._run(name, fn)
        if "financials" in groups:
            self.financials()
        if "tdcc" in groups:
            self._run("tdcc distribution", self.tdcc)
        if "web" in groups and self.policy == "personal":
            now = self.now_fn().astimezone(TAIPEI)
            d = last_tw_trading_day(now.date() if now.time() >= time(17, 0) else now.date() - timedelta(days=1))
            self._run(f"twse web {d}", lambda: self.twse_web_day(d))
        return self.results

    def backfill(self, days: int = 90, symbols: list[str] | None = None) -> list[JobResult]:
        """Personal policy only: TWSE website history by date, then FinMind per symbol."""
        if self.policy != "personal":
            log.info("backfill: DATA_POLICY=commercial has no official history source; nothing to do")
            return self.results
        today = self.now_fn().astimezone(TAIPEI).date()
        have = set(self.db.scalars(select(InstitutionalDaily.date).where(InstitutionalDaily.source == "twse-web")
                                   .distinct()))
        have &= set(self.db.scalars(select(ForeignHoldingDaily.date).where(ForeignHoldingDaily.source == "twse-web")
                                    .distinct()))
        for d in tw_trading_days(today - timedelta(days=days), today - timedelta(days=1)):
            if d not in have:
                self._run(f"twse web {d}", lambda d=d: self.twse_web_day(d, only_missing=True))
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

    parser = argparse.ArgumentParser(description="官方開放資料存檔（證交所、櫃買中心、集保）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="執行一次每日存檔")
    run_p.add_argument("--only", default="", help=f"逗號分隔：{','.join(JOB_GROUPS)}")
    back_p = sub.add_parser("backfill", help="回補歷史（僅 DATA_POLICY=personal）")
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
            results = arch.backfill(args.days, syms)
    for r in results:
        status = f"錯誤：{r.error}" if r.error else f"{r.rows} 筆"
        print(f"  {r.name:<28} {status}")


if __name__ == "__main__":
    main()
