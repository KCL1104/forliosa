import { describe, expect, it } from "vitest"
import { codeOf, formatQuote, formatQuoteChange, limitPrices, limitState, marketOf, quoteDecimals, twTick } from "@/lib/tick"

describe("台股升降單位", () => {
  it("股票：0.01／0.05／0.1／0.5／1／5", () => {
    expect([9.99, 10, 49.95, 50, 99.9, 100, 499.5, 500, 999, 1000].map((p) => twTick(p))).toEqual([0.01, 0.05, 0.05, 0.1, 0.1, 0.5, 0.5, 1, 1, 5])
  })
  it("ETF：50 元以下 0.01、以上 0.05", () => {
    expect(twTick(22.86, "etf")).toBe(0.01)
    expect(twTick(72.4, "etf")).toBe(0.05)
  })
})

describe("漲跌停價（參考價 ±10%，取到升降單位）", () => {
  it("台積電參考價 1,035：漲停 1,135、跌停 935（1,138.5 → 1,135；931.5 → 932）", () => {
    expect(limitPrices(1035, "TWSE")).toEqual({ up: 1135, down: 932 })
  })
  it("跨價位：參考價 95 → 漲停 104.5（0.5 檔）、跌停 85.5（0.1 檔）", () => {
    expect(limitPrices(95, "TWSE")).toEqual({ up: 104.5, down: 85.5 })
  })
  it("ETF 0050 參考價 71.85 → 79.00／64.70", () => {
    expect(limitPrices(71.85, "TWSE", "etf")).toEqual({ up: 79, down: 64.7 })
  })
  it("美股沒有漲跌停", () => {
    expect(limitPrices(212.3, "US")).toBeNull()
  })
  it("判斷是否在漲停或跌停", () => {
    expect(limitState(1135, 1135, 932)).toBe("up")
    expect(limitState(932, 1135, 932)).toBe("down")
    expect(limitState(1000, 1135, 932)).toBeNull()
  })
})

describe("報價顯示的小數位（依升降單位）", () => {
  it("1,085、236.5、398、22.40、72.40、US$212.30", () => {
    expect(formatQuote(1085, "TWSE")).toBe("1,085")
    expect(formatQuote(236.5, "TWSE")).toBe("236.5")
    expect(formatQuote(398, "TWSE")).toBe("398")
    expect(formatQuote(22.4, "TWSE")).toBe("22.40")
    expect(formatQuote(72.4, "TWSE", "etf")).toBe("72.40")
    expect(formatQuote(212.3, "US")).toBe("212.30")
    expect(formatQuote(null, "TWSE")).toBe("—")
  })
  it("漲跌點數跟著現價的位數", () => {
    expect(formatQuoteChange(50, 1085, "TWSE")).toBe("50")
    expect(formatQuoteChange(-5.5, 236.5, "TWSE")).toBe("5.5")
    expect(formatQuoteChange(-0.05, 22.86, "TWSE", "etf")).toBe("0.05")
    expect(quoteDecimals(1085, "TWSE")).toBe(0)
  })
  it("代號與市場", () => {
    expect(marketOf("6488.TWO")).toBe("TPEX")
    expect(marketOf("2330.TW")).toBe("TWSE")
    expect(marketOf("NVDA")).toBe("US")
    expect(codeOf("00878.TW")).toBe("00878")
  })
})
