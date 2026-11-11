import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"
import type { ColorConvention, CostMethod, Preferences, QuantityUnit, ThemePreference } from "@/api/types"

/**
 * 顯示偏好（zustand，存在 localStorage）。
 * 伺服器的 `/me.preferences` 是跨裝置的來源；本機狀態讓畫面切換即時、不閃爍。
 * 隱私模式本身不存檔：每次開啟時依「預設開啟隱私模式」決定。
 */
export interface PrefsState {
  colorConvention: ColorConvention
  theme: ThemePreference
  quantityUnit: QuantityUnit
  compactNumbers: boolean
  privacyDefault: boolean
  costMethod: CostMethod
  benchmark: string
  privacyMode: boolean
  /** 是否已用伺服器偏好初始化過（第一次登入時用） */
  syncedFromServer: boolean
  set: (patch: Partial<Omit<PrefsState, "set" | "togglePrivacy" | "applyServer">>) => void
  togglePrivacy: () => void
  applyServer: (p: Preferences) => void
}

export const PREFS_STORAGE_KEY = "forliosa:prefs"

export const usePrefs = create<PrefsState>()(
  persist(
    (set) => ({
      colorConvention: "tw",
      theme: "system",
      quantityUnit: "lot",
      compactNumbers: true,
      privacyDefault: false,
      costMethod: "average",
      benchmark: "0050.TW",
      privacyMode: false,
      syncedFromServer: false,
      set: (patch) => set(patch),
      togglePrivacy: () => set((s) => ({ privacyMode: !s.privacyMode })),
      applyServer: (p) =>
        set({
          colorConvention: p.color_convention,
          theme: p.theme,
          quantityUnit: p.quantity_unit,
          privacyDefault: p.privacy_mode,
          privacyMode: p.privacy_mode,
          costMethod: p.cost_method,
          benchmark: p.benchmark,
          syncedFromServer: true,
        }),
    }),
    {
      name: PREFS_STORAGE_KEY,
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: ({ privacyMode: _p, set: _s, togglePrivacy: _t, applyServer: _a, ...rest }) => rest,
      onRehydrateStorage: () => (state) => {
        if (state) state.privacyMode = state.privacyDefault
      },
    },
  ),
)

/** 讀取隱私模式的簡寫 */
export const usePrivacy = () => usePrefs((s) => s.privacyMode)
