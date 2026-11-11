"""Request/response models. Field names and units follow docs/api-contract.md exactly."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TxnTypeLiteral = Literal[
    "buy", "sell", "cash_dividend", "stock_dividend", "split", "capital_reduction",
    "deposit", "withdrawal", "fee", "tax", "interest",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- users ------------------------------------------------------------------------------------
class Preferences(BaseModel):
    color_convention: Literal["tw", "us"] = "tw"
    theme: Literal["light", "dark", "system"] = "system"
    quantity_unit: Literal["lot", "share"] = "lot"
    privacy_mode: bool = False
    cost_method: Literal["average", "fifo"] = "average"
    benchmark: str = "0050.TW"


class PreferencesPatch(StrictModel):
    color_convention: Literal["tw", "us"] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    quantity_unit: Literal["lot", "share"] | None = None
    privacy_mode: bool | None = None
    cost_method: Literal["average", "fifo"] | None = None
    benchmark: str | None = None


class User(BaseModel):
    id: str
    email: str
    display_name: str
    preferences: Preferences


class DevLoginIn(StrictModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str | None = Field(default=None, max_length=100)


# -- accounts ---------------------------------------------------------------------------------
class AccountIn(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    broker: str = Field(default="", max_length=100)
    currency: Literal["TWD", "USD"] = "TWD"
    fee_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.1"))
    fee_discount: Decimal = Field(default=Decimal(1), gt=0, le=1)
    min_fee: Decimal | None = Field(default=None, ge=0)
    min_fee_odd_lot: Decimal | None = Field(default=None, ge=0)
    tracking_mode: Literal["transactions", "holdings"] = "transactions"


class AccountPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    broker: str | None = Field(default=None, max_length=100)
    currency: Literal["TWD", "USD"] | None = None
    fee_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.1"))
    fee_discount: Decimal | None = Field(default=None, gt=0, le=1)
    min_fee: Decimal | None = Field(default=None, ge=0)
    min_fee_odd_lot: Decimal | None = Field(default=None, ge=0)
    tracking_mode: Literal["transactions", "holdings"] | None = None


class Account(BaseModel):
    id: str
    name: str
    broker: str
    currency: str
    fee_rate: float
    fee_discount: float
    min_fee: float
    min_fee_odd_lot: float
    tracking_mode: str
    created_at: str


class SnapshotHolding(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(gt=0)
    avg_cost: Decimal = Field(ge=0)


class HoldingsSnapshotIn(StrictModel):
    as_of: date
    holdings: list[SnapshotHolding] = Field(max_length=500)


class HoldingsSnapshot(BaseModel):
    account_id: str
    as_of: date | None
    holdings: list[dict]


# -- instruments & quotes -----------------------------------------------------------------------
class Instrument(BaseModel):
    symbol: str
    code: str
    name: str
    market: Literal["TWSE", "TPEX", "US"]
    type: Literal["stock", "etf"]
    currency: str
    industry: str | None


class InstrumentDetail(Instrument):
    summary: str | None
    chain_stage: str | None
    themes: list[str]
    shares_outstanding: int | None
    market_cap: float | None
    data_sources: list[str]
    is_demo: bool


class Quote(BaseModel):
    symbol: str
    price: float
    prev_close: float | None
    change: float | None
    change_pct: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: int | None
    as_of: str | None
    is_realtime: bool
    is_demo: bool
    source: str


class CandleOut(BaseModel):
    t: date
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: int


class History(BaseModel):
    symbol: str
    interval: str
    candles: list[CandleOut]
    is_demo: bool


class ValuationPoint(BaseModel):
    t: date
    close: float
    eps_ttm: float | None
    bvps: float | None
    per: float | None
    pbr: float | None
    dividend_yield: float | None


class ValuationCurrent(BaseModel):
    per: float | None
    pbr: float | None
    dividend_yield: float | None
    per_percentile_5y: float | None


class Valuation(BaseModel):
    symbol: str
    per_multiples: list[float]
    pbr_multiples: list[float]
    series: list[ValuationPoint]
    current: ValuationCurrent
    notes: list[str] = []
    is_demo: bool


class MonthlyRevenue(BaseModel):
    period: str
    revenue: int
    yoy_pct: float | None
    mom_pct: float | None
    ytd: int | None
    ytd_yoy_pct: float | None


class DividendRecord(BaseModel):
    year: int
    period: str
    cash_dividend: float
    stock_dividend: float
    ex_dividend_date: date | None
    payment_date: date | None
    is_demo: bool = False


# -- transactions -------------------------------------------------------------------------------
class TransactionIn(StrictModel):
    account_id: str
    symbol: str | None = Field(default=None, max_length=20)
    type: TxnTypeLiteral
    trade_date: date
    quantity: Decimal | None = Field(default=None, ge=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, ge=0)
    fee: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    health_insurance: Decimal | None = Field(default=None, ge=0)
    currency: Literal["TWD", "USD"] | None = None
    is_day_trade: bool = False
    note: str = Field(default="", max_length=2000)
    source: Literal["manual", "import"] = "manual"

    @field_validator("symbol")
    @classmethod
    def _blank_symbol(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class TransactionPatch(StrictModel):
    account_id: str | None = None
    symbol: str | None = Field(default=None, max_length=20)
    type: TxnTypeLiteral | None = None
    trade_date: date | None = None
    quantity: Decimal | None = Field(default=None, ge=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, ge=0)
    fee: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    health_insurance: Decimal | None = Field(default=None, ge=0)
    currency: Literal["TWD", "USD"] | None = None
    is_day_trade: bool | None = None
    note: str | None = Field(default=None, max_length=2000)
    source: Literal["manual", "import"] | None = None


class Transaction(BaseModel):
    id: str
    account_id: str
    symbol: str | None
    type: str
    trade_date: date
    quantity: float | None
    price: float | None
    amount: float
    fee: float
    tax: float
    health_insurance: float
    currency: str
    is_day_trade: bool
    note: str
    source: str
    created_at: str


class TransactionPage(BaseModel):
    items: list[Transaction]
    next_cursor: str | None


class TradePreview(BaseModel):
    gross: float
    fee: float
    tax: float
    health_insurance: float
    net_cash: float
    rules: list[str]


# -- portfolio ----------------------------------------------------------------------------------
class AllocationItem(BaseModel):
    key: str
    label: str
    value: float
    weight: float


class Allocation(BaseModel):
    by_market: list[AllocationItem]
    by_industry: list[AllocationItem]
    by_currency: list[AllocationItem]
    by_type: list[AllocationItem]
    by_account: list[AllocationItem] = []


class UpcomingDividend(BaseModel):
    symbol: str
    name: str
    ex_dividend_date: date
    cash_dividend: float
    estimated_amount: float


class PortfolioSummary(BaseModel):
    as_of: str
    market_value: float
    cost_basis: float
    unrealized_pnl: float
    unrealized_pnl_pct: float | None
    realized_pnl: float
    dividend_income: float
    total_pnl: float
    total_return_pct: float | None
    day_change: float
    day_change_pct: float | None
    allocation: Allocation
    upcoming_dividends: list[UpcomingDividend]
    is_demo: bool


class Holding(BaseModel):
    symbol: str
    code: str
    name: str
    market: str
    type: str
    currency: str
    industry: str | None
    quantity: float
    avg_cost: float
    cost_basis: float
    price: float | None
    prev_close: float | None
    market_value: float
    day_change: float
    day_change_pct: float | None
    unrealized_pnl: float
    unrealized_pnl_pct: float | None
    weight: float
    account_ids: list[str]
    is_demo: bool = False


class BenchmarkOut(BaseModel):
    symbol: str
    name: str
    twr: float | None


class PerformancePoint(BaseModel):
    t: date
    market_value: float
    net_invested: float
    twr_index: float
    benchmark_index: float | None


class MonthAmount(BaseModel):
    month: str
    amount: float


class YearAmount(BaseModel):
    year: int
    amount: float


class Performance(BaseModel):
    range: str
    start_date: date | None
    end_date: date | None
    twr: float | None
    xirr: float | None
    max_drawdown: float | None
    volatility: float | None
    benchmark: BenchmarkOut | None
    series: list[PerformancePoint]
    dividends_by_month: list[MonthAmount]
    realized_by_year: list[YearAmount]
    is_demo: bool
