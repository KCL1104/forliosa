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
    Index,
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
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)


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
    """TWSE t187ap03_L / TPEx mopsfin_t187ap03_O 公司基本資料 (latest only). Company facts only: the
    chairman's, managers', spokespeople's and CPAs' names and phone numbers are personal data, not stored."""

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
