import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import { useViewAs, type ViewAsTarget } from "@/api/view-as"
import { Segmented } from "@/components/segmented"
import { PerformanceView } from "@/pages/ledger/PerformanceView"
import { TransactionsView } from "@/pages/ledger/TransactionsView"
import { createAppRouter } from "@/router"

/**
 * 第二輪設計修飾（外殼與帳本）：
 * 手機底部列是文字分頁＋「問 AI」方格；`aria-current="page"` 只在導覽上；
 * 主數字沒有卡片與展開鈕；數字鍵 1–4 切換分段；績效算不出來時不放沒有用的控制項；交易的數量與價格分欄。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  // jsdom 沒有 matchMedia：一律當手機（< 1024px）
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  useViewAs.getState().set(null)
})

const T = { timeout: 4000 }
const DAD: ViewAsTarget = {
  delegation_id: "dlg_dad",
  owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null },
  scope: "accounts",
  accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }],
}
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

function renderApp(path: string) {
  const qc = client()
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}
function renderInRouter(ui: React.ReactNode) {
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(
    <QueryClientProvider client={client()}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}

describe("手機底部列", () => {
  it("文字分頁「帳本｜市場｜群組｜討論」（選取語法 a，沒有圖示）＋「問 AI」方格（不是膠囊）", async () => {
    renderApp("/")
    const nav = await screen.findByRole("navigation", { name: "主要" }, T)
    const links = within(nav).getAllByRole("link")
    expect(links.map((l) => l.textContent)).toEqual(["帳本", "市場", "群組", "討論"])
    // 選取語法 (a) 的底部列版本畫在字上（第三輪：線和字一樣寬、對齊內容的左緣；可按範圍是整個連結）
    for (const link of links) {
      expect(link.querySelector("span")!.className).toMatch(/\bsel-tab-top\b/)
      expect(link.querySelector("svg")).toBeNull()
    }
    expect(links[0]!.querySelector("span")).toHaveAttribute("data-active")
    expect(links[1]!.querySelector("span")).not.toHaveAttribute("data-active")
    expect(links[0]).toHaveAttribute("aria-current", "page")
    expect(links[1]).not.toHaveAttribute("aria-current")
    expect(links[2]).not.toHaveAttribute("aria-current")
    // 底部列本身：平的（.dock），不浮起、沒有陰影或圓角的 class
    const bar = nav.closest(".dock")!
    expect(bar).not.toBeNull()
    expect(bar.innerHTML).not.toMatch(/rounded-full|shadow-lift|bg-gradient/)
    const ask = within(bar as HTMLElement).getByRole("button", { name: "問 AI" })
    expect(ask.className).toMatch(/\bask-box\b/)
    expect(ask.querySelector("svg")).toBeNull()
    // 內容下方留的是底部列的高度（--dock-h），不是寫死的 104px
    expect(document.getElementById("main")!.className).toContain("var(--dock-h)")
  })

  it("查看別人的資產：「問 AI」那一格換成墨色的「結束查看」（簽名格語法）", async () => {
    useViewAs.getState().set(DAD)
    renderApp("/")
    const nav = await screen.findByRole("navigation", { name: "主要" }, T)
    const bar = nav.closest(".dock") as HTMLElement
    const exit = within(bar).getByRole("button", { name: "正在查看爸爸的資產（唯讀），結束查看" })
    expect(exit.className).toMatch(/\bsign-box\b/)
    expect(exit).toHaveTextContent("結束查看")
    expect(within(bar).queryByRole("button", { name: /^問 AI/ })).toBeNull()
  })
})

describe('aria-current="page" 只在導覽上', () => {
  it("字標、本週事項那一列連到目前的網址，也不標「目前頁面」", async () => {
    renderApp("/?view=dividends")
    const week = await screen.findByRole("link", { name: /^本週 \d+ 件事，查看全部$/ }, T)
    // 這個連結的目標就是目前的網址（/?view=dividends）
    expect(week).toHaveAttribute("href", "/?view=dividends")
    expect(week).not.toHaveAttribute("aria-current")
    expect(screen.getByRole("link", { name: "Forliosa 帳本" })).not.toHaveAttribute("aria-current")
    const current = document.querySelectorAll('[aria-current="page"]')
    expect(current).toHaveLength(1)
    expect(current[0]!.closest("nav")).toHaveAttribute("aria-label", "主要")
    expect(current[0]).toHaveTextContent("帳本")
  })
})

describe("帳本主數字與分段", () => {
  it("手機主數字是平的：沒有卡片、沒有展開鈕，今日與總損益直接看得到；本週事項的第一格是日期格", async () => {
    renderApp("/")
    expect(await screen.findByText("總損益（含股利）", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("今日")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /總損益與走勢/ })).toBeNull()
    expect(screen.queryByRole("region", { name: "總資產" })).toBeNull()
    const week = await screen.findByRole("link", { name: /^本週 \d+ 件事，查看全部$/ }, T)
    expect(week.firstElementChild).toHaveClass("date-cell")
    expect(week.querySelector("svg")).toBeNull()
  })

  it("數字鍵 1–4 切換分段；焦點在輸入框裡、或按著修飾鍵時不動作", async () => {
    const router = renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    const view = () => (router.state.location.search as { view?: string }).view
    fireEvent.keyDown(document.body, { key: "2" })
    await waitFor(() => expect(view()).toBe("transactions"))
    fireEvent.keyDown(document.body, { key: "4" })
    await waitFor(() => expect(view()).toBe("performance"))
    fireEvent.keyDown(document.body, { key: "3", metaKey: true })
    const input = document.createElement("input")
    document.body.append(input)
    fireEvent.keyDown(input, { key: "3" })
    await new Promise((r) => setTimeout(r, 50))
    expect(view()).toBe("performance")
    input.remove()
    fireEvent.keyDown(document.body, { key: "1" })
    await waitFor(() => expect(view()).toBeUndefined())
  })

  it("分段：觸控與手機版面每一段 44px，快速鍵寫在 aria-keyshortcuts", () => {
    render(
      <Segmented
        label="帳本內容"
        value="holdings"
        onChange={() => {}}
        options={[
          { value: "holdings", label: "持倉", shortcut: "1" },
          { value: "transactions", label: "交易", shortcut: "2" },
        ]}
      />,
    )
    const tabs = screen.getAllByRole("tab")
    expect(tabs.map((t) => t.getAttribute("aria-keyshortcuts"))).toEqual(["1", "2"])
    for (const tab of tabs) {
      expect(tab.className).toMatch(/\bmax-lg:h-11\b/)
      expect(tab.className).toMatch(/\bpointer-coarse:h-11\b/)
    }
  })
})

describe("績效算不出來（示範帳本含美股）", () => {
  it("只留帳戶選單與一段說明，沒有區間與比較基準；選了新台幣帳戶，控制項才出現", async () => {
    const user = userEvent.setup()
    renderInRouter(<PerformanceView />)
    expect(await screen.findByText("績效還算不出來", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("radiogroup", { name: "績效區間" })).toBeNull()
    expect(screen.queryByRole("combobox", { name: "績效比較基準" })).toBeNull()
    expect(screen.getByRole("combobox", { name: "帳戶" })).toBeInTheDocument()
    // 原因只說一次；最多一個動作
    expect(screen.getAllByText(/美股沒有報價，含美股的績效算不出來/)).toHaveLength(1)
    // 帳戶是另一個查詢：等它回來才有「只看「…」」
    const actions = await screen.findAllByRole("button", { name: /^只看「/ }, T)
    expect(actions).toHaveLength(1)
    await user.click(actions[0]!)
    expect(await screen.findByRole("radiogroup", { name: "績效區間" }, T)).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "績效比較基準" })).toBeInTheDocument()
  })
})

describe("交易列表的表頭", () => {
  it("數量與價格是兩欄，帳戶排在商品後面", async () => {
    renderInRouter(<TransactionsView />)
    const product = await screen.findByText("商品", undefined, T)
    const head = product.closest(".form-head")!
    expect([...head.children].map((c) => c.textContent)).toEqual(["日期", "類型", "商品", "帳戶", "數量", "價格", "金額", "稅費", "動作"])
    expect(document.body.textContent).not.toContain("數量 × 價格")
  })
})
