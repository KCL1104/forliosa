import { formatCompact, formatNumber, formatPercent, formatPrice } from "@/lib/format"
import { marketOf } from "@/lib/tick"
import type { AiChart } from "./remote"

/**
 * AI 圖卡的幾何與讀數（純函式，方便測試）。圖卡畫的每個點都是後端 `draw_chart` 讀的資料；
 * 這裡只決定怎麼放：一個縱軸（不做雙軸）、整齊的刻度、線尾標籤互相讓開。
 */

export type ChartForm = "line" | "bar"

/** 類別軸（月份、季別）的柱子總數不超過這個數才畫柱狀；再多就太細，改畫折線 */
const MAX_BARS = 24

export function chartForm(chart: AiChart): ChartForm {
  if (chart.x === "date") return "line"
  const cats = categories(chart).length
  return cats * chart.series.length <= MAX_BARS ? "bar" : "line"
}

/** 類別軸的刻度：所有系列出現過的月份／季別，照時間排 */
export function categories(chart: AiChart): string[] {
  return [...new Set(chart.series.flatMap((s) => s.points.map((p) => p.t)))].sort()
}

/** 整齊的刻度：1、2、2.5、5 × 10ⁿ 的間隔，涵蓋 lo～hi，大約 `count` 格 */
export function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1]
  if (lo === hi) {
    const pad = Math.abs(lo) * 0.05 || 1
    lo -= pad
    hi += pad
  }
  const raw = (hi - lo) / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw * 0.999) ?? 10 * mag
  const start = Math.floor(lo / step + 1e-9) * step
  const ticks: number[] = []
  for (let i = 0; start + i * step < hi + step * 0.999 && i < 12; i++) ticks.push(Number((start + i * step).toPrecision(12)))
  return ticks
}

/** 縱軸的範圍：報酬率與柱狀圖一定包含 0（柱子從 0 長出來；報酬率要看得出正負） */
export function valueDomain(chart: AiChart, form: ChartForm): { ticks: number[]; min: number; max: number } {
  const values = chart.series.flatMap((s) => s.points.map((p) => p.v))
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  if (chart.unit === "pct" || form === "bar") {
    lo = Math.min(lo, 0)
    hi = Math.max(hi, 0)
  }
  const ticks = niceTicks(lo, hi)
  return { ticks, min: ticks[0]!, max: ticks[ticks.length - 1]! }
}

/** 刻度間隔要幾位小數才寫得出來（2.5 → 1、0.25 → 2、5 → 0），最多 `cap` 位 */
function stepDecimals(step: number, cap = 2): number {
  for (let d = 0; d < cap; d++) {
    const scaled = step * 10 ** d
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9) return d
  }
  return cap
}

/** 縱軸刻度的字（短）：報酬率 +10%、價格 1,050、營收 2,500 億、EPS 12.5 */
export function tickLabel(chart: AiChart, v: number, step: number): string {
  switch (chart.unit) {
    case "pct":
      return formatPercent(v, { decimals: stepDecimals(step * 100, 1) })
    case "amount_k":
      return formatCompact(v * 1000, 0)
    default:
      return formatNumber(v, stepDecimals(step))
  }
}

/** 讀數（提示框、圖例、線尾）：和頁面上同一套格式 */
export function valueLabel(chart: AiChart, v: number, symbol: string | null): string {
  switch (chart.unit) {
    case "pct":
      return formatPercent(v)
    case "amount_k":
      return formatCompact(v * 1000)
    case "eps":
      return formatNumber(v, 2)
    default:
      return formatPrice(v, symbol ? marketOf(symbol) : "TWSE")
  }
}

/** 橫軸的字：日期 5/13（跨年或超過約十個月寫 2025/11）、月份 2025/11、季別 25Q3 */
export function timeLabel(chart: AiChart, t: string, long = false): string {
  if (chart.x === "quarter") return long ? t.replace("Q", " Q") : t.replace(/^(?:FY)?20/, "")
  if (chart.x === "month") return t.replace("-", "/")
  const [y, m, d] = t.split("-")
  return long ? `${y}/${m}/${d}` : `${Number(m)}/${Number(d)}`
}

/** 橫軸刻度：頭、中、尾（點太少就只標頭尾） */
export function axisTicks<T>(items: T[]): T[] {
  if (items.length <= 2) return items
  if (items.length < 5) return [items[0]!, items[items.length - 1]!]
  return [items[0]!, items[Math.floor((items.length - 1) / 2)]!, items[items.length - 1]!]
}

/** 日期軸跨了多久（天）：決定刻度寫「月/日」還是「年/月」 */
export function spanDays(chart: AiChart): number {
  const all = chart.series.flatMap((s) => s.points.map((p) => Date.parse(p.t))).filter(Number.isFinite)
  return all.length ? (Math.max(...all) - Math.min(...all)) / 86_400_000 : 0
}

/** 線尾的短標籤：代號（2330），「我的報酬率」是「我的」 */
export function endLabel(s: AiChart["series"][number]): string {
  if (!s.symbol) return "我的"
  return s.symbol.replace(/\.(TW|TWO|US)$/i, "")
}

/**
 * 線尾標籤互相讓開：照原本的高低排，相鄰至少隔 `gap`，整組留在 [top, bottom] 之內。
 * 回傳和輸入同樣順序的 y；被推開的標籤由圖卡畫一條細線接回線尾。
 */
export function spreadLabels(ys: number[], gap: number, top: number, bottom: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y)
  const placed: number[] = []
  for (const [k, o] of order.entries()) placed.push(k === 0 ? Math.max(o.y, top) : Math.max(o.y, placed[k - 1]! + gap))
  const overflow = placed.length ? placed[placed.length - 1]! - bottom : 0
  if (overflow > 0) {
    for (let k = placed.length - 1; k >= 0; k--) {
      const limit = k === placed.length - 1 ? bottom : placed[k + 1]! - gap
      placed[k] = Math.max(top, Math.min(placed[k]!, limit))
    }
  }
  const out = new Array<number>(ys.length)
  for (const [k, o] of order.entries()) out[o.i] = placed[k]!
  return out
}

/** 一條線在時間 t（含）以前最後一個點的值；沒有就 null（兩個市場的交易日不同時用得到） */
export function valueAt(points: AiChart["series"][number]["points"], t: string): number | null {
  let found: number | null = null
  for (const p of points) {
    if (p.t > t) break
    found = p.v
  }
  return found
}

/** 給螢幕報讀器的一句話：每條線的起訖 */
export function chartSummary(chart: AiChart): string {
  const parts = chart.series
    .filter((s) => s.points.length > 0)
    .map((s) => {
      const first = s.points[0]!
      const last = s.points[s.points.length - 1]!
      return `${s.name}：${timeLabel(chart, first.t, true)} ${valueLabel(chart, first.v, s.symbol)}，${timeLabel(chart, last.t, true)} ${valueLabel(chart, last.v, s.symbol)}`
    })
  return `${chart.title}。${parts.join("；")}`
}
