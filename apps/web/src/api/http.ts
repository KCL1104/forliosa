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
  type HoldingsSnapshotBody,
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
import { sendsViewAs, VIEW_AS_HEADER, viewAsId } from "./view-as"

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

  async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" }
    if (opts.body !== undefined) headers["Content-Type"] = "application/json"
    // 授權查看：查看中每個請求都帶上授權 id（查看者自己的端點除外，見 view-as.ts）
    const viewAs = viewAsId()
    if (viewAs && sendsViewAs(path, method)) headers[VIEW_AS_HEADER] = viewAs
    const res = await fetch(`${prefix}${path}${toQueryString(opts.query)}`, {
      method,
      credentials: "include",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    })
    if (!res.ok) {
      let code = `http_${res.status}`
      let message = `伺服器回應錯誤（${res.status}）`
      try {
        const data = (await res.json()) as Partial<ApiErrorBody>
        if (data.error) {
          code = data.error.code
          message = data.error.message
        }
      } catch {
        // 非 JSON 的錯誤內容：保留預設訊息
      }
      throw new ApiError(res.status, code, message)
    }
    if (res.status === 204) return undefined as T
    const text = await res.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  const enc = encodeURIComponent

  return {
    kind: "http",
    devLogin: (body) => request<User>("POST", "/auth/dev-login", { body }),
    logout: () => request<void>("POST", "/auth/logout"),
    getMe: () => request<User>("GET", "/me"),
    updatePreferences: (patch: Partial<Preferences>) => request<User>("PATCH", "/me/preferences", { body: patch }),

    listAccounts: () => request<Account[]>("GET", "/accounts"),
    createAccount: (body: AccountInput) => request<Account>("POST", "/accounts", { body }),
    updateAccount: (id, patch) => request<Account>("PATCH", `/accounts/${enc(id)}`, { body: patch }),
    deleteAccount: (id) => request<void>("DELETE", `/accounts/${enc(id)}`),
    putHoldings: (id, body: HoldingsSnapshotBody) => request<void>("PUT", `/accounts/${enc(id)}/holdings`, { body }),

    searchInstruments: (q) => request<Instrument[]>("GET", "/instruments/search", { query: { q } }),
    getInstrument: (symbol) => request<InstrumentDetail>("GET", `/instruments/${enc(symbol)}`),
    getQuote: (symbol) => request<Quote>("GET", `/instruments/${enc(symbol)}/quote`),
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
    createTransaction: (body: TransactionInput) => request<Transaction>("POST", "/transactions", { body }),
    updateTransaction: (id, patch) => request<Transaction>("PATCH", `/transactions/${enc(id)}`, { body: patch }),
    deleteTransaction: (id) => request<void>("DELETE", `/transactions/${enc(id)}`),
    previewTransaction: (body) => request<TradePreview>("POST", "/transactions/preview", { body }),

    getPortfolioSummary: (accountId) =>
      request<PortfolioSummary>("GET", "/portfolio/summary", { query: { account_id: accountId } }),
    getHoldings: (accountId) => request<Holding[]>("GET", "/portfolio/holdings", { query: { account_id: accountId } }),
    getUpcoming: (days = 7) => request<UpcomingItem[]>("GET", "/portfolio/upcoming", { query: { days } }),
    getPerformance: (params) => request<Performance>("GET", "/portfolio/performance", { query: params }),
    getClosedPositions: (accountId) => request<ClosedRound[]>("GET", "/portfolio/closed", { query: { account_id: accountId } }),

    listRecurring: (accountId) => request<RecurringPlan[]>("GET", "/recurring", { query: { account_id: accountId } }),
    createRecurring: (body) => request<RecurringPlan>("POST", "/recurring", { body }),
    updateRecurring: (id, patch) => request<RecurringPlan>("PATCH", `/recurring/${enc(id)}`, { body: patch }),
    deleteRecurring: (id) => request<void>("DELETE", `/recurring/${enc(id)}`),
    draftRecurring: (id, date) => request<RecurringDraft>("POST", `/recurring/${enc(id)}/draft`, { query: { date } }),

    getAttributions: () => request<Attributions>("GET", "/meta/attributions"),

    getAnalystViews: (symbol) => request<AnalystViews>("GET", `/instruments/${enc(symbol)}/analyst-views`),
    requestAnalystViews: (symbol) => request<AnalystViews>("POST", `/instruments/${enc(symbol)}/analyst-views`),

    // ── 分享（M5） ──
    getAuthProviders: () => request<AuthProviders>("GET", "/auth/providers"),
    // 整頁導到 API 主機：302 到 Discord，callback 成功後回到 `{FRONTEND_URL}{next}`
    discordLoginUrl: (next) => `${prefix}/auth/discord/start${toQueryString({ next })}`,
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
    getChannels: (id) => request<Channels>("GET", `/groups/${enc(id)}/channels`),
    putDiscord: (id, body) => request<unknown>("PUT", `/groups/${enc(id)}/channels/discord`, { body }),
    patchDiscord: (id, patch) => request<unknown>("PATCH", `/groups/${enc(id)}/channels/discord`, { body: patch }),
    deleteDiscord: (id) => request<void>("DELETE", `/groups/${enc(id)}/channels/discord`),
    linkTelegram: (id) => request<TelegramLinkCode>("POST", `/groups/${enc(id)}/channels/telegram/link`),
    patchTelegram: (id, patch) => request<unknown>("PATCH", `/groups/${enc(id)}/channels/telegram`, { body: patch }),
    deleteTelegram: (id) => request<void>("DELETE", `/groups/${enc(id)}/channels/telegram`),
  }
}
