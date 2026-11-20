import { describe, expect, it } from "vitest"
import { heroCloseLabel, pnlDates } from "../close-label"

/**
 * 帳本的日期寫法（內頁重新設計 2026-11-21）：
 * - 總資產那一行「收盤價・11/12（四）」，和個股頁同一個寫法
 * - 今日損益那一盤的 meta：每個市場各自的收盤日，美股寫紐約的日期（不說今天）
 */
const tw = (day: string, market: "TWSE" | "TPEX" = "TWSE") => ({ market, price: 100, price_date: day }) as const
const us = (day: string | null) => ({ market: "US", price: 100, price_date: day }) as const

describe("總資產那一行的日期", () => {
  it("同一天：「收盤價・11/12（四）」；盤中多「・盤中不更新」", () => {
    expect(heroCloseLabel({ boards: [{ board: "TWSE", day: "2026-11-12" }], asOf: null, usDay: null, intraday: false })).toBe("收盤價・11/12（四）")
    expect(heroCloseLabel({ boards: [{ board: "TWSE", day: "2026-11-12" }, { board: "TPEX", day: "2026-11-12" }], asOf: null, usDay: null, intraday: true })).toBe(
      "收盤價・11/12（四）・盤中不更新",
    )
  })
  it("上市、上櫃不同天：兩個日期不寫星期", () => {
    const label = heroCloseLabel({ boards: [{ board: "TWSE", day: "2026-11-16" }, { board: "TPEX", day: "2026-11-13" }], asOf: null, usDay: null, intraday: false })
    expect(label).toBe("收盤價・上市 11/16・上櫃 11/13")
  })
  it("只有美股：紐約的日期「收盤價・11/11（美東）」，不套盤中", () => {
    expect(heroCloseLabel({ boards: [], asOf: null, usDay: "2026-11-11", intraday: true })).toBe("收盤價・11/11（美東）")
  })
  it("還不知道持股：看 as_of；什麼都沒有時是空的", () => {
    expect(heroCloseLabel({ boards: [], asOf: "2026-11-12T13:30:00+08:00", usDay: null, intraday: false })).toBe("收盤價・11/12（四）")
    expect(heroCloseLabel({ boards: [], asOf: null, usDay: null, intraday: false })).toBe("")
  })
})

describe("今日損益的 meta：每個市場的日期分開寫", () => {
  it("只有台股：「11/12（四）」；上市、上櫃不同天分開寫", () => {
    expect(pnlDates([tw("2026-11-12"), tw("2026-11-12", "TPEX")], null)).toBe("11/12（四）")
    expect(pnlDates([tw("2026-11-16"), tw("2026-11-13", "TPEX")], null)).toBe("上市 11/16・上櫃 11/13")
  })
  it("只有美股：「11/11（美東）」", () => {
    expect(pnlDates([us("2026-11-10"), us("2026-11-11")], null)).toBe("11/11（美東）")
  })
  it("台股和美股：「台股 11/12・美股 11/11（美東）」——美股的漲跌不是今天的", () => {
    expect(pnlDates([tw("2026-11-12"), us("2026-11-11")], null)).toBe("台股 11/12・美股 11/11（美東）")
    expect(pnlDates([tw("2026-11-16"), tw("2026-11-13", "TPEX"), us("2026-11-13")], null)).toBe("上市 11/16・上櫃 11/13・美股 11/13（美東）")
  })
  it("沒有收盤價的不算；美股沒有日期時不猜", () => {
    expect(pnlDates([tw("2026-11-12"), { market: "US", price: null, price_date: null }], null)).toBe("11/12（四）")
    expect(pnlDates([tw("2026-11-12"), us(null)], null)).toBe("台股 11/12・美股（美東）")
    expect(pnlDates([], null)).toBe("")
  })
})
