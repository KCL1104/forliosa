import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { Conversation } from "@/ai/Conversation"
import { PanelHome } from "@/ai/Home"
import type { useAiRunner } from "@/ai/runner"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import type { ForliosaApi } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { Disclaimer } from "@/components/disclaimer"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { useSourceNote } from "@/hooks/use-source-note"
import { DISCLAIMER, DISCLAIMER_PATH } from "@/lib/disclaimer"
import { isPublicReadPath } from "@/lib/next-path"
import { AnalystViewsCard } from "@/pages/stock/AnalystViews"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 全站免責（產品負責人 2026-11-17：清楚標示 Forliosa 只替使用者整理資訊，不是投資顧問，不提供投資建議）：
 * 字只有一份（`lib/disclaimer.ts`），畫面只有一個元件（`<Disclaimer>`，13px 淡墨），每一頁一個頁尾，每個區塊最多一句。
 */
const T = { timeout: 8000 }

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
  vi.restoreAllMocks()
  act(() => {
    resetAi()
    useViewAs.setState({ target: null })
  })
})

/** Link 需要 router：只有一個根路由 */
function inRouter(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}

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

const notes = (root: ParentNode = document) => [...root.querySelectorAll<HTMLElement>("[data-disclaimer]")]

describe("字只有一份", () => {
  it("全站的一句：只替你整理資訊、不是投資顧問、不提供投資建議、自己判斷", () => {
    expect(DISCLAIMER.short).toBe("Forliosa 只替你整理公開資訊與你自己的紀錄，不是投資顧問，不提供投資建議；投資決定請自己判斷。")
    expect(DISCLAIMER.ai).toBe("AI 只替你整理資訊，可能有錯；Forliosa 不是投資顧問，不提供投資建議。")
    for (const s of Object.values(DISCLAIMER)) {
      expect(s).toMatch(/投資建議/)
      expect(s).not.toMatch(/\n/)
    }
    expect(DISCLAIMER_PATH).toBe("/disclaimer")
    expect(isPublicReadPath("/disclaimer")).toBe(true)
  })
})

describe("<Disclaimer>：13px 淡墨的一句", () => {
  it("用常數；後端有給字時用後端的，空字串時回到常數；`link` 接一個「免責聲明」", async () => {
    inRouter(
      <>
        <Disclaimer />
        <Disclaimer kind="ai" text="後端的字。" />
        <Disclaimer kind="analyst" text="" />
        <Disclaimer kind="news" link />
      </>,
    )
    const [short, ai, analyst, news] = await waitFor(() => {
      const all = notes()
      expect(all).toHaveLength(4)
      return all as [HTMLElement, HTMLElement, HTMLElement, HTMLElement]
    })
    expect(short).toHaveTextContent(DISCLAIMER.short)
    expect(short).toHaveClass("text-sm", "text-ink-2")
    expect(short.tagName).toBe("P")
    expect(ai).toHaveTextContent("後端的字。")
    expect(analyst).toHaveTextContent(DISCLAIMER.analyst)
    expect(within(news).getByRole("link", { name: "免責聲明" })).toHaveAttribute("href", "/disclaimer")
  })
})

function Registers() {
  useSourceNote(["臺灣證券交易所〈上市個股日成交資訊〉（2026）"])
  return null
}

describe("頁尾：免責的一句＋「免責聲明」＋「資料來源與授權」，一頁一次", () => {
  it("有登記來源：一句、兩個入口；來源仍是收合的揭示按鈕", async () => {
    inRouter(
      <SourcesProvider>
        <Registers />
        <SourcesFooter />
      </SourcesProvider>,
    )
    const footer = await screen.findByRole("contentinfo", undefined, T)
    expect(notes(footer).map((n) => n.textContent)).toEqual([DISCLAIMER.short])
    expect(within(footer).getByRole("link", { name: "免責聲明" })).toHaveAttribute("href", "/disclaimer")
    expect(within(footer).getByRole("button", { name: "資料來源與授權" })).toHaveAttribute("aria-expanded", "false")
  })
  it("`omit`：在免責聲明頁不放那一句與連到自己的連結；在資料來源頁不放「資料來源與授權」", async () => {
    inRouter(
      <>
        <SourcesFooter omit="disclaimer" className="a" />
        <SourcesFooter omit="sources" className="b" />
      </>,
    )
    await waitFor(() => expect(document.querySelectorAll("footer")).toHaveLength(2))
    const [a, b] = [...document.querySelectorAll("footer")] as HTMLElement[]
    expect(notes(a!)).toHaveLength(0)
    expect(within(a!).queryByRole("link", { name: "免責聲明" })).toBeNull()
    expect(within(a!).getByRole("link", { name: "資料來源與授權" })).toBeInTheDocument()
    expect(notes(b!)).toHaveLength(1)
    expect(within(b!).queryByText("資料來源與授權")).toBeNull()
  })
})

describe("AI：回答下方與面板首頁", () => {
  const runner = { submit: async () => undefined } as unknown as ReturnType<typeof useAiRunner>
  const at = "2026-11-12T13:41:00+08:00"
  const withQuery = (ui: React.ReactNode) =>
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

  it("模型的回答：後端沒給字時是 `ai` 那一句，只出現一次（在最新一則回答下方）", () => {
    withQuery(
      <Conversation
        thread={{ id: "t1", title: "q", updatedAt: at, messages: [
          { id: "a1", role: "ai", model: true, text: "台積電今天上漲。", at },
          { id: "u2", role: "user", text: "那鴻海呢", at },
          { id: "a2", role: "ai", model: true, text: "鴻海今天平盤。", at },
        ] }}
        runner={runner}
      />,
    )
    const all = notes()
    expect(all).toHaveLength(1)
    expect(all[0]).toHaveTextContent(DISCLAIMER.ai)
    expect(all[0]).toHaveAttribute("data-disclaimer", "ai")
  })

  it("還沒問之前（面板首頁）：最下面一句 `ai`", () => {
    withQuery(<PanelHome ctx={{ route: "other" }} runner={runner} suggestions={[]} size="panel" />)
    expect(notes().map((n) => [n.dataset.disclaimer, n.textContent])).toEqual([["ai", DISCLAIMER.ai]])
  })
})

describe("個股頁：為什麼漲跌、法人觀點、新聞報導", { timeout: 30_000 }, () => {
  it("法人觀點：清單上面一句（後端的字），不另外再寫", async () => {
    vi.spyOn(api, "getAnalystViews").mockResolvedValue({ status: "ready", symbol: "2881.TW", as_of: "2026-11-12T09:12:00+08:00", items: [], disclaimer: DISCLAIMER.analyst, notes: [] })
    const inst = await api.getInstrument("2881.TW")
    inRouter(<AnalystViewsCard inst={inst} />)
    fireEvent.click(await screen.findByRole("button", { name: /法人觀點/ }, T))
    const note = await waitFor(() => {
      const n = document.querySelector<HTMLElement>("[data-disclaimer='analyst']")
      expect(n).not.toBeNull()
      return n!
    }, T)
    expect(note).toHaveTextContent(DISCLAIMER.analyst)
    expect(note).toHaveClass("text-sm", "text-ink-2")
  })

  it("為什麼漲跌（規則判斷的句子）下面一句 `short`；有報導的新聞清單下面一句 `news`；頁尾一個", async () => {
    mount()
    vi.spyOn(api, "getWhy").mockResolvedValue({ show: true, headline: "台積電今天漲 4.8%，成交量是平常的 2 倍", reasons: [], as_of: "2026-11-12T14:30:00+08:00", trade_date: "2026-11-12", sources: [] })
    renderApp("/stock/2330.TW")
    const why = await screen.findByRole("button", { name: /台積電今天漲 4.8%/ }, T)
    const next = why.nextElementSibling as HTMLElement
    expect(next).toHaveAttribute("data-disclaimer", "short")
    expect(next).toHaveTextContent(DISCLAIMER.short)
    await waitFor(() => expect(document.querySelector("[data-disclaimer='news']")).not.toBeNull(), T)
    expect(document.querySelectorAll("[data-site-footer]")).toHaveLength(1)
  })

  it("模型寫的「為什麼」（`ai: true`）下面是 `ai` 那一句", async () => {
    mount()
    vi.spyOn(api, "getWhy").mockResolvedValue({ show: true, headline: "台積電法說會上調全年營收展望。", reasons: [], as_of: "2026-11-12T14:30:00+08:00", trade_date: "2026-11-12", sources: [], ai: true } as never)
    renderApp("/stock/2330.TW")
    const why = await screen.findByRole("button", { name: /法說會上調全年營收展望/ }, T)
    expect(why.nextElementSibling).toHaveAttribute("data-disclaimer", "ai")
  })
})

describe("每一頁的頁尾；/disclaimer 不用登入", { timeout: 30_000 }, () => {
  it.each(["/groups", "/discussions", "/history", "/market", "/settings", "/data-sources", "/"])("%s：頁尾一個，裡面是免責的一句與「免責聲明」", async (path) => {
    mount()
    renderApp(path)
    const footer = await waitFor(() => {
      const all = document.querySelectorAll<HTMLElement>("[data-site-footer]")
      expect(all).toHaveLength(1)
      return all[0]!
    }, T)
    expect(within(footer).getByText(DISCLAIMER.short)).toBeInTheDocument()
    expect(within(footer).getByRole("link", { name: "免責聲明" })).toHaveAttribute("href", "/disclaimer")
  })

  it("/disclaimer：沒登入也讀得到；開頭是那一句，寫了我們做什麼、不做什麼；頁尾連到條款", async () => {
    mount({ signedIn: false })
    renderApp("/disclaimer")
    const article = await screen.findByRole("article", undefined, T)
    expect(within(article).getByRole("heading", { level: 1, name: "免責聲明" })).toBeInTheDocument()
    expect(within(article).getByText(DISCLAIMER.short)).toBeInTheDocument()
    for (const h of ["我們做什麼", "我們不做什麼", "資料可能延遲或有錯", "投資決定由你負責"]) expect(within(article).getByRole("heading", { level: 2, name: h })).toBeInTheDocument()
    expect(article.textContent).toMatch(/不是證券投資顧問事業/)
    expect(article.textContent).toMatch(/不代客操作/)
    // 給審閱的人看的那一段（【待律師確認】）不在頁面上
    expect(article.textContent).not.toMatch(/待律師確認|草稿日期/)
    expect(within(article).getByRole("link", { name: "〈服務條款〉第 2 節" })).toHaveAttribute("href", "/terms#sec-2")
    const footer = article.querySelector<HTMLElement>("[data-site-footer]")!
    expect(notes(footer)).toHaveLength(0)
    expect([...footer.querySelectorAll("a")].map((a) => a.textContent)).toEqual(["服務條款", "隱私權政策", "資料來源與授權"])
    await waitFor(() => expect(document.title).toBe("免責聲明｜Forliosa"))
  })

  it("群組週報：每一份下面一句 `ai`（後端的字）", async () => {
    mount()
    renderApp("/groups/grp_family?tab=digests&report=weekly")
    await waitFor(() => expect(document.querySelectorAll("[data-disclaimer='ai']").length).toBeGreaterThan(0), T)
    for (const n of document.querySelectorAll("article [data-disclaimer]")) expect(n).toHaveTextContent(DISCLAIMER.ai)
  })
})
