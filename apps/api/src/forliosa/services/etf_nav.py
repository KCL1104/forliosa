"""ETF NAV and the after-close premium / discount (PRODUCT.md「個股頁補強」第 9 項).

* NAV: 金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉 (data.gov.tw 11109, OGDL), archived daily into
  ``etf_navs`` (``forliosa.archive``, group ``nav``).
* Close: the exchanges' official closes archived from the TWSE / TPEx OpenAPIs (``prices_daily`` rows with source
  ``twse-openapi`` / ``tpex-openapi``) — never demo data, never a quote of another day.
* Premium / discount = close ÷ NAV − 1, **only on a date that has both** (overseas ETFs publish the previous business
  day's NAV, and TWSE's close file can lag a day, so the latest NAV and the latest close often differ: the premium is
  then computed on the newest date both exist, and both latest dates are returned so the page can show them).
* History builds up from the first archived NAV; the page draws the series from :data:`MIN_POINTS` points on.
* No tracking error: it needs the index's daily returns, and index data has no open licence.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.archive import OFFICIAL_CLOSE_SOURCES
from forliosa.datapolicy import labels
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.fund_nav import NAV_DATASET
from forliosa.models import EtfNav, PriceDaily

MIN_POINTS = 20  # same-day (close, NAV) pairs before the history is drawn
HISTORY_POINTS = 60  # at most this many points in the response (about three months of trading days)
LOOKBACK_DAYS = 120  # calendar days of NAV / close rows read to find them

NO_ARCHIVE_NOTE = "資料累積中：ETF 淨值每個交易日晚上存檔"
NOT_IN_DATASET_NOTE = "〈證券投資信託基金每日淨值〉沒有這檔 ETF 的淨值"
NO_MATCH_NOTE = "還沒有同一天的收盤價與淨值，不計算折溢價"


def accumulating_note(since: date) -> str:
    return f"資料累積中：淨值自 {since.isoformat()} 起存檔"


def premium(close: Decimal, nav: Decimal) -> Decimal | None:
    """close ÷ NAV − 1 as a fraction (0.0042 = 溢價 0.42%; negative = 折價)."""
    return close / nav - 1 if nav and nav > 0 else None


def etf_nav(db: Session, info: InstrumentInfo) -> dict[str, Any] | None:
    """The ``etf_nav`` block of ``GET /instruments/{symbol}/overview``; ``None`` for stocks and US listings."""
    if info.market == "US" or info.type != "etf":
        return None
    sym = info.symbol
    latest = db.scalars(select(EtfNav).where(EtfNav.symbol == sym).order_by(EtfNav.date.desc()).limit(1)).first()
    last_close = db.scalars(select(PriceDaily).where(
        PriceDaily.symbol == sym, PriceDaily.source.in_(OFFICIAL_CLOSE_SOURCES)).order_by(PriceDaily.date.desc())
        .limit(1)).first()
    out: dict[str, Any] = {
        "nav": None, "nav_date": None, "currency": None, "fund_name": None,
        "close": ser.price(last_close.close) if last_close else None,
        "close_date": last_close.date if last_close else None,
        "premium_pct": None, "premium_date": None, "history": [], "history_start": None,
        "notes": [], "sources": [],
    }
    if latest is None:
        any_nav = db.scalar(select(EtfNav.symbol).limit(1)) is not None
        out["notes"].append(NOT_IN_DATASET_NOTE if any_nav else NO_ARCHIVE_NOTE)
        return out

    start = db.scalar(select(func.min(EtfNav.date)).where(EtfNav.symbol == sym))
    since = latest.date - timedelta(days=LOOKBACK_DAYS)
    navs = {r.date: r for r in db.scalars(select(EtfNav).where(EtfNav.symbol == sym, EtfNav.date >= since))}
    closes = {r.date: r for r in db.scalars(select(PriceDaily).where(
        PriceDaily.symbol == sym, PriceDaily.date >= since, PriceDaily.source.in_(OFFICIAL_CLOSE_SOURCES)))}
    points: list[dict[str, Any]] = []
    close_sources: dict[str, None] = {}
    for d in sorted(set(navs) & set(closes))[-HISTORY_POINTS:]:
        p = premium(closes[d].close, navs[d].nav)
        if p is not None:
            points.append({"t": d, "nav": ser.price(navs[d].nav), "close": ser.price(closes[d].close),
                           "premium_pct": ser.ratio(p)})
            close_sources[f"{closes[d].source}/price"] = None
    out.update({
        "nav": ser.price(latest.nav), "nav_date": latest.date, "currency": latest.currency,
        "fund_name": latest.fund_name, "history_start": start,
    })
    if points:
        out["premium_pct"], out["premium_date"] = points[-1]["premium_pct"], points[-1]["t"]
    else:
        out["notes"].append(NO_MATCH_NOTE)
    if len(points) < MIN_POINTS and start is not None:
        out["notes"].append(accumulating_note(start))
    out["history"] = points
    out["sources"] = labels([NAV_DATASET, *close_sources])
    return out
