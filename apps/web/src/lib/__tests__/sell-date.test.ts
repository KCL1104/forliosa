import { describe, expect, it, vi } from "vitest"
import type { Page, Transaction, TransactionQuery } from "@/api/types"
import { closeSellDate } from "../sell-date"

/**
 * 用收盤價記的賣出記在哪一天（「減少持股／全部賣出」與 AI 草稿共用）：
 * 美股記在那個收盤的紐約交易日，但這個帳戶這一檔已經有更晚的交易時記今天——不然後端依日期重算會擋下（422）。
 */
const TODAY = "2026-11-16"
const page = (n: number): Page<Transaction> => ({ items: Array.from({ length: n }, () => ({ trade_date: TODAY }) as Transaction), next_cursor: null })
const stub = (n: number) => ({ listTransactions: vi.fn(async (_q: TransactionQuery) => page(n)) })

describe("closeSellDate", () => {
  it("美股、這個帳戶這一檔沒有更晚的交易：記在收盤的紐約交易日；只查收盤日隔天以後的", async () => {
    const api = stub(0)
    expect(await closeSellDate(api, { accountId: "acc_us", symbol: "AAPL", closeDate: "2026-11-13", today: TODAY })).toBe("2026-11-13")
    expect(api.listTransactions).toHaveBeenCalledWith({ account_id: "acc_us", symbol: "AAPL", from: "2026-11-14", limit: 1 })
  })

  it("美股、有更晚的交易（今天剛記的買進）：記今天", async () => {
    expect(await closeSellDate(stub(1), { accountId: "acc_us", symbol: "AAPL", closeDate: "2026-11-13", today: TODAY })).toBe(TODAY)
  })

  it("跨月：收盤日 10/31 → 查 11/1 以後", async () => {
    const api = stub(0)
    await closeSellDate(api, { accountId: "acc_us", symbol: "AAPL", closeDate: "2026-10-31", today: TODAY })
    expect(api.listTransactions.mock.calls[0]![0].from).toBe("2026-11-01")
  })

  it("查不到既有交易：記今天（和改成紐約日期之前一樣）", async () => {
    const api = { listTransactions: vi.fn(async () => Promise.reject(new Error("503"))) }
    expect(await closeSellDate(api, { accountId: "acc_us", symbol: "AAPL", closeDate: "2026-11-13", today: TODAY })).toBe(TODAY)
  })

  it("台股（沒有收盤日）：今天，不查交易", async () => {
    const api = stub(0)
    expect(await closeSellDate(api, { accountId: "acc_tw", symbol: "2330.TW", closeDate: null, today: TODAY })).toBe(TODAY)
    expect(api.listTransactions).not.toHaveBeenCalled()
  })
})
