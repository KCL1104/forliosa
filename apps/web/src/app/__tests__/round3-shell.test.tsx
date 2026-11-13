import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest"
import { useAi } from "@/ai/store"
import type { Draft, Thread } from "@/ai/types"
import { createAppRouter } from "@/router"
import { ACCOUNT_ROUTES, DOCK_TABS, isAccountRoute, isQuietRoute, NAV_ITEMS, QUIET_ROUTES } from "../nav"

/**
 * 第三輪（外殼）：
 * - 導覽設定在一個地方（nav.ts）：頂部列、底部列、AI 面板預設收成窄欄的頁面。
 * - 手機底部列的分頁從內容的左緣開始；深色的「問 AI」平常只有框線（`data-pending` 才實心）；待簽名的筆數同一個畫面不寫兩次。
 * - 手機標題列有搜尋鈕，打開滿版的搜尋。
 * - 桌面 AI 面板：安靜的頁面預設是窄欄；在那裡打開後，換到別的安靜頁面也開著；有對話或草稿時換頁不收起來；紀錄頁不重複列對話。
 */
let desktop = false
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  // jsdom 沒有 matchMedia：`desktop` 決定是不是 ≥ 1024px
  window.matchMedia = ((query: string) => ({
    matches: desktop && /min-width:\s*1024px/.test(query), media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null })
beforeEach(() => act(resetAi))
afterEach(() => {
  cleanup()
  act(resetAi)
  desktop = false
})

const T = { timeout: 6000 }
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
const at = "2026-11-12T13:41:00+08:00"
const draft: Draft = {
  id: "d1", status: "pending", createdAt: at,
  input: { kind: "trade", side: "buy", code: "0050", quantity: 2000, price: 52.4 },
} as unknown as Draft
const thread: Thread = { id: "thr_1", title: "買 0050 2 張 52.4", updatedAt: at, messages: [{ id: "m1", role: "user", text: "買 0050 2 張 52.4", at }] }

describe("導覽設定（nav.ts）：一個地方", () => {
  it("頂部列三個目的地（帳本・群組・討論）、底部列同樣三個分頁（紀錄不在底部列）；個股頁算在帳本裡", () => {
    expect(NAV_ITEMS.map((n) => n.label)).toEqual(["帳本", "群組", "討論"])
    expect(DOCK_TABS.map((n) => n.label)).toEqual(["帳本", "群組", "討論"])
    const ledger = NAV_ITEMS[0]!
    expect(ledger.match("/")).toBe(true)
    expect(ledger.match("/stock/2330.TW")).toBe(true)
    expect(ledger.match("/settings")).toBe(false)
    expect(NAV_ITEMS[1]!.match("/groups/grp_family/members/usr_dad")).toBe(true)
    const discussions = NAV_ITEMS[2]!
    expect(discussions.to).toBe("/discussions")
    for (const p of ["/discussions", "/discussions/new", "/discussions/top_p_tsmc"]) expect(discussions.match(p)).toBe(true)
    for (const p of ["/", "/groups", "/admin/discussions", "/discussionsx"]) expect(discussions.match(p)).toBe(false)
  })

  it("安靜的頁面：群組（清單、群組、成員）、討論（清單、主題、開新主題）、站方管理、設定、紀錄、資料來源；帳本與個股頁不是", () => {
    expect([...QUIET_ROUTES]).toEqual(["/groups", "/discussions", "/admin", "/settings", "/history", "/data-sources"])
    for (const p of ["/groups", "/groups/grp_family", "/groups/grp_family/members/usr_dad", "/discussions", "/discussions/new", "/discussions/top_p_tsmc", "/admin/discussions", "/settings", "/history", "/data-sources"]) expect(isQuietRoute(p)).toBe(true)
    for (const p of ["/", "/stock/2330.TW", "/groupsx", "/settings-old", "/administrator"]) expect(isQuietRoute(p)).toBe(false)
    expect([...ACCOUNT_ROUTES]).toEqual(["/settings", "/data-sources", "/admin"])
    expect(isAccountRoute("/settings")).toBe(true)
    expect(isAccountRoute("/admin/discussions")).toBe(true)
    expect(isAccountRoute("/history")).toBe(false)
    expect(isAccountRoute("/discussions")).toBe(false)
  })
})

describe("手機底部列", () => {
  it("分頁從內容的左緣開始：選取的線畫在字上（和字一樣寬），可按範圍是整個連結", async () => {
    renderApp("/")
    const nav = await screen.findByRole("navigation", { name: "主要" }, T)
    const links = within(nav).getAllByRole("link")
    expect(links.map((l) => l.textContent)).toEqual(["帳本", "群組", "討論"])
    // 列和內容同一個左右邊界（20px）；分頁各自有左右內距，整組往左收回同樣的距離，第一個字落在邊界上
    expect(nav.parentElement!.className).toMatch(/\bpx-5\b/)
    expect(nav.className).toMatch(/-ml-4\b/)
    for (const link of links) {
      expect(link.className).toMatch(/\bpx-4\b/)
      expect(link.className).not.toMatch(/\bflex-1\b/)
      const label = link.querySelector("span")!
      expect(label.className).toMatch(/\bsel-tab-top\b/)
      expect(label.textContent).toBe(link.textContent)
    }
    expect(links[0]!.querySelector("span")).toHaveAttribute("data-active")
    expect(links[1]!.querySelector("span")).not.toHaveAttribute("data-active")
  })

  it("「問 AI」：平常沒有 data-pending（深色只有框線）；有草稿等簽名才有（實心）", async () => {
    renderApp("/groups")
    const ask = await screen.findByRole("button", { name: "問 AI" }, T)
    expect(ask).toHaveClass("ask-box")
    expect(ask).not.toHaveAttribute("data-pending")
    act(() => useAi.setState({ drafts: { d1: draft } }))
    const pending = await screen.findByRole("button", { name: "問 AI（待簽名 1 筆）" }, T)
    expect(pending).toHaveAttribute("data-pending")
    // 群組頁沒有別的地方寫筆數：格子裡寫
    expect(pending).toHaveTextContent("待簽名 1 筆")
  })

  it("帳本頁：分段下面已經有「待簽名 1 筆」那一條，格子裡不再寫一次筆數", async () => {
    act(() => useAi.setState({ drafts: { d1: draft } }))
    renderApp("/")
    const box = await screen.findByRole("button", { name: "問 AI（待簽名 1 筆）" }, T)
    expect(box).toHaveAttribute("data-pending")
    expect(box).toHaveTextContent(/^問 AI$/)
    await screen.findByText("總損益（含股利）", undefined, T)
    // 畫面上看得到的「待簽名 1 筆」只有帳本那一條
    const shown = screen.getAllByText(/待簽名 1 筆/).filter((el) => !el.closest(".dock"))
    expect(shown.length).toBeGreaterThan(0)
    expect(within(box).queryByText(/待簽名/)).toBeNull()
  })
})

describe("手機標題列的搜尋", () => {
  it("放大鏡（搜尋股票，44px）打開滿版的搜尋：輸入框、關閉鈕；搜尋到的股票可以按", async () => {
    const user = userEvent.setup()
    const router = renderApp("/")
    const open = await screen.findByRole("button", { name: "搜尋股票" }, T)
    expect(open.className).toMatch(/\bsize-11\b/)
    expect(open.querySelector("svg")).not.toBeNull()
    await user.click(open)
    const dialog = await screen.findByRole("dialog", { name: "搜尋股票與功能" }, T)
    // 滿版（不是桌面置中的小面板）：貼齊上緣、沒有圓角
    expect(dialog.className).toMatch(/\btop-0\b/)
    expect(dialog.className).toMatch(/\brounded-none\b/)
    expect(dialog.className).toMatch(/\bh-dvh\b/)
    const input = within(dialog).getByRole("combobox")
    await user.type(input, "台積")
    const hit = await within(dialog).findByRole("option", { name: /2330/ }, T)
    await user.click(hit)
    await waitFor(() => expect(router.state.location.pathname).toBe("/stock/2330.TW"))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "搜尋股票與功能" })).toBeNull())
  })

  it("關閉鈕關掉搜尋", async () => {
    const user = userEvent.setup()
    renderApp("/")
    await user.click(await screen.findByRole("button", { name: "搜尋股票" }, T))
    const dialog = await screen.findByRole("dialog", { name: "搜尋股票與功能" }, T)
    await user.click(within(dialog).getByRole("button", { name: "關閉搜尋" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "搜尋股票與功能" })).toBeNull())
  })
})

describe("桌面 AI 面板：安靜的頁面預設是窄欄", () => {
  beforeEach(() => {
    desktop = true
  })
  const rail = () => screen.queryByRole("button", { name: /^展開 AI 面板/ })
  const panel = () => screen.queryByRole("complementary", { name: "問 AI" })
  const go = async (router: ReturnType<typeof renderApp>, to: string) => {
    await act(async () => {
      await router.navigate({ to: to as "/" })
    })
  }

  it("帳本：面板開著（記住的狀態，預設開）；群組：窄欄", async () => {
    const router = renderApp("/")
    await screen.findByRole("complementary", { name: "問 AI" }, T)
    expect(rail()).toBeNull()
    await go(router, "/groups")
    await screen.findByRole("button", { name: "展開 AI 面板" }, T)
    expect(panel()).toBeNull()
    // 回到帳本：照記住的狀態（開）
    await go(router, "/")
    await screen.findByRole("complementary", { name: "問 AI" }, T)
  })

  it("在安靜的頁面自己打開：換到別的安靜頁面也開著（另外記），帳本的開合不受影響；收合後回到窄欄", async () => {
    const user = userEvent.setup()
    const router = renderApp("/groups")
    await user.click(await screen.findByRole("button", { name: "展開 AI 面板" }, T))
    await screen.findByRole("complementary", { name: "問 AI" }, T)
    expect(useAi.getState().quietPanelOpen).toBe(true)
    expect(useAi.getState().panelOpen).toBe(true)
    for (const to of ["/settings", "/history", "/data-sources"]) {
      await go(router, to)
      await waitFor(() => expect(router.state.location.pathname).toBe(to))
      expect(panel()).not.toBeNull()
    }
    await user.click(screen.getByRole("button", { name: "收合 AI 面板" }))
    await screen.findByRole("button", { name: "展開 AI 面板" }, T)
    expect(useAi.getState().quietPanelOpen).toBe(false)
    // 帳本那一邊另外記：還是開的
    expect(useAi.getState().panelOpen).toBe(true)
    await go(router, "/")
    await screen.findByRole("complementary", { name: "問 AI" }, T)
  })

  it("安靜頁面的開合不存檔：只有帳本那一邊的開合寫進 localStorage", () => {
    act(() => useAi.getState().setPanelOpen(true, true))
    const saved = JSON.parse(localStorage.getItem("forliosa:ai") ?? "{}") as { state?: Record<string, unknown> }
    expect(saved.state).toHaveProperty("panelOpen")
    expect(saved.state).not.toHaveProperty("quietPanelOpen")
  })

  it("面板裡開著一段對話：換到安靜的頁面不收起來；使用者自己收合才收", async () => {
    const user = userEvent.setup()
    act(() => useAi.setState({ threads: [thread], threadId: thread.id }))
    const router = renderApp("/")
    await screen.findByRole("complementary", { name: "問 AI" }, T)
    await go(router, "/settings")
    await screen.findByRole("heading", { level: 1, name: "設定" }, T)
    expect(panel()).not.toBeNull()
    expect(rail()).toBeNull()
    // 開新對話（對話關掉了）也不會在使用者眼前收起來
    await user.click(screen.getByRole("button", { name: "新對話" }))
    expect(panel()).not.toBeNull()
    await user.click(screen.getByRole("button", { name: "收合 AI 面板" }))
    await screen.findByRole("button", { name: "展開 AI 面板" }, T)
  })

  it("有草稿在等簽名：安靜的頁面也開著（重新整理後直接落在設定頁也一樣）", async () => {
    act(() => useAi.setState({ drafts: { d1: draft } }))
    renderApp("/settings")
    await screen.findByRole("heading", { level: 1, name: "設定" }, T)
    await screen.findByRole("complementary", { name: "問 AI" }, T)
    expect(rail()).toBeNull()
  })

  it("面板收成窄欄時，主欄記下多出來的寬度（--panel-slack）：版心的左緣不動；開著時沒有", async () => {
    const router = renderApp("/groups")
    await screen.findByRole("button", { name: "展開 AI 面板" }, T)
    const row = document.getElementById("main")!.parentElement!
    expect(row.className).toContain("[--panel-slack:284px]")
    expect(row.className).toContain("xl:[--panel-slack:344px]")
    await go(router, "/")
    await screen.findByRole("complementary", { name: "問 AI" }, T)
    expect(document.getElementById("main")!.parentElement!.className).not.toContain("--panel-slack")
  })

  it("紀錄頁：面板不重複列「最近的對話」（頁面本身就是對話清單）；設定頁照常列", async () => {
    act(() => useAi.setState({ quietPanelOpen: true }))
    const router = renderApp("/settings")
    const aside = await screen.findByRole("complementary", { name: "問 AI" }, T)
    await within(aside).findByRole("list", { name: "最近的對話" }, T)
    await go(router, "/history")
    await screen.findByRole("button", { name: "發起新對話" }, T)
    const onHistory = screen.getByRole("complementary", { name: "問 AI" })
    await waitFor(() => expect(within(onHistory).queryByRole("list", { name: "最近的對話" })).toBeNull())
    // 頁面自己的清單還在
    expect(within(document.getElementById("main")!).getByRole("list", { name: "對話" })).toBeInTheDocument()
  })

  it("設定、資料來源頁：頭像下面畫導覽的線（data-active），選單裡的項目標目前頁面；帳本不標", async () => {
    const user = userEvent.setup()
    const router = renderApp("/settings")
    const avatar = await screen.findByRole("button", { name: /^帳號選單/ }, T)
    expect(avatar).toHaveAttribute("data-active")
    expect(avatar.className).toMatch(/\blg:sel-tab\b/)
    // 不是連結：不標 aria-current（只留給導覽）
    expect(avatar).not.toHaveAttribute("aria-current")
    await user.click(avatar)
    expect(await screen.findByRole("menuitem", { name: "設定" }, T)).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("menuitem", { name: "資料來源與授權" })).not.toHaveAttribute("aria-current")
    await user.keyboard("{Escape}")
    await go(router, "/")
    await screen.findByText("總損益（含股利）", undefined, T)
    expect(screen.getByRole("button", { name: /^帳號選單/ })).not.toHaveAttribute("data-active")
  })
})
