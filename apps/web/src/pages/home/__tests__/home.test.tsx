import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import type { ForliosaApi } from "@/api/types"
import { ABOUT_FORLIOSA, ABOUT_SHORT } from "@/lib/about"
import { isHomePath, isPublicReadPath } from "@/lib/next-path"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 沒登入的首頁（`/`）：簡短的介紹頁，不是登入頁。登入後同一個網址是帳本；其他要登入的頁面照舊導到登入頁。
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
    </QueryClientProvider>,
  )
  return router
}

describe("首頁是哪一個路徑", () => {
  it("只有「/」；它不算在「不用登入就能讀的頁面」裡（那些用路由自己的內容）", () => {
    expect(isHomePath("/")).toBe(true)
    expect(isHomePath("/login") || isHomePath("/discussions") || isHomePath("/stock/2330.TW")).toBe(false)
    expect(isPublicReadPath("/")).toBe(false)
  })

  it("標題的那一句是產品說明的前半句", () => {
    expect(ABOUT_SHORT).toBe("股票帳本")
    expect(ABOUT_FORLIOSA).toContain(ABOUT_SHORT)
  })
})

describe("沒登入的首頁：簡短的介紹頁", () => {
  it("留在「/」、不導到登入頁；一句話、三個標「示範資料」的畫面、頁尾兩份條款；沒有登入按鈕以外的動作", async () => {
    mount({ signedIn: false })
    const router = renderApp("/")
    expect(await screen.findByRole("heading", { level: 1, name: ABOUT_SHORT }, T)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/")
    expect(document.title).toBe("Forliosa")
    // 外殼：字標連到首頁、導覽只有「討論」（不是選取中）、「登入」不帶 next（登入後就是帳本）
    expect(screen.getByRole("link", { name: "Forliosa 首頁" })).toHaveAttribute("href", "/")
    const nav = within(screen.getByRole("navigation", { name: "主要" })).getAllByRole("link")
    expect(nav.map((a) => `${a.textContent}:${a.getAttribute("href")}:${a.getAttribute("aria-current")}`)).toEqual(["討論:/discussions:null"])
    const login = screen.getAllByRole("link", { name: "登入" })
    expect(login).toHaveLength(1) // 這一頁只有一顆「登入」
    expect(login[0]).toHaveAttribute("href", "/login")
    // 頁首用整個版心（不是讀的頁面的欄寬）
    expect(screen.getByRole("link", { name: "Forliosa 首頁" }).parentElement!.className).not.toMatch(/\bmax-w-measure\b/)
    // 三個示範畫面：標題、每個都標「示範資料」、給螢幕報讀器的一句說明；畫面本身是 aria-hidden，裡面沒有可以按的東西
    const figures = screen.getAllByRole("figure")
    expect(figures.map((f) => within(f).getByRole("heading", { level: 2 }).textContent)).toEqual(["帳本", "個股", "問 AI"])
    for (const f of figures) {
      expect(within(f).getAllByText("示範資料")).toHaveLength(1)
      expect(f.querySelector("figcaption .sr-only")!.textContent).toMatch(/^示範畫面：/)
      const body = f.querySelector(":scope > [aria-hidden='true']")!
      expect(body).not.toBeNull()
      expect(body.querySelectorAll("a, button, input, select, textarea, [tabindex]")).toHaveLength(0)
    }
    // 示範資料：帳本的總資產、個股的收盤價與漲跌、草稿卡的合計與簽名格
    const [ledger, stock, draft] = figures as [HTMLElement, HTMLElement, HTMLElement]
    expect(ledger).toHaveTextContent("3,707,922")
    expect(stock).toHaveTextContent("1,085")
    expect(stock).toHaveTextContent("▲4.83%")
    expect(draft).toHaveTextContent("買 0050 2 張 52.4")
    expect(draft).toHaveTextContent("NT$104,841")
    expect(draft.querySelector(".sign-box")).toHaveTextContent("簽名確認入帳")
    // 畫面上沒有日期（寫死的日期會過期）
    expect(document.querySelector("main")!.textContent).not.toMatch(/\d{1,2}\/\d{1,2}|20\d\d/)
    // 頁尾：兩份條款
    const footer = document.querySelector("main footer")!
    expect([...footer.querySelectorAll("a")].map((a) => `${a.textContent}:${a.getAttribute("href")}`)).toEqual(["服務條款:/terms", "隱私權政策:/privacy"])
    // 沒有登入後才有的東西，也沒有登入頁的按鈕；沒登入時不去問帳本的資料
    expect(screen.queryByRole("button", { name: /問 AI/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /^用 (Google|Discord) 登入$/ })).toBeNull()
    expect(document.querySelector(".dock")).toBeNull()
    expect(screen.queryByText("總資產", { selector: "b" })).toBeNull()
    expect(api.getMe).toHaveBeenCalledTimes(1)
    expect(api.getPortfolioSummary).not.toHaveBeenCalled()
  })

  it("帶著參數的首頁（/?view=transactions）也是介紹頁；「登入」帶著原本的網址", async () => {
    mount({ signedIn: false })
    const router = renderApp("/?view=transactions")
    expect(await screen.findByRole("heading", { level: 1, name: ABOUT_SHORT }, T)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/")
    expect(screen.getByRole("link", { name: "登入" })).toHaveAttribute("href", "/login?next=%2F%3Fview%3Dtransactions")
  })

  it("其他要登入的頁面照舊：導到登入頁，帶著原本的網址", async () => {
    mount({ signedIn: false })
    const router = renderApp("/settings")
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"), T)
    expect(router.state.location.search).toEqual({ next: "/settings" })
    expect(screen.queryByRole("heading", { level: 1, name: ABOUT_SHORT })).toBeNull()
  })
})

describe("登入後的首頁", () => {
  it("是帳本，不是介紹頁", async () => {
    mount()
    renderApp("/")
    expect((await screen.findAllByText("總資產", undefined, T)).length).toBeGreaterThan(0)
    expect(screen.queryByRole("heading", { level: 1, name: ABOUT_SHORT })).toBeNull()
    expect(screen.queryByRole("link", { name: "Forliosa 首頁" })).toBeNull()
    expect(document.title).toBe("帳本｜Forliosa")
  })
})
