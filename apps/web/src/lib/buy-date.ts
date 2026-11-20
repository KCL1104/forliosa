import type { Candle } from "@/api/types"

/**
 * 估計買入日（資產組成原型；`docs/proposals/asset-composition.md`〈估計買入日的算法〉）：
 * 匯入庫存只有成本價（券商的均價）、沒有買進日期時，從匯入那天往回找股價「經過」成本價的日子。
 * - 當天最低價 ≤ 成本價 ≤ 當天最高價，就算經過（用最高、最低價判斷，不用收盤價）。
 * - 跳空也算：前一天最高 600、當天最低 620、成本 612——成本落在兩天之間的缺口，取跳過去的那一天（往下跳空同理）。
 * - 從匯入那天往回第一個經過的日子就是估計的買入日；五年內都沒有就不估（買入日用匯入那天）。
 * K 線的價格必須是當時真正的成交價（不是還原權息、照分割換算過的價格），不然和券商的成本比不起來。
 * 這裡只有純函式，不碰畫面：選日期的畫面（`pages/ledger/BuyDatePicker.tsx`）和 mock 都用它。
 */

/** 第 i 天有沒有經過成本價：當天的高低價包住成本，或成本落在和前一天之間的跳空缺口 */
export function crossesOn(candles: readonly Pick<Candle, "h" | "l">[], i: number, cost: number): boolean {
  const c = candles[i]
  if (!c || !Number.isFinite(cost)) return false
  if (c.l <= cost && cost <= c.h) return true
  const prev = candles[i - 1]
  if (!prev) return false
  // 往上跳空：昨天最高還在成本下面，今天最低已經在成本上面；往下跳空反過來
  return (prev.h < cost && c.l > cost) || (prev.l > cost && c.h < cost)
}

/** 經過成本價的日子（在 `candles` 裡的位置，由舊到新）；`until`（含）以後的不算 */
export function crossingIndexes(candles: readonly Pick<Candle, "t" | "h" | "l">[], cost: number, until?: string): number[] {
  const out: number[] = []
  for (let i = 0; i < candles.length; i++) {
    if (until && candles[i]!.t > until) break
    if (crossesOn(candles, i, cost)) out.push(i)
  }
  return out
}

/**
 * 估計的買入日：從 `until`（匯入那天，含）往回第一個經過成本價的日子；都沒有是 null。
 * `from`：最早只找到這一天（匯入以前最近一次股票分割、減資、配股；那天本身可以）——更早的 K 線拿掉，
 * 所以那天的第一根沒有「前一天」，分割那天股價掉下來不算跳空經過成本（後端 `domain/buy_date.py` 的 `start`）。
 */
export function estimateBuyDate(candles: readonly Pick<Candle, "t" | "h" | "l">[], cost: number, until: string, from?: string | null): string | null {
  const bars = from ? candles.filter((c) => c.t >= from) : candles
  let last = -1
  for (let i = 0; i < bars.length && bars[i]!.t <= until; i++) last = i
  for (let i = last; i >= 0; i--) if (crossesOn(bars, i, cost)) return bars[i]!.t
  return null
}

/**
 * 候選的日子：連續好幾天都經過成本價算一段（股價在成本附近來回時會有幾十天），一段只列一天——最近的那一天，
 * 和估計的算法一致（往回找時先碰到的是一段的最後一天）。由新到舊。
 */
export function candidateDays(candles: readonly Pick<Candle, "t" | "h" | "l">[], cost: number, until?: string): number[] {
  const idx = crossingIndexes(candles, cost, until)
  const out: number[] = []
  for (let k = idx.length - 1; k >= 0; k--) {
    const i = idx[k]!
    // 一段的最後一天：後一天不是經過的日子
    if (k === idx.length - 1 || idx[k + 1] !== i + 1) out.push(i)
  }
  return out
}

/** 收盤價和成本差多少（比例，正的是收盤比成本高） */
export function closeGap(close: number, cost: number): number {
  return cost ? close / cost - 1 : 0
}

/** 差多少才在畫面上照實說（「這天收盤 580，和你的成本 612 差 5%」）：3% */
export const FAR_FROM_COST = 0.03

export function isFarFromCost(close: number, cost: number): boolean {
  return Math.abs(closeGap(close, cost)) >= FAR_FROM_COST
}

/** 一個日期在 K 線裡的位置：那一天，或那天之前最後一個交易日；比第一天還早時是 0 */
export function indexOnOrBefore(candles: readonly Pick<Candle, "t">[], day: string): number {
  let lo = 0
  let hi = candles.length - 1
  let ans = 0
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (candles[mid]!.t <= day) {
      ans = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return ans
}
