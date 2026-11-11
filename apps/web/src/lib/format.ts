/**
 * 台股慣例的數字與日期格式。
 * - 負號一律用 U+2212「−」（與連字號區分，等寬數字下對齊）
 * - 金額縮寫：萬、億、兆
 * - 數量：1 張 = 1,000 股
 * - 日期：Asia/Taipei
 */
import type { ColorConvention, Currency, Market, QuantityUnit } from "@/api/types"

export const MINUS = "−"
export const MASK = "••••"
export const TZ = "Asia/Taipei"

export type Direction = "up" | "down" | "flat"

const EPS = 1e-9

export function direction(n: number | null | undefined): Direction {
  if (n === null || n === undefined || Number.isNaN(n) || Math.abs(n) < EPS) return "flat"
  return n > 0 ? "up" : "down"
}

/** ▲ 漲、▼ 跌；平盤不加符號。顏色之外一定要搭配符號（色弱可辨）。 */
export function directionGlyph(d: Direction): string {
  return d === "up" ? "▲" : d === "down" ? "▼" : ""
}

/**
 * 漲跌顏色：台灣慣例紅漲綠跌，美國慣例綠漲紅跌。
 * 回傳語意色名，實際色值由 CSS 變數 `--rise`／`--fall` 決定。
 */
export function conventionColors(convention: ColorConvention): { up: "red" | "green"; down: "red" | "green" } {
  return convention === "tw" ? { up: "red", down: "green" } : { up: "green", down: "red" }
}

/** Tailwind class：上漲用 text-rise、下跌用 text-fall（CSS 依慣例對應紅／綠） */
export function toneClass(d: Direction): string {
  return d === "up" ? "text-rise" : d === "down" ? "text-fall" : "text-muted-foreground"
}

function group(n: number, decimals: number): string {
  return new Intl.NumberFormat("zh-TW", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
}

export function formatNumber(n: number, decimals = 0): string {
  const s = group(Math.abs(n), decimals)
  return n < 0 && Math.abs(n) >= 0.5 * 10 ** -decimals ? `${MINUS}${s}` : s
}

export const CURRENCY_PREFIX: Record<Currency, string> = { TWD: "NT$", USD: "US$" }

export interface MoneyOptions {
  currency?: Currency
  decimals?: number
  /** 正數也加「+」 */
  signed?: boolean
  /** 不加 NT$／US$ */
  bare?: boolean
}

export function formatMoney(n: number, opts: MoneyOptions = {}): string {
  const { currency = "TWD", signed = false, bare = false } = opts
  const decimals = opts.decimals ?? (currency === "USD" ? 2 : 0)
  const abs = group(Math.abs(n), decimals)
  const isZero = Math.abs(n) < 0.5 * 10 ** -decimals
  const sign = isZero ? "" : n < 0 ? MINUS : signed ? "+" : ""
  return `${sign}${bare ? "" : CURRENCY_PREFIX[currency]}${abs}`
}

const UNITS: [number, string][] = [
  [1e12, "兆"],
  [1e8, "億"],
  [1e4, "萬"],
]

/** 萬／億／兆縮寫：3,284,500 → 328.45 萬；123,456,789,012 → 1,234.57 億 */
export function formatCompact(n: number, decimals = 2): string {
  const abs = Math.abs(n)
  const sign = n < 0 && abs >= 0.5 ? MINUS : ""
  for (const [size, unit] of UNITS) {
    if (abs >= size) {
      const v = abs / size
      // 保留至多 decimals 位小數，去掉多餘的 0
      const s = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: decimals }).format(v)
      return `${sign}${s} ${unit}`
    }
  }
  return `${sign}${group(abs, 0)}`
}

export function formatMoneyCompact(n: number, opts: Omit<MoneyOptions, "decimals"> = {}): string {
  const { currency = "TWD", signed = false, bare = false } = opts
  if (Math.abs(n) < 1e4) return formatMoney(n, { currency, signed, bare })
  const body = formatCompact(Math.abs(n))
  const sign = n < 0 ? MINUS : signed ? "+" : ""
  return `${sign}${bare ? "" : CURRENCY_PREFIX[currency]}${body}`
}

export interface PercentOptions {
  decimals?: number
  signed?: boolean
}

/** 比率（0.0124）→「+1.24%」 */
export function formatPercent(r: number | null | undefined, opts: PercentOptions = {}): string {
  if (r === null || r === undefined || Number.isNaN(r)) return "—"
  const { decimals = 2, signed = true } = opts
  const pct = r * 100
  const isZero = Math.abs(pct) < 0.5 * 10 ** -decimals
  const sign = isZero ? "" : pct < 0 ? MINUS : signed ? "+" : ""
  return `${sign}${group(Math.abs(pct), decimals)}%`
}

/** 價格：美股 2 位小數；台股依價位最多 2 位小數 */
export function formatPrice(p: number | null | undefined, market: Market = "TWSE"): string {
  if (p === null || p === undefined) return "—"
  if (market === "US") return formatNumber(p, 2)
  const decimals = Number.isInteger(p) && p >= 1000 ? 0 : 2
  return formatNumber(p, decimals)
}

/**
 * 數量：
 * - 以張顯示（預設）：1500 → 「1 張 500 股」、8000 →「8 張」、37 →「37 股」
 * - 以股顯示：1500 →「1,500 股」
 * - 美股一律以股，允許小數（碎股）
 */
export function formatQuantity(shares: number, unit: QuantityUnit = "lot", market: Market = "TWSE"): string {
  if (market === "US") {
    const decimals = Number.isInteger(shares) ? 0 : Math.min(4, (String(shares).split(".")[1] ?? "").length)
    return `${formatNumber(shares, decimals)} 股`
  }
  if (unit === "share") return `${formatNumber(shares, 0)} 股`
  const sign = shares < 0 ? MINUS : ""
  const abs = Math.abs(Math.round(shares))
  const lots = Math.floor(abs / 1000)
  const rest = abs % 1000
  if (lots === 0) return `${sign}${formatNumber(rest)} 股`
  if (rest === 0) return `${sign}${formatNumber(lots)} 張`
  return `${sign}${formatNumber(lots)} 張 ${formatNumber(rest)} 股`
}

/** 隱私模式遮罩：遮蔽時回傳固定寬度的點點，不洩漏位數 */
export function mask(text: string, hidden: boolean): string {
  return hidden ? MASK : text
}

// ── 日期 ─────────────────────────────────────────────────
const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"]

function parts(d: string): { y: number; m: number; day: number } {
  const [y, m, day] = d.slice(0, 10).split("-").map(Number)
  return { y: y!, m: m!, day: day! }
}

/** 2026-11-11 → 2026/11/11 */
export function formatDate(d: string): string {
  const { y, m, day } = parts(d)
  return `${y}/${String(m).padStart(2, "0")}/${String(day).padStart(2, "0")}`
}

/** 2026-11-11 → 11/11（三） */
export function formatDateShort(d: string, withWeekday = true): string {
  const { y, m, day } = parts(d)
  const w = new Date(Date.UTC(y, m - 1, day)).getUTCDay()
  return `${m}/${day}${withWeekday ? `（${WEEKDAYS[w]}）` : ""}`
}

/** ISO 時間戳 → 台北時間「11/11 13:30」 */
export function formatDateTime(iso: string): string {
  const f = new Intl.DateTimeFormat("zh-TW", {
    timeZone: TZ,
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
  const p = Object.fromEntries(f.formatToParts(new Date(iso)).map((x) => [x.type, x.value]))
  return `${p.month}/${p.day} ${p.hour}:${p.minute}`
}

/** 今天（台北時區）YYYY-MM-DD */
export function todayInTaipei(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(now)
}

export function daysBetween(from: string, to: string): number {
  const a = Date.UTC(parts(from).y, parts(from).m - 1, parts(from).day)
  const b = Date.UTC(parts(to).y, parts(to).m - 1, parts(to).day)
  return Math.round((b - a) / 86400000)
}

/** 「今天」「明天」「7 天後」 */
export function formatDaysUntil(target: string, today: string): string {
  const n = daysBetween(today, target)
  if (n === 0) return "今天"
  if (n === 1) return "明天"
  if (n < 0) return `${-n} 天前`
  return `${n} 天後`
}

/** 月營收（千元）→ 億元字串 */
export function formatRevenueThousands(v: number): string {
  return formatCompact(v * 1000)
}
