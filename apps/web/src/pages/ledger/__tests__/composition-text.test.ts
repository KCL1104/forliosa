import { describe, expect, it } from "vitest"
import { benchmarkGap, estimatedLine, fundRankPeriod, INVESTED_RECOVERED, isRecovered, monthLabel, monthSpanText, offChartText, roughMoney, touchesSpan, trendEstimatedText } from "../composition-text"

describe("資產組成的字", () => {
  it("估計那一段的說明：只寫畫出來的部分；跨年寫年份；沒碰到是 null", () => {
    const days = ["2025-11-12", "2025-11-28", "2025-12-01", "2026-11-12"]
    const span = { from: "2024-07-29", until: "2025-11-28" }
    expect(estimatedLine([span], days, true)).toBe("2025/11/12 – 2025/11/28 用估計的買入日計算")
    expect(estimatedLine([span], ["2026-10-12", "2026-11-12"], false)).toBeNull()
    expect(estimatedLine(null, days, false)).toBeNull()
    expect(estimatedLine([], days, false)).toBeNull()
    // 只碰到一天
    expect(estimatedLine([{ from: "2026-10-12", until: "2026-10-12" }], ["2026-10-12", "2026-11-12"], false)).toBe("10/12 用估計的買入日計算")
  })

  it("分好幾次匯入：一行列出每一段（頓號），不是一段一句；中間真實的日子不寫", () => {
    const days = ["2025-11-12", "2025-11-28", "2025-12-01", "2026-09-01", "2026-11-18", "2026-11-19"]
    const spans = [{ from: "2024-07-29", until: "2025-11-28" }, { from: "2026-09-01", until: "2026-11-18" }]
    expect(estimatedLine(spans, days, true)).toBe("2025/11/12 – 2025/11/28、2026/9/1 – 2026/11/18 用估計的買入日計算")
    // 區間只碰到後面那一段
    expect(estimatedLine(spans, days.slice(2), true)).toBe("2026/9/1 – 2026/11/18 用估計的買入日計算")
  })

  it("#9 區間裡估計的是哪幾天：首頁走勢與績效分段同一個規則——含基準收盤（報酬的分母）；估計那一段剛好在基準收盤結束時也寫", () => {
    const series = ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-11-12"].map((t, i) => ({ t, twr_index: 1 + i / 100 }))
    // 1 月：名目起始 10/12，基準收盤 10/9
    expect(trendEstimatedText(series, "1M", [{ from: "2026-01-01", until: "2026-10-09" }])).toBe("10/9")
    expect(trendEstimatedText(series, "1M", [{ from: "2026-01-01", until: "2026-10-12" }])).toBe("10/9 – 10/12")
    expect(trendEstimatedText(series, "1M", [{ from: "2026-01-01", until: "2026-10-08" }])).toBeNull()
    expect(trendEstimatedText(series, "1M", null)).toBeNull()
  })

  it("區間有沒有用到估計的買入日", () => {
    const span = { from: "2024-07-29", until: "2025-11-28" }
    expect(touchesSpan([span], "2025-11-12", "2026-11-12")).toBe(true)
    expect(touchesSpan([span], "2025-12-01", "2026-11-12")).toBe(false)
    expect(touchesSpan(null, "2025-11-12", "2026-11-12")).toBe(false)
    expect(touchesSpan([span], null, null)).toBe(false)
    // 好幾段：碰到任何一段就算
    expect(touchesSpan([span, { from: "2026-09-01", until: "2026-11-18" }], "2025-12-01", "2026-11-19")).toBe(true)
    expect(touchesSpan([span, { from: "2026-09-01", until: "2026-11-18" }], "2025-12-01", "2026-08-31")).toBe(false)
  })

  it("月份：今年的「11 月」，跨年「2025/12」", () => {
    expect(monthLabel("2026-11", false)).toBe("11 月")
    expect(monthLabel("2025-12", true)).toBe("2025/12")
    expect(monthLabel("2026-03", true)).toBe("2026/3")
  })

  it("不完整的月份寫它算的是哪幾天；整個月不寫", () => {
    expect(monthSpanText({ from: "2026-11-02", to: "2026-11-12", whole: false })).toBe("11/2 – 11/12")
    expect(monthSpanText({ from: "2026-11-12", to: "2026-11-12", whole: false })).toBe("11/12")
    expect(monthSpanText({ from: "2026-10-01", to: "2026-10-30", whole: true })).toBeNull()
  })

  it("和基準差幾個百分點：用多／少說方向（不是價格漲跌）", () => {
    expect(benchmarkGap({ twr: 0.0323, benchmark_twr: 0.0585 })).toEqual({ word: "少", points: "2.62" })
    expect(benchmarkGap({ twr: 0.0369, benchmark_twr: -0.0311 })).toEqual({ word: "多", points: "6.80" })
    expect(benchmarkGap({ twr: 0.01, benchmark_twr: null })).toBeNull()
  })

  it("贏過幾成的基金：期間從今年第一週開始寫「今年」，不然寫從哪天起", () => {
    expect(fundRankPeriod("2026-01-02", "2026-11-12")).toBe("今年")
    expect(fundRankPeriod("2026-07-01", "2026-11-12")).toBe("7/1 以來")
    expect(fundRankPeriod("2025-12-01", "2026-11-12")).toBe("2025/12/1 以來")
  })
})

describe("資產組成 v2：本金在圖外時圖裡那一行", () => {
  it("約略金額和縱軸刻度同一種寫法：萬、億、1 萬以下整數，負號是「−」", () => {
    expect(roughMoney(2_875_955)).toBe("288萬")
    expect(roughMoney(6_327_331)).toBe("633萬")
    expect(roughMoney(123_456_789)).toBe("1.23億")
    expect(roughMoney(-200_000)).toBe("−20萬")
    expect(roughMoney(8_400)).toBe("8,400")
    expect(roughMoney(12_345_678)).toBe("1,235萬")
  })

  it("「本金 288萬，在圖的下方」／上方；隱私模式不寫金額", () => {
    expect(offChartText(2_875_955, "below", false)).toBe("本金 288萬，在圖的下方")
    expect(offChartText(6_327_331, "above", false)).toBe("本金 633萬，在圖的上方")
    expect(offChartText(2_875_955, "below", true)).toBe("本金在圖的下方")
  })
})

describe("資產組成 v2：本金已收回", () => {
  it("本金 ≤ 0（四捨五入到元以後）是「本金已收回」；1 元以上照舊寫金額", () => {
    expect(INVESTED_RECOVERED).toBe("本金已收回")
    expect(isRecovered(0)).toBe(true)
    expect(isRecovered(-0)).toBe(true)
    expect(isRecovered(-1)).toBe(true)
    expect(isRecovered(-5_000_000)).toBe(true)
    expect(isRecovered(1)).toBe(false)
  })
})
