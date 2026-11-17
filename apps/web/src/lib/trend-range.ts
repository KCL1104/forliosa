import type { PerformancePoint } from "@/api/types"

/**
 * 帳本主數字下方的總資產走勢（產品負責人 2026-11-17 選方案 B）：一次讀「全部」的績效序列（`usePerformance("ALL")`），
 * 區間在前端切。每一天的 market_value、net_invested 和區間無關，換區間不用再問伺服器。
 * 區間的起點和後端 `services/portfolio.py` 的 `range_start` 一樣，區間報酬、起始日也和後端的 TWR、`start_date` 一樣
 * （見 `rangeStartIndex`、`trendWindow`），所以首頁的「近 1 個月 報酬 ▲1.2%」「10/12 – 11/12」和績效分段選「1月」的
 * 時間加權報酬、期間是同一個數字、同一天。
 */
export type TrendRange = "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "ALL"

/** 沒有「1日」：沒有盤中價，1 日只有兩個點，今天的變化已經有「今日」那一格 */
export const TREND_RANGES: readonly { value: TrendRange; label: string }[] = [
  { value: "5D", label: "5日" },
  { value: "1M", label: "1月" },
  { value: "3M", label: "3月" },
  { value: "6M", label: "6月" },
  { value: "YTD", label: "今年" },
  { value: "1Y", label: "1年" },
  { value: "ALL", label: "全部" },
]

export const DEFAULT_TREND_RANGE: TrendRange = "1M"

/** 至少這麼多個收盤才放區間按鈕（第 7 個收盤時，「5日」才真的會切掉一段） */
export const MIN_POINTS_FOR_RANGES = 7

export function isTrendRange(v: unknown): v is TrendRange {
  return TREND_RANGES.some((r) => r.value === v)
}

/** 讀數第一行的標題（「全部」由呼叫端寫成「11/12 起」） */
export const RANGE_TITLE: Record<Exclude<TrendRange, "ALL">, string> = {
  "5D": "近 5 日",
  "1M": "近 1 個月",
  "3M": "近 3 個月",
  "6M": "近 6 個月",
  YTD: "今年以來",
  "1Y": "近 1 年",
}

/** YYYY-MM-DD 往前推 n 個日曆月，月底對齊（3/31 往前 1 個月是 2/28；和後端 `add_months` 一樣） */
export function minusMonths(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number]
  const total = y * 12 + (m - 1) - n
  const ny = Math.floor(total / 12)
  const nm = (total % 12) + 1
  const last = new Date(Date.UTC(ny, nm, 0)).getUTCDate()
  return `${ny}-${String(nm).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`
}

/** 區間名目上的起始日（後端 `range_start`）；5D 與 ALL 不看日期，回傳 null */
function nominalStart(lastDay: string, range: TrendRange): string | null {
  switch (range) {
    case "1M":
      return minusMonths(lastDay, 1)
    case "3M":
      return minusMonths(lastDay, 3)
    case "6M":
      return minusMonths(lastDay, 6)
    case "1Y":
      return minusMonths(lastDay, 12)
    case "YTD":
      return `${lastDay.slice(0, 4)}-01-01`
    default:
      return null
  }
}

/**
 * 區間的第一點（基準收盤）在序列裡的位置：
 * - 5D：最後 6 點的第一點（後端的 5D 也是一個基準收盤＋5 個交易日）。
 * - 1M…1Y、今年：名目起始日「之前」的最後一個收盤。後端從起始日當天或之後的第一個收盤開始、那一天的漲跌也算進去，
 *   所以報酬的起點其實是前一個收盤；這裡把那個收盤畫成第一點，`rangeReturn` 就和後端的 TWR 一樣。
 *   今年的起點因此是去年最後一個收盤。
 * - 資料比區間短（起始日之前沒有收盤）：0，整段。ALL：0。
 */
export function rangeStartIndex(series: readonly Pick<PerformancePoint, "t">[], range: TrendRange): number {
  if (series.length === 0 || range === "ALL") return 0
  if (range === "5D") return Math.max(0, series.length - 6)
  const start = nominalStart(series[series.length - 1]!.t, range)!
  let idx = 0
  for (let i = 0; i < series.length; i++) {
    if (series[i]!.t < start) idx = i
    else break
  }
  return idx
}

/** 切出一個區間 */
export function sliceRange<T extends Pick<PerformancePoint, "t">>(series: readonly T[], range: TrendRange): T[] {
  return series.slice(rangeStartIndex(series, range))
}

/** 名目起始日之前的那個收盤當基準的區間（5D 的基準收盤後端也算在區間裡，見 `trendWindow` 的 `from`） */
const CALENDAR: readonly TrendRange[] = ["1M", "3M", "6M", "YTD", "1Y"]

export interface TrendWindow<T> {
  /** 要畫的點（第一點可能是基準收盤） */
  points: T[]
  /**
   * 報酬的分母。區間從序列的第一天開始時（「全部」、資料比區間短）是 1：後端「全部」的 `twr_index` 第一點是
   * 1＋第一天的報酬（`apps/api/CONTRACT_NOTES.md`〈績效計算的解讀〉；從存檔起點開始算的才剛好是 1.0），
   * 用第一點當分母會少算第一天。其他時候是第一點（基準收盤）的 `twr_index`。
   */
  base: number
  /**
   * 區間的起始日（和後端的 `start_date`、績效分段寫的期間一樣）在 `points` 裡的位置：
   * 1M…1Y 的第一點是名目起始日之前的基準收盤，起始日是下一個收盤（1）；5D 的起始日就是基準收盤、整段時是第一天（0）。
   */
  from: number
}

/** 切出一個區間，連同報酬的分母與起始日（見 `TrendWindow`） */
export function trendWindow<T extends Pick<PerformancePoint, "t" | "twr_index">>(series: readonly T[], range: TrendRange): TrendWindow<T> {
  const start = rangeStartIndex(series, range)
  const points = series.slice(start)
  return {
    points,
    base: start === 0 ? 1 : points[0]!.twr_index,
    from: start > 0 && CALENDAR.includes(range) && points.length > 1 ? 1 : 0,
  }
}

/**
 * 資料撐得起來的區間：這個區間真的會切掉一段（第一點不是序列的第一天）才放；有任何一個時再加「全部」。
 * 不到 7 個收盤一律不放（回傳空陣列）。
 */
export function availableRanges(series: readonly Pick<PerformancePoint, "t">[]): TrendRange[] {
  if (series.length < MIN_POINTS_FOR_RANGES) return []
  const cut = TREND_RANGES.map((r) => r.value).filter((r) => r !== "ALL" && rangeStartIndex(series, r) > 0)
  return cut.length ? [...cut, "ALL"] : []
}

/** 上次選的區間現在撐得起來就用它；撐不起來（或還沒有任何按鈕）畫全部 */
export function effectiveRange(stored: TrendRange, available: readonly TrendRange[]): TrendRange {
  return available.includes(stored) ? stored : "ALL"
}

/**
 * 區間報酬（時間加權，扣掉新買進的影響）：從區間開始到第 `upto` 點，`twr_index ÷ 分母 − 1`。
 * 分母見 `TrendWindow.base`——區間從序列第一天開始時第一天的報酬也算進去，和後端同一個區間的 TWR 一樣。
 */
export function rangeReturn(win: Pick<TrendWindow<Pick<PerformancePoint, "twr_index">>, "points" | "base">, upto = win.points.length - 1): number | null {
  const at = win.points[upto]
  if (!at || !win.base) return null
  return at.twr_index / win.base - 1
}

/** 走勢的狀態：少於 2 點不畫；2～6 點畫、每一點一個圓點、不放區間；7 點以上照常 */
export function trendState(points: number): "missing" | "short" | "full" {
  return points < 2 ? "missing" : points < MIN_POINTS_FOR_RANGES ? "short" : "full"
}

const NICE = [1, 2, 2.5, 5]

/**
 * 縱軸：只看總資產（投入本金不算進來，不然賺得多時總資產會被壓成一條平線），上下各留一點空，
 * 而且至少涵蓋資料中點上下各 `minSpan`（預設 3%）——點很少時 +1% 不會畫成從底拉到頂。
 * 格線固定 `lines` 條（預設 3 條），在整齊的數字上（1、2、2.5、5 × 10ⁿ）；縱軸的頭尾不一定是刻度，
 * 範圍裡放不滿 `lines` 條時往離得近的一邊多加一條、範圍跟著放大。
 */
export function trendDomain(values: readonly number[], { minSpan = 0.03, lines = 3, pad = 0.08 } = {}): { ticks: number[]; min: number; max: number } {
  const finite = values.filter(Number.isFinite)
  if (finite.length === 0) return { ticks: Array.from({ length: lines }, (_, i) => i), min: 0, max: lines - 1 }
  const lo = Math.min(...finite)
  const hi = Math.max(...finite)
  const mid = (lo + hi) / 2
  const half = Math.max(((hi - lo) / 2) * (1 + pad), Math.abs(mid) * minSpan) || 1
  let a = mid - half
  let b = mid + half
  // 金額都不是負的：縱軸不畫到負的
  if (lo >= 0 && a < 0) {
    b -= a
    a = 0
  }
  const fix = (v: number) => Number(v.toPrecision(12))
  // 由小到大試整齊的間隔，第一個在範圍裡最多放 `lines` 條的就用它
  const mag = 10 ** Math.floor(Math.log10((b - a) / (lines * 2)))
  for (let e = mag; e <= mag * 1e4; e *= 10) {
    for (const m of NICE) {
      const step = m * e
      const from = Math.ceil(a / step - 1e-9)
      const to = Math.floor(b / step + 1e-9)
      if (to - from + 1 > lines) continue
      const ticks: number[] = []
      for (let k = from; k <= to; k++) ticks.push(fix(k * step))
      while (ticks.length < lines) {
        const below = fix((ticks.length ? ticks[0]! : Math.ceil(a / step) * step) - step)
        const above = fix((ticks.length ? ticks[ticks.length - 1]! : Math.floor(b / step) * step) + step)
        if (!ticks.length) ticks.push(fix(Math.round(mid / step) * step))
        else if (above - b <= a - below || (lo >= 0 && below < 0)) ticks.push(above)
        else ticks.unshift(below)
      }
      return { ticks, min: Math.min(a, ticks[0]!), max: Math.max(b, ticks[ticks.length - 1]!) }
    }
  }
  return { ticks: [a, b], min: a, max: b }
}

/** 投入本金那條線畫不畫：每一天都在縱軸的範圍裡才畫（差太遠就不畫，讀數照樣寫投入本金） */
export function investedVisible(slice: readonly Pick<PerformancePoint, "net_invested">[], min: number, max: number): boolean {
  return slice.length > 0 && slice.every((p) => p.net_invested >= min && p.net_invested <= max)
}

/**
 * 縱軸刻度的精簡寫法（同一條軸用同一個單位、同樣的小數位）：5.03萬、410萬、1.2億；1 萬以下寫整數。
 * 單位看軸上最大的那個刻度，小數位看刻度的間隔。
 */
export function compactTicks(ticks: readonly number[]): string[] {
  const top = Math.max(...ticks.map(Math.abs))
  const unit = top >= 1e8 ? 1e8 : top >= 1e4 ? 1e4 : 1
  const word = unit === 1e8 ? "億" : unit === 1e4 ? "萬" : ""
  const step = ticks.length > 1 ? Math.abs(ticks[1]! - ticks[0]!) / unit : 1
  let decimals = 0
  while (decimals < 2 && Math.abs(step * 10 ** decimals - Math.round(step * 10 ** decimals)) > 1e-6) decimals++
  const fmt = new Intl.NumberFormat("zh-TW", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return ticks.map((v) => `${fmt.format(v / unit)}${word}`)
}

/**
 * 橫軸的日期刻度：三個月以上放在每個月第一個交易日（「2026/06」），更短的只標頭尾（「11/12」「11/16」）。
 * 回傳的是序列裡的位置。
 */
export function dateAxis(days: readonly string[]): { ticks: number[]; format: (t: string) => string; long: boolean } {
  const first = days[0]
  const last = days.at(-1)
  const long = !!first && !!last && Date.parse(last) - Date.parse(first) >= 90 * 86_400_000
  if (!long) {
    const ticks = days.length > 1 ? [0, days.length - 1] : days.length ? [0] : []
    return { ticks, long, format: (t) => `${Number(t.slice(5, 7))}/${Number(t.slice(8, 10))}` }
  }
  const ticks = days.flatMap((t, i) => (i > 0 && t.slice(0, 7) !== days[i - 1]!.slice(0, 7) ? [i] : []))
  return { ticks, long, format: (t) => t.slice(0, 7).replace("-", "/") }
}

/** 區間跨了年（或一年以上）：讀數裡的日期要寫年份 */
export function needsYear(days: readonly string[]): boolean {
  const first = days[0]
  const last = days.at(-1)
  if (!first || !last) return false
  return Date.parse(last) - Date.parse(first) >= 365 * 86_400_000 || first.slice(0, 4) !== last.slice(0, 4)
}
