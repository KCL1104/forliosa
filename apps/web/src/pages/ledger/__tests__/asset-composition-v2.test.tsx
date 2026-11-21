import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Performance, PerformancePoint } from "@/api/types"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"

/**
 * 資產組成 v2（產品負責人選的：一張圖，沒有下面那一格；docs/proposals/asset-composition.md 附錄 A）：
 * 本金是鉛筆灰階梯線（不填色），總資產和本金之間塗淡色——上面是賺的、下面是虧的，交會的地方換顏色；
 * 縱軸照 35% 的規則決定要不要把本金放進來，放不進來時圖裡寫一行本金在哪一邊；圖例兼金額。
 */
vi.mock("@number-flow/react", () => ({
  default: ({ value, format, locales }: { value: number; format?: Intl.NumberFormatOptions; locales?: string }) => <span>{new Intl.NumberFormat(locales, format).format(value)}</span>,
}))

beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  Element.prototype.setPointerCapture ??= () => {}
  Element.prototype.releasePointerCapture ??= () => {}
  Element.prototype.hasPointerCapture ??= () => false
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetPrefs = () => {
  localStorage.removeItem("forliosa:ledger")
  useLedgerPrefs.setState({ columns: DEFAULT_COLUMNS, showTrend: true, pinned: [], showClosed: false, trendRange: "1M", showInvested: true })
  usePrefs.setState({ privacyMode: false, quantityUnit: "lot" })
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
/** 桌面版面（≥ 1024px）：走勢 120px 高、區間按鈕在讀數那一列的右邊（和 main 一樣） */
function asDesktop() {
  const real = window.matchMedia
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => (query === "(min-width: 1024px)" ? ({ ...real(query), matches: true } as MediaQueryList) : real(query)))
}
const trend = () => screen.findByRole("region", { name: "總資產走勢" }, T)
const chart = (region: HTMLElement) => within(region).getByRole("group", { name: /^總資產走勢：/ })
const img = (region: HTMLElement) => within(region).getByRole("img")
const legend = (region: HTMLElement, item: "invested" | "gain" | "dividend" | "total") => region.querySelector<HTMLElement>(`[data-legend="${item}"]`)
/** 縱軸的刻度字（不含橫軸的日期、圖裡的小字） */
const yLabels = (region: HTMLElement) => [...img(region).querySelectorAll("text[text-anchor='end'][dominant-baseline='central']")].map((t) => t.textContent)

const nineDays = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
const comp0 = { dividends: [], estimated: [], months: [], months_estimated: 0 }
/** 九個收盤的序列：每一天的總資產與本金 */
const seriesOf = (rows: [number, number][]): PerformancePoint[] => nineDays.map((t, i) => ({ t, market_value: rows[i]![0], net_invested: rows[i]![1], twr_index: rows[i]![0] / rows[0]![0], benchmark_index: null }))
async function withSeries(series: PerformancePoint[]) {
  const real = api.getPerformance.bind(api)
  const realSummary = api.getPortfolioSummary.bind(api)
  vi.spyOn(api, "getPortfolioSummary").mockImplementation(async (a) => ({ ...(await realSummary(a)), dividend_income: 0 }))
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => ({ ...(await real(q)), series, notes: [], reference_until: null, composition: comp0 }) satisfies Performance)
}

describe("資產組成 v2：一張圖，本金線＋賺虧塗色", { timeout: 20_000 }, () => {
  it("「全部」（示範帳本一直賺）：只塗賺的（漲的顏色的 token，不是寫死的紅），縱軸貼著兩條線（本金在圖裡，不寫在哪一邊）；塗色只在圖的範圍裡", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    const gain = region.querySelector('[data-band="gain"]')!
    expect(gain.getAttribute("fill")).toBe("var(--rise-tint)")
    expect(gain.getAttribute("stroke")).toBe("none")
    expect(region.querySelector('[data-band="loss"]')).toBeNull()
    // 平塗：沒有漸層、沒有動畫
    expect(region.querySelector("linearGradient, radialGradient, animate")).toBeNull()
    // 塗色與本金線都切在圖的範圍裡
    const clip = region.querySelector("clipPath")!
    expect(region.querySelector("[data-bands]")!.getAttribute("clip-path")).toBe(`url(#${clip.id})`)
    expect(region.querySelector('[data-series="invested"]')!.getAttribute("clip-path")).toBe(`url(#${clip.id})`)
    expect(region.querySelector("[data-off-chart]")).toBeNull()
    // 手機（jsdom 不是桌面）：示範帳本有「估計」括線與股利記號那兩列，加高到 114（畫圖的範圍和 main 一樣 66）
    expect(img(region).getAttribute("height")).toBe("114")
  })

  it("1 個月：本金離太遠（總資產的起伏不到兩條線範圍的 35%），縱軸只跟總資產；圖裡寫「本金 288萬，在圖的下方」；滑過時縱軸不跳", async () => {
    // 桌面（120px）：圖裡放得下那一行（手機加高到 114px 也放得下，見下一個測試）
    asDesktop()
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(900)
    renderApp("/")
    const region = await trend()
    expect(img(region).getAttribute("height")).toBe("120")
    await waitFor(() => expect(region.querySelector("[data-off-chart]")).not.toBeNull(), T)
    const note = region.querySelector("[data-off-chart]")!
    expect(note.textContent).toBe("本金 288萬，在圖的下方")
    expect(note.getAttribute("data-off-chart")).toBe("below")
    expect(note.getAttribute("fill")).toBe("var(--muted-foreground)")
    // 縱軸只跟總資產：刻度都在 380 萬上下，不會到 288 萬
    const ticks = yLabels(region)
    expect(ticks.every((t) => Number(t!.replace(/[^\d.]/g, "")) >= 370)).toBe(true)
    // 塗色畫到圖的下緣（本金在圖外）
    expect(region.querySelector('[data-band="gain"]')).not.toBeNull()
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    expect(yLabels(region)).toEqual(ticks)
    for (let i = 0; i < 10; i++) fireEvent.keyDown(g, { key: "ArrowRight" })
    expect(yLabels(region)).toEqual(ticks)
    expect(region.querySelector("[data-off-chart]")!.textContent).toBe("本金 288萬，在圖的下方")
  })

  it("手機（114px，畫圖的範圍和 main 一樣 66px）：同一個 1 個月，圖裡也放得下「本金 288萬，在圖的下方」（48px 時放不下、退回圖例），圖例不再重複", async () => {
    renderApp("/")
    const region = await trend()
    expect(img(region).getAttribute("height")).toBe("114")
    expect(region.querySelector("clipPath rect")!.getAttribute("height")).toBe("66")
    await waitFor(() => expect(region.querySelector("[data-off-chart]")).not.toBeNull(), T)
    expect(region.querySelector("[data-off-chart]")!.textContent).toBe("本金 288萬，在圖的下方")
    expect(legend(region, "invested")!.textContent).toMatch(/^本金 NT\$[\d,]+$/)
    expect(img(region).getAttribute("aria-label")).toContain("，本金 288萬，在圖的下方")
  })

  it("本金在總資產上面而且離太遠（虧很多）：圖裡寫「在圖的上方」", async () => {
    await withSeries(seriesOf([[1_000_000, 2_000_000], [1_010_000, 2_000_000], [990_000, 2_000_000], [1_020_000, 2_000_000], [1_030_000, 2_000_000], [1_000_000, 2_000_000], [1_040_000, 2_000_000], [1_050_000, 2_000_000], [1_060_000, 2_000_000]]))
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    const note = await waitFor(() => region.querySelector("[data-off-chart]")!, T)
    expect(note.textContent).toBe("本金 200萬，在圖的上方")
    expect(note.getAttribute("data-off-chart")).toBe("above")
    expect(region.querySelector('[data-band="loss"]')!.getAttribute("fill")).toBe("var(--fall-tint)")
    expect(region.querySelector('[data-band="gain"]')).toBeNull()
  })

  it("賺轉虧：兩種顏色都有；圖例跟著滑到的那一天換「賺的」「虧的」；圖的說明用字說有賺有虧（不靠顏色）", async () => {
    await withSeries(seriesOf([[100_000, 100_000], [110_000, 100_000], [120_000, 100_000], [105_000, 100_000], [95_000, 100_000], [90_000, 100_000], [100_000, 100_000], [96_000, 100_000], [94_000, 100_000]]))
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(region.querySelector('[data-band="loss"]')).not.toBeNull(), T)
    expect(region.querySelector('[data-band="gain"]')).not.toBeNull()
    expect(img(region).getAttribute("aria-label")).toContain("，資產組成：最後一天本金 NT$100,000，虧的 NT$6,000，這段期間有賺有虧。本金是買股票花的錢")
    // 沒有滑過：最後一天（虧）
    expect(legend(region, "gain")!.textContent).toBe("虧的 −NT$6,000")
    expect(legend(region, "gain")!.querySelector(".text-fall")).not.toBeNull()
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    // 11/4：總資產 120,000、本金 100,000
    expect(legend(region, "gain")!.textContent).toBe("賺的 +NT$20,000")
    expect(legend(region, "gain")!.querySelector(".bg-rise-tint")).not.toBeNull()
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$100,000")
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toMatch(/^11\/4（三）收盤，總資產 NT\$120,000，本金 NT\$100,000，賺的 NT\$20,000，報酬上漲/)
    fireEvent.keyDown(g, { key: "ArrowRight" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    expect(legend(region, "gain")!.textContent).toBe("虧的 −NT$5,000")
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toContain("，虧的 NT$5,000，")
    // v2 圖下面沒有句子（使用者只要圖）
    expect(within(region).queryByText(/^這段期間總資產/)).toBeNull()
  })

  it("隱私模式：圖例、圖裡那一行、圖的說明都不寫金額；塗色照畫", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const region = await trend()
    expect(region.querySelector("[data-off-chart]")!.textContent).toBe("本金在圖的下方")
    expect(legend(region, "invested")!.textContent).not.toMatch(/NT\$/)
    expect(legend(region, "gain")!.textContent).not.toMatch(/NT\$/)
    expect(img(region).getAttribute("aria-label")).not.toMatch(/NT\$|萬/)
    expect(img(region).getAttribute("aria-label")).toMatch(/，資產組成：最後一天賺，本金在圖的下方。本金是買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢$/)
    expect(region.querySelector('[data-band="gain"]')).not.toBeNull()
  })

  it("寬的時候（桌面）：照 main 的格線——讀數｜區間按鈕一列、圖例（＋本金開關）橫跨兩欄、再來是圖；滑過時圖例的金額換成那一天的，讀數第二行是報酬", async () => {
    asDesktop()
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000)
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    expect(region).toHaveClass("lg:grid", "lg:grid-cols-[minmax(0,1fr)_auto]")
    const readout = region.querySelector<HTMLElement>("[data-readout]")!
    await waitFor(() => expect(region.querySelector("[data-legend-row]")).not.toBeNull(), T)
    expect(readout).toHaveClass("h-11", "lg:col-start-1", "lg:row-start-1")
    // 區間按鈕：讀數那一列的右邊（和 main 一樣）
    expect(within(region).getByRole("radiogroup", { name: "走勢區間" })).toHaveClass("lg:col-start-2", "lg:row-start-1")
    // 圖例：讀數下面、圖的上面，橫跨兩欄；本金開關在最右邊（區間按鈕的正下方）
    const row = region.querySelector<HTMLElement>("[data-legend-row]")!
    expect(readout).not.toContainElement(row)
    expect(row).toHaveClass("lg:col-span-2", "lg:row-start-2")
    expect(region.querySelector("[data-legend-grid]")).toBeNull()
    expect([...row.querySelectorAll("[data-legend]")].map((c) => c.getAttribute("data-legend"))).toEqual(["invested", "gain", "dividend", "total"])
    expect(row.lastElementChild).toContainElement(within(region).getByRole("switch", { name: "本金" }))
    expect(chart(region)).toHaveClass("lg:col-span-2", "lg:row-start-3")
    // DOM 順序照舊（鍵盤先到讀數、圖，再到區間）：讀數 → 圖例 → 圖 → 區間按鈕
    const order = [readout, row, chart(region), within(region).getByRole("radiogroup", { name: "走勢區間" })]
    for (let i = 1; i < order.length; i++) expect(order[i - 1]!.compareDocumentPosition(order[i]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const endInvested = legend(region, "invested")!.textContent
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    const second = readout.querySelectorAll(":scope > p")[1]!
    expect(second.textContent).toMatch(/^報酬 /)
    expect(legend(region, "invested")!.textContent).not.toBe(endInvested)
    expect(legend(region, "gain")!.textContent).toMatch(/^(賺的|虧的) [+−]NT\$[\d,]+$/)
    expect(readout).toHaveClass("h-11")
  })

  it("淡墨面積和賺虧塗色只畫一種：本金開著時塗色取代淡墨面積；關掉時是 main 的淡墨面積（上緣 10%、到下緣 0%）", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/")
    const region = await trend()
    expect(region.querySelector("[data-bands]")).not.toBeNull()
    expect(region.querySelector('[data-series="area"]')).toBeNull()
    expect(region.querySelector("linearGradient")).toBeNull()
    fireEvent.click(within(region).getByRole("switch", { name: "本金" }))
    expect(region.querySelector("[data-bands]")).toBeNull()
    const area = region.querySelector('[data-series="area"]')!
    const gradient = region.querySelector("linearGradient")!
    expect(area.getAttribute("fill")).toBe(`url(#${gradient.id})`)
    expect([...gradient.querySelectorAll("stop")].map((s) => [s.getAttribute("stop-color"), s.getAttribute("stop-opacity")])).toEqual([
      ["var(--chart-mine)", "0.1"],
      ["var(--chart-mine)", "0"],
    ])
    // 面積收到畫圖範圍的下緣（股利記號那一列的上面），在總資產線的下面一層
    const d = area.getAttribute("d")!
    const bottom = Number(d.match(/L[\d.]+ ([\d.]+)Z$/)![1])
    const plotBottom = Number(img(region).getAttribute("height")) - 22 - 8
    expect(bottom).toBe(plotBottom)
    expect(area.compareDocumentPosition(region.querySelector('[data-series="total"]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    fireEvent.click(within(region).getByRole("switch", { name: "本金" }))
    expect(region.querySelector('[data-series="area"]')).toBeNull()
  })

  it("有資產組成時，股利記號在圖的下緣、日期上面（不疊進圖裡）", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "3M" }))
    renderApp("/")
    const region = await trend()
    const marks = [...region.querySelectorAll("[data-dividend-mark]")]
    expect(marks.length).toBeGreaterThan(2)
    const plotBottom = Number(region.querySelector("clipPath rect")!.getAttribute("y")) + Number(region.querySelector("clipPath rect")!.getAttribute("height"))
    for (const m of marks) expect(Number(m.getAttribute("y1"))).toBeGreaterThanOrEqual(plotBottom)
    expect(legend(region, "dividend")!.textContent).toBe("股利")
  })

  it("（第二審 1）有買賣的那一天：總資產線和本金線一起垂直跳（路徑裡有 V）；整批賣出、收盤都是賺的——只塗賺的，圖的說明不說有賺有虧（第二審 2）", async () => {
    // 第 4 天整批賣出：本金 98 萬 → −5 萬（收到 103 萬），總資產 150 萬 → 50 萬；每一天收盤都是賺的
    await withSeries(
      seriesOf([[1_400_000, 980_000], [1_450_000, 980_000], [1_480_000, 980_000], [1_500_000, 980_000], [500_000, -50_000], [505_000, -50_000], [510_000, -50_000], [508_000, -50_000], [512_000, -50_000]]),
    )
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(region.querySelector('[data-band="gain"]')).not.toBeNull(), T)
    expect(region.querySelector('[data-band="loss"]')).toBeNull()
    expect(img(region).getAttribute("aria-label")).not.toContain("有賺有虧")
    expect(region.querySelector('[data-series="total"]')!.getAttribute("d")).toMatch(/V/)
    // 本金關掉：總資產照以前的折線（沒有垂直跳）
    fireEvent.click(within(region).getByRole("switch", { name: "本金" }))
    expect(region.querySelector('[data-series="total"]')!.getAttribute("d")).not.toMatch(/V/)
  })

  it("（第二審 3）倒 U（兩個角落都碰到總資產線或最後一點）：本金在圖外那一行不放進圖裡，改寫在圖例「本金 NT$…（在圖的下方）」；手機的圖例改成兩行（本金一行、其他一行）", async () => {
    const arch = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => [Math.round(4_000_000 + 520_000 * Math.sin((Math.PI * i) / 8)), 2_900_000] as [number, number])
    await withSeries(seriesOf(arch))
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "invested")).not.toBeNull(), T)
    expect(region.querySelector("[data-off-chart]")).toBeNull()
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$2,900,000（在圖的下方）")
    const grid = region.querySelector<HTMLElement>("[data-legend-grid]")!
    expect(grid.children).toHaveLength(2)
    expect(grid.children[0]!.querySelector("[data-legend]")!.getAttribute("data-legend")).toBe("invested")
    expect([...grid.children[1]!.querySelectorAll("[data-legend]")].map((c) => c.getAttribute("data-legend"))).toEqual(["gain", "total"])
    // 圖的說明照樣念本金在下面
    expect(img(region).getAttribute("aria-label")).toContain("，本金 290萬，在圖的下方")
  })

  it("（第二審 3）倒 U 在桌面也一樣：寫在圖例那一排", async () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000)
    const arch = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => [Math.round(4_000_000 + 520_000 * Math.sin((Math.PI * i) / 8)), 2_900_000] as [number, number])
    await withSeries(seriesOf(arch))
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(region.querySelector("[data-legend-row]")).not.toBeNull(), T)
    expect(region.querySelector("[data-off-chart]")).toBeNull()
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$2,900,000（在圖的下方）")
  })

  it("（第二審 4）沒有滑過、不是「全部」：圖例寫「目前賺的」（累積到最後一天）；「全部」與滑過時寫「賺的」", async () => {
    renderApp("/")
    const region = await trend()
    expect(legend(region, "gain")!.textContent).toMatch(/^目前賺的 \+NT\$[\d,]+$/)
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    expect(legend(region, "gain")!.textContent).toMatch(/^賺的 \+NT\$[\d,]+$/)
    fireEvent.keyDown(g, { key: "Escape" })
    expect(legend(region, "gain")!.textContent).toMatch(/^目前賺的 /)
    fireEvent.click(within(region).getByRole("radio", { name: "全部" }))
    expect(legend(region, "gain")!.textContent).toMatch(/^賺的 \+NT\$[\d,]+$/)
  })

  it("（第二審 7）鍵盤：讀數寫那一天的總資產、本金、賺的與報酬；日期太長時截斷的是日期、金額一定完整；Esc 收起、報讀器不再念；上面的大數字不變", async () => {
    renderApp("/")
    const region = await trend()
    const g = chart(region)
    const big = document.querySelector(".hero-figure")!.textContent
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    const day = within(region).getByText(/^11\/12（四）收盤$/)
    expect(day).toHaveClass("min-w-0", "truncate")
    const amount = region.querySelector<HTMLElement>("[data-readout] p .font-semibold")!
    expect(amount.textContent).toMatch(/^NT\$[\d,]+$/)
    expect(amount).toHaveClass("shrink-0")
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toMatch(/^11\/12（四）收盤，總資產 NT\$[\d,]+，本金 NT\$[\d,]+，賺的 NT\$[\d,]+，報酬/)
    fireEvent.keyDown(g, { key: "ArrowLeft" })
    expect(within(region).getByText(/^11\/11（三）收盤$/)).toBeInTheDocument()
    expect(document.querySelector(".hero-figure")!.textContent).toBe(big)
    fireEvent.keyDown(g, { key: "Escape" })
    expect(within(region).getByText("近 1 個月")).toBeInTheDocument()
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toBe("")
    expect(document.querySelector(".hero-figure")!.textContent).toBe(big)
  })
})

describe("走勢圖的高度（產品負責人 2026-11-21）", { timeout: 20_000 }, () => {
  /** 畫圖的範圍（本金開著時切塗色的那個方框） */
  const plotHeight = (region: HTMLElement) => region.querySelector("clipPath rect")!.getAttribute("height")
  /** 九個收盤、只換資產組成（有沒有估計的那一段、股利） */
  async function withComposition(composition: Performance["composition"]) {
    const real = api.getPerformance.bind(api)
    const series = seriesOf(nineDays.map((_, i) => [1_000_000 + i * 5_000, 950_000] as [number, number]))
    return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => ({ ...(await real(q)), series, notes: [], reference_until: null, composition }) satisfies Performance)
  }

  it("桌面 120（兩列從畫圖的範圍裡分出來，72）；手機有「估計」括線與股利記號那兩列時加高到 114，畫圖的範圍和 main 一樣 66——看帳本，換區間不跳", async () => {
    asDesktop()
    renderApp("/")
    const desk = await trend()
    expect(img(desk).getAttribute("height")).toBe("120")
    expect(plotHeight(desk)).toBe("72")
    cleanup()
    vi.restoreAllMocks()
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const phone = await trend()
    expect(img(phone).getAttribute("height")).toBe("114")
    expect(plotHeight(phone)).toBe("66")
    expect(phone.querySelector("[data-bracket]")).not.toBeNull()
    // 5 日碰不到估計的那一段（沒有括線）：照樣 114（圖不跳）
    fireEvent.click(within(phone).getByRole("radio", { name: "5日" }))
    await waitFor(() => expect(phone.querySelector("[data-bracket]")).toBeNull(), T)
    expect(img(phone).getAttribute("height")).toBe("114")
    expect(plotHeight(phone)).toBe("66")
  })

  it("手機沒有那兩列（沒有估計的那一段、沒領過股利）：照 main 96，畫圖的範圍 66；只有一列時加那一列", async () => {
    await withComposition(comp0)
    renderApp("/")
    const none = await trend()
    expect(img(none).getAttribute("height")).toBe("96")
    expect(plotHeight(none)).toBe("66")
    cleanup()
    vi.restoreAllMocks()
    await withComposition({ ...comp0, estimated: [{ from: "2026-11-02", until: "2026-11-04" }], months_estimated: 0 })
    renderApp("/")
    const estOnly = await trend()
    expect(img(estOnly).getAttribute("height")).toBe("106")
    expect(plotHeight(estOnly)).toBe("66")
    cleanup()
    vi.restoreAllMocks()
    await withComposition({ ...comp0, dividends: [{ t: "2026-11-05", amount: 3_000 }] })
    renderApp("/")
    const divOnly = await trend()
    expect(img(divOnly).getAttribute("height")).toBe("104")
    expect(plotHeight(divOnly)).toBe("66")
  })
})

describe("「本金」開關（使用者 2026-11-19）", { timeout: 20_000 }, () => {
  const toggle = (region: HTMLElement) => within(region).getByRole("switch", { name: "本金" })

  it("預設打開；關掉：沒有本金線、沒有塗色、圖例只有總資產（和股利），縱軸跟總資產；圖與讀數的高度不變；說得出它做什麼", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    const sw = toggle(region)
    expect(sw).toHaveAttribute("aria-checked", "true")
    expect(sw).toHaveAccessibleDescription("打開時，走勢圖畫本金線，總資產在本金上面塗賺的顏色、下面塗虧的顏色")
    const height = img(region).getAttribute("height")
    const readout = region.querySelector<HTMLElement>("[data-readout]")!
    const readoutClass = readout.className
    fireEvent.click(sw)
    expect(toggle(region)).toHaveAttribute("aria-checked", "false")
    expect(region.querySelector('[data-series="invested"]')).toBeNull()
    expect(region.querySelector("[data-bands]")).toBeNull()
    expect(region.querySelector("clipPath")).toBeNull()
    expect(legend(region, "invested")).toBeNull()
    expect(legend(region, "gain")).toBeNull()
    expect(legend(region, "total")!.textContent).toBe("總資產")
    expect(img(region).getAttribute("aria-label")).not.toMatch(/資產組成|本金/)
    expect(img(region).getAttribute("height")).toBe(height)
    expect(readout.className).toBe(readoutClass)
    // 股利記號與「估計」照舊
    expect(region.querySelectorAll("[data-dividend-mark]").length).toBeGreaterThan(0)
    expect(region.querySelector("[data-bracket]")).not.toBeNull()
    // 打開回來
    fireEvent.click(toggle(region))
    expect(region.querySelector("[data-bands]")).not.toBeNull()
  })

  it("關掉時縱軸跟總資產（1 年：開著時貼著兩條線，刻度到 300 萬以下；關掉後只跟總資產）", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/")
    const region = await trend()
    const on = yLabels(region)
    fireEvent.click(toggle(region))
    const off = yLabels(region)
    expect(off).not.toEqual(on)
    expect(Math.min(...off.map((t) => Number(t!.replace(/[^\d.]/g, ""))))).toBeGreaterThan(Math.min(...on.map((t) => Number(t!.replace(/[^\d.]/g, "")))))
  })

  it("記住選的（帳本的自訂、這台瀏覽器）：重新整理以後還是關著", async () => {
    renderApp("/")
    const region = await trend()
    fireEvent.click(toggle(region))
    const saved = localStorage.getItem("forliosa:ledger")!
    expect(JSON.parse(saved).state.showInvested).toBe(false)
    cleanup()
    // 模擬重新整理：記憶體裡的設定回到預設（這一步也會寫回瀏覽器，所以把存的放回去），再從瀏覽器讀回來
    act(() => useLedgerPrefs.setState({ showInvested: true }))
    localStorage.setItem("forliosa:ledger", saved)
    await act(() => useLedgerPrefs.persist.rehydrate())
    expect(useLedgerPrefs.getState().showInvested).toBe(false)
    renderApp("/")
    const again = await trend()
    expect(toggle(again)).toHaveAttribute("aria-checked", "false")
    expect(again.querySelector("[data-bands]")).toBeNull()
  })

  it("瀏覽器不給存帳本的設定（讀寫都丟錯）：照樣切得動、頁面不壞", async () => {
    // 只讓帳本的設定（forliosa:ledger）丟錯：這個開關存在那裡（其他地方的存取不在這次的範圍）
    const { getItem, setItem } = Storage.prototype
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key: string, value: string) {
      if (key === "forliosa:ledger") throw new Error("blocked")
      return setItem.call(this, key, value)
    })
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, key: string) {
      if (key === "forliosa:ledger") throw new Error("blocked")
      return getItem.call(this, key)
    })
    await act(() => useLedgerPrefs.persist.rehydrate())
    renderApp("/")
    const region = await trend()
    fireEvent.click(toggle(region))
    expect(toggle(region)).toHaveAttribute("aria-checked", "false")
    expect(region.querySelector("[data-bands]")).toBeNull()
    fireEvent.click(toggle(region))
    expect(region.querySelector("[data-bands]")).not.toBeNull()
  })

  it("位置：手機在讀數第二行（期間）的右邊、不多佔一行（讀數兩行和 main 一樣高，圖例兩行在下面）；桌面在圖例那一列的最右邊；字＋小號開關（和個股走勢圖的「重要時刻」一樣）", async () => {
    renderApp("/")
    const region = await trend()
    const readout = region.querySelector<HTMLElement>("[data-readout]")!
    expect(readout).toContainElement(toggle(region))
    expect(readout).toHaveClass("h-11")
    // 至少兩行（2026-11-21：托盤裡 320px、金額上千億時第二欄換到下一行，不撐出畫面；高度照最寬的金額定，滑過時不跳）
    expect(region.querySelector("[data-legend-grid]")).toHaveClass("min-h-10")
    expect(toggle(region)).toHaveAttribute("data-size", "sm")
    expect(toggle(region).closest("label")!.textContent).toBe("本金")
    cleanup()
    asDesktop()
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000)
    renderApp("/")
    const wide = await trend()
    await waitFor(() => expect(wide.querySelector("[data-legend-row]")).not.toBeNull(), T)
    expect(wide.querySelector("[data-legend-row]")).toContainElement(toggle(wide))
    expect(wide.querySelector("[data-readout]")).not.toContainElement(toggle(wide))
    expect(within(wide).getByRole("radiogroup", { name: "走勢區間" })).not.toContainElement(toggle(wide))
  })

  it("舊版後端（沒有資產組成的欄位）沒有這個開關", async () => {
    const real = api.getPerformance.bind(api)
    vi.spyOn(api, "getPerformance").mockImplementation(async (q) => {
      const { composition: _c, fund_rank: _f, ...rest } = await real(q)
      return rest
    })
    renderApp("/")
    const region = await trend()
    expect(within(region).queryByRole("switch")).toBeNull()
  })
})
