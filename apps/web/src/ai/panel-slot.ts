import { create } from "zustand"

/**
 * 桌面 AI 面板標題下面的「本頁」欄位：頁面用 `createPortal` 把自己的一列放進來（帳本的本週事項，產品負責人 2026-11-19 選 B）。
 * 面板收合、手機、看對話紀錄時沒有這一格（`el` 是 null），頁面就放回自己的版面——面板不需要知道是哪一頁放了什麼。
 */
export const usePanelSlot = create<{ el: HTMLElement | null; set: (el: HTMLElement | null) => void }>((set) => ({
  el: null,
  set: (el) => set({ el }),
}))
