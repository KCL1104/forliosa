from types import SimpleNamespace

from forliosa.ai.keypool import KeyPool
from forliosa.ai.smoke import check_workspaces


def _factory(workspaces: dict[str, str | Exception]):
    def make(key: str):
        def create(**params):
            assert params["max_tokens"] == 1
            outcome = workspaces[key]
            if isinstance(outcome, Exception):
                raise outcome
            headers = {"anthropic-workspace-id": outcome, "anthropic-ratelimit-input-tokens-limit": "400000",
                       "anthropic-ratelimit-input-tokens-remaining": "399990"}
            return SimpleNamespace(headers=headers)

        return SimpleNamespace(messages=SimpleNamespace(with_raw_response=SimpleNamespace(create=create)))

    return make


def test_three_keys_in_three_workspaces(capsys):
    pool = KeyPool.from_keys(["k1", "k2", "k3"], client_factory=_factory({"k1": "wrkspc_a", "k2": "wrkspc_b",
                                                                          "k3": "wrkspc_c"}))
    assert check_workspaces(pool, "claude-haiku-5-5") == 0
    out = capsys.readouterr().out
    assert "3 把金鑰分屬 3 個不同的 workspace" in out and "k1" not in out
    assert [s.workspace_id for s in pool.slots] == ["wrkspc_a", "wrkspc_b", "wrkspc_c"]


def test_shared_workspace_and_failed_slot_are_reported(capsys):
    pool = KeyPool.from_keys(["k1", "k2", "k3"], client_factory=_factory({"k1": "wrkspc_a", "k2": "wrkspc_a",
                                                                          "k3": RuntimeError("401")}))
    assert check_workspaces(pool, "claude-haiku-5-5") == 1
    out = capsys.readouterr().out
    assert "#1、#2 在同一個 workspace" in out and "金鑰槽 #3：失敗" in out


def test_the_smoke_answer_follows_a_text_reset(client, engine, pool, monkeypatch, capsys):
    """An edit dropped after part of it was shown (``text_reset``): the CLI prints the answer as written and counts
    that, not the abandoned edit."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from forliosa.ai import smoke
    from forliosa.models import User

    events = [("text", {"delta": "整理到一半的"}), ("text_reset", {"text": "原本寫的回答"}),
              ("done", {"model": "claude-haiku-5-5", "stop_reason": "end_turn", "usage": {}})]

    class Turn:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, **kwargs):
            return iter(events)

    with Session(engine) as db:
        demo = db.scalar(select(User).where(User.email == "demo@forliosa.local"))
    monkeypatch.setattr(smoke, "discover_keys", lambda: ["k1"])
    monkeypatch.setattr(smoke, "build_pool", lambda: pool)
    monkeypatch.setattr(smoke, "ChatTurn", Turn)
    monkeypatch.setattr(smoke, "_demo_user", lambda db: db.merge(demo))
    assert smoke.main(["--ask", "台達電今天為啥跌這麼多?", "--deep"]) == 0
    out = capsys.readouterr().out
    assert "↺ 改回原本寫的回答：\n原本寫的回答" in out
    assert f"回答 {len('原本寫的回答')} 個字" in out  # the reset answer is counted, not the abandoned edit
