"""Charts, tables, the number strip and the calendar block of the market reports — all built by the server from archive
rows (contract §13, §12.1). A model never draws a point: it may only pick one extra 今日圖 from the menu.

Charts use the ``AiChart`` shape the frontend already draws (``ai/remote.ts``), extended with three kinds:

* ``line`` (G1 加權指數), ``columns`` (G7 外資台指期淨未平倉; a ``hidden`` series only in the read-out),
* ``bars`` (G2 類股, G3 點數貢獻, G6 美股 ETF 與 ADR; v2: G17 類股點數貢獻, G15 規模與風格, G8 類股成交比重,
  G2_otc 上櫃類股, G16 上櫃法人依產業別): signed horizontal bars, ``value`` in the unit's scale (``pct`` is a fraction
  like the other charts: 0.0123 = 1.23 %), ``display`` the printed number, ``tone`` the colour (rise / fall for moves,
  ink / pencil for shares and institutional flows). v2 adds an optional baseline, narrow-screen fold, period chips
  and a second number column (:func:`chart`).

Tables use ``TableSpec`` (T2 排行, T3 多期間報酬, T5, T7–T10); the rule a list was picked by is in its header. v2: heat
cells (:func:`heat`) and tab groups (one table at a time on narrow screens).
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
          range_: str | None = None, bench: dict | None = None, fold: dict | None = None,
          views: list[dict] | None = None, aside_label: str | None = None) -> dict[str, Any]:
    """The ``AiChart`` shape. v2 (2026-11-18) adds, only when given: ``bench`` (a dashed baseline across the bars,
    ``{"value", "label"}``), ``fold`` (narrow screens list the first ``head``, ``keep`` and the last ``tail`` bars),
    ``views`` (period chips, each with its own ``bars``, ``bench`` and ``notes``) and ``aside_label`` (the heading of
    the second number column each bar's ``aside`` fills)."""
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
    if bench is not None:
        out["bench"] = bench
    if fold is not None:
        out["fold"] = fold
    if views:
        out["views"] = views
    if aside_label:
        out["aside_label"] = aside_label
    return out


def bar(label: str, value: Any, display: str, tone_: str, sub: str | None = None, href: str | None = None, *,
        aside: str | None = None, group: str | None = None) -> dict[str, Any]:
    out = {"label": label, "value": float(value), "display": display, "tone": tone_, "sub": sub, "href": href}
    if aside is not None:
        out["aside"] = aside
    if group is not None:
        out["group"] = group
    return out


def bench(value: Any, label: str) -> dict[str, Any]:
    """A baseline across the bars: ``value`` in the chart's scale, ``label`` printed above it (「加權 ▼2.31%」)."""
    return {"value": float(value), "label": label}


def pp_text(change: Any) -> str:
    """A change of a share in percentage points: ``+2.2`` / ``−0.7`` / ``0.0`` (``change`` a fraction)."""
    q = round(_d(change) * 100, 1)
    if q == 0:
        return "0.0"
    return f"{'+' if q > 0 else '−'}{abs(q):.1f}"


def g1_index_line(points: list[tuple[date, Decimal]], *, sources: Iterable[str], title: str) -> dict[str, Any] | None:
    """G1: the TAIEX closes (oldest first)."""
    if len(points) < 2:
        return None
    return chart("G1", "line", title, "index", "date",
                 series=[{"name": "加權指數", "symbol": None,
                          "points": [{"t": d.isoformat(), "v": round(float(c), 2)} for d, c in points]}],
                 since=f"{md(points[0][0])} 起", sources=sources)


def g2_sector_bars(rows: list[dict[str, Any]], *, title: str, sources: Iterable[str],
                   notes: Iterable[str] = (), bench_: dict | None = None, views: list[dict] | None = None,
                   reference: dict | None = None, fold: dict | None = None, cid: str = "G2",
                   estimate: bool = False) -> dict[str, Any] | None:
    """G2 (and G2_otc): one bar per sector (``rows``: name, pct, sub), best first. v2: the TAIEX baseline
    (``bench_``), the period chips (``views``, the first is ``rows`` itself), the narrow-screen fold."""
    if not rows:
        return None
    return chart(cid, "bars", title, "pct", "category",
                 bars=[bar(r["name"], r["pct"], pct_text(r["pct"]), tone(r["pct"]), r.get("sub")) for r in rows],
                 sources=sources, notes=notes, bench=bench_, views=views, reference=reference, fold=fold,
                 estimate=estimate)


def sector_view(key: str, label: str, rows: list[dict[str, Any]], bench_: dict | None,
                notes: Iterable[str] = (), *, title: str) -> dict[str, Any]:
    """One period of G2's chips: its own title (with the period's dates), bars (best first over the period),
    baseline and notes."""
    return {"key": key, "label": label, "title": title,
            "bars": [bar(r["name"], r["pct"], pct_text(r["pct"]), tone(r["pct"]), r.get("sub")) for r in rows],
            "bench": bench_, "notes": list(notes)}


SECTOR_FOLD = {"head": 5, "tail": 5, "keep": ["半導體"]}
OTC_FOLD = {"head": 5, "tail": 5, "keep": []}
CONTRIB_NOTE = ("Forliosa 估算：每檔前一日市值權重 × 前一日加權指數 × 漲跌幅，依產業別加總。"
                "權重以上市普通股的已發行股數 × 收盤計，和官方的權重略有差異。")


def g17_sector_contrib_bars(rows: list[dict[str, Any]], rest: dict[str, Any] | None, official: Decimal | None,
                            total: Decimal, groups: int, *, title: str,
                            sources: Iterable[str]) -> dict[str, Any] | None:
    """G17: the sectors that pulled the TAIEX down most and up most (estimated points, ``rows``: name, points, sub),
    then 「其餘 N 類」; the official change and the estimate's sum as reference."""
    if not rows:
        return None
    bars = [bar(r["name"], r["points"], signed_text(r["points"], 0, " 點"), tone(round(_d(r["points"]))),
                r.get("sub")) for r in rows]
    if rest is not None:
        bars.append(bar(f"其餘 {rest['count']} 類", rest["points"], signed_text(rest["points"], 0, " 點"), "pencil",
                        "合計"))
    est = f"{groups} 類估算加總 {signed_text(total, 0, ' 點')}"
    ref = {"label": "官方漲跌", "display": f"{signed_text(official, 2, ' 點')}・{est}"} if official is not None else \
        {"label": "估算加總", "display": est}
    return chart("G17", "bars", title, "points", "category", bars=bars, reference=ref, estimate=True,
                 sources=sources, notes=[CONTRIB_NOTE])


def g15_style_bars(rows: list[dict[str, Any]], bench_: dict | None, *, title: str,
                   sources: Iterable[str]) -> dict[str, Any] | None:
    """G15: the size and style indices (``rows``: group, label, pct), grouped, with the TAIEX baseline."""
    if len(rows) < 2:
        return None
    return chart("G15", "bars", title, "pct", "category",
                 bars=[bar(r["label"], r["pct"], pct_text(r["pct"]), tone(r["pct"]), group=r["group"]) for r in rows],
                 bench=bench_, sources=sources,
                 notes=["虛線是加權指數的漲跌；電子工業是電子類股的合計。"])


def g8_turnover_bars(rows: list[dict[str, Any]], rest: dict[str, Any] | None, *, title: str, notes: Iterable[str],
                     aside_label: str | None, sources: Iterable[str]) -> dict[str, Any] | None:
    """G8: each sector's share of the listed commons' traded value (``rows``: name, share, change, sub), the 8 largest
    then 「其餘 N 類」; ink bars (a share, not a move); ``aside`` the change in percentage points."""
    if not rows:
        return None

    def one(label: str, share: Any, change: Any, sub: str | None, tone_: str) -> dict[str, Any]:
        aside = (pp_text(change) if change is not None else "—") if aside_label else None
        return bar(label, share, f"{_d(share) * 100:.1f}%", tone_, sub, aside=aside)

    bars = [one(r["name"], r["share"], r.get("change"), r.get("sub"), "ink") for r in rows]
    if rest is not None:
        bars.append(one(f"其餘 {rest['count']} 類", rest["share"], rest.get("change"), "合計", "pencil"))
    return chart("G8", "bars", title, "pct", "category", bars=bars, aside_label=aside_label, notes=notes,
                 sources=sources)


def g16_otc_flow_bars(rows: list[dict[str, Any]], total: Decimal | None, *, title: str,
                      sources: Iterable[str]) -> dict[str, Any] | None:
    """G16: TPEx institutional net buying by industry (estimated NT$; ``rows``: name, amount), the largest buys and
    sells; ink and pencil (an institutional flow, not a move)."""
    if not rows:
        return None
    bars = [bar(r["name"], _d(r["amount"]) / Decimal(100_000_000), signed_text(_d(r["amount"]) / Decimal(100_000_000),
                                                                               1, " 億元"),
                "ink" if r["amount"] >= 0 else "pencil", r.get("sub")) for r in rows]
    ref = {"label": "上櫃三大法人合計（估算）",
           "display": f"{'買超' if total >= 0 else '賣超'} {yi_text(abs(total), 1)}"} if total is not None else None
    return chart("G16", "bars", title, "yi", "category", bars=bars, reference=ref, estimate=True, sources=sources,
                 notes=["估算：每檔買賣超股數 × 收盤價，依產業別加總；列買超最多與賣超最多各 5 類。"
                        "上市個股的三大法人沒有開放資料，所以只有上櫃。"])


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
          note: str | None = None, sources: Iterable[str] = (), tab_group: str | None = None,
          tab_label: str | None = None) -> dict[str, Any]:
    """``columns``: (key, label, align, num). ``tab_group``: tables of one section with the same group show one at a
    time on narrow screens, under chips of their ``tab_label`` (「漲幅｜跌幅｜成交值」)."""
    out = {"id": tid, "title": title, "rule": rule,
           "columns": [{"key": k, "label": label, "align": a, "num": n} for k, label, a, n in columns],
           "rows": rows, "fold_after": fold_after, "empty_text": empty_text if not rows else None, "note": note,
           "source_labels": list(dict.fromkeys(sources))}
    if tab_group:
        out["tab_group"] = tab_group
        out["tab_label"] = tab_label or title
    return out


def cell(text: str, tone_: str | None = None, sub: str | None = None, heat: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"text": text}
    if tone_ is not None:
        out["tone"] = tone_ if tone_ in ("rise", "fall") else None
    if sub is not None:
        out["sub"] = sub
    if heat is not None:
        out["heat"] = heat
    return out


# Heat steps of a multi-period cell (the server decides, the page only tints): |move| ≥ the first value is step 1,
# ≥ the second step 2 (T2_top10 v2, T3)
HEAT_STEPS = {"1d": (Decimal("0.01"), Decimal("0.03")), "1w": (Decimal("0.02"), Decimal("0.05")),
              "1m": (Decimal("0.04"), Decimal("0.10"))}


def heat(move: Any, period: str) -> str | None:
    """``rise1`` / ``rise2`` / ``fall1`` / ``fall2`` or ``None`` for a move (a fraction) over ``period``."""
    if move is None:
        return None
    v = _d(move)
    lo, hi = HEAT_STEPS[period]
    if abs(v) < lo:
        return None
    return f"{'rise' if v > 0 else 'fall'}{2 if abs(v) >= hi else 1}"


def move_cell(move: Any, period: str) -> dict[str, Any]:
    """A multi-period cell: the move with its tone and heat, or 「—」 where the archive is too short (never 0)."""
    if move is None:
        return cell("—")
    return cell(pct_text(move), tone(move), heat=heat(move, period))


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
