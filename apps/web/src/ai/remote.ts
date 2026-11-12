/**
 * 真實後端的 AI（M4）：`POST /ai/chat` 的 SSE 串流、對話紀錄、建議問題、用量、草稿狀態。
 * 連真實後端（`api.kind === "http"`）時使用；mock 模式仍用本機的規則版回答（離線備援）。
 * 事件格式見 docs/api-contract.md「AI（M4）」。
 */
import { api, apiBaseUrl } from "@/api"
import { ApiError, type Currency, type Market, type TradePreview, type TransactionInput } from "@/api/types"
import type { Draft, DraftInstrument, Message, Thread } from "./types"

export const aiRemote = api.kind === "http" && !!apiBaseUrl

export interface Citation {
  url: string | null
  title: string | null
  cited_text: string
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

export type ChatEvent =
  | { event: "thread"; data: { id: string; title: string; created: boolean } }
  | { event: "text"; data: { delta: string } }
  | { event: "tool"; data: Required<Pick<ToolStep, "id" | "status">> & ToolStep }
  | { event: "citation"; data: Citation }
  | { event: "draft"; data: ServerDraft }
  | { event: "error"; data: ChatErrorInfo }
  | { event: "done"; data: { thread_id: string; turn_id: string; model: string; stop_reason: string | null; usage: ChatUsage } }

export interface ChatBody {
  thread_id: string | null
  message: string
  page: { route: string; symbol: string | null }
  privacy: boolean
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
  citations: Citation[]
  drafts: ServerDraft[]
  tools: ToolStep[]
  error: ChatErrorInfo | null
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
  model: string
  available: boolean
}

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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${prefix()}${path}`, {
    method,
    credentials: "include",
    headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const aiApi = {
  listThreads: (limit = 50) => request<{ items: ThreadSummary[]; next_cursor: string | null }>("GET", `/ai/threads?limit=${limit}`),
  getThread: (id: string) => request<ThreadDetail>("GET", `/ai/threads/${enc(id)}`),
  deleteThread: (id: string) => request<void>("DELETE", `/ai/threads/${enc(id)}`),
  getSuggestions: (route: string, symbol: string | null) =>
    request<ServerSuggestions>("GET", `/ai/suggestions?route=${enc(route)}${symbol ? `&symbol=${enc(symbol)}` : ""}`),
  getUsage: () => request<AiUsage>("GET", "/ai/usage"),
  patchDraft: (id: string, body: { status: ServerDraft["status"]; transaction_id?: string }) => request<ServerDraft>("PATCH", `/ai/drafts/${enc(id)}`, body),
}

/** SSE 解析器：餵入任意切段的文字，每收到完整事件就呼叫 onEvent（忽略無法解析的事件） */
export function createSseParser(onEvent: (e: ChatEvent) => void): (chunk: string) => void {
  let buffer = ""
  return (chunk: string) => {
    buffer += chunk
    // CRLF / CR → LF; a trailing \r may be the first half of a \r\n split across chunks
    const tail = buffer.endsWith("\r") ? "\r" : ""
    buffer = (tail ? buffer.slice(0, -1) : buffer).replace(/\r\n?/g, "\n")
    let cut = buffer.indexOf("\n\n")
    while (cut !== -1) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      let name = ""
      const data: string[] = []
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim()
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""))
      }
      if (name && data.length > 0) {
        try {
          onEvent({ event: name, data: JSON.parse(data.join("\n")) } as ChatEvent)
        } catch {
          // 壞掉的事件：略過，串流繼續
        }
      }
      cut = buffer.indexOf("\n\n")
    }
    buffer += tail
  }
}

/** 送出一句話並逐事件回呼；HTTP 錯誤（額度、未登入…）以 ApiError 拋出 */
export async function streamChat(body: ChatBody, onEvent: (e: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${prefix()}/ai/chat`, {
    method: "POST",
    credentials: "include",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
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

/** 套用一個串流事件到正在寫的 AI 訊息（純函式，方便測試） */
export function applyChatEvent(m: Message, e: ChatEvent): Message {
  switch (e.event) {
    case "text":
      return { ...m, text: (m.text ?? "") + e.data.delta }
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
    case "error":
      // 拒答：這一輪已經串流出來的字不算數，只留下說明
      return e.data.code === "refusal" ? { ...m, text: "", error: e.data } : { ...m, error: e.data }
    case "done":
      return { ...m, streaming: false }
    default:
      return m
  }
}

export function threadFromServer(t: ThreadDetail): { thread: Thread; drafts: Draft[] } {
  const drafts: Draft[] = []
  const messages: Message[] = t.messages.map((m) => {
    if (m.role === "user") return { id: `srv_${m.id}`, role: "user", text: m.text, at: m.at }
    drafts.push(...m.drafts.map(draftFromServer))
    return {
      id: `srv_${m.id}`,
      role: "ai",
      text: m.text,
      citations: m.citations,
      tools: m.tools,
      error: m.error ?? undefined,
      draftIds: m.drafts.map((d) => d.id),
      at: m.at,
    }
  })
  return { thread: { id: `thr_local_${t.id}`, remoteId: t.id, title: t.title, updatedAt: t.updated_at, messages }, drafts }
}
