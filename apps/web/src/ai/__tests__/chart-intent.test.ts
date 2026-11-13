import { describe, expect, it } from "vitest"
import { buildLocalChart, chartRange, parseChartIntent } from "@/ai/chart-intent"
import type { Financials, ForliosaApi, History, Instrument, MonthlyRevenue, Performance } from "@/api/types"

const inst = (code: string, name: string, p: Partial<Instrument> = {}): Instrument => ({ symbol: `${code}.TW`, code, name, market: "TWSE", type: "stock", currency: "TWD", industry: null, ...p })
const BOOK: Record<string, Instrument> = {
  "2330": inst("2330", "台積電"),
  台積電: inst("2330", "台積電"),
  "2317": inst("2317", "鴻海"),
  鴻海: inst("2317", "鴻海"),
  "0050": inst("0050", "元大台灣50", { type: "etf" }),
  和碩: inst("4938", "和碩"),
}
const resolve = async (t: string) => BOOK[t] ?? null

const history = (symbol: string, closes: number[], start = 1, notes: string[] = []): History => ({
  symbol,
  interval: "1d",
  candles: closes.map((c, i) => ({ t: `2026-10-${String(start + i).padStart(2, "0")}`, o: c, h: c, l: c, c, v: 1 })),
  is_demo: false,
  sources: ["臺灣證券交易所〈上市個股日成交資訊〉"],
  notes,
})

function fakeApi(over: Partial<ForliosaApi> = {}): ForliosaApi {
  return {
    kind: "mock",
    getHistory: async (symbol: string) =>
      symbol === "2330.TW" ? history(symbol, [100, 110, 121]) : symbol === "2317.TW" ? history(symbol, [200, 190], 2, ["資料從 2026/10/02 開始"]) : history(symbol, [50]),
    getRevenue: async (symbol: string): Promise<MonthlyRevenue[]> =>
      symbol === "2330.TW" ? ["2026-09", "2026-10", "2026-08"].map((period, i) => ({ period, revenue: 300 + i, yoy_pct: null, mom_pct: null, ytd: null, ytd_yoy_pct: null })) : [],
    getFinancials: async () => ({ periods: ["2026Q1", "2026Q2"], income: { eps: [10, null] }, sources: ["季報"] }) as unknown as Financials,
    getPerformance: async () =>
      ({
        range: "6M",
        benchmark: { symbol: "0050.TW", name: "元大台灣50", twr: 0.1 },
        series: [
          { t: "2026-10-01", twr_index: 1, benchmark_index: 1, market_value: 3_000_000, net_invested: 2_000_000 },
          { t: "2026-10-02", twr_index: 1.02, benchmark_index: 1.01, market_value: 3_060_000, net_invested: 2_000_000 },
        ],
        is_demo: true,
        notes: [],
      }) as unknown as Performance,
    ...over,
  } as ForliosaApi
}

const deps = (api = fakeApi()) => ({ api, resolve, today: "2026-11-13", newId: (p: string) => `${p}_test` })

describe("parseChartIntent：哪些句子是要畫圖", () => {
  it("畫一檔的走勢、比較幾檔、營收、EPS、自己的報酬率", () => {
    expect(parseChartIntent("畫 0050 的走勢")).toEqual({ kind: "price", targets: ["0050"], range: "6M" })
    expect(parseChartIntent("比較 2330 和 2317")).toEqual({ kind: "compare", targets: ["2330", "2317"], range: "6M" })
    expect(parseChartIntent("比較台積電和鴻海這一年的表現")).toEqual({ kind: "compare", targets: ["台積電", "鴻海"], range: "1Y" })
    expect(parseChartIntent("2330、2317、0050 比一比")).toEqual({ kind: "compare", targets: ["2330", "2317", "0050"], range: "6M" })
    expect(parseChartIntent("畫台積電的月營收")).toEqual({ kind: "revenue", targets: ["台積電"], range: "6M" })
    expect(parseChartIntent("畫 2330、2317 的 EPS")).toEqual({ kind: "eps", targets: ["2330", "2317"], range: "6M" })
    expect(parseChartIntent("畫我的報酬率走勢")).toEqual({ kind: "performance", targets: [], range: "6M" })
    // 名稱開頭的「和」是名稱的一部分
    expect(parseChartIntent("比較台積電、和碩")?.targets).toEqual(["台積電", "和碩"])
    expect(parseChartIntent("比較 1、2、3、4、5、6、7")?.targets).toHaveLength(5)
  })

  it("不是要畫圖的句子不接（交給記帳與其他規則）", () => {
    for (const t of ["買 0050 2 張 52.4", "誰拖累了我的報酬？", "台積電今天怎麼樣", "0050 配息 1,100", "比較", "畫", ""]) {
      expect(parseChartIntent(t), t).toBeNull()
    }
  })

  it("區間：沒說是半年", () => {
    expect(chartRange("近三個月")).toBe("3M")
    expect(chartRange("今年以來")).toBe("YTD")
    expect(chartRange("五年")).toBe("5Y")
    expect(chartRange("最近 1 個月")).toBe("1M")
    expect(chartRange("隨便")).toBe("6M")
  })
})

describe("buildLocalChart：用 API 的資料組出和後端同樣形狀的圖卡", () => {
  it("收盤走勢：每個點是 API 的收盤價", async () => {
    const out = await buildLocalChart({ kind: "price", targets: ["2330"], range: "6M" }, deps())
    expect(out.chart).toMatchObject({ id: "cht_test", kind: "price", unit: "price", currency: "TWD", x: "date", title: "台積電 收盤價（近 6 個月）", is_demo: false })
    expect(out.chart!.series).toEqual([{ name: "台積電", symbol: "2330.TW", points: [{ t: "2026-10-01", v: 100 }, { t: "2026-10-02", v: 110 }, { t: "2026-10-03", v: 121 }] }])
    expect(out.chart!.notes).toContain("收盤價沒有還原權息，除權息日會有缺口")
    expect(out.text).toBe("台積電近 6 個月的收盤走勢畫好了。")
  })

  it("比較：從共同的第一天起算，都從 0 開始；資料不足的那一檔說明沒有畫", async () => {
    const out = await buildLocalChart({ kind: "compare", targets: ["2330", "鴻海", "0050", "不存在"], range: "1Y" }, deps())
    const c = out.chart!
    expect(c.title).toBe("台積電、鴻海 漲跌幅（近 1 年）")
    expect(c.series.map((s) => [s.symbol, s.points])).toEqual([
      ["2330.TW", [{ t: "2026-10-02", v: 0 }, { t: "2026-10-03", v: 0.1 }]],
      ["2317.TW", [{ t: "2026-10-02", v: 0 }, { t: "2026-10-03", v: -0.05 }]],
    ])
    expect(c.notes).toEqual(["找不到「不存在」，沒有畫", "資料從 2026/10/02 開始", "元大台灣50：收盤價不到兩天，沒有畫", "漲跌幅只算價格變動，不含股利"])
    expect(c.unit).toBe("pct")
    const lonely = await buildLocalChart({ kind: "compare", targets: ["2330", "0050"], range: "6M" }, deps())
    expect(lonely.chart).toBeNull()
    expect(lonely.text).toContain("要比較至少需要兩檔有收盤價的商品")
  })

  it("月營收照月份排；ETF 沒有營收；每股盈餘只留有數字的季", async () => {
    const rev = await buildLocalChart({ kind: "revenue", targets: ["2330", "0050"], range: "6M" }, deps())
    expect(rev.chart!.series).toEqual([{ name: "台積電", symbol: "2330.TW", points: [{ t: "2026-08", v: 302 }, { t: "2026-09", v: 300 }, { t: "2026-10", v: 301 }] }])
    expect(rev.chart).toMatchObject({ unit: "amount_k", x: "month", range: null, notes: ["元大台灣50 沒有月營收資料"] })
    const eps = await buildLocalChart({ kind: "eps", targets: ["2330"], range: "6M" }, deps())
    expect(eps.chart!.series[0]!.points).toEqual([{ t: "2026Q1", v: 10 }])
    expect(eps.chart).toMatchObject({ unit: "eps", x: "quarter", sources: ["季報"] })
    const none = await buildLocalChart({ kind: "revenue", targets: ["0050"], range: "6M" }, deps())
    expect(none).toEqual({ chart: null, text: "元大台灣50 沒有月營收資料。" })
  })

  it("我的報酬率只有百分比，沒有任何金額", async () => {
    const out = await buildLocalChart({ kind: "performance", targets: [], range: "6M" }, deps())
    expect(out.chart!.series).toEqual([
      { name: "我的報酬率", symbol: null, points: [{ t: "2026-10-01", v: 0 }, { t: "2026-10-02", v: 0.02 }] },
      { name: "元大台灣50", symbol: "0050.TW", points: [{ t: "2026-10-01", v: 0 }, { t: "2026-10-02", v: 0.01 }] },
    ])
    expect(JSON.stringify(out.chart)).not.toMatch(/3000000|market_value|net_invested/)
    const short = await buildLocalChart({ kind: "performance", targets: [], range: "6M" }, deps(fakeApi({ getPerformance: async () => ({ series: [], notes: ["美股沒有報價，含美股的績效算不出來"] }) as unknown as Performance })))
    expect(short).toEqual({ chart: null, text: "美股沒有報價，含美股的績效算不出來。" })
  })

  it("找不到任何一檔：說明一句，不畫", async () => {
    expect(await buildLocalChart({ kind: "price", targets: ["不存在"], range: "6M" }, deps())).toEqual({ chart: null, text: "找不到「不存在」。換個代號試試，例如 0050、2330。" })
  })
})
