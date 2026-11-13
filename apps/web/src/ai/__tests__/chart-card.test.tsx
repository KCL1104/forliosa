import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ChartCard } from "@/ai/ChartCard"
import { axisTicks, categories, chartForm, chartSummary, endLabel, niceTicks, spreadLabels, tickLabel, timeLabel, valueAt, valueDomain, valueLabel } from "@/ai/chart-geometry"
import { applyChatEvent, isChart, threadFromServer, type AiChart, type ThreadDetail } from "@/ai/remote"
import type { Message } from "@/ai/types"

const days = (n: number) => Array.from({ length: n }, (_, i) => `2026-10-${String(i + 1).padStart(2, "0")}`)

const chart = (p: Partial<AiChart> = {}): AiChart => ({
  id: "cht_1",
  kind: "compare",
  title: "台積電、鴻海 漲跌幅（近 6 個月）",
  unit: "pct",
  currency: null,
  x: "date",
  range: "6M",
  series: [
    { name: "台積電", symbol: "2330.TW", points: days(10).map((t, i) => ({ t, v: i * 0.01 })) },
    { name: "鴻海", symbol: "2317.TW", points: days(10).map((t, i) => ({ t, v: -i * 0.005 })) },
  ],
  notes: ["漲跌幅只算價格變動，不含股利"],
  sources: ["臺灣證券交易所〈上市個股日成交資訊〉"],
  is_demo: false,
  ...p,
})

const price = chart({
  id: "cht_p",
  kind: "price",
  title: "元大台灣50 收盤價（近 6 個月）",
  unit: "price",
  currency: "TWD",
  series: [{ name: "元大台灣50", symbol: "0050.TW", points: days(10).map((t, i) => ({ t, v: 52 + i * 0.35 })) }],
  notes: [],
})

const eps = chart({
  id: "cht_e",
  kind: "eps",
  title: "台積電、鴻海 每季每股盈餘",
  unit: "eps",
  currency: "TWD",
  x: "quarter",
  range: null,
  series: [
    { name: "台積電", symbol: "2330.TW", points: ["2025Q3", "2025Q4", "2026Q1", "2026Q2"].map((t, i) => ({ t, v: 12 + i })) },
    { name: "鴻海", symbol: "2317.TW", points: ["2025Q4", "2026Q1", "2026Q2"].map((t, i) => ({ t, v: i === 1 ? -0.5 : 3 + i })) },
  ],
  is_demo: true,
})

describe("圖卡的幾何（純函式）", () => {
  it("刻度是整齊的數字，涵蓋資料", () => {
    expect(niceTicks(-0.137, 0.224)).toEqual([-0.2, -0.1, 0, 0.1, 0.2, 0.3])
    expect(niceTicks(65.2, 84.9)).toEqual([65, 70, 75, 80, 85])
    expect(niceTicks(0, 3_260_000)).toEqual([0, 1_000_000, 2_000_000, 3_000_000, 4_000_000])
    const flat = niceTicks(100, 100)
    expect(flat[0]).toBeLessThan(100)
    expect(flat.at(-1)).toBeGreaterThan(100)
    expect(niceTicks(Number.NaN, 1)).toEqual([0, 1])
  })

  it("報酬率與柱狀圖的縱軸一定包含 0；價格不從 0 開始", () => {
    expect(valueDomain(chart({ series: [{ name: "a", symbol: "a", points: [{ t: "2026-10-01", v: 0.05 }, { t: "2026-10-02", v: 0.12 }] }] }), "line").min).toBe(0)
    expect(valueDomain(eps, "bar").min).toBeLessThanOrEqual(-0.5)
    expect(valueDomain(eps, "bar").max).toBeGreaterThanOrEqual(15)
    expect(valueDomain(price, "line").min).toBeGreaterThan(40)
  })

  it("日期軸畫折線；類別軸的柱子不超過 24 根才畫柱狀", () => {
    expect(chartForm(chart())).toBe("line")
    expect(chartForm(eps)).toBe("bar")
    expect(categories(eps)).toEqual(["2025Q3", "2025Q4", "2026Q1", "2026Q2"])
    const months = Array.from({ length: 24 }, (_, i) => `${2025 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`)
    const revenue = (n: number) => chart({ kind: "revenue", unit: "amount_k", x: "month", series: Array.from({ length: n }, (_, k) => ({ name: `s${k}`, symbol: `${k}`, points: months.map((t) => ({ t, v: 1 })) })) })
    expect(chartForm(revenue(1))).toBe("bar")
    expect(chartForm(revenue(2))).toBe("line")
  })

  it("讀數和頁面同一套格式；刻度的字比較短", () => {
    expect(valueLabel(chart(), 0.0123, "2330.TW")).toBe("+1.23%")
    expect(valueLabel(chart(), -0.0634, "2317.TW")).toBe("−6.34%")
    expect(valueLabel(price, 1085, "2330.TW")).toBe("1,085")
    expect(valueLabel(price, 52.4, "0050.TW")).toBe("52.40")
    expect(valueLabel(chart({ unit: "amount_k" }), 326_000_000, "2330.TW")).toBe("3,260 億")
    expect(valueLabel(eps, 14.666, "2330.TW")).toBe("14.67")
    expect(tickLabel(chart(), 0.1, 0.1)).toBe("+10%")
    expect(tickLabel(chart(), 0.005, 0.005)).toBe("+0.5%")
    expect(tickLabel(chart({ unit: "amount_k" }), 100_000_000, 100_000_000)).toBe("1,000 億")
    expect(tickLabel(price, 70, 5)).toBe("70")
    expect(tickLabel(eps, 2.5, 2.5)).toBe("2.5")
  })

  it("橫軸的字：日期、月份、季別", () => {
    expect(timeLabel(chart(), "2026-06-01")).toBe("6/1")
    expect(timeLabel(chart(), "2026-06-01", true)).toBe("2026/06/01")
    expect(timeLabel(chart({ x: "month" }), "2025-11")).toBe("2025/11")
    expect(timeLabel(eps, "2025Q3")).toBe("25Q3")
    expect(timeLabel(eps, "FY2026Q1")).toBe("26Q1")
    expect(axisTicks([1, 2, 3, 4, 5, 6, 7])).toEqual([1, 4, 7])
    expect(axisTicks([1, 2, 3])).toEqual([1, 3])
    expect(axisTicks([1])).toEqual([1])
  })

  it("線尾標籤：代號；互相讓開、不超出上下界；沒有那一天的值用前一個交易日", () => {
    expect(endLabel({ name: "台積電", symbol: "2330.TW", points: [] })).toBe("2330")
    expect(endLabel({ name: "某櫃買股", symbol: "6488.TWO", points: [] })).toBe("6488")
    expect(endLabel({ name: "我的報酬率", symbol: null, points: [] })).toBe("我的")
    const spread = spreadLabels([100, 102, 101, 40], 14, 10, 170)
    expect(spread[3]).toBe(40)
    const close = [spread[0]!, spread[2]!, spread[1]!]
    expect(close[1]! - close[0]!).toBeGreaterThanOrEqual(14)
    expect(close[2]! - close[1]!).toBeGreaterThanOrEqual(14)
    const bottom = spreadLabels([168, 169, 170], 14, 10, 170)
    expect(Math.max(...bottom)).toBeLessThanOrEqual(170)
    expect([...bottom].sort((a, b) => a - b).every((y, i, a) => i === 0 || y - a[i - 1]! >= 14)).toBe(true)
    const pts = [{ t: "2026-10-01", v: 1 }, { t: "2026-10-05", v: 2 }]
    expect(valueAt(pts, "2026-10-03")).toBe(1)
    expect(valueAt(pts, "2026-10-05")).toBe(2)
    expect(valueAt(pts, "2026-09-30")).toBeNull()
  })

  it("給報讀器的一句話寫出每條線的起訖", () => {
    expect(chartSummary(chart())).toBe("台積電、鴻海 漲跌幅（近 6 個月）。台積電：2026/10/01 0.00%，2026/10/10 +9.00%；鴻海：2026/10/01 0.00%，2026/10/10 −4.50%")
  })
})

describe("ChartCard", () => {
  it("多條線：標題、圖例（名稱＋最後的值）、線尾代號、說明與資料來源", () => {
    render(<ChartCard chart={chart()} />)
    const fig = screen.getByRole("figure", { name: "台積電、鴻海 漲跌幅（近 6 個月）" })
    const legend = within(fig).getAllByRole("list")[0]!
    expect(within(legend).getByText("台積電")).toBeInTheDocument()
    expect(within(legend).getByText("+9.00%")).toBeInTheDocument()
    expect(within(legend).getByText("−4.50%")).toBeInTheDocument()
    const svg = within(fig).getByRole("img")
    expect(svg).toHaveAccessibleName(/台積電：2026\/10\/01 0\.00%，2026\/10\/10 \+9\.00%/)
    expect(svg.querySelectorAll('path[stroke-width="2"]')).toHaveLength(2)
    // 分類色照順序，不用漲跌的紅綠
    expect([...svg.querySelectorAll('path[stroke-width="2"]')].map((p) => p.getAttribute("stroke"))).toEqual(["var(--series-1)", "var(--series-2)"])
    expect(within(fig).getByText("2330")).toBeInTheDocument()
    expect(within(fig).getByText("2317")).toBeInTheDocument()
    expect(within(fig).getByText("漲跌幅只算價格變動，不含股利")).toBeInTheDocument()
    expect(within(fig).getByText("資料來源：臺灣證券交易所〈上市個股日成交資訊〉")).toBeInTheDocument()
    expect(within(fig).queryByText("示範資料")).toBeNull()
  })

  it("只有一條線：墨色、沒有圖例也沒有線尾標籤", () => {
    render(<ChartCard chart={price} />)
    const fig = screen.getByRole("figure", { name: "元大台灣50 收盤價（近 6 個月）" })
    expect(within(fig).queryAllByRole("list")).toHaveLength(0)
    expect(within(fig).queryByText("0050")).toBeNull()
    expect(within(fig).getByRole("img").querySelector('path[stroke-width="2"]')).toHaveAttribute("stroke", "var(--chart-mine)")
  })

  it("我的報酬率是墨色實線，基準是鉛筆灰虛線", () => {
    const perf = chart({ kind: "performance", title: "我的報酬率與元大台灣50（近 6 個月）", series: [{ ...chart().series[0]!, name: "我的報酬率", symbol: null }, { ...chart().series[1]!, name: "元大台灣50", symbol: "0050.TW" }] })
    render(<ChartCard chart={perf} />)
    const lines = [...screen.getByRole("img").querySelectorAll('path[stroke-width="2"]')]
    expect(lines.map((p) => [p.getAttribute("stroke"), p.getAttribute("stroke-dasharray")])).toEqual([
      ["var(--chart-mine)", null],
      ["var(--chart-bench)", "5 4"],
    ])
    expect(screen.getByText("我的")).toBeInTheDocument()
  })

  it("季別的柱狀圖：每一期每檔一根柱子，示範資料有標示", () => {
    render(<ChartCard chart={eps} />)
    const fig = screen.getByRole("figure", { name: "台積電、鴻海 每季每股盈餘" })
    expect(within(fig).getByText("示範資料")).toBeInTheDocument()
    const svg = within(fig).getByRole("img")
    expect(svg.querySelectorAll("g[fill] > path")).toHaveLength(7)
    expect(svg.querySelectorAll('path[stroke-width="2"]')).toHaveLength(0)
    expect(within(fig).getByText("25Q3")).toBeInTheDocument()
    expect(within(fig).getByText("26Q2")).toBeInTheDocument()
  })

  it("方向鍵逐點看讀數；Esc 收起", () => {
    render(<ChartCard chart={chart()} />)
    const plot = screen.getByRole("group", { name: /用左右方向鍵逐點看數字/ })
    fireEvent.keyDown(plot, { key: "ArrowLeft" })
    expect(screen.getByText("2026/10/09：台積電 +8.00%、鴻海 −4.00%")).toBeInTheDocument()
    fireEvent.keyDown(plot, { key: "Home" })
    expect(screen.getByText("2026/10/01：台積電 0.00%、鴻海 0.00%")).toBeInTheDocument()
    fireEvent.keyDown(plot, { key: "Escape" })
    expect(screen.queryByText(/2026\/10\/01：/)).toBeNull()
  })

  it("沒有點可以畫：說明一句，後端的說明照樣顯示", () => {
    render(<ChartCard chart={chart({ series: [{ name: "鴻海", symbol: "2317.TW", points: [] }], notes: ["資料從 2026/11/12 開始"] })} />)
    expect(screen.getByText("沒有資料可以畫。")).toBeInTheDocument()
    expect(screen.getByText("資料從 2026/11/12 開始")).toBeInTheDocument()
    expect(screen.queryByRole("img")).toBeNull()
  })
})

describe("圖卡的事件與對話紀錄", () => {
  const start: Message = { id: "m1", role: "ai", text: "", streaming: true, at: "" }

  it("chart 事件加進這一則回答；同一張不重複，形狀不對的不收", () => {
    const one = applyChatEvent(start, { event: "chart", data: chart() })
    expect(one.charts).toEqual([chart()])
    expect(applyChatEvent(one, { event: "chart", data: chart() }).charts).toHaveLength(1)
    expect(applyChatEvent(one, { event: "chart", data: price }).charts?.map((c) => c.id)).toEqual(["cht_1", "cht_p"])
    const broken = { ...chart(), series: [{ name: "x", symbol: null, points: [{ t: "2026-10-01", v: "1" }] }] } as unknown as AiChart
    expect(isChart(broken)).toBe(false)
    expect(applyChatEvent(start, { event: "chart", data: broken })).toBe(start)
    expect(isChart(null)).toBe(false)
  })

  it("從後端載入的對話帶回圖卡；舊紀錄沒有 charts 也沒事", () => {
    const detail: ThreadDetail = {
      id: "thr_1",
      title: "比較",
      model: "m",
      created_at: "2026-11-13T09:00:00+08:00",
      updated_at: "2026-11-13T09:00:00+08:00",
      messages: [
        { id: "1", turn_id: "t", role: "user", text: "比較台積電和鴻海", citations: [], drafts: [], tools: [], error: null, at: "" },
        { id: "2", turn_id: "t", role: "ai", text: "台積電漲得比較多。", citations: [], drafts: [], charts: [chart()], tools: [], error: null, at: "" },
        { id: "3", turn_id: "u", role: "ai", text: "舊的回答。", citations: [], drafts: [], tools: [], error: null, at: "" },
      ],
    }
    const { thread } = threadFromServer(detail)
    expect(thread.messages[1]!.charts).toEqual([chart()])
    expect(thread.messages[2]!.charts).toBeUndefined()
  })
})
