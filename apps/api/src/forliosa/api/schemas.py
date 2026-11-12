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
    reference_price: float | None = None
    limit_up: float | None = None
    limit_down: float | None = None
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
    sources: list[str] = []


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
    sources: list[str] = []
    notes: list[str] = []


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
    sources: list[str] = []


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
    notes: list[str] = []


# -- stock page (redesign 2026-11-12) ---------------------------------------------------------------
class TradingStatus(BaseModel):
    attention: bool
    disposition: bool
    note: str | None


class Overview(BaseModel):
    symbol: str
    open: float | None
    high: float | None
    low: float | None
    prev_close: float | None
    reference_price: float | None
    limit_up: float | None
    limit_down: float | None
    volume: int | None
    avg_volume_3m: int | None
    market_cap: float | None
    pe: float | None
    pb: float | None
    dividend_yield: float | None
    last_cash_dividend: float | None
    ex_dividend_date: date | None
    eps_ttm: float | None
    high_52w: float | None
    low_52w: float | None
    shares_outstanding: int | None
    status: TradingStatus
    as_of: str | None
    sources: list[str]
    is_demo: bool


class IntradayPointOut(BaseModel):
    t: str
    price: float
    volume: int | None


class Intraday(BaseModel):
    symbol: str
    date: date
    prev_close: float | None
    reference_price: float | None
    points: list[IntradayPointOut]
    is_partial: bool
    notes: list[str] = []
    sources: list[str]
    is_demo: bool = False


class InstitutionalPoint(BaseModel):
    t: date
    foreign: float | None
    trust: float | None
    dealer: float | None
    total: float | None


class MarginPoint(BaseModel):
    t: date
    margin_balance: int | None
    short_balance: int | None


class PctPoint(BaseModel):
    t: date
    pct: float | None


class HolderBucket(BaseModel):
    level: int
    label: str
    holders: int
    shares: int
    pct: float | None


class MajorHolders(BaseModel):
    as_of: date
    buckets: list[HolderBucket]


class Chips(BaseModel):
    symbol: str
    institutional: list[InstitutionalPoint]
    margin: list[MarginPoint]
    foreign_holding_pct: list[PctPoint]
    major_holders: MajorHolders | None
    sources: list[str]
    notes: list[str] = []


class IncomeSeries(BaseModel):
    revenue: list[float | None]
    gross_profit: list[float | None]
    operating_income: list[float | None]
    net_income: list[float | None]
    eps: list[float | None]


class BalanceSeries(BaseModel):
    total_assets: list[float | None]
    total_liabilities: list[float | None]
    equity: list[float | None]


class CashflowSeries(BaseModel):
    operating: list[float | None]
    investing: list[float | None]
    financing: list[float | None]
    free_cash_flow: list[float | None]


class MarginSeries(BaseModel):
    gross: list[float | None]
    operating: list[float | None]
    net: list[float | None]


class Financials(BaseModel):
    symbol: str
    period: str
    periods: list[str]
    income: IncomeSeries
    balance: BalanceSeries
    cashflow: CashflowSeries
    margins: MarginSeries
    sources: list[str]
    notes: list[str] = []


class StockEvent(BaseModel):
    date: date
    type: Literal["ex_dividend", "dividend_payment", "earnings", "revenue_release", "material_info", "attention",
                  "disposition", "shareholder_meeting"]
    title: str
    detail: str
    url: str | None
    mine: bool
    amount_estimate: float | None
    sources: list[str] = []


class NewsItem(BaseModel):
    published_at: str
    title: str
    source: str
    url: str
    sources: list[str] = []


class PositionMarker(BaseModel):
    date: date
    type: Literal["buy", "sell", "dividend", "stock_dividend"]
    quantity: float | None
    price: float | None
    amount: float | None


class UpcomingDividendEstimate(BaseModel):
    ex_dividend_date: date
    amount_estimate: float | None


class Position(BaseModel):
    symbol: str
    currency: str
    quantity: float
    avg_cost: float
    cost_basis: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float | None
    realized_pnl: float
    dividends_received: float
    day_change: float
    markers: list[PositionMarker]
    upcoming_dividend: UpcomingDividendEstimate | None
    as_of: str
    sources: list[str]
    is_demo: bool


class WhyReason(BaseModel):
    kind: Literal["price_move", "volume", "limit_up", "limit_down", "attention", "disposition", "ex_dividend",
                  "earnings", "revenue_release"]
    text: str


class Why(BaseModel):
    symbol: str
    show: bool
    headline: str | None
    reasons: list[WhyReason]
    as_of: str | None
    sources: list[str] = []


# -- watchlist & upcoming -----------------------------------------------------------------------------
class WatchlistIn(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)


class SparkPoint(BaseModel):
    t: str
    price: float | None


class WatchlistEntry(BaseModel):
    symbol: str
    name: str
    quote: Quote | None
    sparkline: list[SparkPoint]
    sparkline_interval: Literal["1m", "1d"]
    sources: list[str] = []
    is_demo: bool = False


class UpcomingItem(BaseModel):
    date: date
    type: Literal["ex_dividend", "dividend_payment", "recurring"]
    symbol: str | None
    title: str
    amount_estimate: float | None
    is_demo: bool = False
    sources: list[str] = []
