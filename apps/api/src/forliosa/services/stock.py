"""Stock page (個股頁): overview, intraday, chips, financials, events, news, position and "why it moved".

Every response lists its ``sources`` (labels from :mod:`forliosa.datapolicy`; non-commercial ones end
with 「非商用」). Archive tables are read with the policy's source filter, so under
``DATA_POLICY=commercial`` rows that came from FinMind or the TWSE website are never served.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import unprocessable
from forliosa.datapolicy import allowed_sources, labels
from forliosa.marketdata.base import InstrumentInfo, QuoteData
from forliosa.marketdata.demo import report_publication_date
from forliosa.marketdata.opendata import TDCC_LEVELS
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    ForeignHoldingDaily,
    InstitutionalDaily,
    IntradayPoint,
    MarginDaily,
    MarketEvent,
    ShareholdingDistribution,
    User,
)
from forliosa.services.instruments import change_base, require_instrument
from forliosa.services.portfolio import (
    add_months,
    closed_rounds,
    compute_state,
    ledger_view,
    range_start,
    round_out,
)
from forliosa.timeutil import (
    TAIPEI,
    is_tw_market_open,
    iso_taipei,
    last_tw_trading_day,
    today_taipei,
    tw_trading_days,
)

CHIPS_RANGES = ("1M", "3M", "6M", "1Y")
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
    allowed = allowed_sources(md.policy)
    return stmt.where(model.source.in_(allowed)) if allowed is not None else stmt


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
    return status, [r.source for r in attention + disposition]


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
    sources: list[str] = [*(_split(q.source) if q else []), *_split(hist.source)]
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
            sources += rsrc

    eps_ttm = None
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
    if divs.value:
        is_demo |= divs.is_demo
        sources += _split(divs.source)
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
        "shares_outstanding": prof.shares_outstanding,
        "status": status,
        "as_of": iso_taipei(q.as_of) if q and q.as_of else None,
        "sources": labels(sources),
        "is_demo": is_demo,
    }


# -- intraday -------------------------------------------------------------------------------------------
def intraday(db: Session, md: MarketData, symbol: str, tracked: set[str]) -> dict[str, Any]:
    info = require_instrument(md, symbol)
    sym = info.symbol
    q = md.quote(sym)
    today = today_taipei()
    notes: list[str] = []
    points: list[dict[str, Any]] = []
    sources: list[str] = []
    day = q.trade_date if q and q.trade_date else last_tw_trading_day(today)
    if info.market == "US":
        notes.append("美股沒有盤中走勢資料")
    elif md.policy == "commercial":
        notes.append("商用模式沒有授權的盤中行情來源，不提供分時走勢")
    elif sym not in tracked:
        notes.append("只有持股與自選的股票會累積盤中走勢")
    else:
        latest = db.scalar(select(IntradayPoint.date).where(IntradayPoint.symbol == sym)
                           .order_by(IntradayPoint.date.desc()).limit(1))
        if latest is not None and (q is None or q.trade_date is None or latest >= q.trade_date):
            day = latest
        rows = list(db.scalars(select(IntradayPoint).where(IntradayPoint.symbol == sym, IntradayPoint.date == day)
                               .order_by(IntradayPoint.t)))
        prev_cum = 0
        for r in rows:
            vol = None
            if r.cum_volume is not None:
                vol = max(r.cum_volume - prev_cum, 0)
                prev_cum = r.cum_volume
            points.append({"t": r.t, "price": ser.price(r.price), "volume": vol})
            sources.append(r.source)
        if not rows:
            notes.append("今天還沒有累積到盤中資料（背景工作每 60 秒記錄一次）")
    is_partial = info.market != "US" and (not points or (day == today and is_tw_market_open()))
    return {
        "symbol": sym,
        "date": day,
        "prev_close": ser.price(q.prev_close) if q else None,
        "reference_price": ser.price(change_base(q)) if q else None,
        "points": points,
        "is_partial": is_partial,
        "notes": notes,
        "sources": labels(sources),
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

    inst = {r.date: r for r in rows(InstitutionalDaily)}
    margin = {r.date: r for r in rows(MarginDaily)}
    foreign = {r.date: r for r in rows(ForeignHoldingDaily)}
    sources = [r.source for r in (*inst.values(), *margin.values(), *foreign.values())]
    notes: list[str] = []

    expected = len(tw_trading_days(start, today)) * 0.8
    fm = md.provider("finmind") if md.policy == "personal" else None
    if fm is not None and min(len(inst), len(margin), len(foreign)) < expected:
        try:
            extra = fm.chips(sym, start)  # type: ignore[attr-defined]
        except Exception:  # FinMind quota or network: serve what the archive has
            extra = None
            notes.append("FinMind 暫時無法使用，只顯示已存檔的資料")
        if extra:
            for key, target in (("institutional", inst), ("margin", margin), ("foreign", foreign)):
                for r in extra[key]:
                    if r["date"] not in target and start <= r["date"] <= today:
                        target[r["date"]] = _Row(**r, source="finmind")
                        sources.append("finmind")
    if info.market == "TWSE" and md.policy == "commercial":
        notes.append("上市股票的三大法人與外資持股沒有官方 OpenAPI 個股資料，商用模式不提供")

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
        sources += [b.source for b in buckets[:1]]
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
            used.append(sources[period])
    return used


def financials(db: Session, md: MarketData, symbol: str, period: str) -> dict[str, Any]:
    if period not in FINANCIAL_PERIODS:
        raise unprocessable(f"不支援的期間：{period}（可用 quarterly、annual）")
    info = require_instrument(md, symbol)
    sym = info.symbol
    out: dict[str, Any] = {
        "symbol": sym, "period": period, "periods": [],
        "income": {k: [] for k in ("revenue", "gross_profit", "operating_income", "net_income", "eps")},
        "balance": {k: [] for k in ("total_assets", "total_liabilities", "equity")},
        "cashflow": {k: [] for k in ("operating", "investing", "financing", "free_cash_flow")},
        "margins": {k: [] for k in ("gross", "operating", "net")},
        "sources": [], "notes": [],
    }
    if not _is_tw_stock(info):
        out["notes"].append("ETF 與美股沒有財務報表資料" if info.type == "etf" or info.market == "US" else "")
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
def _held_quantity(state, sym: str) -> Decimal:
    row = next((r for r in state.rows if r.symbol == sym), None)
    return row.quantity if row else Decimal(0)


def events(db: Session, md: MarketData, user: User, symbol: str, mine_only: bool = False) -> list[dict[str, Any]]:
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
            amount: Decimal | None = None, sources: list[str] | None = None) -> None:
        out.append({"date": d, "type": type_, "title": title, "detail": detail, "url": url, "mine": mine,
                    "amount_estimate": ser.money(amount), "sources": labels(sources or [])})

    divs = md.dividends(sym)
    div_sources = ["demo"] if divs.is_demo else _split(divs.source)
    ex_dates = set()
    for e in divs.value:
        parts = []
        if e.cash_dividend:
            parts.append(f"現金股利 {e.cash_dividend.normalize():f} 元")
        if e.stock_dividend:
            parts.append(f"股票股利 {e.stock_dividend.normalize():f} 元")
        detail = "、".join(parts) or "金額尚未公告"
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

    stmt = select(MarketEvent).where(MarketEvent.symbol == sym, MarketEvent.date >= lo, MarketEvent.date <= hi)
    for r in db.scalars(_filtered(stmt, MarketEvent, md).order_by(MarketEvent.date)):
        if r.type == "ex_dividend" and r.date in ex_dates:
            continue
        add(r.date, r.type, r.title, r.detail[:600], r.url, mine=qty > 0 and r.date >= today - timedelta(days=7),
            sources=[r.source])

    if _is_tw_stock(info):
        dlo, dhi = today - timedelta(days=DEADLINE_PAST_DAYS), today + timedelta(days=DEADLINE_FUTURE_DAYS)
        for y in (today.year - 1, today.year, today.year + 1):
            for q in (1, 2, 3, 4):
                d = report_publication_date(f"{y}Q{q}")
                if dlo <= d <= dhi:
                    add(d, "earnings", f"{y}Q{q} 財報公布期限",
                        "上市櫃公司季報的法定公布期限（實際公布日以公司公告為準）", mine=qty > 0, sources=["rules"])
            for m in range(1, 13):
                d = date(y, m, 10)
                if dlo <= d <= dhi:
                    prev_m = 12 if m == 1 else m - 1
                    add(d, "revenue_release", f"{prev_m} 月營收公布期限", "每月 10 日前公布上個月營收",
                        mine=qty > 0, sources=["rules"])
    if mine_only:
        out = [e for e in out if e["mine"]]
    out.sort(key=lambda e: (e["date"], e["type"]), reverse=True)
    return out


# -- news -----------------------------------------------------------------------------------------------
def news(md: MarketData, symbol: str) -> list[dict[str, Any]]:
    info = require_instrument(md, symbol)
    if md.policy != "personal" or info.market == "US":
        return []  # headlines only come from FinMind (non-commercial)
    fm = md.provider("finmind")
    if fm is None:
        return []
    try:
        items = fm.news(info.symbol)  # type: ignore[attr-defined]
    except Exception:  # quota (402) or network: degrade to no news
        return []
    out = []
    for n in items[:30]:
        published = n["published_at"]
        with contextlib.suppress(ValueError):
            published = iso_taipei(datetime.fromisoformat(published).replace(tzinfo=TAIPEI))
        out.append({"published_at": published, "title": n["title"], "source": n["source"], "url": n["url"],
                    "sources": labels(["finmind"])})
    return out


# -- position -------------------------------------------------------------------------------------------
def position(db: Session, md: MarketData, user: User, symbol: str) -> dict[str, Any] | None:
    info = require_instrument(md, symbol)
    sym = info.symbol
    state = compute_state(db, user, md)
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
        "sources": labels(["ledger", *(_split(q.source) if q else [])]),
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
            "as_of": iso_taipei(q.as_of) if q.as_of else None, "sources": labels([*_split(q.source), "rules"])}


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
