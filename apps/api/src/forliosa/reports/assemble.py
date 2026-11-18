"""The report JSON (contract §12): the sections of each kind in their fixed order, the server's charts, tables, number
strip and calendar, the AI sentences with their footnotes, the sources, the disclaimers and the model line.

``build`` makes the **admin form** that ``market_report_versions.payload`` keeps: every sentence with its ``refs``
(F001, X003 …) and dropped sections with their reasons. :func:`public` turns it into what a member reads: no refs, no
dropped section, no id string anywhere (``F\\d{3}`` / ``X\\d{3}``), no quote.

:func:`data_highlights` and :func:`data_title` are the rule-made headline and highlights (§12.4) of the data edition,
also used when the writer's title or highlights failed the checks.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime
from typing import Any

from forliosa.datapolicy import label as source_label
from forliosa.reports.prompts import STOCKS_NOT_FOUND
from forliosa.reports.schedule import KIND_LABELS, md, md_wd, span
from forliosa.timeutil import TAIPEI, iso_taipei

# The site's rule (2026-11-17 disclaimers, ``forliosa.disclaimer``): say plainly that Forliosa only organises
# information and is not an investment adviser — the report's own lines keep 「報告本文人人相同」 (contract §12.2).
DISCLAIMER_AI = "AI 依公開資料與媒體報導整理，報告本文人人相同，可能有錯；Forliosa 不是投資顧問，不提供投資建議。"
DISCLAIMER_DATA = "依公開資料整理，報告本文人人相同；Forliosa 不是投資顧問，不提供投資建議。"
DISCLAIMER_FULL = ("這份報告由 AI 依公開資料與媒體報導整理，報告本文人人相同，不針對任何人的持股或財務狀況。"
                   "Forliosa 只替你整理資訊，不是投資顧問；這份報告不是投資建議，也不推薦買賣任何股票。"
                   "內容可能有錯，請以原始來源為準。標「估算」的數字是 Forliosa 自己算的。")
# an edition without AI text (the data editions, a fallback, every AI section dropped): no AI or media wording
DISCLAIMER_FULL_DATA = ("這份報告依公開資料整理，報告本文人人相同，不針對任何人的持股或財務狀況。"
                        "Forliosa 只替你整理資訊，不是投資顧問；這份報告不是投資建議，也不推薦買賣任何股票。"
                        "內容可能有錯，請以原始來源為準。標「估算」的數字是 Forliosa 自己算的。")
MODEL_LINE = "這份報告的 AI 段落由 Anthropic 的 Claude 模型撰寫。"
MODEL_LINE_MENTION = "報告內容提到 Anthropic，撰寫的模型也是 Anthropic 的。"
STATUS_WAITING = "AI 段落還在整理，這是只有資料的版本。"
STATUS_DATA_ONLY = "這一份沒有 AI 段落，只有資料。"
NO_WEB = "本份未取得海外消息，只依官方資料。"
MANUAL_SOURCES = "美股休市、總經行事曆與美股財報日：Forliosa 自行整理，每列連回官方頁面"
ORIGIN_LABEL = {"data": "資料", "ai": "AI 依資料與報導整理"}
NOTE_TEXT = {
    "official_index_missing": "官方加權指數尚未取得，指數相關的數字改用 Forliosa 依市值估算。",
    "twse_close_missing": "上市收盤還沒有進來。",
    "week_closed": "台股這一週整週休市，這份週報只有下週行事曆與國際段落。",
    "week_not_archived": "這一週的上市收盤還沒有存檔，這份週報只有下週行事曆與國際段落。",
}
ID_PATTERN = re.compile(r"\b[FXCNW]\d{3}\b")

# (section key, title, output key or None, collapsed on phones). v2 (2026-11-18): the premarket has 「昨日台股全貌」
# (data only, the previous session's sectors; :func:`section_title` adds its date) and 「昨日籌碼」 (the evening's
# notes, the futures and TPEx institutions, margin); its single-chart 「圖」 section is gone; the weekly's
# 「多期間報酬」 is part of 「類股一週與大方向」.
SECTIONS: dict[str, list[tuple[str, str, str | None, bool]]] = {
    "premarket": [("overnight", "隔夜要聞", "overnight", False), ("watch", "今天市場在看什麼", "watch", False),
                  ("yesterday", "昨日台股全貌", None, False),
                  ("chips", "昨日籌碼（晚間公布）", "evening_notes", True), ("chart_of_day", "今日圖", None, True)],
    "close": [("what_happened", "今天發生什麼", "what_happened", False), ("sectors", "類股", "sectors", False),
              ("stocks", "權值股與個股", "stocks", True), ("chips", "籌碼", "chips", True),
              ("tonight", "盤後重大訊息與今晚要看的", "tonight", True), ("chart_of_day", "今日圖", None, True),
              ("otc", "上櫃", None, True)],
    "weekly": [("summary", "這一週", "summary", False), ("market_week", "上週大盤", "market_week", False),
               ("sectors_week", "類股一週與大方向", "sectors_week", False),
               ("stocks_week", "權值股與個股", "stocks_week", True), ("chips_week", "籌碼", "chips_week", True),
               ("global_week", "國際", "global_week", True),
               ("last_week_review", "上週行事曆回顧", "last_week_review", True),
               ("themes", "市場關注的主題", "themes", False), ("risks", "可能讓關注點改變的事", "risks", False),
               ("chart_of_day", "本週圖", None, True)],
}
OUTPUT_TO_SECTION = {k: {out: sec for sec, _t, out, _c in v if out} for k, v in SECTIONS.items()}
# the chart of the day (the writer's pick) -> the server's chart; G2 and G4 left the menus in v2 (G2 is fixed, G4's
# breadth is the number strip's or G2's reference line)
CHART_KEYS = {"premarket": {"G5": "G5"}, "close": {"G5": "G5"}, "weekly": {"G5": "G5"}}
# the server's blocks of each section, in order (charts by id, tables by id)
YESTERDAY_CHARTS = ("G17", "G15", "G2", "G2_otc", "G8")
CLOSE_SECTOR_CHARTS = ("G17", "G15", "G2", "G8")


# -- small helpers -----------------------------------------------------------------------------------------------
def _d(iso: str | None) -> date | None:
    try:
        return date.fromisoformat(str(iso)[:10]) if iso else None
    except ValueError:
        return None


def _sent(text: str, refs: list[str]) -> dict[str, Any]:
    return {"text": text, "refs": list(refs), "cites": []}


def _para(*sents: dict[str, Any]) -> dict[str, Any]:
    return {"sentences": list(sents)}


def _para_from(p: Any) -> dict[str, Any] | None:
    if not isinstance(p, dict):
        return None
    sents = [_sent(str(s.get("text") or ""), [str(r) for r in s.get("refs") or []])
             for s in p.get("sentences") or [] if isinstance(s, dict) and str(s.get("text") or "").strip()]
    return {"sentences": sents} if sents else None


def as_of_label(as_of: datetime) -> str:
    t = as_of.astimezone(TAIPEI)
    return f"資料截至 {t.month}/{t.day} {t:%H:%M}"


def section_title(kind: str, key: str, title: str, pack: dict[str, Any]) -> str:
    """A section's title; the premarket's 「昨日台股全貌」 says which session (「昨日台股全貌（11/17）」)."""
    if kind == "premarket" and key == "yesterday":
        prev = _d(next(iter((pack.get("dates") or {}).get("prev_session") or []), None))
        return f"{title}（{md(prev)}）" if prev else title
    return title


def edition_label(kind: str, edition_date: date, period: tuple[date, date]) -> str:
    return f"{span(*period)} 回顧" if kind == "weekly" else md_wd(edition_date)


# -- rule-made headline and highlights (§12.4) --------------------------------------------------------------------
def _facts(pack: dict[str, Any], metric: str, group: str | None = None) -> list[dict[str, Any]]:
    return [f for f in pack.get("facts") or []
            if f.get("metric") == metric and (group is None or f.get("group") == group)]


def _first(pack: dict[str, Any], metric: str, group: str | None = None, subject: str | None = None) \
        -> dict[str, Any] | None:
    return next((f for f in _facts(pack, metric, group) if subject is None or f.get("subject") == subject), None)


def data_title(kind: str, pack: dict[str, Any]) -> str:
    ed = _d(pack.get("edition_date")) or date.today()
    if kind == "premarket":
        # what the data edition has: the US close, the day's calendar (never named when it is empty), else the
        # evening's numbers
        us = (pack.get("dates") or {}).get("us_sessions") or []
        last = _d(us[-1]) if us else None
        parts = [f"美股 {md(last)} 收盤"] if last else []
        if any(c.get("date") == pack.get("edition_date") for c in pack.get("calendar") or []):
            parts.append("今日行事曆")
        if not parts:
            facts = pack.get("facts") or []
            prev = any(f.get("group") == "prev_session" for f in facts)
            evening = any(f.get("group") == "evening" for f in facts)
            parts.append("昨日台股全貌" if prev else "昨日籌碼" if evening else "隔夜沒有新的資料")
        return f"盤前重點 {md_wd(ed)}：" + "與".join(parts)
    if kind == "close":
        pct = _first(pack, "index_pct", "today", "加權指數")
        close = _first(pack, "index_close", "today", "加權指數")
        if pct and close:
            return f"盤後重點 {md_wd(ed)}：加權指數 {pct['display']}，收 {close['display']} 點"
        est = _first(pack, "mcap_change_est")
        if est:
            return f"盤後重點 {md_wd(ed)}：上市市值估算 {est['display']}"
        return f"盤後重點 {md_wd(ed)}"
    p = pack.get("period") or {}
    start, end = _d(p.get("start")), _d(p.get("end"))
    wk = _first(pack, "week_pct", "week", "加權指數")
    head = f"市場週報 {span(start, end)}" if start and end else "市場週報"
    return f"{head}：加權指數週 {wk['display']}" if wk else head


def data_highlights(kind: str, pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to three (weekly: three) rule-made highlights, each sentence citing the facts it shows."""
    out: list[dict[str, Any]] = []
    facts = pack.get("facts") or []
    if kind == "premarket":
        us = [f for f in facts if f.get("metric") == "us_pct" and f.get("group") == "overnight"]
        if us:
            last = max(f.get("date") or "" for f in us)
            row = [f for f in us if f.get("date") == last]
            d = _d(last)
            text = f"美股 ETF（美股 {md(d) if d else ''} 收盤）：" + "、".join(
                f"{f['subject']} {f['display']}" for f in row)
            out.append(_para(_sent(text, [f["id"] for f in row])))
        ed = pack.get("edition_date")
        today = [c for c in pack.get("calendar") or [] if c.get("date") == ed]
        key = next((c for c in today if c.get("kind") == "settlement"), None) or next(
            (c for c in today if not c.get("fold")
             and c.get("kind") in ("investor_conference", "macro", "us_earnings")),
            None)
        n_ex = sum(1 for c in today if c.get("kind") == "ex_dividend" and not c.get("fold"))
        n_conf = sum(1 for c in today if c.get("kind") == "investor_conference" and not c.get("fold"))
        parts = []
        refs = []
        if key is not None:
            parts.append(key["title"])
            refs.append(key["id"])
        if n_ex or n_conf:
            parts.append(f"市值前 100 中 {n_ex} 家除權息、{n_conf} 家法說會")
            refs += [c["id"] for c in today if c.get("kind") in ("ex_dividend", "investor_conference")
                     and not c.get("fold")][:6]
        if parts:
            out.append(_para(_sent("今天：" + "；".join(parts), refs)))
        net = _first(pack, "futures_oi_net", "evening")
        if net:
            ch = _first(pack, "futures_oi_change", "evening")
            d = _d(net.get("date"))
            text = f"外資台指期淨未平倉（{md(d) if d else ''}）：{net['display']}" \
                + (f"，較前一日 {ch['display']}" if ch else "")
            out.append(_para(_sent(text, [net["id"], *([ch["id"]] if ch else [])])))
        return out
    if kind == "close":
        close, chg, pct = (_first(pack, m, "today", "加權指數") for m in ("index_close", "index_change", "index_pct"))
        if close and chg and pct:
            out.append(_para(_sent(f"加權指數收 {close['display']} 點，{chg['display']} 點（{pct['display']}）",
                                   [close["id"], chg["id"], pct["id"]])))
        elif (est := _first(pack, "mcap_change_est")) is not None:
            out.append(_para(_sent(f"上市市值變化（Forliosa 估算）：{est['display']}", [est["id"]])))
        up, down = _first(pack, "adv_up", "today"), _first(pack, "adv_down", "today")
        lu, ld = _first(pack, "limit_up", "today"), _first(pack, "limit_down", "today")
        if up and down:
            text = f"上漲 {up['display']}、下跌 {down['display']}"
            refs = [up["id"], down["id"]]
            if lu and ld:
                text += f"；漲停 {lu['display']}、跌停 {ld['display']}"
                refs += [lu["id"], ld["id"]]
            out.append(_para(_sent(text, refs)))
        contribs = [f for f in facts if f.get("metric") == "stock_contrib" and isinstance(f.get("value"), (int, float))]
        if contribs:
            top = max(contribs, key=lambda f: abs(f["value"]))
            out.append(_para(_sent(f"點數貢獻最大：{top['subject']} 約 {top['display']}（估算）", [top["id"]])))
        return out
    wk, pts = _first(pack, "week_pct", "week", "加權指數"), _first(pack, "week_points", "week", "加權指數")
    if wk:
        out.append(_para(_sent(f"加權指數週 {wk['display']}" + (f"（{pts['display']} 點）" if pts else ""),
                               [wk["id"], *([pts["id"]] if pts else [])])))
    tv = _first(pack, "turnover", "week") or _first(pack, "turnover_est", "week")
    if tv:
        est = "（估算）" if tv.get("estimate") else ""
        out.append(_para(_sent(f"全週上市成交金額 {tv['display']}{est}", [tv["id"]])))
    secs = [s for s in pack.get("sectors") or [] if not s.get("concentrated")]
    by_fact = {f["id"]: f for f in facts}
    vals = [(s, by_fact.get(s.get("fact") or "")) for s in secs]
    vals = [(s, f) for s, f in vals if f and isinstance(f.get("value"), (int, float))]
    if vals:
        hi = max(vals, key=lambda x: x[1]["value"])
        lo = min(vals, key=lambda x: x[1]["value"])
        out.append(_para(_sent(f"週漲幅最大的類股：{hi[0]['name']} {hi[1]['display']}；"
                               f"最小：{lo[0]['name']} {lo[1]['display']}"
                               "（排除一檔占一半以上的類股）", [hi[1]["id"], lo[1]["id"]])))
    return out


# -- blocks --------------------------------------------------------------------------------------------------------
def _text(paras: list[dict[str, Any]]) -> dict[str, Any] | None:
    paras = [p for p in paras if p]
    return {"type": "text", "paragraphs": paras} if paras else None


def _chart(blocks: dict[str, Any], key: str, caption: dict[str, Any] | None = None,
           chart_of_day: bool = False) -> dict[str, Any] | None:
    c = (blocks.get("charts") or {}).get(key)
    if not isinstance(c, dict):
        note = (blocks.get("notes") or {}).get(key.split("_")[0])
        return {"type": "note", "text": note} if note else None
    return {"type": "chart", "chart": c, "caption": caption, "chart_of_day": chart_of_day}


def _table(blocks: dict[str, Any], tid: str) -> dict[str, Any] | None:
    t = (blocks.get("tables") or {}).get(tid)
    return {"type": "table", "table": t} if isinstance(t, dict) else None


def _items(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return {"type": "items", "items": rows} if rows else None


def _cal_meta(pack: dict[str, Any], time_ref: str, sectors: list[str]) -> str | None:
    c = next((x for x in pack.get("calendar") or [] if x.get("id") == time_ref), None)
    parts = []
    if c is not None:
        t = c.get("time_taipei")
        d = _d(c.get("date"))
        parts.append(f"台北 {md(d)} {t}" if t and d else f"{md(d)}" if d else "")
    parts += list(sectors or [])
    text = "・".join(p for p in parts if p)
    return text or None


def yesterday_note(pack: dict[str, Any]) -> str:
    """The one line under 「昨日台股全貌」: what it is (data only; the writer never retells the previous session)."""
    prev = _d(next(iter((pack.get("dates") or {}).get("prev_session") or []), None))
    when = md_wd(prev) if prev else "前一個交易日"
    return f"{when}收盤後的類股與大方向，依官方資料整理；標「估算」的是 Forliosa 自己算的。"


def _ai_block(b: dict[str, Any]) -> bool:
    return b["type"] in ("text", "items") or (b["type"] == "chart" and bool(b.get("caption")))


def origin_label(origin: str, blocks: list[dict[str, Any]]) -> str:
    """The label beside a section's title. A section with the server's tables or charts says 「資料」 even when AI text
    sits under them (the page marks that text where it starts); only a section of AI text alone says 「AI 依資料與報導
    整理」. ``origin`` stays ``ai`` whenever there is AI text (corrections and the table versions go by it)."""
    if origin == "ai" and not any(b["type"] in ("table", "chart") for b in blocks):
        return ORIGIN_LABEL["ai"]
    return ORIGIN_LABEL["data"]


def _filings_table(pack: dict[str, Any]) -> dict[str, Any] | None:
    rows = [{"cells": {"time": {"text": f.get("time") or "—"},
                       "who": {"text": f"{f.get('name') or ''}（{str(f.get('symbol') or '').split('.')[0]}）"},
                       "title": {"text": f.get("title") or ""}},
             "href": f"/stock/{f['symbol']}" if f.get("symbol") else None}
            for f in pack.get("filings") or []]
    if not rows:
        return None
    return {"type": "table", "table": {
        "id": "T_filings", "title": "盤後重大訊息（市值前 100 名）", "rule": "市值前 100 名的公司，14:00 以後公告",
        "columns": [{"key": "time", "label": "時間", "align": "left", "num": True},
                    {"key": "who", "label": "公司", "align": "left", "num": False},
                    {"key": "title", "label": "主旨", "align": "left", "num": False}],
        "rows": rows, "fold_after": 8, "empty_text": None, "note": None,
        "source_labels": sorted({source_label(f["dataset"]) for f in pack.get("filings") or [] if f.get("dataset")})}}


def _blocks_for(kind: str, section: str, pack: dict[str, Any], blocks: dict[str, Any], output: dict[str, Any] | None,
                chart_of_day: dict[str, Any] | None) -> list[dict[str, Any]]:
    o = output or {}

    def paras(key: str) -> list[dict[str, Any]]:
        return [p for p in (_para_from(x) for x in o.get(key) or []) if p]

    def items(key: str) -> list[dict[str, Any]]:
        rows = []
        for it in o.get(key) or []:
            p = _para_from(it.get("para")) if isinstance(it, dict) else None
            if p is None:
                continue
            rows.append({"title": str(it.get("event") or ""),
                         "meta": _cal_meta(pack, str(it.get("time_ref") or ""), it.get("sectors") or []),
                         "paragraphs": [p]})
        return rows

    def stock_paras(key: str) -> list[dict[str, Any]]:
        rows = [p for p in (_para_from((it or {}).get("para")) for it in o.get(key) or []) if p]
        if rows and not any(str(r)[:1] in ("X", "W") for p in rows for s in p["sentences"] for r in s["refs"]):
            # no stock has a reason: said once for the section (owner 2026-11-17), not 「未找到報導」 in every item —
            # ``validate.tidy`` took those out of a checked output, but ``validate.drop`` may have taken out the last
            # reason after it: the same cut here (a sentence of its own, or the clause ending one)
            from forliosa.reports.validate import without_not_found

            rows = [{"sentences": without_not_found(p["sentences"])} for p in rows]
            rows.append(_para(_sent(STOCKS_NOT_FOUND, [])))
        return rows

    out: list[dict[str, Any] | None] = []
    if kind == "premarket":
        if section == "overnight":
            texts = paras("overnight")
            if output is not None and not pack.get("web") and not texts:
                out.append({"type": "note", "text": NO_WEB})
            out += [_text(texts), _chart(blocks, "G6")]
            if output is not None and not pack.get("web") and texts:
                out.append({"type": "note", "text": NO_WEB})
        elif section == "watch":
            out.append(_items(items("watch")))
        elif section == "yesterday":
            charts = [_chart(blocks, k) for k in YESTERDAY_CHARTS]
            if any(c and c["type"] == "chart" for c in charts):
                out.append({"type": "note", "text": yesterday_note(pack)})
                out += charts
        elif section == "chips":
            out += [_text(paras("evening_notes")), _chart(blocks, "G7"), _table(blocks, "T7"), _chart(blocks, "G16"),
                    _table(blocks, "T10_up"), _table(blocks, "T10_down")]
        elif section == "chart_of_day":
            out.append(chart_of_day)
    elif kind == "close":
        if section == "what_happened":
            out += [_text(paras("what_happened")), _chart(blocks, "G1")]
        elif section == "sectors":
            out += [_text(paras("sectors")), *(_chart(blocks, k) for k in CLOSE_SECTOR_CHARTS)]
        elif section == "stocks":
            out += [_text(stock_paras("stocks")), _chart(blocks, "G3"),
                    *(_table(blocks, t) for t in ("T2_top10", "T2_gainers", "T2_losers", "T2_value"))]
        elif section == "chips":
            out += [_text(paras("chips")), _table(blocks, "T7"), _table(blocks, "T8"), _table(blocks, "T8_buy"),
                    _table(blocks, "T8_sell"), _chart(blocks, "G16")]
        elif section == "tonight":
            out += [_filings_table(pack), _items(items("tonight"))]
        elif section == "chart_of_day":
            out.append(chart_of_day)
        elif section == "otc":
            out += [*(_table(blocks, t) for t in ("T5_top10", "T5_gainers", "T5_losers")), _chart(blocks, "G2_otc")]
    else:
        if section == "summary":
            out.append(_text([p for p in [_para_from(o.get("summary"))] if p]))
        elif section == "market_week":
            out += [_text(paras("market_week")), _chart(blocks, "G1")]
        elif section == "sectors_week":
            out += [_text(paras("sectors_week")), _chart(blocks, "G17"), _table(blocks, "T3"), _chart(blocks, "G2"),
                    _chart(blocks, "G8")]
        # the AI text first, then the charts and tables (as the close's sections): the reader meets what it says
        # before scrolling past 1,700–2,000px of tables
        elif section == "stocks_week":
            out += [_text(stock_paras("stocks_week")), _chart(blocks, "G3"),
                    *(_table(blocks, t) for t in ("T2_top10", "T2_gainers", "T2_losers", "T2_value"))]
        elif section == "chips_week":
            out += [_text(paras("chips_week")), _chart(blocks, "G7"), _table(blocks, "T9"), _chart(blocks, "G16"),
                    _table(blocks, "T10_up"), _table(blocks, "T10_down")]
        elif section == "global_week":
            out += [_text(paras("global_week")), _chart(blocks, "G6")]
        elif section == "last_week_review":
            rows = []
            for it in o.get("last_week_review") or []:
                p = _para_from((it or {}).get("para"))
                c = next((x for x in pack.get("calendar") or [] if x.get("id") == (it or {}).get("ref")), None)
                if p is None or c is None:
                    continue
                d = _d(c.get("date"))
                rows.append({"title": c.get("title") or "", "meta": md_wd(d) if d else None, "paragraphs": [p]})
            out.append(_items(rows))
        elif section == "themes":
            rows = []
            for it in o.get("themes") or []:
                ps = [p for p in (_para_from((it or {}).get(k)) for k in ("why", "events", "relation")) if p]
                if ps:
                    rows.append({"title": str(it.get("theme") or ""),
                                 "meta": "・".join(it.get("sectors") or []) or None, "paragraphs": ps})
            out.append(_items(rows))
        elif section == "risks":
            out.append(_text(paras("risks")))
        elif section == "chart_of_day":
            out.append(chart_of_day)
    return [b for b in out if b]


def chart_of_day_block(kind: str, output: dict[str, Any] | None, blocks: dict[str, Any],
                       extra_charts: dict[str, Any] | None = None) -> dict[str, Any] | None:
    ch = (output or {}).get("chart_of_day")
    if not isinstance(ch, dict) or ch.get("code") in (None, "none"):
        return None
    caption = _para_from(ch.get("caption"))
    if caption is None:
        return None
    code = str(ch.get("code"))
    key = CHART_KEYS[kind].get(code)
    chart = (extra_charts or {}).get(f"{code}:{ch.get('set')}") \
        or ((blocks.get("charts") or {}).get(key) if key else None)
    if not isinstance(chart, dict):
        return None
    return {"type": "chart", "chart": chart, "caption": caption, "chart_of_day": True}


# -- footnotes -----------------------------------------------------------------------------------------------------
def _footnote_for(pack: dict[str, Any], rid: str, idx: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    x = idx.get(rid)
    if x is None:
        return None
    kind = rid[0]
    if kind == "F":
        ds, d = str(x.get("dataset") or ""), _d(x.get("date"))
        lab = source_label(ds.split(":", 1)[0] if ds.startswith("rules:") else ds)
        # one footnote per source label and day (the rule-made datasets share 「Forliosa 規則計算」)
        return f"F:{lab}:{x.get('date')}", {"kind": "data", "label": f"{lab} {md(d)}" if d else lab, "outlet": None,
                                            "url": None, "date_label": md(d) if d else None}
    if kind == "X":
        pub = str(x.get("published_at") or "")
        d = _d(pub)
        when = None
        if d:
            when = md(d) if x.get("date_only") else f"{md(d)} {pub[11:16]}"
        # several facts from one article (or the same page as a shared-research source): one footnote
        return _page_key(x.get("url"), rid), {"kind": "web", "label": str(x.get("title") or ""),
                                              "outlet": x.get("outlet"), "url": x.get("url"), "date_label": when}
    if kind == "C":
        src = str(x.get("source") or "")
        if src.startswith("rules:"):
            lab = "Forliosa 依期交所規則排定" if src == "rules:settlement" else source_label("rules")
        elif src == "manual-calendar":
            lab = "Forliosa 自行整理的行事曆"
        else:
            lab = source_label(src)
        url = x.get("url") if src == "manual-calendar" else None
        return f"C:{src}:{url or ''}", {"kind": "calendar", "label": lab, "outlet": None, "url": url,
                                        "date_label": None}
    if kind == "N":
        d = _d(x.get("date"))
        lab = source_label(str(x.get("dataset") or ""))
        return f"N:{x.get('dataset')}:{x.get('date')}", {
            "kind": "filing", "label": f"{lab} {md(d)}" if d else lab, "outlet": None, "url": None,
            "date_label": md(d) if d else None}
    if kind == "W":
        s = next(iter(x.get("sources") or []), {}) or {}
        return _page_key(s.get("url"), rid), {"kind": "research", "label": str(s.get("title") or "共用研究的報導"),
                                              "outlet": s.get("outlet"), "url": s.get("url"), "date_label": None}
    return None


def _page_key(url: Any, rid: str) -> str:
    """The footnote key of a web page: its normalised address (https, no www., no tracking parameters, no fragment,
    no trailing slash), so the same article cited through several X (or an X and a W) is one footnote."""
    from forliosa.news.normalize import normalize_url

    u = str(url or "").strip()
    return f"U:{normalize_url(u)}" if u else f"{rid[0]}:{rid}"


def _all_sentences(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = [s for p in payload.get("highlights") or [] for s in p.get("sentences") or []]
    for sec in payload.get("sections") or []:
        if sec.get("dropped"):
            continue
        for b in sec.get("blocks") or []:
            if b["type"] == "text":
                out += [s for p in b["paragraphs"] for s in p["sentences"]]
            elif b["type"] == "items":
                out += [s for it in b["items"] for p in it["paragraphs"] for s in p["sentences"]]
            elif b["type"] == "chart" and b.get("caption"):
                out += list(b["caption"]["sentences"])
    return out


def refresh_ai_lines(payload: dict[str, Any]) -> None:
    """After a correction took AI text out: ``has_ai``, the two disclaimers and the model line follow what is left."""
    left = payload.get("title_origin") == "ai" or payload.get("highlights_origin") == "ai" or any(
        s.get("origin") == "ai" and not s.get("dropped") for s in payload.get("sections") or [])
    if left:
        return
    payload.update({"has_ai": False, "disclaimer_line": DISCLAIMER_DATA, "disclaimer_full": DISCLAIMER_FULL_DATA,
                    "model_line": None})


def number_footnotes(payload: dict[str, Any], pack: dict[str, Any]) -> None:
    idx: dict[str, dict[str, Any]] = {}
    for key in ("facts", "web", "calendar", "filings", "research"):
        for x in pack.get(key) or []:
            idx[x["id"]] = x
    notes: dict[str, dict[str, Any]] = {}
    for s in _all_sentences(payload):
        cites = []
        for r in s.get("refs") or []:
            got = _footnote_for(pack, r, idx)
            if got is None:
                continue
            k, fn = got
            if k not in notes:
                notes[k] = {"n": len(notes) + 1, **fn, "_x": r if r.startswith("X") else None}
            elif r.startswith("X") and notes[k]["_x"] is None:
                # a page first cited as shared research: the verified report's shape (its outlet, title and publish
                # time) from here on, under the same number — whichever sentence came first
                notes[k] = {"n": notes[k]["n"], **fn, "_x": r}
            cites.append(notes[k]["n"])
        s["cites"] = sorted(set(cites))
    payload["footnotes"] = [{k: v for k, v in n.items() if k != "_x"} for n in notes.values()]
    web = []
    by_x = {x["id"]: x for x in pack.get("web") or []}
    for n in notes.values():
        x = by_x.get(n.get("_x") or "")
        if x is not None:
            web.append({"n": n["n"], "outlet": x.get("outlet") or "", "title": x.get("title") or "",
                        "url": x.get("url") or "", "published_label": n.get("date_label") or ""})
    payload["sources"]["web"] = web


# -- the whole report ----------------------------------------------------------------------------------------------
def build(*, kind: str, report_id: str, edition_date: date, period: tuple[date, date],
          next_period: tuple[date, date] | None, version: int, edition: str, pack: dict[str, Any],
          blocks: dict[str, Any], output: dict[str, Any] | None, published_at: datetime,
          first_published_at: datetime | None, as_of: datetime, dropped: dict[str, list[str]] | None = None,
          title_origin: str | None = None, highlights_origin: str | None = None, mentions_anthropic: bool = False,
          corrections: list[dict[str, str]] | None = None, notes: list[str] | None = None,
          status_line: str | None = None, extra_charts: dict[str, Any] | None = None,
          dropped_output: dict[str, Any] | None = None) -> dict[str, Any]:
    """The admin form of one version. ``output``: the checked writer JSON (sections already dropped are empty);
    ``dropped_output``: the draft's text of those sections, kept for the admin view; ``None`` output = the data
    edition."""
    dropped = dropped or {}
    has_ai_text = output is not None
    title = str(output.get("title") or "") if output and title_origin == "ai" else data_title(kind, pack)
    if output is not None and highlights_origin == "ai":
        highlights = [p for p in (_para_from(x) for x in output.get("highlights") or []) if p]
    else:
        highlights = data_highlights(kind, pack)
    cod = chart_of_day_block(kind, output, blocks, extra_charts)
    sections = []
    for key, stitle, out_key, collapsed in SECTIONS[kind]:
        if out_key and out_key in dropped:
            # the admin view keeps the dropped text (and the server's charts and tables, which members still see)
            blocks_ = _blocks_for(kind, key, pack, blocks, dropped_output or {}, None)
            sections.append({"key": key, "title": section_title(kind, key, stitle, pack), "origin": "ai",
                             "origin_label": origin_label("ai", blocks_),
                             "collapsed_mobile": collapsed, "blocks": blocks_,
                             "dropped": {"reasons": list(dropped[out_key])}})
            continue
        bl = _blocks_for(kind, key, pack, blocks, output, cod)
        if not bl:
            continue
        origin = "ai" if any(_ai_block(b) for b in bl) else "data"
        sections.append({"key": key, "title": section_title(kind, key, stitle, pack), "origin": origin,
                         "origin_label": origin_label(origin, bl), "collapsed_mobile": collapsed, "blocks": bl})
    ai_text_left = has_ai_text and (title_origin == "ai" or highlights_origin == "ai" or any(
        s["origin"] == "ai" and not s.get("dropped") for s in sections))
    cal = copy.deepcopy(blocks.get("calendar")) if blocks.get("calendar") else None
    manual = any(c.get("source") == "manual-calendar" for c in pack.get("calendar") or []) or any(
        f.get("dataset") == "manual-calendar" for f in pack.get("facts") or [])
    payload: dict[str, Any] = {
        "id": report_id, "kind": kind, "kind_label": KIND_LABELS[kind], "edition_date": edition_date.isoformat(),
        "edition_label": edition_label(kind, edition_date, period),
        "period": {"start": period[0].isoformat(), "end": period[1].isoformat()},
        "next_period": {"start": next_period[0].isoformat(), "end": next_period[1].isoformat()} if next_period
        else None,
        "version": version, "edition": edition, "has_ai": bool(ai_text_left),
        "published_at": iso_taipei(published_at),
        "first_published_at": iso_taipei(first_published_at or published_at),
        "as_of": iso_taipei(as_of), "as_of_label": as_of_label(as_of),
        "disclaimer_line": DISCLAIMER_AI if ai_text_left else DISCLAIMER_DATA,
        "title": title, "title_origin": "ai" if title_origin == "ai" and output else "rules",
        "highlights": highlights, "highlights_origin": "ai" if highlights_origin == "ai" and output else "rules",
        "numbers": copy.deepcopy(blocks.get("numbers") or []), "sections": sections, "calendar": cal,
        "footnotes": [],
        "sources": {"data": list(blocks.get("source_labels") or []), "web": [],
                    "disagreements": [{"text": d["text"]} for d in pack.get("disagreements") or []],
                    "manual": [MANUAL_SOURCES] if manual else []},
        "disclaimer_full": DISCLAIMER_FULL if ai_text_left else DISCLAIMER_FULL_DATA,
        "model_line": (MODEL_LINE + (MODEL_LINE_MENTION if mentions_anthropic else "")) if ai_text_left else None,
        "corrections": list(corrections or []),
        "notes": [NOTE_TEXT.get(n, n) for n in (notes if notes is not None else pack.get("notes") or [])
                  if n in NOTE_TEXT],
        "status_line": status_line, "is_demo": False,
    }
    number_footnotes(payload, pack)
    return payload


def retable(payload: dict[str, Any], kind: str, pack: dict[str, Any], blocks: dict[str, Any], *, version: int,
            published_at: datetime, as_of: datetime, edition: str = "tables") -> dict[str, Any]:
    """A later version of an AI edition with the server's blocks rebuilt from a newer pack (23:45, 06:40): the AI
    text, its footnotes and its sources stay exactly as they were; charts, tables, the number strip, the calendar, the
    data source labels and the notes are replaced, and sections that only now have data (上櫃, the evening tables)
    are added."""
    out = copy.deepcopy(payload)
    fresh = build(kind=kind, report_id=payload["id"], edition_date=date.fromisoformat(payload["edition_date"]),
                  period=(date.fromisoformat(payload["period"]["start"]), date.fromisoformat(payload["period"]["end"])),
                  next_period=None, version=version, edition=edition, pack=pack, blocks=blocks, output=None,
                  published_at=published_at, first_published_at=None, as_of=as_of)
    fresh_by_key = {s["key"]: s for s in fresh["sections"] if not s.get("dropped")}
    sections = []
    seen = set()
    for sec in out["sections"]:
        if sec.get("dropped"):
            sections.append(sec)
            continue
        new = fresh_by_key.get(sec["key"])
        seen.add(sec["key"])
        if sec["origin"] == "data":
            if new is not None:
                sections.append(new)
            continue
        ai_blocks = [b for b in sec["blocks"] if b["type"] in ("text", "items")
                     or (b["type"] == "chart" and b.get("chart_of_day"))]
        data_blocks = [b for b in (new or {}).get("blocks") or [] if b["type"] in ("chart", "table", "note")
                       and not b.get("chart_of_day")]
        # keep the order of the original: data blocks where the old data blocks stood
        merged, used = [], False
        for b in sec["blocks"]:
            if b in ai_blocks:
                merged.append(b)
            elif not used:
                merged += data_blocks
                used = True
        if not used:
            merged += data_blocks
        sections.append({**sec, "blocks": merged, "origin_label": origin_label(sec["origin"], merged)})
    order = [k for k, *_ in SECTIONS[kind]]
    for key, new in fresh_by_key.items():
        if key not in seen:
            sections.append(new)
    sections.sort(key=lambda s: order.index(s["key"]) if s["key"] in order else 99)
    out["sections"] = sections
    out["numbers"] = fresh["numbers"]
    out["calendar"] = fresh["calendar"]
    out["sources"]["data"] = list(dict.fromkeys([*out["sources"]["data"], *fresh["sources"]["data"]]))
    out["notes"] = fresh["notes"]
    out["version"], out["edition"] = version, edition
    out["published_at"], out["as_of"], out["as_of_label"] = iso_taipei(published_at), iso_taipei(as_of), \
        as_of_label(as_of)
    out["status_line"] = None
    return out


def public(payload: dict[str, Any]) -> dict[str, Any]:
    """What a member reads: no refs, no dropped section."""
    out = copy.deepcopy(payload)
    for k in ("validation", "writer", "variant"):
        out.pop(k, None)

    def clean(p: dict[str, Any]) -> None:
        for s in p.get("sentences") or []:
            s.pop("refs", None)

    for p in out.get("highlights") or []:
        clean(p)
    sections = []
    for sec in out.get("sections") or []:
        if sec.get("dropped"):  # members see the server's blocks of a dropped section, never its text
            kept = [b for b in sec.get("blocks") or [] if _data_block(b)]
            if not kept:
                continue
            sec = {**{k: v for k, v in sec.items() if k != "dropped"}, "blocks": kept, "origin": "data",
                   "origin_label": ORIGIN_LABEL["data"]}
        sections.append(sec)
    out["sections"] = sections
    for sec in out["sections"]:
        for b in sec.get("blocks") or []:
            if b["type"] == "text":
                for p in b["paragraphs"]:
                    clean(p)
            elif b["type"] == "items":
                for it in b["items"]:
                    for p in it["paragraphs"]:
                        clean(p)
            elif b["type"] == "chart" and b.get("caption"):
                clean(b["caption"])
    return out


def _data_block(b: dict[str, Any]) -> bool:
    return b["type"] in ("table", "note") or (b["type"] == "chart" and not b.get("caption"))


def has_id_strings(payload: dict[str, Any]) -> bool:
    import json

    return bool(ID_PATTERN.search(json.dumps(public(payload), ensure_ascii=False)))
