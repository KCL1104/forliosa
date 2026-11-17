"""群組 AI 日報 (群組加值包, 產品負責人 2026-11-16): boosted groups only; facts only from what members share (stored by
user, filtered on read); an anonymous prompt with server-computed numbers; answers that name, advise, predict, explain
or invent numbers are rewritten once, then dropped; the paragraph is withdrawn when a contributor stops sharing; the
report waits for the day's closes (with a cut-off); pushes go out at once or at 07:30, with only pushing members; the
model call is charged to nobody. The Messages API is faked behind the real SDK (no network)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import anthropic
import httpx2
import pytest
from sqlalchemy import select

from forliosa import closes, disclaimer
from forliosa.ai.keypool import KeyPool
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import AiUsage, DatasetStatus, GroupDailyReport, GroupPass, NotificationOutbox, Transaction
from forliosa.services import group_daily, notifications, sharing
from forliosa.timeutil import TAIPEI, last_tw_trading_day, market_close_dt, now_utc
from tests.api.m5 import (
    API,
    SHARE_ALL,
    SHARE_NONE,
    account,
    join,
    login,
    make_group,
    me_id,
    set_share,
    trade,
    trading_day,
)
from tests.api.push_fake import WEBHOOK, PushFake

Answer = str | Callable[[str], str]


def range_answer(prompt: str) -> str:
    """A paragraph that only uses the prompt's own numbers (the range line and the trade count)."""
    lo, hi = re.search(r"最低 (\S+)，最高 (\S+)", prompt).groups()
    n = re.search(r"今天有分享報酬率的成員：(\d+) 位", prompt).group(1)
    trades = re.search(r"買賣筆數（只算有分享交易動態的成員）：(\d+)", prompt).group(1)
    return f"今天有分享報酬的 {n} 個人，從 {lo} 到 {hi}。今天有 {trades} 筆買賣。"


class FakeModel:
    """The Messages endpoint of the real SDK, answering from a script (a text or a function of the prompt)."""

    def __init__(self, *answers: Answer):
        self.answers = list(answers) or [range_answer]
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        prompt = body["messages"][0]["content"]
        text = answer(prompt) if callable(answer) else answer
        return httpx2.Response(200, json={
            "id": "msg_fake", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 300, "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 0}})

    def client(self, key: str) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=key, max_retries=0, http_client=anthropic.DefaultHttpxClient(
            transport=httpx2.MockTransport(self.handler)))

    def pool(self) -> KeyPool:
        return KeyPool.from_keys([(1, "sk-test-daily")], client_factory=self.client, sleep=lambda _s: None)

    @property
    def prompts(self) -> list[str]:
        return [b["messages"][0]["content"] for b in self.requests]


def evening(day: date, at: time = time(23, 40)) -> datetime:
    return datetime.combine(day, at, TAIPEI)


def boost(group_id: str, until: datetime | None = None) -> str:
    with session_factory()() as db:
        p = GroupPass(id=f"gps_{group_id[-8:]}", payer_id=None, group_id=group_id,
                      until=until or now_utc() + timedelta(days=30), source="manual", created_at=now_utc(),
                      updated_at=now_utc())
        db.add(p)
        db.commit()
        return p.id


def run(market, now: datetime, fake: FakeModel | None = None) -> group_daily.RunResult:
    with session_factory()() as db:
        return group_daily.run(db, market, now=now, pool=(fake or FakeModel()).pool())


def reports(group_id: str) -> list[GroupDailyReport]:
    with session_factory()() as db:
        rows = list(db.scalars(select(GroupDailyReport).where(GroupDailyReport.group_id == group_id)
                               .order_by(GroupDailyReport.trading_day)))
        for r in rows:
            db.expunge(r)
        return rows


@pytest.fixture()
def day() -> date:
    return trading_day(3)


@pytest.fixture()
def family(app, client, day):
    """A boosted group: owner 示範使用者 (returns + holdings), 小明 (everything, pushes), 小華 (returns + trades);
    and a free group of the same people."""
    g = make_group(client, "大學同學")
    free = make_group(client, "沒加值")
    b = login(app, "b@x.tw", "小明")
    c = login(app, "c@x.tw", "小華")
    for grp in (g, free):
        join(client, b, grp["id"], SHARE_ALL)
        join(client, c, grp["id"], {**SHARE_NONE, "returns": True, "trades": True})
        set_share(client, grp["id"], returns=True, holdings=True)
    before = trading_day(40)
    a_acc, b_acc, c_acc = account(client), account(b), account(c)
    trade(client, a_acc["id"], "2330", "buy", before, 1000, 500)
    trade(b, b_acc["id"], "2330", "buy", before, 1000, 500)
    trade(c, c_acc["id"], "2317", "buy", before, 1000, 100)
    trade(b, b_acc["id"], "2317", "buy", day, 1000, 100)  # 小明 shares trades: counted
    trade(c, c_acc["id"], "2454", "buy", day, 100, 1000)  # 小華 shares trades: counted
    trade(client, a_acc["id"], "2330", "buy", day, 100, 500)  # the owner does not share trades: never
    imported = {"account_id": account(c, "國泰－一般")["id"], "origin": "import",
                "rows": [{"symbol": "2412", "type": "buy", "trade_date": day.isoformat(), "quantity": 1000,
                          "price": 100}]}
    r = c.post(f"{API}/transactions/batch", json=imported)
    assert r.status_code == 201, r.text  # imported: never
    boost(g["id"])
    return {"g": g, "free": free, "a": client, "b": b, "c": c,
            "ids": {"a": me_id(client), "b": me_id(b), "c": me_id(c)}, "acc": {"b": b_acc, "c": c_acc}}


# -- who gets one, and what it holds -----------------------------------------------------------------------------------
def test_only_boosted_groups_and_only_shared_numbers(family, market, day):
    fake = FakeModel()
    res = run(market, evening(day), fake)
    assert res.day == day and res.created == 1 and res.with_summary == 1
    assert reports(family["free"]["id"]) == []  # not boosted: no daily report (the weekly digest is for everyone)
    [r] = reports(family["g"]["id"])
    ids = family["ids"]
    assert r.status == "ready" and r.trading_day == day and r.attempts == 1
    facts = r.facts
    assert [x["user_id"] for x in facts["returns"]] == [ids["a"], ids["b"], ids["c"]]
    assert sorted(h["user_id"] for h in facts["holdings"]) == sorted([ids["a"], ids["b"]])
    assert {t["user_id"]: [(i["side"], i["symbol"]) for i in t["items"]] for t in facts["trades"]} == {
        ids["b"]: [("buy", "2317.TW")], ids["c"]: [("buy", "2454.TW")]}
    assert len(facts["prompt_trade_ids"]) == 2 and facts["pass_id"]
    blob = json.dumps(facts, ensure_ascii=False)
    for secret in ("示範使用者", "小明", "小華", "大學同學", "quantity", "price", "2412", "永豐", "國泰"):
        assert secret not in blob
    assert facts["prompt_contributors"] == {"returns": [ids["a"], ids["b"], ids["c"]],
                                            "holdings": [ids["a"], ids["b"]], "trades": [ids["b"], ids["c"]]}
    assert run(market, evening(day, time(23, 50)), fake).created == 0  # one per group and day


def test_the_prompt_is_anonymous_with_server_computed_numbers(family, market, day):
    fake = FakeModel()
    run(market, evening(day), fake)
    [prompt] = fake.prompts
    for name in ("示範使用者", "小明", "小華", "大學同學", *family["ids"].values()):
        assert name not in prompt
    assert "成員 A" in prompt and "成員 C" in prompt and "成員 D" not in prompt
    assert re.search(r"上漲 \d 位、下跌 \d 位、持平 \d 位；最低 \S+，最高 \S+", prompt)
    assert "台積電（2 人，" in prompt and "今天的買賣筆數（只算有分享交易動態的成員）：2" in prompt
    assert re.search(r"報酬高於元大台灣50的成員：\d 位", prompt)
    req = fake.requests[0]
    assert req["output_config"] == {"effort": "low"} and "tools" not in req
    assert "不預測之後的走勢" in req["system"] and "不解釋漲跌的原因" in req["system"]
    with session_factory()() as db:  # charged to nobody
        [u] = db.scalars(select(AiUsage)).all()
        [r] = reports(family["g"]["id"])
        assert u.feature == "group_daily" and u.user_id is None and u.thread_id == r.id and u.key_slot == 1
        assert float(u.cost_usd) == pytest.approx((1200 * 0.10 + 300 * 0.50) / 1e6)
    assert family["b"].get(f"{API}/ai/usage").json()["tokens_month"] == 0


def test_reading_shows_names_to_members_and_filters_on_read(app, family, market, day):
    g, a, b, c = family["g"], family["a"], family["b"], family["c"]
    run(market, evening(day))
    url = f"{API}/groups/{g['id']}/daily-reports"
    page = b.get(url)
    assert page.status_code == 200, page.text
    [item] = page.json()["items"]
    assert item["status"] == "ready" and item["trading_day"] == day.isoformat() and item["summary"]
    facts = item["facts"]
    assert [x["display_name"] for x in facts["returns"]] == ["示範使用者", "小明", "小華"]
    assert [(h["symbol"], h["holder_count"]) for h in facts["common_holdings"]] == [("2330.TW", 2)]
    assert sorted((t["side"], t["symbol"], t["count"]) for t in facts["trades"]) == [
        ("buy", "2317.TW", 1), ("buy", "2454.TW", 1)]
    assert facts["trades_count"] == 2 and item["disclaimer"] == disclaimer.AI
    assert item["market_summary"] is False and item["notes"] == []
    assert a.get(f"{API}/groups/{family['free']['id']}/daily-reports").json()["items"] == []
    assert login(app, "z@x.tw", "路人").get(url).status_code == 404  # not a member

    set_share(c, g["id"])  # 小華 turns everything off: out of the facts, and the paragraph is withdrawn
    item = a.get(url).json()["items"][0]
    assert [x["display_name"] for x in item["facts"]["returns"]] == ["示範使用者", "小明"]
    assert item["facts"]["trades_count"] == 1 and item["summary"] == ""
    assert group_daily.SUMMARY_WITHDRAWN in item["notes"]
    set_share(c, g["id"], returns=True, trades=True)  # shared again: the paragraph only holds numbers all see
    assert a.get(url).json()["items"][0]["summary"]
    assert b.delete(f"{API}/groups/{g['id']}/members/{family['ids']['b']}").status_code == 204  # 小明 leaves
    item = a.get(url).json()["items"][0]
    assert item["summary"] == "" and item["facts"]["common_holdings"] == []
    assert b.get(url).status_code == 404


def test_fewer_than_two_sharers_means_no_model_call(app, client, market, day):
    g = make_group(client)
    x = login(app, "x@x.tw", "阿姨")
    join(client, x, g["id"], {**SHARE_NONE, "holdings": True})
    trade(client, account(client)["id"], "2330", "buy", trading_day(40), 1000, 500)
    boost(g["id"])
    fake = FakeModel()
    run(market, evening(day), fake)
    [r] = reports(g["id"])
    assert fake.requests == [] and r.status == "ready" and r.error == "few_sharers" and r.summary == ""
    item = client.get(f"{API}/groups/{g['id']}/daily-reports").json()["items"][0]
    assert item["notes"] == [group_daily.FEW_SHARERS] and len(item["facts"]["returns"]) == 1


def test_a_group_where_nobody_shares_anything_gets_no_report(app, client, market, day):
    g = make_group(client)
    set_share(client, g["id"])
    join(client, login(app, "x@x.tw", "阿姨"), g["id"], SHARE_NONE)
    boost(g["id"])
    assert run(market, evening(day)).created == 0 and reports(g["id"]) == []


def test_members_without_a_number_are_counted_not_described(app, client, market, day):
    """Members who share returns but have no ledger (yet) have no day return: they are not 'sharers' for the AI
    paragraph's two-member minimum, nor in the prompt; the page only counts them."""
    g = make_group(client, "登山社")
    trade(client, account(client)["id"], "2330", "buy", trading_day(40), 1000, 500)
    for i in range(3):
        join(client, login(app, f"h{i}@x.tw", f"山友{i}"), g["id"], {**SHARE_NONE, "returns": True})
    boost(g["id"])
    fake = FakeModel()
    run(market, evening(day), fake)
    [r] = reports(g["id"])
    assert fake.requests == [] and r.error == "few_sharers"
    facts = client.get(f"{API}/groups/{g['id']}/daily-reports").json()["items"][0]["facts"]
    assert len(facts["returns"]) == 1 and facts["returns"][0]["day_return_pct"] is not None
    assert facts["returns_no_data"] == 3 and facts["trades_shared"] is False

    empty = make_group(login(app, "solo@x.tw", "一個人"), "臨時群組")  # only a member without a number: no report
    boost(empty["id"])
    run(market, evening(day))
    assert reports(empty["id"]) == []


def test_nobody_sharing_trades_means_no_trade_count(app, client, market, day):
    g = make_group(client)
    b = login(app, "b@x.tw", "小明")
    join(client, b, g["id"], {**SHARE_NONE, "returns": True})
    for c in (client, b):
        trade(c, account(c)["id"], "2330", "buy", trading_day(40), 1000, 500)
    boost(g["id"])
    fake = FakeModel(lambda p: "今天有分享報酬的 2 個人。")
    run(market, evening(day), fake)
    assert "買賣筆數" not in fake.prompts[0]  # unknown, not 0
    item = client.get(f"{API}/groups/{g['id']}/daily-reports").json()["items"][0]
    assert item["facts"]["trades_shared"] is False and item["facts"]["trades"] == [] and item["summary"]
    with session_factory()() as db:
        members = sharing.members_of(db, g["id"])
        _, allowed = group_daily.anonymous_prompt(reports(g["id"])[0], members)
    assert group_daily.check("今天有 7 筆買賣。", allowed)  # a count the prompt never had


def test_a_deleted_or_changed_trade_drops_out_and_withdraws_the_paragraph(family, market, day):
    g, a, b = family["g"], family["a"], family["b"]
    run(market, evening(day))
    url = f"{API}/groups/{g['id']}/daily-reports"
    assert a.get(url).json()["items"][0]["summary"]
    with session_factory()() as db:
        tid = db.scalar(select(Transaction.id).where(Transaction.user_id == family["ids"]["b"],
                                                     Transaction.trade_date == day))
    r = b.delete(f"{API}/transactions/{tid}")
    assert r.status_code == 204, r.text
    item = a.get(url).json()["items"][0]
    assert [t["symbol"] for t in item["facts"]["trades"]] == ["2454.TW"] and item["facts"]["trades_count"] == 1
    assert item["summary"] == "" and group_daily.SUMMARY_WITHDRAWN in item["notes"]  # it counted 2 trades


def test_one_report_per_boost_and_day(client, market, day):
    """A boost moved to another of the owner's groups after its report was written does not write a second one."""
    g1, g2 = make_group(client, "一"), make_group(client, "二")
    trade(client, account(client)["id"], "2330", "buy", trading_day(40), 1000, 500)
    with session_factory()() as db:
        db.add(GroupPass(id="gps_move", payer_id=me_id(client), group_id=g1["id"], until=now_utc() + timedelta(days=30),
                         source="manual", created_at=now_utc(), updated_at=now_utc()))
        db.commit()
    assert run(market, evening(day, time(23, 30))).created == 1
    assert client.put(f"{API}/groups/{g2['id']}/plan", json={"pass_id": "gps_move"}).status_code == 200
    assert run(market, evening(day, time(23, 40))).created == 0
    assert len(reports(g1["id"])) == 1 and reports(g2["id"]) == []
    boost(g2["id"])  # a second boost of its own: it gets one
    assert run(market, evening(day, time(23, 50))).created == 1


# -- checking the answer ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "成員 A 今天漲最多。",
    "今天大家平均漲 99.9%，台積電目標價 1200 元。",
    "今天多數人上漲，整體而言表現亮眼！",
    "台積電受惠法說會帶動，明天可望續漲。",
])
def test_a_bad_answer_gets_one_rewrite(family, market, day, bad):
    fake = FakeModel(bad, range_answer)
    run(market, evening(day), fake)
    [r] = reports(family["g"]["id"])
    assert r.status == "ready" and r.summary and len(fake.requests) == 2
    assert "上一版不能用" in fake.prompts[1]
    with session_factory()() as db:
        assert len(db.scalars(select(AiUsage)).all()) == 2


def test_two_bad_answers_keep_the_facts_only(family, market, day):
    fake = FakeModel("成員 B 漲最多。", "今天大家平均漲 99.9%。")
    run(market, evening(day), fake)
    [r] = reports(family["g"]["id"])
    assert r.status == "failed" and r.error == "rejected" and r.summary == "" and r.facts["returns"]
    item = family["a"].get(f"{API}/groups/{family['g']['id']}/daily-reports").json()["items"][0]
    assert item["summary"] == "" and item["notes"] == [group_daily.NO_SUMMARY]


def test_check_and_formatting():
    allowed = group_daily.Allowed(pcts={2.3, -1.2, 0.8, -0.6, 0.4}, counts={3, 2, 1, 0},
                                  names=["元大S&P500", "台積電", "元大台灣50"])
    assert group_daily.check("今天有分享報酬的 3 個人，2 個漲、1 個跌，從 −1.2% 到 +2.3%。加權報酬指數漲 0.80%。"
                             "台積電跌 0.6%，元大S&P500 漲 0.4%。今天有 0 筆買賣。", allowed) is None
    assert group_daily.check("從 1.2% 到 2.3%。", allowed) is None  # no sign given: the absolute value is checked
    assert "99.9%" in group_daily.check("漲 99.9%。", allowed)
    # caught on the NFKC form, with the sign or direction, counts, and labels however they are written
    for bad in ("從 −1.2％ 到 +9.9％。", "台積電漲 0.6%。", "台積電上漲了 0.6%。", "漲幅 1.2%。",
                "加權報酬指數 −0.8%。", "今天有分享報酬的 16 個人。", "今天有 5 筆買賣。", "A 和 C 漲得比 0050 多。",
                "成員Ａ漲 2.3%。", "Ｂ漲 2.3%。"):
        assert group_daily.check(bad, allowed) is not None, bad
    assert group_daily.check("", allowed) == "沒有內容"
    assert group_daily.check("字" * 300, allowed) == "太長"
    assert group_daily.pct1(-0.0123, "−") == "−1.2%" and group_daily.pct1(0.0004) == "0.0%"
    assert group_daily.pct1(None) == "無資料"


def test_no_keys_or_no_budget_keeps_the_facts(family, market, day, monkeypatch):
    with session_factory()() as db:
        group_daily.run(db, market, now=evening(day), pool=KeyPool([]))
    [r] = reports(family["g"]["id"])
    assert r.status == "failed" and r.error == "ai_unavailable" and r.facts["returns"]

    with session_factory()() as db:  # the month's budget for all groups is spent: no call
        db.delete(db.get(GroupDailyReport, r.id))
        db.add(AiUsage(user_id=None, thread_id="x", feature="group_daily", model="m", cost_usd=Decimal("6"),
                       created_at=evening(day)))
        db.commit()
    fake = FakeModel()
    run(market, evening(day), fake)
    [r] = reports(family["g"]["id"])
    assert fake.requests == [] and r.status == "failed" and r.error == "month_budget"


# -- when --------------------------------------------------------------------------------------------------------------
def _status(**dates: date | None) -> None:
    keys = {"twse": closes.OFFICIAL_KEYS["TWSE"][0], "tpex": closes.OFFICIAL_KEYS["TPEX"][0],
            "tpex_interim": closes.INTERIM_KEYS["TPEX"], "index": closes.TWSE_INDEX_KEYS[0]}
    with session_factory()() as db:
        for name, d in dates.items():
            row = db.get(DatasetStatus, keys[name]) or DatasetStatus(key=keys[name])
            row.data_date, row.rows, row.fetched_at = d, 1, now_utc()
            db.add(row)
        db.commit()


def before(day: date) -> date:
    """The trading day before ``day`` (on a Tuesday trading_day(4) is ``day`` itself: both are the Friday)."""
    return last_tw_trading_day(day - timedelta(days=1))


def test_waits_for_both_markets_then_the_cutoff(family, market, day):
    prev = before(day)
    _status(twse=day, tpex=prev, index=day)  # TPEx's official file is not in yet
    res = run(market, evening(day))
    assert res.waiting and reports(family["g"]["id"]) == []
    _status(tpex_interim=day)  # only the interim evening close: still waiting before the cut-off
    assert run(market, evening(day, time(23, 55))).waiting
    morning = datetime.combine(day + timedelta(days=1), time(6, 40), TAIPEI)
    res = run(market, morning)  # past 06:30: written with the interim close, saying so
    assert res.created == 1
    [r] = reports(family["g"]["id"])
    assert group_daily.INTERIM_NOTE in r.facts["notes"]


def test_waits_for_the_index_until_the_cutoff(family, market, day):
    _status(twse=day, tpex=day, index=before(day))
    assert run(market, evening(day)).waiting
    assert run(market, datetime.combine(day + timedelta(days=1), time(6, 40), TAIPEI)).created == 1
    _status(index=day)


def test_closes_in_means_written_at_once(family, market, day):
    _status(twse=day, tpex=day, index=day)
    assert run(market, evening(day, time(23, 35))).created == 1


def test_push_at_quiet_hours():
    d = date(2026, 11, 16)
    assert group_daily.push_at(evening(d, time(22, 59))) == evening(d, time(22, 59))
    assert group_daily.push_at(evening(d, time(23, 0))) == datetime.combine(d + timedelta(days=1), time(7, 30), TAIPEI)
    assert group_daily.push_at(evening(d, time(3, 10))) == evening(d, time(7, 30))
    assert group_daily.push_at(evening(d, time(7, 30))) == evening(d, time(7, 30))
    assert group_daily.push_at(evening(d, time(14, 5))) == evening(d, time(14, 5))


# -- expiry and retention ----------------------------------------------------------------------------------------------
def test_an_ended_boost_stops_new_reports_and_keeps_old_ones(family, market, day):
    first = trading_day(6)
    run(market, evening(first))
    assert len(reports(family["g"]["id"])) == 1
    with session_factory()() as db:
        for p in db.scalars(select(GroupPass)):
            p.until = market_close_dt(first) + timedelta(hours=12)
        db.commit()
    assert run(market, evening(day)).created == 0
    items = family["a"].get(f"{API}/groups/{family['g']['id']}/daily-reports").json()["items"]
    assert [i["trading_day"] for i in items] == [first.isoformat()]  # the old one stays
    assert family["a"].get(f"{API}/groups/{family['g']['id']}").json()["plan"]["daily_report"] is False


def test_retention_after_30_days(family, market, day):
    run(market, evening(day))
    with session_factory()() as db:
        assert group_daily.purge_old(db, today=day + timedelta(days=30)) == 0
        assert group_daily.purge_old(db, today=day + timedelta(days=31)) == 1
    assert reports(family["g"]["id"]) == []


# -- push --------------------------------------------------------------------------------------------------------------
def _channel(family, daily: bool = True) -> PushFake:
    fake = PushFake().install()
    g, a = family["g"], family["a"]
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    ch = a.get(f"{API}/groups/{g['id']}/channels").json()["discord"]
    assert ch["notify_daily"] is False  # off by default
    if daily:
        r = a.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_daily": True})
        assert r.status_code == 200 and r.json()["discord"]["notify_daily"] is True
    return fake


def test_finished_at_night_is_pushed_at_0730_with_only_pushing_members(family, market, day):
    fake = _channel(family)
    trade(family["b"], family["acc"]["b"]["id"], "2303", "buy", day, 1000, 50)  # after the channel was set up
    sent_before = len(fake.discord)
    run(market, evening(day, time(23, 40)))
    with session_factory()() as db:
        [row] = db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "daily")).all()
        assert row.not_before == datetime.combine(day + timedelta(days=1), time(7, 30), TAIPEI)
        notifications.send_due(db, market, now=datetime.combine(day + timedelta(days=1), time(7, 0), TAIPEI))
    assert len(fake.discord) == sent_before  # not yet
    with session_factory()() as db:
        notifications.send_due(db, market, now=datetime.combine(day + timedelta(days=1), time(7, 31), TAIPEI))
    text = fake.discord[-1].body["content"]
    assert len(fake.discord) == sent_before + 1
    assert text.startswith("Forliosa 群組「大學同學」日報") and f"{day.month}/{day.day}（" in text
    assert "小明" in text and "示範使用者" not in text and "小華" not in text
    [r] = reports(family["g"]["id"])
    assert r.summary not in text  # 示範使用者 and 小華 contributed, do not push
    assert text.count(disclaimer.SHORT) == 1  # the site's line goes out with or without the AI paragraph
    assert "台積電" not in text  # one pushing member shares holdings: nothing is common
    # sent the morning after: 當日／那天, not 今日／今天
    assert "當日報酬：" in text and "今日報酬" not in text and "今天的買賣" not in text
    # only 小明's trade made after the channel was set up (the push start of trade pushes); 小華 does not push
    assert "那天的買賣：買進 聯電" in text and "鴻海" not in text and "聯發科" not in text


def test_finished_in_the_evening_is_pushed_at_once_and_not_when_off(family, market, day):
    _channel(family, daily=False)
    run(market, evening(day, time(19, 0)))
    with session_factory()() as db:
        assert db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "daily")).all() == []


def test_finished_in_the_evening_is_due_at_once(family, market, day):
    fake = _channel(family)
    n = len(fake.discord)
    run(market, evening(day, time(19, 0)))
    with session_factory()() as db:
        notifications.send_due(db, market, now=evening(day, time(19, 1)))
    text = fake.discord[-1].body["content"]
    assert len(fake.discord) == n + 1 and "日報" in text and "今日報酬：" in text  # sent the same evening


def test_the_daily_job_is_scheduled(monkeypatch):
    from forliosa.worker import Worker

    assert "group_daily" in [j.name for j in Worker(md=object()).jobs]
    monkeypatch.setattr(get_settings(), "group_daily_enabled", False)
    assert "group_daily" not in [j.name for j in Worker(md=object()).jobs]
