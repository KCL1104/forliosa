import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Performance, PerformanceComposition, PerformancePoint } from "@/api/types"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"

/**
 * 資產組成 v2：本金 ≤ 0（賣股票收到的錢已經和買股票花的一樣多或更多）寫「本金已收回」（使用者 2026-11-19，取代方案 D）。
 * 圖例、滑過的讀數、圖的說明不寫金額；價差照實寫（總資產－本金）；本金線畫在 0、塗色從 0 塗到總資產；0 在圖外時縱軸的記號寫「0」。
 * 每月表格的本金增減照舊寫金額。
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
  useLedgerPrefs.setState({ columns: DEFAULT_COLUMNS, showTrend: true, pinned: [], showClosed: false, trendRange: "ALL", showInvested: true })
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
const trend = () => screen.findByRole("region", { name: "總資產走勢" }, T)
const chart = (region: HTMLElement) => within(region).getByRole("group", { name: /^總資產走勢：/ })
const img = (region: HTMLElement) => within(region).getByRole("img")
const legend = (region: HTMLElement, item: "invested" | "gain" | "dividend" | "total") => region.querySelector<HTMLElement>(`[data-legend="${item}"]`)
const live = (region: HTMLElement) => region.querySelector('[aria-live="polite"]')!.textContent
/** 縱軸的刻度字 */
const yTicks = (region: HTMLElement) => [...img(region).querySelectorAll<SVGTextElement>("text[text-anchor='end'][dominant-baseline='central']")]
/** 本金線每一個收盤的高度（階梯線：起點「M x y」，之後每一天「H x V y」） */
const investedYs = (region: HTMLElement) => {
  const d = region.querySelector('[data-series="invested"]')!.getAttribute("d")!
  return [Number(/^M[\d.]+ ([\d.]+)/.exec(d)![1]), ...[...d.matchAll(/V([\d.]+)/g)].map((m) => Number(m[1]))]
}
/** 塗色每一個頂點的高度 */
const bandYs = (region: HTMLElement) =>
  [...region.querySelectorAll("[data-band]")].flatMap((b) => [...b.getAttribute("d")!.matchAll(/[ML][\d.-]+ ([\d.-]+)/g)].map((m) => Number(m[1])))

const nineDays = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
const comp0: PerformanceComposition = { dividends: [], estimated: [], months: [], months_estimated: 0 }
/** 九個收盤的序列：每一天的總資產與本金 */
const seriesOf = (rows: [number, number][]): PerformancePoint[] =>
  nineDays.map((t, i) => ({ t, market_value: rows[i]![0], net_invested: rows[i]![1], twr_index: 1 + i * 0.002, benchmark_index: null }))
async function withSeries(series: PerformancePoint[], composition: PerformanceComposition = comp0) {
  const real = api.getPerformance.bind(api)
  const realSummary = api.getPortfolioSummary.bind(api)
  vi.spyOn(api, "getPortfolioSummary").mockImplementation(async (a) => ({ ...(await realSummary(a)), dividend_income: 0 }))
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => ({ ...(await real(q)), series, notes: [], reference_until: null, composition }) satisfies Performance)
}
/** 總資產 50 萬起每天多 1,000，本金固定：縱軸只跟總資產（本金線在圖外，下面） */
const flat = (p: number) => seriesOf(nineDays.map((_, i) => [500_000 + i * 1_000, p]))

/**
 * 有買有賣、本金在正負之間來回（每一筆都對得起來：買賣的錢同時加減在總資產與本金上，賣的不超過持股）：
 * 11/4 賣 25 萬（本金 20 萬 → −5 萬）、11/9 買 10 萬（→ 5 萬）、11/11 賣 16 萬（→ −11 萬）
 */
const crossing: [number, number][] = [
  [300_000, 200_000],
  [310_000, 200_000],
  [60_000, -50_000],
  [62_000, -50_000],
  [64_000, -50_000],
  [164_000, 50_000],
  [170_000, 50_000],
  [10_000, -110_000],
  [11_000, -110_000],
]

describe("本金已收回（本金 ≤ 0）", { timeout: 20_000 }, () => {
  it.each([
    ["剛好是 0", 0, "+NT$508,000", "NT$508,000"],
    ["稍微負的（−1 元）", -1, "+NT$508,001", "NT$508,001"],
    ["很負的（−500 萬）", -5_000_000, "+NT$5,508,000", "NT$5,508,000"],
  ])("本金%s：圖例寫「本金已收回」、不寫金額；價差照實寫（總資產－本金）；縱軸的記號寫「0」（本金線畫在那裡）；圖的說明念為什麼與本金線畫在 0", async (_, p, gain, gainSpeech) => {
    await withSeries(flat(p))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "invested")).not.toBeNull(), T)
    expect(legend(region, "invested")!.textContent).toBe("本金已收回")
    expect(legend(region, "gain")!.textContent).toBe(`價差 ${gain}`)
    // 本金線畫在 0，0 在圖的下面（縱軸只跟總資產）：縱軸的記號寫「0」，不寫負的金額
    const note = region.querySelector("[data-off-chart]")!
    expect(note.textContent).toBe("0")
    expect(note.getAttribute("data-off-chart")).toBe("below")
    // 縱軸不會到負的
    expect(yTicks(region).some((t) => t.textContent!.startsWith("−"))).toBe(false)
    expect(img(region).getAttribute("aria-label")).toMatch(
      new RegExp(
        `，資產組成：最後一天本金已收回，價差賺 ${gainSpeech.replace("$", "\\$")}。本金是買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢；賣股票收到的錢已經和買股票花的一樣多或更多，所以本金線畫在 0，在圖的下方$`,
      ),
    )
    expect(region.textContent).not.toMatch(/本金 −|−NT\$/)
  })

  it("本金 1 元（還沒收回）：照舊寫金額", async () => {
    await withSeries(flat(1))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "invested")).not.toBeNull(), T)
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$1")
    expect(region.querySelector("[data-off-chart]")!.textContent).toBe("1")
    expect(region.textContent).not.toMatch(/本金已收回/)
  })

  it("本金在正負之間來回：本金線在收回的日子畫在 0（和縱軸的 0 一樣高）；塗色的下緣不低於 0", async () => {
    await withSeries(seriesOf(crossing))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(region.querySelector('[data-series="invested"]')).not.toBeNull(), T)
    // 兩條線都放得下（縱軸從 0 起）：0 是一條刻度
    const zero = yTicks(region).find((t) => t.textContent === "0")!
    const y0 = Number(zero.getAttribute("y"))
    const ys = investedYs(region)
    expect(ys).toHaveLength(9)
    crossing.forEach(([, p], i) => {
      if (p <= 0) expect(ys[i], `第 ${i} 天`).toBeCloseTo(y0, 0)
      else expect(ys[i]!, `第 ${i} 天`).toBeLessThan(y0 - 5)
    })
    // 塗色：每一個頂點都在 0 以上（畫面上 y 越大越低）；本金是負的那幾天不會塗到 0 下面
    const bands = bandYs(region)
    expect(bands.length).toBeGreaterThan(0)
    expect(Math.max(...bands)).toBeLessThanOrEqual(y0 + 0.1)
    expect(region.querySelector('[data-band="loss"]')).toBeNull()
    // 圖例（沒有滑過）：最後一天收回了
    expect(legend(region, "invested")!.textContent).toBe("本金已收回")
    expect(legend(region, "gain")!.textContent).toBe("價差 +NT$121,000")
  })

  it("滑過（手機的圖例）：每一天各自換「本金 NT$…」與「本金已收回」；價差照實寫；報讀器念的也一樣", async () => {
    await withSeries(seriesOf(crossing))
    renderApp("/")
    const region = await trend()
    const g = await waitFor(() => chart(region), T)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    const expected = ["本金 NT$200,000", "本金 NT$200,000", "本金已收回", "本金已收回", "本金已收回", "本金 NT$50,000", "本金 NT$50,000", "本金已收回", "本金已收回"]
    const gains = [100_000, 110_000, 110_000, 112_000, 114_000, 114_000, 120_000, 120_000, 121_000]
    for (let i = 0; i < 9; i++) {
      if (i > 0) fireEvent.keyDown(g, { key: "ArrowRight" })
      expect(legend(region, "invested")!.textContent, `第 ${i} 天`).toBe(expected[i])
      expect(legend(region, "gain")!.textContent, `第 ${i} 天`).toBe(`價差 +NT$${gains[i]!.toLocaleString("en-US")}`)
      const money = crossing[i]![1] > 0 ? `本金 NT\\$${crossing[i]![1].toLocaleString("en-US")}` : "本金已收回"
      expect(live(region), `第 ${i} 天`).toMatch(new RegExp(`，總資產 NT\\$${crossing[i]![0].toLocaleString("en-US")}，${money}，價差賺 NT\\$${gains[i]!.toLocaleString("en-US")}，報酬`))
    }
    // 11/4（第 2 天）：念的是「本金已收回」，不念負的金額
    fireEvent.keyDown(g, { key: "Home" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    expect(live(region)).toMatch(/^11\/4（三）收盤，總資產 NT\$60,000，本金已收回，價差賺 NT\$110,000，報酬/)
    // 手機圖例的第一欄：撐寬用的有本金的金額、「本金已收回」與價差（一樣寬的金額取第一個）
    const sizers = [...region.querySelectorAll<HTMLElement>("[data-legend-col] [data-legend-sizer]")].map((s) => s.textContent)
    expect(sizers).toEqual(["本金 NT$200,000", "本金已收回", "價差 +NT$100,000"])
  })

  it("滑過（寬的時候，圖例那一列）：收回的那一天寫「本金已收回」「價差 +NT$…」，讀數第二行是報酬", async () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000)
    await withSeries(seriesOf(crossing))
    renderApp("/")
    const region = await trend()
    const readout = region.querySelector<HTMLElement>("[data-readout]")!
    await waitFor(() => expect(region.querySelector("[data-legend-row]")).not.toBeNull(), T)
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    const second = () => readout.querySelectorAll(":scope > p")[1]!.textContent
    const shown = () => [legend(region, "invested")!.textContent, legend(region, "gain")!.textContent]
    expect(shown()).toEqual(["本金 NT$200,000", "價差 +NT$100,000"])
    expect(second()).toMatch(/^報酬 /)
    fireEvent.keyDown(g, { key: "ArrowRight" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    expect(shown()).toEqual(["本金已收回", "價差 +NT$110,000"])
    fireEvent.keyDown(g, { key: "ArrowRight" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    expect(shown()).toEqual(["本金 NT$50,000", "價差 +NT$114,000"])
  })

  it("倒 U（以前圖裡兩個角都放不下）：縱軸的記號照樣在縱軸那一欄（「0」）；圖例就是「本金已收回」（不加在哪一邊）；手機圖例照兩行兩欄", async () => {
    const arch = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => [Math.round(4_000_000 + 520_000 * Math.sin((Math.PI * i) / 8)), -100_000] as [number, number])
    await withSeries(seriesOf(arch))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "invested")).not.toBeNull(), T)
    expect(region.querySelector("[data-off-chart]")!.textContent).toBe("0")
    expect(legend(region, "invested")!.textContent).toBe("本金已收回")
    expect(region.querySelector("[data-legend-col]")).not.toBeNull()
    expect(img(region).getAttribute("aria-label")).toMatch(/，資產組成：最後一天本金已收回，價差賺 NT\$4,100,000。.*所以本金線畫在 0，在圖的下方$/)
  })

  it("隱私模式：還是寫「本金已收回」（沒有金額），縱軸的記號只有箭頭；圖的說明不念金額", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    await withSeries(flat(-200_000))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "invested")).not.toBeNull(), T)
    expect(legend(region, "invested")!.textContent).toBe("本金已收回")
    expect(legend(region, "gain")!.textContent).not.toMatch(/NT\$/)
    expect(region.querySelector("[data-off-chart]")!.textContent).toBe("")
    const label = img(region).getAttribute("aria-label")!
    expect(label).not.toMatch(/NT\$|萬/)
    expect(label).toMatch(/，資產組成：最後一天價差賺，本金已收回。本金是買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢；賣股票收到的錢已經和買股票花的一樣多或更多，所以本金線畫在 0，在圖的下方$/)
    // 滑過也一樣
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    expect(live(region)).toMatch(/，總資產 已隱藏，本金已收回，價差賺 已隱藏，/)
  })

  it("本金開關關掉：沒有本金那一層，也沒有「本金已收回」", async () => {
    act(() => useLedgerPrefs.setState({ showInvested: false }))
    await withSeries(flat(-200_000))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "total")).not.toBeNull(), T)
    expect(region.textContent).not.toMatch(/本金已收回/)
    expect(img(region).getAttribute("aria-label")).not.toMatch(/本金/)
  })

  it("每月表格的本金增減照舊寫金額（本金收回的那個月是「−NT$…」）", async () => {
    const month = { month: "2026-11", from: "2026-11-02", to: "2026-11-12", whole: false, flows: -250_000, pnl: 1_000, twr: 0.01, benchmark_twr: null }
    await withSeries(seriesOf(crossing), { ...comp0, months: [month] })
    renderApp("/?view=performance")
    const table = await screen.findByRole("table", { name: /每個月的本金增減/ }, T)
    expect(table.textContent).toContain("−NT$250,000")
    expect(table.textContent).not.toMatch(/本金已收回/)
  })
})
