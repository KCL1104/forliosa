import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { BriefingBlock, BriefingHistory } from "@/ai/Briefing"
import { useBriefingUnread } from "@/ai/use-briefing-unread"
import { api } from "@/api"
import type { Briefing } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"

/**
 * 每日收盤簡報（預設關）：面板首頁最上面的那一塊、還沒看過的小圓點、設定裡的開關、紀錄頁的「之前的簡報」。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  // jsdom 沒有 matchMedia：一律當手機（< 1024px），底部有「問 AI」那一格
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  useViewAs.getState().set(null)
  act(() => usePrefs.setState({ privacyMode: false }))
})

const T = { timeout: 4000 }
const tw = { market: "TWSE" as const, type: "stock" as const }

const briefing = (over: Partial<Briefing> = {}): Briefing => ({
  id: "brf_1",
  date: "2026-11-12",
  created_at: "2026-11-12T22:20:00+08:00",
  read: false,
  facts: {
    market_value: 3_707_922,
    day_change: 78_015,
    day_change_pct: 0.0215,
    holdings: 9,
    unpriced: 3,
    gainers: [{ symbol: "2330.TW", code: "2330", name: "台積電", ...tw, close: 1085, change_pct: 0.0483, day_change: 75_000 }],
    losers: [{ symbol: "6488.TWO", code: "6488", name: "環球晶", ...tw, close: 398, change_pct: -0.0185, day_change: -7_500 }],
    watchlist: [{ symbol: "2603.TW", code: "2603", name: "長榮", ...tw, close: 190, change_pct: 0.0412 }],
    upcoming: [
      { date: "2026-11-12", type: "recurring", symbol: "00878.TW", title: "國泰永續高股息 定期定額 NT$4,000", amount_estimate: 4000 },
      { date: "2026-11-18", type: "ex_dividend", symbol: "00878.TW", title: "00878 除息", amount_estimate: null },
    ],
    is_demo: false,
  },
  points: [
    {
      text: "台積電公布上月營收，年增兩成。",
      sources: [
        { url: "https://news.example/a", title: "台積電營收年增兩成", outlet: "示範通訊社" },
        { url: "https://news.example/b", title: "同一家的另一篇", outlet: "示範通訊社" },
      ],
    },
  ],
  ...over,
})

const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe("面板首頁的收盤簡報", () => {
  it("在帳本旁邊（besideLedger）：總資產、當日、這一週左邊都看得到，不再列一次；漲跌最多與 AI 補充照常", async () => {
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing())
    vi.spyOn(api, "markBriefingRead").mockResolvedValue(undefined)
    wrap(<BriefingBlock size="panel" besideLedger />)
    const block = await screen.findByRole("region", { name: "收盤簡報" }, T)
    await within(block).findByText("台積電公布上月營收，年增兩成。", {}, T)
    expect(within(block).queryByText("NT$3,707,922")).toBeNull()
    expect(within(block).queryByText("當日")).toBeNull()
    expect(within(block).queryByText("這一週")).toBeNull()
    expect(within(block).queryByText(/沒有收盤價/)).toBeNull()
    expect(within(block).getByText("漲最多")).toBeInTheDocument()
  })

  it("還沒看過：展開著，有小圓點；事實是印刷的字、AI 補的是鉛筆並列出報導", async () => {
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing())
    vi.spyOn(api, "markBriefingRead").mockResolvedValue(undefined)
    wrap(<BriefingBlock size="panel" />)
    const block = await screen.findByRole("region", { name: "收盤簡報" }, T)
    const head = within(block).getByRole("button", { name: /收盤簡報/ })
    expect(head).toHaveAttribute("aria-expanded", "true")
    expect(head.querySelector("[data-briefing-dot]")).not.toBeNull()
    expect(head.textContent).toContain("11/12")
    // 事實
    expect(within(block).getByText("NT$3,707,922")).toHaveClass("num")
    expect(within(block).getByText("+NT$78,015")).toHaveClass("text-rise")
    expect(within(block).getByText("台積電").textContent).toContain("4.83%")
    expect(within(block).getByText("環球晶").querySelector(".text-fall")).not.toBeNull()
    expect(within(block).getByText("長榮").textContent).toContain("4.12%")
    expect(within(block).getByText("00878 定期定額・NT$4,000")).toBeInTheDocument()
    expect(within(block).getByText("00878 除息")).toBeInTheDocument()
    expect(within(block).getByText("3 檔沒有收盤價，不算在當日。")).toBeInTheDocument()
    // 事實不是楷體；AI 的那一點才是
    expect(within(block).getByText("NT$3,707,922").closest(".ai-voice")).toBeNull()
    expect(within(block).getByText("台積電公布上月營收，年增兩成。").closest("p")).toHaveClass("ai-voice")
    // 同一家媒體只列一次，連到原文、另開視窗
    const links = within(block).getAllByRole("link")
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute("href", "https://news.example/a")
    expect(links[0]).toHaveAttribute("target", "_blank")
    expect(links[0]!.textContent).toContain("示範通訊社")
  })

  it("展開著停一下就算看過：記到伺服器、圓點消失", async () => {
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing())
    const mark = vi.spyOn(api, "markBriefingRead").mockResolvedValue(undefined)
    wrap(<BriefingBlock size="panel" />)
    const block = await screen.findByRole("region", { name: "收盤簡報" }, T)
    expect(mark).not.toHaveBeenCalled()
    await waitFor(() => expect(mark).toHaveBeenCalledWith("brf_1"), T)
    await waitFor(() => expect(block.querySelector("[data-briefing-dot]")).toBeNull())
    // 看過之後不會自己收起來（正在讀）
    expect(within(block).getByRole("button", { name: /收盤簡報/ })).toHaveAttribute("aria-expanded", "true")
  })

  it("看過的：收成一列、沒有圓點、不再記一次；按一下展開", async () => {
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing({ read: true }))
    const mark = vi.spyOn(api, "markBriefingRead").mockResolvedValue(undefined)
    wrap(<BriefingBlock size="screen" />)
    const block = await screen.findByRole("region", { name: "收盤簡報" }, T)
    const head = within(block).getByRole("button", { name: /收盤簡報/ })
    expect(head).toHaveAttribute("aria-expanded", "false")
    expect(block.querySelector("[data-briefing-dot]")).toBeNull()
    expect(within(block).getByText("NT$3,707,922")).not.toBeVisible()
    fireEvent.click(head)
    expect(head).toHaveAttribute("aria-expanded", "true")
    expect(within(block).getByText("NT$3,707,922")).toBeVisible()
    expect(mark).not.toHaveBeenCalled()
  })

  it("隱私模式：金額遮起來（總資產、當日損益、定期定額的金額），漲跌幅照常", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing({ read: true }))
    wrap(<BriefingBlock size="panel" />)
    const block = await screen.findByRole("region", { name: "收盤簡報" }, T)
    fireEvent.click(within(block).getByRole("button", { name: /收盤簡報/ }))
    expect(block.textContent).not.toMatch(/NT\$/)
    expect(within(block).getAllByLabelText("已隱藏")).toHaveLength(2)
    expect(within(block).getByText("00878 定期定額・••••")).toBeInTheDocument()
    expect(block.textContent).toContain("2.15%")
    expect(block.textContent).toContain("4.83%")
  })

  it("只有觀察清單（沒有持股）：不列總資產與當日損益；沒有 AI 補充就只有事實", async () => {
    const b = briefing({ points: [] })
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue({ ...b, facts: { ...b.facts, holdings: 0, unpriced: 0, market_value: 0, day_change: 0, day_change_pct: null, gainers: [], losers: [], upcoming: [] } })
    vi.spyOn(api, "markBriefingRead").mockResolvedValue(undefined)
    wrap(<BriefingBlock size="panel" />)
    const block = await screen.findByRole("region", { name: "收盤簡報" }, T)
    expect(within(block).queryByText("總資產")).toBeNull()
    expect(within(block).queryByText("當日")).toBeNull()
    expect(within(block).getByText("觀察清單")).toBeInTheDocument()
    expect(within(block).queryByText(/AI 依這些報導整理/)).toBeNull()
    expect(block.querySelector(".ai-voice")).toBeNull()
  })

  it("沒有簡報（沒打開開關，或超過兩個交易日）：整塊不出現", async () => {
    const get = vi.spyOn(api, "getLatestBriefing").mockResolvedValue(null)
    wrap(<BriefingBlock size="panel" />)
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(screen.queryByRole("region", { name: "收盤簡報" })).toBeNull()
  })
})

describe("還沒看過的小圓點", () => {
  function Probe() {
    return <output>{useBriefingUnread() ? "unread" : "none"}</output>
  }

  it("最新的一則還沒看過才有", async () => {
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing())
    wrap(<Probe />)
    expect(await screen.findByText("unread", undefined, T)).toBeInTheDocument()
    cleanup()
    vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing({ read: true }))
    wrap(<Probe />)
    await waitFor(() => expect(api.getLatestBriefing).toHaveBeenCalled())
    expect(screen.getByText("none")).toBeInTheDocument()
  })

  it("查看別人的資產時不問、也不顯示（簡報是自己的）", async () => {
    useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "all", accounts: [] })
    const get = vi.spyOn(api, "getLatestBriefing").mockResolvedValue(briefing())
    wrap(
      <>
        <Probe />
        <BriefingBlock size="panel" />
      </>,
    )
    await new Promise((r) => setTimeout(r, 30))
    expect(get).not.toHaveBeenCalled()
    expect(screen.getByText("none")).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "收盤簡報" })).toBeNull()
  })
})

describe("對話紀錄頁的「收盤簡報」", () => {
  it("一列一則（日期、當日損益），按一下展開內容；再按收起來", async () => {
    const older = briefing({ id: "brf_0", date: "2026-11-11", read: true, points: [] })
    vi.spyOn(api, "listBriefings").mockResolvedValue([briefing(), { ...older, facts: { ...older.facts, day_change: -31_206, day_change_pct: -0.0086 } }])
    wrap(<BriefingHistory />)
    expect(await screen.findByRole("heading", { name: "收盤簡報" }, T)).toBeInTheDocument()
    const rows = screen.getAllByRole("button", { expanded: false })
    expect(rows).toHaveLength(2)
    expect(rows[0]!.textContent).toContain("11/12")
    expect(rows[0]!.textContent).toContain("+NT$78,015")
    expect(rows[1]!.textContent).toContain("11/11")
    expect(rows[1]!.textContent).toContain("−NT$31,206")
    expect(screen.queryByText("總資產")).toBeNull()
    fireEvent.click(rows[0]!)
    expect(rows[0]).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText("總資產")).toBeVisible()
    expect(screen.getByText("台積電公布上月營收，年增兩成。").closest("p")).toHaveClass("ai-voice")
    fireEvent.click(rows[0]!)
    expect(screen.queryByText("總資產")).toBeNull()
  })

  it("一則都沒有：整段不出現（不放空狀態）", async () => {
    const list = vi.spyOn(api, "listBriefings").mockResolvedValue([])
    const { container } = wrap(<BriefingHistory />)
    await waitFor(() => expect(list).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})

describe("設定：每日收盤簡報的開關（預設關）", () => {
  function renderApp(path: string) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
  }

  it("預設是關的、沒有簡報也沒有圓點；打開後存到偏好，「問 AI」出現圓點；關掉就沒有", async () => {
    const patch = vi.spyOn(api, "updatePreferences")
    renderApp("/settings")
    const sw = await screen.findByRole("switch", { name: "每日收盤簡報" }, T)
    expect(sw).toHaveAttribute("aria-checked", "false")
    expect(screen.getByText("收盤後依你的持股與觀察清單寫一則，在「問 AI」最上面。")).toBeInTheDocument()
    expect(await api.getLatestBriefing()).toBeNull()
    expect(await api.listBriefings()).toEqual([])
    expect(screen.getByRole("button", { name: "問 AI" }).querySelector("[data-briefing-dot]")).toBeNull()

    fireEvent.click(sw)
    await waitFor(() => expect(patch).toHaveBeenCalledWith({ daily_briefing: true }))
    await waitFor(() => expect(sw).toHaveAttribute("aria-checked", "true"), T)
    const ask = await screen.findByRole("button", { name: "問 AI（有新的收盤簡報）" }, T)
    expect(ask.querySelector("[data-briefing-dot]")).not.toBeNull()
    // 圓點不是數字徽章
    expect(ask.querySelector("[data-briefing-dot]")!.textContent).toBe("")
    expect((await api.listBriefings()).length).toBeGreaterThan(0)

    await waitFor(() => expect(sw).not.toBeDisabled())
    fireEvent.click(sw)
    await waitFor(() => expect(patch).toHaveBeenLastCalledWith({ daily_briefing: false }))
    expect(await screen.findByRole("button", { name: "問 AI" }, T)).toBeInTheDocument()
    expect(await api.getLatestBriefing()).toBeNull()
  })
})
