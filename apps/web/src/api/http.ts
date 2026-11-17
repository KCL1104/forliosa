import {
  ApiError,
  type Account,
  type AccountInput,
  type ApiErrorBody,
  type DividendRecord,
  type ForliosaApi,
  type History,
  type HistoryRange,
  type Holding,
  type Instrument,
  type InstrumentDetail,
  type MonthlyRevenue,
  type Page,
  type Performance,
  type PortfolioSummary,
  type Preferences,
  type Quote,
  type TradePreview,
  type Transaction,
  type TransactionInput,
  type TransactionQuery,
  type User,
  type Valuation,
  type Chips,
  type Financials,
  type InstrumentEvent,
  type InstrumentOverview,
  type Intraday,
  type NewsItem,
  type Position,
  type UpcomingItem,
  type WatchItem,
  type Why,
  type Attributions,
  type Briefing,
  type MarketOverview,
  type MarketStatus,
  type ClosedRound,
  type PositionHistory,
  type RecurringDraft,
  type RecurringPlan,
  type AnalystViews,
  type CompanyAbout,
  type RelatedStocks,
} from "./types"
import type {
  AuthProviders,
  Channels,
  Comment,
  DailyClose,
  Delegation,
  DelegationCandidate,
  DelegationList,
  Digest,
  FeedItem,
  Group,
  GroupHoldings,
  GroupInvite,
  GroupSummary,
  InvitePreview,
  Leaderboard,
  Paged,
  ShareSettings,
  SharedPortfolio,
  TelegramLinkCode,
} from "./types"
import type { AdminGroupPass, DailyReport, MyGroupPass } from "./types"
import type { AdminMember, AdminOverview, AdminReport, BlockDomainResult, BlockedDomain, Reply, Suspension, Topic, TopicSummary } from "./types"
import type { HoldingDeleted, RecordCounts, RecordsCleared, StatementImport, TransactionBatchCheck, TransactionBatchResult, TransactionCounts } from "./types"
import type { PositionsCommitCheck, PositionsCommitResult, PositionsImport } from "./types"
import type {
  AdminReportsOverview,
  AdminTrial,
  MacroEvent,
  MarketReport,
  MemberTrial,
  NyseHoliday,
  ReportsConfigResult,
  ReportsStatus,
  ReportSummary,
  TrialReveal,
  UsEarning,
} from "./types"
import { sendsViewAs, VIEW_AS_HEADER, viewAsId } from "./view-as"
import { withTab } from "@/realtime/tab"

type Query = Record<string, string | number | null | undefined>

function toQueryString(query?: Query): string {
  if (!query) return ""
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue
    params.set(key, String(value))
  }
  const s = params.toString()
  return s ? `?${s}` : ""
}

/**
 * 真實後端（FastAPI）用的 adapter。
 * - 前綴 `/api/v1`（若 VITE_API_BASE_URL 已含 /api/v1 就不重複加）
 * - session cookie：一律 `credentials: "include"`
 * - 錯誤：`{"error": {"code", "message"}}` 轉成 ApiError
 */
export function createHttpAdapter(baseUrl: string): ForliosaApi {
  const root = baseUrl.replace(/\/+$/, "")
  const prefix = root.endsWith("/api/v1") ? root : `${root}/api/v1`

  async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; keepalive?: boolean; signal?: AbortSignal } = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" }
    if (opts.body !== undefined) headers["Content-Type"] = "application/json"
    // 授權查看：查看中每個請求都帶上授權 id（查看者自己的端點除外，見 view-as.ts）
    const viewAs = viewAsId()
    if (viewAs && sendsViewAs(path, method)) headers[VIEW_AS_HEADER] = viewAs
    const res = await fetch(`${prefix}${path}${toQueryString(opts.query)}`, {
      method,
      credentials: "include",
      // 寫入帶上分頁 id（即時更新：自己這個分頁改的，伺服器的事件會標出來，不再重抓一次）；頁面關掉時送的不用
      headers: opts.keepalive ? headers : withTab(method, headers),
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      // 頁面卸載時送出的請求（延後的刪除）：瀏覽器在頁面關掉後照樣送完
      ...(opts.keepalive ? { keepalive: true } : {}),
      // 匯入對帳單的「取消」：中斷還在等的讀取
      ...(opts.signal ? { signal: opts.signal } : {}),
    })
    if (!res.ok) {
      let code = `http_${res.status}`
      let message = `伺服器回應錯誤（${res.status}）`
      // 討論串的錯誤另外帶欄位（retry_after_seconds、until、retry_after_days），和 code／message 同一層
      let extra: Record<string, unknown> = {}
      try {
        const data = (await res.json()) as Partial<ApiErrorBody>
        if (data.error) {
          const { code: c, message: m, ...rest } = data.error
          code = c
          message = m
          extra = rest
        }
      } catch {
        // 非 JSON 的錯誤內容：保留預設訊息
      }
      throw new ApiError(res.status, code, message, extra)
    }
    if (res.status === 204) return undefined as T
    const text = await res.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  const enc = encodeURIComponent

  return {
    kind: "http",
    // 即時更新：cookie 登入；`last` 放網址參數（不帶自訂標頭，仍是不用預檢的簡單請求）；查看別人時也是自己的串流（不帶查看標頭）
    openEvents: (last, signal) =>
      fetch(`${prefix}/events${toQueryString({ last })}`, { credentials: "include", headers: { Accept: "text/event-stream" }, cache: "no-store", signal }),
    devLogin: (body) => request<User>("POST", "/auth/dev-login", { body }),
    logout: () => request<void>("POST", "/auth/logout"),
    getMe: () => request<User>("GET", "/me"),
    exportMe: () => request<Record<string, unknown>>("GET", "/me/export"),
    deleteMe: (confirm) => request<void>("DELETE", "/me", { body: { confirm } }),
    acceptTerms: (version) => request<User>("POST", "/me/terms-accept", { body: { version } }),
    updatePreferences: (patch: Partial<Preferences>) => request<User>("PATCH", "/me/preferences", { body: patch }),

    listAccounts: () => request<Account[]>("GET", "/accounts"),
    createAccount: (body: AccountInput) => request<Account>("POST", "/accounts", { body }),
    updateAccount: (id, patch) => request<Account>("PATCH", `/accounts/${enc(id)}`, { body: patch }),
    deleteAccount: (id) => request<void>("DELETE", `/accounts/${enc(id)}`),

    searchInstruments: (q) => request<Instrument[]>("GET", "/instruments/search", { query: { q } }),
    getInstrument: (symbol) => request<InstrumentDetail>("GET", `/instruments/${enc(symbol)}`),
    getQuote: (symbol) => request<Quote>("GET", `/instruments/${enc(symbol)}/quote`),
    getDailyClose: (symbol, date) => request<DailyClose>("GET", `/instruments/${encodeURIComponent(symbol)}/close`, { query: { date } }),
    getQuotes: (symbols) => request<Quote[]>("GET", "/quotes", { query: { symbols: symbols.join(",") } }),
    getHistory: (symbol, range: HistoryRange) => request<History>("GET", `/instruments/${enc(symbol)}/history`, { query: { range } }),
    getValuation: (symbol, range = "5Y") => request<Valuation>("GET", `/instruments/${enc(symbol)}/valuation`, { query: { range } }),
    getRevenue: (symbol) => request<MonthlyRevenue[]>("GET", `/instruments/${enc(symbol)}/revenue`),
    getDividends: (symbol) => request<DividendRecord[]>("GET", `/instruments/${enc(symbol)}/dividends`),
    getOverview: (symbol) => request<InstrumentOverview>("GET", `/instruments/${enc(symbol)}/overview`),
    getIntraday: (symbol) => request<Intraday>("GET", `/instruments/${enc(symbol)}/intraday`),
    getChips: (symbol, range = "3M") => request<Chips>("GET", `/instruments/${enc(symbol)}/chips`, { query: { range } }),
    getFinancials: (symbol, period = "quarterly") =>
      request<Financials>("GET", `/instruments/${enc(symbol)}/financials`, { query: { period } }),
    getEvents: (symbol, mine = false) =>
      request<InstrumentEvent[]>("GET", `/instruments/${enc(symbol)}/events`, { query: { mine: String(mine) } }),
    getNews: (symbol) => request<NewsItem[]>("GET", `/instruments/${enc(symbol)}/news`),
    getRelated: (symbol) => request<RelatedStocks>("GET", `/instruments/${enc(symbol)}/related`),
    getCompany: (symbol) => request<CompanyAbout>("GET", `/instruments/${enc(symbol)}/company`),
    getPosition: (symbol) => request<Position | null>("GET", `/instruments/${enc(symbol)}/position`),
    // 注意路徑：`/instruments/{symbol}/history` 是日線，交易歷史在 position 底下
    getPositionHistory: (symbol) => request<PositionHistory>("GET", `/instruments/${enc(symbol)}/position/history`),
    getWhy: (symbol) => request<Why>("GET", `/instruments/${enc(symbol)}/why`),

    getWatchlist: () => request<WatchItem[]>("GET", "/watchlist"),
    addWatch: (symbol) => request<void>("POST", "/watchlist", { body: { symbol } }),
    removeWatch: (symbol) => request<void>("DELETE", `/watchlist/${enc(symbol)}`),

    listTransactions: (query: TransactionQuery) =>
      request<Page<Transaction>>("GET", "/transactions", { query: query as Query }),
    getTransactionCounts: () => request<TransactionCounts>("GET", "/transactions/counts"),
    createTransaction: (body: TransactionInput) => request<Transaction>("POST", "/transactions", { body }),
    updateTransaction: (id, patch) => request<Transaction>("PATCH", `/transactions/${enc(id)}`, { body: patch }),
    deleteTransaction: (id) => request<void>("DELETE", `/transactions/${enc(id)}`),
    previewTransaction: (body) => request<TradePreview>("POST", "/transactions/preview", { body }),
    // 匯入對帳單：JSON（base64 的頁面圖片），不是 multipart
    parseStatement: (body, opts) => request<StatementImport>("POST", "/imports/statement", { body, signal: opts?.signal }),
    checkTransactionBatch: (body) => request<TransactionBatchCheck>("POST", "/transactions/batch", { body: { ...body, dry_run: true } }),
    createTransactionBatch: (body) => request<TransactionBatchResult>("POST", "/transactions/batch", { body: { ...body, dry_run: false } }),
    deleteTransactionBatch: (batchId) => request<{ batch_id: string; deleted: number }>("DELETE", `/transactions/batches/${enc(batchId)}`),
    parsePositions: (body, opts) => request<PositionsImport>("POST", "/imports/positions", { body, signal: opts?.signal }),
    checkPositions: (body) => request<PositionsCommitCheck>("POST", "/imports/positions/commit", { body: { ...body, dry_run: true } }),
    commitPositions: (body) => request<PositionsCommitResult>("POST", "/imports/positions/commit", { body: { ...body, dry_run: false } }),
    deleteHolding: (accountId, symbol, opts) =>
      request<HoldingDeleted>("DELETE", `/accounts/${enc(accountId)}/holdings/${enc(symbol)}`, { query: { pause_plans: opts?.pausePlans ? "true" : undefined } }),
    getRecordCounts: () => request<RecordCounts>("GET", "/portfolio/records"),
    // 範圍一定寫清楚：一個帳戶（account_id）或全部帳戶（all_accounts=true）；兩個都沒有時後端回 422，不會全部清掉
    clearRecords: (accountId, opts) =>
      request<RecordsCleared>("DELETE", "/portfolio/records", {
        query: { ...(accountId === null ? { all_accounts: "true" } : { account_id: accountId }), pause_plans: opts?.pausePlans ? "true" : undefined },
      }),

    getPortfolioSummary: (accountId) =>
      request<PortfolioSummary>("GET", "/portfolio/summary", { query: { account_id: accountId } }),
    getHoldings: (accountId) => request<Holding[]>("GET", "/portfolio/holdings", { query: { account_id: accountId } }),
    getUpcoming: (days = 7, opts) => request<UpcomingItem[]>("GET", "/portfolio/upcoming", { query: { days, types: opts?.types } }),
    getPerformance: (params) => request<Performance>("GET", "/portfolio/performance", { query: params }),
    getClosedPositions: (accountId) => request<ClosedRound[]>("GET", "/portfolio/closed", { query: { account_id: accountId } }),

    listRecurring: (accountId) => request<RecurringPlan[]>("GET", "/recurring", { query: { account_id: accountId } }),
    createRecurring: (body) => request<RecurringPlan>("POST", "/recurring", { body }),
    updateRecurring: (id, patch) => request<RecurringPlan>("PATCH", `/recurring/${enc(id)}`, { body: patch }),
    deleteRecurring: (id) => request<void>("DELETE", `/recurring/${enc(id)}`),
    draftRecurring: (id, date) => request<RecurringDraft>("POST", `/recurring/${enc(id)}/draft`, { query: { date } }),

    getAttributions: () => request<Attributions>("GET", "/meta/attributions"),
    getMarketStatus: () => request<MarketStatus>("GET", "/meta/market-status"),
    getMarketOverview: () => request<MarketOverview>("GET", "/market/overview"),
    getLatestBriefing: () => request<Briefing | null>("GET", "/ai/briefings/latest"),
    listBriefings: (limit) => request<Briefing[]>("GET", "/ai/briefings", { query: { limit } }),
    markBriefingRead: (id) => request<void>("POST", `/ai/briefings/${enc(id)}/read`),
    deleteAiThreads: () => request<void>("DELETE", "/ai/threads"),

    getAnalystViews: (symbol) => request<AnalystViews>("GET", `/instruments/${enc(symbol)}/analyst-views`),
    requestAnalystViews: (symbol) => request<AnalystViews>("POST", `/instruments/${enc(symbol)}/analyst-views`),

    // ── 分享（M5） ──
    getAuthProviders: () => request<AuthProviders>("GET", "/auth/providers"),
    // 整頁導到 API 主機：302 到 Discord，callback 成功後回到 `{FRONTEND_URL}{next}`
    discordLoginUrl: (next) => `${prefix}/auth/discord/start${toQueryString({ next })}`,
    googleLoginUrl: (next) => `${prefix}/auth/google/start${toQueryString({ next })}`,
    updateMe: (patch) => request<User>("PATCH", "/me", { body: patch }),

    listDelegations: () => request<DelegationList>("GET", "/delegations"),
    listDelegationCandidates: () => request<DelegationCandidate[]>("GET", "/delegations/candidates"),
    createDelegation: (body) => request<Delegation>("POST", "/delegations", { body }),
    updateDelegation: (id, patch) => request<Delegation>("PATCH", `/delegations/${enc(id)}`, { body: patch }),
    deleteDelegation: (id) => request<void>("DELETE", `/delegations/${enc(id)}`),

    listGroups: () => request<GroupSummary[]>("GET", "/groups"),
    createGroup: (body) => request<Group>("POST", "/groups", { body }),
    getGroup: (id) => request<Group>("GET", `/groups/${enc(id)}`),
    updateGroup: (id, patch) => request<Group>("PATCH", `/groups/${enc(id)}`, { body: patch }),
    listMyGroupPasses: () => request<MyGroupPass[]>("GET", "/me/group-passes"),
    attachGroupPass: (id, passId) => request<Group>("PUT", `/groups/${enc(id)}/plan`, { body: { pass_id: passId } }),
    deleteGroup: (id) => request<void>("DELETE", `/groups/${enc(id)}`),
    transferGroup: (id, userId) => request<unknown>("POST", `/groups/${enc(id)}/transfer`, { body: { user_id: userId } }),
    setMemberRole: (id, userId, role) => request<unknown>("PATCH", `/groups/${enc(id)}/members/${enc(userId)}`, { body: { role } }),
    removeMember: (id, userId) => request<void>("DELETE", `/groups/${enc(id)}/members/${enc(userId)}`),
    createInvite: (id, body) => request<GroupInvite>("POST", `/groups/${enc(id)}/invites`, { body }),
    listInvites: (id) => request<GroupInvite[]>("GET", `/groups/${enc(id)}/invites`),
    revokeInvite: (id, inviteId) => request<void>("DELETE", `/groups/${enc(id)}/invites/${enc(inviteId)}`),
    getInvite: (token) => request<InvitePreview>("GET", `/invites/${enc(token)}`),
    acceptInvite: (token, share) => request<Group>("POST", `/invites/${enc(token)}/accept`, { body: { share } }),
    getShare: (id) => request<ShareSettings>("GET", `/groups/${enc(id)}/share`),
    putShare: (id, share) => request<unknown>("PUT", `/groups/${enc(id)}/share`, { body: share }),
    getLeaderboard: (id, period) => request<Leaderboard>("GET", `/groups/${enc(id)}/leaderboard`, { query: { period } }),
    getGroupHoldings: (id) => request<GroupHoldings>("GET", `/groups/${enc(id)}/holdings`),
    getSharedPortfolio: (id, userId) => request<SharedPortfolio>("GET", `/groups/${enc(id)}/members/${enc(userId)}/shared`),
    getFeed: (id, query = {}) => request<Paged<FeedItem>>("GET", `/groups/${enc(id)}/feed`, { query }),
    listComments: (id, target, query = {}) => request<Paged<Comment>>("GET", `/groups/${enc(id)}/comments`, { query: { target, ...query } }),
    createComment: (id, body) => request<Comment>("POST", `/groups/${enc(id)}/comments`, { body }),
    deleteComment: (id, commentId) => request<void>("DELETE", `/groups/${enc(id)}/comments/${enc(commentId)}`),
    addReaction: (id, body) => request<void>("PUT", `/groups/${enc(id)}/reactions`, { body }),
    removeReaction: (id, target, emoji) => request<void>("DELETE", `/groups/${enc(id)}/reactions`, { query: { target, emoji } }),
    listDigests: (id, query = {}) => request<Paged<Digest>>("GET", `/groups/${enc(id)}/digests`, { query }),
    listDailyReports: (id, query = {}) => request<Paged<DailyReport>>("GET", `/groups/${enc(id)}/daily-reports`, { query }),
    getChannels: (id) => request<Channels>("GET", `/groups/${enc(id)}/channels`),
    putDiscord: (id, body) => request<unknown>("PUT", `/groups/${enc(id)}/channels/discord`, { body }),
    patchDiscord: (id, patch) => request<unknown>("PATCH", `/groups/${enc(id)}/channels/discord`, { body: patch }),
    deleteDiscord: (id) => request<void>("DELETE", `/groups/${enc(id)}/channels/discord`),
    linkTelegram: (id) => request<TelegramLinkCode>("POST", `/groups/${enc(id)}/channels/telegram/link`),
    patchTelegram: (id, patch) => request<unknown>("PATCH", `/groups/${enc(id)}/channels/telegram`, { body: patch }),
    deleteTelegram: (id) => request<void>("DELETE", `/groups/${enc(id)}/channels/telegram`),

    // ── 討論串（docs/api-contract.md「討論串（2026-11-13）」） ──
    setPublicName: (public_name) => request<User>("PUT", "/users/me/public-name", { body: { public_name } }),
    listTopics: (query = {}) =>
      request<Paged<TopicSummary>>("GET", "/discussions/topics", { query: { ...query, mine: query.mine ? "true" : undefined } }),
    createTopic: (body) => request<Topic>("POST", "/discussions/topics", { body }),
    getTopic: (id) => request<Topic>("GET", `/discussions/topics/${enc(id)}`),
    deleteTopic: (id, opts) => request<void>("DELETE", `/discussions/topics/${enc(id)}`, { keepalive: opts?.keepalive }),
    listReplies: (topicId, query = {}) => request<Paged<Reply>>("GET", `/discussions/topics/${enc(topicId)}/replies`, { query }),
    createReply: (topicId, body) => request<Reply>("POST", `/discussions/topics/${enc(topicId)}/replies`, { body }),
    deleteReply: (id, opts) => request<void>("DELETE", `/discussions/replies/${enc(id)}`, { keepalive: opts?.keepalive }),
    addDiscussionReaction: (body) => request<void>("PUT", "/discussions/reactions", { body }),
    removeDiscussionReaction: (target, emoji) => request<void>("DELETE", "/discussions/reactions", { query: { target, emoji } }),
    reportDiscussion: (body) => request<void>("POST", "/discussions/reports", { body }),
    listAdminReports: (query = {}) => request<Paged<AdminReport>>("GET", "/admin/discussions/reports", { query }),
    moderateDiscussion: (body) => request<void>("POST", "/admin/discussions/moderation", { body }),
    listSuspensions: () => request<Suspension[]>("GET", "/admin/discussions/suspensions"),
    // `days` 一定要送：永久要明確傳 null（漏掉欄位後端回 422）
    createSuspension: ({ target, days, reason }) =>
      request<Suspension>("POST", "/admin/discussions/suspensions", { body: { target, days, ...(reason ? { reason } : {}) } }),
    liftSuspension: (id) => request<void>("DELETE", `/admin/discussions/suspensions/${enc(id)}`),
    getAdminOverview: () => request<AdminOverview>("GET", "/admin/overview"),
    listBlockedDomains: () => request<BlockedDomain[]>("GET", "/admin/news/blocked-domains"),
    blockDomain: ({ domain, reason }) =>
      request<BlockDomainResult>("POST", "/admin/news/blocked-domains", { body: { domain, ...(reason ? { reason } : {}) } }),
    unblockDomain: (domain) => request<void>("DELETE", `/admin/news/blocked-domains/${enc(domain)}`),
    listMembers: () => request<AdminMember[]>("GET", "/admin/members"),
    grantMember: ({ email, until, note }) =>
      request<AdminMember>("PUT", "/admin/members", { body: { email, until, ...(note ? { note } : {}) } }),
    revokeMember: (userId) => request<void>("DELETE", `/admin/members/${enc(userId)}`),
    listGroupPasses: () => request<AdminGroupPass[]>("GET", "/admin/group-passes"),
    grantGroupPass: ({ email, until, note, group_id }) =>
      request<AdminGroupPass>("POST", "/admin/group-passes", { body: { email, until, ...(note ? { note } : {}), ...(group_id ? { group_id } : {}) } }),
    updateGroupPass: (id, patch) => request<AdminGroupPass>("PATCH", `/admin/group-passes/${enc(id)}`, { body: patch }),
    revokeGroupPass: (id) => request<void>("DELETE", `/admin/group-passes/${enc(id)}`),

    // ── 市場報告（docs/api-contract.md「市場報告（2026-11-17）」） ──
    getMarketReportStatus: () => request<ReportsStatus>("GET", "/market/reports/status"),
    listMarketReports: (query = {}) => request<Paged<ReportSummary>>("GET", "/market/reports", { query }),
    getLatestMarketReport: (kind) => request<MarketReport | null>("GET", "/market/reports/latest", { query: { kind } }),
    getMarketReport: (id, version) => request<MarketReport>("GET", `/market/reports/${enc(id)}`, { query: { version } }),
    markMarketReportsSeen: () => request<void>("POST", "/market/reports/seen"),
    getMarketReportTrial: (id) => request<MemberTrial>("GET", `/market/reports/${enc(id)}/trial`),
    getMarketReportVariant: (id, label) => request<MarketReport>("GET", `/market/reports/${enc(id)}/variants/${enc(label)}`),
    voteMarketReport: (id, preferred) => request<MemberTrial>("PUT", `/market/reports/${enc(id)}/vote`, { body: { preferred } }),
    getAdminReportsOverview: () => request<AdminReportsOverview>("GET", "/admin/market-reports/overview"),
    putReportsConfig: (body) => request<ReportsConfigResult>("PUT", "/admin/market-reports/config", { body }),
    getAdminReportsTrial: () => request<AdminTrial>("GET", "/admin/market-reports/trial"),
    getAdminReportVariant: (reportId, label) => request<MarketReport>("GET", `/admin/market-reports/${enc(reportId)}/variants/${enc(label)}`),
    voteReport: (reportId, body) => request<void>("PUT", `/admin/market-reports/${enc(reportId)}/vote`, { body }),
    revealTrial: (body = {}) => request<TrialReveal>("POST", "/admin/market-reports/trial/reveal", { body }),
    addReportCorrection: (reportId, body) => request<MarketReport>("POST", `/admin/market-reports/${enc(reportId)}/corrections`, { body }),
    rebuildReportData: (body) => request<void>("POST", "/admin/market-reports/rebuild-data", { body }),
    listNyseHolidays: () => request<NyseHoliday[]>("GET", "/admin/market-calendar/nyse"),
    putNyseHoliday: (date, body) => request<NyseHoliday>("PUT", `/admin/market-calendar/nyse/${enc(date)}`, { body }),
    deleteNyseHoliday: (date) => request<void>("DELETE", `/admin/market-calendar/nyse/${enc(date)}`),
    listMacroEvents: (query = {}) => request<MacroEvent[]>("GET", "/admin/market-calendar/macro", { query }),
    addMacroEvent: (body) => request<MacroEvent>("POST", "/admin/market-calendar/macro", { body }),
    deleteMacroEvent: (id) => request<void>("DELETE", `/admin/market-calendar/macro/${enc(id)}`),
    listUsEarnings: () => request<UsEarning[]>("GET", "/admin/market-calendar/us-earnings"),
    addUsEarning: (body) => request<UsEarning>("POST", "/admin/market-calendar/us-earnings", { body }),
    deleteUsEarning: (id) => request<void>("DELETE", `/admin/market-calendar/us-earnings/${enc(id)}`),
  }
}
