"""Request/response models. Field names and units follow docs/api-contract.md exactly."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from forliosa.textsafe import has_control

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
    avatar_url: str | None = None
    preferences: Preferences
    # Discussions: the nickname on public posts, site admin (ADMIN_EMAILS), and until when public posting is
    # suspended (ISO time in UTC; permanent = "9999-12-31T00:00:00Z").
    public_name: str | None = None
    is_admin: bool = False
    public_posting_suspended_until: str | None = None


class MePatch(StrictModel):
    display_name: str = Field(description="1–30 字（去頭尾空白；不能有換行、Tab 等控制字元或看不見的格式字元）")

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 30:
            raise ValueError("顯示名稱需為 1–30 字")
        if has_control(v):
            raise ValueError("顯示名稱不能有換行或控制字元")
        return v


class DevLoginIn(StrictModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _one_line(cls, v: str | None) -> str | None:
        if v is not None and has_control(v):
            raise ValueError("顯示名稱不能有換行或控制字元")
        return v


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
    listed_date: date | None = None  # 上市／上櫃日期 (t187ap03_L / mopsfin_t187ap03_O)
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


class CashSources(BaseModel):
    """Cash per share by source (TWSE t187ap45_L): earnings, legal reserve, capital surplus."""

    earnings: float | None
    legal_reserve: float | None
    capital_surplus: float | None


class DividendRecord(BaseModel):
    year: int
    period: str
    cash_dividend: float
    stock_dividend: float
    ex_dividend_date: date | None
    payment_date: date | None
    is_demo: bool = False
    status: Literal["announced", "resolved"] = "announced"  # resolved: board / AGM resolution, no ex-date yet
    progress: str | None = None  # 決議（擬議）進度
    board_date: date | None = None
    meeting_date: date | None = None
    cash_sources: CashSources | None = None
    sources: list[str] = []


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
    source: Literal["manual", "import", "ai_draft"] = "manual"

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
    source: Literal["manual", "import", "ai_draft"] | None = None


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
    # manual | import | ai_draft | auto (booked by the automatic dividend sync) | auto_edited (an automatic
    # dividend the user edited; never overwritten again)
    source: Literal["manual", "import", "ai_draft", "auto", "auto_edited"]
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


class NavPoint(BaseModel):
    """One day with both an archived official close and a NAV."""

    t: date
    nav: float
    close: float
    premium_pct: float  # close ÷ NAV − 1 (fraction; negative = 折價)


class EtfNavOut(BaseModel):
    """ETF NAV (證券期貨局〈證券投資信託基金每日淨值〉) and the after-close premium / discount on the same date."""

    nav: float | None  # latest archived NAV; when null every number below is null too
    nav_date: date | None
    currency: str | None
    fund_name: str | None  # 基金名稱 as published
    close: float | None  # latest archived official close (only with a NAV)
    close_date: date | None
    premium_pct: float | None  # on premium_date: the newest date with both a close and a NAV
    premium_date: date | None
    history: list[NavPoint]  # same-day points, oldest first (at most 60)
    history_start: date | None  # first archived NAV of this ETF
    history_missing: list[date] = []  # trading days inside the history's span with no same-day point (archive gaps)
    notes: list[str]
    sources: list[str]


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
    listed_date: date | None = None
    status: TradingStatus
    etf_nav: EtfNavOut | None = None  # Taiwan ETFs only
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


class ForeignTop20(BaseModel):
    """A listed stock in TWSE's 外資及陸資持股前 20 名 (the latest archived list): rank and foreign holding."""

    as_of: date
    rank: int
    pct: float  # fraction of issued shares
    limit_pct: float | None = None


class Chips(BaseModel):
    symbol: str
    institutional: list[InstitutionalPoint]
    margin: list[MarginPoint]
    foreign_holding_pct: list[PctPoint]
    major_holders: MajorHolders | None
    sources: list[str]
    notes: list[str] = []
    foreign_top20: ForeignTop20 | None = None  # listed (TWSE) stocks only


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


class FinancialShares(BaseModel):
    """US stocks (SEC EDGAR): cover-page shares outstanding and the diluted weighted-average share count."""

    outstanding: int | None
    outstanding_as_of: date | None
    diluted_average: list[int | None]


class Financials(BaseModel):
    symbol: str
    period: str
    periods: list[str]  # Taiwan "2026Q2" / "2025"; US fiscal "FY2026Q1" / "FY2025"
    period_ends: list[date | None] = []  # last day of each period (US fiscal periods end on the company's dates)
    currency: Literal["TWD", "USD"] = "TWD"
    amount_unit: int = 1000  # amounts × amount_unit = currency units (Taiwan: thousands; US: 1)
    income: IncomeSeries
    balance: BalanceSeries
    cashflow: CashflowSeries
    margins: MarginSeries
    shares: FinancialShares | None = None
    as_of: str | None = None  # US: when the SEC company facts were fetched
    sources: list[str]
    notes: list[str] = []


class StockEvent(BaseModel):
    date: date
    type: Literal["ex_dividend", "dividend_payment", "dividend_resolution", "earnings", "revenue_release",
                  "investor_conference", "material_info", "attention", "disposition", "shareholder_meeting",
                  "sec_filing"]
    title: str
    detail: str
    url: str | None
    mine: bool
    amount_estimate: float | None
    estimated: bool = False  # true only for a legal-deadline fallback (no actual date known yet)
    period: str | None = None  # earnings "2026Q3", revenue_release "2026-10"
    form: str | None = None  # sec_filing: "8-K" | "10-Q" | "10-K" (or "/A" amendments)
    sources: list[str] = []


class ClosePoint(BaseModel):
    t: date
    price: float | None


class RelatedCard(BaseModel):
    """One 「相關股票」 card (rules: docs/research/news-and-external-sources.md §8)."""

    symbol: str
    name: str
    reason: Literal["benchmark", "constituent", "affiliate", "peer", "leader", "holding", "same_index", "same_type"]
    reason_label: str
    close: float | None
    change_pct: float | None
    as_of: date | None = None
    sparkline: list[ClosePoint] = []
    is_index: bool = False
    notes: list[str] = []
    is_demo: bool = False


class Related(BaseModel):
    symbol: str
    items: list[RelatedCard]
    sources: list[str]
    notes: list[str] = []


class CompanyDescriptionOut(BaseModel):
    kind: Literal["wikipedia", "ai"]
    text: str
    label: str  # 「節錄」 | 「AI 依公開資料整理」
    title: str | None = None
    url: str | None = None
    source: str | None = None  # 「維基百科」
    license: str | None = None  # CC BY-SA 4.0
    license_url: str | None = None
    revision_id: int | None = None
    updated_at: str | None = None


class FormerName(BaseModel):
    name: str
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class FundFacts(BaseModel):
    fund_type: str | None = None
    index_name: str | None = None
    custodian: str | None = None
    units: int | None = None


class CompanyAbout(BaseModel):
    """「關於〈公司〉」: official facts (t187ap03 / SEC submissions / t187ap47) and the description."""

    symbol: str
    name: str
    short_name: str
    english_short_name: str | None = None
    market: str
    type: str
    industry: str | None = None
    incorporated: date | None = None
    years_since_incorporation: int | None = None
    listed_date: date | None = None
    listing: str | None = None  # 上市 | 上櫃
    hq: str | None = None
    registered_in: str | None = None  # KY etc.: the registration country instead of an HQ city
    website: str | None = None
    paid_in_capital: int | None = None  # NT$
    chairman: str | None = None  # 董事長, as published (shown with its source; never used by AI)
    president: str | None = None  # 總經理, as published
    auditor: str | None = None
    transfer_agent: str | None = None
    exchanges: list[str] = []  # US
    fiscal_year_end: str | None = None  # US: "09-26"
    former_names: list[FormerName] = []  # US
    fund: FundFacts | None = None  # ETFs
    description: CompanyDescriptionOut | None = None
    data_date: date | None = None
    sources: list[str] = []
    notes: list[str] = []


class NewsItem(BaseModel):
    """An official announcement (``source: "公告"``) or a media headline (``category: "media"``: original title,
    ``outlet``, time and the link to the original site; ``source`` names how it was found)."""

    published_at: str
    title: str
    source: str  # 「公告」; media: GDELT | AI 搜尋 | SearXNG | Yahoo股市 | FinMind
    outlet: str | None = None  # media only: 聯合新聞網, 中央社 … (unknown outlets: their domain)
    url: str
    category: Literal["material_info", "exchange_news", "media"] = "media"
    date_only: bool = False  # the source gave a date without a time (show the date, not「N 小時前」)
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


class ClosedRound(BaseModel):
    """One holding round (0 → >0 → 0 shares) of a symbol in one account; amounts in TWD."""

    symbol: str
    name: str
    account_id: str
    currency: str
    opened_at: date
    closed_at: date
    holding_days: int
    total_bought_qty: float
    total_sold_qty: float
    cost_basis: float
    realized_pnl: float
    realized_pnl_pct: float | None
    dividends_received: float
    fees_and_taxes: float
    sources: list[str] = []


class HistoryMarker(PositionMarker):
    account_id: str


class PositionHistory(BaseModel):
    symbol: str
    rounds: list[ClosedRound]
    markers: list[HistoryMarker]
    sources: list[str] = []


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
    # recurring only
    plan_id: str | None = None
    account_id: str | None = None
    scheduled_date: date | None = None  # the plan's day before moving to the next trading day


# -- recurring plans (定期定額) ---------------------------------------------------------------------------
def _days_of_month(v: int | list[int] | None) -> list[int] | None:
    if v is None:
        return None
    days = [v] if isinstance(v, int) else list(v)
    if not days:
        raise ValueError("至少要有一個扣款日")
    if any(not isinstance(d, int) or isinstance(d, bool) or not 1 <= d <= 28 for d in days):
        raise ValueError("扣款日必須是 1–28 的整數")
    return sorted(set(days))


class RecurringPlanIn(StrictModel):
    account_id: str
    symbol: str = Field(min_length=1, max_length=20)
    amount: Decimal = Field(gt=0, le=Decimal(100_000_000), description="每次扣款金額（新台幣）")
    day_of_month: int | list[int] = Field(description="每月扣款日 1–28；可為整數或陣列（如 [6, 16, 26]）")
    start_date: date | None = None
    end_date: date | None = None
    active: bool = True
    note: str = Field(default="", max_length=500)

    @field_validator("day_of_month")
    @classmethod
    def _days(cls, v: int | list[int] | None) -> list[int] | None:
        return _days_of_month(v)


class RecurringPlanPatch(StrictModel):
    account_id: str | None = None
    symbol: str | None = Field(default=None, min_length=1, max_length=20)
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal(100_000_000))
    day_of_month: int | list[int] | None = None
    start_date: date | None = None
    end_date: date | None = None
    active: bool | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("day_of_month")
    @classmethod
    def _days(cls, v: int | list[int] | None) -> list[int] | None:
        return _days_of_month(v)


class RecurringPlanOut(BaseModel):
    id: str
    account_id: str
    symbol: str
    name: str
    amount: float
    day_of_month: list[int]
    start_date: date
    end_date: date | None
    active: bool
    note: str
    next_date: date | None
    created_at: str
    updated_at: str


class DraftTransaction(BaseModel):
    account_id: str
    symbol: str
    type: Literal["buy"]
    trade_date: date
    quantity: float
    price: float
    note: str
    source: Literal["ai_draft"]


class RecurringDraft(BaseModel):
    plan_id: str
    scheduled_date: date
    date: date
    name: str
    amount: float
    price_as_of: date
    transaction: DraftTransaction
    preview: TradePreview
    is_demo: bool
    sources: list[str] = []


# -- derivatives (TAIFEX OpenAPI archive, 2026-11-12) -------------------------------------------------------
class FuturesSession(BaseModel):
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change: float | None
    change_pct: float | None
    volume: int | None
    settlement_price: float | None = None  # regular session only
    open_interest: int | None = None  # regular session only


class FuturesQuote(BaseModel):
    code: str
    name: str
    contract_month: str
    regular: FuturesSession | None
    after_hours: FuturesSession | None  # the night session booked to the same trading day


class PutCallRatioOut(BaseModel):
    date: date
    volume_ratio: float | None  # fraction: 1.0708 = 107.08%
    oi_ratio: float | None
    put_volume: int | None
    call_volume: int | None
    put_oi: int | None
    call_oi: int | None
    oi_ratio_prev: float | None


class InstitutionalSide(BaseModel):
    oi_net: int | None
    oi_net_change: int | None
    oi_net_value_k: int | None
    net_volume: int | None


class InstitutionalPosition(BaseModel):
    investor: Literal["dealers", "trust", "foreign"]
    investor_name: str
    oi_net: int | None  # contracts (口); + long, − short
    oi_net_change: int | None  # vs the previous archived trading day
    oi_long: int | None
    oi_short: int | None
    oi_net_value_k: int | None  # thousand NT$
    net_volume: int | None  # today's net traded contracts
    calls: InstitutionalSide | None = None  # TXO only
    puts: InstitutionalSide | None = None


class InstitutionalOut(BaseModel):
    TX: list[InstitutionalPosition]
    TXO: list[InstitutionalPosition]


class TraderSpecific(BaseModel):
    top5_net: int | None
    top10_net: int | None


class TraderBlock(BaseModel):
    top5_buy: int | None
    top5_sell: int | None
    top10_buy: int | None
    top10_sell: int | None
    top5_net: int | None
    top10_net: int | None
    market_oi: int | None
    specific: TraderSpecific | None  # 特定法人 (TypeOfTraders 1) among the large traders
    contract_month: str | None = None


class FuturesLargeTraders(BaseModel):
    contract: str
    name: str
    all_months: TraderBlock | None
    near_month: TraderBlock | None


class OptionsLargeTraders(BaseModel):
    contract: str
    name: str
    calls: TraderBlock | None
    puts: TraderBlock | None


class LargeTradersOut(BaseModel):
    TX: FuturesLargeTraders | None
    TXO: OptionsLargeTraders | None


class DerivativesServed(BaseModel):
    futures: bool
    options_large_traders: bool


class DerivativesOverview(BaseModel):
    as_of: date | None
    futures: list[FuturesQuote]
    put_call_ratio: PutCallRatioOut | None
    institutional: InstitutionalOut
    large_traders: LargeTradersOut
    served: DerivativesServed
    notes: list[str]
    sources: list[str]


class FuturesHistoryPoint(BaseModel):
    t: date
    contract_month: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change: float | None
    change_pct: float | None
    volume: int | None
    settlement_price: float | None
    open_interest: int | None
    after_hours: FuturesSession | None


class FuturesHistory(BaseModel):
    code: str
    name: str
    range: str
    series: list[FuturesHistoryPoint]
    notes: list[str]
    sources: list[str]
