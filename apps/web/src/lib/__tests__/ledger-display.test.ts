import { describe, expect, it } from "vitest"
import type { ClosedRound, InstrumentEvent, NewsItem, RecurringPlan, Transaction, UpcomingItem } from "@/api/types"
import { createMockAdapter } from "@/api/mock/adapter"
import { missedDebits, planDebits, recurringOffers } from "@/ai/recurring-offer"
import type { Draft } from "@/ai/types"
import { announcementHost, eventLabel, eventTitle, mergeAnnouncements } from "@/lib/events"
import { activePlansBySymbol, closedByYear, closedTotals, daysLabel, holdingPeriod, planStatus, recurringLabel, unpricedHoldings, upcomingShort, upcomingText } from "@/lib/ledger-display"

const round = (p: Partial<ClosedRound>): ClosedRound => ({
  symbol: "2603.TW", name: "長榮", account_id: "a", currency: "TWD", opened_at: "2024-01-10", closed_at: "2025-02-20", holding_days: 407,
  total_bought_qty: 1000, total_sold_qty: 1000, cost_basis: 100_000, realized_pnl: 5_000, realized_pnl_pct: 0.05, dividends_received: 0, fees_and_taxes: 400, ...p,
})

describe("出清回合", () => {
  it("持有期間：日期區間與天數；當沖是當天出清", () => {
    expect(holdingPeriod(round({}))).toEqual({ range: "2024/01/10 – 2025/02/20", days: "持有 407 天" })
    expect(holdingPeriod(round({ opened_at: "2026-11-12", closed_at: "2026-11-12", holding_days: 0 }))).toEqual({ range: "2026/11/12", days: "當天出清" })
  })
  it("合計：檔數去重、已實現加總", () => {
    expect(closedTotals([round({}), round({ realized_pnl: -8_000 }), round({ symbol: "3008.TW", realized_pnl: 1_000 })])).toEqual({ symbols: 2, realized: -2_000 })
  })
  it("依出清年份分組：新的年份在前、年內新到舊、每年有已實現小計與檔數", () => {
    const years = closedByYear([
      round({ symbol: "2603.TW", closed_at: "2025-02-20", realized_pnl: -94_021 }),
      round({ symbol: "2412.TW", closed_at: "2026-07-15", realized_pnl: 3_000 }),
      round({ symbol: "3008.TW", closed_at: "2025-08-12", realized_pnl: 22_848 }),
      round({ symbol: "2409.TW", closed_at: "2024-09-10", realized_pnl: -1_200 }),
      round({ symbol: "2603.TW", opened_at: "2025-03-01", closed_at: "2025-10-01", realized_pnl: 500 }),
    ])
    expect(years.map((y) => y.year)).toEqual(["2026", "2025", "2024"])
    const y2025 = years[1]!
    expect(y2025.rounds.map((r) => r.closed_at)).toEqual(["2025-10-01", "2025-08-12", "2025-02-20"])
    expect(y2025).toMatchObject({ realized: -94_021 + 22_848 + 500, symbols: 2 })
    expect(years[0]).toMatchObject({ realized: 3_000, symbols: 1 })
    expect(closedByYear([])).toEqual([])
  })
})

describe("持股與本週事項", () => {
  it("沒有報價的持股（商用模式的美股）", () => {
    expect(unpricedHoldings([{ name: "Apple", price: null, market: "US" }, { name: "台積電", price: 1085, market: "TWSE" }]).map((h) => h.name)).toEqual(["Apple"])
  })
  const rec: UpcomingItem = {
    date: "2026-12-07", type: "recurring", symbol: "0050.TW", title: "元大台灣50 定期定額 NT$5,000（12/6 非交易日，順延）", amount_estimate: 5000,
    plan_id: "p1", account_id: "a", scheduled_date: "2026-12-06",
  }
  it("定期定額由欄位組成：隱私模式不露出標題裡的金額", () => {
    expect(upcomingText(rec, false)).toBe("0050 定期定額（遇休市順延）・NT$5,000")
    expect(upcomingText(rec, true)).toBe("0050 定期定額（遇休市順延）・••••")
    expect(upcomingShort(rec)).toBe("0050 定期定額")
    expect(upcomingText({ ...rec, type: "ex_dividend", title: "0056 除息", amount_estimate: 8660 }, false)).toBe("0056 除息・預估 +NT$8,660")
  })
  it("計畫狀態與扣款日說明", () => {
    expect(planStatus({ active: true, end_date: null, next_date: "2026-11-19" }, "2026-11-12")).toBe("active")
    expect(planStatus({ active: false, end_date: null, next_date: null }, "2026-11-12")).toBe("paused")
    expect(planStatus({ active: true, end_date: "2026-10-31", next_date: null }, "2026-11-12")).toBe("ended")
    expect(daysLabel([19, 6])).toBe("每月 6、19 日")
  })
})

describe("事件與公告", () => {
  const ev = (p: Partial<InstrumentEvent>): InstrumentEvent => ({ date: "2026-11-11", type: "material_info", title: "代子公司公告取得設備", detail: null, url: null, mine: false, amount_estimate: null, ...p })
  const news = (p: Partial<NewsItem>): NewsItem => ({ published_at: "2026-11-11T17:30:00+08:00", title: "代子公司公告取得設備", source: "公告", url: "https://mops.twse.com.tw/mops/#/web/t05st01", category: "material_info", ...p })
  it("預估：標題去掉「（預估）」，改用標記", () => {
    expect(eventTitle({ title: "2026Q3 財報公布期限（預估）", estimated: true })).toBe("2026Q3 財報公布期限")
    expect(eventTitle({ title: "2026Q3 法說會", estimated: false })).toBe("2026Q3 法說會")
  })
  it("美股 SEC 申報依表單標類型；連結說明寫 SEC EDGAR", () => {
    expect(eventLabel({ type: "sec_filing", form: "10-K" })).toBe("年報")
    expect(eventLabel({ type: "sec_filing", form: "10-Q/A" })).toBe("季報修正")
    expect(eventLabel({ type: "sec_filing", form: "8-K" })).toBe("重大事件")
    expect(eventLabel({ type: "sec_filing", form: "S-1" })).toBe("SEC 申報")
    expect(eventLabel({ type: "investor_conference" })).toBe("法說會")
    expect(announcementHost("https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm")).toBe("SEC EDGAR")
  })
  it("公告併入時間軸：同日同標題的重大訊息補上連結，不重複；證交所公告各成一列", () => {
    const rows = mergeAnnouncements([ev({})], [news({}), news({ published_at: "2026-11-10T00:00:00+08:00", title: "暫停交易公告", category: "exchange_news", url: "https://www.twse.com.tw/zh/news/newsList.html" })])
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ type: "material_info", url: "https://mops.twse.com.tw/mops/#/web/t05st01", category: "material_info" })
    expect(rows[1]).toMatchObject({ type: "announcement", date: "2026-11-10", category: "exchange_news" })
  })
})

describe("扣款日的定期定額草稿", () => {
  const up: UpcomingItem = { date: "2026-11-12", type: "recurring", symbol: "00878.TW", title: "國泰永續高股息 定期定額 NT$4,000", amount_estimate: 4000, plan_id: "p2", account_id: "a", scheduled_date: "2026-11-12" }
  const buy = (symbol: string): Transaction => ({
    id: "t", account_id: "a", symbol, type: "buy", trade_date: "2026-11-12", quantity: 100, price: 22.86, amount: 2286, fee: 1, tax: 0, health_insurance: 0,
    currency: "TWD", is_day_trade: false, note: "", source: "manual", created_at: "",
  })
  it("今天要扣、還沒記下才提出", () => {
    const [o] = recurringOffers([up, { ...up, date: "2026-11-19", plan_id: "p1" }], "2026-11-12", [], [])
    expect(o).toMatchObject({ kind: "recurring_draft", text: "記下今天的 00878 定期定額", recurring: { planId: "p2", date: "2026-11-12", name: "國泰永續高股息" } })
    expect(recurringOffers([up], "2026-11-12", [buy("00878.TW")], [])).toEqual([])
    expect(recurringOffers([up], "2026-11-12", [buy("2330.TW")], [])).toHaveLength(1)
  })
  it("這個計畫今天已經寫過草稿（簽了或捨棄了）就不再提", () => {
    const d = { recurring: { planId: "p2", date: "2026-11-12" } } as Draft
    expect(recurringOffers([up], "2026-11-12", [], [d])).toEqual([])
  })
})

const plan = (p: Partial<RecurringPlan>): RecurringPlan => ({
  id: "p1", account_id: "a", symbol: "0050.TW", name: "元大台灣50", amount: 10_000, day_of_month: [6], start_date: "2024-01-01", end_date: null,
  active: true, note: "", next_date: "2026-12-07", created_at: "", updated_at: "", ...p,
})
const buyOn = (symbol: string, trade_date: string, account_id = "a"): Transaction => ({
  id: `t-${symbol}-${trade_date}`, account_id, symbol, type: "buy", trade_date, quantity: 100, price: 72.4, amount: 7240, fee: 1, tax: 0, health_insurance: 0,
  currency: "TWD", is_day_trade: false, note: "", source: "manual", created_at: "",
})

describe("漏記的定期定額（最近 7 天）", () => {
  const today = "2026-11-12"
  it("扣款日（週末順延）：11/08 是星期日 → 11/09", () => {
    expect(planDebits({ day_of_month: [6, 8], start_date: "2024-01-01", end_date: null }, "2026-11-05", today)).toEqual([
      ["2026-11-06", "2026-11-06"],
      ["2026-11-08", "2026-11-09"],
    ])
    // 上個月底順延到這個月初（2026-02-28 是星期六）
    expect(planDebits({ day_of_month: [28], start_date: "2024-01-01", end_date: null }, "2026-03-01", "2026-03-05")).toEqual([["2026-02-28", "2026-03-02"]])
  })
  it("11/06 沒有買進紀錄 → 補記 11/06 的 0050；記了（當天或之後）就不提", () => {
    const [o] = missedDebits([plan({})], today, [], [])
    expect(o).toMatchObject({ kind: "recurring_draft", text: "補記 11/06 的 0050 定期定額", lines: ["11/06 扣款", "補記 0050 定期定額"], recurring: { planId: "p1", scheduledDate: "2026-11-06", date: "2026-11-06", missed: true } })
    expect(missedDebits([plan({})], today, [buyOn("0050.TW", "2026-11-06")], [])).toEqual([])
    expect(missedDebits([plan({})], today, [buyOn("0050.TW", "2026-11-09")], [])).toEqual([])
    // 別的帳戶、別的股票、扣款日之前的買進都不算
    expect(missedDebits([plan({})], today, [buyOn("0050.TW", "2026-11-06", "b"), buyOn("00878.TW", "2026-11-06"), buyOn("0050.TW", "2026-11-05")], [])).toHaveLength(1)
  })
  it("今天的扣款不算漏記；超過 7 天、計畫暫停、開始日之後才有的都不提", () => {
    expect(missedDebits([plan({ day_of_month: [12] })], today, [], [])).toEqual([])
    expect(missedDebits([plan({ day_of_month: [4] })], today, [], [])).toEqual([])
    expect(missedDebits([plan({ active: false })], today, [], [])).toEqual([])
    expect(missedDebits([plan({ start_date: "2026-11-07" })], today, [], [])).toEqual([])
    expect(missedDebits([plan({ end_date: "2026-11-05" })], today, [], [])).toEqual([])
  })
  it("下一次扣款記了，不代表這一次也記了；草稿寫過（待簽名、簽了、捨棄）就不再提", () => {
    const twice = plan({ day_of_month: [6, 10] })
    expect(missedDebits([twice], today, [buyOn("0050.TW", "2026-11-10")], []).map((o) => o.recurring!.date)).toEqual(["2026-11-06"])
    const d = { recurring: { planId: "p1", date: "2026-11-06" } } as Draft
    expect(missedDebits([plan({})], today, [], [d])).toEqual([])
  })
  it("最舊的在前，最多 3 筆", () => {
    const plans = [
      plan({ id: "a1", symbol: "2330.TW", day_of_month: [10] }),
      plan({ id: "a2", symbol: "0050.TW", day_of_month: [6] }),
      plan({ id: "a3", symbol: "00878.TW", day_of_month: [9] }),
      plan({ id: "a4", symbol: "2454.TW", day_of_month: [11] }),
    ]
    expect(missedDebits(plans, today, [], []).map((o) => o.text)).toEqual(["補記 11/06 的 0050 定期定額", "補記 11/09 的 00878 定期定額", "補記 11/10 的 2330 定期定額"])
  })
  it("mock：11/06 的 0050 扣款沒有記，帳本會提出補記", async () => {
    const api = createMockAdapter({ latency: [0, 0] })
    const plans = await api.listRecurring()
    const buys = (await api.listTransactions({ type: "buy", from: "2026-11-05", to: today, limit: 200 })).items
    expect(missedDebits(plans, today, buys, []).map((o) => o.text)).toEqual(["補記 11/06 的 0050 定期定額"])
  })
})

describe("持倉上的定期定額標記", () => {
  it("只標啟用中的計畫，同一檔多個計畫合在一起；說明在隱私模式遮金額", () => {
    const m = activePlansBySymbol([plan({}), plan({ id: "p2", day_of_month: [19, 6], amount: 5_000, account_id: "b" }), plan({ id: "p3", symbol: "00878.TW", active: false, next_date: null })], "2026-11-12")
    expect([...m.keys()]).toEqual(["0050.TW"])
    expect(m.get("0050.TW")).toHaveLength(2)
    expect(recurringLabel([{ day_of_month: [19, 6], amount: 5_000 }], false)).toBe("定期定額：每月 6、19 日 NT$5,000")
    expect(recurringLabel(m.get("0050.TW")!, true)).toBe("定期定額：每月 6 日 ••••；每月 6、19 日 ••••")
  })
})
