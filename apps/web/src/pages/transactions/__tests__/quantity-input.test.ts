import { describe, expect, it } from "vitest"
import { otherUnit, quantityError, toShares } from "../quantity-input"

/** 數量的輸入（產品負責人 2026-11-22）：欄位旁的「張｜股」，也可以直接寫「500股」「1張500股」 */
describe("數量：張｜股與直接寫單位", () => {
  it("沒寫單位照欄位的單位；寫了單位照寫的算（不看欄位的單位）", () => {
    expect(toShares("2", true)).toBe(2000)
    expect(toShares("0.195", true)).toBe(195)
    expect(toShares("195", false)).toBe(195)
    expect(toShares("500股", true)).toBe(500)
    expect(toShares("1張500股", false)).toBe(1500)
    expect(toShares("1 張 500 股", true)).toBe(1500)
    expect(toShares("1張500", true)).toBe(1500)
    expect(toShares("2張", false)).toBe(2000)
    expect(toShares("１張５００股", true)).toBe(1500)
    expect(toShares("1,500股", true)).toBe(1500)
    expect(toShares("股", true)).toBeNull()
    expect(toShares("500股2張", true)).toBeNull()
  })

  it("錯誤是短的標籤，照欄位的單位寫", () => {
    expect(quantityError("", true, false)).toBe("請輸入張數")
    expect(quantityError("股", false, false)).toBe("請輸入股數")
    expect(quantityError("0.0005", true, false)).toBe("張數最多寫到小數第三位（1 股）")
    expect(quantityError("1.0005張", false, false)).toBe("張數最多寫到小數第三位（1 股）")
    expect(quantityError("10.5", false, false)).toBe("台股股數必須是整數")
    expect(quantityError("1張10.5股", true, false)).toBe("台股股數必須是整數")
    expect(quantityError("1張500股", true, false)).toBeNull()
    expect(quantityError("195", false, false)).toBeNull()
    // 美股：股數可以有小數，沒有「張」
    expect(quantityError("10.5股", false, true)).toBeNull()
    expect(quantityError("1張", false, true)).toBe("請輸入股數")
  })

  it("欄位下面的換算：以張填或寫了單位的寫股數；以股填的整張才寫張數；美股不寫", () => {
    expect(otherUnit(2000, true, false)).toBe("2,000 股")
    expect(otherUnit(1500, false, false, "1張500股")).toBe("1,500 股")
    expect(otherUnit(500, true, false, "500股")).toBe("500 股")
    expect(otherUnit(195, false, false, "195")).toBeNull()
    expect(otherUnit(2000, false, false, "2000")).toBe("2 張")
    expect(otherUnit(10, false, true, "10股")).toBeNull()
  })
})
