"""Sharing projection: the ONLY way group and delegation code reads another user's data (docs/api-contract.md
「分享（M5）」).

* **Delegations** (read-only viewing): :func:`enter_view_as` resolves ``X-Forliosa-View-As`` on every request and
  limits the request to the delegation's *current* scope (``services.scope``); revoked or foreign → 403
  ``delegation_revoked``.
* **Groups**: everything a member sees of another member is built here from that member's *current* share settings in
  that group, re-applied on every read (turning a toggle off, leaving the group: gone at once, from the feed too).
  A block whose toggle is off is **absent** (no key — not ``null``, not 0); a member who shares nothing is simply not
  in the leaderboard, holdings or feed (nothing says "did not share"). Weights are rounded to 0.01 and returns to
  0.0001; amounts (only with ``amounts``) to 2 decimals. Projections never contain quantities, account names, notes,
  fees, transaction ids or prices (prices only in the feed with ``trade_prices``).

Group feed items are computed, not stored: a trade item is one member's buys (or sells) of one symbol on one Taipei
day (``manual`` / ``import`` / ``ai_draft`` buy / sell rows only), its id a keyed hash of that key
(:func:`feed_item_id`). Comments and reactions on a trade item are deleted with its last underlying transaction
(:func:`purge_trade_threads`).

Pushes to group channels (``services.notifications``) and the weekly AI digest (``services.digests``) read through
here too: :func:`push_trade_candidates` / :func:`still_pushable` / :func:`push_trade_view` (only members who share both
``trades`` and ``push``), :func:`digest_week_facts` (what each member shares, stored by user id) and
:func:`digest_facts_view` (those facts filtered by the *current* memberships and toggles; ``pushing_only`` for what a
channel may show) and :func:`digest_summary_visible` (the AI summary only while everyone it was written from still
shares what they contributed).
"""

from __future__ import annotations

import base64
import binascii
import bisect
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import ApiError, unprocessable
from forliosa.crypto import keyed_id
from forliosa.datapolicy import labels, tagged
from forliosa.domain.fees import ZERO
from forliosa.domain.performance import benchmark_returns, simulate
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    BrokerAccount,
    Delegation,
    DelegationAccount,
    Group,
    GroupComment,
    GroupDigest,
    GroupMember,
    GroupReaction,
    GroupShareSetting,
    HoldingSnapshot,
    Transaction,
    User,
)
from forliosa.services.coverage import ymd
from forliosa.services.ledger_io import FxBook, load_ledger_input
from forliosa.services.portfolio import PortfolioState, compute_state
from forliosa.services.scope import ViewScope, set_view_scope
from forliosa.timeutil import (
    MARKET_CLOSE,
    TAIPEI,
    is_tw_trading_day,
    iso_taipei,
    last_tw_trading_day,
    market_close_dt,
    now_taipei,
    today_taipei,
    tw_trading_days,
)

SHARE_KEYS = ("returns", "holdings", "amounts", "trades", "trade_prices", "push")
DEFAULT_SHARE = {"returns": True, "holdings": False, "amounts": False, "trades": False, "trade_prices": False,
                 "push": False}
PERIODS = ("day", "month", "year")
BENCHMARKS = ("^TAIEXTR", "0050.TW")
FEED_DAYS = 90
FEED_SOURCES = ("manual", "import", "ai_draft")
FEED_SIDES = ("buy", "sell")
REACTION_EMOJI = ("👍", "🎉", "🔥", "😮", "😢", "👀")
LEFT_MEMBER = "已離開的成員"
DELETED_ACCOUNT = "已刪除的帳號"


# -- rounding ---------------------------------------------------------------------------------------------
def _round(value: Decimal | float, places: int) -> float:
    d = value if isinstance(value, Decimal) else Decimal(repr(value))
    f = float(d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))
    return 0.0 if f == 0 else f


def weight(value: Decimal | float) -> float:
    """Shared weights: 0.01."""
    return _round(value, 2)


def pct(value: Decimal | float | None) -> float | None:
    """Shared returns: 0.0001."""
    return None if value is None else _round(value, 4)


# -- delegations: read-only viewing ------------------------------------------------------------------------
def enter_view_as(db: Session, viewer: User, delegation_id: str) -> User:
    """Resolve the delegation behind ``X-Forliosa-View-As`` for ``viewer`` and limit this request to its current
    scope. Returns the owner, whose data the request then reads (as if the owner had only the delegated accounts)."""
    dlg = db.get(Delegation, delegation_id)
    owner = db.get(User, dlg.owner_id) if dlg is not None and dlg.viewer_id == viewer.id else None
    if dlg is None or owner is None:
        raise ApiError(403, "delegation_revoked", "這份唯讀授權已撤銷或不存在")
    ids = None if dlg.scope == "all" else frozenset(
        db.scalars(select(DelegationAccount.account_id).where(DelegationAccount.delegation_id == dlg.id)))
    set_view_scope(db, ViewScope(dlg.id, owner.id, viewer.id, ids))
    return owner


# -- group membership and share settings -------------------------------------------------------------------
@dataclass
class Member:
    user: User
    role: str
    joined_at: datetime
    share: GroupShareSetting | None

    @property
    def user_id(self) -> str:
        return self.user.id

    def shares(self, key: str) -> bool:
        return bool(self.share is not None and getattr(self.share, key))


def members_of(db: Session, group_id: str) -> list[Member]:
    """Current members in join order, with their share settings in this group."""
    rows = db.execute(
        select(GroupMember, User, GroupShareSetting)
        .join(User, User.id == GroupMember.user_id)
        .outerjoin(GroupShareSetting, (GroupShareSetting.group_id == GroupMember.group_id)
                   & (GroupShareSetting.user_id == GroupMember.user_id))
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at, GroupMember.user_id)
    ).all()
    return [Member(u, m.role, m.joined_at, s) for m, u, s in rows]


def share_out(s: GroupShareSetting | None) -> dict[str, bool]:
    if s is None:
        return dict(DEFAULT_SHARE)
    return {k: bool(getattr(s, k)) for k in SHARE_KEYS}


def identity(user: User) -> dict[str, Any]:
    return {"user_id": user.id, "display_name": user.display_name, "avatar_url": user.avatar_url}


# -- one member's numbers ------------------------------------------------------------------------------------
@dataclass
class PeriodWindow:
    end: date  # the latest close
    starts: dict[str, date]  # period -> base close (shared by every member and the benchmarks)
    clipped: bool  # a start was moved to the first archived day
    archive_since: date | None


def latest_close(md: MarketData, now: datetime | None = None) -> date:
    """The latest Taiwan close: today after 13:30 on a trading day, else the previous trading day — or the newest
    benchmark close when the data has not caught up yet."""
    now = (now or now_taipei()).astimezone(TAIPEI)
    today = now.date()
    clock = today if is_tw_trading_day(today) and now.time() >= MARKET_CLOSE else last_tw_trading_day(
        today - timedelta(days=1))
    lo = clock - timedelta(days=14)
    newest = [h.candles[-1].t for h in (md.index_history("^TAIEXTR", lo, clock), md.history("0050.TW", lo, clock))
              if h.candles]
    return min(clock, max(newest)) if newest else clock


def window_for(md: MarketData, starts: dict[str, date], end: date) -> PeriodWindow:
    """A window ending at the close of ``end``; under commercial a start before the first archived day is moved to
    that day (the archive is the only price source)."""
    starts = dict(starts)
    since = md.archive_since() if md.policy == "commercial" else None
    clipped = False
    if since is not None:
        for k, s in starts.items():
            if s < since:
                starts[k] = min(since, end)
                clipped = True
    return PeriodWindow(end, starts, clipped, since)


def period_window(md: MarketData, end: date | None = None) -> PeriodWindow:
    end = end or latest_close(md)
    return window_for(md, {
        "day": last_tw_trading_day(end - timedelta(days=1)),
        "month": last_tw_trading_day(end.replace(day=1) - timedelta(days=1)),
        "year": last_tw_trading_day(date(end.year, 1, 1) - timedelta(days=1)),
    }, end)


def _forward_filled(axis: list[date], closes: dict[date, Decimal]) -> dict[date, Decimal]:
    out: dict[date, Decimal] = {}
    known = sorted(closes)
    j = 0
    last: Decimal | None = None
    for d in axis:
        while j < len(known) and known[j] <= d:
            last = closes[known[j]]
            j += 1
        if last is not None:
            out[d] = last
    return out


def _axis(window: PeriodWindow) -> list[date]:
    base = min(window.starts.values())
    axis = tw_trading_days(base, window.end)
    if not axis or axis[0] != base:
        axis = sorted({base, *axis})
    return axis


def _window_return(daily: list[float], active: list[bool], axis: list[date], start: date, end: date) -> float | None:
    """TWR over (start, end] from daily returns on ``axis``; None when nothing was invested in the window."""
    if start >= end:
        return None
    s = bisect.bisect_right(axis, start) - 1
    e = bisect.bisect_right(axis, end) - 1
    if s < 0 or e <= s or not any(active[s + 1:e + 1]):
        return None
    acc = 1.0
    for r in daily[s + 1:e + 1]:
        acc *= 1.0 + r
    return acc - 1.0


def member_period_returns(db: Session, md: MarketData, user: User, window: PeriodWindow) -> dict[str, float | None]:
    return member_period_returns_ex(db, md, user, window)[0]


def member_period_returns_ex(db: Session, md: MarketData, user: User,
                             window: PeriodWindow) -> tuple[dict[str, float | None], bool]:
    """Time-weighted returns of all of ``user``'s accounts combined (TWD, closes) for every period of the window
    (leaderboard: day / month / year; weekly digest: week), from the window's common start dates. A member who starts
    holding during a period counts from the first day with holdings.

    Holdings with no close at all in the window (US stocks under commercial) are left out, the same rule as the
    ledger's 今日 and the performance page: the second value says so (product owner 2026-11-14 — before this the
    member's every period was None, so someone with a 複委託 account never got a rank). Any other gap → None."""
    none = dict.fromkeys(window.starts)
    inp = load_ledger_input(db, user)
    if inp.first_date is None or inp.first_date > window.end:
        return none, False
    axis = _axis(window)
    symbols = sorted({t.symbol for t in inp.effective_transactions() if t.symbol and t.type in (
        "buy", "sell", "stock_dividend", "split", "capital_reduction", "cash_dividend")}
        | {s.symbol for s in inp.snapshots})
    lookback = axis[0] - timedelta(days=14)
    closes = {s: _forward_filled(axis, {c.t: c.c for c in md.history(s, lookback, window.end).candles})
              for s in symbols}
    fx = FxBook.load(md, inp.first_date, window.end)
    txns, openings = inp.ledger_txns(fx), inp.openings(fx)

    def run(skip: set[str]):
        return simulate([t for t in txns if t.symbol not in skip], axis, lambda s, d: closes.get(s, {}).get(d),
                        lambda c, d: fx.rate(c, d), inp.method, [o for o in openings if o.symbol not in skip]).points

    points = run(set())
    excluded = False
    if any(p.unpriced for p in points):
        never = {s for s, c in closes.items() if not c}
        if not never:
            return none, False
        points, excluded = run(never), True
        if any(p.unpriced for p in points):
            return none, False
    daily = [p.daily_return for p in points]
    active = [False] + [points[i - 1].value + points[i].inflow > 0 for i in range(1, len(points))]
    return {k: _window_return(daily, active, axis, start, window.end) for k, start in window.starts.items()}, excluded


@dataclass
class Totals:
    market_value: Decimal
    cost: Decimal
    total_pnl: Decimal
    day_change: Decimal

    @property
    def total_return(self) -> Decimal | None:
        return self.total_pnl / self.cost if self.cost else None


def totals(state: PortfolioState) -> Totals:
    """Same arithmetic as ``PortfolioSummary`` (total P&L = unrealized + realized + dividends)."""
    mv = sum((r.market_value for r in state.rows), ZERO)
    cost = sum((r.cost_twd for r in state.rows), ZERO)
    realized = sum((e.pnl_twd for e in state.ledger.realized), ZERO)
    dividends = sum((e.net_twd for e in state.ledger.income), ZERO)
    return Totals(mv, cost, mv - cost + realized + dividends, sum((r.day_change for r in state.rows), ZERO))


def holdings_list(state: PortfolioState) -> list[dict[str, Any]]:
    """Symbol, name and weight only (no quantities, prices, amounts or accounts)."""
    total = sum((r.market_value for r in state.rows), ZERO)
    out = [{"symbol": r.symbol, "name": r.info.name if r.info else r.symbol,
            "weight": weight(r.market_value / total) if total else 0.0,
            "_industry": r.info.industry if r.info else None}
           for r in state.rows if r.quantity > 0]
    out.sort(key=lambda h: (-h["weight"], h["symbol"]))
    return out


class Projector:
    """Builds members' shared blocks for one request (each member's ledger is computed at most once)."""

    def __init__(self, db: Session, md: MarketData, window: PeriodWindow | None = None):
        self.db = db
        self.md = md
        self._states: dict[str, PortfolioState] = {}
        self._returns: dict[str, dict[str, float | None]] = {}
        self._excluded: dict[str, bool] = {}
        self._window = window  # default: the leaderboard's day / month / year window

    @property
    def window(self) -> PeriodWindow:
        if self._window is None:
            self._window = period_window(self.md)
        return self._window

    def state(self, user: User) -> PortfolioState:
        if user.id not in self._states:
            self._states[user.id] = compute_state(self.db, user, self.md)
        return self._states[user.id]

    def period_returns(self, user: User) -> dict[str, float | None]:
        if user.id not in self._returns:
            self._returns[user.id], self._excluded[user.id] = member_period_returns_ex(self.db, self.md, user,
                                                                                       self.window)
        return self._returns[user.id]

    def excludes_unpriced(self, user: User) -> bool:
        """The period returns leave out holdings without a close (US stocks under commercial)."""
        self.period_returns(user)
        return self._excluded.get(user.id, False)

    def returns_block(self, user: User) -> dict[str, float | None]:
        r = self.period_returns(user)
        return {"day": pct(r["day"]), "month": pct(r["month"]), "year": pct(r["year"]),
                "total": pct(totals(self.state(user)).total_return)}

    def holdings_block(self, user: User) -> list[dict[str, Any]]:
        return [{k: v for k, v in h.items() if not k.startswith("_")} for h in holdings_list(self.state(user))]

    def amounts_block(self, user: User) -> dict[str, float | None]:
        t = totals(self.state(user))
        return {"market_value": ser.money(t.market_value), "day_change": ser.money(t.day_change),
                "total_pnl": ser.money(t.total_pnl)}

    def is_demo(self, user: User) -> bool:
        return self.state(user).is_demo


# -- shared portfolio, holdings overlap, leaderboard ---------------------------------------------------------
def shared_portfolio(proj: Projector, member: Member) -> dict[str, Any]:
    """One member's ``SharedPortfolio``: identity, then only the blocks the member shares in this group."""
    out = identity(member.user)
    any_block = False
    if member.shares("returns"):
        out["returns"] = proj.returns_block(member.user)
        any_block = True
    if member.shares("holdings"):
        out["holdings"] = proj.holdings_block(member.user)
        any_block = True
    if member.shares("amounts"):
        out["amounts"] = proj.amounts_block(member.user)
        any_block = True
    if any_block:
        out["is_demo"] = proj.is_demo(member.user)
    return out


def group_holdings(proj: Projector, members: list[Member]) -> dict[str, Any]:
    sharing = [m for m in members if m.shares("holdings")]
    rows: list[dict[str, Any]] = []
    holders: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    industries: dict[str, set[str]] = defaultdict(set)
    is_demo = False
    for m in sharing:
        hs = holdings_list(proj.state(m.user))
        is_demo |= proj.is_demo(m.user)
        rows.append({**identity(m.user), "holdings": [{k: v for k, v in h.items() if not k.startswith("_")}
                                                      for h in hs]})
        for h in hs:
            holders[h["symbol"]].add(m.user_id)
            names[h["symbol"]] = h["name"]
            if h["_industry"]:
                industries[h["_industry"]].add(m.user_id)
    common = [{"symbol": s, "name": names[s], "holder_count": len(u)} for s, u in holders.items() if len(u) >= 2]
    common.sort(key=lambda c: (-c["holder_count"], c["symbol"]))
    inds = [{"industry": k, "holder_count": len(u)} for k, u in industries.items()]
    inds.sort(key=lambda c: (-c["holder_count"], c["industry"]))
    return {"members": rows, "common": common, "industries": inds, "is_demo": is_demo}


def _benchmark_period_returns(md: MarketData, window: PeriodWindow) -> tuple[list[dict[str, Any]], list[str], bool,
                                                                           list[str]]:
    axis = _axis(window)
    lookback = axis[0] - timedelta(days=14)
    rows: list[dict[str, Any]] = []
    sources: list[str] = []
    notes: list[str] = []
    is_demo = False
    for sym in BENCHMARKS:
        if sym.startswith("^"):
            hist = md.index_history(sym, lookback, window.end)
            kind = "index"
            divs: dict[date, Decimal] = {}
            splits: dict[date, Decimal] = {}
        else:
            hist = md.history(sym, lookback, window.end)
            kind = "price"
            divs = {e.ex_dividend_date: e.cash_dividend for e in md.dividends(sym).value if e.ex_dividend_date}
            splits = {e.date: e.ratio for e in md.corporate_events(sym) if e.kind == "split"}
        closes = _forward_filled(axis, {c.t: c.c for c in hist.candles})
        is_demo |= hist.is_demo
        if hist.source:
            sources.extend(tagged(hist.source, kind))
        daily = benchmark_returns(axis, closes.get, lambda d, divs=divs: divs.get(d, ZERO),
                                  lambda d, splits=splits: splits.get(d, Decimal(1)))
        priced = [d in closes for d in axis]
        out: dict[str, float | None] = {}
        for k, start in window.starts.items():
            s = bisect.bisect_right(axis, start) - 1
            ok = s >= 0 and priced[s] and priced[-1]
            out[k] = _window_return(daily, [True] * len(axis), axis, start, window.end) if ok else None
        rows.append({"symbol": sym, "name": md.benchmark_name(sym), "_returns": out})
        if md.policy == "commercial" and not closes:
            notes.append(f"沒有 {md.benchmark_name(sym)} 的資料，不能比較")
    return rows, sources, is_demo, notes


def rank_entries(entries: list[dict[str, Any]], ranked: bool) -> list[dict[str, Any]]:
    """Ranked: by ``return_pct`` (already rounded to 4 places) descending, ties share a rank (1, 1, 3), members
    without a value last with no rank. Unranked: join order, no ranks."""
    if not ranked:
        return [{**e, "rank": None} for e in entries]
    valued = sorted((e for e in entries if e["return_pct"] is not None), key=lambda e: -e["return_pct"])
    out = []
    for e in valued:
        out.append({**e, "rank": 1 + sum(1 for o in valued if o["return_pct"] > e["return_pct"])})
    out.extend({**e, "rank": None} for e in entries if e["return_pct"] is None)
    return out


def leaderboard(proj: Projector, group: Group, members: list[Member], me_id: str, period: str) -> dict[str, Any]:
    if period not in PERIODS:
        raise unprocessable(f"不支援的期間：{period}（可用 day、month、year）")
    window = proj.window
    is_demo = False
    entries = []
    for m in members:
        if not m.shares("returns"):
            continue
        r = proj.period_returns(m.user)
        is_demo |= proj.is_demo(m.user)
        mine = m.user_id == me_id
        # only my own row says what was left out: another member's US holdings are not for the group to see
        entries.append({**identity(m.user), "return_pct": pct(r[period]),
                        "total_return_pct": pct(totals(proj.state(m.user)).total_return), "is_me": mine,
                        "excludes_unpriced": mine and proj.excludes_unpriced(m.user)})
    bench, sources, bench_demo, notes = _benchmark_period_returns(proj.md, window)
    if window.clipped and window.archive_since is not None:
        notes.insert(0, f"資料從 {ymd(window.archive_since)} 開始，這段期間從 {ymd(window.starts[period])} 收盤起算")
    # the day's thread (``leaderboard:<date>``, the same for every period): a comment count and reaction tallies,
    # like feed items and digests — who reacted is not listed, and nothing counts the members who do not share
    target = f"leaderboard:{window.end.isoformat()}"
    counts, reactions = social_summary(proj.db, group.id, [target], me_id)
    return {
        "period": period,
        "date": window.end,
        "start_date": window.starts[period],
        "as_of": iso_taipei(market_close_dt(window.end)),
        "ranked": bool(group.ranking_enabled),
        "entries": rank_entries(entries, bool(group.ranking_enabled)),
        "benchmarks": [{"symbol": b["symbol"], "name": b["name"], "return_pct": pct(b["_returns"][period])}
                       for b in bench],
        "notes": notes,
        "sources": labels(["ledger", *sources]),
        "is_demo": is_demo or bench_demo,
        "comment_count": counts.get(target, 0),
        "reactions": reactions.get(target, []),
    }


# -- feed -----------------------------------------------------------------------------------------------------
def feed_item_id(user_id: str, trade_date: date, symbol: str, side: str) -> str:
    """Stable, unguessable id of one member's buys (or sells) of ``symbol`` on ``trade_date``."""
    return "gfi_" + keyed_id("feed-item-id", f"trade|{user_id}|{trade_date.isoformat()}|{symbol}|{side}")


def joined_item_id(group_id: str, user_id: str, joined_at: datetime) -> str:
    return "gfi_" + keyed_id("feed-item-id", f"joined|{group_id}|{user_id}|{joined_at.isoformat()}")


def snapshot_cutoffs(db: Session, user_ids: Iterable[str]) -> dict[str, date]:
    """Holdings-only accounts of these users → their snapshot date (like the ledger, transactions on or before it do
    not count)."""
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    return dict(db.execute(
        select(HoldingSnapshot.account_id, func.max(HoldingSnapshot.as_of))
        .join(BrokerAccount, BrokerAccount.id == HoldingSnapshot.account_id)
        .where(HoldingSnapshot.user_id.in_(ids), BrokerAccount.tracking_mode == "holdings")
        .group_by(HoldingSnapshot.account_id)).all())


def feed_eligible(t: Transaction, cutoffs: dict[str, date]) -> bool:
    """A transaction that can appear in a group feed (and so be pushed): a manual / imported / signed-draft buy or sell
    with a symbol, not covered by a holdings-only account's snapshot."""
    if t.type not in FEED_SIDES or t.source not in FEED_SOURCES or not t.symbol:
        return False
    as_of = cutoffs.get(t.account_id)
    return as_of is None or t.trade_date > as_of


def _feed_window(today: date | None = None) -> tuple[date, date]:
    today = today or today_taipei()
    return today - timedelta(days=FEED_DAYS), today


def _reaction_summary(db: Session, group_id: str, targets: list[str], me_id: str
                      ) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    if not targets:
        return {}, {}
    counts = dict(db.execute(
        select(GroupComment.target, func.count()).where(GroupComment.group_id == group_id,
                                                         GroupComment.target.in_(targets))
        .group_by(GroupComment.target)).all())
    rx: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for target, emoji, uid in db.execute(
            select(GroupReaction.target, GroupReaction.emoji, GroupReaction.user_id)
            .where(GroupReaction.group_id == group_id, GroupReaction.target.in_(targets))):
        cell = rx[target][emoji]
        cell[0] += 1
        cell[1] |= uid == me_id
    reactions = {t: [{"emoji": e, "count": rx[t][e][0], "mine": bool(rx[t][e][1])}
                     for e in REACTION_EMOJI if e in rx[t]] for t in rx}
    return counts, reactions


def social_summary(db: Session, group_id: str, targets: list[str], me_id: str
                   ) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    """Comment counts and reaction tallies of these (visible) targets."""
    return _reaction_summary(db, group_id, targets, me_id)


def reactions_for(db: Session, group_id: str, target: str, me_id: str) -> list[dict[str, Any]]:
    return _reaction_summary(db, group_id, [target], me_id)[1].get(target, [])


def feed_items(db: Session, md: MarketData, group: Group, members: list[Member], me_id: str,
               user_id: str | None = None, with_social: bool = True) -> list[dict[str, Any]]:
    """Every visible feed item of the group, newest first (trade date, then created time, then id)."""
    lo, hi = _feed_window()
    chosen = [m for m in members if user_id is None or m.user_id == user_id]
    sharing = {m.user_id: m for m in chosen if m.shares("trades")}
    items: list[tuple[tuple, dict[str, Any]]] = []
    if sharing:
        txns = db.scalars(select(Transaction).where(
            Transaction.user_id.in_(sorted(sharing)), Transaction.type.in_(FEED_SIDES),
            Transaction.source.in_(FEED_SOURCES), Transaction.symbol.is_not(None),
            Transaction.trade_date >= lo, Transaction.trade_date <= hi))
        cutoffs = snapshot_cutoffs(db, sharing)
        merged: dict[tuple[str, date, str, str], dict[str, Any]] = {}
        for t in txns:
            if not feed_eligible(t, cutoffs):
                continue
            key = (t.user_id, t.trade_date, t.symbol or "", t.type)
            cell = merged.setdefault(key, {"count": 0, "qty": ZERO, "value": ZERO, "currency": t.currency,
                                           "created_at": t.created_at})
            cell["count"] += 1
            cell["qty"] += t.quantity or ZERO
            cell["value"] += (t.quantity or ZERO) * (t.price or ZERO)
            cell["created_at"] = max(cell["created_at"], t.created_at)
        for (uid, d, sym, side), cell in merged.items():
            m = sharing[uid]
            info = md.instrument(sym)
            item: dict[str, Any] = {
                "id": feed_item_id(uid, d, sym, side), "type": "trade", **identity(m.user),
                "side": side, "symbol": sym, "name": info.name if info else sym, "trade_date": d,
                "count": cell["count"],
            }
            if m.shares("trade_prices") and cell["qty"] > 0:
                item["price"] = ser.price(cell["value"] / cell["qty"])
                item["currency"] = cell["currency"]
            item["created_at"] = iso_taipei(cell["created_at"])
            items.append(((d, cell["created_at"], item["id"]), item))
    for m in chosen:
        joined = m.joined_at.astimezone(TAIPEI).date()
        if lo <= joined <= hi:
            item = {"id": joined_item_id(group.id, m.user_id, m.joined_at), "type": "member_joined",
                    **identity(m.user), "created_at": iso_taipei(m.joined_at)}
            items.append(((joined, m.joined_at, item["id"]), item))
    items.sort(key=lambda kv: kv[0], reverse=True)
    out = []
    for key, item in items:
        item["_key"] = key
        out.append(item)
    if with_social:
        trade_targets = [f"trade:{i['id']}" for i in out if i["type"] == "trade"]
        counts, reactions = _reaction_summary(db, group.id, trade_targets, me_id)
        for i in out:
            if i["type"] == "trade":
                t = f"trade:{i['id']}"
                i["comment_count"] = counts.get(t, 0)
                i["reactions"] = reactions.get(t, [])
    return out


def _encode_cursor(key: tuple) -> str:
    d, created, item_id = key
    raw = f"{d.isoformat()}|{created.astimezone(TAIPEI).isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        d, created, item_id = raw.split("|", 2)
        return date.fromisoformat(d), datetime.fromisoformat(created), item_id
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise unprocessable("分頁游標無效") from exc


def feed_page(db: Session, md: MarketData, group: Group, members: list[Member], me_id: str, limit: int,
              cursor: str | None, user_id: str | None) -> dict[str, Any]:
    items = feed_items(db, md, group, members, me_id, user_id)
    if cursor:
        after = _decode_cursor(cursor)
        items = [i for i in items if i["_key"] < after]
    page = items[:limit]
    nxt = _encode_cursor(page[-1]["_key"]) if len(items) > limit else None
    return {"items": [{k: v for k, v in i.items() if k != "_key"} for i in page], "next_cursor": nxt}


def visible_trade_ids(db: Session, md: MarketData, group: Group, members: list[Member]) -> set[str]:
    return {i["id"] for i in feed_items(db, md, group, members, "", with_social=False) if i["type"] == "trade"}


def latest_activity(db: Session, md: MarketData, group: Group, members: list[Member]) -> datetime | None:
    """Newest visible feed item or comment on a visible target (nothing hidden moves it)."""
    items = feed_items(db, md, group, members, "", with_social=False)
    newest = [max(i["_key"][1] for i in items)] if items else []
    targets = [f"trade:{i['id']}" for i in items if i["type"] == "trade"]
    q = select(func.max(GroupComment.created_at)).where(GroupComment.group_id == group.id)
    ready = [f"digest:{d}" for d in db.scalars(select(GroupDigest.id).where(GroupDigest.group_id == group.id,
                                                                           GroupDigest.status == "ready"))]
    c = db.scalar(q.where(GroupComment.target.in_(targets + ready) | GroupComment.target.like("leaderboard:%")))
    if c is not None:
        newest.append(c)
    return max(newest) if newest else None


# -- comment targets -------------------------------------------------------------------------------------------
def target_visible(db: Session, md: MarketData, group: Group, members: list[Member], target: str) -> bool:
    """A comment / reaction target of this group that the current projection shows (else the caller answers 404)."""
    kind, _, ref = target.partition(":")
    if kind == "trade":
        return ref.startswith("gfi_") and ref in visible_trade_ids(db, md, group, members)
    if kind == "digest":
        d = db.get(GroupDigest, ref)
        return d is not None and d.group_id == group.id and d.status == "ready"
    if kind == "leaderboard":
        try:
            day = date.fromisoformat(ref)
        except ValueError:
            return False
        if day > today_taipei():
            return False
        if day >= group.created_at.astimezone(TAIPEI).date():
            return True
        # before the group was made: only the board it first showed — a group made on a weekend (or before the
        # close) shows the previous close, and that day's thread (comments and reactions under it) must work too
        return day >= latest_close(md, group.created_at)
    return False


# -- deleting a trade deletes its feed item's thread ---------------------------------------------------------
TradeKey = tuple[date, str, str]  # (trade_date, symbol, side)


def trade_keys(txns: Iterable[Transaction]) -> list[TradeKey]:
    """Feed keys of the transactions that can appear in a feed (call before they are deleted or changed)."""
    return [(t.trade_date, t.symbol, t.type) for t in txns
            if t.type in FEED_SIDES and t.source in FEED_SOURCES and t.symbol]


def purge_trade_threads(db: Session, user_id: str, keys: Iterable[TradeKey]) -> None:
    """Delete the comments and reactions (in every group) of feed items that no transaction backs any more."""
    for d, symbol, side in set(keys):
        left = db.scalar(select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user_id, Transaction.trade_date == d, Transaction.symbol == symbol,
            Transaction.type == side, Transaction.source.in_(FEED_SOURCES)))
        if left:
            continue
        target = f"trade:{feed_item_id(user_id, d, symbol, side)}"
        db.execute(delete(GroupComment).where(GroupComment.target == target))
        db.execute(delete(GroupReaction).where(GroupReaction.target == target))


# -- push to group channels (``services.notifications``) ------------------------------------------------------
PUSH_TRADE_DAYS = 3  # the trade date must be one of the last 3 calendar days (Taipei), today included
PUSH_DELAY = timedelta(minutes=15)


def push_start(member: Member, configured_at: datetime) -> datetime | None:
    """Trades created after this moment may go to a channel configured at ``configured_at``: after the channel was set
    up and after the member last turned on both ``push`` and ``trades``. None: the member does not push trades."""
    s = member.share
    if s is None or not (s.push and s.trades) or s.push_enabled_at is None or s.trades_enabled_at is None:
        return None
    return max(configured_at, s.push_enabled_at, s.trades_enabled_at)


def push_trade_dates(now: datetime) -> tuple[date, date]:
    today = now.astimezone(TAIPEI).date()
    return today - timedelta(days=PUSH_TRADE_DAYS - 1), today


def push_trade_candidates(db: Session, members: list[Member], now: datetime) -> list[tuple[Member, Transaction]]:
    """Feed-eligible trades of the members who currently share both ``trades`` and ``push`` here, with a trade date in
    the last 3 calendar days and created within that window."""
    pushing = {m.user_id: m for m in members if m.shares("push") and m.shares("trades")}
    if not pushing:
        return []
    lo, hi = push_trade_dates(now)
    txns = db.scalars(select(Transaction).where(
        Transaction.user_id.in_(sorted(pushing)), Transaction.type.in_(FEED_SIDES),
        Transaction.source.in_(FEED_SOURCES), Transaction.symbol.is_not(None),
        Transaction.trade_date >= lo, Transaction.trade_date <= hi,
        Transaction.created_at >= now - timedelta(days=PUSH_TRADE_DAYS + 1)).order_by(Transaction.created_at))
    cutoffs = snapshot_cutoffs(db, pushing)
    return [(pushing[t.user_id], t) for t in txns if feed_eligible(t, cutoffs)]


def still_pushable(db: Session, member: Member, txn: Transaction, configured_at: datetime, now: datetime) -> bool:
    """Re-checked right before sending: the member still pushes trades, the trade was created after the channel and
    the toggles were (last) turned on, it is still a feed trade and its date is still in the 3-day window."""
    start = push_start(member, configured_at)
    lo, hi = push_trade_dates(now)
    return (start is not None and txn.created_at > start and lo <= txn.trade_date <= hi
            and feed_eligible(txn, snapshot_cutoffs(db, [member.user_id])))


def push_trade_view(md: MarketData, member: Member, txns: list[Transaction]) -> dict[str, Any]:
    """What a channel may show of one member's buys (or sells) of one symbol on one day: name, side, symbol, date and
    count — plus the share-weighted average price only with ``trade_prices``. Never quantities, amounts, accounts,
    notes or fees."""
    first = txns[0]
    info = md.instrument(first.symbol or "")
    out: dict[str, Any] = {"display_name": member.user.display_name, "side": first.type, "symbol": first.symbol,
                           "name": info.name if info else first.symbol, "trade_date": first.trade_date,
                           "count": len(txns)}
    qty = sum((t.quantity or ZERO for t in txns), ZERO)
    if member.shares("trade_prices") and qty > 0:
        out["price"] = ser.price(sum(((t.quantity or ZERO) * (t.price or ZERO) for t in txns), ZERO) / qty)
        out["currency"] = first.currency
    return out


# -- weekly AI digest facts (``services.digests``) -----------------------------------------------------------------
def digest_week_facts(db: Session, md: MarketData, members: list[Member], week_start: date,
                      week_end: date) -> tuple[dict[str, Any], list[str]] | None:
    """One group's week (Monday–Friday, Taipei), computed from the projection: week returns of the members who share
    ``returns``, held symbols of those who share ``holdings``, trade counts of those who share ``trades``, and the
    benchmarks' week returns. Stored **by user_id**; :func:`digest_facts_view` filters them by the current memberships
    and toggles on every read. None when the week had no Taiwan trading day."""
    days = tw_trading_days(week_start, week_end)
    if not days:
        return None
    base = last_tw_trading_day(week_start - timedelta(days=1))
    window = window_for(md, {"week": base}, days[-1])
    proj = Projector(db, md, window)
    returns, holdings, trades = [], [], []
    symbols: dict[str, dict[str, Any]] = {}
    is_demo = False
    for m in members:
        if m.shares("returns"):
            returns.append({"user_id": m.user_id, "week_return_pct": pct(proj.period_returns(m.user)["week"])})
            is_demo |= proj.is_demo(m.user)
        if m.shares("holdings"):
            hs = holdings_list(proj.state(m.user))
            is_demo |= proj.is_demo(m.user)
            holdings.append({"user_id": m.user_id, "symbols": [h["symbol"] for h in hs]})
            for h in hs:
                symbols[h["symbol"]] = {"name": h["name"], "industry": h["_industry"]}
    sharing_trades = [m.user_id for m in members if m.shares("trades")]
    if sharing_trades:
        cutoffs = snapshot_cutoffs(db, sharing_trades)
        counts: dict[str, int] = dict.fromkeys(sharing_trades, 0)
        for t in db.scalars(select(Transaction).where(
                Transaction.user_id.in_(sharing_trades), Transaction.type.in_(FEED_SIDES),
                Transaction.source.in_(FEED_SOURCES), Transaction.trade_date >= week_start,
                Transaction.trade_date <= week_end)):
            if feed_eligible(t, cutoffs):
                counts[t.user_id] += 1
        trades = [{"user_id": uid, "count": counts[uid]} for uid in sharing_trades]
    bench, sources, bench_demo, notes = _benchmark_period_returns(md, window)
    if window.clipped and window.archive_since is not None:
        notes.insert(0, f"資料從 {ymd(window.archive_since)} 開始，本週從 {ymd(window.starts['week'])} 收盤起算")
    facts = {
        "v": 1, "base_date": window.starts["week"].isoformat(), "end_date": window.end.isoformat(),
        "trading_days": len(days), "returns": returns, "holdings": holdings, "symbols": symbols, "trades": trades,
        "benchmarks": [{"symbol": b["symbol"], "name": b["name"], "week_return_pct": pct(b["_returns"]["week"])}
                       for b in bench],
        "notes": notes, "is_demo": is_demo or bench_demo,
    }
    return facts, labels(["ledger", *sources])


def _allowed(by_id: dict[str, Member], user_id: str, key: str, pushing_only: bool) -> Member | None:
    m = by_id.get(user_id)
    if m is None or not m.shares(key) or (pushing_only and not m.shares("push")):
        return None
    return m


def digest_facts_view(facts: dict[str, Any], members: list[Member], pushing_only: bool = False) -> dict[str, Any]:
    """A stored digest's facts as members see them **now**: only current members who still share the matching toggle
    here (``pushing_only``: who also push — what a channel may show). Common holdings need two holders; industries
    count holders of any of their symbols; ``trades_count`` adds up members who share trades."""
    by_id = {m.user_id: m for m in members}
    returns = []
    for r in facts.get("returns", []):
        m = _allowed(by_id, r["user_id"], "returns", pushing_only)
        if m is not None:
            returns.append({"user_id": m.user_id, "display_name": m.user.display_name,
                            "week_return_pct": r["week_return_pct"]})
    holders: dict[str, set[str]] = defaultdict(set)
    industries: dict[str, set[str]] = defaultdict(set)
    info = facts.get("symbols", {})
    for h in facts.get("holdings", []):
        if _allowed(by_id, h["user_id"], "holdings", pushing_only) is None:
            continue
        for sym in h["symbols"]:
            holders[sym].add(h["user_id"])
            ind = (info.get(sym) or {}).get("industry")
            if ind:
                industries[ind].add(h["user_id"])
    common = [{"symbol": s, "name": (info.get(s) or {}).get("name") or s, "holder_count": len(u)}
              for s, u in holders.items() if len(u) >= 2]
    common.sort(key=lambda c: (-c["holder_count"], c["symbol"]))
    inds = [{"industry": k, "holder_count": len(u)} for k, u in industries.items()]
    inds.sort(key=lambda c: (-c["holder_count"], c["industry"]))
    trades_count = sum(t["count"] for t in facts.get("trades", [])
                       if _allowed(by_id, t["user_id"], "trades", pushing_only) is not None)
    return {"returns": returns, "benchmarks": list(facts.get("benchmarks", [])), "common_holdings": common,
            "industries": inds, "trades_count": trades_count}


DIGEST_PARTS = ("returns", "holdings", "trades")


def digest_prompt_contributors(facts: dict[str, Any], members: list[Member]) -> dict[str, list[str]]:
    """Whose stored facts a prompt built now uses, per toggle: the rows :func:`digest_facts_view` keeps. Recorded on
    the digest (``facts["prompt_contributors"]``) every time its prompt is built for a model call."""
    by_id = {m.user_id: m for m in members}
    return {key: [row["user_id"] for row in facts.get(key, [])
                  if _allowed(by_id, row["user_id"], key, False) is not None] for key in DIGEST_PARTS}


def digest_summary_visible(facts: dict[str, Any], members: list[Member], pushing_only: bool = False) -> bool:
    """The AI summary was written from its contributors' numbers (it may describe the range of returns, common
    holdings, how often people traded), so it may be shown only while each of them is still a member who shares the
    toggle they contributed under — in the app and, with ``pushing_only``, in a channel (they must also push).
    Contributors: ``facts["prompt_contributors"]``; every stored row when it is missing. Otherwise a member who leaves
    or turns a toggle off would still be readable in "returns between −1.20% and +3.40%"."""
    by_id = {m.user_id: m for m in members}
    contributors = facts.get("prompt_contributors")
    if not isinstance(contributors, dict):
        contributors = {key: [row["user_id"] for row in facts.get(key, [])] for key in DIGEST_PARTS}
    return all(_allowed(by_id, uid, key, pushing_only) is not None
               for key in DIGEST_PARTS for uid in contributors.get(key, []))


def digest_summary_pushable(facts: dict[str, Any], members: list[Member]) -> bool:
    """:func:`digest_summary_visible` for a channel: every contributor must also push."""
    return digest_summary_visible(facts, members, pushing_only=True)
