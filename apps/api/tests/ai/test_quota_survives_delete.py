"""2026-11-14 review: deleting conversations gave the day's questions back (the count came from ai_messages)."""
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import text


def test_deleting_conversations_does_not_reset_the_daily_limit(client, pool, fake, ai_env):
    ai_env(AI_DAILY_MESSAGE_LIMIT=2)
    for _ in range(2):
        fake.reply(text("好"))
        status, _ = chat(client, "台積電今天怎麼了？")
        assert status == 200
    status, body = chat(client, "再問一題")
    assert status == 429, body
    assert client.delete(f"{API}/ai/threads").status_code == 204
    assert client.get(f"{API}/ai/usage").json()["messages_today"] == 2
    calls = len(fake.requests)
    status, body = chat(client, "再問一題")
    assert status == 429, body
    assert len(fake.requests) == calls  # no model call
