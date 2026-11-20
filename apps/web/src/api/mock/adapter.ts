import {
  ACCOUNT_DELETE_CONFIRMATION,
  ApiError,
  type Account,
  type AllocationLimits,
  type ForliosaApi,
  type History,
  type HistoryRange,
  type Performance,
  type Preferences,
  type Quote,
  type RecurringPlan,
  type Transaction,
  type User,
} from "../types"
import { viewAsId } from "../view-as"
import { createAnalystStore } from "./analyst"
import { beforeShareChangeMessage, shareChangeOn, skipKey, syncAutoDividends } from "./auto-dividends"
import { buildAttributions, DATABENTO_ATTRIBUTION, sourceOf } from "./attributions"
import { mockMarketNow, mockMarketStatus, mockToday, type MockMarket } from "./market-status"
import { buildFacts as buildBriefingFacts, createMockBriefings } from "./briefings"
import { buildMarketOverview } from "./market-overview"
import { buildCompany, buildRelated } from "./company"
import {
  accumulatingNote,
  ARCHIVE_START,
  BACKFILL_START,
  hasUsCloses,
  INDEX_NOTE,
  NO_DATA_NOTE,
  priceOnlyNote,
  REFERENCE_NOTE,
  referenceNote,
  US_ARCHIVE_START,
  US_AS_OF,
  US_SESSION,
  US_VALUATION_NOTE,
  usCandles,
  YAHOO_HISTORY_LABEL,
  ymd,
  type MockPolicy,
} from "./commercial"
import { computePreview } from "./fees"
import { createImportStore } from "./imports"
import { findInstrument, INSTRUMENTS, STRESS_INSTRUMENT, type MockInstrumentSpec } from "./instruments"
import { validLimit } from "./allocation"
import { ACCOUNTS, buildAllocation, buildHoldings, buildPerformance, buildSummary, mockBenchmark, seedTransactions } from "./ledger"
import { addDays, dailyCandles, dividendRecords, MOCK_AS_OF, MOCK_TODAY, monthlyRevenue, valuationSeries } from "./market"
import { createRecurringStore, seedPlans } from "./recurring"
import { DAD_ACCOUNTS, seedDadTransactions, type RawTrade } from "./members"
import { createSharingStore, type MemberSource } from "./sharing"
import { createDiscussionStore, type DiscussionOptions } from "./discussions"
import { createAdminStore } from "./admin"
import { isPriceOnlyNote, isReferenceNote } from "@/lib/data-notes"
import { DISCLAIMER } from "@/lib/disclaimer"
import { createMarketReportsStore, type MockReportsScenario } from "./market-reports"
import { todayInTaipei } from "@/lib/format"
import { closedRounds, positionHistory } from "./rounds"
import { monthlyBreakdown } from "@/lib/asset-composition"
import {
  buildChips,
  buildEvents,
  buildFinancials,
  buildIntraday,
  buildNews,
  buildOverview,
  buildPosition,
  buildUpcoming,
  buildWhy,
  limitsOf,
  referencePrice,
} from "./research"

/**
 * 示範情境：
 * - default：一般示範資料
 * - empty：首次使用（沒有任何交易與持股）
 * - stress：極端資料（超長股名、上千億金額、大幅虧損），給 harden 測試用
 * - cashout：資產組成原型——多一筆買了又整批賣掉的台積電，賣股票收到的錢比買股票花的多（本金是負的）
 * - loss：資產組成原型——多一筆在高點買的長榮，從第一天起一直虧（總資產在本金下面）
 * - cross：資產組成原型——多一筆中美晶，先賺、後來轉虧（總資產從本金上面掉到下面）
 * - lastday：資產組成原型——換成一個小帳本，最後一天在高點買進、整體從賺變虧（見 ledger.ts 的 `lastDayTrades`）
 * 以網址 `?mock=empty` 切換，會記在 sessionStorage。
 */
export type MockScenario = "default" | "empty" | "stress" | "cashout" | "loss" | "cross" | "lastday"

export function readMockScenario(): MockScenario {
  if (typeof window === "undefined") return "default"
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("mock")
    if (fromUrl === "empty" || fromUrl === "stress" || fromUrl === "default" || fromUrl === "cashout" || fromUrl === "loss" || fromUrl === "cross" || fromUrl === "lastday") {
      window.sessionStorage.setItem("forliosa:mock", fromUrl)
      return fromUrl
    }
    const saved = window.sessionStorage.getItem("forliosa:mock")
    if (saved === "empty" || saved === "stress" || saved === "cashout" || saved === "loss" || saved === "cross" || saved === "lastday") return saved
  } catch {
    // sessionStorage 不可用時使用預設情境
  }
  return "default"
}

/**
 * mock 的登入狀態：網址 `?auth=signed-out` 模擬還沒登入（看登入頁與邀請預覽），
 * 「用 Discord 登入」回到 `next` 時帶 `?auth=signed-in`。記在 sessionStorage。
 */
export function readMockSignedIn(): boolean {
  if (typeof window === "undefined") return true
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("auth")
    if (fromUrl === "signed-out") window.sessionStorage.setItem("forliosa:mock-auth", "signed-out")
    if (fromUrl === "signed-in") window.sessionStorage.removeItem("forliosa:mock-auth")
    return window.sessionStorage.getItem("forliosa:mock-auth") !== "signed-out"
  } catch {
    return true
  }
}

/**
 * mock 的討論串情境：網址 `?discuss=named`（示範使用者已經有公開暱稱「示範小資」）、`?discuss=suspended`（有暱稱、公開發言被停權 7 天）、
 * `?discuss=member`（不是站方管理員）；`?discuss=default` 切回預設（沒有公開暱稱、是站方管理員）。記在 sessionStorage。
 */
/** mock 的條款情境：網址 `?terms=updated`（條款有新版本、這個帳號還沒確認）；`?terms=default` 切回預設（沒有啟用版本）。記在 sessionStorage。 */
export function readMockTerms(): MockOptions["terms"] {
  if (typeof window === "undefined") return undefined
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("terms")
    if (fromUrl === "default") window.sessionStorage.removeItem("forliosa:mock-terms")
    else if (fromUrl === "updated") window.sessionStorage.setItem("forliosa:mock-terms", fromUrl)
    return window.sessionStorage.getItem("forliosa:mock-terms") === "updated" ? { current: "2026-12-01", accepted: "2026-11-13", effectiveDate: "2026-12-01", summary: "新增匯出資料與刪除帳號的說明" } : undefined
  } catch {
    return undefined
  }
}

/**
 * mock 的帳本歷史長短（總資產走勢與績效）：網址 `?hist=N` 只留最後 N 個收盤（和正式環境存檔剛開始時一樣：
 * 「績效從 … 收盤開始算，之前沒有資料」；N = 1 是算不出來），`?hist=all` 切回全部。記在 sessionStorage。
 */
export function readMockHistory(): number | undefined {
  if (typeof window === "undefined") return undefined
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("hist")
    if (fromUrl === "all") window.sessionStorage.removeItem("forliosa:mock-hist")
    else if (fromUrl && /^\d+$/.test(fromUrl) && Number(fromUrl) > 0) window.sessionStorage.setItem("forliosa:mock-hist", fromUrl)
    const saved = Number(window.sessionStorage.getItem("forliosa:mock-hist") ?? "")
    return saved > 0 ? saved : undefined
  } catch {
    return undefined
  }
}

/**
 * 只給截圖用的走勢形狀（資產組成原型，總資產走勢 v2）：網址 `?curve=arch` 把「全部」的走勢換成最後 9 個收盤的倒 U——
 * 從最後一天的總資產往上 52 萬再回來、本金都是最後一天的本金（示範帳本：410 萬 → 462 萬 → 410 萬，本金 288 萬）。
 * 兩個角落都碰到總資產線，「本金…在圖的下方」那一行放不進圖裡、改寫在圖例。上面的大數字不跟著變（最後一天一樣）。
 * `?curve=off` 切回。記在 sessionStorage。
 */
export function readMockCurve(): "arch" | undefined {
  if (typeof window === "undefined") return undefined
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("curve")
    if (fromUrl === "arch") window.sessionStorage.setItem("forliosa:mock-curve", "arch")
    else if (fromUrl) window.sessionStorage.removeItem("forliosa:mock-curve")
    return window.sessionStorage.getItem("forliosa:mock-curve") === "arch" ? "arch" : undefined
  } catch {
    return undefined
  }
}

/** `?curve=arch`：最後 9 個收盤換成倒 U（見 `readMockCurve`）；沒有買賣、沒有股利、沒有估計的那一段 */
export function archCurve(p: Performance): Performance {
  const days = p.series.map((x) => x.t)
  if (days.length < 9) return p
  const last = p.series.at(-1)!
  const base = limitHistory(p, days[days.length - 9]!)
  const mv = (i: number) => Math.round(last.market_value + 520_000 * Math.sin((Math.PI * i) / 8))
  return {
    ...base,
    series: base.series.map((x, i) => ({ ...x, market_value: mv(i), net_invested: last.net_invested, twr_index: Number((mv(i) / mv(0)).toFixed(6)) })),
    ...(base.composition ? { composition: { ...base.composition, dividends: [], estimated: [] } } : {}),
  }
}

/**
 * 只留 `first` 那天以後的收盤（`?hist=N`）：和後端存檔晚於持股期間時一樣，第一點是基準收盤（twr_index 1），
 * 說明換成「績效從 … 收盤開始算，之前沒有資料」；剩不到兩點時算不出來（series 空的＋「資料從 … 開始」）。
 */
export function limitHistory(p: Performance, first: string): Performance {
  const series = p.series.filter((x) => x.t >= first)
  if (series.length === p.series.length) return p
  // 留下的日子都在 Yahoo 參考價之後時，那一句（和股票基準只算價格那一句）與 reference_until 也拿掉
  const reference = p.reference_until && first <= p.reference_until ? p.reference_until : null
  const others = (p.notes ?? []).filter((n) => !n.startsWith("績效從 ") && (reference || (!isReferenceNote(n) && !isPriceOnlyNote(n))))
  if (series.length < 2) {
    return {
      ...p, start_date: null, end_date: null, twr: null, xirr: null, max_drawdown: null, volatility: null, series: [],
      benchmark: p.benchmark ? { ...p.benchmark, twr: null } : null, dividends_by_month: [], realized_by_year: [],
      notes: [`${accumulatingNote(first)}；持股期間有幾天沒有收盤價，績效算不出來`],
      ...(p.composition ? { composition: { ...p.composition, dividends: [], months: [], months_estimated: 0 }, fund_rank: null } : {}),
    }
  }
  const base = series[0]!
  const rebased = series.map((x) => ({
    ...x,
    twr_index: Number((x.twr_index / (base.twr_index || 1)).toFixed(6)),
    benchmark_index: x.benchmark_index !== null && base.benchmark_index ? Number((x.benchmark_index / base.benchmark_index).toFixed(6)) : null,
  }))
  const lastPoint = rebased[rebased.length - 1]!
  let peak = 0
  let mdd = 0
  for (const x of rebased) {
    peak = Math.max(peak, x.twr_index)
    mdd = Math.min(mdd, x.twr_index / peak - 1)
  }
  return {
    ...p,
    start_date: base.t,
    twr: lastPoint.twr_index - 1,
    // 幾天的現金流不年化；波動度示範時不重算
    xirr: null,
    max_drawdown: Number(mdd.toFixed(4)),
    volatility: null,
    benchmark: p.benchmark ? { ...p.benchmark, twr: lastPoint.benchmark_index !== null ? lastPoint.benchmark_index - 1 : null } : null,
    series: rebased,
    dividends_by_month: p.dividends_by_month.filter((d) => d.month >= first.slice(0, 7)),
    realized_by_year: p.realized_by_year.filter((r) => r.year >= Number(first.slice(0, 4))),
    notes: [`績效從 ${ymd(base.t)} 收盤開始算，之前沒有資料`, ...others],
    reference_until: reference,
    // 資產組成（原型）：第一點是基準收盤，股利與每個月從它的下一天算起
    ...(p.composition
      ? (() => {
          const { months, skipped } = monthlyBreakdown(rebased.slice(1), { base: rebased[0]!, estimated: p.composition.estimated })
          return {
            composition: { ...p.composition, dividends: p.composition.dividends.filter((d) => d.t > base.t), months, months_estimated: skipped },
            fund_rank: p.fund_rank && p.fund_rank.start > base.t ? p.fund_rank : null,
          }
        })()
      : {}),
  }
}

/** 舊版後端沒有的欄位（`?composition=off`）：買進日期的來由 */
function withoutDateBasis(t: Transaction): Transaction {
  if (t.date_basis === undefined && t.estimated_date === undefined && t.imported_on === undefined) return t
  const { date_basis: _b, estimated_date: _e, imported_on: _i, ...rest } = t
  return rest
}

/**
 * mock 的匯入開關（和後端的 `IMPORT_STATEMENTS` 一樣，兩種匯入同一個開關）：網址 `?import=admins`（只有站方管理員）、
 * `?import=off`（誰都沒有）；`?import=all` 切回預設（所有登入的帳號）。記在 sessionStorage。
 */
export function readMockImport(): MockImportStatements {
  if (typeof window === "undefined") return "all"
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("import")
    if (fromUrl === "all") window.sessionStorage.removeItem("forliosa:mock-import")
    else if (fromUrl === "admins" || fromUrl === "off") window.sessionStorage.setItem("forliosa:mock-import", fromUrl)
    const saved = window.sessionStorage.getItem("forliosa:mock-import")
    if (saved === "admins" || saved === "off") return saved
  } catch {
    // sessionStorage 不可用時使用預設（all）
  }
  return "all"
}

export function readMockDiscussion(): DiscussionOptions {
  if (typeof window === "undefined") return {}
  let mode: string | null = null
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("discuss")
    if (fromUrl === "default") window.sessionStorage.removeItem("forliosa:mock-discuss")
    else if (fromUrl === "named" || fromUrl === "suspended" || fromUrl === "member") window.sessionStorage.setItem("forliosa:mock-discuss", fromUrl)
    mode = window.sessionStorage.getItem("forliosa:mock-discuss")
  } catch {
    // sessionStorage 不可用時使用預設情境
  }
  if (mode === "named") return { publicName: "示範小資" }
  if (mode === "suspended") return { publicName: "示範小資", suspended: true }
  if (mode === "member") return { admin: false }
  return {}
}

const DEFAULT_PREFS: Preferences = {
  color_convention: "tw",
  theme: "system",
  quantity_unit: "lot",
  privacy_mode: false,
  cost_method: "average",
  benchmark: "0050.TW",
  daily_briefing: false,
}

/** 後端 `IMPORT_STATEMENTS` 的三個值：all（預設，所有登入的帳號）、admins（只有站方管理員）、off */
export type MockImportStatements = "all" | "admins" | "off"

export interface MockOptions {
  scenario?: MockScenario
  /** 資料政策（預設 commercial，和後端一樣）：commercial 沒有示範標記，存檔不足處回空＋notes */
  policy?: MockPolicy
  /** 模擬網路延遲（毫秒）；測試時設 0 */
  latency?: [number, number]
  /** 法人觀點：POST 之後多久變成 ready（毫秒）；測試時設 0 */
  analystDelayMs?: number
  /** 是否已登入（預設 true；`?auth=signed-out` 模擬還沒登入） */
  signedIn?: boolean
  /** 台股的市場狀態（預設 closed：最新的收盤價已經進來）；`?market=open|pending|evening|night` 模擬盤中、收盤後與半夜還沒進來 */
  market?: MockMarket
  /** 討論串：示範使用者的公開暱稱、是不是站方管理員、有沒有被停權（預設：沒有暱稱、是管理員、沒有停權） */
  discussion?: DiscussionOptions
  /** 討論串的時鐘（毫秒，預設 Date.now）：頻率限制與暱稱冷卻用實際經過的時間算；測試時換掉就不用等 */
  clock?: () => number
  /**
   * 條款版本（預設：沒有啟用，兩個欄位都是 null）。`current`：後端的 TERMS_VERSION；`accepted`：這個帳號同意過的版本。
   * 兩個不同時登入後會看到「服務條款與隱私權政策已更新」。
   */
  terms?: { current: string; accepted?: string | null; effectiveDate?: string | null; summary?: string | null }
  /** 帳本的歷史只留最後幾個收盤（`?hist=N`，看存檔剛開始時的走勢與績效）；預設全部 */
  history?: number
  /** 只給截圖用的走勢形狀（`?curve=arch`，見 `readMockCurve`）；預設照帳本算 */
  curve?: "arch"
  /** 市場報告的情境（`?mreport=`，見 `mock/market-reports.ts`）；預設 public（對全站公開） */
  reports?: MockReportsScenario
  /**
   * Yahoo 的歷史日線回補在不在（預設 true，和正式環境一樣）：在的話商用模式存檔開始以前的台股日期有「參考收盤」；
   * false 模擬關掉或整批刪掉（`history_backfill drop`），和以前一樣什麼都不寫
   */
  historyBackfill?: boolean
  /** 匯入（匯入對帳單、匯入庫存）開給誰（`?import=`）；預設 all，和後端的 `IMPORT_STATEMENTS` 預設一樣 */
  importStatements?: MockImportStatements
  /** 配置的上限（`?limits=30,50`：單一個股 30%、單一產業 50%）；預設都沒設，和後端一樣 */
  allocationLimits?: AllocationLimits
  /**
   * 資產組成的欄位（原型；績效的 `composition`、`fund_rank`，匯入庫存的 `estimated_date`，交易的 `date_basis`）：
   * 預設 true；false 模擬還沒有這些欄位的後端（`?composition=off`），畫面要和以前一樣
   */
  composition?: boolean
}

/** mock 的資產組成欄位：網址 `?composition=off` 拿掉（模擬舊版後端），`?composition=on` 切回。記在 sessionStorage */
export function readMockComposition(): boolean | undefined {
  if (typeof window === "undefined") return undefined
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("composition")
    if (fromUrl === "on") window.sessionStorage.removeItem("forliosa:mock-composition")
    else if (fromUrl === "off") window.sessionStorage.setItem("forliosa:mock-composition", "off")
    return window.sessionStorage.getItem("forliosa:mock-composition") === "off" ? false : undefined
  } catch {
    return undefined
  }
}

/**
 * mock 的配置上限：網址 `?limits=30,50`（單一個股 30%、單一產業 50%；只設一個時另一個寫 `-`，例如 `?limits=-,40`），
 * `?limits=none` 清掉。記在 sessionStorage（截圖用）。
 */
export function readMockLimits(): AllocationLimits | undefined {
  if (typeof window === "undefined") return undefined
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("limits")
    if (fromUrl === "none") window.sessionStorage.removeItem("forliosa:mock-limits")
    else if (fromUrl && /^(\d+|-),(\d+|-)$/.test(fromUrl)) window.sessionStorage.setItem("forliosa:mock-limits", fromUrl)
    const saved = window.sessionStorage.getItem("forliosa:mock-limits")
    if (!saved) return undefined
    const [h, i] = saved.split(",").map((x) => (x === "-" ? null : Number(x) / 100))
    return { holding: h ?? null, industry: i ?? null }
  } catch {
    return undefined
  }
}

/**
 * 商品搜尋，排序和後端 `MarketData.search` 相同：代號（或完整代號 2330.TW）相同 → 代號開頭 → 名稱相同 → 名稱開頭 → 名稱包含 → 代號包含；
 * 同一級台股在前、代號短的在前、內建清單在收盤檔的 ETF 之前。SEC 的美股只有英文查詢（ASCII、有英文字母）搜得到，
 * 代號完全相同以外都排在最後。
 */
export function searchCatalog(items: MockInstrumentSpec[], q: string): MockInstrumentSpec[] {
  const query = q.trim()
  if (!query) return []
  const qu = query.toUpperCase()
  const english = /^[\x20-\x7e]+$/.test(query) && /[A-Za-z]/.test(query)
  const alt = english ? qu.replace(/\./g, "-") : qu
  const scored: { item: MockInstrumentSpec; key: number[] }[] = []
  for (const item of items) {
    const sec = item.listing === "sec"
    if (sec && !english) continue
    const code = item.code.toUpperCase()
    const name = item.name
    const nameU = name.toUpperCase()
    const rank =
      code === qu || code === alt || item.symbol.toUpperCase() === qu ? 0
      : code.startsWith(qu) || code.startsWith(alt) ? 1
      : name === query || nameU === qu ? 2
      : name.startsWith(query) || nameU.startsWith(qu) ? 3
      : name.includes(query) || nameU.includes(qu) ? 4
      : code.includes(qu) ? 5
      : -1
    if (rank < 0) continue
    scored.push({ item, key: [sec && rank > 0 ? 1 : 0, rank, item.market === "US" ? 1 : 0, item.code.length, item.listing ? 1 : 0] })
  }
  const cmp = (a: number[], b: number[]) => a.reduce((acc, v, i) => acc || v - b[i]!, 0)
  return scored.sort((a, b) => cmp(a.key, b.key) || a.item.code.localeCompare(b.item.code)).map((s) => s.item)
}

export function createMockAdapter(options: MockOptions = {}): ForliosaApi {
  const scenario = options.scenario ?? "default"
  const commercial = (options.policy ?? "commercial") === "commercial"
  const backfill = options.historyBackfill ?? true
  // 資產組成的欄位（原型）：false 模擬舊版後端（`?composition=off`）
  const composition = options.composition ?? true
  const demo = !commercial
  const [minLatency, maxLatency] = options.latency ?? [120, 320]

  let user: User = {
    id: "usr_01JDEMO", email: "demo@forliosa.local", display_name: "示範使用者", avatar_url: null, preferences: { ...DEFAULT_PREFS },
    terms_version_accepted: options.terms ? (options.terms.accepted ?? null) : null,
    terms_version_current: options.terms?.current ?? null,
    terms_effective_date: options.terms?.effectiveDate ?? null,
    terms_summary: options.terms?.summary ?? null,
  }
  /** 匯出的次數（每小時 5 次；mock 不算時間，第 6 次起擋下） */
  let exports = 0
  /** 配置的上限（使用者偏好裡的 `allocation_limits`；`GET /me` 不列出，只透過配置的端點讀寫） */
  let allocationLimits: AllocationLimits = { holding: null, industry: null, ...options.allocationLimits }
  let signedIn = options.signedIn ?? true
  let accounts: Account[] = scenario === "empty" ? [] : ACCOUNTS.map((a) => ({ ...a }))
  // 資產組成原型：`?composition=off` 時不套用匯入庫存的估計買入日（和現在的示範帳本一樣）；
  // `?mock=cashout` 本金是負的、`?mock=loss` 一直虧、`?mock=cross` 賺轉虧（在示範帳本上多幾筆；分享、討論串照預設）
  const extra = scenario === "cashout" || scenario === "loss" || scenario === "cross" || scenario === "lastday" ? scenario : undefined
  const storeScenario = scenario === "cashout" || scenario === "loss" || scenario === "cross" || scenario === "lastday" ? "default" : scenario
  let txns: Transaction[] = scenario === "empty" ? [] : seedTransactions({ importedLots: composition, extra })
  if (scenario === "stress") {
    txns.push({
      id: "txn_stress", account_id: ACCOUNTS[0]!.id, symbol: STRESS_INSTRUMENT.symbol, type: "buy", trade_date: "2025-06-02",
      quantity: 9_876_543, price: 13_420, amount: 132_543_207_060, fee: 52_998_000, tax: 0, health_insurance: 0,
      currency: "TWD", is_day_trade: false, note: "壓力測試：極端金額與超長名稱", source: "manual", created_at: "2025-06-02T14:00:00+08:00",
    })
    txns.sort((a, b) => a.trade_date.localeCompare(b.trade_date))
  }
  let nextId = 90000
  // 股利自動入帳：使用者刪掉或改過的自動入帳股利（不再產生）
  const skips = new Set<string>()
  /** 交易變更之後重算自動入帳的股利（後端在同一個請求裡做） */
  const resync = () => {
    txns = syncAutoDividends(txns, { accounts, skips, today: MOCK_TODAY })
  }
  let watch: string[] = scenario === "empty" ? [] : ["2382.TW", "2308.TW", "2881.TW"]
  const recurring = createRecurringStore(scenario === "empty" ? [] : seedPlans(ACCOUNTS[0]!.id), () => accounts)
  const analyst = createAnalystStore({ delayMs: options.analystDelayMs })

  // ── 分享（M5）：爸爸的帳本（授權查看、他在群組的分享都從這裡算）與我的分享內容 ──
  const dadTxns = seedDadTransactions()
  const memo = <T,>(fn: () => T) => {
    let v: T | undefined
    return () => (v ??= fn())
  }
  /** 只記 manual／import／ai_draft 的買賣（股利、自動入帳、快照不列） */
  const rawTrades = (list: Transaction[]): RawTrade[] =>
    list
      .filter((t) => (t.type === "buy" || t.type === "sell") && t.symbol && ["manual", "import", "ai_draft"].includes(t.source))
      .map((t) => ({ txn_id: t.id, side: t.type as "buy" | "sell", symbol: t.symbol!, trade_date: t.trade_date, quantity: t.quantity ?? 0, price: t.price ?? 0, currency: t.currency, created_at: t.created_at }))
  const periodReturns = (list: Transaction[]) => {
    const summary = buildSummary(list, undefined, commercial)
    const holdings = buildHoldings(list, undefined, commercial)
    // 沒有收盤價的持股（商用模式：還沒抓到收盤價的美股）不算進期間報酬，和帳本的「今日」同一條規則（2026-11-14）
    const unpriced = new Set(commercial ? holdings.filter((h) => h.price === null).map((h) => h.symbol) : [])
    const priced = unpriced.size ? list.filter((t) => !t.symbol || !unpriced.has(t.symbol)) : list
    // 存檔開始以前：Yahoo 回補開著時用參考價算（產品負責人 2026-11-18），從回補的第一天起
    const opts = { isDemo: !commercial, ...(commercial ? { minStart: backfill ? BACKFILL_START : ARCHIVE_START } : {}) }
    return {
      day: summary.day_change_pct,
      month: buildPerformance(priced, "MTD", undefined, "0050.TW", opts).twr,
      year: buildPerformance(priced, "YTD", undefined, "0050.TW", opts).twr,
      total: summary.total_return_pct,
      excludes_unpriced: unpriced.size > 0,
    }
  }
  const sharedHoldings = (list: Transaction[]) =>
    buildHoldings(list, undefined, commercial)
      .filter((h) => h.weight > 0)
      .sort((a, b) => b.weight - a.weight)
      .map((h) => ({ symbol: h.symbol, name: h.name, weight: h.weight }))
  const sharedAmounts = (list: Transaction[]) => {
    const s = buildSummary(list, undefined, commercial)
    return { market_value: s.market_value, day_change: s.day_change, total_pnl: s.total_pnl }
  }
  const dadReturns = memo(() => periodReturns(dadTxns))
  const dad: MemberSource = {
    returns: dadReturns,
    holdings: memo(() => sharedHoldings(dadTxns)),
    amounts: memo(() => sharedAmounts(dadTxns)),
    trades: memo(() => rawTrades(dadTxns)),
    week: (w) => ({ "2026-11-02": 0.0121, "2026-10-26": 0.0058 })[w] ?? null,
  }
  const mine: MemberSource = {
    returns: () => periodReturns(txns),
    holdings: () => sharedHoldings(txns),
    amounts: () => sharedAmounts(txns),
    trades: () => rawTrades(txns),
    // 沒有收盤價的持股不算進週報酬（和排行同一條規則）
    week: (w) => ({ "2026-11-02": 0.0097, "2026-10-26": 0.0043 })[w] ?? null,
  }
  const sharing = createSharingStore(
    {
      me: () => ({ user_id: user.id, display_name: user.display_name, avatar_url: user.avatar_url ?? null }),
      signedIn: () => signedIn,
      commercial,
      backfill,
      myAccounts: () => accounts,
      mine,
      dad,
      dadAccounts: DAD_ACCOUNTS,
      origin: () => (typeof window === "undefined" ? "http://localhost:5173" : window.location.origin),
      marketReportsPublic: () => reports.publicMode(),
    },
    storeScenario,
  )

  /** 示範的「今天」：平常是最後一個收盤日；`?market=open|pending` 是它的下一個交易日（本週事項從這一天起算） */
  const today = mockToday(options.market)
  /** 還在進行的定期定額：和後端、前端的 planStatus 同一個判斷（啟用中、結束日沒過、還有下一次扣款日） */
  const runningPlan = (p: RecurringPlan) => p.active && (!p.end_date || p.end_date >= today) && !!p.next_date

  // ── 討論串：時間從示範資料的「現在」起算，加上開啟後實際經過的時間（10 秒間隔、7 天冷卻都照真的時間） ──
  const clock = options.clock ?? Date.now
  const clockStart = clock()
  const discussionNow = () => mockMarketNow(options.market).getTime() + (clock() - clockStart)
  const discussions = createDiscussionStore(
    {
      me: () => ({ user_id: user.id, display_name: user.display_name, avatar_url: user.avatar_url ?? null }),
      signedIn: () => signedIn,
      myGroupRoles: () => sharing.myGroupRoles(),
      groupRoster: (id) => sharing.groupRoster(id),
      now: discussionNow,
    },
    storeScenario,
    options.discussion,
  )
  // ── 管理後台：和討論串的站方管理同一個判斷（沒登入 401、不是站方管理員 404） ──
  const admin = createAdminStore({
    requireAdmin: () => {
      if (!signedIn) throw new ApiError(401, "unauthorized", "請先登入")
      if (!discussions.meFields().is_admin) throw new ApiError(404, "not_found", "找不到這個頁面")
    },
  })
  // ── 市場報告：登入的人都看得到；回補的只有站方管理員（和討論串的站方管理同一個判斷） ──
  const reports = createMarketReportsStore(
    { now: () => mockMarketNow(options.market), isAdmin: () => discussions.meFields().is_admin, signedIn: () => signedIn, demo },
    options.reports,
  )
  /**
   * `User`：個人資料多了 public_name、is_admin、public_posting_suspended_until（`GET /me`、開發登入、PATCH 都有）。
   * 方案：示範使用者是會員；兩種匯入照 `importStatements`（`?import=`），預設和後端的 `IMPORT_STATEMENTS=all` 一樣所有人都有
   * （2026-11-17：會員和免費帳號只差 AI 額度與收盤簡報）
   */
  const importOpen = () => {
    const mode = options.importStatements ?? "all"
    return mode === "all" || (mode === "admins" && discussions.meFields().is_admin)
  }
  /** 和後端的 `require_access` 一樣：讀檔（匯入對帳單、匯入庫存）前先看開關，沒開放 403 */
  const requireImport = (message: string) => {
    if (!importOpen()) throw new ApiError(403, "import_not_enabled", message)
  }
  const me = (): User => {
    const fields = discussions.meFields()
    return {
      ...user,
      ...fields,
      // 站方管理員算會員、沒有到期日；`?discuss=member`（不是管理員）是開通到 12/31 的會員（設定頁「會員，到 12/31」）
      plan: { tier: "member", until: fields.is_admin ? null : "2026-12-31", deep_search: true, daily_briefing: true, statement_import: importOpen() },
    }
  }

  /**
   * 這次請求讀的是誰的帳本：平常是我；查看模式是授權者，而且只有授權範圍內的帳戶
   * （伺服器的分享投影；`account_id` 超出範圍回 404）。
   */
  const ledger = (accountId?: string | null): { accounts: Account[]; txns: Transaction[]; viewing: boolean } => {
    const viewAs = viewAsId()
    if (!viewAs) return { accounts, txns, viewing: false }
    const { owner, accountIds } = sharing.viewAsOwner(viewAs)
    const ownerAccounts = owner.user_id === "usr_dad" ? DAD_ACCOUNTS : []
    const scoped = ownerAccounts.filter((a) => accountIds === "all" || accountIds.includes(a.id))
    if (accountId && !scoped.some((a) => a.id === accountId)) throw new ApiError(404, "not_found", "找不到帳戶")
    const ids = new Set(scoped.map((a) => a.id))
    return { accounts: scoped, txns: (owner.user_id === "usr_dad" ? dadTxns : []).filter((t) => ids.has(t.account_id)), viewing: true }
  }

  const wait = <T>(value: T | (() => T)): Promise<T> =>
    new Promise((resolve, reject) => {
      const ms = minLatency + Math.random() * Math.max(maxLatency - minLatency, 0)
      setTimeout(() => {
        try {
          resolve(typeof value === "function" ? (value as () => T)() : value)
        } catch (e) {
          reject(e)
        }
      }, ms)
    })

  const spec = (symbol: string): MockInstrumentSpec => {
    const s = findInstrument(symbol)
    if (!s || (s === STRESS_INSTRUMENT && scenario !== "stress")) throw new ApiError(404, "not_found", "找不到商品")
    return s
  }
  const visible = () => INSTRUMENTS.filter((i) => scenario === "stress" || i !== STRESS_INSTRUMENT)
  /**
   * 商用模式沒有收盤價的美股（只有 SEC 代號表認得、模擬還沒抓到收盤價的）：`/quote` 404。
   * 和合約一樣，美股收盤價開著時 `has_quote` 一律是 true（搜尋結果分不出還沒抓到的）
   */
  const noQuote = (s: MockInstrumentSpec) => commercial && s.market === "US" && !hasUsCloses(s)
  /** 商用模式有 Databento 收盤價的美股：日線是紐約的交易日（最後一根是 `US_SESSION`） */
  const usPriced = (s: MockInstrumentSpec) => commercial && hasUsCloses(s)
  const candlesOf = (s: MockInstrumentSpec) => (usPriced(s) ? usCandles(s) : dailyCandles(s))
  /** 日線的顯名聲明（商用模式） */
  const priceSource = (s: MockInstrumentSpec) => (s.market === "US" ? DATABENTO_ATTRIBUTION : sourceOf(`${s.market === "TPEX" ? "tpex" : "twse"}-openapi/price`))
  const strip = (s: MockInstrumentSpec) => ({
    symbol: s.symbol, code: s.code, name: s.name, market: s.market, type: s.type, currency: s.currency, industry: s.industry,
    // mock 的商用模式模擬美股收盤價開著（顯名清單有 Databento）、個人模式是示範資料：都有報價
    has_quote: true,
  })
  /** 名稱的出處（沒有其他公司資料時）：收盤檔的 ETF、SEC 的代號表 */
  const listingSources = (s: MockInstrumentSpec): string[] =>
    s.listing === "sec" ? [sourceOf("sec-edgar/tickers")] : [sourceOf(s.market === "TPEX" ? "tpex-openapi/price" : "twse-openapi/price")]
  const quoteOf = (s: MockInstrumentSpec): Quote => {
    if (noQuote(s)) throw new ApiError(404, "not_found", "沒有報價")
    const last = candlesOf(s).at(-1)!
    const ref = referencePrice(s)
    const limits = limitsOf(s)
    const us = usPriced(s)
    return {
      symbol: s.symbol, price: s.price, prev_close: s.prev_close,
      change: Math.round((s.price - ref) * 100) / 100,
      change_pct: Math.round((s.price / ref - 1) * 10000) / 10000,
      open: last.o, high: last.h, low: last.l, volume: last.v,
      // 美股：紐約 16:00 收盤（台北隔天清晨）；trade_date 是紐約的日期（和後端相同，商用模式才有）
      as_of: s.market === "US" ? US_AS_OF : MOCK_AS_OF,
      ...(commercial ? { trade_date: us ? US_SESSION : MOCK_TODAY } : {}),
      is_realtime: false, is_demo: demo, source: commercial ? (us ? "databento-equs" : s.market === "TPEX" ? "tpex-openapi" : "twse-openapi") : "demo",
      // 美股沒有參考價與漲跌停（Databento 的收盤只有開高低收量）
      reference_price: us ? null : ref,
      limit_up: limits?.up ?? null,
      limit_down: limits?.down ?? null,
    }
  }
  const tracked = (symbol: string) => watch.includes(symbol) || buildHoldings(txns).some((h) => h.symbol === symbol)
  const holdingsNow = (accountId?: string) => buildHoldings(ledger(accountId).txns, accountId, commercial)
  // 每日收盤簡報：只讀自己的帳本（不跟著查看模式），事實和帳本頁、本週事項是同一組數字
  // 和後端相同：簡報講的是台股那一天，漲跌只談台股（美股的收盤是紐約前一天）——美股的持股照算在持股數裡，但不列進漲跌
  const briefings = createMockBriefings(MOCK_TODAY, () => {
    const mine = buildHoldings(txns, undefined, commercial)
    const movers = commercial ? mine.map((h) => (h.market === "US" ? { ...h, day_change_pct: null } : h)) : mine
    const watched = watch.map((symbol) => {
      const w = spec(symbol)
      return { symbol: w.symbol, code: w.code, name: w.name, market: w.market, type: w.type, quote: commercial && w.market === "US" ? null : quoteOf(w) }
    })
    return buildBriefingFacts(
      buildSummary(txns, undefined, commercial), movers, watched,
      buildUpcoming(mine, findInstrument, 7, recurring.upcoming(today, addDays(today, 7)), commercial, today), demo,
    )
  })
  /** 商用模式：回應裡最早的資料不早於存檔起點（美股是 Databento 的 2024-07-01）；區間更早時加上「資料從 … 開始」 */
  const clip = <T extends { t: string }>(rows: T[], from: string, since = ARCHIVE_START): { rows: T[]; notes: string[] } =>
    commercial && from < since ? { rows: rows.filter((r) => r.t >= since), notes: [accumulatingNote(since)] } : { rows, notes: [] }
  /**
   * 存檔開始以前的日子用 Yahoo 參考價算時（回補開著；產品負責人 2026-11-18），和後端一樣多一句說明與 `reference_until`：
   * 區間裡最後一個用參考價估台股市值的日子（存檔開始前一天以前、當天有市值）。美股沒有回補。
   */
  const withReference = (p: Performance, mine: Transaction[], benchmark: string): Performance => {
    const tw = backfill && mine.some((t) => t.trade_date < ARCHIVE_START && findInstrument(t.symbol!)?.market !== "US")
    const until = tw ? (p.series.filter((x) => x.t < ARCHIVE_START && x.market_value > 0).at(-1)?.t ?? null) : null
    // 股票基準（0050）存檔開始以前也用參考價，但沒有除息資料：那段只算價格，和後端一樣多一句（2026-11-18 審查）
    const stock = backfill && !benchmark.startsWith("^") && findInstrument(benchmark)?.market !== "US" && p.benchmark?.twr != null
    const benchUntil = stock ? (p.series.filter((x) => x.t < ARCHIVE_START).at(-1)?.t ?? null) : null
    if (!until && !benchUntil) return { ...p, reference_until: null }
    const notes = p.notes ?? []
    const clip = notes.filter((n) => n.startsWith("績效從 "))
    const last = [until, benchUntil].filter((d): d is string => !!d).sort().at(-1)!
    const added = [referenceNote(last), ...(benchUntil ? [priceOnlyNote(p.benchmark!.name, benchUntil)] : [])]
    return { ...p, reference_until: until, notes: [...clip, ...added, ...notes.filter((n) => !clip.includes(n))] }
  }
  /**
   * 商用模式的績效（和後端相同）：只算每一檔持股都有收盤價的日子。台股的收盤從存檔起點（ARCHIVE_START）開始
   * （Yahoo 回補開著時從回補的第一天 BACKFILL_START，存檔以前是參考價）、美股從 2024-07-01（Databento）開始：
   * 持股期間早於這些日子時，從「每一檔都有收盤價」的第一天收盤開始算。
   * 現在還持有沒有收盤價的美股（剛加入、還沒抓到）就算不出來：「MSFT：還沒有收盤價，績效算不出來」。
   */
  const commercialPerformance = (txns: Transaction[], range: Parameters<typeof buildPerformance>[1], accountId: string | undefined, benchmark: string) => {
    const mine = txns.filter((t) => t.symbol && (!accountId || t.account_id === accountId))
    const symbols = [...new Set(mine.map((t) => t.symbol!))].sort()
    const firstTrade = (sym: string) => mine.find((t) => t.symbol === sym)!.trade_date
    const twStart = backfill ? BACKFILL_START : ARCHIVE_START
    const startOf = (sym: string) => (findInstrument(sym)!.market === "US" ? US_ARCHIVE_START : twStart)
    const unpriced = buildHoldings(txns, accountId, true).filter((h) => h.price === null).map((h) => h.symbol).sort()
    const priced = symbols.filter((sym) => !unpriced.includes(sym) && !noQuote(findInstrument(sym)!))
    // 日期軸從有收盤價的第一天開始（後端：持有過的商品實際有收盤的日子）；之前的交易都記在那一天
    const inception = mine.map((t) => t.trade_date).sort()[0]
    const firstClose = priced.map(startOf).sort()[0]
    const axisStart = inception && firstClose ? (inception > firstClose ? inception : firstClose) : null
    const empty = buildPerformance([], range, accountId, benchmark, { isDemo: false, composition })
    if (unpriced.length > 0) {
      // 持股期間有幾天台股沒有收盤價（台股的存檔起點晚於日期軸的第一天）時，後端多一句「資料從 … 開始；…」
      const twGap = !!axisStart && axisStart < twStart && priced.some((sym) => startOf(sym) === twStart && firstTrade(sym) < twStart)
      return {
        ...empty, start_date: null, end_date: null, series: [],
        notes: [`${unpriced.join("、")}：還沒有收盤價，績效算不出來`, ...(twGap ? [`${accumulatingNote()}；持股期間有幾天沒有收盤價，績效算不出來`] : [])],
        reference_until: null,
      }
    }
    // 每一檔都有收盤價的第一天：持有時還沒有收盤價的商品，從它的收盤開始那天起；日期軸本身的第一天也是
    const minStart = [axisStart ?? twStart, ...priced.filter((sym) => firstTrade(sym) < startOf(sym)).map(startOf)].sort().at(-1)!
    const full = buildPerformance(txns, range, accountId, benchmark, { isDemo: false, composition })
    if (!full.start_date || full.start_date >= minStart) return withReference({ ...full, notes: [] }, mine, benchmark)
    const clipped = buildPerformance(txns, range, accountId, benchmark, { isDemo: false, minStart, composition })
    const bench =
      benchmark === "^TAIEXTR"
        ? {
            benchmark: clipped.benchmark ? { ...clipped.benchmark, twr: null } : null,
            series: clipped.series.map((p) => ({ ...p, benchmark_index: null })),
            // 指數存檔以前沒有資料：每個月和基準的差距也算不出來
            ...(clipped.composition ? { composition: { ...clipped.composition, months: clipped.composition.months.map((m) => ({ ...m, benchmark_twr: null })) } } : {}),
          }
        : {}
    return withReference({ ...clipped, ...bench, notes: [`績效從 ${ymd(clipped.start_date!)} 收盤開始算，之前沒有資料`, ...(benchmark === "^TAIEXTR" ? [INDEX_NOTE] : [])] }, mine, benchmark)
  }
  const sortTxns = () =>
    txns.sort((a, b) => (a.trade_date === b.trade_date ? a.id.localeCompare(b.id) : a.trade_date.localeCompare(b.trade_date)))

  const rangeFrom = (range: HistoryRange): string => {
    switch (range) {
      case "5D": return addDays(MOCK_TODAY, -7)
      case "1M": return addDays(MOCK_TODAY, -31)
      case "6M": return addDays(MOCK_TODAY, -183)
      case "YTD": return `${MOCK_TODAY.slice(0, 4)}-01-01`
      case "1Y": return addDays(MOCK_TODAY, -365)
      case "5Y": return addDays(MOCK_TODAY, -1826)
      case "MAX": return "0000-01-01"
    }
  }

  // 匯入對帳單與匯入庫存：讀檔回示範的對帳單、庫存畫面；一次寫入、整批復原（和後端一樣排序、重算自動入帳的股利）
  const imports = createImportStore({
    accounts: () => accounts,
    txns: () => txns,
    commit: (next) => {
      txns = next
      sortTxns()
      resync()
      return txns
    },
    // 以券商為準：和 deleteHolding 同一個寫法，刪掉這個帳戶這幾檔的略過紀錄
    dropSkips: (accountId, symbols) => {
      for (const sym of symbols) for (const k of [...skips]) if (k.startsWith(`${accountId}|${sym}|`)) skips.delete(k)
    },
    today,
  })

  /** AI 讀檔（匯入對帳單、匯入庫存）：示範縮短成 1.5 秒左右；取消時照真的 fetch 一樣丟 AbortError */
  const aiRead = <T,>(run: () => T, signal?: AbortSignal): Promise<T> =>
    new Promise((resolve, reject) => {
      const abort = () => reject(new DOMException("讀取已取消", "AbortError"))
      if (signal?.aborted) return abort()
      const ms = minLatency === 0 && maxLatency === 0 ? 0 : 1200 + Math.random() * 600
      const t = setTimeout(() => {
        signal?.removeEventListener("abort", onAbort)
        try {
          resolve(run())
        } catch (e) {
          reject(e)
        }
      }, ms)
      const onAbort = () => {
        clearTimeout(t)
        abort()
      }
      signal?.addEventListener("abort", onAbort, { once: true })
    })

  const base: ForliosaApi = {
    kind: "mock",
    devLogin: (body) =>
      wait(() => {
        signedIn = true
        user = { ...user, email: body.email, display_name: body.display_name ?? body.email.split("@")[0]! }
        return me()
      }),
    logout: () =>
      wait(() => {
        signedIn = false
      }),
    getMe: () =>
      wait(() => {
        if (!signedIn) throw new ApiError(401, "unauthorized", "請先登入")
        return me()
      }),
    exportMe: () =>
      wait(() => {
        if (!signedIn) throw new ApiError(401, "unauthorized", "請先登入")
        if (++exports > 5) throw new ApiError(429, "rate_limited", "匯出太頻繁，請稍後再試", { retry_after_seconds: 1800 })
        // 和後端同一個形狀（docs/api-contract.md「匯出我的資料」）；示範資料只放帳本的部分
        return {
          exported_at: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
          format_version: 1,
          disclaimer: DISCLAIMER.short,
          profile: { id: user.id, email: user.email, display_name: user.display_name, public_name: me().public_name ?? null, preferences: user.preferences, terms_version_accepted: user.terms_version_accepted ?? null },
          accounts,
          transactions: txns,
          recurring_plans: [],
          watchlist: [],
          auto_dividend_skips: [],
          ai: { threads: [], drafts: [] },
          groups: [],
          group_comments: [],
          group_reactions: [],
          delegations: { given: [], received: [] },
          discussions: { topics: [], replies: [], reactions: [] },
        }
      }),
    deleteMe: (confirm) =>
      wait(() => {
        if (!signedIn) throw new ApiError(401, "unauthorized", "請先登入")
        if (confirm !== ACCOUNT_DELETE_CONFIRMATION) throw new ApiError(422, "validation_error", `請輸入「${ACCOUNT_DELETE_CONFIRMATION}」確認`)
        signedIn = false
        accounts = []
        txns = []
      }),
    acceptTerms: (version) =>
      wait(() => {
        if (!signedIn) throw new ApiError(401, "unauthorized", "請先登入")
        if (!user.terms_version_current || version !== user.terms_version_current) throw new ApiError(409, "terms_version_mismatch", "條款版本已經更新，請重新整理後再確認")
        user = { ...user, terms_version_accepted: version }
        return me()
      }),
    updatePreferences: (patch) =>
      wait(() => {
        user = { ...user, preferences: { ...user.preferences, ...patch } }
        return me()
      }),

    listAccounts: () => wait(() => ledger().accounts),
    createAccount: (body) =>
      wait(() => {
        // 與後端的預設相同（費率欄位留著，但手續費不再自動算）
        const usd = body.currency === "USD"
        const acc: Account = {
          fee_rate: usd ? 0.001 : 0.001425,
          fee_discount: 1,
          min_fee: usd ? 0 : 20,
          min_fee_odd_lot: usd ? 0 : 1,
          ...body,
          id: `acc_${++nextId}`,
          created_at: new Date().toISOString(),
        }
        accounts = [...accounts, acc]
        return acc
      }),
    updateAccount: (id, patch) =>
      wait(() => {
        const found = accounts.find((a) => a.id === id)
        if (!found) throw new ApiError(404, "not_found", "找不到帳戶")
        const next = { ...found, ...patch }
        accounts = accounts.map((a) => (a.id === id ? next : a))
        return next
      }),
    deleteAccount: (id) =>
      wait(() => {
        if (!accounts.some((a) => a.id === id)) throw new ApiError(404, "not_found", "找不到帳戶")
        accounts = accounts.filter((a) => a.id !== id)
        txns = txns.filter((t) => t.account_id !== id)
        for (const k of [...skips]) if (k.startsWith(`${id}|`)) skips.delete(k)
        // 和後端相同（外鍵 ON DELETE CASCADE）：這個帳戶的定期定額一起刪除
        for (const p of recurring.list(id)) recurring.remove(p.id)
      }),
    searchInstruments: (q) => wait(() => searchCatalog(visible(), q).slice(0, 20).map(strip)),
    getInstrument: (symbol) =>
      wait(() => {
        const s = spec(symbol)
        // 商用模式不提供 shioaji-data 的 AI 研究欄位（簡介、產業鏈、題材；授權待定），美股只有商品清單
        if (commercial) {
          const us = s.market === "US"
          return {
            ...strip(s), summary: null, chain_stage: null, themes: [],
            shares_outstanding: us ? null : s.shares_outstanding, market_cap: us ? null : s.market_cap,
            data_sources: s.listing ? listingSources(s) : us ? ["內建商品清單"] : [sourceOf("shioaji-data/official")], is_demo: false,
          }
        }
        return {
          ...strip(s), summary: s.summary, chain_stage: s.chain_stage, themes: s.themes,
          shares_outstanding: s.shares_outstanding, market_cap: s.market_cap, data_sources: s.listing === "sec" ? listingSources(s) : s.data_sources,
          is_demo: true,
        }
      }),
    getQuote: (symbol) => wait(() => quoteOf(spec(symbol))),
    // 批次報價：沒有報價的代號（商用模式還沒有收盤價的美股）直接略過
    getDailyClose: (symbol, date) =>
      wait(() => {
        // 和後端一樣先看自己存檔的官方收盤：商用模式下存檔開始以前、還沒有收盤價的美股都沒有；
        // 美股的收盤（Databento）從 2024-07-01 起，日期是紐約的交易日。
        // 存檔開始以前的台股日期：Yahoo 回補在的話是「參考收盤」（reference: true，產品負責人 2026-11-17）；回補沒有美股
        const s = spec(symbol)
        const archived = !commercial || (hasUsCloses(s) ? date >= US_ARCHIVE_START : s.market !== "US" && date >= ARCHIVE_START)
        const backfilled = commercial && backfill && s.market !== "US" && date < ARCHIVE_START && date >= BACKFILL_START
        const close = archived || backfilled ? (candlesOf(s).find((c) => c.t === date)?.c ?? null) : null
        const reference = !archived && backfilled && close !== null
        return { symbol: s.symbol, date, close, currency: s.market === "US" ? "USD" : "TWD", reference, note: reference ? REFERENCE_NOTE : null }
      }),
    getQuotes: (symbols) => wait(() => symbols.map((x) => spec(x)).filter((x) => !noQuote(x)).map(quoteOf)),
    getHistory: (symbol, range, opts) =>
      wait((): History => {
        if (commercial && symbol.startsWith("^")) return { symbol, interval: "1d", candles: [], is_demo: false, sources: [], notes: [INDEX_NOTE] }
        // 指數（^TAIEXTR）：示範資料以 0050 的走勢代替
        const s = symbol.startsWith("^") ? spec(mockBenchmark(symbol).proxy) : spec(symbol)
        // 還沒有收盤價的美股：「還沒有資料」（和後端 coverage.since_note 相同）
        if (noQuote(s)) return { symbol: s.symbol, interval: "1d", candles: [], is_demo: false, sources: [], notes: [NO_DATA_NOTE] }
        const from = rangeFrom(range)
        // 選買入日（資產組成原型，`prices=as_traded`）：台股存檔以前用 Yahoo 回補、換算回當時的成交價（示範的日線本來就是），
        // 美股從 2024/7/1 起（Databento）；回補關掉時和一般的走勢一樣從存檔開始
        // `pick_from`（和後端一樣，`until`＝匯入那天）：那天以前最近一次股票分割、減資、配股——選日期的畫面不給選更早的日子
        const pickFrom = opts?.asTraded && composition ? { pick_from: shareChangeOn(s.symbol, opts.until && opts.until < MOCK_TODAY ? opts.until : MOCK_TODAY) } : {}
        if (opts?.asTraded && composition && commercial && backfill && s.market !== "US") {
          const rows = candlesOf(s).filter((c) => c.t >= (from > BACKFILL_START ? from : BACKFILL_START))
          const refUntil = rows.filter((c) => c.t < ARCHIVE_START).at(-1)?.t
          return {
            symbol: s.symbol, interval: "1d", candles: rows, is_demo: false,
            sources: [priceSource(s), YAHOO_HISTORY_LABEL], notes: refUntil ? [`${ymd(refUntil)} 以前的股價來自 Yahoo Finance，不是官方資料`] : [],
            ...pickFrom,
          }
        }
        const { rows, notes } = clip(candlesOf(s).filter((c) => c.t >= from), from, s.market === "US" ? US_ARCHIVE_START : ARCHIVE_START)
        return {
          symbol: symbol.startsWith("^") ? symbol : s.symbol, interval: "1d", candles: rows, is_demo: demo,
          sources: commercial ? [priceSource(s)] : [], notes,
          ...pickFrom,
        }
      }),
    getValuation: (symbol, range = "5Y") =>
      wait(() => {
        const s = spec(symbol)
        const from = addDays(MOCK_TODAY, -Math.round((range === "MAX" ? 6 : 5) * 365.25))
        const clipped = clip(valuationSeries(s, range === "MAX" ? 6 : 5), from)
        // 美股沒有本益比、股價淨值比的來源（SEC 的 EPS 只在財務分頁）：沒有估值序列
        const series = commercial && s.market === "US" ? [] : clipped.rows
        const last = series.at(-1)
        const pers = series.map((p) => p.per).filter((x): x is number => x !== null)
        const currentPer = last?.per ?? null
        return {
          symbol: s.symbol,
          per_multiples: commercial && s.market === "US" ? [] : (s.per_multiples ?? []),
          pbr_multiples: commercial && s.market === "US" ? [] : (s.pbr_multiples ?? []),
          series,
          current: {
            per: currentPer,
            pbr: last?.pbr ?? null,
            dividend_yield: last?.dividend_yield ?? null,
            per_percentile_5y:
              currentPer === null || pers.length === 0
                ? null
                : Math.round((pers.filter((p) => p <= currentPer).length / pers.length) * 100) / 100,
          },
          notes: commercial
            ? s.market === "US"
              ? [US_VALUATION_NOTE]
              : [...clipped.notes, ...(s.type === "etf" ? ["ETF 沒有每股盈餘與每股帳面淨值，不提供本益比與股價淨值比區間"] : ["本益比、股價淨值比、殖利率為證交所／櫃買中心公布值；EPS = 收盤價 ÷ 本益比"])]
            : s.type === "etf" ? ["ETF 沒有每股盈餘與每股帳面淨值，不提供本益比與股價淨值比區間"] : ["示範資料：EPS、淨值與倍數皆為模擬"],
          is_demo: demo,
        }
      }),
    getRevenue: (symbol) => wait(() => monthlyRevenue(spec(symbol))),
    // 商用模式的股利歷史只有存檔以來的除權息預告
    getDividends: (symbol) =>
      wait(() => {
        const rows = dividendRecords(spec(symbol)).map((d) => ({ ...d, is_demo: demo }))
        if (!commercial) return rows
        return spec(symbol).market === "US" ? [] : rows.filter((d) => (d.ex_dividend_date ?? "") >= ARCHIVE_START)
      }),
    getOverview: (symbol) => wait(() => buildOverview(spec(symbol), commercial)),
    getIntraday: (symbol) => wait(() => buildIntraday(spec(symbol), tracked(spec(symbol).symbol), commercial)),
    getChips: (symbol, range = "3M") => wait(() => buildChips(spec(symbol), range, commercial)),
    getFinancials: (symbol, period = "quarterly") => wait(() => buildFinancials(spec(symbol), period, commercial)),
    getEvents: (symbol, mine = false) =>
      wait(() => {
        const s = spec(symbol)
        const all = buildEvents(s, holdingsNow().find((h) => h.symbol === s.symbol), commercial)
        return mine ? all.filter((e) => e.mine) : all
      }),
    getNews: (symbol) => wait(() => buildNews(spec(symbol), commercial).filter((n) => n.category !== "media" || !admin.hides(n.url))),
    getRelated: (symbol) => wait(() => buildRelated(spec(symbol), user.preferences.benchmark)),
    getCompany: (symbol) => wait(() => buildCompany(spec(symbol))),
    getPosition: (symbol) => wait(() => buildPosition(spec(symbol), ledger().txns, commercial)),
    getPositionHistory: (symbol) => wait(() => positionHistory(ledger().txns, spec(symbol).symbol)),
    // 沒有報價時不判斷（和後端相同）
    getWhy: (symbol) =>
      wait(() => {
        const s = spec(symbol)
        return noQuote(s) ? { show: false, headline: null, reasons: [], as_of: null, trade_date: null, sources: [] } : buildWhy(s, commercial)
      }),

    getWatchlist: () =>
      wait(() =>
        watch.map((symbol) => {
          const s = spec(symbol)
          if (commercial) {
            // 沒有盤中來源：迷你走勢是最近 20 個收盤（sparkline_interval = 1d；美股是紐約的交易日）
            const none = noQuote(s)
            return {
              symbol: s.symbol, name: s.name, quote: none ? null : quoteOf(s),
              sparkline: none ? [] : candlesOf(s).slice(-20).map((c) => ({ t: c.t, price: c.c })),
              sparkline_interval: "1d" as const, sources: none ? [] : [priceSource(s)], is_demo: false,
            }
          }
          const intraday = buildIntraday(s, true)
          const step = Math.max(1, Math.floor(intraday.points.length / 48))
          return {
            symbol: s.symbol,
            name: s.name,
            quote: quoteOf(s),
            sparkline: intraday.points.filter((_, i) => i % step === 0 || i === intraday.points.length - 1).map((p) => ({ t: p.t, price: p.price })),
            sparkline_interval: "1m" as const,
            is_demo: true,
          }
        }),
      ),
    addWatch: (symbol) =>
      wait(() => {
        const s = spec(symbol)
        if (!watch.includes(s.symbol)) watch = [...watch, s.symbol]
      }),
    removeWatch: (symbol) =>
      wait(() => {
        watch = watch.filter((x) => x !== spec(symbol).symbol)
      }),

    listTransactions: (query) =>
      wait(() => {
        // 與後端相同：每頁最多 200 筆
        if ((query.limit ?? 50) > 200) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：筆數")
        const filtered = ledger(query.account_id).txns
          .filter((t) => !query.account_id || t.account_id === query.account_id)
          .filter((t) => !query.symbol || t.symbol === query.symbol)
          .filter((t) => !query.type || t.type === query.type)
          .filter((t) => !query.from || t.trade_date >= query.from)
          .filter((t) => !query.to || t.trade_date <= query.to)
          .slice()
          .reverse()
        const offset = query.cursor ? Number(query.cursor) : 0
        const limit = query.limit ?? 50
        // 舊版後端（`?composition=off`）沒有買進日期的來由
        const items = filtered.slice(offset, offset + limit).map((t) => (composition ? t : withoutDateBasis(t)))
        return { items, next_cursor: offset + limit < filtered.length ? String(offset + limit) : null }
      }),
    getTransactionCounts: () =>
      wait(() => {
        const by_type: Record<string, number> = {}
        for (const t of ledger().txns) by_type[t.type] = (by_type[t.type] ?? 0) + 1
        const transactions = Object.values(by_type).reduce((a, b) => a + b, 0)
        return { transactions, dividends: (by_type.cash_dividend ?? 0) + (by_type.stock_dividend ?? 0), by_type }
      }),
    createTransaction: (body) =>
      wait(() => {
        const account = accounts.find((a) => a.id === body.account_id)
        if (!account) throw new ApiError(422, "invalid_account", "請先選擇券商帳戶")
        // 與後端相同：自動入帳只由系統產生
        if ((body.source as string | undefined)?.startsWith("auto")) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：source")
        const s = body.symbol ? spec(body.symbol) : undefined
        // 使用者新記的：不自動算手續費與證交稅（自動入帳的股利、定期定額草稿另外產生）
        const p = computePreview(body, account, s, { auto: false })
        const txn: Transaction = {
          id: `txn_${++nextId}`,
          account_id: body.account_id,
          symbol: body.symbol,
          type: body.type,
          trade_date: body.trade_date,
          quantity: body.quantity,
          price: body.price,
          amount: body.amount ?? p.gross,
          fee: body.fee ?? p.fee,
          tax: body.tax ?? p.tax,
          health_insurance: body.health_insurance ?? p.health_insurance,
          currency: account.currency,
          is_day_trade: body.is_day_trade ?? false,
          note: body.note ?? "",
          source: body.source ?? "manual",
          created_at: new Date().toISOString(),
        }
        txns.push(txn)
        sortTxns()
        resync()
        return txn
      }),
    updateTransaction: (id, patch) =>
      wait(() => {
        const idx = txns.findIndex((t) => t.id === id)
        const found = txns[idx]
        if (!found) throw new ApiError(404, "not_found", "找不到這筆交易")
        if ((patch.source as string | undefined)?.startsWith("auto")) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：source")
        // 改了自動入帳的股利：變成使用者的版本（auto_edited），這次股利之後不再自動產生
        if (found.source === "auto") skips.add(skipKey(found))
        // 換成新的物件（不原地修改）：React Query 才看得出資料變了
        const next: Transaction = { ...found, ...(patch as Partial<Transaction>), source: found.source === "auto" ? "auto_edited" : found.source }
        // 資產組成原型（和後端 `_basis_after` 一樣）：匯入庫存的買進——
        // 改成別的種類或別的股票：變成一般的紀錄（三個欄位清掉；估計與匯入那天是原本那一檔的）；
        // 還是那一筆買進：日期不能晚於匯入那天、不能早於匯入以前最近一次分割、減資、配股；改了日期（走勢圖上選的、或完整表單裡改的）就是「自己選的日期」
        if (found.date_basis) {
          if (next.type !== "buy" || next.symbol !== found.symbol) Object.assign(next, { date_basis: null, estimated_date: null, imported_on: null })
          else {
            const day = patch.trade_date ?? found.trade_date
            if (patch.trade_date && found.imported_on && day > found.imported_on) throw new ApiError(422, "after_import_day", `買進日期不能晚於匯入那天（${found.imported_on.replaceAll("-", "/")}）`)
            const change = day !== found.trade_date && found.symbol ? shareChangeOn(found.symbol, found.imported_on ?? MOCK_TODAY) : null
            if (change && day < change.date) throw new ApiError(422, "before_share_change", beforeShareChangeMessage(change))
            next.date_basis = day !== found.trade_date || patch.date_basis === "picked" ? "picked" : found.date_basis
          }
        }
        // 與後端相同：數量、價格、日期等輸入改了，沒有指定的手續費、稅、二代健保依新內容重算；買賣與現金股利改了數量或價格時金額也重算
        const inputsChanged = (["quantity", "price", "amount", "type", "trade_date", "symbol", "account_id", "is_day_trade"] as const).some((k) => k in patch)
        if (inputsChanged) {
          const recomputeAmount = patch.amount == null && ["buy", "sell", "cash_dividend"].includes(next.type) && ("quantity" in patch || "price" in patch)
          const p = computePreview(
            { ...next, amount: recomputeAmount ? null : next.amount, fee: patch.fee ?? null, tax: patch.tax ?? null, health_insurance: patch.health_insurance ?? null, source: undefined },
            accounts.find((a) => a.id === next.account_id),
            next.symbol ? findInstrument(next.symbol) : undefined,
            { auto: false },
          )
          // 與後端相同：手續費與稅只用這次送來的（沒送就是 0，不自動算）
          Object.assign(next, { amount: p.gross, fee: p.fee, tax: p.tax, health_insurance: p.health_insurance })
        }
        txns[idx] = next
        sortTxns()
        resync()
        return { ...next }
      }),
    deleteTransaction: (id) =>
      wait(() => {
        const found = txns.find((t) => t.id === id)
        // 刪掉自動入帳的股利：記一筆略過，之後不再產生
        if (found?.source === "auto") skips.add(skipKey(found))
        txns = txns.filter((t) => t.id !== id)
        resync()
      }),
    previewTransaction: (body) =>
      wait(() => computePreview(body, accounts.find((a) => a.id === body.account_id), body.symbol ? findInstrument(body.symbol) : undefined, { auto: false })),
    // 讀檔要 10–40 秒（實測）；示範縮短成 1.5 秒左右。取消時照真的 fetch 一樣丟 AbortError
    parseStatement: (body, opts) =>
      aiRead(() => {
        requireImport("這個帳號還不能匯入對帳單。")
        return imports.parse(body)
      }, opts?.signal),
    checkTransactionBatch: (body) => wait(() => imports.check(body)),
    createTransactionBatch: (body) => wait(() => imports.create(body)),
    deleteTransactionBatch: (batchId) => wait(() => imports.remove(batchId)),
    // 匯入庫存（2026-11-17）：讀和匯入對帳單一樣慢；寫入、檢查、復原和一般的請求一樣
    parsePositions: (body, opts) =>
      aiRead(() => {
        requireImport("這個帳號還不能匯入庫存。")
        const doc = imports.parsePositions(body)
        // 舊版後端（`?composition=off`）：沒有估計的買入日，整批一個日期
        if (composition) return doc
        return { ...doc, rows: doc.rows.map(({ estimated_date: _e, ...r }) => ({ ...r, flags: r.flags.filter((f) => f.code !== "no_crossing") })) }
      }, opts?.signal),
    checkPositions: (body) => wait(() => imports.checkPositions(body)),
    commitPositions: (body) => wait(() => imports.commitPositions(body)),
    // 和後端相同：這個帳戶這一檔的每一筆（買賣、股利含自動入帳的…）都刪掉，略過紀錄跟著清掉；定期定額只在要求時暫停
    deleteHolding: (accountId, symbol, opts) =>
      wait(() => {
        if (!accounts.some((a) => a.id === accountId)) throw new ApiError(404, "not_found", "找不到帳戶")
        const sym = txns.some((t) => t.symbol === symbol) ? symbol : (findInstrument(symbol)?.symbol ?? symbol.toUpperCase())
        const gone = txns.filter((t) => t.account_id === accountId && t.symbol === sym)
        if (gone.length === 0) throw new ApiError(404, "no_records", "這個帳戶沒有這一檔的紀錄")
        txns = txns.filter((t) => !(t.account_id === accountId && t.symbol === sym))
        for (const k of [...skips]) if (k.startsWith(`${accountId}|${sym}|`)) skips.delete(k)
        const running = recurring.list(accountId).filter((p) => p.symbol === sym && runningPlan(p))
        const pause = !!opts?.pausePlans
        if (pause) for (const p of running) recurring.update(p.id, { active: false })
        resync()
        return { account_id: accountId, symbol: sym, deleted: gone.length, plans_paused: pause ? running.length : 0, plans_running: pause ? 0 : running.length }
      }),
    // 清除所有持倉（和後端相同）：每個帳戶的筆數；還在進行的定期定額和 deleteHolding 同一個判斷
    getRecordCounts: () =>
      wait(() => {
        const count = (list: Transaction[], plans: RecurringPlan[]) => ({
          records: list.length,
          trades: list.filter((t) => t.type === "buy" || t.type === "sell").length,
          dividends: list.filter((t) => t.type === "cash_dividend" || t.type === "stock_dividend").length,
          symbols: new Set(list.flatMap((t) => (t.symbol ? [t.symbol] : []))).size,
          plans_running: plans.filter((p) => runningPlan(p)).length,
        })
        return {
          ...count(txns.filter((t) => accounts.some((a) => a.id === t.account_id)), recurring.list()),
          accounts: accounts.map((a) => ({ account_id: a.id, ...count(txns.filter((t) => t.account_id === a.id), recurring.list(a.id)) })),
        }
      }),
    // 一個帳戶或全部帳戶的每一筆紀錄都刪掉（帳戶、觀察清單留著），略過紀錄跟著清掉；定期定額只在要求時暫停
    clearRecords: (accountId, opts) =>
      wait(() => {
        if (accountId !== null && !accounts.some((a) => a.id === accountId)) throw new ApiError(404, "not_found", "找不到帳戶")
        const inScope = (t: { account_id: string }) => (accountId === null ? accounts.some((a) => a.id === t.account_id) : t.account_id === accountId)
        const gone = txns.filter(inScope)
        const running = recurring.list(accountId ?? undefined).filter(runningPlan)
        const pause = !!opts?.pausePlans
        // 沒有紀錄可以清（別的分頁已經清掉）時，要求的暫停照樣做，404 裡帶暫停了幾個、還有幾個在進行
        if (pause) for (const p of running) recurring.update(p.id, { active: false })
        const plans = { plans_paused: pause ? running.length : 0, plans_running: pause ? 0 : running.length }
        if (gone.length === 0) throw new ApiError(404, "no_records", accountId === null ? "沒有任何紀錄" : "這個帳戶沒有任何紀錄", plans)
        txns = txns.filter((t) => !inScope(t))
        for (const k of [...skips]) if (accountId === null || k.startsWith(`${accountId}|`)) skips.delete(k)
        return {
          account_id: accountId,
          deleted: gone.length,
          symbols: new Set(gone.flatMap((t) => (t.symbol ? [t.symbol] : []))).size,
          ...plans,
        }
      }),

    getPortfolioSummary: (accountId) =>
      wait(() => {
        const l = ledger(accountId)
        return buildSummary(l.txns, accountId, commercial, { limits: l.viewing ? VIEWED_LIMITS : allocationLimits, accounts: l.viewing ? l.accounts : accounts })
      }),
    getHoldings: (accountId) => wait(() => holdingsNow(accountId)),
    // 配置（2026-11-18）：和持股同一批；查看別人的資產時是授權者的上限、不能改
    getAllocation: (accountId) =>
      wait(() => {
        const l = ledger(accountId)
        return buildAllocation(l.txns, accountId, commercial, {
          limits: l.viewing ? VIEWED_LIMITS : allocationLimits,
          accounts: l.viewing ? l.accounts : accounts,
          canEditLimits: !l.viewing,
        })
      }),
    putAllocationLimits: (limits) =>
      wait(() => {
        const extra = Object.keys(limits).filter((k) => k !== "holding" && k !== "industry")
        if (extra.length > 0 || !validLimit(limits.holding ?? null) || !validLimit(limits.industry ?? null)) {
          throw new ApiError(422, "validation_error", "上限要在 1% 到 100% 之間")
        }
        const round = (v: number | null) => (v === null ? null : Math.round(v * 10000) / 10000)
        allocationLimits = { holding: round(limits.holding ?? null), industry: round(limits.industry ?? null) }
        return { ...allocationLimits }
      }),
    // 查看模式：授權者沒有定期定額（示範），本週事項只有除息與入帳
    getUpcoming: (days = 7, opts) =>
      wait(() => {
        const items = buildUpcoming(holdingsNow(), findInstrument, days, ledger().viewing ? [] : recurring.upcoming(today, addDays(today, days)), commercial, today)
        // 與後端相同：types=recurring 只回定期定額扣款（順序不變）
        return opts?.types === "recurring" ? items.filter((u) => u.type === "recurring") : items
      }),
    getPerformance: ({ range, account_id, benchmark }) =>
      wait(() => {
        const l = ledger(account_id)
        // 查看模式的基準用授權者的（示範：0050）
        const bench = benchmark ?? (l.viewing ? "0050.TW" : user.preferences.benchmark)
        const perf = (r: typeof range) => (commercial ? commercialPerformance(l.txns, r, account_id, bench) : buildPerformance(l.txns, r, account_id, bench, { composition }))
        const p = perf(range)
        // ?curve=arch：首頁走勢（「全部」）換成倒 U，只給截圖用
        if (options.curve === "arch" && range === "ALL") return archCurve(p)
        if (!options.history) return p
        // ?hist=N：從「全部」的最後 N 個收盤開始
        const days = (range === "ALL" ? p : perf("ALL")).series.map((x) => x.t)
        return days.length > options.history ? limitHistory(p, days[days.length - options.history]!) : p
      }),
    getClosedPositions: (accountId) => wait(() => closedRounds(ledger(accountId).txns, { accountId })),

    listRecurring: (accountId) => wait(() => recurring.list(accountId)),
    createRecurring: (body) => wait(() => recurring.create(body)),
    updateRecurring: (id, patch) => wait(() => recurring.update(id, patch)),
    deleteRecurring: (id) => wait(() => recurring.remove(id)),
    draftRecurring: (id, date) => wait(() => recurring.draft(id, date)),

    getAttributions: () => wait(() => buildAttributions(commercial ? "commercial" : "personal")),
    getMarketStatus: () => wait(() => mockMarketStatus(options.market ?? "closed")),
    getMarketOverview: () => wait(() => buildMarketOverview(demo, mockToday())),

    // 每日收盤簡報：打開開關的人才有；事實從示範帳本算，和帳本頁同一組數字
    getLatestBriefing: () => wait(() => (user.preferences.daily_briefing ? briefings.latest() : null)),
    listBriefings: (limit) => wait(() => (user.preferences.daily_briefing ? briefings.list(limit) : [])),
    markBriefingRead: (id) =>
      wait(() => {
        if (!briefings.markRead(id)) throw new ApiError(404, "not_found", "找不到這則簡報")
      }),
    // mock 模式的 AI 對話只存在這台瀏覽器（ai/store.ts）：伺服器這邊沒有東西可刪
    deleteAiThreads: () =>
      wait(() => {
        if (!signedIn) throw new ApiError(401, "unauthorized", "請先登入")
      }),

    getAnalystViews: (symbol) => wait(() => analyst.get(spec(symbol).symbol)),
    requestAnalystViews: (symbol) => wait(() => analyst.request(spec(symbol).symbol)),

    // ── 分享（M5） ──
    getAuthProviders: () => wait(() => ({ discord: true, google: true, dev_login: false })),
    // 沒有真的 Discord：整頁回到 next，帶 `auth=signed-in` 當作登入成功
    discordLoginUrl: (next) => `${next}${next.includes("?") ? "&" : "?"}auth=signed-in`,
    googleLoginUrl: (next) => `${next}${next.includes("?") ? "&" : "?"}auth=signed-in`,
    updateMe: (patch) =>
      wait(() => {
        const name = (patch.display_name ?? "").trim()
        if (name.length < 1 || name.length > 30) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：display_name")
        user = { ...user, display_name: name }
        return me()
      }),
    listDelegations: () => wait(() => sharing.listDelegations()),
    listDelegationCandidates: () => wait(() => sharing.listDelegationCandidates()),
    createDelegation: (body) => wait(() => sharing.createDelegation(body)),
    updateDelegation: (id, patch) => wait(() => sharing.updateDelegation(id, patch)),
    deleteDelegation: (id) => wait(() => sharing.deleteDelegation(id)),
    listGroups: () => wait(() => sharing.listGroups()),
    createGroup: (body) => wait(() => sharing.createGroup(body)),
    getGroup: (id) => wait(() => sharing.getGroup(id)),
    updateGroup: (id, patch) => wait(() => sharing.updateGroup(id, patch)),
    listMyGroupPasses: () => wait(() => sharing.listMyGroupPasses()),
    attachGroupPass: (id, passId) => wait(() => sharing.attachGroupPass(id, passId)),
    deleteGroup: (id) =>
      wait(() => {
        sharing.deleteGroup(id)
        // 刪除群組時連同它的主題一起刪
        discussions.purgeGroup(id)
      }),
    transferGroup: (id, userId) => wait(() => sharing.transferGroup(id, userId)),
    setMemberRole: (id, userId, role) => wait(() => sharing.setMemberRole(id, userId, role)),
    removeMember: (id, userId) => wait(() => sharing.removeMember(id, userId)),
    createInvite: (id, body) => wait(() => sharing.createInvite(id, body)),
    listInvites: (id) => wait(() => sharing.listInvites(id)),
    revokeInvite: (id, inviteId) => wait(() => sharing.revokeInvite(id, inviteId)),
    getInvite: (token) => wait(() => sharing.getInvite(token)),
    acceptInvite: (token, share) => wait(() => sharing.acceptInvite(token, share)),
    getShare: (id) => wait(() => sharing.getShare(id)),
    putShare: (id, share) => wait(() => sharing.putShare(id, share)),
    getLeaderboard: (id, period) => wait(() => sharing.getLeaderboard(id, period)),
    getGroupHoldings: (id) => wait(() => sharing.getGroupHoldings(id)),
    getSharedPortfolio: (id, userId) => wait(() => sharing.getSharedPortfolio(id, userId)),
    getFeed: (id, query) => wait(() => sharing.getFeed(id, query)),
    listComments: (id, target, query) => wait(() => sharing.listComments(id, target, query)),
    createComment: (id, body) => wait(() => sharing.createComment(id, body)),
    deleteComment: (id, commentId) => wait(() => sharing.deleteComment(id, commentId)),
    addReaction: (id, body) => wait(() => sharing.addReaction(id, body)),
    removeReaction: (id, target, emoji) => wait(() => sharing.removeReaction(id, target, emoji)),
    listDigests: (id, query) => wait(() => sharing.listDigests(id, query)),
    listDailyReports: (id, query) => wait(() => sharing.listDailyReports(id, query)),
    getChannels: (id) => wait(() => sharing.getChannels(id)),
    putDiscord: (id, body) => wait(() => sharing.putDiscord(id, body)),
    patchDiscord: (id, patch) => wait(() => sharing.patchDiscord(id, patch)),
    deleteDiscord: (id) => wait(() => sharing.deleteDiscord(id)),
    linkTelegram: (id) => wait(() => sharing.linkTelegram(id)),
    patchTelegram: (id, patch) => wait(() => sharing.patchTelegram(id, patch)),
    deleteTelegram: (id) => wait(() => sharing.deleteTelegram(id)),

    // ── 討論串 ──
    setPublicName: (name) =>
      wait(() => {
        discussions.setPublicName(name)
        return me()
      }),
    listTopics: (query) => wait(() => discussions.listTopics(query)),
    createTopic: (body) => wait(() => discussions.createTopic(body)),
    getTopic: (id) => wait(() => discussions.getTopic(id)),
    deleteTopic: (id) => wait(() => discussions.deleteTopic(id)),
    listReplies: (topicId, query) => wait(() => discussions.listReplies(topicId, query)),
    createReply: (topicId, body) => wait(() => discussions.createReply(topicId, body)),
    deleteReply: (id) => wait(() => discussions.deleteReply(id)),
    addDiscussionReaction: (body) => wait(() => discussions.addReaction(body)),
    removeDiscussionReaction: (target, emoji) => wait(() => discussions.removeReaction(target, emoji)),
    reportDiscussion: (body) => wait(() => discussions.report(body)),
    listAdminReports: (query) => wait(() => discussions.adminReports(query)),
    moderateDiscussion: (body) => wait(() => discussions.moderate(body)),
    listSuspensions: () => wait(() => discussions.listSuspensions()),
    createSuspension: (body) => wait(() => discussions.createSuspension(body)),
    liftSuspension: (id) => wait(() => discussions.liftSuspension(id)),

    // ── 管理後台 ──
    getAdminOverview: () => wait(() => admin.overview()),
    listBlockedDomains: () => wait(() => admin.list()),
    blockDomain: (body) => wait(() => admin.block(body, new Date(discussionNow()))),
    unblockDomain: (domain) => wait(() => admin.unblock(domain)),
    listMembers: () => wait(() => admin.members(todayInTaipei(new Date(discussionNow())))),
    grantMember: (body) => wait(() => admin.grant(body, todayInTaipei(new Date(discussionNow())))),
    revokeMember: (userId) => wait(() => admin.revoke(userId)),
    listGroupPasses: () =>
      wait(() => {
        admin.requireAdmin()
        return sharing.adminPasses((uid) => (uid === user.id ? { email: user.email, display_name: user.display_name } : admin.accountById(uid)))
      }),
    grantGroupPass: (body) =>
      wait(() => {
        const payer = admin.accountByEmail(body.email)
        const created = sharing.adminGrantPass(payer.user_id, body, todayInTaipei(new Date(discussionNow())))
        return sharing.adminPasses(() => ({ email: payer.email, display_name: payer.display_name })).find((x) => x.id === created.id)!
      }),
    updateGroupPass: (id, patch) =>
      wait(() => {
        admin.requireAdmin()
        sharing.adminUpdatePass(id, patch, todayInTaipei(new Date(discussionNow())))
        return sharing.adminPasses((uid) => admin.accountById(uid)).find((x) => x.id === id)!
      }),
    revokeGroupPass: (id) =>
      wait(() => {
        admin.requireAdmin()
        sharing.adminRevokePass(id)
      }),

    // ── 市場報告 ──
    getMarketReportStatus: () => wait(() => reports.status()),
    listMarketReports: (query) => wait(() => reports.list(query)),
    getLatestMarketReport: (kind) => wait(() => reports.latest(kind)),
    getMarketReport: (id, version) => wait(() => reports.get(id, version)),
    markMarketReportsSeen: () => wait(() => reports.seen()),
    getAdminReportsOverview: () => wait(() => reports.overview()),
    putReportsConfig: (body) => wait(() => reports.config(body)),
    addReportCorrection: (reportId, body) => wait(() => reports.correction(reportId, body)),
    rebuildReportData: (body) => wait(() => reports.rebuild(body)),
    listNyseHolidays: () => wait(() => reports.nyseList()),
    putNyseHoliday: (date, body) => wait(() => reports.nysePut(date, body)),
    deleteNyseHoliday: (date) => wait(() => reports.nyseDelete(date)),
    listMacroEvents: () => wait(() => reports.macroList()),
    addMacroEvent: (body) => wait(() => reports.macroAdd(body)),
    deleteMacroEvent: (id) => wait(() => reports.macroDelete(id)),
    listUsEarnings: () => wait(() => reports.earningsList()),
    addUsEarning: (body) => wait(() => reports.earningsAdd(body)),
    deleteUsEarning: (id) => wait(() => reports.earningsDelete(id)),
  }

  return guardViewAs(base, (id) => sharing.viewAsOwner(id), wait)
}

/** 查看別人的資產時，授權者（示範：爸爸）自己設的配置上限：只能看、不能改 */
const VIEWED_LIMITS: AllocationLimits = { holding: 0.25, industry: null }

// ── 授權查看的路由白名單（與後端相同，預設拒絕） ─────────────────
type MethodName = Exclude<keyof ForliosaApi, "kind">
/** 查看者自己的端點（不帶標頭）：`/me`、偏好、登入、讀自己收到的授權（`GET /delegations`，查看中更新橫幅的範圍） */
const VIEWER_OWN = new Set<MethodName>(["getLatestBriefing", "listBriefings", "markBriefingRead", "devLogin", "logout", "getMe", "exportMe", "deleteMe", "acceptTerms", "updateMe", "updatePreferences", "getAuthProviders", "discordLoginUrl", "googleLoginUrl", "listDelegations", "setPublicName"])
/** 不讀使用者資料的端點：忽略標頭 */
const IGNORES_VIEW_AS = new Set<MethodName>([
  "searchInstruments", "getInstrument", "getQuote", "getQuotes", "getHistory", "getDailyClose", "getValuation", "getRevenue", "getDividends", "getOverview",
  "getIntraday", "getChips", "getFinancials", "getNews", "getWhy", "getAttributions", "getMarketStatus", "getMarketOverview",
  // 討論串的讀取一律以登入者本人回答（前端在查看模式擋下討論頁）
  "listTopics", "getTopic", "listReplies",
  // 市場報告沒有個人資料：以登入者本人回答（`POST /market/reports/seen` 照規則 read_only）
  "getMarketReportStatus", "listMarketReports", "getLatestMarketReport", "getMarketReport",
])
/** 以授權者身分回應的唯讀端點 */
export const VIEW_AS_READS = new Set<MethodName>([
  "listAccounts", "getPortfolioSummary", "getHoldings", "getAllocation", "getPerformance", "getClosedPositions", "getUpcoming", "listTransactions", "getTransactionCounts",
  "getPosition", "getPositionHistory", "getEvents",
])
/** 非 GET 的方法（查看模式一律 read_only） */
const WRITES = new Set<MethodName>([
  "deleteAiThreads",
  "createAccount", "updateAccount", "deleteAccount", "addWatch", "removeWatch", "createTransaction", "updateTransaction",
  "deleteTransaction", "previewTransaction", "parseStatement", "checkTransactionBatch", "createTransactionBatch", "deleteTransactionBatch", "parsePositions", "checkPositions", "commitPositions", "deleteHolding", "clearRecords", "putAllocationLimits", "createRecurring", "updateRecurring", "deleteRecurring", "draftRecurring", "requestAnalystViews",
  "createDelegation", "updateDelegation", "deleteDelegation", "createGroup", "updateGroup", "deleteGroup", "transferGroup", "setMemberRole",
  "removeMember", "createInvite", "revokeInvite", "acceptInvite", "putShare", "createComment", "deleteComment", "addReaction", "removeReaction",
  "putDiscord", "patchDiscord", "deleteDiscord", "linkTelegram", "patchTelegram", "deleteTelegram",
  "createTopic", "deleteTopic", "createReply", "deleteReply", "addDiscussionReaction", "removeDiscussionReaction", "reportDiscussion",
  "moderateDiscussion", "createSuspension", "liftSuspension", "blockDomain", "unblockDomain", "grantMember", "revokeMember",
  "markMarketReportsSeen", "putReportsConfig", "addReportCorrection", "rebuildReportData",
  "putNyseHoliday", "deleteNyseHoliday", "addMacroEvent", "deleteMacroEvent", "addUsEarning", "deleteUsEarning",
])

function guardViewAs(base: ForliosaApi, validate: (id: string) => unknown, wait: <T>(value: T | (() => T)) => Promise<T>): ForliosaApi {
  const out: Record<string, unknown> = { ...base }
  for (const key of Object.keys(base) as (keyof ForliosaApi)[]) {
    if (key === "kind" || VIEWER_OWN.has(key) || IGNORES_VIEW_AS.has(key)) continue
    const fn = base[key] as (...args: unknown[]) => Promise<unknown>
    out[key] = (...args: unknown[]) => {
      const id = viewAsId()
      if (!id) return fn(...args)
      return wait(() => {
        validate(id) // 授權不存在、已撤銷、或被授權者不是我：403 delegation_revoked
        if (WRITES.has(key)) throw new ApiError(403, "read_only", "正在以唯讀身分查看，不能修改")
        if (!VIEW_AS_READS.has(key)) throw new ApiError(403, "view_as_not_allowed", "查看別人的資產時不能使用這個功能")
      }).then(() => fn(...args))
    }
  }
  return out as unknown as ForliosaApi
}
