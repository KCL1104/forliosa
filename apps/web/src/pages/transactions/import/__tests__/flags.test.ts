import { describe, expect, it } from "vitest"
import type { Account, ImportRow } from "@/api/types"
import {
  accountForBroker,
  editRow,
  isSkipped,
  mergeFlags,
  newFlagCodes,
  rowErrors,
  rowTotal,
  shortfallRow,
  skippedSummary,
  toCandidate,
  toDraftRow,
  totalsLine,
  unsupportedLine,
} from "../flags"

const row = (over: Partial<ImportRow["candidate"]> = {}, flags: ImportRow["flags"] = [], include = true, name = "鴻海"): ImportRow => ({
  row_id: "row_01",
  candidate: { account_id: "acc_1", symbol: "2317.TW", type: "buy", trade_date: "2026-10-01", quantity: 3000, price: 196, amount: 588000, fee: 837, tax: 0, is_day_trade: false, note: "", ...over },
  raw: { name, symbol_code: "2317", page: 1 },
  flags,
  include,
})
const flag = (code: string, message = code, severity: "error" | "warning" = "warning") => ({ code, message, severity })

describe("確認表的一列", () => {
  it("伺服器的一列變成可以改的列：數字加千分位、名稱用對帳單上的、預設勾不勾照伺服器", () => {
    const d = toDraftRow(row({ quantity: 3000, price: 1450.5, fee: 1234 }, [flag("margin")], true))
    expect(d).toMatchObject({ id: "row_01", include: true, type: "buy", date: "2026-10-01", qty: "3,000", price: "1,450.5", fee: "1,234", tax: "0", amount: 588000 })
    expect(d.symbol).toEqual({ symbol: "2317.TW", code: "2317", name: "鴻海", market: "TWSE" })
    expect(toDraftRow(row({ symbol: "6488.TWO" })).symbol?.market).toBe("TPEX")
    expect(toDraftRow(row({ symbol: null }, [flag("unknown_symbol")], false, "台積")).symbol).toBeNull()
  })

  it("改了股數或價格：對帳單的價金不再照送（伺服器重算）；改手續費不影響價金；改過的格子記下來（墨色）", () => {
    const d = toDraftRow(row())
    const fee = editRow(d, { fee: "900" })
    expect(fee.amount).toBe(588000)
    expect([...fee.edited]).toEqual(["fee"])
    const qty = editRow(d, { qty: "2,000" })
    expect(qty.amount).toBeNull()
    expect(toCandidate(qty, "acc_9")).toMatchObject({ account_id: "acc_9", symbol: "2317.TW", quantity: 2000, price: 196, amount: null, fee: 837, tax: 0, note: "" })
  })

  it("選了股票：「找不到」「對到好幾檔」那一句拿掉", () => {
    const d = toDraftRow(row({ symbol: null }, [flag("unknown_symbol", "找不到「台積」。", "error"), flag("price_far_from_close")], false, "台積"))
    const picked = editRow(d, { symbol: { symbol: "2330.TW", code: "2330", name: "台積電", market: "TWSE" } })
    expect(picked.flags.map((f) => f.code)).toEqual(["price_far_from_close"])
    expect(picked.picked).toBe(true)
  })

  it("合計：買進是價金＋手續費＋稅、賣出是價金－手續費－稅；沒有價格就算不出來", () => {
    expect(rowTotal(toDraftRow(row()))).toBe(588837)
    expect(rowTotal(toDraftRow(row({ type: "sell", amount: 648000, fee: 554, tax: 1944 })))).toBe(645502)
    expect(rowTotal(editRow(toDraftRow(row()), { price: "" }))).toBeNull()
  })

  it("簽名前的基本檢查：股票、日期（不能是未來）、股數、價格；手續費與稅要是數字", () => {
    const d = toDraftRow(row())
    expect(rowErrors(d, "2026-11-12")).toEqual({})
    expect(rowErrors(editRow(d, { date: "2026-12-01" }), "2026-11-12").date).toBe("不能是未來的日期")
    expect(rowErrors({ ...editRow(d, { qty: "0", price: "abc", fee: "-1" }), symbol: null, date: "" }, "2026-11-12")).toEqual({
      symbol: "請選股票", date: "請選日期", qty: "請輸入股數", price: "請輸入價格", fee: "請填數字",
    })
  })
})

describe("賣超：補一筆買進", () => {
  it("從伺服器的句子算出差的股數；日期與價格空著讓使用者填", () => {
    const sell = toDraftRow(row({ type: "sell", symbol: "2603.TW", quantity: 2000, price: 216 }, [flag("oversell", "賣出 2,000 股，超過當時持有的 1,000 股。", "error")], false, "長榮"))
    const buy = shortfallRow(sell, "added_1")
    expect(buy).toMatchObject({ id: "added_1", include: true, type: "buy", qty: "1000", date: "", price: "", added: true })
    expect(buy?.symbol?.symbol).toBe("2603.TW")
    // 當時一股都沒有
    const none = toDraftRow(row({ type: "sell", quantity: 500 }, [flag("oversell", "賣出 500 股，超過當時持有的 0 股。", "error")]))
    expect(shortfallRow(none, "added_2")?.qty).toBe("500")
  })
})

describe("重新驗算（dry_run）的結果併進來", () => {
  it("伺服器算得出來的換成新的；讀檔時才知道的留著，處理過就拿掉", () => {
    const d = toDraftRow(row({}, [flag("unreadable", "這一列沒讀清楚。", "error"), flag("margin"), flag("oversell", "", "error")]))
    expect(mergeFlags(d, [flag("duplicate")]).map((f) => f.code)).toEqual(["unreadable", "margin", "duplicate"])
    // 改過股數：「沒讀清楚」拿掉
    expect(mergeFlags(editRow(d, { qty: "3000" }), []).map((f) => f.code)).toEqual(["margin"])
    // 同一個代碼不重複
    expect(mergeFlags(d, [flag("margin")]).filter((f) => f.code === "margin")).toHaveLength(1)
  })

  it("多出來的代碼（使用者還沒看過）", () => {
    expect(newFlagCodes([flag("margin")], [flag("margin"), flag("oversell")])).toEqual(["oversell"])
    expect(newFlagCodes([flag("oversell")], [])).toEqual([])
  })
})

describe("整份的句子", () => {
  it("合計相符、少了、多了；沒有印合計就不說", () => {
    expect(totalsLine({ totals_check: { ok: true, diff: 0 } })).toBe("和對帳單的合計相符。")
    expect(totalsLine({ totals_check: { ok: false, diff: -12450 } })).toBe("比對帳單的合計少 NT$12,450，可能漏讀了。")
    expect(totalsLine({ totals_check: { ok: false, diff: 900 } })).toBe("比對帳單的合計多 NT$900，可能有一列讀了兩次。")
    expect(totalsLine({ totals_check: { ok: null, diff: null } })).toBeNull()
    expect(totalsLine({ totals_check: null })).toBeNull()
  })

  it("庫存畫面第一版不能匯入；不是交易紀錄、沒有讀到買賣都直接說", () => {
    expect(unsupportedLine({ document_kind: "holdings_snapshot", rows: [row()] })).toMatch(/^這是庫存畫面，沒有買進日期，還不能匯入。/)
    expect(unsupportedLine({ document_kind: "not_a_trade_record", rows: [] })).toBe("這個檔案裡沒有買賣紀錄。")
    expect(unsupportedLine({ document_kind: "monthly_statement", rows: [] })).toBe("這個檔案裡沒有讀到買賣。")
    expect(unsupportedLine({ document_kind: "app_screenshot", rows: [row()] })).toBeNull()
  })

  it("股利、融券收成「略過」一行", () => {
    const rows = [row({}, [flag("dividend_auto")]), row({}, [flag("dividend_auto")]), row({}, [flag("short_sale")]), row()]
    expect(rows.filter(isSkipped)).toHaveLength(3)
    expect(skippedSummary(rows)).toBe("略過 2 筆股利、1 筆融券")
    expect(skippedSummary([row()])).toBeNull()
  })

  it("對帳單上的券商對到帳戶（公司名稱的尾巴不算）；對不到就照原本的", () => {
    const accounts = [
      { id: "a1", name: "國泰・複委託", broker: "國泰證券", currency: "USD" },
      { id: "a2", name: "永豐・一般", broker: "永豐金證券", currency: "TWD" },
    ] as Account[]
    expect(accountForBroker(accounts, "永豐金證券股份有限公司", "a1")).toBe("a2")
    expect(accountForBroker(accounts, "範例證券股份有限公司", "a1")).toBe("a1")
    expect(accountForBroker(accounts, "", "a2")).toBe("a2")
  })
})
