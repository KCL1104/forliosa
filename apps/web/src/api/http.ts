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
} from "./types"

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
    const res = await fetch(`${prefix}${path}${toQueryString(opts.query)}`, {
      method,
      credentials: "include",
      headers: opts.body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
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

    listTransactions: (query: TransactionQuery) =>
      request<Page<Transaction>>("GET", "/transactions", { query: query as Query }),
    createTransaction: (body: TransactionInput) => request<Transaction>("POST", "/transactions", { body }),
    updateTransaction: (id, patch) => request<Transaction>("PATCH", `/transactions/${enc(id)}`, { body: patch }),
    deleteTransaction: (id) => request<void>("DELETE", `/transactions/${enc(id)}`),
    previewTransaction: (body) => request<TradePreview>("POST", "/transactions/preview", { body }),

    getPortfolioSummary: (accountId) =>
      request<PortfolioSummary>("GET", "/portfolio/summary", { query: { account_id: accountId } }),
    getHoldings: (accountId) => request<Holding[]>("GET", "/portfolio/holdings", { query: { account_id: accountId } }),
    getPerformance: (params) => request<Performance>("GET", "/portfolio/performance", { query: params }),
  }
}
