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
  /** 每日收盤簡報：收盤資料公布後，依持股與觀察清單寫一則，放在「問 AI」裡（預設關） */
  daily_briefing?: boolean
}

export interface User {
  id: string
  email: string
  /** 群組裡顯示的就是這個名稱（`PATCH /me`，1–30 字） */
  display_name: string
  /** Discord 頭像網址（M5）；開發登入或沒有頭像時為 null／不存在 */
  avatar_url?: string | null
  preferences: Preferences
  /** 公開討論用的暱稱（`PUT /users/me/public-name`，2–20 字）；還沒設定過是 null。群組裡仍用 display_name */
  public_name?: string | null
  /** 站方管理員（後端的 ADMIN_EMAILS）：看得到 `/admin/discussions` */
  is_admin?: boolean
  /**
   * 服務條款與隱私權政策的版本：這個帳號同意過的、和目前的（後端的 TERMS_VERSION；沒有啟用時兩個都是 null）。
   * 目前的版本存在、而且和同意過的不同時，登入後顯示一行「已更新」請使用者按「知道了」（`POST /me/terms-accept`）。
   */
  terms_version_accepted?: string | null
  terms_version_current?: string | null
  /** 條款更新那一行用：新版從哪一天生效（YYYY-MM-DD）、改了什麼的一句話；站方沒填是 null */
  terms_effective_date?: string | null
  terms_summary?: string | null
  /** 公開發言停權到什麼時候（UTC、`Z` 結尾；永久是 `PERMANENT_UNTIL`）；沒有停權是 null */
  public_posting_suspended_until?: string | null
  /** 站方暫停時寫的原因（只有本人看得到；沒寫是 null） */
  public_posting_suspended_reason?: string | null
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

/** 新增帳戶：手續費率等欄位不再由畫面填（不自動算手續費，2026-11-14），後端有預設值 */
export type AccountInput = Omit<Account, "id" | "created_at" | "fee_rate" | "fee_discount" | "min_fee" | "min_fee_odd_lot"> &
  Partial<Pick<Account, "fee_rate" | "fee_discount" | "min_fee" | "min_fee_odd_lot">>

export interface HoldingsSnapshotBody {
  as_of: string
  holdings: { symbol: string; quantity: number; avg_cost: number }[]
}

/** 「只記持股」帳戶目前的快照（`GET /accounts/{id}/holdings`）：還沒存過時 `as_of` 是 null、`holdings` 是空的 */
export interface HoldingsSnapshot {
  account_id: string
  as_of: string | null
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
  /** false：這個市場沒有報價來源（商用模式的美股），搜尋結果標「沒有報價」。後端一定回；測試資料可以省略（視為有） */
  has_quote?: boolean
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
  sources?: string[]
  /** 商用模式存檔不足時的說明，例如「資料累積中：自 2026-11-11 起存檔」 */
  notes?: string[]
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
  /**
   * `ai_draft`：由 AI 草稿經使用者簽名確認後建立（介面標示「由 AI 建立」）；
   * `auto`：台股股利由系統在除息日自動入帳（介面標示「自動」）；`auto_edited`：使用者改過的自動入帳股利（「自動・已修改」）
   */
  source: TransactionSource
  created_at: string
}

/**
 * 交易來源：
 * - `manual`：使用者自己記的（表單）
 * - `import`：匯入對帳單
 * - `ai_draft`：AI 草稿經使用者簽名
 * - `auto`：系統依除息（權）預告在除息（權）日自動記的台股現金股利或配股（股數＝除息日前一天收盤的持股）。
 *   使用者自己記的同類股利優先：同帳戶同商品在除息日起 120 天內有自己記的，就不產生這筆
 * - `auto_edited`：使用者改過的自動入帳股利；之後系統不會再更新它
 * 刪除 `auto` 那筆後，同一次股利不會再自動入帳。用戶端不能建立 `auto`／`auto_edited`。
 */
export type TransactionSource = "manual" | "import" | "ai_draft" | "auto" | "auto_edited"

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
  /** 自動入帳（`auto`、`auto_edited`）只由後端產生，後端的 POST／PATCH 會拒絕 */
  source?: Exclude<TransactionSource, "import" | "auto" | "auto_edited">
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

/** 1D／5D 以交易日計，第一個點是基準收盤（twr_index = 1.0）；MTD = 上月最後收盤起（M5，分享卡的「本月」） */
export type PerformanceRange = "1D" | "5D" | "1M" | "MTD" | "3M" | "6M" | "YTD" | "1Y" | "ALL"

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
  /** 「資料累積中：自 … 起存檔」、「美股目前沒有可商用的行情來源…」 */
  notes?: string[]
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
  /** 台股 ETF 才有（股票、美股為 null）：淨值與同一天的盤後折溢價 */
  etf_nav?: EtfNav | null
  as_of: string | null
  sources: string[]
  is_demo: boolean
  symbol?: string
}

/** 同一天有收盤價也有淨值的一天 */
export interface NavPoint {
  t: string
  nav: number
  close: number
  /** 收盤價 ÷ 淨值 − 1（比率；負數是折價） */
  premium_pct: number
}

/**
 * ETF 淨值：金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（data.gov.tw 11109）。
 * 折溢價只用同一天的收盤價與淨值；`premium_date` 是兩者都有的最近一天（海外標的的淨值常是前一個營業日）。
 * `nav` 是 null 時其他數字也都是 null（收盤價也不給）、`sources` 是空陣列。
 */
export interface EtfNav {
  nav: number | null
  nav_date: string | null
  currency: string | null
  fund_name: string | null
  /** 最近一筆存檔的官方收盤價（有淨值時才有） */
  close: number | null
  close_date: string | null
  premium_pct: number | null
  premium_date: string | null
  /** 由舊到新，最多 60 個有資料的交易日（不一定連續）；滿 20 點才畫走勢 */
  history: NavPoint[]
  history_start: string | null
  /** `history` 第一點到最後一點之間沒有資料的交易日（存檔缺口；走勢在這裡斷開） */
  history_missing: string[]
  notes: string[]
  /** 區塊裡每個數字的資料集：淨值，加上收盤價的證交所／櫃買資料集 */
  sources: string[]
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
  /** 上市股票：名列證交所「外資及陸資持股前 20 名」時的名次與持股比（最新一次存檔）；不在名單上是 null */
  foreign_top20?: { as_of: string; rank: number; pct: number; limit_pct?: number | null } | null
}

export type FinancialsPeriod = "quarterly" | "annual"
type Col = (number | null)[]

/**
 * 財務報表：每個欄位是與 `periods` 等長的陣列。
 * 台股：期間 `2026Q2`／`2025`，金額單位新台幣千元（`amount_unit: 1000`）。
 * 美股（SEC EDGAR）：期間是公司會計年度 `FY2026Q1`／`FY2025`，金額單位美元（`amount_unit: 1`），EPS 為稀釋 EPS。
 */
export interface Financials {
  periods: string[]
  /** 每期最後一天（美股會計年度不一定在月底結束） */
  period_ends?: (string | null)[]
  currency?: "TWD" | "USD"
  /** 金額 × amount_unit = 幣別單位（台股 1000，美股 1） */
  amount_unit?: number
  income: { revenue: Col; gross_profit: Col; operating_income: Col; net_income: Col; eps: Col }
  balance: { total_assets: Col; total_liabilities: Col; equity: Col }
  cashflow: { operating: Col; investing: Col; financing: Col; free_cash_flow: Col }
  margins: { gross: Col; operating: Col; net: Col }
  /** 美股：封面頁的流通股數與稀釋加權平均股數 */
  shares?: { outstanding: number | null; outstanding_as_of: string | null; diluted_average: (number | null)[] } | null
  as_of?: string | null
  sources: string[]
  is_demo?: boolean
  notes?: string[]
}

export type InstrumentEventType =
  | "ex_dividend"
  | "dividend_payment"
  | "earnings"
  | "revenue_release"
  | "investor_conference"
  | "material_info"
  | "attention"
  | "disposition"
  | "shareholder_meeting"
  /** 美股：SEC 的 8-K／10-Q／10-K 申報（`form`），連到 sec.gov 原文 */
  | "sec_filing"

export interface InstrumentEvent {
  date: string
  type: InstrumentEventType
  title: string
  detail: string | null
  url: string | null
  mine: boolean
  amount_estimate: number | null
  sources?: string[]
  /** 只有法定期限的備援是 true（實際日期還不知道）：介面標「預估」 */
  estimated?: boolean
  /** 財報「2026Q3」、營收「2026-10」 */
  period?: string | null
  /** sec_filing：「8-K」「10-Q」「10-K」（修正是「/A」） */
  form?: string | null
}

export type NewsCategory = "material_info" | "exchange_news" | "media"

/**
 * `/instruments/{symbol}/news`：先列官方公告（重大訊息、證交所新聞，`source: "公告"`），再列新聞報導（`category: "media"`）。
 * 新聞報導只有媒體原標題、媒體名稱（`outlet`）、時間與原文連結；`source` 是怎麼找到的（GDELT、AI 搜尋、SearXNG、Yahoo股市、FinMind）。
 */
export interface NewsItem {
  published_at: string
  title: string
  /** 「公告」；新聞報導：GDELT | AI 搜尋 | SearXNG | Yahoo股市 | FinMind */
  source: string
  /** 新聞報導的媒體名稱（聯合新聞網、中央社…；不認得的媒體是網域）；官方公告為 null */
  outlet?: string | null
  url: string
  category?: NewsCategory
  /** 來源只給日期沒有時間：顯示日期，不顯示「N 小時前」 */
  date_only?: boolean
  sources?: string[]
}

/**
 * 相關股票（產品負責人 2026-11-12 第 4 項）：最多 4 張卡，依規則從政府開放資料挑選。
 * `reason`：benchmark＝使用者的比較基準（不是「某 ETF 持有本股」）、constituent＝富櫃五十成分股、affiliate＝關係企業（法人董事／大股東）、
 * peer／leader／holding＝同業、same_index／same_type＝ETF 頁的同指數／同類型。`reason_label` 直接顯示。
 */
export type RelatedReason = "benchmark" | "constituent" | "affiliate" | "peer" | "leader" | "holding" | "same_index" | "same_type"

export interface RelatedCard {
  symbol: string
  name: string
  reason: RelatedReason
  reason_label: string
  close: number | null
  change_pct: number | null
  as_of?: string | null
  /** 存檔的收盤價（約一個月） */
  sparkline: { t: string; price: number | null }[]
  /** 指數卡（比較基準是指數時）：不能點進個股頁 */
  is_index?: boolean
  notes?: string[]
  is_demo?: boolean
}

export interface RelatedStocks {
  symbol: string
  items: RelatedCard[]
  sources: string[]
  notes?: string[]
}

/** 公司簡介：維基百科節錄（CC BY-SA 4.0，不改寫）或 AI 依官方資料寫的 2–3 句 */
export interface CompanyDescription {
  kind: "wikipedia" | "ai"
  text: string
  /** 「節錄」｜「AI 依公開資料整理」 */
  label: string
  title?: string | null
  url?: string | null
  source?: string | null
  license?: string | null
  license_url?: string | null
  revision_id?: number | null
  updated_at?: string | null
}

/** 關於〈公司〉：證交所／櫃買〈公司基本資料〉（董事長、總經理照原文）、美股 SEC、ETF 基金基本資料 */
export interface CompanyAbout {
  symbol: string
  name: string
  short_name: string
  english_short_name?: string | null
  market: Market
  type: InstrumentType
  industry?: string | null
  incorporated?: string | null
  years_since_incorporation?: number | null
  listed_date?: string | null
  /** 上市｜上櫃 */
  listing?: string | null
  hq?: string | null
  /** KY 等外國企業：註冊地（取代總部） */
  registered_in?: string | null
  website?: string | null
  /** 新台幣元 */
  paid_in_capital?: number | null
  chairman?: string | null
  president?: string | null
  auditor?: string | null
  transfer_agent?: string | null
  exchanges?: string[]
  /** 美股會計年度結束日「09-26」 */
  fiscal_year_end?: string | null
  former_names?: { name: string; from?: string | null; to?: string | null }[]
  fund?: { fund_type?: string | null; index_name?: string | null; custodian?: string | null; units?: number | null } | null
  description: CompanyDescription | null
  data_date?: string | null
  sources: string[]
  notes?: string[]
}

export type PositionMarkerType = "buy" | "sell" | "dividend" | "stock_dividend"

export interface PositionMarker {
  date: string
  type: PositionMarkerType
  quantity: number | null
  price: number | null
  amount: number | null
  /** `position/history` 的標記帶帳戶 */
  account_id?: string
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
  /** 定期定額：計畫 id、帳戶、計畫原本的日子（`date` 是遇休市順延後的扣款日） */
  plan_id?: string | null
  account_id?: string | null
  scheduled_date?: string | null
}

// ── 第二批（2026-11-12）：出清紀錄、定期定額、資料授權 ───────────
/** 出清回合：某帳戶某檔從 0 股 → 持有 → 回到 0 股；金額為台幣 */
export interface ClosedRound {
  symbol: string
  name: string
  account_id: string
  currency: Currency
  opened_at: string
  closed_at: string
  /** 日曆天數 */
  holding_days: number
  total_bought_qty: number
  total_sold_qty: number
  cost_basis: number
  realized_pnl: number
  realized_pnl_pct: number | null
  /** 已扣二代健保 */
  dividends_received: number
  fees_and_taxes: number
  sources?: string[]
}

/** `GET /instruments/{symbol}/position/history`：未持有也會回（從未交易時兩個陣列都是空的） */
export interface PositionHistory {
  symbol: string
  rounds: ClosedRound[]
  markers: PositionMarker[]
  sources?: string[]
}

/** 定期定額計畫 */
export interface RecurringPlan {
  id: string
  account_id: string
  symbol: string
  name: string
  /** 每次扣款的新台幣整數元 */
  amount: number
  /** 每月扣款日 1–28，排序過 */
  day_of_month: number[]
  start_date: string
  end_date: string | null
  active: boolean
  note: string
  /** 今天（含）之後的下一次扣款日；停用或已結束為 null */
  next_date: string | null
  created_at: string
  updated_at: string
}

export interface RecurringPlanInput {
  account_id: string
  symbol: string
  amount: number
  day_of_month: number[]
  start_date?: string
  end_date?: string | null
  active?: boolean
  note?: string
}

/** 一次扣款的交易草稿：**不會建立交易**，使用者簽名後才 `POST /transactions` */
export interface RecurringDraft {
  plan_id: string
  scheduled_date: string
  date: string
  name: string
  amount: number
  price_as_of: string
  transaction: {
    account_id: string
    symbol: string
    type: "buy"
    trade_date: string
    quantity: number
    price: number
    note: string
    source: "ai_draft"
  }
  preview: TradePreview
  is_demo: boolean
  sources?: string[]
}

/** `GET /meta/attributions`：每個資料集的顯名聲明（授權條款規定必須顯示） */
export interface AttributionDataset {
  key: string
  agency: string
  dataset: string
  url: string
  used_for: string
  year: number
  license: string
  license_url: string
  commercial: boolean
  /** 完整顯名聲明：「提供機關〈資料集名稱〉（年份），依政府資料開放授權條款第 1 版」 */
  attribution: string
}

export interface Attributions {
  policy: "commercial" | "personal"
  notice: string[]
  datasets: AttributionDataset[]
  not_used: string[]
}

// ── 法人觀點（2026-11-12，api-contract「法人觀點與美股基本面」）──────────
/**
 * `none`：今天還沒有人查過（或上次查不到、已過 10 分鐘可以再查）；`pending`：AI 正在搜尋（POST 之後，或別人剛觸發）；
 * `ready`：有結果（`items` 可能是空的＝近期查無報導）；`unavailable`：這次查不到（AI 暫停、搜尋失敗；`notes` 寫幾點後可再查）。
 * 只有個股：ETF 回 422 `analyst_views_stocks_only`（前端不對 ETF 顯示這一塊）。
 */
export type AnalystViewsStatus = "none" | "pending" | "ready" | "unavailable"

/** 一筆第三方觀點：照原文列出，不換算、不評論；網址必定是這次搜尋結果中的一篇，日期由搜尋結果核對，核對不到的後端不列 */
export interface AnalystView {
  /** 機構名稱（照報導原文） */
  institution: string
  /** 調升／調降／維持／首評；報導沒寫為空字串 */
  action: string
  /** 評等原文，例如「加碼」「優於大盤」「Overweight」；報導沒寫為 null */
  rating_text: string | null
  target_price: number | null
  currency: Currency
  /** 報導日期（由搜尋結果的網址或頁面日期核對） */
  date: string
  source_title: string
  url: string
}

/** `GET/POST /instruments/{symbol}/analyst-views`：同一檔同一交易日全體共用，24 小時後刪除；最多 5 筆，新到舊 */
export interface AnalystViews {
  status: AnalystViewsStatus
  symbol?: string
  as_of?: string | null
  expires_at?: string | null
  items?: AnalystView[]
  /** 固定顯示的免責文字（後端提供；沒有時前端用常數） */
  disclaimer?: string
  notes?: string[]
}

// ── 分享（M5，docs/api-contract.md「分享（M5）」）─────────────────────
// 分享投影：沒開放的欄位「鍵不存在」（不是 null 也不是 0）。型別一律寫成選用欄位，前端只顯示存在的部分，
// 不拿成員名單去比對排行或動態，也不顯示「某某沒分享」。

/** `GET /auth/providers`（不需登入） */
export interface AuthProviders {
  discord: boolean
  /** Google 登入有沒有開（舊版後端沒有這個欄位：當成沒開） */
  google?: boolean
  dev_login: boolean
}

/** Discord 登入失敗時 callback 導回 `/login?error=<code>` */
export type OAuthErrorCode =
  | "oauth_disabled"
  | "oauth_denied"
  | "oauth_state"
  | "oauth_email_unverified"
  | "oauth_email_conflict"
  | "oauth_failed"

export interface UserRef {
  user_id: string
  display_name: string
  avatar_url: string | null
}

export type DelegationScope = "all" | "accounts"

export interface Delegation {
  id: string
  owner: UserRef
  viewer: UserRef
  /** `all` 也包含之後新增的帳戶 */
  scope: DelegationScope
  /** 授權範圍內的帳戶；帳戶刪除後自動移出 */
  accounts: { id: string; name: string }[]
  created_at: string
}

export interface DelegationList {
  /** 我授權給別人的 */
  granted: Delegation[]
  /** 別人授權給我的 */
  received: Delegation[]
}

/** 可以授權的人：和我同群組的成員（已授權的也列，帶 delegation_id） */
export interface DelegationCandidate extends UserRef {
  delegation_id?: string | null
}

export interface DelegationInput {
  viewer_user_id: string
  scope: DelegationScope
  account_ids: string[]
}

export type GroupRole = "owner" | "admin" | "member"

export interface GroupSummary {
  id: string
  name: string
  my_role: GroupRole
  member_count: number
  ranking_enabled: boolean
  latest_activity_at: string | null
  latest_digest_at: string | null
}

export interface GroupMember extends UserRef {
  role: GroupRole
  joined_at: string
  is_me: boolean
}

/** 我在一個群組的分享設定（預設只開 returns；接受邀請時由本人確認） */
export interface ShareSettings {
  /** 報酬率（只有 %）：今日、本月、今年、總報酬率 */
  returns: boolean
  /** 持股名稱與權重（不含股數、金額） */
  holdings: boolean
  /** 實際金額與損益：市值、今日損益、總損益 */
  amounts: boolean
  /** 交易動態：買進／賣出哪一檔（打開時也顯示最近 90 天） */
  trades: boolean
  /** 交易動態附上成交價（trades 關閉時保存但無作用） */
  trade_prices: boolean
  /** 把我開放的內容送到群組的 Discord／Telegram 頻道 */
  push: boolean
}

export interface PushTarget {
  kind: "discord" | "telegram"
  label: string
}

export interface Group {
  id: string
  name: string
  my_role: GroupRole
  ranking_enabled: boolean
  created_at: string
  members: GroupMember[]
  my_share: ShareSettings
  /** 群組推播到哪些頻道（每位成員都看得到） */
  push_targets: PushTarget[]
}

export type LeaderboardPeriod = "day" | "month" | "year"

export interface LeaderboardEntry extends UserRef {
  /** 期間報酬；有持股沒有收盤價時為 null（排在最後、沒有 rank） */
  return_pct: number | null
  /** 總報酬率（含股利）：每筆都附上、不排名、沒有基準 */
  total_return_pct: number | null
  /** 排行關閉（ranked: false）或期間報酬為 null 時沒有 */
  rank?: number | null
  is_me: boolean
  /** 只在我自己那一列：期間報酬沒有算進沒有收盤價的持股（商用模式的美股）。別人的一律 false */
  excludes_unpriced?: boolean
}

export interface BenchmarkReturn {
  symbol: string
  name: string
  return_pct: number | null
}

export interface Leaderboard {
  period: LeaderboardPeriod
  /** 最新收盤的交易日；也是當天排行討論串的對象 `leaderboard:<date>` */
  date: string
  /** 期間起點（所有成員與基準共用） */
  start_date: string
  as_of: string
  /** owner 關掉排行時為 false：沒有 rank，依加入順序 */
  ranked: boolean
  entries: LeaderboardEntry[]
  benchmarks: BenchmarkReturn[]
  notes: string[]
  sources: string[]
  is_demo: boolean
  /** 當天排行討論串（`leaderboard:<date>`，三個期間同一串）的留言數與表情；只有計數，不列出誰按的 */
  comment_count: number
  reactions: Reaction[]
}

export interface SharedHolding {
  symbol: string
  name: string
  weight: number
}

export interface GroupHoldings {
  /** 只有開了 holdings 的成員 */
  members: (UserRef & { holdings: SharedHolding[] })[]
  /** 兩人以上持有，依人數排序 */
  common: { symbol: string; name: string; holder_count: number }[]
  industries: { industry: string; holder_count: number }[]
  is_demo: boolean
}

/** 一位成員分享給這個群組的內容：只出現對方開放的區塊（沒開放的鍵不存在） */
export interface SharedPortfolio extends UserRef {
  returns?: { day: number | null; month: number | null; year: number | null; total: number | null }
  holdings?: SharedHolding[]
  amounts?: { market_value: number; day_change: number; total_pnl: number }
  is_demo: boolean
}

export const REACTION_EMOJIS = ["👍", "🎉", "🔥", "😮", "😢", "👀"] as const
export type ReactionEmoji = (typeof REACTION_EMOJIS)[number]

export interface Reaction {
  emoji: ReactionEmoji
  count: number
  mine: boolean
}

export interface FeedItem {
  id: string
  type: "trade" | "member_joined"
  user_id: string
  display_name: string
  avatar_url: string | null
  /** 以下只有 type = trade 才有 */
  side?: "buy" | "sell"
  symbol?: string
  name?: string
  trade_date?: string
  /** 同一人同一天同一檔同方向的交易合併成一則 */
  count?: number
  /** 只有對方開了 trade_prices 才有這兩個鍵：交易幣別的成交價（多筆合併時為加權平均），不含費用 */
  price?: number
  currency?: Currency
  created_at: string
  comment_count: number
  reactions: Reaction[]
}

export interface Paged<T> {
  items: T[]
  next_cursor: string | null
}

/** 留言對象：`trade:<feed_item_id>`、`digest:<digest_id>`、`leaderboard:<YYYY-MM-DD>` */
export type CommentTarget = string

export interface Comment {
  id: string
  target: CommentTarget
  /** 已離開群組的成員：null（display_name 為「已離開的成員」） */
  user_id: string | null
  display_name: string
  body: string
  created_at: string
  can_delete: boolean
}

export interface DigestFacts {
  returns: { user_id: string; display_name: string; week_return_pct: number | null }[]
  benchmarks: { symbol: string; name: string; week_return_pct: number | null }[]
  common_holdings: { symbol: string; name: string; holder_count: number }[]
  industries: { industry: string; holder_count: number }[]
  /** 只算開了 trades 的成員 */
  trades_count: number
}

export interface Digest {
  id: string
  status: "pending" | "ready" | "failed"
  week_start: string
  week_end: string
  created_at: string
  /** AI 只寫群組整體，不點名個人，不給買賣建議或目標價 */
  summary: string | null
  facts: DigestFacts | null
  disclaimer: string
  sources: string[]
  comment_count: number
  reactions: Reaction[]
}

export type ChannelStatus = "active" | "disabled"

export interface DiscordChannel {
  configured: boolean
  status: ChannelStatus | null
  disabled_reason: string | null
  /** 只有 owner 看得到（webhook 網址最後 4 碼） */
  webhook_hint?: string | null
  notify_trades: boolean
  notify_digest: boolean
}

export interface TelegramChannel {
  configured: boolean
  status: ChannelStatus | null
  disabled_reason: string | null
  chat_title: string | null
  notify_trades: boolean
  notify_digest: boolean
}

export interface Channels {
  discord: DiscordChannel
  telegram: TelegramChannel
  /** 伺服器有設定 bot 時才為 true */
  telegram_available: boolean
}

export interface ChannelNotify {
  notify_trades?: boolean
  notify_digest?: boolean
}

export interface TelegramLinkCode {
  code: string
  bot_username: string
  expires_at: string
}

export interface GroupInvite {
  id: string
  /** 只在建立時回傳 */
  url?: string
  expires_at: string
  multi_use: boolean
  uses: number
}

export interface InviteInput {
  expires: "24h" | "7d"
  multi_use: boolean
}

/** `GET /invites/{token}`（不需登入） */
export interface InvitePreview {
  group_name: string
  inviter_display_name: string
  /** member：已登入且已是成員 */
  status: "valid" | "member"
  /** 只有 `status: "member"` 時有（成員本人才拿得到）：直接連到那個群組 */
  group_id?: string
}

// ── 討論串（docs/api-contract.md「討論串（2026-11-13）」）──────────────────
// 這一節的時間是 UTC、結尾 `Z`、到秒。公開的主題與回覆不用登入就能讀；發言、表情、檢舉、群組範圍都要登入。

export type DiscussionScope = "public" | "group"
export type DiscussionStatus = "visible" | "hidden"

/**
 * 作者。公開範圍只有 `name`（公開暱稱）與 `is_you` 兩個鍵——沒有 user_id、顯示名稱、頭像；
 * 群組範圍另有 `user_id`、`avatar_url`（已離開的成員：name「已離開的成員」、user_id null）。帳號刪除後 `name: null`。
 */
export interface DiscussionAuthor {
  name: string | null
  is_you: boolean
  user_id?: string | null
  avatar_url?: string | null
}

export interface TopicSymbol {
  symbol: string
  code: string
  name: string
}

export interface TopicSummary {
  id: string
  scope: DiscussionScope
  /** 群組範圍才有 */
  group: { id: string; name: string } | null
  title: string
  /** 內文前 120 字（去掉換行） */
  excerpt: string
  symbols: TopicSymbol[]
  author: DiscussionAuthor
  created_at: string
  last_activity_at: string
  /** 含被隱藏的回覆（它們留在原位） */
  reply_count: number
  status: DiscussionStatus
  mine: boolean
}

export interface Topic extends Omit<TopicSummary, "excerpt"> {
  /** 被站方隱藏時是 null（作者本人與站方管理員仍拿得到） */
  body: string | null
  reactions: Reaction[]
  can_delete: boolean
  /** 公開範圍、已登入、不是自己的內容 */
  can_report: boolean
  /** 已登入而且主題沒被隱藏（沒有公開暱稱或被停權時，送出才會收到 409／403） */
  can_reply: boolean
}

export interface Reply {
  id: string
  topic_id: string
  body: string | null
  author: DiscussionAuthor
  created_at: string
  status: DiscussionStatus
  reactions: Reaction[]
  mine: boolean
  can_delete: boolean
  can_report: boolean
}

/** 表情與檢舉的對象：`topic:<id>`、`reply:<id>` */
export type DiscussionTarget = string

export type TopicListScope = "public" | "group" | "all"
export type TopicSort = "active" | "new"

export interface TopicQuery {
  /** `all`＝公開＋我所有群組的（要登入）；預設 public */
  scope?: TopicListScope
  /** 只有 scope=group 時有效（而且必填） */
  group_id?: string
  symbol?: string
  mine?: boolean
  /** active（預設）：依最後回覆時間；new：依建立時間 */
  sort?: TopicSort
  limit?: number
  cursor?: string | null
}

export interface TopicInput {
  scope: DiscussionScope
  group_id?: string
  /** 1–80 字、一行 */
  title: string
  /** 1–5000 字，可換行 */
  body: string
  /** 最多 5 檔，必須是商品主檔裡的代號 */
  symbols?: string[]
}

export const TOPIC_TITLE_MAX = 80
export const TOPIC_BODY_MAX = 5000
export const REPLY_BODY_MAX = 2000
export const REPORT_NOTE_MAX = 300
export const TOPIC_SYMBOLS_MAX = 5
export const PUBLIC_NAME_MIN = 2
export const PUBLIC_NAME_MAX = 20
/** 永久停權的 `until` */
export const PERMANENT_UNTIL = "9999-12-31T00:00:00Z"

export const REPORT_REASONS = ["spam", "solicitation", "abuse", "other"] as const
export type ReportReason = (typeof REPORT_REASONS)[number]

export interface ReportInput {
  target: DiscussionTarget
  reason: ReportReason
  /** 最多 300 字 */
  note?: string
}

/** 站方管理：依對象彙整的檢舉（只有公開內容；不含 email、user_id） */
export interface AdminReport {
  target: DiscussionTarget
  kind: "topic" | "reply"
  /** 主題是「標題｜內文」的前 120 字，回覆是內文前 120 字 */
  excerpt: string
  author_name: string | null
  topic_id: string
  /** 含已處理的 */
  report_count: number
  reasons: Partial<Record<ReportReason, number>>
  notes: string[]
  first_reported_at: string
  status: "open" | "resolved"
  hidden: boolean
}

export type ModerationAction = "hide" | "unhide" | "dismiss"
/** 停權天數；null＝永久（一定要明確傳） */
export type SuspensionDays = 1 | 7 | 30 | null

export interface Suspension {
  id: string
  public_name: string | null
  until: string
  reason: string | null
  created_at: string
}

// ── 錯誤 ──────────────────────────────────────────────────
export interface ApiErrorBody {
  error: { code: string; message: string; [extra: string]: unknown }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  /**
   * `error` 物件裡 `code`／`message` 以外的欄位（討論串）：`rate_limited` → `retry_after_seconds`、
   * `posting_suspended` → `until`、`public_name_cooldown` → `retry_after_days`。
   */
  readonly extra: Readonly<Record<string, unknown>>
  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.extra = extra
  }
}

/** 前端與資料來源之間唯一的邊界：HTTP 版與 mock 版都實作這個介面。 */
/**
 * `GET /meta/market-status`：台股今天是不是交易日、現在是不是盤中（不讀使用者資料，不用登入）。
 * 沒有盤中即時報價：這個狀態只用來決定價格旁要不要加一行「盤中不更新」「今天的收盤價還沒公布」。
 */
/**
 * 市場頁（`GET /market/overview`）：都是收盤後的官方資料，沒有盤中、沒有海外指數。
 * 每個指數有自己的日期（上市、上櫃、期貨、匯率公布的時間不同）。
 */
export interface MarketIndex {
  key: "taiex" | "tpex" | "tx" | "usdtwd"
  name: string
  /** 點｜元 */
  unit: string
  value: number | null
  change: number | null
  /** 分數（0.0123＝1.23%） */
  change_pct: number | null
  date: string
  /** 最多 20 個收盤，舊到新；不到 2 點就不畫 */
  sparkline: { t: string; v: number | null }[]
}
export interface MarketSummarySource {
  url: string
  title: string
  outlet: string
}
/** 每個交易日一則、全站共用的 AI 收盤整理：每一點都附它依據的報導 */
export interface MarketSummary {
  date: string
  headline: string | null
  points: { text: string; sources: MarketSummarySource[] }[]
}

/** 每日收盤簡報裡的一檔：持股（有當天的市值變動）或觀察清單（沒有） */
export interface BriefingMover {
  symbol: string
  code: string
  name: string
  market: Market
  type: InstrumentType
  close: number | null
  change_pct: number | null
  day_change?: number | null
}

export interface BriefingUpcoming {
  date: string
  type: UpcomingType
  symbol: string | null
  /** 定期定額的標題本身含金額；畫面由欄位組（`upcomingText`），隱私模式才不會露出金額 */
  title: string
  amount_estimate: number | null
}

/** 規則算出來的部分（不是模型寫的）：官方收盤價、自己的帳本與觀察清單 */
export interface BriefingFacts {
  market_value: number
  day_change: number
  day_change_pct: number | null
  holdings: number
  /** 沒有收盤價的持股檔數（例如美股）：不在今日損益裡 */
  unpriced: number
  gainers: BriefingMover[]
  losers: BriefingMover[]
  /** 觀察清單裡漲跌 3% 以上的 */
  watchlist: BriefingMover[]
  upcoming: BriefingUpcoming[]
  is_demo: boolean
}

export interface Briefing {
  id: string
  /** 這一則講的交易日 */
  date: string
  created_at: string
  read: boolean
  facts: BriefingFacts
  /** AI 依報導補的幾點（可能沒有） */
  points: { text: string; sources: MarketSummarySource[] }[]
}
export interface MarketSector {
  /** 半導體 */
  name: string
  /** 半導體類指數 */
  index_name: string
  close: number | null
  change_pct: number
}
export interface MarketMover {
  symbol: string
  code: string
  name: string
  market: Market
  close: number | null
  change: number | null
  /** 以當天的官方參考價為準（沒有就用前一天收盤） */
  change_pct: number | null
  /** 股 */
  volume: number | null
}
export interface MarketMovers {
  /** 上市與上櫃都已公布的最新一天 */
  date: string
  prev_date: string | null
  /** 列入排行的普通股檔數 */
  count: number
  gainers: MarketMover[]
  losers: MarketMover[]
  volume: MarketMover[]
}
export interface MarketAnnouncement {
  symbol: string
  code: string
  name: string
  title: string
  /** 「17:30」（台北） */
  time: string | null
  url: string | null
}
export interface MarketOverview {
  as_of: string | null
  indices: MarketIndex[]
  summary: MarketSummary | null
  sectors: { date: string; items: MarketSector[] } | null
  movers: MarketMovers | null
  /** 最新一天的重大訊息：新的在前，最多 30 則；`total` 是當天全部的則數 */
  announcements: { date: string; total: number; items: MarketAnnouncement[] } | null
  is_demo: boolean
  notes: string[]
  sources: string[]
}

export interface MarketStatus {
  tw: {
    /** 台北時間的今天（YYYY-MM-DD） */
    date: string
    /** 依官方行事曆 */
    is_trading_day: boolean
    /** 交易日 09:00–13:30（台北） */
    is_open: boolean
    open: string
    close: string
  }
}

/** 刪除帳號時要輸入的字（和後端相同） */
export const ACCOUNT_DELETE_CONFIRMATION = "刪除我的帳號"

export interface ForliosaApi {
  readonly kind: "http" | "mock"
  // 認證與使用者
  devLogin(body: DevLoginBody): Promise<User>
  logout(): Promise<void>
  getMe(): Promise<User>
  /** 匯出我的資料（`GET /me/export`）：一個 JSON 物件，只有這個帳號自己的資料；每人每小時 5 次（429 `rate_limited`） */
  exportMe(): Promise<Record<string, unknown>>
  /** 刪除帳號（`DELETE /me`，不能復原）：`confirm` 必須是 `ACCOUNT_DELETE_CONFIRMATION`；成功後 session 也沒了 */
  deleteMe(confirm: string): Promise<void>
  /** 確認已讀目前版本的條款（`POST /me/terms-accept`）；版本不是目前的 → 409 `terms_version_mismatch` */
  acceptTerms(version: string): Promise<User>
  updatePreferences(patch: Partial<Preferences>): Promise<User>
  // 帳戶
  listAccounts(): Promise<Account[]>
  createAccount(body: AccountInput): Promise<Account>
  updateAccount(id: string, patch: Partial<AccountInput>): Promise<Account>
  /** 刪除帳戶（不能復原）：連同交易、自動入帳的股利、持股快照與定期定額 */
  deleteAccount(id: string): Promise<void>
  /** 「只記持股」帳戶目前的快照 */
  getAccountHoldings(id: string): Promise<HoldingsSnapshot>
  /** 以快照覆蓋「只記持股」帳戶的持股（逐筆交易的帳戶回 409）：快照日（含）之前的交易不算，自動股利從快照日之後才記 */
  putHoldings(id: string, body: HoldingsSnapshotBody): Promise<HoldingsSnapshot>
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
  getRelated(symbol: string): Promise<RelatedStocks>
  getCompany(symbol: string): Promise<CompanyAbout>
  getPosition(symbol: string): Promise<Position | null>
  getPositionHistory(symbol: string): Promise<PositionHistory>
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
  getClosedPositions(accountId?: string): Promise<ClosedRound[]>
  getPerformance(params: {
    range: PerformanceRange
    benchmark?: string
    account_id?: string
  }): Promise<Performance>
  // 定期定額
  listRecurring(accountId?: string): Promise<RecurringPlan[]>
  createRecurring(body: RecurringPlanInput): Promise<RecurringPlan>
  updateRecurring(id: string, patch: Partial<RecurringPlanInput>): Promise<RecurringPlan>
  deleteRecurring(id: string): Promise<void>
  draftRecurring(id: string, date?: string): Promise<RecurringDraft>
  // 資料來源與授權（不需登入）
  getAttributions(): Promise<Attributions>
  getMarketStatus(): Promise<MarketStatus>
  // 市場頁：指數、AI 收盤整理、類股、排行、重大訊息（收盤後的官方資料）
  getMarketOverview(): Promise<MarketOverview>
  // 每日收盤簡報（開了的人才有；是登入者自己的，查看別人的資產時不讀）
  getLatestBriefing(): Promise<Briefing | null>
  listBriefings(limit?: number): Promise<Briefing[]>
  markBriefingRead(id: string): Promise<void>
  /**
   * 刪除全部 AI 對話（`DELETE /ai/threads`）：草稿保留，已簽名草稿建立的交易留在帳本；查看別人的資產時 403 `read_only`。
   * mock 模式的對話只存在這台瀏覽器（`ai/store.ts`），這裡沒有東西可刪。
   */
  deleteAiThreads(): Promise<void>
  // 法人觀點：GET 讀當日共用快取；POST 觸發 AI 網路搜尋（計入觸發者的 AI 額度）
  getAnalystViews(symbol: string): Promise<AnalystViews>
  requestAnalystViews(symbol: string): Promise<AnalystViews>
  // ── 分享（M5） ──
  // 登入（Discord OAuth）與個人資料
  getAuthProviders(): Promise<AuthProviders>
  /** 開始 Discord 登入的網址（整頁導過去；成功後回到 `next`） */
  discordLoginUrl(next: string): string
  /** `GET /auth/google/start?next=`：瀏覽器直接導過去（不是 fetch） */
  googleLoginUrl(next: string): string
  updateMe(patch: { display_name: string }): Promise<User>
  // 授權唯讀查看
  listDelegations(): Promise<DelegationList>
  listDelegationCandidates(): Promise<DelegationCandidate[]>
  createDelegation(body: DelegationInput): Promise<Delegation>
  updateDelegation(id: string, patch: Pick<DelegationInput, "scope" | "account_ids">): Promise<Delegation>
  deleteDelegation(id: string): Promise<void>
  // 群組
  listGroups(): Promise<GroupSummary[]>
  createGroup(body: { name: string }): Promise<Group>
  getGroup(id: string): Promise<Group>
  updateGroup(id: string, patch: { name?: string; ranking_enabled?: boolean }): Promise<Group>
  deleteGroup(id: string): Promise<void>
  transferGroup(id: string, userId: string): Promise<unknown>
  setMemberRole(id: string, userId: string, role: "admin" | "member"): Promise<unknown>
  removeMember(id: string, userId: string): Promise<void>
  createInvite(id: string, body: InviteInput): Promise<GroupInvite>
  listInvites(id: string): Promise<GroupInvite[]>
  revokeInvite(id: string, inviteId: string): Promise<void>
  getInvite(token: string): Promise<InvitePreview>
  acceptInvite(token: string, share: ShareSettings): Promise<Group>
  getShare(id: string): Promise<ShareSettings>
  putShare(id: string, share: ShareSettings): Promise<unknown>
  getLeaderboard(id: string, period: LeaderboardPeriod): Promise<Leaderboard>
  getGroupHoldings(id: string): Promise<GroupHoldings>
  getSharedPortfolio(id: string, userId: string): Promise<SharedPortfolio>
  getFeed(id: string, query?: { limit?: number; cursor?: string | null; user_id?: string }): Promise<Paged<FeedItem>>
  listComments(id: string, target: CommentTarget, query?: { limit?: number; cursor?: string | null }): Promise<Paged<Comment>>
  createComment(id: string, body: { target: CommentTarget; body: string }): Promise<Comment>
  deleteComment(id: string, commentId: string): Promise<void>
  addReaction(id: string, body: { target: CommentTarget; emoji: ReactionEmoji }): Promise<void>
  removeReaction(id: string, target: CommentTarget, emoji: ReactionEmoji): Promise<void>
  listDigests(id: string, query?: { limit?: number; cursor?: string | null }): Promise<Paged<Digest>>
  getChannels(id: string): Promise<Channels>
  putDiscord(id: string, body: { webhook_url: string } & Required<ChannelNotify>): Promise<unknown>
  patchDiscord(id: string, patch: ChannelNotify): Promise<unknown>
  deleteDiscord(id: string): Promise<void>
  linkTelegram(id: string): Promise<TelegramLinkCode>
  patchTelegram(id: string, patch: ChannelNotify): Promise<unknown>
  deleteTelegram(id: string): Promise<void>
  // ── 討論串 ──
  /** `PUT /users/me/public-name`：409 public_name_taken／public_name_cooldown（帶 retry_after_days） */
  setPublicName(public_name: string): Promise<User>
  /** 公開清單不用登入；scope=group／all、mine 要登入 */
  listTopics(query?: TopicQuery): Promise<Paged<TopicSummary>>
  createTopic(body: TopicInput): Promise<Topic>
  getTopic(id: string): Promise<Topic>
  /** `keepalive`：頁面要關掉或藏起來時送出的刪除（延後刪除的通知還沒結束），請求在頁面卸載後照樣送完 */
  deleteTopic(id: string, opts?: { keepalive?: boolean }): Promise<void>
  /** 舊到新 */
  listReplies(topicId: string, query?: { limit?: number; cursor?: string | null }): Promise<Paged<Reply>>
  createReply(topicId: string, body: { body: string }): Promise<Reply>
  deleteReply(id: string, opts?: { keepalive?: boolean }): Promise<void>
  /** 204：沒有內容，前端自己更新或重新讀取 */
  addDiscussionReaction(body: { target: DiscussionTarget; emoji: ReactionEmoji }): Promise<void>
  removeDiscussionReaction(target: DiscussionTarget, emoji: ReactionEmoji): Promise<void>
  reportDiscussion(body: ReportInput): Promise<void>
  // 站方管理（不是管理員 → 404）
  listAdminReports(query?: { status?: "open" | "resolved"; limit?: number; cursor?: string | null }): Promise<Paged<AdminReport>>
  moderateDiscussion(body: { target: DiscussionTarget; action: ModerationAction }): Promise<void>
  listSuspensions(): Promise<Suspension[]>
  createSuspension(body: { target: DiscussionTarget; days: SuspensionDays; reason?: string }): Promise<Suspension>
  liftSuspension(id: string): Promise<void>
}
