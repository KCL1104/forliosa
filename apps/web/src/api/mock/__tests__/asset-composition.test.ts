import { describe, expect, it } from "vitest"
import type { Transaction } from "../../types"
import { createMockAdapter } from "../adapter"
import { estimatedSpans, IMPORT_DAY, seedTransactions } from "../ledger"

/** mock 的資產組成原型：示範帳本的匯入庫存、`?composition=off`、`?mock=cashout` */
const buys = (txns: Transaction[], symbol: string) => txns.filter((t) => t.type === "buy" && t.symbol === symbol)

describe("mock：資產組成原型的示範帳本", () => {
  it("#21 匯入庫存的那幾筆和規格一樣：手續費 0、價格是券商的成本、匯入那天是星期六（11/29）", () => {
    const txns = seedTransactions()
    expect(IMPORT_DAY).toBe("2025-11-29")
    const imported = txns.filter((t) => t.date_basis)
    expect(imported.map((t) => [t.symbol, t.date_basis]).sort()).toEqual([["2317.TW", "picked"], ["2454.TW", "import_day"], ["6488.TWO", "estimated"], ["VOO", "estimated"]])
    for (const t of imported) expect(t).toMatchObject({ fee: 0, source: "import", imported_on: "2025-11-29" })
    expect(buys(txns, "2454.TW")[0]).toMatchObject({ trade_date: "2025-11-29", price: 488, estimated_date: null })
    // 估計的那一段：最早的估計到匯入前一個交易日（示範資料沒有國定假日，前一個交易日就是前一個平日）
    expect(estimatedSpans(txns)).toEqual([{ from: "2024-07-29", until: "2025-11-28" }])
  })

  it("#19 ?composition=off：和原本的示範帳本一模一樣（不搬日期、聯發科不是 488、手續費照舊），回應沒有新欄位", async () => {
    const off = createMockAdapter({ latency: [0, 0], composition: false })
    const page = await off.listTransactions({ limit: 200, type: "buy" })
    const all: Transaction[] = [...page.items]
    for (let cursor = page.next_cursor; cursor; ) {
      const next = await off.listTransactions({ limit: 200, type: "buy", cursor })
      all.push(...next.items)
      cursor = next.next_cursor
    }
    expect(buys(all, "6488.TWO")[0]!.trade_date).toBe("2024-05-20")
    expect(buys(all, "VOO")[0]!.trade_date).toBe("2024-02-01")
    expect(buys(all, "2454.TW")[0]).toMatchObject({ trade_date: "2024-10-21", price: 642 })
    expect(buys(all, "2454.TW")[0]!.fee).toBeGreaterThan(0)
    expect(all.some((t) => "date_basis" in t)).toBe(false)
    // 和直接產生原本的示範帳本一樣
    const legacy = seedTransactions({ importedLots: false }).filter((t) => t.type === "buy")
    expect(all.map((t) => [t.symbol, t.trade_date, t.price, t.fee]).sort()).toEqual(legacy.map((t) => [t.symbol, t.trade_date, t.price, t.fee]).sort())
    const perf = await off.getPerformance({ range: "ALL" })
    expect(perf).not.toHaveProperty("composition")
    expect(perf).not.toHaveProperty("fund_rank")
  })

  it("基金排名是編的：標示範資料（is_demo），畫面才會標「示範資料」", async () => {
    const api = createMockAdapter({ latency: [0, 0] })
    expect((await api.getPerformance({ range: "1M" })).fund_rank).toMatchObject({ is_demo: true })
  })

  it("?mock=cashout：賣股票收到的錢比買的多，本金是負的", async () => {
    const api = createMockAdapter({ latency: [0, 0], scenario: "cashout" })
    const perf = await api.getPerformance({ range: "ALL" })
    expect(perf.series.at(-1)!.net_invested).toBeLessThan(0)
  })

  it("?mock=loss（一直虧）：走勢的每一天總資產都在本金下面；主數字的總損益是負的", async () => {
    const api = createMockAdapter({ latency: [0, 0], scenario: "loss" })
    const perf = await api.getPerformance({ range: "ALL" })
    expect(perf.series.length).toBeGreaterThan(100)
    expect(perf.series.every((p) => p.market_value < p.net_invested)).toBe(true)
    expect((await api.getPortfolioSummary()).total_pnl).toBeLessThan(0)
  })

  it("?mock=lastday（最後一天轉虧）：前一天整體還賺，最後一天買進（本金變多）以後收盤是虧的", async () => {
    const api = createMockAdapter({ latency: [0, 0], scenario: "lastday" })
    const { series } = await api.getPerformance({ range: "ALL" })
    const [prev, last] = series.slice(-2) as [(typeof series)[number], (typeof series)[number]]
    expect(prev.market_value - prev.net_invested).toBeGreaterThan(0)
    expect(last.net_invested - prev.net_invested).toBeGreaterThan(400_000)
    expect(last.market_value - last.net_invested).toBeLessThan(0)
    expect(last.market_value - last.net_invested).toBeGreaterThan(-40_000)
  })

  it("?curve=arch（只給截圖用）：「全部」換成最後 9 個收盤的倒 U，最後一天和帳本一樣；其他區間不動", async () => {
    const plain = createMockAdapter({ latency: [0, 0] })
    const api = createMockAdapter({ latency: [0, 0], curve: "arch" })
    const real = await plain.getPerformance({ range: "ALL" })
    const { series, composition } = await api.getPerformance({ range: "ALL" })
    expect(series).toHaveLength(9)
    expect(series.at(-1)!.market_value).toBe(Math.round(real.series.at(-1)!.market_value))
    expect(series[4]!.market_value - series[0]!.market_value).toBe(520_000)
    expect(new Set(series.map((x) => x.net_invested)).size).toBe(1)
    expect(composition).toMatchObject({ dividends: [], estimated: [] })
    expect((await api.getPerformance({ range: "1M" })).series.length).toBeGreaterThan(9)
  })

  it("分兩次匯入：每一次一段估計，兩次之間的真實紀錄不算估計（和後端 estimated_spans 一樣）", () => {
    const txns = seedTransactions()
    const second = { ...buys(txns, "2330.TW")[0]!, id: "txn_second", trade_date: "2026-10-05", date_basis: "estimated" as const, estimated_date: "2026-10-05", imported_on: "2026-11-12" }
    expect(estimatedSpans([...txns, second])).toEqual([
      { from: "2024-07-29", until: "2025-11-28" },
      { from: "2026-10-05", until: "2026-11-11" },
    ])
    // 第二次匯入的估計早於第一段的結尾：併成一段
    expect(estimatedSpans([...txns, { ...second, trade_date: "2025-06-02" }])).toEqual([{ from: "2024-07-29", until: "2026-11-11" }])
    // 連在一起（中間只有週末）：一段
    const a = { ...second, id: "a", trade_date: "2026-10-01", imported_on: "2026-10-11" } // 到 10/9（五）
    const b = { ...second, id: "b", trade_date: "2026-10-12", imported_on: "2026-10-20" } // 從 10/12（一）
    expect(estimatedSpans([a, b])).toEqual([{ from: "2026-10-01", until: "2026-10-19" }])
  })

  it("分割、減資、配股以前的日子不能是匯入的買進日（和後端一樣）：日線的 pick_from、讀截圖的估計、送出、改日期", async () => {
    const api = createMockAdapter({ latency: [0, 0] })
    const h = await api.getHistory("0050.TW", "5Y", { asTraded: true, until: "2026-11-12" })
    expect(h.pick_from).toEqual({ date: "2025-06-18", reason: "split" })
    expect((await api.getHistory("0050.TW", "5Y", { asTraded: true, until: "2025-06-01" })).pick_from).toBeNull()
    expect((await api.getHistory("2330.TW", "5Y", { asTraded: true })).pick_from).toBeNull()
    expect((await api.getHistory("0050.TW", "5Y")).pick_from).toBeUndefined()
    // 讀截圖：分割以前才經過的成本，找不到，句子寫分割那天
    const candles = h.candles.filter((c) => c.t >= "2025-06-18")
    const lo = Math.min(...candles.map((c) => c.l))
    const hi = Math.max(...candles.map((c) => c.h))
    const early = h.candles.find((c) => c.t < "2025-06-18" && (c.h < lo || c.l > hi))!
    const read = await api.parsePositions({ kind: "text", text: `0050 元大台灣50 1000 ${early.c}`, account_id: "acc_01JSINOPAC" })
    expect(read.rows[0]!.estimated_date).toBeNull()
    expect(read.rows[0]!.flags.find((f) => f.code === "no_crossing")!.message).toMatch(/^2025\/6\/18 以後的股價都沒有經過均價 .*（那天股票分割，之前的股價和現在的均價比不起來）。$/)
    // 送出：日期早於分割那天、估計不是估得到的日子
    const row = { symbol: "0050.TW", quantity: 1000, price: 50, currency: "TWD" as const, replace: true }
    const check = await api.checkPositions({ account_id: "acc_01JSINOPAC", rows: [{ ...row, trade_date: "2025-06-17", date_basis: "picked", estimated_date: "2025-06-10" }] })
    expect(check.ok).toBe(false)
    expect(check.rows[0]!.flags.map((f) => [f.code, f.message])).toEqual(expect.arrayContaining([
      ["before_share_change", "2025/6/18 股票分割，買進日期不能早於這一天。"],
      ["bad_estimated_date", "估計的買入日 2025/6/10 不在估得到的期間（2025/6/18 – 2026/11/12）。"],
    ]))
    // 分割那天本身可以；寫進去以後改日期也不能早於它
    const done = await api.commitPositions({ account_id: "acc_01JSINOPAC", rows: [{ ...row, trade_date: "2025-06-18", date_basis: "estimated", estimated_date: "2025-06-18" }] })
    const id = done.created[0]!
    await expect(api.updateTransaction(id, { trade_date: "2025-06-17" })).rejects.toMatchObject({ code: "before_share_change", message: "2025/6/18 股票分割，買進日期不能早於這一天" })
    await expect(api.updateTransaction(id, { trade_date: "2026-11-13" })).rejects.toMatchObject({ code: "after_import_day" })
    expect(await api.updateTransaction(id, { trade_date: "2025-07-01" })).toMatchObject({ date_basis: "picked", estimated_date: "2025-06-18" })
    // 價格改了照舊；換成別的股票：變成一般的紀錄（三個欄位清掉）
    expect(await api.updateTransaction(id, { price: 51 })).toMatchObject({ date_basis: "picked" })
    expect(await api.updateTransaction(id, { symbol: "2330.TW" })).toMatchObject({ date_basis: null, estimated_date: null, imported_on: null })
  })

  it("?mock=cross（賺轉虧）：前面總資產在本金上面、最後在下面", async () => {
    const api = createMockAdapter({ latency: [0, 0], scenario: "cross" })
    const { series } = await api.getPerformance({ range: "ALL" })
    const gain = (p: (typeof series)[number]) => p.market_value - p.net_invested
    expect(gain(series[0]!)).toBeGreaterThan(0)
    expect(series.filter((p) => gain(p) > 0).length).toBeGreaterThan(100)
    expect(gain(series.at(-1)!)).toBeLessThan(0)
  })
})
