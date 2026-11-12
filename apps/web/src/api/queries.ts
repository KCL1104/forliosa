import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, DEV_LOGIN } from "./index"
import {
  ApiError,
  type User,
} from "./types"
import type {
  AccountInput,
  ChipsRange,
  FinancialsPeriod,
  HistoryRange,
  PerformanceRange,
  Preferences,
  TransactionInput,
  TransactionQuery,
} from "./types"

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
  position: (symbol: string) => ["portfolio", "position", symbol] as const,
  why: (symbol: string) => ["why", symbol] as const,
  watchlist: ["watchlist"] as const,
  upcoming: (days: number) => ["portfolio", "upcoming", days] as const,
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

export const meQuery = () => queryOptions({ queryKey: qk.me, queryFn: fetchMe, staleTime: 5 * 60_000 })
export const accountsQuery = () => queryOptions({ queryKey: qk.accounts, queryFn: () => api.listAccounts(), staleTime: 5 * 60_000 })
export const summaryQuery = (accountId?: string) =>
  queryOptions({ queryKey: qk.summary(accountId), queryFn: () => api.getPortfolioSummary(accountId), staleTime: 30_000 })
export const holdingsQuery = (accountId?: string) =>
  queryOptions({ queryKey: qk.holdings(accountId), queryFn: () => api.getHoldings(accountId), staleTime: 30_000 })

export function useMe() {
  return useQuery(meQuery())
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
  return useQuery({ enabled, queryKey: qk.quote(symbol), queryFn: () => api.getQuote(symbol), staleTime: 15_000, refetchInterval: 60_000 })
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
export function usePosition(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.position(symbol), queryFn: () => api.getPosition(symbol), staleTime: 30_000 })
}
export function useWhy(symbol: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.why(symbol), queryFn: () => api.getWhy(symbol), staleTime: 60_000, refetchInterval: 120_000 })
}
export function useWatchlist() {
  return useQuery({ queryKey: qk.watchlist, queryFn: () => api.getWatchlist(), staleTime: 30_000, refetchInterval: 60_000 })
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
