import { describe, expect, it } from "vitest"
import {
  availableRanges,
  compactTicks,
  dateAxis,
  effectiveRange,
  investedVisible,
  minusMonths,
  needsYear,
  rangeReturn,
  rangeStartIndex,
  sliceRange,
  trendDomain,
  trendState,
} from "../trend-range"

/** 從 from 到 to 的每一個週一到週五（示範用的交易日，不管國定假日） */
function weekdays(from: string, to: string): { t: string; twr_index: number }[] {
  const out: { t: string; twr_index: number }[] = []
  for (let d = new Date(`${from}T00:00:00Z`); d <= new Date(`${to}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 1)) {
    const w = d.getUTCDay()
    if (w === 0 || w === 6) continue
    out.push({ t: d.toISOString().slice(0, 10), twr_index: 1 + out.length * 0.01 })
  }
  return out
}

describe("minusMonths（和後端 add_months 一樣）", () => {
  it("往前推日曆月，月底對齊", () => {
    expect(minusMonths("2026-11-16", 1)).toBe("2026-10-16")
    expect(minusMonths("2026-03-31", 1)).toBe("2026-02-28")
    expect(minusMonths("2027-01-15", 3)).toBe("2026-10-15")
    expect(minusMonths("2026-11-16", 12)).toBe("2025-11-16")
  })
})

describe("sliceRange：區間的第一點是基準收盤（和後端的 TWR 同一個起點）", () => {
  const s = weekdays("2026-06-01", "2026-11-12")
  it("5D 取最後 6 點（一個基準收盤＋5 個交易日）", () => {
    expect(sliceRange(s, "5D").map((p) => p.t)).toEqual(["2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"])
  })
  it("1M：名目起始日（一個月前那天）之前的最後一個收盤", () => {
    // 11/12 往前一個月是 10/12（週一）：後端從 10/12 算起、含 10/12 的漲跌，所以基準是 10/9（週五）
    expect(sliceRange(s, "1M")[0]!.t).toBe("2026-10-09")
    // 起始日是週末：12/14 往前一個月是 11/14（週六）→ 基準是 11/13（週五）
    expect(sliceRange(weekdays("2026-06-01", "2026-12-14"), "1M")[0]!.t).toBe("2026-11-13")
  })
  it("今年：從去年最後一個收盤起算", () => {
    const t = weekdays("2026-11-12", "2027-01-04")
    expect(sliceRange(t, "YTD").map((p) => p.t)).toEqual(["2026-12-31", "2027-01-01", "2027-01-04"])
  })
  it("資料比區間短：整段；ALL 是全部", () => {
    expect(sliceRange(s, "1Y")).toHaveLength(s.length)
    expect(rangeStartIndex(s, "6M")).toBe(0)
    expect(sliceRange(s, "ALL")).toHaveLength(s.length)
    expect(sliceRange([], "1M")).toEqual([])
  })
})

describe("availableRanges：資料撐得起來的區間才放", () => {
  it("2～6 點：不放任何區間", () => {
    expect(availableRanges(weekdays("2026-11-12", "2026-11-13"))).toEqual([])
    expect(availableRanges(weekdays("2026-11-12", "2026-11-16"))).toEqual([])
    expect(availableRanges(weekdays("2026-11-12", "2026-11-19"))).toEqual([])
  })
  it("第 7 個收盤（11/20）：5日・全部", () => {
    expect(availableRanges(weekdays("2026-11-12", "2026-11-20"))).toEqual(["5D", "ALL"])
  })
  it("12/14 出現 1月；2027-01-04 出現今年；2027-02 出現 3月", () => {
    expect(availableRanges(weekdays("2026-11-12", "2026-12-11"))).toEqual(["5D", "ALL"])
    expect(availableRanges(weekdays("2026-11-12", "2026-12-14"))).toEqual(["5D", "1M", "ALL"])
    expect(availableRanges(weekdays("2026-11-12", "2027-01-04"))).toEqual(["5D", "1M", "YTD", "ALL"])
    expect(availableRanges(weekdays("2026-11-12", "2027-02-15"))).toEqual(["5D", "1M", "3M", "YTD", "ALL"])
  })
  it("示範資料（2026-06-01 起到 11/12）：5日・1月・3月・全部（沒有 6月、今年、1年）", () => {
    expect(availableRanges(weekdays("2026-06-01", "2026-11-12"))).toEqual(["5D", "1M", "3M", "ALL"])
  })
})

describe("effectiveRange：上次選的撐不起來時畫全部", () => {
  it("撐得起來就用上次選的", () => {
    expect(effectiveRange("3M", ["5D", "1M", "3M", "ALL"])).toBe("3M")
  })
  it("撐不起來（或一顆按鈕都沒有）用全部", () => {
    expect(effectiveRange("1Y", ["5D", "1M", "3M", "ALL"])).toBe("ALL")
    expect(effectiveRange("1M", [])).toBe("ALL")
  })
})

describe("rangeReturn", () => {
  it("twr_index 從區間的第一點重新起算", () => {
    const s = [{ twr_index: 1.1 }, { twr_index: 1.21 }, { twr_index: 1.155 }]
    expect(rangeReturn(s)).toBeCloseTo(0.05)
    expect(rangeReturn(s, 1)).toBeCloseTo(0.1)
    expect(rangeReturn(s, 0)).toBe(0)
    expect(rangeReturn([])).toBeNull()
  })
})

describe("trendState：歷史短的三種樣子", () => {
  it("少於 2 點不畫；2～6 點畫圓點、不放區間；7 點以上照常", () => {
    expect(trendState(0)).toBe("missing")
    expect(trendState(1)).toBe("missing")
    expect(trendState(2)).toBe("short")
    expect(trendState(6)).toBe("short")
    expect(trendState(7)).toBe("full")
  })
})

describe("trendDomain：縱軸只看總資產、至少 ±3%、3 條格線", () => {
  const check = (values: number[]) => {
    const d = trendDomain(values)
    const lo = Math.min(...values)
    const hi = Math.max(...values)
    const mid = (lo + hi) / 2
    expect(d.ticks).toHaveLength(3)
    // 資料和刻度都在範圍裡
    expect(d.min).toBeLessThanOrEqual(lo)
    expect(d.max).toBeGreaterThanOrEqual(hi)
    for (const t of d.ticks) {
      expect(t).toBeGreaterThanOrEqual(d.min - 1e-6)
      expect(t).toBeLessThanOrEqual(d.max + 1e-6)
    }
    // 至少涵蓋中點上下各 3%
    expect(d.min).toBeLessThanOrEqual(mid * 0.97 + 1e-6)
    expect(d.max).toBeGreaterThanOrEqual(mid * 1.03 - 1e-6)
    // 間隔是整齊的數字
    const step = d.ticks[1]! - d.ticks[0]!
    expect(d.ticks[2]! - d.ticks[1]!).toBeCloseTo(step)
    const m = step / 10 ** Math.floor(Math.log10(step))
    expect([1, 2, 2.5, 5]).toContainEqual(Number(m.toFixed(6)))
    return d
  }
  it("兩個收盤只差 +0.7%：不會從底拉到頂（線只佔中間一小段）", () => {
    const d = check([50_000, 50_350])
    expect((50_350 - 50_000) / (d.max - d.min)).toBeLessThan(0.15)
    expect(d.ticks).toEqual([49_000, 50_000, 51_000])
  })
  it("一個月 +9%：範圍貼著資料，不會被投入本金壓平", () => {
    const d = check([3_750_000, 3_820_000, 4_000_000, 4_107_724])
    expect((4_107_724 - 3_750_000) / (d.max - d.min)).toBeGreaterThan(0.75)
  })
  it("各種大小都是 3 條格線", () => {
    check([1, 1])
    check([980, 1_020])
    check([12_345, 12_400, 13_900])
    check([120_000_000, 135_000_000])
    check([0.5, 9_000])
  })
  it("全部都是 0 也畫得出來；金額不畫到負的", () => {
    const d = trendDomain([0, 0])
    expect(d.ticks).toHaveLength(3)
    expect(d.min).toBeGreaterThanOrEqual(0)
    expect(trendDomain([0, 100]).min).toBeGreaterThanOrEqual(0)
  })
})

describe("investedVisible：投入本金在縱軸的範圍裡才畫", () => {
  const slice = [{ net_invested: 48_000 }, { net_invested: 48_000 }, { net_invested: 49_500 }]
  it("每一天都在範圍裡：畫", () => {
    expect(investedVisible(slice, 47_000, 51_000)).toBe(true)
  })
  it("有一天不在範圍裡（賺得多、離太遠）：整條不畫", () => {
    expect(investedVisible(slice, 48_500, 51_000)).toBe(false)
    expect(investedVisible([{ net_invested: 2_700_000 }], 3_700_000, 4_200_000)).toBe(false)
    expect(investedVisible([], 0, 1)).toBe(false)
  })
})

describe("compactTicks：同一條軸同一個單位、同樣的小數位", () => {
  it("萬：4.9萬、5.0萬、5.1萬；410萬；1 萬以下寫整數；億", () => {
    expect(compactTicks([49_000, 50_000, 51_000])).toEqual(["4.9萬", "5.0萬", "5.1萬"])
    expect(compactTicks([50_200, 50_300, 50_400])).toEqual(["5.02萬", "5.03萬", "5.04萬"])
    expect(compactTicks([3_800_000, 4_000_000, 4_200_000])).toEqual(["380萬", "400萬", "420萬"])
    expect(compactTicks([800, 900, 1_000])).toEqual(["800", "900", "1,000"])
    expect(compactTicks([9_000, 10_000, 11_000])).toEqual(["0.9萬", "1.0萬", "1.1萬"])
    expect(compactTicks([100_000_000, 150_000_000, 200_000_000])).toEqual(["1.0億", "1.5億", "2.0億"])
  })
})

describe("dateAxis 與 needsYear", () => {
  it("短區間只標頭尾", () => {
    const d = weekdays("2026-11-12", "2026-11-16").map((p) => p.t)
    const a = dateAxis(d)
    expect(a.ticks).toEqual([0, 2])
    expect(a.format(d[0]!)).toBe("11/12")
    expect(dateAxis(["2026-11-12", "2026-11-13"]).ticks).toEqual([0, 1])
  })
  it("3 個月以上：每月第一個交易日", () => {
    const d = weekdays("2026-06-01", "2026-11-12").map((p) => p.t)
    const a = dateAxis(d)
    expect(a.ticks.map((i) => a.format(d[i]!))).toEqual(["2026/07", "2026/08", "2026/09", "2026/10", "2026/11"])
  })
  it("跨年或一年以上要寫年份", () => {
    expect(needsYear(["2026-11-12", "2026-11-16"])).toBe(false)
    expect(needsYear(["2026-12-31", "2027-01-04"])).toBe(true)
    expect(needsYear(["2025-11-14", "2026-11-13"])).toBe(true)
  })
})
