import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest"
import { useAi } from "@/ai/store"
import { createAppRouter } from "@/router"

/**
 * 商品清單補上全部台股 ETF 與 SEC 的美股（待決定事項 1-4、1-5）：搜尋結果標「沒有報價」，
 * 只有英文名的美股（MSFT）與收盤檔裡的 ETF（00981A）個股頁都打得開。
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
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null })
beforeEach(() => act(resetAi))
afterEach(() => {
  cleanup()
  act(resetAi)
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
  return router
}

describe("搜尋：美股標「沒有報價」，收盤檔的 ETF 搜得到", () => {
  it("輸入 tsla：Tesla 那一列寫「美股・沒有報價」；按下去打開個股頁", async () => {
    const user = userEvent.setup()
    const router = renderApp("/")
    await user.click(await screen.findByRole("button", { name: "搜尋股票" }, T))
    const dialog = await screen.findByRole("dialog", { name: "搜尋股票與功能" }, T)
    await user.type(within(dialog).getByRole("combobox"), "tsla")
    const hit = await within(dialog).findByRole("option", { name: /TSLA/ }, T)
    expect(hit.textContent).toContain("Tesla, Inc.")
    expect(hit.textContent).toContain("美股・沒有報價")
    await user.click(hit)
    await waitFor(() => expect(router.state.location.pathname).toBe("/stock/TSLA"))
  })

  it("輸入 00981：主動式 ETF 那一列寫「上市・ETF」", async () => {
    const user = userEvent.setup()
    renderApp("/")
    await user.click(await screen.findByRole("button", { name: "搜尋股票" }, T))
    const dialog = await screen.findByRole("dialog", { name: "搜尋股票與功能" }, T)
    await user.type(within(dialog).getByRole("combobox"), "00981")
    const hit = await within(dialog).findByRole("option", { name: /00981A/ }, T)
    expect(hit.textContent).toContain("主動統一台股增長")
    expect(hit.textContent).toContain("上市・ETF")
  })
})

describe("個股頁", () => {
  it("MSFT（SEC 代號表，只有英文名）：顯示名稱與「沒有報價」", async () => {
    renderApp("/stock/MSFT")
    expect(await screen.findByText("沒有報價", undefined, T)).toBeInTheDocument()
    expect((await screen.findAllByText("MICROSOFT CORP", undefined, T)).length).toBeGreaterThan(0)
  })

  it("00981A（收盤檔的 ETF）：有收盤價", async () => {
    renderApp("/stock/00981A.TW")
    expect((await screen.findAllByText("主動統一台股增長", undefined, T)).length).toBeGreaterThan(0)
    expect(screen.queryByText("沒有報價")).toBeNull()
  })
})
