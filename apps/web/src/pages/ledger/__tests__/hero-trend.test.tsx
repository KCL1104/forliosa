import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { limitHistory } from "@/api/mock/adapter"
import { ApiError, type Performance, type PerformancePoint } from "@/api/types"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"

/**
 * 總資產走勢（產品負責人 2026-11-17 選方案 B）：主數字下方滿版的走勢、滑過看那一天、區間在前端切；
 * 和績效分段共用一個區間，整頁只有一排區間按鈕；績效分段不再畫「市值與投入本金」。
 * 區間按鈕一律七顆（2026-11-17 負責人要求）：比資料長的區間畫全部的資料，期間寫「只有 … 的資料」。
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
  useLedgerPrefs.setState({ columns: DEFAULT_COLUMNS, showTrend: true, pinned: [], showClosed: false, trendRange: "1M", showInvested: true })
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
const ALL_CHIPS = ["5日", "1月", "3月", "6月", "今年", "1年", "全部"]
const chipLabels = (group: HTMLElement) => within(group).getAllByRole("radio").map((r) => r.textContent)
/** 讀數第一行的報酬（「報酬 ▲1.23%上漲」） */
const headlineReturn = (region: HTMLElement) => within(region).getByText(/^報酬/, { selector: "span" }).textContent
/** 圖上方固定兩行的讀數 */
const readout = (region: HTMLElement) => region.querySelector<HTMLElement>("[data-readout]")!

/**
 * 舊版後端（績效沒有 composition）：走勢和資產組成以前一模一樣（讀數寫投入本金、縱軸只看總資產）。
 * 示範帳本預設有資產組成（v2：本金線＋賺虧塗色，見 asset-composition-v2.test.tsx），測以前的畫法時用這個
 */
async function withoutComposition() {
  const real = api.getPerformance.bind(api)
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => {
    const { composition: _c, fund_rank: _f, ...rest } = await real(q)
    return rest
  })
}

/** 「全部」的序列只留最後 n 個收盤（和正式環境存檔剛開始時一樣） */
async function withHistory(n: number) {
  const real = api.getPerformance.bind(api)
  const all = await real({ range: "ALL" })
  const first = all.series[all.series.length - n]!.t
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => limitHistory(await real(q), first))
}

describe("主數字下方的總資產走勢", { timeout: 20_000 }, () => {
  it("預設近 1 個月；區間按鈕一律七顆（沒有 1日）；換區間不再問伺服器、記住選的", async () => {
    const spy = vi.spyOn(api, "getPerformance")
    renderApp("/")
    const region = await trend()
    const chips = within(region).getByRole("radiogroup", { name: "走勢區間" })
    expect(chipLabels(chips)).toEqual(ALL_CHIPS)
    expect(within(chips).getByRole("radio", { name: "1月" })).toHaveAttribute("aria-checked", "true")
    expect(within(region).getByText("近 1 個月")).toBeInTheDocument()
    expect(within(region).getByRole("img", { name: /^近 1 個月，總資產從 NT\$[\d,]+ 到 NT\$[\d,]+，報酬(上漲|下跌|持平)/ })).toBeInTheDocument()
    // 起訖寫區間的起始日（和績效分段的期間同一天：11/12 往前一個月是 10/12），不是當基準畫的前一個收盤（10/9）
    expect(within(region).getByText("10/12 – 11/12")).toBeInTheDocument()
    expect([...within(region).getByRole("img").querySelectorAll("text")].map((t) => t.textContent)).toContain("10/12")
    // 首頁的走勢只問「全部」一次（不帶基準），不再另外問 1M；本月（MTD）是分享卡問的（有加入群組時帳本也放，2026-11-21）
    expect(spy.mock.calls.filter(([q]) => (q.range !== "ALL" || q.benchmark) && q.range !== "MTD")).toEqual([])
    // 只數走勢自己的請求：分享卡的本月（MTD）可能比這裡晚送出，數進去就會偶爾多 1（CI 2026-11-21）
    const trendCalls = () => spy.mock.calls.filter(([q]) => q.range !== "MTD").length
    const before = trendCalls()
    await userEvent.click(within(chips).getByRole("radio", { name: "3月" }))
    expect(within(region).getByText("近 3 個月")).toBeInTheDocument()
    expect(trendCalls()).toBe(before)
    expect(useLedgerPrefs.getState().trendRange).toBe("3M")
  })

  it("比資料長的區間（資料 6/1 起，選 1年）：畫全部的資料，標題照樣寫「近 1 年」，期間寫「只有 … 的資料」、不寫年份；報酬和「全部」一樣", async () => {
    // 示範帳本有存檔開始以前的 Yahoo 參考價（回補開著）：只留 6/1 以後的收盤，當成一個比較新的帳本
    const real = api.getPerformance.bind(api)
    const since = (await real({ range: "ALL" })).series.filter((x) => x.t >= "2026-06-01").length
    await withHistory(since)
    const all = await api.getPerformance({ range: "ALL" })
    const first = all.series[0]!.t
    const start = `${Number(first.slice(5, 7))}/${Number(first.slice(8, 10))}`
    renderApp("/")
    const region = await trend()
    const chips = within(region).getByRole("radiogroup", { name: "走勢區間" })
    await userEvent.click(within(chips).getByRole("radio", { name: "全部" }))
    const allReturn = headlineReturn(region)
    expect(within(region).getByText(`${start} – 11/12`)).toBeInTheDocument()
    await userEvent.click(within(chips).getByRole("radio", { name: "1年" }))
    expect(within(chips).getByRole("radio", { name: "1年" })).toHaveAttribute("aria-checked", "true")
    expect(within(region).getByText("近 1 年")).toBeInTheDocument()
    expect(within(region).getByText(`只有 ${start} – 11/12 的資料`)).toBeInTheDocument()
    expect(headlineReturn(region)).toBe(allReturn)
    expect(within(region).getByRole("img", { name: new RegExp(`^近 1 年，只有 ${start} – 11/12 的資料，總資產從`) })).toBeInTheDocument()
    // 3 月撐得起來：期間不加「只有」
    await userEvent.click(within(chips).getByRole("radio", { name: "3月" }))
    expect(within(region).getByText("8/12 – 11/12")).toBeInTheDocument()
    expect(within(region).queryByText(/^只有 /)).toBeNull()
  })

  it("存檔開始以前用 Yahoo 參考價算（產品負責人 2026-11-18）：區間用到時按鈕下面寫一行（1 年寫年份），區間都在存檔以後就不寫", async () => {
    renderApp("/")
    const region = await trend()
    const chips = within(region).getByRole("radiogroup", { name: "走勢區間" })
    // 1 月（10/12 起）都是存檔以後的官方收盤
    expect(within(region).queryByText(/以前用 Yahoo 參考價計算/)).toBeNull()
    await userEvent.click(within(chips).getByRole("radio", { name: "1年" }))
    expect(within(region).getByText("2026/5/29 以前用 Yahoo 參考價計算，不是官方資料")).toBeInTheDocument()
    // 資料夠長了：不寫「只有 … 的資料」
    expect(within(region).queryByText(/^只有 /)).toBeNull()
    await userEvent.click(within(chips).getByRole("radio", { name: "6月" }))
    expect(within(region).getByText("5/29 以前用 Yahoo 參考價計算，不是官方資料")).toBeInTheDocument()
  })

  it("鍵盤：End 到最後一個收盤、← 前一天、Esc 收起；讀數寫那一天的總資產、投入本金、報酬；大數字不變", async () => {
    await withoutComposition()
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
    // 讀數裡的金額（只看讀數那兩行）
    expect(within(readout(region)).getByText(/^NT\$[\d,]+$/)).toHaveClass("shrink-0")
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
    await withoutComposition()
    renderApp("/")
    const region = await trend()
    expect(region.querySelector('[data-series="total"]')).not.toBeNull()
    expect(region.querySelector('[data-series="invested"]')).toBeNull()
    expect(within(region).queryByText("投入本金")).toBeNull()
  })

  it("投入本金在範圍裡：畫鉛筆灰階梯線＋一個圖例", async () => {
    const days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
    const series: PerformancePoint[] = days.map((t, i) => ({ t, market_value: 50_000 + i * 60, net_invested: i < 5 ? 49_000 : 49_500, twr_index: 1 + i * 0.001, benchmark_index: null }))
    // 舊版後端（沒有 composition）：資產組成時本金線一律畫，圖例也不一樣
    const { composition: _c, ...real } = await api.getPerformance({ range: "ALL" })
    const perf = { ...real, series, notes: [] } satisfies Performance
    vi.spyOn(api, "getPerformance").mockResolvedValue(perf)
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    expect(region.querySelector('[data-series="invested"]')).not.toBeNull()
    // 圖例在讀數第二行
    expect(within(readout(region)).getByText("投入本金")).toBeInTheDocument()
  })

  it("隱私模式：照樣畫線，但不標金額刻度；讀數遮金額、日期與 % 照常；圖的說明不念金額", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const region = await trend()
    const img = within(region).getByRole("img", { name: /^近 1 個月，總資產報酬/ })
    expect(img.getAttribute("aria-label")).not.toMatch(/NT\$/)
    expect(region.querySelector('[data-series="total"]')).not.toBeNull()
    // 只剩橫軸的日期（資產組成：1 月的本金在圖外，圖裡那一行不寫金額）
    expect([...img.querySelectorAll("text:not([data-off-chart])")].map((t) => t.textContent).every((s) => /^\d+\/\d+$/.test(s ?? ""))).toBe(true)
    expect(img.querySelector("[data-off-chart]")!.textContent).toBe("本金在圖的下方")
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
  it("2～6 個收盤：照畫、每個收盤一個圓點、七顆區間照放（上次選的 1 月）；按鈕下面寫後端的說明＋目前幾個收盤日", async () => {
    await withHistory(3)
    renderApp("/")
    const region = await trend()
    const chips = within(region).getByRole("radiogroup", { name: "走勢區間" })
    expect(chipLabels(chips)).toEqual(ALL_CHIPS)
    expect(within(chips).getByRole("radio", { name: "1月" })).toHaveAttribute("aria-checked", "true")
    expect(region.querySelectorAll('[data-point="close"]')).toHaveLength(3)
    const note = within(region).getByText(/目前 3 個收盤日/).closest("p")!
    expect(note.textContent).toMatch(/^績效從 2026\/11\/10 收盤開始算，之前沒有資料。目前 3 個收盤日$/)
    // 說明在區間按鈕下面（按鈕的位置和歷史夠長以後一樣）
    expect(chips.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 比資料長：標題照樣寫近 1 個月，期間照實寫
    expect(within(region).getByText("近 1 個月")).toBeInTheDocument()
    expect(within(region).getByText("只有 11/10 – 11/12 的資料")).toBeInTheDocument()
    const oneMonth = headlineReturn(region)
    // 全部：標題寫「11/10 起」、期間不加「只有」；報酬一樣（都從第一個收盤算起）
    await userEvent.click(within(chips).getByRole("radio", { name: "全部" }))
    expect(within(region).getByText("11/10 起")).toBeInTheDocument()
    expect(within(region).getByText("11/10 – 11/12")).toBeInTheDocument()
    expect(headlineReturn(region)).toBe(oneMonth)
    // 1 年：比資料長時不寫年份（畫的是實際那幾天）
    await userEvent.click(within(chips).getByRole("radio", { name: "1年" }))
    expect(within(region).getByText("近 1 年")).toBeInTheDocument()
    expect(within(region).getByText("只有 11/10 – 11/12 的資料")).toBeInTheDocument()
    expect(useLedgerPrefs.getState().trendRange).toBe("1Y")
  })

  it("2～6 個收盤：績效分段也是同一排按鈕＋同一句（高度不跟著分段變），工具列不放自己的；說明不重複；期間照實寫", async () => {
    await withHistory(3)
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", undefined, T)
    const region = await trend()
    expect(region.textContent).toMatch(/績效從 2026\/11\/10 收盤開始算，之前沒有資料。目前 3 個收盤日/)
    expect(screen.getAllByText(/績效從 2026\/11\/10 收盤開始算/)).toHaveLength(1)
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1)
    expect(chipLabels(within(region).getByRole("radiogroup", { name: "走勢區間" }))).toEqual(ALL_CHIPS)
    expect(screen.queryByRole("radiogroup", { name: "績效區間" })).toBeNull()
    expect(await screen.findByText("只有 2026/11/10 – 2026/11/12 的資料", undefined, T)).toBeInTheDocument()
    expect(within(region).getByText("只有 11/10 – 11/12 的資料")).toBeInTheDocument()
  })

  it("2～6 個收盤：持倉和績效分段的走勢一模一樣（按鈕和說明都在，換分段時分段列不跳）", async () => {
    await withHistory(3)
    renderApp("/")
    const holdings = await trend()
    const shape = (r: HTMLElement) => [!!within(r).queryByRole("radiogroup", { name: "走勢區間" }), !!within(r).queryByText(/目前 3 個收盤日/)]
    expect(shape(holdings)).toEqual([true, true])
    await userEvent.click(screen.getByRole("tab", { name: /績效/ }))
    await screen.findByText("最大回撤", undefined, T)
    expect(shape(await trend())).toEqual([true, true])
  })

  it("少於 2 個收盤：不畫圖、沒有區間按鈕，一行原因連到績效（手機也看得到）", async () => {
    await withHistory(1)
    renderApp("/")
    const link = await screen.findByRole("link", { name: "總資產走勢：資料還不夠" }, T)
    expect(link.className).not.toMatch(/max-lg:hidden/)
    // 手機（2026-11-21）：「總資產走勢」那一盤只有這一行原因——標題已經寫了「總資產走勢」，看得到的只寫原因；沒有圖
    const region = screen.getByRole("region", { name: "總資產走勢" })
    expect(within(region).queryByRole("img")).toBeNull()
    expect(link).toHaveTextContent(/^總資產走勢：資料還不夠$/)
    expect(within(link).getByText("總資產走勢：")).toHaveClass("sr-only")
    expect(screen.queryByRole("radiogroup")).toBeNull()
  })

  it("少於 2 個收盤：績效分段也放同一行（一樣高，換分段時分段列不跳），但不連到自己；換區間也算不出來，不放區間", async () => {
    await withHistory(1)
    renderApp("/?view=performance")
    await screen.findByText("算不出績效", undefined, T)
    expect(await screen.findByText("總資產走勢：資料還不夠", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "總資產走勢：資料還不夠" })).toBeNull()
    expect(screen.queryByRole("radiogroup")).toBeNull()
  })

  it("「自訂」關掉走勢、2～6 個收盤：績效分段的工具列放七顆「績效區間」（整頁只有一排），期間照實寫", async () => {
    await withHistory(3)
    act(() => useLedgerPrefs.setState({ showTrend: false }))
    renderApp("/?view=performance")
    const chips = await screen.findByRole("radiogroup", { name: "績效區間" }, T)
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1)
    expect(chipLabels(chips)).toEqual(ALL_CHIPS)
    expect(within(chips).getByRole("radio", { name: "1月" })).toHaveAttribute("aria-checked", "true")
    expect(await screen.findByText("只有 2026/11/10 – 2026/11/12 的資料", undefined, T)).toBeInTheDocument()
    // 走勢關掉時說明照樣寫在績效分段（只寫一次）
    expect(screen.getAllByText(/績效從 2026\/11\/10 收盤開始算/)).toHaveLength(1)
  })

  it("比資料長的區間：首頁走勢和績效分段（後端）同一個報酬、同一個起始日，都和「全部」一樣從第一個收盤算起", async () => {
    await withHistory(4)
    const all = await api.getPerformance({ range: "ALL" })
    const { rangeReturn, trendWindow } = await import("@/lib/trend-range")
    for (const range of ["5D", "1M", "3M", "6M", "YTD", "1Y"] as const) {
      const p = await api.getPerformance({ range })
      const win = trendWindow(all.series, range)
      expect(win.exceeds).toBe(true)
      expect(win.points).toHaveLength(4)
      // 示範資料的短區間 twr_index 只留 4 位小數，比到 0.1% 以內（和上面「1 月、3 月、全部」那一則一樣）
      expect(rangeReturn(win)!).toBeCloseTo(p.twr!, 3)
      expect(rangeReturn(win)!).toBeCloseTo(all.twr!, 6)
      expect(win.points[win.from]!.t).toBe(p.start_date)
    }
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
    expect(chipLabels(chips)).toEqual(ALL_CHIPS)
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

  it("用到 Yahoo 參考價的區間：走勢下面寫了那一句，績效分段不再寫；走勢關掉時寫在績效分段（只寫一次）", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", undefined, T)
    const region = await trend()
    await within(region).findByText("2026/5/29 以前用 Yahoo 參考價計算，不是官方資料", undefined, T)
    expect(screen.getAllByText(/以前用 Yahoo 參考價計算/)).toHaveLength(1)
    cleanup()
    act(() => useLedgerPrefs.setState({ showTrend: false }))
    renderApp("/?view=performance")
    await screen.findByText("2026/05/29 以前用 Yahoo 參考價計算，不是官方資料", undefined, T)
    expect(screen.getAllByText(/以前用 Yahoo 參考價計算/)).toHaveLength(1)
  })

  it("「自訂」關掉走勢時：區間按鈕在績效分段的工具列（整頁還是只有一排）", async () => {
    act(() => useLedgerPrefs.setState({ showTrend: false }))
    renderApp("/?view=performance")
    const chips = await screen.findByRole("radiogroup", { name: "績效區間" }, T)
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1)
    expect(chipLabels(chips)).toEqual(ALL_CHIPS)
  })

  it("主數字讀不到（走勢也就不放）、2～6 個收盤：績效分段的工具列放七顆「績效區間」，說明寫在績效分段（只寫一次）", async () => {
    await withHistory(3)
    vi.spyOn(api, "getPortfolioSummary").mockRejectedValue(new ApiError(500, "internal", "伺服器錯誤"))
    renderApp("/?view=performance")
    const chips = await screen.findByRole("radiogroup", { name: "績效區間" }, T)
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1)
    expect(chipLabels(chips)).toEqual(ALL_CHIPS)
    expect(screen.queryByRole("region", { name: "總資產走勢" })).toBeNull()
    expect(await screen.findAllByText(/績效從 2026\/11\/10 收盤開始算/, undefined, T)).toHaveLength(1)
  })

  it.each([
    ["新帳戶的「全部」先回來", "ALL"],
    ["新帳戶的區間先回來", "range"],
  ] as const)("切換帳戶時兩個查詢回來的先後不同（%s）：舊帳戶真的 1 個月不會寫成「只有」；新帳戶的回來以後才寫", async (_, early) => {
    const real = api.getPerformance.bind(api)
    const all = (await real({ range: "ALL" })).series
    const first = all[all.length - 4]!.t
    const acct = (await api.listAccounts())[0]!
    let release = () => {}
    const gate = new Promise<void>((r) => (release = r))
    let earlyDone = () => {}
    const earlyBack = new Promise<void>((r) => (earlyDone = r))
    vi.spyOn(api, "getPerformance").mockImplementation(async (q) => {
      if (q.account_id !== acct.id) return real(q)
      const p = limitHistory(await real(q), first)
      if ((q.range === "ALL") === (early === "ALL")) {
        setTimeout(earlyDone, 0)
        return p
      }
      await gate
      return p
    })
    renderApp("/?view=performance")
    await screen.findByText("2026/10/12 – 2026/11/12", undefined, T)
    await userEvent.click(screen.getByRole("combobox", { name: "帳戶" }))
    await userEvent.click(await screen.findByRole("option", { name: acct.name }, T))
    await earlyBack
    await act(() => new Promise((r) => setTimeout(r, 50)))
    expect(screen.queryByText(/^只有 /)).toBeNull()
    act(release)
    expect(await screen.findByText(`只有 ${first.replaceAll("-", "/")} – 2026/11/12 的資料`, undefined, T)).toBeInTheDocument()
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
