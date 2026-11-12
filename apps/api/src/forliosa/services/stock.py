"""Stock page (個股頁): overview, intraday, chips, financials, events, news, position and "why it moved".

Every response lists its ``sources`` (labels from :mod:`forliosa.datapolicy`; non-commercial ones end
with 「非商用」). Archive tables are read with the policy's source filter, so under
``DATA_POLICY=commercial`` rows that came from FinMind or the TWSE website are never served.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import unprocessable
from forliosa.datapolicy import labels, source_clause, tagged
from forliosa.marketdata.base import InstrumentInfo, QuoteData
from forliosa.marketdata.demo import report_publication_date
from forliosa.marketdata.opendata import TDCC_LEVELS
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    ForeignHoldingDaily,
    InstitutionalDaily,
    MarginDaily,
    MarketEvent,
    ShareholdingDistribution,
    User,
)
from forliosa.services.announcements import classify
from forliosa.services.instruments import change_base, require_instrument
from forliosa.services.portfolio import (
    PortfolioState,
    add_months,
    closed_rounds,
    compute_state,
    ledger_view,
    range_start,
    round_out,
)
from forliosa.timeutil import (
    TAIPEI,
    iso_taipei,
    last_tw_trading_day,
    today_taipei,
    tw_trading_days,
)

CHIPS_RANGES = ("1M", "3M", "6M", "1Y")
LISTED_CHIPS_NOTE = ("證交所 OpenAPI 沒有上市股票的個股三大法人與外資持股（證交所以付費商品提供），目前不提供；"
                     "上櫃股票由櫃買中心 OpenAPI 每日存檔")
FINANCIAL_PERIODS = ("quarterly", "annual")
EVENT_PAST_DAYS = 365
EVENT_FUTURE_DAYS = 120
DEADLINE_PAST_DAYS = 90
DEADLINE_FUTURE_DAYS = 60
WHY_MOVE_PCT = Decimal("0.03")
WHY_VOLUME_MULTIPLE = Decimal(2)
EARNINGS_WORDS = ("財務報告", "財報", "自結損益", "合併財務")
REVENUE_WORDS = ("營收", "營業收入")


def _filtered(stmt, model, md: MarketData):
    return stmt.where(source_clause(model.source, md.policy))


def _split(source: str) -> list[str]:
    return [s for s in (source or "").split("+") if s]


def _is_tw_stock(info: InstrumentInfo) -> bool:
    return info.market != "US" and info.type == "stock"


# -- status (注意／處置) ------------------------------------------------------------------------------
def trading_status(db: Session, md: MarketData, symbol: str, today: date | None = None) -> tuple[dict, list[str]]:
    today = today or today_taipei()
    since = last_tw_trading_day(today - timedelta(days=1))
    stmt = select(MarketEvent).where(MarketEvent.symbol == symbol, MarketEvent.type.in_(("attention", "disposition")),
                                     MarketEvent.date >= today - timedelta(days=40))
    rows = list(db.scalars(_filtered(stmt, MarketEvent, md)))
    attention = [r for r in rows if r.type == "attention" and since <= r.date <= today]
    disposition = [r for r in rows if r.type == "disposition" and r.date <= today <= (r.end_date or r.date)]
    notes = []
    if disposition:
        d = disposition[-1]
        period = f"{d.date:%m/%d}–{d.end_date:%m/%d}" if d.end_date else f"{d.date:%m/%d} 起"
        notes.append(f"{d.title}，處置期間 {period}")
    if attention:
        info = attention[-1].detail.strip()
        notes.append("列為注意股票" + (f"：{info[:80]}" if info else ""))
    status = {"attention": bool(attention), "disposition": bool(disposition), "note": "；".join(notes) or None}
    return status, [f"{r.source}/{r.type}" for r in attention + disposition]


# -- overview -------------------------------------------------------------------------------------------
def overview(db: Session, md: MarketData, symbol: str) -> dict[str, Any]:
    info = require_instrument(md, symbol)
    sym = info.symbol
    today = today_taipei()
    q = md.quote(sym)
    hist = md.history(sym, today - timedelta(days=400), today)
    year = [c for c in hist.candles if c.t > today - timedelta(days=365)]
    three_m = [c for c in hist.candles if c.t >= add_months(today, -3)]
    prof = md.profile(sym)
    price = q.price if q else (hist.candles[-1].c if hist.candles else None)
    sources: list[str] = [*(tagged(q.source, "price") if q else []), *tagged(hist.source, "price")]
    is_demo = bool(q and q.is_demo) or hist.is_demo or prof.is_demo

    market_cap = prof.market_cap
    if market_cap is None and prof.shares_outstanding and price is not None:
        market_cap = Decimal(prof.shares_outstanding) * price

    pe = pb = dy = None
    if info.market != "US":
        ratios, rsrc = md.valuation_ratios_with_source(sym, today - timedelta(days=30), today)
        if ratios:
            latest = ratios[max(ratios)]
            pe, pb, dy = latest.get("per"), latest.get("pbr"), latest.get("dividend_yield")
            sources += tagged(rsrc, "valuation")

    eps_ttm = None
    shares_outstanding = prof.shares_outstanding
    if info.market == "US" and info.type == "stock":  # SEC EDGAR cache (diluted EPS, cover-page shares)
        from forliosa.services import sec as sec_svc

        key = sec_svc.cached_key_data(db, sym)
        eps_ttm = key["eps_ttm"]
        shares_outstanding = shares_outstanding or key["shares_outstanding"]
        sources += key["sources"]
    if _is_tw_stock(info):
        st = md.statements(sym)
        quarters = _quarterly_table(st.value) if st else {}
        last4 = [quarters[p]["eps"] for p in sorted(quarters)[-4:]]
        if len(last4) == 4 and all(v is not None for v in last4):
            eps_ttm = sum((v for v in last4 if v is not None), Decimal(0))
            sources.append(st.source)  # type: ignore[union-attr]
        vi = md.valuation_inputs(sym) if eps_ttm is None else None
        if vi is not None:
            last4 = [x for x in vi.value if x.eps is not None][-4:]
            if len(last4) == 4:
                eps_ttm = sum((x.eps for x in last4 if x.eps is not None), Decimal(0))
                is_demo |= vi.is_demo
                sources += _split(vi.source)
        if eps_ttm is None and pe and price is not None:
            eps_ttm = price / pe

    divs = md.dividends(sym)
    cash_events = [e for e in divs.value if e.ex_dividend_date and e.cash_dividend > 0]
    last_div = max(cash_events, key=lambda e: e.ex_dividend_date) if cash_events else None
    if cash_events:  # only ex-dated cash dividends are used here (resolutions without an ex-date are not)
        is_demo |= divs.is_demo
        sources += ["demo"] if divs.is_demo else tagged(divs.source, "ex_dividend")
    if dy is None and price:
        trailing = sum((e.cash_dividend for e in cash_events
                        if today - timedelta(days=365) < e.ex_dividend_date <= today), Decimal(0))
        dy = trailing / price if trailing else None

    status, status_sources = trading_status(db, md, sym, today)
    sources += status_sources
    for s in prof.data_sources:
        if s.startswith("shioaji-data"):
            if "AI" not in s:
                sources.append("shioaji-data")
        else:
            sources.append(s)
    return {
        "symbol": sym,
        "open": ser.price(q.open) if q else None,
        "high": ser.price(q.high) if q else None,
        "low": ser.price(q.low) if q else None,
        "prev_close": ser.price(q.prev_close) if q else None,
        "reference_price": ser.price(q.reference_price) if q else None,
        "limit_up": ser.price(q.limit_up) if q else None,
        "limit_down": ser.price(q.limit_down) if q else None,
        "volume": q.volume if q else None,
        "avg_volume_3m": int(sum(c.v for c in three_m) / len(three_m)) if three_m else None,
        "market_cap": ser.money(market_cap),
        "pe": ser.price(pe),
        "pb": ser.price(pb),
        "dividend_yield": ser.ratio(dy),
        "last_cash_dividend": ser.price(last_div.cash_dividend) if last_div else None,
        "ex_dividend_date": last_div.ex_dividend_date if last_div else None,
        "eps_ttm": ser.price(eps_ttm),
        "high_52w": ser.price(max(c.h for c in year)) if year else None,
        "low_52w": ser.price(min(c.l for c in year)) if year else None,
        "shares_outstanding": shares_outstanding,
        "listed_date": prof.listed_date,
        "status": status,
        "as_of": iso_taipei(q.as_of) if q and q.as_of else None,
        "sources": labels(sources),
        "is_demo": is_demo,
    }


# -- intraday -------------------------------------------------------------------------------------------
INTRADAY_NOTE = "目前沒有授權的盤中行情來源（證交所即時／延遲行情需付費授權），不提供分時走勢"


def intraday(md: MarketData, symbol: str) -> dict[str, Any]:
    """No points in any mode until a licensed intraday source exists (MIS was removed, see CONTRACT_NOTES)."""
    info = require_instrument(md, symbol)
    sym = info.symbol
    q = md.quote(sym)
    day = q.trade_date if q and q.trade_date else last_tw_trading_day(today_taipei())
    return {
        "symbol": sym,
        "date": day,
        "prev_close": ser.price(q.prev_close) if q else None,
        "reference_price": ser.price(change_base(q)) if q else None,
        "points": [],
        "is_partial": info.market != "US",
        "notes": ["美股沒有盤中走勢資料"] if info.market == "US" else [INTRADAY_NOTE],
        "sources": [],
        "is_demo": False,
    }


# -- chips ----------------------------------------------------------------------------------------------
def chips(db: Session, md: MarketData, symbol: str, range_: str) -> dict[str, Any]:
    if range_ not in CHIPS_RANGES:
        raise unprocessable(f"不支援的區間：{range_}（可用 {'、'.join(CHIPS_RANGES)}）")
    info = require_instrument(md, symbol)
    sym = info.symbol
    empty = {"symbol": sym, "institutional": [], "margin": [], "foreign_holding_pct": [], "major_holders": None,
             "sources": [], "notes": []}
    if info.market == "US":
        return {**empty, "notes": ["美股沒有籌碼資料"]}
    today = today_taipei()
    start = range_start(range_, today, date(1990, 1, 1))

    def rows(model):
        stmt = select(model).where(model.symbol == sym, model.date >= start, model.date <= today)
        return list(db.scalars(_filtered(stmt, model, md).order_by(model.date)))

    # Listed (TWSE) stocks: no per-stock 三大法人 / 外資持股 in any mode (owner, 2026-11-12) — TWSE's OpenAPI has no
    # such dataset and its website may not be downloaded by program; FinMind only mirrors that website, so those
    # datasets are not even requested from it (margin only).
    listed = info.market == "TWSE"
    inst = {} if listed else {r.date: r for r in rows(InstitutionalDaily)}
    margin = {r.date: r for r in rows(MarginDaily)}
    foreign = {} if listed else {r.date: r for r in rows(ForeignHoldingDaily)}
    sources = [*tagged([r.source for r in inst.values()], "institutional"),
               *tagged([r.source for r in margin.values()], "margin"),
               *tagged([r.source for r in foreign.values()], "foreign_holding")]
    notes: list[str] = []

    expected = len(tw_trading_days(start, today)) * 0.8
    fm = md.provider("finmind") if md.policy == "personal" else None
    wanted = (("margin", margin),) if listed else (("institutional", inst), ("margin", margin), ("foreign", foreign))
    if fm is not None and min(len(target) for _, target in wanted) < expected:
        try:
            extra = fm.chips(sym, start, datasets=[key for key, _ in wanted])  # type: ignore[attr-defined]
        except Exception:  # FinMind quota or network: serve what the archive has
            extra = None
            notes.append("FinMind 暫時無法使用，只顯示已存檔的資料")
        if extra:
            for key, target in wanted:
                for r in extra[key]:
                    if r["date"] not in target and start <= r["date"] <= today:
                        target[r["date"]] = _Row(**r, source="finmind")
                        sources.append("finmind")
    if listed:
        notes.append(LISTED_CHIPS_NOTE)

    def lots(shares: int | None) -> float | None:
        return ser.price(Decimal(shares) / 1000) if shares is not None else None

    tdcc_date = db.scalar(_filtered(select(ShareholdingDistribution.date).where(
        ShareholdingDistribution.symbol == sym), ShareholdingDistribution, md)
        .order_by(ShareholdingDistribution.date.desc()).limit(1))
    major = None
    if tdcc_date is not None:
        buckets = list(db.scalars(_filtered(select(ShareholdingDistribution).where(
            ShareholdingDistribution.symbol == sym, ShareholdingDistribution.date == tdcc_date,
            ShareholdingDistribution.level <= 15), ShareholdingDistribution, md)
            .order_by(ShareholdingDistribution.level)))
        major = {"as_of": tdcc_date, "buckets": [
            {"level": b.level, "label": TDCC_LEVELS.get(b.level, str(b.level)), "holders": b.holders,
             "shares": b.shares, "pct": ser.ratio(b.pct)} for b in buckets]}
        sources += tagged([b.source for b in buckets[:1]], "distribution")
    return {
        "symbol": sym,
        "institutional": [{"t": d, "foreign": lots(r.foreign_net), "trust": lots(r.trust_net),
                           "dealer": lots(r.dealer_net), "total": lots(r.total_net)}
                          for d, r in sorted(inst.items())],
        "margin": [{"t": d, "margin_balance": r.margin_balance, "short_balance": r.short_balance}
                   for d, r in sorted(margin.items())],
        "foreign_holding_pct": [{"t": d, "pct": ser.ratio(r.pct)} for d, r in sorted(foreign.items())],
        "major_holders": major,
        "sources": labels(sources),
        "notes": notes,
    }


class _Row:
    def __init__(self, source: str, **kw: Any):
        self.source = source
        for k, v in kw.items():
            setattr(self, k, v)


# -- financials -----------------------------------------------------------------------------------------
_LINE_ITEMS = {
    "revenue": (("營業收入",), ("淨收益",), ("收益合計",)),
    "gross_profit": (("營業毛利（毛損）淨額",), ("營業毛利（毛損）",)),
    "operating_income": (("營業利益（損失）",),),
    "net_income": (("淨利（淨損）歸屬於母公司業主",), ("本期淨利（淨損）",), ("本期稅後淨利（淨損）",)),
    "eps": (("基本每股盈餘（元）",), ("基本每股盈餘",)),
    "total_assets": (("資產總計",), ("資產總額",)),
    "total_liabilities": (("負債總計",), ("負債總額",)),
    "equity": (("權益總計",), ("權益總額",)),
    "operating": (("營業活動之淨現金流入（流出）",),),
    "investing": (("投資活動之淨現金流入（流出）",),),
    "financing": (("籌資活動之淨現金流入（流出）",),),
}
_ARCHIVE_KEYS = {"revenue": "revenue", "gross_profit": "gross_profit", "operating_income": "operating_income",
                 "net_income": "net_income_parent", "eps": "eps", "total_assets": "total_assets",
                 "total_liabilities": "total_liabilities", "equity": "equity"}


def _series(table: dict[str, list], item: str, n: int) -> list[Decimal | None]:
    for keys in _LINE_ITEMS[item]:
        for k in keys:
            if k in table:
                return [_dec(v) for v in (table[k] + [None] * n)[:n]]
    return [None] * n


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except ArithmeticError:
        return None


def _quarterly_table(st: dict[str, Any]) -> dict[str, dict[str, Decimal | None]]:
    periods = [str(p) for p in st.get("periods") or []]
    n = len(periods)
    inc, bal, cf = st.get("income_quarter") or {}, st.get("balance") or {}, st.get("cash_flow_quarter") or {}
    cols = {item: _series(inc, item, n) for item in ("revenue", "gross_profit", "operating_income", "net_income",
                                                     "eps")}
    cols |= {item: _series(bal, item, n) for item in ("total_assets", "total_liabilities", "equity")}
    cols |= {item: _series(cf, item, n) for item in ("operating", "investing", "financing")}
    ytd = st.get("income_ytd") or {}
    cols |= {f"ytd_{item}": _series(ytd, item, n) for item in ("revenue", "gross_profit", "operating_income",
                                                                "net_income", "eps")}
    return {p: {k: v[i] for k, v in cols.items()} for i, p in enumerate(periods)}


def _prev_quarter(period: str) -> str:
    y, q = int(period[:4]), int(period[-1])
    return f"{y}Q{q - 1}" if q > 1 else f"{y - 1}Q4"


def _add_archived_quarters(db: Session, md: MarketData, sym: str,
                           table: dict[str, dict[str, Decimal | None]]) -> list[str]:
    """Latest-quarter OpenAPI statements (income is year-to-date) -> extra quarters shioaji-data lacks."""
    from forliosa.models import FinancialReport

    stmt = select(FinancialReport).where(FinancialReport.symbol == sym)
    reports = list(db.scalars(_filtered(stmt, FinancialReport, md)))
    by_period: dict[str, dict[str, dict]] = defaultdict(dict)
    sources: dict[str, str] = {}
    for r in reports:
        by_period[r.period][r.kind] = r.values
        sources[r.period] = r.source
    used = []
    for period in sorted(by_period):
        if period in table:
            continue
        kinds = by_period[period]
        row: dict[str, Decimal | None] = dict.fromkeys(_LINE_ITEMS)
        income = kinds.get("income_ytd") or {}
        prev = table.get(_prev_quarter(period)) if not period.endswith("Q1") else None
        for item in ("revenue", "gross_profit", "operating_income", "net_income", "eps"):
            ytd = _dec(income.get(_ARCHIVE_KEYS[item]) or (income.get("net_income") if item == "net_income" else None))
            row[f"ytd_{item}"] = ytd
            if period.endswith("Q1"):
                row[item] = ytd
            elif prev is not None and ytd is not None and prev.get(f"ytd_{item}") is not None:
                row[item] = ytd - prev[f"ytd_{item}"]  # type: ignore[operator]
        balance = kinds.get("balance") or {}
        for item in ("total_assets", "total_liabilities", "equity"):
            row[item] = _dec(balance.get(_ARCHIVE_KEYS[item]))
        if any(v is not None for v in row.values()):
            table[period] = row
            used.append(f"{sources[period]}/income")
    return used


def financials(db: Session, md: MarketData, symbol: str, period: str) -> dict[str, Any]:
    if period not in FINANCIAL_PERIODS:
        raise unprocessable(f"不支援的期間：{period}（可用 quarterly、annual）")
    info = require_instrument(md, symbol)
    sym = info.symbol
    out: dict[str, Any] = {
        "symbol": sym, "period": period, "periods": [], "period_ends": [],
        "currency": info.currency, "amount_unit": 1000,
        "income": {k: [] for k in ("revenue", "gross_profit", "operating_income", "net_income", "eps")},
        "balance": {k: [] for k in ("total_assets", "total_liabilities", "equity")},
        "cashflow": {k: [] for k in ("operating", "investing", "financing", "free_cash_flow")},
        "margins": {k: [] for k in ("gross", "operating", "net")},
        "shares": None, "as_of": None, "sources": [], "notes": [],
    }
    if info.market == "US" and info.type == "stock":  # SEC EDGAR company facts (USD, fiscal periods)
        from forliosa.services import sec as sec_svc

        return sec_svc.financials(db, info, period, out)
    if not _is_tw_stock(info):
        out["notes"].append("ETF 沒有財務報表資料" if info.type == "etf" else "")
        out["notes"] = [n for n in out["notes"] if n]
        return out
    ans = md.statements(sym)
    table = _quarterly_table(ans.value) if ans else {}
    sources = [ans.source] if ans else []
    sources += _add_archived_quarters(db, md, sym, table)
    if not table:
        out["notes"].append("沒有這檔股票的財務報表資料")
        return out
    if period == "annual":
        table = _annual(table)
        out["notes"].append("年度數字為四季加總（損益、現金流量）與第四季底餘額（資產負債）；只列四季齊全的年度")
    periods = sorted(table)
    out["periods"] = periods
    out["period_ends"] = [_period_end(p) for p in periods]

    def col(item: str) -> list[float | None]:
        return [ser.price(table[p].get(item)) if item == "eps" else ser.money(table[p].get(item)) for p in periods]

    for item in out["income"]:
        out["income"][item] = col(item)
    for item in out["balance"]:
        out["balance"][item] = col(item)
    for item in ("operating", "investing", "financing"):
        out["cashflow"][item] = col(item)
    fcf = []
    for p in periods:
        o, i = table[p].get("operating"), table[p].get("investing")
        fcf.append(ser.money(o + i) if o is not None and i is not None else None)
    out["cashflow"]["free_cash_flow"] = fcf
    for name, item in (("gross", "gross_profit"), ("operating", "operating_income"), ("net", "net_income")):
        vals = []
        for p in periods:
            num, rev = table[p].get(item), table[p].get("revenue")
            vals.append(ser.ratio(num / rev) if num is not None and rev else None)
        out["margins"][name] = vals
    out["notes"].append("金額單位：新台幣千元；自由現金流量 = 營業活動現金流量 + 投資活動現金流量")
    out["sources"] = labels(sources)
    return out


def _period_end(period: str) -> date | None:
    """Taiwan reporting periods are calendar quarters / years: ``2026Q2`` -> 2026-06-30, ``2025`` -> 2025-12-31."""
    try:
        year = int(period[:4])
        if len(period) == 4:
            return date(year, 12, 31)
        q = int(period[-1])
        return add_months(date(year, 3 * q, 1), 1) - timedelta(days=1)
    except (ValueError, IndexError):
        return None


def _annual(table: dict[str, dict[str, Decimal | None]]) -> dict[str, dict[str, Decimal | None]]:
    years: dict[int, list[str]] = defaultdict(list)
    for p in table:
        years[int(p[:4])].append(p)
    out = {}
    for y, ps in years.items():
        if len(ps) != 4:
            continue
        ps = sorted(ps)
        row: dict[str, Decimal | None] = {}
        for item in ("revenue", "gross_profit", "operating_income", "net_income", "eps", "operating", "investing",
                     "financing"):
            vals = [table[p].get(item) for p in ps]
            row[item] = sum(vals, Decimal(0)) if all(v is not None for v in vals) else None  # type: ignore[arg-type]
        if table[ps[-1]].get("ytd_eps") is not None:
            row["eps"] = table[ps[-1]]["ytd_eps"]  # full-year EPS as reported (share count changes)
        for item in ("total_assets", "total_liabilities", "equity"):
            row[item] = table[ps[-1]].get(item)
        out[str(y)] = row
    return out


# -- events ---------------------------------------------------------------------------------------------
_EVENT_KINDS = {"revenue_release": "revenue", "exchange_news": "news"}


def _event_source(r: MarketEvent) -> str:
    """An archived event row's dataset key, e.g. ``twse-openapi/material_info``."""
    return f"{r.source}/{_EVENT_KINDS.get(r.type, r.type)}"

def _resolution_title(e) -> str:
    progress = e.progress or ""
    if "擬議" in progress and "決議" not in progress:
        return "董事會擬議股利"
    return "股東會確認股利" if "股東會確認" in progress and "董事會" not in progress else "董事會決議股利"


def resolution_detail(e) -> str:
    """「現金股利 0.8 元（資本公積 0.8 元）…」 for a t187ap45_L resolution."""
    parts = []
    if e.cash_dividend:
        names = ("盈餘", "法定盈餘公積", "資本公積")
        split = [f"{n} {v.normalize():f} 元" for n, v in zip(names, e.cash_sources or (), strict=False) if v]
        parts.append(f"現金股利 {e.cash_dividend.normalize():f} 元" + (f"（{'、'.join(split)}）" if split else ""))
    if e.stock_dividend:
        parts.append(f"股票股利 {e.stock_dividend.normalize():f} 元")
    detail = "、".join(parts) or "不配發股利"
    if e.cash_sources and e.cash_sources[2]:
        detail += "；資本公積發放的現金一般不屬股利所得、不扣二代健保（依公司公告的來源為準）"
    if e.progress:
        detail += f"。進度：{e.progress}"
    if e.meeting_date:
        detail += f"，股東會 {e.meeting_date:%Y-%m-%d}"
    if e.ex_dividend_date is None:
        detail += "；除權息日尚未公告"
    return detail


def _held_quantity(state, sym: str) -> Decimal:
    row = next((r for r in state.rows if r.symbol == sym), None)
    return row.quantity if row else Decimal(0)


def events(db: Session, md: MarketData, user: User, symbol: str, mine_only: bool = False) -> list[dict[str, Any]]:
    """Dated events of ``symbol``, newest first (future included).

    ``earnings`` / ``revenue_release`` / ``investor_conference`` dates are **actual** dates read from the
    archive: 重大訊息 (board approval of a financial report, 法人說明會, monthly revenue announcements; see
    :mod:`forliosa.services.announcements`) and the first day a company's month appeared in the monthly
    revenue datasets (t187ap05). Only when no actual date is known is the legal deadline shown, with
    ``estimated: true``.
    """
    info = require_instrument(md, symbol)
    sym = info.symbol
    today = today_taipei()
    lo, hi = today - timedelta(days=EVENT_PAST_DAYS), today + timedelta(days=EVENT_FUTURE_DAYS)
    state = compute_state(db, user, md)
    qty = _held_quantity(state, sym)
    fx = next((r.fx for r in state.rows if r.symbol == sym), Decimal(1))
    div_txns: dict[date, Decimal] = defaultdict(Decimal)
    for t in state.inp.effective_transactions():
        if t.symbol == sym and t.type == "cash_dividend":
            div_txns[t.trade_date] += (t.amount or Decimal(0)) * fx
    out: list[dict[str, Any]] = []

    def add(d: date, type_: str, title: str, detail: str = "", url: str | None = None, mine: bool = False,
            amount: Decimal | None = None, sources: list[str] | None = None, estimated: bool = False,
            period: str | None = None) -> None:
        out.append({"date": d, "type": type_, "title": title, "detail": detail, "url": url, "mine": mine,
                    "amount_estimate": ser.money(amount), "estimated": estimated, "period": period,
                    "sources": labels(sources or [])})

    if info.market == "US" and info.type == "stock":  # 8-K / 10-Q / 10-K from SEC EDGAR submissions
        from forliosa.services import sec as sec_svc

        out += sec_svc.filing_events(db, info, lo, hi, held=qty > 0, today=today)

    divs = md.dividends(sym)
    div_sources = ["demo"] if divs.is_demo else tagged(divs.source, "ex_dividend")
    ex_dates = set()
    for e in divs.value:
        parts = []
        if e.cash_dividend:
            parts.append(f"現金股利 {e.cash_dividend.normalize():f} 元")
        if e.stock_dividend:
            parts.append(f"股票股利 {e.stock_dividend.normalize():f} 元")
        detail = "、".join(parts) or "金額尚未公告"
        if e.board_date is not None and lo <= e.board_date <= hi and not divs.is_demo:
            add(e.board_date, "dividend_resolution", f"{_resolution_title(e)}（{e.period}）",
                resolution_detail(e), mine=qty > 0, sources=["twse-openapi/dividend_resolution"])
        for d, type_, title in ((e.ex_dividend_date, "ex_dividend", "除權息" if e.stock_dividend else "除息"),
                                (e.payment_date, "dividend_payment", "現金股利發放")):
            if d is None or not lo <= d <= hi or (type_ == "dividend_payment" and not e.cash_dividend):
                continue
            if type_ == "ex_dividend":
                ex_dates.add(d)
            if d >= today:
                mine = qty > 0
                amount = qty * e.cash_dividend * fx if mine and e.cash_dividend else None
            else:
                recorded = div_txns.get(d) or (div_txns.get(e.ex_dividend_date) if e.ex_dividend_date else None)
                mine = recorded is not None
                amount = recorded
            add(d, type_, f"{title}（{e.period}）", detail, mine=mine, amount=amount, sources=div_sources)

    # Actual release dates: (kind, period) -> earliest (date, row)
    releases: dict[tuple[str, str], tuple[date, MarketEvent]] = {}
    backlog_revenue: dict[str, MarketEvent] = {}

    def release(kind: str, period: str, d: date, row: MarketEvent) -> None:
        cur = releases.get((kind, period))
        if cur is None or d < cur[0]:
            releases[(kind, period)] = (d, row)

    recent = qty > 0
    stmt = select(MarketEvent).where(MarketEvent.symbol == sym, MarketEvent.date >= lo, MarketEvent.date <= hi)
    for r in db.scalars(_filtered(stmt, MarketEvent, md).order_by(MarketEvent.date)):
        if (r.type == "ex_dividend" and r.date in ex_dates) or r.type == "exchange_news":
            continue
        if r.type == "revenue_release":  # first seen in the monthly revenue dataset (t187ap05)
            period = (r.data or {}).get("period")
            if period and (r.data or {}).get("backlog"):
                backlog_revenue[period] = r
            elif period:
                release("revenue_release", period, r.date, r)
            continue
        if r.type == "material_info":
            rel = classify(r.title, r.detail, r.data, r.date)
            if rel is not None and rel.kind == "investor_conference":
                if lo <= rel.date <= hi:
                    add(rel.date, "investor_conference", r.title, r.detail[:600], r.url,
                        mine=recent and rel.date >= today - timedelta(days=7), sources=[_event_source(r)])
                continue
            if rel is not None and rel.period:
                release(rel.kind, rel.period, rel.date, r)
                continue
            if rel is not None:  # a financial report whose period could not be read: still an actual date
                add(r.date, rel.kind, r.title, r.detail[:600], r.url, mine=recent, sources=[_event_source(r)])
                continue
        add(r.date, r.type, r.title, r.detail[:600], r.url, mine=recent and r.date >= today - timedelta(days=7),
            sources=[_event_source(r)])

    for (kind, period), (d, r) in releases.items():
        if kind == "earnings":
            title, detail = f"{period} 財報公布", r.title
        else:
            month = int(period[5:])
            title = f"{month} 月營收公布"
            detail = r.detail if r.type == "revenue_release" else r.title
        add(d, kind, title, detail[:600], r.url, mine=recent, sources=[_event_source(r)], period=period)

    if _is_tw_stock(info):  # legal deadlines only where no actual date is known
        dlo, dhi = today - timedelta(days=DEADLINE_PAST_DAYS), today + timedelta(days=DEADLINE_FUTURE_DAYS)
        for y in (today.year - 1, today.year, today.year + 1):
            for q in (1, 2, 3, 4):
                period = f"{y}Q{q}"
                d = report_publication_date(period)
                if dlo <= d <= dhi and ("earnings", period) not in releases:
                    add(d, "earnings", f"{period} 財報公布期限（預估）",
                        "尚未偵測到實際公布日：以上市櫃公司季報的法定公布期限顯示（實際日期以公司公告為準）",
                        mine=recent, sources=["rules"], estimated=True, period=period)
            for m in range(1, 13):
                d = date(y, m, 10)
                prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
                period = f"{prev_y}-{prev_m:02d}"
                if not dlo <= d <= dhi or ("revenue_release", period) in releases:
                    continue
                detail = "尚未偵測到實際公布日：每月 10 日前公布上個月營收（法定期限）"
                seen = backlog_revenue.get(period)
                if seen is not None:
                    detail = f"{seen.detail}；在開始存檔前已公布，實際日期不明，以法定期限顯示"
                add(d, "revenue_release", f"{prev_m} 月營收公布期限（預估）", detail, mine=recent,
                    sources=["rules", *([_event_source(seen)] if seen is not None else [])], estimated=True,
                    period=period)
    if mine_only:
        out = [e for e in out if e["mine"]]
    out.sort(key=lambda e: (e["date"], e["type"]), reverse=True)
    return out


# -- news (official announcements) ----------------------------------------------------------------------
NEWS_DAYS = 90
NEWS_LIMIT = 30
MARKET_SYMBOL = "MARKET"  # exchange news not tied to one company
# 公開資訊觀測站 重大訊息 query page (official; the OpenAPI rows carry no per-announcement link).
MOPS_MATERIAL_URL = "https://mops.twse.com.tw/mops/#/web/t05st01"


def _published_at(r: MarketEvent) -> str:
    hhmmss = str((r.data or {}).get("time") or "").zfill(6)
    try:
        at = datetime.combine(r.date, datetime.strptime(hhmmss, "%H%M%S").time(), TAIPEI)
    except ValueError:
        at = datetime.combine(r.date, datetime.min.time(), TAIPEI)
    return iso_taipei(at)


def news(db: Session, md: MarketData, symbol: str) -> list[dict[str, Any]]:
    """Official announcements (公告) first, then media headlines (新聞報導).

    * Official (``category: material_info | exchange_news``, ``source: "公告"``): the company's 重大訊息 and TWSE
      news that names it — government open data (t187ap04_L / mopsfin_t187ap04_O, TWSE /news/newsList), archived
      daily; the last 90 days, at most 30. Taiwan stocks only.
    * Media (``category: "media"``): headlines collected by the news worker (:mod:`forliosa.news`) — the original
      title, ``outlet`` (媒體名稱), ``published_at`` and the link to the original site, ``source`` naming how it was
      found (GDELT, AI 搜尋, SearXNG, Yahoo股市; FinMind under an explicit personal opt-in). Metadata only.

    Viewing a symbol's news records the symbol and time (no user) so the worker keeps it fresh for 3 days.
    """
    from forliosa.news import service as news_service
    from forliosa.news.normalize import Headline, clean_title

    info = require_instrument(md, symbol)
    sym = info.symbol
    out: list[dict[str, Any]] = []
    if info.market != "US":
        since = today_taipei() - timedelta(days=NEWS_DAYS)
        company = select(MarketEvent).where(MarketEvent.symbol == sym, MarketEvent.type == "material_info",
                                            MarketEvent.date >= since)
        exchange = select(MarketEvent).where(
            MarketEvent.type == "exchange_news", MarketEvent.date >= since,
            or_(MarketEvent.symbol == sym,
                and_(MarketEvent.symbol == MARKET_SYMBOL, MarketEvent.title.contains(info.name))))
        rows = [*db.scalars(_filtered(company, MarketEvent, md)), *db.scalars(_filtered(exchange, MarketEvent, md))]
        rows.sort(key=lambda r: (r.date, str((r.data or {}).get("time") or "")), reverse=True)
        out = [{"published_at": _published_at(r), "title": r.title, "source": "公告", "outlet": None,
                "url": r.url or MOPS_MATERIAL_URL, "category": r.type, "date_only": False,
                "sources": labels([_event_source(r)])}
               for r in rows[:NEWS_LIMIT]]
    extra: list[Headline] = []
    fm = md.provider("finmind") if md.policy == "personal" and info.market != "US" else None
    if fm is not None:
        try:
            items = fm.news(sym)  # type: ignore[attr-defined]
        except Exception:  # quota (402) or network: the stored headlines only
            items = []
        for n in items[:NEWS_LIMIT]:
            try:
                published = datetime.fromisoformat(n["published_at"]).replace(tzinfo=TAIPEI)
            except ValueError:
                continue
            outlet = n["source"] or "FinMind"
            extra.append(Headline(title=clean_title(n["title"], n["url"], outlet), url=n["url"], outlet=outlet[:100],
                                  domain="", published_at=published, source="finmind"))
    out += news_service.media_items(db, md, info, extra=extra)
    try:
        news_service.record_view(db, sym)
    except SQLAlchemyError:  # never fail the page over the view note
        db.rollback()
    return out


# -- position -------------------------------------------------------------------------------------------
def position(db: Session, md: MarketData, user: User, symbol: str,
             state: PortfolioState | None = None) -> dict[str, Any] | None:
    """The user's open position in ``symbol`` (None when not held). Pass ``state`` to read the values from a
    portfolio state the caller also uses (the AI tool takes its FX notes from ``state.fx``)."""
    info = require_instrument(md, symbol)
    sym = info.symbol
    state = state or compute_state(db, user, md)
    row = next((r for r in state.rows if r.symbol == sym), None)
    if row is None or row.quantity <= 0:
        return None
    led = state.ledger
    realized = sum((e.pnl_twd for e in led.realized if e.symbol == sym), Decimal(0))
    dividends = sum((e.net_twd for e in led.income if e.symbol == sym), Decimal(0))
    mv = row.market_value
    unreal = mv - row.cost_twd
    markers = _markers(state, sym)
    today = today_taipei()
    divs = md.dividends(sym)
    upcoming = sorted((e for e in divs.value if e.ex_dividend_date and e.ex_dividend_date > today
                       and e.cash_dividend > 0), key=lambda e: e.ex_dividend_date)
    q = row.quote
    return {
        "symbol": sym,
        "currency": row.currency,
        "quantity": ser.qty(row.quantity),
        "avg_cost": ser.price(row.cost / row.quantity),
        "cost_basis": ser.money(row.cost_twd),
        "market_value": ser.money(mv),
        "unrealized_pnl": ser.money(unreal),
        "unrealized_pnl_pct": ser.ratio(unreal / row.cost_twd) if row.cost_twd else None,
        "realized_pnl": ser.money(realized),
        "dividends_received": ser.money(dividends),
        "day_change": ser.money(row.day_change),
        "markers": markers,
        "upcoming_dividend": {
            "ex_dividend_date": upcoming[0].ex_dividend_date,
            "amount_estimate": ser.money(row.quantity * upcoming[0].cash_dividend * row.fx),
        } if upcoming else None,
        "as_of": iso_taipei(q.as_of) if q and q.as_of else iso_taipei(state.as_of),
        "sources": labels(["ledger", *(tagged(q.source, "price") if q else []),
                           *(tagged(state.fx.source, "fx") if row.currency != "TWD" else [])]),
        "is_demo": bool(q.is_demo) if q else md.demo_data_allowed,
    }


_MARKER_KINDS = {"buy": "buy", "sell": "sell", "cash_dividend": "dividend", "stock_dividend": "stock_dividend"}


def _markers(state, sym: str, with_account: bool = False) -> list[dict[str, Any]]:
    """Buy / sell / dividend markers of ``sym`` in trade-date order (all accounts in the state)."""
    led = state.ledger
    out = []
    for t in sorted(state.inp.effective_transactions(), key=lambda t: (t.trade_date, t.created_at)):
        if t.symbol != sym or t.type not in _MARKER_KINDS:
            continue
        eff = led.effective.get(t.id)
        quantity = eff.quantity if eff is not None and t.type == "stock_dividend" else t.quantity
        m = {"date": t.trade_date, "type": _MARKER_KINDS[t.type],
             "quantity": ser.qty(quantity) if t.type != "cash_dividend" else ser.qty(t.quantity) or None,
             "price": ser.price(t.price) if t.type in ("buy", "sell", "cash_dividend") else None,
             "amount": ser.money(t.amount)}
        if with_account:
            m["account_id"] = t.account_id
        out.append(m)
    return out


def position_history(db: Session, md: MarketData, user: User, symbol: str) -> dict[str, Any]:
    """Closed rounds and every trade / dividend marker of ``symbol``, also when it is no longer held."""
    info = require_instrument(md, symbol)
    sym = info.symbol
    view = ledger_view(db, user, md)
    return {
        "symbol": sym,
        "rounds": [round_out(r, md) for r in closed_rounds(view, sym)],
        "markers": _markers(view, sym, with_account=True),
        "sources": labels(["ledger"]),
    }


# -- why did it move ------------------------------------------------------------------------------------
def why(db: Session, md: MarketData, symbol: str) -> dict[str, Any]:
    info = require_instrument(md, symbol)
    sym = info.symbol
    today = today_taipei()
    q = md.quote(sym)
    if q is None or q.price is None:
        return {"symbol": sym, "show": False, "headline": None, "reasons": [], "as_of": None, "sources": []}
    reasons = why_reasons(db, md, info, q, today)
    texts = [r["text"] for r in reasons]
    headline = None
    if reasons:
        lead = f"{info.name}{texts[0]}" if texts[0].startswith("今天") else f"{info.name} {texts[0]}"
        headline = "，".join([lead, *texts[1:2]])
    return {"symbol": sym, "show": bool(reasons), "headline": headline, "reasons": reasons,
            "as_of": iso_taipei(q.as_of) if q.as_of else None,
            "sources": labels([*tagged(q.source, "price"), "rules"])}


def why_reasons(db: Session, md: MarketData, info: InstrumentInfo, q: QuoteData, today: date) -> list[dict]:
    """Rule-based anomalies (no AI): ±3 %, 2× volume, limit up/down, attention/disposition, ex-rights day,
    earnings / revenue announcement day. Ordered by importance."""
    sym = info.symbol
    reasons: list[dict[str, str]] = []
    base = change_base(q)
    day = q.trade_date or today
    when = "今天" if day == today else f"{day.month}/{day.day} "
    if q.price is not None and q.limit_up is not None and q.price >= q.limit_up:
        reasons.append({"kind": "limit_up", "text": f"{when}漲停"})
    elif q.price is not None and q.limit_down is not None and q.price <= q.limit_down:
        reasons.append({"kind": "limit_down", "text": f"{when}跌停"})
    elif base and q.price is not None:
        pct = (q.price - base) / base
        if abs(pct) >= WHY_MOVE_PCT:
            word = "上漲" if pct > 0 else "下跌"
            reasons.append({"kind": "price_move", "text": f"{when}{word} {abs(pct) * 100:.1f}%"})
    hist = md.history(sym, day - timedelta(days=45), day)
    past = [c for c in hist.candles if c.t < day][-20:]
    if q.volume and len(past) >= 10:
        avg = Decimal(sum(c.v for c in past)) / len(past)
        if avg > 0 and Decimal(q.volume) >= WHY_VOLUME_MULTIPLE * avg:
            reasons.append({"kind": "volume", "text": f"成交量是 20 日均量的 {Decimal(q.volume) / avg:.1f} 倍"})
    if q.reference_price is not None and q.prev_close is not None and q.reference_price != q.prev_close:
        reasons.append({"kind": "ex_dividend",
                        "text": f"{when}除權息，漲跌以參考價 {q.reference_price.normalize():f} 計算"
                                f"（昨收 {q.prev_close.normalize():f}）"})
    status, _ = trading_status(db, md, sym, today)
    if status["disposition"]:
        reasons.append({"kind": "disposition", "text": status["note"] or "處置中"})
    elif status["attention"]:
        reasons.append({"kind": "attention", "text": "列為注意股票"})
    stmt = select(MarketEvent).where(MarketEvent.symbol == sym, MarketEvent.type == "material_info",
                                     MarketEvent.date == day)
    titles = [r.title for r in db.scalars(_filtered(stmt, MarketEvent, md))]
    if any(any(w in t for w in EARNINGS_WORDS) for t in titles):
        reasons.append({"kind": "earnings", "text": f"{when}公布財報"})
    elif any(any(w in t for w in REVENUE_WORDS) for t in titles):
        reasons.append({"kind": "revenue_release", "text": f"{when}公布營收"})
    return reasons
