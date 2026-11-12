import type { Market, TradePreview, TransactionInput } from "@/api/types"
import type { UngroundedPassage } from "./answer-text"
import type { ChatErrorInfo, Citation, ToolStep } from "./remote"

/** 依頁面自動出現的建議問題（介面上不加說明字樣） */
export type SuggestionKind =
  | "drag"
  | "lift"
  | "dividends_next"
  | "concentration"
  | "onboard"
  | "why_move"
  | "next_dividend"
  | "cost_on_river"
  | "add_one_lot"
  | "is_expensive"
  | "if_hold_dividend"
  | "foreign_flow"
  | "group_share"
  | "recurring_draft"

export interface Suggestion {
  kind: SuggestionKind
  text: string
  /** 手機卡片用的兩行版本（第一行短） */
  lines?: [string, string]
  symbol?: string
  /** 定期定額扣款日的草稿（`recurring_draft`）：計畫與原本的扣款日；`missed`＝最近 7 天漏記、補記 */
  recurring?: { planId: string; scheduledDate: string; date: string; name: string; missed?: boolean }
}

export interface AnswerRow {
  label: string
  value: string
  tone?: "up" | "down" | "flat"
  hint?: string
}

export interface AnswerLink {
  label: string
  /** 路由；或 `#trade-form` 打開手動記帳表單 */
  to: string
  params?: Record<string, string>
  search?: Record<string, string>
}

/** 本機規則版的回答（不是模型寫的，墨色 Noto Sans）：一句話＋可選的數字列＋可以接著去的地方＋資料時間 */
export interface Answer {
  text: string
  rows?: AnswerRow[]
  links?: AnswerLink[]
  /** 「資料至 11/12 13:30」 */
  asOf?: string | null
  /** 回答之後的追問 */
  followUps?: string[]
}

export interface DraftInstrument {
  symbol: string
  code: string
  name: string
  market: Market
  currency: "TWD" | "USD"
}

export type DraftStatus = "loading" | "pending" | "signed" | "discarded" | "error"

export interface Draft {
  id: string
  status: DraftStatus
  input: TransactionInput
  instrument: DraftInstrument
  preview?: TradePreview
  /** 例如「沒有寫價格，以 11/12 收盤價 52.35 估算」 */
  notes: string[]
  txnId?: string
  signedAt?: string
  error?: string
  createdAt: string
  /** 後端 AI 產生的草稿（`/ai/drafts`），簽名、捨棄、復原時同步狀態 */
  remote?: boolean
  /** 定期定額扣款的草稿（`POST /recurring/{id}/draft`）：同一個計畫同一天只提一次 */
  recurring?: { planId: string; date: string }
}

export interface Message {
  id: string
  role: "user" | "ai"
  text?: string
  /**
   * `text` 是模型寫的（`/ai/chat` 串流、`/ai/threads` 載入）＝紫色楷體；`false` 是本機規則或範本寫的句子
   * （草稿的說明、定期定額的說明）＝墨色 Noto Sans。舊紀錄沒有這個欄位：連後端的對話視為模型寫的。
   */
  model?: boolean
  answer?: Answer
  draftId?: string
  /** 後端 AI 一次回答裡產生的草稿（可能不只一份） */
  draftIds?: string[]
  /** 回答引用的網路來源（必須顯示） */
  citations?: Citation[]
  /** 查資料的步驟（串流中顯示成一行進度） */
  tools?: ToolStep[]
  /** 還在串流 */
  streaming?: boolean
  error?: ChatErrorInfo
  /** 固定顯示在回答下方的免責聲明（後端 `done.disclaimer`；沒有時用常數） */
  disclaimer?: string
  /** 像事實陳述、卻沒有附來源的段落（後端 `grounding` 事件）：畫面在段落後面加「無來源」 */
  ungrounded?: UngroundedPassage[]
  at: string
}

export interface Thread {
  id: string
  /** 後端的對話 id（`/ai/threads`）；接著問時帶上 */
  remoteId?: string
  title: string
  updatedAt: string
  messages: Message[]
  /** 示範紀錄：打開時用目前資料重新回答 */
  seeded?: boolean
}
