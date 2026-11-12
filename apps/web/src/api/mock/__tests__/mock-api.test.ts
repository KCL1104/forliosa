import { describe, expect, it } from "vitest"
import { createMockAdapter } from "@/api/mock/adapter"

/** mock 要和真實後端的語意一致（apps/api/CONTRACT_NOTES.md） */
describe("mock adapter 與後端一致", () => {
  const api = createMockAdapter({ latency: [0, 0], policy: "personal" })

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
  const api = createMockAdapter({ latency: [0, 0], policy: "personal" })

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

describe("商用模式（預設，與後端 DATA_POLICY=commercial 一致）", () => {
  const api = createMockAdapter({ latency: [0, 0] })

  it("沒有示範標記；存檔不足處回空資料＋「資料累積中」", async () => {
    expect((await api.getPortfolioSummary()).is_demo).toBe(false)
    expect((await api.getHoldings()).every((h) => !h.is_demo)).toBe(true)
    const h = await api.getHistory("2330.TW", "1Y")
    expect(h.is_demo).toBe(false)
    expect(h.notes?.[0]).toMatch(/^資料累積中：自 \d{4}-\d{2}-\d{2} 起存檔$/)
    expect((await api.getHistory("2330.TW", "1M")).notes).toEqual([])
  })
  it("美股：SEC EDGAR 的財報（美元、公司會計年度）與 8-K／10-Q／10-K 申報", async () => {
    const f = await api.getFinancials("AAPL", "quarterly")
    expect(f).toMatchObject({ currency: "USD", amount_unit: 1, is_demo: false })
    expect(f.periods.at(-1)).toBe("FY2026Q4")
    expect(f.period_ends?.at(-1)).toBe("2026-09-26")
    expect(f.sources[0]).toMatch(/^美國證券交易委員會（SEC）〈EDGAR XBRL 財報數據/)
    expect((await api.getFinancials("AAPL", "annual")).periods.at(-1)).toBe("FY2026")
    const filings = (await api.getEvents("AAPL")).filter((e) => e.type === "sec_filing")
    expect(filings.map((e) => e.form)).toEqual(expect.arrayContaining(["10-K", "10-Q", "8-K"]))
    expect(filings.every((e) => e.url?.startsWith("https://www.sec.gov/Archives/edgar/data/320193/"))).toBe(true)
    expect((await api.getOverview("AAPL")).eps_ttm).toBe(8.98)
    expect((await api.getFinancials("VOO")).notes).toEqual(["ETF 沒有財務報表資料"])
  })
  it("盤中走勢一律沒有點，notes 說明沒有授權來源", async () => {
    const i = await api.getIntraday("2330.TW")
    expect(i.points).toEqual([])
    expect(i.notes?.[0]).toContain("授權")
  })
  it("美股沒有報價：持股 price 為 null、以成本計值；報價 404；含美股時績效為空＋notes", async () => {
    const aapl = (await api.getHoldings()).find((x) => x.symbol === "AAPL")!
    expect(aapl.price).toBeNull()
    expect(aapl.market_value).toBe(aapl.cost_basis)
    await expect(api.getQuote("AAPL")).rejects.toMatchObject({ status: 404 })
    const all = await api.getPerformance({ range: "1Y" })
    expect(all.series).toEqual([])
    expect(all.notes?.join("")).toContain("美股")
    const [tw] = await api.listAccounts()
    const one = await api.getPerformance({ range: "1Y", account_id: tw!.id })
    expect(one.series.length).toBeGreaterThan(20)
    expect(one.series[0]!.twr_index).toBe(1)
    expect(one.notes?.[0]).toContain("資料累積中")
  })
  it("公告取代新聞：source 是「公告」、有 category；上市股票沒有個股法人", async () => {
    const news = await api.getNews("2330.TW")
    expect(news.length).toBeGreaterThan(0)
    expect(news.every((n) => n.source === "公告" && (n.category === "material_info" || n.category === "exchange_news"))).toBe(true)
    const c = await api.getChips("2330.TW", "3M")
    expect(c.institutional).toEqual([])
    expect(c.notes?.[0]).toContain("上市股票")
    expect((await api.getChips("6488.TWO", "1M")).institutional.length).toBeGreaterThan(0)
  })
  it("事件：法說會、預估（法定期限）與期間", async () => {
    const ev = await api.getEvents("2330.TW")
    expect(ev.some((e) => e.type === "investor_conference")).toBe(true)
    const est = ev.find((e) => e.estimated)!
    expect(est.type).toBe("revenue_release")
    expect(est.period).toMatch(/^\d{4}-\d{2}$/)
  })
})

describe("出清紀錄與交易歷史", () => {
  const api = createMockAdapter({ latency: [0, 0] })

  it("出清的股票不在持股，回合有持有期間、已實現、股利與稅費", async () => {
    const rounds = await api.getClosedPositions()
    const holdings = await api.getHoldings()
    expect(rounds.length).toBeGreaterThanOrEqual(2)
    for (const r of rounds) {
      expect(holdings.some((h) => h.symbol === r.symbol)).toBe(false)
      expect(r.closed_at >= r.opened_at).toBe(true)
      expect(r.total_sold_qty).toBe(r.total_bought_qty)
      expect(r.fees_and_taxes).toBeGreaterThan(0)
      expect(r.realized_pnl_pct).toBeCloseTo(r.realized_pnl / r.cost_basis, 4)
    }
    // 最近出清的在前
    expect(rounds.map((r) => r.closed_at)).toEqual([...rounds.map((r) => r.closed_at)].sort().reverse())
    // 長榮持有期間有除息：股利算在回合裡
    expect(rounds.find((r) => r.symbol === "2603.TW")!.dividends_received).toBeGreaterThan(0)
  })
  it("position/history：未持有也有回合與買賣點；從未交易時是空的", async () => {
    const h = await api.getPositionHistory("2603.TW")
    expect(await api.getPosition("2603.TW")).toBeNull()
    expect(h.rounds).toHaveLength(1)
    expect(h.markers.map((m) => m.type)).toEqual(expect.arrayContaining(["buy", "sell", "dividend"]))
    expect(await api.getPositionHistory("2881.TW")).toMatchObject({ rounds: [], markers: [] })
  })
})

describe("定期定額", () => {
  it("CRUD、下一次扣款日、本週事項與草稿（不建立交易）", async () => {
    const api = createMockAdapter({ latency: [0, 0] })
    const [tw, us] = await api.listAccounts()
    const plans = await api.listRecurring()
    expect(plans.map((p) => p.symbol)).toEqual(["0050.TW", "00878.TW"])
    // 今天 11/12 是 00878 的扣款日
    expect(plans[1]!.next_date).toBe("2026-11-12")
    const up = await api.getUpcoming(7)
    expect(up.find((u) => u.type === "recurring")).toMatchObject({ date: "2026-11-12", plan_id: plans[1]!.id, amount_estimate: 4000 })

    const before = (await api.listTransactions({ limit: 200 })).items.length
    const d = await api.draftRecurring(plans[1]!.id)
    expect(d.transaction).toMatchObject({ type: "buy", trade_date: "2026-11-12", source: "ai_draft" })
    expect(d.transaction.quantity).toBe(Math.floor(4000 / d.transaction.price))
    expect(d.preview.tax).toBe(0)
    expect((await api.listTransactions({ limit: 200 })).items.length).toBe(before)

    // 週末順延：每月 14 日（2026-11-14 是星期六）→ 11/16
    const created = await api.createRecurring({ account_id: tw!.id, symbol: "2330.TW", amount: 1000, day_of_month: [14] })
    expect(created.next_date).toBe("2026-11-16")
    const moved = (await api.getUpcoming(7)).find((u) => u.plan_id === created.id)!
    expect(moved).toMatchObject({ date: "2026-11-16", scheduled_date: "2026-11-14" })
    await expect(api.draftRecurring(created.id)).rejects.toMatchObject({ code: "amount_too_small" })

    const paused = await api.updateRecurring(created.id, { active: false })
    expect(paused.next_date).toBeNull()
    await expect(api.createRecurring({ account_id: us!.id, symbol: "VOO", amount: 3000, day_of_month: [5] })).rejects.toMatchObject({ status: 422 })
    await expect(api.createRecurring({ account_id: tw!.id, symbol: "0050.TW", amount: 3000, day_of_month: [29] })).rejects.toMatchObject({ status: 422 })
    await api.deleteRecurring(created.id)
    expect((await api.listRecurring()).length).toBe(2)
  })
})

describe("資料來源與授權", () => {
  it("每個資料集都有完整顯名聲明；commercial 沒有非商用來源", async () => {
    const a = await createMockAdapter({ latency: [0, 0] }).getAttributions()
    expect(a.policy).toBe("commercial")
    expect(a.datasets.length).toBeGreaterThan(20)
    for (const d of a.datasets) {
      // 政府資料開放授權條款：「依…第 1 版」；SEC EDGAR 是美國政府公開資料（授權連結另列）
      const tail = d.key.startsWith("sec-edgar/") ? "美國政府公開資料" : `依${d.license}`
      expect(d.attribution).toBe(`${d.agency}〈${d.dataset}〉（${d.year}），${tail}`)
    }
    expect(a.datasets.filter((d) => d.key.startsWith("sec-edgar/")).map((d) => d.license_url)).toEqual(Array(3).fill("https://www.sec.gov/about/webmaster-frequently-asked-questions"))
    expect(a.datasets.every((d) => d.commercial)).toBe(true)
    const p = await createMockAdapter({ latency: [0, 0], policy: "personal" }).getAttributions()
    expect(p.datasets.some((d) => !d.commercial)).toBe(true)
  })
})
