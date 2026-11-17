import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"
import { DEFAULT_TREND_RANGE, type TrendRange } from "@/lib/trend-range"

/** 帳本的自訂（取代「簡易版／專業版」）：欄位、走勢圖與區間、釘選持股、手機持倉列的第二行。存在這台瀏覽器。 */
export type HoldingColumn = "price" | "day_pct" | "day_change" | "pnl" | "value" | "avg_cost" | "unrealized" | "unrealized_pct"

export const COLUMN_LABEL: Record<HoldingColumn, string> = {
  price: "收盤價",
  day_pct: "今日漲跌",
  day_change: "今日損益",
  // 未實現損益的金額，下面一行報酬率（產品負責人 2026-11-16 選 A：預設就看得到每一檔賺賠多少）
  pnl: "損益",
  value: "市值・佔比",
  // 預設寫在「收盤價」那一格的第二行（表頭「收盤價・均價」，產品負責人 2026-11-17）；在「自訂」打開就自己一欄，收盤價下面不再重複
  avg_cost: "均價",
  unrealized: "未實現損益",
  unrealized_pct: "報酬率",
}

/** 欄名看不出算法的欄位：表頭與「自訂」選單滑過時的說明（「損益」和主數字的「總損益（含股利）」對不起來，寫清楚不含股利） */
export const COLUMN_HINT: Partial<Record<HoldingColumn, string>> = {
  pnl: "未實現損益與報酬率：市值減成本，不含股利",
  // 每一筆買賣的價格不含手續費，均價含，所以會比只用價格算的高一點
  avg_cost: "均價：每股的平均成本，含買進手續費",
}

/** 這個順序就是表格的欄位順序，也是「自訂」選單的順序 */
export const ALL_COLUMNS: HoldingColumn[] = ["price", "day_pct", "day_change", "pnl", "value", "avg_cost", "unrealized", "unrealized_pct"]
export const DEFAULT_COLUMNS: HoldingColumn[] = ["price", "day_pct", "day_change", "pnl", "value"]
/**
 * 手機持倉列右下那一行（產品負責人 2026-11-17 選 A）：「day」今日漲跌（預設），「pnl」這一檔的報酬率——
 * 和桌面「損益」欄的第二行同一個數字（未實現損益÷成本，不含股利）。按手機的表頭「收盤價・今日漲跌」切換。
 */
export type PhoneLine = "day" | "pnl"

/** 第 1 版的預設欄位（沒有「損益」） */
const DEFAULT_COLUMNS_V1: HoldingColumn[] = ["price", "day_pct", "day_change", "value"]

const sameColumns = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((c) => b.includes(c))

/**
 * 存在瀏覽器裡的舊設定：第 1 版的欄位還是當時的預設（沒動過）就換成新的預設（多了「損益」）；自己選過欄位的照舊。
 */
export function migrateLedgerPrefs(persisted: unknown, version: number): unknown {
  if (!persisted || typeof persisted !== "object") return persisted
  const state = persisted as { columns?: unknown }
  if (version < 2 && Array.isArray(state.columns) && sameColumns(state.columns, DEFAULT_COLUMNS_V1)) {
    return { ...state, columns: DEFAULT_COLUMNS }
  }
  return persisted
}

interface LedgerPrefs {
  columns: HoldingColumn[]
  showTrend: boolean
  pinned: string[]
  /** 持倉底下的「已出清」是否展開 */
  showClosed: boolean
  /** 手機持倉列右下那一行看今日漲跌還是報酬率（見 `PhoneLine`） */
  phoneLine: PhoneLine
  togglePhoneLine: () => void
  /** 總資產走勢（和績效分段共用）上次選的區間 */
  trendRange: TrendRange
  setTrendRange: (r: TrendRange) => void
  setShowClosed: (v: boolean) => void
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
      showClosed: false,
      phoneLine: "day",
      trendRange: DEFAULT_TREND_RANGE,
      setTrendRange: (trendRange) => set({ trendRange }),
      setShowClosed: (showClosed) => set({ showClosed }),
      // 存的值不認得時（手改過、以後的版本）當成今日漲跌，按一下換成報酬率
      togglePhoneLine: () => set((s) => ({ phoneLine: s.phoneLine === "pnl" ? "day" : "pnl" })),
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
    {
      name: "forliosa:ledger",
      // 第 2 版（2026-11-16）：預設欄位多了「損益」。
      // 之後加的 phoneLine、trendRange（2026-11-17）不用升版：存的設定裡沒有這兩項時，讀回來用預設（persist 把存的值蓋在預設上），其他設定照舊
      version: 2,
      migrate: migrateLedgerPrefs as (persisted: unknown, version: number) => LedgerPrefs,
      partialize: ({ columns, showTrend, pinned, showClosed, phoneLine, trendRange }) => ({
        columns,
        showTrend,
        pinned,
        showClosed,
        phoneLine,
        trendRange,
      }),
      storage: createJSONStorage(() => localStorage),
    },
  ),
)
