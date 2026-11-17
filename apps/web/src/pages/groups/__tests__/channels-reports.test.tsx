import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import type { ForliosaApi } from "@/api/types"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 群組頻道的市場報告推播（2026-11-17）：對全站公開時每個頻道多三個開關（所有群組都能開；盤前、盤後預設關，週報預設開），
 * 只有擁有者能改；試跑期間看不到。群組「報告」分頁：今天的盤前重點出來了、最新的日報是前一個交易日的，那一則就是「昨日你的群組」。
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

describe("頻道的三個報告開關", () => {
  it("對全站公開：擁有者看到三個開關（盤前、盤後關，週報開）＋一行說明，改了送出；試跑期間沒有", async () => {
    const user = userEvent.setup()
    const spies = mount({ reports: "public" })
    renderApp("/groups/grp_family?tab=channels")
    const discord = (await screen.findByRole("heading", { name: "Discord" }, T)).closest("section")!
    const pre = await within(discord).findByRole("switch", { name: "盤前重點（交易日 7:30）" }, T)
    expect(pre).toHaveAttribute("aria-checked", "false")
    expect(within(discord).getByRole("switch", { name: "盤後重點（交易日 16:00）" })).toHaveAttribute("aria-checked", "false")
    expect(within(discord).getByRole("switch", { name: "市場週報（週日 18:00）" })).toHaveAttribute("aria-checked", "true")
    expect(within(discord).getByText("推到頻道的是文字與連結，報告本文人人相同。")).toBeInTheDocument()
    await user.click(pre)
    await waitFor(() => expect(spies.patchDiscord).toHaveBeenCalledWith("grp_family", { notify_premarket: true }), T)
    await waitFor(() => expect(within(discord).getByRole("switch", { name: "盤前重點（交易日 7:30）" })).toHaveAttribute("aria-checked", "true"), T)
  })

  it("試跑期間（管理員也一樣）：沒有報告的開關", async () => {
    mount()
    renderApp("/groups/grp_family?tab=channels")
    const discord = (await screen.findByRole("heading", { name: "Discord" }, T)).closest("section")!
    await within(discord).findByRole("switch", { name: "交易動態" }, T)
    expect(within(discord).queryByRole("switch", { name: /盤前重點/ })).toBeNull()
    expect(document.querySelector("[data-report-toggles]")).toBeNull()
  })

  it("不是擁有者：看得到，不能改", async () => {
    mount({ reports: "public" })
    renderApp("/groups/grp_friends?tab=channels")
    const telegram = (await screen.findByRole("heading", { name: "Telegram" }, T)).closest("section")!
    const weekly = await within(telegram).findByRole("switch", { name: "市場週報（週日 18:00）" }, T)
    expect(weekly).toHaveAttribute("aria-disabled", "true")
  })
})

describe("群組的報告分頁：昨日你的群組", () => {
  it("今天的盤前重點出來了、最新的日報是前一個交易日的：那一則叫「昨日你的群組」，旁邊連到盤前重點", async () => {
    mount({ reports: "public", market: "open" })
    renderApp("/groups/grp_family?tab=digests")
    const heading = await screen.findByRole("heading", { level: 2, name: "昨日你的群組" }, T)
    const article = heading.closest("article")!
    expect(within(article).getByText(/^11\/12（四）・/)).toBeInTheDocument()
    expect(within(article).getByRole("link", { name: "盤前重點 11/13（五） →" })).toHaveAttribute("href", "/market/reports/mrp_premarket_20261113")
    // 較早的日報照舊寫日期
    expect(screen.getByRole("heading", { level: 2, name: "11/11（三） 日報" })).toBeInTheDocument()
  })

  it("日報就是今天的（收盤後）：照舊寫「11/12（四） 日報」", async () => {
    mount({ reports: "public" })
    renderApp("/groups/grp_family?tab=digests")
    expect(await screen.findByRole("heading", { level: 2, name: "11/12（四） 日報" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { level: 2, name: "昨日你的群組" })).toBeNull()
  })
})
