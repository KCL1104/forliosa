import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createHttpAdapter } from "@/api/http"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { listTransactionsUpTo } from "@/api/queries"
import type { ForliosaApi } from "@/api/types"
import { useViewAs, VIEW_AS_HEADER } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { Toaster } from "@/components/ui/sonner"
import { sameAccountName } from "@/lib/account-name"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))
// 數字動畫（NumberFlow 是 web component）在 jsdom 裡更新數字會丟錯：刪掉一筆之後總資產會變，換成一般的字
vi.mock("@number-flow/react", () => ({
  default: ({ value, format, locales }: { value: number; format?: Intl.NumberFormatOptions; locales?: string }) => <span>{new Intl.NumberFormat(locales, format).format(value)}</span>,
}))

/**
 * 產品負責人 2026-11-14 照建議決定的三件事：
 * - 記一筆（2026-11-14 第二次）：照 Google 財經分兩步，先選股票，再填股數、買進日期（月曆，一定要選）與價格；「只記持股」取消；
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

/** 打開記一筆（帳本右上的「記一筆」） */
async function openQuickAdd() {
  const user = userEvent.setup({ pointerEventsCheck: 0 })
  await user.click((await screen.findAllByRole("button", { name: "記一筆" }, T))[0]!)
  return screen.findByRole("dialog", { name: "記一筆" }, T)
}

describe("記一筆：先選股票，再填股數、買進日期、價格（產品負責人 2026-11-14，照 Google 財經）", { timeout: 20_000 }, () => {
  it("第一步：沒打字時列持有的與觀察清單（現價、漲跌），「新增」不能按；選了才出現股數、日期、價格；✕ 回到第一步", async () => {
    mount()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const dialog = await openQuickAdd()
    const held = await within(dialog).findByRole("group", { name: "持有的" }, T)
    const tsmc = within(held).getByRole("option", { name: /2330.*台積電/ })
    expect(tsmc).toHaveTextContent("1,085")
    expect(within(dialog).getByRole("group", { name: "觀察清單" })).toHaveTextContent("廣達")
    expect(within(dialog).queryByRole("textbox", { name: "張數" })).toBeNull()
    expect(within(dialog).getByRole("button", { name: "新增" })).toBeDisabled()

    await user.click(tsmc)
    const card = await within(dialog).findByRole("group", { name: "選好的股票" }, T)
    expect(card).toHaveTextContent("2330")
    expect(card).toHaveTextContent("台積電")
    expect(within(dialog).getByRole("textbox", { name: "張數" })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "買進日期，還沒選" })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "新增" })).toBeEnabled()

    await user.click(within(card).getByRole("button", { name: "改選其他股票" }))
    expect(await within(dialog).findByRole("group", { name: "持有的" }, T)).toBeInTheDocument()
    expect(within(dialog).queryByRole("textbox", { name: "張數" })).toBeNull()
  })

  it("買進日期一開始空白、一定要選；月曆選一天之後，價格下面有那天的收盤價，點一下才填入；新增記成那一天的買進", async () => {
    mount()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const dialog = await openQuickAdd()
    await user.click(await within(dialog).findByRole("option", { name: /2330.*台積電/ }, T))
    await user.type(await within(dialog).findByRole("textbox", { name: "張數" }, T), "1")
    await user.click(within(dialog).getByRole("button", { name: "新增" }))
    expect(within(dialog).getByText("請選買進日期")).toBeInTheDocument()
    expect(within(dialog).getByText("請輸入價格")).toBeInTheDocument()

    await user.click(within(dialog).getByRole("button", { name: "買進日期，還沒選" }))
    // 今天以後的日子不能選
    expect(await screen.findByRole("button", { name: /2026 年 11 月 13 日/ }, T)).toBeDisabled()
    await user.click(screen.getByRole("button", { name: /2026 年 11 月 10 日/ }))
    expect(await within(dialog).findByRole("button", { name: "買進日期：2026/11/10（二）" }, T)).toBeInTheDocument()

    const { close } = await api.getDailyClose("2330.TW", "2026-11-10")
    expect(close).not.toBeNull()
    const price = within(dialog).getByRole("textbox", { name: "買進價格" })
    expect(price).toHaveValue("")
    await user.click(await within(dialog).findByRole("button", { name: /^用 11\/10 收盤 .* 填入價格$/ }, T))
    expect(price).toHaveValue(String(close))

    await user.click(within(dialog).getByRole("button", { name: "新增" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "記一筆" })).toBeNull(), T)
    const buys = (await api.listTransactions({ symbol: "2330.TW", limit: 50 })).items.filter((t) => t.type === "buy" && t.trade_date === "2026-11-10")
    expect(buys.map((t) => [t.quantity, t.price])).toEqual([[1000, close]])
  })

  it("存檔開始以前的日期沒有收盤價：價格下面什麼都不寫", async () => {
    mount()
    expect((await api.getDailyClose("2330.TW", "2024-03-15")).close).toBeNull()
    expect((await api.getDailyClose("2330.TW", "2026-11-10")).close).toBeGreaterThan(0)
  })

  it("持倉的「加碼」直接到第二步（那一檔選好），焦點在股數", async () => {
    mount()
    renderApp("/")
    await screen.findByRole("table", { name: "持倉" }, T)
    act(() => useUi.getState().openTradeForm({ symbol: "2330" }))
    const dialog = await screen.findByRole("dialog", { name: "記一筆" }, T)
    expect(await within(dialog).findByRole("group", { name: "選好的股票" }, T)).toHaveTextContent("台積電")
    await waitFor(() => expect(within(dialog).getByRole("textbox", { name: "張數" })).toHaveFocus(), T)
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

describe("持倉展開每一筆買賣（產品負責人 2026-11-14，參考 Google 財經）", { timeout: 20_000 }, () => {
  const expand = async (name: string) => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const table = await screen.findByRole("table", { name: "持倉" }, T)
    await user.click(within(table).getByRole("button", { name: `展開${name}的每一筆買賣` }))
    return within(table).findByRole("list", { name: `${name}的每一筆買賣` }, T)
  }

  it("展開台積電：每一筆的日期（不是今年寫出年份）、類型、股數、價格、金額、買進後漲跌；再按一次收起", async () => {
    mount()
    renderApp("/")
    const list = await expand("台積電")
    const rows = within(list).getAllByRole("listitem")
    expect(rows).toHaveLength(2)
    // 新的在前；2024/8/6 買 500 股 815 → 今天 1,085：+33.13%
    expect(rows[0]).toHaveTextContent("2024/8/6（二）")
    expect(rows[0]).toHaveTextContent("買進")
    expect(rows[0]).toHaveTextContent("500 股")
    expect(rows[0]).toHaveTextContent("NT$407,500")
    expect(rows[0]).toHaveTextContent("33.13%")
    expect(rows[1]).toHaveTextContent("2023/3/15（三）")
    expect(rows[1]).toHaveTextContent("71.95%")
    const table = screen.getByRole("table", { name: "持倉" })
    const toggle = within(table).getByRole("button", { name: "收起台積電的每一筆買賣" })
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    await userEvent.setup({ pointerEventsCheck: 0 }).click(toggle)
    expect(within(table).queryByRole("list", { name: "台積電的每一筆買賣" })).toBeNull()
  })

  it("每一筆的 ⋯：修改打開完整表單（帶入那一筆，日期可以改）；刪除先確認，刪掉之後清單少一列", async () => {
    mount()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    let list = await expand("台積電")
    await user.click(within(list).getByRole("button", { name: "2024/8/6（二） 買進的動作" }))
    await user.click(await screen.findByRole("menuitem", { name: "修改" }, T))
    const dialog = await screen.findByRole("dialog", { name: "編輯交易" }, T)
    expect(within(dialog).getByRole("button", { name: "日期" })).toHaveTextContent("2024/8/6（二）")
    act(() => useUi.getState().closeTradeForm())
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "編輯交易" })).toBeNull(), T)

    list = screen.getByRole("list", { name: "台積電的每一筆買賣" })
    await user.click(within(list).getByRole("button", { name: "2023/3/15（三） 買進的動作" }))
    await user.click(await screen.findByRole("menuitem", { name: "刪除" }, T))
    const confirm = await screen.findByRole("alertdialog", undefined, T)
    expect(confirm).toHaveTextContent("刪除這筆買進？")
    await user.click(within(confirm).getByRole("button", { name: "刪除" }))
    await waitFor(() => expect(api.deleteTransaction).toHaveBeenCalledTimes(1), T)
    await waitFor(() => expect(within(screen.getByRole("list", { name: "台積電的每一筆買賣" })).getAllByRole("listitem")).toHaveLength(1), T)
  })

  it("最下面：再加一筆買進（記一筆、這一檔帶好）、減少持股", async () => {
    mount()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    await expand("台積電")
    await user.click(screen.getByRole("button", { name: "再加一筆買進" }))
    expect(useUi.getState().tradeForm).toMatchObject({ open: true, symbol: "2330" })
    act(() => useUi.getState().closeTradeForm())
    await user.click(screen.getByRole("button", { name: "減少持股" }))
    expect(useUi.getState().reduce).toMatchObject({ open: true, symbol: "2330.TW" })
    act(() => useUi.setState({ reduce: { open: false } }))
  })

  it("分割過的那一檔（NVDA）不列買進後漲跌，最下面寫一句；隱私模式遮住股數、價格、金額", async () => {
    mount()
    renderApp("/")
    const list = await expand("NVIDIA")
    expect(within(list).getAllByRole("listitem").length).toBeGreaterThan(0)
    expect(list.parentElement!.parentElement).toHaveTextContent("配過股或分割過，不列每一筆的漲跌。")
    expect(list).not.toHaveTextContent("%")
    cleanup()
    act(() => usePrefs.setState({ privacyMode: true }))
    try {
      renderApp("/")
      const masked = await expand("台積電")
      expect(masked).not.toHaveTextContent("NT$407,500")
      expect(masked).not.toHaveTextContent("500 股")
      expect(masked).toHaveTextContent("2024/8/6（二）")
    } finally {
      act(() => usePrefs.setState({ privacyMode: false }))
    }
  })
})
