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
 * 管理後台「市場報告」（2026-11-17）：狀態與模式切換、盲測（A／B／C、投票、揭曉）、三張手動維護的表。
 * 揭曉前不顯示盲測用的模型與花費。
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
  it("試跑中：撰寫設定寫「盲測中」；切到對全站公開要再確認一次", async () => {
    const user = userEvent.setup()
    mount()
    renderApp()
    const status = await section("狀態")
    const modeRow = within(status).getByText("模式").parentElement!
    expect(within(modeRow).getByText("試跑")).toBeInTheDocument()
    expect(within(status).getAllByText("盲測中")).toHaveLength(3)
    expect(within(status).getByText(/^US\$\d+\.\d{2}／US\$45\.00・第 3／5 個交易日・週報未做$/)).toBeInTheDocument()
    expect(within(status).getByText("金鑰 4・正常")).toBeInTheDocument()
    await user.click(within(status).getByRole("button", { name: "切換" }))
    const dialog = await screen.findByRole("dialog", {}, T)
    await user.click(within(dialog).getByRole("radio", { name: /對全站公開/ }))
    await user.click(within(dialog).getByRole("button", { name: "切換" }))
    const confirm = await screen.findByRole("alertdialog", {}, T)
    expect(within(confirm).getByText("之後的新報告會對所有登入的人公開，並推播到有開的群組。")).toBeInTheDocument()
    await user.click(within(confirm).getByRole("button", { name: "對全站公開" }))
    await waitFor(() => expect(within(modeRow).getByText("對全站公開")).toBeInTheDocument(), T)
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

describe("盲測", () => {
  it("每份一列 A／B／C（連到並排比較）、狀態與問題數；揭曉前沒有模型與花費；投票是選取語法 (b)；沒做完是「提前揭曉」", async () => {
    const user = userEvent.setup()
    mount()
    const router = renderApp()
    const trial = await section("盲測")
    const rowsOf = () => [...trial.querySelectorAll<HTMLElement>("[data-trial-report]")]
    await waitFor(() => expect(rowsOf()).toHaveLength(5), T)
    const rows = rowsOf()
    expect(trial.textContent).not.toMatch(/Opus|Sonnet|US\$/)
    const first = rows.find((r) => r.textContent?.startsWith("盤前重點 11/11"))!
    expect(within(first).getByText(/只有資料/)).toBeInTheDocument()
    const vote = within(first).getByRole("group", { name: /投給哪一個/ })
    await user.click(within(vote).getByRole("button", { name: "C" }))
    await waitFor(() => expect(within(vote).getByRole("button", { name: "C" })).toHaveAttribute("aria-pressed", "true"), T)
    expect(within(trial).queryByRole("button", { name: "揭曉" })).toBeNull()
    await user.click(within(trial).getByRole("button", { name: "提前揭曉" }))
    expect(await screen.findByRole("alertdialog", { name: "盲測還沒做完，要提前揭曉？" }, T)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "取消" }))
    // 打開一個版本：管理員形式（每句後面有 refs）
    await user.click(within(first).getByRole("link", { name: "看 B 版" }))
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/reports/mrp_premarket_20261111"), T)
    expect(await screen.findByRole("heading", { level: 1, name: "盤前重點 11/11（三）・盲測" }, T)).toBeInTheDocument()
    await waitFor(() => expect(document.querySelector("[data-refs]")).not.toBeNull(), T)
    expect(document.querySelector("[data-refs]")!.textContent).toMatch(/^[FXCNW]\d{3}/)
  })

  it("揭曉後：每種報告每組設定的彙總、過關、建議（過關裡平均花費最低）；被拿掉的段在管理員檢視照樣顯示原因", async () => {
    mount({ reports: "public" })
    renderApp()
    const trial = await section("盲測")
    const suggested = await within(trial).findAllByText((_, el) => el?.tagName === "P" && /^建議：/.test(el.textContent ?? ""), {}, T)
    expect(suggested).toHaveLength(3)
    expect(within(trial).getAllByText("過關").length).toBeGreaterThan(0)
    expect(trial.textContent).toMatch(/Opus 5\.5・high/)
    cleanup()
    // 被拿掉一段的版本（Sonnet）：段標題下一行「這一段被拿掉」
    renderApp("/admin/reports/mrp_close_20261027?v=A")
    const dropped = await screen.findAllByText(/^這一段被拿掉：/, {}, T).catch(() => [])
    if (dropped.length === 0) {
      // A 不一定是被拿掉段的那一個（每份重新打亂）：換 B、C 找
      for (const v of ["B", "C"]) {
        fireEvent.click(screen.getByRole("radio", { name: v }))
        if ((await screen.findAllByText(/^這一段被拿掉：/, {}, { timeout: 1500 }).catch(() => [])).length) break
      }
    }
    expect(screen.getAllByText(/^這一段被拿掉：數字和主體對不上/).length).toBeGreaterThan(0)
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
