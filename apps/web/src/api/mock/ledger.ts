import type {
  Account,
  AllocationLimits,
  FundRank,
  Holding,
  Performance,
  PerformanceComposition,
  PerformancePoint,
  PerformanceRange,
  PortfolioAllocation,
  PortfolioSummary,
  Transaction,
} from "../types"
import { allocationOf, summaryAllocation } from "./allocation"
import { syncAutoDividends } from "./auto-dividends"
import { BACKFILL_START, hasUsCloses, US_ARCHIVE_START, US_AS_OF, US_SESSION, usCandles } from "./commercial"
import { computePreview } from "./fees"
import { minusMonths } from "@/lib/trend-range"
import { inSpans, monthlyBreakdown, type MonthPoint, type Span } from "@/lib/asset-composition"
import { estimateBuyDate } from "@/lib/buy-date"
import { findInstrument, type MockInstrumentSpec } from "./instruments"
import {
  addDays,
  closeOn,
  dailyCandles,
  dividendRecords,
  FX_NOW,
  MOCK_AS_OF,
  MOCK_TODAY,
  parseDay,
  rng,
  tradingDays,
  usdTwd,
} from "./market"

export const ACCOUNTS: Account[] = [
  {
    id: "acc_01JSINOPAC", name: "永豐・一般", broker: "永豐金證券", currency: "TWD",
    fee_rate: 0.001425, fee_discount: 0.28, min_fee: 20, min_fee_odd_lot: 1,
    created_at: "2023-03-01T10:00:00+08:00",
  },
  {
    id: "acc_01JCATHAYUS", name: "國泰・複委託", broker: "國泰證券", currency: "USD",
    fee_rate: 0.001, fee_discount: 1, min_fee: 3, min_fee_odd_lot: 3,
    created_at: "2023-05-20T10:00:00+08:00",
  },
]

const TW = ACCOUNTS[0]!
const US = ACCOUNTS[1]!

function nextWeekday(day: string): string {
  let d = day
  while ([0, 6].includes(parseDay(d).getUTCDay())) d = addDays(d, 1)
  return d
}

let seq = 0
function makeTxn(partial: Omit<Transaction, "id" | "created_at" | "source" | "note" | "is_day_trade" | "currency"> & Partial<Transaction>): Transaction {
  seq += 1
  const account = ACCOUNTS.find((a) => a.id === partial.account_id)!
  return {
    id: `txn_${String(seq).padStart(5, "0")}`,
    note: "",
    source: "manual",
    is_day_trade: false,
    currency: account.currency,
    created_at: `${partial.trade_date}T14:00:00+08:00`,
    ...partial,
  }
}

function trade(type: "buy" | "sell", account: Account, symbol: string, day: string, qty: number, priceOverride?: number, note = ""): Transaction {
  const spec = findInstrument(symbol)!
  const d = nextWeekday(day)
  const price = priceOverride ?? closeOn(spec, d)
  const p = computePreview({ account_id: account.id, symbol, type, trade_date: d, quantity: qty, price }, account, spec)
  return makeTxn({ account_id: account.id, symbol, type, trade_date: d, quantity: qty, price, amount: p.gross, fee: p.fee, tax: p.tax, health_insurance: 0, note })
}

function cash(type: Transaction["type"], account: Account, day: string, amount: number, note = ""): Transaction {
  return makeTxn({ account_id: account.id, symbol: null, type, trade_date: nextWeekday(day), quantity: null, price: null, amount, fee: 0, tax: 0, health_insurance: 0, note })
}

/**
 * 示範情境：使用者自己記股利記到 8 月；之後的台股股利（2330 9/16、6488 9/22、2454 10/8 除息）由股利自動入帳記下。
 * 美股沒有可商用的股利資料，一直是自己記。
 */
export const AUTO_BOOKING_FROM = "2026-09-01"

/**
 * 資產組成原型（`docs/proposals/asset-composition.md`）：示範使用者 2025/11/29（星期六）匯入過一次庫存截圖，
 * 其中四檔沒有買進日期，買入日照股價估（從匯入那天往回，股價最近一次經過成本價的那天；`lib/buy-date.ts`）：
 * - VOO：估計 2024/7/29（美股的歷史只從 2024/7/1 開始；離匯入約 16 個月）
 * - 環球晶：估計 2025/7/2（離匯入約 5 個月）
 * - 聯發科：成本 488，五年內股價都沒有經過（最低 516）：買入日用匯入那天（星期六，沒有收盤：漲跌算在下一個收盤日 12/1）
 * - 鴻海 2024/3/11 那一筆：估計是 2025/9/4，使用者在走勢圖上自己改回 2024/3/11（自己選的日期）
 * 和規格一樣：成本價、股數和券商一樣，手續費 0，只有日期是估計的。估計的那一段是 2024/7/29 到匯入前一個交易日（2025/11/28）；
 * 分好幾次匯入時每一次各一段（`estimatedSpans`）。
 * `?composition=off`（模擬舊版後端）時不套用：和現在的示範帳本一模一樣（`seedTransactions({ importedLots: false })`）。
 */
export const IMPORT_DAY = "2025-11-29"
const IMPORT_BATCH = "imp_demo_20251129"

/** 美股的估計只能用 2024/7/1 以後的收盤（Databento）；台股用 Yahoo 回補的五年 */
function tradedCandles(spec: MockInstrumentSpec) {
  return spec.market === "US" ? usCandles(spec).filter((c) => c.t >= US_ARCHIVE_START) : dailyCandles(spec).filter((c) => c.t >= BACKFILL_START)
}

function importedLots(t: Transaction[]) {
  const lot = (symbol: string, day: string) => t.find((x) => x.type === "buy" && x.symbol === symbol && x.trade_date === nextWeekday(day))
  const mark = (x: Transaction | undefined, patch: Partial<Transaction>) => {
    if (!x) return
    // 匯入庫存的買進：價格是券商的均價、手續費 0（券商的均價多半已含手續費）
    Object.assign(x, { source: "import", import_batch_id: IMPORT_BATCH, created_at: `${IMPORT_DAY}T10:00:00+08:00`, imported_on: IMPORT_DAY, fee: 0, ...patch })
  }
  for (const [symbol, day] of [["VOO", "2024-02-01"], ["6488.TWO", "2024-05-20"]] as const) {
    const x = lot(symbol, day)
    const est = x ? estimateBuyDate(tradedCandles(findInstrument(symbol)!), x.price!, IMPORT_DAY) : null
    if (x && est) mark(x, { trade_date: est, date_basis: "estimated", estimated_date: est })
  }
  // 聯發科：成本比五年來的最低價還低（很早以前買的），找不到：用匯入那天
  const mtk = lot("2454.TW", "2024-10-21")
  if (mtk) mark(mtk, { trade_date: IMPORT_DAY, price: 488, amount: 488 * (mtk.quantity ?? 0), date_basis: "import_day", estimated_date: null, note: "" })
  // 鴻海 2024/3/11 那一筆：自動估的是 2025/9/4，使用者自己選回 2024/3/11
  const honHai = lot("2317.TW", "2024-03-11")
  if (honHai) mark(honHai, { date_basis: "picked", estimated_date: estimateBuyDate(tradedCandles(findInstrument("2317.TW")!), honHai.price!, IMPORT_DAY) })
}

/** 前一個平日（mock 的行事曆沒有國定假日） */
function weekdayBefore(day: string): string {
  let d = addDays(day, -1)
  while ([0, 6].includes(parseDay(d).getUTCDay())) d = addDays(d, -1)
  return d
}

/**
 * 估計的那幾段（頭尾都含），由舊到新：每一次匯入（`imported_on`）一段——那一次匯入最早一筆還是「估計」的買進，到那次匯入前一個平日；
 * 重疊或連在一起（中間沒有平日）的併成一段。都自己選過了就是空的（和後端 `services/composition.estimated_spans` 一樣）。
 */
export function estimatedSpans(txns: Transaction[], accountId?: string): Span[] {
  const byImport = new Map<string, string>()
  for (const x of txns) {
    if (x.type !== "buy" || x.date_basis !== "estimated" || (accountId && x.account_id !== accountId)) continue
    const day = x.imported_on ?? MOCK_TODAY
    const cur = byImport.get(day)
    if (!cur || x.trade_date < cur) byImport.set(day, x.trade_date)
  }
  const spans = [...byImport]
    .map(([imported, from]) => ({ from, until: weekdayBefore(imported) }))
    .filter((sp) => sp.until >= sp.from)
    .sort((a, b) => (a.from === b.from ? a.until.localeCompare(b.until) : a.from.localeCompare(b.from)))
  const out: Span[] = []
  for (const sp of spans) {
    const prev = out.at(-1)
    // 連在一起：下一段的第一天不晚於前一段結束後的下一個平日
    if (prev && weekdayBefore(sp.from) <= prev.until) out[out.length - 1] = { from: prev.from, until: sp.until > prev.until ? sp.until : prev.until }
    else out.push(sp)
  }
  return out
}

/** 匯入時找不到買入日、用匯入那天記的買進（`import_day`）的日期：「每月報酬率」暫時不列這些月份（見 `monthlyBreakdown`） */
export function importDays(txns: Transaction[], accountId?: string): string[] {
  return txns.filter((x) => x.type === "buy" && x.date_basis === "import_day" && (!accountId || x.account_id === accountId)).map((x) => x.trade_date)
}

/**
 * 產生示範交易紀錄（由舊到新），含自動入帳的股利。
 * - `importedLots`（預設 true）：資產組成原型的匯入庫存（估計的買入日）；false 和原本的示範帳本一樣。
 * - `extra`：資產組成原型的示範情境（網址 `?mock=…`，見 adapter 的 `MockScenario`），在示範帳本上多幾筆：
 *   - `cashout`：2023 年買、2026/10 整批賣掉的台積電 10 張——賣股票收到的錢比買股票花的多，本金是負的。
 *   - `loss`（一直虧）：2023/3 在高點買的長榮 5 張（690 元），之後一路跌到 200 元上下——從第一天起總資產都在本金下面。
 *   - `cross`（賺轉虧）：2023/3 買的中美晶 10 張（327 元），2024 年漲到 440 元上下、之後跌到 120 元上下——先賺、後來轉虧。
 *   - `lastday`（最後一天轉虧）：換成一個小帳本（見 `lastDayTrades`）——前一天整體還賺一點，最後一天在高點買進台積電，收盤變成虧的。
 */
export function seedTransactions(opts: { importedLots?: boolean; extra?: "cashout" | "loss" | "cross" | "lastday" } = {}): Transaction[] {
  seq = 0
  const t: Transaction[] = []
  t.push(cash("deposit", TW, "2023-03-01", 1_500_000, "初始資金"))
  t.push(trade("buy", TW, "2330.TW", "2023-03-15", 1000))
  t.push(cash("deposit", US, "2023-05-22", 15_000, "匯入美元"))
  t.push(trade("buy", US, "AAPL", "2023-06-01", 10))
  t.push(trade("buy", US, "NVDA", "2023-09-12", 4, Math.round(closeOn(findInstrument("NVDA")!, "2023-09-12") * 1000) / 100, "分割前買進"))
  t.push(trade("buy", TW, "2603.TW", "2024-01-10", 1000))
  t.push(trade("buy", TW, "2409.TW", "2024-02-15", 2000))
  t.push(trade("buy", US, "VOO", "2024-02-01", 10))
  t.push(trade("buy", TW, "2317.TW", "2024-03-11", 1000))
  t.push(trade("buy", US, "AAPL", "2024-04-22", 5))
  t.push(trade("buy", TW, "3008.TW", "2024-05-08", 100))
  t.push(trade("buy", TW, "6488.TWO", "2024-05-20", 1000))
  t.push(makeTxn({ account_id: US.id, symbol: "NVDA", type: "split", trade_date: "2024-06-10", quantity: 10, price: null, amount: 0, fee: 0, tax: 0, health_insurance: 0, note: "1 股分割為 10 股" }))
  t.push(trade("buy", TW, "2330.TW", "2024-08-06", 500))
  t.push(trade("sell", TW, "2409.TW", "2024-09-10", 2000))
  t.push(trade("buy", TW, "2454.TW", "2024-10-21", 200, undefined, "零股"))
  t.push(trade("sell", TW, "2603.TW", "2025-02-20", 1000))
  t.push(trade("buy", TW, "2317.TW", "2025-04-14", 1000))
  t.push(trade("sell", TW, "3008.TW", "2025-08-12", 100))
  // 已出清依年份分組：2024（友達）、2025（長榮、大立光）、2026（中華電、群益台灣精選高息）
  t.push(trade("buy", TW, "2412.TW", "2026-01-12", 1000))
  t.push(trade("buy", TW, "00919.TW", "2026-03-02", 3000))
  t.push(trade("sell", TW, "2412.TW", "2026-07-15", 1000))
  t.push(trade("sell", TW, "00919.TW", "2026-09-21", 3000))
  t.push(cash("fee", US, "2025-12-31", 25, "年度帳戶管理費"))

  // 定期定額（與 recurring.ts 的示範計畫一致）：0050 每月 6 日 NT$10,000、00878 每月 12、26 日 NT$4,000（零股）。
  // 今天的扣款還沒入帳：AI 面板會在扣款日提出草稿，簽名後才記下；最近 7 天漏記的扣款會提出補記
  for (let y = 2024; y <= 2026; y++) {
    for (let m = 1; m <= 12; m++) {
      const mm = String(m).padStart(2, "0")
      for (const [symbol, day, amount] of [["0050.TW", "06", 10_000], ["00878.TW", "12", 4_000], ["00878.TW", "26", 4_000]] as const) {
        const d = `${y}-${mm}-${day}`
        if (nextWeekday(d) >= MOCK_TODAY) continue
        // 11/06 的 0050 扣款沒有記：AI 面板會提出「補記 11/06 的 0050 定期定額」
        if (symbol === "0050.TW" && d === "2026-11-06") continue
        const p = closeOn(findInstrument(symbol)!, nextWeekday(d))
        t.push(trade("buy", TW, symbol, d, Math.floor(amount / p), undefined, "定期定額"))
      }
      if ([3, 6, 9, 12].includes(m) && `${y}-${mm}-21` <= MOCK_TODAY) {
        t.push(cash("interest", TW, `${y}-${mm}-21`, 18 + ((y * 7 + m * 3) % 40), "交割戶利息"))
      }
    }
  }

  if (opts.extra === "cashout") {
    t.push(trade("buy", TW, "2330.TW", "2023-03-15", 10_000, undefined, "整批買進"))
    t.push(trade("sell", TW, "2330.TW", "2026-10-20", 10_000, undefined, "整批賣出"))
  }
  if (opts.extra === "loss") t.push(trade("buy", TW, "2603.TW", "2023-03-15", 5_000, undefined, "高點買進"))
  if (opts.extra === "cross") t.push(trade("buy", TW, "5483.TWO", "2023-03-15", 10_000))
  if (opts.extra === "lastday") t.splice(0, t.length, ...lastDayTrades())
  if (opts.importedLots ?? true) importedLots(t)
  t.sort((a, b) => (a.trade_date === b.trade_date ? a.id.localeCompare(b.id) : a.trade_date.localeCompare(b.trade_date)))

  // 現金股利：使用者自己記的（發放日入帳、manual）。台股從 AUTO_BOOKING_FROM 起改由股利自動入帳記在除息日（source: auto），
  // 之前自己記的維持手動（自己記的優先，自動入帳不會重複產生）
  const dividends: Transaction[] = []
  const held = new Set(t.filter((x) => x.symbol).map((x) => x.symbol!))
  for (const symbol of held) {
    const spec = findInstrument(symbol)!
    const account = spec.market === "US" ? US : TW
    for (const rec of dividendRecords(spec)) {
      if (!rec.ex_dividend_date || !rec.payment_date || rec.payment_date > MOCK_TODAY || rec.cash_dividend <= 0) continue
      if (spec.market !== "US" && rec.ex_dividend_date >= AUTO_BOOKING_FROM) continue
      const qty = quantityOn(t, symbol, addDays(rec.ex_dividend_date, -1))
      if (qty <= 0) continue
      const p = computePreview({ account_id: account.id, symbol, type: "cash_dividend", trade_date: rec.payment_date, quantity: qty, price: rec.cash_dividend }, account, spec)
      dividends.push(makeTxn({
        account_id: account.id, symbol, type: "cash_dividend", trade_date: nextWeekday(rec.payment_date), quantity: qty, price: rec.cash_dividend,
        amount: p.gross, fee: 0, tax: p.tax, health_insurance: p.health_insurance, note: `${rec.period} 現金股利`,
      }))
    }
  }
  return syncAutoDividends([...t, ...dividends], { accounts: ACCOUNTS, skips: new Set(), today: MOCK_TODAY })
}

/**
 * `?mock=lastday`（資產組成原型，總資產走勢 v2 的截圖用）：最後一天的買進讓整體從賺變虧。
 * 帳本只有兩筆：元大台灣50 2 萬股（買在收盤價比 11/11 低一點的那一天：11/11 收盤時整體賺 1.5 萬上下），
 * 和 11/12 在高點買的台積電 460 股（約 50 萬）——買進價照收盤推回去，讓 11/12 收盤時整體虧 1.5 萬上下。
 * 價格都從 mock 的收盤算，每次一樣。
 */
function lastDayTrades(): Transaction[] {
  const etf = findInstrument("0050.TW")!
  const tsmc = findInstrument("2330.TW")!
  const prev = "2026-11-11"
  const qty = 20_000
  const before = closeOn(etf, prev)
  // 收盤價最接近「11/11 收盤 − 0.75 元」的那一天買（賺 1.5 萬上下）
  let buyDay = "2025-01-02"
  let best = Infinity
  for (let d = "2025-01-02"; d < "2026-10-31"; d = addDays(d, 1)) {
    if ([0, 6].includes(parseDay(d).getUTCDay())) continue
    const diff = Math.abs(closeOn(etf, d) - (before - 0.75))
    if (diff < best) {
      best = diff
      buyDay = d
    }
  }
  const buy = trade("buy", TW, "0050.TW", buyDay, qty)
  const gainBefore = qty * before - buy.amount! - buy.fee
  const last = MOCK_TODAY
  const close = closeOn(tsmc, last)
  // 11/12 收盤時整體虧 1.5 萬：台積電要賠掉「前一天賺的＋元大台灣50 這一天的漲跌＋1.5 萬」（手續費約 0.1425%，先估進去）
  const shares = 460
  const loss = gainBefore + qty * (closeOn(etf, last) - before) + 15_000
  const price = Math.round(((close * shares + loss) / shares / 1.001425) * 2) / 2
  return [cash("deposit", TW, addDays(buyDay, -3), 2_000_000, "初始資金"), buy, trade("buy", TW, "2330.TW", last, shares, price, "零股（買在高點）")]
}

function quantityOn(txns: Transaction[], symbol: string, day: string): number {
  let q = 0
  for (const x of txns) {
    if (x.symbol !== symbol || x.trade_date > day) continue
    if (x.type === "buy") q += x.quantity ?? 0
    else if (x.type === "sell") q -= x.quantity ?? 0
    else if (x.type === "split") q *= x.quantity ?? 1
    else if (x.type === "capital_reduction") q -= q * (x.quantity ?? 0)
    else if (x.type === "stock_dividend") q += Math.floor(q * ((x.price ?? 0) / 10))
  }
  return q
}

// ── 持股與損益（移動平均成本） ────────────────────────────
interface Position {
  symbol: string
  /**
   * 每個帳戶目前的股數：`account_ids` 只列還持有的帳戶（和後端 `open_positions` 相同；一個帳戶賣光了就不算，
   * 「刪除這檔」的預設帳戶靠它）
   */
  held: Map<string, number>
  qty: number
  cost: number // 原幣，含買進手續費
  costTwd: number
  /** 成本裡的買進手續費（原幣）：和成本一起照比例扣（示範帳本只用移動平均，帳戶合在一起算） */
  fee: number
}

export interface LedgerState {
  positions: Map<string, Position>
  realizedTwd: number
  realizedByYear: Map<number, number>
  realizedEvents: { t: string; amount: number }[]
  dividendsTwd: number
}

function fxFor(currency: string, day: string) {
  return currency === "USD" ? usdTwd(day) : 1
}

export function replay(txns: Transaction[], until = MOCK_TODAY, accountId?: string): LedgerState {
  const positions = new Map<string, Position>()
  let realizedTwd = 0
  let dividendsTwd = 0
  const realizedByYear = new Map<number, number>()
  const realizedEvents: { t: string; amount: number }[] = []
  for (const x of txns) {
    if (x.trade_date > until) break
    if (accountId && x.account_id !== accountId) continue
    if (!x.symbol) continue
    const fx = fxFor(x.currency, x.trade_date)
    let pos = positions.get(x.symbol)
    if (!pos) {
      pos = { symbol: x.symbol, held: new Map(), qty: 0, cost: 0, costTwd: 0, fee: 0 }
      positions.set(x.symbol, pos)
    }
    const before = pos.qty
    const mine = pos.held.get(x.account_id) ?? 0
    const q = x.quantity ?? 0
    switch (x.type) {
      case "buy":
        pos.qty += q
        pos.cost += x.amount + x.fee
        pos.costTwd += (x.amount + x.fee) * fx
        pos.fee += x.fee
        break
      case "sell": {
        if (pos.qty <= 0) break
        const ratio = Math.min(q / pos.qty, 1)
        const proceedsTwd = (x.amount - x.fee - x.tax) * fx
        const r = proceedsTwd - pos.costTwd * ratio
        realizedTwd += r
        const year = Number(x.trade_date.slice(0, 4))
        realizedByYear.set(year, (realizedByYear.get(year) ?? 0) + r)
        realizedEvents.push({ t: x.trade_date, amount: r })
        pos.qty -= q
        pos.cost -= pos.cost * ratio
        pos.costTwd -= pos.costTwd * ratio
        pos.fee -= pos.fee * ratio
        break
      }
      case "split":
        pos.qty *= q || 1
        break
      case "capital_reduction":
        pos.qty -= pos.qty * q
        break
      case "stock_dividend":
        // 和後端相同：有配發股數就用它，沒有才照每股配股（元）÷ 面額 10 元算
        pos.qty += x.quantity ? x.quantity : Math.floor(pos.qty * ((x.price ?? 0) / 10))
        break
      case "cash_dividend":
        dividendsTwd += (x.amount - x.tax - x.health_insurance) * fx
        break
    }
    // 這個帳戶的股數跟著變：買進、配股加上去，賣出扣掉；分割、減資照整檔的比例
    if (x.type === "buy" || x.type === "stock_dividend") pos.held.set(x.account_id, mine + (pos.qty - before))
    else if (x.type === "sell") pos.held.set(x.account_id, Math.max(mine - q, 0))
    else if (x.type === "split" || x.type === "capital_reduction") pos.held.set(x.account_id, before > 0 ? mine * (pos.qty / before) : mine)
    else pos.held.set(x.account_id, mine)
  }
  return { positions, realizedTwd, realizedByYear, realizedEvents, dividendsTwd }
}

/** 還持有這一檔的帳戶（第一次記這一檔的順序） */
const holdingAccounts = (pos: Position) => [...pos.held].filter(([, q]) => q > 0.0001).map(([id]) => id)

const r2 = (n: number) => Math.round(n * 100) / 100
const r4 = (n: number) => Math.round(n * 10000) / 10000

/**
 * 持股。`commercial`（與後端相同，不標示示範資料）：每一檔帶 `price_date`（價格屬於哪一個交易日；美股是紐約的日期
 * `US_SESSION`）。美股的收盤價（Databento）以今天的匯率換算新台幣；還沒有收盤價的美股（只有 SEC 代號表認得的，
 * 模擬剛加入、還沒抓到）`price: null`、以成本計值、今日與未實現為 0。
 */
export function buildHoldings(txns: Transaction[], accountId?: string, commercial = false): Holding[] {
  const state = replay(txns, MOCK_TODAY, accountId)
  const rows: Holding[] = []
  for (const pos of state.positions.values()) {
    if (pos.qty <= 0.0001) continue
    const spec = findInstrument(pos.symbol)!
    if (commercial && spec.market === "US" && !hasUsCloses(spec)) {
      rows.push({
        symbol: spec.symbol, code: spec.code, name: spec.name, market: spec.market, type: spec.type,
        currency: spec.currency, industry: spec.industry, quantity: pos.qty, avg_cost: r4(pos.cost / pos.qty),
        cost_basis: r2(pos.costTwd), fees_in_cost: r2(pos.fee), price: null, prev_close: null, price_date: null, market_value: r2(pos.costTwd), day_change: 0,
        day_change_pct: 0, unrealized_pnl: 0, unrealized_pnl_pct: 0, weight: 0, account_ids: holdingAccounts(pos), is_demo: false,
      })
      continue
    }
    const fx = spec.currency === "USD" ? FX_NOW : 1
    const mv = pos.qty * spec.price * fx
    const day = pos.qty * (spec.price - spec.prev_close) * fx
    rows.push({
      symbol: spec.symbol, code: spec.code, name: spec.name, market: spec.market, type: spec.type,
      currency: spec.currency, industry: spec.industry,
      quantity: pos.qty,
      avg_cost: r4(pos.cost / pos.qty),
      cost_basis: r2(pos.costTwd),
      fees_in_cost: r2(pos.fee),
      price: spec.price,
      prev_close: spec.prev_close,
      ...(commercial ? { price_date: spec.market === "US" ? US_SESSION : MOCK_TODAY } : {}),
      market_value: r2(mv),
      day_change: r2(day),
      day_change_pct: r4(spec.price / spec.prev_close - 1),
      unrealized_pnl: r2(mv - pos.costTwd),
      unrealized_pnl_pct: r4(mv / pos.costTwd - 1),
      weight: 0,
      account_ids: holdingAccounts(pos),
      is_demo: !commercial,
    })
  }
  const total = rows.reduce((s, h) => s + h.market_value, 0)
  for (const h of rows) h.weight = total ? r4(h.market_value / total) : 0
  return rows.sort((a, b) => b.market_value - a.market_value)
}

/**
 * 每一檔在每個帳戶的市值（配置的「帳戶」那一組）：照每個帳戶的股數分這一檔的市值，加起來剛好等於這一檔的市值
 * （和後端 `HoldingRow.by_account_value` 一樣，同一個價格與匯率）
 */
function valueByAccount(txns: Transaction[], holdings: Holding[], accountId: string | undefined, commercial: boolean): Map<string, Map<string, number>> {
  const ids = accountId ? [accountId] : [...new Set(txns.map((t) => t.account_id))]
  const qty = new Map<string, Map<string, number>>()
  for (const id of ids) {
    for (const h of buildHoldings(txns, id, commercial)) {
      const m = qty.get(h.symbol) ?? new Map<string, number>()
      m.set(id, h.quantity)
      qty.set(h.symbol, m)
    }
  }
  const out = new Map<string, Map<string, number>>()
  for (const h of holdings) {
    const per = qty.get(h.symbol) ?? new Map<string, number>()
    const totalQty = [...per.values()].reduce((a, b) => a + b, 0)
    out.set(h.symbol, new Map([...per].map(([id, q]) => [id, totalQty ? (h.market_value * q) / totalQty : 0])))
  }
  return out
}

export interface AllocationOptions {
  /** 使用者自己設的上限（預設都沒設） */
  limits?: AllocationLimits
  /** 帳戶名稱（「帳戶」那一組；預設示範帳戶） */
  accounts?: Account[]
}

const NO_LIMITS: AllocationLimits = { holding: null, industry: null }

function allocationParts(txns: Transaction[], holdings: Holding[], accountId: string | undefined, commercial: boolean, opts: AllocationOptions) {
  return allocationOf(holdings, valueByAccount(txns, holdings, accountId, commercial), opts.accounts ?? ACCOUNTS, opts.limits ?? NO_LIMITS)
}

/** `GET /portfolio/allocation`：和 `buildHoldings` 同一批持股、同一個價格與匯率 */
export function buildAllocation(txns: Transaction[], accountId: string | undefined, commercial: boolean, opts: AllocationOptions & { canEditLimits: boolean }): PortfolioAllocation {
  const holdings = buildHoldings(txns, accountId, commercial)
  const { groups, concentration, total } = allocationParts(txns, holdings, accountId, commercial, opts)
  const onlyUs = commercial && holdings.some((h) => h.price !== null) && holdings.every((h) => h.price === null || h.market === "US")
  return {
    as_of: onlyUs ? US_AS_OF : MOCK_AS_OF,
    account_id: accountId ?? null,
    market_value: r2(total),
    fx: holdings.some((h) => h.currency === "USD") ? { USD: FX_NOW } : {},
    groups,
    concentration,
    valued_at_cost: holdings.filter((h) => h.price === null).map((h) => h.symbol),
    can_edit_limits: opts.canEditLimits,
    is_demo: !commercial,
  }
}

export function buildSummary(txns: Transaction[], accountId?: string, commercial = false, opts: AllocationOptions = {}): PortfolioSummary {
  const holdings = buildHoldings(txns, accountId, commercial)
  // 配置與集中度：和 `GET /portfolio/allocation` 同一套分類（2026-11-18）
  const { groups, concentration } = allocationParts(txns, holdings, accountId, commercial, opts)
  const state = replay(txns, MOCK_TODAY, accountId)
  const mv = holdings.reduce((s, h) => s + h.market_value, 0)
  const cost = holdings.reduce((s, h) => s + h.cost_basis, 0)
  const day = holdings.reduce((s, h) => s + h.day_change, 0)
  const unrealized = mv - cost
  const total = unrealized + state.realizedTwd + state.dividendsTwd
  const upcoming = holdings
    .filter((h) => !commercial || h.market !== "US")
    .flatMap((h) => {
      const spec = findInstrument(h.symbol)!
      return dividendRecords(spec)
        .filter((d) => d.ex_dividend_date && d.ex_dividend_date >= MOCK_TODAY && d.ex_dividend_date <= addDays(MOCK_TODAY, 60))
        .map((d) => ({
          symbol: h.symbol,
          name: h.name,
          ex_dividend_date: d.ex_dividend_date!,
          cash_dividend: d.cash_dividend,
          estimated_amount: r2(d.cash_dividend * h.quantity * (h.currency === "USD" ? FX_NOW : 1)),
        }))
    })
    .sort((a, b) => a.ex_dividend_date.localeCompare(b.ex_dividend_date))

  // 和後端相同：混合持股的時間用台股的收盤（美股的收盤在台北是清晨，不能讓台股看起來新了一天）；只有美股時是美股收盤的時間
  const onlyUs = commercial && holdings.some((h) => h.price !== null) && holdings.every((h) => h.price === null || h.market === "US")
  return {
    as_of: onlyUs ? US_AS_OF : MOCK_AS_OF,
    market_value: r2(mv),
    cost_basis: r2(cost),
    unrealized_pnl: r2(unrealized),
    unrealized_pnl_pct: cost ? r4(unrealized / cost) : 0,
    realized_pnl: r2(state.realizedTwd),
    dividend_income: r2(state.dividendsTwd),
    total_pnl: r2(total),
    total_return_pct: cost ? r4(total / cost) : 0,
    day_change: r2(day),
    day_change_pct: mv - day ? r4(day / (mv - day)) : 0,
    allocation: summaryAllocation(groups),
    concentration,
    upcoming_dividends: upcoming,
    is_demo: !commercial,
  }
}

// ── 績效（依 api-contract 的計算定義） ─────────────────────
interface DailyRow extends PerformancePoint {
  r: number
  inflow: number
  outflow: number
  /** 這一天領到的現金股利（新台幣，扣掉預扣稅與二代健保） */
  dividend: number
}

/**
 * 示範用的基準：真實後端支援任何商品與 `^TAIEXTR`（加權報酬指數）；mock 沒有指數資料，
 * 以 0050 的示範走勢代替（整份回應本來就是 is_demo）。
 */
const MOCK_BENCHMARKS: Record<string, { proxy: string; name: string }> = {
  "0050.TW": { proxy: "0050.TW", name: "元大台灣50" },
  "006208.TW": { proxy: "0050.TW", name: "富邦台50" },
  "^TAIEXTR": { proxy: "0050.TW", name: "發行量加權股價報酬指數" },
  VOO: { proxy: "VOO", name: "Vanguard S&P 500 ETF" },
}

export function mockBenchmark(symbol: string | undefined): { symbol: string; proxy: string; name: string } {
  const key = symbol && MOCK_BENCHMARKS[symbol] ? symbol : "0050.TW"
  return { symbol: key, ...MOCK_BENCHMARKS[key]! }
}

/** `legacy`：`?composition=off` 時照原本的示範帳本（投入本金把現金股利當成拿回扣掉），畫面和現在的示範一模一樣 */
function dailyRows(txns: Transaction[], accountId?: string, benchmark = "0050.TW", legacy = false): DailyRow[] {
  const relevant = txns.filter((x) => !accountId || x.account_id === accountId)
  const first = relevant.find((x) => x.symbol)?.trade_date
  if (!first) return []
  const days = tradingDays(1800).filter((d) => d >= first)
  const bench = findInstrument(mockBenchmark(benchmark).proxy)!
  const qty = new Map<string, number>()
  const rows: DailyRow[] = []
  let idx = 0
  let prevV = 0
  let twr = 1
  let invested = 0
  const bench0 = closeOn(bench, days[0]!)
  for (const day of days) {
    let inflow = 0
    let outflow = 0
    let sold = 0
    let dividend = 0
    while (idx < relevant.length && relevant[idx]!.trade_date <= day) {
      const x = relevant[idx++]!
      if (!x.symbol) continue
      const fx = fxFor(x.currency, x.trade_date)
      const q = qty.get(x.symbol) ?? 0
      if (x.type === "buy") {
        qty.set(x.symbol, q + (x.quantity ?? 0))
        inflow += (x.amount + x.fee) * fx
      } else if (x.type === "sell") {
        qty.set(x.symbol, q - (x.quantity ?? 0))
        outflow += (x.amount - x.fee - x.tax) * fx
        sold += (x.amount - x.fee - x.tax) * fx
      } else if (x.type === "split") {
        qty.set(x.symbol, q * (x.quantity ?? 1))
      } else if (x.type === "cash_dividend") {
        const net = (x.amount - x.tax - x.health_insurance) * fx
        outflow += net
        dividend += net
      }
    }
    let v = 0
    for (const [symbol, q] of qty) {
      if (q <= 0) continue
      const spec = findInstrument(symbol)!
      v += q * closeOn(spec, day) * (spec.currency === "USD" ? usdTwd(day) : 1)
    }
    if (day === MOCK_TODAY) {
      v = 0
      for (const [symbol, q] of qty) {
        if (q <= 0) continue
        const spec = findInstrument(symbol)!
        v += q * spec.price * (spec.currency === "USD" ? FX_NOW : 1)
      }
    }
    const denom = prevV + inflow
    const r = denom > 0 ? (v + outflow) / denom - 1 : 0
    twr *= 1 + r
    // 和後端相同（CONTRACT_NOTES：買進成本 − 賣出淨收入，現金股利不扣）：股利不算拿回本金，累積損益才不含股利
    invested += legacy ? inflow - outflow : inflow - sold
    rows.push({
      t: day,
      market_value: r2(v),
      net_invested: r2(invested),
      twr_index: twr,
      benchmark_index: closeOn(bench, day) / bench0,
      r,
      inflow,
      outflow,
      dividend,
    })
    prevV = v
  }
  return rows
}

/** 1D／5D 以交易日計（見 rangeRows），這裡只處理日曆區間：和後端 `range_start` 一樣往前推日曆月（月底對齊） */
function rangeStart(range: Exclude<PerformanceRange, "1D" | "5D" | "MTD">): string {
  switch (range) {
    case "1M": return minusMonths(MOCK_TODAY, 1)
    case "3M": return minusMonths(MOCK_TODAY, 3)
    case "6M": return minusMonths(MOCK_TODAY, 6)
    case "YTD": return `${MOCK_TODAY.slice(0, 4)}-01-01`
    case "1Y": return minusMonths(MOCK_TODAY, 12)
    case "ALL": return "0000-01-01"
  }
}

function xirr(flows: { t: string; amount: number }[]): number | null {
  if (flows.length < 2) return null
  const t0 = parseDay(flows[0]!.t).getTime()
  const years = flows.map((f) => (parseDay(f.t).getTime() - t0) / (365.25 * 86400000))
  let rate = 0.1
  for (let i = 0; i < 100; i++) {
    let f = 0
    let df = 0
    flows.forEach((fl, j) => {
      const y = years[j]!
      const disc = Math.pow(1 + rate, y)
      f += fl.amount / disc
      df -= (y * fl.amount) / (disc * (1 + rate))
    })
    if (Math.abs(df) < 1e-12) break
    const next = rate - f / df
    if (!Number.isFinite(next)) return null
    if (Math.abs(next - rate) < 1e-9) return next
    rate = Math.max(next, -0.99)
  }
  return Number.isFinite(rate) ? rate : null
}

export interface PerformanceOptions {
  /** 商用模式：存檔從這天開始，區間更早時從這天收盤開始計算（當作基準收盤） */
  minStart?: string
  isDemo?: boolean
  /** 資產組成的欄位（原型；`composition`、`fund_rank`）：false 模擬舊版後端（`?composition=off`），回應沒有這兩個欄位 */
  composition?: boolean
}

/**
 * 示範的「贏過幾成的台股基金」（原型）：今年第一個交易日到最新淨值那天（前一個交易日）的時間加權報酬，
 * 和 812 檔境內台股基金的今年報酬（固定亂數，平均 12%）比。今年有估計的那一段時，從真實紀錄的第一天起。
 */
function fundRankOf(all: DailyRow[], estimated: readonly Span[]): FundRank | null {
  const year = MOCK_TODAY.slice(0, 4)
  const end = all.filter((x) => x.t < MOCK_TODAY).at(-1)
  let startIdx = all.findIndex((x) => x.t >= `${year}-01-01`)
  if (startIdx >= 0) {
    while (startIdx < all.length && inSpans(all[startIdx]!.t, estimated)) startIdx++
  }
  const start = all[startIdx]
  const base = all[startIdx - 1]
  if (!end || !start || !base || start.t >= end.t || base.market_value <= 0) return null
  const mine = end.twr_index / base.twr_index - 1
  const r = rng(`funds-${year}`)
  const funds = 812
  let beaten = 0
  // 示範：基金的報酬圍著示範帳本的報酬分布（平均低 3.5 個百分點、標準差 6 個百分點），畫面才是「贏過七成左右」的樣子
  for (let i = 0; i < funds; i++) {
    const u = Math.max(r(), 1e-9)
    const fund = mine - 0.035 + 0.06 * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r())
    if (mine > fund) beaten++
  }
  return {
    start: start.t, end: end.t, beat: Math.round((beaten / funds) * 100) / 100, funds, universe: "境內台股基金",
    source: "金融監督管理委員會證券期貨局〈境內基金每日淨值〉（2026），依政府資料開放授權條款第 1 版",
    notes: ["基金淨值不含配息，配息的基金照公告的配息加回"],
    // 示範：數字是編的，畫面標「示範資料」，來源不登記到頁尾
    is_demo: true,
  }
}

export function buildPerformance(txns: Transaction[], range: PerformanceRange, accountId?: string, benchmark?: string, opts: PerformanceOptions = {}): Performance {
  const isDemo = opts.isDemo ?? true
  const bench = mockBenchmark(benchmark)
  const all = dailyRows(txns, accountId, bench.symbol, opts.composition === false)
  // 1D／5D：最後 N 個交易日的報酬，序列第一點是基準收盤（與後端相同）
  const days = range === "1D" ? 1 : range === "5D" ? 5 : null
  // MTD：上月最後一個收盤是基準點（與後端相同）
  const monthStart = `${MOCK_TODAY.slice(0, 7)}-01`
  const mtdFrom = all.filter((x) => x.t < monthStart).at(-1)?.t ?? monthStart
  let rows =
    days !== null
      ? all.slice(-(days + 1))
      : range === "MTD"
        ? all.filter((x) => x.t >= mtdFrom)
        : all.filter((x) => x.t >= rangeStart(range as Exclude<PerformanceRange, "1D" | "5D" | "MTD">))
  if (opts.minStart) rows = rows.filter((x) => x.t >= opts.minStart!)
  const benchSpec = { symbol: bench.symbol, name: bench.name }
  if (rows.length < 2) {
    return {
      range, start_date: rows[0]?.t ?? MOCK_TODAY, end_date: MOCK_TODAY, twr: null, xirr: null, max_drawdown: null, volatility: null,
      benchmark: { symbol: benchSpec.symbol, name: benchSpec.name, twr: null }, series: rows.map(stripRow),
      dividends_by_month: [], realized_by_year: [], is_demo: isDemo,
      ...(opts.composition === false ? {} : { composition: { dividends: [], estimated: estimatedSpans(txns, accountId), months: [], months_estimated: 0 }, fund_rank: null }),
    }
  }
  // 指數的 1.0：1D／5D、MTD 與從存檔起點開始算（minStart）時是第一點（基準收盤）；1M…1Y 和後端一樣，
  // 第一個收盤那天的漲跌也算進區間，1.0 是它前一個收盤（首頁走勢在前端切區間時，同一個區間的報酬才對得起來）。
  // 區間從第一筆交易開始（ALL、資料比區間短）時照合約：第一點是 1＋第一天的報酬，不是 1.0（CONTRACT_NOTES〈績效計算的解讀〉）
  const before = days === null && range !== "MTD" ? all[all.indexOf(rows[0]!) - 1] : undefined
  const prev = before && !(opts.minStart && before.t < opts.minStart) ? before : undefined
  const fromInception = days === null && range !== "MTD" && !before
  const base = prev ? prev.twr_index : fromInception ? 1 : rows[0]!.twr_index
  const bBase = (prev ?? rows[0]!).benchmark_index ?? 1
  const series: PerformancePoint[] = rows.map((x) => ({
    t: x.t,
    market_value: x.market_value,
    net_invested: x.net_invested,
    twr_index: r4(x.twr_index / base),
    benchmark_index: x.benchmark_index === null ? null : r4(x.benchmark_index / bBase),
  }))
  let peak = 0
  let mdd = 0
  for (const p of series) {
    peak = Math.max(peak, p.twr_index)
    mdd = Math.min(mdd, p.twr_index / peak - 1)
  }
  const rets = rows.slice(1).map((x) => x.r)
  const mean = rets.reduce((s, x) => s + x, 0) / rets.length
  const variance = rets.reduce((s, x) => s + (x - mean) ** 2, 0) / Math.max(rets.length - 1, 1)
  const flows = [
    { t: rows[0]!.t, amount: -rows[0]!.market_value },
    ...rows.slice(1).flatMap((x) => [
      ...(x.inflow ? [{ t: x.t, amount: -x.inflow }] : []),
      ...(x.outflow ? [{ t: x.t, amount: x.outflow }] : []),
    ]),
    { t: rows[rows.length - 1]!.t, amount: rows[rows.length - 1]!.market_value },
  ].filter((f) => f.amount !== 0)
  const startDate = rows[0]!.t
  // 1D／5D 的第一點是基準日：當天的股利與已實現損益不算在區間內
  const flowsFrom = days !== null ? rows[1]!.t : startDate
  const dividends = new Map<string, number>()
  const realized = new Map<number, number>()
  const state = replay(txns, MOCK_TODAY, accountId)
  for (const e of state.realizedEvents) {
    if (e.t < flowsFrom) continue
    const y = Number(e.t.slice(0, 4))
    realized.set(y, (realized.get(y) ?? 0) + e.amount)
  }
  for (const x of txns) {
    if (x.type !== "cash_dividend" || x.trade_date < flowsFrom) continue
    if (accountId && x.account_id !== accountId) continue
    const m = x.trade_date.slice(0, 7)
    dividends.set(m, (dividends.get(m) ?? 0) + (x.amount - x.tax - x.health_insurance) * fxFor(x.currency, x.trade_date))
  }
  const last = series[series.length - 1]!
  // 資產組成（原型）：每天領到的股利、估計的那一段、每個月的拆解。區間的基準收盤：前一個收盤（prev）、
  // 從第一筆開始時沒有（當成 0）、1D／5D／MTD 與從存檔起點開始算時是第一點
  const estimated = estimatedSpans(txns, accountId)
  const baseRow = prev ?? (fromInception ? null : rows[0]!)
  const monthRows = prev || fromInception ? rows : rows.slice(1)
  const toMonthPoint = (x: DailyRow): MonthPoint => ({ t: x.t, market_value: x.market_value, net_invested: x.net_invested, twr_index: x.twr_index, benchmark_index: x.benchmark_index })
  // 暫定：用匯入那天記的買進（找不到買入日）所在的月份不列（`importDays`，產品負責人還沒決定）
  const { months, skipped, skippedImport } = monthlyBreakdown(monthRows.map(toMonthPoint), { base: baseRow ? toMonthPoint(baseRow) : null, estimated, importDays: importDays(txns, accountId) })
  const composition: PerformanceComposition = {
    dividends: rows.filter((x) => x.dividend > 0 && x.t >= flowsFrom).map((x) => ({ t: x.t, amount: r2(x.dividend) })),
    estimated,
    months,
    months_estimated: skipped,
    months_import_day: skippedImport,
  }
  // 估計的那幾段不算年化報酬（區間碰到任何一段時 XIRR 是 null）
  const touchesEstimate = estimated.some((sp) => sp.from <= MOCK_TODAY && sp.until >= startDate)
  return {
    range,
    start_date: startDate,
    end_date: MOCK_TODAY,
    twr: r4(last.twr_index - 1),
    xirr: (() => {
      if (days !== null) return null // 一到五天的現金流年化沒有意義
      if (touchesEstimate && opts.composition !== false) return null
      const v = xirr(flows)
      return v === null ? null : r4(v)
    })(),
    max_drawdown: r4(mdd),
    volatility: r4(Math.sqrt(variance) * Math.sqrt(252)),
    benchmark: { symbol: benchSpec.symbol, name: benchSpec.name, twr: last.benchmark_index === null ? null : r4(last.benchmark_index - 1) },
    series,
    dividends_by_month: [...dividends.entries()].sort().map(([month, amount]) => ({ month, amount: r2(amount) })),
    realized_by_year: [...realized.entries()].sort((a, b) => a[0] - b[0]).map(([year, amount]) => ({ year, amount: r2(amount) })),
    is_demo: isDemo,
    ...(opts.composition === false ? {} : { composition, fund_rank: fundRankOf(all, estimated) }),
  }
}

function stripRow(x: DailyRow): PerformancePoint {
  return { t: x.t, market_value: x.market_value, net_invested: x.net_invested, twr_index: x.twr_index, benchmark_index: x.benchmark_index }
}

export function ensureHistory(spec: MockInstrumentSpec) {
  return dailyCandles(spec)
}
