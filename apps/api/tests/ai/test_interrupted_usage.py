"""2026-11-14 review: a streamed call cut off by the browser leaving was billed but never recorded in ai_usage."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai.chat import ChatTurn
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.marketdata.service import get_market_data
from forliosa.models import AiUsage, User
from tests.ai.fake_anthropic import text


def test_a_call_cut_off_by_the_browser_still_counts(client, pool, fake, engine):
    fake.reply(text("第一段很長的回答，台積電今天的走勢如下所述。"), text("第二段"))
    with session_factory()() as db:
        me = db.scalar(select(User))
        turn = ChatTurn(db, me, get_market_data(), pool, get_settings())
        gen = turn.run(thread_id=None, message="台積電今天怎麼了？", route="/", symbol=None, privacy=False)
        for name, _ in gen:
            if name == "text":
                break
        gen.close()  # what Starlette does when the browser goes away
    with Session(engine) as db:
        rows = list(db.scalars(select(AiUsage)))
        assert [r.stop_reason for r in rows] == ["interrupted"]
        assert rows[0].input_tokens > 0
