import type { Performance } from "@/api/types"
import { isCoverageNote, REFERENCE_TAIL } from "@/lib/data-notes"
import { formatDateShort } from "@/lib/format"
import { trendState, trendWindow, type TrendRange } from "@/lib/trend-range"

/**
 * 後端 notes 說「有持股沒有收盤價，所以算不出來」的那一句：剛加入、還沒抓到收盤價的美股
 * （「MSFT：還沒有收盤價，績效算不出來」）；美股收盤價沒開的環境是「AAPL：美股沒有報價，含美股的績效算不出來」。
 * 「持股期間有幾天沒有收盤價」是資料還不夠，不算這一種。
 */
export function isUnpricedNote(note: string): boolean {
  return /還沒有收盤價|沒有報價/.test(note)
}

/**
 * 帳本主數字下方的總資產走勢畫不出來的原因（`HeroTrend` 的一行說明）。
 * 只取後端 notes 明講的兩種——有持股還沒有收盤價、資料還不夠；
 * 其他情況（載入失敗、沒有持股、notes 沒說）回傳 null，畫面不寫原因。
 */
export function trendMissingReason(notes: readonly string[]): string | null {
  if (notes.some(isUnpricedNote)) return "有持股還沒有收盤價"
  if (notes.some(isCoverageNote)) return "資料還不夠"
  return null
}

/**
 * 歷史短（2～6 個收盤）時，走勢的區間按鈕下面那一行引用的後端原文（「績效從 2026/11/12 收盤開始算，之前沒有資料」）。
 * 每個分段都寫（高度不跟著分段變）；績效分段的說明就不再重複同一句（`PerformanceView`）。
 */
export function trendClipNote(p: Pick<Performance, "series" | "notes"> | undefined): string | undefined {
  if (!p || trendState(p.series.length) !== "short") return undefined
  return (p.notes ?? []).find((n) => /^績效從 .+ 收盤開始算/.test(n))
}

/**
 * 區間用到存檔開始以前的 Yahoo 參考價時（產品負責人 2026-11-18）走勢下面的一行：「11/11 以前用 Yahoo 參考價計算，不是官方資料」。
 * 首頁走勢只拿一次「全部」、在前端切區間，所以看這個區間的第一點（基準收盤也算：區間報酬的分母）有沒有在
 * 後端的 `reference_until` 之前或當天。沒用到時是 null。`withYear`：走勢的日期寫年份時（跨年、1 年），這裡也寫。
 */
export function trendReferenceLine(p: Pick<Performance, "series" | "reference_until"> | undefined, range: TrendRange, withYear = false): string | null {
  const until = p?.reference_until
  if (!p || !until || p.series.length === 0) return null
  const first = trendWindow(p.series, range).points[0]
  if (!first || first.t > until) return null
  return `${withYear ? `${until.slice(0, 4)}/` : ""}${formatDateShort(until, false)} ${REFERENCE_TAIL}`
}
