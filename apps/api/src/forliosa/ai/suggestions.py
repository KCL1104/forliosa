"""Questions and actions that appear next to the AI input, chosen by rules from the user's own data (no model
call). Same kinds and wording as the frontend's offline rules (``apps/web/src/ai/suggestions.ts``); the UI shows
them without any "suggested for this page" label (PRODUCT.md)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai.prompts import route_kind
from forliosa.marketdata.service import MarketData
from forliosa.models import AiDraft, User, WatchlistItem
from forliosa.timeutil import today_taipei

log = logging.getLogger(__name__)

MAX_QUESTIONS = 3
DIVIDEND_WINDOW_DAYS = 31
CONCENTRATION = {"single": 0.15, "top3": 0.45, "industry": 0.4}


def _q(kind: str, text: str, a: str, b: str, symbol: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind, "text": text, "lines": [a, b]}
    if symbol:
        out["symbol"] = symbol
    return out


def _days(today: date, d: Any) -> int | None:
    if d is None:
        return None
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return (d - today).days


def _pending_drafts(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(AiDraft).where(AiDraft.user_id == user.id,
                                                                     AiDraft.status == "pending")) or 0


def ledger_questions(holdings: list[dict], summary: dict | None, today: date) -> list[dict[str, Any]]:
    if not holdings:
        return [_q("onboard", "怎麼用一句話記帳？", "怎麼用", "一句話記帳？")]
    out = []
    if any((h.get("day_change") or 0) < 0 for h in holdings):
        out.append(_q("drag", "今天誰拖累了我的報酬？", "今天", "誰拖累了我？"))
    elif any((h.get("day_change") or 0) > 0 for h in holdings):
        out.append(_q("lift", "今天誰幫我賺最多？", "今天", "誰幫我賺最多？"))
    soon = [d for d in (summary or {}).get("upcoming_dividends", [])
            if (n := _days(today, d.get("ex_dividend_date"))) is not None and 0 <= n <= DIVIDEND_WINDOW_DAYS]
    if soon:
        out.append(_q("dividends_next", "下個月我能領多少股利？", "下個月", "能領多少股利？"))
    weights = sorted((h.get("weight") or 0 for h in holdings), reverse=True)
    industries = [i for i in ((summary or {}).get("allocation") or {}).get("by_industry", []) if i.get("key") != "ETF"]
    top_industry = max((i.get("weight") or 0 for i in industries), default=0)
    if (weights and weights[0] >= CONCENTRATION["single"]) or sum(weights[:3]) >= CONCENTRATION["top3"] \
            or top_industry >= CONCENTRATION["industry"]:
        out.append(_q("concentration", "我的持股會不會太集中？", "我的持股", "會不會太集中？"))
    return out[:MAX_QUESTIONS]


def stock_questions(info: Any, quote: Any, overview: dict | None, position: dict | None, why: dict | None,
                    today: date) -> list[dict[str, Any]]:
    sym = info.symbol
    out = []
    if why and why.get("show"):
        pct = getattr(quote, "change", None)
        word = "跌" if pct is not None and pct < 0 else "漲"
        out.append(_q("why_move", f"{info.name}今天為什麼{word}？", "今天", f"為什麼{word}？", sym))
    ov = overview or {}
    if position:
        nxt = position.get("upcoming_dividend")
        n = _days(today, nxt.get("ex_dividend_date")) if nxt else None
        if n is not None and 0 <= n <= DIVIDEND_WINDOW_DAYS:
            out.append(_q("next_dividend", "這次除息我可以領多少？", "這次除息", "我可以領多少？", sym))
        if info.type == "stock" and (ov.get("eps_ttm") or 0) > 0:
            out.append(_q("cost_on_river", "我的成本在河流圖哪裡？", "我的成本", "在河流圖哪裡？", sym))
        if info.market != "US":
            out.append(_q("add_one_lot", "加碼 1 張，均價會變多少？", "加碼 1 張", "均價會變多少？", sym))
    else:
        if info.type == "stock" and ov.get("pe") is not None:
            out.append(_q("is_expensive", "現在的本益比算貴嗎？", "現在的本益比", "算貴嗎？", sym))
        if (ov.get("last_cash_dividend") or 0) > 0:
            out.append(_q("if_hold_dividend", "持有 1 張一年能領多少股利？", "持有 1 張", "一年能領多少？", sym))
    return out[:MAX_QUESTIONS]


def suggestions(db: Session, user: User, md: MarketData, route: str | None, symbol: str | None) -> dict[str, Any]:
    from forliosa.services import portfolio as psvc
    from forliosa.services import stock as ssvc

    kind = route_kind(route)
    if kind == "stock" and not symbol and route:
        symbol = route.rstrip("/").rsplit("/", 1)[-1] or None
    today = today_taipei()
    questions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    pending = _pending_drafts(db, user)
    resolved: str | None = None

    if kind == "stock" and symbol and (info := md.instrument(symbol)) is not None:
        resolved = info.symbol
        quote = md.quote(info.symbol)
        overview = position = why = None
        try:
            overview = ssvc.overview(db, md, info.symbol)
            position = ssvc.position(db, md, user, info.symbol)
            why = ssvc.why(db, md, info.symbol)
        except Exception:  # degrade to fewer questions rather than failing the panel
            log.exception("suggestions: stock data for %s failed", info.symbol)
        questions = stock_questions(info, quote, overview, position, why, today)
        actions.append({"kind": "draft_transaction", "label": f"記一筆 {info.name}", "prompt": f"買 {info.code} "})
        if position:
            actions.append({"kind": "draft_transaction", "label": f"賣出 {info.name}", "prompt": f"賣 {info.code} "})
        watched = db.scalar(select(WatchlistItem.id).where(WatchlistItem.user_id == user.id,
                                                          WatchlistItem.symbol == info.symbol))
        if watched is None and not position:
            actions.append({"kind": "watchlist_add", "label": "加入自選", "symbol": info.symbol})
    elif kind == "ledger" or kind == "other":
        holdings: list[dict] = []
        summary: dict | None = None
        try:
            state = psvc.compute_state(db, user, md)
            holdings = psvc.holdings(state)
            summary = psvc.summary(state, md)
        except Exception:
            log.exception("suggestions: portfolio data failed")
        questions = ledger_questions(holdings, summary, today)
        actions.append({"kind": "draft_transaction", "label": "記一筆交易", "prompt": "買 "})
    elif kind == "groups":
        questions = [_q("group_share", "群組會分享我的哪些資料？", "群組會分享", "我的哪些資料？")]
    if pending:
        actions.append({"kind": "review_drafts", "label": f"確認 {pending} 筆草稿", "count": pending})
    return {"route": kind, "symbol": resolved, "questions": questions, "actions": actions}
