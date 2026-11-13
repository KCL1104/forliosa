"""ORM models. Every user-owned row carries ``user_id`` so queries can always be scoped."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forliosa.db import Base, Money, TZDateTime
from forliosa.timeutil import now_utc


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # Discord avatar (M5)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    # Public discussions: the nickname shown on public posts (never the display name or avatar). ``public_name_key``
    # is its NFKC + casefold form (``textsafe.name_key``), unique so names differing only in case or width collide.
    # ``public_name_changed_at``: when it was last chosen or changed (it can be changed again 7 days later).
    public_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    public_name_key: Mapped[str | None] = mapped_column(String(400), nullable=True, unique=True, index=True)
    public_name_changed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # HMAC-SHA256 of the cookie token
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    broker: Mapped[str] = mapped_column(String(100), default="")
    currency: Mapped[str] = mapped_column(String(3), default="TWD")
    fee_rate: Mapped[Decimal] = mapped_column(Money)
    fee_discount: Mapped[Decimal] = mapped_column(Money)
    min_fee: Mapped[Decimal] = mapped_column(Money)
    min_fee_odd_lot: Mapped[Decimal] = mapped_column(Money)
    tracking_mode: Mapped[str] = mapped_column(String(16), default="transactions")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_date", "user_id", "trade_date", "id"),
        Index("ix_transactions_account_date", "account_id", "trade_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[str] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"))
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(24))
    trade_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    fee: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    health_insurance: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3), default="TWD")
    is_day_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    # manual | import | ai_draft (a signed AI / recurring-plan draft) | auto (booked by the dividend sync) |
    # auto_edited (an automatic dividend the user edited; the sync never touches it again)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)

    account: Mapped[BrokerAccount] = relationship(back_populates="transactions")


class AutoDividendSkip(Base):
    """An automatically booked dividend the user deleted or edited (``forliosa.services.auto_dividends``):
    the sync never books (account, symbol, ex_date, kind) again. ``reason``: ``deleted`` | ``edited``."""

    __tablename__ = "auto_dividend_skips"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", "ex_date", "kind", name="uq_auto_dividend_skip"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    ex_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(8))  # cash | stock
    reason: Mapped[str] = mapped_column(String(16), default="deleted")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class HoldingSnapshot(Base):
    """Holdings-only accounts: the latest snapshot replaces the previous one (see PUT /holdings)."""

    __tablename__ = "holding_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_holding_snapshot_account_symbol"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Money)
    avg_cost: Mapped[Decimal] = mapped_column(Money)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class Instrument(Base):
    """Instrument master cache (refreshed by the worker from the market-data providers)."""

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(100))
    market: Mapped[str] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    industry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)


class PriceDaily(Base):
    """Unadjusted daily candles written by the worker (real sources only)."""

    __tablename__ = "prices_daily"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class FxRate(Base):
    __tablename__ = "fx_rates"

    pair: Mapped[str] = mapped_column(String(7), primary_key=True)  # "USDTWD"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(32))


# -- archive (official open data stored daily; see forliosa/archive.py) ----------------------------
class ValuationDaily(Base):
    """PER / PBR / dividend yield as published (TWSE BWIBBU_ALL, TPEx peratio_analysis, FinMind)."""

    __tablename__ = "valuation_daily"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    per: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    pbr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    dividend_yield: Mapped[Decimal | None] = mapped_column(Money, nullable=True)  # fraction
    source: Mapped[str] = mapped_column(String(32))


class ReferencePrice(Base):
    """Reference price (開盤競價基準) and limits for a trading day (TWSE TWT84U, TPEx Next*)."""

    __tablename__ = "reference_prices"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)  # the trading day it applies to
    reference_price: Mapped[Decimal] = mapped_column(Money)
    limit_up: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    limit_down: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class MarginDaily(Base):
    """Margin purchase / short sale balances in lots (張)."""

    __tablename__ = "margin_daily"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    margin_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margin_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class InstitutionalDaily(Base):
    """Net buy (+) / sell (−) of the three institutional investor groups, in shares."""

    __tablename__ = "institutional_daily"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    foreign_net: Mapped[int] = mapped_column(BigInteger)  # incl. foreign dealers
    trust_net: Mapped[int] = mapped_column(BigInteger)
    dealer_net: Mapped[int] = mapped_column(BigInteger)  # proprietary + hedging
    total_net: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))


class ForeignHoldingDaily(Base):
    __tablename__ = "foreign_holding_daily"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    pct: Mapped[Decimal] = mapped_column(Money)  # fraction of issued shares
    shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class ShareholdingDistribution(Base):
    """TDCC 集保戶股權分散表 (weekly; only the latest week is downloadable, so it is archived)."""

    __tablename__ = "shareholding_distribution"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    level: Mapped[int] = mapped_column(primary_key=True)  # 1–15 (16 adjustment, 17 total)
    holders: Mapped[int] = mapped_column(BigInteger)
    shares: Mapped[int] = mapped_column(BigInteger)
    pct: Mapped[Decimal] = mapped_column(Money)  # fraction
    source: Mapped[str] = mapped_column(String(32))


class MarketEvent(Base):
    """Dated announcements: ex-dividend notices, material information, attention / disposition lists,
    shareholder meetings. ``key`` makes re-archiving the same announcement idempotent."""

    __tablename__ = "market_events"
    __table_args__ = (
        UniqueConstraint("key", name="uq_market_events_key"),
        Index("ix_market_events_symbol_date", "symbol", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(20))
    date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    type: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class FinancialReport(Base):
    """Latest-quarter statements from the OpenAPI (t187ap06 income YTD, t187ap07 balance, t187ap17)."""

    __tablename__ = "financial_reports"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    period: Mapped[str] = mapped_column(String(8), primary_key=True)  # "2026Q3"
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # income_ytd | balance | margins
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class IntradayPoint(Base):
    """Intraday quote samples for symbols someone holds or watches (worker, 30–60 s polling)."""

    __tablename__ = "intraday_points"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    t: Mapped[str] = mapped_column(String(5), primary_key=True)  # "09:01" Taipei minute
    price: Mapped[Decimal] = mapped_column(Money)
    cum_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # shares, accumulated
    source: Mapped[str] = mapped_column(String(32))


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class MarketHoliday(Base):
    """TWSE holidaySchedule (official market calendar of the current year, archived by forliosa.archive).

    The schedule also lists trading-day markers (「國曆新年開始交易日」「農曆春節前最後交易日」): those rows
    have ``is_trading_day = True``. Years present here replace the built-in holiday list in ``timeutil``.
    """

    __tablename__ = "market_holidays"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    is_trading_day: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32))


class RecurringPlan(Base):
    """定期定額: buy ``amount`` TWD of ``symbol`` on each of ``days_of_month`` (1–28; the debit moves to the
    next trading day). Plans never create transactions by themselves: ``POST /recurring/{id}/draft`` returns
    a draft the user signs."""

    __tablename__ = "recurring_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Money)  # TWD per debit
    days_of_month: Mapped[list] = mapped_column(JSON, default=list)  # sorted ints 1–28
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)


# -- AI (M4): conversations, drafts, usage, shared "why" cache ----------------------------------------
class AiThread(Base):
    """One AI conversation. ``model`` is fixed when the thread starts (thinking blocks are bound to it), and so is
    ``key_slot`` (the API key slot, i.e. workspace, every turn uses: prompt caches, thinking blocks and web-search
    ``encrypted_content`` belong to it; the key itself is never stored). When the thread moves to another slot,
    the history is continued from plain-text recap messages starting at ``context_from_seq``."""

    __tablename__ = "ai_threads"
    __table_args__ = (Index("ix_ai_threads_user_updated", "user_id", "updated_at"),
                      Index("ix_ai_threads_updated", "updated_at"))

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="")
    model: Mapped[str] = mapped_column(String(64))
    context_tokens: Mapped[int] = mapped_column(BigInteger, default=0)  # prompt size of the latest call
    key_slot: Mapped[int | None] = mapped_column(nullable=True)  # None: not pinned yet (new or pre-0005 thread)
    context_from_seq: Mapped[int] = mapped_column(default=0, server_default="0")  # replay ai_messages.seq >= this
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class AiMessage(Base):
    """One Messages-API message of a thread, stored exactly as sent / received (content blocks incl. thinking
    signatures and web-search ``encrypted_content``) so the conversation can be replayed append-only.
    ``in_context = False`` rows (failed or refused turns) are shown in the history but never sent again."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        Index("ix_ai_messages_thread_seq", "thread_id", "seq"),
        Index("ix_ai_messages_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("ai_threads.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    turn_id: Mapped[str] = mapped_column(String(32))
    seq: Mapped[int] = mapped_column()
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[list | str] = mapped_column(JSON)
    in_context: Mapped[bool] = mapped_column(Boolean, default=True)
    is_user_input: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text, default="")  # display text
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # citations, drafts, tools, error
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class AiDraft(Base):
    """A transaction drafted by the AI. Never written to the ledger by the AI: the user signs it in the UI,
    which calls ``POST /transactions`` with ``source: "ai_draft"``."""

    __tablename__ = "ai_drafts"
    __table_args__ = (Index("ix_ai_drafts_updated", "updated_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str | None] = mapped_column(ForeignKey("ai_threads.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | signed | discarded
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # TransactionIn body
    preview: Mapped[dict] = mapped_column(JSON, default=dict)  # TradePreview
    instrument: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    transaction_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class AiUsage(Base):
    """One model call: tokens, server-tool requests, the key slot and the estimated cost (USD). Kept for
    accounting after the thread is deleted (retention); never holds message content."""

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_user_created", "user_id", "created_at"),
                      Index("ix_ai_usage_slot_created", "key_slot", "created_at"))

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feature: Mapped[str] = mapped_column(String(16))  # chat | why | smoke
    model: Mapped[str] = mapped_column(String(64))
    key_slot: Mapped[int | None] = mapped_column(nullable=True)  # n of CLAUDE_API_KEY_<n> (0 = ANTHROPIC_API_KEY)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_creation_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    web_search_requests: Mapped[int] = mapped_column(default=0)
    web_fetch_requests: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    stop_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class AiWhyCache(Base):
    """AI one-sentence "why did it move" per symbol per trading day, shared by every user."""

    __tablename__ = "ai_why_cache"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))  # ok | empty | failed
    text: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class AiAnalystViews(Base):
    """Third-party ratings / target prices found by AI web search (``forliosa.ai.analyst``): one shared entry per
    symbol per Taiwan trading day, deleted ``expires_at`` (24 h after creation). Only the verified items of one
    answer are kept — no history, no aggregates."""

    __tablename__ = "ai_analyst_views"
    __table_args__ = (Index("ix_ai_analyst_views_expires", "expires_at"),)

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    trading_day: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))  # pending | ready | unavailable
    items: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(64), default="")
    generation_id: Mapped[str] = mapped_column(String(32))  # ai_usage.thread_id of this generation's calls
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)


class FundProfile(Base):
    """ETF / fund basics from TWSE t187ap47_L 基金基本資料彙總表 (stored now, exposed later).

    Only fund facts are kept (type, tracked index, dates, units, custodian); the managers' and officers'
    names, phone numbers and addresses in the dataset are personal data and are not stored.
    """

    __tablename__ = "fund_profiles"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date)  # 出表日期
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


# -- open-data additions (2026-11-12, docs/research/open-data-inventory.md) ------------------------------
class IndexDaily(Base):
    """Index closes: TWSE MI_INDEX (all indices incl. 發行量加權股價報酬指數) and MFI94U (current month),
    TPEx tpex_index (OHLC) and tpex_reward_index (櫃買指數, 櫃買報酬指數). Keyed by the published index name."""

    __tablename__ = "index_daily"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    market: Mapped[str] = mapped_column(String(8))  # TWSE | TPEX
    open: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    close: Mapped[Decimal] = mapped_column(Money)
    change: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    change_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)  # fraction
    source: Mapped[str] = mapped_column(String(32))


class DividendResolution(Base):
    """TWSE t187ap45_L 上市公司股利分派情形: dividends resolved by the board / confirmed by the shareholders'
    meeting, with the cash split by source (earnings, legal reserve, capital surplus). NT$ per share."""

    __tablename__ = "dividend_resolutions"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)  # 股利所屬期間 start
    seq: Mapped[int] = mapped_column(primary_key=True)  # 期別
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    dividend_year: Mapped[int] = mapped_column()  # 股利年度 (Gregorian)
    period: Mapped[str] = mapped_column(String(8))  # "2026Q3" | "2026H1" | "2025"
    progress: Mapped[str] = mapped_column(String(80))  # 決議（擬議）進度
    board_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    meeting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cash_earnings: Mapped[Decimal] = mapped_column(Money)
    cash_legal_reserve: Mapped[Decimal] = mapped_column(Money)
    cash_capital_surplus: Mapped[Decimal] = mapped_column(Money)
    stock_earnings: Mapped[Decimal] = mapped_column(Money)
    stock_legal_reserve: Mapped[Decimal] = mapped_column(Money)
    stock_capital_surplus: Mapped[Decimal] = mapped_column(Money)
    cash_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # NT$
    stock_total_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published: Mapped[date] = mapped_column(Date)  # 出表日期
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class CompanyProfile(Base):
    """TWSE t187ap03_L / TPEx mopsfin_t187ap03_O 公司基本資料 (latest only: every run overwrites the row, so no
    history is kept).

    ``values`` holds the company facts of the 「關於」 section (product owner 2026-11-12, decision 6): name, short and
    English short name, ``hq`` (縣市 derived from the address; the address is not kept), ``registered_in`` (KY),
    ``website``, ``auditor`` (firm), ``transfer_agent`` (name), paid-in capital, incorporation date — and the
    ``chairman`` / ``president`` (董事長、總經理) exactly as published. Those two names are shown with their source
    only on the stock page: they never go into AI prompts or AI tool outputs and are never joined with board holdings
    or pledges (``board_links`` keeps company ↔ company rows only). Spokespeople, CPAs, phones, fax, e-mail and the
    tax number are not stored. (Lawyer check before charging users: docs/research/news-and-external-sources.md §9.)
    """

    __tablename__ = "company_profiles"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date)  # 出表日期
    industry_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    listed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # issued common shares
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class ExRightsResult(Base):
    """TPEx tpex_exright_daily 除權除息計算結果: the official reference price and limits on an ex-date."""

    __tablename__ = "ex_rights_results"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)  # ex-date (the day the reference applies to)
    kind: Mapped[str] = mapped_column(String(8))  # 除權 | 除息 | 除權息
    prev_close: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    ex_quote: Mapped[Decimal | None] = mapped_column(Money, nullable=True)  # theoretical, unrounded
    reference_price: Mapped[Decimal] = mapped_column(Money)  # 開始交易基準價
    limit_up: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    limit_down: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    cash_dividend: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    stock_dividend: Mapped[Decimal | None] = mapped_column(Money, nullable=True)  # 權值
    source: Mapped[str] = mapped_column(String(32))


class DatasetStatus(Base):
    """Newest data date the archive saw per dataset (``datapolicy`` keys): ``/meta/attributions`` shows it."""

    __tablename__ = "dataset_status"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rows: Mapped[int] = mapped_column(default=0)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


# -- TAIFEX OpenAPI (open-data-inventory §12; dates are Gregorian YYYYMMDD upstream) ------------------------
class TaifexFuturesDaily(Base):
    """DailyMarketReportFut. ``session`` 'regular' (一般) or 'after_hours' (盤後): the after-hours row dated D
    is the night session that opened at 15:00 on the previous trading day and closed at 05:00 on D."""

    __tablename__ = "taifex_futures_daily"
    __table_args__ = (Index("ix_taifex_futures_contract_date", "contract", "trade_date"),)

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    session: Mapped[str] = mapped_column(String(12), primary_key=True)
    contract: Mapped[str] = mapped_column(String(12), primary_key=True)
    contract_month: Mapped[str] = mapped_column(String(24), primary_key=True)  # 202611, 202611W2, 202611/202612
    open: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    last: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    change: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    change_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)  # fraction
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    settlement_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    best_bid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    best_ask: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    hist_high: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    hist_low: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    halted: Mapped[str] = mapped_column(String(16), default="")
    spread_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class TaifexOptionsDaily(Base):
    """DailyMarketReportOpt: index options (TXO, TEO, TFO) in full, other contracts' two nearest expiries."""

    __tablename__ = "taifex_options_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    session: Mapped[str] = mapped_column(String(12), primary_key=True)
    contract: Mapped[str] = mapped_column(String(12), primary_key=True)
    contract_month: Mapped[str] = mapped_column(String(24), primary_key=True)
    strike: Mapped[Decimal] = mapped_column(Money, primary_key=True)
    call_put: Mapped[str] = mapped_column(String(1), primary_key=True)  # C | P
    open: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    close: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    settlement_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    best_bid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    best_ask: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class TaifexInstitutional(Base):
    """三大法人 by the date. ``scope``: all (總表) | fut_opt (期貨／選擇權二類; contract_name 期貨 or 選擇權) |
    futures | options (各契約) | calls_puts (買賣權分計, call_put C/P). Values in thousand NT$ (總表 is published
    in millions and converted); volumes and open interest in contracts (口)."""

    __tablename__ = "taifex_institutional"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    scope: Mapped[str] = mapped_column(String(12), primary_key=True)
    contract_name: Mapped[str] = mapped_column(String(40), primary_key=True)
    call_put: Mapped[str] = mapped_column(String(1), primary_key=True)  # "" | C | P
    investor: Mapped[str] = mapped_column(String(12), primary_key=True)  # 自營商 | 投信 | 外資及陸資
    contract_code: Mapped[str | None] = mapped_column(String(12), nullable=True)  # TX, TXO … (contract map)
    long_vol: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    long_value_k: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_vol: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_value_k: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_vol: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_value_k: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_long: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_long_value_k: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_short: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_short_value_k: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_net_value_k: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class TaifexLargeTraders(Base):
    """OpenInterestOfLargeTraders{Futures,Options}. ``settlement_month`` keeps the published value: 999912 =
    all months combined, 666666 = weekly contracts combined. ``trader_type`` 0 = all large traders, 1 = of
    which specific legal entities (特定法人)."""

    __tablename__ = "taifex_large_traders"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)  # futures | options
    contract: Mapped[str] = mapped_column(String(12), primary_key=True)
    call_put: Mapped[str] = mapped_column(String(1), primary_key=True)  # "" | C | P
    settlement_month: Mapped[str] = mapped_column(String(12), primary_key=True)
    trader_type: Mapped[int] = mapped_column(primary_key=True)
    contract_name: Mapped[str] = mapped_column(String(60), default="")
    top5_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top5_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top10_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top10_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    market_oi: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class TaifexPutCallRatio(Base):
    """PutCallRatio (the response carries about a month of days: upserted)."""

    __tablename__ = "taifex_put_call_ratio"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    put_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    call_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    volume_ratio: Mapped[Decimal | None] = mapped_column(Money, nullable=True)  # fraction (1.0708 = 107.08%)
    put_oi: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    call_oi: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_ratio: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class TaifexContractMap(Base):
    """Chinese product names (三大法人, 保證金, 大額交易人) -> contract codes (行情): 臺股期貨 -> TX."""

    __tablename__ = "taifex_contract_map"

    name_zh: Mapped[str] = mapped_column(String(60), primary_key=True)
    contract_code: Mapped[str | None] = mapped_column(String(12), nullable=True)  # None: an aggregate (股票期貨)
    kind: Mapped[str] = mapped_column(String(8))  # futures | options
    source: Mapped[str] = mapped_column(String(32))


class TaifexFinalSettlement(Base):
    """FinalSettlementPrice (weekly upsert; ``contract`` as published, e.g. "TX/MTX/TMF")."""

    __tablename__ = "taifex_final_settlement"

    contract: Mapped[str] = mapped_column(String(24), primary_key=True)
    delivery_month: Mapped[str] = mapped_column(String(12), primary_key=True)
    settlement_day: Mapped[date] = mapped_column(Date)
    contract_name: Mapped[str] = mapped_column(String(80), default="")
    price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class TaifexMargin(Base):
    """保證金一覽表 (index / stock / ETF). A row is added only when a contract's margins change; ``date`` is the
    published Date of the first response that carried the new values."""

    __tablename__ = "taifex_margins"

    kind: Mapped[str] = mapped_column(String(8), primary_key=True)  # index | stock | etf
    contract: Mapped[str] = mapped_column(String(60), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    underlying_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    group_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_rate: Mapped[bool] = mapped_column(Boolean, default=False)  # stock futures: fractions of contract value
    clearing: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    maintenance: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    initial: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class TaifexUnderlying(Base):
    """SSFLists / SSOLists: which stocks and ETFs have single-stock futures / options (weekly)."""

    __tablename__ = "taifex_underlyings"

    kind: Mapped[str] = mapped_column(String(4), primary_key=True)  # SSF | SSO
    contract: Mapped[str] = mapped_column(String(12), primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(12), index=True)
    stock_name: Mapped[str] = mapped_column(String(60), default="")
    type: Mapped[str] = mapped_column(String(40), default="")
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))


# -- SEC EDGAR (US fundamentals and filings; forliosa.services.sec) -------------------------------------
class SecTicker(Base):
    """www.sec.gov/files/company_tickers.json: ticker -> CIK (SEC's ticker spelling, e.g. ``BRK-B``)."""

    __tablename__ = "sec_tickers"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    cik: Mapped[int] = mapped_column(BigInteger, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class SecCompany(Base):
    """One SEC registrant: the trimmed XBRL company facts (only the us-gaap tags Forliosa shows, one value per
    period) and when its companyfacts / submissions were last fetched. ``facts`` is
    ``{"v": 2, "tags": {tag: {unit: [[start, end, value, fy, fp, filed], …]}}, "splits": [[first filed, ratio], …]}``
    (see ``marketdata.sec``; facts of an older ``v`` are fetched again)."""

    __tablename__ = "sec_companies"

    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(200), default="")
    fiscal_year_end: Mapped[str | None] = mapped_column(String(4), nullable=True)  # "0926" (MMDD)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # dei cover page
    shares_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    facts_fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    filings_fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="sec-edgar")
    # Company facts from the submissions JSON (「關於」): {industry, sic, city, state, country, exchanges,
    # former_names: [{name, from, to}]} — no people, phones or EIN.
    profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SecFiling(Base):
    """8-K / 10-Q / 10-K (and amendments) from data.sec.gov/submissions: only the index fields and the link."""

    __tablename__ = "sec_filings"
    __table_args__ = (Index("ix_sec_filings_cik_date", "cik", "filing_date"),)

    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    accession: Mapped[str] = mapped_column(String(24), primary_key=True)  # 0000320193-26-000026
    form: Mapped[str] = mapped_column(String(12))
    filing_date: Mapped[date] = mapped_column(Date)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    items: Mapped[str] = mapped_column(String(120), default="")  # 8-K items, e.g. "2.02,9.01"
    primary_document: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(32), default="sec-edgar")
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


# -- M5: login identities, delegations, groups (docs/api-contract.md 「分享（M5）」) ------------------------------
class UserIdentity(Base):
    """An external login linked to a user: ``provider`` = ``discord``, ``subject`` = the Discord user id. One Discord
    id per user; the provider's access / refresh tokens are never stored (used once to read the profile)."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_identity_subject"),
        UniqueConstraint("user_id", "provider", name="uq_user_identity_user_provider"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)  # as last reported by the provider
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    last_login_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class Delegation(Base):
    """One-to-one read-only access: ``viewer`` may view ``owner``'s ledger (``scope`` all | accounts)."""

    __tablename__ = "delegations"
    __table_args__ = (UniqueConstraint("owner_id", "viewer_id", name="uq_delegation_owner_viewer"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    viewer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(8), default="all")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)


class DelegationAccount(Base):
    """The accounts of a ``scope = accounts`` delegation; deleting the account removes it from the scope."""

    __tablename__ = "delegation_accounts"

    delegation_id: Mapped[str] = mapped_column(ForeignKey("delegations.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"), primary_key=True,
                                            index=True)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    ranking_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)


class GroupMember(Base):
    """``role``: owner (exactly one) | admin | member. Join order = ``joined_at``."""

    __tablename__ = "group_members"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(8), default="member")
    joined_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class GroupShareSetting(Base):
    """What one member shares in one group. Deleted with the membership (leaving, removal); chosen again on rejoin.
    ``trades_enabled_at`` / ``push_enabled_at``: when ``trades`` / ``push`` were last turned on (push only sends
    trades created after both)."""

    __tablename__ = "group_share_settings"
    __table_args__ = (
        ForeignKeyConstraint(["group_id", "user_id"], ["group_members.group_id", "group_members.user_id"],
                             ondelete="CASCADE", name="fk_group_share_member"),
    )

    group_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    returns: Mapped[bool] = mapped_column(Boolean, default=True)
    holdings: Mapped[bool] = mapped_column(Boolean, default=False)
    amounts: Mapped[bool] = mapped_column(Boolean, default=False)
    trades: Mapped[bool] = mapped_column(Boolean, default=False)
    trade_prices: Mapped[bool] = mapped_column(Boolean, default=False)
    push: Mapped[bool] = mapped_column(Boolean, default=False)
    trades_enabled_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    push_enabled_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)


class GroupInvite(Base):
    """An invite link. Only the SHA-256 of the random token (256 bits) is stored; the URL is shown once."""

    __tablename__ = "group_invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    multi_use: Mapped[bool] = mapped_column(Boolean, default=False)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class GroupComment(Base):
    """A comment on ``target`` (``trade:<feed item id>`` | ``digest:<id>`` | ``leaderboard:<YYYY-MM-DD>``).
    ``user_id`` is null once the author's account is deleted."""

    __tablename__ = "group_comments"
    __table_args__ = (Index("ix_group_comments_target", "group_id", "target", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    target: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class GroupReaction(Base):
    __tablename__ = "group_reactions"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    target: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class GroupDigest(Base):
    """群組 AI 週報. ``facts`` are stored by ``user_id`` and filtered by the current memberships and share settings on
    every read. ``status``: pending | ready | failed."""

    __tablename__ = "group_digests"
    __table_args__ = (UniqueConstraint("group_id", "week_start", name="uq_group_digest_week"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    week_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class GroupChannel(Base):
    """A group's push channel (``kind`` discord | telegram; one each). The Discord webhook URL is stored encrypted
    (``crypto.encrypt_secret``); responses only show ``webhook_hint`` (its last 4 characters). ``status`` active |
    disabled (``disabled_reason``) | removed (the owner removed it: no URL or chat id; the row stays so a later set-up
    counts as a new destination). ``configured_at``: trades created before it are never pushed."""

    __tablename__ = "group_channels"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    status: Mapped[str] = mapped_column(String(10), default="active")
    disabled_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    webhook_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notify_trades: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    configured_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    configured_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)


class NotificationOutbox(Base):
    """Pending pushes to group channels. A trade row references its transaction (deleted with it, so a trade deleted
    within the 15-minute delay is never sent); everything sent is re-checked against the share settings at send
    time. ``status``: pending | sent | failed | cancelled; retried with exponential backoff up to 5 attempts."""

    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_notification_outbox_due", "status", "not_before"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    channel_kind: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(10))  # trade | digest
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"),
                                                       nullable=True, index=True)
    digest_id: Mapped[str | None] = mapped_column(ForeignKey("group_digests.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    not_before: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class TelegramLinkCode(Base):
    """A one-time ``/link <code>`` code (10 minutes) that binds a Telegram group chat to a Forliosa group; only the
    SHA-256 of the code is stored."""

    __tablename__ = "telegram_link_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)

# -- News (個股頁「新聞報導」; forliosa.news) -------------------------------------------------------------------
class NewsArticle(Base):
    """One media headline about one symbol: **metadata only** — the headline, outlet, time and link. Never the
    article text, a description / og:description or an image (docs/research/news-and-external-sources.md §1).
    Deleted ``NEWS_RETENTION_DAYS`` (30) after publication."""

    __tablename__ = "news_articles"
    __table_args__ = (UniqueConstraint("symbol", "url_key", name="uq_news_articles_symbol_url"),
                      Index("ix_news_articles_symbol_published", "symbol", "published_at"),
                      Index("ix_news_articles_published", "published_at"))

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20))
    url_key: Mapped[str] = mapped_column(String(64))  # sha256 of the normalised URL
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)  # normalised headline
    outlet: Mapped[str] = mapped_column(String(100))  # 聯合新聞網; unknown outlets: their domain
    domain: Mapped[str] = mapped_column(String(253))
    published_at: Mapped[datetime] = mapped_column(TZDateTime)
    date_only: Mapped[bool] = mapped_column(Boolean, default=False)  # the source gave a date without a time
    source: Mapped[str] = mapped_column(String(16))  # gdelt | ai_search | searxng | yahoo_rss
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class NewsBlockedDomain(Base):
    """Takedown blocklist (下架處理): an outlet that asked to be removed. Its headlines are deleted, never stored
    again and never shown (subdomains included). ``python -m forliosa.news block|unblock|blocked``."""

    __tablename__ = "news_blocked_domains"

    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class NewsTrackedView(Base):
    """When a symbol's news was last viewed: only the symbol and the time, never who viewed it. Symbols viewed in
    the last ``NEWS_VIEW_DAYS`` days are refreshed by the news worker job."""

    __tablename__ = "news_tracked_views"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_viewed_at: Mapped[datetime] = mapped_column(TZDateTime)


class NewsFetchState(Base):
    """Per source and symbol: the last attempt / success and its outcome. ``symbol = "*"`` is the source as a
    whole (``backoff_until`` after a 429 or a block: the source is not asked again before then)."""

    __tablename__ = "news_fetch_state"

    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(24), default="")  # ok | empty | error | rate_limited | blocked
    items: Mapped[int] = mapped_column(default=0)
    failures: Mapped[int] = mapped_column(default=0)
    backoff_until: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


# -- Stock page 2026-11-12 (decisions 4, 6, 7, 8): related stocks, company facts and description ------------------
class BoardLink(Base):
    """Company ↔ company relation from TWSE t187ap11_L / TPEx mopsfin_t187ap11_O 董監事持股餘額明細 (monthly):
    ``holder_symbol`` (a listed / OTC company, matched by its exact full name) is a director (法人董事) or major
    shareholder (大股東, > 10 %) of ``symbol``. Natural persons' rows are dropped while parsing: no person's name,
    holding or pledge is ever stored. ``period`` is 資料年月 (about six weeks behind)."""

    __tablename__ = "board_links"
    __table_args__ = (Index("ix_board_links_holder", "holder_symbol", "period"),)

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    holder_symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), primary_key=True)  # "2026-09"
    roles: Mapped[str] = mapped_column(String(100))  # 「董事長、董事、大股東」
    shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # the holder company's current shares
    data_date: Mapped[date] = mapped_column(Date)  # 出表日期
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class IndexConstituent(Base):
    """Published index constituent lists (TPEx tpex50_constituents 富櫃五十指數, daily)."""

    __tablename__ = "index_constituents"

    index_code: Mapped[str] = mapped_column(String(16), primary_key=True)  # "TPEX50"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))


class HolderCountMonthly(Base):
    """TDCC 2-22 (TWSE) / 2-23 (TPEx) 集保股東戶數 per stock and ETF, month end (only the latest month is published,
    so it is archived monthly)."""

    __tablename__ = "holder_counts_monthly"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), primary_key=True)  # "2026-10"
    holders: Mapped[int] = mapped_column(BigInteger)
    custody_k_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 本月底保管千股數
    issued_k_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 發行千股數
    source: Mapped[str] = mapped_column(String(32))


class ForeignHoldingTop20(Base):
    """TWSE /fund/MI_QFIIS_sort_20 集中市場外資及陸資持股前 20 名 (daily; the only per-stock foreign holding TWSE
    publishes as open data). The dataset has no date: rows are stamped with the trading day they belong to."""

    __tablename__ = "foreign_holding_top20"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    rank: Mapped[int] = mapped_column()
    pct: Mapped[Decimal] = mapped_column(Money)  # fraction of issued shares held by foreign investors
    shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    issued_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    available_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    limit_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class EsgProductOutput(Base):
    """t187ap46_L_14 / t187ap46_O_14 ESG 揭露「依產品類別之產品產量」 (latest report year): one of the official facts
    the AI-written company description may use when there is no Wikipedia article."""

    __tablename__ = "esg_product_output"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    year: Mapped[int] = mapped_column()  # 報告年度 (Gregorian)
    text: Mapped[str] = mapped_column(Text)
    data_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))


class CompanyDescription(Base):
    """The 「關於」 description (decision 7): a zh.wikipedia excerpt (``kind = "wikipedia"``, CC BY-SA 4.0: title,
    link and revision kept, the text never rewritten by AI; refreshed monthly) or, without an article, an AI-written
    2–3 sentence description from official facts only (``kind = "ai"``, regenerated only when ``facts_key`` — a hash
    of those facts — changes; ``sources``: the datasets those facts came from). ``kind = "none"``: looked up, nothing
    to show. A model reply that was refused (too long, a name, cut off) or an API error is remembered with the facts
    it was for (``ai_failed_key``, ``ai_failures``, ``ai_attempted_at``): the same facts are retried only after a
    back-off (24 h, doubling)."""

    __tablename__ = "company_descriptions"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))  # wikipedia | ai | none
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)  # Wikipedia article title
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wikidata_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    facts_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)  # dataset keys behind an AI description
    ai_failed_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # facts of the last failed attempt
    ai_failures: Mapped[int] = mapped_column(default=0, server_default="0")  # in a row, for ai_failed_key
    ai_attempted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)  # last AI call
    checked_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)  # last Wikipedia lookup
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)  # text last changed


# -- ETF NAV 2026-11-12 (decision 9) ---------------------------------------------------------------------------------
class EtfNav(Base):
    """Daily NAV of listed / OTC ETFs from 金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉 (data.gov.tw 11109,
    OGDL; ``forliosa.marketdata.fund_nav``). The file only holds each fund's latest NAV, so history grows from the day
    archiving starts. Only rows whose 受益憑證代號 is the trading code of an ETF we know (an archived official close or
    the instrument master) are kept; other funds are skipped. ``date`` is the NAV's own date (overseas funds: often the
    previous business day). The premium / discount is computed on read against the archived close of the same day."""

    __tablename__ = "etf_navs"
    __table_args__ = (Index("ix_etf_navs_date", "date"),)

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    fund_name: Mapped[str] = mapped_column(String(200))  # 基金名稱 as published (e.g. 元大台灣卓越50基金)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


# -- discussion threads (docs/api-contract.md 「討論串…」; services/discussions.py) --------------------------------
class DiscussionTopic(Base):
    """A topic. ``scope`` public (everyone, read without login) | group (``group_id``; members only). ``user_id`` is
    null once the author's account is deleted (the content stays). ``status`` visible | hidden (site admins hide
    public content; they never see group content). ``last_activity_at``: the newest reply, else ``created_at``."""

    __tablename__ = "discussion_topics"
    __table_args__ = (
        Index("ix_discussion_topics_scope_activity", "scope", "last_activity_at", "id"),
        Index("ix_discussion_topics_scope_created", "scope", "created_at", "id"),
        Index("ix_discussion_topics_group_activity", "group_id", "last_activity_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(8))
    group_id: Mapped[str | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), default="visible")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    last_activity_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class DiscussionTopicSymbol(Base):
    """The instruments a topic is tagged with (at most 5; ``position`` keeps the author's order)."""

    __tablename__ = "discussion_topic_symbols"

    topic_id: Mapped[str] = mapped_column(ForeignKey("discussion_topics.id", ondelete="CASCADE"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class DiscussionReply(Base):
    """A reply (one level). ``user_id`` is null once the author's account is deleted."""

    __tablename__ = "discussion_replies"
    __table_args__ = (Index("ix_discussion_replies_topic", "topic_id", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("discussion_topics.id", ondelete="CASCADE"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), default="visible")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class DiscussionReaction(Base):
    """An emoji on a topic or a reply (``target_kind`` topic | reply). ``topic_id`` is the topic the target belongs
    to, so everything goes with the topic."""

    __tablename__ = "discussion_reactions"

    target_kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    emoji: Mapped[str] = mapped_column(String(16), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("discussion_topics.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


class DiscussionReport(Base):
    """A report of public content: one per reporter per target. ``status`` open | resolved (hidden or dismissed by a
    site admin). ``reporter_id`` is null once the reporter's account is deleted (the report still counts)."""

    __tablename__ = "discussion_reports"
    __table_args__ = (
        UniqueConstraint("target_kind", "target_id", "reporter_id", name="uq_discussion_report_reporter"),
        Index("ix_discussion_reports_status", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[str] = mapped_column(String(32))
    topic_id: Mapped[str] = mapped_column(ForeignKey("discussion_topics.id", ondelete="CASCADE"), index=True)
    reporter_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="open")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class DiscussionSuspension(Base):
    """A user's public posting is suspended until ``until`` (permanent: 9999-12-31T00:00:00Z) unless lifted. Group
    posting is not affected. At most one active row per user (a new suspension replaces the active one)."""

    __tablename__ = "discussion_suspensions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    until: Mapped[datetime] = mapped_column(TZDateTime)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    lifted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class DiscussionPostLog(Base):
    """One row per topic or reply a user posted (``kind`` topic | reply, ``scope`` public | group) — no content. The
    posting rate limits are counted from these rows, so deleting a post does not give its slot back; a user's rows
    older than the longest window (one day) are removed the next time they post."""

    __tablename__ = "discussion_post_log"
    __table_args__ = (Index("ix_discussion_post_log_user", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
