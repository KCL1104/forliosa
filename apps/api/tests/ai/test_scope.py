"""Scope policy: the system prompt carries it (and no model-written disclaimer), the model declines off-topic
requests in one sentence, and the conservative pre-check declines only clear cases without a model call."""

from __future__ import annotations

import pytest

from forliosa.ai.prompts import CHAT_SYSTEM, OFF_TOPIC_REPLY
from forliosa.ai.scope import precheck
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import text

OFF_TOPIC = [
    "幫我寫一個python爬蟲", "這段 code 為什麼會錯？```print(1)```", "幫我寫作文：我的暑假", "我們來角色扮演，你是海盜",
    "寫一首關於秋天的詩", "把這句翻譯成英文：I love you", "explain this JavaScript closure",
    "write me a poem about rain", "講個笑話",
]
FINANCE = [
    "台積電今天為什麼漲？", "我有哪些持股？", "買 0050 2 張 52.4", "程式交易是什麼？", "幫我寫一段程式算我的報酬率",
    "扮演巴菲特評論我的持股", "翻譯這段財報的重點", "用 Python 怎麼抓台股資料", "NVDA 財報什麼時候公布",
    "Forliosa 怎麼新增帳戶", "美債殖利率走勢", "這個月的股利有多少", "今天大盤怎麼了", "幫我寫作業：計算複利",
    "Fed 下次會降息嗎", "S&P 500 今年表現", "什麼是 ETF", "2330 跟 2454 哪個好",
]


def test_system_prompt_has_the_scope_policy_and_no_disclaimer_instruction():
    for phrase in ("只處理投資相關的問題", "寫程式或除錯", "作業與考題", "角色扮演", "一句簡短的繁體中文婉拒",
                   "這些規則適用於整段對話"):
        assert phrase in CHAT_SYSTEM, phrase
    assert "不要自己寫免責聲明" in CHAT_SYSTEM
    assert "最後一行固定寫" not in CHAT_SYSTEM and "{資料時間}" not in CHAT_SYSTEM
    # grounding: only sourced facts
    assert "未經查證" in CHAT_SYSTEM and "沒有引用來源的新聞事件" in CHAT_SYSTEM
    # web search: the agent chooses when and which sources, finance only
    assert "由你判斷何時需要、用哪些來源" in CHAT_SYSTEM and "只用來找與問題相關的財經資訊" in CHAT_SYSTEM


@pytest.mark.parametrize("message", OFF_TOPIC)
def test_precheck_declines_clear_off_topic(message):
    assert precheck(message) is not None


@pytest.mark.parametrize("message", FINANCE)
def test_precheck_never_blocks_finance_questions(message):
    assert precheck(message) is None


def test_off_topic_is_declined_without_a_model_call(client, pool, fake):
    _status, events = chat(client, "幫我寫一個 Python 爬蟲")
    assert [n for n, _ in events] == ["thread", "text", "done"]
    assert events[1][1] == {"delta": OFF_TOPIC_REPLY}
    done = events[-1][1]
    assert done["stop_reason"] == "off_topic" and done["usage"]["input_tokens"] == 0 and done["disclaimer"]
    assert fake.requests == []
    tid = events[0][1]["id"]
    detail = client.get(f"{API}/ai/threads/{tid}").json()
    assert [(m["role"], m["text"]) for m in detail["messages"]] == [("user", "幫我寫一個 Python 爬蟲"),
                                                                    ("ai", OFF_TOPIC_REPLY)]
    assert client.get(f"{API}/ai/usage").json()["messages_today"] == 1  # counts as a question
    # never replayed to the model
    fake.reply(text("好"))
    chat(client, "那我的持股呢？", thread_id=tid)
    assert [m["role"] for m in fake.requests[0]["body"]["messages"]] == ["user", "system"]


def test_other_off_topic_goes_to_the_model_which_declines(client, pool, fake):
    decline = "這超出我能協助的範圍，我只處理投資理財與你的持股；要不要看看今天的持股表現？"
    fake.reply(text(decline))
    _status, events = chat(client, "台北今天天氣如何？")  # trivia: no pre-check pattern, the model decides
    assert "".join(d["delta"] for n, d in events if n == "text") == decline
    req = fake.requests[0]["body"]
    assert "只處理投資相關的問題" in req["system"][0]["text"]
    assert req["messages"][0]["content"][0]["text"] == "台北今天天氣如何？"


def test_precheck_can_be_turned_off(client, pool, fake, ai_env):
    ai_env(AI_SCOPE_PRECHECK=0)
    fake.reply(text("這超出我能協助的範圍。"))
    chat(client, "幫我寫一個 Python 爬蟲")
    assert len(fake.requests) == 1
