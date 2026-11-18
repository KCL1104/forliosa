import type { AiChart, AiChartBar as Bar } from "./remote"

/** 市場報告的雙向橫條（`HBarsChart`）怎麼排：零軸、收合、名稱欄寬、兩欄排的門檻。純函式，測試也用 */

/**
 * 零軸的位置與比例：`axis` 是零軸從橫條欄左邊算的百分比，`k` 是值 1 佔幾個百分點。
 * 有正有負時，零軸依兩邊最大的絕對值（基準線也算）的比例放，兩邊各至少 25%——跌多的日子橫條不會只用到一半寬；
 * 只有正的在左邊、只有負的在右邊。只給報告的橫條用（市場頁的 `SectorList` 照舊在中間）。
 */
export function barScale(values: readonly number[]): { axis: number; k: number } {
  let up = 0
  let down = 0
  for (const v of values) {
    if (v > up) up = v
    if (-v > down) down = -v
  }
  if (up > 0 && down > 0) {
    const axis = Math.min(75, Math.max(25, (down / (down + up)) * 100))
    return { axis, k: Math.min(axis / down, (100 - axis) / up) }
  }
  if (down > 0) return { axis: 100, k: 100 / down }
  return { axis: 0, k: 100 / (up || 1e-9) }
}

/**
 * 窄的主欄要收起哪幾條（`true` 是看得到）：前 `head` 條、`keep` 裡的名稱、後 `tail` 條。
 * 只收起一條的地方照樣列出來（換成「⋯ 另 1 類」不會比較短）；一條都不用收時是 `null`。
 */
export function foldPlan(bars: readonly Bar[], fold: AiChart["fold"]): boolean[] | null {
  if (!fold) return null
  const n = bars.length
  const keep = new Set(fold.keep)
  const shown = bars.map((b, i) => i < fold.head || i >= n - fold.tail || keep.has(b.label))
  for (let i = 0; i < n; i++) {
    if (!shown[i] && (i === 0 || shown[i - 1]) && (i === n - 1 || shown[i + 1])) shown[i] = true
  }
  return shown.every(Boolean) ? null : shown
}

/** 名稱欄的寬度（em，估計；兩欄排的時候兩半用同一個寬度，零軸才對得齊）：中文字 1em、數字與英文約半個字 */
export function labelEm(s: string): number {
  let w = 0
  for (const ch of s) w += ch.charCodeAt(0) > 255 ? 1 : /[0-9]/.test(ch) ? 0.56 : /[A-Z]/.test(ch) ? 0.66 : 0.52
  return w
}

/** 兩欄排的門檻（32 類）；和 `ReportSection` 讓圖用整個主欄寬的門檻相同 */
export const SPLIT_BARS = 12

