import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "./index"
import type {
  AccountInput,
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
}

export const meQuery = () => queryOptions({ queryKey: qk.me, queryFn: () => api.getMe(), staleTime: 5 * 60_000 })
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
export function useInstrument(symbol: string) {
  return useQuery({ queryKey: qk.instrument(symbol), queryFn: () => api.getInstrument(symbol), staleTime: 10 * 60_000, retry: (n, e) => !(e as { status?: number }).status?.toString().startsWith("4") && n < 2 })
}
export function useQuote(symbol: string) {
  return useQuery({ queryKey: qk.quote(symbol), queryFn: () => api.getQuote(symbol), staleTime: 15_000, refetchInterval: 60_000 })
}
export function useHistory(symbol: string, range: HistoryRange) {
  return useQuery({ queryKey: qk.history(symbol, range), queryFn: () => api.getHistory(symbol, range), placeholderData: keepPreviousData, staleTime: 5 * 60_000 })
}
export function useValuation(symbol: string) {
  return useQuery({ queryKey: qk.valuation(symbol), queryFn: () => api.getValuation(symbol, "5Y"), staleTime: 30 * 60_000 })
}
export function useRevenue(symbol: string) {
  return useQuery({ queryKey: qk.revenue(symbol), queryFn: () => api.getRevenue(symbol), staleTime: 30 * 60_000 })
}
export function useDividends(symbol: string) {
  return useQuery({ queryKey: qk.dividends(symbol), queryFn: () => api.getDividends(symbol), staleTime: 30 * 60_000 })
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
export function useUpdateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<AccountInput> }) => api.updateAccount(id, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.accounts })
    },
  })
}
