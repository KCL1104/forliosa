import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { toast } from "sonner"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { ApiError, type ForliosaApi, type MyGroupPass } from "@/api/types"
import { Toaster } from "@/components/ui/sonner"
import { groupFull, groupPlanLabel, untilDay, userPlanLabel } from "@/lib/plan"
import { createAppRouter } from "@/router"
import { limitText } from "../labels"
import { DISCLAIMER } from "@/lib/disclaimer"

/**
 * 群組加值包第一階段（產品負責人 2026-11-16）的畫面：「報告」分頁的日報｜週報、頻道的「日報」開關、群組設定的方案與加值、
 * 人數上限（邀請與加入）、設定頁的方案、管理後台的群組加值。用瀏覽器裡的 mock adapter（和後端同一套規則）。
 * 示範資料：家族投資（我是擁有者，加值到 12/31，有四天的日報）、大學同學（以前加值過，只剩舊的日報）、
 * 登山社（我是擁有者，免費、5 人已經滿了）；我另外有一個到 12/15、還沒用的加值。
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
afterEach(() => {
  act(() => {
    toast.dismiss()
  })
  cleanup()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
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
      <Toaster />
    </QueryClientProvider>,
  )
  return router
}

describe("方案的寫法", () => {
  it("自己的方案：會員到哪天、沒有到期日、免費；不是今年寫年份", () => {
    expect(userPlanLabel({ tier: "member", until: "2026-12-31" }, "2026-11-16")).toBe("會員，到 12/31")
    expect(userPlanLabel({ tier: "member", until: "2027-01-31" }, "2026-11-16")).toBe("會員，到 2027/1/31")
    expect(userPlanLabel({ tier: "member", until: null }, "2026-11-16")).toBe("會員")
    expect(userPlanLabel({ tier: "free", until: null }, "2026-11-16")).toBe("免費")
    expect(untilDay("2026-01-05", "2026-11-16")).toBe("1/5")
  })
  it("群組的方案：上限照伺服器給的寫（不寫死 5、50）；到了或超過上限就是滿了", () => {
    expect(groupPlanLabel({ tier: "boosted", until: "2026-12-31", member_cap: 50 }, "2026-11-16")).toBe("加值到 12/31・上限 50 人")
    expect(groupPlanLabel({ tier: "free", until: null, member_cap: 8 }, "2026-11-16")).toBe("免費・上限 8 人")
    expect(groupPlanLabel({ tier: "free", until: null, member_cap: 5 }, "2026-11-16")).toBe("免費・上限 5 人")
    expect(groupFull(5, { member_cap: 5 })).toBe(true)
    expect(groupFull(30, { member_cap: 5 })).toBe(true)
    expect(groupFull(4, { member_cap: 5 })).toBe(false)
    expect(groupFull(99, null)).toBe(false)
  })
  it("加入時群組滿了：照伺服器的句子寫、說要找誰；自己的群組太多：前面加「沒辦法加入」", () => {
    expect(limitText("這個群組已經滿了：免費群組最多 5 位成員（加值的群組最多 50 位）")).toBe(
      "這個群組已經滿了：免費群組最多 5 位成員（加值的群組最多 50 位）。請告訴邀請你的人。",
    )
    expect(limitText("每人最多加入 20 個群組")).toBe("沒辦法加入：每人最多加入 20 個群組")
  })
})

describe("報告分頁：日報｜週報（不加第九個分頁）", () => {
  it("加值群組：預設是日報；最新一則有「今日報酬」、買賣、「為什麼漲跌」與收盤重點，較早的寫「當日」、沒有站內連結", async () => {
    mount()
    renderApp("/groups/grp_family?tab=digests")
    const tabs = await screen.findAllByRole("tab", undefined, T)
    expect(tabs.map((t) => t.textContent)).toEqual(["排行", "動態", "討論", "持股", "報告", "分享", "成員", "頻道"])
    const kind = await screen.findByRole("radiogroup", { name: "報告" }, T)
    expect(within(kind).getByRole("radio", { name: "日報" })).toHaveAttribute("aria-checked", "true")
    const articles = await screen.findAllByRole("article", undefined, T)
    expect(articles).toHaveLength(4)
    const [latest, older] = articles as [HTMLElement, HTMLElement]
    expect(within(latest).getByRole("heading", { level: 2 })).toHaveTextContent("11/12（四） 日報")
    // AI 段落不放（2026-11-22 評論：頁面只放標籤和數字；推播照樣帶）。數字：今日報酬只有開了報酬率的人（阿弟沒開）
    expect(latest.querySelector(".ai-voice")).toBeNull()
    expect(latest.textContent).not.toMatch(/有分享報酬的 \d+ 個人/)
    expect(within(latest).getByText("今日報酬")).toBeInTheDocument()
    expect(within(latest).queryByText("阿弟")).toBeNull()
    expect(within(latest).getByText("今天的買賣")).toBeInTheDocument()
    expect(within(latest).getByRole("link", { name: "收盤重點 →" })).toHaveAttribute("href", "/market#market-summary")
    expect(within(latest).getByText("為什麼漲跌")).toBeInTheDocument()
    expect(within(latest).getByRole("link", { name: "台積電" })).toHaveAttribute("href", "/stock/2330.TW")
    // 免責：頁面上只有伺服器算的數字，全站那一句，13px 淡墨
    expect(within(latest).getByText(DISCLAIMER.short)).toHaveAttribute("data-disclaimer", "short")
    expect(within(older).getByText(DISCLAIMER.short)).toHaveClass("text-sm", "text-ink-2")
    expect(within(latest).queryByText(DISCLAIMER.ai)).toBeNull()
    expect(within(older).getByText("當日報酬")).toBeInTheDocument()
    expect(within(older).getByText("那天的買賣")).toBeInTheDocument()
    expect(within(older).queryByRole("link")).toBeNull()
  })

  it("一位小數、不到 0.05% 是持平（和 AI 段落一樣）；沒有數字的人只寫人數；沒人開交易動態時沒有買賣那一列", async () => {
    mount()
    const [real] = (await api.listDailyReports("grp_family")).items
    vi.spyOn(api, "listDailyReports").mockResolvedValue({
      items: [
        {
          ...real!,
          summary: "",
          facts: {
            ...real!.facts,
            returns: [
              { user_id: "u1", display_name: "阿哲", day_return_pct: -0.0002 },
              { user_id: "u2", display_name: "小芸", day_return_pct: 0.0123 },
            ],
            returns_no_data: 2,
            trades: [],
            trades_count: 0,
            trades_shared: false,
          },
        },
      ],
      next_cursor: null,
    })
    renderApp("/groups/grp_family?tab=digests&report=daily")
    const [article] = (await screen.findAllByRole("article", undefined, T)) as [HTMLElement]
    const flat = within(article).getByText("阿哲").closest("li")!
    expect(flat).toHaveTextContent("0.0%")
    expect(flat).not.toHaveTextContent("▼")
    expect(within(article).getByText("小芸").closest("li")).toHaveTextContent("▲1.2%")
    expect(within(article).getByText("另 2 人沒有這天的資料。")).toBeInTheDocument()
    expect(within(article).queryByText(/的買賣$/)).toBeNull()
  })

  it("切到週報：網址記住（?report=weekly），看到原本的週報", async () => {
    const user = userEvent.setup()
    mount()
    const router = renderApp("/groups/grp_family?tab=digests")
    const kind = await screen.findByRole("radiogroup", { name: "報告" }, T)
    await user.click(within(kind).getByRole("radio", { name: "週報" }))
    expect(await screen.findByRole("heading", { name: "11/2–11/6 週報" }, T)).toBeInTheDocument()
    expect(router.state.location.search).toMatchObject({ tab: "digests", report: "weekly" })
  })

  it("有人關掉報酬率：那個人的數字不見；後端說 AI 摘要收回的那一句也不放（頁面本來就沒有段落）", async () => {
    mount()
    await api.putShare("grp_family", { returns: false, holdings: true, amounts: false, trades: true, trade_prices: false, push: false })
    renderApp("/groups/grp_family?tab=digests")
    const [latest] = (await screen.findAllByRole("article", undefined, T)) as [HTMLElement]
    expect(latest.querySelector(".ai-voice")).toBeNull()
    expect(within(latest).queryByText(/摘要/)).toBeNull()
    expect(within(latest).queryByText("示範使用者")).toBeNull()
  })

  it("加值結束的群組：以前的日報照樣看得到，說明不會再有新的；從來沒有日報的群組沒有切換，直接是週報", async () => {
    mount()
    renderApp("/groups/grp_friends?tab=digests")
    expect(await screen.findByText("加值已結束，不再有新的日報", undefined, T)).toBeInTheDocument()
    expect(screen.getAllByRole("article")).toHaveLength(2)
    cleanup()
    mount()
    renderApp("/groups/grp_hiking?tab=digests")
    expect(await screen.findByText("還沒有週報", undefined, T)).toBeInTheDocument()
    // 2026-11-18：群組週報週日 18:00 出來（和頻道的週報同時）；只寫時間（標籤，不寫「整理好…表現」）
    expect(screen.getByText("每週日 18:00 更新")).toBeInTheDocument()
    expect(screen.queryByRole("radiogroup", { name: "報告" })).toBeNull()
  })

  it("舊版後端沒有日報（404）：照樣是週報，沒有切換", async () => {
    mount()
    vi.spyOn(api, "listDailyReports").mockRejectedValue(new ApiError(404, "not_found", "Not Found"))
    vi.spyOn(api, "getGroup").mockImplementation(async (id) => ({ ...(await createMockAdapter({ latency: [0, 0] }).getGroup(id)), plan: undefined }))
    renderApp("/groups/grp_family?tab=digests")
    expect(await screen.findByRole("heading", { name: "11/2–11/6 週報" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("radiogroup", { name: "報告" })).toBeNull()
  })
})

describe("頻道沒有「日報」開關（2026-11-18：併進盤前）", () => {
  it("加值群組：群組 AI 日報跟著盤前送（昨日你的群組），沒有另外的「日報」「週報」列", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/groups/grp_family?tab=channels")
    const sw = await screen.findByRole("switch", { name: "盤前（交易日 7:30）" }, T)
    expect(sw).toHaveAttribute("aria-checked", "false")
    expect(screen.getByText("盤前重點，加上昨日你的群組（加值群組）")).toBeInTheDocument()
    expect(screen.queryByRole("switch", { name: "日報" })).toBeNull()
    expect(screen.queryByRole("switch", { name: "週報" })).toBeNull()
    await user.click(sw)
    await waitFor(() => expect(api.patchDiscord).toHaveBeenCalledWith("grp_family", { notify_premarket: true }))
    await waitFor(() => expect(screen.getByRole("switch", { name: "盤前（交易日 7:30）" })).toHaveAttribute("aria-checked", "true"), T)
  })
})

describe("群組設定的方案與人數上限", () => {
  it("加值中的群組：「加值到 12/31・上限 50 人」；可以產生邀請連結", async () => {
    mount()
    renderApp("/groups/grp_family?tab=members")
    expect(await screen.findByText("加值到 12/31・上限 50 人", undefined, T)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "產生邀請連結" })).toBeEnabled()
    expect(screen.queryByText(/新的成員不能加入/)).toBeNull()
  })

  it("免費、5 人滿了：說新的成員不能加入、不能產生邀請連結；擁有者把還沒用的加值用在這裡 → 上限 50", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/groups/grp_hiking?tab=members")
    expect(await screen.findByText("免費・上限 5 人", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("已經有 5 位成員，上限是 5 人。新的成員不能加入。")).toHaveAttribute("role", "status")
    expect(screen.getByRole("button", { name: "產生邀請連結" })).toBeDisabled()
    // 我的兩個加值：還沒用的（直接用）與用在家族投資的（移過來要先確認）
    expect(await screen.findByText("加值到 12/15・還沒有用在群組", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("加值到 12/31・用在「家族投資」")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "用在這個群組" }))
    await waitFor(() => expect(api.attachGroupPass).toHaveBeenCalledWith("grp_hiking", "gps_spare"))
    expect(await screen.findByText("加值到 12/15・上限 50 人", undefined, T)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "產生邀請連結" })).toBeEnabled()
  })

  it("把加值從別的群組移過來：先確認（那個群組回到免費、不移出成員）", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/groups/grp_hiking?tab=members")
    await user.click(await screen.findByRole("button", { name: "移到這個群組" }, T))
    const dialog = await screen.findByRole("alertdialog", undefined, T)
    expect(dialog).toHaveTextContent("把加值移到「登山社」？")
    expect(dialog).toHaveTextContent("「家族投資」會回到免費，日報停止。成員不會被移出。")
    expect(api.attachGroupPass).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole("button", { name: "移過來" }))
    await waitFor(() => expect(api.attachGroupPass).toHaveBeenCalledWith("grp_hiking", "gps_family"))
    expect(await screen.findByText("加值到 12/31・上限 50 人", undefined, T)).toBeInTheDocument()
  })

  it("以前建立的免費群組上限維持 50；不是擁有者看不到加值的按鈕", async () => {
    mount()
    renderApp("/groups/grp_friends?tab=members")
    // 我在大學同學只是成員：沒有群組設定
    await screen.findByRole("button", { name: "離開群組" }, T)
    expect(screen.queryByText(/上限/)).toBeNull()
    expect((await api.getGroup("grp_friends")).plan).toEqual({ tier: "free", until: null, member_cap: 50, grandfathered: true, daily_report: false })
  })
})

describe("邀請：群組滿了", () => {
  it("加入時伺服器說滿了（409 limit_reached）：照寫上限、說要找誰", async () => {
    const user = userEvent.setup()
    mount()
    vi.spyOn(api, "acceptInvite").mockRejectedValue(
      new ApiError(409, "limit_reached", "這個群組已經滿了：免費群組最多 5 位成員（加值的群組最多 50 位）"),
    )
    renderApp("/invite/club-2026")
    await user.click(await screen.findByRole("button", { name: "加入群組" }, T))
    expect(await screen.findByText("這個群組已經滿了：免費群組最多 5 位成員（加值的群組最多 50 位）。請告訴邀請你的人。", undefined, T)).toBeInTheDocument()
  })
  it("預覽就說滿了（full）：不讓對方選完分享才被擋", async () => {
    mount()
    vi.spyOn(api, "getInvite").mockResolvedValue({
      group_name: "登山社", inviter_display_name: "阿凱", status: "valid", full: true,
      full_message: "這個群組已經滿了：免費群組最多 5 位成員（加值的群組最多 50 位）",
    })
    renderApp("/invite/hiking-open")
    expect(await screen.findByText("這個群組已經滿了：免費群組最多 5 位成員（加值的群組最多 50 位）。請告訴邀請你的人。", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "加入群組" })).toBeNull()
  })
  it("示範資料：登山社是這次改變以後建立的免費群組，5 人、上限 5", async () => {
    const adapter = createMockAdapter({ latency: [0, 0] })
    const g = await adapter.getGroup("grp_hiking")
    expect(g.members).toHaveLength(5)
    expect(g.plan).toEqual({ tier: "free", until: null, member_cap: 5, grandfathered: false, daily_report: false })
  })
})

describe("設定頁的方案（決定 14）", () => {
  it("站方管理員：「會員」；我的群組加值一個一列（用在哪個群組、還沒用的只寫狀態，不教去哪裡按）", async () => {
    mount()
    renderApp("/settings")
    const section = (await screen.findByRole("heading", { name: "方案" }, T)).closest("section")!
    await within(section).findByText("群組加值，到 12/31", undefined, T)
    expect(within(section).getByText("會員")).toBeInTheDocument()
    expect(within(section).getByRole("link", { name: "家族投資" })).toHaveAttribute("href", "/groups/grp_family")
    expect(within(section).getByText("群組加值，到 12/15")).toBeInTheDocument()
    expect(within(section).getByText("還沒有用在群組")).toBeInTheDocument()
    expect(section.textContent).not.toMatch(/分頁選/)
  })
  it("到期 30 天內的加值照樣列出，寫已到期；更早的不列", async () => {
    mount()
    vi.spyOn(api, "listMyGroupPasses").mockResolvedValue([
      { id: "gps_a", until: "2026-11-06", active: false, attached: true, group: { id: "grp_friends", name: "大學同學", my_role: "member" } },
      { id: "gps_b", until: "2026-09-01", active: false, attached: false, group: null },
    ] satisfies MyGroupPass[])
    renderApp("/settings")
    const section = (await screen.findByRole("heading", { name: "方案" }, T)).closest("section")!
    expect(await within(section).findByText("群組加值，11/6 已到期", undefined, T)).toBeInTheDocument()
    expect(within(section).getByRole("link", { name: "大學同學" })).toBeInTheDocument()
    expect(within(section).queryByText(/9\/1/)).toBeNull()
  })
  it("一般會員：「會員，到 12/31」；免費帳號：「免費」；沒有加值就只有這一列", async () => {
    mount({ discussion: { admin: false } })
    vi.spyOn(api, "listMyGroupPasses").mockResolvedValue([] satisfies MyGroupPass[])
    renderApp("/settings")
    const section = (await screen.findByRole("heading", { name: "方案" }, T)).closest("section")!
    expect(await within(section).findByText("會員，到 12/31", undefined, T)).toBeInTheDocument()
    cleanup()
    const adapter = mount({ discussion: { admin: false } })
    vi.spyOn(api, "listMyGroupPasses").mockResolvedValue([])
    vi.spyOn(api, "getMe").mockImplementation(async () => ({ ...(await adapter.getMe()), plan: { tier: "free", until: null, deep_search: true, daily_briefing: false, statement_import: true } }))
    renderApp("/settings")
    const free = (await screen.findByRole("heading", { name: "方案" }, T)).closest("section")!
    expect(await within(free).findByText("免費", undefined, T)).toBeInTheDocument()
    expect(within(free).queryByText(/群組加值/)).toBeNull()
  })
})

describe("管理後台：群組加值", () => {
  it("會員頁切到「群組加值」：清單只有付款人與群組編號（沒有群組名稱）；過期的只有「延長」", async () => {
    const user = userEvent.setup()
    mount()
    const router = renderApp("/admin/members")
    const kind = await screen.findByRole("radiogroup", { name: "種類" }, T)
    await user.click(within(kind).getByRole("radio", { name: "群組加值" }))
    expect(router.state.location.search).toMatchObject({ kind: "group" })
    const list = await screen.findByRole("list", { name: "群組加值" }, T)
    const rows = [...list.children].map((li) => li.textContent)
    expect(rows).toEqual([
      "示範使用者demo@forliosa.local到 2026/12/15・還沒選群組・11/16 試用（第二個）延長停止",
      "示範使用者demo@forliosa.local到 2026/12/31・群組 grp_family・11/16 試用延長停止",
      "阿凱kai@forliosa.local2026/11/6 到期・群組 grp_friends・10/7 轉帳 NT$300延長",
    ])
    expect(list).not.toHaveTextContent("家族投資")
  })

  it("開通：找不到帳號、付款人不是那個群組的擁有者，都就地寫在那一欄下面；成功後清單多一列", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/admin/members?kind=group")
    const email = await screen.findByRole("textbox", { name: "付款人的 Email" }, T)
    await user.click(screen.getByRole("button", { name: "開通" }))
    expect(screen.getByRole("alert")).toHaveTextContent("請輸入付款人登入用的 email。")
    expect(api.grantGroupPass).not.toHaveBeenCalled()
    await user.type(email, "nobody@example.com")
    await user.click(screen.getByRole("button", { name: "開通" }))
    expect(await screen.findByRole("alert", undefined, T)).toHaveTextContent("請對方先登入一次 Forliosa")
    await user.clear(email)
    await user.type(email, "friend@forliosa.local")
    await user.type(screen.getByRole("textbox", { name: "群組編號（選填）" }), "grp_family")
    await user.click(screen.getByRole("button", { name: "開通" }))
    expect(await screen.findByRole("alert", undefined, T)).toHaveTextContent("這個帳號不是這個群組的擁有者")
    await user.clear(screen.getByRole("textbox", { name: "群組編號（選填）" }))
    await user.click(screen.getByRole("button", { name: "開通" }))
    await waitFor(() => expect(screen.getByRole("list", { name: "群組加值" }).children).toHaveLength(4), T)
    expect(api.grantGroupPass).toHaveBeenLastCalledWith(expect.objectContaining({ email: "friend@forliosa.local" }))
    expect(vi.mocked(api.grantGroupPass).mock.lastCall![0]).not.toHaveProperty("group_id")
  })

  it("延長：從原本的最後一天往後接一個月；停止先確認（不移出成員）", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/admin/members?kind=group")
    await user.click(await screen.findByRole("button", { name: "延長 阿凱 的群組加值" }, T))
    const dialog = await screen.findByRole("dialog", undefined, T)
    expect(dialog).toHaveTextContent("現在在 2026/11/6 到期。")
    await user.click(within(dialog).getByRole("button", { name: "儲存" }))
    await waitFor(() => expect(api.updateGroupPass).toHaveBeenCalledWith("gps_friends", expect.objectContaining({ note: "10/7 轉帳 NT$300" })))
    await user.click(screen.getAllByRole("button", { name: "停止 示範使用者 的群組加值" })[1]!)
    const confirm = await screen.findByRole("alertdialog", undefined, T)
    expect(confirm).toHaveTextContent("那個群組馬上回到免費：日報停止，人數超過上限時不能再加人，不會移出成員。")
    await user.click(within(confirm).getByRole("button", { name: "停止加值" }))
    await waitFor(() => expect(api.revokeGroupPass).toHaveBeenCalledWith("gps_family"))
  })
})
