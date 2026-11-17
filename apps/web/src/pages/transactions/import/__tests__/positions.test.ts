import { describe, expect, it } from "vitest"
import type { ImportFlag, LedgerHolding, PositionRow } from "@/api/types"
import { maskPlainText } from "../mask"
import { ImageReadError } from "../prepare-image"
import { imageError } from "../read-utils"
import {
  applyCheck,
  checkable,
  costTotals,
  costTotalsText,
  editPosition,
  inLedgerLine,
  isShortSale,
  positionErrors,
  priceText,
  replacedIncomeText,
  replacedRecordsText,
  setInclude,
  setReplace,
  toCommitRow,
  toDraftPosition,
  totalCost,
  totalText,
  unitPrice,
} from "../positions"

const flag = (code: string, severity: ImportFlag["severity"] = "warning", message = code): ImportFlag => ({ code, message, severity })
const held = (over: Partial<LedgerHolding> = {}): LedgerHolding => ({ quantity: 1500, avg_cost: 692.61, currency: "TWD", records: 3, dividends: 0, sells: 0, ...over })

function row(over: Partial<PositionRow> = {}): PositionRow {
  return {
    row_id: "p1", symbol: "2330.TW", name: "台積電", currency: "TWD", quantity: 1500, price: 612.4, price_basis: "average_cost", total_cost: 918600,
    raw: { symbol_code: "2330", name: "台積電" }, flags: [], include: true, in_ledger: null, ...over,
  }
}

describe("匯入庫存的一列", () => {
  it("均價或總成本二選一：給的那一格照原樣，另一格照它算", () => {
    const byAvg = toDraftPosition(row())
    expect(byAvg.basis).toBe("price")
    expect(unitPrice(byAvg)).toBe(612.4)
    expect(totalCost(byAvg)).toBe(918600)
    expect(priceText(byAvg)).toBe("612.4")
    expect(totalText(byAvg)).toBe("918,600")
    // 只有總成本（中華電 1.5 張、總成本 180,000）：均價是算出來的，寫入時送總成本
    const byTotal = toDraftPosition(row({ symbol: "2412.TW", name: "中華電", quantity: 1500, price: 120, price_basis: "total_cost", total_cost: 180000 }))
    expect(byTotal.basis).toBe("total")
    expect(priceText(byTotal)).toBe("120")
    expect(toCommitRow(byTotal, "2026-11-17")).toEqual({ symbol: "2412.TW", quantity: 1500, total_cost: 180000, currency: "TWD" })
    // 改了股數：總成本不變、均價跟著變
    expect(priceText(editPosition(byTotal, { qty: "2,000" }))).toBe("90")
    // 改了均價：改成照均價
    const edited = editPosition(byTotal, { price: "121.5" })
    expect(edited.basis).toBe("price")
    expect(toCommitRow(edited, "2026-11-17")).toEqual({ symbol: "2412.TW", quantity: 1500, price: 121.5, currency: "TWD" })
  })

  it("寫入：日期和整批不同才送；以券商為準才送 replace；美股是美元", () => {
    const d = { ...toDraftPosition(row({ symbol: "AAPL", name: "Apple", currency: "USD", quantity: 10.5, price: 230.5, total_cost: null })), date: "2026-10-17" }
    expect(toCommitRow(d, "2026-11-17")).toEqual({ symbol: "AAPL", quantity: 10.5, price: 230.5, currency: "USD", trade_date: "2026-10-17" })
    expect(toCommitRow({ ...d, date: "2026-11-17" }, "2026-11-17")).not.toHaveProperty("trade_date")
    const inLedger = toDraftPosition(row({ in_ledger: held(), include: false, flags: [flag("in_ledger")] }))
    expect(toCommitRow(setReplace(inLedger, true), "2026-11-17")).toMatchObject({ symbol: "2330.TW", replace: true })
  })

  it("已在帳本：預設不勾；勾選和以券商為準綁在一起（不換掉的話伺服器不收）", () => {
    const d = toDraftPosition(row({ in_ledger: held(), include: false, flags: [flag("in_ledger"), flag("margin")] }))
    // in_ledger 的句子照數字寫，不放在旗標裡
    expect(d.flags.map((f) => f.code)).toEqual(["margin"])
    expect(d.include).toBe(false)
    const on = setInclude(d, true)
    expect([on.include, on.replace]).toEqual([true, true])
    const off = setReplace(on, false)
    expect([off.include, off.replace]).toEqual([false, false])
    // 不在帳本的列：勾選不碰以券商為準
    expect(setInclude(toDraftPosition(row()), true).replace).toBe(false)
  })

  it("以券商為準會刪掉什麼：股利與賣出照實說（損益會跟著變）", () => {
    expect(replacedRecordsText(held())).toBe("3 筆紀錄")
    expect(replacedRecordsText(held({ records: 15, dividends: 3, sells: 1 }))).toBe("15 筆紀錄（含 3 筆股利、1 筆賣出）")
    expect(replacedRecordsText(held({ records: 4, dividends: 2 }))).toBe("4 筆紀錄（含 2 筆股利）")
    expect(replacedIncomeText([held(), held({ sells: 2 })])).toBe("賣出的損益")
    expect(replacedIncomeText([held({ dividends: 1 }), held({ sells: 2 })])).toBe("領過的股利、賣出的損益")
    expect(replacedIncomeText([held()])).toBe("")
  })

  it("帳本那一行：股數和均價都一樣時直說；不一樣時寫帳本的股數與均價（改了股數就跟著變）", () => {
    const d = toDraftPosition(row({ in_ledger: held() }))
    expect(inLedgerLine(d)).toBe("帳本裡已經有 1,500 股，均價 692.61。")
    const same = editPosition(d, { price: "692.61" })
    expect(inLedgerLine(same)).toBe("帳本裡已經有，股數和均價都一樣。")
    expect(inLedgerLine(editPosition(same, { qty: "1,000" }))).toBe("帳本裡已經有 1,500 股，均價 692.61。")
    expect(inLedgerLine(toDraftPosition(row()))).toBeNull()
  })

  it("讀的時候的問題，改了相關的格子就拿掉；選了股票，「找不到」拿掉、帳本要重新檢查", () => {
    const d = toDraftPosition(row({ flags: [flag("cost_mismatch"), flag("margin"), flag("not_whole_lots")] }))
    expect(editPosition(d, { price: "600" }).flags.map((f) => f.code)).toEqual(["margin", "not_whole_lots"])
    expect(editPosition(d, { qty: "2000" }).flags.map((f) => f.code)).toEqual(["margin"])
    const unknown = toDraftPosition(row({ symbol: null, name: "台光電", raw: { name: "台光電" }, include: false, flags: [flag("unknown_symbol", "error")] }))
    expect(unknown.symbol).toBeNull()
    expect(unknown.readName).toBe("台光電")
    const picked = editPosition({ ...unknown, inLedger: held(), replace: true }, { symbol: { symbol: "2383.TW", code: "2383", name: "台光電", market: "TWSE" } })
    expect(picked.flags).toEqual([])
    expect(picked.inLedger).toBeNull()
    expect(picked.replace).toBe(false)
  })

  it("簽名前的檢查：股票、股數（台股整數）、均價或總成本、日期（不能在未來；空的用整批的）", () => {
    const d = toDraftPosition(row())
    expect(positionErrors(d, "2026-11-17", "2026-11-17")).toEqual({})
    expect(positionErrors({ ...d, qty: "1.5" }, "2026-11-17", "2026-11-17").qty).toBe("台股的股數要是整數")
    expect(positionErrors({ ...d, symbol: { ...d.symbol!, market: "US" }, qty: "1.5" }, "2026-11-17", "2026-11-17").qty).toBeUndefined()
    expect(positionErrors({ ...d, price: "" }, "2026-11-17", "2026-11-17").price).toBe("請輸入均價")
    expect(positionErrors({ ...d, basis: "total", total: "0" }, "2026-11-17", "2026-11-17").total).toBe("請輸入總成本")
    expect(positionErrors({ ...d, date: "2026-11-18" }, "2026-11-17", "2026-11-17").date).toBe("不能是未來的日期")
    expect(positionErrors(d, "", "2026-11-17").date).toBe("請選日期")
    expect(positionErrors({ ...d, symbol: null }, "2026-11-17", "2026-11-17").symbol).toBe("請選股票")
    expect(checkable({ ...d, symbol: null })).toBe(false)
    expect(checkable(d)).toBe(true)
  })

  it("融券不進表格；成本合計只算勾著的，新台幣與美元分開", () => {
    expect(isShortSale(row({ flags: [flag("short_sale")] }))).toBe(true)
    const rows = [
      toDraftPosition(row()),
      toDraftPosition(row({ row_id: "p2", symbol: "AAPL", name: "Apple", currency: "USD", quantity: 10, price: 230.5, total_cost: null })),
      { ...toDraftPosition(row({ row_id: "p3" })), include: false },
    ]
    const t = costTotals(rows)
    expect(t).toEqual({ TWD: 918600, USD: 2305 })
    expect(costTotalsText(t)).toBe("NT$918,600、US$2,305.00")
  })
})

describe("重新檢查（dry_run）的結果", () => {
  const sent = (rows: ReturnType<typeof toDraftPosition>[]) => rows

  it("換帳戶後新出現在帳本：不勾、不換掉，算一列變了；別的帳戶也有的句子拿掉", () => {
    const d = toDraftPosition(row({ flags: [flag("in_other_account")] }))
    const res = applyCheck([d], sent([d]), { rows: [{ index: 0, flags: [flag("in_ledger", "error")], in_ledger: held() }] }, true)
    expect(res.rows[0]!.include).toBe(false)
    expect(res.rows[0]!.inLedger).toEqual(held())
    expect(res.rows[0]!.flags).toEqual([])
    expect(res.changed).toBe(1)
    expect(res.blocking).toBe(0)
  })

  it("以券商為準只對勾的那個帳戶：換到也有這一檔的帳戶，不再勾著、不換掉，算一列變了（要對新的帳戶重新勾）", () => {
    // 帳戶 A 有 1,500 股，勾了以券商為準
    const a = setReplace(toDraftPosition(row({ in_ledger: held(), include: false, flags: [flag("in_ledger")] })), true)
    expect([a.include, a.replace]).toEqual([true, true])
    // 換到帳戶 B（也有 300 股）：dry_run 帶著 replace，伺服器不標 in_ledger 錯誤，只回 B 的持股
    const inB = held({ quantity: 300, avg_cost: 500, records: 1 })
    const res = applyCheck([a], [a], { rows: [{ index: 0, flags: [], in_ledger: inB }] }, true)
    expect(res.rows[0]).toMatchObject({ include: false, replace: false, inLedger: inB })
    expect(res.changed).toBe(1)
    expect(toCommitRow(res.rows[0]!, "2026-11-17")).not.toHaveProperty("replace")
    // 對 B 重新勾了以後，同一個帳戶再檢查一次：照舊勾著
    const again = setReplace(res.rows[0]!, true)
    const same = applyCheck([again], [again], { rows: [{ index: 0, flags: [], in_ledger: inB }] }, false)
    expect(same.rows[0]).toMatchObject({ include: true, replace: true })
    expect(same.changed).toBe(0)
    // 換帳戶時還沒送出去（檢查不了）的列：以券商為準和它綁著的勾選一起拿掉
    const notSent = { ...a, qty: "" }
    const out = applyCheck([notSent], [], { rows: [] }, true)
    expect(out.rows[0]).toMatchObject({ include: false, replace: false, inLedger: null })
  })

  it("不在帳本了：以券商為準拿掉；使用者沒動過勾選的重新勾上", () => {
    const d = toDraftPosition(row({ in_ledger: held(), include: false, flags: [flag("in_ledger")] }))
    const res = applyCheck([d], [d], { rows: [{ index: 0, flags: [], in_ledger: null }] }, true)
    expect(res.rows[0]!.include).toBe(true)
    expect(res.rows[0]!.replace).toBe(false)
    // 自己取消過的不替他勾
    const mine = { ...d, includeSet: true }
    expect(applyCheck([mine], [mine], { rows: [{ index: 0, flags: [], in_ledger: null }] }, true).rows[0]!.include).toBe(false)
  })

  it("勾著卻寫不進去（日期、找不到股票）：算進不能匯入的列數；沒送出去的列不動", () => {
    const a = toDraftPosition(row())
    const b = toDraftPosition(row({ row_id: "p2", symbol: null, name: "台光電", include: false }))
    const res = applyCheck([a, b], [a], { rows: [{ index: 0, flags: [flag("bad_date", "error", "日期要在 1990/1/1 到今天之間。")], in_ledger: null }] }, false)
    expect(res.blocking).toBe(1)
    expect(res.changed).toBe(1)
    expect(res.rows[0]!.flags.map((f) => f.message)).toEqual(["日期要在 1990/1/1 到今天之間。"])
    expect(res.rows[1]).toBe(b)
    // 再檢查一次、沒問題了：上一次的錯誤換掉
    const again = applyCheck(res.rows, [res.rows[0]!], { rows: [{ index: 0, flags: [], in_ledger: null }] }, false)
    expect(again.rows[0]!.flags).toEqual([])
    expect(again.changed).toBe(0)
  })
})

describe("截圖打不開的一句話", () => {
  it("匯入庫存不收 PDF，不能說「只收 PDF、…」；匯入對帳單照舊", () => {
    const e = new ImageReadError("unsupported", "a.tiff")
    expect(imageError(e)).toBe("只收 PDF、JPEG、PNG、WebP。")
    expect(imageError(e, { pdf: false })).toBe("只收 JPEG、PNG、WebP 的截圖。")
    expect(imageError(new ImageReadError("heic", "a.heic"), { pdf: false })).toBe("這張是 HEIC 格式，這個瀏覽器讀不了。請改存成 JPEG，或改用截圖。")
  })
})

describe("貼上的文字先塗掉個資", () => {
  it("身分證字號、帳號、姓名換成〔已遮蔽〕；庫存的數字不動", () => {
    const text = "客戶姓名：王小明  帳號：9A99-0123456\nA123456789\n2330 台積電 1,000 股 均價 580.5"
    const out = maskPlainText(text)
    expect(out.masked).toBe(3)
    expect(out.text).not.toContain("王小明")
    expect(out.text).not.toContain("9A99-0123456")
    expect(out.text).not.toContain("A123456789")
    expect(out.text).toContain("2330 台積電 1,000 股 均價 580.5")
    expect(maskPlainText("0050 3 張 150").masked).toBe(0)
  })
})
