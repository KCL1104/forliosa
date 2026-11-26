/**
 * 真實後端的 AI（M4）：`POST /ai/chat` 的 SSE 串流、對話紀錄、建議問題、用量、草稿狀態。
 * 連真實後端（`api.kind === "http"`）時使用；mock 模式仍用本機的規則版回答（離線備援）。
 * 事件格式見 docs/api-contract.md「AI（M4）」。
 */
import { api, apiBaseUrl } from "@/api"
import { ApiError, type Currency, type Market, type TradePreview, type TransactionInput } from "@/api/types"
import { sendsViewAs, VIEW_AS_HEADER, viewAsId } from "@/api/view-as"
import { createSseReader } from "@/lib/sse"
import { withTab } from "@/realtime/tab"
import { parseGrounding, type UngroundedPassage } from "./answer-text"
import type { Draft, DraftInstrument, Message, Thread } from "./types"

export const aiRemote = api.kind === "http" && !!apiBaseUrl

export interface Citation {
  url: string | null
  title: string | null
  cited_text: string
  /** 引用的是個股新聞工具的那一則時，那一則的媒體（或「公開資訊觀測站」）；網路搜尋的引用沒有，畫面改寫網域 */
  outlet?: string | null
}

export interface ToolStep {
  id?: string
  name: string
  label: string
  status?: "running" | "done" | "error"
}

export interface ChatErrorInfo {
  code: string
  message: string
}

export interface ChatUsage {
  input_tokens: number
  output_tokens: number
  cache_creation_input_tokens: number
  cache_read_input_tokens: number
  web_search_requests: number
  web_fetch_requests: number
}

export interface ServerDraft {
  id: string
  status: "pending" | "signed" | "discarded"
  input: TransactionInput
  instrument: DraftInstrument | null
  preview: TradePreview
  notes: string[]
  account: { id: string; name: string } | null
  transaction_id: string | null
  created_at: string
}

/**
 * 雙向橫條的一條（市場報告）：值（和 unit 同一個尺度）、印出來的字、顏色（漲跌色／墨色／鉛筆灰）、名稱下面一行、站內連結。
 * v2（2026-11-18）：`aside` 右邊第二個數字欄（成交比重的「+2.2」，欄名是圖的 `aside_label`）；`group` 換了就插一行分組小標（「大小型股」）
 */
export interface AiChartBar {
  label: string
  value: number
  display: string
  tone: "rise" | "fall" | "ink" | "pencil"
  sub?: string | null
  href?: string | null
  aside?: string | null
  group?: string | null
}
/** 橫條的基準虛線（「加權 ▼2.31%」）：值和 bars 同一個尺度 */
export interface AiChartBench {
  value: number
  label: string
}
/** 期間切換的一組（「1 日｜近 1 週｜近 1 月」或「11/12 起」）：自己的標題（寫出這一期的起訖）、bars（依這一期排序）、基準與說明 */
export interface AiChartView {
  key: "1d" | "1w" | "1m" | "since"
  label: string
  /** 「上市類股指數漲跌（11/10 收盤至 11/17）」；第一組和圖的標題一樣。舊的資料沒有時沿用圖的標題 */
  title?: string | null
  bars: AiChartBar[]
  bench?: AiChartBench | null
  notes: string[]
}

/** `draw_chart` 畫出來的圖卡（SSE `chart` 事件、對話紀錄的 `charts`）：每個點都是伺服器讀的資料，不是模型寫的 */
export interface AiChart {
  id: string
  /**
   * 對話的 `draw_chart`：price、compare、revenue、eps、performance。
   * 市場報告（2026-11-17，伺服器從存檔畫，模型只能從固定的選單挑）：line（加權指數）、columns（交易日一根柱，
   * 外資台指期淨未平倉）、bars（以零為軸的雙向橫條：類股、點數貢獻、漲跌家數、美股 ETF；畫 `bars`，`series` 是空的）
   */
  kind: "price" | "compare" | "revenue" | "eps" | "performance" | "line" | "columns" | "bars"
  title: string
  /**
   * price＝收盤價（原幣）；pct＝分數（0.0123＝1.23%）；amount_k＝新台幣千元；eps＝每股盈餘（元）；
   * index＝指數（2 位小數）；points＝點數；count＝家數；lots＝口數；yi＝億元
   */
  unit: "price" | "pct" | "amount_k" | "eps" | "index" | "points" | "count" | "lots" | "yi"
  currency: string | null
  /** 橫軸：日期 YYYY-MM-DD、月份 YYYY-MM、季別 2026Q3、交易日（一天一根，日期當類別）、類別（bars） */
  x: "date" | "month" | "quarter" | "day" | "category"
  range: string | null
  /** `hidden` 的線不畫，只出現在讀數（提示框、螢幕報讀） */
  series: { name: string; symbol: string | null; points: { t: string; v: number }[]; hidden?: boolean }[]
  /** bars：每一條的值（和 unit 同一個尺度）、印出來的字、顏色（漲跌色／墨色／鉛筆灰）、名稱下面一行、站內連結 */
  bars?: AiChartBar[] | null
  /** 圖下面一行（點數貢獻的「官方漲跌 −2,635.04 點」） */
  reference?: { label: string; display: string } | null
  /** 標題旁「估算」 */
  estimate?: boolean
  /** 標題旁「11/12 起」（存檔從哪一天開始） */
  since?: string | null
  /** v2（2026-11-18，以下只有給了才有）：橫條的基準虛線（加權指數同一期間的漲跌） */
  bench?: AiChartBench | null
  /** 窄的主欄（< 768px，和兩欄排同一個門檻）先列前 `head`、`keep` 裡的名稱、後 `tail` 條，中間收成一行「⋯ 另 17 類」 */
  fold?: { head: number; tail: number; keep: string[] } | null
  /** 期間切換：第一組就是上面的 `bars`；只有一個期間時沒有 */
  views?: AiChartView[] | null
  /** 右邊第二個數字欄的欄名（「較前一日」），每一條的 `aside` 填這一欄 */
  aside_label?: string | null
  notes: string[]
  sources: string[]
  is_demo: boolean
}

export type ChatEvent =
  | { event: "thread"; data: { id: string; title: string; created: boolean } }
  | { event: "text"; data: { delta: string } }
  /** 整理過的回答邊寫邊送；編輯中途失敗、被截斷或少了數字時，用這一輪回答原本寫的全文取代已顯示的字（2026-11-16） */
  | { event: "text_reset"; data: { text: string } }
  | { event: "tool"; data: Required<Pick<ToolStep, "id" | "status">> & ToolStep }
  | { event: "citation"; data: Citation }
  | { event: "draft"; data: ServerDraft }
  | { event: "chart"; data: AiChart }
  /** 接著問（`suggest_follow_ups`，2026-11-26）：同一輪有新的就取代舊的 */
  | { event: "follow_ups"; data: { questions: string[] } }
  | { event: "error"; data: ChatErrorInfo }
  /** 沒有附來源的段落（後端尚未定稿：容錯接受 `{items: [{text, reason, start?, end?}]}`） */
  | { event: "grounding"; data: unknown }
  | { event: "done"; data: { thread_id: string; turn_id: string; model: string; stop_reason: string | null; usage: ChatUsage; disclaimer?: string | null } }

export interface ChatBody {
  thread_id: string | null
  message: string
  page: { route: string; symbol: string | null }
  privacy: boolean
  /** 深度搜尋：這一題多查幾輪、寫成一份整理（算 `AiUsage.deep_search_cost` 題） */
  mode?: "deep"
}

export interface ThreadSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  preview: string
}

interface ThreadMessage {
  id: string
  turn_id: string
  role: "user" | "ai"
  text: string
  /** 使用者的那一則：`deep`＝深度搜尋（選填：舊版後端沒有） */
  mode?: "deep" | null
  citations: Citation[]
  drafts: ServerDraft[]
  /** 選填：舊版後端沒有 */
  charts?: AiChart[]
  /** 選填：2026-11-26 以前的後端沒有 */
  follow_ups?: string[]
  tools: ToolStep[]
  error: ChatErrorInfo | null
  /** 選填：後端開始保存時才有 */
  disclaimer?: string | null
  grounding?: unknown
  at: string
}

export interface ThreadDetail {
  id: string
  title: string
  model: string
  created_at: string
  updated_at: string
  messages: ThreadMessage[]
}

export interface ServerSuggestions {
  route: "ledger" | "stock" | "groups" | "history" | "other"
  symbol: string | null
  questions: { kind: string; text: string; lines: string[]; symbol: string | null }[]
  actions: { kind: "draft_transaction" | "watchlist_add" | "review_drafts"; label: string; prompt: string | null; symbol: string | null; count: number | null }[]
}

export interface AiUsage {
  date: string
  month: string
  messages_today: number
  daily_message_limit: number | null
  messages_remaining: number | null
  tokens_month: number
  monthly_token_budget: number | null
  tokens_remaining: number | null
  cost_usd_month: number
  /** 每人每月的 AI 花費上限（美元，估計值）；`null`＝不限 */
  monthly_cost_budget_usd?: number | null
  /** 會員方案（`GET /me` 的 `plan.tier`；選填：舊版後端沒有） */
  plan?: "free" | "member"
  /** 省錢模式：這個月的花費上限用完了，還可以問，但不上網搜尋；深度搜尋、法人觀點等下個月 1 日 */
  economy?: boolean
  /** 這個月連省錢模式的額度也用完了（或 token 上限）：不能再問，下個月 1 日重新計算 */
  month_budget_reached?: boolean
  model: string
  available: boolean
  /** 深度搜尋一次算幾題（不超過每天的題數；所有帳號都能用，算自己的題數）；`null`＝現在不能用（省錢模式、這個環境沒開網路搜尋，
   * 或後端設了 `AI_FREE_DEEP_SEARCH=false` 時的免費帳號），切換鈕不出現（選填：舊版後端沒有，當成 3） */
  deep_search_cost?: number | null
  /** 這個環境有深度搜尋，但這個方案沒有：只在後端設 `AI_FREE_DEEP_SEARCH=false` 時才會是 true（2026-11-17 起預設大家都有）；前端不讀 */
  deep_search_members_only?: boolean
  /** 固定顯示的免責聲明（後端提供） */
  disclaimer?: string
}

/** 深度搜尋一次算幾題（後端沒說時的預設，也是 mock 模式用的數字）：每天的題數裡算 3 題（產品負責人 2026-11-15；2026-11-17 起所有帳號都能用） */
export const DEEP_SEARCH_COST = 3

function prefix(): string {
  const root = (apiBaseUrl ?? "").replace(/\/+$/, "")
  return root.endsWith("/api/v1") ? root : `${root}/api/v1`
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`
  let message = `伺服器回應錯誤（${res.status}）`
  try {
    const data = (await res.json()) as { error?: { code: string; message: string } }
    if (data.error) {
      code = data.error.code
      message = data.error.message
    }
  } catch {
    // 非 JSON：保留預設訊息
  }
  return new ApiError(res.status, code, message)
}

/**
 * 授權查看：AI 的請求也和 API client 一樣帶上 `X-Forliosa-View-As`。畫面在查看模式不提供 AI，
 * 萬一漏擋了，伺服器的白名單回 403 `view_as_not_allowed`，不會以查看者自己的身分寫進他的 AI 紀錄。
 */
function withViewAs(path: string, method: string, headers: Record<string, string>): Record<string, string> {
  const viewAs = viewAsId()
  return viewAs && sendsViewAs(path, method) ? { ...headers, [VIEW_AS_HEADER]: viewAs } : headers
}

async function request<T>(method: string, path: string, body?: unknown, opts: { keepalive?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" }
  const res = await fetch(`${prefix()}${path}`, {
    method,
    credentials: "include",
    // 寫入帶上分頁 id（即時更新：自己這個分頁改的，不再重抓一次；頁面關掉時送的不用）
    headers: withViewAs(path.split("?")[0]!, method, opts.keepalive ? headers : withTab(method, headers)),
    body: body === undefined ? undefined : JSON.stringify(body),
    ...(opts.keepalive ? { keepalive: true } : {}),
  })
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const aiApi = {
  listThreads: (limit = 50) => request<{ items: ThreadSummary[]; next_cursor: string | null }>("GET", `/ai/threads?limit=${limit}`),
  getThread: (id: string) => request<ThreadDetail>("GET", `/ai/threads/${enc(id)}`),
  /** `keepalive`：頁面要關掉時送出的刪除（復原的通知還沒結束），頁面卸載後照樣送完 */
  deleteThread: (id: string, opts?: { keepalive?: boolean }) => request<void>("DELETE", `/ai/threads/${enc(id)}`, undefined, opts),
  getSuggestions: (route: string, symbol: string | null) =>
    request<ServerSuggestions>("GET", `/ai/suggestions?route=${enc(route)}${symbol ? `&symbol=${enc(symbol)}` : ""}`),
  getUsage: () => request<AiUsage>("GET", "/ai/usage"),
  patchDraft: (id: string, body: { status: ServerDraft["status"]; transaction_id?: string }) => request<ServerDraft>("PATCH", `/ai/drafts/${enc(id)}`, body),
}

/** SSE 解析器：餵入任意切段的文字，每收到完整事件就呼叫 onEvent（忽略無法解析的事件） */
export function createSseParser(onEvent: (e: ChatEvent) => void): (chunk: string) => void {
  // 切段、換行與欄位的解析和即時更新共用（lib/sse.ts）；這裡只收有名稱、內容是 JSON 的事件
  return createSseReader(({ event, data }) => {
    if (!event.trim()) return
    try {
      onEvent({ event: event.trim(), data: JSON.parse(data) } as ChatEvent)
    } catch {
      // 壞掉的事件：略過，串流繼續
    }
  })
}

/** 送出一句話並逐事件回呼；HTTP 錯誤（額度、未登入…）以 ApiError 拋出 */
export async function streamChat(body: ChatBody, onEvent: (e: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${prefix()}/ai/chat`, {
    method: "POST",
    credentials: "include",
    headers: withViewAs("/ai/chat", "POST", withTab("POST", { Accept: "text/event-stream", "Content-Type": "application/json" })),
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw await toApiError(res)
  const feed = createSseParser(onEvent)
  if (!res.body) {
    feed(`${await res.text()}\n\n`)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    feed(decoder.decode(value, { stream: true }))
  }
  feed(`${decoder.decode()}\n\n`)
}

// ── 轉成面板用的型別 ─────────────────────────────────────

const CASH: Record<Currency, DraftInstrument> = {
  TWD: { symbol: "", code: "TWD", name: "現金", market: "TWSE" as Market, currency: "TWD" },
  USD: { symbol: "", code: "USD", name: "美元現金", market: "US" as Market, currency: "USD" },
}

export function draftFromServer(d: ServerDraft): Draft {
  const currency = (d.input.currency ?? d.instrument?.currency ?? "TWD") as Currency
  return {
    id: d.id,
    status: d.status,
    input: d.input,
    instrument: d.instrument ?? CASH[currency],
    preview: d.preview,
    notes: d.notes,
    txnId: d.transaction_id ?? undefined,
    createdAt: d.created_at,
    remote: true,
  }
}

/** 形狀不對的圖卡不畫（後端改版、事件壞掉時不讓整段對話壞掉） */
export function isChart(c: unknown): c is AiChart {
  const x = c as Partial<AiChart> | null
  return (
    !!x &&
    typeof x.id === "string" &&
    typeof x.title === "string" &&
    Array.isArray(x.series) &&
    x.series.every((s) => !!s && typeof s.name === "string" && Array.isArray(s.points) && s.points.every((p) => !!p && typeof p.t === "string" && Number.isFinite(p.v)))
  )
}

/** 接著問：只收非空的字串，最多 3 題（後端改版、事件壞掉時不讓對話壞掉） */
export function followUpsOf(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((q): q is string => typeof q === "string" && q.trim().length > 0).map((q) => q.trim()).slice(0, 3)
}

/** 套用一個串流事件到正在寫的 AI 訊息（純函式，方便測試） */
export function applyChatEvent(m: Message, e: ChatEvent): Message {
  switch (e.event) {
    case "text":
      return { ...m, text: (m.text ?? "") + e.data.delta }
    case "text_reset":
      // 這一輪的全文：取代目前顯示的字（不是接在後面）
      return typeof e.data?.text === "string" ? { ...m, text: e.data.text } : m
    case "tool": {
      const tools = [...(m.tools ?? [])]
      const i = tools.findIndex((t) => t.id === e.data.id)
      if (i >= 0) tools[i] = { ...tools[i]!, status: e.data.status }
      else tools.push({ id: e.data.id, name: e.data.name, label: e.data.label, status: e.data.status })
      return { ...m, tools }
    }
    case "citation": {
      const cites = m.citations ?? []
      if (cites.some((c) => c.url === e.data.url && c.cited_text === e.data.cited_text)) return m
      return { ...m, citations: [...cites, e.data] }
    }
    case "draft":
      return m.draftIds?.includes(e.data.id) ? m : { ...m, draftIds: [...(m.draftIds ?? []), e.data.id] }
    case "chart":
      return !isChart(e.data) || m.charts?.some((c) => c.id === e.data.id) ? m : { ...m, charts: [...(m.charts ?? []), e.data] }
    case "follow_ups": {
      const questions = followUpsOf(e.data?.questions)
      return questions.length ? { ...m, followUps: questions } : m
    }
    case "error":
      // 拒答：這一輪已經串流出來的字不算數，只留下說明
      return e.data.code === "refusal" ? { ...m, text: "", error: e.data } : { ...m, error: e.data }
    case "grounding": {
      const items = parseGrounding(e.data)
      if (items.length === 0) return m
      const seen = new Set((m.ungrounded ?? []).map((u) => u.text))
      return { ...m, ungrounded: [...(m.ungrounded ?? []), ...items.filter((u: UngroundedPassage) => !seen.has(u.text))] }
    }
    case "done":
      return { ...m, streaming: false, ...(e.data.disclaimer ? { disclaimer: e.data.disclaimer } : {}) }
    default:
      return m
  }
}

export function threadFromServer(t: ThreadDetail): { thread: Thread; drafts: Draft[] } {
  const drafts: Draft[] = []
  const messages: Message[] = t.messages.map((m) => {
    if (m.role === "user") return { id: `srv_${m.id}`, role: "user", text: m.text, ...(m.mode === "deep" ? { mode: "deep" as const } : {}), at: m.at }
    drafts.push(...m.drafts.map(draftFromServer))
    return {
      id: `srv_${m.id}`,
      role: "ai",
      text: m.text,
      model: true,
      citations: m.citations,
      tools: m.tools,
      error: m.error ?? undefined,
      draftIds: m.drafts.map((d) => d.id),
      ...(m.charts?.some(isChart) ? { charts: m.charts.filter(isChart) } : {}),
      ...(followUpsOf(m.follow_ups).length ? { followUps: followUpsOf(m.follow_ups) } : {}),
      ...(m.disclaimer ? { disclaimer: m.disclaimer } : {}),
      ...(m.grounding ? { ungrounded: parseGrounding(m.grounding) } : {}),
      at: m.at,
    }
  })
  return { thread: { id: `thr_local_${t.id}`, remoteId: t.id, title: t.title, updatedAt: t.updated_at, messages }, drafts }
}
