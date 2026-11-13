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
import { viewAsId } from "../view-as"
import { createAnalystStore } from "./analyst"
import { skipKey, syncAutoDividends } from "./auto-dividends"
import { buildAttributions, sourceOf } from "./attributions"
import { mockMarketStatus, type MockMarket } from "./market-status"
import { buildCompany, buildRelated } from "./company"
import { accumulatingNote, ARCHIVE_START, INDEX_NOTE, US_NOTE, type MockPolicy } from "./commercial"
import { computePreview } from "./fees"
import { findInstrument, INSTRUMENTS, STRESS_INSTRUMENT, type MockInstrumentSpec } from "./instruments"
import { ACCOUNTS, buildHoldings, buildPerformance, buildSummary, mockBenchmark, seedTransactions } from "./ledger"
import { addDays, dailyCandles, dividendRecords, MOCK_AS_OF, MOCK_TODAY, monthlyRevenue, valuationSeries } from "./market"
import { createRecurringStore, seedPlans } from "./recurring"
import { DAD_ACCOUNTS, seedDadTransactions, type RawTrade } from "./members"
import { createSharingStore, type MemberSource } from "./sharing"
import { createDiscussionStore, type DiscussionOptions } from "./discussions"
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
}

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
  /** 台股的市場狀態（預設 closed：最新的收盤價已經進來）；`?market=open|pending` 模擬盤中、收盤後還沒公布 */
  market?: MockMarket
  /** 討論串：示範使用者的公開暱稱、是不是站方管理員、有沒有被停權（預設：沒有暱稱、是管理員、沒有停權） */
  discussion?: DiscussionOptions
  /** 討論串的時鐘（毫秒，預設 Date.now）：頻率限制與暱稱冷卻用實際經過的時間算；測試時換掉就不用等 */
  clock?: () => number
}

export function createMockAdapter(options: MockOptions = {}): ForliosaApi {
  const scenario = options.scenario ?? "default"
  const commercial = (options.policy ?? "commercial") === "commercial"
  const demo = !commercial
  const [minLatency, maxLatency] = options.latency ?? [120, 320]

  let user: User = { id: "usr_01JDEMO", email: "demo@forliosa.local", display_name: "示範使用者", avatar_url: null, preferences: { ...DEFAULT_PREFS } }
  let signedIn = options.signedIn ?? true
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
  // 股利自動入帳：使用者刪掉或改過的自動入帳股利（不再產生）、只記持股帳戶的快照日
  const skips = new Set<string>()
  const snapshotAsOf = new Map<string, string>()
  /** 交易、快照、追蹤模式變更之後重算自動入帳的股利（後端在同一個請求裡做） */
  const resync = () => {
    txns = syncAutoDividends(txns, { accounts, skips, snapshotAsOf: (id) => snapshotAsOf.get(id), today: MOCK_TODAY })
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
      .filter((t) => (t.type === "buy" || t.type === "sell") && t.symbol && ["manual", "import", "ai_draft"].includes(t.source) && t.note !== "持股快照")
      .map((t) => ({ txn_id: t.id, side: t.type as "buy" | "sell", symbol: t.symbol!, trade_date: t.trade_date, quantity: t.quantity ?? 0, price: t.price ?? 0, currency: t.currency, created_at: t.created_at }))
  const periodReturns = (list: Transaction[]) => {
    const summary = buildSummary(list, undefined, commercial)
    const holdings = buildHoldings(list, undefined, commercial)
    // 有任何持股沒有收盤價（商用模式的美股）時，所有期間都是 null（不說明原因）
    if (commercial && holdings.some((h) => h.price === null)) return { day: null, month: null, year: null, total: summary.total_return_pct }
    const opts = { isDemo: !commercial, ...(commercial ? { minStart: ARCHIVE_START } : {}) }
    return {
      day: summary.day_change_pct,
      month: buildPerformance(list, "MTD", undefined, "0050.TW", opts).twr,
      year: buildPerformance(list, "YTD", undefined, "0050.TW", opts).twr,
      total: summary.total_return_pct,
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
    // 商用模式：我有美股、沒有收盤價，週報酬算不出來
    week: (w) => (commercial ? null : ({ "2026-11-02": 0.0097, "2026-10-26": 0.0043 })[w] ?? null),
  }
  const sharing = createSharingStore(
    {
      me: () => ({ user_id: user.id, display_name: user.display_name, avatar_url: user.avatar_url ?? null }),
      signedIn: () => signedIn,
      commercial,
      myAccounts: () => accounts,
      mine,
      dad,
      dadAccounts: DAD_ACCOUNTS,
      origin: () => (typeof window === "undefined" ? "http://localhost:5173" : window.location.origin),
    },
    scenario,
  )

  // ── 討論串：時間從示範資料的「現在」起算，加上開啟後實際經過的時間（10 秒間隔、7 天冷卻都照真的時間） ──
  const clock = options.clock ?? Date.now
  const clockStart = clock()
  const discussions = createDiscussionStore(
    {
      me: () => ({ user_id: user.id, display_name: user.display_name, avatar_url: user.avatar_url ?? null }),
      signedIn: () => signedIn,
      myGroupRoles: () => sharing.myGroupRoles(),
      groupRoster: (id) => sharing.groupRoster(id),
      now: () => Date.parse(MOCK_AS_OF) + (clock() - clockStart),
    },
    scenario,
    options.discussion,
  )
  /** `User`：個人資料多了 public_name、is_admin、public_posting_suspended_until（`GET /me`、開發登入、PATCH 都有） */
  const me = (): User => ({ ...user, ...discussions.meFields() })

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
  const holdingsNow = (accountId?: string) => buildHoldings(ledger(accountId).txns, accountId, commercial)
  /** 商用模式：回應裡最早的資料不早於存檔起點；區間更早時加上「資料累積中」 */
  const clip = <T extends { t: string }>(rows: T[], from: string): { rows: T[]; notes: string[] } =>
    commercial && from < ARCHIVE_START ? { rows: rows.filter((r) => r.t >= ARCHIVE_START), notes: [accumulatingNote()] } : { rows, notes: [] }
  /** 商用模式的績效：含美股（沒有可商用的價格）就算不出來，其餘從存檔起點開始 */
  const commercialPerformance = (txns: Transaction[], range: Parameters<typeof buildPerformance>[1], accountId: string | undefined, benchmark: string) => {
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
    updatePreferences: (patch) =>
      wait(() => {
        user = { ...user, preferences: { ...user.preferences, ...patch } }
        return me()
      }),

    listAccounts: () => wait(() => ledger().accounts),
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
        if (next.tracking_mode !== found.tracking_mode) resync()
        return next
      }),
    deleteAccount: (id) =>
      wait(() => {
        accounts = accounts.filter((a) => a.id !== id)
        txns = txns.filter((t) => t.account_id !== id)
        for (const k of [...skips]) if (k.startsWith(`${id}|`)) skips.delete(k)
        snapshotAsOf.delete(id)
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
        snapshotAsOf.set(id, body.as_of)
        sortTxns()
        resync()
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
    getNews: (symbol) => wait(() => buildNews(spec(symbol), commercial)),
    getRelated: (symbol) => wait(() => buildRelated(spec(symbol), user.preferences.benchmark)),
    getCompany: (symbol) => wait(() => buildCompany(spec(symbol))),
    getPosition: (symbol) => wait(() => buildPosition(spec(symbol), ledger().txns, commercial)),
    getPositionHistory: (symbol) => wait(() => positionHistory(ledger().txns, spec(symbol).symbol)),
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
        const items = filtered.slice(offset, offset + limit)
        return { items, next_cursor: offset + limit < filtered.length ? String(offset + limit) : null }
      }),
    createTransaction: (body) =>
      wait(() => {
        const account = accounts.find((a) => a.id === body.account_id)
        if (!account) throw new ApiError(422, "invalid_account", "請先選擇券商帳戶")
        // 與後端相同：自動入帳只由系統產生
        if ((body.source as string | undefined)?.startsWith("auto")) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：source")
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
        // 與後端相同：數量、價格、日期等輸入改了，沒有指定的手續費、稅、二代健保依新內容重算；買賣與現金股利改了數量或價格時金額也重算
        const inputsChanged = (["quantity", "price", "amount", "type", "trade_date", "symbol", "account_id", "is_day_trade"] as const).some((k) => k in patch)
        if (inputsChanged) {
          const recomputeAmount = patch.amount == null && ["buy", "sell", "cash_dividend"].includes(next.type) && ("quantity" in patch || "price" in patch)
          const p = computePreview(
            { ...next, amount: recomputeAmount ? null : next.amount, fee: patch.fee ?? null, tax: patch.tax ?? null, health_insurance: patch.health_insurance ?? null, source: undefined },
            accounts.find((a) => a.id === next.account_id),
            next.symbol ? findInstrument(next.symbol) : undefined,
          )
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
      wait(() => computePreview(body, accounts.find((a) => a.id === body.account_id), body.symbol ? findInstrument(body.symbol) : undefined)),

    getPortfolioSummary: (accountId) => wait(() => buildSummary(ledger(accountId).txns, accountId, commercial)),
    getHoldings: (accountId) => wait(() => holdingsNow(accountId)),
    // 查看模式：授權者沒有定期定額（示範），本週事項只有除息與入帳
    getUpcoming: (days = 7) =>
      wait(() => buildUpcoming(holdingsNow(), findInstrument, days, ledger().viewing ? [] : recurring.upcoming(MOCK_TODAY, addDays(MOCK_TODAY, days)), commercial)),
    getPerformance: ({ range, account_id, benchmark }) =>
      wait(() => {
        const l = ledger(account_id)
        // 查看模式的基準用授權者的（示範：0050）
        const bench = benchmark ?? (l.viewing ? "0050.TW" : user.preferences.benchmark)
        return commercial ? commercialPerformance(l.txns, range, account_id, bench) : buildPerformance(l.txns, range, account_id, bench)
      }),
    getClosedPositions: (accountId) => wait(() => closedRounds(ledger(accountId).txns, { accountId })),

    listRecurring: (accountId) => wait(() => recurring.list(accountId)),
    createRecurring: (body) => wait(() => recurring.create(body)),
    updateRecurring: (id, patch) => wait(() => recurring.update(id, patch)),
    deleteRecurring: (id) => wait(() => recurring.remove(id)),
    draftRecurring: (id, date) => wait(() => recurring.draft(id, date)),

    getAttributions: () => wait(() => buildAttributions(commercial ? "commercial" : "personal")),
    getMarketStatus: () => wait(() => mockMarketStatus(options.market ?? "closed")),

    getAnalystViews: (symbol) => wait(() => analyst.get(spec(symbol).symbol)),
    requestAnalystViews: (symbol) => wait(() => analyst.request(spec(symbol).symbol)),

    // ── 分享（M5） ──
    getAuthProviders: () => wait(() => ({ discord: true, dev_login: false })),
    // 沒有真的 Discord：整頁回到 next，帶 `auth=signed-in` 當作登入成功
    discordLoginUrl: (next) => `${next}${next.includes("?") ? "&" : "?"}auth=signed-in`,
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
  }

  return guardViewAs(base, (id) => sharing.viewAsOwner(id), wait)
}

// ── 授權查看的路由白名單（與後端相同，預設拒絕） ─────────────────
type MethodName = Exclude<keyof ForliosaApi, "kind">
/** 查看者自己的端點（不帶標頭）：`/me`、偏好、登入、讀自己收到的授權（`GET /delegations`，查看中更新橫幅的範圍） */
const VIEWER_OWN = new Set<MethodName>(["devLogin", "logout", "getMe", "updateMe", "updatePreferences", "getAuthProviders", "discordLoginUrl", "listDelegations", "setPublicName"])
/** 不讀使用者資料的端點：忽略標頭 */
const IGNORES_VIEW_AS = new Set<MethodName>([
  "searchInstruments", "getInstrument", "getQuote", "getQuotes", "getHistory", "getValuation", "getRevenue", "getDividends", "getOverview",
  "getIntraday", "getChips", "getFinancials", "getNews", "getWhy", "getAttributions", "getMarketStatus",
  // 討論串的讀取一律以登入者本人回答（前端在查看模式擋下討論頁）
  "listTopics", "getTopic", "listReplies",
])
/** 以授權者身分回應的唯讀端點 */
export const VIEW_AS_READS = new Set<MethodName>([
  "listAccounts", "getPortfolioSummary", "getHoldings", "getPerformance", "getClosedPositions", "getUpcoming", "listTransactions",
  "getPosition", "getPositionHistory", "getEvents",
])
/** 非 GET 的方法（查看模式一律 read_only） */
const WRITES = new Set<MethodName>([
  "createAccount", "updateAccount", "deleteAccount", "putHoldings", "addWatch", "removeWatch", "createTransaction", "updateTransaction",
  "deleteTransaction", "previewTransaction", "createRecurring", "updateRecurring", "deleteRecurring", "draftRecurring", "requestAnalystViews",
  "createDelegation", "updateDelegation", "deleteDelegation", "createGroup", "updateGroup", "deleteGroup", "transferGroup", "setMemberRole",
  "removeMember", "createInvite", "revokeInvite", "acceptInvite", "putShare", "createComment", "deleteComment", "addReaction", "removeReaction",
  "putDiscord", "patchDiscord", "deleteDiscord", "linkTelegram", "patchTelegram", "deleteTelegram",
  "createTopic", "deleteTopic", "createReply", "deleteReply", "addDiscussionReaction", "removeDiscussionReaction", "reportDiscussion",
  "moderateDiscussion", "createSuspension", "liftSuspension",
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
