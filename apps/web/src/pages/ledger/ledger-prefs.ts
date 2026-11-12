import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"

/** 帳本的自訂（取代「簡易版／專業版」）：欄位、走勢圖、釘選持股。存在這台瀏覽器。 */
export type HoldingColumn = "price" | "day_pct" | "day_change" | "value" | "avg_cost" | "unrealized" | "unrealized_pct"

export const COLUMN_LABEL: Record<HoldingColumn, string> = {
  price: "現價",
  day_pct: "今日漲跌",
  day_change: "今日損益",
  value: "市值・佔比",
  avg_cost: "均價",
  unrealized: "未實現損益",
  unrealized_pct: "報酬率",
}

export const ALL_COLUMNS: HoldingColumn[] = ["price", "day_pct", "day_change", "value", "avg_cost", "unrealized", "unrealized_pct"]
export const DEFAULT_COLUMNS: HoldingColumn[] = ["price", "day_pct", "day_change", "value"]

interface LedgerPrefs {
  columns: HoldingColumn[]
  showTrend: boolean
  pinned: string[]
  setColumns: (c: HoldingColumn[]) => void
  toggleColumn: (c: HoldingColumn) => void
  setShowTrend: (v: boolean) => void
  togglePin: (symbol: string) => void
  reset: () => void
}

export const useLedgerPrefs = create<LedgerPrefs>()(
  persist(
    (set) => ({
      columns: DEFAULT_COLUMNS,
      showTrend: true,
      pinned: [],
      setColumns: (columns) => set({ columns }),
      toggleColumn: (c) =>
        set((s) => {
          const on = s.columns.includes(c)
          const next = on ? s.columns.filter((x) => x !== c) : [...s.columns, c]
          // 至少保留現價
          return { columns: ALL_COLUMNS.filter((x) => next.includes(x) || x === "price") }
        }),
      setShowTrend: (showTrend) => set({ showTrend }),
      togglePin: (symbol) => set((s) => ({ pinned: s.pinned.includes(symbol) ? s.pinned.filter((x) => x !== symbol) : [...s.pinned, symbol] })),
      reset: () => set({ columns: DEFAULT_COLUMNS, showTrend: true, pinned: [] }),
    }),
    { name: "forliosa:ledger", version: 1, storage: createJSONStorage(() => localStorage) },
  ),
)
