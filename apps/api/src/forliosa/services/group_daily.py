"""群組 AI 日報 (產品負責人 2026-11-16, the group subscription memo, decisions 4–6 and 9): a short report of each
**boosted** group's trading day (``services.group_plans``), on the group page (``GET /groups/{id}/daily-reports``) and,
when the owner turns 「盤前」 on for a channel, pushed there as 「昨日你的群組」 (2026-11-18: no 「日報」 switch).

* **Inputs**: only what members already share with the group, the same rules as the weekly digest
  (``sharing.digest_day_facts``): the day return (the leaderboard's 今日) of members who share ``returns``, the symbols
  of those who share ``holdings`` (only symbols two or more hold are ever shown) with each one's move that day, the
  day's feed trades of those who share ``trades`` (side and stock; imported statement rows never), and the day returns
  of 發行量加權股價報酬指數 and 元大台灣50. Never amounts, quantities, watchlists, personal briefings or AI chats. News
  only as links to pages the site already has: the market page's AI 收盤重點 and the stocks' 「為什麼漲跌」 — the report
  does no web search of its own.
* **The AI paragraph** (2–4 sentences): only with two or more members sharing returns who have a number that day (a
  member without a ledger is only counted on the page). The model sees anonymous labels in a random order and numbers
  the server already worked out (how many rose and fell, the range, how many beat each benchmark, the common holdings'
  moves, the trade count — only while someone shares trades). An answer that names a label (also a lone or full-width
  letter), gives advice or a target price, predicts, explains a move, uses a percentage (or its direction) or a count
  the prompt did not have, or reads like boilerplate is rejected; one
  rewrite is asked for, then the report keeps its facts only (``failed``). One normal Messages call on the digest model
  (Haiku, effort low), charged to nobody (``ai_usage.feature = "group_daily"``, ``user_id`` NULL, ``thread_id`` the
  report id). ``AI_GROUP_DAILY_MONTHLY_BUDGET_USD`` caps the month for all groups together.
* **Withdrawal**: like the digest, the paragraph is shown (and pushed) only while every member whose numbers went into
  it still shares them and every trade it counted is still there (``sharing.daily_summary_visible``); the facts are
  filtered by the current settings on every read, and a trade deleted or changed later drops out
  (``sharing.daily_trades_live``).
* **When**: trading days, for the latest finished session, once both markets' official closes of that session are
  stored (``forliosa.closes``: TWSE's same-day file in the afternoon, TPEx about 23:30) and TWSE's indices too. From
  06:30 the next morning (:data:`CUTOFF`) it is written with whatever is in: interim evening closes for a market whose
  official file is late (with a note), no 加權報酬指數 comparison while TWSE's index file is missing. The worker looks
  every 10 minutes (``Worker.group_daily``); one report per group and day, and per boost and day (a boost moved to
  another group after its report was written does not write a second one that day).
* **Push**: channels with ``notify_premarket`` (盤前, default off; 產品負責人 2026-11-18). The report of session D goes
  out at 07:30 of the next trading day, inside the 盤前重點 message when there is one, else alone
  (``reports.push.daily_due``); only members who push contribute to the pushed text.
* **When a boost ends** no new report is written; earlier ones stay readable until they are 30 days old.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import anthropic
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.keypool import KeyPool, KeysBusy, get_key_pool, is_failover_error
from forliosa.ai.pricing import CallUsage
from forliosa.api.errors import unprocessable
from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import AiMarketSummary, AiUsage, DatasetStatus, Group, GroupDailyReport, NotificationOutbox
from forliosa.services import group_plans, notifications, sharing
from forliosa.timeutil import TAIPEI, iso_taipei, market_close_dt, now_utc, today_taipei

log = logging.getLogger("forliosa.group_daily")

FEATURE = "group_daily"
DIGEST_MODEL_FEATURE = "group_digest"  # the same model as the weekly digest (AI_MODEL_DIGEST, else AI_MODEL)
MIN_RETURN_SHARERS = 2
MAX_AGE_DAYS = 4  # a session older than this is not reported any more (e.g. after a long outage)
CUTOFF = time(6, 30)  # the morning after the session: write with whatever closes are in (before the 07:30 push)
RETENTION_DAYS = 30
MAX_ATTEMPTS = 3  # model calls that failed on a key, a connection or a busy pool before the report keeps facts only
MAX_TOKENS = 1500
MAX_SUMMARY_CHARS = 220
DISCLAIMER = notifications.DISCLAIMER
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
WEEKDAYS = "一二三四五六日"
SUMMARY_WITHDRAWN = "寫這段 AI 摘要時用到的分享內容已有變動（有成員調整了分享設定或離開群組），摘要不再顯示。"
FEW_SHARERS = f"分享報酬率的成員不到 {MIN_RETURN_SHARERS} 位，這天沒有 AI 摘要。"
NO_SUMMARY = "這天的 AI 摘要沒有寫成，下面的數字照常。"
WRITING = "AI 摘要還在寫。"
INTERIM_NOTE = "寫這份日報時，有一個市場的正式收盤價還沒進來，用的是晚間的暫時收盤價（不含 ETF）。"

# Privacy and advice: a label, a target price, advice, a prediction or an explanation of a move.
FORBIDDEN = re.compile(
    r"成員\s*[A-Z]|目標價|建議|買進訊號|賣出訊號|加碼|減碼|進場|出場|停損|停利|明天|明日|下週|後市|預期|預估|可望|看好|看淡|"
    r"看壞|有望|將會|恐將|因為|由於|受惠|受累|帶動|拖累|消息面")
# House style: no evaluations, filler connectives, dashes, exclamation marks or Markdown.
STYLE = re.compile(r"整體而言|整體來看|總的來說|總體來看|值得注意|值得一提|此外|另外值得|表現亮眼|亮眼|"
                   r"值得肯定|穩健|可喜|遺憾|不錯|強勁|疲弱|—|――|！|!|\*\*|#")
# Checked on the NFKC form (full-width ％, letters and digits become plain ones): a percentage with its sign, a count
# of people or trades, a lone capital letter (a member label; stock names are taken out first).
PERCENT = re.compile(r"([+\-−]?)\s*(\d+(?:\.\d+)?)\s*%")
COUNT = re.compile(r"(?<![\d.])(\d+)\s*(?:個|位|人|筆)")
LABEL = re.compile(r"(?<![A-Za-z0-9])[A-Z](?![A-Za-z0-9])")
MINUS = re.compile(r"-(?=\d+(?:\.\d+)?\s*%)")

SYSTEM = (
    "你替一個親友投資群組寫「今日摘要」，會顯示在群組頁面上，也可能推播到群組的聊天室。"
    "你只會拿到匿名的成員代號與伺服器算好的數字。\n\n"
    "規則：\n"
    "1. 只描述群組整體：幾個人漲、幾個人跌、報酬的範圍；和「發行量加權股價報酬指數」「元大台灣50」比；"
    "兩人以上共同持有的股票今天的漲跌（最多寫兩檔，持有人數多的先寫）；今天有幾筆買賣。\n"
    "2. 不點名，也不要寫出任何成員代號（不要出現「成員 A」這類字），不要猜測任何人的身分，不要評論誰做得好或不好。\n"
    "3. 不給任何買進、賣出、加碼、減碼建議，不提目標價，不預測之後的走勢，不解釋漲跌的原因。\n"
    "4. 只用提供的數字和人數，照抄，不要自己算新的數字；百分比照提供的寫到小數點後一位。"
    "指數和股票的漲跌，負的寫「跌」：台積電 −0.6% 寫成「台積電跌 0.6%」；報酬的範圍照提供的寫（從 −2.5% 到 +1.0%）。"
    "沒有資料的項目就略過。\n"
    "5. 繁體中文（台灣用語），2 到 4 句、150 字以內，純文字：不要標題、條列或 Markdown。\n"
    "6. 像群組裡的人在報今天的數字：句子短，直接說。不加評語或鼓勵（不寫「表現亮眼」「值得肯定」「穩健」），"
    "不用「整體而言」「值得注意的是」「此外」這類連接語，不用破折號或驚嘆號，最後一句不總結、不展望。\n\n"
    "寫法像這樣（字母換成提供的數字，沒有的項目整句拿掉）：\n"
    "今天有分享報酬的 N 個人，A 個漲、B 個跌，從 X% 到 Y%。發行量加權股價報酬指數漲 P%，元大台灣50 漲 Q%，"
    "N 個人裡有 K 個漲得比 0050 多。M 個人都有的某某股漲 R%。今天有 T 筆買賣。"
)


# -- when ------------------------------------------------------------------------------------------------------------
def report_day(now: datetime) -> date | None:
    """The latest session whose close (13:30 Taipei) has passed, or None when it is too old to report."""
    from forliosa.closes import due_session

    day = due_session(now)
    return None if (now.astimezone(TAIPEI).date() - day).days > MAX_AGE_DAYS else day


def closes_ready(db: Session, day: date, now: datetime) -> tuple[bool, list[str]]:
    """Whether ``day``'s closes are in (``dataset_status``) and the notes the report then carries. Without any archive
    row at all (demo data, development) the day is used as it is."""
    from forliosa.closes import INTERIM_KEYS, MARKETS, OFFICIAL_KEYS, TWSE_INDEX_KEYS

    keys = [*TWSE_INDEX_KEYS, *INTERIM_KEYS.values()] + [k for m in MARKETS for k in OFFICIAL_KEYS[m]]
    status = {r.key: r.data_date for r in db.scalars(select(DatasetStatus).where(DatasetStatus.key.in_(keys)))}
    if not any(status.values()):
        return True, []

    def newest(names) -> date | None:
        return max((d for d in (status.get(k) for k in names) if d is not None), default=None)

    late = now >= datetime.combine(day + timedelta(days=1), CUTOFF, TAIPEI)
    notes: list[str] = []
    official = {m: newest(OFFICIAL_KEYS[m]) for m in MARKETS}
    if not all(d is not None and d >= day for d in official.values()):
        if not late:
            return False, []
        anything = {m: newest([*OFFICIAL_KEYS[m], INTERIM_KEYS[m]]) for m in MARKETS}
        if not all(d is not None and d >= day for d in anything.values()):
            return False, []
        notes.append(INTERIM_NOTE)
    index = newest(TWSE_INDEX_KEYS)
    if (index is None or index < day) and not late:
        return False, []
    return True, notes


# -- the model's input: labels and numbers only ----------------------------------------------------------------------
def _label(i: int) -> str:
    return LETTERS[i] if i < len(LETTERS) else LETTERS[i // len(LETTERS) - 1] + LETTERS[i % len(LETTERS)]


def pct1(value: float | None, minus: str = "-") -> str:
    """One decimal, signed (the report's own style: +2.3%, −1.2%)."""
    if value is None:
        return "無資料"
    text = f"{value * 100:+.1f}%"
    return text.replace("-", minus) if text not in ("+0.0%", "-0.0%") else "0.0%"


def weekday(d: date) -> str:
    return WEEKDAYS[d.weekday()]


@dataclass
class Allowed:
    """What a paragraph may write: the percentages as the prompt shows them (signed, one decimal), the counts of
    people and trades, and the stock and benchmark names (their letters are not member labels)."""
    pcts: set[float] = field(default_factory=set)
    counts: set[int] = field(default_factory=set)
    names: list[str] = field(default_factory=list)


def anonymous_prompt(report: GroupDailyReport, members: list[sharing.Member],
                     shuffle: Callable[[list], None] | None = None,
                     live: dict[str, tuple[str, str]] | None = None) -> tuple[str, Allowed]:
    """What the model sees, and what it may write. Never a display name, user id, group name or one member's
    holdings. Members without a number that day are left out; the trade count only while someone shares trades."""
    facts = report.facts or {}
    view = sharing.daily_facts_view(facts, members, live=live)
    values = [r["day_return_pct"] for r in view["returns"] if r["day_return_pct"] is not None]
    known = list(values)
    (shuffle or secrets.SystemRandom().shuffle)(values)
    allowed = Allowed()

    def show(v: float | None) -> str:
        text = pct1(v)
        if v is not None:
            allowed.pcts.add(float(text.rstrip("%")))
        return text

    def count(n: int) -> int:
        allowed.counts.add(n)
        return n

    day = report.trading_day
    lines = [f"交易日：{day.isoformat()}（{weekday(day)}）",
             f"今天有分享報酬率的成員：{count(len(values))} 位（匿名、順序隨機）"]
    lines += [f"- 成員 {_label(i)}：{show(v)}" for i, v in enumerate(values)]
    if known:
        up = sum(1 for v in known if v >= sharing.DAILY_FLAT)
        down = sum(1 for v in known if v <= -sharing.DAILY_FLAT)
        lines.append(f"上漲 {count(up)} 位、下跌 {count(down)} 位、持平 {count(len(known) - up - down)} 位；"
                     f"最低 {show(min(known))}，最高 {show(max(known))}")
    bench = [b for b in view["benchmarks"] if b.get("day_return_pct") is not None]
    if bench:
        lines.append("對照（今日）：" + "、".join(f"{b['name']} {show(b['day_return_pct'])}" for b in bench))
        for b in bench:
            above = sum(1 for v in known if v > b["day_return_pct"])
            lines.append(f"報酬高於{b['name']}的成員：{count(above)} 位")
    common = [f"{c['name']}（{count(c['holder_count'])} 人，{show(c['day_change_pct'])}）"
              for c in view["common_holdings"][:10]]
    lines.append("兩人以上共同持有的股票（持有人數，今日漲跌）：" + ("、".join(common) if common else "無"))
    if view["trades_shared"]:  # nobody shares trades: the count is unknown, not 0
        lines.append(f"今天的買賣筆數（只算有分享交易動態的成員）：{count(view['trades_count'])}")
    allowed.names = [b["name"] for b in bench] + [c["name"] for c in view["common_holdings"][:10]]
    return "\n".join(lines), allowed


def _direction(before: str) -> int:
    """The sign the words right before a percentage give it: 漲 0.6%, 上漲了 0.6%, 漲幅 0.6% (+1), 跌 0.6% (−1)."""
    tail = before.rstrip().removesuffix("了").removesuffix("幅")
    return 1 if tail.endswith("漲") else -1 if tail.endswith("跌") else 0


def check(text: str, allowed: Allowed) -> str | None:
    """Why ``text`` cannot be shown (None: it can). Checked on the NFKC form, so full-width ％, letters and digits
    are caught too: a percentage must be one the prompt had, with its sign when the text gives one (−0.6%, 跌 0.6%);
    a count of people or trades must be one of the prompt's; no lone capital letter (a member label)."""
    if not text:
        return "沒有內容"
    if len(text) > MAX_SUMMARY_CHARS:
        return "太長"
    norm = unicodedata.normalize("NFKC", text)
    if m := FORBIDDEN.search(norm):
        return f"用了「{m.group(0)}」"
    if m := STYLE.search(norm):
        return f"用了「{m.group(0)}」"
    bare = norm
    for name in sorted(allowed.names, key=len, reverse=True):
        bare = bare.replace(unicodedata.normalize("NFKC", name), " ")
    if m := LABEL.search(bare):
        return f"寫了成員代號「{m.group(0)}」"
    plain = {abs(v) for v in allowed.pcts}
    for m in PERCENT.finditer(norm):
        value = round(float(m.group(2)), 1)
        sign = {"+": 1, "-": -1, "−": -1}.get(m.group(1)) or _direction(norm[:m.start()])
        if (sign * value not in allowed.pcts) if sign else (value not in plain):
            return f"寫了提供的資料裡沒有的數字或方向 {m.group(0).strip()}"
    for m in COUNT.finditer(norm):
        if int(m.group(1)) not in allowed.counts:
            return f"寫了提供的資料裡沒有的人數或筆數 {m.group(0)}"
    return None


def request_params(prompt: str, model: str) -> dict[str, Any]:
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}], "output_config": {"effort": "low"}}


# -- writing ---------------------------------------------------------------------------------------------------------
@dataclass
class RunResult:
    day: date | None = None
    waiting: bool = False  # boosted groups wait for the day's closes
    created: int = 0
    with_summary: int = 0
    group_ids: list[str] = field(default_factory=list)


def month_cost(db: Session, now: datetime) -> Decimal:
    total = db.scalar(select(func.sum(AiUsage.cost_usd)).where(AiUsage.feature == FEATURE,
                                                              AiUsage.created_at >= store.month_start(now)))
    return Decimal(total or 0)


def _done(db: Session, r: GroupDailyReport, status: str, now: datetime, summary: str = "",
          error: str | None = None) -> None:
    r.status, r.summary, r.error, r.finished_at = status, summary, error, now
    db.commit()
    notifications.enqueue_daily(db, r, now)


def _transient(exc: BaseException) -> bool:
    return isinstance(exc, (KeysBusy, anthropic.APIConnectionError)) or is_failover_error(exc)


def write(db: Session, r: GroupDailyReport, pool: KeyPool | None, settings: Settings, now: datetime) -> None:
    """The AI paragraph of a pending report (or why there is none), then its pushes."""
    members = sharing.members_of(db, r.group_id)
    live = sharing.daily_trades_live(db, r.facts or {}, members)
    view = sharing.daily_facts_view(r.facts or {}, members, live=live)
    if len(view["returns"]) < MIN_RETURN_SHARERS:  # members with a number that day
        _done(db, r, "ready", now, error="few_sharers")
        return
    budget = Decimal(str(settings.ai_group_daily_monthly_budget_usd))
    if budget > 0 and month_cost(db, now) >= budget:
        _done(db, r, "failed", now, error="month_budget")
        return
    pool = pool or get_key_pool()
    if not pool.available:
        _done(db, r, "failed", now, error="ai_unavailable")
        return
    facts = dict(r.facts or {})
    facts["prompt_contributors"] = sharing.digest_prompt_contributors(facts, members)
    traders = set(facts["prompt_contributors"]["trades"])
    # the trades the paragraph counts: one deleted or changed later withdraws it (sharing.daily_summary_visible)
    facts["prompt_trade_ids"] = sorted(it["id"] for t in facts.get("trades", []) if t["user_id"] in traders
                                       for it in t.get("items", [])
                                       if live.get(it.get("id", "")) == (it["side"], it["symbol"]))
    r.facts = facts
    prompt, allowed = anonymous_prompt(r, members, live=live)
    problem: str | None = None
    for _ in range(2):  # the answer, and one rewrite when it cannot be shown
        content = prompt if problem is None else f"{prompt}\n\n（上一版不能用：{problem}。照規則重寫，只回摘要本身。）"
        params = request_params(content, r.model)
        try:
            raw, slot = pool.call(lambda c, p=params: c.messages.with_raw_response.create(**p),
                                  costs=store.slot_month_costs(db))
            pool.observe(slot, raw.headers)
            msg = raw.parse()
        except Exception as exc:  # classified below; never logs request content
            db.rollback()
            r.attempts = (r.attempts or 0) + 1
            log.warning("group daily %s: model call failed (%s)", r.id, type(exc).__name__)
            if _transient(exc) and r.attempts < MAX_ATTEMPTS:
                db.commit()  # stays pending: the next run tries again
            else:
                _done(db, r, "failed", now, error=type(exc).__name__[:200])
            return
        r.attempts = (r.attempts or 0) + 1
        store.record_usage(db, user_id=None, thread_id=r.id, feature=FEATURE,
                           model=getattr(msg, "model", None) or r.model, key_slot=slot,
                           usage=CallUsage.from_sdk(getattr(msg, "usage", None)),
                           stop_reason=getattr(msg, "stop_reason", None))
        text = " ".join("".join(getattr(b, "text", "") for b in msg.content
                                if getattr(b, "type", None) == "text").split())
        text = MINUS.sub("−", text)  # the report's own minus sign (−1.2%), like its numbers
        if getattr(msg, "stop_reason", None) not in ("end_turn", "stop_sequence"):
            problem = "沒寫完"
            continue
        problem = check(text, allowed)
        if problem is None:
            _done(db, r, "ready", now, summary=text)
            return
    log.info("group daily %s: no usable paragraph (%s)", r.id, problem)
    _done(db, r, "failed", now, error="rejected")


def create(db: Session, md: MarketData, group: Group, day: date, now: datetime, notes: list[str],
           settings: Settings, pass_id: str | None = None) -> GroupDailyReport | None:
    """The day's report with its facts (pending), or None when nobody shares anything the report could show (a day
    return, a common holding or a trade). ``pass_id``: the boost it is written under (one report per boost and day)."""
    members = sharing.members_of(db, group.id)
    if not any(m.shares(k) for m in members for k in sharing.DIGEST_PARTS):
        return None
    facts, sources = sharing.digest_day_facts(db, md, members, day)
    view = sharing.daily_facts_view(facts, members)
    if not (view["returns"] or view["common_holdings"] or view["trades"]):
        return None
    facts["notes"] = [*notes, *facts.get("notes", [])]
    facts["pass_id"] = pass_id
    r = GroupDailyReport(id=new_id("gdr"), group_id=group.id, trading_day=day, status="pending", summary="",
                         facts=facts, sources=sources, model=store.model_for(DIGEST_MODEL_FEATURE, settings),
                         attempts=0, created_at=now)
    db.add(r)
    try:
        db.commit()
    except IntegrityError:  # another run wrote it first
        db.rollback()
        return None
    return r


def run(db: Session, md: MarketData, now: datetime | None = None, pool: KeyPool | None = None,
        settings: Settings | None = None) -> RunResult:
    """One look (the worker, every 10 minutes): finish reports still pending, then write the latest session's report
    of every boosted group that has none, once the closes are in."""
    settings = settings or get_settings()
    now = now or now_utc()
    res = RunResult()
    for r in list(db.scalars(select(GroupDailyReport).where(GroupDailyReport.status == "pending")
                             .order_by(GroupDailyReport.created_at, GroupDailyReport.id))):
        write(db, r, pool, settings, now)
    day = report_day(now)
    if day is None:
        return res
    res.day = day
    passes = group_plans.boosting_passes(db, market_close_dt(day), now)
    if not passes:
        return res
    done = db.execute(select(GroupDailyReport.group_id, GroupDailyReport.facts)
                      .where(GroupDailyReport.trading_day == day)).all()
    have = {gid for gid, _ in done}
    # one report per boost and day: a boost moved to another group after its report was written does not write a
    # second one that day
    used = {(facts or {}).get("pass_id") for _, facts in done}
    todo = sorted(set(passes) - have)
    if not todo:
        return res
    ready, notes = closes_ready(db, day, now)
    if not ready:
        res.waiting = True
        return res
    for gid in todo:
        group = db.get(Group, gid)
        free = [p for p in passes[gid] if p not in used]
        if group is None or not free:
            continue
        used.add(free[0])
        r = create(db, md, group, day, now, notes, settings, pass_id=free[0])
        if r is None:
            continue
        res.created += 1
        res.group_ids.append(gid)
        write(db, r, pool, settings, now)
        res.with_summary += bool(r.summary)
    if res.created:
        log.info("group daily reports %s: %d written, %d with an AI paragraph", day.isoformat(), res.created,
                 res.with_summary)
    return res


# -- reading ---------------------------------------------------------------------------------------------------------
def report_out(r: GroupDailyReport, members: list[sharing.Member], market_summary: bool,
               live: dict[str, tuple[str, str]] | None = None) -> dict[str, Any]:
    """``live``: :func:`sharing.daily_trades_live` (the trades still there); without it, none are."""
    facts = r.facts or {}
    live = live or {}
    show = bool(r.summary) and r.status == "ready" and sharing.daily_summary_visible(facts, members, live)
    notes = list(facts.get("notes", []))
    if r.status == "pending":
        notes.append(WRITING)
    elif r.summary and not show:
        notes.append(SUMMARY_WITHDRAWN)
    elif not r.summary:
        notes.append(FEW_SHARERS if r.error == "few_sharers" else NO_SUMMARY)
    return {
        "id": r.id, "status": r.status, "trading_day": r.trading_day, "created_at": iso_taipei(r.created_at),
        "finished_at": iso_taipei(r.finished_at) if r.finished_at else None,
        "summary": r.summary if show else "", "facts": sharing.daily_facts_view(facts, members, live=live),
        "notes": notes,
        "market_summary": market_summary, "disclaimer": DISCLAIMER, "sources": list(r.sources or []),
        "is_demo": bool(facts.get("is_demo")),
    }


def _cursor(r: GroupDailyReport) -> str:
    return base64.urlsafe_b64encode(f"{r.trading_day.isoformat()}|{r.id}".encode()).decode().rstrip("=")


def reports_page(db: Session, group: Group, limit: int, cursor: str | None) -> dict[str, Any]:
    """The group's daily reports, newest day first (also after its boost ended), filtered by the current settings."""
    q = select(GroupDailyReport).where(GroupDailyReport.group_id == group.id)
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
            d, rid = raw.split("|", 1)
            after = date.fromisoformat(d)
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise unprocessable("分頁游標無效") from exc
        q = q.where((GroupDailyReport.trading_day < after)
                    | ((GroupDailyReport.trading_day == after) & (GroupDailyReport.id < rid)))
    rows = list(db.scalars(q.order_by(GroupDailyReport.trading_day.desc(), GroupDailyReport.id.desc())
                           .limit(limit + 1)))
    page = rows[:limit]
    members = sharing.members_of(db, group.id)
    days = {r.trading_day for r in page}
    summaries = set(db.scalars(select(AiMarketSummary.trading_day).where(
        AiMarketSummary.trading_day.in_(days), AiMarketSummary.status == "ok"))) if days else set()
    return {"items": [report_out(r, members, r.trading_day in summaries,
                                 sharing.daily_trades_live(db, r.facts or {}, members)) for r in page],
            "next_cursor": _cursor(page[-1]) if len(rows) > limit else None}


# -- retention -------------------------------------------------------------------------------------------------------
def purge_old(db: Session, today: date | None = None) -> int:
    """Reports more than 30 days old, with their queued pushes."""
    cutoff = (today or today_taipei()) - timedelta(days=RETENTION_DAYS)
    ids = list(db.scalars(select(GroupDailyReport.id).where(GroupDailyReport.trading_day < cutoff)))
    if ids:
        db.execute(delete(NotificationOutbox).where(NotificationOutbox.daily_report_id.in_(ids)))
        db.execute(delete(GroupDailyReport).where(GroupDailyReport.id.in_(ids)))
    db.commit()
    return len(ids)
