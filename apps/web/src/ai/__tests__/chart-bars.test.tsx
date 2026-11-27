import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from "@tanstack/react-router"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ChartCard } from "@/ai/ChartCard"
import { chartForm, chartSummary, tickLabel, timeLabel, valueDomain, valueLabel, visibleSeries } from "@/ai/chart-geometry"
import type { AiChart } from "@/ai/remote"

/**
 * 市場報告的三種圖（2026-11-17）：line（加權指數）、columns（交易日一根柱、hidden 的線只在讀數）、bars（以零為軸的雙向橫條）。
 * 舊的五種（對話的 draw_chart）行為不變。
 */
const base = (p: Partial<AiChart>): AiChart => ({
  id: "G", kind: "bars", title: "圖", unit: "pct", currency: null, x: "category", range: null, series: [], notes: [], sources: [], is_demo: false, ...p,
})

const sectors = base({
  id: "G2",
  title: "上市類股漲跌（11/11）",
  bars: [
    { label: "造紙", value: 0.0153, display: "▲1.53%", tone: "rise" },
    { label: "半導體", value: -0.0046, display: "▼0.46%", tone: "fall", sub: "主要由台積電構成（約 77%）" },
    { label: "橡膠", value: -0.0082, display: "▼0.82%", tone: "fall" },
  ],
  sources: ["臺灣證券交易所〈每日收盤行情－大盤統計資訊〉"],
})

const contrib = base({
  id: "G3",
  title: "市值前 10 的點數貢獻（11/11）",
  unit: "points",
  estimate: true,
  bars: [
    { label: "台積電", value: 51, display: "+51 點", tone: "rise", href: "/stock/2330.TW" },
    { label: "其餘合計", value: 40, display: "+40 點", tone: "pencil", sub: "市值前 10 以外的上市普通股" },
  ],
  reference: { label: "官方漲跌", display: "+112.08 點" },
})

const breadth = base({
  id: "G4",
  title: "上市漲跌家數",
  unit: "count",
  bars: [
    { label: "上漲", value: 635, display: "635 家", tone: "rise" },
    { label: "平盤", value: 52, display: "52 家", tone: "ink" },
    { label: "下跌", value: 359, display: "359 家", tone: "fall" },
  ],
})

const days = ["2026-11-09", "2026-11-10", "2026-11-11"]
const futures = base({
  id: "G7",
  kind: "columns",
  title: "外資台指期淨未平倉",
  unit: "lots",
  x: "day",
  series: [
    { name: "淨未平倉", symbol: null, points: days.map((t, i) => ({ t, v: [-30000, 12000, -28000][i]! })) },
    { name: "較前一日", symbol: null, points: days.map((t, i) => ({ t, v: [-1000, 42000, -40000][i]! })), hidden: true },
  ],
  notes: ["正值是淨多單，負值是淨空單"],
})

const index = base({
  id: "G1",
  kind: "line",
  title: "加權指數收盤",
  unit: "index",
  x: "date",
  since: "10/26 起",
  series: [{ name: "加權指數", symbol: null, points: days.map((t, i) => ({ t, v: 26700 + i * 51.234 })) }],
})

/** bars 的整列連結用路由的 <Link>：給一個最小的路由 */
function renderInRouter(ui: React.ReactNode) {
  const root = createRootRoute({ component: () => <Outlet /> })
  const home = createRoute({ getParentRoute: () => root, path: "/", component: () => <>{ui}</> })
  const stock = createRoute({ getParentRoute: () => root, path: "/stock/$symbol", component: () => <p>個股頁</p> })
  const router = createRouter({ routeTree: root.addChildren([home, stock]), history: createMemoryHistory({ initialEntries: ["/"] }) })
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}

describe("bars：以零為軸的雙向橫條", () => {
  it("有正有負時零軸依兩邊最大值的比例放（各至少 25%）：漲往右、跌往左；長度依同一個比例；顏色跟 tone；名稱下面一行是 sub", async () => {
    renderInRouter(<ChartCard chart={sectors} />)
    const fig = (await screen.findByText("上市類股漲跌（11/11）")).closest("figure")!
    const rows = within(fig).getAllByRole("listitem")
    expect(rows).toHaveLength(3)
    const bar = (i: number) => rows[i]!.querySelector<HTMLElement>("[data-bar-tone]")!
    // 跌最多 0.82%、漲最多 1.53%：零軸在 0.82 ÷ 2.35 ≈ 34.9% 的地方，兩邊用同一個比例、最長的那條碰到邊
    const axis = (0.0082 / (0.0082 + 0.0153)) * 100
    expect(bar(0).dataset.barTone).toBe("rise")
    expect(bar(0).className).toContain("bg-rise/40")
    expect(Number.parseFloat(bar(0).style.left)).toBeCloseTo(axis, 2)
    expect(Number.parseFloat(bar(0).style.width)).toBeCloseTo(100 - axis, 2)
    expect(bar(1).className).toContain("bg-fall/40")
    expect(Number.parseFloat(bar(1).style.right)).toBeCloseTo(100 - axis, 2)
    expect(Number.parseFloat(bar(1).style.width)).toBeCloseTo((0.0046 / 0.0153) * (100 - axis), 1)
    expect(Number.parseFloat(bar(2).style.width)).toBeCloseTo(axis, 1)
    expect(within(rows[1]!).getByText("主要由台積電構成（約 77%）")).toHaveClass("text-ink-2")
    // 漲跌幅的數字用漲跌色；沒有提示框
    expect(within(rows[0]!).getByText("▲1.53%")).toHaveClass("text-rise")
    expect(within(rows[2]!).getByText("▼0.82%")).toHaveClass("text-fall")
    expect(within(fig).getByText(/資料來源：/)).toBeInTheDocument()
  })

  it("點數貢獻：標題旁「估算」、其餘合計是鉛筆灰、下面一行官方漲跌；有連結的整列連到個股頁", async () => {
    renderInRouter(<ChartCard chart={contrib} />)
    const fig = (await screen.findByText("市值前 10 的點數貢獻（11/11）")).closest("figure")!
    expect(within(fig).getByText("估算")).toHaveClass("demo-tag")
    expect(within(fig).getByText("其餘合計").closest("li")!.querySelector("[data-bar-tone]")!.className).toContain("bg-chart-bench")
    expect(within(fig).getByText(/^官方漲跌/)).toHaveTextContent("官方漲跌 +112.08 點")
    const link = within(fig).getByRole("link", { name: /台積電/ })
    expect(link).toHaveAttribute("href", "/stock/2330.TW")
    fireEvent.click(link)
    expect(await screen.findByText("個股頁")).toBeInTheDocument()
  })

  it("只有正的（家數）：軸在左邊；家數的數字是墨色（紅綠只給價格）；平盤是墨色的條", async () => {
    renderInRouter(<ChartCard chart={breadth} />)
    const fig = (await screen.findByText("上市漲跌家數")).closest("figure")!
    const rows = within(fig).getAllByRole("listitem")
    expect(rows[0]!.querySelector<HTMLElement>("[data-bar-tone]")!.style.left).toBe("0%")
    expect(rows[0]!.querySelector<HTMLElement>("[data-bar-tone]")!.style.width).toBe("100%")
    expect(within(rows[0]!).getByText("635 家")).toHaveClass("text-ink")
    expect(rows[1]!.querySelector("[data-bar-tone]")!.className).toContain("bg-ink/35")
    expect(chartSummary(breadth)).toBe("上市漲跌家數。上漲 635 家、平盤 52 家、下跌 359 家")
  })
})

describe("columns：交易日一根柱", () => {
  it("正值墨色、負值鉛筆灰；hidden 的線不畫、不算進縱軸，只出現在讀數", () => {
    expect(chartForm(futures)).toBe("bar")
    expect(visibleSeries(futures).map((s) => s.name)).toEqual(["淨未平倉"])
    // 縱軸只看淨未平倉（−30,000 到 12,000），不看較前一日的 ±42,000
    const { min, max } = valueDomain(futures, "bar")
    expect(min).toBeGreaterThanOrEqual(-40000)
    expect(max).toBeLessThanOrEqual(20000)
    render(<ChartCard chart={futures} />)
    const fig = screen.getByText("外資台指期淨未平倉").closest("figure")!
    const paths = [...fig.querySelectorAll("svg path")].filter((p) => p.getAttribute("fill"))
    expect(paths.map((p) => p.getAttribute("fill"))).toEqual(["var(--chart-bench)", "var(--chart-mine)", "var(--chart-bench)"])
    // 一條看得到的線：沒有圖例
    expect(fig.textContent).not.toContain("較前一日")
    const plot = within(fig).getByRole("group")
    fireEvent.keyDown(plot, { key: "End" })
    const live = fig.querySelector("[aria-live]")!
    expect(live.textContent).toContain("淨未平倉 −28,000 口")
    expect(live.textContent).toContain("較前一日 −40,000 口")
    fireEvent.keyDown(plot, { key: "ArrowLeft" })
    expect(live.textContent).toContain("較前一日 +42,000 口")
    expect(timeLabel(futures, "2026-11-11")).toBe("11/11")
  })
})

describe("line 與新的單位", () => {
  it("加權指數是一條墨色的線，標題旁「10/26 起」；指數 2 位小數", () => {
    render(<ChartCard chart={index} />)
    const fig = screen.getByText("加權指數收盤").closest("figure")!
    expect(within(fig).getByText("10/26 起")).toBeInTheDocument()
    expect(chartForm(index)).toBe("line")
    expect(valueLabel(index, 26802.468, null)).toBe("26,802.47")
  })

  it("指數與它的均線：主線墨色有線尾的圓點，均線是赭、藍筆的細線沒有圓點；圖例寫出每條線，沒有線尾的標籤", () => {
    const five = ["2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11"]
    const withAverages: AiChart = {
      ...index,
      series: [
        { name: "加權指數", symbol: null, points: five.map((t, i) => ({ t, v: 26700 + i * 51.234 })) },
        { name: "5 日線", symbol: null, role: "average", points: five.slice(1).map((t, i) => ({ t, v: 26720 + i * 40 })) },
        { name: "10 日線", symbol: null, role: "average", points: five.slice(2).map((t) => ({ t, v: 26700 })) },
      ],
    }
    render(<ChartCard chart={withAverages} />)
    const fig = screen.getByText("加權指數收盤").closest("figure")!
    for (const name of ["加權指數", "5 日線", "10 日線"]) expect(within(fig).getByText(name)).toBeInTheDocument()
    const groups = [...fig.querySelectorAll("svg[role='img'] g")].filter((g) => g.querySelector(":scope > path[stroke-width]"))
    const averages = groups.filter((g) => g.getAttribute("data-series") === "average")
    const main = groups.filter((g) => g.getAttribute("data-series") !== "average")
    expect(averages.map((g) => g.querySelector("path")!.getAttribute("stroke"))).toEqual(["var(--chart-ochre)", "var(--chart-blue)"])
    for (const g of averages) {
      expect(g.querySelector("path")!.getAttribute("stroke-width")).toBe("1.5")
      expect(g.querySelector("circle")).toBeNull()
    }
    expect(main).toHaveLength(1)
    expect(main[0]!.querySelector("path")!.getAttribute("stroke")).toBe("var(--chart-mine)")
    expect(main[0]!.querySelector("circle")).not.toBeNull()
    // 主線最後畫（蓋在均線上面）
    expect(groups.indexOf(main[0]!)).toBe(groups.length - 1)
    // 沒有線尾的「我的」標籤（那是比較圖的）
    expect(within(fig).queryByText("我的")).toBeNull()
  })

  it("點數、家數、口數、億元的讀數與刻度", () => {
    const c = (unit: AiChart["unit"]) => base({ unit })
    expect(valueLabel(c("points"), -1070.4, null)).toBe("−1,070 點")
    expect(valueLabel(c("count"), 635, null)).toBe("635 家")
    expect(valueLabel(c("lots"), -32415, null)).toBe("−32,415 口")
    expect(valueLabel(c("lots"), 1234, null, { signed: true })).toBe("+1,234 口")
    expect(valueLabel(c("yi"), 5240, null)).toBe("5,240 億")
    expect(tickLabel(c("lots"), -30000, 10000)).toBe("−3 萬")
    expect(tickLabel(c("lots"), 5000, 5000)).toBe("5,000")
    expect(tickLabel(c("points"), -500, 250)).toBe("−500")
  })

  it("舊的 kind 不變：月份的營收照樣是柱狀、日期的比較圖照樣是折線", () => {
    const revenue = base({ kind: "revenue", unit: "amount_k", x: "month", series: [{ name: "台積電", symbol: "2330.TW", points: ["2026-08", "2026-09"].map((t, i) => ({ t, v: 1e8 + i })) }] })
    expect(chartForm(revenue)).toBe("bar")
    const compare = base({ kind: "compare", x: "date", series: [{ name: "a", symbol: "2330.TW", points: days.map((t) => ({ t, v: 0 })) }] })
    expect(chartForm(compare)).toBe("line")
  })
})
