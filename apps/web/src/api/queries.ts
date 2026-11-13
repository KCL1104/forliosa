import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, DEV_LOGIN } from "./index"
import {
  ApiError,
  type User,
} from "./types"
import type {
  AccountInput,
  Briefing,
  ChipsRange,
  FinancialsPeriod,
  HistoryRange,
  PerformanceRange,
  Preferences,
  RecurringPlanInput,
  Transaction,
  TransactionInput,
  TransactionQuery,
} from "./types"
import { useReadOnly } from "@/api/view-as"

export const qk = {
  me: ["me"] as const,
  accounts: ["accounts"] as const,
  summary: (accountId?: string) => ["portfolio", "summary", accountId ?? "all"] as const,
  holdings: (accountId?: string) => ["portfolio", "holdings", accountId ?? "all"] as const,
  performance: (range: PerformanceRange, accountId?: string, benchmark?: string) =>
    ["portfolio", "performance", range, accountId ?? "all", benchmark ?? "default"] as const,
  instrument: (symbol: string) => ["instrument", symbol] as const,
  quote: (symbol: string) => ["quote", symbol] as const,
  history: (symbol: string, range: HistoryRange) => ["history", symbol, range] as const,
  valuation: (symbol: string) => ["valuation", symbol] as const,
  revenue: (symbol: string) => ["revenue", symbol] as const,
  dividends: (symbol: string) => ["dividends", symbol] as const,
  search: (q: string) => ["search", q] as const,
  transactions: (query: TransactionQuery) => ["transactions", query] as const,
  overview: (symbol: string) => ["overview", symbol] as const,
  intraday: (symbol: string) => ["intraday", symbol] as const,
  chips: (symbol: string, range: ChipsRange) => ["chips", symbol, range] as const,
  financials: (symbol: string, period: FinancialsPeriod) => ["financials", symbol, period] as const,
  events: (symbol: string) => ["events", symbol] as const,
  news: (symbol: string) => ["news", symbol] as const,
  related: (symbol: string) => ["related", symbol] as const,
  company: (symbol: string) => ["company", symbol] as const,
  position: (symbol: string) => ["portfolio", "position", symbol] as const,
  why: (symbol: string) => ["why", symbol] as const,
  watchlist: ["watchlist"] as const,
  upcoming: (days: number) => ["portfolio", "upcoming", days] as const,
  // 放在 portfolio 底下：交易改了就跟著重新計算
  closed: (accountId?: string) => ["portfolio", "closed", accountId ?? "all"] as const,
  positionHistory: (symbol: string) => ["portfolio", "position-history", symbol] as const,
  recurring: ["recurring"] as const,
  attributions: ["meta", "attributions"] as const,
  marketStatus: ["meta", "market-status"] as const,
  marketOverview: ["market", "overview"] as const,
  briefingLatest: ["ai", "briefings", "latest"] as const,
  briefings: ["ai", "briefings", "list"] as const,
}

/** 後端每頁最多 200 筆：依 cursor 一頁一頁讀，最多讀到 `max` 筆（回傳是否還有更多） */
export const PAGE_LIMIT = 200
export async function listTransactionsUpTo(query: Omit<TransactionQuery, "limit" | "cursor">, max: number): Promise<{ items: Transaction[]; more: boolean }> {
  const items: Transaction[] = []
  let cursor: string | null = null
  do {
    const page = await api.listTransactions({ ...query, limit: Math.min(PAGE_LIMIT, max - items.length), cursor })
    items.push(...page.items)
    cursor = page.next_cursor
  } while (cursor && items.length < max)
  return { items, more: !!cursor }
}

let devAutoLoginTried = false

/**
 * `GET /me`；開發模式連真實後端時，第一次 401 會自動開發登入（每次載入頁面最多一次，避免迴圈）。
 * 開發登入失敗（例如後端不是 dev）時保留原本的 401，由 AuthGate 顯示登入說明。
 */
async function fetchMe(): Promise<User> {
  try {
    return await api.getMe()
  } catch (err) {
    if (DEV_LOGIN.auto && !devAutoLoginTried && err instanceof ApiError && err.status === 401) {
      devAutoLoginTried = true
      try {
        return await api.devLogin({ email: DEV_LOGIN.email })
      } catch {
        throw err
      }
    }
    throw err
  }
}

/**
 * `retryOnMount: false`：沒登入（401）時，之後掛上來的元件不再各自重問一次 `/me`——
 * 不用登入就能讀的頁面（公開討論）裡，每個想知道「有沒有登入」的元件都讀這個查詢；重問會讓登入閘門回到載入中、
 * 把整頁卸載再掛回來。Session 的變化由登入（寫入快取）與 401 的重設（main.tsx）處理。
 */
export const meQuery = () => queryOptions({ queryKey: qk.me, queryFn: fetchMe, staleTime: 5 * 60_000, retryOnMount: false })
export const accountsQuery = () => queryOptions({ queryKey: qk.accounts, queryFn: () => api.listAccounts(), staleTime: 5 * 60_000 })
export const summaryQuery = (accountId?: string) =>
  queryOptions({ queryKey: qk.summary(accountId), queryFn: () => api.getPortfolioSummary(accountId), staleTime: 30_000 })
export const holdingsQuery = (accountId?: string) =>
  queryOptions({ queryKey: qk.holdings(accountId), queryFn: () => api.getHoldings(accountId), staleTime: 30_000 })

export function useMe() {
  return useQuery(meQuery())
}
/**
 * 現在是誰在看（不用登入就能讀的頁面用）：`user` 沒登入是 null。
 * 登入閘門已經確認過 `/me`，所以這裡不會是載入中——只有「有登入」和「沒登入」。
 */
export function useViewer(): { user: User | null; signedIn: boolean } {
  const me = useQuery(meQuery())
  return { user: me.data ?? null, signedIn: !!me.data }
}
export function useAccounts() {
  return useQuery(accountsQuery())
}
export function useSummary(accountId?: string) {
  return useQuery(summaryQuery(accountId))
}
export function useHoldings(accountId?: string) {
  return useQuery(holdingsQuery(accountId))
}
export function usePerformance(range: PerformanceRange, accountId?: string, benchmark?: string) {
  return useQuery({
    queryKey: qk.performance(range, accountId, benchmark),
    queryFn: () => api.getPerformance({ range, account_id: accountId, benchmark }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}
export function useInstrument(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.instrument(symbol), queryFn: () => api.getInstrument(symbol), staleTime: 10 * 60_000, retry: (n, e) => !(e as { status?: number }).status?.toString().startsWith("4") && n < 2 })
}
export function useQuote(symbol: string, enabled = true) {
  // 沒有報價（商用模式的美股）回 404：不重試，也不要每分鐘再問
  return useQuery({
    enabled, queryKey: qk.quote(symbol), queryFn: () => api.getQuote(symbol), staleTime: 15_000,
    refetchInterval: (q) => (q.state.error ? false : 60_000),
    retry: (n, e) => !(e as { status?: number }).status?.toString().startsWith("4") && n < 2,
  })
}
export function useHistory(symbol: string, range: HistoryRange) {
  return useQuery({ queryKey: qk.history(symbol, range), queryFn: () => api.getHistory(symbol, range), placeholderData: keepPreviousData, staleTime: 5 * 60_000 })
}
export function useValuation(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.valuation(symbol), queryFn: () => api.getValuation(symbol, "5Y"), staleTime: 30 * 60_000 })
}
export function useRevenue(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.revenue(symbol), queryFn: () => api.getRevenue(symbol), staleTime: 30 * 60_000 })
}
export function useDividends(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.dividends(symbol), queryFn: () => api.getDividends(symbol), staleTime: 30 * 60_000 })
}
export function useInstrumentSearch(q: string) {
  const query = q.trim()
  return useQuery({
    queryKey: qk.search(query),
    queryFn: () => api.searchInstruments(query),
    enabled: query.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}

function useInvalidatePortfolio() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ["portfolio"] })
    void qc.invalidateQueries({ queryKey: ["transactions"] })
  }
}

export function useCreateTransaction() {
  const invalidate = useInvalidatePortfolio()
  return useMutation({ mutationFn: (body: TransactionInput) => api.createTransaction(body), onSuccess: invalidate })
}
export function useUpdateTransaction() {
  const invalidate = useInvalidatePortfolio()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<TransactionInput> }) => api.updateTransaction(id, patch),
    onSuccess: invalidate,
  })
}
export function useDeleteTransaction() {
  const invalidate = useInvalidatePortfolio()
  return useMutation({ mutationFn: (id: string) => api.deleteTransaction(id), onSuccess: invalidate })
}
export function useUpdatePreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<Preferences>) => api.updatePreferences(patch),
    onSuccess: (user) => qc.setQueryData(qk.me, user),
  })
}
export function useCreateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AccountInput) => api.createAccount(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.accounts })
    },
  })
}
export function useUpdateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<AccountInput> }) => api.updateAccount(id, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.accounts })
    },
  })
}

// ── 重新設計新增（2026-11-12） ─────────────────────────────
const notFound = (n: number, e: unknown) => !(e as { status?: number }).status?.toString().startsWith("4") && n < 2

export function useOverview(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.overview(symbol), queryFn: () => api.getOverview(symbol), staleTime: 60_000, refetchInterval: 60_000, retry: notFound })
}
/** 盤中走勢：持股與自選每 30–60 秒輪詢 */
export function useIntraday(symbol: string, enabled = true) {
  return useQuery({ queryKey: qk.intraday(symbol), queryFn: () => api.getIntraday(symbol), staleTime: 30_000, refetchInterval: 60_000, enabled })
}
export function useChips(symbol: string, range: ChipsRange = "3M") {
  return useQuery({ queryKey: qk.chips(symbol, range), queryFn: () => api.getChips(symbol, range), staleTime: 30 * 60_000, placeholderData: keepPreviousData })
}
export function useFinancials(symbol: string, period: FinancialsPeriod = "quarterly") {
  return useQuery({ queryKey: qk.financials(symbol, period), queryFn: () => api.getFinancials(symbol, period), staleTime: 60 * 60_000, placeholderData: keepPreviousData })
}
export function useEvents(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.events(symbol), queryFn: () => api.getEvents(symbol, false), staleTime: 30 * 60_000 })
}
export function useNews(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.news(symbol), queryFn: () => api.getNews(symbol), staleTime: 10 * 60_000 })
}
/** 相關股票：規則挑選，資料每天更新 */
export function useRelated(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.related(symbol), queryFn: () => api.getRelated(symbol), staleTime: 30 * 60_000 })
}
/** 關於〈公司〉：公司基本資料每天覆寫、簡介每月更新 */
export function useCompany(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.company(symbol), queryFn: () => api.getCompany(symbol), staleTime: 60 * 60_000 })
}
export function usePosition(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.position(symbol), queryFn: () => api.getPosition(symbol), staleTime: 30_000 })
}
export function useWhy(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.why(symbol), queryFn: () => api.getWhy(symbol), staleTime: 60_000, refetchInterval: 120_000 })
}
/** 自選：查看別人的資產時不讀（不在授權查看的白名單） */
export function useWatchlist() {
  const readOnly = useReadOnly()
  return useQuery({ enabled: !readOnly, queryKey: qk.watchlist, queryFn: () => api.getWatchlist(), staleTime: 30_000, refetchInterval: 60_000 })
}
export function useUpcoming(days = 7) {
  return useQuery({ queryKey: qk.upcoming(days), queryFn: () => api.getUpcoming(days), staleTime: 10 * 60_000 })
}
export function useToggleWatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, on }: { symbol: string; on: boolean }) => (on ? api.addWatch(symbol) : api.removeWatch(symbol)),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.watchlist })
    },
  })
}

// ── 第二批（2026-11-12）：出清紀錄、定期定額、資料授權 ─────────────
export function useClosedPositions(accountId?: string) {
  return useQuery({ queryKey: qk.closed(accountId), queryFn: () => api.getClosedPositions(accountId), staleTime: 60_000 })
}
/** 交易歷史（出清的回合與所有買賣點）；未持有也會回 */
export function usePositionHistory(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.positionHistory(symbol), queryFn: () => api.getPositionHistory(symbol), staleTime: 60_000, retry: notFound })
}
/** 定期定額：查看別人的資產時不讀（不在授權查看的白名單） */
export function useRecurringPlans() {
  const readOnly = useReadOnly()
  return useQuery({ enabled: !readOnly, queryKey: qk.recurring, queryFn: () => api.listRecurring(), staleTime: 60_000 })
}
function useInvalidateRecurring() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: qk.recurring })
    // 本週事項列出每一次扣款
    void qc.invalidateQueries({ queryKey: ["portfolio", "upcoming"] })
  }
}
export function useCreateRecurring() {
  const invalidate = useInvalidateRecurring()
  return useMutation({ mutationFn: (body: RecurringPlanInput) => api.createRecurring(body), onSuccess: invalidate })
}
export function useUpdateRecurring() {
  const invalidate = useInvalidateRecurring()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<RecurringPlanInput> }) => api.updateRecurring(id, patch),
    onSuccess: invalidate,
  })
}
export function useDeleteRecurring() {
  const invalidate = useInvalidateRecurring()
  return useMutation({ mutationFn: (id: string) => api.deleteRecurring(id), onSuccess: invalidate })
}
export function useAttributions() {
  return useQuery({ queryKey: qk.attributions, queryFn: () => api.getAttributions(), staleTime: 60 * 60_000 })
}

/**
 * 台股現在是不是盤中、今天是不是交易日：大約每分鐘問一次（開盤、收盤的那一刻不用重新整理也會換）。
 * 只用來決定價格旁要不要加一行說明；載入失敗就當作沒有說明，不重試、不報錯。
 */
/** 市場頁：收盤後的資料，一天只變幾次；AI 整理產生後下一次重新整理就看得到 */
export function useMarketOverview() {
  return useQuery({ queryKey: qk.marketOverview, queryFn: () => api.getMarketOverview(), staleTime: 60_000, refetchInterval: 5 * 60_000 })
}

/**
 * 每日收盤簡報：最新一則（過了兩個交易日、沒開、還沒產生都是 null）。一天只產生一次，不用常問。
 * `enabled`：查看別人的資產時不問（那是登入者自己的 AI 內容）。
 */
export function useLatestBriefing(enabled = true) {
  return useQuery({ enabled, queryKey: qk.briefingLatest, queryFn: () => api.getLatestBriefing(), staleTime: 5 * 60_000, refetchInterval: 15 * 60_000 })
}
export function useBriefings(enabled = true) {
  return useQuery({ enabled, queryKey: qk.briefings, queryFn: () => api.listBriefings(14), staleTime: 5 * 60_000 })
}
/** 看過了：未讀的圓點馬上消失，伺服器記下來（別的裝置也不再標未讀） */
export function useMarkBriefingRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.markBriefingRead(id),
    onMutate: (id) => {
      qc.setQueryData<Briefing | null>(qk.briefingLatest, (b) => (b && b.id === id ? { ...b, read: true } : b))
      qc.setQueryData<Briefing[]>(qk.briefings, (list) => list?.map((b) => (b.id === id ? { ...b, read: true } : b)))
    },
  })
}

export function useMarketStatus() {
  return useQuery({ queryKey: qk.marketStatus, queryFn: () => api.getMarketStatus(), staleTime: 30_000, refetchInterval: 60_000, retry: false })
}
