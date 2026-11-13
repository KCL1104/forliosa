"""``GET /market/overview``: the market page — indices, the day's AI summary, sector moves, rankings and the day's
material information. Everything is after-close official open data from our archive (plus the shared AI summary);
there is no intraday data, no overseas index, no US stock, no crypto.

* **indices** — 加權指數 and 櫃買指數 (``index_daily``), 台指期近月 when its licence gate is open
  (``derivatives``; a conditional TAIFEX dataset) and 美元兌新台幣 (the central bank's close, ``fx_rates``). Each
  carries its own date and up to 20 earlier closes for a sparkline (the index archive begins 2026-11-12).
* **sectors** — the TWSE 「…類指數」 of the TAIEX's latest day, best first (the four old composite groups whose
  members are listed on their own are left out).
* **movers** — common stocks only (four-digit codes that do not start with ``00``): the 10 biggest gains, the 10
  biggest falls and the 10 largest volumes of the latest day **both** exchanges have published (TWSE and TPEx post
  at different hours; ranking half a market would mislead). The change is measured from the official reference
  price of that day when the archive has it (ex-dividend days), else from the previous close. Only official rows:
  the history backfill's days (``yahoo-history``) are never read here.
* **announcements** — the newest day of 重大訊息 (``market_events``), latest first.
* **summary** — ``forliosa.ai.market_summary`` (shared, one per trading day); ``None`` when there is none.

The rankings scan two days of the whole market, so they are kept in memory per (day, policy).
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.datapolicy import dataset_served, labels, source_clause
from forliosa.marketdata.base import code_of_symbol, market_of_symbol
from forliosa.marketdata.cbc import FX_DATASET, PAIR
from forliosa.marketdata.service import MarketData
from forliosa.models import DatasetStatus, FxRate, IndexDaily, MarketEvent, PriceDaily, ReferencePrice
from forliosa.services import derivatives
from forliosa.services.coverage import NO_DATA_NOTE

TAIEX = "發行量加權股價指數"
TPEX_INDEX = "櫃買指數"
SPARK_POINTS = 20
TOP_N = 10
ANNOUNCEMENTS_MAX = 30
SECTOR_SUFFIX = "類指數"
# TWSE's older composite groups: each is the sum of sectors that are listed on their own, so they are not rows.
SECTOR_COMPOSITES = frozenset({"機電", "塑膠化工", "水泥窯製", "化學生技醫療"})
_COMMON_STOCK = re.compile(r"^(?!00)\d{4}$")
# A close further than this from its base is a data problem or a symbol without a price limit on its first days,
# not a ranking entry (the daily limit is ±10 %).
MAX_MOVE = Decimal("0.11")

_movers_cache: dict[tuple[date, str], dict[str, Any]] = {}
_movers_lock = threading.Lock()


def clear_cache() -> None:
    with _movers_lock:
        _movers_cache.clear()


def _official(stmt, column, md: MarketData):
    return stmt.where(source_clause(column, md.policy))


# -- indices ----------------------------------------------------------------------------------------------------
def _index_rows(db: Session, md: MarketData, name: str) -> list[IndexDaily]:
    stmt = select(IndexDaily).where(IndexDaily.name == name).order_by(IndexDaily.date.desc()).limit(SPARK_POINTS + 1)
    return list(db.scalars(_official(stmt, IndexDaily.source, md)))[::-1]


def _signed_pct(change: Decimal | None, pct: Decimal | None, close: Decimal) -> Decimal | None:
    """The published percentage with the sign of the change; computed from the change when it is missing."""
    if change is None:
        return pct
    if pct is None:
        base = close - change
        return change / base if base else None
    return -abs(pct) if change < 0 else abs(pct)


def _index_item(key: str, label: str, rows: list[IndexDaily], dataset: str) -> tuple[dict[str, Any], str] | None:
    if not rows:
        return None
    last = rows[-1]
    change = last.change
    if change is None and len(rows) > 1:
        change = last.close - rows[-2].close
    return {"key": key, "name": label, "unit": "點", "value": ser.price(last.close), "change": ser.price(change),
            "change_pct": ser.ratio(_signed_pct(change, last.change_pct, last.close)), "date": last.date,
            "sparkline": [{"t": r.date, "v": ser.price(r.close)} for r in rows[-SPARK_POINTS:]]}, dataset


def _futures_item(db: Session, md: MarketData) -> tuple[dict[str, Any], str] | None:
    if not dataset_served("taifex-openapi/futures_daily", md.policy):
        return None
    quotes, day = derivatives._futures_overview(db, md)
    tx = next((q for q in quotes if q["code"] == "TX" and q.get("regular")), None)
    if tx is None or day is None or tx["regular"].get("close") is None:
        return None
    history = derivatives.futures_history(db, md, "TX", "1M")["series"][-SPARK_POINTS:]
    reg = tx["regular"]
    return {"key": "tx", "name": "台指期近月", "unit": "點", "value": reg["close"], "change": reg["change"],
            "change_pct": reg["change_pct"], "date": day,
            "sparkline": [{"t": p["t"], "v": p["close"]} for p in history if p.get("close") is not None]}, \
        "taifex-openapi/futures_daily"


def _fx_item(db: Session, md: MarketData) -> tuple[dict[str, Any], str] | None:
    stmt = select(FxRate).where(FxRate.pair == PAIR).order_by(FxRate.date.desc()).limit(SPARK_POINTS + 1)
    rows = list(db.scalars(_official(stmt, FxRate.source, md)))[::-1]
    if not rows:
        return None
    last = rows[-1]
    change = last.rate - rows[-2].rate if len(rows) > 1 else None
    pct = change / rows[-2].rate if change is not None and rows[-2].rate else None
    return {"key": "usdtwd", "name": "美元兌新台幣", "unit": "元", "value": ser.price(last.rate),
            "change": ser.price(change), "change_pct": ser.ratio(pct), "date": last.date,
            "sparkline": [{"t": r.date, "v": ser.price(r.rate)} for r in rows[-SPARK_POINTS:]]}, FX_DATASET


def _indices(db: Session, md: MarketData) -> tuple[list[dict[str, Any]], list[str], date | None]:
    taiex = _index_rows(db, md, TAIEX)
    found = [_index_item("taiex", "加權指數", taiex, "twse-openapi/index"),
             _index_item("tpex", TPEX_INDEX, _index_rows(db, md, TPEX_INDEX), "tpex-openapi/index"),
             _futures_item(db, md), _fx_item(db, md)]
    items = [f for f in found if f is not None]
    return [i for i, _ in items], [k for _, k in items], (taiex[-1].date if taiex else None)


# -- sectors ----------------------------------------------------------------------------------------------------
def _sectors(db: Session, md: MarketData, day: date | None) -> dict[str, Any] | None:
    if day is None:
        return None
    stmt = select(IndexDaily).where(IndexDaily.date == day, IndexDaily.market == "TWSE",
                                    IndexDaily.name.like(f"%{SECTOR_SUFFIX}"))
    out = []
    for r in db.scalars(_official(stmt, IndexDaily.source, md)):
        pct = _signed_pct(r.change, r.change_pct, r.close)
        name = r.name.removesuffix(SECTOR_SUFFIX)
        if pct is None or "報酬" in r.name or name in SECTOR_COMPOSITES:
            continue
        out.append({"name": name, "index_name": r.name, "close": ser.price(r.close), "change_pct": ser.ratio(pct)})
    if not out:
        return None
    out.sort(key=lambda s: (-s["change_pct"], s["name"]))
    return {"date": day, "items": out}


# -- movers -----------------------------------------------------------------------------------------------------
def _ranking_day(db: Session, md: MarketData) -> date | None:
    """The latest day both exchanges' closes are stored for (``dataset_status``); without those rows, the newest
    official day in ``prices_daily``."""
    days = [d for d in db.scalars(select(DatasetStatus.data_date).where(
        DatasetStatus.key.in_(("twse-openapi/price", "tpex-openapi/price")))) if d is not None]
    if len(days) == 2:
        return min(days)
    return db.scalar(_official(select(func.max(PriceDaily.date)), PriceDaily.source, md))


def _entry(md: MarketData, symbol: str, close: Decimal, base: Decimal, volume: int | None) -> dict[str, Any]:
    info = md.instrument(symbol)
    change = close - base
    return {"symbol": symbol, "code": code_of_symbol(symbol), "name": info.name if info else code_of_symbol(symbol),
            "market": market_of_symbol(symbol), "close": ser.price(close), "change": ser.price(change),
            "change_pct": ser.ratio(change / base), "volume": volume}


def _movers(db: Session, md: MarketData) -> dict[str, Any] | None:
    day = _ranking_day(db, md)
    if day is None:
        return None
    with _movers_lock:
        hit = _movers_cache.get((day, md.policy))
    if hit is not None:
        return hit
    prev = db.scalar(_official(select(func.max(PriceDaily.date)).where(PriceDaily.date < day), PriceDaily.source, md))
    today_rows = db.execute(_official(select(PriceDaily.symbol, PriceDaily.close, PriceDaily.volume)
                                      .where(PriceDaily.date == day), PriceDaily.source, md)).all()
    prev_close: dict[str, Decimal] = {}
    if prev is not None:
        prev_close = dict(db.execute(_official(select(PriceDaily.symbol, PriceDaily.close)
                                               .where(PriceDaily.date == prev), PriceDaily.source, md)).all())
    refs = dict(db.execute(_official(select(ReferencePrice.symbol, ReferencePrice.reference_price)
                                     .where(ReferencePrice.date == day), ReferencePrice.source, md)).all())
    rows = []
    for symbol, close, volume in today_rows:
        if not _COMMON_STOCK.match(code_of_symbol(symbol)) or not close or not volume:
            continue
        base = refs.get(symbol) or prev_close.get(symbol)
        if not base:
            continue
        pct = (close - base) / base
        if abs(pct) > MAX_MOVE:
            continue
        rows.append((symbol, close, base, volume, pct))
    if not rows:
        out = None
    else:
        def top(key, reverse: bool, only=lambda r: True) -> list[dict[str, Any]]:
            picked = sorted((r for r in rows if only(r)), key=key, reverse=reverse)[:TOP_N]
            return [_entry(md, s, c, b, v) for s, c, b, v, _ in picked]

        out = {"date": day, "prev_date": prev, "count": len(rows),
               "gainers": top(lambda r: (r[4], r[3]), True, lambda r: r[4] > 0),
               "losers": top(lambda r: (r[4], -r[3]), False, lambda r: r[4] < 0),
               "volume": top(lambda r: r[3], True)}
    if out is not None:
        with _movers_lock:
            _movers_cache.clear()  # one day at a time
            _movers_cache[(day, md.policy)] = out
    return out


# -- announcements ----------------------------------------------------------------------------------------------
def _announcements(db: Session, md: MarketData) -> dict[str, Any] | None:
    base = MarketEvent.type == "material_info"
    day = db.scalar(_official(select(func.max(MarketEvent.date)).where(base), MarketEvent.source, md))
    if day is None:
        return None
    rows = list(db.scalars(_official(select(MarketEvent).where(base, MarketEvent.date == day),
                                     MarketEvent.source, md)))
    rows.sort(key=lambda r: (_clock((r.data or {}).get("time")) or "", r.symbol), reverse=True)
    items = []
    for r in rows[:ANNOUNCEMENTS_MAX]:
        info = md.instrument(r.symbol)
        items.append({"symbol": r.symbol, "code": code_of_symbol(r.symbol),
                      "name": info.name if info else code_of_symbol(r.symbol), "title": r.title,
                      "time": _clock((r.data or {}).get("time")), "url": r.url})
    return {"date": day, "total": len(rows), "items": items,
            "sources": sorted({f"{r.source}/material_info" for r in rows})}


def _clock(raw: Any) -> str | None:
    """``"173005"`` / ``"92005"`` (no leading zero) / ``"17:30:05"`` → ``"17:30"`` / ``"09:20"``."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if not 4 <= len(digits) <= 6:
        return None
    digits = digits.zfill(6)
    return f"{digits[:2]}:{digits[2:4]}"


# -- the response -----------------------------------------------------------------------------------------------
def overview(db: Session, md: MarketData, now: datetime | None = None) -> dict[str, Any]:
    from forliosa.ai import market_summary

    indices, index_sources, taiex_day = _indices(db, md)
    sectors = _sectors(db, md, taiex_day)
    movers = _movers(db, md)
    announcements = _announcements(db, md)
    market_summary.ensure(db, now)
    summary = market_summary.latest(db, now)
    sources = [*index_sources]
    if movers:
        sources += ["twse-openapi/price", "tpex-openapi/price"]
    if announcements:
        sources += announcements.pop("sources")
    as_of = max((d for d in (taiex_day, movers["date"] if movers else None) if d is not None), default=None)
    empty = not indices and not movers and not announcements
    return {
        "as_of": as_of,
        "indices": indices,
        "summary": summary,
        "sectors": sectors,
        "movers": movers,
        "announcements": announcements,
        "is_demo": False,
        "notes": [NO_DATA_NOTE] if empty else [],
        "sources": labels(dict.fromkeys(sources)),
    }
