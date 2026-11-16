import { describe, expect, it } from "vitest"
import type { MarketStatus, TwClose } from "@/api/types"
import { mockCloses, mockMarketNow, mockMarketStatus } from "@/api/mock/market-status"
import { closeLine, closeNote, closesChanged, closeState, expectedWindow, indexNote, ledgerBoardDays, type BoardDay } from "../as-of"

/**
 * 預計更新的時間（產品負責人 2026-11-16）：上市、上櫃的收盤價各自什麼時候進來，由後端依開著的來源給時間窗
 * （`market-status` 的 `tw.closes`）；畫面寫「今天的收盤價預計下午 2:00–2:30 更新」。
 * 時間是 2026-11-16（一）。
 */
const at = (day: string, time: string) => new Date(`${day}T${time}:00+08:00`)
const iso = (day: string, time: string) => `${day}T${time}:00+08:00`
const MON = "2026-11-16"
const TUE = "2026-11-17"
/** 上週五 11/13 的收盤價 */
const FRI_CLOSE = "2026-11-13T13:30:00+08:00"

const close = (market: TwClose["market"], o: Partial<TwClose> = {}): TwClose => ({
  market, session: MON, stored: false, latest: "2026-11-13", interim: false, expected_from: null, expected_to: null, ...o,
})
const win = (day: string, from: string, to: string) => ({ expected_from: iso(day, from), expected_to: iso(day, to) })
/** 上市下午那一批（證交所的下載網址）、上櫃晚上那一批 */
const TWSE_PM = win(MON, "14:00", "14:30")
const TPEX_EVE = win(MON, "20:30", "23:45")
const TWSE_DAWN = win(TUE, "05:20", "05:40")

const status = (date: string, closes: TwClose[], o: Partial<MarketStatus["tw"]> = {}): MarketStatus["tw"] => ({
  date, is_trading_day: true, is_open: false, open: "09:00", close: "13:30", closes, ...o,
})

describe("expectedWindow：時間窗寫成字", () => {
  it("下午、今晚、清晨；12 小時制", () => {
    expect(expectedWindow(TWSE_PM, at(MON, "13:40"))).toEqual({ full: "下午 2:00–2:30", short: "下午 2:30 前" })
    expect(expectedWindow(TPEX_EVE, at(MON, "13:40"))).toEqual({ full: "今晚 8:30–11:45", short: "今晚" })
    expect(expectedWindow(TWSE_DAWN, at(MON, "21:00"))?.full).toBe("明天清晨 5:20–5:40")
    // 過了半夜：同一天的清晨
    expect(expectedWindow(TWSE_DAWN, at(TUE, "01:30"))).toEqual({ full: "清晨 5:20–5:40", short: "清晨 5:40 前" })
  })

  it("已經在時間窗裡：只寫結束的時間；時間窗過了：null（不寫一個已經過去的時間）", () => {
    expect(expectedWindow(TWSE_PM, at(MON, "14:10"))).toEqual({ full: "下午 2:30 前", short: "下午 2:30 前" })
    expect(expectedWindow(TWSE_PM, at(MON, "14:31"))).toBeNull()
    expect(expectedWindow({ expected_from: null, expected_to: null }, at(MON, "14:00"))).toBeNull()
    expect(expectedWindow(undefined, at(MON, "14:00"))).toBeNull()
  })

  it("跨過半夜、更遠的日子", () => {
    expect(expectedWindow({ expected_from: iso(MON, "23:30"), expected_to: iso(TUE, "01:30") }, at(MON, "22:00"))?.full).toBe("今晚 11:30 到半夜 1:30")
    expect(expectedWindow(win(TUE, "00:00", "01:30"), at(MON, "23:50"))?.full).toBe("半夜 12:00–1:30")
    expect(expectedWindow(win(TUE, "03:00", "04:00"), at(MON, "23:50"))?.full).toBe("凌晨 3:00–4:00")
    // 週五的收盤週六清晨沒進來：下一次是週一清晨（從週六晚上看）
    expect(expectedWindow(win("2026-11-16", "05:20", "05:40"), at("2026-11-14", "21:00"))?.full).toBe("11/16 清晨 5:20–5:40")
    expect(expectedWindow(win("2026-11-15", "05:20", "05:40"), at("2026-11-14", "21:00"))?.full).toBe("明天清晨 5:20–5:40")
  })
})

describe("closeState／closeNote：每個市場自己的收盤（tw.closes）", () => {
  it("收盤後：上市下午、上櫃今晚", () => {
    const m = status(MON, [close("TWSE", TWSE_PM), close("TPEX", TPEX_EVE)])
    const now = at(MON, "13:40")
    expect(closeState(m, FRI_CLOSE, now, "TWSE")).toBe("pending")
    expect(closeNote("pending", FRI_CLOSE, m.closes![0], now)).toBe("今天的收盤價預計下午 2:00–2:30 更新")
    expect(closeNote("pending", FRI_CLOSE, m.closes![1], now)).toBe("今天的收盤價預計今晚 8:30–11:45 更新")
    expect(closeNote("pending", FRI_CLOSE, m.closes![0], at(MON, "14:12"))).toBe("今天的收盤價預計下午 2:30 前更新")
  })

  it("半夜以後還在等前一個交易日的：說明不會不見（11/16 的收盤價還沒公布，預計清晨…）", () => {
    // 週二 01:30：今天（11/17）是交易日、還沒開盤；11/16 的上市收盤價還沒進來
    const m = status(TUE, [close("TWSE", TWSE_DAWN), close("TPEX", { stored: true, latest: MON })])
    const now = at(TUE, "01:30")
    expect(closeState(m, FRI_CLOSE, now, "TWSE")).toBe("pending")
    expect(closeNote("pending", FRI_CLOSE, m.closes![0], now)).toBe("11/16 的收盤價還沒公布，預計清晨 5:20–5:40 更新")
    // 沒有時間窗（來源都過了）：只說還沒公布
    expect(closeNote("pending", FRI_CLOSE, close("TWSE"), now)).toBe("11/16 的收盤價還沒公布")
    // 上櫃已經存了：上櫃股票是 11/16 的，不加說明
    expect(closeState(m, "2026-11-16T13:30:00+08:00", now, "TPEX")).toBe("settled")
    // 舊版後端（沒有 closes）的判斷：過了半夜就不說了——這是要修的那個問題
    expect(closeState({ ...m, closes: undefined }, FRI_CLOSE, now, "TWSE")).toBe("settled")
  })

  it("那個市場的收盤價已經存了，這一檔還是舊的（停牌、沒有成交）：不說「還沒公布」", () => {
    const m = status(MON, [close("TWSE", { stored: true, latest: MON })])
    expect(closeState(m, FRI_CLOSE, at(MON, "15:00"), "TWSE")).toBe("settled")
  })

  it("盤中照舊；今天不是交易日、也沒有欠著的收盤價：不加說明", () => {
    const open = status(MON, [close("TWSE", { session: "2026-11-13", stored: true })], { is_open: true })
    expect(closeState(open, FRI_CLOSE, at(MON, "10:00"), "TWSE")).toBe("open")
    expect(closeNote("open", FRI_CLOSE, open.closes![0], at(MON, "10:00"))).toBe("盤中不更新")
    const sat = status("2026-11-14", [close("TWSE", { session: "2026-11-13", stored: true, latest: "2026-11-13" })], { is_trading_day: false })
    expect(closeState(sat, FRI_CLOSE, at("2026-11-14", "11:00"), "TWSE")).toBe("settled")
  })
})

describe("closeLine：帳本（上市、上櫃一起）", () => {
  const both = (twse: string, tpex: string): BoardDay[] => [{ board: "TWSE", day: twse }, { board: "TPEX", day: tpex }]

  it("13:40 兩個市場都在等，時間窗不同：一行並列（上市寫到幾點、上櫃寫今晚）；「今日」換成日期", () => {
    const m = status(MON, [close("TWSE", TWSE_PM), close("TPEX", TPEX_EVE)])
    expect(closeLine(m, both("2026-11-13", "2026-11-13"), FRI_CLOSE, at(MON, "13:40"), MON)).toEqual({
      label: "11/13 收盤", note: "上市預計下午 2:30 前更新・上櫃預計今晚更新", day: "11/13",
    })
  })

  it("15:00 上市進來了、上櫃還沒：日期分開寫，只說上櫃；「今日」不寫（每一檔是它自己那天的漲跌）", () => {
    const m = status(MON, [close("TWSE", { stored: true, latest: MON }), close("TPEX", TPEX_EVE)])
    expect(closeLine(m, both(MON, "2026-11-13"), FRI_CLOSE, at(MON, "15:00"), MON)).toEqual({
      label: "上市 11/16・上櫃 11/13 收盤", note: "上櫃預計今晚 8:30–11:45 更新", day: "當日",
    })
  })

  it("每個市場都是今天的收盤才寫「今日」", () => {
    const m = status(MON, [close("TWSE", { stored: true, latest: MON }), close("TPEX", { stored: true, latest: MON })])
    expect(closeLine(m, both(MON, MON), FRI_CLOSE, at(MON, "23:50"), MON)).toEqual({ label: "11/16 收盤", note: null, day: "今日" })
  })

  it("只有上市的帳本、或兩個市場等同一個時間窗：不寫市場的名稱", () => {
    const m = status(MON, [close("TWSE", TWSE_PM), close("TPEX", TPEX_EVE)])
    expect(closeLine(m, [{ board: "TWSE", day: "2026-11-13" }], FRI_CLOSE, at(MON, "13:40"), MON).note).toBe("今天的預計下午 2:00–2:30 更新")
    const evening = status(MON, [close("TWSE", TPEX_EVE), close("TPEX", TPEX_EVE)])
    expect(closeLine(evening, both("2026-11-13", "2026-11-13"), FRI_CLOSE, at(MON, "21:00"), MON).note).toBe("今天的預計今晚 11:45 前更新")
  })

  it("半夜以後：寫在等的是哪一天", () => {
    const m = status(TUE, [close("TWSE", TWSE_DAWN), close("TPEX", TWSE_DAWN)])
    expect(closeLine(m, both("2026-11-13", "2026-11-13"), FRI_CLOSE, at(TUE, "01:30"), TUE)).toEqual({
      label: "11/13 收盤", note: "11/16 的預計清晨 5:20–5:40 更新", day: "11/13",
    })
    const split = status(TUE, [close("TWSE", TWSE_DAWN), close("TPEX")])
    expect(closeLine(split, both("2026-11-13", "2026-11-13"), FRI_CLOSE, at(TUE, "01:30"), TUE).note).toBe("11/16 的收盤：上市預計清晨 5:40 前更新・上櫃還沒公布")
    const one = status(TUE, [close("TWSE", TWSE_DAWN), close("TPEX", { stored: true, latest: MON })])
    expect(closeLine(one, both("2026-11-13", MON), FRI_CLOSE, at(TUE, "01:30"), TUE).note).toBe("上市 11/16 的收盤預計清晨 5:20–5:40 更新")
  })

  it("盤中：「11/13 收盤・盤中不更新」，沒有預計更新的說明", () => {
    const m = status(MON, [close("TWSE", { session: "2026-11-13", stored: true }), close("TPEX", { session: "2026-11-13", stored: true })], { is_open: true })
    expect(closeLine(m, both("2026-11-13", "2026-11-13"), FRI_CLOSE, at(MON, "10:00"), MON)).toEqual({ label: "11/13 收盤・盤中不更新", note: null, day: "11/13" })
  })

  it("持股還沒載入（不知道有哪些市場）：哪個市場在等就說哪個", () => {
    const m = status(MON, [close("TWSE", { stored: true, latest: MON }), close("TPEX", TPEX_EVE)])
    expect(closeLine(m, [], FRI_CLOSE, at(MON, "15:00"), MON).note).toBe("今天的預計今晚 8:30–11:45 更新")
  })

  it("舊版後端（沒有 closes）：照舊「今天的還沒公布」", () => {
    const m = status(MON, [])
    delete m.closes
    expect(closeLine(m, both("2026-11-13", "2026-11-13"), FRI_CLOSE, at(MON, "15:00"), MON).note).toBe("今天的還沒公布")
  })
})

describe("ledgerBoardDays：帳本裡上市、上櫃各自的收盤日", () => {
  it("每個市場取最新的那天；停牌的一檔、美股、沒有價格的不影響", () => {
    const holdings = [
      { market: "TWSE" as const, price: 1085, price_date: MON },
      { market: "TWSE" as const, price: 12, price_date: "2026-11-10" },
      { market: "TPEX" as const, price: 300, price_date: "2026-11-13" },
      { market: "US" as const, price: 356, price_date: "2026-11-13" },
      { market: "TPEX" as const, price: null, price_date: null },
    ]
    // `oldest`：最舊的那天（晚上只存了暫時收盤價時看 ETF 是不是還在等，見下面）
    expect(ledgerBoardDays(holdings, FRI_CLOSE)).toEqual([{ board: "TWSE", day: MON, oldest: "2026-11-10" }, { board: "TPEX", day: "2026-11-13" }])
    // 舊版後端沒有 price_date：用 as_of 的台北日期
    expect(ledgerBoardDays([{ market: "TPEX", price: 300 }], FRI_CLOSE)).toEqual([{ board: "TPEX", day: "2026-11-13" }])
    expect(ledgerBoardDays(undefined, FRI_CLOSE)).toEqual([])
  })
})

describe("closesChanged：收盤價進來時重新讀帳本", () => {
  const before = [close("TWSE", TWSE_PM), close("TPEX", TPEX_EVE)]
  it("上市進來了（stored、latest 變了）：要重新讀", () => {
    expect(closesChanged(before, [close("TWSE", { stored: true, latest: MON }), close("TPEX", TPEX_EVE)])).toBe(true)
  })
  it("暫時的收盤價被官方檔覆蓋（interim 變了）：要重新讀", () => {
    const interim = [close("TWSE", { stored: true, latest: MON, interim: true })]
    expect(closesChanged(interim, [close("TWSE", { stored: true, latest: MON, interim: false })])).toBe(true)
  })
  it("第一次、只是時間窗換了、13:30 換成等今天的：不算", () => {
    expect(closesChanged(undefined, before)).toBe(false)
    expect(closesChanged(before, [close("TWSE", TPEX_EVE), close("TPEX", TPEX_EVE)])).toBe(false)
    const yesterday = [close("TWSE", { session: "2026-11-13", stored: true, latest: "2026-11-13" })]
    expect(closesChanged(yesterday, [close("TWSE", TWSE_PM)])).toBe(false)
  })
})

describe("mock：時間窗跟著示範的時鐘", () => {
  it("13:40 上市下午、上櫃今晚；晚上 9 點都等晚上那一批；隔天凌晨 2 點上市等清晨、上櫃沒有時間窗", () => {
    const pending = mockMarketStatus("pending").tw.closes!
    expect(pending.map((c) => [c.market, c.session, c.stored, c.expected_from, c.expected_to])).toEqual([
      ["TWSE", "2026-11-13", false, "2026-11-13T14:00:00+08:00", "2026-11-13T14:30:00+08:00"],
      ["TPEX", "2026-11-13", false, "2026-11-13T20:30:00+08:00", "2026-11-13T23:45:00+08:00"],
    ])
    expect(mockMarketStatus("evening").tw.closes!.map((c) => c.expected_from)).toEqual(["2026-11-13T20:30:00+08:00", "2026-11-13T20:30:00+08:00"])
    const night = mockMarketStatus("night")
    expect(night.tw.date).toBe("2026-11-14")
    expect(night.tw.closes!.map((c) => [c.session, c.expected_from])).toEqual([["2026-11-13", "2026-11-14T05:20:00+08:00"], ["2026-11-13", null]])
    expect(closeNote("pending", "2026-11-12T13:30:00+08:00", night.tw.closes![0], mockMarketNow("night"))).toBe("11/13 的收盤價還沒公布，預計清晨 5:20–5:45 更新")
    // 預設與盤中：最新的收盤價已經進來，沒有時間窗
    for (const flag of ["closed", "open"] as const) expect(mockMarketStatus(flag).tw.closes!.every((c) => c.stored && c.expected_from === null)).toBe(true)
    // 存到那一天：不再等
    expect(mockCloses(at("2026-11-13", "15:00"), "2026-11-13").every((c) => c.stored)).toBe(true)
  })
})

/**
 * 2026-11-16 審查：晚上的暫時收盤價（shioaji-data）沒有 ETF，後端卻把整個市場標成「已存」——ETF 默默顯示前一天的價格、
 * 帳本還寫「今日」。後端現在在只存了暫時收盤價時（`interim`）給官方檔的時間窗。
 */
describe("只存了晚上的暫時收盤價（interim）：ETF 還在等官方檔", () => {
  const TPEX_OFFICIAL = win(MON, "23:15", "23:45")
  const interim = close("TPEX", { stored: true, latest: MON, interim: true, ...TPEX_OFFICIAL })
  const m = status(MON, [close("TWSE", { stored: true, latest: MON }), interim])

  it("個股頁：ETF（前一天的價格）寫官方檔預計幾點更新；有暫時收盤價的股票不寫（也不標「暫時」）", () => {
    const now = at(MON, "21:00")
    expect(closeState(m, FRI_CLOSE, now, "TPEX")).toBe("pending")
    expect(closeNote("pending", FRI_CLOSE, interim, now)).toBe("今天的收盤價預計今晚 11:15–11:45 更新")
    expect(closeState(m, `${MON}T13:30:00+08:00`, now, "TPEX")).toBe("settled")
    // 官方檔進來以後（interim 變回 false）：舊的就是停牌、沒有成交，不說
    const official = status(MON, [close("TWSE", { stored: true, latest: MON }), close("TPEX", { stored: true, latest: MON })])
    expect(closeState(official, FRI_CLOSE, now, "TPEX")).toBe("settled")
  })

  it("帳本：那個市場有 ETF 還是前一天的——說預計幾點更新，「今日」改「當日」", () => {
    const boards: BoardDay[] = [{ board: "TWSE", day: MON }, { board: "TPEX", day: MON, oldest: "2026-11-13" }]
    expect(closeLine(m, boards, FRI_CLOSE, at(MON, "21:00"), MON)).toEqual({ label: "11/16 收盤", note: "上櫃預計今晚 11:15–11:45 更新", day: "當日" })
    // 全部都有暫時收盤價（沒有 ETF）：照舊
    expect(closeLine(m, [{ board: "TWSE", day: MON }, { board: "TPEX", day: MON }], FRI_CLOSE, at(MON, "21:00"), MON)).toEqual({ label: "11/16 收盤", note: null, day: "今日" })
    // 不是暫時的（官方檔）：舊的一檔是停牌，不影響
    const official = status(MON, [close("TWSE", { stored: true, latest: MON }), close("TPEX", { stored: true, latest: MON })])
    expect(closeLine(official, boards, FRI_CLOSE, at(MON, "23:50"), MON)).toEqual({ label: "11/16 收盤", note: null, day: "今日" })
  })
})

/** 2026-11-16 實測：上市個股的下載檔進來了，3 秒後指數檔被擋（307）——加權指數停在上一個交易日，要說什麼時候更新 */
describe("indexNote：加權指數還沒進來", () => {
  const index = (o: Partial<NonNullable<TwClose["index"]>> = {}) => ({ stored: false, latest: "2026-11-13", expected_from: iso(TUE, "05:20"), expected_to: iso(TUE, "05:45"), ...o })
  it("上市個股進來了、指數還沒：寫指數預計幾點更新；半夜以後寫哪一天的", () => {
    const twse = close("TWSE", { stored: true, latest: MON, index: index() })
    expect(indexNote(twse, at(MON, "15:50"))).toBe("加權指數預計明天清晨 5:20–5:45 更新")
    expect(indexNote(twse, at(TUE, "00:30"))).toBe("加權指數 11/16 的收盤預計清晨 5:20–5:45 更新")
    expect(indexNote(twse, at(TUE, "06:00"))).toBe("加權指數還沒更新")
  })
  it("指數也進來了、上市個股還在等（標題旁已經說了）、上櫃、舊版後端：不寫", () => {
    expect(indexNote(close("TWSE", { stored: true, latest: MON, index: index({ stored: true, latest: MON }) }), at(MON, "15:50"))).toBeNull()
    expect(indexNote(close("TWSE", { index: index() }), at(MON, "15:50"))).toBeNull()
    expect(indexNote(close("TPEX", { stored: true, latest: MON, index: null }), at(MON, "15:50"))).toBeNull()
    expect(indexNote(close("TWSE", { stored: true, latest: MON }), at(MON, "15:50"))).toBeNull()
  })
})
