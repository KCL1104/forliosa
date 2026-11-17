import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { toast } from "sonner"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { ApiError, type ForliosaApi, type MemberTrial } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 盲測開給所有登入的人（產品負責人 2026-11-17「我讓我的朋友們一起選」；mock 情境 `trial-open`）：
 * 一般帳號在市場頁「報告」看到「盲測：三種寫法」、A／B／C 與投票，可以改票；揭曉前沒有模型與花費；
 * 預設情境（只給管理員）一般帳號照舊看不到；管理後台可以切換誰參加，盲測的票會員、管理員分開寫；群組頻道有三個開關。
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
  useViewAs.getState().set(null)
  act(resetAi)
})

const T = { timeout: 6000 }
const MEMBER: MockOptions = { reports: "trial-open", discussion: { admin: false } }

function mount(options: MockOptions = {}) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  const spies = {} as Record<keyof ForliosaApi, ReturnType<typeof vi.spyOn>>
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") spies[key] = vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  return spies
}

function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const trialBar = async () => (await screen.findByText("盲測：三種寫法", { selector: "[data-trial-bar] span" }, T)).closest("section")!
const voteRow = () => document.querySelector<HTMLElement>("[data-trial-vote]")!

describe("一般帳號：盲測開給所有人", () => {
  it("報告分頁：看得到「盲測：三種寫法」與 A／B／C，揭曉前沒有模型；選一個、再改選", async () => {
    const user = userEvent.setup()
    const spies = mount(MEMBER)
    renderApp("/market?tab=reports&kind=close")
    const bar = await trialBar()
    expect(within(bar).getByText("同一份資料寫了三次。看完選一個你覺得最好讀的。", { exact: false })).toBeInTheDocument()
    const chips = within(bar).getByRole("radiogroup", { name: "看哪一種寫法" })
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["A", "B", "C"])
    expect(within(bar).getByText("還沒選")).toBeInTheDocument()
    // 選的那一種的全文（一般形式）：報告名稱是標題，沒有模型、花費
    const article = await screen.findByRole("heading", { level: 2, name: /^盤後重點 / }, T)
    const root = article.closest("article")!
    expect(root.textContent).not.toMatch(/Opus|Sonnet|US\$\d|F\d{3}|X\d{3}/)
    const label = within(chips).getAllByRole("radio").find((r) => r.getAttribute("aria-checked") === "true")!.textContent!
    await user.click(within(voteRow()).getByRole("button", { name: `選 ${label}` }))
    await waitFor(() => expect(spies.voteMarketReport).toHaveBeenCalledWith(expect.stringMatching(/^mrp_close_/), label), T)
    await waitFor(() => expect(within(bar).getByText(`你選了 ${label}`)).toBeInTheDocument(), T)
    // 按鈕換成「你選了 X」：焦點移到那一行（不掉回頁首，讀屏會念出來）
    const pick = voteRow().querySelector<HTMLElement>("[data-my-pick]")!
    expect(pick).toHaveTextContent(`你選了 ${label}`)
    await waitFor(() => expect(document.activeElement).toBe(pick), T)
    // 看另一種：按下的「看 X」消失，焦點移到上面選取的 X；按鈕變「改選」，旁邊寫原本選的
    const other = ["A", "B", "C"].find((l) => l !== label && within(voteRow()).queryByRole("button", { name: `看 ${l}` }))!
    await user.click(within(voteRow()).getByRole("button", { name: `看 ${other}` }))
    await waitFor(() => expect(document.activeElement).toBe(within(chips).getByRole("radio", { name: other })), T)
    expect(document.activeElement).toHaveAttribute("aria-checked", "true")
    const change = await within(voteRow()).findByRole("button", { name: `改選 ${other}` }, T)
    expect(within(voteRow()).getByText(`你選了 ${label}`)).toBeInTheDocument()
    await user.click(change)
    await waitFor(() => expect(within(bar).getByText(`你選了 ${other}`)).toBeInTheDocument(), T)
    expect(spies.voteMarketReport).toHaveBeenLastCalledWith(expect.stringMatching(/^mrp_close_/), other)
    await waitFor(() => expect(document.activeElement).toHaveTextContent(`你選了 ${other}`), T)
  })

  it("沒有投票成功：焦點回到按鈕，提示原因", async () => {
    const user = userEvent.setup()
    const spies = mount(MEMBER)
    const err = vi.spyOn(toast, "error").mockImplementation(() => 1)
    spies.voteMarketReport.mockRejectedValue(new ApiError(409, "trial_revealed", "盲測已經揭曉，不能再投票或改票。"))
    renderApp("/market?tab=reports&kind=close")
    await trialBar()
    await screen.findByRole("heading", { level: 2, name: /^盤後重點 / }, T)
    const button = within(voteRow()).getByRole("button", { name: /^選 [ABC]$/ })
    await user.click(button)
    await waitFor(() => expect(err).toHaveBeenCalledWith("沒有投票成功", { description: "盲測已經揭曉，不能再投票或改票。" }), T)
    await waitFor(() => expect(document.activeElement).toBe(within(voteRow()).getByRole("button", { name: /^選 [ABC]$/ })), T)
    expect(voteRow().querySelector("[data-my-pick]")).toBeNull()
  })

  it("三種都還不能看：說一句，下面是資料版（不是只剩「還在寫」），沒有投票", async () => {
    const spies = mount(MEMBER)
    const real = spies.getMarketReportTrial.getMockImplementation()!
    spies.getMarketReportTrial.mockImplementation(async (...args: unknown[]) => {
      const t = (await real(...args)) as MemberTrial
      return { ...t, can_vote: false, variants: t.variants.map((v) => ({ ...v, state: "writing" as const })) }
    })
    renderApp("/market?tab=reports&kind=close")
    const bar = await trialBar()
    expect(within(bar).getByText("三種寫法還沒好，先看資料。寫好就可以選。", { exact: false })).toBeInTheDocument()
    expect(within(bar).queryByRole("radiogroup")).toBeNull()
    // 資料版的全文（報告名稱是標題），沒有「A 還在寫」，沒有投票的那一列
    await screen.findByRole("heading", { level: 2, name: /^盤後重點 / }, T)
    expect(screen.queryByText(/^[ABC] 還在寫$/)).toBeNull()
    expect(voteRow()).toBeNull()
    expect(spies.getMarketReportVariant).not.toHaveBeenCalled()
    cleanup()
    // 都不會來了（沒有寫成）：說法不同
    spies.getMarketReportTrial.mockImplementation(async (...args: unknown[]) => {
      const t = (await real(...args)) as MemberTrial
      return { ...t, can_vote: false, variants: t.variants.map((v) => ({ ...v, state: "none" as const })) }
    })
    renderApp("/market?tab=reports&kind=close")
    expect(within(await trialBar()).getByText("這一份沒有寫成三種寫法，下面是資料。", { exact: false })).toBeInTheDocument()
    await screen.findByRole("heading", { level: 2, name: /^盤後重點 / }, T)
    expect(screen.queryByText(/^[ABC] 這次沒有寫成$/)).toBeNull()
  })

  it("報告頁（推播的投票連結）：同一個盲測畫面，頁面標題寫盲測；更早的報告列出「盲測：三種寫法・還沒選」", async () => {
    mount(MEMBER)
    renderApp("/market?tab=reports&kind=premarket")
    await trialBar()
    const earlier = (await screen.findByRole("heading", { name: "更早的報告" }, T)).closest("section")!
    expect(within(earlier).getAllByText(/盲測：三種寫法・(還沒選|你選了 [ABC])/).length).toBeGreaterThan(0)
    cleanup()
    const router = renderApp("/market/reports/mrp_premarket_20261111")
    await trialBar()
    await waitFor(() => expect(document.title).toMatch(/^盤前重點 11\/11（三）・盲測/), T)
    expect(router.state.location.pathname).toBe("/market/reports/mrp_premarket_20261111")
  })

  it("沒有寫成的那一種：選它時寫「這次沒有寫成」，不能投它", async () => {
    const user = userEvent.setup()
    mount(MEMBER)
    renderApp("/market/reports/mrp_premarket_20261111")
    const bar = await trialBar()
    const chips = within(bar).getByRole("radiogroup", { name: "看哪一種寫法" })
    for (const l of ["A", "B", "C"]) {
      await user.click(within(chips).getByRole("radio", { name: l }))
      if (screen.queryByText(`${l} 這次沒有寫成`)) {
        expect(screen.queryByRole("button", { name: `選 ${l}` })).toBeNull()
        return
      }
    }
    throw new Error("mock 的第二份盤前重點（11/11）應該有一種沒有寫成")
  })

  it("只給管理員（預設）：一般帳號沒有報告分頁，盲測的報告頁是找不到", async () => {
    mount({ discussion: { admin: false } })
    renderApp("/market/reports/mrp_premarket_20261111")
    expect(await screen.findByText("找不到這份報告", {}, T)).toBeInTheDocument()
    expect(document.querySelector("[data-trial-bar]")).toBeNull()
  })

  it("查看別人的資產時：看得到，沒有投票的按鈕", async () => {
    mount(MEMBER)
    useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "all", accounts: [] })
    renderApp("/market?tab=reports&kind=close")
    await trialBar()
    await screen.findByRole("heading", { level: 2, name: /^盤後重點 / }, T)
    expect(screen.queryByRole("button", { name: /^(選|改選) [ABC]$/ })).toBeNull()
  })
})

describe("管理後台：誰參加盲測、會員與管理員的票", () => {
  it("開給所有人：狀態寫「所有登入的人」，每份寫大家的票（會員、管理員分開）；切回只有管理員", async () => {
    const user = userEvent.setup()
    const spies = mount({ reports: "trial-open" })
    renderApp("/admin/reports")
    const status = (await screen.findByRole("heading", { level: 2, name: "狀態" }, T)).closest("section")!
    const row = within(status).getByText("盲測對象").parentElement!
    expect(within(row).getByText("所有登入的人")).toBeInTheDocument()
    expect(within(row).getByText("（預設）")).toBeInTheDocument()
    const trial = (await screen.findByRole("heading", { level: 2, name: "盲測" }, T)).closest("section")!
    expect(await within(trial).findByText(/^開給所有登入的人：會員 \d+ 人、管理員 \d+ 人投過票。$/, {}, T)).toBeInTheDocument()
    const votes = trial.querySelector<HTMLElement>("[data-trial-votes]")!
    expect(votes.textContent).toMatch(/大家的票 A \d+・B \d+・C \d+/)
    expect(votes.textContent).toMatch(/會員 A \d+・B \d+・C \d+；管理員 A \d+・B \d+・C \d+/)
    await user.click(within(row).getByRole("button", { name: "切換盲測對象" }))
    const dialog = await screen.findByRole("dialog", {}, T)
    await user.click(within(dialog).getByRole("radio", { name: /只有站方管理員/ }))
    await user.click(within(dialog).getByRole("button", { name: "切換" }))
    await waitFor(() => expect(spies.putReportsConfig).toHaveBeenCalledWith({ trial_audience: "admins" }), T)
    await waitFor(() => expect(within(row).getByText("只有站方管理員")).toBeInTheDocument(), T)
  })
})

describe("群組頻道：盲測開給所有人時", () => {
  it("有三個報告開關，說明寫投票連結", async () => {
    mount({ reports: "trial-open" })
    renderApp("/groups/grp_family?tab=channels")
    const discord = (await screen.findByRole("heading", { name: "Discord" }, T)).closest("section")!
    expect(await within(discord).findByRole("switch", { name: "盤後重點（交易日 16:00）" }, T)).toBeInTheDocument()
    expect(within(discord).getByText("盲測期間每份報告推一則投票連結：三種寫法，看完選一個。")).toBeInTheDocument()
    // 不併群組的週報：週報那一列的說明照平常寫
    expect(within(discord).getByText("每週六晚上的群組 AI 週報。")).toBeInTheDocument()
  })
})
