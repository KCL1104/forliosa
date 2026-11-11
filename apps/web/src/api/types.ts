/**
 * API 型別：與 docs/api-contract.md（v1 草稿）逐欄對應，欄位一律 snake_case。
 * 後端改由 FastAPI 的 OpenAPI 產生型別後，這個檔案應改為自動產生的版本。
 */

export type ColorConvention = "tw" | "us"
export type ThemePreference = "light" | "dark" | "system"
export type QuantityUnit = "lot" | "share"
export type CostMethod = "average" | "fifo"

export interface Preferences {
  color_convention: ColorConvention
  theme: ThemePreference
  quantity_unit: QuantityUnit
  privacy_mode: boolean
  cost_method: CostMethod
  benchmark: string
}

export interface User {
  id: string
  email: string
  display_name: string
  preferences: Preferences
}

export interface DevLoginBody {
  email: string
  display_name: string
}

// ── 券商帳戶 ──────────────────────────────────────────────
export type Currency = "TWD" | "USD"
export type TrackingMode = "transactions" | "holdings"

export interface Account {
  id: string
  name: string
  broker: string
  currency: Currency
  fee_rate: number
  fee_discount: number
  min_fee: number
  min_fee_odd_lot: number
  tracking_mode: TrackingMode
  created_at: string
}

export type AccountInput = Omit<Account, "id" | "created_at">

export interface HoldingsSnapshotBody {
  as_of: string
  holdings: { symbol: string; quantity: number; avg_cost: number }[]
}

// ── 商品與行情 ────────────────────────────────────────────
export type Market = "TWSE" | "TPEX" | "US"
export type InstrumentType = "stock" | "etf"

export interface Instrument {
  symbol: string
  code: string
  name: string
  market: Market
  type: InstrumentType
  currency: Currency
  industry: string | null
}

export interface InstrumentDetail extends Instrument {
  summary: string | null
  chain_stage: string | null
  themes: string[]
  shares_outstanding: number | null
  market_cap: number | null
  data_sources: string[]
}

export interface Quote {
  symbol: string
  price: number
  prev_close: number
  change: number
  change_pct: number
  open: number
  high: number
  low: number
  volume: number
  as_of: string
  is_realtime: boolean
  is_demo: boolean
  source: string
}

export type HistoryRange = "5D" | "1M" | "6M" | "YTD" | "1Y" | "5Y" | "MAX"

export interface Candle {
  t: string
  o: number
  h: number
  l: number
  c: number
  v: number
}

export interface History {
  symbol: string
  interval: string
  candles: Candle[]
  is_demo: boolean
}

export interface ValuationPoint {
  t: string
  close: number
  eps_ttm: number | null
  bvps: number | null
  per: number | null
  pbr: number | null
  dividend_yield: number | null
}

export interface Valuation {
  symbol: string
  per_multiples: number[]
  pbr_multiples: number[]
  series: ValuationPoint[]
  current: {
    per: number | null
    pbr: number | null
    dividend_yield: number | null
    per_percentile_5y: number | null
  }
  is_demo: boolean
}

/** 月營收：單位為新台幣「千元」，與公開資訊觀測站一致 */
export interface MonthlyRevenue {
  period: string
  revenue: number
  yoy_pct: number | null
  mom_pct: number | null
  ytd: number
  ytd_yoy_pct: number | null
}

export interface DividendRecord {
  year: number
  period: string
  cash_dividend: number
  stock_dividend: number
  ex_dividend_date: string | null
  payment_date: string | null
}

// ── 交易 ──────────────────────────────────────────────────
export type TransactionType =
  | "buy"
  | "sell"
  | "cash_dividend"
  | "stock_dividend"
  | "split"
  | "capital_reduction"
  | "deposit"
  | "withdrawal"
  | "fee"
  | "tax"
  | "interest"

export interface Transaction {
  id: string
  account_id: string
  symbol: string | null
  type: TransactionType
  trade_date: string
  quantity: number | null
  price: number | null
  amount: number
  fee: number
  tax: number
  health_insurance: number
  currency: Currency
  is_day_trade: boolean
  note: string
  source: "manual" | "import"
  created_at: string
}

export interface TransactionInput {
  account_id: string
  symbol: string | null
  type: TransactionType
  trade_date: string
  quantity: number | null
  price: number | null
  amount?: number | null
  fee?: number | null
  tax?: number | null
  health_insurance?: number | null
  currency?: Currency
  is_day_trade?: boolean
  note?: string
}

export interface TransactionQuery {
  account_id?: string
  symbol?: string
  type?: TransactionType
  from?: string
  to?: string
  limit?: number
  cursor?: string | null
}

export interface TradePreview {
  gross: number
  fee: number
  tax: number
  health_insurance: number
  net_cash: number
  rules: string[]
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

// ── 投資組合 ──────────────────────────────────────────────
export interface AllocationSlice {
  key: string
  label: string
  value: number
  weight: number
}

export interface UpcomingDividend {
  symbol: string
  name: string
  ex_dividend_date: string
  cash_dividend: number
  estimated_amount: number
}

export interface PortfolioSummary {
  as_of: string
  market_value: number
  cost_basis: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  realized_pnl: number
  dividend_income: number
  total_pnl: number
  total_return_pct: number
  day_change: number
  day_change_pct: number
  allocation: {
    by_market: AllocationSlice[]
    by_industry: AllocationSlice[]
    by_currency: AllocationSlice[]
    by_type: AllocationSlice[]
  }
  upcoming_dividends: UpcomingDividend[]
  is_demo: boolean
}

export interface Holding {
  symbol: string
  code: string
  name: string
  market: Market
  type: InstrumentType
  currency: Currency
  industry: string | null
  quantity: number
  avg_cost: number
  cost_basis: number
  price: number
  prev_close: number
  market_value: number
  day_change: number
  day_change_pct: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  weight: number
  account_ids: string[]
}

export type PerformanceRange = "1M" | "3M" | "6M" | "YTD" | "1Y" | "ALL"

export interface PerformancePoint {
  t: string
  market_value: number
  net_invested: number
  twr_index: number
  benchmark_index: number | null
}

export interface Performance {
  range: PerformanceRange
  start_date: string
  end_date: string
  twr: number | null
  xirr: number | null
  max_drawdown: number | null
  volatility: number | null
  benchmark: { symbol: string; name: string; twr: number | null } | null
  series: PerformancePoint[]
  dividends_by_month: { month: string; amount: number }[]
  realized_by_year: { year: number; amount: number }[]
  is_demo: boolean
}

// ── 錯誤 ──────────────────────────────────────────────────
export interface ApiErrorBody {
  error: { code: string; message: string }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
  }
}

/** 前端與資料來源之間唯一的邊界：HTTP 版與 mock 版都實作這個介面。 */
export interface ForliosaApi {
  readonly kind: "http" | "mock"
  // 認證與使用者
  devLogin(body: DevLoginBody): Promise<User>
  logout(): Promise<void>
  getMe(): Promise<User>
  updatePreferences(patch: Partial<Preferences>): Promise<User>
  // 帳戶
  listAccounts(): Promise<Account[]>
  createAccount(body: AccountInput): Promise<Account>
  updateAccount(id: string, patch: Partial<AccountInput>): Promise<Account>
  deleteAccount(id: string): Promise<void>
  putHoldings(id: string, body: HoldingsSnapshotBody): Promise<void>
  // 商品與行情
  searchInstruments(q: string): Promise<Instrument[]>
  getInstrument(symbol: string): Promise<InstrumentDetail>
  getQuote(symbol: string): Promise<Quote>
  getQuotes(symbols: string[]): Promise<Quote[]>
  getHistory(symbol: string, range: HistoryRange): Promise<History>
  getValuation(symbol: string, range?: "5Y" | "MAX"): Promise<Valuation>
  getRevenue(symbol: string): Promise<MonthlyRevenue[]>
  getDividends(symbol: string): Promise<DividendRecord[]>
  // 交易
  listTransactions(query: TransactionQuery): Promise<Page<Transaction>>
  createTransaction(body: TransactionInput): Promise<Transaction>
  updateTransaction(id: string, patch: Partial<TransactionInput>): Promise<Transaction>
  deleteTransaction(id: string): Promise<void>
  previewTransaction(body: TransactionInput): Promise<TradePreview>
  // 投資組合
  getPortfolioSummary(accountId?: string): Promise<PortfolioSummary>
  getHoldings(accountId?: string): Promise<Holding[]>
  getPerformance(params: {
    range: PerformanceRange
    benchmark?: string
    account_id?: string
  }): Promise<Performance>
}
