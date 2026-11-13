"""Futures market data for a future 期貨 page and for AI context (TAIFEX OpenAPI archive, ``taifex_*`` tables).

* ``overview``: TX / MTX / TE / TF near-month futures (regular session and the night session booked to the same
  trading day), the TAIEX options put/call ratio, 三大法人 net open interest in TX and TXO (calls and puts
  split), and the large traders' top-5 / top-10 net positions.
* ``futures_history``: the near-month continuous daily series of one futures contract (regular + after-hours).

Licence gate: 期貨每日交易行情 (DailyMarketReportFut) and 選擇權大額交易人 are ``conditional`` datasets. Under
``DATA_POLICY=commercial`` they are not served until ``TAIFEX_CONDITIONAL_CONFIRMED=true``; the response then
carries empty lists / ``null`` and a note instead (``served`` says which parts are on). 三大法人, futures large
traders and the put/call ratio are OGDL datasets (data.gov.tw 11592–11600, 11337/11338, 11322) and always served.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import not_found, unprocessable
from forliosa.datapolicy import CONDITIONAL_NOTE, dataset_served, labels, source_clause
from forliosa.marketdata.service import MarketData
from forliosa.marketdata.taifex import ALL_MONTHS, CONTRACT_NAMES, INVESTORS, is_monthly
from forliosa.models import (
    TaifexFuturesDaily,
    TaifexInstitutional,
    TaifexLargeTraders,
    TaifexPutCallRatio,
)
from forliosa.services.coverage import since_note
from forliosa.services.portfolio import range_start
from forliosa.timeutil import next_tw_trading_day, today_taipei

OVERVIEW_FUTURES = ("TX", "MTX", "TE", "TF")
FUTURES_RANGES = ("1M", "3M", "6M", "1Y", "MAX")
FUTURES_NAMES = {code: name for name, (code, kind) in CONTRACT_NAMES.items()
                 if code and kind == "futures" and "(" not in name and name not in ("小型臺指", "櫃買期貨")}
_CODE = re.compile(r"^[A-Z0-9]{2,4}$")
FUTURES_PENDING = "期貨行情（臺灣期貨交易所〈期貨每日交易行情〉）的商用授權待期交所確認，暫不顯示"
OPTIONS_LT_PENDING = ("選擇權大額交易人（臺灣期貨交易所〈選擇權大額交易人未沖銷部位資料〉）的商用授權待期交所確認，"
                      "暫不顯示")


def _filtered(stmt, model, md: MarketData):
    return stmt.where(source_clause(model.source, md.policy))


def _latest_two(db: Session, md: MarketData, model, *where) -> list[date]:
    stmt = select(model.trade_date).where(*where).distinct().order_by(model.trade_date.desc()).limit(2)
    return list(db.scalars(_filtered(stmt, model, md)))


# -- futures ------------------------------------------------------------------------------------------------
def _session_out(r: TaifexFuturesDaily | None, full: bool) -> dict[str, Any] | None:
    if r is None:
        return None
    out = {"open": ser.price(r.open), "high": ser.price(r.high), "low": ser.price(r.low), "close": ser.price(r.last),
           "change": ser.price(r.change), "change_pct": ser.ratio(r.change_pct), "volume": r.volume}
    if full:
        out |= {"settlement_price": ser.price(r.settlement_price), "open_interest": r.open_interest}
    return out


def _near_month(rows: list[TaifexFuturesDaily]) -> str | None:
    months = sorted({r.contract_month for r in rows if r.session == "regular" and is_monthly(r.contract_month)})
    return months[0] if months else None


def _futures_overview(db: Session, md: MarketData) -> tuple[list[dict[str, Any]], date | None]:
    day = db.scalar(_filtered(select(func.max(TaifexFuturesDaily.trade_date)), TaifexFuturesDaily, md))
    if day is None:
        return [], None
    stmt = select(TaifexFuturesDaily).where(TaifexFuturesDaily.trade_date == day,
                                            TaifexFuturesDaily.contract.in_(OVERVIEW_FUTURES))
    rows = list(db.scalars(_filtered(stmt, TaifexFuturesDaily, md)))
    by_code: dict[str, list[TaifexFuturesDaily]] = defaultdict(list)
    for r in rows:
        by_code[r.contract].append(r)
    out = []
    for code in OVERVIEW_FUTURES:
        month = _near_month(by_code.get(code, []))
        if month is None:
            continue
        pick = {r.session: r for r in by_code[code] if r.contract_month == month}
        out.append({"code": code, "name": FUTURES_NAMES.get(code, code), "contract_month": month,
                    "regular": _session_out(pick.get("regular"), True),
                    "after_hours": _session_out(pick.get("after_hours"), False)})
    return out, day


# -- put / call ratio ---------------------------------------------------------------------------------------
def _put_call(db: Session, md: MarketData) -> dict[str, Any] | None:
    rows = list(db.scalars(_filtered(select(TaifexPutCallRatio).order_by(TaifexPutCallRatio.trade_date.desc())
                                     .limit(2), TaifexPutCallRatio, md)))
    if not rows:
        return None
    r, prev = rows[0], rows[1] if len(rows) > 1 else None
    return {"date": r.trade_date, "volume_ratio": ser.ratio(r.volume_ratio), "oi_ratio": ser.ratio(r.oi_ratio),
            "put_volume": r.put_volume, "call_volume": r.call_volume, "put_oi": r.put_oi, "call_oi": r.call_oi,
            "oi_ratio_prev": ser.ratio(prev.oi_ratio) if prev else None}


# -- 三大法人 --------------------------------------------------------------------------------------------------
def _institutional(db: Session, md: MarketData, scope: str, code: str) -> tuple[list[dict[str, Any]], date | None]:
    days = _latest_two(db, md, TaifexInstitutional, TaifexInstitutional.scope == scope,
                       TaifexInstitutional.contract_code == code)
    if not days:
        return [], None
    rows = list(db.scalars(_filtered(select(TaifexInstitutional).where(
        TaifexInstitutional.scope.in_((scope, "calls_puts")), TaifexInstitutional.contract_code == code,
        TaifexInstitutional.trade_date.in_(days)), TaifexInstitutional, md)))
    cur = {(r.investor, r.call_put): r for r in rows if r.trade_date == days[0]}
    prev = {(r.investor, r.call_put): r for r in rows if len(days) > 1 and r.trade_date == days[1]}

    def change(key: tuple[str, str]) -> int | None:
        a, b = cur.get(key), prev.get(key)
        return a.oi_net - b.oi_net if a and b and a.oi_net is not None and b.oi_net is not None else None

    out = []
    for investor, key in INVESTORS.items():
        r = cur.get((investor, ""))
        if r is None:
            continue
        item: dict[str, Any] = {"investor": key, "investor_name": investor, "oi_net": r.oi_net,
                                "oi_net_change": change((investor, "")), "oi_long": r.oi_long, "oi_short": r.oi_short,
                                "oi_net_value_k": r.oi_net_value_k, "net_volume": r.net_vol}
        if scope == "options":
            for cp, name in (("C", "calls"), ("P", "puts")):
                x = cur.get((investor, cp))
                item[name] = ({"oi_net": x.oi_net, "oi_net_change": change((investor, cp)),
                               "oi_net_value_k": x.oi_net_value_k, "net_volume": x.net_vol} if x else None)
        out.append(item)
    return out, days[0]


# -- large traders ------------------------------------------------------------------------------------------
def _trader_block(rows: list[TaifexLargeTraders]) -> dict[str, Any] | None:
    by_type = {r.trader_type: r for r in rows}
    r = by_type.get(0)
    if r is None:
        return None

    def net(a: int | None, b: int | None) -> int | None:
        return a - b if a is not None and b is not None else None

    out: dict[str, Any] = {"top5_buy": r.top5_buy, "top5_sell": r.top5_sell, "top10_buy": r.top10_buy,
                           "top10_sell": r.top10_sell, "top5_net": net(r.top5_buy, r.top5_sell),
                           "top10_net": net(r.top10_buy, r.top10_sell), "market_oi": r.market_oi}
    s = by_type.get(1)
    out["specific"] = ({"top5_net": net(s.top5_buy, s.top5_sell), "top10_net": net(s.top10_buy, s.top10_sell)}
                       if s else None)
    return out


def _large_traders(db: Session, md: MarketData, kind: str, contract: str) -> tuple[dict[str, Any] | None,
                                                                                   date | None]:
    day = db.scalar(_filtered(select(func.max(TaifexLargeTraders.trade_date)).where(
        TaifexLargeTraders.kind == kind, TaifexLargeTraders.contract == contract), TaifexLargeTraders, md))
    if day is None:
        return None, None
    rows = list(db.scalars(_filtered(select(TaifexLargeTraders).where(
        TaifexLargeTraders.kind == kind, TaifexLargeTraders.contract == contract,
        TaifexLargeTraders.trade_date == day), TaifexLargeTraders, md)))
    groups: dict[tuple[str, str], list[TaifexLargeTraders]] = defaultdict(list)
    for r in rows:
        groups[(r.call_put, r.settlement_month)].append(r)
    if kind == "futures":
        months = sorted(m for (_cp, m) in groups if is_monthly(m) and m != ALL_MONTHS)
        near = months[0] if months else None
        return {"contract": contract, "name": rows[0].contract_name if rows else contract,
                "all_months": _trader_block(groups.get(("", ALL_MONTHS), [])),
                "near_month": ({"contract_month": near, **(_trader_block(groups[("", near)]) or {})}
                               if near else None)}, day
    return {"contract": contract, "name": rows[0].contract_name if rows else contract,
            "calls": _trader_block(groups.get(("C", ALL_MONTHS), [])),
            "puts": _trader_block(groups.get(("P", ALL_MONTHS), []))}, day


def overview(db: Session, md: MarketData) -> dict[str, Any]:
    """``GET /derivatives/overview`` (also the AI tool ``get_derivatives_overview``)."""
    policy = md.policy
    served = {"futures": dataset_served("taifex-openapi/futures_daily", policy),
              "options_large_traders": dataset_served("taifex-openapi/large_traders_options", policy)}
    notes: list[str] = []
    sources: list[str] = []
    dates: list[date] = []

    futures: list[dict[str, Any]] = []
    if served["futures"]:
        futures, day = _futures_overview(db, md)
        if futures:
            sources.append("taifex-openapi/futures_daily")
            dates.append(day)  # type: ignore[arg-type]
    else:
        notes.append(FUTURES_PENDING)

    pcr = _put_call(db, md)
    if pcr:
        sources.append("taifex-openapi/put_call_ratio")
        dates.append(pcr["date"])

    tx, d1 = _institutional(db, md, "futures", "TX")
    txo, d2 = _institutional(db, md, "options", "TXO")
    if tx:
        sources.append("taifex-openapi/institutional_futures")
    if txo:
        sources += ["taifex-openapi/institutional_options", "taifex-openapi/institutional_calls_puts"]
    dates += [d for d in (d1, d2) if d]

    lt_tx, d3 = _large_traders(db, md, "futures", "TX")
    if lt_tx:
        sources.append("taifex-openapi/large_traders_futures")
        dates.append(d3)  # type: ignore[arg-type]
    lt_txo = None
    if served["options_large_traders"]:
        lt_txo, d4 = _large_traders(db, md, "options", "TXO")
        if lt_txo:
            sources.append("taifex-openapi/large_traders_options")
            dates.append(d4)  # type: ignore[arg-type]
    else:
        notes.append(OPTIONS_LT_PENDING)

    if not (futures or pcr or tx or txo or lt_tx or lt_txo):
        notes.append("還沒有期交所資料，每個交易日 21:40 更新")
    notes.append("夜盤（盤後交易時段）列在它所屬的交易日：前一個交易日 15:00 開盤、當日 05:00 收盤；"
                 "漲跌以前一個交易日的結算價計算，和當日一般交易時段相同")
    return {
        "as_of": max(dates) if dates else None,
        "futures": futures,
        "put_call_ratio": pcr,
        "institutional": {"TX": tx, "TXO": txo},
        "large_traders": {"TX": lt_tx, "TXO": lt_txo},
        "served": served,
        "notes": notes,
        "sources": labels(sources),
    }


def futures_history(db: Session, md: MarketData, code: str, range_: str) -> dict[str, Any]:
    """``GET /derivatives/futures/{code}/history?range=``: the near-month contract of each trading day (the series
    rolls when a month expires; ``contract_month`` shows which), regular session plus the after-hours session
    booked to that day."""
    code = code.strip().upper()
    if not _CODE.match(code):
        raise unprocessable("期貨契約代號格式不正確（例如 TX、MTX、TE、TF）")
    if range_ not in FUTURES_RANGES:
        raise unprocessable(f"不支援的區間：{range_}（可用 {'、'.join(FUTURES_RANGES)}）")
    known = code in FUTURES_NAMES or db.scalar(select(TaifexFuturesDaily.contract).where(
        TaifexFuturesDaily.contract == code).limit(1)) is not None
    if not known:
        raise not_found("找不到這個期貨契約")
    out: dict[str, Any] = {"code": code, "name": FUTURES_NAMES.get(code, code), "range": range_, "series": [],
                           "notes": [], "sources": []}
    if not dataset_served("taifex-openapi/futures_daily", md.policy):
        out["notes"] = [FUTURES_PENDING, CONDITIONAL_NOTE]
        return out
    today = today_taipei()
    start = range_start(range_, today, date(1990, 1, 1))
    rows = list(db.scalars(_filtered(select(TaifexFuturesDaily).where(
        TaifexFuturesDaily.contract == code, TaifexFuturesDaily.trade_date >= start,
        TaifexFuturesDaily.trade_date <= today), TaifexFuturesDaily, md).order_by(TaifexFuturesDaily.trade_date)))
    by_day: dict[date, list[TaifexFuturesDaily]] = defaultdict(list)
    for r in rows:
        by_day[r.trade_date].append(r)
    series = []
    for d in sorted(by_day):
        month = _near_month(by_day[d])
        if month is None:
            continue
        pick = {r.session: r for r in by_day[d] if r.contract_month == month}
        reg = pick.get("regular")
        if reg is None:
            continue
        series.append({"t": d, "contract_month": month, **(_session_out(reg, True) or {}),
                       "after_hours": _session_out(pick.get("after_hours"), False)})
    out["series"] = series
    if series:
        out["sources"] = labels(["taifex-openapi/futures_daily"])
    if not series or series[0]["t"] > next_tw_trading_day(start) + timedelta(days=5):
        first = db.scalar(_filtered(select(func.min(TaifexFuturesDaily.trade_date)), TaifexFuturesDaily, md))
        out["notes"].append(since_note(first))
    return out
