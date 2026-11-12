/**
 * 法人觀點卡的狀態（純函式，元件與測試共用）。
 * 展開 → GET（當日共用快取）→ `none` 時使用者按「查詢近期法人觀點」→ POST（AI 網路搜尋）→ `pending` 時每 2.5 秒輪詢 GET → `ready`。
 * 規則（產品負責人）：照原文列出，不算平均、上漲空間，不排名、不寫買賣提示，評等不上色。
 */
import type { AnalystView, AnalystViews, Currency } from "@/api/types"
import { formatDate, formatDateShort, formatNumber } from "@/lib/format"
import { formatQuote } from "@/lib/tick"

/** 後端沒有附免責文字時用的常數（和合約範例相同） */
export const ANALYST_DISCLAIMER_FALLBACK = "以下為媒體報導的第三方觀點，可能不完整或未經授權轉載，非 Forliosa 建議。"
export const ANALYST_MAX_ITEMS = 5
/** 後端實測（2026-11-12，2 次網路搜尋）一次生成約 13–17 秒；每 2.5 秒問一次 */
export const ANALYST_POLL_MS = 2500
/** 搜尋超過這麼久還沒好：停止輪詢，請使用者稍後再打開（後端 5 分鐘沒完成會改成 `unavailable`） */
export const ANALYST_TIMEOUT_MS = 90_000

/**
 * - `idle`：還沒展開過（不打 API）
 * - `loading`：第一次 GET
 * - `none`：今天還沒有人查過 → 顯示「查詢近期法人觀點」
 * - `searching`：POST 進行中，或結果是 `pending`（輪詢中）
 * - `ready`／`empty`：有結果／查完沒有報導
 * - `unavailable`：這次查不到（AI 暫停、搜尋失敗）
 * - `error`：請求失敗（可重試）
 */
export type AnalystPhase = "idle" | "loading" | "none" | "searching" | "ready" | "empty" | "unavailable" | "error"

export interface AnalystState {
  phase: AnalystPhase
  data: AnalystViews | null
  /** 正在等的請求 */
  inFlight: "get" | "post" | null
  error: { message: string; code: string | null; during: "get" | "post" } | null
  /** 開始搜尋的時間（輪詢逾時用） */
  searchStartedAt: number | null
}

export type AnalystEvent =
  | { type: "load" }
  | { type: "loaded"; data: AnalystViews; at: number }
  | { type: "search"; at: number }
  | { type: "searched"; data: AnalystViews; at: number }
  | { type: "failed"; during: "get" | "post"; message: string; code?: string | null }
  | { type: "timeout" }

export const ANALYST_INITIAL: AnalystState = { phase: "idle", data: null, inFlight: null, error: null, searchStartedAt: null }

export function phaseOf(data: AnalystViews): AnalystPhase {
  switch (data.status) {
    case "none":
      return "none"
    case "pending":
      return "searching"
    case "unavailable":
      return "unavailable"
    case "ready":
      return (data.items ?? []).length > 0 ? "ready" : "empty"
  }
}

/** 收到一份回應（GET 或 POST）。剛按下查詢時，共用快取可能還是 `none`：繼續等，不退回查詢按鈕 */
function receive(s: AnalystState, data: AnalystViews, at: number): AnalystState {
  if (s.phase === "searching" && data.status === "none") return { ...s, inFlight: null }
  const phase = phaseOf(data)
  return {
    phase,
    data,
    inFlight: null,
    error: null,
    // 別人剛觸發（GET 回 pending）也要能逾時
    searchStartedAt: phase === "searching" ? (s.searchStartedAt ?? at) : null,
  }
}

export function analystReducer(s: AnalystState, e: AnalystEvent): AnalystState {
  switch (e.type) {
    case "load":
      if (s.inFlight) return s
      return { ...s, phase: s.phase === "idle" || s.phase === "error" ? "loading" : s.phase, inFlight: "get", error: null }
    case "loaded":
    case "searched":
      return receive(s, e.data, e.at)
    case "search":
      if (s.inFlight === "post") return s
      return { ...s, phase: "searching", inFlight: "post", error: null, searchStartedAt: e.at }
    case "failed": {
      // 輪詢時偶發的失敗：繼續等下一次（逾時會停）
      if (s.phase === "searching" && e.during === "get") return { ...s, inFlight: null }
      // AI 暫停（503）：和 `unavailable` 一樣是安靜的說明，不是錯誤
      if (e.code === "ai_unavailable") return { ...s, phase: "unavailable", inFlight: null, error: { message: e.message, code: e.code, during: e.during }, searchStartedAt: null }
      // 後端還沒有這個端點（404）：同樣安靜地說明，不顯示「伺服器回應錯誤（404）」
      if (e.code === "not_found" || e.code === "http_404") {
        return { ...s, phase: "unavailable", inFlight: null, error: { message: "這項資料還沒有開放。", code: e.code, during: e.during }, searchStartedAt: null }
      }
      return { ...s, phase: "error", inFlight: null, error: { message: e.message, code: e.code ?? null, during: e.during }, searchStartedAt: null }
    }
    case "timeout":
      if (s.phase !== "searching") return s
      return { ...s, phase: "error", inFlight: null, searchStartedAt: null, error: { message: "這次查得比平常久，稍後再打開看看。", code: "timeout", during: "get" } }
  }
}

/** 輪詢：搜尋中、沒有請求在等時，下一步是再 GET 一次，或已經逾時 */
export function nextPoll(s: AnalystState, now: number): "poll" | "timeout" | null {
  if (s.phase !== "searching" || s.inFlight) return null
  if (s.searchStartedAt !== null && now - s.searchStartedAt > ANALYST_TIMEOUT_MS) return "timeout"
  return "poll"
}

/** 要顯示的列：最多 5 筆、新到舊（後端已排序；這裡再保證一次），沒有日期或來源的不列 */
export function visibleViews(items: AnalystView[] | undefined): AnalystView[] {
  return (items ?? [])
    .filter((v) => v.date && v.url && v.source_title)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, ANALYST_MAX_ITEMS)
}

/** 目標價：台股依升降單位＋「元」，美股 US$ 兩位小數；沒有寫目標價為「—」 */
export function formatTarget(price: number | null, currency: Currency): string {
  if (price === null || price === undefined) return "—"
  return currency === "USD" ? `US$${formatNumber(price, 2)}` : `${formatQuote(price, "TWSE")} 元`
}

/** 報導日期：今年「11/10」，跨年「2025/12/30」 */
export function viewDate(date: string, today: string): string {
  return date.slice(0, 4) === today.slice(0, 4) ? formatDateShort(date, false) : formatDate(date)
}

/** 評等原文：「調升」＋「加碼」→「調升「加碼」」（照抄，不翻譯成看好／看壞） */
export function ratingLine(v: Pick<AnalystView, "action" | "rating_text">): string {
  return `${v.action ?? ""}${v.rating_text ? `「${v.rating_text}」` : ""}`.trim()
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return ""
  }
}
