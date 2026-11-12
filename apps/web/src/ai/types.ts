import type { Market, TradePreview, TransactionInput } from "@/api/types"

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
  | "group_share"

export interface Suggestion {
  kind: SuggestionKind
  text: string
  /** 手機卡片用的兩行版本（第一行短） */
  lines?: [string, string]
  symbol?: string
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

/** AI 的回答：一句話（紫色文楷）＋可選的數字列＋可以接著去的地方＋資料時間 */
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
}

export interface Message {
  id: string
  role: "user" | "ai"
  text?: string
  answer?: Answer
  draftId?: string
  at: string
}

export interface Thread {
  id: string
  title: string
  updatedAt: string
  messages: Message[]
  /** 示範紀錄：打開時用目前資料重新回答 */
  seeded?: boolean
}
