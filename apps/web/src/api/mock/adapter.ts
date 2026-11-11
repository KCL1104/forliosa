import {
  ApiError,
  type Account,
  type ForliosaApi,
  type History,
  type HistoryRange,
  type Preferences,
  type Quote,
  type Transaction,
  type User,
} from "../types"
import { computePreview } from "./fees"
import { findInstrument, INSTRUMENTS, STRESS_INSTRUMENT, type MockInstrumentSpec } from "./instruments"
import { ACCOUNTS, buildHoldings, buildPerformance, buildSummary, seedTransactions } from "./ledger"
import { addDays, dailyCandles, dividendRecords, MOCK_AS_OF, MOCK_TODAY, monthlyRevenue, valuationSeries } from "./market"

/**
 * 示範情境：
 * - default：一般示範資料
 * - empty：首次使用（沒有任何交易與持股）
 * - stress：極端資料（超長股名、上千億金額、大幅虧損），給 harden 測試用
 * 以網址 `?mock=empty` 切換，會記在 sessionStorage。
 */
export type MockScenario = "default" | "empty" | "stress"

export function readMockScenario(): MockScenario {
  if (typeof window === "undefined") return "default"
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("mock")
    if (fromUrl === "empty" || fromUrl === "stress" || fromUrl === "default") {
      window.sessionStorage.setItem("forliosa:mock", fromUrl)
      return fromUrl
    }
    const saved = window.sessionStorage.getItem("forliosa:mock")
    if (saved === "empty" || saved === "stress") return saved
  } catch {
    // sessionStorage 不可用時使用預設情境
  }
  return "default"
}

const DEFAULT_PREFS: Preferences = {
  color_convention: "tw",
  theme: "system",
  quantity_unit: "lot",
  privacy_mode: false,
  cost_method: "average",
  benchmark: "0050.TW",
}

export interface MockOptions {
  scenario?: MockScenario
  /** 模擬網路延遲（毫秒）；測試時設 0 */
  latency?: [number, number]
}

export function createMockAdapter(options: MockOptions = {}): ForliosaApi {
  const scenario = options.scenario ?? "default"
  const [minLatency, maxLatency] = options.latency ?? [120, 320]

  let user: User = { id: "usr_01JDEMO", email: "demo@forliosa.local", display_name: "示範使用者", preferences: { ...DEFAULT_PREFS } }
  let accounts: Account[] = scenario === "empty" ? [] : ACCOUNTS.map((a) => ({ ...a }))
  let txns: Transaction[] = scenario === "empty" ? [] : seedTransactions()
  if (scenario === "stress") {
    txns.push({
      id: "txn_stress", account_id: ACCOUNTS[0]!.id, symbol: STRESS_INSTRUMENT.symbol, type: "buy", trade_date: "2025-06-02",
      quantity: 9_876_543, price: 13_420, amount: 132_543_207_060, fee: 52_998_000, tax: 0, health_insurance: 0,
      currency: "TWD", is_day_trade: false, note: "壓力測試：極端金額與超長名稱", source: "manual", created_at: "2025-06-02T14:00:00+08:00",
    })
    txns.sort((a, b) => a.trade_date.localeCompare(b.trade_date))
  }
  let nextId = 90000

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
  const strip = (s: MockInstrumentSpec) => ({
    symbol: s.symbol, code: s.code, name: s.name, market: s.market, type: s.type, currency: s.currency, industry: s.industry,
  })
  const quoteOf = (s: MockInstrumentSpec): Quote => {
    const last = dailyCandles(s).at(-1)!
    return {
      symbol: s.symbol, price: s.price, prev_close: s.prev_close,
      change: Math.round((s.price - s.prev_close) * 100) / 100,
      change_pct: Math.round((s.price / s.prev_close - 1) * 10000) / 10000,
      open: last.o, high: last.h, low: last.l, volume: last.v,
      as_of: s.market === "US" ? "2026-11-11T05:00:00+08:00" : MOCK_AS_OF,
      is_realtime: false, is_demo: true, source: "demo",
    }
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

  return {
    kind: "mock",
    devLogin: (body) =>
      wait(() => (user = { ...user, email: body.email, display_name: body.display_name ?? body.email.split("@")[0]! })),
    logout: () => wait(undefined),
    getMe: () => wait(() => user),
    updatePreferences: (patch) => wait(() => (user = { ...user, preferences: { ...user.preferences, ...patch } })),

    listAccounts: () => wait(() => accounts),
    createAccount: (body) =>
      wait(() => {
        const acc: Account = { ...body, id: `acc_${++nextId}`, created_at: new Date().toISOString() }
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
        accounts = accounts.filter((a) => a.id !== id)
        txns = txns.filter((t) => t.account_id !== id)
      }),
    putHoldings: (id, body) =>
      wait(() => {
        txns = txns.filter((t) => t.account_id !== id)
        for (const h of body.holdings) {
          txns.push({
            id: `txn_${++nextId}`, account_id: id, symbol: h.symbol, type: "buy", trade_date: body.as_of, quantity: h.quantity,
            price: h.avg_cost, amount: Math.round(h.quantity * h.avg_cost), fee: 0, tax: 0, health_insurance: 0,
            currency: accounts.find((a) => a.id === id)?.currency ?? "TWD", is_day_trade: false, note: "持股快照", source: "manual",
            created_at: new Date().toISOString(),
          })
        }
        sortTxns()
      }),

    searchInstruments: (q) =>
      wait(() => {
        const query = q.trim().toLowerCase()
        if (!query) return []
        return visible()
          .filter((i) => i.code.toLowerCase().includes(query) || i.name.toLowerCase().includes(query) || i.symbol.toLowerCase().includes(query))
          .sort((a, b) => Number(b.code.toLowerCase().startsWith(query)) - Number(a.code.toLowerCase().startsWith(query)))
          .slice(0, 20)
          .map(strip)
      }),
    getInstrument: (symbol) =>
      wait(() => {
        const s = spec(symbol)
        return {
          ...strip(s), summary: s.summary, chain_stage: s.chain_stage, themes: s.themes,
          shares_outstanding: s.shares_outstanding, market_cap: s.market_cap, data_sources: s.data_sources,
          is_demo: true,
        }
      }),
    getQuote: (symbol) => wait(() => quoteOf(spec(symbol))),
    getQuotes: (symbols) => wait(() => symbols.map((s) => quoteOf(spec(s)))),
    getHistory: (symbol, range) =>
      wait((): History => {
        const s = spec(symbol)
        const from = rangeFrom(range)
        return { symbol: s.symbol, interval: "1d", candles: dailyCandles(s).filter((c) => c.t >= from), is_demo: true }
      }),
    getValuation: (symbol, range = "5Y") =>
      wait(() => {
        const s = spec(symbol)
        const series = valuationSeries(s, range === "MAX" ? 6 : 5)
        const last = series.at(-1)
        const pers = series.map((p) => p.per).filter((x): x is number => x !== null)
        const currentPer = last?.per ?? null
        return {
          symbol: s.symbol,
          per_multiples: s.per_multiples ?? [],
          pbr_multiples: s.pbr_multiples ?? [],
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
          notes: s.type === "etf" ? ["ETF 沒有每股盈餘與淨值，不提供本益比與股價淨值比區間"] : ["示範資料：EPS、淨值與倍數皆為模擬"],
          is_demo: true,
        }
      }),
    getRevenue: (symbol) => wait(() => monthlyRevenue(spec(symbol))),
    getDividends: (symbol) => wait(() => dividendRecords(spec(symbol))),

    listTransactions: (query) =>
      wait(() => {
        const filtered = txns
          .filter((t) => !query.account_id || t.account_id === query.account_id)
          .filter((t) => !query.symbol || t.symbol === query.symbol)
          .filter((t) => !query.type || t.type === query.type)
          .filter((t) => !query.from || t.trade_date >= query.from)
          .filter((t) => !query.to || t.trade_date <= query.to)
          .slice()
          .reverse()
        const offset = query.cursor ? Number(query.cursor) : 0
        const limit = query.limit ?? 50
        const items = filtered.slice(offset, offset + limit)
        return { items, next_cursor: offset + limit < filtered.length ? String(offset + limit) : null }
      }),
    createTransaction: (body) =>
      wait(() => {
        const account = accounts.find((a) => a.id === body.account_id)
        if (!account) throw new ApiError(422, "invalid_account", "請先選擇券商帳戶")
        const s = body.symbol ? spec(body.symbol) : undefined
        const p = computePreview(body, account, s)
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
          source: "manual",
          created_at: new Date().toISOString(),
        }
        txns.push(txn)
        sortTxns()
        return txn
      }),
    updateTransaction: (id, patch) =>
      wait(() => {
        const found = txns.find((t) => t.id === id)
        if (!found) throw new ApiError(404, "not_found", "找不到這筆交易")
        Object.assign(found, patch)
        // 沒有手動覆寫稅費時，依新內容重新計算
        if (patch.fee === undefined || patch.tax === undefined) {
          const p = computePreview({ ...found }, accounts.find((a) => a.id === found.account_id), found.symbol ? findInstrument(found.symbol) : undefined)
          if (patch.fee === undefined) found.fee = p.fee
          if (patch.tax === undefined) found.tax = p.tax
          found.health_insurance = p.health_insurance
          found.amount = patch.amount ?? p.gross
        }
        sortTxns()
        return { ...found }
      }),
    deleteTransaction: (id) =>
      wait(() => {
        txns = txns.filter((t) => t.id !== id)
      }),
    previewTransaction: (body) =>
      wait(() => computePreview(body, accounts.find((a) => a.id === body.account_id), body.symbol ? findInstrument(body.symbol) : undefined)),

    getPortfolioSummary: (accountId) => wait(() => buildSummary(txns, accountId)),
    getHoldings: (accountId) => wait(() => buildHoldings(txns, accountId)),
    getPerformance: ({ range, account_id, benchmark }) =>
      wait(() => buildPerformance(txns, range, account_id, benchmark ?? user.preferences.benchmark)),
  }
}
