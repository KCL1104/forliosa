import { create } from "zustand"
import type { Transaction } from "@/api/types"

/** 跨元件的暫時 UI 狀態（不存檔）：⌘K 搜尋、記一筆、減少持股 */
interface UiState {
  searchOpen: boolean
  setSearchOpen: (open: boolean) => void
  /**
   * 記一筆：預設是簡單的買進輸入（股票 → 股數、日期、價格）；`full` 是完整表單（賣出、股利、其他類型），
   * `edit` 一律用完整表單。open 時可預先帶入代號
   */
  tradeForm: { open: boolean; symbol?: string; edit?: Transaction; full?: boolean; sell?: boolean }
  /** `sell`：完整表單一開始就選「賣出」（從「減少持股」的「改日期或價格」過來） */
  openTradeForm: (opts?: { symbol?: string; edit?: Transaction; full?: boolean; sell?: boolean }) => void
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
  openTradeForm: (opts) => set({ tradeForm: { open: true, symbol: opts?.symbol, edit: opts?.edit, full: opts?.full, sell: opts?.sell } }),
  closeTradeForm: () => set((s) => ({ tradeForm: { ...s.tradeForm, open: false } })),
  reduce: { open: false },
  openReduce: (symbol, all) => set({ reduce: { open: true, symbol, all } }),
  closeReduce: () => set((s) => ({ reduce: { ...s.reduce, open: false } })),
}))
