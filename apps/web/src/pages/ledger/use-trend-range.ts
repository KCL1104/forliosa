import { useMemo } from "react"
import { usePerformance } from "@/api/queries"
import { availableRanges, DEFAULT_TREND_RANGE, effectiveRange, isTrendRange, type TrendRange } from "@/lib/trend-range"
import { useLedgerPrefs } from "./ledger-prefs"

/**
 * 帳本整頁只有一個區間（產品負責人 2026-11-17：首頁走勢負責總資產＋投入本金，績效分段負責報酬率與基準）：
 * 主數字下方的總資產走勢和績效分段用同一個選擇（`ledger-prefs` 的 `trendRange`，存在這台瀏覽器）。
 * 哪些區間撐得起來看「全部」的序列（`usePerformance("ALL", 帳戶)`，不帶基準；不帶帳戶時和首頁走勢是同一個查詢）。
 * 上次選的區間現在撐不起來時用「全部」。序列還沒讀到時先用上次選的（`known` 是 false）。
 */
export function useTrendRange(accountId?: string): {
  perf: ReturnType<typeof usePerformance>
  ranges: TrendRange[]
  known: boolean
  range: TrendRange
  setRange: (r: TrendRange) => void
} {
  const perf = usePerformance("ALL", accountId)
  const raw = useLedgerPrefs((s) => s.trendRange)
  const setRange = useLedgerPrefs((s) => s.setTrendRange)
  const stored = isTrendRange(raw) ? raw : DEFAULT_TREND_RANGE
  const series = perf.data?.series
  const ranges = useMemo(() => (series ? availableRanges(series) : null), [series])
  return { perf, ranges: ranges ?? [], known: !!ranges, range: ranges ? effectiveRange(stored, ranges) : stored, setRange }
}
