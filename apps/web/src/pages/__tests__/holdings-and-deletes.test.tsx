import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api, appToday } from "@/api"
import { createHttpAdapter } from "@/api/http"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { listTransactionsUpTo } from "@/api/queries"
import type { Account, ForliosaApi } from "@/api/types"
import { useViewAs, VIEW_AS_HEADER } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { Toaster } from "@/components/ui/sonner"
import { sameAccountName } from "@/lib/account-name"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 產品負責人 2026-11-14 照建議決定的三件事：
 * - 2-1「只記持股」的帳戶：記一筆換成持股的輸入（股票＋張數＋均價，一次好幾檔，存成快照），設定頁的帳戶列也進得去；
 * - 2-5 刪除券商帳戶：帳戶的編輯框裡「刪除這個帳戶」，說清楚一起刪掉什麼，要輸入帳戶名稱才能刪；
 * - 3-2 設定頁「刪除全部 AI 對話」：伺服器與這台瀏覽器上的對話都清掉，先問一次。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  Element.prototype.setPointerCapture ??= () => {}
  Element.prototype.releasePointerCapture ??= () => {}
  Element.prototype.hasPointerCapture ??= () => false
  // 桌面版（對話框）：jsdom 裡 Vaul 抽屜的動畫與指標事件不完整
  window.matchMedia = ((query: string) => ({
    matches: query.includes("min-width"), media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ threadId: null, threads: [], drafts: {}, focusDraftId: null, ownerId: null, hiddenThreadIds: [] })
beforeEach(() => {
  act(resetAi)
  usePrefs.setState({ quantityUnit: "lot" })
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  act(() => {
    resetAi()
    useViewAs.setState({ target: null })
    useUi.getState().closeTradeForm()
  })
})

const T = { timeout: 6000 }

/** 每個測試一份新的 mock（帳戶、交易、快照互不影響） */
function mount(options: MockOptions = {}) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  return adapter
}

function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  )
  return router
}

const holdingsAccount = (): Promise<Account> =>
  api.createAccount({ name: "元大－只記持股", broker: "元大證券", currency: "TWD", fee_rate: 0.001425, fee_discount: 0.6, min_fee: 20, min_fee_odd_lot: 1, tracking_mode: "holdings" })

/** 在持股的輸入裡選一檔：搜尋框打代號，按那一列 */
async function pick(dialog: HTMLElement, label: string, code: string) {
  const user = userEvent.setup()
  const box = await within(dialog).findByRole("combobox", { name: label }, T)
  await user.type(box, code)
  await user.click(await within(dialog).findByRole("option", { name: new RegExp(code) }, T))
}

describe("只記持股的帳戶：持股的輸入", { timeout: 20_000 }, () => {
  it("設定頁的帳戶列「編輯持股」→ 一次填兩檔（張數照偏好）→ 存成持股；逐筆交易的帳戶沒有這個動作", async () => {
    mount()
    const acc = await holdingsAccount()
    const user = userEvent.setup()
    renderApp("/settings")
    await screen.findByRole("heading", { name: "券商帳戶" }, T)
    expect(screen.queryByRole("button", { name: "編輯 永豐・一般 的持股" })).toBeNull()
    await user.click(await screen.findByRole("button", { name: "編輯 元大－只記持股 的持股" }, T))
    const dialog = await screen.findByRole("dialog", {}, T)
    expect(within(dialog).getByRole("heading", { name: "目前持股" })).toBeInTheDocument()
    expect(within(dialog).queryByText("買進日期")).toBeNull()

    // 沒填就存：說要選股票，不送出
    await user.click(await within(dialog).findByRole("button", { name: "存成持股" }, T))
    expect(within(dialog).getByText("請選擇股票或 ETF")).toBeInTheDocument()

    await pick(dialog, "第 1 檔的股票", "2330")
    await user.type(within(dialog).getByRole("textbox", { name: "台積電的張數" }), "1.5")
    expect(within(dialog).getByText("1,500 股")).toBeInTheDocument()
    await user.type(within(dialog).getByRole("textbox", { name: "台積電的均價" }), "600")
    await user.click(within(dialog).getByRole("button", { name: "再加一檔" }))
    await pick(dialog, "第 2 檔的股票", "0050")
    await user.type(within(dialog).getByRole("textbox", { name: "元大台灣50的張數" }), "2.0005")
    await user.type(within(dialog).getByRole("textbox", { name: "元大台灣50的均價" }), "150")
    await user.click(within(dialog).getByRole("button", { name: "存成持股" }))
    expect(within(dialog).getByText("張數最多寫到小數第三位（1 股）")).toBeInTheDocument()
    await user.clear(within(dialog).getByRole("textbox", { name: "元大台灣50的張數" }))
    await user.type(within(dialog).getByRole("textbox", { name: "元大台灣50的張數" }), "2.006")
    await user.click(within(dialog).getByRole("button", { name: "存成持股" }))

    await waitFor(() => expect(useUi.getState().tradeForm.open).toBe(false), T)
    expect(await screen.findByText("已存成持股：2 檔", {}, T)).toBeInTheDocument()
    const snap = await api.getAccountHoldings(acc.id)
    expect(snap.as_of).toBe(appToday())
    // 2.006 張 → 2,006 股（取整，不是 2005.9999）
    expect(snap.holdings).toEqual([
      { symbol: "0050.TW", quantity: 2006, avg_cost: 150 },
      { symbol: "2330.TW", quantity: 1500, avg_cost: 600 },
    ])
    // 帳本照快照算
    const held = await api.getHoldings(acc.id)
    expect(held.map((h) => [h.symbol, h.quantity]).sort()).toEqual([["0050.TW", 2006], ["2330.TW", 1500]])
  })

  it("帶入現在的快照：只改均價沿用原本的日期；改股數、移除一檔是今天的快照；「復原」放回原本的快照", async () => {
    mount()
    const acc = await holdingsAccount()
    await api.putHoldings(acc.id, { as_of: "2026-10-01", holdings: [{ symbol: "2330.TW", quantity: 1000, avg_cost: 600 }, { symbol: "0050.TW", quantity: 2000, avg_cost: 150 }] })
    const user = userEvent.setup()
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)

    act(() => useUi.getState().openTradeForm({ accountId: acc.id }))
    let dialog = await screen.findByRole("dialog", {}, T)
    const cost = await within(dialog).findByRole("textbox", { name: "台積電的均價" }, T)
    expect((within(dialog).getByRole("textbox", { name: "台積電的張數" }) as HTMLInputElement).value).toBe("1")
    expect((within(dialog).getByRole("textbox", { name: "元大台灣50的張數" }) as HTMLInputElement).value).toBe("2")
    await user.clear(cost)
    await user.type(cost, "612.5")
    await user.click(within(dialog).getByRole("button", { name: "存成持股" }))
    await waitFor(() => expect(useUi.getState().tradeForm.open).toBe(false), T)
    let snap = await api.getAccountHoldings(acc.id)
    expect(snap.as_of).toBe("2026-10-01")
    expect(snap.holdings.find((h) => h.symbol === "2330.TW")).toEqual({ symbol: "2330.TW", quantity: 1000, avg_cost: 612.5 })

    act(() => useUi.getState().openTradeForm({ accountId: acc.id }))
    dialog = await screen.findByRole("dialog", {}, T)
    await user.click(await within(dialog).findByRole("button", { name: "移除元大台灣50" }, T))
    const qty = within(dialog).getByRole("textbox", { name: "台積電的張數" })
    await user.clear(qty)
    await user.type(qty, "2")
    await user.click(within(dialog).getByRole("button", { name: "存成持股" }))
    await waitFor(() => expect(useUi.getState().tradeForm.open).toBe(false), T)
    snap = await api.getAccountHoldings(acc.id)
    expect(snap).toMatchObject({ as_of: appToday(), holdings: [{ symbol: "2330.TW", quantity: 2000, avg_cost: 612.5 }] })

    const toastEl = (await screen.findAllByText("已存成持股：1 檔", {}, T)).at(-1)!.closest("[data-sonner-toast]") as HTMLElement
    await user.click(within(toastEl).getByRole("button", { name: "復原" }))
    await waitFor(async () => expect((await api.getAccountHoldings(acc.id)).holdings).toHaveLength(2), T)
    snap = await api.getAccountHoldings(acc.id)
    expect(snap.as_of).toBe("2026-10-01")
    expect(snap.holdings).toEqual([
      { symbol: "0050.TW", quantity: 2000, avg_cost: 150 },
      { symbol: "2330.TW", quantity: 1000, avg_cost: 612.5 },
    ])
  })

  it("記一筆：帳戶選到只記持股的帳戶，就換成持股的輸入（不記買進）；換回來又是買進", async () => {
    mount()
    await holdingsAccount()
    // 下拉選單打開的動畫期間選項是 pointer-events: none：機器忙的時候會剛好點在動畫中，不檢查這一項
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    act(() => useUi.getState().openTradeForm())
    const dialog = await screen.findByRole("dialog", {}, T)
    expect(within(dialog).getByRole("heading", { name: "記一筆" })).toBeInTheDocument()
    expect(await within(dialog).findByRole("button", { name: "新增" }, T)).toBeInTheDocument()

    await user.click(within(dialog).getByRole("combobox", { name: "券商帳戶" }))
    await user.click(await screen.findByRole("option", { name: /元大－只記持股/ }, T))
    expect(await within(dialog).findByRole("heading", { name: "目前持股" }, T)).toBeInTheDocument()
    expect(await within(dialog).findByRole("button", { name: "存成持股" }, T)).toBeInTheDocument()
    expect(within(dialog).queryByRole("button", { name: "新增" })).toBeNull()
    expect(within(dialog).queryByText("買進價格")).toBeNull()

    await user.click(within(dialog).getByRole("combobox", { name: "券商帳戶" }))
    await user.click(await screen.findByRole("option", { name: /永豐・一般/ }, T))
    expect(await within(dialog).findByRole("heading", { name: "記一筆" }, T)).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "新增" })).toBeInTheDocument()
  })

  it("持倉的「加碼」：那一檔在只記持股的帳戶裡，就開持股的輸入，焦點在那一檔的數量", async () => {
    mount()
    const acc = await holdingsAccount()
    await api.putHoldings(acc.id, { as_of: "2026-10-01", holdings: [{ symbol: "2382.TW", quantity: 2000, avg_cost: 300 }] })
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    act(() => useUi.getState().openTradeForm({ symbol: "2382" }))
    const dialog = await screen.findByRole("dialog", {}, T)
    expect(await within(dialog).findByRole("heading", { name: "目前持股" }, T)).toBeInTheDocument()
    const qty = await within(dialog).findByRole("textbox", { name: "廣達的張數" }, T)
    await waitFor(() => expect(document.activeElement).toBe(qty), T)
  })
})

describe("刪除券商帳戶", { timeout: 20_000 }, () => {
  it("編輯框的「刪除這個帳戶」：寫出會一起刪掉的筆數，輸入帳戶名稱才能按；刪掉之後帳戶不見了", async () => {
    mount()
    const user = userEvent.setup()
    const records = (await listTransactionsUpTo({ account_id: "acc_01JSINOPAC" }, 1000)).items.length
    expect(records).toBeGreaterThan(0)
    renderApp("/settings")
    await user.click(await screen.findByRole("button", { name: "編輯 永豐・一般" }, T))
    const edit = await screen.findByRole("dialog", {}, T)
    await user.click(within(edit).getByRole("button", { name: "刪除這個帳戶" }))

    const dialog = await screen.findByRole("dialog", { name: "刪除「永豐・一般」？" }, T)
    expect(within(dialog).getByText("刪除之後不能復原。")).toBeInTheDocument()
    await waitFor(() => expect(dialog).toHaveTextContent(`帳戶裡的 ${records.toLocaleString("en-US")} 筆紀錄、2 個定期定額會一起刪除。`), T)
    const button = within(dialog).getByRole("button", { name: "刪除帳戶" })
    expect(button).toBeDisabled()
    const input = within(dialog).getByRole("textbox", { name: "請輸入帳戶名稱「永豐・一般」" })
    await user.type(input, "永豐")
    expect(button).toBeDisabled()
    // 間隔號打成台灣鍵盤上的「‧」也算對
    await user.type(input, "‧一般")
    expect(button).toBeEnabled()
    await user.click(button)

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "刪除「永豐・一般」？" })).toBeNull(), T)
    expect(await screen.findByText("已刪除「永豐・一般」", {}, T)).toBeInTheDocument()
    expect((await api.listAccounts()).map((a) => a.name)).toEqual(["國泰・複委託"])
    expect((await api.listTransactions({ account_id: "acc_01JSINOPAC", limit: 10 })).items).toEqual([])
    expect(await api.listRecurring()).toEqual([])
    await waitFor(() => expect(screen.queryByRole("button", { name: "編輯 永豐・一般" })).toBeNull(), T)
  })

  it("取消就什麼都沒刪；新增帳戶的框沒有刪除", async () => {
    mount()
    const user = userEvent.setup()
    renderApp("/settings")
    await user.click(await screen.findByRole("button", { name: "新增帳戶" }, T))
    const create = await screen.findByRole("dialog", {}, T)
    expect(within(create).queryByRole("button", { name: "刪除這個帳戶" })).toBeNull()
    await user.click(within(create).getByRole("button", { name: "取消" }))
    await user.click(await screen.findByRole("button", { name: "編輯 國泰・複委託" }, T))
    await user.click(within(await screen.findByRole("dialog", {}, T)).getByRole("button", { name: "刪除這個帳戶" }))
    const dialog = await screen.findByRole("dialog", { name: "刪除「國泰・複委託」？" }, T)
    await user.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    expect(await api.listAccounts()).toHaveLength(2)
  })

  it("帳戶名稱的比對不管全形半形、連字號與間隔號的寫法", () => {
    expect(sameAccountName("永豐-一般", "永豐－一般")).toBe(true)
    expect(sameAccountName(" 永豐‧一般 ", "永豐・一般")).toBe(true)
    expect(sameAccountName("cathay us", "Cathay US")).toBe(true)
    expect(sameAccountName("永豐", "永豐・一般")).toBe(false)
    expect(sameAccountName("", "")).toBe(false)
  })
})

describe("刪除全部 AI 對話", { timeout: 20_000 }, () => {
  const thread = (id: string) => ({ id, title: "台積電怎麼看", updatedAt: new Date().toISOString(), messages: [{ id: `m_${id}`, role: "user" as const, text: "台積電怎麼看", at: new Date().toISOString() }] })

  it("先問一次；按「全部刪除」→ 伺服器的刪掉、這台瀏覽器上的對話與草稿清掉（仍記得是誰的），示範紀錄也藏起來", async () => {
    mount()
    const user = userEvent.setup()
    act(() => useAi.setState({ ownerId: "usr_01JDEMO", threads: [thread("thr_a"), thread("thr_b")], threadId: "thr_a" }))
    renderApp("/settings")
    await user.click(await screen.findByRole("button", { name: "刪除全部 AI 對話" }, T))
    const dialog = await screen.findByRole("alertdialog", { name: "刪除全部 AI 對話？" }, T)
    expect(dialog).toHaveTextContent("不能復原。已簽名的草稿記下的交易會留在帳本。")

    // 取消：什麼都沒動
    await user.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), T)
    expect(useAi.getState().threads).toHaveLength(2)
    expect(api.deleteAiThreads).not.toHaveBeenCalled()

    await user.click(screen.getByRole("button", { name: "刪除全部 AI 對話" }))
    await user.click(within(await screen.findByRole("alertdialog", {}, T)).getByRole("button", { name: "全部刪除" }))
    await waitFor(() => expect(useAi.getState().threads).toEqual([]), T)
    expect(api.deleteAiThreads).toHaveBeenCalledTimes(1)
    expect(useAi.getState()).toMatchObject({ threadId: null, drafts: {}, ownerId: "usr_01JDEMO" })
    expect(useAi.getState().hiddenThreadIds).toEqual(expect.arrayContaining(["seed_why", "seed_878", "seed_import", "seed_conc"]))
    expect(await screen.findByText("已刪除全部 AI 對話", {}, T)).toBeInTheDocument()
  })

  it("伺服器沒刪成功：對話都還在", async () => {
    mount()
    vi.mocked(api.deleteAiThreads).mockRejectedValueOnce(new Error("連不上伺服器"))
    const user = userEvent.setup()
    act(() => useAi.setState({ ownerId: "usr_01JDEMO", threads: [thread("thr_a")] }))
    renderApp("/settings")
    await user.click(await screen.findByRole("button", { name: "刪除全部 AI 對話" }, T))
    await user.click(within(await screen.findByRole("alertdialog", {}, T)).getByRole("button", { name: "全部刪除" }))
    expect(await screen.findByText("沒有刪除，對話都還在。", {}, T)).toBeInTheDocument()
    expect(useAi.getState().threads).toHaveLength(1)
  })

  it("API：http 是 DELETE /ai/threads（查看別人時帶標頭，讓伺服器回 read_only）；mock 在查看模式回 read_only", async () => {
    const calls: { url: string; method: string; headers: Record<string, string> }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push({ url, method: init.method ?? "GET", headers: { ...(init.headers as Record<string, string>) } })
        return new Response(null, { status: 204 })
      }),
    )
    const http = createHttpAdapter("https://api.example.test")
    await http.deleteAiThreads()
    useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "accounts", accounts: [] })
    await http.deleteAiThreads()
    expect(calls.map((c) => [c.method, c.url, c.headers[VIEW_AS_HEADER]])).toEqual([
      ["DELETE", "https://api.example.test/api/v1/ai/threads", undefined],
      ["DELETE", "https://api.example.test/api/v1/ai/threads", "dlg_dad"],
    ])
    const mock = createMockAdapter({ latency: [0, 0] })
    await expect(mock.deleteAiThreads()).rejects.toMatchObject({ status: 403, code: "read_only" })
  })
})
