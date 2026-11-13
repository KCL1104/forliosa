"""``draw_chart``: the model names what to draw, the server reads every number.

The model passes a kind, up to five symbols and a range. The handler reads the series from the same services the
pages use (archived daily closes, monthly revenue, quarterly EPS, the user's time-weighted return), so no point
on a chart was written by the model. It returns two things:

* the **card** — the ``chart`` SSE event and what the thread keeps for the history view: every series with its
  points (sampled to ``POINT_BUDGET`` across the chart);
* the **summary** for the model — first / last value, change, high and low of each series plus the notes, so its
  text can say the gist without listing points.

Nothing is drawn when the data cannot show a line (fewer than two closes) or a bar: the result says why
(``status: "no_data"``) and no card is sent. A ``performance`` chart is percentages only (TWR index − 1), so it
carries no amount, cost or share count in any mode.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from forliosa.datapolicy import labels, tagged
from forliosa.ids import new_id
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.services.coverage import covers, series_notes, ymd
from forliosa.timeutil import today_taipei

KINDS = ["price", "compare", "revenue", "eps", "performance"]
RANGES = ["1M", "3M", "6M", "YTD", "1Y", "5Y"]
RANGE_LABELS = {"1M": "近 1 個月", "3M": "近 3 個月", "6M": "近 6 個月", "YTD": "今年以來", "1Y": "近 1 年",
                "5Y": "近 5 年"}
MAX_SYMBOLS = 5
MAX_PER_TURN = 3
POINT_BUDGET = 480  # points across all series of one card (a 5-year daily line is sampled, never truncated)
REVENUE_MONTHS = 24
EPS_QUARTERS = 8
PRICE_ONLY_NOTE = "漲跌幅只算價格變動，不含股利"
SHOWN = ("圖表已顯示在畫面上。文字只講重點：每條線到最後一天的數字（漲跌幅換成百分比）、誰高誰低、資料的起訖日；"
         "不要逐點列出數字；notes 的內容照實轉述。")
NOT_SHOWN = "沒有畫圖。直接寫缺什麼資料（照 notes 的內容），不要提到工具或系統，不要自己補數字。"


class ChartError(Exception):
    """A request the tool cannot draw (message in zh-TW, returned to the model as an ``is_error`` result)."""


def sample(rows: list[Any], n: int) -> list[Any]:
    """At most ``n`` evenly spaced rows, always keeping the first and the last one."""
    if len(rows) <= n or n < 2:
        return rows
    step = (len(rows) - 1) / (n - 1)
    idx = sorted({round(i * step) for i in range(n)} | {len(rows) - 1})
    return [rows[i] for i in idx]


def _f(value: Decimal | float | int, places: int = 4) -> float:
    return round(float(value), places)


def _range_start(range_: str, today: date) -> date:
    from forliosa.services.portfolio import range_start

    return range_start(range_, today, date(1990, 1, 1))


def _closes(md: MarketData, info: InstrumentInfo, range_: str, today: date) -> dict[str, Any]:
    start = _range_start(range_, today)
    h = md.history(info.symbol, start, today, backfill=True)  # a chart: may show the history backfill's days
    rows = [(c.t, c.c) for c in h.candles if c.c is not None]
    notes = series_notes(md, info.symbol, start, rows[0][0] if rows else None, backfill=True)
    return {"rows": rows, "notes": notes, "sources": ["demo"] if h.is_demo else tagged(h.source, "price"),
            "is_demo": h.is_demo, "start": start, "backfill_until": md.backfill_until(info.symbol)}


def _adjustments(md: MarketData, symbol: str) -> dict[date, tuple[str, Decimal]]:
    """Splits and capital reductions by date (the day the price jumps without a gain or a loss)."""
    out: dict[date, tuple[str, Decimal]] = {}
    for e in md.corporate_events(symbol):
        if e.kind in ("split", "capital_reduction") and e.ratio and e.ratio > 0:
            out[e.date] = (e.kind, e.ratio)
    return out


def _factor(kind: str, ratio: Decimal) -> Decimal:
    """What a close after the event is multiplied by to compare it with the close before: a split's ratio is new
    shares per old one, a capital reduction's is the shares removed per share."""
    return ratio if kind == "split" else (Decimal(1) - ratio if ratio < 1 else Decimal(1))


def _comparable(close: Decimal, prev: Decimal, kind: str, ratio: Decimal) -> Decimal:
    """The close of an event day in the terms of the day before. The history backfill's days are already
    split-adjusted by their source while official closes are not, so the factor is applied only when it makes the
    day's change smaller — a series that is already continuous across the event is left alone."""
    adjusted = close * _factor(kind, ratio)
    if not prev:
        return adjusted
    return adjusted if abs(adjusted / prev - 1) < abs(close / prev - 1) else close


def _point(t: Any, v: float) -> dict[str, Any]:
    return {"t": t.isoformat() if isinstance(t, date) else str(t), "v": v}


def _summary(series: dict[str, Any], pct: bool) -> dict[str, Any]:
    pts = series["points"]
    first, last = pts[0], pts[-1]
    hi = max(pts, key=lambda p: p["v"])
    lo = min(pts, key=lambda p: p["v"])
    out: dict[str, Any] = {"name": series["name"], "symbol": series.get("symbol"), "points": len(pts),
                           "from": first["t"], "to": last["t"], "first": first["v"], "last": last["v"],
                           "high": hi, "low": lo}
    if not pct and first["v"]:
        out["change_pct"] = round(last["v"] / first["v"] - 1, 4)
    return out


def _card(kind: str, title: str, unit: str, x: str, series: list[dict[str, Any]], notes: list[str],
          sources: list[str], is_demo: bool, *, range_: str | None = None, currency: str | None = None) -> dict:
    cap = max(40, POINT_BUDGET // max(1, len(series)))
    for s in series:
        s["points"] = sample(s["points"], cap)
    return {"id": new_id("cht"), "kind": kind, "title": title, "unit": unit, "currency": currency, "x": x,
            "range": range_, "series": series, "notes": list(dict.fromkeys(notes)),
            "sources": labels(dict.fromkeys(sources)), "is_demo": is_demo}


def _names(infos: list[InstrumentInfo]) -> str:
    return "、".join(i.name for i in infos)


# -- kinds -----------------------------------------------------------------------------------------------
def price_chart(md: MarketData, info: InstrumentInfo, range_: str) -> dict[str, Any] | list[str]:
    today = today_taipei()
    c = _closes(md, info, range_, today)
    rows, notes = c["rows"], list(c["notes"])
    if len(rows) < 2:
        return notes or [f"{info.name} 的收盤價不到兩天，畫不出走勢"]
    until = c["backfill_until"]  # days up to here come split-adjusted (the series note says so)
    for d, (kind, ratio) in sorted(_adjustments(md, info.symbol).items()):
        if rows[0][0] < d <= rows[-1][0] and (until is None or d > until):
            what = f"股票分割（1 股變 {ratio.normalize():f} 股）" if kind == "split" else "減資"
            notes.append(f"{ymd(d)} {what}，之前是當時的價格")
    notes.append("收盤價沒有還原權息，除權息日會有缺口")
    series = [{"name": info.name, "symbol": info.symbol, "points": [_point(t, _f(v)) for t, v in rows]}]
    return _card("price", f"{info.name} 收盤價（{RANGE_LABELS[range_]}）", "price", "date", series, notes,
                 c["sources"], c["is_demo"], range_=range_, currency=info.currency)


def compare_chart(md: MarketData, infos: list[InstrumentInfo], range_: str) -> dict[str, Any] | list[str]:
    today = today_taipei()
    notes: list[str] = []
    sources: list[str] = []
    is_demo = False
    usable: list[tuple[InstrumentInfo, list[tuple[date, Decimal]]]] = []
    start = _range_start(range_, today)
    for info in infos:
        c = _closes(md, info, range_, today)
        if len(c["rows"]) < 2:
            reason = "；".join(c["notes"]) or "收盤價不到兩天"
            notes.append(f"{info.name}：{reason}，沒有畫")
            continue
        usable.append((info, c["rows"]))
        sources += c["sources"]
        is_demo |= c["is_demo"]
    if len(usable) < 2:
        return notes or ["要比較至少需要兩檔有收盤價的商品"]
    base = max(rows[0][0] for _, rows in usable)  # the first day every line has a close
    late = max(usable, key=lambda u: u[1][0][0])
    if not covers(base, start):
        notes.append(f"從 {ymd(base)} 起算：{late[0].name} 的資料從這天開始")
    series: list[dict[str, Any]] = []
    for info, rows in usable:
        rows = [r for r in rows if r[0] >= base]
        if len(rows) < 2:
            notes.append(f"{info.name}：{ymd(base)} 之後的收盤價不到兩天，沒有畫")
            continue
        adj = _adjustments(md, info.symbol)
        cum, prev = 1.0, rows[0][1]
        pts = [_point(rows[0][0], 0.0)]
        for t, close in rows[1:]:
            if t in adj:
                kind, ratio = adj[t]
                close_cmp = _comparable(close, prev, kind, ratio)
                if close_cmp != close:
                    what = "股票分割" if kind == "split" else "減資"
                    notes.append(f"{info.name} {ymd(t)} {what}，漲跌幅已調整")
            else:
                close_cmp = close
            if prev:
                cum *= float(close_cmp / prev)
            prev = close
            pts.append(_point(t, round(cum - 1, 6)))
        series.append({"name": info.name, "symbol": info.symbol, "points": pts})
    if len(series) < 2:
        return notes or ["要比較至少需要兩檔有收盤價的商品"]
    notes.append(PRICE_ONLY_NOTE)
    drawn = [i for i in infos if any(s["symbol"] == i.symbol for s in series)]
    return _card("compare", f"{_names(drawn)} 漲跌幅（{RANGE_LABELS[range_]}）", "pct", "date", series, notes,
                 sources, is_demo, range_=range_)


def revenue_chart(md: MarketData, infos: list[InstrumentInfo]) -> dict[str, Any] | list[str]:
    notes: list[str] = []
    sources: list[str] = []
    is_demo = False
    series: list[dict[str, Any]] = []
    for info in infos:
        if info.type != "stock" or info.market == "US":
            notes.append(f"{info.name} 沒有月營收資料")
            continue
        ans = md.monthly_revenue(info.symbol)
        rows = sorted(ans.value, key=lambda r: r.period)[-REVENUE_MONTHS:]
        if not rows:
            notes.append(f"{info.name} 沒有月營收資料")
            continue
        series.append({"name": info.name, "symbol": info.symbol,
                       "points": [_point(r.period, float(r.revenue)) for r in rows]})
        sources += ["demo"] if ans.is_demo else tagged(ans.source, "revenue")
        is_demo |= ans.is_demo
    if not series:
        return notes
    drawn = [i for i in infos if any(s["symbol"] == i.symbol for s in series)]
    return _card("revenue", f"{_names(drawn)} 月營收", "amount_k", "month", series, notes, sources, is_demo,
                 currency="TWD")


def eps_chart(db: Any, md: MarketData, infos: list[InstrumentInfo]) -> dict[str, Any] | list[str]:
    from forliosa.services import stock as svc

    if len({i.currency for i in infos}) > 1:
        raise ChartError("台股和美股的每股盈餘幣別不同，不能畫在同一張圖；請分開畫")
    notes: list[str] = []
    sources: list[str] = []
    series: list[dict[str, Any]] = []
    for info in infos:
        if info.type != "stock":
            notes.append(f"{info.name} 沒有每股盈餘資料")
            continue
        f = svc.financials(db, md, info.symbol, "quarterly")
        pairs = [(p, v) for p, v in zip(f.get("periods") or [], (f.get("income") or {}).get("eps") or [],
                                        strict=False) if v is not None][-EPS_QUARTERS:]
        if not pairs:
            notes.append(f"{info.name} 沒有每股盈餘資料")
            notes += [f"{info.name}：{n}" for n in f.get("notes") or []]
            continue
        series.append({"name": info.name, "symbol": info.symbol, "points": [_point(p, _f(v)) for p, v in pairs]})
        sources += f.get("sources") or []
    if not series:
        return notes
    drawn = [i for i in infos if any(s["symbol"] == i.symbol for s in series)]
    card = _card("eps", f"{_names(drawn)} 每季每股盈餘", "eps", "quarter", series, notes, [], False,
                 currency=drawn[0].currency)
    card["sources"] = list(dict.fromkeys(sources))  # ``financials`` already returns labels
    return card


def performance_chart(db: Any, md: MarketData, user: Any, range_: str, benchmark: str | None) -> dict | list[str]:
    from forliosa.services import portfolio as psvc

    perf = psvc.performance(db, user, md, "ALL" if range_ == "5Y" else range_, benchmark, None)
    rows = perf.get("series") or []
    notes = list(perf.get("notes") or [])
    if len(rows) < 2:
        return notes or ["帳本的資料不到兩個交易日，畫不出報酬率"]
    bench = perf["benchmark"]
    mine = {"name": "我的報酬率", "symbol": None,
            "points": [_point(r["t"], round(r["twr_index"] - 1, 6)) for r in rows]}
    series = [mine]
    if all(r.get("benchmark_index") is not None for r in rows):
        series.append({"name": bench["name"], "symbol": bench["symbol"],
                       "points": [_point(r["t"], round(r["benchmark_index"] - 1, 6)) for r in rows]})
    label = "全部期間" if range_ == "5Y" else RANGE_LABELS[range_]
    title = f"我的報酬率與{bench['name']}（{label}）" if len(series) > 1 else f"我的報酬率（{label}）"
    notes.append("報酬率是時間加權報酬率；基準含股利")
    return _card("performance", title, "pct", "date", series, notes, ["ledger"], bool(perf.get("is_demo")),
                 range_=range_)


# -- the tool ----------------------------------------------------------------------------------------------
def draw(db: Any, md: MarketData, user: Any, resolve: Any, args: dict[str, Any], drawn: int) -> dict[str, Any]:
    """Returns ``{"card": <card or None>, "result": <what the model reads>}``. ``resolve`` maps the model's text to
    an instrument (``tools.resolve_instrument``); ``drawn`` is how many cards this turn already has."""
    kind, range_ = args.get("kind"), args.get("range")
    if kind not in KINDS:
        raise ChartError(f"kind 必須是 {'、'.join(KINDS)} 其中之一")
    if range_ not in RANGES:
        raise ChartError(f"range 必須是 {'、'.join(RANGES)} 其中之一")
    if drawn >= MAX_PER_TURN:
        raise ChartError(f"這一則回答已經畫了 {MAX_PER_TURN} 張圖，不能再畫")
    raw = args.get("symbols")
    if not isinstance(raw, list) or any(not isinstance(s, str) for s in raw):
        raise ChartError("symbols 必須是代號或名稱的清單")
    texts = [s.strip() for s in raw if s.strip()]
    if len(texts) > MAX_SYMBOLS:
        raise ChartError(f"一張圖最多 {MAX_SYMBOLS} 檔")
    if kind == "performance":
        if len(texts) > 1:
            raise ChartError("performance 最多給一檔當作比較的基準")
        built = performance_chart(db, md, user, range_, texts[0] if texts else None)
    else:
        infos: list[InstrumentInfo] = []
        for t in texts:
            info = resolve(md, t)
            if all(info.symbol != i.symbol for i in infos):
                infos.append(info)
        if not infos:
            raise ChartError("請在 symbols 填要畫的股票代號或名稱")
        if kind == "price":
            if len(infos) != 1:
                raise ChartError("price 一次畫一檔；要比較幾檔的走勢請用 compare")
            built = price_chart(md, infos[0], range_)
        elif kind == "compare":
            if len(infos) < 2:
                raise ChartError("compare 需要 2 到 5 檔")
            built = compare_chart(md, infos, range_)
        elif kind == "revenue":
            built = revenue_chart(md, infos)
        else:
            built = eps_chart(db, md, infos)
    if isinstance(built, list):
        return {"card": None, "result": {"status": "no_data", "kind": kind, "notes": built,
                                         "instruction": NOT_SHOWN}}
    pct = built["unit"] == "pct"
    units = {"price": "收盤價（原幣，見 currency）",
             "pct": ("分數（0.0123＝1.23%），以共同的第一天為 0" if kind == "compare"
                     else "分數（0.0123＝1.23%），區間累積報酬率"),
             "amount_k": "新台幣千元", "eps": "每股盈餘（元，見 currency）"}[built["unit"]]
    result = {"status": "chart_shown", "chart_id": built["id"], "kind": kind, "title": built["title"],
              "currency": built["currency"], "units": units,
              "series": [_summary(s, pct) for s in built["series"]], "notes": built["notes"],
              "sources": built["sources"], "is_demo": built["is_demo"], "instruction": SHOWN}
    return {"card": built, "result": result}
