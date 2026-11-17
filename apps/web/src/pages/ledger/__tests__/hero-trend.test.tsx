import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { limitHistory } from "@/api/mock/adapter"
import type { Performance, PerformancePoint } from "@/api/types"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"

/**
 * 總資產走勢（產品負責人 2026-11-17 選方案 B）：主數字下方滿版的走勢、滑過看那一天、區間在前端切；
 * 和績效分段共用一個區間，整頁只有一排區間按鈕；績效分段不再畫「市值與投入本金」。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetPrefs = () => {
  localStorage.removeItem("forliosa:ledger")
  useLedgerPrefs.setState({ columns: DEFAULT_COLUMNS, showTrend: true, pinned: [], showClosed: false, trendRange: "1M" })
  usePrefs.setState({ privacyMode: false })
}
beforeEach(() => act(resetPrefs))
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(resetPrefs)
})

const T = { timeout: 8000 }
function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}
const trend = () => screen.findByRole("region", { name: "總資產走勢" }, T)
const chart = (region: HTMLElement) => within(region).getByRole("group", { name: /^總資產走勢：/ })

/** 「全部」的序列只留最後 n 個收盤（和正式環境存檔剛開始時一樣） */
async function withHistory(n: number) {
  const real = api.getPerformance.bind(api)
  const all = await real({ range: "ALL" })
  const first = all.series[all.series.length - n]!.t
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => limitHistory(await real(q), first))
}

describe("主數字下方的總資產走勢", { timeout: 20_000 }, () => {
  it("預設近 1 個月；區間按鈕只放資料撐得起來的（示範資料：5日・1月・3月・全部，沒有 1日）；換區間不再問伺服器、記住選的", async () => {
    const spy = vi.spyOn(api, "getPerformance")
    renderApp("/")
    const region = await trend()
    const chips = within(region).getByRole("radiogroup", { name: "走勢區間" })
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["5日", "1月", "3月", "全部"])
    expect(within(chips).getByRole("radio", { name: "1月" })).toHaveAttribute("aria-checked", "true")
    expect(within(region).getByText("近 1 個月")).toBeInTheDocument()
    expect(within(region).getByRole("img", { name: /^近 1 個月，總資產從 NT\$[\d,]+ 到 NT\$[\d,]+，報酬(上漲|下跌|持平)/ })).toBeInTheDocument()
    // 起訖寫區間的起始日（和績效分段的期間同一天：11/12 往前一個月是 10/12），不是當基準畫的前一個收盤（10/9）
    expect(within(region).getByText("10/12 – 11/12")).toBeInTheDocument()
    expect([...within(region).getByRole("img").querySelectorAll("text")].map((t) => t.textContent)).toContain("10/12")
    // 首頁只問「全部」一次（不帶基準），不再另外問 1M
    expect(spy.mock.calls.filter(([q]) => q.range !== "ALL" || q.benchmark)).toEqual([])
    const before = spy.mock.calls.length
    await userEvent.click(within(chips).getByRole("radio", { name: "3月" }))
    expect(within(region).getByText("近 3 個月")).toBeInTheDocument()
    expect(spy.mock.calls.length).toBe(before)
    expect(useLedgerPrefs.getState().trendRange).toBe("3M")
  })

  it("鍵盤：End 到最後一個收盤、← 前一天、Esc 收起；讀數寫那一天的總資產、投入本金、報酬；大數字不變", async () => {
    renderApp("/")
    const region = await trend()
    const g = chart(region)
    const big = document.querySelector(".hero-figure")!.textContent
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    expect(within(region).getByText(/^11\/12（四）收盤$/)).toBeInTheDocument()
    expect(within(region).getByText(/^投入本金 NT\$[\d,]+$/)).toBeInTheDocument()
    // 窄螢幕放不下時截斷的是日期（「上市 11/17・上櫃 11/14 收盤」），金額一定完整
    expect(within(region).getByText(/^11\/12（四）收盤$/)).toHaveClass("min-w-0", "truncate")
    expect(within(region).getByText(/^NT\$[\d,]+$/)).toHaveClass("shrink-0")
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toMatch(/^11\/12（四）收盤，總資產 NT\$[\d,]+，投入本金 NT\$[\d,]+，報酬/)
    fireEvent.keyDown(g, { key: "ArrowLeft" })
    expect(within(region).getByText(/^11\/11（三）收盤$/)).toBeInTheDocument()
    expect(document.querySelector(".hero-figure")!.textContent).toBe(big)
    fireEvent.keyDown(g, { key: "Escape" })
    expect(within(region).getByText("近 1 個月")).toBeInTheDocument()
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toBe("")
  })

  it("滑鼠滑過不念（aria-live 只在鍵盤移動時更新）", async () => {
    renderApp("/")
    const region = await trend()
    const g = chart(region)
    fireEvent.pointerMove(g, { pointerType: "mouse", clientX: 10, clientY: 10 })
    expect(within(region).getByText(/收盤$/)).toBeInTheDocument()
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toBe("")
    fireEvent.pointerLeave(g, { pointerType: "mouse" })
    expect(within(region).getByText("近 1 個月")).toBeInTheDocument()
  })

  it("投入本金離總資產太遠（縱軸只看總資產）：那條線不畫、沒有圖例；讀數照樣寫投入本金", async () => {
    renderApp("/")
    const region = await trend()
    expect(region.querySelector('[data-series="total"]')).not.toBeNull()
    expect(region.querySelector('[data-series="invested"]')).toBeNull()
    expect(within(region).queryByText("投入本金")).toBeNull()
  })

  it("投入本金在範圍裡：畫鉛筆灰階梯線＋一個圖例", async () => {
    const days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
    const series: PerformancePoint[] = days.map((t, i) => ({ t, market_value: 50_000 + i * 60, net_invested: i < 5 ? 49_000 : 49_500, twr_index: 1 + i * 0.001, benchmark_index: null }))
    const perf = { ...(await api.getPerformance({ range: "ALL" })), series, notes: [] } satisfies Performance
    vi.spyOn(api, "getPerformance").mockResolvedValue(perf)
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    expect(region.querySelector('[data-series="invested"]')).not.toBeNull()
    expect(within(region).getByText("投入本金")).toBeInTheDocument()
  })

  it("隱私模式：照樣畫線，但不標金額刻度；讀數遮金額、日期與 % 照常；圖的說明不念金額", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const region = await trend()
    const img = within(region).getByRole("img", { name: /^近 1 個月，總資產報酬/ })
    expect(img.getAttribute("aria-label")).not.toMatch(/NT\$/)
    expect(region.querySelector('[data-series="total"]')).not.toBeNull()
    // 只剩橫軸的日期
    expect([...img.querySelectorAll("text")].map((t) => t.textContent).every((s) => /^\d+\/\d+$/.test(s ?? ""))).toBe(true)
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    expect(within(region).getByText(/^11\/12（四）收盤$/)).toBeInTheDocument()
    expect(within(region).getAllByLabelText("已隱藏").length).toBeGreaterThanOrEqual(2)
    expect(within(region).getByText(/^報酬/, { selector: "span" }).textContent).toMatch(/%/)
    expect(region.querySelector('[aria-live="polite"]')!.textContent).not.toMatch(/NT\$/)
  })

  it("主數字的骨架等走勢的序列也回來才一起換掉：不先放一塊整張圖大的骨架", async () => {
    const real = api.getPerformance.bind(api)
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    vi.spyOn(api, "getPerformance").mockImplementation(async (q) => {
      await gate
      return real(q)
    })
    const summary = vi.spyOn(api, "getPortfolioSummary")
    renderApp("/")
    // 主數字已經讀到了，但走勢還沒：主數字照樣是骨架，走勢不放骨架
    await vi.waitFor(() => expect(summary).toHaveBeenCalled(), T)
    await act(async () => {
      await summary.mock.results[0]!.value
    })
    expect(screen.getByLabelText("總資產載入中")).toBeInTheDocument()
    expect(screen.queryByLabelText("總資產走勢載入中")).toBeNull()
    expect(screen.queryByText("總損益（含股利）")).toBeNull()
    // 走勢的序列和主數字同時開始讀（不等主數字回來才問）
    expect(vi.mocked(api.getPerformance).mock.calls.some(([q]) => q.range === "ALL" && !q.account_id && !q.benchmark)).toBe(true)
    release()
    await screen.findByText("總損益（含股利）", undefined, T)
    expect(await trend()).toBeInTheDocument()
  })

  it("「自訂」關掉走勢圖：整塊不放", async () => {
    act(() => useLedgerPrefs.setState({ showTrend: false }))
    renderApp("/")
    await screen.findByText("總損益（含股利）", undefined, T)
    expect(screen.queryByRole("region", { name: "總資產走勢" })).toBeNull()
  })
})

describe("歷史短（正式存檔 2026/11/12 才開始）", { timeout: 20_000 }, () => {
  it("2～6 個收盤：照畫、每個收盤一個圓點、不放區間；圖下面寫後端的說明＋目前幾個收盤日", async () => {
    await withHistory(3)
    renderApp("/")
    const region = await trend()
    expect(within(region).queryByRole("radiogroup")).toBeNull()
    expect(region.querySelectorAll('[data-point="close"]')).toHaveLength(3)
    expect(region.textContent).toMatch(/績效從 2026\/11\/10 收盤開始算，之前沒有資料・目前 3 個收盤日/)
    // 上次選的 1 月撐不起來：畫全部（標題寫「11/10 起」）
    expect(within(region).getByText("11/10 起")).toBeInTheDocument()
  })

  it("2～6 個收盤：績效分段也寫同一句（高度不跟著分段變），績效分段的說明不再重複那一句", async () => {
    await withHistory(3)
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", undefined, T)
    const region = await trend()
    expect(region.textContent).toMatch(/績效從 2026\/11\/10 收盤開始算，之前沒有資料・目前 3 個收盤日/)
    expect(screen.getAllByText(/績效從 2026\/11\/10 收盤開始算/)).toHaveLength(1)
    // 走勢沒有區間按鈕（不到 7 個收盤）：績效分段也沒有
    expect(screen.queryByRole("radiogroup")).toBeNull()
  })

  it("少於 2 個收盤：不畫圖，一行原因連到績效（手機也看得到）", async () => {
    await withHistory(1)
    renderApp("/")
    const link = await screen.findByRole("link", { name: "總資產走勢：資料還不夠" }, T)
    expect(link.className).not.toMatch(/max-lg:hidden/)
    expect(screen.queryByRole("region", { name: "總資產走勢" })).toBeNull()
  })

  it("少於 2 個收盤：績效分段也放同一行（一樣高，換分段時分段列不跳），但不連到自己", async () => {
    await withHistory(1)
    renderApp("/?view=performance")
    await screen.findByText("算不出績效", undefined, T)
    expect(await screen.findByText("總資產走勢：資料還不夠", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "總資產走勢：資料還不夠" })).toBeNull()
  })
})

describe("和績效分段分工：整頁只有一排區間按鈕", { timeout: 20_000 }, () => {
  it("績效分段：區間按鈕照樣在走勢下面（每個分段同一排、同一個位置），工具列不放；換區間績效跟著換；不再畫「市值與投入本金」", async () => {
    const spy = vi.spyOn(api, "getPerformance")
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", undefined, T)
    const region = await trend()
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1)
    expect(screen.queryByRole("radiogroup", { name: "績效區間" })).toBeNull()
    const chips = within(region).getByRole("radiogroup", { name: "走勢區間" })
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["5日", "1月", "3月", "全部"])
    expect(within(chips).getByRole("radio", { name: "1月" })).toHaveAttribute("aria-checked", "true")
    expect(screen.queryByText("市值與投入本金")).toBeNull()
    // 工具列的期間和走勢的起訖是同一天
    expect(screen.getByText("2026/10/12 – 2026/11/12")).toBeInTheDocument()
    expect(within(region).getByText("10/12 – 11/12")).toBeInTheDocument()
    await userEvent.click(within(chips).getByRole("radio", { name: "3月" }))
    expect(within(region).getByText("近 3 個月")).toBeInTheDocument()
    expect(useLedgerPrefs.getState().trendRange).toBe("3M")
    await vi.waitFor(() => expect(spy.mock.calls.some(([q]) => q.range === "3M")).toBe(true), T)
    await screen.findByText("2026/08/12 – 2026/11/12", undefined, T)
    expect(within(region).getByText("8/12 – 11/12")).toBeInTheDocument()
  })

  it("「自訂」關掉走勢時：區間按鈕在績效分段的工具列（整頁還是只有一排）", async () => {
    act(() => useLedgerPrefs.setState({ showTrend: false }))
    renderApp("/?view=performance")
    const chips = await screen.findByRole("radiogroup", { name: "績效區間" }, T)
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1)
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["5日", "1月", "3月", "全部"])
  })

  it("首頁走勢的區間報酬和績效分段同一個區間的時間加權報酬是同一個數字（1 月、3 月、全部）", async () => {
    const all = await api.getPerformance({ range: "ALL" })
    const { rangeReturn, trendWindow } = await import("@/lib/trend-range")
    for (const range of ["1M", "3M", "ALL"] as const) {
      const p = await api.getPerformance({ range })
      const win = trendWindow(all.series, range)
      expect(rangeReturn(win)!).toBeCloseTo(p.twr!, 3)
      expect(win.points[win.from]!.t).toBe(p.start_date)
    }
  })
})
