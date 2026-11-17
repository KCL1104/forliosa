import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api, appToday } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { ApiError, type ForliosaApi } from "@/api/types"
import { useViewAs, type ViewAsTarget } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { Toaster } from "@/components/ui/sonner"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"
import { recordBreakdown } from "../delete-holding"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))
// 刪掉一檔之後總資產會變：NumberFlow（web component）在 jsdom 裡更新數字會丟錯，換成一般的字
vi.mock("@number-flow/react", () => ({
  default: ({ value, format, locales }: { value: number; format?: Intl.NumberFormatOptions; locales?: string }) => <span>{new Intl.NumberFormat(locales, format).format(value)}</span>,
}))

/**
 * 刪除這檔（產品負責人 2026-11-17：「還要有刪除股票的功能」）：持倉的「⋯」最後一項（上面一條格線）、展開後最下面淡墨的
 * 文字動作（手機沒有「⋯」）→ 確認框說清楚刪什麼（哪個帳戶、幾筆、各幾筆），有定期定額時可以一起暫停 → 通知。
 * 查看別人的資產時都沒有。
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
const resetPrefs = () => {
  useLedgerPrefs.setState({ columns: DEFAULT_COLUMNS, showTrend: true, pinned: [], showClosed: false, phoneLine: "day" })
  usePrefs.setState({ privacyMode: false, quantityUnit: "lot" })
}
beforeEach(() => act(resetPrefs))
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(() => {
    resetPrefs()
    useViewAs.setState({ target: null })
    useUi.getState().closeDeleteHolding()
  })
})

const T = { timeout: 8000 }
const TW = "acc_01JSINOPAC"

/** 每個測試一份新的 mock（刪掉的紀錄、暫停的定期定額互不影響） */
function mount(options: MockOptions = {}) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  return adapter
}

function renderApp(path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  )
}

const user = () => userEvent.setup({ pointerEventsCheck: 0 })

async function holdingsTable() {
  const table = await screen.findByRole("table", { name: "持倉" }, T)
  await within(table).findByRole("link", { name: "台積電" }, T)
  return table
}

/** 從桌面的「⋯」打開確認框 */
async function openFromMenu(name: string) {
  const table = await holdingsTable()
  await user().click(within(table).getByRole("button", { name: `${name}的動作` }))
  const menu = await screen.findByRole("menu", {}, T)
  await user().click(within(menu).getByRole("menuitem", { name: "刪除這檔" }))
  return screen.findByRole("alertdialog", {}, T)
}

/** 這個帳戶這一檔的紀錄（所有類型），和確認框數的同一份 */
async function recordsOf(accountId: string, symbol: string) {
  return (await api.listTransactions({ account_id: accountId, symbol, limit: 200 })).items
}

describe("入口", { timeout: 20_000 }, () => {
  it("持倉的「⋯」：最後一項是「刪除這檔」，上面一條格線和加碼、減少持股、全部賣出隔開", async () => {
    mount()
    renderApp()
    const table = await holdingsTable()
    await user().click(within(table).getByRole("button", { name: "台積電的動作" }))
    const menu = await screen.findByRole("menu", {}, T)
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["加碼", "減少持股", "全部賣出", "刪除這檔"])
    const separator = within(menu).getByRole("separator")
    const last = within(menu).getByRole("menuitem", { name: "刪除這檔" })
    expect(separator.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(separator.compareDocumentPosition(within(menu).getByRole("menuitem", { name: "全部賣出" })) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    // 不用紅色（紅色是「漲」）：和其他項目同一個樣子
    expect(last).toHaveAttribute("data-variant", "default")
    await user().click(last)
    expect(useUi.getState().deleteHolding).toMatchObject({ open: true, symbol: "2330.TW" })
  })

  it("手機（沒有「⋯」）：展開一檔，最下面淡墨的「刪除這檔」打開同一個確認框", async () => {
    mount()
    renderApp()
    const phone = await screen.findByRole("list", { name: "持倉" }, T)
    await user().click(await within(phone).findByRole("button", { name: "展開台積電的每一筆買賣" }, T))
    await within(phone).findByRole("list", { name: "台積電的每一筆買賣" }, T)
    const action = within(phone).getByRole("button", { name: "刪除這檔" })
    expect(action).toHaveClass("text-ink-2")
    // 在「再加一筆買進」「減少持股」後面
    const add = within(phone).getByRole("button", { name: "再加一筆買進" })
    expect(add.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await user().click(action)
    const dialog = await screen.findByRole("alertdialog", {}, T)
    expect(dialog).toHaveTextContent(/^刪除台積電在「永豐・一般」的/)
  })
})

describe("確認框與刪除", { timeout: 20_000 }, () => {
  it("說清楚刪什麼：哪個帳戶、幾筆（含股利）、會重算、不能復原；按下後只刪那個帳戶那一檔，通知筆數，持倉少一檔", async () => {
    mount()
    const rows = await recordsOf(TW, "2330.TW")
    const trades = rows.filter((t) => t.type === "buy" || t.type === "sell").length
    const dividends = rows.filter((t) => t.type === "cash_dividend" || t.type === "stock_dividend").length
    expect(trades).toBeGreaterThan(0)
    expect(dividends).toBeGreaterThan(0) // 示範帳本的台積電有自動入帳的股利：也算在要刪的紀錄裡
    renderApp()
    const dialog = await openFromMenu("台積電")
    const title = within(dialog).getByRole("heading")
    await waitFor(() => expect(title).toHaveTextContent(`刪除台積電在「永豐・一般」的 ${rows.length} 筆紀錄？`), T)
    expect(dialog).toHaveTextContent(`包括 ${trades} 筆買賣、${dividends} 筆股利。持股、損益與績效會重新計算，刪除後無法復原。`)
    expect(dialog).toHaveTextContent("賣掉了就用「全部賣出」，損益才會留著。")
    // 台積電沒有定期定額：沒有勾選；只有一個帳戶：沒有帳戶的選項
    expect(within(dialog).queryByRole("checkbox")).toBeNull()
    expect(within(dialog).queryByRole("radio")).toBeNull()
    const others = (await api.listTransactions({ limit: 200 })).items.filter((t) => !(t.account_id === TW && t.symbol === "2330.TW")).length

    await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
    await waitFor(() => expect(api.deleteHolding).toHaveBeenCalledWith(TW, "2330.TW", { pausePlans: false }), T)
    expect(await screen.findByText(`已刪除台積電的 ${rows.length} 筆紀錄`, {}, T)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), T)
    const table = screen.getByRole("table", { name: "持倉" })
    await waitFor(() => expect(within(table).queryByRole("link", { name: "台積電" })).toBeNull(), T)
    expect(within(table).getByRole("link", { name: "鴻海" })).toBeInTheDocument()
    // 別的股票、別的帳戶一筆都沒少；不是賣出，所以也沒有多一筆
    expect(await recordsOf(TW, "2330.TW")).toEqual([])
    expect((await api.listTransactions({ limit: 200 })).items.length).toBe(others)
  })

  it("有定期定額的那一檔（0050）：預設勾著「同時暫停」，寫出是哪一個；刪除後計畫暫停（不是刪掉），通知說已暫停", async () => {
    mount()
    renderApp()
    const dialog = await openFromMenu("元大台灣50")
    const box = await within(dialog).findByRole("checkbox", { name: /同時暫停這一檔的定期定額/ }, T)
    expect(box).toBeChecked()
    expect(box.closest("label")).toHaveTextContent("每月 6 日 NT$10,000")
    await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
    await waitFor(() => expect(api.deleteHolding).toHaveBeenCalledWith(TW, "0050.TW", { pausePlans: true }), T)
    expect(await screen.findByText("這一檔的定期定額已暫停。", {}, T)).toBeInTheDocument()
    const plan = (await api.listRecurring()).find((p) => p.symbol === "0050.TW")!
    expect(plan.active).toBe(false)
  })

  it("取消勾選：計畫照常進行，通知說下次扣款日會再提出草稿（附「到設定」）", async () => {
    mount()
    renderApp()
    const dialog = await openFromMenu("元大台灣50")
    await user().click(await within(dialog).findByRole("checkbox", {}, T))
    await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
    await waitFor(() => expect(api.deleteHolding).toHaveBeenCalledWith(TW, "0050.TW", { pausePlans: false }), T)
    expect(await screen.findByText("這一檔的定期定額還在進行，下次扣款日會再提出草稿。", {}, T)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "到設定" })).toBeInTheDocument()
    expect((await api.listRecurring()).find((p) => p.symbol === "0050.TW")!.active).toBe(true)
  })

  it("好幾個帳戶都持有這一檔：一列一個帳戶（筆數），預設持有的第一個；選另一個，標題與刪的帳戶跟著換", async () => {
    mount()
    const second = await api.createAccount({ name: "國泰・一般", broker: "國泰證券", currency: "TWD" })
    await api.createTransaction({ account_id: second.id, symbol: "2330.TW", type: "buy", trade_date: "2025-03-03", quantity: 100, price: 900 })
    const mine = await recordsOf(TW, "2330.TW")
    // 國泰那一筆買進之後的除息也自動入帳了：買進 1 筆＋股利
    const theirs = await recordsOf(second.id, "2330.TW")
    expect(theirs.length).toBeGreaterThan(1)
    renderApp()
    const dialog = await openFromMenu("台積電")
    const radios = await within(dialog).findAllByRole("radio", {}, T)
    expect(radios.map((r) => r.closest("label")!.textContent)).toEqual([`永豐・一般${mine.length} 筆`, `國泰・一般${theirs.length} 筆`])
    expect(radios[0]).toBeChecked()
    await user().click(radios[1]!)
    expect(within(dialog).getByRole("heading")).toHaveTextContent(`刪除台積電在「國泰・一般」的 ${theirs.length} 筆紀錄？`)
    await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
    await waitFor(() => expect(api.deleteHolding).toHaveBeenCalledWith(second.id, "2330.TW", { pausePlans: false }), T)
    expect(await recordsOf(TW, "2330.TW")).toHaveLength(mine.length)
  })

  it("只有第二個帳戶持有、第一個帳戶已經賣光：預設第二個，紀錄讀完也不會換；選已賣光的帳戶時改說已實現損益也會刪", async () => {
    const adapter = mount()
    const held = (await api.getHoldings()).find((h) => h.symbol === "2330.TW")!
    // 永豐（帳戶清單第一個）全部賣掉：只剩紀錄與已實現損益；國泰買進、現在持有
    await api.createTransaction({ account_id: TW, symbol: "2330.TW", type: "sell", trade_date: appToday(), quantity: held.quantity, price: 1000 })
    const second = await api.createAccount({ name: "國泰・一般", broker: "國泰證券", currency: "TWD" })
    await api.createTransaction({ account_id: second.id, symbol: "2330.TW", type: "buy", trade_date: "2025-03-03", quantity: 100, price: 900 })
    expect((await api.getHoldings()).find((h) => h.symbol === "2330.TW")!.account_ids).toEqual([second.id])
    const theirs = await recordsOf(second.id, "2330.TW")
    // 這一檔的紀錄先不讓它讀完：看讀完前後預設有沒有換
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    vi.spyOn(api, "listTransactions").mockImplementation(async (q) => {
      if (q?.symbol === "2330.TW") await gate
      return adapter.listTransactions(q)
    })
    renderApp()
    const dialog = await openFromMenu("台積電")
    const title = within(dialog).getByRole("heading")
    expect(title).toHaveTextContent("刪除台積電在「國泰・一般」的紀錄？")
    expect(dialog).toHaveAccessibleDescription(expect.stringContaining("賣掉了就用「全部賣出」，損益才會留著。"))
    act(() => release())
    const radios = await within(dialog).findAllByRole("radio", {}, T)
    expect(radios.map((r) => r.closest("label")!.textContent!.replace(/\d+ 筆$/, ""))).toEqual(["永豐・一般", "國泰・一般"])
    expect(radios[1]).toBeChecked()
    expect(title).toHaveTextContent(`刪除台積電在「國泰・一般」的 ${theirs.length} 筆紀錄？`)
    // 已經賣光的帳戶：沒有持股可以「全部賣出」，刪掉就是丟掉已實現損益——說出來
    await user().click(radios[0]!)
    expect(title).toHaveTextContent(/^刪除台積電在「永豐・一般」的 \d+ 筆紀錄？$/)
    expect(dialog).toHaveAccessibleDescription(expect.stringContaining("這個帳戶已實現的損益也會一起刪掉。"))
    expect(dialog).not.toHaveTextContent("賣掉了就用「全部賣出」")
  })

  it("提示「全部賣出」那句也在確認框的說明裡（aria-describedby），讀屏會唸到", async () => {
    mount()
    renderApp()
    const dialog = await openFromMenu("鴻海")
    await waitFor(() => expect(within(dialog).getByRole("heading")).toHaveTextContent(/筆紀錄？$/), T)
    expect(dialog).toHaveAccessibleDescription(/持股、損益與績效會重新計算，刪除後無法復原。\s*賣掉了就用「全部賣出」，損益才會留著。$/)
  })

  it("伺服器拒絕：確認框留著，就地說「沒有刪除，紀錄都還在。」＋原因", async () => {
    mount()
    vi.spyOn(api, "deleteHolding").mockRejectedValue(new ApiError(500, "internal_error", "伺服器出了問題，等一下再試一次。"))
    renderApp()
    const dialog = await openFromMenu("鴻海")
    await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
    expect(await within(dialog).findByRole("alert", {}, T)).toHaveTextContent("沒有刪除，紀錄都還在。伺服器出了問題，等一下再試一次。")
    expect(screen.getByRole("alertdialog")).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "刪除這檔" })).toBeEnabled()
  })

  it("已經在別的地方刪掉了（404 no_records）：當成刪好了——關掉、通知已經不在了、持倉重抓", async () => {
    const adapter = mount()
    renderApp()
    const dialog = await openFromMenu("鴻海")
    await waitFor(() => expect(within(dialog).getByRole("heading")).toHaveTextContent(/筆紀錄？$/), T)
    // 另一個分頁先刪了（不經過畫面）
    await adapter.deleteHolding(TW, "2317.TW")
    await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
    expect(await screen.findByText("鴻海在「永豐・一般」的紀錄已經不在了", {}, T)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), T)
    expect(screen.queryByText(/沒有刪除/)).toBeNull()
    const table = screen.getByRole("table", { name: "持倉" })
    await waitFor(() => expect(within(table).queryByRole("link", { name: "鴻海" })).toBeNull(), T)
  })

  it("連不上伺服器：不說「紀錄都還在」（不知道刪了沒有）、不露出英文錯誤；取消時重抓持倉", async () => {
    mount()
    vi.spyOn(api, "deleteHolding").mockRejectedValue(new TypeError("Failed to fetch"))
    renderApp()
    const dialog = await openFromMenu("鴻海")
    await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
    const alert = await within(dialog).findByRole("alert", {}, T)
    expect(alert).toHaveTextContent("連不上伺服器，不確定有沒有刪除。請檢查網路後再試一次。")
    expect(alert).not.toHaveTextContent("Failed to fetch")
    expect(alert).not.toHaveTextContent("紀錄都還在")
    const before = vi.mocked(api.getHoldings).mock.calls.length
    await user().click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(vi.mocked(api.getHoldings).mock.calls.length).toBeGreaterThan(before), T)
  })

  it("刪掉之後焦點留在持倉表裡（那一列和它的「⋯」已經不在了），不會掉回頁首", async () => {
    mount()
    // jsdom 沒有版面：讓桌面的表格算「看得到」（手機清單在桌面是藏著的）
    const rects = Object.getOwnPropertyDescriptor(HTMLTableElement.prototype, "getClientRects")
    Object.defineProperty(HTMLTableElement.prototype, "getClientRects", { configurable: true, value: () => [new DOMRect(0, 0, 100, 100)] })
    try {
      renderApp()
      const dialog = await openFromMenu("鴻海")
      await waitFor(() => expect(within(dialog).getByRole("heading")).toHaveTextContent(/筆紀錄？$/), T)
      await user().click(within(dialog).getByRole("button", { name: "刪除這檔" }))
      await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), T)
      const table = screen.getByRole("table", { name: "持倉" })
      await waitFor(() => expect(within(table).queryByRole("link", { name: "鴻海" })).toBeNull(), T)
      // 表格裡第一個可以按的（base-ui 把焦點交給容器裡第一個 tabbable），不是 body
      await waitFor(() => expect(table.contains(document.activeElement)).toBe(true), T)
    } finally {
      if (rects) Object.defineProperty(HTMLTableElement.prototype, "getClientRects", rects)
      else delete (HTMLTableElement.prototype as { getClientRects?: unknown }).getClientRects
    }
  })

  it("筆數只有一種時不另外列（標題的筆數就是那一種）", () => {
    expect(recordBreakdown([{ type: "buy" }, { type: "sell" }])).toBeNull()
    expect(recordBreakdown([{ type: "buy" }, { type: "cash_dividend" }, { type: "split" }])).toBe("包括 1 筆買賣、1 筆股利、1 筆其他紀錄。")
  })
})

describe("查看別人的資產（唯讀）", { timeout: 20_000 }, () => {
  const DAD: ViewAsTarget = {
    delegation_id: "dlg_dad",
    owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null },
    scope: "accounts",
    accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }],
  }

  it("沒有「⋯」、展開後沒有「刪除這檔」，也沒有確認框", async () => {
    mount()
    act(() => useViewAs.getState().set(DAD))
    renderApp()
    const table = await screen.findByRole("table", { name: "持倉" }, T)
    const expandButtons = await within(table).findAllByRole("button", { name: /^展開.+的每一筆買賣$/ }, T)
    expect(within(table).queryAllByRole("button", { name: /的動作$/ })).toEqual([])
    await user().click(expandButtons[0]!)
    await within(table).findAllByRole("listitem", {}, T)
    expect(screen.queryByRole("button", { name: "刪除這檔" })).toBeNull()
    act(() => useUi.getState().openDeleteHolding("2330.TW"))
    expect(screen.queryByRole("alertdialog")).toBeNull()
    expect(api.deleteHolding).not.toHaveBeenCalled()
  })
})
