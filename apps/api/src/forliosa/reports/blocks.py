"""Charts, tables, the number strip and the calendar block of the market reports — all built by the server from archive
rows (contract §13, §12.1). A model never draws a point: it may only pick one extra 今日圖 from the menu.

Charts use the ``AiChart`` shape the frontend already draws (``ai/remote.ts``), extended with three kinds:

* ``line`` (G1 加權指數), ``columns`` (G7 外資台指期淨未平倉; a ``hidden`` series only in the read-out),
* ``bars`` (G2 類股, G3 點數貢獻, G4 漲跌家數, G6 美股 ETF 與 ADR): signed horizontal bars, ``value`` in the
  unit's scale (``pct`` is a fraction like the other charts: 0.0123 = 1.23 %), ``display`` the printed number,
  ``tone`` the colour.

Tables use ``TableSpec`` (T2 排行, T3 多期間報酬, T5–T8, T-evening); the rule a list was picked by is in its header.
Nothing here predicts: no trend line, no band, no support or resistance, no score.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from forliosa.reports.calendars import FOLD_LABELS, FOLD_UNITS, CalEvent
from forliosa.reports.schedule import md, md_wd

STOCK_HREF = "/stock/{symbol}"


# -- formatting (the same text the facts carry as ``display``) ---------------------------------------------------------
def _d(x: Any) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def tone(x: Any) -> str:
    if x is None:
        return "flat"
    v = _d(x)
    return "rise" if v > 0 else "fall" if v < 0 else "flat"


def pct_text(p: Any, nd: int = 2) -> str:
    """A fraction as ``▲1.23%`` / ``▼6.03%`` / ``0.00%``."""
    v = _d(p) * 100
    q = round(v, nd)
    if q == 0:
        return f"{0:.{nd}f}%"
    return f"{'▲' if q > 0 else '▼'}{abs(q):,.{nd}f}%"


def points_text(v: Any, nd: int = 2) -> str:
    """An index change as ``▲1,545.23`` / ``▼2,635.04`` / ``平盤``."""
    q = round(_d(v), nd)
    if q == 0:
        return "平盤"
    return f"{'▲' if q > 0 else '▼'}{abs(q):,.{nd}f}"


def signed_text(v: Any, nd: int = 0, unit: str = "") -> str:
    """``+95 點`` / ``−2,635 點`` (a true minus sign)."""
    q = round(_d(v), nd)
    sign = "+" if q > 0 else "−" if q < 0 else ""
    return f"{sign}{abs(q):,.{nd}f}{unit}"


def number_text(v: Any, nd: int = 2) -> str:
    return f"{round(_d(v), nd):,.{nd}f}"


def yi_text(v: Any, nd: int = 0) -> str:
    """NT$ as ``9,009 億元``."""
    return f"{round(_d(v) / Decimal(100_000_000), nd):,.{nd}f} 億元"


def zhao_text(v: Any, nd: int = 2) -> str:
    """NT$ as ``37.08 兆元``."""
    return f"{round(_d(v) / Decimal(1_000_000_000_000), nd):,.{nd}f} 兆元"


def lots_text(v: Any) -> str:
    return f"{int(v):,} 口"


def price_text(v: Any) -> str:
    return f"{_d(v):,.2f}"


def stock_label(name: str, code: str) -> str:
    return f"{name}（{code}）"


# -- charts ----------------------------------------------------------------------------------------------------------
def chart(cid: str, kind: str, title: str, unit: str, x: str, *, series: list[dict] | None = None,
          bars: list[dict] | None = None, reference: dict | None = None, estimate: bool = False,
          since: str | None = None, notes: Iterable[str] = (), sources: Iterable[str] = (),
          range_: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": cid, "kind": kind, "title": title, "unit": unit, "currency": None, "x": x,
                           "range": range_, "series": series or [], "notes": list(notes),
                           "sources": list(dict.fromkeys(sources)), "is_demo": False}
    if bars is not None:
        out["bars"] = bars
    if reference is not None:
        out["reference"] = reference
    if estimate:
        out["estimate"] = True
    if since:
        out["since"] = since
    return out


def bar(label: str, value: Any, display: str, tone_: str, sub: str | None = None,
        href: str | None = None) -> dict[str, Any]:
    return {"label": label, "value": float(value), "display": display, "tone": tone_, "sub": sub, "href": href}


def g1_index_line(points: list[tuple[date, Decimal]], *, sources: Iterable[str], title: str) -> dict[str, Any] | None:
    """G1: the TAIEX closes (oldest first)."""
    if len(points) < 2:
        return None
    return chart("G1", "line", title, "index", "date",
                 series=[{"name": "加權指數", "symbol": None,
                          "points": [{"t": d.isoformat(), "v": round(float(c), 2)} for d, c in points]}],
                 since=f"{md(points[0][0])} 起", sources=sources)


def g2_sector_bars(rows: list[dict[str, Any]], *, title: str, sources: Iterable[str],
                   notes: Iterable[str] = ()) -> dict[str, Any] | None:
    """G2: one bar per sector (``rows``: name, pct, sub), best first."""
    if not rows:
        return None
    return chart("G2", "bars", title, "pct", "category",
                 bars=[bar(r["name"], r["pct"], pct_text(r["pct"]), tone(r["pct"]), r.get("sub")) for r in rows],
                 sources=sources, notes=notes)


def g3_contribution_bars(rows: list[dict[str, Any]], rest: Decimal | None, official: Decimal | None, *, title: str,
                         sources: Iterable[str]) -> dict[str, Any] | None:
    """G3: the 10 largest stocks' estimated points, then 「其餘合計」, with the official change as reference."""
    if not rows:
        return None
    bars = [bar(r["label"], r["points"], signed_text(r["points"], 0, " 點"), tone(r["points"]),
                href=STOCK_HREF.format(symbol=r["symbol"])) for r in rows]
    if rest is not None:
        bars.append(bar("其餘合計", rest, signed_text(rest, 0, " 點"), "pencil", "市值前 10 以外的上市普通股"))
    ref = {"label": "官方漲跌", "display": signed_text(official, 2, " 點")} if official is not None else None
    return chart("G3", "bars", title, "points", "category", bars=bars, reference=ref, estimate=True,
                 sources=sources, notes=["Forliosa 估算：前一日加權指數 × 前一日市值權重 × 漲跌幅"])


def g4_breadth_bars(up: int, flat: int, down: int, lu: int, ld: int, *, title: str,
                    sources: Iterable[str]) -> dict[str, Any]:
    rows = (("上漲", up, "rise"), ("平盤", flat, "ink"), ("下跌", down, "fall"), ("漲停", lu, "rise"),
            ("跌停", ld, "fall"))
    return chart("G4", "bars", title, "count", "category",
                 bars=[bar(label, n, f"{n:,} 家", t) for label, n, t in rows], sources=sources,
                 notes=["上市普通股；漲跌以當天參考價計，漲跌停以官方漲跌停價計"])


def g6_us_bars(rows: list[dict[str, Any]], *, title: str, sources: Iterable[str]) -> dict[str, Any] | None:
    """G6: SPY, DIA, ONEQ, SMH and TSMC's ADR as moves (never index points)."""
    if not rows:
        return None
    return chart("G6", "bars", title, "pct", "category",
                 bars=[bar(r["label"], r["pct"], pct_text(r["pct"]), tone(r["pct"]), r.get("sub")) for r in rows],
                 sources=sources, notes=["ETF 與 ADR 的漲跌，不是指數點數"])


def g7_futures_columns(series: list[tuple[date, int]], *, title: str, sources: Iterable[str]) -> dict[str, Any] | None:
    """G7: foreign investors' TAIEX futures net open interest (contracts), with the day's change hidden for read-out."""
    if len(series) < 2:
        return None
    pts = [{"t": d.isoformat(), "v": oi} for d, oi in series]
    changes = [{"t": series[i][0].isoformat(), "v": series[i][1] - series[i - 1][1]} for i in range(1, len(series))]
    return chart("G7", "columns", title, "lots", "day",
                 series=[{"name": "淨未平倉", "symbol": None, "points": pts[1:]},
                         {"name": "較前一日", "symbol": None, "points": changes, "hidden": True}],
                 sources=sources, notes=["正值是淨多單，負值是淨空單"])


# -- tables ----------------------------------------------------------------------------------------------------------
def table(tid: str, title: str, columns: list[tuple[str, str, str, bool]], rows: list[dict[str, Any]], *,
          rule: str | None = None, fold_after: int | None = None, empty_text: str | None = None,
          note: str | None = None, sources: Iterable[str] = ()) -> dict[str, Any]:
    """``columns``: (key, label, align, num)."""
    return {"id": tid, "title": title, "rule": rule,
            "columns": [{"key": k, "label": label, "align": a, "num": n} for k, label, a, n in columns],
            "rows": rows, "fold_after": fold_after, "empty_text": empty_text if not rows else None, "note": note,
            "source_labels": list(dict.fromkeys(sources))}


def cell(text: str, tone_: str | None = None, sub: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"text": text}
    if tone_ is not None:
        out["tone"] = tone_ if tone_ in ("rise", "fall") else None
    if sub is not None:
        out["sub"] = sub
    return out


STOCK_COLUMNS = [("stock", "股票", "left", False), ("close", "收盤", "right", True), ("pct", "漲跌幅", "right", True)]


def stock_row(q: Any, extra: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    cells = {"stock": cell(stock_label(q.name, q.code)), "close": cell(price_text(q.close)),
             "pct": cell(pct_text(q.pct) if q.pct is not None else "—", tone(q.pct))}
    cells.update(extra or {})
    return {"cells": cells, "href": STOCK_HREF.format(symbol=q.symbol)}


# -- number strip ----------------------------------------------------------------------------------------------------
def number(key: str, label: str, value: str, *, change: str | None = None, tone_: str | None = None,
           date_label: str = "", estimate: bool = False, note: str | None = None) -> dict[str, Any]:
    return {"key": key, "label": label, "value": value, "change": change,
            "tone": tone_ if tone_ in ("rise", "fall", "flat") else None, "date_label": date_label,
            "estimate": estimate, "note": note}


# -- calendar block (T1) ---------------------------------------------------------------------------------------------
def calendar_block(events: list[CalEvent], *, title: str, labels: dict[str, str] | None = None,
                   empty_text: str = "這段期間沒有已排定的事件。") -> dict[str, Any]:
    """Grouped by date; ETF / bond ETF / REIT ex-dividend rows, invited conferences and the filings of companies
    outside the 100 largest fold into one line each (contract §7.6.4)."""
    labels = labels or {}
    by_day: dict[date, list[CalEvent]] = {}
    for e in events:
        by_day.setdefault(e.date, []).append(e)
    groups = []
    for d in sorted(by_day):
        rows, folds = [], {}
        for e in by_day[d]:
            r = cal_row(e, labels)
            if e.fold:
                folds.setdefault(e.fold, []).append(r)
            else:
                rows.append(r)
        groups.append({"date": d.isoformat(), "date_label": md_wd(d), "rows": rows,
                       "folded": [{"label": f"{FOLD_LABELS[k]} {len(v)} {FOLD_UNITS[k]}", "count": len(v), "rows": v}
                                  for k, v in folds.items()]})
    return {"title": title, "groups": groups, "empty_text": None if groups else empty_text,
            "source_labels": sorted({labels.get(e.source, e.source) for e in events})}


def cal_row(e: CalEvent, labels: dict[str, str] | None = None) -> dict[str, Any]:
    labels = labels or {}
    return {"time_label": e.time_label, "title": e.title, "kind": e.kind, "kind_label": e.kind_label,
            "sectors": list(e.sectors), "symbol": e.symbol,
            "href": STOCK_HREF.format(symbol=e.symbol) if e.symbol and "." in e.symbol else None,
            "url": e.url, "source_label": labels.get(e.source, e.source)}
