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
