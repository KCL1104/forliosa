import { create } from "zustand"
import type { Transaction } from "@/api/types"

/** 打開完整表單時先填好的欄位（從記一筆、減少持股過來時不用再填一次） */
export interface TradePrefill {
  /** 完整表單先選好的類型（股利入帳用） */
  type?: "cash_dividend"
  accountId?: string
  quantity?: number
  price?: number
  date?: string
}

/** 跨元件的暫時 UI 狀態（不存檔）：⌘K 搜尋、記一筆、減少持股 */
interface UiState {
  searchOpen: boolean
  setSearchOpen: (open: boolean) => void
  /**
   * 記一筆：預設是簡單的買進輸入（股票 → 股數、日期、價格；「只記持股」的帳戶是持股的輸入）；`full` 是完整表單（賣出、股利、其他類型），
   * `edit` 一律用完整表單。open 時可預先帶入代號
   */
  tradeForm: { open: boolean; symbol?: string; edit?: Transaction; full?: boolean; sell?: boolean; prefill?: TradePrefill; accountId?: string }
  /**
   * `sell`：完整表單一開始就選「賣出」（從「減少持股」的「改日期或價格」過來）。
   * `accountId`：記一筆先選好這個帳戶（設定頁的「編輯持股」）；「只記持股」的帳戶開的是持股的輸入（`HoldingsEditor`）
   */
  openTradeForm: (opts?: { symbol?: string; edit?: Transaction; full?: boolean; sell?: boolean; prefill?: TradePrefill; accountId?: string }) => void
  closeTradeForm: () => void
  /** 減少持股／全部賣出：只填股數，用最新的收盤價記成賣出（`all`：股數先填成全部） */
  reduce: { open: boolean; symbol?: string; all?: boolean }
  openReduce: (symbol: string, all?: boolean) => void
  closeReduce: () => void
}

export const useUi = create<UiState>((set) => ({
  searchOpen: false,
  setSearchOpen: (searchOpen) => set({ searchOpen }),
  tradeForm: { open: false },
  openTradeForm: (opts) =>
    set({ tradeForm: { open: true, symbol: opts?.symbol, edit: opts?.edit, full: opts?.full, sell: opts?.sell, prefill: opts?.prefill, accountId: opts?.accountId } }),
  closeTradeForm: () => set((s) => ({ tradeForm: { ...s.tradeForm, open: false } })),
  reduce: { open: false },
  openReduce: (symbol, all) => set({ reduce: { open: true, symbol, all } }),
  closeReduce: () => set((s) => ({ reduce: { ...s.reduce, open: false } })),
}))
