import type { UTCTimestamp } from "lightweight-charts"
import type { Candle } from "@/api/types"

/** 交易日 → 圖表時間（UTC 00:00） */
export const dayTime = (t: string) => (Date.parse(`${t}T00:00:00Z`) / 1000) as UTCTimestamp

export function movingAverage(candles: Candle[], n: number) {
  const out: { time: UTCTimestamp; value: number }[] = []
  let sum = 0
  candles.forEach((c, i) => {
    sum += c.c
    if (i >= n) sum -= candles[i - n]!.c
    if (i >= n - 1) out.push({ time: dayTime(c.t), value: sum / n })
  })
  return out
}

/** 重要時刻：區間內單日漲跌幅最大的幾天（≥ 3%），最多 5 個 */
export function importantMoments(candles: Candle[], limit = 5): { t: string; ret: number }[] {
  const moves = candles.slice(1).map((c, i) => ({ t: c.t, ret: c.c / candles[i]!.c - 1 }))
  return moves
    .filter((m) => Math.abs(m.ret) >= 0.03)
    .sort((a, b) => Math.abs(b.ret) - Math.abs(a.ret))
    .slice(0, limit)
    .sort((a, b) => a.t.localeCompare(b.t))
}

