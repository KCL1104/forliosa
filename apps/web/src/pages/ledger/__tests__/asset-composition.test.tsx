import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { toast, Toaster } from "sonner"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Performance, PerformancePoint, Transaction } from "@/api/types"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { BuyDatePicker } from "../BuyDatePicker"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"

/**
 * 資產組成（原型；docs/proposals/asset-composition.md）：
 * A 首頁走勢（v2：一張圖，本金線＋賺虧塗色；圖下面沒有拆解的句子）；B 股利的記號；C 估計的那一段；D 每月報酬率；E 買入日的標記與選日期；G 贏過幾成的基金。
 * 示範帳本：2025/12/1 匯入過庫存，VOO、環球晶的買入日是估計的，聯發科找不到（用匯入那天），台積電 8/6 那一筆是自己選的。
 * 後端沒有這些欄位時（舊版），每一樣都不出現、畫面和以前一樣。
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
  toast.dismiss()
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
      <Toaster />
    </QueryClientProvider>,
  )
}
const trend = () => screen.findByRole("region", { name: "總資產走勢" }, T)
const chart = (region: HTMLElement) => within(region).getByRole("group", { name: /^總資產走勢：/ })
/** 圖下面那一句拆解（使用者 2026-11-19：只要圖，不放）：「這段期間總資產多了…」「總資產 NT$…＝本金…」 */
const sentence = (region: HTMLElement) => within(region).queryByText(/^這段期間總資產|^總資產\s*(NT\$[\d,]+)?＝/)
const legend = (region: HTMLElement, item: "invested" | "gain" | "dividend" | "total") => region.querySelector<HTMLElement>(`[data-legend="${item}"]`)
/** 「NT$1,234」「−NT$1,234」「+NT$1,234」→ 數字 */
const money = (s: string) => Number(s.replace(/[^\d−-]/g, "").replace("−", "-"))

/** 舊版後端：績效沒有 composition、fund_rank */
async function withoutComposition() {
  const real = api.getPerformance.bind(api)
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => {
    const { composition: _c, fund_rank: _f, ...rest } = await real(q)
    return rest
  })
}
/** 改掉「全部」的序列與組成（測極端情況） */
async function withPerformance(patch: (p: Performance) => Performance) {
  const real = api.getPerformance.bind(api)
  return vi.spyOn(api, "getPerformance").mockImplementation(async (q) => patch(await real(q)))
}

describe("A＋B＋C：首頁走勢的資產組成", { timeout: 20_000 }, () => {
  it("區間（3 個月）：圖下面沒有拆解的句子（使用者只要圖）；圖例的價差只有名字「目前價差」（2026-11-22：主數字已經有總損益），滑過時也一樣；本金＋價差＝總資產（圖的說明念）", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "3M" }))
    renderApp("/")
    const region = await trend()
    expect(sentence(region)).toBeNull()
    expect(region.querySelector("[data-bands]")).not.toBeNull()
    expect(legend(region, "gain")!.textContent).toBe("目前價差")
    // 最後一天：本金＋價差＝總資產（圖的說明念的「到 NT$…」與資產組成）
    const label = within(region).getByRole("img").getAttribute("aria-label")!
    const to = /總資產從 NT\$[\d,]+ 到 (NT\$[\d,]+)/.exec(label)![1]!
    const gain = /價差賺 (NT\$[\d,]+)/.exec(label)![1]!
    expect(money(legend(region, "invested")!.textContent!) + money(gain)).toBe(money(to))
    // 滑過：圖例的本金換成那一天的，價差照樣只有名字；本金＋價差＝讀數的總資產（報讀器念那一天的價差）
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    fireEvent.keyDown(g, { key: "ArrowRight" })
    expect(legend(region, "gain")!.textContent).toBe("目前價差")
    const shown = region.querySelector("[data-readout] p .font-semibold")!.textContent!
    const dayGain = /價差賺 (NT\$[\d,]+)/.exec(region.querySelector('[aria-live="polite"]')!.textContent!)![1]!
    expect(money(legend(region, "invested")!.textContent!) + money(dayGain)).toBe(money(shown))
  })

  it("「全部」：圖例寫「價差」（不寫「目前」）；本金＋價差＝主數字的總資產，價差＋全部領過的股利＝主數字的「總損益（含股利）」；畫面上沒有「賺的」；圖的說明念資產組成、本金只算還在股票裡的錢", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    expect(sentence(region)).toBeNull()
    const invested = /^本金 (NT\$[\d,]+)$/.exec(legend(region, "invested")!.textContent!)![1]!
    // 價差只有名字（2026-11-22）：金額從圖的說明讀
    expect(legend(region, "gain")!.textContent).toBe("價差")
    const profit = /價差賺 (NT\$[\d,]+)。/.exec(within(region).getByRole("img").getAttribute("aria-label")!)![1]!
    // 主數字寫「總損益（含股利）」，圖例不再有第二個讀成「賺多少」的「賺的」（2026-11-21 評論），也沒有第二個金額（2026-11-22）
    expect(region.querySelector("[data-legend-row], [data-legend-grid]")!.textContent).not.toMatch(/賺的|虧的/)
    expect(legend(region, "gain")!.textContent).not.toMatch(/NT\$/)
    expect(legend(region, "total")!.textContent).toBe("總資產")
    const summary = await api.getPortfolioSummary()
    expect(money(invested) + money(profit)).toBe(Math.round(summary.market_value))
    expect(money(profit) + Math.round(summary.dividend_income)).toBe(Math.round(summary.total_pnl))
    // 決定 1：「資產組成」念在圖的說明裡；決定 5（只算還在股票裡的錢）畫面上不寫、念在這裡
    expect(within(region).queryByText(/只算還在股票裡的錢/)).toBeNull()
    expect(within(region).getByRole("img").getAttribute("aria-label")).toMatch(
      new RegExp(`，資產組成：最後一天本金 ${invested.replace("$", "\\$")}，價差賺 ${profit.replace("$", "\\$")}。本金是買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢$`),
    )
  })

  it("估計的那一段：細線、上面標「估計」、按鈕下面一行寫是哪幾天；區間碰不到時都沒有", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    expect(region.querySelector("[data-estimated]")).not.toBeNull()
    expect(region.querySelector("[data-bracket]")).not.toBeNull()
    expect(within(region).getByText("估計")).toBeInTheDocument()
    expect(within(region).getByText("2024/7/29 – 2025/11/28 用估計的買入日計算")).toBeInTheDocument()
    // 不用虛線（虛線是 AI 的草稿與比較基準）
    expect(region.querySelector("[stroke-dasharray]")).toBeNull()
    // 滑到估計的那一天：讀數第一行多一個「估計」標記，自己一格、不會被截斷（截斷的只有日期）
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "Home" })
    // 序列從 2024/7/1 開始，估計的那一段從 7/29 起
    for (let i = 0; i < 40 && !region.querySelector("[data-estimated-day]"); i++) fireEvent.keyDown(g, { key: "ArrowRight" })
    const tag = region.querySelector<HTMLElement>("[data-estimated-day]")!
    expect(tag.textContent).toBe("估計")
    expect(tag).toHaveClass("shrink-0")
    const dayText = within(region).getByText(/^2024\/7\/29（一）收盤$/)
    expect(dayText).toHaveClass("min-w-0", "truncate")
    expect(dayText.textContent).not.toContain("估計")
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toMatch(/^2024\/7\/29（一）收盤（估計），/)
    // 1 年：只碰到頭上一小段——含基準收盤（11/11，區間報酬的分母），和績效分段指標下面那一行同一個規則
    await userEvent.click(within(region).getByRole("radio", { name: "1年" }))
    expect(within(region).getByText("2025/11/11 – 2025/11/28 用估計的買入日計算")).toBeInTheDocument()
    await userEvent.click(within(region).getByRole("radio", { name: "1月" }))
    expect(region.querySelector("[data-estimated]")).toBeNull()
    expect(within(region).queryByText(/用估計的買入日計算/)).toBeNull()
    expect(within(region).queryByText("估計")).toBeNull()
  })

  it("股利：領到的日子在橫軸上一個記號＋圖例；鍵盤移到那一天時讀數寫「領股利」，報讀器也念", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "3M" }))
    renderApp("/")
    const region = await trend()
    expect(region.querySelectorAll("[data-dividend-mark]").length).toBeGreaterThan(2)
    expect(within(region).getByText("股利")).toBeInTheDocument()
    const g = chart(region)
    act(() => g.focus())
    fireEvent.keyDown(g, { key: "End" })
    for (let i = 0; i < 70 && !region.querySelector("[data-dividend]"); i++) fireEvent.keyDown(g, { key: "ArrowLeft" })
    expect(region.querySelector("[data-dividend]")!.textContent).toMatch(/^領股利 NT\$[\d,]+$/)
    expect(region.querySelector('[aria-live="polite"]')!.textContent).toMatch(/，領股利 NT\$[\d,]+$/)
  })

  it("沒有股利：沒有記號、沒有圖例", async () => {
    await withPerformance((p) => (p.composition ? { ...p, composition: { ...p.composition, dividends: [] } } : p))
    act(() => useLedgerPrefs.setState({ trendRange: "3M" }))
    renderApp("/")
    const region = await trend()
    await waitFor(() => expect(legend(region, "gain")).not.toBeNull(), T)
    expect(region.querySelector("[data-dividend-mark]")).toBeNull()
    expect(within(region).queryByText("股利")).toBeNull()
  })

  it("虧損、整段都是估計的：圖例「價差」（跌的顏色的色塊，金額念在圖的說明）、整條是細線、只塗虧的", async () => {
    const days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
    const series: PerformancePoint[] = days.map((t, i) => ({ t, market_value: 1_000_000 - i * 20_000, net_invested: 1_050_000, twr_index: 1 - i * 0.02, benchmark_index: null }))
    await withPerformance((p) => ({ ...p, series, notes: [], reference_until: null, composition: { dividends: [], estimated: [{ from: "2026-01-01", until: "2026-11-12" }], months: [], months_estimated: 1 } }))
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    expect(sentence(region)).toBeNull()
    expect(legend(region, "invested")!.textContent).toBe("本金 NT$1,050,000")
    expect(within(region).getByText("11/2 – 11/12 用估計的買入日計算")).toBeInTheDocument()
    // 整條都是估計的：沒有一般的粗線；塗色照常（只有虧的）
    expect(region.querySelectorAll('[data-series="total"] path')).toHaveLength(1)
    expect(region.querySelector('[data-band="loss"]')).not.toBeNull()
    expect(region.querySelector('[data-band="gain"]')).toBeNull()
    expect(legend(region, "gain")!.textContent).toBe("價差")
    expect(legend(region, "gain")!.querySelector(".bg-fall-tint")).not.toBeNull()
    expect(within(region).getByRole("img").getAttribute("aria-label")).toContain("價差虧 NT$210,000")
  })

  it("隱私模式：圖例的金額都遮掉；% 照常", async () => {
    act(() => {
      usePrefs.setState({ privacyMode: true })
      useLedgerPrefs.setState({ trendRange: "3M" })
    })
    renderApp("/")
    const region = await trend()
    const grid = region.querySelector<HTMLElement>("[data-legend-grid]")!
    expect(grid.textContent).not.toMatch(/NT\$/)
    expect(within(legend(region, "invested")!).getByLabelText("已隱藏")).toBeInTheDocument()
    expect(legend(region, "gain")!.textContent).toBe("目前價差")
    expect(within(region).getByText(/^報酬/, { selector: "span" }).textContent).toMatch(/%/)
    // 圖的說明不念金額
    expect(within(region).getByRole("img").getAttribute("aria-label")).not.toMatch(/NT\$/)
  })

  it("舊版後端（沒有 composition）：和以前一模一樣——沒有塗色、新的圖例、那一句、股利記號，圖還是原本的高度", async () => {
    await withoutComposition()
    act(() => useLedgerPrefs.setState({ trendRange: "ALL" }))
    renderApp("/")
    const region = await trend()
    expect(region.querySelector("[data-bands]")).toBeNull()
    expect(region.querySelector("clipPath")).toBeNull()
    expect(region.querySelector("[data-legend]")).toBeNull()
    expect(region.querySelector("[data-off-chart]")).toBeNull()
    expect(sentence(region)).toBeNull()
    expect(region.querySelector("[data-dividend-mark]")).toBeNull()
    expect(region.querySelector("[data-bracket]")).toBeNull()
    expect(within(region).queryByText(/用估計的買入日計算/)).toBeNull()
    // 手機的高度（jsdom 不是桌面）：和 main 一樣 96；面積是 main 的淡墨面積
    expect(within(region).getByRole("img").getAttribute("height")).toBe("96")
    expect(region.querySelector('[data-series="area"]')!.getAttribute("fill")).toBe("url(#hero-trend-area)")
    expect(region.querySelector("[data-legend-row], [data-legend-grid], [data-invested-switch]")).toBeNull()
  })
})

describe("D＋G：績效分段的「每月報酬率」與「贏過幾成的台股基金」", { timeout: 20_000 }, () => {
  const months = () => screen.findByRole("table", { name: /每個月的本金增減/ }, T)

  it("1 年：一個月一列（新的在上面），表格上面沒有「最好、最差」那一句；估計的那一段、匯入那天的月份不列，表格下面各說一次；年化 XIRR 說為什麼不算", async () => {
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/?view=performance")
    const table = await months()
    const rows = within(table).getAllByRole("rowheader").map((th) => th.textContent)
    // 2025/12 不列（暫定）：聯發科 11/29（星期六）匯入時找不到買入日，成本到匯入那天的漲跌都算在下一個收盤日 12/1。
    // 列出來的都在今年：月份寫「11 月」
    expect(rows.at(-1)).toMatch(/^1 月/)
    expect(rows).toHaveLength(11)
    // 11 月還沒過完：寫它算的是哪幾天
    expect(rows[0]).toMatch(/^11 月 11\/2 – 11\/12/)
    // 2026-11-22 評論：表格下面只放標籤；本金增減的意思與匯入那天的算法在「計算方式」裡
    expect(screen.getByText("未列 1 個月・估計的買入日")).toBeInTheDocument()
    expect(screen.getByText("未列 1 個月・匯入時找不到買入日")).toBeInTheDocument()
    // 決定 5：本金增減只算還在股票裡的錢（用和圖一樣的說法：本金）——收在「計算方式」裡
    const flowsDef = screen.getByText("本金增減：買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢，股利不算。")
    expect(flowsDef).not.toBeVisible()
    await userEvent.click(screen.getByRole("button", { name: /計算方式/ }))
    expect(flowsDef).toBeVisible()
    expect(screen.getByText("匯入時找不到買入日的持股，從成本到匯入那天的漲跌都算在匯入那天，那個月不列。")).toBeVisible()
    expect(within(table).getByRole("columnheader", { name: "本金增減" })).toBeInTheDocument()
    // 使用者 2026-11-19：表格上面不放「報酬率最好的是…。最差的是…。」（只要表格）
    expect(screen.queryByText(/報酬率最好的是|最差的是/)).toBeNull()
    expect(table.textContent).not.toMatch(/2025\/12|12 月/)
    // 和基準差幾個百分點：用多／少（不是紅綠）
    expect(table.textContent).toMatch(/(多|少) [\d.]+ 個百分點/)
    expect(screen.getByText("含估計的買入日・不年化")).toBeInTheDocument()
  })

  it("贏過幾成的台股基金（示範資料）：標籤＋數字、期間與比了幾檔；怎麼比與後端的說明在「計算方式」；標「示範資料」，來源不登記到頁尾", async () => {
    renderApp("/?view=performance")
    await screen.findByText("與基準比較", {}, T)
    const [line, period, ...rest] = [...document.querySelectorAll<HTMLElement>("[data-fund-rank] p")]
    // 2026-11-22 評論：標籤和數字，不是一句「今年贏過 72% 的台股基金」
    expect(line!.textContent).toMatch(/^贏過的台股基金（今年） \d+%示範資料$/)
    expect(within(line!).getByText("示範資料")).toHaveClass("demo-tag")
    expect(period!.textContent).toBe("1/1 – 11/11・812 檔境內台股基金")
    expect(rest).toHaveLength(0)
    const how = screen.getByText("贏過的台股基金：同一段期間的時間加權報酬，和每一檔基金的淨值報酬比。基金淨值不含配息，配息的基金照公告的配息加回。")
    expect(how).not.toBeVisible()
    await userEvent.click(screen.getByRole("button", { name: /計算方式/ }))
    expect(how).toBeVisible()
    // 編的數字不掛在金管會的名下：頁尾沒有登記任何來源時只是一個連結
    expect(screen.getByRole("link", { name: "資料來源與授權" })).toBeInTheDocument()
  })

  it("真的基金排名（is_demo 不是 true）：沒有示範標記，來源登記到頁尾", async () => {
    await withPerformance((p) => (p.fund_rank ? { ...p, fund_rank: { ...p.fund_rank, is_demo: false } } : p))
    renderApp("/?view=performance")
    await screen.findByText("與基準比較", {}, T)
    expect(document.querySelector("[data-fund-rank] .demo-tag")).toBeNull()
    await userEvent.click(await screen.findByRole("button", { name: /資料來源與授權/ }, T))
    expect(await screen.findByText(/金融監督管理委員會證券期貨局〈境內基金每日淨值〉/, {}, T)).toBeInTheDocument()
  })

  it("1 個月：只有兩列（區間頭尾都不完整）", async () => {
    renderApp("/?view=performance")
    const table = await months()
    expect(within(table).getAllByRole("rowheader").map((th) => th.textContent)).toEqual([expect.stringMatching(/^11 月 11\/2 – 11\/12/), expect.stringMatching(/^10 月 10\/12 – 10\/30/)])
    expect(screen.queryByText(/^報酬率最好的是/)).toBeNull()
  })

  it("全部都是估計的：一句話、沒有表格；沒有基金的資料：那一行不放", async () => {
    await withPerformance((p) => (p.composition ? { ...p, fund_rank: null, composition: { ...p.composition, months: [], months_estimated: 12 } } : p))
    renderApp("/?view=performance")
    expect(await screen.findByText("沒有可以比的月份・都是估計的買入日", {}, T)).toBeInTheDocument()
    expect(screen.queryByRole("table", { name: /每個月的本金增減/ })).toBeNull()
    expect(document.querySelector("[data-fund-rank]")).toBeNull()
  })

  it("隱私模式：表格的金額遮掉，報酬率照常", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/?view=performance")
    const table = await months()
    expect(table.textContent).not.toMatch(/NT\$/)
    expect(table.textContent).toMatch(/[▲▼][\d.]+%/)
  })

  it("舊版後端（沒有 composition、fund_rank）：沒有表格、沒有基金那一行，XIRR 的說明照舊", async () => {
    await withoutComposition()
    act(() => useLedgerPrefs.setState({ trendRange: "1Y" }))
    renderApp("/?view=performance")
    await screen.findByText("最大回撤", {}, T)
    expect(screen.queryByText("每月報酬率")).toBeNull()
    expect(document.querySelector("[data-fund-rank]")).toBeNull()
    expect(screen.queryByText("含估計的買入日・不年化")).toBeNull()
  })
})

describe("E：持倉展開的買入日標記與在走勢圖上選日期", { timeout: 30_000 }, () => {
  async function expand(name: string) {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const table = await screen.findByRole("table", { name: "持倉" }, T)
    await user.click(within(table).getByRole("button", { name: `展開${name}的每一筆買賣` }))
    return within(table).findByRole("list", { name: `${name}的每一筆買賣` }, T)
  }

  it("估計的標「估計」、自己選的標「自己選的日期」、找不到（用匯入那天）的不標但選單裡可以選", async () => {
    renderApp("/")
    const gw = await expand("環球晶")
    expect(within(gw).getAllByRole("button", { name: /是估計的買入日：在走勢圖上選日期$/ }).length).toBeGreaterThan(0)
    const honHai = await expand("鴻海")
    expect(within(honHai).getAllByRole("button", { name: /是自己選的買入日：在走勢圖上選日期$/ }).length).toBeGreaterThan(0)
    const mtk = await expand("聯發科")
    expect(within(mtk).queryByText("估計")).toBeNull()
    expect(within(mtk).queryByText("自己選的日期")).toBeNull()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.click(within(mtk).getByRole("button", { name: /買進的動作$/ }))
    expect(await screen.findByRole("menuitem", { name: "在走勢圖上選買入日" }, T)).toBeInTheDocument()
  })

  it("找不到交會的日子（聯發科，成本比五年來的最低價還低）：照實說，圖上還是可以自己選", async () => {
    renderApp("/")
    const mtk = await expand("聯發科")
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.click(within(mtk).getByRole("button", { name: /買進的動作$/ }))
    await user.click(await screen.findByRole("menuitem", { name: "在走勢圖上選買入日" }, T))
    const dialog = await screen.findByRole("dialog", { name: "聯發科的買入日" }, T)
    // 照實寫有資料的那幾年；帳本上的日期（11/29 星期六匯入）沒有收盤：打開時不會準備好改成前一天
    expect(await within(dialog).findByText("2021/11/12 – 2025/11/28・沒有經過成本 488", {}, T)).toBeInTheDocument()
    expect(within(dialog).getByRole("group", { name: /^價格走勢/ })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "改日期" })).toBeDisabled()
    expect(within(dialog).getByText("帳本 2025/11/29 沒有收盤・前一個交易日")).toBeInTheDocument()
  })

  it("隱私模式：不寫成本（縱軸、成本線的字），讀數下面那一句也不放（收盤加差幾 % 就算得出成本）", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const gw = await expand("環球晶")
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.click(within(gw).getAllByRole("button", { name: /是估計的買入日/ })[0]!)
    const dialog = await screen.findByRole("dialog", { name: "環球晶的買入日" }, T)
    await within(dialog).findByRole("radiogroup", { name: "股價經過成本的日子" }, T)
    expect(dialog.textContent).not.toMatch(/成本 580/)
    expect(dialog.textContent).not.toMatch(/差 [\d.]+%/)
    expect(dialog.querySelector("[data-picker-readout]")!.querySelectorAll("p")).toHaveLength(1)
  })

  it("打開走勢圖：候選的日子一排、估計的那天先選好；鍵盤選離成本很遠的一天照實說；「改成…」只改日期，之後標「自己選的日期」", async () => {
    const update = vi.spyOn(api, "updateTransaction")
    renderApp("/")
    const gw = await expand("環球晶")
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const lot = (await api.listTransactions({ symbol: "6488.TWO", type: "buy", limit: 10 })).items[0]!
    expect(lot).toMatchObject({ date_basis: "estimated", estimated_date: lot.trade_date })
    await user.click(within(gw).getAllByRole("button", { name: /是估計的買入日/ })[0]!)
    const dialog = await screen.findByRole("dialog", { name: "環球晶的買入日" }, T)
    const list = await within(dialog).findByRole("radiogroup", { name: "股價經過成本的日子" }, T)
    const radios = within(list).getAllByRole("radio")
    expect(radios.length).toBeGreaterThan(1)
    expect(radios[0]).toHaveAttribute("aria-checked", "true")
    expect(within(radios[0]!).getByText("估計")).toBeInTheDocument()
    expect(within(radios[0]!).getByText("目前的日期")).toBeInTheDocument()
    // 還沒改：定案的按鈕不能按
    expect(within(dialog).getByRole("button", { name: "改日期" })).toBeDisabled()
    // 估計的那天：寫那天的最低–最高經過成本，不寫「收盤和成本差幾 %」（不讓估計看起來像估錯）
    expect(within(dialog).getByText(/^當天 [\d,]+–[\d,]+・經過成本 580$/)).toBeInTheDocument()
    // 用鍵盤在圖上往前移：換成那一天的讀數（各種句子見 buy-date-picker.test.tsx 的 readoutLine）
    const g = within(dialog).getByRole("group", { name: /^價格走勢/ })
    act(() => g.focus())
    for (let i = 0; i < 40; i++) fireEvent.keyDown(g, { key: "ArrowLeft" })
    expect(dialog.querySelector("[data-picker-readout]")!.textContent).toMatch(/^2025\/5\/\d+收盤 /)
    expect(within(dialog).getByRole("button", { name: /^改成 2025\/5\/\d+$/ })).toBeEnabled()
    // Page Down 跳到下一個候選；按一個候選就選它
    await user.click(radios[1]!)
    expect(radios[1]).toHaveAttribute("aria-checked", "true")
    const sign = within(dialog).getByRole("button", { name: /^改成 \d{4}\/\d+\/\d+$/ })
    const day = sign.textContent!.replace("改成 ", "").split("/").map(Number)
    await user.click(sign)
    await waitFor(() => expect(update).toHaveBeenCalled(), T)
    const [id, patch] = update.mock.calls[0]!
    expect(id).toBe(lot.id)
    // 只改日期：手續費與稅照原本的一起送
    expect(patch).toEqual({ trade_date: `${day[0]}-${String(day[1]).padStart(2, "0")}-${String(day[2]).padStart(2, "0")}`, fee: lot.fee, tax: lot.tax, date_basis: "picked" })
    // 等寫入完成（先出現通知），再看帳本裡的那一筆
    expect(await screen.findByText(/^已改成 \d{4}\/\d+\/\d+ 買進$/, {}, T)).toBeInTheDocument()
    const after = (await api.listTransactions({ symbol: "6488.TWO", type: "buy", limit: 10 })).items[0]! as Transaction
    expect(after).toMatchObject({ date_basis: "picked", price: lot.price, quantity: lot.quantity, estimated_date: lot.estimated_date })
    await waitFor(() => expect(within(gw).getAllByRole("button", { name: /是自己選的買入日/ }).length).toBeGreaterThan(0), T)
  })
})

describe("E：選日期的對話框（直接畫）", () => {
  const lot: Transaction = {
    id: "txn_long", account_id: "acc_01JSINOPAC", symbol: "2330.TW", type: "buy", trade_date: "2025-07-02", quantity: 1000, price: 1000, amount: 1_000_000,
    fee: 0, tax: 0, health_insurance: 0, currency: "TWD", is_day_trade: false, note: "", source: "import", created_at: "2025-12-01T10:00:00+08:00",
    date_basis: "estimated", estimated_date: "2025-07-02", imported_on: "2025-12-01",
  }
  it("名字很長（12 個字）：標題照寫（換行，不截斷）", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <BuyDatePicker lot={lot} name="台灣積體電路製造股份有限" market="TWSE" type="stock" open onOpenChange={() => {}} />
      </QueryClientProvider>,
    )
    expect(await screen.findByRole("dialog", { name: "台灣積體電路製造股份有限的買入日" }, T)).toBeInTheDocument()
    expect(screen.getByText(/^成本 1,000・1 張・2025\/12\/1 匯入$/)).toBeInTheDocument()
  })
})

describe("E：舊版後端（交易沒有 date_basis）", { timeout: 20_000 }, () => {
  it("沒有標記、選單沒有「在走勢圖上選買入日」", async () => {
    const real = api.listTransactions.bind(api)
    vi.spyOn(api, "listTransactions").mockImplementation(async (q) => {
      const page = await real(q)
      return { ...page, items: page.items.map(({ date_basis: _b, estimated_date: _e, imported_on: _i, ...t }) => t) }
    })
    renderApp("/")
    const table = await screen.findByRole("table", { name: "持倉" }, T)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.click(within(table).getByRole("button", { name: "展開環球晶的每一筆買賣" }))
    const list = await within(table).findByRole("list", { name: "環球晶的每一筆買賣" }, T)
    await within(list).findAllByRole("listitem", {}, T)
    expect(within(list).queryByText("估計")).toBeNull()
    await user.click(within(list).getAllByRole("button", { name: /買進的動作$/ })[0]!)
    await screen.findByRole("menuitem", { name: "修改" }, T)
    expect(screen.queryByRole("menuitem", { name: "在走勢圖上選買入日" })).toBeNull()
  })
})
