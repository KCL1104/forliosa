// @vitest-environment node
import { describe, expect, it } from "vitest"
import { monthlyBreakdown, type MonthPoint, type Span } from "../asset-composition"
import { estimateBuyDate } from "../buy-date"

/**
 * 每月拆解的前後端對答案（資產組成原型）：後端 `services/composition.py` 的 `monthly_breakdown` 是這個函式一行一行搬過去的，
 * 兩邊都拿同一份檢查進去的 JSON（`apps/api/tests/fixtures/monthly_breakdown_parity.json`）比：
 * - 這裡：同樣的輸入，`monthlyBreakdown` 現在算的要和檔案裡的 `expected` 一樣（前端改了算法就會失敗）；
 * - 後端：`tests/test_composition.py` 用 Python 算同樣的輸入，要和 `expected` 一樣。
 * 改了算法要重新產生（兩邊再一起跑）：`UPDATE_PARITY=1 pnpm vitest run src/lib/__tests__/monthly-breakdown-parity.test.ts`
 */

const FIXTURE = new URL("../../../../api/tests/fixtures/monthly_breakdown_parity.json", import.meta.url)
const nodeFs = "node:fs"
const fs = (await import(/* @vite-ignore */ nodeFs)) as {
  readFileSync(p: URL, enc: "utf8"): string
  writeFileSync(p: URL, s: string): void
}
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {}

/** 固定的亂數（mulberry32）：每次產生一樣的輸入 */
function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const r2 = (n: number) => Math.round(n * 100) / 100
const r6 = (n: number) => Math.round(n * 1e6) / 1e6

/** 平日（不含週末）的日期，從 `from` 起 `n` 天 */
function weekdays(from: string, n: number): string[] {
  const out: string[] = []
  const d = new Date(`${from}T00:00:00Z`)
  while (out.length < n) {
    const w = d.getUTCDay()
    if (w !== 0 && w !== 6) out.push(d.toISOString().slice(0, 10))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

/** 一段序列：總資產隨機走、買賣讓本金跳、時間加權與基準指數累乘；`benchNullFirst` 天基準沒有資料 */
function series(seed: number, from: string, n: number, opts: { benchNullFirst?: number; sellAll?: number } = {}): MonthPoint[] {
  const next = rng(seed)
  let mv = 0
  let ni = 0
  let twr = 1
  let bench = 1
  return weekdays(from, n).map((t, i) => {
    const r = (next() - 0.48) * 0.04
    const prev = mv
    mv = mv * (1 + r)
    twr = prev > 0 ? twr * (1 + r) : twr
    bench *= 1 + (next() - 0.48) * 0.03
    const flow = i === 0 ? 1_000_000 : next() < 0.06 ? Math.round((next() - 0.3) * 400_000) : 0
    const sell = opts.sellAll === i ? -mv : 0
    const f = flow + sell
    if (f < 0 && -f > mv) return { t, market_value: r2(mv), net_invested: r2(ni), twr_index: r6(twr), benchmark_index: i < (opts.benchNullFirst ?? 0) ? null : r6(bench) }
    mv += f
    ni += sell ? sell * 1.4 : f
    return { t, market_value: r2(mv), net_invested: r2(ni), twr_index: r6(twr), benchmark_index: i < (opts.benchNullFirst ?? 0) ? null : r6(bench) }
  })
}

interface Case {
  name: string
  points: MonthPoint[]
  base: MonthPoint | null
  /** 估計的那幾段（每一次匯入一段） */
  estimated: Span[]
  importDays: string[]
}

function cases(): Case[] {
  const all = series(1, "2024-07-29", 320, { benchNullFirst: 12 })
  const year = series(2, "2025-03-03", 300)
  const mtd = series(3, "2026-10-30", 10)
  const cash = series(4, "2025-01-02", 200, { sellAll: 150 })
  const twice = series(5, "2024-01-02", 330)
  const late = series(6, "2025-01-02", 120, { benchNullFirst: 30 })
  return [
    // 「全部」：從第一筆開始（沒有基準收盤，當成 0），估計的那一段切掉前面好幾個月和一個月的一部分，匯入那天在週末（算到下一個收盤日）
    { name: "all_from_inception", points: all, base: null, estimated: [{ from: all[0]!.t, until: all[70]!.t }], importDays: ["2025-02-15", all[200]!.t] },
    // 一年：基準是區間前一個收盤（指數 1），估計的那一段只碰到開頭，匯入那天在基準以前（不算）
    {
      name: "one_year_with_prev",
      points: year.slice(40),
      base: { ...year[39]!, twr_index: 1, benchmark_index: 1 },
      estimated: [{ from: "2024-12-01", until: year[45]!.t }],
      importDays: [year[20]!.t, year[39]!.t, year[150]!.t],
    },
    // 本月（MTD）：基準收盤是序列的第一點
    { name: "based_mtd", points: mtd.slice(1), base: mtd[0]!, estimated: [], importDays: [] },
    // 整段都是估計的：沒有可以比的月份
    { name: "all_estimated", points: year.slice(0, 60), base: null, estimated: [{ from: year[0]!.t, until: year[59]!.t }], importDays: [] },
    // 賣光以後本金是負的（賣出收到的比買的多）
    { name: "cash_out", points: cash, base: null, estimated: [], importDays: [] },
    // 只有一天
    { name: "one_point", points: year.slice(10, 11), base: year[9]!, estimated: [], importDays: [] },
    // 分兩次匯入：兩段估計在歷史的中間——前面有真實的月份（估計那一段以前），兩段之間的月份照樣列；
    // 第二段整段在同一個月的月中（那個月前後兩部分各一列）
    {
      name: "two_imports_middle",
      points: twice,
      base: null,
      estimated: [
        { from: twice[60]!.t, until: twice[120]!.t },
        { from: twice[250]!.t, until: twice[255]!.t },
      ],
      importDays: [],
    },
    // 基準前 30 天沒有資料：第二個月的基準收盤（1 月最後一天）基準是 null，那個月和基準比不了
    { name: "bench_null_base", points: late, base: null, estimated: [], importDays: [] },
  ]
}

/** 估計買入日（`lib/buy-date.ts`）的對答案：後端 `domain/buy_date.py` 用同一份輸入（`buy_date_parity.json`）比 */
const BUY_DATE_FIXTURE = new URL("../../../../api/tests/fixtures/buy_date_parity.json", import.meta.url)

function buyDateCases() {
  const next = rng(7)
  const series: { t: string; h: number; l: number }[][] = []
  const cases: { series: number; cost: number; until: string; from?: string; expected: string | null }[] = []
  for (let n = 0; n < 20; n++) {
    const days = weekdays("2024-01-01", 90)
    let px = 100 + next() * 50
    // 有些序列跳空很多（缺口裡的成本），有些波動很小（常常找不到）
    const gappy = n % 3 === 0
    const candles = days.map((t) => {
      px *= 1 + (next() - 0.5) * (gappy ? 0.12 : 0.03)
      const spread = px * (gappy ? 0.004 : 0.01) * next()
      return { t, l: r2(px - spread), h: r2(px + spread) }
    })
    series.push(candles)
    for (let k = 0; k < 8; k++) {
      // 成本在這段股價附近（有時在範圍外：找不到）
      const cost = r2(candles[Math.floor(next() * candles.length)]!.h * (0.85 + next() * 0.3))
      const until = days[Math.floor(next() * days.length)]!
      cases.push({ series: n, cost, until, expected: estimateBuyDate(candles, cost, until) })
    }
  }
  // 加的情況（原本的 160 個不變）：
  const more = rng(11)
  series.forEach((candles, n) => {
    const days = candles.map((c) => c.t)
    // 匯入那天比第一根 K 線還早：找不到
    cases.push({ series: n, cost: candles[0]!.h, until: "2023-12-29", expected: estimateBuyDate(candles, candles[0]!.h, "2023-12-29") })
    // 最早只找到分割、減資、配股那天（`from`）：成本是那天以前經過的價格
    const from = days[45]!
    const cost = r2(candles[Math.floor(more() * 45)]!.h * (0.97 + more() * 0.06))
    cases.push({ series: n, cost, until: days[89]!, from, expected: estimateBuyDate(candles, cost, days[89]!, from) })
    // 那天和前一天之間的缺口不算經過（那天的第一根沒有前一天）
    for (let i = 1; i < candles.length; i++) {
      const prev = candles[i - 1]!
      const c = candles[i]!
      if (prev.h < c.l || prev.l > c.h) {
        const gap = r2(prev.h < c.l ? (prev.h + c.l) / 2 : (prev.l + c.h) / 2)
        cases.push({ series: n, cost: gap, until: c.t, from: c.t, expected: estimateBuyDate(candles, gap, c.t, c.t) })
        break
      }
    }
  })
  return { series, cases }
}

describe("估計買入日：前後端同一份答案", () => {
  it("estimateBuyDate 的結果和檢查進去的 fixture 一樣（後端拿同一份比）", () => {
    const computed = buyDateCases()
    if (env.UPDATE_PARITY === "1") {
      const doc = { note: "Generated by apps/web/src/lib/__tests__/monthly-breakdown-parity.test.ts from lib/buy-date.ts estimateBuyDate (regenerate as monthly_breakdown_parity.json).", ...computed }
      fs.writeFileSync(BUY_DATE_FIXTURE, `${JSON.stringify(doc)}\n`)
    }
    const fixture = JSON.parse(fs.readFileSync(BUY_DATE_FIXTURE, "utf8")) as typeof computed
    expect({ series: fixture.series, cases: fixture.cases }).toEqual(computed)
    expect(computed.cases.filter((c) => c.expected === null).length).toBeGreaterThan(10)
    expect(computed.cases.filter((c) => c.expected !== null).length).toBeGreaterThan(40)
    // 加的情況真的走到：匯入那天在第一根以前、`from` 改變了答案、缺口在 `from` 那天不算
    const limited = computed.cases.filter((c) => c.from)
    expect(computed.cases.filter((c) => c.until === "2023-12-29").every((c) => c.expected === null)).toBe(true)
    expect(limited.some((c) => c.expected !== estimateBuyDate(computed.series[c.series]!, c.cost, c.until))).toBe(true)
    expect(limited.filter((c) => c.from === c.until).length).toBeGreaterThan(3)
    expect(limited.filter((c) => c.from === c.until).every((c) => c.expected === null)).toBe(true)
  })
})

describe("每月拆解：前後端同一份答案", () => {
  it("monthlyBreakdown 的結果和檢查進去的 fixture 一樣（後端拿同一份比）", () => {
    const computed = cases().map((c) => ({
      ...c,
      expected: monthlyBreakdown(c.points, { base: c.base, estimated: c.estimated, importDays: c.importDays }),
    }))
    if (env.UPDATE_PARITY === "1") {
      const doc = {
        note: "Generated by apps/web/src/lib/__tests__/monthly-breakdown-parity.test.ts from lib/asset-composition.ts monthlyBreakdown. Regenerate: UPDATE_PARITY=1 pnpm vitest run src/lib/__tests__/monthly-breakdown-parity.test.ts (in apps/web), then run apps/api tests/test_composition.py.",
        cases: computed,
      }
      fs.writeFileSync(FIXTURE, `${JSON.stringify(doc)}\n`)
    }
    const fixture = JSON.parse(fs.readFileSync(FIXTURE, "utf8")) as { cases: typeof computed }
    expect(fixture.cases).toEqual(computed)
    // 有內容：每一種情況都真的走到（估計略過、匯入那天略過、和基準比不了的第一個月）
    const byName = Object.fromEntries(computed.map((c) => [c.name, c.expected]))
    expect(byName.all_from_inception!.skipped).toBeGreaterThan(0)
    expect(byName.all_from_inception!.skippedImport).toBe(2)
    expect(byName.one_year_with_prev!.skippedImport).toBe(1)
    expect(byName.all_estimated!.months).toEqual([])
    expect(byName.cash_out!.months.some((m) => m.flows < 0)).toBe(true)
    // 分兩次匯入：第一段以前的月份、兩段之間的月份都列；整個月在估計裡的不列
    const twice = computed.find((c) => c.name === "two_imports_middle")!
    const listed = new Set(twice.expected.months.map((m) => m.month))
    const firstSpanStart = twice.estimated[0]!.from.slice(0, 7)
    expect([...listed].some((m) => m < firstSpanStart)).toBe(true)
    const between = twice.points.filter((p) => p.t > twice.estimated[0]!.until && p.t < twice.estimated[1]!.from).map((p) => p.t.slice(0, 7))
    for (const m of new Set(between)) expect(listed.has(m)).toBe(true)
    expect(twice.expected.skipped).toBeGreaterThan(0)
    // 基準是 null 的基準收盤：那個月列出來，和基準的差距是 null
    const late = byName.bench_null_base!
    expect(late.months.length).toBeGreaterThan(3)
    expect(late.months.at(-2)!.benchmark_twr).toBeNull()
    expect(late.months.at(-3)!.benchmark_twr).not.toBeNull()
  })
})
