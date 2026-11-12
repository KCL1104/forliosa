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
    source: Mapped[str] = mapped_column(String(16), default="manual")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_utc, onupdate=now_utc)

    account: Mapped[BrokerAccount] = relationship(back_populates="transactions")


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
