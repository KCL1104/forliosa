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

describe("重新設計新增的端點（形狀與 api-contract 一致）", () => {
  const api = createMockAdapter({ latency: [0, 0] })

  it("報價帶參考價與漲跌停，漲跌以參考價計算", async () => {
    const q = await api.getQuote("2330.TW")
    expect(q.reference_price).toBe(1035)
    expect(q).toMatchObject({ limit_up: 1135, limit_down: 932 })
    expect(q.change).toBe(50)
    expect((await api.getQuote("NVDA")).limit_up).toBeNull()
  })
  it("盤中點：只有持股與自選有，其他回空陣列", async () => {
    expect((await api.getIntraday("2330.TW")).points.length).toBeGreaterThan(200)
    expect((await api.getIntraday("2382.TW")).points.length).toBeGreaterThan(200)
    expect((await api.getIntraday("3008.TW")).points).toEqual([])
  })
  it("部位：未持有回 null；持有時有買賣與股利標記", async () => {
    expect(await api.getPosition("3008.TW")).toBeNull()
    const p = (await api.getPosition("2330.TW"))!
    expect(p.quantity).toBe(1500)
    expect(p.markers.some((m) => m.type === "buy")).toBe(true)
    expect(p.markers.some((m) => m.type === "dividend")).toBe(true)
  })
  it("why：異常時才 show", async () => {
    expect((await api.getWhy("2330.TW")).show).toBe(true)
    expect((await api.getWhy("2317.TW")).show).toBe(false)
  })
  it("籌碼、財報、事件、新聞、本週事項", async () => {
    const c = await api.getChips("2330.TW", "1M")
    expect(c.institutional[0]).toEqual(expect.objectContaining({ foreign: expect.any(Number), total: expect.any(Number) }))
    const f = await api.getFinancials("2330.TW", "quarterly")
    expect(f.income.eps).toHaveLength(f.periods.length)
    expect((await api.getFinancials("0050.TW")).periods).toEqual([])
    expect((await api.getEvents("2330.TW")).some((e) => e.type === "ex_dividend")).toBe(true)
    expect((await api.getNews("2330.TW"))[0]).toEqual(expect.objectContaining({ title: expect.any(String), source: expect.any(String), url: expect.any(String) }))
    const up = await api.getUpcoming(7)
    expect(up.map((u) => u.type)).toEqual(expect.arrayContaining(["ex_dividend", "dividend_payment"]))
  })
  it("自選：新增、移除", async () => {
    const before = await api.getWatchlist()
    await api.addWatch("3008.TW")
    expect((await api.getWatchlist()).map((w) => w.symbol)).toContain("3008.TW")
    await api.removeWatch("3008.TW")
    expect((await api.getWatchlist()).length).toBe(before.length)
  })
  it("AI 草稿入帳帶 source: ai_draft", async () => {
    const [acc] = await api.listAccounts()
    const t = await api.createTransaction({ account_id: acc!.id, symbol: "0050.TW", type: "buy", trade_date: "2026-11-12", quantity: 2000, price: 52.4, source: "ai_draft" })
    expect(t.source).toBe("ai_draft")
    expect(t.fee).toBe(41)
  })
})
