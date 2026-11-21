import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Performance, PerformancePoint } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"

/**
 * 資產組成原型：獨立審查之後的修正（docs/proposals/asset-composition.md），每一條一個測試。
 * 編號是審查意見的編號；其他的在 asset-composition.test.tsx、buy-date-picker.test.tsx 與 lib／positions 的單元測試。
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
  act(() => useViewAs.setState({ target: null }))
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
/** 圖下面那一句拆解（使用者 2026-11-19：只要圖，不放）：「這段期間總資產多了…」「總資產 NT$…＝本金…」 */
const sentence = (region: HTMLElement) => within(region).queryByText(/^這段期間總資產|^總資產\s*(NT\$[\d,]+)?＝/)
const legend = (region: HTMLElement, item: "invested" | "gain" | "dividend" | "total") => region.querySelector<HTMLElement>(`[data-legend="${item}"]`)

/** 改掉績效的回應（測極端情況） */
async function withPerformance(patch: (p: Performance) => Performance) {
  const real = api.getPerformance.bind(api)
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => patch(await real(q)))
}
/** 主數字的 dividend_income 設成 0（自己編的序列沒有股利） */
async function withoutLifetimeDividends() {
  const real = api.getPortfolioSummary.bind(api)
  return vi.spyOn(api, "getPortfolioSummary").mockImplementation(async (a) => ({ ...(await real(a)), dividend_income: 0 }))
}

/** 九個收盤（11/2–11/12）的序列 */
const nineDays = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
const comp0 = { dividends: [], estimated: [], months: [], months_estimated: 0 }
const seriesOf = (f: (i: number) => Pick<PerformancePoint, "market_value" | "net_invested">): PerformancePoint[] =>
  nineDays.map((t, i) => ({ t, ...f(i), twr_index: 1 + i * 0.002, benchmark_index: null }))

describe("審查後的修正：首頁走勢", { timeout: 20_000 }, () => {
  it("#2 本金是負的（賣股票收到的錢比買的多）：v2 寫「本金已收回」（使用者 2026-11-19），不寫負的金額；價差照實寫（總資產－本金）；為什麼念在圖的說明裡", async () => {
    await withPerformance((p) => ({ ...p, series: seriesOf((i) => ({ market_value: 500_000 + i * 1_000, net_invested: -200_000 })), notes: [], reference_until: null, composition: comp0 }))
    await withoutLifetimeDividends()
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "invested")).not.toBeNull(), T)
    expect(legend(region, "invested")!.textContent).toBe("本金已收回")
    expect(legend(region, "gain")!.textContent).toBe("價差 +NT$708,000")
    // v2 圖下面沒有句子（使用者只要圖）
    expect(sentence(region)).toBeNull()
    // 本金線畫在 0、0 離總資產太遠：縱軸只跟總資產，縱軸的記號寫「0」（本金線畫在那裡）
    expect(region.querySelector("[data-off-chart]")!.textContent).toBe("0")
    expect(within(region).getByRole("img").getAttribute("aria-label")).toMatch(
      /，資產組成：最後一天本金已收回，價差賺 NT\$708,000。本金是買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢；賣股票收到的錢已經和買股票花的一樣多或更多，所以本金線畫在 0，在圖的下方$/,
    )
  })

  it("#4 手機（窄）：圖例兩行兩欄、金額寫完整（10 位數也不截斷）；第一欄撐到這段期間最寬的金額（第二審 6：滑過時不跳）", async () => {
    await withPerformance((p) => ({ ...p, series: seriesOf((i) => ({ market_value: 1_234_567_890 + i * 10_000_000, net_invested: 987_654_321 })), notes: [], reference_until: null, composition: comp0 }))
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    const grid = await waitFor(() => region.querySelector<HTMLElement>("[data-legend-grid]")!, T)
    expect(grid).not.toHaveClass("overflow-hidden")
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$987,654,321")
    expect(legend(region, "gain")!.textContent).toBe("價差 +NT$326,913,569")
    for (const item of grid.querySelectorAll("[data-legend]")) expect(item).toHaveClass("whitespace-nowrap")
    // 第一欄：本金、價差，加上兩個看不到、不佔高度的撐寬用的（這段期間最寬的本金與價差）
    const col = grid.querySelector<HTMLElement>("[data-legend-col]")!
    expect([...col.querySelectorAll("[data-legend]")].map((c) => c.getAttribute("data-legend"))).toEqual(["invested", "gain"])
    const sizers = [...col.querySelectorAll<HTMLElement>("[data-legend-sizer]")]
    // 一樣寬的金額取第一個（數字是等寬字）
    expect(sizers.map((s) => s.textContent)).toEqual(["本金 NT$987,654,321", "價差 +NT$246,913,569"])
    for (const s of sizers) {
      expect(s).toHaveClass("invisible", "h-0", "overflow-hidden")
      expect(s).toHaveAttribute("aria-hidden", "true")
    }
  })

  it("#5 區間比資料長（1 年、只有 9 個收盤）：錢的拆解和報酬同一個起點（從 0 算起），和「全部」一模一樣", async () => {
    await withPerformance((p) => ({
      ...p, series: seriesOf((i) => ({ market_value: 100_000 + i * 1_000 + (i > 4 ? 50_000 : 0), net_invested: 97_000 + (i > 4 ? 50_000 : 0) })),
      notes: [], reference_until: null, composition: comp0,
    }))
    await withoutLifetimeDividends()
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "gain")).not.toBeNull(), T)
    expect(within(region).getByText(/^只有 /)).toBeInTheDocument()
    // 從 0 起算（和「全部」一樣）：圖例寫「價差」、不是「目前價差」
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$147,000")
    expect(legend(region, "gain")!.textContent).toBe("價差 +NT$11,000")
    const oneYearLegend = region.querySelector("[data-legend-grid]")!.textContent
    const speech = (s: string) => s.replace(/^近 1 年，只有 [^，]+ 的資料，|^[^，]+ 起，/, "")
    const oneYearSpeech = speech(within(region).getByRole("img").getAttribute("aria-label")!)
    await userEvent.click(within(region).getByRole("radio", { name: "全部" }))
    expect(region.querySelector("[data-legend-grid]")!.textContent).toBe(oneYearLegend)
    expect(speech(within(region).getByRole("img").getAttribute("aria-label")!)).toBe(oneYearSpeech)
  })

  it("#7 週末領的股利：記號與滑過的讀數算在下一個收盤日（星期一）", async () => {
    // 11/7 是星期六 → 11/9（一）
    await withPerformance((p) => ({
      ...p, series: seriesOf((i) => ({ market_value: 1_000_000 + i * 1_000, net_invested: 900_000 })), notes: [], reference_until: null,
      composition: { ...comp0, dividends: [{ t: "2026-11-07", amount: 3_000 }] },
    }))
    act(() => useLedgerPrefs.setState({ trendRange: "5D" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(region.querySelectorAll("[data-dividend-mark]")).toHaveLength(1), T)
    expect(within(region).getByText("股利")).toBeInTheDocument()
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    for (let i = 0; i < 9 && !region.querySelector("[data-dividend]"); i++) fireEvent.keyDown(g, { key: "ArrowLeft" })
    expect(within(region).getByText(/^11\/9（一）收盤$/)).toBeInTheDocument()
    expect(region.querySelector("[data-dividend]")!.textContent).toBe("領股利 NT$3,000")
  })

  it("#3 手機（窄）：估計那一段裡領股利的那一天，「估計」自己一格在日期前面、股利放第二行——第一行只剩日期會被截斷", async () => {
    await withPerformance((p) => ({
      ...p, series: seriesOf((i) => ({ market_value: 1_000_000 + i * 1_000, net_invested: 900_000 })), notes: [], reference_until: null,
      composition: { ...comp0, estimated: [{ from: "2026-11-02", until: "2026-11-12" }], dividends: [{ t: "2026-11-09", amount: 3_000 }] },
    }))
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    const readout = await waitFor(() => region.querySelector<HTMLElement>("[data-readout]")!, T)
    // v2 的手機：讀數兩行（日期與總資產、報酬與股利；和 main 一樣高）＋下面兩行圖例，滑過時高度不變
    expect(readout).toHaveClass("h-11")
    // 至少兩行（2026-11-21：托盤裡 320px、金額上千億時第二欄換到下一行，不撐出畫面；高度照最寬的金額定，滑過時不跳）
    expect(region.querySelector("[data-legend-grid]")).toHaveClass("min-h-10")
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    for (let i = 0; i < 9 && !region.querySelector("[data-dividend]"); i++) fireEvent.keyDown(g, { key: "ArrowLeft" })
    expect(readout).toHaveClass("h-11")
    const [first, second] = [...readout.querySelectorAll(":scope > p")]
    expect(first!.querySelector("[data-estimated-day]")).toHaveClass("shrink-0")
    expect(first!.firstElementChild).toBe(first!.querySelector("[data-estimated-day]"))
    expect(first!.querySelector("[data-dividend]")).toBeNull()
    expect(second!.querySelector("[data-dividend]")!.textContent).toBe("領股利 NT$3,000")
    // 圖例換成那一天的本金與價差
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$900,000")
    expect(legend(region, "gain")!.textContent).toMatch(/^價差 \+NT\$10\d,000$/)
    expect(legend(region, "dividend")!.textContent).toBe("股利")
  })

  it("#8 基準收盤那天領的股利：不算進區間，記號、圖例、滑過的讀數都不放；「全部」從 0 起算時才算", async () => {
    // 5 日：基準收盤是 11/5（最後 6 點的第一點）
    await withPerformance((p) => ({
      ...p, series: seriesOf((i) => ({ market_value: 1_000_000 + i * 1_000, net_invested: 900_000 })), notes: [], reference_until: null,
      composition: { ...comp0, dividends: [{ t: "2026-11-05", amount: 3_000 }] },
    }))
    act(() => useLedgerPrefs.setState({ trendRange: "5D" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "gain")).not.toBeNull(), T)
    expect(region.querySelector("[data-dividend-mark]")).toBeNull()
    expect(within(region).queryByText("股利")).toBeNull()
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    expect(within(region).getByText(/^11\/5（四）收盤$/)).toBeInTheDocument()
    expect(region.querySelector("[data-dividend]")).toBeNull()
    await userEvent.click(within(region).getByRole("radio", { name: "全部" }))
    expect(region.querySelectorAll("[data-dividend-mark]")).toHaveLength(1)
  })
})

describe("審查後的修正：績效分段與查看別人的資產", { timeout: 20_000 }, () => {
  it("#9＋#11 區間碰到估計那一段：指標下面一行（13px 淡墨）寫哪幾天，和首頁走勢那一行同一個規則（含基準收盤）；1 月碰不到就沒有", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", {}, T)
    const line = await waitFor(() => document.querySelector<HTMLElement>("[data-metrics-estimate]")!, T)
    expect(line.textContent).toBe("這些數字含 2025/11/11 – 2025/11/28，那段期間用估計的買入日計算。")
    expect(line).toHaveClass("text-sm", "text-ink-2")
    const region = await trend()
    expect(within(region).getByText("2025/11/11 – 2025/11/28 用估計的買入日計算")).toBeInTheDocument()
    cleanup()
    act(() => useLedgerPrefs.setState({ trendRange: "1M" }))
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", {}, T)
    expect(document.querySelector("[data-metrics-estimate]")).toBeNull()
  })

  it("分兩次匯入（估計兩段）：首頁走勢兩條括線、兩段細線，下面一行列出兩段；績效分段那一行也列兩段", async () => {
    await withPerformance((p) => (p.composition ? { ...p, composition: { ...p.composition, estimated: [...p.composition.estimated, { from: "2026-09-01", until: "2026-11-11" }] } } : p))
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", {}, T)
    // 等到回應換成兩段的那一份（第一次畫的可能還是上一份）
    const line = await waitFor(() => {
      const el = document.querySelector<HTMLElement>("[data-metrics-estimate]")
      expect(el?.textContent).toBe("這些數字含 2025/11/11 – 2025/11/28、2026/9/1 – 2026/11/11，那幾段期間用估計的買入日計算。")
      return el!
    }, T)
    expect(line).toHaveClass("text-sm", "text-ink-2")
    const region = await trend()
    expect(within(region).getByText("2025/11/11 – 2025/11/28、2026/9/1 – 2026/11/11 用估計的買入日計算")).toBeInTheDocument()
    expect(region.querySelectorAll("[data-bracket]")).toHaveLength(2)
    expect(region.querySelectorAll("[data-estimated]")).toHaveLength(2)
    // 兩段之間（2025/12 – 2026/8）是一般的粗線
    expect(region.querySelectorAll('[data-series="total"] path:not([data-estimated])').length).toBeGreaterThanOrEqual(1)
  })

  it("#12 查看別人的資產：走勢的資產組成、每月拆解、基金排名、估計的說明、買入日的標記都不放（先只給自己看）", async () => {
    act(() =>
      useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "accounts", accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }] }),
    )
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", {}, T)
    const region = await trend()
    expect(region.querySelector("[data-bands]")).toBeNull()
    expect(region.querySelector("[data-legend]")).toBeNull()
    // 「本金」開關也不放（只給自己看）
    expect(within(region).queryByRole("switch")).toBeNull()
    expect(sentence(region)).toBeNull()
    expect(region.querySelector("[data-dividend-mark]")).toBeNull()
    expect(screen.queryByText("每月報酬率")).toBeNull()
    expect(document.querySelector("[data-fund-rank]")).toBeNull()
    expect(document.querySelector("[data-metrics-estimate]")).toBeNull()
  })

  it("#12（第二次審查 5）查看別人的資產：績效指標的「含估計的買入日，不年化」也不寫（回應裡有估計的那一段也一樣）", async () => {
    // 爸爸的帳本沒有估計的買進：把估計的那一段塞進回應（後端漏擋時也不能露出來）
    await withPerformance((p) => ({ ...p, xirr: null, composition: { ...(p.composition ?? comp0), estimated: [{ from: "2020-01-01", until: "2026-11-12" }] } }))
    act(() =>
      useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "accounts", accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }] }),
    )
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", {}, T)
    expect(screen.queryByText("含估計的買入日，不年化")).toBeNull()
    expect(screen.getByText("期間太短或現金流不足，無法計算")).toBeInTheDocument()
    expect(document.querySelector("[data-metrics-estimate]")).toBeNull()
    // 自己的帳本（同一個回應）：照寫
    cleanup()
    act(() => useViewAs.setState({ target: null }))
    renderApp("/?view=performance")
    expect(await screen.findByText("含估計的買入日，不年化", {}, T)).toBeInTheDocument()
  })

  it("#12 查看別人的資產：持倉展開裡估計的那一筆不標「估計」（同一個元件，換成有估計的交易來測）", async () => {
    const lot = (await api.listTransactions({ symbol: "6488.TWO", type: "buy", limit: 10 })).items[0]!
    expect(lot.date_basis).toBe("estimated")
    act(() =>
      useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "accounts", accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }] }),
    )
    // 爸爸的帳本沒有估計的買進：把自己的那一筆塞進爸爸的回應，看查看模式會不會標
    const real = api.listTransactions.bind(api)
    vi.spyOn(api, "listTransactions").mockImplementation(async (q) => {
      const page = await real(q)
      return { ...page, items: page.items.map((t) => (t.type === "buy" ? { ...t, date_basis: "estimated" as const, estimated_date: t.trade_date, imported_on: "2025-11-29" } : t)) }
    })
    renderApp("/")
    const table = await screen.findByRole("table", { name: "持倉" }, T)
    const expandButtons = await within(table).findAllByRole("button", { name: /^展開.+的每一筆買賣$/ }, T)
    await userEvent.setup({ pointerEventsCheck: 0 }).click(expandButtons[0]!)
    await within(table).findAllByRole("listitem", {}, T)
    expect(within(table).queryByText("估計")).toBeNull()
  })
})
