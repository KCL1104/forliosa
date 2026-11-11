import { describe, expect, it } from "vitest"
import {
  conventionColors,
  direction,
  directionGlyph,
  formatCompact,
  formatDate,
  formatDateShort,
  formatDateTime,
  formatDaysUntil,
  formatMoney,
  formatMoneyCompact,
  formatPercent,
  formatPrice,
  formatPriceLevel,
  formatQuantity,
  mask,
  MASK,
  MINUS,
  toneClass,
} from "../format"

describe("張／股", () => {
  it("以張顯示：整張、零股、張＋股", () => {
    expect(formatQuantity(8000)).toBe("8 張")
    expect(formatQuantity(1500)).toBe("1 張 500 股")
    expect(formatQuantity(37)).toBe("37 股")
    expect(formatQuantity(0)).toBe("0 股")
    expect(formatQuantity(9_876_543)).toBe("9,876 張 543 股")
  })
  it("以股顯示加千分位", () => {
    expect(formatQuantity(1500, "share")).toBe("1,500 股")
  })
  it("美股一律以股，允許碎股", () => {
    expect(formatQuantity(15, "lot", "US")).toBe("15 股")
    expect(formatQuantity(0.5, "lot", "US")).toBe("0.5 股")
  })
  it("負數（減資等）用 U+2212", () => {
    expect(formatQuantity(-1500)).toBe(`${MINUS}1 張 500 股`)
  })
})

describe("萬／億／兆", () => {
  it("萬", () => {
    expect(formatCompact(3_284_500)).toBe("328.45 萬")
    expect(formatCompact(10_000)).toBe("1 萬")
  })
  it("億：上千億金額", () => {
    expect(formatCompact(123_456_789_012)).toBe("1,234.57 億")
  })
  it("兆", () => {
    expect(formatCompact(28_137_000_000_000)).toBe("28.14 兆")
  })
  it("一萬以下顯示完整數字", () => {
    expect(formatCompact(9_999)).toBe("9,999")
  })
  it("負數", () => {
    expect(formatCompact(-67_158)).toBe(`${MINUS}6.72 萬`)
    expect(formatMoneyCompact(-67_158, { signed: true })).toBe(`${MINUS}NT$6.72 萬`)
  })
  it("金額縮寫保留幣別", () => {
    expect(formatMoneyCompact(1_627_500)).toBe("NT$162.75 萬")
    expect(formatMoneyCompact(5_000)).toBe("NT$5,000")
  })
})

describe("金額", () => {
  it("台幣無小數、美元兩位", () => {
    expect(formatMoney(123_456_789_012)).toBe("NT$123,456,789,012")
    expect(formatMoney(268.42, { currency: "USD" })).toBe("US$268.42")
  })
  it("正負號", () => {
    expect(formatMoney(40_320, { signed: true })).toBe("+NT$40,320")
    expect(formatMoney(-7_500, { signed: true })).toBe(`${MINUS}NT$7,500`)
    expect(formatMoney(0, { signed: true })).toBe("NT$0")
  })
})

describe("百分比", () => {
  it("比率轉百分比並加正負號", () => {
    expect(formatPercent(0.0124)).toBe("+1.24%")
    expect(formatPercent(-0.0085)).toBe(`${MINUS}0.85%`)
    expect(formatPercent(0)).toBe("0.00%")
    expect(formatPercent(0.4955, { signed: false, decimals: 1 })).toBe("49.6%")
  })
  it("無資料顯示破折號", () => {
    expect(formatPercent(null)).toBe("—")
    expect(formatPercent(undefined)).toBe("—")
  })
})

describe("價格", () => {
  it("台股：千元以上整數價不帶小數", () => {
    expect(formatPrice(1085)).toBe("1,085")
    expect(formatPrice(22.86)).toBe("22.86")
    expect(formatPrice(612.5)).toBe("612.50")
    expect(formatPrice(268.42, "US")).toBe("268.42")
  })
  it("河流圖價位", () => {
    expect(formatPriceLevel(1500.8)).toBe("1,501")
    expect(formatPriceLevel(857.6)).toBe("857.6")
    expect(formatPriceLevel(5.04)).toBe("5.04")
  })
})

describe("漲跌慣例", () => {
  it("台灣紅漲綠跌、美國綠漲紅跌", () => {
    expect(conventionColors("tw")).toEqual({ up: "red", down: "green" })
    expect(conventionColors("us")).toEqual({ up: "green", down: "red" })
  })
  it("方向與符號：顏色之外一定有 ▲▼", () => {
    expect(direction(15)).toBe("up")
    expect(direction(-0.01)).toBe("down")
    expect(direction(0)).toBe("flat")
    expect(direction(null)).toBe("flat")
    expect(directionGlyph("up")).toBe("▲")
    expect(directionGlyph("down")).toBe("▼")
    expect(directionGlyph("flat")).toBe("")
    expect(toneClass("up")).toBe("text-rise")
    expect(toneClass("down")).toBe("text-fall")
    expect(toneClass("flat")).toBe("text-muted-foreground")
  })
})

describe("隱私遮罩", () => {
  it("遮蔽時回傳固定寬度，不洩漏位數", () => {
    expect(mask("NT$123,456,789,012", true)).toBe(MASK)
    expect(mask("NT$12", true)).toBe(MASK)
    expect(mask("NT$12", false)).toBe("NT$12")
  })
})

describe("日期（台北時區）", () => {
  it("日期格式", () => {
    expect(formatDate("2026-11-11")).toBe("2026/11/11")
    expect(formatDateShort("2026-11-11")).toBe("11/11（三）")
    expect(formatDateShort("2026-11-18", false)).toBe("11/18")
  })
  it("ISO 時間轉成台北時間", () => {
    expect(formatDateTime("2026-11-11T13:30:00+08:00")).toBe("11/11 13:30")
    expect(formatDateTime("2026-11-11T05:30:00Z")).toBe("11/11 13:30")
  })
  it("倒數天數", () => {
    expect(formatDaysUntil("2026-11-11", "2026-11-11")).toBe("今天")
    expect(formatDaysUntil("2026-11-12", "2026-11-11")).toBe("明天")
    expect(formatDaysUntil("2026-11-18", "2026-11-11")).toBe("7 天後")
  })
})
