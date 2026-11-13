import { describe, expect, it } from "vitest"
import { createMockAdapter } from "@/api/mock/adapter"
import { cashNote, coveredByUser, exDividendNotices } from "@/api/mock/auto-dividends"
import type { ForliosaApi, Transaction, TransactionInput } from "@/api/types"

/** 股利自動入帳：mock 要和後端（apps/api/src/forliosa/services/auto_dividends.py、docs/handoff.md §3.0）一致 */
const fresh = () => createMockAdapter({ latency: [0, 0] })

async function dividends(api: ForliosaApi, symbol?: string): Promise<Transaction[]> {
  return (await api.listTransactions({ type: "cash_dividend", symbol, limit: 200 })).items
}
const autos = async (api: ForliosaApi, symbol?: string) => (await dividends(api, symbol)).filter((t) => t.source === "auto" || t.source === "auto_edited")
const tw = async (api: ForliosaApi) => (await api.listAccounts())[0]!

describe("示範資料", () => {
  it("最近的台股股利在除息日自動入帳（上市、上櫃、零股），股數是除息日前一天的持股", async () => {
    const rows = await autos(fresh())
    expect(rows.map((t) => [t.symbol, t.trade_date, t.quantity, t.price, t.amount, t.source])).toEqual([
      ["2454.TW", "2026-10-08", 200, 25, 5000, "auto"],
      ["6488.TWO", "2026-09-22", 1000, 4, 4000, "auto"],
      ["2330.TW", "2026-09-16", 1500, 5, 7500, "auto"],
    ])
    expect(rows[2]!.note).toBe("1,500 股 × 每股 5 元，10/09 發放")
    expect(rows.every((t) => t.health_insurance === 0 && t.fee === 0 && t.currency === "TWD")).toBe(true)
  })
  it("之前自己記的股利維持手動；美股一直是手動；還沒到的除息日不記", async () => {
    const api = fresh()
    const all = await dividends(api)
    const manual2330 = all.filter((t) => t.symbol === "2330.TW" && t.source === "manual").map((t) => t.trade_date)
    expect(manual2330).toContain("2026-07-09")
    expect(all.filter((t) => t.symbol === "2330.TW" && t.trade_date >= "2026-06-11" && t.trade_date <= "2026-07-09")).toHaveLength(1)
    expect(all.filter((t) => t.currency === "USD").every((t) => t.source === "manual")).toBe(true)
    // 00878 11/18 除息（還沒到）、2412 7/16 除息（7/15 已賣光）都沒有
    expect(all.some((t) => t.symbol === "00878.TW" && t.trade_date >= "2026-11-12")).toBe(false)
    expect(all.some((t) => t.symbol === "2412.TW")).toBe(false)
  })
  it("沒有交易的情境沒有自動入帳", async () => {
    expect(await createMockAdapter({ latency: [0, 0], scenario: "empty" }).listTransactions({})).toMatchObject({ items: [] })
  })
})

describe("修改與刪除", () => {
  it("修改自動入帳的股利 → auto_edited，之後重算不再碰它", async () => {
    const api = fresh()
    const [row] = await autos(api, "2454.TW")
    const edited = await api.updateTransaction(row!.id, { note: "券商入帳 5,000" })
    expect(edited.source).toBe("auto_edited")
    // 回頭補一筆除息前的買進：改過的那筆不會被更新，也不會多一筆自動的
    const acc = await tw(api)
    await api.createTransaction({ account_id: acc.id, symbol: "2454.TW", type: "buy", trade_date: "2026-09-01", quantity: 1000, price: 1400 })
    const rows = await autos(api, "2454.TW")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ id: row!.id, source: "auto_edited", quantity: 200, note: "券商入帳 5,000" })
  })
  it("改了股數：金額跟著重算（與後端相同）", async () => {
    const api = fresh()
    const [row] = await autos(api, "2330.TW")
    const edited = await api.updateTransaction(row!.id, { quantity: 1000, price: 5 })
    expect(edited).toMatchObject({ source: "auto_edited", quantity: 1000, amount: 5000 })
    expect((await autos(api, "2330.TW"))[0]).toMatchObject({ id: row!.id, source: "auto_edited", amount: 5000 })
  })
  it("刪除自動入帳的股利後不會再產生", async () => {
    const api = fresh()
    const before = (await api.getPortfolioSummary()).dividend_income
    const [row] = await autos(api, "6488.TWO")
    await api.deleteTransaction(row!.id)
    expect(await autos(api, "6488.TWO")).toEqual([])
    // 之後的變更會觸發重算，刪掉的那筆仍然不回來
    const acc = await tw(api)
    await api.createTransaction({ account_id: acc.id, symbol: "6488.TWO", type: "buy", trade_date: "2026-09-01", quantity: 1000, price: 500 })
    expect(await autos(api, "6488.TWO")).toEqual([])
    expect((await api.getPortfolioSummary()).dividend_income).toBe(before - 4000)
  })
  it("用戶端不能建立或改成 auto", async () => {
    const api = fresh()
    const acc = await tw(api)
    const body = { account_id: acc.id, symbol: "2330.TW", type: "cash_dividend", trade_date: "2026-09-16", quantity: 1500, price: 5, source: "auto" } as unknown as TransactionInput
    await expect(api.createTransaction(body)).rejects.toMatchObject({ status: 422, code: "validation_error" })
    const [row] = await autos(api, "2330.TW")
    await expect(api.updateTransaction(row!.id, { source: "auto_edited" } as unknown as Partial<TransactionInput>)).rejects.toMatchObject({ status: 422 })
  })
})

describe("重算", () => {
  it("回補除息前的買進：股數、金額與二代健保跟著重算；刪掉買進就回到原本", async () => {
    const api = fresh()
    const acc = await tw(api)
    const buy = await api.createTransaction({ account_id: acc.id, symbol: "2454.TW", type: "buy", trade_date: "2026-09-01", quantity: 1000, price: 1400 })
    const [row] = await autos(api, "2454.TW")
    expect(row).toMatchObject({ source: "auto", trade_date: "2026-10-08", quantity: 1200, amount: 30000, health_insurance: 633 })
    expect(row!.note).toBe("1,200 股 × 每股 25 元，10/30 發放")
    await api.deleteTransaction(buy.id)
    expect((await autos(api, "2454.TW"))[0]).toMatchObject({ quantity: 200, amount: 5000, health_insurance: 0 })
  })
  it("除息日當天才買不算；前一天賣光就沒有", async () => {
    const api = fresh()
    const acc = await tw(api)
    await api.createTransaction({ account_id: acc.id, symbol: "6488.TWO", type: "buy", trade_date: "2026-09-22", quantity: 1000, price: 500 })
    expect((await autos(api, "6488.TWO"))[0]).toMatchObject({ quantity: 1000, amount: 4000 })
    await api.createTransaction({ account_id: acc.id, symbol: "2330.TW", type: "sell", trade_date: "2026-09-15", quantity: 1500, price: 1200 })
    expect(await autos(api, "2330.TW")).toEqual([])
  })
  it("自己記的優先：記了同一次股利就移除自動那筆，刪掉自己記的又會自動入帳", async () => {
    const api = fresh()
    const acc = await tw(api)
    const mine = await api.createTransaction({ account_id: acc.id, symbol: "6488.TWO", type: "cash_dividend", trade_date: "2026-10-16", quantity: 1000, price: 4 })
    expect(mine.source).toBe("manual")
    expect(await autos(api, "6488.TWO")).toEqual([])
    expect((await dividends(api, "6488.TWO")).filter((t) => t.trade_date >= "2026-09-22")).toHaveLength(1)
    await api.deleteTransaction(mine.id)
    expect(await autos(api, "6488.TWO")).toHaveLength(1)
  })
  it("只記持股的帳戶：只記快照日之後的除息日", async () => {
    const api = fresh()
    const acc = await api.createAccount({
      name: "元大－只記持股", broker: "元大證券", currency: "TWD", fee_rate: 0.001425, fee_discount: 0.6, min_fee: 20, min_fee_odd_lot: 1, tracking_mode: "holdings",
    })
    await api.putHoldings(acc.id, { as_of: "2026-09-20", holdings: [{ symbol: "2330.TW", quantity: 1000, avg_cost: 900 }, { symbol: "6488.TWO", quantity: 2000, avg_cost: 450 }] })
    const rows = (await autos(api)).filter((t) => t.account_id === acc.id)
    // 2330 9/16 除息在快照日之前（快照已經反映）：不記
    expect(rows.map((t) => [t.symbol, t.trade_date, t.amount])).toEqual([["6488.TWO", "2026-09-22", 8000]])
  })
})

describe("規則", () => {
  it("除息預告只有台股、存檔起點之後、金額大於 0", () => {
    expect(exDividendNotices("AAPL")).toEqual([])
    expect(exDividendNotices("2330.TW").map((e) => e.ex_dividend_date)).toEqual(["2026-06-11", "2026-09-16", "2026-12-11"])
  })
  it("自己記的紀錄代表 120 天內最近的除息日，每股金額相同的優先", () => {
    const notices = exDividendNotices("2330.TW")
    const rec = (trade_date: string, price: number | null) => ({ type: "cash_dividend", trade_date, price }) as Transaction
    expect([...coveredByUser([rec("2026-10-09", null)], notices)]).toEqual(["2026-09-16"])
    expect([...coveredByUser([rec("2026-10-09", 4.5)], notices)]).toEqual(["2026-06-11"])
    expect([...coveredByUser([rec("2027-03-01", null)], notices)]).toEqual(["2026-12-11"])
    expect([...coveredByUser([rec("2026-06-10", null)], notices)]).toEqual([])
  })
  it("備註和後端相同；沒有發放日就不寫", () => {
    expect(cashNote(10000, 2, "2026-07-10")).toBe("10,000 股 × 每股 2 元，07/10 發放")
    expect(cashNote(1500, 0.55, null)).toBe("1,500 股 × 每股 0.55 元")
  })
})
