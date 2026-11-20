import { describe, expect, it } from "vitest"
import type { PerformancePoint } from "@/api/types"
import { dividendsByDay, estimatedRuns, fromZero, inSpan, inSpans, monthlyBreakdown, profitOf, snapDividends, spanIndexes } from "../asset-composition"
import { trendWindow } from "../trend-range"

/** 一天：總資產、投入本金、時間加權指數、基準指數 */
const p = (t: string, market_value: number, net_invested: number, twr_index = 1, benchmark_index: number | null = 1): PerformancePoint => ({ t, market_value, net_invested, twr_index, benchmark_index })

describe("資產組成：投入本金＋累積損益＝總資產", () => {
  it("累積損益是總資產減投入本金（不含股利）", () => {
    expect(profitOf(p("2026-01-02", 1_200_000, 1_000_000))).toBe(200_000)
    expect(profitOf(p("2026-01-02", 900_000, 1_000_000))).toBe(-100_000)
  })

  it("一天領好幾筆股利加起來", () => {
    expect(dividendsByDay([{ t: "2026-09-16", amount: 7_500 }, { t: "2026-09-16", amount: 500 }, { t: "2026-10-08", amount: 5_000 }])).toEqual(
      new Map([["2026-09-16", 8_000], ["2026-10-08", 5_000]]),
    )
  })
})

describe("估計的那一段", () => {
  it("一天在不在裡面（頭尾都含）；和畫出來的這幾天重疊的位置", () => {
    const span = { from: "2026-01-05", until: "2026-01-07" }
    expect(inSpan("2026-01-05", span)).toBe(true)
    expect(inSpan("2026-01-07", span)).toBe(true)
    expect(inSpan("2026-01-08", span)).toBe(false)
    expect(inSpan("2026-01-06", null)).toBe(false)
    const days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    expect(spanIndexes(days, [span])).toEqual([{ first: 1, last: 3 }])
    expect(spanIndexes(days, [{ from: "2025-01-01", until: "2025-12-31" }])).toEqual([])
    expect(spanIndexes(days, [])).toEqual([])
    expect(spanIndexes(days, null)).toEqual([])
    // 整段都是估計的
    expect(spanIndexes(days, [{ from: "2025-01-01", until: "2026-12-31" }])).toEqual([{ first: 0, last: 4 }])
  })

  it("分好幾次匯入：每一次一段，中間真實的日子不算估計；畫出來時連在一起的兩段算一段", () => {
    const days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    const spans = [{ from: "2025-12-01", until: "2026-01-02" }, { from: "2026-01-07", until: "2026-01-08" }]
    expect(inSpans("2026-01-05", spans)).toBe(false)
    expect(inSpans("2026-01-07", spans)).toBe(true)
    expect(inSpans("2026-01-07", null)).toBe(false)
    expect(spanIndexes(days, spans)).toEqual([{ first: 0, last: 0 }, { first: 3, last: 4 }])
    // 兩段之間沒有收盤（週末）：畫出來是一段
    expect(spanIndexes(days, [{ from: "2026-01-02", until: "2026-01-03" }, { from: "2026-01-04", until: "2026-01-05" }])).toEqual([{ first: 0, last: 1 }])
  })

  it("總資產線的細線與粗線：每一段估計從前一天畫到後一天，粗線在交界接起來", () => {
    expect(estimatedRuns(6, [])).toEqual({ thin: [], thick: [[0, 1, 2, 3, 4, 5]] })
    expect(estimatedRuns(8, [{ first: 0, last: 1 }, { first: 4, last: 5 }])).toEqual({
      thin: [[0, 1, 2], [3, 4, 5, 6]],
      thick: [[2, 3], [6, 7]],
    })
    // 只剩一點的粗線不畫
    expect(estimatedRuns(5, [{ first: 1, last: 3 }])).toEqual({ thin: [[0, 1, 2, 3, 4]], thick: [] })
  })
})

describe("每個月的拆解（每月報酬率）", () => {
  // 9/30 是基準收盤；10 月整個月、11 月到 11/12
  const series = [
    p("2026-10-01", 1_010_000, 1_000_000, 1.01, 1.02),
    p("2026-10-30", 1_100_000, 1_050_000, 1.05, 1.03),
    p("2026-11-02", 1_090_000, 1_050_000, 1.04, 1.02),
    p("2026-11-12", 1_200_000, 1_100_000, 1.0920, 1.0815),
  ]
  const base = p("2026-09-30", 1_000_000, 1_000_000, 1, 1)

  it("一個月一列、新的在上面：加碼或拿回、損益（不含股利）、報酬率、基準的報酬率；整個月才是 whole", () => {
    const { months, skipped } = monthlyBreakdown(series, { base })
    expect(skipped).toBe(0)
    expect(months.map((m) => m.month)).toEqual(["2026-11", "2026-10"])
    const [nov, oct] = months
    expect(oct).toMatchObject({ from: "2026-10-01", to: "2026-10-30", whole: true, flows: 50_000, pnl: 50_000 })
    expect(oct!.twr).toBeCloseTo(0.05, 6)
    expect(oct!.benchmark_twr).toBeCloseTo(0.03, 6)
    // 11 月還沒過完：不是整個月
    expect(nov).toMatchObject({ from: "2026-11-02", to: "2026-11-12", whole: false, flows: 50_000, pnl: 50_000 })
    expect(nov!.twr).toBeCloseTo(1.092 / 1.05 - 1, 6)
  })

  it("從第一筆開始（沒有基準收盤）：當成從 0 開始；第一個月不是整個月", () => {
    const { months } = monthlyBreakdown([p("2026-10-15", 101_000, 100_000, 1.01, 1), p("2026-10-30", 103_000, 100_000, 1.03, 1.01)], { base: null })
    expect(months).toHaveLength(1)
    expect(months[0]).toMatchObject({ month: "2026-10", flows: 100_000, pnl: 3_000, whole: false })
    expect(months[0]!.twr).toBeCloseTo(0.03, 6)
  })

  it("估計的那一段不列：整個月都在裡面的略過（算進 skipped），一部分在裡面的只算真實紀錄那幾天", () => {
    const { months, skipped } = monthlyBreakdown(series, { base, estimated: [{ from: "2026-09-01", until: "2026-11-02" }] })
    expect(skipped).toBe(1)
    expect(months.map((m) => m.month)).toEqual(["2026-11"])
    // 11 月只算 11/2（估計）之後：基準是 11/2
    expect(months[0]).toMatchObject({ from: "2026-11-12", to: "2026-11-12", whole: false, flows: 50_000, pnl: 60_000 })
    expect(months[0]!.twr).toBeCloseTo(1.092 / 1.04 - 1, 6)
  })

  it("全部都是估計的：沒有可以列的月份", () => {
    const { months, skipped } = monthlyBreakdown(series, { base, estimated: [{ from: "2026-01-01", until: "2026-12-31" }] })
    expect(months).toEqual([])
    expect(skipped).toBe(2)
  })

  it("基準沒有資料：和基準的差距是 null", () => {
    const { months } = monthlyBreakdown([p("2026-10-01", 1, 1, 1.01, null)], { base: p("2026-09-30", 1, 1, 1, null) })
    expect(months[0]!.benchmark_twr).toBeNull()
  })
})

describe("審查後的修正", () => {
  it("#5 區間比資料長：從 0 起算（和 trendWindow 的報酬分母 1 同一個規則），和「全部」一樣", () => {
    const s = [p("2026-11-10", 100_000, 97_000, 1.03), p("2026-11-11", 101_000, 97_000, 1.04), p("2026-11-12", 103_000, 100_000, 1.06)]
    const win = trendWindow(s, "1Y")
    expect(win.exceeds).toBe(true)
    expect(win.base).toBe(1)
    expect(fromZero(win, "1Y")).toBe(true)
    // 資料夠長的區間照舊從基準收盤算
    expect(fromZero({ exceeds: false }, "1M")).toBe(false)
  })

  it("#6 從第一筆開始的第一個月：自己的報酬含第一天、基準沒有第一天以前的收盤——不比，差距是 null", () => {
    const { months } = monthlyBreakdown([p("2026-10-15", 105_000, 100_000, 1.05, 1), p("2026-10-30", 106_000, 100_000, 1.06, 1.01), p("2026-11-02", 107_000, 100_000, 1.07, 1.02)], { base: null })
    const oct = months.find((m) => m.month === "2026-10")!
    expect(oct.twr).toBeCloseTo(0.06, 6)
    expect(oct.benchmark_twr).toBeNull()
    // 之後的月份兩邊都從前一個收盤算，照常比
    expect(months.find((m) => m.month === "2026-11")!.benchmark_twr).toBeCloseTo(1.02 / 1.01 - 1, 6)
  })

  it("#7 股利的日期對到收盤日：週末、假日領的算下一個收盤日；最後一個收盤以後的不列；同一天加起來", () => {
    const days = ["2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"]
    expect(snapDividends([{ t: "2026-11-07", amount: 3_000 }, { t: "2026-11-09", amount: 500 }, { t: "2026-11-06", amount: 100 }, { t: "2026-11-11", amount: 9 }], days)).toEqual([
      { t: "2026-11-09", amount: 3_500 },
      { t: "2026-11-06", amount: 100 },
    ])
    // 第一個收盤以前的對到第一天
    expect(snapDividends([{ t: "2026-11-01", amount: 1 }], days)).toEqual([{ t: "2026-11-05", amount: 1 }])
  })

  it("#18（暫定）匯入時找不到買入日、用匯入那天記的月份不列，另外數；匯入在星期六時算下一個收盤日的月份；在區間以前的不算", () => {
    const points = [p("2025-11-27", 1, 1, 1.0), p("2025-11-28", 1, 1, 1.01), p("2025-12-01", 2, 1, 1.2), p("2025-12-31", 2, 1, 1.21), p("2026-01-05", 2, 1, 1.22)]
    const base = p("2025-11-26", 1, 1, 1)
    const { months, skippedImport } = monthlyBreakdown(points, { base, importDays: ["2025-11-29"] })
    expect(months.map((m) => m.month)).toEqual(["2026-01", "2025-11"])
    expect(skippedImport).toBe(1)
    // 匯入在區間以前（基準收盤當天或更早）：不影響
    expect(monthlyBreakdown(points, { base, importDays: ["2025-11-20"] }).skippedImport).toBe(0)
    // 不傳 importDays：照舊全部列（這條規則可以整個拿掉）
    expect(monthlyBreakdown(points, { base }).months).toHaveLength(3)
  })
})
