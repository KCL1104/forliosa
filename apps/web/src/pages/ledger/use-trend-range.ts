import { usePerformance, useSummary } from "@/api/queries"
import { DEFAULT_TREND_RANGE, isTrendRange, trendState, type TrendRange } from "@/lib/trend-range"
import { useLedgerPrefs } from "./ledger-prefs"
import { trendMissingReason } from "./trend-reason"

/**
 * 帳本整頁只有一個區間（產品負責人 2026-11-17：首頁走勢負責總資產＋投入本金，績效分段負責報酬率與基準）：
 * 主數字下方的總資產走勢和績效分段用同一個選擇（`ledger-prefs` 的 `trendRange`，存在這台瀏覽器），按鈕只有一排（`useTrendChipsShown`）。
 * 七個區間一律可以選（2026-11-17 負責人要求）：比資料長的區間畫全部的資料、期間照實寫（`lib/trend-range.ts` 的 `rangeExceedsData`），
 * 所以上次選的區間就是現在的區間，不再因為資料短而換成「全部」。
 * `perf` 是「全部」的序列（`usePerformance("ALL", 帳戶)`，不帶基準；不帶帳戶時和首頁走勢是同一個查詢）。
 */
export function useTrendRange(accountId?: string): {
  perf: ReturnType<typeof usePerformance>
  range: TrendRange
  setRange: (r: TrendRange) => void
} {
  const perf = usePerformance("ALL", accountId)
  const raw = useLedgerPrefs((s) => s.trendRange)
  const setRange = useLedgerPrefs((s) => s.setTrendRange)
  return { perf, range: isTrendRange(raw) ? raw : DEFAULT_TREND_RANGE, setRange }
}

/**
 * 帳本要不要放總資產走勢（手機上它自己一盤「總資產走勢」，要先知道畫不畫才放托盤）：和 `HeroTrend` 回傳的東西同一個條件——
 * 「自訂」沒關掉、序列讀得到，而且畫得出走勢或後端說了畫不出來的原因。
 */
export function useHeroTrendShown(): boolean {
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const { perf } = useTrendRange()
  if (!showTrend || perf.isError) return false
  if (!perf.data) return true
  return trendState(perf.data.series.length) !== "missing" || !!trendMissingReason(perf.data.notes ?? [])
}

/**
 * 首頁走勢（全部帳戶）下面放不放區間按鈕：和 `HeroTrend` 實際畫不畫同一個條件——「自訂」沒關掉走勢、主數字讀到了
 * （`LedgerPage` 等主數字回來才放走勢）、走勢的序列讀得到、畫得出走勢（2 個收盤以上；歷史短時也放）。
 * 整頁只有一排區間按鈕：放的時候每個分段都是這一排（換分段時分段列不會上下跳），績效分段不放自己的；
 * 不放的時候（走勢關掉、主數字或走勢讀不到、不到 2 個收盤）績效分段才在工具列放「績效區間」。
 * 主數字還在讀時當作會放（主數字和走勢一起出現）：績效分段先不放，免得按鈕先出現在工具列、再搬到走勢下面。
 */
export function useTrendChipsShown(): boolean {
  const { perf } = useTrendRange()
  const summary = useSummary()
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const heroShown = summary.data !== undefined || summary.isPending
  return showTrend && heroShown && !perf.isError && !!perf.data && trendState(perf.data.series.length) !== "missing"
}
