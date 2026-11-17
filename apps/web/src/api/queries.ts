import { keepPreviousData, queryOptions, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, DEV_LOGIN } from "./index"
import {
  ApiError,
  type User,
} from "./types"
import type {
  AccountInput,
  ReportKind,
  ReportsStatus,
  ReportVariant,
  Briefing,
  ChipsRange,
  FinancialsPeriod,
  HistoryRange,
  PerformanceRange,
  PositionsCommitInput,
  Preferences,
  RecurringPlanInput,
  Transaction,
  TransactionBatchInput,
  TransactionInput,
  TransactionQuery,
} from "./types"
import { useReadOnly } from "@/api/view-as"

export const qk = {
  me: ["me"] as const,
  accounts: ["accounts"] as const,
  summary: (accountId?: string) => ["portfolio", "summary", accountId ?? "all"] as const,
  holdings: (accountId?: string) => ["portfolio", "holdings", accountId ?? "all"] as const,
  /** 「只記持股」帳戶的快照：放在 portfolio 底下，存了快照、刪了帳戶就跟著重新讀 */
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
  /** 只有定期定額扣款（`types=recurring`）：AI 面板在每一頁都讀，不算持股與股利 */
  upcomingRecurring: (days: number) => ["portfolio", "upcoming", days, "recurring"] as const,
  // 放在 portfolio 底下：交易改了就跟著重新計算
  closed: (accountId?: string) => ["portfolio", "closed", accountId ?? "all"] as const,
  /** 清除所有持倉的筆數：放在 portfolio 底下，記了、刪了紀錄就跟著重新數 */
  recordCounts: ["portfolio", "records"] as const,
  positionHistory: (symbol: string) => ["portfolio", "position-history", symbol] as const,
  recurring: ["recurring"] as const,
  attributions: ["meta", "attributions"] as const,
  marketStatus: ["meta", "market-status"] as const,
  marketOverview: ["market", "overview"] as const,
  briefingLatest: ["ai", "briefings", "latest"] as const,
  briefings: ["ai", "briefings", "list"] as const,
  // 市場報告：都在 ["market", "reports"] 底下（管理員改了模式、加了更正就整組重新讀）
  reports: ["market", "reports"] as const,
  reportsStatus: ["market", "reports", "status"] as const,
  reportLatest: (kind?: ReportKind) => ["market", "reports", "latest", kind ?? "any"] as const,
  report: (id: string, version?: number) => ["market", "reports", "one", id, version ?? "current"] as const,
  reportList: (kind?: ReportKind) => ["market", "reports", "list", kind ?? "all"] as const,
  // 盲測開給所有人時：一份的 A／B／C 狀態與我的票、一個版本的全文
  reportTrial: (id: string) => ["market", "reports", "trial", id] as const,
  reportVariant: (id: string, label: ReportVariant) => ["market", "reports", "variant", id, label] as const,
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
/** 4xx：問了也一樣（例如沒有報價的 404），不重試、不再問 */
const isClientError = (e: unknown) => !!(e as { status?: number } | null)?.status?.toString().startsWith("4")

export function useQuote(symbol: string, enabled = true) {
  // 沒有報價（還沒有收盤價的美股，或美股收盤價沒開）回 404：不重試，也不要每分鐘再問。
  // 暫時的錯誤（5xx、網路斷了）照樣每分鐘再問：不然第一次就遇到的話，台股整頁一直停在「沒有報價」
  return useQuery({
    enabled, queryKey: qk.quote(symbol), queryFn: () => api.getQuote(symbol), staleTime: 15_000,
    refetchInterval: (q) => (isClientError(q.state.error) ? false : 60_000),
    retry: (n, e) => !isClientError(e) && n < 2,
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

/** 記了、改了、刪了紀錄之後重抓：持股與總資產、紀錄、個股事件（「刪除這檔」不知道刪了沒有時也用） */
export function useInvalidatePortfolio() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ["portfolio"] })
    void qc.invalidateQueries({ queryKey: ["transactions"] })
    // 個股頁的事件（「你可領約 NT$…」）照持股算：記了交易也要重抓（2026-11-14 review）
    void qc.invalidateQueries({ queryKey: ["events"] })
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
/** 匯入對帳單：一次寫入整批（全部或全不）；寫進去之後持股、總資產、交易清單重抓 */
export function useCreateTransactionBatch() {
  const invalidate = useInvalidatePortfolio()
  return useMutation({ mutationFn: (body: TransactionBatchInput) => api.createTransactionBatch(body), onSuccess: invalidate })
}
/** 匯入庫存：一次寫入（每一檔一筆買進；以券商為準的刪除在同一個交易裡）；寫進去之後持股、總資產、交易清單重抓 */
export function useCommitPositions() {
  const invalidate = useInvalidatePortfolio()
  return useMutation({ mutationFn: (body: PositionsCommitInput) => api.commitPositions(body), onSuccess: invalidate })
}
/** 匯入的「復原」：整批刪掉（不是一筆一筆刪：有賣出的批次一筆一筆刪會被擋） */
export function useDeleteTransactionBatch() {
  const invalidate = useInvalidatePortfolio()
  return useMutation({ mutationFn: (batchId: string) => api.deleteTransactionBatch(batchId), onSuccess: invalidate })
}
/**
 * 刪除這檔：一個帳戶裡這一檔的每一筆紀錄（不是賣出）。和刪一筆交易一樣重抓持股、總資產、紀錄與個股事件；
 * 一起暫停了定期定額時，定期定額與本週事項（每一次扣款）也重抓
 */
export function useDeleteHolding() {
  const qc = useQueryClient()
  const invalidate = useInvalidatePortfolio()
  return useMutation({
    mutationFn: ({ accountId, symbol, pausePlans }: { accountId: string; symbol: string; pausePlans?: boolean }) =>
      api.deleteHolding(accountId, symbol, { pausePlans }),
    onSuccess: (res) => {
      invalidate()
      if (res.plans_paused > 0) void qc.invalidateQueries({ queryKey: qk.recurring })
    },
  })
}
/**
 * 清除所有持倉的確認框：每個帳戶有幾筆紀錄（打開時重新數，不拿舊的）。網路恢復時不自己重抓：確認框裡的範圍是使用者選的，
 * 筆數在打字確認的中途變來變去沒有幫助（範圍本身不會跟著變，見 `ClearRecordsDialog`）
 */
export function useRecordCounts(enabled = true) {
  return useQuery({ enabled, queryKey: qk.recordCounts, queryFn: () => api.getRecordCounts(), staleTime: 0, refetchOnReconnect: false })
}
/**
 * 清除所有持倉：一個帳戶（`accountId`）或全部帳戶（`null`）的每一筆紀錄。和刪除這檔一樣重抓持股、總資產、紀錄與個股事件；
 * 一起暫停了定期定額時，定期定額也重抓（本週事項在 portfolio 底下，已經跟著重抓）。404 `no_records`（別的分頁已經清掉了）
 * 也一樣重抓：後端照樣做了要求的暫停（`extra.plans_paused`）
 */
export function useClearRecords() {
  const qc = useQueryClient()
  const invalidate = useInvalidatePortfolio()
  const settle = (plansPaused: unknown) => {
    invalidate()
    if (typeof plansPaused === "number" && plansPaused > 0) void qc.invalidateQueries({ queryKey: qk.recurring })
  }
  return useMutation({
    mutationFn: ({ accountId, pausePlans }: { accountId: string | null; pausePlans?: boolean }) => api.clearRecords(accountId, { pausePlans }),
    onSuccess: (res) => settle(res.plans_paused),
    onError: (err) => {
      if (err instanceof ApiError && err.code === "no_records") settle(err.extra.plans_paused)
    },
  })
}
export function useUpdatePreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<Preferences>) => api.updatePreferences(patch),
    onSuccess: (user, patch) => {
      qc.setQueryData(qk.me, user)
      // 開關「每日收盤簡報」：有沒有簡報跟著變
      if (patch.daily_briefing !== undefined) void qc.invalidateQueries({ queryKey: ["ai", "briefings"] })
      // 換成本計算方式：已實現損益、均價、績效都重算（2026-11-14 review：原本要等重新整理才看得到）
      if (patch.cost_method !== undefined) {
        void qc.invalidateQueries({ queryKey: ["portfolio"] })
        void qc.invalidateQueries({ queryKey: ["transactions"] })
      }
    },
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
/** 刪除帳戶（不能復原）：帳戶清單、持股、紀錄、定期定額都跟著重新讀 */
export function useDeleteAccount() {
  const qc = useQueryClient()
  const invalidate = useInvalidatePortfolio()
  return useMutation({
    mutationFn: (id: string) => api.deleteAccount(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.accounts })
      void qc.invalidateQueries({ queryKey: qk.recurring })
      invalidate()
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
/** 本週事項裡的定期定額扣款（和 `useUpcoming` 的 recurring 項目相同；後端不重算帳本、不讀股利） */
export function useUpcomingRecurring(days = 7) {
  return useQuery({
    queryKey: qk.upcomingRecurring(days),
    queryFn: () => api.getUpcoming(days, { types: "recurring" }),
    staleTime: 10 * 60_000,
  })
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

/**
 * 台股現在是不是盤中、上市與上櫃的收盤價進來了沒有（`tw.closes`）。每分鐘問一次（分頁在背景時不問）；
 * 回到這個分頁時馬上再問（全站預設不在回到分頁時重抓）：收盤價進來時帳本自己更新（`useCloseRefresh`）。
 */
export function useMarketStatus() {
  return useQuery({ queryKey: qk.marketStatus, queryFn: () => api.getMarketStatus(), staleTime: 30_000, refetchInterval: 60_000, refetchOnWindowFocus: true, retry: false })
}

// ── 市場報告（盤前重點、盤後重點、市場週報；2026-11-17） ──────────────
/** 報告一頁 10 份（「再看 10 份」） */
export const REPORT_PAGE_SIZE = 10
/**
 * 有沒有報告可看、有沒有新的（市場頁的「報告」分頁、導覽的未讀小圓點）。外殼一直掛著，所以 5 分鐘問一次；
 * 失敗就當作沒有（不重試、不報錯：市場頁照舊）。
 */
export function useMarketReportStatus(enabled = true) {
  return useQuery<ReportsStatus>({ enabled, queryKey: qk.reportsStatus, queryFn: () => api.getMarketReportStatus(), staleTime: 60_000, refetchInterval: 5 * 60_000, retry: false })
}
/** 某一種最新的一份（沒有就是 null） */
export function useMarketReportLatest(kind: ReportKind, enabled = true) {
  return useQuery({ enabled, queryKey: qk.reportLatest(kind), queryFn: () => api.getLatestMarketReport(kind), staleTime: 60_000, retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 1 })
}
/** 一份報告（`version` 看舊版）；看不到是 404 */
export function useMarketReport(id: string, version?: number) {
  return useQuery({ queryKey: qk.report(id, version), queryFn: () => api.getMarketReport(id, version), staleTime: 60_000, retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 1 })
}
/**
 * 更早的報告（新到舊；「再看 10 份」＝下一頁）。第一頁多讀一份：最新的那一份已經整份顯示在上面，清單不再列它，
 * 先看到的還是 10 份。
 */
export function useMarketReports(kind?: ReportKind, enabled = true) {
  return useInfiniteQuery({
    enabled,
    queryKey: qk.reportList(kind),
    queryFn: ({ pageParam }) => api.listMarketReports({ kind, limit: pageParam ? REPORT_PAGE_SIZE : REPORT_PAGE_SIZE + 1, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}
/** 盲測的一份：A／B／C 哪些能看、我的票（盲測開給所有人時；否則 404，不重試） */
export function useMarketReportTrial(id: string, enabled = true) {
  return useQuery({ enabled, queryKey: qk.reportTrial(id), queryFn: () => api.getMarketReportTrial(id), staleTime: 30_000, refetchInterval: 2 * 60_000, retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 1 })
}
/** 盲測的一個版本（一般形式）；還在寫是 409、沒有寫成是 404 */
export function useMarketReportVariant(id: string, label: ReportVariant, enabled = true) {
  return useQuery({ enabled, queryKey: qk.reportVariant(id, label), queryFn: () => api.getMarketReportVariant(id, label), staleTime: 5 * 60_000, retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 1 })
}
/** 投票／改票：回來的就是這一份最新的狀態；清單與「每種最新一份」上的「你選了」也重新讀 */
export function useVoteMarketReport(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (preferred: ReportVariant) => api.voteMarketReport(id, preferred),
    onSuccess: (t) => {
      qc.setQueryData(qk.reportTrial(id), t)
      void qc.invalidateQueries({ queryKey: qk.reportsStatus })
      void qc.invalidateQueries({ queryKey: ["market", "reports", "list"] })
      void qc.invalidateQueries({ queryKey: ["admin", "market-reports", "trial"] }) // 管理員也是投票的人：後台的票數
    },
  })
}
/** 看過了：未讀的小圓點馬上消失（伺服器記下來，別的裝置也不再標未讀）；查看別人的資產時不呼叫 */
export function useMarkReportsSeen() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.markMarketReportsSeen(),
    onMutate: () => qc.setQueryData<ReportsStatus>(qk.reportsStatus, (s) => (s ? { ...s, unread: false } : s)),
  })
}
