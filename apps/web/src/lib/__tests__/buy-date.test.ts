import { describe, expect, it } from "vitest"
import type { Candle } from "@/api/types"
import { candidateDays, closeGap, crossesOn, crossingIndexes, estimateBuyDate, indexOnOrBefore, isFarFromCost } from "../buy-date"

/** 一天的 K 線：只在意最高、最低（收盤取中間） */
const k = (t: string, l: number, h: number, c = (l + h) / 2): Candle => ({ t, o: c, h, l, c, v: 0 })

describe("估計買入日：股價經過成本價（docs/proposals/asset-composition.md〈估計買入日的算法〉）", () => {
  it("當天最低 ≤ 成本 ≤ 當天最高就算經過；用最高、最低判斷，不用收盤價", () => {
    const candles = [k("2026-01-05", 600, 620, 601)]
    expect(crossesOn(candles, 0, 612)).toBe(true)
    // 收盤 601 離成本 612 很遠，但盤中經過：照樣算
    expect(crossesOn(candles, 0, 600)).toBe(true)
    expect(crossesOn(candles, 0, 620)).toBe(true)
    expect(crossesOn(candles, 0, 621)).toBe(false)
  })

  it("跳空也算經過：前一天最高 600、當天最低 620、成本 612——取跳過去的那一天；往下跳空同理", () => {
    const up = [k("2026-01-05", 590, 600), k("2026-01-06", 620, 630)]
    expect(crossesOn(up, 0, 612)).toBe(false)
    expect(crossesOn(up, 1, 612)).toBe(true)
    const down = [k("2026-01-05", 620, 630), k("2026-01-06", 590, 600)]
    expect(crossesOn(down, 1, 612)).toBe(true)
    // 第一天沒有前一天：只看自己的高低
    expect(crossesOn(up, 0, 625)).toBe(false)
  })

  it("從匯入那天往回第一個經過的日子；匯入那天以後的不算；五年都沒有是 null", () => {
    const candles = [k("2025-03-03", 600, 615), k("2025-03-04", 620, 640), k("2025-08-14", 605, 618), k("2025-08-15", 630, 650), k("2025-12-02", 600, 620)]
    expect(estimateBuyDate(candles, 612, "2025-12-01")).toBe("2025-08-14")
    expect(estimateBuyDate(candles, 612, "2025-12-02")).toBe("2025-12-02")
    expect(estimateBuyDate(candles, 612, "2025-08-13")).toBe("2025-03-03")
    // 成本比五年來的最低還低（領過配股、很早以前買的）：找不到
    expect(estimateBuyDate(candles, 488, "2025-12-01")).toBeNull()
    expect(estimateBuyDate([], 612, "2025-12-01")).toBeNull()
  })

  it("候選的日子：連續經過的一段只列最近的那一天（和估計同一個規則），由新到舊", () => {
    const candles = [
      k("2025-01-02", 600, 615), // 一段：1/2–1/3
      k("2025-01-03", 605, 614),
      k("2025-01-06", 620, 630),
      k("2025-01-07", 608, 613), // 一段：1/7
      k("2025-01-08", 625, 640),
    ]
    expect(crossingIndexes(candles, 612)).toEqual([0, 1, 3])
    expect(candidateDays(candles, 612).map((i) => candles[i]!.t)).toEqual(["2025-01-07", "2025-01-03"])
    // 匯入那天以後的不列
    expect(candidateDays(candles, 612, "2025-01-06").map((i) => candles[i]!.t)).toEqual(["2025-01-03"])
    expect(candidateDays(candles, 1_000)).toEqual([])
  })

  it("收盤和成本差多少；差 3% 以上要照實說", () => {
    expect(closeGap(580, 612)).toBeCloseTo(-0.0523, 4)
    expect(isFarFromCost(580, 612)).toBe(true)
    expect(isFarFromCost(600, 612)).toBe(false)
    expect(isFarFromCost(612, 612)).toBe(false)
  })

  it("一個日期在 K 線裡的位置：那一天或之前最後一個交易日（週末、假日）", () => {
    const candles = [k("2025-01-02", 1, 2), k("2025-01-03", 1, 2), k("2025-01-06", 1, 2)]
    expect(indexOnOrBefore(candles, "2025-01-03")).toBe(1)
    expect(indexOnOrBefore(candles, "2025-01-05")).toBe(1)
    expect(indexOnOrBefore(candles, "2024-12-31")).toBe(0)
    expect(indexOnOrBefore(candles, "2025-02-01")).toBe(2)
  })
})
