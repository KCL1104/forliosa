import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { qk } from "@/api/queries"
import { ApiError, type ForliosaApi } from "@/api/types"
import { useViewAs, type ViewAsTarget } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { Toaster } from "@/components/ui/sonner"
import { DEFAULT_COLUMNS, useLedgerPrefs } from "@/pages/ledger/ledger-prefs"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { CLEAR_RECORDS_CONFIRMATION } from "../ClearRecordsDialog"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))
// 清完之後總資產會變：NumberFlow（web component）在 jsdom 裡更新數字會丟錯，換成一般的字
vi.mock("@number-flow/react", () => ({
  default: ({ value, format, locales }: { value: number; format?: Intl.NumberFormatOptions; locales?: string }) => <span>{new Intl.NumberFormat(locales, format).format(value)}</span>,
}))

/**
 * 清除所有持倉（產品負責人 2026-11-17：「也要有清除所有持倉的功能」）：設定「帳號與資料」的「清除…」（和帳本「自訂」最下面的連結）→
 * 確認框選範圍（全部帳戶或一個帳戶，附筆數）、說清楚會刪除與會留下的、可以一起暫停定期定額、建議先匯出、要輸入「清除」才能按 → 通知。
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
    useUi.getState().closeClearRecords()
  })
})

const T = { timeout: 8000 }
const TW = "acc_01JSINOPAC"
const US = "acc_01JCATHAYUS"

/** 每個測試一份新的 mock（清掉的紀錄、暫停的定期定額互不影響） */
function mount(options: MockOptions = {}) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  return adapter
}

let queryClient: QueryClient

function renderApp(path = "/settings") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient = qc
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  )
  return router
}

/** 確認框打開期間筆數重抓（網路恢復、別的地方記了或刪了紀錄之後 portfolio 重抓） */
async function refetchCounts() {
  const before = vi.mocked(api.getRecordCounts).mock.calls.length
  await act(() => queryClient.invalidateQueries({ queryKey: qk.recordCounts }))
  await waitFor(() => expect(vi.mocked(api.getRecordCounts).mock.calls.length).toBeGreaterThan(before), T)
}

const user = () => userEvent.setup({ pointerEventsCheck: 0 })

async function recordsIn(accountId?: string) {
  return (await api.listTransactions({ ...(accountId ? { account_id: accountId } : {}), limit: 200 })).items
}

/** 設定「帳號與資料」的「清除…」打開確認框，等筆數讀完 */
async function openFromSettings() {
  const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
  await user().click(within(section).getByRole("button", { name: "清除…" }))
  const dialog = await screen.findByRole("dialog", { name: "清除所有持倉？" }, T)
  await within(dialog).findByRole("radio", { name: /全部帳戶/ }, T)
  return dialog
}

async function confirm(dialog: HTMLElement) {
  await user().type(within(dialog).getByRole("textbox", { name: `請輸入「${CLEAR_RECORDS_CONFIRMATION}」` }), CLEAR_RECORDS_CONFIRMATION)
  await user().click(within(dialog).getByRole("button", { name: /^清除 [\d,]+ 筆紀錄$/ }))
}

describe("入口", { timeout: 20_000 }, () => {
  it("設定「帳號與資料」：「清除所有持倉」一列，在刪除帳號前面；外框按鈕「清除…」打開確認框", async () => {
    mount()
    renderApp()
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    expect(section).toHaveTextContent("刪掉一個或全部帳戶的紀錄，帳戶留著")
    const clear = within(section).getByRole("button", { name: "清除…" })
    const deleteMe = within(section).getByRole("button", { name: "刪除帳號…" })
    expect(clear.compareDocumentPosition(deleteMe) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await user().click(clear)
    expect(await screen.findByRole("dialog", { name: "清除所有持倉？" }, T)).toBeInTheDocument()
  })

  it("帳本「自訂」最下面（一條格線之後）的「清除所有持倉…」：關掉選單、打開同一個確認框；取消後焦點回到「自訂」", async () => {
    mount()
    renderApp("/")
    await screen.findByRole("table", { name: "持倉" }, T)
    const trigger = screen.getByRole("button", { name: "自訂欄位與顯示" })
    await user().click(trigger)
    const link = await screen.findByRole("button", { name: "清除所有持倉…" }, T)
    expect(link).toHaveClass("text-ink-2")
    expect(link.parentElement).toHaveClass("border-t")
    // 在「還原預設」後面
    const reset = screen.getByRole("button", { name: "還原預設" })
    expect(reset.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await user().click(link)
    const dialog = await screen.findByRole("dialog", { name: "清除所有持倉？" }, T)
    await waitFor(() => expect(screen.queryByRole("button", { name: "還原預設" })).toBeNull(), T)
    await user().click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    await waitFor(() => expect(document.activeElement).toBe(trigger), T)
    expect(api.clearRecords).not.toHaveBeenCalled()
  })
})

describe("確認框", { timeout: 20_000 }, () => {
  it("範圍：全部帳戶在最上面、預設選它，每個帳戶一列（筆數）；說清楚會刪除、會留下的；要輸入「清除」才能按", async () => {
    mount()
    const all = await recordsIn()
    const tw = await recordsIn(TW)
    const us = await recordsIn(US)
    expect(tw.length).toBeGreaterThan(0)
    expect(us.length).toBeGreaterThan(0)
    const trades = all.filter((t) => t.type === "buy" || t.type === "sell").length
    const dividends = all.filter((t) => t.type === "cash_dividend" || t.type === "stock_dividend").length
    const symbols = new Set(all.flatMap((t) => (t.symbol ? [t.symbol] : []))).size
    renderApp()
    const dialog = await openFromSettings()
    expect(dialog).toHaveAccessibleDescription("每一筆紀錄都會刪掉，刪除之後不能復原。")
    const radios = within(dialog).getAllByRole("radio")
    expect(radios.map((r) => r.closest("label")!.textContent)).toEqual([`全部帳戶${all.length} 筆`, `永豐・一般${tw.length} 筆`, `國泰・複委託${us.length} 筆`])
    expect(radios[0]).toBeChecked()
    expect(dialog).toHaveTextContent(`全部帳戶的 ${all.length} 筆紀錄（${symbols} 檔股票）`)
    const other = all.length - trades - dividends
    expect(dialog).toHaveTextContent(`包括 ${trades} 筆買賣、${dividends} 筆股利${other > 0 ? `、${other} 筆其他紀錄` : ""}。`)
    expect(dialog).toHaveTextContent("這些紀錄算出來的持股、損益、出清紀錄與績效")
    // 示範的使用者有加入群組：群組動態裡這些交易（連同別人的留言與表情）也會刪，留下的是成員身分
    expect(dialog).toHaveTextContent("群組動態裡這些交易，連同上面的留言與表情")
    expect(dialog).toHaveTextContent("券商帳戶，清除後可以重新記")
    expect(dialog).toHaveTextContent("觀察清單、群組成員身分、AI 對話與設定")
    expect(dialog).not.toHaveTextContent("其他帳戶的紀錄")
    // 示範帳本有 2 個還在進行的定期定額（永豐）：預設勾著
    const box = within(dialog).getByRole("checkbox", { name: /同時暫停 2 個定期定額/ })
    expect(box).toBeChecked()
    expect(box.closest("label")).toHaveTextContent("暫停不是刪除，在設定可以恢復。")
    expect(within(dialog).getByRole("button", { name: "匯出資料" })).toBeInTheDocument()
    // 要打對字才能按：少一個字、別的字都不行
    const sign = within(dialog).getByRole("button", { name: `清除 ${all.length} 筆紀錄` })
    expect(sign).toBeDisabled()
    const input = within(dialog).getByRole("textbox", { name: "請輸入「清除」" })
    await user().type(input, "清")
    expect(sign).toBeDisabled()
    await user().type(input, "掉")
    expect(sign).toBeDisabled()
    await user().clear(input)
    await user().type(input, " 清除 ")
    expect(sign).toBeEnabled()
    expect(api.clearRecords).not.toHaveBeenCalled()
  })

  it("選一個帳戶：筆數與留下的跟著換（其他帳戶的紀錄留著）；清除後只清那個帳戶，定期定額暫停，通知筆數", async () => {
    mount()
    const tw = await recordsIn(TW)
    const us = await recordsIn(US)
    renderApp()
    const dialog = await openFromSettings()
    await user().click(within(dialog).getByRole("radio", { name: /永豐・一般/ }))
    expect(dialog).toHaveTextContent(`「永豐・一般」的 ${tw.length} 筆紀錄`)
    expect(dialog).toHaveTextContent("其他帳戶的紀錄")
    await confirm(dialog)
    await waitFor(() => expect(api.clearRecords).toHaveBeenCalledWith(TW, { pausePlans: true }), T)
    expect(await screen.findByText(`已清除「永豐・一般」的 ${tw.length} 筆紀錄`, {}, T)).toBeInTheDocument()
    expect(screen.getByText("2 個定期定額已暫停。")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    expect(await recordsIn(TW)).toEqual([])
    expect(await recordsIn(US)).toHaveLength(us.length)
    expect((await api.listRecurring()).map((p) => p.active)).toEqual([false, false])
    expect((await api.listAccounts()).map((a) => a.id)).toEqual([TW, US])
  })

  it("全部帳戶、不暫停：每一筆都清掉、持倉重抓成空的；定期定額照常，通知說下次扣款日會再提出草稿（附「到設定」）", async () => {
    mount()
    const all = await recordsIn()
    const router = renderApp()
    const dialog = await openFromSettings()
    await user().click(within(dialog).getByRole("checkbox"))
    await confirm(dialog)
    await waitFor(() => expect(api.clearRecords).toHaveBeenCalledWith(null, { pausePlans: false }), T)
    expect(await screen.findByText(`已清除全部帳戶的 ${all.length} 筆紀錄`, {}, T)).toBeInTheDocument()
    expect(screen.getByText("還有 2 個定期定額在進行，下次扣款日會再提出草稿。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "到設定" })).toBeInTheDocument()
    expect(await recordsIn()).toEqual([])
    expect((await api.listRecurring()).every((p) => p.active)).toBe(true)
    // 帳本（不重新載入）：持倉是空的
    await act(() => router.navigate({ to: "/" }))
    expect(await screen.findByText("帳本還是空的", {}, T)).toBeInTheDocument()
    expect(await api.getWatchlist()).not.toEqual([])
  })

  it("先匯出資料：就地下載匯出檔（不離開確認框），下載好了就地說", async () => {
    mount()
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:forliosa-export"), revokeObjectURL: vi.fn() })
    const clicks: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.download)
    })
    renderApp()
    const dialog = await openFromSettings()
    await user().click(within(dialog).getByRole("button", { name: "匯出資料" }))
    await waitFor(() => expect(clicks).toHaveLength(1), T)
    expect(clicks[0]).toMatch(/^forliosa-export-\d{8}\.json$/)
    expect(await within(dialog).findByText("已下載匯出檔。", {}, T)).toBeInTheDocument()
    expect(screen.getByRole("dialog", { name: "清除所有持倉？" })).toBeInTheDocument()
    expect(api.clearRecords).not.toHaveBeenCalled()
  })

  it("伺服器拒絕：確認框留著，就地說「沒有清除，紀錄都還在。」＋原因", async () => {
    mount()
    vi.spyOn(api, "clearRecords").mockRejectedValue(new ApiError(500, "internal_error", "伺服器出了問題，等一下再試一次。"))
    renderApp()
    const dialog = await openFromSettings()
    await confirm(dialog)
    expect(await within(dialog).findByRole("alert", {}, T)).toHaveTextContent("沒有清除，紀錄都還在。伺服器出了問題，等一下再試一次。")
    expect(within(dialog).getByRole("button", { name: /^清除 [\d,]+ 筆紀錄$/ })).toBeEnabled()
  })

  it("閘道回的 5xx（不是後端的 JSON 錯誤，例如 Cloudflare、Railway 的 502）：不說「紀錄都還在」，說不確定", async () => {
    mount()
    vi.spyOn(api, "clearRecords").mockRejectedValue(new ApiError(502, "http_502", "伺服器回應錯誤（502）"))
    renderApp()
    const dialog = await openFromSettings()
    await confirm(dialog)
    const alert = await within(dialog).findByRole("alert", {}, T)
    expect(alert).toHaveTextContent("伺服器沒有回應，不確定有沒有清除。請稍後再試一次。")
    expect(alert).not.toHaveTextContent("紀錄都還在")
    expect(alert).not.toHaveTextContent("502")
  })

  it("連不上伺服器：不說「紀錄都還在」（不知道清了沒有）；取消時重抓持倉", async () => {
    mount()
    vi.spyOn(api, "clearRecords").mockRejectedValue(new TypeError("Failed to fetch"))
    renderApp()
    const dialog = await openFromSettings()
    await confirm(dialog)
    const alert = await within(dialog).findByRole("alert", {}, T)
    expect(alert).toHaveTextContent("連不上伺服器，不確定有沒有清除。請檢查網路後再試一次。")
    expect(alert).not.toHaveTextContent("紀錄都還在")
    expect(alert).not.toHaveTextContent("Failed to fetch")
    const before = vi.mocked(api.getRecordCounts).mock.calls.length
    await user().click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    // 重新數一次（筆數在 portfolio 底下，跟著持倉一起重抓）：下一次打開是實際的
    await user().click(within(screen.getByRole("region", { name: "帳號與資料" })).getByRole("button", { name: "清除…" }))
    await waitFor(() => expect(vi.mocked(api.getRecordCounts).mock.calls.length).toBeGreaterThan(before), T)
  })

  it("已經在別的地方清掉了（404 no_records）：當成清好了——關掉、通知已經不在了；勾著的暫停照樣做，通知裡說", async () => {
    const adapter = mount()
    renderApp()
    const dialog = await openFromSettings()
    // 另一個分頁沒勾暫停就清了
    await adapter.clearRecords(null)
    expect((await api.listRecurring()).every((p) => p.active)).toBe(true)
    await confirm(dialog)
    expect(await screen.findByText("全部帳戶的紀錄已經不在了", {}, T)).toBeInTheDocument()
    expect(screen.getByText("可能已經在別的地方清除了。2 個定期定額已暫停。")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    expect(screen.queryByText(/沒有清除/)).toBeNull()
    expect((await api.listRecurring()).map((p) => p.active)).toEqual([false, false])
  })

  it("已經在別的地方清掉了、這裡沒勾暫停：通知說定期定額還在進行（附「到設定」）", async () => {
    const adapter = mount()
    renderApp()
    const dialog = await openFromSettings()
    await adapter.clearRecords(null)
    await user().click(within(dialog).getByRole("checkbox"))
    await confirm(dialog)
    expect(await screen.findByText("全部帳戶的紀錄已經不在了", {}, T)).toBeInTheDocument()
    expect(screen.getByText("可能已經在別的地方清除了。還有 2 個定期定額在進行，下次扣款日會再提出草稿。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "到設定" })).toBeInTheDocument()
    expect((await api.listRecurring()).every((p) => p.active)).toBe(true)
  })

  it("筆數沒有讀到：就地說還不能清除（沒有簽名格可以按），「再試一次」重新數", async () => {
    const adapter = mount()
    vi.spyOn(api, "getRecordCounts").mockRejectedValueOnce(new TypeError("Failed to fetch"))
    renderApp()
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    await user().click(within(section).getByRole("button", { name: "清除…" }))
    const dialog = await screen.findByRole("dialog", { name: "清除所有持倉？" }, T)
    const alert = await within(dialog).findByRole("alert", {}, T)
    expect(alert).toHaveTextContent("筆數沒有載入，還不能清除。")
    expect(within(dialog).getByRole("button", { name: "清除" })).toBeDisabled()
    vi.mocked(api.getRecordCounts).mockImplementation(adapter.getRecordCounts)
    await user().click(within(alert).getByRole("button", { name: "再試一次" }))
    expect(await within(dialog).findByRole("radio", { name: /全部帳戶/ }, T)).toBeChecked()
  })

  it("沒有任何紀錄：說不用清除，只有「關閉」", async () => {
    const adapter = mount()
    await adapter.clearRecords(null)
    renderApp()
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    await user().click(within(section).getByRole("button", { name: "清除…" }))
    const dialog = await screen.findByRole("dialog", { name: "清除所有持倉？" }, T)
    expect(await within(dialog).findByText("目前沒有任何紀錄，不用清除。", {}, T)).toBeInTheDocument()
    expect(within(dialog).queryByRole("textbox")).toBeNull()
    expect(within(dialog).queryByRole("radio")).toBeNull()
    expect(within(dialog).getAllByRole("button", { name: "關閉" }).length).toBeGreaterThan(0)
  })

  it("沒有加入群組：不提群組動態，留下的也不寫群組", async () => {
    mount()
    vi.spyOn(api, "listGroups").mockResolvedValue([])
    renderApp()
    const dialog = await openFromSettings()
    expect(dialog).not.toHaveTextContent("群組動態")
    expect(dialog).toHaveTextContent("觀察清單、AI 對話與設定")
    expect(dialog).not.toHaveTextContent("群組成員身分")
  })

  it("只有一個帳戶有紀錄：不用選範圍，直接寫那個帳戶", async () => {
    const adapter = mount()
    await adapter.clearRecords(US)
    const tw = await recordsIn(TW)
    renderApp()
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    await user().click(within(section).getByRole("button", { name: "清除…" }))
    const dialog = await screen.findByRole("dialog", { name: "清除所有持倉？" }, T)
    expect(await within(dialog).findByText(new RegExp(`「永豐・一般」的 ${tw.length} 筆紀錄`), {}, T)).toBeInTheDocument()
    expect(within(dialog).queryByRole("radio")).toBeNull()
    await confirm(dialog)
    await waitFor(() => expect(api.clearRecords).toHaveBeenLastCalledWith(TW, { pausePlans: true }), T)
  })
})

describe("範圍不會自己變（筆數重抓時）", { timeout: 20_000 }, () => {
  it("選了一個帳戶、它在別的地方被清掉：不會退回「全部帳戶」或換成別的帳戶；照實說、不能按，換範圍要重打「清除」", async () => {
    const adapter = mount()
    renderApp()
    const dialog = await openFromSettings()
    await user().click(within(dialog).getByRole("radio", { name: /永豐・一般/ }))
    const input = within(dialog).getByRole("textbox", { name: "請輸入「清除」" })
    await user().type(input, CLEAR_RECORDS_CONFIRMATION)
    // 別的分頁把永豐清掉了，這裡的筆數重抓
    await adapter.clearRecords(TW)
    await refetchCounts()
    expect(await within(dialog).findByText("「永豐・一般」已經沒有紀錄了，可能已經在別的地方清除了。", {}, T)).toBeInTheDocument()
    expect(within(dialog).getByRole("radio", { name: /永豐・一般/ })).toBeChecked()
    expect(within(dialog).getByRole("radio", { name: /全部帳戶/ })).not.toBeChecked()
    expect(within(dialog).getByRole("radio", { name: /國泰・複委託/ })).not.toBeChecked()
    expect(within(dialog).queryByRole("textbox")).toBeNull()
    const sign = within(dialog).getByRole("button", { name: "清除" })
    expect(sign).toBeDisabled()
    await user().click(sign)
    expect(api.clearRecords).not.toHaveBeenCalled()
    // 換成國泰：打好的字清掉，要重打
    await user().click(within(dialog).getByRole("radio", { name: /國泰・複委託/ }))
    expect(within(dialog).getByRole("textbox", { name: "請輸入「清除」" })).toHaveValue("")
    await confirm(dialog)
    await waitFor(() => expect(api.clearRecords).toHaveBeenCalledTimes(1), T)
    expect(api.clearRecords).toHaveBeenCalledWith(US, { pausePlans: false })
  })

  it("換範圍時打好的「清除」清空", async () => {
    mount()
    renderApp()
    const dialog = await openFromSettings()
    const input = within(dialog).getByRole("textbox", { name: "請輸入「清除」" })
    await user().type(input, CLEAR_RECORDS_CONFIRMATION)
    await user().click(within(dialog).getByRole("radio", { name: /永豐・一般/ }))
    expect(within(dialog).getByRole("textbox", { name: "請輸入「清除」" })).toHaveValue("")
    expect(within(dialog).getByRole("button", { name: /^清除 [\d,]+ 筆紀錄$/ })).toBeDisabled()
  })

  it("只有一個帳戶有紀錄時定下的範圍：別的帳戶後來有了紀錄，也不會擴大成全部帳戶", async () => {
    const adapter = mount()
    await adapter.clearRecords(US)
    const tw = await recordsIn(TW)
    renderApp()
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    await user().click(within(section).getByRole("button", { name: "清除…" }))
    const dialog = await screen.findByRole("dialog", { name: "清除所有持倉？" }, T)
    expect(await within(dialog).findByText(new RegExp(`「永豐・一般」的 ${tw.length} 筆紀錄`), {}, T)).toBeInTheDocument()
    await user().type(within(dialog).getByRole("textbox", { name: "請輸入「清除」" }), CLEAR_RECORDS_CONFIRMATION)
    // 別的分頁在國泰記了一筆
    await adapter.createTransaction({ account_id: US, symbol: "AAPL", type: "buy", trade_date: "2025-03-03", quantity: 1, price: 200 })
    await refetchCounts()
    await within(dialog).findByRole("radio", { name: /國泰・複委託/ }, T)
    expect(within(dialog).getByRole("radio", { name: /永豐・一般/ })).toBeChecked()
    expect(within(dialog).getByRole("radio", { name: /全部帳戶/ })).not.toBeChecked()
    expect(dialog).toHaveTextContent(`「永豐・一般」的 ${tw.length} 筆紀錄`)
    await user().click(within(dialog).getByRole("button", { name: `清除 ${tw.length} 筆紀錄` }))
    await waitFor(() => expect(api.clearRecords).toHaveBeenCalledTimes(1), T)
    expect(api.clearRecords).toHaveBeenCalledWith(TW, { pausePlans: true })
    expect(await recordsIn(US)).toHaveLength(1)
  })

  it("連不上伺服器（其實清好了）之後再試一次：送的還是同一個帳戶，不會變成全部帳戶；範圍的選項停用", async () => {
    const adapter = mount()
    // 後端清好了，回應在路上斷掉
    vi.spyOn(api, "clearRecords").mockImplementationOnce(async (accountId, opts) => {
      await adapter.clearRecords(accountId, opts)
      throw new TypeError("Failed to fetch")
    })
    renderApp()
    const dialog = await openFromSettings()
    await user().click(within(dialog).getByRole("radio", { name: /永豐・一般/ }))
    await confirm(dialog)
    expect(await within(dialog).findByRole("alert", {}, T)).toHaveTextContent("連不上伺服器，不確定有沒有清除。")
    // 網路恢復、筆數重抓：範圍與畫面還是送出的那一個
    await refetchCounts()
    for (const radio of within(dialog).getAllByRole("radio")) expect(radio).toBeDisabled()
    expect(within(dialog).getByRole("radio", { name: /永豐・一般/ })).toBeChecked()
    await user().click(within(dialog).getByRole("button", { name: /^清除 [\d,]+ 筆紀錄$/ }))
    await waitFor(() => expect(api.clearRecords).toHaveBeenCalledTimes(2), T)
    expect(vi.mocked(api.clearRecords).mock.calls.map((c) => c[0])).toEqual([TW, TW])
    expect(await screen.findByText("「永豐・一般」的紀錄已經不在了", {}, T)).toBeInTheDocument()
    expect((await recordsIn(US)).length).toBeGreaterThan(0)
  })
})

describe("查看別人的資產（唯讀）", { timeout: 20_000 }, () => {
  const DAD: ViewAsTarget = {
    delegation_id: "dlg_dad",
    owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null },
    scope: "accounts",
    accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }],
  }

  it("帳本「自訂」裡沒有「清除所有持倉…」，也沒有確認框", async () => {
    mount()
    act(() => useViewAs.getState().set(DAD))
    renderApp("/")
    await screen.findByRole("table", { name: "持倉" }, T)
    await user().click(screen.getByRole("button", { name: "自訂欄位與顯示" }))
    await screen.findByRole("button", { name: "還原預設" }, T)
    expect(screen.queryByRole("button", { name: "清除所有持倉…" })).toBeNull()
    act(() => useUi.getState().openClearRecords())
    expect(screen.queryByRole("dialog", { name: "清除所有持倉？" })).toBeNull()
    expect(api.getRecordCounts).not.toHaveBeenCalled()
    expect(api.clearRecords).not.toHaveBeenCalled()
  })
})
