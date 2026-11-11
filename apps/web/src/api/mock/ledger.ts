import type {
  Account,
  AllocationSlice,
  Holding,
  Performance,
  PerformancePoint,
  PerformanceRange,
  PortfolioSummary,
  Transaction,
} from "../types"
import { computePreview } from "./fees"
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
  tradingDays,
  usdTwd,
} from "./market"

export const ACCOUNTS: Account[] = [
  {
    id: "acc_01JSINOPAC", name: "永豐－一般", broker: "永豐金證券", currency: "TWD",
    fee_rate: 0.001425, fee_discount: 0.28, min_fee: 20, min_fee_odd_lot: 1,
    tracking_mode: "transactions", created_at: "2023-03-01T10:00:00+08:00",
  },
  {
    id: "acc_01JCATHAYUS", name: "國泰－複委託", broker: "國泰證券", currency: "USD",
    fee_rate: 0.001, fee_discount: 1, min_fee: 3, min_fee_odd_lot: 3,
    tracking_mode: "transactions", created_at: "2023-05-20T10:00:00+08:00",
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

/** 產生示範交易紀錄（由舊到新） */
export function seedTransactions(): Transaction[] {
  seq = 0
  const t: Transaction[] = []
  t.push(cash("deposit", TW, "2023-03-01", 1_500_000, "初始資金"))
  t.push(trade("buy", TW, "2330.TW", "2023-03-15", 1000))
  t.push(cash("deposit", US, "2023-05-22", 15_000, "匯入美元"))
  t.push(trade("buy", US, "AAPL", "2023-06-01", 10))
  t.push(trade("buy", US, "NVDA", "2023-09-12", 4, Math.round(closeOn(findInstrument("NVDA")!, "2023-09-12") * 1000) / 100, "分割前買進"))
  t.push(trade("buy", TW, "2603.TW", "2024-01-10", 1000))
  t.push(trade("buy", US, "VOO", "2024-02-01", 10))
  t.push(trade("buy", TW, "2317.TW", "2024-03-11", 1000))
  t.push(trade("buy", US, "AAPL", "2024-04-22", 5))
  t.push(trade("buy", TW, "3008.TW", "2024-05-08", 100))
  t.push(trade("buy", TW, "6488.TWO", "2024-05-20", 1000))
  t.push(makeTxn({ account_id: US.id, symbol: "NVDA", type: "split", trade_date: "2024-06-10", quantity: 10, price: null, amount: 0, fee: 0, tax: 0, health_insurance: 0, note: "1 股分割為 10 股" }))
  t.push(trade("buy", TW, "2330.TW", "2024-08-06", 500))
  t.push(trade("buy", TW, "2454.TW", "2024-10-21", 200, undefined, "零股"))
  t.push(trade("sell", TW, "2603.TW", "2025-02-20", 1000))
  t.push(trade("buy", TW, "2317.TW", "2025-04-14", 1000))
  t.push(trade("sell", TW, "3008.TW", "2025-08-12", 100))
  t.push(cash("fee", US, "2025-12-31", 25, "年度帳戶管理費"))

  // 定期定額：0050 每月 6 日 NT$10,000、00878 每月 26 日 NT$8,000（零股）
  for (let y = 2024; y <= 2026; y++) {
    for (let m = 1; m <= 12; m++) {
      const mm = String(m).padStart(2, "0")
      const d1 = `${y}-${mm}-06`
      const d2 = `${y}-${mm}-26`
      if (d1 <= MOCK_TODAY) {
        const p = closeOn(findInstrument("0050.TW")!, nextWeekday(d1))
        t.push(trade("buy", TW, "0050.TW", d1, Math.floor(10000 / p), undefined, "定期定額"))
      }
      if (d2 <= MOCK_TODAY) {
        const p = closeOn(findInstrument("00878.TW")!, nextWeekday(d2))
        t.push(trade("buy", TW, "00878.TW", d2, Math.floor(8000 / p), undefined, "定期定額"))
      }
      if ([3, 6, 9, 12].includes(m) && `${y}-${mm}-21` <= MOCK_TODAY) {
        t.push(cash("interest", TW, `${y}-${mm}-21`, 18 + ((y * 7 + m * 3) % 40), "交割戶利息"))
      }
    }
  }

  t.sort((a, b) => (a.trade_date === b.trade_date ? a.id.localeCompare(b.id) : a.trade_date.localeCompare(b.trade_date)))

  // 現金股利：依除息日持有股數產生
  const dividends: Transaction[] = []
  const held = new Set(t.filter((x) => x.symbol).map((x) => x.symbol!))
  for (const symbol of held) {
    const spec = findInstrument(symbol)!
    const account = spec.market === "US" ? US : TW
    for (const rec of dividendRecords(spec)) {
      if (!rec.ex_dividend_date || !rec.payment_date || rec.payment_date > MOCK_TODAY || rec.cash_dividend <= 0) continue
      const qty = quantityOn(t, symbol, addDays(rec.ex_dividend_date, -1))
      if (qty <= 0) continue
      const p = computePreview({ account_id: account.id, symbol, type: "cash_dividend", trade_date: rec.payment_date, quantity: qty, price: rec.cash_dividend }, account, spec)
      dividends.push(makeTxn({
        account_id: account.id, symbol, type: "cash_dividend", trade_date: nextWeekday(rec.payment_date), quantity: qty, price: rec.cash_dividend,
        amount: p.gross, fee: 0, tax: p.tax, health_insurance: p.health_insurance, note: `${rec.period} 現金股利`,
      }))
    }
  }
  const all = [...t, ...dividends]
  all.sort((a, b) => (a.trade_date === b.trade_date ? a.id.localeCompare(b.id) : a.trade_date.localeCompare(b.trade_date)))
  return all
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
  accounts: Set<string>
  qty: number
  cost: number // 原幣，含買進手續費
  costTwd: number
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
      pos = { symbol: x.symbol, accounts: new Set(), qty: 0, cost: 0, costTwd: 0 }
      positions.set(x.symbol, pos)
    }
    pos.accounts.add(x.account_id)
    const q = x.quantity ?? 0
    switch (x.type) {
      case "buy":
        pos.qty += q
        pos.cost += x.amount + x.fee
        pos.costTwd += (x.amount + x.fee) * fx
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
        break
      }
      case "split":
        pos.qty *= q || 1
        break
      case "capital_reduction":
        pos.qty -= pos.qty * q
        break
      case "stock_dividend":
        pos.qty += Math.floor(pos.qty * ((x.price ?? 0) / 10))
        break
      case "cash_dividend":
        dividendsTwd += (x.amount - x.tax - x.health_insurance) * fx
        break
    }
  }
  return { positions, realizedTwd, realizedByYear, realizedEvents, dividendsTwd }
}

const r2 = (n: number) => Math.round(n * 100) / 100
const r4 = (n: number) => Math.round(n * 10000) / 10000

export function buildHoldings(txns: Transaction[], accountId?: string): Holding[] {
  const state = replay(txns, MOCK_TODAY, accountId)
  const rows: Holding[] = []
  for (const pos of state.positions.values()) {
    if (pos.qty <= 0.0001) continue
    const spec = findInstrument(pos.symbol)!
    const fx = spec.currency === "USD" ? FX_NOW : 1
    const mv = pos.qty * spec.price * fx
    const day = pos.qty * (spec.price - spec.prev_close) * fx
    rows.push({
      symbol: spec.symbol, code: spec.code, name: spec.name, market: spec.market, type: spec.type,
      currency: spec.currency, industry: spec.industry,
      quantity: pos.qty,
      avg_cost: r4(pos.cost / pos.qty),
      cost_basis: r2(pos.costTwd),
      price: spec.price,
      prev_close: spec.prev_close,
      market_value: r2(mv),
      day_change: r2(day),
      day_change_pct: r4(spec.price / spec.prev_close - 1),
      unrealized_pnl: r2(mv - pos.costTwd),
      unrealized_pnl_pct: r4(mv / pos.costTwd - 1),
      weight: 0,
      account_ids: [...pos.accounts],
      is_demo: true,
    })
  }
  const total = rows.reduce((s, h) => s + h.market_value, 0)
  for (const h of rows) h.weight = total ? r4(h.market_value / total) : 0
  return rows.sort((a, b) => b.market_value - a.market_value)
}

const MARKET_LABEL: Record<string, string> = { TWSE: "上市", TPEX: "上櫃", US: "美股" }
const CURRENCY_LABEL: Record<string, string> = { TWD: "新台幣", USD: "美元" }
const TYPE_LABEL: Record<string, string> = { stock: "個股", etf: "ETF" }

function groupBy(holdings: Holding[], key: (h: Holding) => string, label: (k: string) => string): AllocationSlice[] {
  const total = holdings.reduce((s, h) => s + h.market_value, 0)
  const map = new Map<string, number>()
  for (const h of holdings) map.set(key(h), (map.get(key(h)) ?? 0) + h.market_value)
  return [...map.entries()]
    .map(([k, value]) => ({ key: k, label: label(k), value: r2(value), weight: total ? r4(value / total) : 0 }))
    .sort((a, b) => b.value - a.value)
}

export function buildSummary(txns: Transaction[], accountId?: string): PortfolioSummary {
  const holdings = buildHoldings(txns, accountId)
  const state = replay(txns, MOCK_TODAY, accountId)
  const mv = holdings.reduce((s, h) => s + h.market_value, 0)
  const cost = holdings.reduce((s, h) => s + h.cost_basis, 0)
  const day = holdings.reduce((s, h) => s + h.day_change, 0)
  const unrealized = mv - cost
  const total = unrealized + state.realizedTwd + state.dividendsTwd
  const upcoming = holdings
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

  return {
    as_of: MOCK_AS_OF,
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
    allocation: {
      by_market: groupBy(holdings, (h) => h.market, (k) => MARKET_LABEL[k] ?? k),
      by_industry: groupBy(holdings, (h) => h.industry ?? "其他", (k) => k),
      by_currency: groupBy(holdings, (h) => h.currency, (k) => CURRENCY_LABEL[k] ?? k),
      by_type: groupBy(holdings, (h) => h.type, (k) => TYPE_LABEL[k] ?? k),
    },
    upcoming_dividends: upcoming,
    is_demo: true,
  }
}

// ── 績效（依 api-contract 的計算定義） ─────────────────────
interface DailyRow extends PerformancePoint {
  r: number
  inflow: number
  outflow: number
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

function dailyRows(txns: Transaction[], accountId?: string, benchmark = "0050.TW"): DailyRow[] {
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
      } else if (x.type === "split") {
        qty.set(x.symbol, q * (x.quantity ?? 1))
      } else if (x.type === "cash_dividend") {
        outflow += (x.amount - x.tax - x.health_insurance) * fx
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
    invested += inflow - outflow
    rows.push({
      t: day,
      market_value: r2(v),
      net_invested: r2(invested),
      twr_index: twr,
      benchmark_index: closeOn(bench, day) / bench0,
      r,
      inflow,
      outflow,
    })
    prevV = v
  }
  return rows
}

/** 1D／5D 以交易日計（見 rangeRows），這裡只處理日曆區間 */
function rangeStart(range: Exclude<PerformanceRange, "1D" | "5D">): string {
  switch (range) {
    case "1M": return addDays(MOCK_TODAY, -31)
    case "3M": return addDays(MOCK_TODAY, -92)
    case "6M": return addDays(MOCK_TODAY, -183)
    case "YTD": return `${MOCK_TODAY.slice(0, 4)}-01-01`
    case "1Y": return addDays(MOCK_TODAY, -365)
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

export function buildPerformance(txns: Transaction[], range: PerformanceRange, accountId?: string, benchmark?: string): Performance {
  const bench = mockBenchmark(benchmark)
  const all = dailyRows(txns, accountId, bench.symbol)
  // 1D／5D：最後 N 個交易日的報酬，序列第一點是基準收盤（與後端相同）
  const days = range === "1D" ? 1 : range === "5D" ? 5 : null
  const rows = days !== null ? all.slice(-(days + 1)) : all.filter((x) => x.t >= rangeStart(range as Exclude<PerformanceRange, "1D" | "5D">))
  const benchSpec = { symbol: bench.symbol, name: bench.name }
  if (rows.length < 2) {
    return {
      range, start_date: rows[0]?.t ?? MOCK_TODAY, end_date: MOCK_TODAY, twr: null, xirr: null, max_drawdown: null, volatility: null,
      benchmark: { symbol: benchSpec.symbol, name: benchSpec.name, twr: null }, series: rows.map(stripRow),
      dividends_by_month: [], realized_by_year: [], is_demo: true,
    }
  }
  const base = rows[0]!.twr_index
  const bBase = rows[0]!.benchmark_index ?? 1
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
  return {
    range,
    start_date: startDate,
    end_date: MOCK_TODAY,
    twr: r4(last.twr_index - 1),
    xirr: (() => {
      if (days !== null) return null // 一到五天的現金流年化沒有意義
      const v = xirr(flows)
      return v === null ? null : r4(v)
    })(),
    max_drawdown: r4(mdd),
    volatility: r4(Math.sqrt(variance) * Math.sqrt(252)),
    benchmark: { symbol: benchSpec.symbol, name: benchSpec.name, twr: last.benchmark_index === null ? null : r4(last.benchmark_index - 1) },
    series,
    dividends_by_month: [...dividends.entries()].sort().map(([month, amount]) => ({ month, amount: r2(amount) })),
    realized_by_year: [...realized.entries()].sort((a, b) => a[0] - b[0]).map(([year, amount]) => ({ year, amount: r2(amount) })),
    is_demo: true,
  }
}

function stripRow(x: DailyRow): PerformancePoint {
  return { t: x.t, market_value: x.market_value, net_invested: x.net_invested, twr_index: x.twr_index, benchmark_index: x.benchmark_index }
}

export function ensureHistory(spec: MockInstrumentSpec) {
  return dailyCandles(spec)
}
