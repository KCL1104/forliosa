import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import type { ForliosaApi } from "@/api/types"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 管理後台「市場報告」（2026-11-17）：狀態與模式切換、撰寫設定、三張手動維護的表。
 * 盲測（A／B／C、投票、揭曉）2026-11-18 拿掉了：沒有盲測的段落與比較頁。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null, ownerId: null })
beforeEach(() => act(resetAi))
afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
  act(resetAi)
})

const T = { timeout: 6000 }

function mount(options: MockOptions = {}) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
}

function renderApp(path = "/admin/reports") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const section = async (name: string) => (await screen.findByRole("heading", { level: 2, name }, T)).closest("section")!

describe("狀態", () => {
  it("對全站公開：每種報告的撰寫設定（預設 Opus 5.5・high）；模式只有公開與暫停，沒有試跑、盲測；暫停後再公開要再確認一次", async () => {
    const user = userEvent.setup()
    mount()
    renderApp()
    const status = await section("狀態")
    const modeRow = within(status).getByText("模式").parentElement!
    expect(within(modeRow).getByText("對全站公開")).toBeInTheDocument()
    expect(within(status).getAllByText(/Opus 5\.5・high/)).toHaveLength(3)
    expect(within(status).queryByText(/盲測|試跑/)).toBeNull()
    expect(screen.queryByRole("heading", { level: 2, name: "盲測" })).toBeNull()
    expect(within(status).getByText("金鑰 4・正常")).toBeInTheDocument()
    // 暫停
    await user.click(within(status).getByRole("button", { name: "切換" }))
    let dialog = await screen.findByRole("dialog", {}, T)
    expect(within(dialog).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual([
      expect.stringMatching(/^對全站公開/),
      expect.stringMatching(/^暫停/),
    ])
    await user.click(within(dialog).getByRole("radio", { name: /暫停/ }))
    await user.click(within(dialog).getByRole("button", { name: "切換" }))
    await waitFor(() => expect(within(modeRow).getByText("暫停")).toBeInTheDocument(), T)
    // 再公開：要再確認一次
    await user.click(within(status).getByRole("button", { name: "切換" }))
    dialog = await screen.findByRole("dialog", {}, T)
    await user.click(within(dialog).getByRole("radio", { name: /對全站公開/ }))
    await user.click(within(dialog).getByRole("button", { name: "切換" }))
    const confirm = await screen.findByRole("alertdialog", {}, T)
    expect(within(confirm).getByText("之後的新報告會對所有登入的人公開，並推播到有開的群組。")).toBeInTheDocument()
    await user.click(within(confirm).getByRole("button", { name: "對全站公開" }))
    await waitFor(() => expect(within(modeRow).getByText("對全站公開")).toBeInTheDocument(), T)
  })

  it("部署交接時舊的 API 還回 trial：當成對全站公開，模式對話框照常打開", async () => {
    const user = userEvent.setup()
    mount()
    const other = createMockAdapter({ latency: [0, 0] })
    vi.spyOn(api, "getAdminReportsOverview").mockImplementation(async () => ({ ...(await other.getAdminReportsOverview()), mode: "trial" as unknown as "public" }))
    renderApp()
    const status = await section("狀態")
    const modeRow = within(status).getByText("模式").parentElement!
    expect(within(modeRow).getByText("對全站公開")).toBeInTheDocument()
    await user.click(within(status).getByRole("button", { name: "切換" }))
    const dialog = await screen.findByRole("dialog", {}, T)
    expect(within(dialog).getByText("現在是「對全站公開」。")).toBeInTheDocument()
    expect(within(dialog).getByRole("radio", { name: /對全站公開/ })).toBeChecked()
  })

  it("不是站方管理員：找不到這個頁面", async () => {
    mount({ discussion: { admin: false } })
    renderApp()
    expect(await screen.findByText("找不到這個頁面", {}, T)).toBeInTheDocument()
  })

  it("伺服器沒有開：一行說明", async () => {
    mount({ reports: "off" })
    renderApp()
    expect(await screen.findByText("市場報告沒有開", {}, T)).toBeInTheDocument()
  })
})

describe("手動維護的表", () => {
  it("休市表：未核對的列標出來、可以標記已核對；總經行事曆只能連到官方網站（伺服器的錯寫在那一欄下面）；必填就地檢查", async () => {
    const user = userEvent.setup()
    mount()
    renderApp()
    const nyse = await section("美股休市表")
    expect(within(nyse).getByText(/尚未核對 2 列/)).toBeInTheDocument()
    const list = await within(nyse).findByRole("list", { name: "美股休市日" }, T)
    const jan1 = within(list).getByText(/元旦/).closest("li")!
    expect(within(jan1).getByText("未核對")).toBeInTheDocument()
    await user.click(within(jan1).getByRole("button", { name: "標記已核對" }))
    await waitFor(() => expect(within(nyse).getByText(/尚未核對 1 列/)).toBeInTheDocument(), T)

    const macro = await section("總經行事曆")
    await user.click(within(macro).getByRole("button", { name: "新增" }))
    expect(within(macro).getByText("請選日期。")).toBeInTheDocument()
    expect(within(macro).getByText("請寫數據名稱，例如「10 月消費者物價指數」。")).toBeInTheDocument()
    fireEvent.change(within(macro).getByLabelText("日期（當地）"), { target: { value: "2026-11-25" } })
    await user.type(within(macro).getByLabelText("數據名稱"), "10 月個人消費支出物價指數")
    await user.type(within(macro).getByLabelText("公布機關"), "美國經濟分析局")
    await user.type(within(macro).getByLabelText("官方頁面"), "https://www.example.com/pce")
    await user.click(within(macro).getByRole("button", { name: "新增" }))
    expect(await within(macro).findByText("只能連到官方網站（例如 bls.gov、dgbas.gov.tw）。", {}, T)).toBeInTheDocument()
    const url = within(macro).getByLabelText("官方頁面")
    await user.clear(url)
    await user.type(url, "https://www.bea.gov/data/personal-consumption-expenditures-price-index")
    await user.click(within(macro).getByRole("button", { name: "新增" }))
    expect(await within(macro).findByText("10 月個人消費支出物價指數", {}, T)).toBeInTheDocument()
  })
})
