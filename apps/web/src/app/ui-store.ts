import { create } from "zustand"
import type { Transaction } from "@/api/types"

/** 跨元件的暫時 UI 狀態（不存檔）：⌘K 搜尋、記一筆 */
interface UiState {
  searchOpen: boolean
  setSearchOpen: (open: boolean) => void
  /**
   * 記一筆：預設是簡單的買進輸入（股票 → 股數、日期、價格）；`full` 是完整表單（賣出、股利、其他類型），
   * `edit` 一律用完整表單。open 時可預先帶入代號
   */
  tradeForm: { open: boolean; symbol?: string; edit?: Transaction; full?: boolean }
  openTradeForm: (opts?: { symbol?: string; edit?: Transaction; full?: boolean }) => void
  closeTradeForm: () => void
}

export const useUi = create<UiState>((set) => ({
  searchOpen: false,
  setSearchOpen: (searchOpen) => set({ searchOpen }),
  tradeForm: { open: false },
  openTradeForm: (opts) => set({ tradeForm: { open: true, symbol: opts?.symbol, edit: opts?.edit, full: opts?.full } }),
  closeTradeForm: () => set((s) => ({ tradeForm: { ...s.tradeForm, open: false } })),
}))
