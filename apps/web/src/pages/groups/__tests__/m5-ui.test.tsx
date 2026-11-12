import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import { api } from "@/api"
import type { Group } from "@/api/types"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_SHARE } from "../labels"
import { SharedPortfolioView } from "../MemberPage"
import { ShareToggles } from "../ShareToggles"
import { FeedTab } from "../tabs/FeedTab"
import { RankingTab } from "../tabs/RankingTab"

/**
 * 分享的顯示規則：只顯示伺服器給的、從不寫「未分享」；沒開放的鍵不存在時那一塊就不出現。
 * 用瀏覽器裡的 mock adapter（和合約一樣的投影規則）。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  // AppShell 用 matchMedia 判斷桌面／手機；jsdom 沒有
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  usePrefs.setState({ privacyMode: false })
})

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

/** 只有一個根路由的 router（Link 需要 router context） */
function renderInRouter(ui: React.ReactNode) {
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(
    <QueryClientProvider client={client()}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}

const T = { timeout: 4000 }

describe("分享開關", () => {
  it("附上成交價要先打開交易動態；交易動態旁明講最近 90 天", () => {
    renderInRouter(<ShareToggles value={DEFAULT_SHARE} onChange={() => {}} />)
    return waitFor(() => {
      expect(screen.getByRole("switch", { name: "報酬率" })).toHaveAttribute("aria-checked", "true")
      expect(screen.getByRole("switch", { name: "交易動態" })).toHaveAttribute("aria-checked", "false")
      expect(screen.getByRole("switch", { name: "附上成交價" })).toHaveAttribute("data-disabled")
      expect(screen.getByText(/最近 90 天的買賣也會出現在動態裡/)).toBeInTheDocument()
      expect(screen.getByText(/要先打開交易動態才會附上/)).toBeInTheDocument()
    })
  })
  it("持股與金額都打開時提示可以推算股數；只開一個不提示；推播列出頻道", async () => {
    const { rerender } = renderInRouter(<ShareToggles value={{ ...DEFAULT_SHARE, holdings: true }} onChange={() => {}} />)
    await screen.findByText("持股與權重")
    expect(screen.queryByText(/可以推算你大約持有幾股/)).toBeNull()
    cleanup()
    renderInRouter(
      <ShareToggles
        value={{ ...DEFAULT_SHARE, holdings: true, amounts: true, trades: true }}
        onChange={() => {}}
        pushTargets={[
          { kind: "discord", label: "Discord 頻道" },
          { kind: "telegram", label: "家族投資群" },
        ]}
      />,
    )
    expect(await screen.findByText(/可以推算你大約持有幾股/)).toBeInTheDocument()
    expect(screen.getByRole("switch", { name: "附上成交價" })).not.toHaveAttribute("data-disabled")
    expect(screen.getByText("Discord 頻道、Telegram「家族投資群」")).toBeInTheDocument()
    void rerender
  })
})

describe("群組畫面不透露誰沒分享", () => {
  let family: Group
  beforeAll(async () => {
    family = await api.getGroup("grp_family")
  })

  it("排行：只有開了報酬率的人；沒有「未分享」；算不出來是「—」", async () => {
    renderInRouter(<RankingTab group={family} />)
    const table = await screen.findByRole("table", { name: "今日排行" }, T)
    await within(table).findByText("爸爸", undefined, T)
    expect(within(table).queryByText("阿弟")).toBeNull()
    expect(document.body.textContent).not.toContain("未分享")
    expect(within(table).getAllByText("沒有資料").length).toBeGreaterThan(0)
    // 只對自己說明為什麼是「—」
    expect(screen.getByText(/你的持股裡有沒有收盤價的股票/)).toBeInTheDocument()
  })

  it("動態：沒開交易動態的人只有「加入了群組」；成交價只在對方開了才出現，隱私模式遮住", async () => {
    renderInRouter(<FeedTab group={family} />)
    const list = await screen.findByRole("list", { name: "動態" }, T)
    const rows = within(list).getAllByRole("listitem")
    const bro = rows.filter((r) => r.textContent?.includes("阿弟"))
    expect(bro.map((r) => r.textContent)).toEqual([expect.stringContaining("加入了群組")])
    const dadToday = rows.find((r) => /爸爸\s*買進\s*台積電/.test(r.textContent ?? ""))!
    expect(dadToday.textContent).toContain("成交價")
    const sis = rows.find((r) => /姊姊\s*買進\s*國泰永續高股息/.test(r.textContent ?? ""))!
    expect(sis.textContent).not.toContain("成交價")
    expect(document.body.textContent).not.toContain("未分享")
    act(() => usePrefs.setState({ privacyMode: true }))
    await waitFor(() => expect(within(dadToday).getByLabelText("已隱藏")).toBeInTheDocument())
  })

  it("成員分享：沒開放的區塊不出現；什麼都沒有是「還沒有資料」", async () => {
    const bro = await api.getSharedPortfolio("grp_family", "usr_bro")
    renderInRouter(<SharedPortfolioView p={bro} groupId="grp_family" isMe={false} />)
    expect(await screen.findByText("還沒有資料。", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "報酬率" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "金額" })).toBeNull()
    expect(document.body.textContent).not.toContain("未分享")
    cleanup()
    const mom = await api.getSharedPortfolio("grp_family", "usr_mom")
    renderInRouter(<SharedPortfolioView p={mom} groupId="grp_family" isMe={false} />)
    expect(await screen.findByRole("heading", { name: "報酬率" }, T)).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: /持股/ })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "金額" })).toBeNull()
  })

  it("金額在隱私模式下遮住，百分比照常", async () => {
    const dad = await api.getSharedPortfolio("grp_family", "usr_dad")
    usePrefs.setState({ privacyMode: true })
    renderInRouter(<SharedPortfolioView p={dad} groupId="grp_family" isMe={false} />)
    const amounts = await screen.findByRole("region", { name: "金額" }, T).catch(() => null)
    const section = amounts ?? (await screen.findByRole("heading", { name: "金額" }, T)).closest("section")!
    expect(within(section as HTMLElement).getAllByLabelText("已隱藏")).toHaveLength(3)
    expect(screen.getByRole("heading", { name: "報酬率" }).closest("section")!.textContent).toMatch(/%/)
  })
})

describe("邀請：加入前先選分享", () => {
  const renderApp = (path: string) => {
    const qc = client()
    const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
    return router
  }

  it("沒登入：看得到群組名稱與邀請人，按鈕帶 next 到登入頁", async () => {
    await api.logout()
    try {
      renderApp("/invite/club-2026")
      expect(await screen.findByRole("heading", { name: "投資讀書會" }, T)).toBeInTheDocument()
      expect(screen.getByText("林老師 邀請你加入")).toBeInTheDocument()
      const link = screen.getByRole("link", { name: /登入後加入/ })
      expect(link.getAttribute("href")).toBe("/login?next=%2Finvite%2Fclub-2026")
    } finally {
      await api.devLogin({ email: "demo@forliosa.local", display_name: "示範使用者" })
    }
  })

  it("已登入：預設只開報酬率，打開交易動態後加入，伺服器收到的就是這組設定", async () => {
    const user = userEvent.setup()
    const router = renderApp("/invite/club-2026")
    const trades = await screen.findByRole("switch", { name: "交易動態" }, T)
    expect(screen.getByRole("switch", { name: "報酬率" })).toHaveAttribute("aria-checked", "true")
    for (const name of ["持股與權重", "金額與損益", "推播"]) expect(screen.getByRole("switch", { name })).toHaveAttribute("aria-checked", "false")
    await user.click(trades)
    await user.click(screen.getByRole("button", { name: "加入群組" }))
    await waitFor(() => expect(router.state.location.pathname).toBe("/groups/grp_club"), T)
    expect(await api.getShare("grp_club")).toEqual({ ...DEFAULT_SHARE, trades: true })
    // 已經是成員：預覽變成「已經是成員」
    expect((await api.getInvite("club-2026")).status).toBe("member")
  })

  it("失效的邀請（410）與不存在的（404）有不同的說明", async () => {
    renderApp("/invite/club-expired")
    expect(await screen.findByRole("heading", { name: "這個邀請已經失效" }, T)).toBeInTheDocument()
    cleanup()
    renderApp("/invite/nope")
    expect(await screen.findByRole("heading", { name: "找不到這個邀請連結" }, T)).toBeInTheDocument()
  })
})
