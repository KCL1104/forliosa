"""全站免責文字（產品負責人 2026-11-17）: one wording everywhere, the short line once in every push, and the chat
prompt says answers are not investment advice."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from forliosa import disclaimer
from forliosa.ai import prompts
from forliosa.config import get_settings
from forliosa.services import channels, digests, group_daily, notifications

REPO = Path(__file__).resolve().parents[3]
WEB_COPY = REPO / "apps" / "web" / "src" / "lib" / "disclaimer.ts"
FULL_STATEMENT = REPO / "docs" / "legal" / "disclaimer.md"
TERMS = REPO / "docs" / "legal" / "terms-of-service.md"


def test_the_lines_say_what_forliosa_is_and_is_not():
    assert "只替你整理" in disclaimer.SHORT and "不是投資顧問" in disclaimer.SHORT
    assert "不提供投資建議" in disclaimer.SHORT and "自己判斷" in disclaimer.SHORT
    assert "只替你整理" in disclaimer.AI and "可能有錯" in disclaimer.AI and "不是投資顧問" in disclaimer.AI
    assert "第三方" in disclaimer.ANALYST and "不是投資建議" in disclaimer.ANALYST
    # one line each: they go into one-line UI rows and push messages
    assert all("\n" not in s for s in (disclaimer.SHORT, disclaimer.AI, disclaimer.ANALYST))


@pytest.mark.skipif(not WEB_COPY.exists(), reason="the frontend is not in this checkout (e.g. the API image)")
def test_backend_and_frontend_use_the_same_words():
    source = WEB_COPY.read_text(encoding="utf-8")
    web = dict(re.findall(r'^\s*(\w+): "([^"]+)",$', source, re.M))
    assert web["short"] == disclaimer.SHORT
    assert web["ai"] == disclaimer.AI
    assert web["analyst"] == disclaimer.ANALYST


@pytest.mark.skipif(not FULL_STATEMENT.exists(), reason="docs are not in this checkout")
def test_full_statement_and_terms_carry_the_same_line():
    full = FULL_STATEMENT.read_text(encoding="utf-8")
    assert disclaimer.SHORT in full and "〈服務條款〉第 2 節" in full
    terms = TERMS.read_text(encoding="utf-8")
    section2 = terms[terms.index("## 2. "):terms.index("## 3. ")]
    assert disclaimer.SHORT in section2
    assert "不是證券投資顧問事業" in section2 and "投資分析意見或推介建議" in section2


def test_api_fields_use_the_shared_text():
    assert prompts.DISCLAIMER == disclaimer.AI  # done.disclaimer, GET /ai/usage
    assert prompts.ANALYST_DISCLAIMER == disclaimer.ANALYST  # analyst-views
    assert notifications.DISCLAIMER == disclaimer.AI  # weekly digests, daily reports
    assert digests.DISCLAIMER == disclaimer.AI and group_daily.DISCLAIMER == disclaimer.AI


def test_chat_prompt_keeps_its_rules_and_says_answers_are_not_advice():
    assert "Forliosa 只替使用者整理資訊，不是投資顧問：回答不要寫成替使用者做的投資建議或推薦" in prompts.CHAT_SYSTEM
    assert "也不自稱投資顧問或分析師" in prompts.CHAT_SYSTEM
    # the existing rules stay as they were
    assert "只做分析與整理，不保證報酬，不下買進或賣出的指令，也不給你自己的目標價" in prompts.CHAT_SYSTEM
    assert "不要自己寫免責聲明" in prompts.CHAT_SYSTEM
    assert prompts.CHAT_SYSTEM.index("只做分析與整理") < prompts.CHAT_SYSTEM.index("Forliosa 只替使用者整理資訊") \
        < prompts.CHAT_SYSTEM.index("不要自己寫免責聲明")


# -- push texts ------------------------------------------------------------------------------------------------------
GROUP = SimpleNamespace(name="大學同學")
NO_RETURNS: dict = {"returns": [], "benchmarks": [], "common_holdings": [], "trades": [], "trades_count": 0}


def once_at_the_end(text: str) -> None:
    assert text.count(disclaimer.SHORT) == 1, text
    assert text.endswith(disclaimer.SHORT)


@pytest.mark.parametrize("kind", ["discord", "telegram"])
def test_trade_push_ends_with_the_line(kind):
    view = {"trade_date": date(2026, 11, 17), "count": 1, "price": 1085.0, "currency": "TWD",
            "display_name": "小明", "side": "buy", "name": "台積電", "symbol": "2330.TW"}
    text = notifications.trade_text(GROUP, view, kind, get_settings())
    assert text.startswith("小明 買進 台積電（2330）")
    once_at_the_end(text)


def ai_marked(text: str, summary: str | None) -> None:
    """With an AI paragraph: that line starts with 「AI 整理：」 and the last line says it may be wrong, then the site's
    line (still once, still last). Without one: no AI marks at all."""
    lines = text.split("\n")
    if summary:
        assert lines[1] == disclaimer.AI_LABEL + summary, text
        assert lines[-1] == disclaimer.AI_NOTE + disclaimer.SHORT, text
        assert text.count(disclaimer.AI_LABEL) == 1 and text.count(disclaimer.AI_NOTE) == 1
    else:
        assert "AI" not in text, text
        assert lines[-1] == disclaimer.SHORT
    assert disclaimer.AI not in text  # one line at the end, not the web's AI line as well


@pytest.mark.parametrize("summary", ["這週四個人都上漲。", None])
@pytest.mark.parametrize("kind", ["discord", "telegram"])
def test_digest_push_has_the_line_with_or_without_the_ai_summary(summary, kind):
    digest = SimpleNamespace(week_start=date(2026, 11, 9), week_end=date(2026, 11, 13))
    view = {**NO_RETURNS, "returns": [{"display_name": "小明", "week_return_pct": 0.012}], "trades_count": 2}
    text = notifications.digest_text(GROUP, digest, view, summary, kind, get_settings())
    once_at_the_end(text)
    ai_marked(text, summary)


@pytest.mark.parametrize("summary", ["今天有分享報酬的 2 個人，都漲。", None])
@pytest.mark.parametrize("same_day", [True, False])
def test_daily_push_has_the_line_with_or_without_the_ai_paragraph(summary, same_day):
    report = SimpleNamespace(trading_day=date(2026, 11, 16))
    view = {**NO_RETURNS, "returns": [{"display_name": "小明", "day_return_pct": 0.023}]}
    text = notifications.daily_text(GROUP, report, view, summary, "telegram", get_settings(), same_day)
    assert text.startswith("Forliosa 群組「大學同學」日報")
    once_at_the_end(text)
    ai_marked(text, summary)


def test_signed_is_the_public_helper_for_other_pushes():
    """Other features' pushes (market reports) build their lines and call ``signed``; ``_signed`` stays as an alias."""
    assert notifications._signed is notifications.signed
    plain = notifications.signed(["盤後重點 11/17"], "discord")
    assert plain == "盤後重點 11/17\n" + disclaimer.SHORT
    body = ["盤後重點 11/17", notifications.ai_line("加權指數收漲 1.2%。", "telegram")]
    with_ai = notifications.signed(body, "telegram", ai=True)
    assert with_ai.split("\n") == [*body, disclaimer.AI_NOTE + disclaimer.SHORT]
    assert body[1] == "AI 整理：加權指數收漲 1.2%。"
    once_at_the_end(with_ai)


def test_channel_connected_messages_have_the_line():
    once_at_the_end(channels.connect_message(GROUP))
    once_at_the_end(channels.linked_message(GROUP))


@pytest.mark.parametrize("kind", ["discord", "telegram"])
def test_a_long_message_is_shortened_before_the_line_not_after(kind):
    """Discord cuts at 2,000 characters and Telegram at 4,096 (``pushers``): the line must still be the last one."""
    digest = SimpleNamespace(week_start=date(2026, 11, 9), week_end=date(2026, 11, 13))
    returns = [{"display_name": f"很長很長的顯示名稱第{i:02d}位成員", "week_return_pct": 0.01} for i in range(50)]
    view = {**NO_RETURNS, "returns": returns, "trades_count": 2}
    text = notifications.digest_text(GROUP, digest, view, "摘要。" * 1500, kind, get_settings())
    limit = 2000 if kind == "discord" else 4096
    assert len(text) <= limit
    once_at_the_end(text)
    assert text.split("\n")[-2].endswith("…")
    assert text.split("\n")[-1] == disclaimer.AI_NOTE + disclaimer.SHORT  # the AI note survives the cut too
