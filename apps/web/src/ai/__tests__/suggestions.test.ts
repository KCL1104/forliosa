import { describe, expect, it } from "vitest"
import type { Holding, PortfolioSummary } from "@/api/types"
import { answerFor, classifyQuestion, fallbackAnswer, isConcentrated, ledgerSuggestions, stockSuggestions, type AiContext } from "@/ai/suggestions"
import { MASK } from "@/lib/format"

const TODAY = "2026-11-12"
const h = (p: Partial<Holding>): Holding => ({
  symbol: "2330.TW", code: "2330", name: "台積電", market: "TWSE", type: "stock", currency: "TWD", industry: "半導體業",
  quantity: 1000, avg_cost: 600, cost_basis: 600_000, price: 1000, prev_close: 990, market_value: 1_000_000,
  day_change: 10_000, day_change_pct: 0.0101, unrealized_pnl: 400_000, unrealized_pnl_pct: 0.67, weight: 0.1, account_ids: [], is_demo: true, ...p,
})
const summary = (upcoming: PortfolioSummary["upcoming_dividends"] = []): PortfolioSummary =>
  ({ as_of: "2026-11-12T13:30:00+08:00", upcoming_dividends: upcoming, allocation: { by_industry: [{ key: "半導體業", label: "半導體業", value: 1, weight: 0.3 }] } }) as unknown as PortfolioSummary

describe("帳本的建議問題（依資料自動出現，最多 3 個）", () => {
  it("有下跌的持股 → 誰拖累；有 31 天內除息 → 下個月股利；集中 → 太集中", () => {
    const holdings = [h({ weight: 0.4 }), h({ symbol: "6488.TWO", name: "環球晶", day_change: -7500, day_change_pct: -0.0185, weight: 0.1 })]
    const s = ledgerSuggestions({ holdings, summary: summary([{ symbol: "00878.TW", name: "國泰永續高股息", ex_dividend_date: "2026-11-18", cash_dividend: 0.55, estimated_amount: 11000 }]) }, TODAY)
    expect(s.map((x) => x.kind)).toEqual(["drag", "dividends_next", "concentration"])
  })
  it("全部上漲時改問誰賺最多；沒有除息、不集中就不出現", () => {
    const holdings = Array.from({ length: 10 }, (_, i) => h({ symbol: `${i}`, weight: 0.1 }))
    const s = ledgerSuggestions({ holdings, summary: { ...summary(), allocation: { by_industry: [{ key: "x", label: "x", value: 1, weight: 0.2 }] } } as PortfolioSummary }, TODAY)
    expect(s.map((x) => x.kind)).toEqual(["lift"])
  })
  it("沒有持股：教怎麼記帳", () => {
    expect(ledgerSuggestions({ holdings: [] }, TODAY).map((x) => x.kind)).toEqual(["onboard"])
  })
  it("集中門檻：單一持股 ≥ 15%、前三大 ≥ 45%、單一產業 ≥ 40%", () => {
    expect(isConcentrated([h({ weight: 0.16 })])).toBe(true)
    expect(isConcentrated([h({ weight: 0.14 }), h({ weight: 0.14 }), h({ weight: 0.14 })])).toBe(false)
  })
})

describe("個股頁的建議問題", () => {
  const base = { symbol: "2330.TW", code: "2330", name: "台積電", market: "TWSE" as const, type: "stock" as const }
  it("持有＋異常＋即將除息", () => {
    const s = stockSuggestions(
      {
        ...base,
        quote: { change_pct: 0.048 } as never,
        why: { show: true, headline: "成交量是均量 2 倍", reasons: [], as_of: null },
        overview: { eps_ttm: 52.3, pe: 20 } as never,
        position: { avg_cost: 600, quantity: 1500, upcoming_dividend: { ex_dividend_date: "2026-12-11", amount_estimate: 7500 } } as never,
      },
      TODAY,
    )
    expect(s.map((x) => x.kind)).toEqual(["why_move", "foreign_flow", "next_dividend"])
    expect(s[0]!.text).toBe("台積電今天為什麼漲？")
  })
  it("未持有：外資動向（上市個股）、貴不貴、持有 1 張能領多少", () => {
    const s = stockSuggestions({ ...base, position: null, overview: { pe: 20, last_cash_dividend: 5 } as never }, TODAY)
    expect(s.map((x) => x.kind)).toEqual(["foreign_flow", "is_expensive", "if_hold_dividend"])
    expect(s[0]).toMatchObject({ text: "最近外資對這檔的動向？", lines: ["最近外資", "對這檔的動向？"], symbol: "2330.TW" })
    expect(s.some((x) => /建議|本頁/.test(x.text))).toBe(false)
  })
  it("上市個股才問外資動向：上櫃（頁面有櫃買的法人資料）、上市 ETF、美股不問", () => {
    const kinds = (p: { symbol: string; market: "TWSE" | "TPEX" | "US"; type: "stock" | "etf" }) =>
      stockSuggestions({ ...base, ...p, position: null, overview: { pe: 20 } as never }, TODAY).map((x) => x.kind)
    expect(kinds({ symbol: "6488.TWO", market: "TPEX", type: "stock" })).not.toContain("foreign_flow")
    expect(kinds({ symbol: "0050.TW", market: "TWSE", type: "etf" })).not.toContain("foreign_flow")
    expect(kinds({ symbol: "NVDA", market: "US", type: "stock" })).not.toContain("foreign_flow")
  })
  it("外資動向：自由提問也對得到；本機規則版不給數字，說明原因並連到看得到的資料", () => {
    const ctx: AiContext = { route: "stock", stock: { ...base, position: null } }
    expect(classifyQuestion("外資最近在賣台積電嗎", ctx)).toBe("foreign_flow")
    expect(classifyQuestion("最近外資對這檔的動向？", ctx)).toBe("foreign_flow")
    const tpex: AiContext = { route: "stock", stock: { ...base, symbol: "6488.TWO", market: "TPEX" as const, position: null } }
    expect(classifyQuestion("外資最近在賣嗎", tpex)).toBeNull()
    const a = answerFor("foreign_flow", { ctx, privacy: false, today: TODAY })!
    expect(a.text).toContain("不顯示")
    expect(a.text).not.toMatch(/\d+ 張/)
    expect(a.links!.map((l) => l.search)).toEqual([{ tab: "chips" }, { tab: "events" }])
  })
})

describe("規則版回答：只用使用者自己的資料，隱私模式遮金額", () => {
  const ctx: AiContext = {
    route: "ledger",
    ledger: { holdings: [h({ name: "環球晶", day_change: -7500, day_change_pct: -0.0185 }), h({ name: "國泰永續高股息", day_change: -662, day_change_pct: -0.0022 })], summary: summary() },
  }
  it("誰拖累：依今日損益排序，句子用百分比、數字列用金額", () => {
    const a = answerFor("drag", { ctx, privacy: false, today: TODAY })!
    expect(a.text).toContain("環球晶（▼1.85%）")
    expect(a.rows![0]).toMatchObject({ label: "環球晶", value: "−NT$7,500", tone: "down" })
  })
  it("隱私模式：金額變成遮罩", () => {
    const a = answerFor("drag", { ctx, privacy: true, today: TODAY })!
    expect(a.rows![0]!.value).toBe(MASK)
  })
  it("自由提問分類與誠實的備援回答", () => {
    expect(classifyQuestion("今天是誰拖累我", ctx)).toBe("drag")
    expect(classifyQuestion("持股集中嗎", ctx)).toBe("concentration")
    const f = fallbackAnswer("幫我分析台積電的護城河", ctx)
    expect(f.text).toContain("下一階段")
    expect(f.links!.length).toBeGreaterThan(0)
  })
})
