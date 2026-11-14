import { describe, expect, it } from "vitest"
import { api } from "@/api"
import type { Instrument } from "@/api/types"
import { buildLocalChart, parseChartIntent } from "@/ai/chart-intent"
import { parseIntent } from "@/ai/intent"
import { pickInstrument } from "@/ai/resolve"

/**
 * 商品清單加了全部台股 ETF 與 SEC 的美股代號（待決定事項 1-4、1-5）之後，本機規則對商品的判斷：
 * 中文問句照舊對到台股，英文字只有代號或名稱完全相同才會變成美股。
 */
const resolve = async (target: string) => pickInstrument(target, await api.searchInstruments(target))

const inst = (symbol: string, name: string, market: Instrument["market"] = "TWSE"): Instrument => ({
  symbol, code: symbol.split(".")[0]!, name, market, type: "stock", currency: market === "US" ? "USD" : "TWD", industry: null,
})

describe("pickInstrument：從搜尋結果挑那一檔", () => {
  it("代號、名稱完全相同的優先（不分大小寫；BRK.B 等於 BRK-B）", () => {
    const results = [inst("2330.TW", "台積電"), inst("TSM", "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "US")]
    expect(pickInstrument("tsm", results)?.symbol).toBe("TSM")
    expect(pickInstrument("2330.tw", results)?.symbol).toBe("2330.TW")
    expect(pickInstrument("brk.b", [inst("BRK-B", "BERKSHIRE HATHAWAY INC", "US")])?.symbol).toBe("BRK-B")
    expect(pickInstrument("apple", [inst("AAPL", "Apple", "US")])?.symbol).toBe("AAPL")
  })

  it("英文字只有部分相同時，不會變成某一檔美股", () => {
    const usOnly = [inst("MSFT", "MICROSOFT CORP", "US"), inst("MU", "MICRON TECHNOLOGY INC", "US")]
    expect(pickInstrument("micro", usOnly)).toBeNull()
    expect(pickInstrument("TSMC", [inst("TSM", "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "US"), inst("2330.TW", "台積電")])?.symbol).toBe("2330.TW")
  })

  it("中文名稱照舊取第一筆（內建美股的中文別名：輝達 → NVDA）", () => {
    expect(pickInstrument("輝達", [inst("NVDA", "NVIDIA", "US")])?.symbol).toBe("NVDA")
    expect(pickInstrument("台積", [inst("2330.TW", "台積電")])?.symbol).toBe("2330.TW")
    expect(pickInstrument("沒有這檔", [])).toBeNull()
  })
})

describe("mock 的商品清單：和後端一樣的搜尋規則", () => {
  it("0050 仍然第一；收盤檔裡的 ETF 搜得到", async () => {
    expect((await api.searchInstruments("0050"))[0]!.symbol).toBe("0050.TW")
    expect((await api.searchInstruments("00679b"))[0]).toMatchObject({ symbol: "00679B.TWO", type: "etf", industry: "ETF", has_quote: true })
    expect((await api.searchInstruments("主動統一"))[0]!.symbol).toBe("00981A.TW")
    expect((await api.getInstrument("00981A.TW")).data_sources[0]).toContain("上市個股日成交資訊")
  })

  it("SEC 的美股：只有英文查詢搜得到、代號完全相同才排第一，其他排在台股後面，標「沒有報價」", async () => {
    for (const q of ["台積", "微軟", "2330", "00", "高股息"]) {
      const hits = await api.searchInstruments(q)
      expect(hits.some((h) => ["MSFT", "TSM", "TSLA", "T", "AMZN"].includes(h.symbol)), q).toBe(false)
    }
    expect((await api.searchInstruments("T"))[0]).toMatchObject({ symbol: "T", name: "AT&T INC.", market: "US", has_quote: false })
    expect((await api.searchInstruments("microsoft"))[0]!.symbol).toBe("MSFT")
    expect((await api.searchInstruments("BRK.B"))[0]!.symbol).toBe("BRK-B")
    const detail = await api.getInstrument("MSFT")
    expect(detail).toMatchObject({ name: "MICROSOFT CORP", industry: null, summary: null, has_quote: false })
    expect(detail.data_sources[0]).toContain("company_tickers.json")
  })
})

describe("中文問句照舊（本機規則 + mock 的搜尋）", () => {
  it("記帳指令：台積電、0050、鴻海；美股代號照樣記", async () => {
    for (const [text, symbol] of [["買台積電 1 張", "2330.TW"], ["買 0050 2 張 52.4", "0050.TW"], ["賣 2317 1 張", "2317.TW"], ["買 T 10 股 26", "T"], ["買 brk.b 1 股", "BRK-B"]] as const) {
      const intent = parseIntent(text, "2026-11-12")
      expect(intent.kind, text).toBe("trade")
      if (intent.kind === "trade") expect((await resolve(intent.target))?.symbol, text).toBe(symbol)
    }
  })

  it("「畫 2330 的月營收」「比較台積電和鴻海」畫的和以前一樣", async () => {
    const deps = { api, resolve, today: "2026-11-13", newId: (p: string) => `${p}_t` }
    const revenue = parseChartIntent("畫 2330 的月營收")!
    expect(revenue).toEqual({ kind: "revenue", targets: ["2330"], range: "6M" })
    const r = await buildLocalChart(revenue, deps)
    expect(r.chart?.series.map((s) => s.symbol)).toEqual(["2330.TW"])
    const compare = parseChartIntent("比較台積電和鴻海")!
    expect(compare).toEqual({ kind: "compare", targets: ["台積電", "鴻海"], range: "6M" })
    const c = await buildLocalChart(compare, deps)
    expect(c.chart?.series.map((s) => s.symbol)).toEqual(["2330.TW", "2317.TW"])
  })

  it("K 線與技術指標的縮寫不是另一檔（K、KD、MA 也是美股代號）", () => {
    expect(parseChartIntent("畫 2330 的 K 線")).toEqual({ kind: "price", targets: ["2330"], range: "6M" })
    expect(parseChartIntent("畫台積電的日K")).toEqual({ kind: "price", targets: ["台積電"], range: "6M" })
    expect(parseChartIntent("畫 2330 的 KD 和 5MA")).toEqual({ kind: "price", targets: ["2330"], range: "6M" })
    expect(parseChartIntent("比較 0050 和 VOO")?.targets).toEqual(["0050", "VOO"])
  })
})
