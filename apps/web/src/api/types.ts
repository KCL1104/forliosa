/**
 * API 型別：與 docs/api-contract.md（v1 草稿）逐欄對應，欄位一律 snake_case。
 * 可為 null 的欄位與後端新增的欄位依 apps/api/CONTRACT_NOTES.md（以真實後端驗證過）。
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
  display_name?: string
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
  /** 公司資料（簡介、題材）是否為示範資料 */
  is_demo: boolean
}

/** 報價：資料源沒有的欄位為 null（CONTRACT_NOTES「可能為 null」） */
export interface Quote {
  symbol: string
  price: number
  prev_close: number | null
  change: number | null
  change_pct: number | null
  open: number | null
  high: number | null
  low: number | null
  /** 股數（MIS 的「張」已乘 1,000） */
  volume: number | null
  as_of: string | null
  is_realtime: boolean
  is_demo: boolean
  source: string
  /** 參考價（平盤價）：除權息日 `change`／`change_pct` 以它計算，不是昨收 */
  reference_price?: number | null
  /** 漲停／跌停價（美股沒有，為 null） */
  limit_up?: number | null
  limit_down?: number | null
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
  /** 河流圖的說明與資料來源，例如「EPS ≤ 0，本益比區間留白」 */
  notes: string[]
  is_demo: boolean
}

/** 月營收：單位為新台幣「千元」，與公開資訊觀測站一致 */
export interface MonthlyRevenue {
  period: string
  revenue: number
  yoy_pct: number | null
  mom_pct: number | null
  ytd: number | null
  ytd_yoy_pct: number | null
}

export interface DividendRecord {
  year: number
  period: string
  cash_dividend: number
  stock_dividend: number
  ex_dividend_date: string | null
  payment_date: string | null
  /** 陣列回應沒有整體的 is_demo，逐筆標示 */
  is_demo: boolean
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
  /** `ai_draft`：由 AI 草稿經使用者簽名確認後建立（介面標示「由 AI 建立」） */
  source: TransactionSource
  created_at: string
}

export type TransactionSource = "manual" | "import" | "ai_draft"

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
  source?: Exclude<TransactionSource, "import">
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
  /** 分母（成本）為 0 時為 null */
  unrealized_pnl_pct: number | null
  realized_pnl: number
  dividend_income: number
  total_pnl: number
  total_return_pct: number | null
  day_change: number
  day_change_pct: number | null
  allocation: {
    by_market: AllocationSlice[]
    by_industry: AllocationSlice[]
    by_currency: AllocationSlice[]
    by_type: AllocationSlice[]
    by_account?: AllocationSlice[]
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
  /** 沒有報價時為 null（以成本計值，並標示 is_demo） */
  price: number | null
  prev_close: number | null
  market_value: number
  day_change: number
  day_change_pct: number | null
  unrealized_pnl: number
  unrealized_pnl_pct: number | null
  weight: number
  account_ids: string[]
  /** 這一檔的報價是否含模擬資料 */
  is_demo: boolean
}

/** 1D／5D 以交易日計，第一個點是基準收盤（twr_index = 1.0） */
export type PerformanceRange = "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "ALL"

export interface PerformancePoint {
  t: string
  market_value: number
  net_invested: number
  twr_index: number
  benchmark_index: number | null
}

export interface Performance {
  range: PerformanceRange
  /** 沒有交易時為 null */
  start_date: string | null
  end_date: string | null
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


// ── 重新設計新增（2026-11-12）：個股頁、帳本、自選 ───────────────
export interface InstrumentStatus {
  /** 注意股票 */
  attention: boolean
  /** 處置股票 */
  disposition: boolean
  note: string | null
}

/** `GET /instruments/{symbol}/overview`：欄位缺資料時為 null */
export interface InstrumentOverview {
  open: number | null
  high: number | null
  low: number | null
  prev_close: number | null
  reference_price: number | null
  limit_up: number | null
  limit_down: number | null
  /** 股數 */
  volume: number | null
  avg_volume_3m: number | null
  market_cap: number | null
  pe: number | null
  pb: number | null
  dividend_yield: number | null
  last_cash_dividend: number | null
  ex_dividend_date: string | null
  eps_ttm: number | null
  high_52w: number | null
  low_52w: number | null
  shares_outstanding: number | null
  status: InstrumentStatus
  as_of: string | null
  sources: string[]
  is_demo: boolean
  symbol?: string
}

export interface IntradayPoint {
  /** 台北時間「09:01」 */
  t: string
  price: number
  volume: number
}

/** `GET /instruments/{symbol}/intraday`：只有持股與自選會累積盤中點，其他回 `points: []` */
export interface Intraday {
  symbol: string
  date: string
  prev_close: number | null
  reference_price: number | null
  points: IntradayPoint[]
  is_partial: boolean
  sources: string[]
  is_demo?: boolean
  /** 例如「商用模式沒有授權的即時來源」（CONTRACT_NOTES） */
  notes?: string[]
}

export type ChipsRange = "1M" | "3M" | "6M" | "1Y"

/** 籌碼：法人與融資融券單位都是「張」 */
export interface Chips {
  institutional: { t: string; foreign: number; trust: number; dealer: number; total: number }[]
  margin: { t: string; margin_balance: number; short_balance: number }[]
  foreign_holding_pct: { t: string; pct: number }[]
  /** 集保股權分散：後端提供 15 個分級，另有 `label`（例如「1,000 張以上」） */
  major_holders: { as_of: string; buckets: { level: string; label?: string; holders: number; shares: number; pct: number }[] } | null
  sources: string[]
  is_demo?: boolean
  notes?: string[]
}

export type FinancialsPeriod = "quarterly" | "annual"
type Col = (number | null)[]

/** 財務報表：每個欄位是與 `periods` 等長的陣列，金額單位新台幣千元 */
export interface Financials {
  periods: string[]
  income: { revenue: Col; gross_profit: Col; operating_income: Col; net_income: Col; eps: Col }
  balance: { total_assets: Col; total_liabilities: Col; equity: Col }
  cashflow: { operating: Col; investing: Col; financing: Col; free_cash_flow: Col }
  margins: { gross: Col; operating: Col; net: Col }
  sources: string[]
  is_demo?: boolean
  notes?: string[]
}

export type InstrumentEventType =
  | "ex_dividend"
  | "dividend_payment"
  | "earnings"
  | "revenue_release"
  | "material_info"
  | "attention"
  | "disposition"
  | "shareholder_meeting"

export interface InstrumentEvent {
  date: string
  type: InstrumentEventType
  title: string
  detail: string | null
  url: string | null
  mine: boolean
  amount_estimate: number | null
  sources?: string[]
}

/** 新聞：只有標題、來源、連結 */
export interface NewsItem {
  published_at: string
  title: string
  source: string
  url: string
  sources?: string[]
}

export type PositionMarkerType = "buy" | "sell" | "dividend" | "stock_dividend"

export interface PositionMarker {
  date: string
  type: PositionMarkerType
  quantity: number | null
  price: number | null
  amount: number | null
}

/** `GET /instruments/{symbol}/position`：未持有回 null */
export interface Position {
  quantity: number
  avg_cost: number
  cost_basis: number
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number | null
  realized_pnl: number
  dividends_received: number
  day_change: number
  markers: PositionMarker[]
  upcoming_dividend: { ex_dividend_date: string; amount_estimate: number } | null
  currency?: Currency
  as_of?: string | null
  sources?: string[]
  is_demo?: boolean
}

export interface WhyReason {
  /** move、volume、limit、attention、disposition、ex_dividend、earnings、high_52w、low_52w… */
  kind: string
  text: string
}

/** 「為什麼漲跌」：規則判斷，只在異常時 `show: true` */
export interface Why {
  show: boolean
  headline: string | null
  reasons: WhyReason[]
  as_of: string | null
  sources?: string[]
}

export interface WatchItem {
  symbol: string
  name: string
  /** 資料源沒有報價時為 null */
  quote: Quote | null
  /** `1m`：盤中點（t 為 09:01）；`1d`：最近 20 個收盤（t 為日期） */
  sparkline: { t: string; price: number }[]
  sparkline_interval?: "1m" | "1d"
  sources?: string[]
  is_demo?: boolean
}

export type UpcomingType = "ex_dividend" | "dividend_payment" | "recurring"

/** 「本週事項」：除息、股利入帳、定期定額（規則計算） */
export interface UpcomingItem {
  date: string
  type: UpcomingType
  symbol: string | null
  title: string
  amount_estimate: number | null
  sources?: string[]
  is_demo?: boolean
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
  getOverview(symbol: string): Promise<InstrumentOverview>
  getIntraday(symbol: string): Promise<Intraday>
  getChips(symbol: string, range?: ChipsRange): Promise<Chips>
  getFinancials(symbol: string, period?: FinancialsPeriod): Promise<Financials>
  getEvents(symbol: string, mine?: boolean): Promise<InstrumentEvent[]>
  getNews(symbol: string): Promise<NewsItem[]>
  getPosition(symbol: string): Promise<Position | null>
  getWhy(symbol: string): Promise<Why>
  // 自選
  getWatchlist(): Promise<WatchItem[]>
  addWatch(symbol: string): Promise<void>
  removeWatch(symbol: string): Promise<void>
  // 交易
  listTransactions(query: TransactionQuery): Promise<Page<Transaction>>
  createTransaction(body: TransactionInput): Promise<Transaction>
  updateTransaction(id: string, patch: Partial<TransactionInput>): Promise<Transaction>
  deleteTransaction(id: string): Promise<void>
  previewTransaction(body: TransactionInput): Promise<TradePreview>
  // 投資組合
  getPortfolioSummary(accountId?: string): Promise<PortfolioSummary>
  getHoldings(accountId?: string): Promise<Holding[]>
  getUpcoming(days?: number): Promise<UpcomingItem[]>
  getPerformance(params: {
    range: PerformanceRange
    benchmark?: string
    account_id?: string
  }): Promise<Performance>
}
