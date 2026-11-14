/**
 * 台股慣例的數字與日期格式。
 * - 負號一律用 U+2212「−」（與連字號區分，等寬數字下對齊）
 * - 金額縮寫：萬、億、兆
 * - 數量：1 張 = 1,000 股
 * - 日期：Asia/Taipei
 */
import type { ColorConvention, Currency, InstrumentType, Market, QuantityUnit } from "@/api/types"
import { quoteDecimals } from "@/lib/tick"

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

/**
 * 價格的唯一格式（現價、成交價、均價、圖表讀數、相關股票）——The Tick Decimal Rule：
 * - 美股一律 2 位。
 * - 台股依升降單位（`quoteDecimals`）：1,085、236.5、398、22.40；ETF 50 元以上是 0.05 檔，2 位（52.40）。
 * - 不在升降單位上的價位（均價這類算出來的數字）不藏精度：補到看得出差異為止，最多 2 位（692.61、612.5）。
 * - 呼叫端沒給 `type`（不知道是股票還是 ETF）時：500 元以下用 2 位（股票 0.1／0.5 檔和 ETF 0.05 檔都能照實顯示），
 *   500 元以上用 0 位；同樣不藏精度。知道 `type` 的地方都要傳，才會是 214 而不是 214.00。
 */
export function formatPrice(p: number | null | undefined, market: Market = "TWSE", type?: InstrumentType): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—"
  if (market === "US") return formatNumber(p, 2)
  const abs = Math.abs(p)
  let decimals = type ? quoteDecimals(abs, market, type) : abs >= 500 ? 0 : 2
  // 價格最多到分（0.01）：四捨五入到 2 位後，位數不夠表達這個值就往上補
  const cents = Math.round(abs * 100) / 100
  while (decimals < 2 && Math.abs(cents - Math.round(cents * 10 ** decimals) / 10 ** decimals) > 1e-9) decimals++
  return formatNumber(p, decimals)
}

/**
 * 換算出來的價位（河流圖各倍數的股價、指數點位）：是估計值，四捨五入到報價的位數（Tick Decimal Rule），
 * 不像均價那樣補位數：836.8 → 837、287.3、5.04。
 */
export function formatPriceLevel(p: number, market: Market = "TWSE", type: InstrumentType = "stock"): string {
  if (market === "US") return formatNumber(p, 2)
  return formatNumber(p, quoteDecimals(Math.abs(p), market, type))
}

/**
 * 每股金額（近四季 EPS、每股淨值）：財報到分，固定 2 位；台股值後面接「元」，美股前綴 US$。
 * 52.30 元、−1.25 元、US$8.98。股利每股金額用 `{ dividend: true }`：照公告的位數、最多 3 位、不補 0（5 元、0.415 元）。
 */
export function formatPerShare(n: number, market: Market, opts: { dividend?: boolean } = {}): string {
  const abs = opts.dividend
    ? new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 3 }).format(Math.abs(n))
    : group(Math.abs(n), 2)
  const sign = n < 0 && Math.abs(n) >= (opts.dividend ? 0.0005 : 0.005) ? MINUS : ""
  return market === "US" ? `${sign}US$${abs}` : `${sign}${abs} 元`
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

/** 2026-11-11 → 2026/11/11（三）（日期欄位：買進日期常常是好幾年前） */
export function formatDateLong(d: string): string {
  return `${parts(d).y}/${formatDateShort(d)}`
}

/** 2026-11-11 → 11/11（三） */
export function formatDateShort(d: string, withWeekday = true): string {
  const { y, m, day } = parts(d)
  const w = new Date(Date.UTC(y, m - 1, day)).getUTCDay()
  return `${m}/${day}${withWeekday ? `（${WEEKDAYS[w]}）` : ""}`
}

/** 成交量：台股以張（1 張 = 1,000 股）、美股以股；資料源沒有時為「—」 */
export function formatVolume(shares: number | null | undefined, market: Market, opts: { compact?: boolean } = {}): string {
  if (shares === null || shares === undefined) return "—"
  if (market === "US") return `${opts.compact ? formatCompact(shares) : formatNumber(shares)} 股`
  return `${formatNumber(Math.round(shares / 1000))} 張`
}

/** ISO 時間戳 → 台北時間「11/11 13:30」；沒有時間（資料源未提供）時為「—」 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
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
