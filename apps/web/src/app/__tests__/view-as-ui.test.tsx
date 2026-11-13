import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { useViewAs, type ViewAsTarget } from "@/api/view-as"
import { CommandSearch } from "@/app/CommandSearch"
import { useUi } from "@/app/ui-store"
import { DividendsView } from "@/pages/ledger/DividendsView"
import { TransactionsView } from "@/pages/ledger/TransactionsView"
import { EventsTab } from "@/pages/stock/tabs/EventsTab"
import { createAppRouter } from "@/router"

/**
 * 查看別人的資產（唯讀）時的畫面：查看者自己的頁面擋下、沒有寫入或 AI 的動作、
 * 稱呼換成授權者的名稱、橫幅一直看得到而且範圍跟著授權者目前的設定。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  // cmdk 用 ResizeObserver 與 scrollIntoView；jsdom 沒有
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  // jsdom 沒有 matchMedia：一律當手機（< 1024px）
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  useViewAs.getState().set(null)
  useUi.getState().setSearchOpen(false)
})

const T = { timeout: 4000 }
const DAD: ViewAsTarget = {
  delegation_id: "dlg_dad",
  owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null },
  scope: "accounts",
  accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }],
}

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

function renderInRouter(ui: React.ReactNode) {
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(
    <QueryClientProvider client={client()}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}

function renderApp(path: string) {
  const qc = client()
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe("查看模式：查看者自己的頁面", () => {
  it("紀錄頁（AI 對話）擋下，不能發起對話", async () => {
    useViewAs.getState().set(DAD)
    renderApp("/history")
    expect(await screen.findByText(/這裡是你自己的紀錄，結束查看後才能使用/, undefined, T)).toBeInTheDocument()
    expect(screen.queryByText("發起新對話")).toBeNull()
    expect(screen.queryByText("我的持股會不會太集中？")).toBeNull()
  })
})

describe("查看模式：⌘K", () => {
  const selected = () => document.querySelectorAll("[cmdk-item][data-selected=true]")

  it("打開時選在第一個看得到的項目（沒有「記一筆交易」），Enter 有作用", async () => {
    useViewAs.getState().set(DAD)
    useUi.getState().setSearchOpen(true)
    renderInRouter(<CommandSearch />)
    await screen.findByText("切換隱私模式", undefined, T)
    expect(screen.queryByText("記一筆交易")).toBeNull()
    await waitFor(() => expect(selected()).toHaveLength(1))
    expect(selected()[0]!.textContent).toContain("切換隱私模式")
  })

  it("自己的帳本：第一個是「記一筆交易」", async () => {
    useUi.getState().setSearchOpen(true)
    renderInRouter(<CommandSearch />)
    await screen.findByText("記一筆交易", undefined, T)
    await waitFor(() => expect(selected()).toHaveLength(1))
    expect(selected()[0]!.textContent).toContain("記一筆交易")
  })
})

describe("查看模式：帳本沒有寫入或 AI 的動作", () => {
  it("沒有交易：中性的空狀態，沒有「記第一筆交易」和 AI 記帳說明", async () => {
    vi.spyOn(api, "listTransactions").mockResolvedValue({ items: [], next_cursor: null })
    useViewAs.getState().set(DAD)
    renderInRouter(<TransactionsView />)
    expect(await screen.findByText("沒有交易紀錄", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "記第一筆交易" })).toBeNull()
    expect(document.body.textContent).not.toContain("跟 AI 說")
  })

  it("自己的帳本沒有交易：照常有「記第一筆交易」", async () => {
    vi.spyOn(api, "listTransactions").mockResolvedValue({ items: [], next_cursor: null })
    renderInRouter(<TransactionsView />)
    expect(await screen.findByRole("button", { name: "記第一筆交易" }, T)).toBeInTheDocument()
  })

  it("「接下來」的定期定額扣款是純文字，不連到被擋下的設定頁", async () => {
    const recurring = { date: "2026-11-19", type: "recurring" as const, symbol: "0050.TW", title: "0050 定期定額", amount_estimate: 5000, plan_id: "rcp_1", account_id: "acc_dad_yuanta" }
    vi.spyOn(api, "getUpcoming").mockResolvedValue([recurring])
    useViewAs.getState().set(DAD)
    renderInRouter(<DividendsView />)
    expect(await screen.findByText("定期定額扣款", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "定期定額扣款" })).toBeNull()
    cleanup()
    useViewAs.getState().set(null)
    renderInRouter(<DividendsView />)
    expect(await screen.findByRole("link", { name: "定期定額扣款" }, T)).toHaveAttribute("href", "/settings#recurring")
  })
})

describe("查看模式：稱呼換成授權者", () => {
  it("事件分頁：「只看爸爸的」「爸爸可領約」，沒有「我的」「你可領」", async () => {
    const inst = await api.getInstrument("2330.TW")
    vi.spyOn(api, "getNews").mockResolvedValue([])
    vi.spyOn(api, "getEvents").mockResolvedValue([
      { date: "2026-12-18", type: "ex_dividend", title: "除息", detail: null, url: null, mine: true, amount_estimate: 12500 },
    ])
    useViewAs.getState().set(DAD)
    const user = userEvent.setup()
    renderInRouter(<EventsTab inst={inst} position={null} markers={[]} />)
    expect(await screen.findByText(/爸爸可領約/, undefined, T)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/你可領|只看我的/)
    await user.click(screen.getByRole("radio", { name: "只看爸爸的" }))
    expect(await screen.findByText("沒有爸爸的交易或股利紀錄。")).toBeInTheDocument()
  })

  it("自己的帳本照原本寫「你」「我」", async () => {
    const inst = await api.getInstrument("2330.TW")
    vi.spyOn(api, "getNews").mockResolvedValue([])
    vi.spyOn(api, "getEvents").mockResolvedValue([
      { date: "2026-12-18", type: "ex_dividend", title: "除息", detail: null, url: null, mine: true, amount_estimate: 12500 },
    ])
    renderInRouter(<EventsTab inst={inst} position={null} markers={[]} />)
    expect(await screen.findByText(/你可領約/, undefined, T)).toBeInTheDocument()
    expect(screen.getByRole("radio", { name: "只看我的" })).toBeInTheDocument()
  })
})

describe("查看模式：橫幅", () => {
  it("手機：橫幅黏在頂端，sticky 分頁列排在它下面", async () => {
    useViewAs.getState().set(DAD)
    renderApp("/")
    const banner = await screen.findByRole("region", { name: "查看模式" }, T)
    expect(banner.className).toMatch(/\bsticky\b/)
    expect(banner.className).toMatch(/\btop-0\b/)
    const shell = banner.closest<HTMLElement>("[style]")!
    expect(shell.style.getPropertyValue("--sticky-top")).toBe("3.75rem")
  })

  it("範圍跟著授權者目前的設定，不是進入時的快照", async () => {
    // 進入時是兩個帳戶；授權者之後只留「元大・爸爸」（mock 的 dlg_dad）
    useViewAs.getState().set({ ...DAD, accounts: [...DAD.accounts, { id: "acc_dad_fubon", name: "富邦・退休金" }] })
    renderApp("/")
    const banner = await screen.findByRole("region", { name: "查看模式" }, T)
    await waitFor(() => expect(within(banner).getByText(/範圍：/).textContent).toBe("範圍：元大・爸爸"), T)
    expect(useViewAs.getState().target?.accounts.map((a) => a.name)).toEqual(["元大・爸爸"])
  })
})
