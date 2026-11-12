import { describe, expect, it } from "vitest"
import type { ClosedRound, InstrumentEvent, NewsItem, Transaction, UpcomingItem } from "@/api/types"
import { recurringOffers } from "@/ai/recurring-offer"
import type { Draft } from "@/ai/types"
import { eventTitle, mergeAnnouncements } from "@/lib/events"
import { closedTotals, daysLabel, holdingPeriod, planStatus, unpricedHoldings, upcomingShort, upcomingText } from "@/lib/ledger-display"

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
