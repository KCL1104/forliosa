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
