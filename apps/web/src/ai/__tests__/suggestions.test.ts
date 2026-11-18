import { describe, expect, it } from "vitest"
import type { Concentration, Holding, PortfolioSummary } from "@/api/types"
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

describe("會不會太集中：和「配置」分段同一份數字（summary.concentration，2026-11-18）", () => {
  const conc = (p: Partial<Concentration> = {}): Concentration => ({
    holdings_count: 9,
    top_holding: { symbol: "2330.TW", name: "台積電", weight: 0.396, is_etf: false },
    top3_weight: 0.613,
    top5_weight: 0.784,
    top_industry: { key: "半導體業", label: "半導體業", weight: 0.563 },
    etf_weight: 0.225,
    limits: { holding: null, industry: null },
    over_limits: [],
    ...p,
  })
  const withConc = (c: Concentration) => ({ ...summary(), concentration: c }) as PortfolioSummary
  const holdings = [h({ weight: 0.12 }), h({ symbol: "2317.TW", name: "鴻海", weight: 0.11 })]

  it("沒設上限：用集中度的數字照舊的提示門檻（最大產業不含 ETF）", () => {
    expect(isConcentrated(holdings, withConc(conc()))).toBe(true)
    expect(isConcentrated(holdings, withConc(conc({ top_holding: { symbol: "x", name: "x", weight: 0.1, is_etf: false }, top3_weight: 0.3, top_industry: { key: "y", label: "y", weight: 0.2 } })))).toBe(false)
  })
  it("自己設了上限：只看自己的上限——有超過才問，沒超過就不問（就算數字很集中）", () => {
    const limits = { holding: 0.5, industry: 0.6 }
    expect(isConcentrated(holdings, withConc(conc({ limits })))).toBe(false)
    const over = conc({ limits: { holding: 0.3, industry: null }, over_limits: [{ kind: "holding", key: "2330.TW", label: "台積電", weight: 0.396, limit: 0.3 }] })
    expect(isConcentrated(holdings, withConc(over))).toBe(true)
    expect(ledgerSuggestions({ holdings, summary: withConc(conc({ limits })) }, TODAY).map((x) => x.kind)).not.toContain("concentration")
  })
  it("回答只寫事實：最大一檔、前 5 大、最大產業（不含 ETF）；有上限時寫超過了哪些，不說該怎麼做；連到配置", () => {
    const ctx = (c: Concentration): AiContext => ({ route: "ledger", ledger: { holdings, summary: withConc(c) } })
    const plain = answerFor("concentration", { ctx: ctx(conc()), privacy: false, today: TODAY })!
    expect(plain.text).toBe("最大的一檔是台積電，佔 39.6%；前 5 大合計 78.4%；最大的產業是半導體業，佔 56.3%（不含 ETF）。")
    expect(plain.links).toEqual([{ label: "看配置", to: "/", search: { view: "allocation" } }])
    const over = conc({
      limits: { holding: 0.3, industry: 0.5 },
      over_limits: [
        { kind: "holding", key: "2330.TW", label: "台積電", weight: 0.396, limit: 0.3 },
        { kind: "industry", key: "半導體業", label: "半導體業", weight: 0.563, limit: 0.5 },
      ],
    })
    const a = answerFor("concentration", { ctx: ctx(over), privacy: true, today: TODAY })!
    expect(a.text).toContain("超過你設定的上限：台積電 39.6%（上限 30%）、半導體業 56.3%（上限 50%）。")
    expect(a.text).not.toMatch(/建議|應該|減碼|賣出/)
    const under = answerFor("concentration", { ctx: ctx(conc({ limits: { holding: 0.5, industry: null } })), privacy: false, today: TODAY })!
    expect(under.text).toContain("沒有超過你設定的上限。")
    // 持股 5 檔以下：寫前 3 大
    expect(answerFor("concentration", { ctx: ctx(conc({ holdings_count: 4 })), privacy: false, today: TODAY })!.text).toContain("前 3 大合計 61.3%")
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
  it("收盤價還不是今天的（盤中、今天的還沒進來）：問「台積電 11/12 為什麼漲？」，不說「今天」", () => {
    const s = stockSuggestions(
      { ...base, quote: { change_pct: 0.048, as_of: "2026-11-12T13:30:00+08:00" } as never, why: { show: true, headline: "成交量是均量 2 倍", reasons: [], as_of: null } },
      "2026-11-13",
    )
    expect(s[0]!.text).toBe("台積電 11/12 為什麼漲？")
    expect(stockSuggestions({ ...base, quote: { change_pct: 0.048, as_of: "2026-11-13T13:30:00+08:00" } as never, why: { show: true, headline: "x", reasons: [], as_of: null } }, "2026-11-13")[0]!.text).toBe("台積電今天為什麼漲？")
  })
  it("未持有：外資動向（上市個股）、貴不貴、持有 1 張能領多少", () => {
    const s = stockSuggestions({ ...base, position: null, overview: { pe: 20, last_cash_dividend: 5 } as never }, TODAY)
    expect(s.map((x) => x.kind)).toEqual(["foreign_flow", "is_expensive", "if_hold_dividend"])
    expect(s[0]).toMatchObject({ text: "最近外資對這檔的動向？", symbol: "2330.TW" })
    expect(s.some((x) => /建議|本頁/.test(x.text))).toBe(false)
  })
  it("美股的漲跌是紐約那一天的：問句與回答寫「11/13（美東）」不寫「今天」；沒有法人與籌碼，只連到事件；追問以股計", () => {
    const us = {
      symbol: "AAPL", code: "AAPL", name: "Apple", market: "US" as const, type: "stock" as const,
      quote: { price: 356.27, change_pct: 0.0179, as_of: "2026-11-14T05:00:00+08:00", trade_date: "2026-11-13" } as never,
      why: { show: true, headline: "成交量是均量 2 倍", reasons: [], as_of: "2026-11-14T05:00:00+08:00", trade_date: "2026-11-13" },
    }
    const s = stockSuggestions({ ...us, position: null }, TODAY)
    expect(s[0]).toMatchObject({ kind: "why_move", text: "Apple 11/13（美東）為什麼漲？" })
    const held: AiContext = { route: "stock", stock: { ...us, position: { avg_cost: 143.41, quantity: 15 } as never } }
    const a = answerFor("why_move", { ctx: held, privacy: false, today: TODAY })!
    expect(a.text).toBe("Apple 11/13（美東）上漲 1.79%：成交量是均量 2 倍。")
    expect(a.text).not.toContain("今天")
    expect(a.links!.map((l) => l.search)).toEqual([{ tab: "events" }])
    expect(a.followUps).toEqual(["加碼 10 股，均價會變多少？"])
    // 回答下面的「收盤」是台北的日期，美股不放
    expect(a.asOf ?? null).toBeNull()
    // 沒持有：美股沒有本益比資料，不追問貴不貴
    const notHeld = answerFor("why_move", { ctx: { route: "stock", stock: { ...us, position: null } }, privacy: false, today: TODAY })!
    expect(notHeld.followUps).toEqual([])
    // 平常範圍：不說「法人」，連到事件
    const quiet = answerFor("why_move", { ctx: { route: "stock", stock: { ...us, why: { ...us.why, show: false } } }, privacy: false, today: TODAY })!
    expect(quiet.text).toBe("Apple 11/13（美東）的漲跌在平常的範圍內（上漲 1.79%），沒有出現異常的成交量或事件。")
    expect(quiet.links!.map((l) => l.search)).toEqual([{ tab: "events" }])
  })

  it("台股的漲跌照舊：「今天」、連到籌碼與事件、追問 1 張", () => {
    const tw: AiContext = {
      route: "stock",
      stock: {
        ...base,
        quote: { price: 1085, change_pct: 0.048, as_of: "2026-11-12T13:30:00+08:00" } as never,
        why: { show: true, headline: "成交量是均量 2 倍", reasons: [], as_of: "2026-11-12T13:30:00+08:00" },
        position: { avg_cost: 600, quantity: 1000 } as never,
      },
    }
    const a = answerFor("why_move", { ctx: tw, privacy: false, today: TODAY })!
    expect(a.text).toBe("台積電今天上漲 4.80%：成交量是均量 2 倍。")
    expect(a.links!.map((l) => l.label)).toEqual(["看籌碼", "看事件"])
    expect(a.followUps).toEqual(["加碼 1 張，均價會變多少？"])
    expect(a.asOf).toBe("2026-11-12T13:30:00+08:00")
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
    // 只說事實（沒有逐檔資料）；授權的原因只在「資料來源與授權」頁講
    expect(a.text).toBe("台積電沒有逐檔的外資買賣資料。")
    expect(a.text).not.toMatch(/可商用|付費|每一點都要附來源/)
    expect(a.text).not.toMatch(/\d+ 張/)
    expect(a.links!.map((l) => l.search)).toEqual([{ tab: "chips" }, { tab: "events" }])
  })
})

describe("規則版回答：只用使用者自己的資料，隱私模式遮金額", () => {
  const ctx: AiContext = {
    route: "ledger",
    ledger: { holdings: [h({ name: "環球晶", day_change: -7500, day_change_pct: -0.0185 }), h({ name: "國泰永續高股息", day_change: -662, day_change_pct: -0.0022 })], summary: summary() },
  }
  it("誰拖累：依今日損益排序，句子用文字說漲跌（▲▼ 只在數字列），數字列用金額＋百分比", () => {
    const a = answerFor("drag", { ctx, privacy: false, today: TODAY })!
    expect(a.text).toContain("環球晶（下跌 1.85%）")
    expect(a.text).not.toMatch(/[▲▼]/)
    expect(a.rows![0]).toMatchObject({ label: "環球晶", value: "−NT$7,500", tone: "down", hint: "▼1.85%" })
  })
  it("隱私模式：金額變成遮罩", () => {
    const a = answerFor("drag", { ctx, privacy: true, today: TODAY })!
    expect(a.rows![0]!.value).toBe(MASK)
  })
  it("自由提問分類與誠實的備援回答", () => {
    expect(classifyQuestion("今天是誰拖累我", ctx)).toBe("drag")
    expect(classifyQuestion("持股集中嗎", ctx)).toBe("concentration")
    const f = fallbackAnswer("幫我分析台積電的護城河", ctx)
    // 現在式：只說現在能做什麼，不承諾時程，也不扮演 AI 的人格
    expect(f.text).toBe("這題要查網路資料，現在沒辦法。")
    expect(f.text).not.toMatch(/下一階段|開放|猜的答案/)
    expect(f.links!.length).toBeGreaterThan(0)
  })
})

describe("帳本的「誰拖累／誰賺最多」說的是哪一天（美股的收盤是紐約另一天的）", () => {
  /** 紐約 11/13（五）的收盤：as_of 是紐約 16:00＝台北 11/14 05:00 */
  const usSummary = { ...summary(), as_of: "2026-11-14T05:00:00+08:00" } as PortfolioSummary
  const apple = h({ symbol: "AAPL", code: "AAPL", name: "Apple", market: "US", currency: "USD", price: 356.27, price_date: "2026-11-13", day_change: -4200, day_change_pct: -0.021, weight: 0.1 })
  const nvidia = h({ symbol: "NVDA", code: "NVDA", name: "輝達", market: "US", currency: "USD", price: 190, price_date: "2026-11-13", day_change: 3100, day_change_pct: 0.012, weight: 0.1 })

  it("只有美股：問句與回答寫「11/13（美東）」，不寫「今天」或台北的「11/14」；回答下面不放台北日期的「收盤」", () => {
    for (const today of ["2026-11-14", "2026-11-16"]) {
      const s = ledgerSuggestions({ holdings: [apple, nvidia], summary: usSummary }, today)
      expect(s[0]).toEqual({ kind: "drag", text: "11/13（美東）誰拖累了我的報酬？" })
      const ctx: AiContext = { route: "ledger", ledger: { holdings: [apple, nvidia], summary: usSummary } }
      const a = answerFor("drag", { ctx, privacy: false, today })!
      expect(a.text).toBe("11/13（美東）拖累最多的是 Apple（下跌 2.10%）。")
      expect(a.asOf ?? null).toBeNull()
      expect(answerFor("lift", { ctx, privacy: false, today })!.text).toBe("11/13（美東）貢獻最多的是輝達（上漲 1.20%）。")
    }
    // 週二早上（台北）：紐約週一 11/16 的收盤，也不是「今天」
    const tue = { ...summary(), as_of: "2026-11-17T05:00:00+08:00" } as PortfolioSummary
    const mon = [{ ...apple, price_date: "2026-11-16" }]
    expect(ledgerSuggestions({ holdings: mon, summary: tue }, "2026-11-17")[0]!.text).toBe("11/16（美東）誰拖累了我的報酬？")
  })

  it("台股和美股都有：「今天」只算台股；美股的漲跌是紐約另一天的，不算進這一句", () => {
    const tsmc = h({ day_change: 10_000, day_change_pct: 0.0101 })
    // 只有美股下跌、台股上漲：問「今天誰幫我賺最多」，不問誰拖累
    const s = ledgerSuggestions({ holdings: [apple, tsmc], summary: summary() }, TODAY)
    expect(s[0]).toEqual({ kind: "lift", text: "今天誰幫我賺最多？" })
    const ctx: AiContext = { route: "ledger", ledger: { holdings: [apple, nvidia, tsmc], summary: summary() } }
    const lift = answerFor("lift", { ctx, privacy: false, today: TODAY })!
    expect(lift.text).toBe("今天貢獻最多的是台積電（上漲 1.01%）。")
    expect(lift.rows!.map((r) => r.label)).toEqual(["台積電"])
    expect(answerFor("drag", { ctx, privacy: false, today: TODAY })!.text).toBe("今天沒有持股下跌。")
    // 只有美股有漲跌：「今天誰…」都不問
    expect(ledgerSuggestions({ holdings: [apple, h({ day_change: 0, day_change_pct: 0 })], summary: summary() }, TODAY).some((x) => x.kind === "drag" || x.kind === "lift")).toBe(false)
  })

  it("上市今天下午進來了、上櫃要到晚上：每一檔是它自己那天的漲跌，寫「最近」，不說「今天」", () => {
    // 後端的 as_of 是兩個市場裡最新的那天（今天）
    const mon = { ...summary(), as_of: "2026-11-16T13:30:00+08:00" } as PortfolioSummary
    const tsmc = h({ price_date: "2026-11-16", day_change: -8000, day_change_pct: -0.008 })
    const otc = h({ symbol: "6488.TWO", code: "6488", name: "環球晶", market: "TPEX", price_date: "2026-11-13", day_change: 2000, day_change_pct: 0.004 })
    expect(ledgerSuggestions({ holdings: [tsmc, otc], summary: mon }, "2026-11-16")[0]).toEqual({ kind: "drag", text: "最近誰拖累了我的報酬？" })
    const ctx: AiContext = { route: "ledger", ledger: { holdings: [tsmc, otc], summary: mon } }
    expect(answerFor("drag", { ctx, privacy: false, today: "2026-11-16" })!.text).toBe("最近拖累最多的是台積電（下跌 0.80%）。")
    // 兩個市場都是今天的：「今天」
    expect(ledgerSuggestions({ holdings: [tsmc, { ...otc, price_date: "2026-11-16" }], summary: mon }, "2026-11-16")[0]!.text).toBe("今天誰拖累了我的報酬？")
  })
})

describe("「我的成本在河流圖哪裡」：只在畫得出河流圖時問；價格與成本都帶單位", () => {
  const base = { symbol: "2330.TW", code: "2330", name: "台積電", market: "TWSE" as const, type: "stock" as const }
  const held = { avg_cost: 692.61, quantity: 1500 } as never
  const river = { per_multiples: [12, 16, 20, 24, 28], current: { per: 20.8, per_percentile_5y: 0.96 } }
  const kinds = (p: object) => stockSuggestions({ ...base, position: held, ...p }, TODAY).map((x) => x.kind)

  it("台股、有倍數帶、有本益比才問；美股、沒有倍數帶、沒有本益比都不問", () => {
    expect(kinds({ overview: { eps_ttm: 52.3, pe: 20.8 }, valuation: river })).toContain("cost_on_river")
    expect(kinds({ overview: { eps_ttm: 52.3, pe: 20.8 }, valuation: { ...river, per_multiples: [] } })).not.toContain("cost_on_river")
    expect(kinds({ overview: { eps_ttm: 52.3, pe: null }, valuation: river })).not.toContain("cost_on_river")
    const us = stockSuggestions(
      { ...base, symbol: "AAPL", code: "AAPL", name: "Apple", market: "US", position: held, overview: { eps_ttm: 8.98, pe: null } as never, valuation: river as never },
      TODAY,
    )
    expect(us.map((x) => x.kind)).not.toContain("cost_on_river")
    // 美股不用張：還沒有收盤價時算不出來，不問加碼；有收盤價時問「加碼 10 股」，不是「1 張」
    expect(us.map((x) => x.kind)).not.toContain("add_one_lot")
    const priced = stockSuggestions(
      { ...base, symbol: "AAPL", code: "AAPL", name: "Apple", market: "US", position: held, quote: { price: 356.27 } as never, overview: { eps_ttm: 8.98, pe: null } as never },
      TODAY,
    )
    expect(priced.find((x) => x.kind === "add_one_lot")?.text).toBe("加碼 10 股，均價會變多少？")
    expect(priced.some((x) => /張/.test(x.text))).toBe(false)
  })

  it("台股的回答：均價帶「元」、EPS 帶「元」，有本益比才說現在幾倍", () => {
    const ctx: AiContext = { route: "stock", stock: { ...base, position: held, overview: { eps_ttm: 52.3, pe: 20.8 } as never, valuation: river as never } }
    const a = answerFor("cost_on_river", { ctx, privacy: false, today: TODAY })!
    expect(a.text).toContain("你的均價 692.61 元")
    expect(a.text).toContain("EPS 52.3 元")
    expect(a.text).toContain("現在是 20.8 倍")
    expect(a.text).not.toContain("—")
    expect(a.links!.map((l) => l.label)).toEqual(["看河流圖"])
  })

  it("美股（自由提問也一樣）：均價寫 US$，照實說沒有河流圖，不出現「—」，也不連到空的估值分頁", () => {
    const ctx: AiContext = {
      route: "stock",
      stock: {
        ...base,
        symbol: "AAPL",
        code: "AAPL",
        name: "Apple",
        market: "US",
        position: { avg_cost: 143.41, quantity: 15 } as never,
        overview: { eps_ttm: 8.98, pe: null } as never,
        // 美股沒有可商用的行情：有倍數帶的設定，但算不出現在的本益比
        valuation: { ...river, series: [], current: { per: null, per_percentile_5y: null } } as never,
      },
    }
    expect(classifyQuestion("我的成本在河流圖哪裡？", ctx)).toBe("cost_on_river")
    const a = answerFor("cost_on_river", { ctx, privacy: false, today: TODAY })!
    expect(a.text).toContain("你的均價 US$143.41")
    expect(a.text).not.toMatch(/143\.41 元|—|倍以下的帶/)
    expect(a.links!.map((l) => l.search)).toEqual([{ tab: "financials" }])
    expect(answerFor("cost_on_river", { ctx, privacy: true, today: TODAY })!.text).not.toContain("143.41")
    // 原因是沒有美股的本益比序列（美股有收盤價了），不再說「沒有報價」
    expect(a.text).toContain("美股沒有歷史本益比的資料")
    expect(a.text).not.toContain("沒有報價")
    // 本益比貴不貴：照實說沒有本益比的資料，不說「ETF 或近四季虧損」；連到財務，備援回答也連到財務，不連到空的估值分頁
    const expensive = answerFor("is_expensive", { ctx, privacy: false, today: TODAY })!
    expect(expensive.text).toBe("美股沒有歷史本益比的資料，看不出現在貴不貴。每股盈餘在財務分頁。")
    expect(expensive.links!.map((l) => l.search)).toEqual([{ tab: "financials" }])
    expect(fallbackAnswer("本益比合理嗎", ctx).links!.map((l) => l.search)).toEqual([{ tab: "financials" }])
  })

  it("美股加碼：以股計（10 股），收盤寫紐約的日期與 US$；回答下面不放台北日期的「收盤」", () => {
    const ctx: AiContext = {
      route: "stock",
      stock: {
        ...base,
        symbol: "AAPL",
        code: "AAPL",
        name: "Apple",
        market: "US",
        position: { avg_cost: 143.41, quantity: 15 } as never,
        quote: { price: 356.27, as_of: "2026-11-14T05:00:00+08:00", trade_date: "2026-11-13" } as never,
      },
    }
    expect(classifyQuestion("加碼 10 股，均價會變多少？", ctx)).toBe("add_one_lot")
    const a = answerFor("add_one_lot", { ctx, privacy: false, today: TODAY })!
    expect(a.text).toBe("以 11/13（美東）收盤價 US$356.27 加碼 10 股，均價會從 US$143.41 變成約 US$228.55。")
    expect(a.rows!.map((r) => r.value)).toEqual(["15 股", "25 股"])
    expect(a.followUps).toEqual(["買 AAPL 10 股 356.27"])
    expect(a.asOf ?? null).toBeNull()
  })

  it("加碼 1 張：收盤價與均價都帶「元」", () => {
    const ctx: AiContext = { route: "stock", stock: { ...base, position: { avg_cost: 600, quantity: 1000 } as never, quote: { price: 1085 } as never } }
    const a = answerFor("add_one_lot", { ctx, privacy: false, today: TODAY })!
    // 小數位跟著價格的格式（formatPrice），這裡只看單位
    expect(a.text).toMatch(/^以收盤價 1,085 元加碼 1 張，均價會從 600(\.00)? 元變成約 842\.50? 元。$/)
  })
})
