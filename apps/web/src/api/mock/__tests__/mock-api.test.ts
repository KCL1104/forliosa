import { describe, expect, it } from "vitest"
import { createMockAdapter } from "@/api/mock/adapter"

/** mock 要和真實後端的語意一致（apps/api/CONTRACT_NOTES.md） */
describe("mock adapter 與後端一致", () => {
  const api = createMockAdapter({ latency: [0, 0] })

  it("1D／5D 以交易日計：第一點是基準收盤（指數 1.0），不算 XIRR", async () => {
    const all = await api.getPerformance({ range: "ALL" })
    const one = await api.getPerformance({ range: "1D" })
    expect(one.series.map((p) => p.t)).toEqual(all.series.slice(-2).map((p) => p.t))
    expect(one.series[0]!.twr_index).toBe(1)
    expect(one.xirr).toBeNull()
    const five = await api.getPerformance({ range: "5D" })
    expect(five.series).toHaveLength(6)
    expect(five.twr).toBeCloseTo(five.series.at(-1)!.twr_index - 1, 4)
  })

  it("基準可以是加權報酬指數（mock 以 0050 示範走勢代替）", async () => {
    const p = await api.getPerformance({ range: "1M", benchmark: "^TAIEXTR" })
    expect(p.benchmark).toMatchObject({ symbol: "^TAIEXTR", name: "發行量加權股價報酬指數" })
  })

  it("現金類交易沒有數量與價格；手續費元以下捨去", async () => {
    const page = await api.listTransactions({ type: "deposit" })
    expect(page.items[0]!.quantity).toBeNull()
    expect(page.items[0]!.price).toBeNull()
    const [acc] = await api.listAccounts()
    const preview = await api.previewTransaction({ account_id: acc!.id, symbol: "2330.TW", type: "buy", trade_date: "2026-11-11", quantity: 1000, price: 1070 })
    expect(preview.fee).toBe(426)
  })
})
