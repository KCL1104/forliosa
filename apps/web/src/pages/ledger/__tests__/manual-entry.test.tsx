import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import { api } from "@/api"
import { useViewAs } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { createAppRouter } from "@/router"

/**
 * 手動記帳的入口（產品負責人 2026-11-13：「應該要有手動匯入的功能，只有 AI 匯入不太對」）：
 * 帳本的分段旁邊有「記一筆」，直接開表單（不經過 AI 面板）；表單可以勾「存檔後再記一筆」連續補好幾筆。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  // 手機版的表單在 Vaul 抽屜裡：jsdom 沒有 pointer capture
  Element.prototype.setPointerCapture ??= () => {}
  Element.prototype.releasePointerCapture ??= () => {}
  Element.prototype.hasPointerCapture ??= () => false
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  useViewAs.getState().set(null)
  useUi.getState().closeTradeForm()
})

const T = { timeout: 4000 }

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

describe("帳本的「記一筆」", () => {
  it("在持倉分段就看得到，按了直接開表單，不會先到 AI 面板", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    const buttons = screen.getAllByRole("button", { name: "記一筆" })
    expect(buttons.length).toBeGreaterThan(0)
    expect(useUi.getState().tradeForm.open).toBe(false)
    await userEvent.click(buttons[0]!)
    expect(useUi.getState().tradeForm.open).toBe(true)
    expect(await screen.findByRole("heading", { name: "記一筆交易" }, T)).toBeInTheDocument()
    // AI 面板沒有被叫出來問「買賣了什麼？」
    expect(screen.queryByText(/買賣了什麼/)).toBeNull()
  })

  it("交易分段不再另外放一顆「記一筆」（工具列那一顆每個分段都在）", async () => {
    renderApp("/?view=transactions")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    const panel = document.getElementById("ledger-view")!
    await waitFor(() => expect(within(panel).queryAllByRole("row").length + within(panel).queryAllByRole("button").length).toBeGreaterThan(0), T)
    expect(within(panel).queryByRole("button", { name: "記一筆" })).toBeNull()
    expect(screen.getAllByRole("button", { name: "記一筆" }).length).toBeGreaterThan(0)
  })
})

describe("表單：存檔後再記一筆", () => {
  it("勾了之後存檔，表單留著：帳戶、類型、日期不動，股票、數量、價格清空", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    useUi.getState().openTradeForm({ symbol: "2330" })
    const dialog = await screen.findByRole("dialog", {}, T)
    const form = within(dialog)
    await waitFor(() => expect(form.getByText("台積電")).toBeInTheDocument(), T)
    const before = (await api.listTransactions({ limit: 200 })).items.length
    fireEvent.change(dialog.querySelector("#trade-date")!, { target: { value: "2024-03-05" } })
    await userEvent.type(dialog.querySelector("#trade-qty")!, "2")
    await userEvent.type(dialog.querySelector("#trade-price")!, "700")
    await userEvent.click(form.getByRole("checkbox", { name: "存檔後再記一筆" }))
    await userEvent.click(form.getByRole("button", { name: "儲存" }))
    await waitFor(async () => expect((await api.listTransactions({ limit: 200 })).items.length).toBe(before + 1), T)
    // 表單還開著，可以接著記下一筆
    expect(useUi.getState().tradeForm.open).toBe(true)
    await waitFor(() => expect((dialog.querySelector("#trade-qty") as HTMLInputElement).value).toBe(""), T)
    expect((dialog.querySelector("#trade-price") as HTMLInputElement).value).toBe("")
    expect((dialog.querySelector("#trade-date") as HTMLInputElement).value).toBe("2024-03-05")
    expect(form.queryByText("台積電")).toBeNull()
    expect(form.getByRole("checkbox", { name: "存檔後再記一筆" })).toBeChecked()
  })
})
