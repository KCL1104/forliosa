import type { InstrumentType, Market, Quote } from "@/api/types"
import { limitPrices } from "@/lib/tick"

/**
 * 這一檔今天的漲跌停價（個股頁的價格與漲跌停軌道用）。
 * - 美股沒有漲跌停：null。
 * - 報價有帶這兩個欄位（新版後端）：照後端的。**後端給 null 就是沒有漲跌停**——國外成分 ETF、新上市前五日，
 *   證交所的升降幅度表沒有漲跌停價；不能自己用參考價 ±10% 補一個出來。
 * - 報價沒有這兩個欄位（舊版後端）：用參考價 ±10% 算（`lib/tick.ts` 的 `limitPrices`）。
 */
export function quoteLimits(quote: Quote | undefined, reference: number | null, market: Market, type: InstrumentType): { up: number; down: number } | null {
  if (market === "US" || !quote) return null
  if (quote.limit_up !== undefined || quote.limit_down !== undefined) {
    const up = quote.limit_up ?? null
    const down = quote.limit_down ?? null
    return up !== null && down !== null ? { up, down } : null
  }
  return limitPrices(reference, market, type)
}

export interface LimitTrackInput {
  close: number
  reference: number
  up: number
  down: number
  /** 當天的最低、最高（沒有就不畫範圍） */
  low?: number | null
  high?: number | null
}

export interface LimitTrackGeometry {
  /** 位置都是 0（跌停）到 1（漲停） */
  close: number
  reference: number
  /** 當天的範圍；資料不完整或互相矛盾（最低比收盤高…）時是 null */
  band: { from: number; to: number } | null
  /** 收在漲停或跌停 */
  at: "up" | "down" | null
}

const ok = (n: number | null | undefined): n is number => typeof n === "number" && Number.isFinite(n) && n > 0
/** 浮點誤差：0.05 的升降單位乘來乘去會差 1e-12 */
const EPS = 1e-9

/**
 * 漲跌停軌道的位置：跌停在 0、漲停在 1，參考價、收盤、當天的最低最高照比例放。
 * 資料對不起來時不畫（回傳 null），不畫一條會騙人的軌道：
 * 漲停不高於跌停、參考價不在兩者之間、收盤落在漲跌停外面（例如漲跌停還是前一天的）。
 * 最低、最高只在 最低 ≤ 收盤 ≤ 最高 時畫；超出漲跌停一點點（四捨五入）就停在端點。
 */
export function limitTrack(i: LimitTrackInput): LimitTrackGeometry | null {
  const { close, reference, up, down } = i
  if (!ok(close) || !ok(reference) || !ok(up) || !ok(down)) return null
  if (!(up > down) || reference <= down || reference >= up) return null
  if (close < down - EPS || close > up + EPS) return null
  const span = up - down
  const pos = (v: number) => Math.min(1, Math.max(0, (v - down) / span))
  const band = ok(i.low) && ok(i.high) && i.low <= i.high && i.low <= close + EPS && i.high >= close - EPS ? { from: pos(i.low), to: pos(i.high) } : null
  return {
    close: pos(close),
    reference: pos(reference),
    band,
    at: close >= up - EPS ? "up" : close <= down + EPS ? "down" : null,
  }
}
