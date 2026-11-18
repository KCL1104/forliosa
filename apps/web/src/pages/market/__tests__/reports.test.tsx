import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { buildMockReport, publicView } from "@/api/mock/market-reports"
import type { ForliosaApi } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 市場報告（2026-11-17）：市場頁的「報告」分頁、報告頁、導覽的未讀圓點。
 * 每一份都對所有登入的人公開（盲測 2026-11-18 拿掉了；mock 預設 public，三種都有 AI 版）。
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
  window.matchMedia = ((query: string) => ({
    // 桌面（≥ 1024px）由測試切換；其他媒體查詢一律 false
    matches: desktop && /min-width: 1024px/.test(query), media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null, ownerId: null })
beforeEach(() => {
  desktop = false
  act(resetAi)
})
afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
  vi.useRealTimers()
  useViewAs.getState().set(null)
  act(resetAi)
})

const T = { timeout: 6000 }

function mount(options: MockOptions = {}) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  const spies = {} as Record<keyof ForliosaApi, ReturnType<typeof vi.spyOn>>
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") spies[key] = vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  return spies
}

function renderApp(path = "/market") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const report = async () => (await screen.findByRole("heading", { level: 2, name: /^(盤前重點|盤後重點|市場週報) / }, T)).closest("article")!

describe("市場頁的分頁「行情｜報告」", () => {
  it("不是站方管理員：有分頁列，報告分頁是同一份公開的報告（沒有 A／B／C、沒有投票）；報告頁看得到", async () => {
    mount({ discussion: { admin: false } })
    renderApp("/market?tab=reports&kind=premarket")
    const tabs = await screen.findByRole("tablist", { name: "市場內容" }, T)
    expect(within(tabs).getByRole("tab", { name: "報告" })).toHaveAttribute("aria-selected", "true")
    const article = await report()
    expect(within(article).getByText("這份報告的 AI 段落由 Anthropic 的 Claude 模型撰寫。")).toBeInTheDocument()
    // 盲測拿掉了：一份報告、沒有版本切換與投票
    expect(screen.queryByRole("radiogroup", { name: /版本|看哪一個/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /選 [ABC]|投票|選這一個/ })).toBeNull()
    expect(screen.queryByText(/盲測/)).toBeNull()
    expect(screen.getAllByRole("article")).toHaveLength(1)
    cleanup()
    renderApp("/market/reports/mrp_premarket_20261112")
    expect(await report()).toBeInTheDocument()
    expect(screen.queryByText("找不到這份報告")).toBeNull()
    expect(screen.queryByText(/盲測/)).toBeNull()
  })

  it("伺服器沒有開：管理員也沒有分頁列", async () => {
    mount({ reports: "off" })
    renderApp("/market")
    expect(await screen.findByRole("heading", { name: "類股" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("tablist", { name: "市場內容" })).toBeNull()
  })

  it("站方管理員：有分頁列；報告分頁預設是最新發布的那一種，選項記在網址；換成週報", async () => {
    mount()
    const router = renderApp("/market")
    const tabs = await screen.findByRole("tablist", { name: "市場內容" }, T)
    expect(within(tabs).getByRole("tab", { name: "行情" })).toHaveAttribute("aria-selected", "true")
    fireEvent.click(within(tabs).getByRole("tab", { name: "報告" }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ tab: "reports" }), T)
    const kinds = await screen.findByRole("radiogroup", { name: "報告種類" }, T)
    expect(within(kinds).getAllByRole("radio").filter((r) => r.getAttribute("aria-checked") === "true")).toHaveLength(1)
    expect(await report()).toBeInTheDocument()
    fireEvent.click(within(kinds).getByRole("radio", { name: "週報" }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ tab: "reports", kind: "weekly" }), T)
    expect(await screen.findByRole("heading", { level: 2, name: /^市場週報 / }, T)).toBeInTheDocument()
  })
})

describe("報告頁", () => {
  it("由上到下：免責一行與資料截至、名稱、一句話、重點、數字欄、各段、行事曆、來源、完整免責、模型行；畫面上沒有 F001／X003", async () => {
    desktop = true
    mount({ reports: "public" })
    renderApp("/market?tab=reports&kind=close")
    const article = await report()
    const text = article.textContent ?? ""
    const order = [
      "AI 依公開資料與媒體報導整理，報告本文人人相同，可能有錯；Forliosa 不是投資顧問，不提供投資建議。",
      "資料截至",
      "已更正（",
      "盤後重點 11/11（三）",
      "上市普通股上漲",
      "加權指數",
      "今天發生什麼",
      "類股",
      "權值股與個股",
      "籌碼",
      "11/12 行事曆",
      "來源",
      "這份報告由 AI 依公開資料與媒體報導整理",
      "這份報告的 AI 段落由 Anthropic 的 Claude 模型撰寫。",
    ]
    let at = -1
    for (const piece of order) {
      const next = text.indexOf(piece, at + 1)
      expect(next, piece).toBeGreaterThan(at)
      at = next
    }
    // 編號（F001、X003、C001…）只在管理員檢視；一般的頁面絕不出現
    expect(text).not.toMatch(/\b[FXCNW]\d{3}\b/)
    expect(article.querySelector("[data-refs]")).toBeNull()
    // 有圖的段標「資料」，段裡的 AI 文字開始的地方標「AI 依資料與報導整理」
    const sectors = within(article).getByRole("heading", { level: 3, name: "類股" }).closest("section")!
    expect(within(sectors.querySelector("header")!).getByText("資料")).toBeInTheDocument()
    expect(within(sectors).getByText("AI 依資料與報導整理")).toBeInTheDocument()
    // 註腳是上標的號碼，連到來源的那一條；那一條的號碼連回原句
    const cite = article.querySelector<HTMLAnchorElement>("sup a[data-fn-ref]")!
    expect(cite.getAttribute("href")).toMatch(/^#fn-\d+$/)
    const target = article.querySelector(cite.getAttribute("href")!)!
    expect(target.tagName).toBe("LI")
    expect(within(target as HTMLElement).getByRole("link", { name: /回到出處 \d+ 的原句/ })).toBeInTheDocument()
    // 圖：類股是雙向橫條（類股內的漲跌家數與集中度寫在名稱下面）；點數貢獻標「估算」與官方漲跌
    expect(within(article).getByText(/^漲 \d+・跌 \d+・主要由台積電構成（約 77%）$/)).toBeInTheDocument()
    const g3 = within(article).getByText(/^市值前 10 的點數貢獻/).closest("figure")!
    expect(within(g3).getByText("估算")).toBeInTheDocument()
    expect(within(g3).getByText(/^官方漲跌/)).toBeInTheDocument()
    // 表：規則寫在表頭；有連結的列整列連到個股頁
    expect(within(article).getAllByText("範圍：市值前 200 名或 300 億元以上；排除創新板、全額交割、處置股").length).toBeGreaterThan(0)
    expect(within(article).getAllByRole("link", { name: /台積電（2330）/ })[0]).toHaveAttribute("href", "/stock/2330.TW")
  })

  it("手機：預設收合的段，標題是按鈕（aria-expanded）；桌面一律展開、沒有收合鈕", async () => {
    mount({ reports: "public" })
    renderApp("/market?tab=reports&kind=close")
    const article = await report()
    const toggle = within(article).getByRole("button", { name: "權值股與個股" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).not.toBeVisible()
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toBeVisible()
    // 「今天發生什麼」「類股」不收合：沒有按鈕
    expect(within(article).queryByRole("button", { name: "今天發生什麼" })).toBeNull()
    expect(within(article).getByRole("heading", { level: 3, name: "今天發生什麼" })).toBeInTheDocument()
    expect(within(article).queryByRole("button", { name: "類股" })).toBeNull()
  })

  it("AI 段落還在整理：只有資料的版本，寫一行狀態；沒有模型行", async () => {
    mount({ reports: "pending" })
    renderApp("/market?tab=reports&kind=premarket")
    const article = await report()
    expect(within(article).getByText("AI 段落還在整理，這是只有資料的版本。")).toBeInTheDocument()
    expect(within(article).getByText(/^依公開資料整理，報告本文人人相同；Forliosa 不是投資顧問，不提供投資建議。/)).toBeInTheDocument()
    expect(within(article).queryByText("這份報告的 AI 段落由 Anthropic 的 Claude 模型撰寫。")).toBeNull()
    // 規則寫的標題不重複上面的名稱與日期
    expect(article.querySelector("[data-report-title]")!.textContent).toMatch(/^美股 11\/11 收盤與今日行事曆$/)
  })

  it("更早的報告：一份一列，整列連到那一份；報告頁的分頁列選在「報告」", async () => {
    mount({ reports: "public" })
    const router = renderApp("/market?tab=reports&kind=close")
    const earlier = (await screen.findByRole("heading", { name: "更早的報告" }, T)).closest("section")!
    const links = within(earlier).getAllByRole("link")
    expect(links.length).toBeGreaterThan(3)
    expect(links.every((a) => /^\/market\/reports\/mrp_close_/.test(a.getAttribute("href") ?? ""))).toBe(true)
    // 只有資料的那一份標出來
    expect(within(earlier).getAllByText(/只有資料/).length).toBeGreaterThan(0)
    fireEvent.click(links[0]!)
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/market\/reports\/mrp_close_/), T)
    const tabs = await screen.findByRole("tablist", { name: "市場內容" }, T)
    expect(within(tabs).getByRole("tab", { name: "報告" })).toHaveAttribute("aria-selected", "true")
    await waitFor(() => expect(document.title).toMatch(/^盤後重點 .+｜Forliosa$/), T)
  })

  it("官方加權指數沒進來：數字欄是上市市值估算，加權指數的圖換成一行說明", async () => {
    mount({ reports: "public" })
    renderApp("/market/reports/mrp_close_20261104")
    const article = await report()
    expect(within(article).getByText("官方加權指數尚未取得，數字欄的上市市值變化是 Forliosa 估算。")).toBeInTheDocument()
    const strip = within(article).getByRole("list", { name: "數字" })
    expect(within(strip).getByText("上市市值變化")).toBeInTheDocument()
    expect(within(strip).getAllByText("估算").length).toBeGreaterThan(0)
  })
})

describe("未讀圓點", () => {
  it("有新的報告：導覽「市場」旁一個小圓點、名稱多「（有新的市場報告）」；打開報告分頁 1.2 秒後記成看過", async () => {
    const spies = mount()
    renderApp("/market")
    const nav = (await screen.findAllByRole("navigation", { name: "主要" }))[0]!
    const link = await within(nav).findByRole("link", { name: "市場（有新的市場報告）" }, T)
    expect(link.querySelector("[data-reports-dot]")).not.toBeNull()
    expect(link.textContent).toBe("市場")
    fireEvent.click(within(await screen.findByRole("tablist", { name: "市場內容" }, T)).getByRole("tab", { name: "報告" }))
    await waitFor(() => expect(spies.markMarketReportsSeen).toHaveBeenCalledTimes(1), { timeout: 4000 })
    await waitFor(() => expect(within(nav).getByRole("link", { name: "市場" }).querySelector("[data-reports-dot]")).toBeNull(), T)
  })

  it("查看別人的資產時：沒有圓點、報告照常看得到、不記看過", async () => {
    const spies = mount({ reports: "public" })
    useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "all", accounts: [] })
    renderApp("/market?tab=reports&kind=weekly")
    await report()
    await new Promise((r) => setTimeout(r, 1500))
    expect(spies.markMarketReportsSeen).not.toHaveBeenCalled()
    for (const nav of screen.getAllByRole("navigation", { name: "主要" })) expect(within(nav).getByRole("link", { name: "市場" }).querySelector("[data-reports-dot]")).toBeNull()
  })
})

describe("mock 的報告", () => {
  it("一般使用者的形式拿掉 refs、被拿掉的段與 validation", () => {
    const admin = buildMockReport("close", "2026-11-11", { dropped: [{ key: "sectors", reasons: ["number_subject_mismatch"] }] })
    expect(admin.sections.some((s) => s.dropped)).toBe(true)
    const pub = publicView(admin)
    expect(pub.sections.some((s) => s.key === "sectors")).toBe(false)
    expect(JSON.stringify(pub)).not.toMatch(/"refs"|"validation"/)
    // 每一句都有出處；號碼從 1 開始、和註腳對得起來
    const cites = new Set(pub.highlights.flatMap((p) => p.sentences.flatMap((s) => s.cites)))
    expect([...cites].every((n) => pub.footnotes.some((f) => f.n === n))).toBe(true)
  })
})
