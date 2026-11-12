import { describe, expect, it } from "vitest"
import { createMockAdapter } from "@/api/mock/adapter"
import { findInstrument } from "@/api/mock/instruments"
import { closeOn } from "@/api/mock/market"

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
    const c = await api.getChips("6488.TWO", "1M")
    expect(c.institutional[0]).toEqual(expect.objectContaining({ foreign: expect.any(Number), total: expect.any(Number) }))
    // 上市股票：任何模式都沒有逐檔三大法人與外資持股（融資融券、股權分散照常）
    const listed = await api.getChips("2330.TW", "1M")
    expect([listed.institutional, listed.foreign_holding_pct]).toEqual([[], []])
    expect(listed.margin.length).toBeGreaterThan(0)
    expect(listed.notes?.[0]).toContain("上市股票")
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
    // 股票分割：沒被重編的舊年度已換算成目前的股數（NVIDIA 2021 年 1 拆 4、2024 年 1 拆 10），不會出現 3.85 → 0.17
    const nvda = await api.getFinancials("NVDA", "annual")
    const shares = (nvda.shares?.diluted_average ?? []).filter((v): v is number => v !== null)
    expect(shares.length).toBe(nvda.periods.length)
    expect(Math.max(...shares) / Math.min(...shares)).toBeLessThan(1.1)
    expect(nvda.income.eps[nvda.periods.indexOf("FY2022")]).toBe(0.385)
    expect(nvda.notes?.some((n) => n.includes("2024-08-28 起申報的財報反映 1 股拆成 10 股"))).toBe(true)
    // 美股沒有可商用的配息來源：股利是空的（畫面要說「沒有來源」，不是「沒有配過息」）
    expect(await api.getDividends("VOO")).toEqual([])
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
  it("公告在前、新聞報導在後；新聞報導只有標題、媒體、時間、連結；上市股票沒有個股法人", async () => {
    const news = await api.getNews("2330.TW")
    const official = news.filter((n) => n.category !== "media")
    const media = news.filter((n) => n.category === "media")
    expect(official.length).toBeGreaterThan(0)
    expect(official.every((n) => n.source === "公告" && (n.category === "material_info" || n.category === "exchange_news"))).toBe(true)
    expect(news.indexOf(media[0]!)).toBe(official.length)
    expect(media.length).toBeGreaterThan(8)
    expect(media.every((n) => n.outlet && /^https:\/\//.test(n.url) && ["GDELT", "SearXNG", "AI 搜尋"].includes(n.source))).toBe(true)
    // SearXNG（自架元搜尋）預設開啟：它找到的標題標「SearXNG」，顯名是後端 datapolicy 的 searxng
    expect(media.some((n) => n.source === "SearXNG" && n.sources?.[0]?.startsWith("SearXNG 自架元搜尋"))).toBe(true)
    // 商用模式沒有 Yahoo股市 RSS（條款限非商用）
    expect(media.some((n) => n.source === "Yahoo股市")).toBe(false)
    expect(media.some((n) => n.source === "GDELT" && n.sources?.[0]?.includes("gdeltproject.org"))).toBe(true)
    expect((await api.getNews("2317.TW")).filter((n) => n.category === "media")).toEqual([])
    // 示範新聞不掛真實媒體：媒體名稱都有「示範」或 Demo、連到 example.com（審查 2026-11-12）
    for (const sym of ["2330.TW", "2454.TW", "6488.TWO", "NVDA"]) {
      for (const n of (await api.getNews(sym)).filter((x) => x.category === "media")) {
        expect(n.outlet).toMatch(/示範|Demo/)
        expect(new URL(n.url).hostname).toBe("example.com")
      }
    }
    const c = await api.getChips("2330.TW", "3M")
    expect(c.institutional).toEqual([])
    expect(c.notes?.[0]).toContain("上市股票")
    expect((await api.getChips("6488.TWO", "1M")).institutional.length).toBeGreaterThan(0)
  })
  it("上市股票：名列外資持股前 20 名才有外資持股比（名次＋說明）", async () => {
    const ase = await api.getChips("3711.TW", "1M")
    expect(ase.foreign_top20).toEqual({ as_of: "2026-11-12", rank: 12, pct: 0.7552, limit_pct: 1 })
    expect(ase.foreign_holding_pct.at(-1)?.pct).toBe(0.7552)
    // 在榜時仍說明為什麼沒有三大法人（與後端相同），再加前 20 名的說明
    expect(ase.notes?.[0]).toContain("上市股票")
    expect(ase.notes?.[0]).toContain("以付費商品提供")
    expect(ase.notes?.[1]).toContain("前 20 名")
    expect(ase.sources.join("")).toContain("外資及陸資持股前20名彙總表")
    const tsmc = await api.getChips("2330.TW", "1M")
    expect(tsmc.foreign_top20).toBeNull()
    expect(tsmc.foreign_holding_pct).toEqual([])
  })
  it("相關股票：基準不寫「持有本股」、關係企業、同業；ETF 頁同指數；美股沒有", async () => {
    const r = await api.getRelated("2330.TW")
    expect(r.items.map((c) => [c.symbol, c.reason])).toEqual([
      ["0050.TW", "benchmark"], ["3443.TW", "affiliate"], ["2454.TW", "peer"], ["3711.TW", "peer"],
    ])
    expect(r.items[0]!.reason_label).toBe("你的比較基準")
    expect(r.items.every((c) => !c.reason_label.includes("持有本股") && c.sparkline.length >= 15)).toBe(true)
    expect(r.notes).toEqual(["關係企業依董監事持股餘額明細（2026 年 9 月）"])
    const gw = await api.getRelated("6488.TWO")
    expect(gw.items[0]).toMatchObject({ symbol: "006201.TWO", reason: "constituent", reason_label: "富櫃五十成分股（櫃買中心公布）" })
    expect(gw.items[1]).toMatchObject({ symbol: "5483.TWO", reason: "affiliate", reason_label: "環球晶的法人董事及大股東" })
    const hon = await api.getRelated("2317.TW")
    expect(hon.items.filter((c) => c.reason === "affiliate").map((c) => c.symbol).sort()).toEqual(["2258.TW", "2328.TW"])
    const etf = await api.getRelated("0050.TW")
    expect(etf.items.map((c) => [c.symbol, c.reason])[0]).toEqual(["006208.TW", "same_index"])
    expect((await api.getRelated("AAPL")).items).toEqual([])
  })
  it("關於〈公司〉：官方資料（董事長、總經理照原文）、維基百科節錄或 AI 簡介", async () => {
    const c = await api.getCompany("2330.TW")
    expect([c.chairman, c.president, c.hq, c.website, c.years_since_incorporation]).toEqual(["魏哲家", "總裁: 魏哲家", "新竹科學園區", "https://www.tsmc.com", 39])
    expect(c.description).toMatchObject({ kind: "wikipedia", label: "節錄", license: "CC BY-SA 4.0" })
    expect(c.sources.join("")).toContain("CC BY-SA 4.0")
    const gw = await api.getCompany("6488.TWO")
    expect(gw.description).toMatchObject({ kind: "ai", label: "AI 依公開資料整理" })
    // AI 簡介用到 ESG 產品類別：來源也列 ESG 資料集
    expect(gw.sources.join("")).toContain("上櫃公司企業ESG資訊揭露彙總資料-產品品質與安全")
    expect(gw.description!.text).not.toContain(gw.chairman!)
    expect((await api.getCompany("AAPL")).hq).toBe("Cupertino, CA")
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
    expect(d.price_as_of).toBe("2026-11-12")
    expect(d.transaction.quantity).toBe(Math.floor(4000 / d.transaction.price))
    expect(d.preview.tax).toBe(0)
    expect((await api.listTransactions({ limit: 200 })).items.length).toBe(before)

    // 補記過去的扣款（0050 的 11/6）：成交日是扣款日，用那天的收盤價，不是最近收盤價
    const missed = await api.draftRecurring(plans[0]!.id, "2026-11-06")
    const close = closeOn(findInstrument("0050.TW")!, "2026-11-06")
    expect(missed).toMatchObject({ date: "2026-11-06", price_as_of: "2026-11-06" })
    expect(missed.transaction).toMatchObject({ trade_date: "2026-11-06", price: close, quantity: Math.floor(10_000 / close) })
    expect(close).not.toBe(findInstrument("0050.TW")!.price)
    expect(missed.preview.rules[0]).toContain("（11/6）")

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
      // GDELT（新聞報導）：使用條款要求引用並連回 gdeltproject.org；維基百科 CC BY-SA 4.0 節錄、Wikidata CC0
      const special: Record<string, string> = {
        "gdelt/doc": "依 GDELT 使用條款引用：https://www.gdeltproject.org/",
        "wikipedia/zh": "依 CC BY-SA 4.0 節錄（不改寫）",
        "wikidata/entities": "CC0 1.0（公眾領域）",
      }
      const tail = d.key.startsWith("sec-edgar/") ? "美國政府公開資料" : special[d.key] ?? `依${d.license}`
      expect(d.attribution).toBe(`${d.agency}〈${d.dataset}〉（${d.year}），${tail}`)
    }
    expect(a.datasets.filter((d) => d.key.startsWith("sec-edgar/")).map((d) => d.license_url)).toEqual(Array(3).fill("https://www.sec.gov/about/webmaster-frequently-asked-questions"))
    expect(a.datasets.every((d) => d.commercial)).toBe(true)
    expect(a.datasets.some((d) => d.key === "yahoo-rss/stock")).toBe(false)
    const p = await createMockAdapter({ latency: [0, 0], policy: "personal" }).getAttributions()
    expect(p.datasets.some((d) => !d.commercial)).toBe(true)
    expect(p.datasets.find((d) => d.key === "yahoo-rss/stock")?.commercial).toBe(false)
  })

  it("美股的台幣金額附上中央銀行收盤匯率的顯名聲明", async () => {
    const fx = "中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版"
    const api = createMockAdapter({ latency: [0, 0] })
    expect((await api.getAttributions()).datasets.map((d) => d.attribution)).toContain(fx)
    const holdings = await api.getHoldings()
    const us = holdings.find((h) => h.currency === "USD")!
    expect((await api.getPosition(us.symbol))!.sources).toEqual(["本系統帳本", fx])
    const tw = holdings.find((h) => h.currency === "TWD")!
    expect((await api.getPosition(tw.symbol))!.sources).toEqual(["本系統帳本"])
  })
})
