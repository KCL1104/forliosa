/**
 * 台股升降單位（tick）與漲跌停價。
 * - 股票：< 10 → 0.01、< 50 → 0.05、< 100 → 0.1、< 500 → 0.5、< 1000 → 1、其餘 5
 * - ETF（含受益憑證）：< 50 → 0.01、其餘 0.05
 * - 漲跌停：參考價 ±10%，漲停向下、跌停向上取到該價位的升降單位
 * 美股沒有漲跌停，回傳 null。
 */
import type { InstrumentType, Market } from "@/api/types"

export function twTick(price: number, type: InstrumentType = "stock"): number {
  if (type === "etf") return price < 50 ? 0.01 : 0.05
  if (price < 10) return 0.01
  if (price < 50) return 0.05
  if (price < 100) return 0.1
  if (price < 500) return 0.5
  if (price < 1000) return 1
  return 5
}

/** 浮點誤差修正：四捨五入到 4 位小數 */
const fix = (n: number) => Math.round(n * 10_000) / 10_000

export function limitPrices(
  reference: number | null | undefined,
  market: Market,
  type: InstrumentType = "stock",
): { up: number; down: number } | null {
  if (market === "US" || reference === null || reference === undefined || reference <= 0) return null
  const rawUp = reference * 1.1
  const tUp = twTick(rawUp, type)
  const up = fix(Math.floor(fix(rawUp / tUp)) * tUp)
  const rawDown = reference * 0.9
  const tDown = twTick(rawDown, type)
  const down = fix(Math.ceil(fix(rawDown / tDown)) * tDown)
  return { up, down }
}

/** 現價是否在漲停或跌停 */
export function limitState(price: number | null | undefined, up: number | null | undefined, down: number | null | undefined): "up" | "down" | null {
  if (price === null || price === undefined) return null
  if (up !== null && up !== undefined && price >= up) return "up"
  if (down !== null && down !== undefined && price <= down) return "down"
  return null
}

/** 由代號判斷市場：2330.TW 上市、6488.TWO 上櫃、其餘美股 */
export function marketOf(symbol: string): Market {
  if (symbol.endsWith(".TWO")) return "TPEX"
  if (symbol.endsWith(".TW")) return "TWSE"
  return "US"
}

/** 2330.TW → 2330 */
export function codeOf(symbol: string): string {
  return symbol.replace(/\.(TW|TWO)$/i, "")
}
