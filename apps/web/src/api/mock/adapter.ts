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
import { buildAttributions, sourceOf } from "./attributions"
import { accumulatingNote, ARCHIVE_START, INDEX_NOTE, US_NOTE, type MockPolicy } from "./commercial"
import { computePreview } from "./fees"
import { findInstrument, INSTRUMENTS, STRESS_INSTRUMENT, type MockInstrumentSpec } from "./instruments"
import { ACCOUNTS, buildHoldings, buildPerformance, buildSummary, mockBenchmark, seedTransactions } from "./ledger"
import { addDays, dailyCandles, dividendRecords, MOCK_AS_OF, MOCK_TODAY, monthlyRevenue, valuationSeries } from "./market"
import { createRecurringStore, seedPlans } from "./recurring"
import { closedRounds, positionHistory } from "./rounds"
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
  /** 資料政策（預設 commercial，和後端一樣）：commercial 沒有示範標記，存檔不足處回空＋notes */
  policy?: MockPolicy
  /** 模擬網路延遲（毫秒）；測試時設 0 */
  latency?: [number, number]
}

export function createMockAdapter(options: MockOptions = {}): ForliosaApi {
  const scenario = options.scenario ?? "default"
  const commercial = (options.policy ?? "commercial") === "commercial"
  const demo = !commercial
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
  let watch: string[] = scenario === "empty" ? [] : ["2382.TW", "2308.TW", "2881.TW"]
  const recurring = createRecurringStore(scenario === "empty" ? [] : seedPlans(ACCOUNTS[0]!.id), () => accounts)

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
    if (commercial && s.market === "US") throw new ApiError(404, "not_found", "目前沒有報價")
    const last = dailyCandles(s).at(-1)!
    const ref = referencePrice(s)
    const limits = limitsOf(s)
    return {
      symbol: s.symbol, price: s.price, prev_close: s.prev_close,
      change: Math.round((s.price - ref) * 100) / 100,
      change_pct: Math.round((s.price / ref - 1) * 10000) / 10000,
      open: last.o, high: last.h, low: last.l, volume: last.v,
      as_of: s.market === "US" ? "2026-11-12T05:00:00+08:00" : MOCK_AS_OF,
      is_realtime: false, is_demo: demo, source: commercial ? (s.market === "TPEX" ? "tpex-openapi" : "twse-openapi") : "demo",
      reference_price: ref,
      limit_up: limits?.up ?? null,
      limit_down: limits?.down ?? null,
    }
  }
  const tracked = (symbol: string) => watch.includes(symbol) || buildHoldings(txns).some((h) => h.symbol === symbol)
  const holdingsNow = (accountId?: string) => buildHoldings(txns, accountId, commercial)
  /** 商用模式：回應裡最早的資料不早於存檔起點；區間更早時加上「資料累積中」 */
  const clip = <T extends { t: string }>(rows: T[], from: string): { rows: T[]; notes: string[] } =>
    commercial && from < ARCHIVE_START ? { rows: rows.filter((r) => r.t >= ARCHIVE_START), notes: [accumulatingNote()] } : { rows, notes: [] }
  /** 商用模式的績效：含美股（沒有可商用的價格）就算不出來，其餘從存檔起點開始 */
  const commercialPerformance = (range: Parameters<typeof buildPerformance>[1], accountId: string | undefined, benchmark: string) => {
    const usHeld = [...new Set(txns.filter((t) => t.symbol && t.currency === "USD" && (!accountId || t.account_id === accountId)).map((t) => t.symbol!))].sort()
    const empty = buildPerformance([], range, accountId, benchmark, { isDemo: false })
    if (usHeld.length > 0) {
      return {
        ...empty, start_date: null, end_date: null, series: [],
        notes: [`${usHeld.join("、")}：${US_NOTE}，含美股時無法計算績效`, `${accumulatingNote()}；需要持股期間每天的收盤價才能計算績效`],
      }
    }
    const full = buildPerformance(txns, range, accountId, benchmark, { isDemo: false })
    if (!full.start_date || full.start_date >= ARCHIVE_START) return { ...full, notes: [] }
    const clipped = buildPerformance(txns, range, accountId, benchmark, { isDemo: false, minStart: ARCHIVE_START })
    const bench = benchmark === "^TAIEXTR" ? { benchmark: clipped.benchmark ? { ...clipped.benchmark, twr: null } : null, series: clipped.series.map((p) => ({ ...p, benchmark_index: null })) } : {}
    return { ...clipped, ...bench, notes: [`${accumulatingNote()}；績效從 ${clipped.start_date} 收盤開始計算`, ...(benchmark === "^TAIEXTR" ? [INDEX_NOTE] : [])] }
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
        // 商用模式不提供 shioaji-data 的 AI 研究欄位（簡介、產業鏈、題材；授權待定），美股只有商品清單
        if (commercial) {
          const us = s.market === "US"
          return {
            ...strip(s), summary: null, chain_stage: null, themes: [],
            shares_outstanding: us ? null : s.shares_outstanding, market_cap: us ? null : s.market_cap,
            data_sources: us ? ["內建商品清單"] : [sourceOf("shioaji-data/official")], is_demo: false,
          }
        }
        return {
          ...strip(s), summary: s.summary, chain_stage: s.chain_stage, themes: s.themes,
          shares_outstanding: s.shares_outstanding, market_cap: s.market_cap, data_sources: s.data_sources,
          is_demo: true,
        }
      }),
    getQuote: (symbol) => wait(() => quoteOf(spec(symbol))),
    // 批次報價：沒有報價的代號（商用模式的美股）直接略過
    getQuotes: (symbols) => wait(() => symbols.map((x) => spec(x)).filter((x) => !(commercial && x.market === "US")).map(quoteOf)),
    getHistory: (symbol, range) =>
      wait((): History => {
        if (commercial && symbol.startsWith("^")) return { symbol, interval: "1d", candles: [], is_demo: false, sources: [], notes: [INDEX_NOTE] }
        // 指數（^TAIEXTR）：示範資料以 0050 的走勢代替
        const s = symbol.startsWith("^") ? spec(mockBenchmark(symbol).proxy) : spec(symbol)
        if (commercial && s.market === "US") return { symbol: s.symbol, interval: "1d", candles: [], is_demo: false, sources: [], notes: [US_NOTE] }
        const from = rangeFrom(range)
        const { rows, notes } = clip(dailyCandles(s).filter((c) => c.t >= from), from)
        return {
          symbol: symbol.startsWith("^") ? symbol : s.symbol, interval: "1d", candles: rows, is_demo: demo,
          sources: commercial ? [sourceOf(`${s.market === "TPEX" ? "tpex" : "twse"}-openapi/price`)] : [], notes,
        }
      }),
    getValuation: (symbol, range = "5Y") =>
      wait(() => {
        const s = spec(symbol)
        const from = addDays(MOCK_TODAY, -Math.round((range === "MAX" ? 6 : 5) * 365.25))
        const clipped = clip(valuationSeries(s, range === "MAX" ? 6 : 5), from)
        const series = commercial && s.market === "US" ? [] : clipped.rows
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
          notes: commercial
            ? s.market === "US"
              ? [US_NOTE]
              : [...clipped.notes, ...(s.type === "etf" ? ["ETF 沒有每股盈餘與淨值，不提供本益比與股價淨值比區間"] : ["本益比、股價淨值比、殖利率為證交所／櫃買中心公布值；EPS = 收盤價 ÷ 本益比"])]
            : s.type === "etf" ? ["ETF 沒有每股盈餘與淨值，不提供本益比與股價淨值比區間"] : ["示範資料：EPS、淨值與倍數皆為模擬"],
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
    getNews: (symbol) => wait(() => buildNews(spec(symbol), commercial)),
    getPosition: (symbol) => wait(() => buildPosition(spec(symbol), txns, commercial)),
    getPositionHistory: (symbol) => wait(() => positionHistory(txns, spec(symbol).symbol)),
    getWhy: (symbol) => wait(() => buildWhy(spec(symbol))),

    getWatchlist: () =>
      wait(() =>
        watch.map((symbol) => {
          const s = spec(symbol)
          if (commercial) {
            // 沒有盤中來源：迷你走勢是最近 20 個收盤（sparkline_interval = 1d）
            const us = s.market === "US"
            return {
              symbol: s.symbol, name: s.name, quote: us ? null : quoteOf(s),
              sparkline: us ? [] : dailyCandles(s).slice(-20).map((c) => ({ t: c.t, price: c.c })),
              sparkline_interval: "1d" as const, sources: us ? [] : [sourceOf(`${s.market === "TPEX" ? "tpex" : "twse"}-openapi/price`)], is_demo: false,
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
          source: body.source ?? "manual",
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
        Object.assign(found, { ...patch, source: found.source })
        // 沒有手動覆寫稅費時，依新內容重新計算
        if (patch.fee === undefined || patch.tax === undefined) {
          const p = computePreview({ ...found, source: undefined }, accounts.find((a) => a.id === found.account_id), found.symbol ? findInstrument(found.symbol) : undefined)
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

    getPortfolioSummary: (accountId) => wait(() => buildSummary(txns, accountId, commercial)),
    getHoldings: (accountId) => wait(() => holdingsNow(accountId)),
    getUpcoming: (days = 7) => wait(() => buildUpcoming(holdingsNow(), findInstrument, days, recurring.upcoming(MOCK_TODAY, addDays(MOCK_TODAY, days)), commercial)),
    getPerformance: ({ range, account_id, benchmark }) =>
      wait(() =>
        commercial
          ? commercialPerformance(range, account_id, benchmark ?? user.preferences.benchmark)
          : buildPerformance(txns, range, account_id, benchmark ?? user.preferences.benchmark),
      ),
    getClosedPositions: (accountId) => wait(() => closedRounds(txns, { accountId })),

    listRecurring: (accountId) => wait(() => recurring.list(accountId)),
    createRecurring: (body) => wait(() => recurring.create(body)),
    updateRecurring: (id, patch) => wait(() => recurring.update(id, patch)),
    deleteRecurring: (id) => wait(() => recurring.remove(id)),
    draftRecurring: (id, date) => wait(() => recurring.draft(id, date)),

    getAttributions: () => wait(() => buildAttributions(commercial ? "commercial" : "personal")),
  }
}
