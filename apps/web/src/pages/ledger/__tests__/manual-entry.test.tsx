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
 * 手動記帳（產品負責人 2026-11-13、11-14）：帳本的分段旁邊有「記一筆」，直接開輸入框（不經過 AI 面板）。
 * 輸入方式照 Google 財經：選一檔 → 股數、買進日期、買進價格，可以「再加一筆買進」；沒有稅費試算。
 * 賣出、股利與其他類型按下面的連結開完整表單；完整表單可以勾「存檔後再記一筆」。
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
  useUi.getState().closeReduce()
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
    const dialog = await screen.findByRole("dialog", {}, T)
    expect(within(dialog).getByRole("heading", { name: "記一筆" })).toBeInTheDocument()
    // AI 面板沒有被叫出來問「買賣了什麼？」
    expect(screen.queryByText(/買賣了什麼/)).toBeNull()
    // 簡單的輸入：沒有類型、備註、稅費試算
    expect(within(dialog).queryByText("稅費試算")).toBeNull()
    expect(within(dialog).queryByRole("group", { name: "交易類型" })).toBeNull()
    expect(within(dialog).getByRole("textbox", { name: "買進價格" })).toBeInTheDocument()
  })

  it("選一檔、填兩筆買進 → 新增：記成兩筆買進，對話框關閉", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    useUi.getState().openTradeForm({ symbol: "2330" })
    const dialog = await screen.findByRole("dialog", {}, T)
    const form = within(dialog)
    await waitFor(() => expect(form.getByText("台積電")).toBeInTheDocument(), T)
    const before = (await api.listTransactions({ limit: 200 })).items.length
    // 沒填就按新增：說哪一格要填，不送出
    await userEvent.click(form.getByRole("button", { name: "新增" }))
    expect(form.getByText("請輸入股數")).toBeInTheDocument()
    expect(form.getByText("請輸入價格")).toBeInTheDocument()

    const first = dialog.querySelector<HTMLInputElement>("#lot-qty-0")!
    await userEvent.type(first, first.getAttribute("aria-label") === "張數" ? "1" : "1000")
    fireEvent.change(dialog.querySelector("#lot-date-0")!, { target: { value: "2024-03-05" } })
    await userEvent.type(dialog.querySelector("#lot-price-0")!, "700")
    await userEvent.click(form.getByRole("button", { name: "再加一筆買進" }))
    const second = await form.findByRole("textbox", { name: /第 2 筆的(張數|股數)/ })
    // 新的一筆沿用上一筆的日期
    expect((form.getByLabelText("第 2 筆的買進日期") as HTMLInputElement).value).toBe("2024-03-05")
    await userEvent.type(second, second.getAttribute("aria-label")!.endsWith("張數") ? "2" : "2000")
    fireEvent.change(form.getByLabelText("第 2 筆的買進日期"), { target: { value: "2024-04-10" } })
    await userEvent.type(form.getByRole("textbox", { name: "第 2 筆的買進價格" }), "760")
    await userEvent.click(form.getByRole("button", { name: "新增" }))

    await waitFor(() => expect(useUi.getState().tradeForm.open).toBe(false), T)
    const after = (await api.listTransactions({ limit: 200 })).items
    expect(after.length).toBe(before + 2)
    const added = after.filter((t) => t.symbol === "2330.TW" && (t.trade_date === "2024-03-05" || t.trade_date === "2024-04-10"))
    expect(added.map((t) => [t.trade_date, t.type, t.quantity, t.price]).sort()).toEqual([
      ["2024-03-05", "buy", 1000, 700],
      ["2024-04-10", "buy", 2000, 760],
    ])
  })

  it("「賣出、股利或其他」開完整表單，選好的股票留著", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    useUi.getState().openTradeForm({ symbol: "2330" })
    const dialog = await screen.findByRole("dialog", {}, T)
    await waitFor(() => expect(within(dialog).getByText("台積電")).toBeInTheDocument(), T)
    await userEvent.click(within(dialog).getByRole("button", { name: "賣出、股利或其他" }))
    const full = await screen.findByRole("dialog", {}, T)
    expect(await within(full).findByRole("heading", { name: "記一筆交易" }, T)).toBeInTheDocument()
    expect(await within(full).findByText("稅費試算", {}, T)).toBeInTheDocument()
    await waitFor(() => expect(within(full).getByText("台積電")).toBeInTheDocument(), T)
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

describe("完整表單：存檔後再記一筆", () => {
  it("勾了之後存檔，表單留著：帳戶、類型、日期不動，股票、數量、價格清空", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    useUi.getState().openTradeForm({ symbol: "2330", full: true })
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

describe("減少持股（賣出不用開表單）", () => {
  it("只填股數：用最新的收盤價、今天的日期記成一筆賣出；超過持有的股數會擋下", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    const held = (await api.getHoldings()).find((h) => h.symbol === "2317.TW")!
    const quote = await api.getQuote("2317.TW")
    useUi.getState().openReduce("2317.TW")
    const dialog = await screen.findByRole("dialog", {}, T)
    const form = within(dialog)
    expect(await form.findByRole("heading", { name: "減少持股" }, T)).toBeInTheDocument()
    await form.findByText(/記成賣出。$/, {}, T)
    const qty = dialog.querySelector<HTMLInputElement>("#reduce-qty")!
    const inLots = dialog.querySelector('label[for="reduce-qty"]')!.textContent!.endsWith("張數")
    // 超過持有
    await userEvent.type(qty, String(inLots ? held.quantity / 1000 + 1 : held.quantity + 1000))
    await userEvent.click(form.getByRole("button", { name: "賣出" }))
    expect(form.getByText(/^最多 /)).toBeInTheDocument()
    await userEvent.clear(qty)
    await userEvent.type(qty, inLots ? "1" : "1000")
    const before = (await api.listTransactions({ limit: 200 })).items.length
    await userEvent.click(form.getByRole("button", { name: "賣出" }))
    await waitFor(() => expect(useUi.getState().reduce.open).toBe(false), T)
    const after = (await api.listTransactions({ limit: 200 })).items
    expect(after.length).toBe(before + 1)
    const sell = after.find((t) => t.type === "sell" && t.symbol === "2317.TW" && t.quantity === 1000 && t.price === quote.price)
    expect(sell).toBeTruthy()
  })

  it("「全部賣出」先把股數填成全部；「改日期或價格」開完整表單、已經選在賣出", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    const held = (await api.getHoldings()).find((h) => h.symbol === "6488.TWO")!
    useUi.getState().openReduce("6488.TWO", true)
    const dialog = await screen.findByRole("dialog", {}, T)
    const qty = await waitFor(() => {
      const el = dialog.querySelector<HTMLInputElement>("#reduce-qty")
      expect(el).not.toBeNull()
      return el!
    }, T)
    await waitFor(() => expect([String(held.quantity), String(held.quantity / 1000)]).toContain(qty.value), T)
    await userEvent.click(within(dialog).getByRole("button", { name: "改日期或價格" }))
    const full = await screen.findByRole("dialog", {}, T)
    expect(await within(full).findByRole("heading", { name: "記一筆交易" }, T)).toBeInTheDocument()
    expect(await within(full).findByRole("radio", { name: "賣出" }, T)).toBeChecked()
  })

  it("持股有零股（1 張 500 股）：改收股數，「全部」填 1500；欄位下面寫換算", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    const held = (await api.getHoldings()).find((h) => h.symbol === "2330.TW")!
    expect(held.quantity % 1000).not.toBe(0)
    useUi.getState().openReduce("2330.TW")
    const dialog = await screen.findByRole("dialog", {}, T)
    await within(dialog).findByText(/記成賣出。$/, {}, T)
    expect(dialog.querySelector('label[for="reduce-qty"]')!.textContent).toBe("賣出的股數")
    await userEvent.click(within(dialog).getByRole("button", { name: "全部" }))
    expect((dialog.querySelector("#reduce-qty") as HTMLInputElement).value).toBe(String(held.quantity))
    expect(within(dialog).getByText(/^\d+ 張( \d+ 股)?$/)).toBeInTheDocument()
    await userEvent.clear(dialog.querySelector("#reduce-qty")!)
    await userEvent.type(dialog.querySelector("#reduce-qty")!, String(held.quantity + 1))
    await userEvent.click(within(dialog).getByRole("button", { name: "賣出" }))
    expect(within(dialog).getByText(`最多 ${new Intl.NumberFormat("zh-TW").format(held.quantity)} 股`)).toBeInTheDocument()
  })

  it("持倉的每一列有動作選單：加碼、減少持股、全部賣出", async () => {
    renderApp("/")
    const table = await screen.findByRole("table", { name: "持倉" }, T)
    await userEvent.click(await within(table).findByRole("button", { name: "鴻海的動作" }, T))
    const menu = await screen.findByRole("menu", {}, T)
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["加碼", "減少持股", "全部賣出"])
    await userEvent.click(within(menu).getByRole("menuitem", { name: "全部賣出" }))
    expect(useUi.getState().reduce).toMatchObject({ open: true, symbol: "2317.TW", all: true })
  })
})
