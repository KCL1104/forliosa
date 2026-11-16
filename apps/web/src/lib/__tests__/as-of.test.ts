import { describe, expect, it } from "vitest"
import type { MarketStatus } from "@/api/types"
import { mockMarketNow, mockMarketStatus } from "@/api/mock/market-status"
import { asOfLabel, closeDay, closeLabel, closeLine, closeNote, closeState, dayWord, ledgerUsCloseDay, twseLiveQuoteUrl, withDayWord } from "../as-of"

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

  it("mock 的情境（?market=closed|open|pending|evening|night）和它的時鐘對得起來", () => {
    for (const [flag, state] of [["closed", "settled"], ["open", "open"], ["pending", "pending"], ["evening", "pending"], ["night", "pending"]] as const) {
      expect(closeState(mockMarketStatus(flag).tw, THU_CLOSE, mockMarketNow(flag), "TWSE")).toBe(state)
      expect(closeState(mockMarketStatus(flag).tw, THU_CLOSE, mockMarketNow(flag), "TPEX")).toBe(state)
    }
  })
})

describe("標示的文字", () => {
  it("價格：「收盤價・11/12（四）」；說明照合約的字", () => {
    expect(closeLabel(THU_CLOSE)).toBe("收盤價・11/12（四）")
    // 說明只有一句，不重複日期（上面一行已經寫了「收盤價・11/12（四）」）
    expect(closeNote("open", THU_CLOSE)).toBe("盤中不更新")
    expect(closeNote("pending", THU_CLOSE)).toBe("今天的收盤價還沒公布")
    expect(closeNote("settled", THU_CLOSE)).toBeNull()
    expect(closeLabel(null)).toBe("收盤價")
    expect(closeNote("open", null)).toBeNull()
  })

  it("帳本主數字旁的寫法（舊版後端沒有 closes）：盤中、還沒公布、最新", () => {
    const line = (m: MarketStatus["tw"], asOf: string | null, now: Date) => closeLine(m, [], asOf, now, m.date)
    expect(line(tw("2026-11-13", { is_open: true }), THU_CLOSE, at("2026-11-13", "10:00"))).toEqual({ label: "11/12 收盤・盤中不更新", note: null, day: "11/12" })
    expect(line(tw("2026-11-13"), THU_CLOSE, at("2026-11-13", "15:00"))).toEqual({ label: "11/12 收盤", note: "今天的還沒公布", day: "11/12" })
    expect(line(tw("2026-11-13"), "2026-11-13T13:30:00+08:00", at("2026-11-13", "20:00"))).toEqual({ label: "11/13 收盤", note: null, day: "今日" })
    expect(line(tw("2026-11-13"), null, at("2026-11-13", "20:00")).label).toBe("")
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
    // 上市、上櫃的日期不同（帳本）：「當日漲跌」
    expect(withDayWord("今日漲跌", "當日")).toBe("當日漲跌")
  })

  it("證交所的連結只是網址（帶代號；上市 tse、上櫃 otc），不是 API", () => {
    expect(twseLiveQuoteUrl("2330", "TWSE")).toBe("https://mis.twse.com.tw/stock/detail-item?id=tse_2330.tw&ex=tse&lang=zhHant")
    expect(twseLiveQuoteUrl("6488", "TPEX")).toBe("https://mis.twse.com.tw/stock/detail-item?id=otc_6488.tw&ex=otc&lang=zhHant")
    expect(twseLiveQuoteUrl("00679B", "TPEX")).toBe("https://mis.twse.com.tw/stock/detail-item?id=otc_00679B.tw&ex=otc&lang=zhHant")
  })

  it("沒有任何「盤中・延遲」「即時」的寫法：其他市場的時間一律是「收盤」", () => {
    // 台北 10:42 的時間以前會寫成「10:42 盤中・延遲」
    expect(asOfLabel("2026-11-12T10:42:00+08:00")).toBe("11/12 10:42 收盤")
    expect(asOfLabel("2026-11-12T05:00:00+08:00")).toBe("11/12 05:00 收盤")
    expect(asOfLabel(null)).toBe("")
    const open = closeLine(tw("2026-11-13", { is_open: true }), [], THU_CLOSE, at("2026-11-13", "10:00"), "2026-11-13")
    for (const text of [closeLabel(THU_CLOSE), closeNote("open", THU_CLOSE), closeNote("pending", THU_CLOSE), open.label]) {
      expect(text).not.toMatch(/延遲|即時/)
    }
  })
})

describe("ledgerUsCloseDay：帳本只有美股有價格時，那是紐約哪一天的收盤", () => {
  /** 紐約 11/13（五）16:00 的收盤＝台北 11/14（六）05:00 */
  const usSummary = { as_of: "2026-11-14T05:00:00+08:00" }
  const aapl = { market: "US" as const, price: 356.27, price_date: "2026-11-13" }
  const tsmc = { market: "TWSE" as const, price: 1085, price_date: "2026-11-13" }

  it("只有美股有價格：持股 price_date 最大的那天（不是台北的日期）", () => {
    expect(ledgerUsCloseDay(usSummary, [aapl])).toBe("2026-11-13")
    expect(ledgerUsCloseDay(usSummary, [{ ...aapl, price_date: "2026-11-12" }, aapl])).toBe("2026-11-13")
    // 還沒有收盤價的美股（price null）不影響
    expect(ledgerUsCloseDay(usSummary, [aapl, { market: "US", price: null, price_date: null }])).toBe("2026-11-13")
  })

  it("舊版後端沒有 price_date：由 summary.as_of 換算成紐約的日期（冬令、夏令）", () => {
    expect(ledgerUsCloseDay(usSummary, [{ market: "US", price: 356.27 }])).toBe("2026-11-13")
    expect(ledgerUsCloseDay({ as_of: "2026-07-02T04:00:00+08:00" }, [{ market: "US", price: 210, price_date: null }])).toBe("2026-07-01")
  })

  it("有任何一檔台股有價格、沒有持股、或全部都沒有價格：照台股（null）", () => {
    expect(ledgerUsCloseDay({ as_of: THU_CLOSE }, [aapl, tsmc])).toBeNull()
    expect(ledgerUsCloseDay({ as_of: THU_CLOSE }, [aapl, { ...tsmc, market: "TPEX" }])).toBeNull()
    expect(ledgerUsCloseDay({ as_of: THU_CLOSE }, [])).toBeNull()
    expect(ledgerUsCloseDay({ as_of: THU_CLOSE }, [{ market: "US", price: null, price_date: null }])).toBeNull()
    // 台股沒有價格（以成本計）、美股有：帳本的 as_of 是美股的收盤
    expect(ledgerUsCloseDay(usSummary, [aapl, { ...tsmc, price: null, price_date: null }])).toBe("2026-11-13")
  })

  it("持股還沒載入：as_of 正好是紐約 16:00 才當成美股的收盤（冬令、夏令）", () => {
    expect(ledgerUsCloseDay(usSummary, undefined)).toBe("2026-11-13")
    expect(ledgerUsCloseDay({ as_of: "2026-07-02T04:00:00+08:00" }, undefined)).toBe("2026-07-01")
    expect(ledgerUsCloseDay(undefined, undefined)).toBeNull()
    expect(ledgerUsCloseDay({ as_of: null }, undefined)).toBeNull()
  })

  it("持股還沒載入、全部都沒有價格：as_of 是「現在」，不當成美股（不會寫出週日的紐約日期）", () => {
    // 週一 11/16 10:00 台北＝紐約週日 11/15 21:00；配置裡只有美股（沒有價格的以成本計）
    const unpriced = { as_of: "2026-11-16T10:00:00+08:00", allocation: { by_market: [{ key: "US" }] } }
    expect(ledgerUsCloseDay(unpriced, undefined)).toBeNull()
    // 台股的收盤時刻（13:30 台北）也不是
    expect(ledgerUsCloseDay({ as_of: THU_CLOSE }, undefined)).toBeNull()
    // 差一秒也不是
    expect(ledgerUsCloseDay({ as_of: "2026-11-14T05:00:01+08:00" }, undefined)).toBeNull()
  })
})
