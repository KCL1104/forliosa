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

/**
 * 報價的小數位數（依升降單位）：
 * - 升降單位 ≥ 1（≥ 500 元的股票）→ 0 位：1,085、932
 * - 升降單位 0.1／0.5 → 1 位，整數時不帶小數：236.5、398
 * - 升降單位 0.01／0.05 → 2 位：22.40、52.35
 * - 美股一律 2 位
 */
export function quoteDecimals(price: number, market: Market, type: InstrumentType = "stock"): number {
  if (market === "US") return 2
  const t = twTick(price, type)
  if (t >= 1) return 0
  if (t >= 0.1) return Number.isInteger(Math.round(price * 100) / 100) ? 0 : 1
  return 2
}

export function formatQuote(price: number | null | undefined, market: Market, type: InstrumentType = "stock"): string {
  if (price === null || price === undefined) return "—"
  const d = quoteDecimals(price, market, type)
  return new Intl.NumberFormat("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d }).format(price)
}

/** 漲跌點數：用現價的位數（▲50、▲5.5、▲0.55） */
export function formatQuoteChange(change: number, price: number, market: Market, type: InstrumentType = "stock"): string {
  const d = Math.max(quoteDecimals(price, market, type), Number.isInteger(Math.round(change * 100) / 100) ? 0 : 1)
  return new Intl.NumberFormat("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d }).format(Math.abs(change))
}
