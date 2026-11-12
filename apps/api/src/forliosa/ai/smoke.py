"""Live smoke test against the real Claude API: ``uv run python -m forliosa.ai.smoke``.

1. A chat turn with tool use on the seeded demo user (``demo@forliosa.local``; seeded if missing).
2. A question about 台積電 today that needs web search (citations printed).

Prints the streamed answer, tool steps, citations, grounding flags, token usage and the estimated cost of each
turn, then the state of every key slot. Needs a key (``CLAUDE_API_KEY_<n>`` / ``ANTHROPIC_API_KEY``, or
``AI_DEV_DUMMY_KEY=1`` behind a key-injecting proxy). Exit code 2 when no key is configured, 1 when a turn
failed. Never prints keys (only slot numbers).
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from forliosa.ai.chat import ChatTurn
from forliosa.ai.keypool import build_pool, discover_keys
from forliosa.ai.pricing import CallUsage, estimate_cost
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.marketdata.service import get_market_data
from forliosa.models import User

QUESTIONS = [
    ("我目前有哪些持股？今天哪一檔漲跌最多？", "/", None),
    ("台積電今天有什麼新聞？股價為什麼這樣動？", "/stock/2330.TW", "2330.TW"),
]


def _demo_user(db) -> User:
    from forliosa.seed import DEMO_EMAIL, run_migrations, seed

    run_migrations()
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        print("建立示範使用者與交易紀錄…")
        seed(db, get_market_data())
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    assert user is not None
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forliosa AI live smoke test (real API, small cost)")
    parser.add_argument("--only", type=int, choices=[1, 2], help="run only question 1 or 2")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    keys = discover_keys()
    if not keys and not settings.ai_dev_dummy_key:
        print("沒有 API 金鑰：請設定 CLAUDE_API_KEY_1（或 ANTHROPIC_API_KEY），或在會注入金鑰的 proxy 後面設 "
              "AI_DEV_DUMMY_KEY=1。smoke test 沒有執行。")
        return 2
    pool = build_pool()
    slot_names = ", ".join(f"#{s.index}" for s in pool.slots)
    print(f"金鑰槽：{slot_names}；模型：{settings.ai_model_chat or settings.ai_model}")
    failed = False
    grand = CallUsage()
    grand_cost = 0.0
    with session_factory()() as db:
        user = _demo_user(db)
        md = get_market_data()
        for n, (question, route, symbol) in enumerate(QUESTIONS, start=1):
            if args.only and args.only != n:
                continue
            print(f"\n=== {n}. {question}（頁面 {route}）")
            turn = ChatTurn(db, user, md, pool, settings)
            model = settings.ai_model
            for name, data in turn.run(thread_id=None, message=question, route=route, symbol=symbol,
                                       privacy=False):
                if name == "text":
                    print(data["delta"], end="", flush=True)
                elif name == "tool":
                    print(f"\n  [{data['status']}] {data['label']}", flush=True)
                elif name == "citation":
                    print(f"\n  ↳ 來源：{data['title']} {data['url']}", flush=True)
                elif name == "draft":
                    print(f"\n  ✎ 草稿 {data['id']}", flush=True)
                elif name == "grounding":
                    for item in data["items"]:
                        print(f"\n  ⚠ 無來源：{item['text']}", flush=True)
                elif name == "error":
                    failed = failed or data["code"] not in ("truncated",)
                    print(f"\n  ✗ {data['code']}：{data['message']}", flush=True)
                elif name == "done":
                    model = data["model"]
                    u = CallUsage(**data["usage"])
                    grand.add(u)
                    cost = float(estimate_cost(model, u))
                    grand_cost += cost
                    print(f"\n--- 用量：輸入 {u.input_tokens}、快取寫入 {u.cache_creation_input_tokens}、快取讀取 "
                          f"{u.cache_read_input_tokens}、輸出 {u.output_tokens}、搜尋 {u.web_search_requests} 次、"
                          f"擷取 {u.web_fetch_requests} 次；估計 US${cost:.5f}（{model}，stop={data['stop_reason']}）")
    print(f"\n合計：輸入 {grand.input_tokens}、快取寫入 {grand.cache_creation_input_tokens}、快取讀取 "
          f"{grand.cache_read_input_tokens}、輸出 {grand.output_tokens}、搜尋 {grand.web_search_requests} 次；"
          f"估計 US${grand_cost:.5f}")
    with session_factory()() as db:
        from forliosa.ai import store
        from forliosa.ai.tools import excluded_tools

        costs, calls = store.slot_month_usage(db)
        for row in pool.status(costs, calls, store.slot_thread_counts(db)):
            if row["configured"]:
                print(f"金鑰槽 #{row['slot']}：{row['state']}、本月 US${row['month_cost_usd']:.4f}"
                      f"（{row['month_calls']} 次）、workspace {row['workspace_id'] or '?'}、"
                      f"headroom {row['headroom']}")
        for tool in excluded_tools():
            print(f"停用的伺服器工具：{tool['type']}（{tool['reason']}）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
