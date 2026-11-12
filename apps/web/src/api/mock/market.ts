import type { Candle, DividendRecord, MonthlyRevenue, ValuationPoint } from "../types"
import { NEGATIVE_EPS_WINDOWS, type MockInstrumentSpec } from "./instruments"

/** 示範資料的「今天」（台北時區）。固定日期讓截圖與測試穩定。 */
export const MOCK_TODAY = "2026-11-12"
export const MOCK_AS_OF = `${MOCK_TODAY}T13:30:00+08:00`

// ── 日期工具（以 UTC 日期字串運算，避免時區偏移） ─────────────
export function parseDay(d: string): Date {
  return new Date(`${d}T00:00:00Z`)
}
export function fmtDay(d: Date): string {
  return d.toISOString().slice(0, 10)
}
export function addDays(d: string, n: number): string {
  const x = parseDay(d)
  x.setUTCDate(x.getUTCDate() + n)
  return fmtDay(x)
}
function isWeekday(d: Date) {
  const w = d.getUTCDay()
  return w !== 0 && w !== 6
}

/** 今天往回 n 個交易日（只排除週末；示範資料不處理國定假日） */
export function tradingDays(count: number, end = MOCK_TODAY): string[] {
  const out: string[] = []
  const d = parseDay(end)
  while (out.length < count) {
    if (isWeekday(d)) out.push(fmtDay(d))
    d.setUTCDate(d.getUTCDate() - 1)
  }
  return out.reverse()
}

// ── 可重現的亂數 ──────────────────────────────────────────
function hashString(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}
export function rng(seed: string) {
  let a = hashString(seed)
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
function normal(r: () => number) {
  const u = Math.max(r(), 1e-9)
  const v = r()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

const round = (n: number, d = 2) => Math.round(n * 10 ** d) / 10 ** d

/** 台股升降單位（tick） */
export function twTick(price: number): number {
  if (price < 10) return 0.01
  if (price < 50) return 0.05
  if (price < 100) return 0.1
  if (price < 500) return 0.5
  if (price < 1000) return 1
  return 5
}
function snap(price: number, spec: MockInstrumentSpec) {
  if (spec.market === "US") return round(price, 2)
  const t = twTick(price)
  return round(Math.round(price / t) * t, 2)
}

// ── 日線（約 6 年） ───────────────────────────────────────
export const HISTORY_DAYS = 1560
const historyCache = new Map<string, Candle[]>()

export function dailyCandles(spec: MockInstrumentSpec): Candle[] {
  const cached = historyCache.get(spec.symbol)
  if (cached) return cached
  const days = tradingDays(HISTORY_DAYS)
  const r = rng(`hist:${spec.symbol}`)
  const dailyVol = spec.vol / Math.sqrt(252)
  const dailyDrift = spec.drift / 252
  const closes = new Array<number>(days.length)
  closes[days.length - 1] = spec.price
  closes[days.length - 2] = spec.prev_close
  for (let i = days.length - 3; i >= 0; i--) {
    const ret = dailyDrift + dailyVol * normal(r)
    closes[i] = Math.max(closes[i + 1]! / (1 + ret), spec.price * 0.05)
  }
  const candles: Candle[] = days.map((t, i) => {
    const c = snap(closes[i]!, spec)
    const prev = i > 0 ? closes[i - 1]! : c
    const o = snap(prev * (1 + dailyVol * 0.35 * normal(r)), spec)
    const hi = snap(Math.max(o, c) * (1 + Math.abs(dailyVol * 0.5 * normal(r))), spec)
    const lo = snap(Math.min(o, c) * (1 - Math.abs(dailyVol * 0.5 * normal(r))), spec)
    const v = Math.round(spec.avg_volume * Math.exp(0.35 * normal(r)) / 1000) * 1000
    return { t, o, h: hi, l: lo, c, v }
  })
  // 最後一根與示範報價一致
  const last = candles[candles.length - 1]!
  last.c = spec.price
  last.o = snap(spec.prev_close * 1.002, spec)
  last.h = Math.max(last.h, last.c, last.o)
  last.l = Math.min(last.l, last.c, last.o)
  historyCache.set(spec.symbol, candles)
  return candles
}

/** 某日（或之前最近一個交易日）的收盤價 */
export function closeOn(spec: MockInstrumentSpec, day: string): number {
  const candles = dailyCandles(spec)
  let lo = 0
  let hi = candles.length - 1
  if (day < candles[0]!.t) return candles[0]!.c
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (candles[mid]!.t <= day) lo = mid
    else hi = mid - 1
  }
  return candles[lo]!.c
}

/** 美元兌台幣（示範） */
export function usdTwd(day: string): number {
  const t = (parseDay(day).getTime() - parseDay("2021-01-01").getTime()) / 86400000
  return round(31.2 + 1.1 * Math.sin(t / 210) + 0.4 * Math.sin(t / 47), 3)
}
export const FX_NOW = 31.85

// ── 估值 ─────────────────────────────────────────────────
/** 季初收盤價（估值基準每季更新一次） */
function quarterStartClose(spec: MockInstrumentSpec, day: string): number {
  const m = Number(day.slice(5, 7))
  const qStart = `${day.slice(0, 4)}-${String(Math.floor((m - 1) / 3) * 3 + 1).padStart(2, "0")}-01`
  return closeOn(spec, qStart)
}

/**
 * 示範 EPS／每股淨值：讓「倍數」在區間內緩慢擺盪（約 3 年一個循環），
 * 再整體縮放，使最新一季剛好等於 eps_now／bvps_now。河流圖因此看起來像真的。
 */
function ratioWave(spec: MockInstrumentSpec, day: string, mid: number, amp: number): number {
  const t = (parseDay(day).getTime() - parseDay("2020-01-01").getTime()) / (365.25 * 86400000)
  const phase = (hashPhase(spec.symbol) % 628) / 100
  return mid * (1 + amp * Math.sin((2 * Math.PI * t) / 3.1 + phase))
}
function hashPhase(s: string) {
  let h = 7
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}
function quarterKey(day: string) {
  const m = Number(day.slice(5, 7))
  return `${day.slice(0, 4)}-${String(Math.floor((m - 1) / 3) * 3 + 1).padStart(2, "0")}-15`
}
function rawBase(spec: MockInstrumentSpec, day: string, multiples: number[]) {
  const mid = (multiples[0]! + multiples[multiples.length - 1]!) / 2
  const q = quarterKey(day)
  return quarterStartClose(spec, day) / ratioWave(spec, q, mid, 0.22)
}
function epsAt(spec: MockInstrumentSpec, day: string): number | null {
  if (spec.eps_now === undefined || !spec.per_multiples) return null
  for (const w of NEGATIVE_EPS_WINDOWS[spec.symbol] ?? []) {
    if (day >= w.from && day <= w.to) return w.eps
  }
  const scale = spec.eps_now / rawBase(spec, MOCK_TODAY, spec.per_multiples)
  return round(rawBase(spec, day, spec.per_multiples) * scale, 2)
}
function bvpsAt(spec: MockInstrumentSpec, day: string): number | null {
  if (spec.bvps_now === undefined || !spec.pbr_multiples) return null
  const scale = spec.bvps_now / rawBase(spec, MOCK_TODAY, spec.pbr_multiples)
  // 淨值變動比 EPS 平緩：與線性成長混合
  const years = (parseDay(MOCK_TODAY).getTime() - parseDay(day).getTime()) / (365.25 * 86400000)
  const trend = spec.bvps_now / Math.pow(1.1, Math.floor(years * 4) / 4)
  return round(0.5 * rawBase(spec, day, spec.pbr_multiples) * scale + 0.5 * trend, 2)
}

export function valuationSeries(spec: MockInstrumentSpec, years: number): ValuationPoint[] {
  const candles = dailyCandles(spec)
  const from = addDays(MOCK_TODAY, -Math.round(years * 365.25))
  const pts: ValuationPoint[] = []
  const divs = dividendRecords(spec)
  const exDates = divs.map((d) => d.ex_dividend_date).filter((d): d is string => !!d).sort()
  const firstEx = exDates[0] ?? null
  const inRange = candles.filter((c) => c.t >= from)
  inRange.forEach((c, i) => {
    // 每週一個點，最後一天一定要有
    if (i % 5 !== 0 && i !== inRange.length - 1) return
    const eps = epsAt(spec, c.t)
    const bvps = bvpsAt(spec, c.t)
    const trailing = divs
      .filter((d) => d.ex_dividend_date && d.ex_dividend_date <= c.t && d.ex_dividend_date > addDays(c.t, -365))
      .reduce((s, d) => s + d.cash_dividend, 0)
    // 示範股利資料只涵蓋近幾年：涵蓋範圍以前的殖利率視為「無資料」，不是 0
    const covered = firstEx !== null && c.t >= addDays(firstEx, 365)
    pts.push({
      t: c.t,
      close: c.c,
      eps_ttm: eps,
      bvps,
      per: eps !== null && eps > 0 ? round(c.c / eps, 2) : null,
      pbr: bvps ? round(c.c / bvps, 2) : null,
      dividend_yield: covered ? round(trailing / c.c, 4) : null,
    })
  })
  return pts
}

// ── 月營收（千元） ────────────────────────────────────────
const SEASONALITY = [0.92, 0.84, 1.0, 0.96, 0.98, 1.0, 1.02, 1.04, 1.03, 1.06, 1.05, 1.1]

export function monthlyRevenue(spec: MockInstrumentSpec): MonthlyRevenue[] {
  if (spec.revenue_base === undefined || spec.market === "US") return []
  const g = spec.revenue_growth ?? 0
  const r = rng(`rev:${spec.symbol}`)
  // 2022-10 起產生，輸出 2023-10 起（shioaji-data 的月營收起點）
  const months: string[] = []
  for (let y = 2022; y <= 2026; y++) {
    for (let m = 1; m <= 12; m++) {
      const p = `${y}-${String(m).padStart(2, "0")}`
      if (p >= "2022-10" && p <= "2026-10") months.push(p)
    }
  }
  const lastIdx = months.length - 1
  const values = months.map((p, i) => {
    const monthsBack = lastIdx - i
    const m = Number(p.slice(5, 7))
    const base = spec.revenue_base! / Math.pow(1 + g, monthsBack / 12)
    const season = SEASONALITY[m - 1]! / SEASONALITY[9]!
    return Math.round(base * season * (1 + (r() - 0.5) * 0.08))
  })
  const out: MonthlyRevenue[] = []
  months.forEach((p, i) => {
    if (p < "2023-10") return
    const v = values[i]!
    const prevYear = values[i - 12]
    const prevMonth = values[i - 1]
    const year = p.slice(0, 4)
    const ytd = months.reduce((s, q, j) => (q.startsWith(year) && j <= i ? s + values[j]! : s), 0)
    const ytdPrev = months.reduce(
      (s, q, j) => (q.startsWith(String(Number(year) - 1)) && Number(q.slice(5)) <= Number(p.slice(5)) ? s + values[j]! : s),
      0,
    )
    out.push({
      period: p,
      revenue: v,
      yoy_pct: prevYear ? round(v / prevYear - 1, 4) : null,
      mom_pct: prevMonth ? round(v / prevMonth - 1, 4) : null,
      ytd,
      ytd_yoy_pct: ytdPrev ? round(ytd / ytdPrev - 1, 4) : null,
    })
  })
  return out
}

// ── 股利（由新到舊） ──────────────────────────────────────
type Div = [period: string, cash: number, stock: number, ex: string | null, pay: string | null]

const DIVIDENDS: Record<string, Div[]> = {
  "2330.TW": [
    ["2026Q2", 5.0, 0, "2026-12-11", "2027-01-08"],
    ["2026Q1", 5.0, 0, "2026-09-16", "2026-10-09"],
    ["2025Q4", 4.5, 0, "2026-06-11", "2026-07-09"],
    ["2025Q3", 4.5, 0, "2026-03-17", "2026-04-09"],
    ["2025Q2", 4.0, 0, "2025-12-11", "2026-01-08"],
    ["2025Q1", 4.0, 0, "2025-09-16", "2025-10-09"],
    ["2024Q4", 3.5, 0, "2025-06-12", "2025-07-10"],
    ["2024Q3", 3.5, 0, "2025-03-18", "2025-04-10"],
    ["2024Q2", 4.0, 0, "2024-12-12", "2025-01-09"],
    ["2024Q1", 3.5, 0, "2024-09-12", "2024-10-09"],
    ["2023Q4", 3.5, 0, "2024-06-13", "2024-07-11"],
    ["2023Q3", 3.5, 0, "2024-03-14", "2024-04-11"],
    ["2023Q2", 3.0, 0, "2023-12-14", "2024-01-11"],
    ["2023Q1", 3.0, 0, "2023-09-14", "2023-10-12"],
  ],
  "0050.TW": [
    ["2026H1", 0.95, 0, "2026-07-21", "2026-08-13"],
    ["2025H2", 0.82, 0, "2026-01-21", "2026-02-12"],
    ["2025H1", 0.36, 0, "2025-07-18", "2025-08-12"],
    ["2024H2", 0.76, 0, "2025-01-17", "2025-02-12"],
    ["2024H1", 0.43, 0, "2024-07-17", "2024-08-09"],
  ],
  "00878.TW": [
    ["2026Q3", 0.55, 0, "2026-11-18", "2026-12-15"],
    ["2026Q2", 0.5, 0, "2026-08-18", "2026-09-12"],
    ["2026Q1", 0.47, 0, "2026-05-19", "2026-06-13"],
    ["2025Q4", 0.47, 0, "2026-02-23", "2026-03-18"],
    ["2025Q3", 0.4, 0, "2025-11-18", "2025-12-15"],
    ["2025Q2", 0.5, 0, "2025-08-18", "2025-09-12"],
    ["2025Q1", 0.47, 0, "2025-05-19", "2025-06-13"],
    ["2024Q4", 0.5, 0, "2025-02-18", "2025-03-14"],
    ["2024Q3", 0.55, 0, "2024-11-18", "2024-12-13"],
    ["2024Q2", 0.55, 0, "2024-08-16", "2024-09-11"],
    ["2024Q1", 0.51, 0, "2024-05-17", "2024-06-13"],
  ],
  "2454.TW": [
    ["2026H1", 25.0, 0, "2026-10-08", "2026-10-30"],
    ["2025H2", 29.0, 0, "2026-04-08", "2026-04-30"],
    ["2025H1", 25.0, 0, "2025-10-08", "2025-10-30"],
    ["2024H2", 31.0, 0, "2025-04-08", "2025-04-30"],
  ],
  "2317.TW": [
    ["2025", 5.8, 0, "2026-07-02", "2026-08-05"],
    ["2024", 5.4, 0, "2025-07-02", "2025-08-05"],
    ["2023", 5.3, 0, "2024-07-02", "2024-08-05"],
  ],
  "6488.TWO": [
    ["2026H1", 4.0, 0, "2026-09-22", "2026-10-16"],
    ["2025H2", 4.0, 0, "2026-03-24", "2026-04-17"],
    ["2025H1", 6.0, 0, "2025-09-23", "2025-10-17"],
    ["2024H2", 8.0, 0, "2025-03-25", "2025-04-18"],
  ],
  AAPL: [
    ["2026Q4", 0.27, 0, "2026-11-10", "2026-11-13"],
    ["2026Q3", 0.27, 0, "2026-08-11", "2026-08-14"],
    ["2026Q2", 0.26, 0, "2026-05-11", "2026-05-14"],
    ["2026Q1", 0.26, 0, "2026-02-09", "2026-02-12"],
  ],
  NVDA: [["2026Q3", 0.01, 0, "2026-09-11", "2026-10-02"]],
  VOO: [
    ["2026Q4", 1.85, 0, "2026-12-22", "2026-12-26"],
    ["2026Q3", 1.74, 0, "2026-09-28", "2026-10-01"],
    ["2026Q2", 1.81, 0, "2026-06-29", "2026-07-02"],
    ["2026Q1", 1.7, 0, "2026-03-27", "2026-03-31"],
  ],
  "2409.TW": [
    ["2025", 0.3, 0, "2026-07-15", "2026-08-08"],
    ["2023", 0, 0, null, null],
    ["2022", 0.45, 0, "2023-07-13", "2023-08-09"],
  ],
  "0056.TW": [["2026Q3", 0.866, 0, "2026-11-20", "2026-12-15"]],
  "2412.TW": [["2025", 4.98, 0, "2026-07-16", "2026-08-12"]],
  "2603.TW": [["2025", 10.0, 0, "2026-06-25", "2026-07-20"]],
  "3008.TW": [["2025", 70.0, 0, "2026-06-30", "2026-07-25"]],
  "00919.TW": [["2026Q3", 0.54, 0, "2026-12-16", "2027-01-14"]],
}

export function dividendRecords(spec: MockInstrumentSpec): DividendRecord[] {
  return (DIVIDENDS[spec.symbol] ?? []).map(([period, cash, stock, ex, pay]) => ({
    year: Number(period.slice(0, 4)),
    period,
    cash_dividend: cash,
    stock_dividend: stock,
    ex_dividend_date: ex,
    payment_date: pay,
    is_demo: true,
  }))
}
