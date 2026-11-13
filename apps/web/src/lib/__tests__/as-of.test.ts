import { describe, expect, it } from "vitest"
import type { MarketStatus } from "@/api/types"
import { mockMarketNow, mockMarketStatus } from "@/api/mock/market-status"
import { asOfLabel, closeDay, closeLabel, closeNote, closeState, dayWord, ledgerAsOf, twseLiveQuoteUrl, withDayWord } from "../as-of"

/**
 * 收盤價的標示（api-contract「收盤價的標示與盤中狀態」）：沒有盤中即時報價，
 * 盤中、收盤後今天的還沒公布時多一行說明；其他時候只標「收盤價・日期」。
 */
const tw = (date: string, o: Partial<MarketStatus["tw"]> = {}): MarketStatus["tw"] => ({ date, is_trading_day: true, is_open: false, open: "09:00", close: "13:30", ...o })
const at = (day: string, time: string) => new Date(`${day}T${time}:00+08:00`)
/** 11/12（四）的收盤價 */
const THU_CLOSE = "2026-11-12T13:30:00+08:00"

describe("closeState：盤中／收盤後還沒公布／其他", () => {
  it("盤中（交易日 09:00–13:30）：手上還是上一個交易日的收盤價", () => {
    expect(closeState(tw("2026-11-13", { is_open: true }), THU_CLOSE, at("2026-11-13", "09:00"))).toBe("open")
    expect(closeState(tw("2026-11-13", { is_open: true }), THU_CLOSE, at("2026-11-13", "13:29"))).toBe("open")
  })

  it("剛好 13:30：已經收盤，今天的收盤價還沒公布", () => {
    expect(closeState(tw("2026-11-13"), THU_CLOSE, at("2026-11-13", "13:30"))).toBe("pending")
    expect(closeState(tw("2026-11-13"), THU_CLOSE, at("2026-11-13", "23:59"))).toBe("pending")
  })

  it("報價的日期就是今天：最新的收盤價已經進來，不加說明（盤中、收盤後都一樣）", () => {
    const today = "2026-11-13T13:30:00+08:00"
    expect(closeState(tw("2026-11-13"), today, at("2026-11-13", "20:00"))).toBe("settled")
    expect(closeState(tw("2026-11-13", { is_open: true }), today, at("2026-11-13", "10:00"))).toBe("settled")
    // 示範資料的預設情境：今天 11/12、剛好 13:30、收盤價也是 11/12
    expect(closeState(tw("2026-11-12"), THU_CLOSE, at("2026-11-12", "13:30"))).toBe("settled")
  })

  it("假日的平日（不是交易日）：不說「還沒公布」", () => {
    // 2027-01-01（五）元旦休市，手上是 12/31 的收盤價
    const holiday = tw("2027-01-01", { is_trading_day: false })
    expect(closeState(holiday, "2026-12-31T13:30:00+08:00", at("2027-01-01", "10:30"))).toBe("settled")
    expect(closeState(holiday, "2026-12-31T13:30:00+08:00", at("2027-01-01", "15:00"))).toBe("settled")
  })

  it("週末：不是交易日，只標收盤價的日期", () => {
    const saturday = tw("2026-11-14", { is_trading_day: false })
    expect(closeState(saturday, "2026-11-13T13:30:00+08:00", at("2026-11-14", "11:00"))).toBe("settled")
    expect(closeState(tw("2026-11-15", { is_trading_day: false }), "2026-11-13T13:30:00+08:00", at("2026-11-15", "14:00"))).toBe("settled")
  })

  it("交易日還沒開盤（08:00）：昨天的收盤價就是最新的，不加說明", () => {
    expect(closeState(tw("2026-11-13"), THU_CLOSE, at("2026-11-13", "08:00"))).toBe("settled")
  })

  it("市場狀態還沒載入、報價沒有時間、本機時鐘和伺服器的日期對不上：都不加說明", () => {
    expect(closeState(undefined, THU_CLOSE, at("2026-11-13", "10:00"))).toBe("settled")
    expect(closeState(tw("2026-11-13", { is_open: true }), null, at("2026-11-13", "10:00"))).toBe("settled")
    expect(closeState(tw("2026-11-13"), THU_CLOSE, at("2026-11-14", "15:00"))).toBe("settled")
  })

  it("時間用台北時區判斷（UTC 的 05:30 是台北 13:30）", () => {
    expect(closeState(tw("2026-11-13"), THU_CLOSE, new Date("2026-11-13T05:30:00Z"))).toBe("pending")
    expect(closeState(tw("2026-11-13"), THU_CLOSE, new Date("2026-11-13T05:29:00Z"))).toBe("settled")
    // 報價的 as_of 用 UTC 寫也一樣算台北的日期
    expect(closeDay("2026-11-12T05:30:00Z")).toBe("2026-11-12")
    expect(closeDay("2026-11-12T16:30:00Z")).toBe("2026-11-13")
  })

  it("mock 的三個情境（?market=closed|open|pending）和它的時鐘對得起來", () => {
    for (const [flag, state] of [["closed", "settled"], ["open", "open"], ["pending", "pending"]] as const) {
      expect(closeState(mockMarketStatus(flag).tw, THU_CLOSE, mockMarketNow(flag))).toBe(state)
    }
  })
})

describe("標示的文字", () => {
  it("價格：「收盤價・11/12（四）」；說明照合約的字", () => {
    expect(closeLabel(THU_CLOSE)).toBe("收盤價・11/12（四）")
    expect(closeNote("open", THU_CLOSE)).toBe("盤中不更新：這是 11/12（四）的收盤價。")
    expect(closeNote("pending", THU_CLOSE)).toBe("今天的收盤價還沒公布，這是 11/12（四）的收盤價。")
    expect(closeNote("settled", THU_CLOSE)).toBeNull()
    expect(closeLabel(null)).toBe("收盤價")
    expect(closeNote("open", null)).toBeNull()
  })

  it("帳本主數字旁的三種寫法", () => {
    expect(ledgerAsOf("open", THU_CLOSE)).toBe("11/12 收盤・盤中不更新")
    expect(ledgerAsOf("pending", THU_CLOSE)).toBe("11/12 收盤・今天的還沒公布")
    expect(ledgerAsOf("settled", "2026-11-13T13:30:00+08:00")).toBe("11/13 收盤")
    expect(ledgerAsOf("settled", null)).toBe("")
  })

  it("「今日」只在收盤價是今天的時候寫，否則寫那個日期", () => {
    expect(dayWord(THU_CLOSE, "2026-11-12")).toBe("今日")
    expect(dayWord(THU_CLOSE, "2026-11-13")).toBe("11/12")
    expect(dayWord(null, "2026-11-13")).toBe("今日")
    expect(withDayWord("今日漲跌", "今日")).toBe("今日漲跌")
    expect(withDayWord("今日漲跌", "11/12")).toBe("11/12 漲跌")
    expect(withDayWord("今日損益", "11/12")).toBe("11/12 損益")
    expect(withDayWord("今日", "11/12")).toBe("11/12")
    expect(withDayWord("收盤價", "11/12")).toBe("收盤價")
  })

  it("證交所的連結只是網址（帶代號），不是 API", () => {
    expect(twseLiveQuoteUrl("2330")).toBe("https://mis.twse.com.tw/stock/fibest.jsp?stock=2330")
    expect(twseLiveQuoteUrl("00679B")).toBe("https://mis.twse.com.tw/stock/fibest.jsp?stock=00679B")
  })

  it("沒有任何「盤中・延遲」「即時」的寫法：其他市場的時間一律是「收盤」", () => {
    // 台北 10:42 的時間以前會寫成「10:42 盤中・延遲」
    expect(asOfLabel("2026-11-12T10:42:00+08:00")).toBe("11/12 10:42 收盤")
    expect(asOfLabel("2026-11-12T05:00:00+08:00")).toBe("11/12 05:00 收盤")
    expect(asOfLabel(null)).toBe("")
    for (const text of [closeLabel(THU_CLOSE), closeNote("open", THU_CLOSE), closeNote("pending", THU_CLOSE), ledgerAsOf("open", THU_CLOSE), ledgerAsOf("pending", THU_CLOSE)]) {
      expect(text).not.toMatch(/延遲|即時/)
    }
  })
})
