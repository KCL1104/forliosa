import { create } from "zustand"
import type { Transaction } from "@/api/types"

/** 跨元件的暫時 UI 狀態（不存檔）：⌘K 搜尋、新增交易表單 */
interface UiState {
  searchOpen: boolean
  setSearchOpen: (open: boolean) => void
  /** 新增交易：open 時可預先帶入代號 */
  tradeForm: { open: boolean; symbol?: string; edit?: Transaction }
  openTradeForm: (opts?: { symbol?: string; edit?: Transaction }) => void
  closeTradeForm: () => void
}

export const useUi = create<UiState>((set) => ({
  searchOpen: false,
  setSearchOpen: (searchOpen) => set({ searchOpen }),
  tradeForm: { open: false },
  openTradeForm: (opts) => set({ tradeForm: { open: true, symbol: opts?.symbol, edit: opts?.edit } }),
  closeTradeForm: () => set((s) => ({ tradeForm: { ...s.tradeForm, open: false } })),
}))
