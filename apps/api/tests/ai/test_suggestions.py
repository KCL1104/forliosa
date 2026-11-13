"""GET /ai/suggestions (rules only) and GET /ai/usage."""

from __future__ import annotations

from tests.ai.conftest import API, buy, make_account


def test_empty_ledger_onboards(client):
    s = client.get(f"{API}/ai/suggestions?route=/").json()
    assert s["route"] == "ledger"
    assert [q["kind"] for q in s["questions"]] == ["onboard"]
    assert s["actions"][0] == {"kind": "draft_transaction", "label": "記一筆交易", "prompt": "買 ", "symbol": None,
                               "count": None}


def test_ledger_questions_from_holdings(client):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    s = client.get(f"{API}/ai/suggestions?route=/").json()
    kinds = [q["kind"] for q in s["questions"]]
    assert 1 <= len(kinds) <= 3 and "concentration" in kinds  # one stock = 100 % weight
    for q in s["questions"]:
        assert len(q["lines"]) == 2 and q["text"]
        assert "建議" not in q["text"] and "本頁" not in q["text"]  # no meta labels


def test_stock_page(client):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    s = client.get(f"{API}/ai/suggestions", params={"route": "/stock/2330.TW", "symbol": "2330"}).json()
    assert s["route"] == "stock" and s["symbol"] == "2330.TW"
    assert len(s["questions"]) <= 3 and all(q["symbol"] == "2330.TW" for q in s["questions"])
    labels = [a["label"] for a in s["actions"]]
    assert labels[:2] == ["記一筆 台積電", "賣出 台積電"]
    # not held and not watched: offers the watchlist
    s2 = client.get(f"{API}/ai/suggestions", params={"route": "/stock/0050.TW"}).json()
    assert s2["symbol"] == "0050.TW" and any(a["kind"] == "watchlist_add" for a in s2["actions"])


def test_listed_stocks_ask_about_foreign_investors(client):
    """Listed stocks show no per-stock 三大法人／外資持股: the question is answered from web news by the model."""
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    for symbol in ("2330.TW", "2317.TW"):  # held and not held
        s = client.get(f"{API}/ai/suggestions", params={"route": f"/stock/{symbol}"}).json()
        flow = [q for q in s["questions"] if q["kind"] == "foreign_flow"]
        assert flow == [{"kind": "foreign_flow", "text": "最近外資對這檔的動向？",
                         "lines": ["最近外資", "對這檔的動向？"], "symbol": symbol}], s["questions"]
    # not for TPEx stocks (their flows are on the page), ETFs or US stocks
    for symbol in ("6488.TWO", "0050.TW", "AAPL"):
        s = client.get(f"{API}/ai/suggestions", params={"route": f"/stock/{symbol}"}).json()
        assert all(q["kind"] != "foreign_flow" for q in s["questions"]), symbol


def test_groups_and_unknown_routes(client):
    assert [q["kind"] for q in client.get(f"{API}/ai/suggestions?route=/groups").json()["questions"]] == [
        "group_share"]
    assert client.get(f"{API}/ai/suggestions?route=/history").json()["questions"] == []
    assert client.get(f"{API}/ai/suggestions?route=/stock/NOPE999").json()["questions"] == []


def test_usage_shape(client, pool, ai_env):
    ai_env(AI_DAILY_MESSAGE_LIMIT=30, AI_MONTHLY_TOKEN_BUDGET=0)
    u = client.get(f"{API}/ai/usage").json()
    assert u == {**u, "messages_today": 0, "daily_message_limit": 30, "messages_remaining": 30, "tokens_month": 0,
                 "monthly_token_budget": None, "tokens_remaining": None, "cost_usd_month": 0.0,
                 "model": "claude-haiku-5-5", "available": True, "deep_search_cost": 5,
                 "disclaimer": "AI 回答僅供參考，非投資建議。"}
    assert set(u) == {"date", "month", "messages_today", "daily_message_limit", "messages_remaining",
                      "tokens_month", "monthly_token_budget", "tokens_remaining", "cost_usd_month", "model",
                      "available", "deep_search_cost", "disclaimer"}


def test_day_word_follows_the_close_date():
    """Before today's close is published the numbers are yesterday's: the question names the date, not 「今天」."""
    from datetime import date

    from forliosa.ai.suggestions import ledger_questions

    holdings = [{"day_change": -10, "weight": 0.1}, {"day_change": 5, "weight": 0.1}]
    today = date(2026, 11, 13)
    old = ledger_questions(holdings, {"as_of": "2026-11-12T13:30:00+08:00"}, today)[0]
    assert old["text"] == "11/12 誰拖累了我的報酬？" and old["lines"] == ["11/12", "誰拖累了我？"]
    fresh = ledger_questions(holdings, {"as_of": "2026-11-13T13:30:00+08:00"}, today)[0]
    assert fresh["text"] == "今天誰拖累了我的報酬？"
    assert ledger_questions(holdings, None, today)[0]["text"].startswith("今天")
