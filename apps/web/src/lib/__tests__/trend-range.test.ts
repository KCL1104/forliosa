import { describe, expect, it } from "vitest"
import {
  compactTicks,
  dateAxis,
  investedVisible,
  minusMonths,
  needsYear,
  rangeExceedsData,
  rangeReturn,
  rangeStartIndex,
  responseExceedsData,
  sliceRange,
  TREND_RANGES,
  trendDomain,
  trendState,
  trendWindow,
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

describe("區間按鈕一律七顆（2026-11-17 負責人要求）", () => {
  it("5日・1月・3月・6月・今年・1年・全部，沒有 1日", () => {
    expect(TREND_RANGES.map((r) => r.label)).toEqual(["5日", "1月", "3月", "6月", "今年", "1年", "全部"])
  })
})

describe("rangeExceedsData：區間比資料長（畫全部的資料，期間要照實寫）", () => {
  const exceeding = (s: { t: string }[]) => TREND_RANGES.map((r) => r.value).filter((r) => rangeExceedsData(s, r))
  it("存檔才開始（11/12 起 4 個收盤）：全部的區間都比資料長，「全部」不算", () => {
    expect(exceeding(weekdays("2026-11-12", "2026-11-17"))).toEqual(["5D", "1M", "3M", "6M", "YTD", "1Y"])
  })
  it("5日：不到 6 個收盤（基準收盤＋5 個交易日）才算；第 6 個收盤起是真的 5 日", () => {
    expect(rangeExceedsData(weekdays("2026-11-12", "2026-11-18"), "5D")).toBe(true)
    expect(rangeExceedsData(weekdays("2026-11-12", "2026-11-19"), "5D")).toBe(false)
  })
  it("1月：名目起始日當天或之前沒有收盤才算（12/11 的一個月前是 11/11，還沒有資料；12/14 的是 11/14，11/12、11/13 有）", () => {
    expect(rangeExceedsData(weekdays("2026-11-12", "2026-12-11"), "1M")).toBe(true)
    expect(rangeExceedsData(weekdays("2026-11-12", "2026-12-14"), "1M")).toBe(false)
    // 名目起始日之前只有第一個收盤（11/13 休市）：它就是基準收盤，不算
    expect(rangeExceedsData(weekdays("2026-11-12", "2026-12-14").filter((p) => p.t !== "2026-11-13"), "1M")).toBe(false)
    // 名目起始日剛好是第一個收盤：沒有基準收盤，那一天的漲跌算不到，算比資料長
    expect(rangeExceedsData([{ t: "2026-11-12" }, { t: "2026-12-11" }, { t: "2026-12-12" }], "1M")).toBe(true)
  })
  it("今年：2027 年以後去年底有收盤，不算；示範資料（6/1 起）只有 6月以上算", () => {
    expect(rangeExceedsData(weekdays("2026-11-12", "2027-01-04"), "YTD")).toBe(false)
    expect(exceeding(weekdays("2026-06-01", "2026-11-12"))).toEqual(["6M", "YTD", "1Y"])
  })
  it("沒有資料：不算", () => {
    expect(rangeExceedsData([], "1M")).toBe(false)
  })
})

describe("rangeReturn", () => {
  it("切過的區間：twr_index 從第一點（基準收盤）重新起算", () => {
    const s = [{ twr_index: 1.1 }, { twr_index: 1.21 }, { twr_index: 1.155 }]
    const win = { points: s, base: s[0]!.twr_index }
    expect(rangeReturn(win)).toBeCloseTo(0.05)
    expect(rangeReturn(win, 1)).toBeCloseTo(0.1)
    expect(rangeReturn(win, 0)).toBe(0)
    expect(rangeReturn({ points: [], base: 1 })).toBeNull()
  })
  it("沒切過的「全部」：第一點是 1＋第一天的報酬（後端合約），區間報酬＝最後一點 − 1，和後端的 TWR 一樣", () => {
    // 11/20 買 1,000 股、每股 1,000 元加手續費 1,425，三天收盤 1010／1005／1020（後端 daily_return／twr_index 算的）
    const s = [
      { t: "2026-11-20", twr_index: 1.008563 },
      { t: "2026-11-23", twr_index: 1.00357 },
      { t: "2026-11-24", twr_index: 1.018549 },
    ]
    const win = trendWindow(s, "ALL")
    expect(win.base).toBe(1)
    expect(rangeReturn(win)).toBeCloseTo(0.018549, 6)
    // 滑到第一天：那一天自己的報酬（績效圖那一點是 +0.86%），不是 0
    expect(rangeReturn(win, 0)).toBeCloseTo(0.008563, 6)
    // 資料比區間短、整段時也一樣（後端從第一天算、含第一天的漲跌）
    expect(rangeReturn(trendWindow(s, "1M"))).toBeCloseTo(0.018549, 6)
  })
  it("切過的區間：分母是基準收盤，報酬不含它自己那天", () => {
    const s = weekdays("2026-06-01", "2026-11-12")
    const win = trendWindow(s, "1M")
    expect(win.points[0]!.t).toBe("2026-10-09")
    expect(win.base).toBe(win.points[0]!.twr_index)
    expect(rangeReturn(win)).toBeCloseTo(s.at(-1)!.twr_index / win.points[0]!.twr_index - 1, 9)
  })
})

describe("responseExceedsData：績效分段的期間什麼時候寫「只有 … 的資料」", () => {
  const newAcct = weekdays("2026-11-12", "2026-11-17")
  const resp = (range: string, series: { t: string }[], start_date = series[0]?.t ?? null) => ({ range, start_date, series })
  it("區間比這個帳戶的資料長、回應從它的第一個收盤開始：寫", () => {
    expect(responseExceedsData(resp("3M", newAcct), newAcct)).toBe(true)
    expect(responseExceedsData(resp("1M", newAcct), newAcct)).toBe(true)
  })
  it("切換帳戶、新帳戶的「全部」先回來，區間的回應還是舊帳戶真的 3 個月：不寫（舊帳戶的期間照樣是它自己的）", () => {
    const old3M = weekdays("2026-08-12", "2026-11-17")
    expect(responseExceedsData(resp("3M", old3M), newAcct)).toBe(false)
    // 舊帳戶真的 5 日（6 個收盤）、新帳戶 4 個收盤
    expect(responseExceedsData(resp("5D", weekdays("2026-11-10", "2026-11-17")), newAcct)).toBe(false)
  })
  it("反過來：區間的回應先回來（新帳戶），「全部」還是舊帳戶的長序列：區間沒有比那個序列長，不寫", () => {
    expect(responseExceedsData(resp("3M", newAcct), weekdays("2026-06-01", "2026-11-17"))).toBe(false)
  })
  it("5日：第一筆錢前一天的收盤是基準（市值 0），第二點才是第一個收盤：照樣寫", () => {
    const acct = weekdays("2026-11-16", "2026-11-17")
    expect(responseExceedsData(resp("5D", weekdays("2026-11-13", "2026-11-17")), acct)).toBe(true)
    // 第二點不是第一個收盤：湊不起來，不寫
    expect(responseExceedsData(resp("5D", weekdays("2026-11-12", "2026-11-17")), acct)).toBe(false)
  })
  it("「全部」、不是走勢的區間、沒有起始日、還沒讀到「全部」：不寫", () => {
    expect(responseExceedsData(resp("ALL", newAcct), newAcct)).toBe(false)
    expect(responseExceedsData(resp("1D", newAcct), newAcct)).toBe(false)
    expect(responseExceedsData(resp("3M", newAcct, null), newAcct)).toBe(false)
    expect(responseExceedsData(resp("3M", newAcct), undefined)).toBe(false)
  })
})

describe("trendWindow 的起始日：和後端的 start_date（績效分段寫的期間）同一天", () => {
  const s = weekdays("2026-06-01", "2026-11-12")
  it("1M／3M：第一點是基準收盤（10/9），起始日是下一個收盤（10/12）", () => {
    const m = trendWindow(s, "1M")
    expect(m.points[m.from]!.t).toBe("2026-10-12")
    const q = trendWindow(s, "3M")
    expect(q.points[0]!.t).toBe("2026-08-11")
    expect(q.points[q.from]!.t).toBe("2026-08-12")
  })
  it("5D：後端的起始日就是基準收盤；全部、資料比區間短：第一天", () => {
    const d = trendWindow(s, "5D")
    expect(d.from).toBe(0)
    expect(d.points[0]!.t).toBe("2026-11-05")
    expect(trendWindow(s, "ALL").from).toBe(0)
    expect(trendWindow(s, "1Y").from).toBe(0)
  })
  it("今年：基準是去年最後一個收盤，起始日是今年第一個收盤", () => {
    const y = trendWindow(weekdays("2026-11-12", "2027-01-05"), "YTD")
    expect(y.points[0]!.t).toBe("2026-12-31")
    expect(y.points[y.from]!.t).toBe("2027-01-01")
  })
})

describe("trendWindow：區間比資料長時畫全部、報酬從第一個收盤算起（和後端、「全部」同一個數字）", () => {
  const s = weekdays("2026-11-12", "2026-11-17")
  it("4 個收盤選 1月、3月、1年、5日：整段、分母 1、起始日是第一個收盤，報酬和「全部」一樣", () => {
    const all = trendWindow(s, "ALL")
    for (const r of ["5D", "1M", "3M", "1Y"] as const) {
      const w = trendWindow(s, r)
      expect(w.exceeds).toBe(true)
      expect(w.points).toHaveLength(4)
      expect(w.base).toBe(1)
      expect(w.points[w.from]!.t).toBe("2026-11-12")
      expect(rangeReturn(w)).toBeCloseTo(rangeReturn(all)!, 12)
    }
    expect(all.exceeds).toBe(false)
  })
  it("基準收盤剛好是資料的第一天（不是比資料長）：分母是它的 twr_index，起始日是下一個收盤（和後端一樣不含第一天的漲跌）", () => {
    // 11/13 休市：12/14 的一個月前是 11/14，之前只有 11/12 一個收盤，它就是基準
    const t = weekdays("2026-11-12", "2026-12-14").filter((p) => p.t !== "2026-11-13")
    const w = trendWindow(t, "1M")
    expect(w.exceeds).toBe(false)
    expect(w.points[0]!.t).toBe("2026-11-12")
    expect(w.base).toBe(t[0]!.twr_index)
    expect(w.points[w.from]!.t).toBe("2026-11-16")
  })
  it("5日剛好 6 個收盤：第一個收盤是基準，分母是它的 twr_index", () => {
    const six = weekdays("2026-11-12", "2026-11-19")
    const w = trendWindow(six, "5D")
    expect(w.exceeds).toBe(false)
    expect(w.base).toBe(six[0]!.twr_index)
    expect(w.from).toBe(0)
  })
})

describe("trendState：歷史短的三種樣子", () => {
  it("少於 2 點不畫；2～6 點畫圓點、寫說明（區間照樣放）；7 點以上照常", () => {
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
