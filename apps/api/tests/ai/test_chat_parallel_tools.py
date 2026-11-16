"""2026-11-16: the read-only client tools of one round run side by side, each on a session of its own; the tools that
write or add to the turn (``draft_transaction``, ``draw_chart``) run after them on the turn's session; every result
goes back in the model's order in one user message, and what the results add to the turn is merged in that order."""

from __future__ import annotations

import json
import logging
import threading
import time

from forliosa.ai import chat as chat_mod
from forliosa.ai.chat import ChatTurn
from forliosa.ai.tools import ToolOutcome
from forliosa.ai.tools import execute as real_execute
from tests.ai.conftest import buy, chat, make_account
from tests.ai.fake_anthropic import text, tool_use


def tool_events(events) -> list[tuple[str, str]]:
    return [(d["id"], d["status"]) for n, d in events if n == "tool"]


def results_of(fake, request: int = 1) -> list[dict]:
    return fake.requests[request]["body"]["messages"][-1]["content"]


def on_worker() -> bool:
    return threading.current_thread().name.startswith("ai-tool")


def test_read_only_tools_of_a_round_run_side_by_side(client, pool, fake, monkeypatch, caplog):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    both_running = threading.Barrier(2, timeout=5)  # passes only when the two tools run at the same time
    seen: dict[str, tuple[bool, object]] = {}

    def spy(ctx, name, args):
        both_running.wait()
        seen[name] = (on_worker(), ctx.db)
        return real_execute(ctx, name, args)

    monkeypatch.setattr(chat_mod, "execute", spy)
    fake.reply(tool_use("toolu_a", "get_holdings", {}), tool_use("toolu_b", "get_portfolio_summary", {}),
               stop_reason="tool_use")
    fake.reply(text("你持有台積電 1 張。"))
    with caplog.at_level(logging.INFO, logger="forliosa.ai.chat"):
        _, events = chat(client, "我的持股？")
    assert tool_events(events) == [("toolu_a", "running"), ("toolu_b", "running"), ("toolu_a", "done"),
                                   ("toolu_b", "done")]
    # each on a worker thread with a session of its own (which sees the ledger)
    assert seen["get_holdings"][0] and seen["get_portfolio_summary"][0]
    assert seen["get_holdings"][1] is not seen["get_portfolio_summary"][1]
    results = results_of(fake)
    assert [r["tool_use_id"] for r in results] == ["toolu_a", "toolu_b"] and not any("is_error" in r for r in results)
    assert [h["symbol"] for h in json.loads(results[0]["content"])["holdings"]] == ["2330.TW"]
    line = next(r.getMessage() for r in caplog.records if "timings" in r.getMessage())
    assert "parallel [get_holdings " in line and ", get_portfolio_summary " in line


def test_drafts_run_after_the_read_only_tools_on_the_turns_session(client, pool, fake, monkeypatch):
    make_account(client)
    order: list[tuple[str, bool]] = []

    def spy(ctx, name, args):
        if name == "get_stock_overview":
            time.sleep(0.2)
        out = real_execute(ctx, name, args)
        order.append((name, on_worker()))
        return out

    monkeypatch.setattr(chat_mod, "execute", spy)
    fake.reply(tool_use("toolu_d", "draft_transaction", {"type": "buy", "symbol": "0050", "quantity": 2000,
                                                         "price": 52.4}),
               tool_use("toolu_o", "get_stock_overview", {"symbol": "2330"}),
               tool_use("toolu_h", "get_holdings", {}), stop_reason="tool_use")
    fake.reply(text("草稿已準備好。"))
    _, events = chat(client, "買 0050 2 張 52.4，順便看台積電")
    assert sorted(order[:2]) == [("get_holdings", True), ("get_stock_overview", True)]
    assert order[2] == ("draft_transaction", False)  # after both, on the turn's own thread and session
    assert tool_events(events) == [("toolu_o", "running"), ("toolu_h", "running"), ("toolu_o", "done"),
                                   ("toolu_h", "done"), ("toolu_d", "running"), ("toolu_d", "done")]
    assert [n for n, _ in events].count("draft") == 1
    results = results_of(fake)
    assert [r["tool_use_id"] for r in results] == ["toolu_d", "toolu_o", "toolu_h"]  # the model's order
    assert not any(r.get("is_error") for r in results)


def test_a_failing_tool_is_still_an_is_error_result(client, pool, fake):
    fake.reply(tool_use("toolu_e", "get_stock_overview", {"symbol": "不存在的公司XYZ"}),
               tool_use("toolu_h", "get_holdings", {}), stop_reason="tool_use")
    fake.reply(text("查不到這家公司。"))
    _, events = chat(client, "XYZ 股價？")
    assert ("toolu_e", "error") in tool_events(events) and ("toolu_h", "done") in tool_events(events)
    first, second = results_of(fake)
    assert first["is_error"] is True and "找不到商品" in first["content"]
    assert "is_error" not in second


def test_results_merge_in_the_models_order_not_by_who_finished_first(client, pool, fake, monkeypatch):
    url = "https://news.example.com/a"

    def news(outlet: str) -> ToolOutcome:
        return ToolOutcome([{"type": "search_result", "source": url, "title": "標題", "citations": {"enabled": True},
                             "content": [{"type": "text", "text": "內容"}]}], outlets={url: outlet})

    def spy(ctx, name, args):
        if name == "get_news":
            time.sleep(0.3)  # the first tool finishes last
            return news("先呼叫的")
        return news("後呼叫的")

    monkeypatch.setattr(chat_mod, "execute", spy)
    fake.reply(tool_use("toolu_1", "get_news", {"symbol": "2330"}), tool_use("toolu_2", "get_events",
                                                                            {"symbol": "2330", "mine_only": False}),
               stop_reason="tool_use")
    fake.reply(text("有一則新聞。", [{"type": "search_result_location", "source": url, "title": "標題",
                                    "cited_text": "內容", "search_result_index": 0, "start_block_index": 0,
                                    "end_block_index": 0}]))
    _, events = chat(client, "台積電有什麼新聞？")
    assert tool_events(events)[2:] == [("toolu_1", "done"), ("toolu_2", "done")]
    cite = next(d for n, d in events if n == "citation")
    assert cite["outlet"] == "後呼叫的"  # the later call in the model's order wins, whichever finished first
    assert [r["tool_use_id"] for r in results_of(fake)] == ["toolu_1", "toolu_2"]


def test_one_read_only_tool_runs_in_turn_and_a_missing_session_falls_back(client, pool, fake, monkeypatch, caplog):
    where: list[bool] = []

    def spy(ctx, name, args):
        where.append(on_worker())
        return real_execute(ctx, name, args)

    monkeypatch.setattr(chat_mod, "execute", spy)
    fake.reply(tool_use("toolu_h", "get_holdings", {}), stop_reason="tool_use").reply(text("沒有持股。"))
    chat(client, "我的持股？")
    assert where == [False]  # a single tool needs no worker

    def no_session():
        raise RuntimeError("no connection")

    monkeypatch.setattr(ChatTurn, "_tool_sessions", lambda self: no_session)
    where.clear()
    fake.reply(tool_use("toolu_a", "get_holdings", {}), tool_use("toolu_b", "get_portfolio_summary", {}),
               stop_reason="tool_use").reply(text("沒有持股。"))
    with caplog.at_level(logging.WARNING, logger="forliosa.ai.chat"):
        _, events = chat(client, "我的持股？")
    assert where == [False, False]  # each ran here instead
    assert tool_events(events)[2:] == [("toolu_a", "done"), ("toolu_b", "done")]
    assert [r["tool_use_id"] for r in results_of(fake, 3)] == ["toolu_a", "toolu_b"]
    assert sum("could not run on its own session" in r.getMessage() for r in caplog.records) == 2
