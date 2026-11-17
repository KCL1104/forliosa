"""Writer outputs and gathering replies that pass every check against the conftest market (made-up numbers): the
tests change one thing at a time to see one check fail."""

from __future__ import annotations

import copy
import json
from typing import Any

from tests.ai.fake_anthropic import search_citation, server_tool_use, text, web_search_result


def fid(pack: dict[str, Any], metric: str, subject: str | None = None, group: str | None = None) -> str:
    return next(f["id"] for f in pack["facts"] if f["metric"] == metric and (subject is None or f["subject"] == subject)
                and (group is None or f["group"] == group))


def cid(pack: dict[str, Any], title_part: str) -> str:
    return next(c["id"] for c in pack["calendar"] if title_part in c["title"])


def s(t: str, *refs: str) -> dict[str, Any]:
    return {"text": t, "refs": list(refs)}


def p(*sents: dict[str, Any]) -> dict[str, Any]:
    return {"sentences": list(sents)}


NO_CHART = {"code": "none", "period": "none", "set": "none", "caption": {"sentences": []}}

INST_X = {"id": "X001", "topic": "TWSE_INST", "key": "TWSE_INST.foreign", "subject": "外資",
          "claim": "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", "outlet": "中央社", "title": "外資賣超千億",
          "url": "https://www.cna.com.tw/news/afe/202611160123.aspx", "published_at": "2026-11-16T15:32:00+08:00",
          "date_only": False, "numbers": ["1234.5"], "us_session": None,
          "quote": "外資 11/16 賣超 1,234.5 億元，投信賣超 179.63 億元"}
TRUST_X = {**INST_X, "id": "X002", "key": "TWSE_INST.trust", "subject": "投信",
           "claim": "〔中央社〕報導，投信賣超 179.63 億元。",
           "numbers": ["179.63"]}


def with_web(pack: dict[str, Any], *facts: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(pack)
    out["web"] = [copy.deepcopy(f) for f in facts] or [copy.deepcopy(INST_X), copy.deepcopy(TRUST_X)]
    return out


def close_output(pk: dict[str, Any]) -> dict[str, Any]:
    f = lambda m, sub=None: fid(pk, m, sub, None if m.startswith("sector_conc") else "today")  # noqa: E731
    return {
        "title": "加權指數跌 6.03%，收 41,040.08 點",
        "highlights": [
            p(s("加權指數收 41,040.08 點，跌 2,635.04 點（▼6.03%）。", f("index_close"), f("index_change"),
                f("index_pct"))),
            p(s("上市普通股上漲 6 家、下跌 6 家。", f("adv_up"), f("adv_down"))),
            p(s("台積電（2330）點數貢獻約 −1,616 點（估算）。", f("stock_contrib", "台積電"))),
        ],
        "what_happened": [
            p(s("加權指數收 41,040.08 點。", f("index_close"))),
            p(s("櫃買指數收 319.12 點，跌 6.80%。", f("otc_close"), f("otc_pct"))),
        ],
        "sectors": [p(s("半導體類指數跌 4.50%，主要由台積電構成，約 94%。", f("sector_pct", "半導體"),
                        fid(pk, "sector_concentration", "半導體")))],
        "stocks": [{"symbol": "2330.TW", "para": p(s("台積電（2330）收 1,430.00 元，跌 4.67%。",
                                                     f("stock_close", "台積電"),
                                                     f("stock_pct", "台積電")),
                                                   s("未找到報導。", f("stock_pct", "台積電")))}],
        "chips": [p(s("〔中央社〕報導，外資賣超 1,234.5 億元。", "X001"))],
        "tonight": [{"event": "鴻海法說會", "time_ref": cid(pk, "鴻海"), "sectors": ["其他電子"],
                     "para": p(s("已排定：鴻海（2317）11/17（二）法說會。", cid(pk, "鴻海")))}],
        "chart_of_day": {"code": "G4", "period": "day", "set": "none",
                         "caption": p(s("上市普通股上漲 6 家、下跌 6 家。", f("adv_up"), f("adv_down")))},
    }


def premarket_output(pk: dict[str, Any]) -> dict[str, Any]:
    us = lambda sub: fid(pk, "us_pct", sub, "overnight")  # noqa: E731
    return {
        "title": "SMH 美股 11/16 跌 2.58%，台積電 ADR 跌 1.00%",
        "highlights": [
            p(s("SMH 美股 11/16 跌 2.58%。", us("SMH"))),
            p(s("已排定：鴻海（2317）11/17（二）法說會。", cid(pk, "鴻海"))),
            p(s("外資台指期淨空 96,787 口。", fid(pk, "futures_oi_net"))),
        ],
        "overnight": [
            p(s("SPY 美股 11/16 漲 0.50%。", us("SPY"))),
            p(s("台積電 ADR 美股 11/16 跌 1.00%。", us("台積電 ADR"))),
            p(s("ONEQ 美股 11/16 漲 1.12%。", us("ONEQ"))),
        ],
        "evening_notes": [p(s("櫃買指數 11/16 收 319.12 點。", fid(pk, "otc_close", group="evening")))],
        "watch": [
            {"event": "鴻海法說會", "time_ref": cid(pk, "鴻海"), "sectors": ["其他電子"],
             "para": p(s("已排定：鴻海（2317）11/17（二）法說會。", cid(pk, "鴻海")))},
            {"event": "富邦金除息", "time_ref": cid(pk, "富邦金"), "sectors": ["金融保險"],
             "para": p(s("已排定：富邦金（2881）11/17（二）除息。", cid(pk, "富邦金")))},
        ],
        "chart_of_day": dict(NO_CHART),
    }


# -- the gathering's replies -------------------------------------------------------------------------------------
def gather_reply(key: str, claim: str, url: str, title: str, cited: str, page_age: str = "2026-11-16T15:32:00+08:00",
                 tool_id: str = "srv1") -> list[dict[str, Any]]:
    """One search and one cited fact (blocks for ``FakeAnthropic.reply``)."""
    return [server_tool_use(tool_id, "web_search", {"query": "q"}),
            web_search_result(tool_id, [{"url": url, "title": title, "page_age": page_age}]),
            text(f"[{key}] "), text(claim, [search_citation(url, title, cited)]), text("\n\n")]


def json_text(obj: Any) -> dict[str, Any]:
    return text(json.dumps(obj, ensure_ascii=False))
