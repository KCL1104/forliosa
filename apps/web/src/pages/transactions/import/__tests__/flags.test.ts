import { describe, expect, it } from "vitest"
import type { Account, ImportRow } from "@/api/types"
import {
  accountForBroker,
  editRow,
  forAccountSwitch,
  includeAfterCheck,
  isSkipped,
  mergeFlags,
  newFlagCodes,
  rowErrors,
  rowTotal,
  shortfallRow,
  skippedSummary,
  statementCurrency,
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
    // 幣別：TWD／USD 照送，讀不出來（"" 或 other）不送
    expect(toCandidate(toDraftRow(row({ currency: "USD" })), "a").currency).toBe("USD")
    expect("currency" in toCandidate(toDraftRow(row({ currency: "other" as "TWD" })), "a")).toBe(false)
  })

  it("選了股票：「找不到」「對到好幾檔」那一句拿掉", () => {
    const d = toDraftRow(row({ symbol: null }, [flag("unknown_symbol", "找不到「台積」", "error"), flag("price_far_from_close")], false, "台積"))
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
    const sell = toDraftRow(row({ type: "sell", symbol: "2603.TW", quantity: 2000, price: 216 }, [flag("oversell", "賣出 2,000 股・當時只有 1,000 股", "error")], false, "長榮"))
    const buy = shortfallRow(sell, "added_1")
    // 股數和其他列一樣寫千分位
    expect(buy).toMatchObject({ id: "added_1", include: true, type: "buy", qty: "1,000", date: "", price: "", added: true })
    expect(buy?.symbol?.symbol).toBe("2603.TW")
    // 當時一股都沒有
    const none = toDraftRow(row({ type: "sell", quantity: 500 }, [flag("oversell", "賣出 500 股・當時只有 0 股", "error")]))
    expect(shortfallRow(none, "added_2")?.qty).toBe("500")
  })
})

describe("重新驗算（dry_run）的結果併進來", () => {
  it("伺服器算得出來的換成新的；讀檔時才知道的留著，處理過就拿掉", () => {
    const d = toDraftRow(row({}, [flag("unreadable", "沒讀清楚・價格", "error"), flag("margin"), flag("oversell", "", "error")]))
    expect(mergeFlags(d, [flag("duplicate")]).map((f) => f.code)).toEqual(["unreadable", "margin", "duplicate"])
    // 改過股數：「沒讀清楚」拿掉
    expect(mergeFlags(editRow(d, { qty: "3000" }), []).map((f) => f.code)).toEqual(["margin"])
    // 同一個代碼不重複
    expect(mergeFlags(d, [flag("margin")]).filter((f) => f.code === "margin")).toHaveLength(1)
  })

  it("讀檔時才算得出來的（張數、買賣看反、價格、非交易日、手續費、稅、期間）重新驗算後還在；改了相關的格子才拿掉", () => {
    const read = [
      flag("amount_mismatch", "股數 × 價格和成交金額差 587,412・可能是張數（1 張＝1,000 股）"),
      flag("side_inconsistent"), flag("price_far_from_close"), flag("not_trading_day"), flag("outside_period"),
      flag("fee_out_of_range"), flag("tax_out_of_range"), flag("currency_mismatch"), flag("day_trade"),
    ]
    const d = toDraftRow(row({ quantity: 3 }, read))
    // 換帳戶時的重新驗算：dry_run 只回帳本的，讀檔時的一個都不少
    expect(mergeFlags(d, []).map((f) => f.code)).toEqual(read.map((f) => f.code))
    expect(newFlagCodes(d.flags, mergeFlags(d, []))).toEqual([])
    const codes = (patch: Parameters<typeof editRow>[1]) => mergeFlags(editRow(d, patch), []).map((f) => f.code)
    expect(codes({ qty: "3,000" })).not.toContain("amount_mismatch")
    expect(codes({ qty: "3,000" })).toContain("not_trading_day")
    expect(codes({ date: "2026-10-02" })).not.toContain("not_trading_day")
    expect(codes({ date: "2026-10-02" })).not.toContain("outside_period")
    expect(codes({ fee: "837" })).not.toContain("fee_out_of_range")
    expect(codes({ type: "sell" })).not.toContain("side_inconsistent")
    // 幣別、當沖改哪一格都留著
    expect(codes({ qty: "1", price: "1", fee: "1", tax: "1", date: "2026-10-02", type: "sell" })).toEqual(["currency_mismatch", "day_trade"])
  })

  it("新出現的賣超、重複：使用者沒自己動過勾選就跟伺服器一樣不勾；自己勾的照舊", () => {
    const d = toDraftRow(row())
    const merged = mergeFlags(d, [flag("duplicate", "10/1 已記過一樣的")])
    expect(includeAfterCheck(d, merged)).toBe(false)
    expect(includeAfterCheck({ ...d, includeSet: true }, merged)).toBe(true)
    // 早就看過的（不是新的）、或只是提醒（價格）：不動
    const seen = toDraftRow(row({}, [flag("duplicate")]))
    expect(includeAfterCheck(seen, mergeFlags(seen, [flag("duplicate")]))).toBe(true)
    expect(includeAfterCheck(d, mergeFlags(d, [flag("price_far_from_close")]))).toBe(true)
  })

  it("換帳戶：沒勾的列上舊帳戶的賣超、重複拿掉；只因為這些沒勾的列重新勾上（自己取消的、讀不清楚的不動）", () => {
    const dup = toDraftRow(row({}, [flag("duplicate", "10/1 已記過一樣的")], false))
    const mine = { ...dup, id: "mine", includeSet: true }
    const unread = toDraftRow(row({}, [flag("duplicate"), flag("unreadable", "沒讀清楚・價格", "error")], false))
    const day = toDraftRow(row({}, [flag("day_trade")], false))
    const [a, b, c, e] = forAccountSwitch([dup, mine, unread, day])
    expect([a!.include, a!.flags]).toEqual([true, []])
    expect([b!.include, b!.flags]).toEqual([false, []])
    expect([c!.include, c!.flags.map((f) => f.code)]).toEqual([false, ["unreadable"]])
    expect(e).toBe(day)
  })

  it("多出來的代碼（使用者還沒看過）", () => {
    expect(newFlagCodes([flag("margin")], [flag("margin"), flag("oversell")])).toEqual(["oversell"])
    expect(newFlagCodes([flag("oversell")], [])).toEqual([])
  })
})

describe("整份的句子", () => {
  it("合計相符、少了、多了（標籤，不是句子）；沒有印合計就不寫", () => {
    expect(totalsLine({ totals_check: { ok: true, diff: 0 } })).toBe("合計相符")
    expect(totalsLine({ totals_check: { ok: false, diff: -12450 } })).toBe("比對帳單合計少 NT$12,450・可能漏讀")
    expect(totalsLine({ totals_check: { ok: false, diff: 900 } })).toBe("比對帳單合計多 NT$900・可能重複讀")
    expect(totalsLine({ totals_check: { ok: null, diff: null } })).toBeNull()
    expect(totalsLine({ totals_check: null })).toBeNull()
  })

  it("庫存畫面改用匯入庫存；不是交易紀錄、沒有讀到買賣都直接寫（標籤）", () => {
    expect(unsupportedLine({ document_kind: "holdings_snapshot", rows: [row()] })).toBe("這是庫存畫面・改用匯入庫存")
    expect(unsupportedLine({ document_kind: "not_a_trade_record", rows: [] })).toBe("沒有買賣紀錄")
    expect(unsupportedLine({ document_kind: "monthly_statement", rows: [] })).toBe("沒有讀到買賣")
    expect(unsupportedLine({ document_kind: "app_screenshot", rows: [row()] })).toBeNull()
    // 伺服器寫了句子就照它的；能匯入的檔案不因為有 notice 就擋下來
    expect(unsupportedLine({ document_kind: "holdings_snapshot", rows: [], notice: "庫存截圖還不能匯入。" })).toBe("庫存截圖還不能匯入。")
    expect(unsupportedLine({ document_kind: "monthly_statement", rows: [row()], notice: "x" })).toBeNull()
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

  it("先選帳戶也看幣別：台股對帳單不選同一家的美元複委託；原本的幣別不對時改成幣別相同的", () => {
    const accounts = [
      { id: "tw_other", name: "元大－一般", broker: "元大證券", currency: "TWD" },
      { id: "us", name: "富邦－複委託", broker: "富邦證券", currency: "USD" },
      { id: "tw", name: "富邦－一般", broker: "富邦證券", currency: "TWD" },
    ] as Account[]
    expect(accountForBroker(accounts, "富邦綜合證券股份有限公司", "tw_other", "TWD")).toBe("tw")
    expect(accountForBroker(accounts, "富邦綜合證券股份有限公司", "tw_other", "USD")).toBe("us")
    expect(accountForBroker(accounts, "國泰證券", "tw_other", "USD")).toBe("us")
    expect(accountForBroker(accounts, "國泰證券", "tw_other", "TWD")).toBe("tw_other")
    expect(statementCurrency({ rows: [row(), row({ symbol: "AAPL" }), row({ symbol: "NVDA" })] })).toBe("USD")
    expect(statementCurrency({ rows: [row(), row({ symbol: "AAPL" }, [flag("dividend_auto")])] })).toBe("TWD")
    expect(statementCurrency({ rows: [] })).toBeNull()
  })
})
