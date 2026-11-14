import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Channels, Group } from "@/api/types"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { DEFAULT_SHARE } from "../labels"
import { SharedPortfolioView } from "../MemberPage"
import { ShareToggles } from "../ShareToggles"
import { ChannelsTab } from "../tabs/ChannelsTab"
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
  vi.restoreAllMocks()
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
  it("成員的推播旁說明群組換頻道時會自動關掉；擁有者、還沒有頻道、邀請預覽都不說", async () => {
    const targets = [{ kind: "discord" as const, label: "Discord 頻道" }]
    renderInRouter(<ShareToggles value={DEFAULT_SHARE} onChange={() => {}} pushTargets={targets} pushAutoOff />)
    const note = await screen.findByText("群組換頻道時會自動關掉。")
    // 念開關時一起念（aria-describedby）
    expect(screen.getByRole("switch", { name: "推播" }).getAttribute("aria-describedby")).toContain(note.id)
    cleanup()
    renderInRouter(<ShareToggles value={DEFAULT_SHARE} onChange={() => {}} pushTargets={targets} pushAutoOff={false} />)
    await screen.findByText("Discord 頻道")
    expect(screen.queryByText("群組換頻道時會自動關掉。")).toBeNull()
    cleanup()
    renderInRouter(<ShareToggles value={DEFAULT_SHARE} onChange={() => {}} pushTargets={[]} pushAutoOff />)
    await screen.findByText("這個群組還沒有設定頻道。")
    expect(screen.queryByText("群組換頻道時會自動關掉。")).toBeNull()
    cleanup()
    renderInRouter(<ShareToggles value={DEFAULT_SHARE} onChange={() => {}} pushAutoOff />)
    await screen.findByText(/群組有設定頻道才會送/)
    expect(screen.queryByText("群組換頻道時會自動關掉。")).toBeNull()
  })
})

describe("群組畫面不透露誰沒分享", () => {
  let family: Group
  beforeAll(async () => {
    family = await api.getGroup("grp_family")
  })

  it("排行：只有開了報酬率的人；沒有「未分享」；有美股的人也有名次（只在自己那一列標「不含美股」）", async () => {
    renderInRouter(<RankingTab group={family} />)
    const table = await screen.findByRole("table", { name: "今日排行" }, T)
    await within(table).findByText("爸爸", undefined, T)
    expect(within(table).queryByText("阿弟")).toBeNull()
    expect(document.body.textContent).not.toContain("未分享")
    // 我有美股：期間報酬只算有收盤價的持股，只在自己那一列標「不含美股」（別人的不說）
    expect(within(table).getAllByText("不含美股")).toHaveLength(1)
  })

  it("排行下面有當天的表情（和動態、週報同一個元件）；按了以伺服器的計數為準，只有計數", async () => {
    const user = userEvent.setup()
    renderInRouter(<RankingTab group={family} />)
    const table = await screen.findByRole("table", { name: "今日排行" }, T)
    const chip = await screen.findByRole("button", { name: "恭喜 3，你按過" }, T)
    expect(chip).toHaveAttribute("aria-pressed", "true")
    // 在排行表之後（表下面），不是在討論串裡
    expect(table.compareDocumentPosition(chip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole("button", { name: "加表情" })).toBeInTheDocument()
    await user.click(chip)
    expect(await screen.findByRole("button", { name: "恭喜 2" }, T)).toHaveAttribute("aria-pressed", "false")
    // 還原示範資料（其他測試共用同一個 mock）
    await user.click(screen.getByRole("button", { name: "恭喜 2" }))
    await screen.findByRole("button", { name: "恭喜 3，你按過" }, T)
    expect(document.body.textContent).not.toContain("未分享")
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

  it("成員分享：沒開放的區塊不出現；只有動態時不說「還沒有資料」；真的什麼都沒有才說", async () => {
    const bro = await api.getSharedPortfolio("grp_family", "usr_bro")
    renderInRouter(<SharedPortfolioView p={bro} groupId="grp_family" isMe={false} />)
    // 阿弟什麼都沒開：只有每個人都看得到的「加入了群組」
    const feed = await screen.findByRole("heading", { name: "動態" }, T)
    expect(feed.closest("section")!.textContent).toContain("加入了群組")
    expect(screen.queryByText("還沒有資料")).toBeNull()
    expect(screen.queryByRole("heading", { name: "報酬率" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "金額" })).toBeNull()
    expect(document.body.textContent).not.toContain("未分享")
    cleanup()
    // 沒有任何區塊、也沒有動態（例如建立群組的人什麼都沒開）
    renderInRouter(<SharedPortfolioView p={{ ...bro, user_id: "usr_nobody" }} groupId="grp_family" isMe={false} />)
    expect(await screen.findByText("還沒有資料", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "動態" })).toBeNull()
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

  it("已經是成員：直接連到那個群組（預覽帶 group_id），不是群組清單", async () => {
    renderApp("/invite/family-open")
    expect(await screen.findByText("你已經是這個群組的成員。", undefined, T)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "到群組" }).getAttribute("href")).toBe("/groups/grp_family")
    expect((await api.getInvite("family-open")).group_id).toBe("grp_family")
    // 還不是成員的人拿不到群組 id
    await api.logout()
    try {
      expect(await api.getInvite("family-open")).not.toHaveProperty("group_id")
    } finally {
      await api.devLogin({ email: "demo@forliosa.local", display_name: "示範使用者" })
    }
  })

  it("失效的邀請（410）與不存在的（404）有不同的說明", async () => {
    renderApp("/invite/club-expired")
    expect(await screen.findByRole("heading", { name: "這個邀請已經失效" }, T)).toBeInTheDocument()
    cleanup()
    renderApp("/invite/nope")
    expect(await screen.findByRole("heading", { name: "找不到這個邀請連結" }, T)).toBeInTheDocument()
  })
})

describe("頻道：Telegram 停用後重新連結", () => {
  const disabled: Channels = {
    discord: { configured: false, status: null, disabled_reason: null, webhook_hint: null, notify_trades: true, notify_digest: true },
    telegram: { configured: true, status: "disabled", disabled_reason: "Bot 已被移出 Telegram 群組", chat_title: "家族投資群", notify_trades: true, notify_digest: true },
    telegram_available: true,
  }
  const active: Channels = { ...disabled, telegram: { ...disabled.telegram, status: "active", disabled_reason: null, chat_title: "家族投資群" } }

  it("產生連結碼後看得到碼，不會先說「連結完成」；頻道變成使用中才完成", async () => {
    const family = await api.getGroup("grp_family")
    const channels = vi.spyOn(api, "getChannels").mockResolvedValue(disabled)
    vi.spyOn(api, "linkTelegram").mockResolvedValue({ code: "654321", bot_username: "forliosa_bot", expires_at: "2026-11-12T21:10:00+08:00" })
    const user = userEvent.setup()
    renderInRouter(<ChannelsTab group={{ ...family, my_role: "owner" }} />)
    await user.click(await screen.findByRole("button", { name: "產生連結碼" }, T))
    expect(await screen.findByText("/link 654321", undefined, T)).toBeInTheDocument()
    expect(screen.queryByText("連結完成")).toBeNull()
    // owner 在 Telegram 群組傳了 /link：下一次輪詢看到使用中
    channels.mockResolvedValue(active)
    expect(await screen.findByText("連結完成", undefined, { timeout: 6000 })).toBeInTheDocument()
    expect(screen.queryByText("/link 654321")).toBeNull()
    expect(screen.queryByRole("button", { name: "產生連結碼" })).toBeNull()
  }, 10_000)
})
