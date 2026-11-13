import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { toggleReaction } from "@/api/discussion-queries"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { ApiError, type ForliosaApi, type Reaction } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { createAppRouter } from "@/router"
import { DISCLAIMER, postErrorText, publicNameErrorText, reportErrorText, retryText, suspendedText } from "../labels"
import { PublicNamePrompt } from "../PublicNamePrompt"
import { ReportDialog } from "../ReportDialog"

// 走勢圖（lightweight-charts）在 jsdom 沒有 canvas 可以畫：這裡測的是討論，個股頁的圖換成空的
vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 討論串的畫面：沒登入的精簡外殼、清單的篩選與排序、公開暱稱、回覆與頻率限制、表情的樂觀更新、檢舉、
 * 站方管理的權限、開新主題、查看模式擋下、手機的紀錄入口。
 * 每個測試用一個全新的 mock adapter（和合約同一套規則），掛在全站共用的 `api` 上；時鐘可以往前撥。
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
    matches: desktop && /min-width:\s*1024px/.test(query), media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null })
beforeEach(() => act(resetAi))
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(() => {
    resetAi()
    useViewAs.setState({ target: null })
  })
  desktop = false
})

const T = { timeout: 6000 }

/** 這個測試用的後端：全新的 mock adapter，掛到全站共用的 `api` 上 */
function mount(options: MockOptions = {}) {
  let now = 1_000_000
  const adapter = createMockAdapter({ latency: [0, 0], clock: () => now, ...options })
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    // 把全站共用的 `api` 的每個方法換成這個 adapter 的（測試結束時 restoreAllMocks 還原）
    if (typeof fn === "function") vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  return { adapter, tick: (ms: number) => (now += ms) }
}
const named = { discussion: { publicName: "示範小資" } } satisfies MockOptions

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
function renderAlone(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}
const topicTitles = () => [...screen.getByRole("list", { name: "主題" }).children].map((li) => li.querySelector("a")!.textContent)
const hrefs = () => [...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "")

describe("沒登入：公開討論在精簡的外殼裡（字標＋登入）", () => {
  it("清單：只有公開的主題、沒有篩選、沒有 AI／底部列／連到帳本的東西；/me 只問一次", async () => {
    mount({ signedIn: false })
    renderApp("/discussions")
    expect(await screen.findByRole("heading", { level: 1, name: "討論" }, T)).toBeInTheDocument()
    await screen.findByText("台積電法說會前，大家怎麼配置？", undefined, T)
    // 外殼：字標連到討論、「登入」帶著回來的網址
    expect(screen.getByRole("link", { name: "Forliosa 討論" })).toHaveAttribute("href", "/discussions")
    expect(screen.getByRole("link", { name: "登入" })).toHaveAttribute("href", "/login?next=%2Fdiscussions")
    expect(screen.queryByRole("navigation", { name: "主要" })).toBeNull()
    expect(screen.queryByRole("button", { name: /問 AI/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /帳號選單/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /搜尋股票/ })).toBeNull()
    expect(document.querySelector(".dock")).toBeNull()
    expect(hrefs().filter((h) => h === "/" || /^\/(stock|groups|settings|history|admin)/.test(h))).toEqual([])
    // 內容：八則公開主題，沒有群組的；標記的股票是純文字
    expect(topicTitles()).toHaveLength(8)
    expect(screen.queryByText("我把聯發科的交易補記好了")).toBeNull()
    expect(screen.getAllByText(/台積電/).length).toBeGreaterThan(0)
    expect(screen.queryByRole("radiogroup", { name: "範圍" })).toBeNull()
    expect(screen.getByRole("radiogroup", { name: "排序" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "登入後發言" })).toHaveAttribute("href", "/login?next=%2Fdiscussions%2Fnew")
    expect(screen.queryByRole("link", { name: "開新主題" })).toBeNull()
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()
    // 沒登入時不問要登入的端點（不會 401、不會把整頁重新載入）
    expect(api.listGroups).not.toHaveBeenCalled()
    expect(vi.mocked(api.listTopics).mock.calls.every(([q]) => q?.scope === "public")).toBe(true)
    expect(api.getMe).toHaveBeenCalledTimes(1)
  })

  it("主題頁：讀得到內文與回覆；表情只有計數、被隱藏的回覆只有說明、股票是純文字、回覆區是「登入後發言」", async () => {
    mount({ signedIn: false })
    renderApp("/discussions/top_p_tsmc")
    expect(await screen.findByRole("heading", { level: 1, name: "台積電法說會前，大家怎麼配置？" }, T)).toBeInTheDocument()
    const replies = await screen.findByRole("list", { name: "回覆" }, T)
    expect(replies.children).toHaveLength(5)
    expect(within(replies).getByText("比重超過自己睡得著的程度就調，不用等法說會。")).toBeInTheDocument()
    expect(within(replies).getByText("這則內容已被站方隱藏。")).toBeInTheDocument()
    expect(screen.queryByText(/保證獲利/)).toBeNull()
    // 表情：只有計數，不能按
    expect(screen.getAllByRole("list", { name: "表情" }).length).toBeGreaterThan(0)
    expect(screen.getAllByText("讚 3")).toHaveLength(2)
    expect(screen.queryByRole("button", { name: "加表情" })).toBeNull()
    expect(screen.queryByRole("button", { name: /^(檢舉|刪除)/ })).toBeNull()
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("link", { name: /台積電 2330/ })).toBeNull()
    expect(screen.getByText("台積電", { exact: false, selector: "span" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "登入後發言" })).toHaveAttribute("href", "/login?next=%2Fdiscussions%2Ftop_p_tsmc")
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()
    expect(screen.queryByRole("navigation", { name: "主要" })).toBeNull()
    expect(api.getMe).toHaveBeenCalledTimes(1)
  })

  it("群組的主題：找不到（不透露存在）；開新主題要登入：導到登入頁、登入後回來", async () => {
    mount({ signedIn: false })
    renderApp("/discussions/top_g_dca")
    expect(await screen.findByRole("heading", { level: 1, name: "找不到這個主題" }, T)).toBeInTheDocument()
    expect(screen.getByText(/群組裡的主題只有成員看得到，要先登入。/)).toBeInTheDocument()
    expect(screen.queryByText("這個月的定期定額，大家扣了嗎？")).toBeNull()
    cleanup()
    const router = renderApp("/discussions/new?scope=public")
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"), T)
    expect(router.state.location.search).toMatchObject({ next: "/discussions/new?scope=public" })
  })
})

describe("清單：篩選（全部｜公開｜我的群組）與排序", () => {
  it("登入後預設是全部；公開的篩選裡沒有群組主題；群組的篩選只有那個群組的；「開新主題」跟著篩選預先選好", async () => {
    const user = userEvent.setup()
    mount()
    const router = renderApp("/discussions")
    const scope = await screen.findByRole("radiogroup", { name: "範圍" }, T)
    await within(scope).findByRole("radio", { name: "家族投資" }, T)
    expect(within(scope).getAllByRole("radio").map((r) => r.textContent)).toEqual(["全部", "公開", "家族投資", "大學同學"])
    expect(within(scope).getByRole("radio", { name: "全部" })).toHaveAttribute("aria-checked", "true")
    await screen.findByText("我把聯發科的交易補記好了", undefined, T)
    expect(topicTitles()).toHaveLength(12)
    // 群組範圍的主題寫群組名稱與「（你）」；標記的股票是連到個股頁的連結
    const mine = screen.getByText("我把聯發科的交易補記好了").closest("li")!
    expect(mine).toHaveTextContent("示範使用者（你）・1 則回覆・聯發科 2454・家族投資")
    expect(within(mine).getByRole("link", { name: "聯發科 2454" })).toHaveAttribute("href", "/stock/2454.TW")
    expect(within(mine).getByRole("link", { name: "我把聯發科的交易補記好了" })).toHaveAttribute("href", "/discussions/top_g_fix")
    expect(screen.getByRole("link", { name: "開新主題" })).toHaveAttribute("href", "/discussions/new")
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()

    await user.click(within(scope).getByRole("radio", { name: "公開" }))
    await waitFor(() => expect(screen.queryByText("我把聯發科的交易補記好了")).toBeNull(), T)
    await waitFor(() => expect(topicTitles()).toHaveLength(8), T)
    expect(router.state.location.search).toMatchObject({ scope: "public" })
    expect(screen.getByRole("link", { name: "開新主題" })).toHaveAttribute("href", "/discussions/new?scope=public")

    await user.click(within(scope).getByRole("radio", { name: "家族投資" }))
    await waitFor(() => expect(topicTitles()).toEqual(["我把聯發科的交易補記好了", "過年的紅包，要不要一起存 0056？", "這個月的定期定額，大家扣了嗎？"]), T)
    expect(within(scope).getByRole("radio", { name: "家族投資" })).toHaveAttribute("aria-checked", "true")
    expect(screen.getByRole("link", { name: "開新主題" })).toHaveAttribute("href", "/discussions/new?scope=group&group_id=grp_family")
    // 只有群組內容時沒有免責那一行（那是給公開內容的）
    expect(screen.queryByText(DISCLAIMER)).toBeNull()
  })

  it("排序：最新回覆（預設，日期格是最後回覆的時間）｜最新主題（日期格是發表的時間）；記在網址", async () => {
    const user = userEvent.setup()
    mount()
    const router = renderApp("/discussions?scope=public")
    const sort = await screen.findByRole("radiogroup", { name: "排序" }, T)
    await screen.findByText("0050 要不要改買 006208？", undefined, T)
    expect(within(sort).getByRole("radio", { name: "最新回覆" })).toHaveAttribute("aria-checked", "true")
    expect(topicTitles().slice(0, 3)).toEqual(["台積電法說會前，大家怎麼配置？", "0050 要不要改買 006208？", "00878 的殖利率，大家怎麼算？"])
    expect(document.querySelector(".form-head")).toHaveTextContent("最後回覆主題")
    const etf = () => screen.getByText("0050 要不要改買 006208？").closest("li")!
    expect(etf().querySelector(".date-cell")).toHaveTextContent("11/12（四）最後回覆12:31")

    await user.click(within(sort).getByRole("radio", { name: "最新主題" }))
    await waitFor(() => expect(topicTitles().slice(0, 3)).toEqual(["台積電法說會前，大家怎麼配置？", "00878 的殖利率，大家怎麼算？", "0050 要不要改買 006208？"]), T)
    expect(within(sort).getByRole("radio", { name: "最新主題" })).toHaveAttribute("aria-checked", "true")
    expect(document.querySelector(".form-head")).toHaveTextContent("發表主題")
    expect(etf().querySelector(".date-cell")).toHaveTextContent("11/10（二）發表於10:10")
    expect(router.state.location.search).toMatchObject({ scope: "public", sort: "new" })
  })

  it("空的：一個空狀態（原因＋怎麼開始），沒有表頭、沒有免責", async () => {
    mount({ scenario: "empty" })
    renderApp("/discussions")
    expect(await screen.findByText("還沒有主題", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("開第一個主題，問問大家怎麼看。")).toBeInTheDocument()
    expect(document.querySelector(".form-head")).toBeNull()
    expect(screen.queryByText(DISCLAIMER)).toBeNull()
  })
})

describe("公開暱稱：還沒有的時候，回覆框換成選暱稱的一欄表單", () => {
  it("規則就地說明（保留字不送到伺服器、重複是 409）→ 選好之後就是回覆框，寫著用什麼名字發言", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/discussions/top_p_etf")
    const form = await screen.findByRole("form", { name: "選公開暱稱" }, T)
    expect(screen.queryByRole("textbox", { name: "回覆內容" })).toBeNull()
    expect(within(form).getByText(/2 到 20 個字，之後每 7 天可以改一次/)).toBeInTheDocument()
    const input = within(form).getByRole("textbox", { name: "先選一個公開暱稱" })
    const save = within(form).getByRole("button", { name: "用這個暱稱" })
    await user.type(input, "官方小編")
    await user.click(save)
    expect(within(form).getByRole("alert")).toHaveTextContent("公開暱稱不能含「官方」。")
    expect(api.setPublicName).not.toHaveBeenCalled()
    await user.clear(input)
    await user.type(input, "阿土伯")
    await user.click(save)
    expect(await within(form).findByText("這個暱稱已經有人用了，換一個試試。", undefined, T)).toHaveAttribute("role", "alert")
    await user.clear(input)
    await user.type(input, "示範小資")
    await user.click(save)
    const box = await screen.findByRole("textbox", { name: "回覆內容" }, T)
    expect(screen.queryByRole("form", { name: "選公開暱稱" })).toBeNull()
    const reply = screen.getByRole("form", { name: "回覆這個主題" })
    expect(reply).toHaveTextContent("以「示範小資」公開發言")
    expect(within(reply).getByRole("link", { name: "改" })).toHaveAttribute("href", "/settings#profile")
    expect(box).toHaveValue("")
  })

  it("獨立的元件：不在任何頁面裡也能用；選好之後回報新的個人資料", async () => {
    const user = userEvent.setup()
    mount()
    const onDone = vi.fn()
    renderAlone(<PublicNamePrompt onDone={onDone} />)
    const input = screen.getByRole("textbox", { name: "先選一個公開暱稱" })
    expect(screen.getByRole("button", { name: "用這個暱稱" })).toBeDisabled()
    await user.type(input, "一")
    await user.click(screen.getByRole("button", { name: "用這個暱稱" }))
    expect(screen.getByRole("alert")).toHaveTextContent("公開暱稱要 2 到 20 個字。")
    expect(input).toHaveAttribute("aria-invalid", "true")
    await user.type(input, "二三")
    expect(screen.queryByRole("alert")).toBeNull()
    await user.click(screen.getByRole("button", { name: "用這個暱稱" }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ public_name: "一二三" })), T)
  })

  it("設定：個人資料裡的公開暱稱一欄（改過才有簽名格）；停權時寫到什麼時候", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/settings")
    const input = await screen.findByRole("textbox", { name: "公開暱稱" }, T)
    expect(input).toHaveValue("")
    expect(screen.getByText(/公開討論裡大家看到的是這個名字，群組裡仍用顯示名稱。2 到 20 個字；選好之後，每 7 天可以改一次。/)).toBeInTheDocument()
    const form = input.closest("form")!
    expect(within(form).queryByRole("button", { name: "儲存" })).toBeNull()
    await user.type(input, "示範小資")
    await user.click(within(form).getByRole("button", { name: "儲存" }))
    await waitFor(() => expect(api.setPublicName).toHaveBeenCalledWith("示範小資"), T)
    expect(await screen.findByText(/改了之後 7 天內不能再改。/, undefined, T)).toBeInTheDocument()
    expect(await screen.findByRole("textbox", { name: "公開暱稱" })).toHaveValue("示範小資")

    cleanup()
    vi.restoreAllMocks()
    mount({ discussion: { publicName: "示範小資", suspended: true } })
    renderApp("/settings")
    expect(await screen.findByText("你的公開發言已被站方暫停到 11/19（四）13:30。群組裡的發言不受影響。", undefined, T)).toBeInTheDocument()
  })
})

describe("回覆", () => {
  it("送出後出現在回覆裡（公開暱稱＋「（你）」）；馬上再發一則 → 就地說多久之後可以再送、內容留著；時間到了就能送", async () => {
    const user = userEvent.setup()
    const { tick } = mount(named)
    renderApp("/discussions/top_p_etf")
    const box = await screen.findByRole("textbox", { name: "回覆內容" }, T)
    const send = screen.getByRole("button", { name: "回覆" })
    await user.type(box, "我也是新的錢改買。")
    await user.click(send)
    const replies = screen.getByRole("list", { name: "回覆" })
    const posted = (await within(replies).findByText("我也是新的錢改買。", undefined, T)).closest("li")!
    expect(posted).toHaveTextContent("示範小資（你）")
    expect(within(posted).getByRole("button", { name: "刪除示範小資的回覆" })).toBeInTheDocument()
    expect(within(posted).queryByRole("button", { name: /^檢舉/ })).toBeNull()
    await waitFor(() => expect(box).toHaveValue(""), T)
    expect(await screen.findByText("5 則", undefined, T)).toBeInTheDocument()

    await user.type(box, "再補一句")
    await user.click(send)
    expect(await screen.findByRole("alert", undefined, T)).toHaveTextContent("發言太頻繁，10 秒後可以再送出。內容還在。")
    expect(box).toHaveValue("再補一句")
    expect(box).toHaveAttribute("aria-invalid", "true")
    tick(10_000)
    await user.click(send)
    expect(await within(replies).findByText("再補一句", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("空白的回覆不送出；公開發言被暫停時沒有回覆框、寫到什麼時候；群組的主題照常可以回覆（用顯示名稱）", async () => {
    const user = userEvent.setup()
    mount({ discussion: { publicName: "示範小資", suspended: true } })
    renderApp("/discussions/top_p_etf")
    expect(await screen.findByText("你的公開發言已被站方暫停到 11/19（四）13:30。群組裡的發言不受影響。", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("textbox")).toBeNull()
    cleanup()
    renderApp("/discussions/top_g_dca")
    const box = await screen.findByRole("textbox", { name: "回覆內容" }, T)
    expect(screen.getByRole("form", { name: "回覆這個主題" })).toHaveTextContent("以「示範使用者」在「家族投資」發言")
    expect(screen.queryByRole("link", { name: "改" })).toBeNull()
    await user.type(box, "   ")
    await user.click(screen.getByRole("button", { name: "回覆" }))
    expect(screen.getByRole("alert")).toHaveTextContent("請寫回覆。")
    expect(api.createReply).not.toHaveBeenCalled()
    // 群組範圍：頭像與顯示名稱；已離開的成員；沒有檢舉、沒有免責
    const replies = screen.getByRole("list", { name: "回覆" })
    expect(within(replies).getByText("已離開的成員")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /^檢舉/ })).toBeNull()
    expect(screen.queryByText(DISCLAIMER)).toBeNull()
  })

  it("回覆很多的主題：一次讀 50 則（看更多回覆）；送出自己的回覆之後，後面的都讀進來、看得到自己剛寫的", async () => {
    const user = userEvent.setup()
    const { adapter } = mount()
    for (let i = 1; i <= 55; i++) await adapter.createReply("top_g_red", { body: `第 ${i} 則` })
    renderApp("/discussions/top_g_red")
    const replies = await screen.findByRole("list", { name: "回覆" }, T)
    expect(replies.children).toHaveLength(50)
    expect(screen.getByText("57 則")).toBeInTheDocument()
    expect(within(replies).queryByText("第 55 則")).toBeNull()
    expect(screen.getByRole("button", { name: "看更多回覆" })).toBeInTheDocument()
    await user.type(screen.getByRole("textbox", { name: "回覆內容" }), "最後一則是我的")
    await user.click(screen.getByRole("button", { name: "回覆" }))
    expect(await within(replies).findByText("最後一則是我的", undefined, T)).toBeInTheDocument()
    expect(replies.children).toHaveLength(58)
    expect(within(replies).getByText("第 55 則")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("button", { name: "看更多回覆" })).toBeNull(), T)
  })

  it("被隱藏的內容：站方管理員（與作者）看得到原文，上面一行說明其他人看不到", async () => {
    mount(named)
    renderApp("/discussions/top_p_tsmc")
    const replies = await screen.findByRole("list", { name: "回覆" }, T)
    const hidden = within(replies).getByText("這則內容已被站方隱藏，其他人看不到下面的原文。").closest("li")!
    expect(hidden).toHaveTextContent(/保證獲利/)
  })

  it("刪除自己的主題：先確認（說會一起刪掉幾則回覆）→ 刪掉、回到清單", async () => {
    const user = userEvent.setup()
    const { adapter } = mount()
    const router = renderApp("/discussions/top_g_fix")
    await user.click(await screen.findByRole("button", { name: "刪除主題" }, T))
    const dialog = await screen.findByRole("alertdialog", undefined, T)
    expect(dialog).toHaveTextContent("刪除這個主題？")
    expect(dialog).toHaveTextContent("主題和底下的 1 則回覆會一起刪除，不能復原。")
    await user.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), T)
    expect(api.deleteTopic).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "刪除主題" }))
    await user.click(within(await screen.findByRole("alertdialog", undefined, T)).getByRole("button", { name: "刪除" }))
    await waitFor(() => expect(router.state.location.pathname).toBe("/discussions"), T)
    await expect(adapter.getTopic("top_g_fix")).rejects.toMatchObject({ status: 404 })
  })
})

describe("表情：按下立刻反映（樂觀更新），失敗還原", () => {
  const r = (emoji: Reaction["emoji"], count: number, mine: boolean): Reaction => ({ emoji, count, mine })
  it("toggleReaction：照固定的順序、數到 0 的拿掉、重複按不重複計", () => {
    expect(toggleReaction([r("👀", 2, false)], "👍", true)).toEqual([r("👍", 1, true), r("👀", 2, false)])
    expect(toggleReaction([r("👍", 3, true), r("👀", 1, false)], "👍", false)).toEqual([r("👍", 2, false), r("👀", 1, false)])
    expect(toggleReaction([r("🔥", 1, true)], "🔥", false)).toEqual([])
    expect(toggleReaction([r("👍", 3, true)], "👍", true)).toEqual([r("👍", 3, true)])
    expect(toggleReaction([r("👍", 3, false)], "👍", false)).toEqual([r("👍", 3, false)])
  })

  it("主題的表情：伺服器還沒回來就已經加一；伺服器失敗就還原", async () => {
    const user = userEvent.setup()
    mount(named)
    let fail!: (e: unknown) => void
    vi.mocked(api.addDiscussionReaction).mockImplementation(() => new Promise<void>((_, reject) => (fail = reject)))
    renderApp("/discussions/top_p_us")
    const chip = await screen.findByRole("button", { name: "關注 2" }, T)
    expect(chip).toHaveAttribute("aria-pressed", "false")
    await user.click(chip)
    // 請求還掛著：畫面已經是按過的樣子
    expect(await screen.findByRole("button", { name: "關注 3，你按過" })).toHaveAttribute("aria-pressed", "true")
    expect(api.addDiscussionReaction).toHaveBeenCalledWith({ target: "topic:top_p_us", emoji: "👀" })
    await act(async () => fail(new ApiError(500, "internal", "伺服器錯誤")))
    expect(await screen.findByRole("button", { name: "關注 2" }, T)).toHaveAttribute("aria-pressed", "false")
  })

  it("收回自己按過的：立刻減一；成功後以伺服器的計數為準", async () => {
    const user = userEvent.setup()
    const { adapter } = mount(named)
    renderApp("/discussions/top_p_etf")
    const chip = await screen.findByRole("button", { name: "讚 3，你按過" }, T)
    await user.click(chip)
    // 同一顆按鈕（主題的表情）：請求還沒回來就已經是沒按過、少一個
    await waitFor(() => expect(chip).toHaveAttribute("aria-label", "讚 2"))
    expect(chip).toHaveAttribute("aria-pressed", "false")
    await waitFor(() => expect(api.removeDiscussionReaction).toHaveBeenCalledWith("topic:top_p_etf", "👍"), T)
    await waitFor(async () => expect((await adapter.getTopic("top_p_etf")).reactions[0]).toEqual({ emoji: "👍", count: 2, mine: false }), T)
    expect(chip).toHaveAttribute("aria-label", "讚 2")
  })

  it("回覆的表情：從「加表情」選一個，那一則回覆多一個自己按過的小格", async () => {
    const user = userEvent.setup()
    mount(named)
    renderApp("/discussions/top_p_us")
    const reply = (await screen.findByText("金額不大、買了就放著的話，複委託的定期定額很省事。", undefined, T)).closest("li")!
    await user.click(within(reply).getByRole("button", { name: "加表情" }))
    await user.click(await screen.findByRole("button", { name: "恭喜" }, T))
    expect(await within(reply).findByRole("button", { name: "恭喜 1，你按過" }, T)).toHaveAttribute("aria-pressed", "true")
    expect(api.addDiscussionReaction).toHaveBeenCalledWith({ target: "reply:rep_p_us_1", emoji: "🎉" })
  })
})

describe("檢舉", () => {
  it("主題頁：別人的公開內容才有「檢舉」；要選理由；送出帶著合約的 target、理由與補充說明", async () => {
    const user = userEvent.setup()
    mount(named)
    renderApp("/discussions/top_p_etf")
    await user.click(await screen.findByRole("button", { name: "檢舉定期定額派的回覆" }, T))
    const dialog = await screen.findByRole("dialog", undefined, T)
    expect(within(dialog).getByRole("heading", { name: "檢舉這則回覆" })).toBeInTheDocument()
    expect(within(dialog).getAllByRole("radio").map((el) => el.closest("label")!.textContent)).toEqual(["廣告或洗版", "招攬或帶單", "辱罵或騷擾", "其他"])
    await user.click(within(dialog).getByRole("button", { name: "送出檢舉" }))
    expect(within(dialog).getByRole("alert")).toHaveTextContent("請選一個理由。")
    expect(api.reportDiscussion).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole("radio", { name: "招攬或帶單" }))
    await user.type(within(dialog).getByRole("textbox", { name: "補充說明（選填）" }), " 一直貼一樣的話 ")
    await user.click(within(dialog).getByRole("button", { name: "送出檢舉" }))
    await waitFor(() => expect(api.reportDiscussion).toHaveBeenCalledWith({ target: "reply:rep_p_etf_1", reason: "solicitation", note: "一直貼一樣的話" }), T)
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    // 主題本身也可以檢舉（別人的）
    expect(screen.getByRole("button", { name: "檢舉主題" })).toBeInTheDocument()
  })

  it("獨立的元件：只要一個 target；沒有補充說明就不送 note；伺服器的頻率限制就地說明", async () => {
    const user = userEvent.setup()
    mount(named)
    const onClose = vi.fn()
    renderAlone(<ReportDialog target="topic:top_p_etf" what="主題" onClose={onClose} />)
    expect(screen.getByRole("heading", { name: "檢舉這則主題" })).toBeInTheDocument()
    vi.mocked(api.reportDiscussion).mockRejectedValueOnce(new ApiError(429, "rate_limited", "檢舉太頻繁", { retry_after_seconds: 1500 }))
    await user.click(screen.getByRole("radio", { name: "其他" }))
    await user.click(screen.getByRole("button", { name: "送出檢舉" }))
    expect(await screen.findByRole("alert", undefined, T)).toHaveTextContent("檢舉太頻繁，約 25 分鐘後可以再送出。")
    expect(onClose).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "送出檢舉" }))
    await waitFor(() => expect(onClose).toHaveBeenCalled(), T)
    expect(api.reportDiscussion).toHaveBeenLastCalledWith({ target: "topic:top_p_etf", reason: "other" })
  })
})

describe("站方管理：只有站方管理員", () => {
  it("不是管理員：/admin/discussions 是「找不到這個頁面」、不向伺服器要檢舉；頭像選單沒有「站方管理」", async () => {
    const user = userEvent.setup()
    mount({ discussion: { admin: false } })
    renderApp("/admin/discussions")
    expect(await screen.findByRole("heading", { level: 1, name: "找不到這個頁面" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "站方管理" })).toBeNull()
    expect(api.listAdminReports).not.toHaveBeenCalled()
    expect(api.listSuspensions).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: /帳號選單/ }))
    expect(await screen.findByRole("menuitem", { name: "設定" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("menuitem", { name: "站方管理" })).toBeNull()
  })

  it("管理員：頭像選單有「站方管理」；待處理的檢舉是格線列，隱藏先確認、處理完就離開待處理", async () => {
    const user = userEvent.setup()
    const { adapter } = mount()
    const router = renderApp("/discussions")
    await user.click(await screen.findByRole("button", { name: /帳號選單/ }, T))
    await user.click(await screen.findByRole("menuitem", { name: "站方管理" }, T))
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/discussions"), T)
    expect(await screen.findByRole("heading", { level: 1, name: "站方管理" }, T)).toBeInTheDocument()
    const open = await screen.findByRole("list", { name: "待處理的檢舉" }, T)
    expect(open.children).toHaveLength(2)
    const row = open.children[0] as HTMLElement
    expect(row).toHaveTextContent("回覆")
    expect(row).toHaveTextContent("抱一半還敢說自己長期持有？看不懂財報就不要出來亂講。")
    expect(row).toHaveTextContent("短線獵人・檢舉 2 次：辱罵或騷擾 2・最早 11/12（四） 09:40")
    expect(within(row).getByRole("list", { name: "檢舉人的補充說明" })).toHaveTextContent("「人身攻擊，不是在討論」")
    expect(within(row).getByRole("link", { name: "看主題 →" })).toHaveAttribute("href", "/discussions/top_p_tsmc")
    expect(open.children[1]).toHaveTextContent("領息達人・檢舉 3 次：廣告或洗版 1、招攬或帶單 2")

    await user.click(within(row).getByRole("button", { name: "隱藏「短線獵人」的回覆" }))
    const dialog = await screen.findByRole("alertdialog", undefined, T)
    expect(dialog).toHaveTextContent("隱藏這則回覆？")
    expect(dialog).toHaveTextContent("這則的 2 次檢舉會標為已處理")
    await user.click(within(dialog).getByRole("button", { name: "隱藏" }))
    await waitFor(() => expect(screen.getByRole("list", { name: "待處理的檢舉" }).children).toHaveLength(1), T)
    expect((await adapter.listReplies("top_p_tsmc")).items[2]).toMatchObject({ id: "rep_p_tsmc_3", status: "hidden" })

    // 已處理：被隱藏的可以取消隱藏
    await user.click(screen.getByRole("radio", { name: "已處理" }))
    const resolved = await screen.findByRole("list", { name: "已處理的檢舉" }, T)
    expect(resolved.children).toHaveLength(3)
    expect(within(resolved).getByRole("button", { name: "取消隱藏「短線獵人」的回覆" })).toBeInTheDocument()
    expect(within(resolved).queryByRole("button", { name: /^不處理/ })).toBeNull()
    expect(router.state.location.search).toMatchObject({ status: "resolved" })
  })

  it("停權：選期間（預設 7 天）與原因，確認後出現在「停權中」；解除先確認", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/admin/discussions")
    const open = await screen.findByRole("list", { name: "待處理的檢舉" }, T)
    await user.click(within(open).getByRole("button", { name: "停權「領息達人」" }))
    const dialog = await screen.findByRole("alertdialog", undefined, T)
    expect(dialog).toHaveTextContent("暫停「領息達人」的公開發言？")
    const days = within(dialog).getByRole("radiogroup", { name: "停權期間" })
    expect(within(days).getAllByRole("radio").map((el) => el.textContent)).toEqual(["1 天", "7 天", "30 天", "永久"])
    expect(within(days).getByRole("radio", { name: "7 天" })).toHaveAttribute("aria-checked", "true")
    expect(within(dialog).getByRole("button", { name: "停權 7 天" })).toBeInTheDocument()
    await user.click(within(days).getByRole("radio", { name: "永久" }))
    await user.type(within(dialog).getByRole("textbox", { name: "原因（選填）" }), "洗版")
    await user.click(within(dialog).getByRole("button", { name: "永久停權" }))
    await waitFor(() => expect(api.createSuspension).toHaveBeenCalledWith({ target: "reply:rep_p_div_2", days: null, reason: "洗版" }), T)
    const list = await screen.findByRole("list", { name: "停權中" }, T)
    await waitFor(() => expect(list.children).toHaveLength(2), T)
    expect(list.children[0]).toHaveTextContent("領息達人")
    expect(list.children[0]).toHaveTextContent("永久")
    expect(list.children[0]).toHaveTextContent("洗版")
    expect(list.children[1]).toHaveTextContent("飆股情報站到 12/11（五） 22:30・11/11（三） 22:30 起・重複張貼招攬訊息")

    await user.click(within(list).getByRole("button", { name: "解除「飆股情報站」的停權" }))
    const confirm = await screen.findByRole("alertdialog", undefined, T)
    expect(confirm).toHaveTextContent("解除「飆股情報站」的停權？")
    await user.click(within(confirm).getByRole("button", { name: "解除" }))
    await waitFor(() => expect(screen.getByRole("list", { name: "停權中" }).children).toHaveLength(1), T)
    expect(api.liftSuspension).toHaveBeenCalledWith("sus_tout")
  })
})

describe("開新主題", () => {
  it("從群組來：預先選好群組與標記的股票；空的不送出、每一欄就地說明；發表後到那個主題", async () => {
    const user = userEvent.setup()
    mount()
    const router = renderApp("/discussions/new?scope=group&group_id=grp_family&symbol=2454.TW")
    expect(await screen.findByRole("radio", { name: /家族投資/ }, T)).toBeChecked()
    expect(screen.getByRole("radio", { name: /公開/ })).not.toBeChecked()
    expect(await screen.findByRole("list", { name: "已標記的股票" }, T)).toHaveTextContent("聯發科2454")
    const form = screen.getByRole("form", { name: "新主題" })
    expect(form).toHaveTextContent("以「示範使用者」在「家族投資」發言")
    await user.click(screen.getByRole("button", { name: "發表" }))
    expect(screen.getAllByRole("alert").map((el) => el.textContent)).toEqual(["請寫標題。", "請寫內文。"])
    expect(api.createTopic).not.toHaveBeenCalled()
    await user.type(screen.getByRole("textbox", { name: "標題" }), "年底要不要一起檢查帳本")
    expect(screen.getAllByRole("alert").map((el) => el.textContent)).toEqual(["請寫內文。"])
    await user.type(screen.getByRole("textbox", { name: "內文" }), "大家把今年的交易補齊，{Enter}{Enter}過年前來對一下。")
    await user.click(screen.getByRole("button", { name: "發表" }))
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/discussions\/top_\d+$/), T)
    expect(api.createTopic).toHaveBeenCalledWith({ scope: "group", group_id: "grp_family", title: "年底要不要一起檢查帳本", body: "大家把今年的交易補齊，\n\n過年前來對一下。", symbols: ["2454.TW"] })
    expect(await screen.findByRole("heading", { level: 1, name: "年底要不要一起檢查帳本" }, T)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "聯發科 2454" })).toHaveAttribute("href", "/stock/2454.TW")
  })

  it("沒有預先選：不替使用者決定發到哪裡；公開又沒有暱稱時，下面是選暱稱的表單，發表前要先選", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/discussions/new")
    await screen.findByRole("radio", { name: /家族投資/ }, T)
    expect(screen.getAllByRole("radio").filter((el) => (el as HTMLInputElement).checked)).toEqual([])
    expect(screen.queryByRole("form", { name: "選公開暱稱" })).toBeNull()
    await user.type(screen.getByRole("textbox", { name: "標題" }), "標題")
    await user.type(screen.getByRole("textbox", { name: "內文" }), "內文")
    await user.click(screen.getByRole("button", { name: "發表" }))
    expect(screen.getByRole("alert")).toHaveTextContent("請選擇要發到哪裡。")
    await user.click(screen.getByRole("radio", { name: /公開/ }))
    expect(screen.queryByRole("alert")).toBeNull()
    expect(await screen.findByRole("form", { name: "選公開暱稱" })).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "發表" }))
    expect(screen.getByRole("alert")).toHaveTextContent("發公開主題前，先在上面選一個公開暱稱。")
    expect(api.createTopic).not.toHaveBeenCalled()
    // 換成群組就不需要公開暱稱
    await user.click(screen.getByRole("radio", { name: /大學同學/ }))
    expect(screen.queryByRole("form", { name: "選公開暱稱" })).toBeNull()
    expect(screen.getByRole("form", { name: "新主題" })).toHaveTextContent("以「示範使用者」在「大學同學」發言")
  })

  it("伺服器的錯誤就地說明、內容留著：發言太頻繁（多久之後）、公開發言被暫停（到什麼時候）", async () => {
    const user = userEvent.setup()
    mount(named)
    renderApp("/discussions/new?scope=public")
    await screen.findByRole("radio", { name: /公開/ }, T)
    await user.type(screen.getByRole("textbox", { name: "標題" }), "標題")
    await user.type(screen.getByRole("textbox", { name: "內文" }), "內文")
    vi.mocked(api.createTopic).mockRejectedValueOnce(new ApiError(429, "rate_limited", "發言太頻繁，請 7200 秒後再試", { retry_after_seconds: 7200 }))
    await user.click(screen.getByRole("button", { name: "發表" }))
    expect(await screen.findByRole("alert", undefined, T)).toHaveTextContent("發言太頻繁，約 2 小時後可以再送出。內容還在。")
    expect(screen.getByRole("textbox", { name: "標題" })).toHaveValue("標題")
    expect(screen.getByRole("textbox", { name: "內文" })).toHaveValue("內文")
    vi.mocked(api.createTopic).mockRejectedValueOnce(new ApiError(403, "posting_suspended", "你的公開發言已被站方暫停", { until: "2026-11-20T04:00:00Z" }))
    await user.click(screen.getByRole("button", { name: "發表" }))
    expect(await screen.findByText("你的公開發言已被站方暫停到 11/20（五）12:00。群組裡的發言不受影響。", undefined, T)).toHaveAttribute("role", "alert")
  })
})

describe("錯誤訊息：說哪裡不對、什麼時候可以再試", () => {
  it("頻率限制的時間寫成人看得懂的；停權寫到什麼時候（永久另外寫）；其他錯誤照伺服器的句子", () => {
    expect(retryText(1)).toBe("1 秒後")
    expect(retryText(59)).toBe("59 秒後")
    expect(retryText(61)).toBe("約 2 分鐘後")
    expect(retryText(3600)).toBe("約 1 小時後")
    expect(retryText(86_100)).toBe("約 24 小時後")
    expect(suspendedText("9999-12-31T00:00:00Z")).toBe("你的公開發言已被站方永久暫停。群組裡的發言不受影響。")
    expect(suspendedText(null)).toBe("你的公開發言已被站方暫停。群組裡的發言不受影響。")
    expect(postErrorText(new ApiError(429, "rate_limited", "x", { retry_after_seconds: 8 }), "回覆")).toBe("發言太頻繁，8 秒後可以再送出。內容還在。")
    expect(postErrorText(new ApiError(429, "rate_limited", "x"), "回覆")).toBe("發言太頻繁，請稍後再送出。內容還在。")
    expect(postErrorText(new ApiError(409, "public_name_required", "x"), "主題")).toBe("發公開內容前要先選一個公開暱稱。")
    expect(postErrorText(new ApiError(409, "topic_hidden", "x"), "回覆")).toBe("這個主題已被站方隱藏，不能再回覆。")
    expect(postErrorText(new ApiError(422, "unknown_symbol", "找不到商品：NOPE"), "主題")).toBe("標記的股票裡有找不到的代號（NOPE），請移除後再送出。")
    expect(postErrorText(new ApiError(422, "validation_error", "標題最多 80 個字，現在 81 個字。"), "主題")).toBe("標題最多 80 個字，現在 81 個字。")
    expect(postErrorText(new ApiError(404, "not_found", "x"), "回覆")).toBe("這個主題已經看不到了，回覆沒有送出。")
    expect(postErrorText(new TypeError("Failed to fetch"), "回覆")).toBe("回覆沒有送出，內容還在。請檢查網路後再試一次。")
    expect(publicNameErrorText(new ApiError(409, "public_name_cooldown", "x", { retry_after_days: 3 }))).toBe("公開暱稱 7 天內只能改一次，3 天後可以再改。")
    expect(publicNameErrorText(new ApiError(409, "public_name_taken", "x"))).toBe("這個暱稱已經有人用了，換一個試試。")
    expect(reportErrorText(new ApiError(404, "not_found", "x"))).toBe("這則內容已經看不到了。")
  })
})

describe("個股與群組的「討論」分頁", () => {
  it("群組：這個群組的主題（不重複寫群組名稱）；「開新主題」預先選好這個群組", async () => {
    mount()
    renderApp("/groups/grp_family?tab=discussions")
    expect(await screen.findByRole("tab", { name: "討論" }, T)).toHaveAttribute("aria-selected", "true")
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["排行", "動態", "討論", "持股", "週報", "分享", "成員", "頻道"])
    await screen.findByText("我把聯發科的交易補記好了", undefined, T)
    expect(topicTitles()).toHaveLength(3)
    expect(screen.getByText("我把聯發科的交易補記好了").closest("li")).toHaveTextContent("示範使用者（你）・1 則回覆・聯發科 2454")
    expect(screen.getByText("我把聯發科的交易補記好了").closest("li")).not.toHaveTextContent("家族投資")
    expect(screen.getByRole("link", { name: "開新主題" })).toHaveAttribute("href", "/discussions/new?scope=group&group_id=grp_family")
    expect(api.listTopics).toHaveBeenCalledWith(expect.objectContaining({ scope: "group", group_id: "grp_family" }))
  })

  it("個股：標記這一檔的主題（公開＋我的群組）；「開新主題」預先標記這一檔；沒有主題時是空狀態", async () => {
    mount()
    renderApp("/stock/0050.TW?tab=discussions")
    expect(await screen.findByRole("tab", { name: "討論" }, T)).toHaveAttribute("aria-selected", "true")
    await screen.findByText("0050 要不要改買 006208？", undefined, T)
    expect(topicTitles().sort()).toEqual(["0050 要不要改買 006208？", "台積電法說會前，大家怎麼配置？", "這個月的定期定額，大家扣了嗎？", "高股息 ETF 要不要全部換成市值型？"].sort())
    expect(screen.getByText("這個月的定期定額，大家扣了嗎？").closest("li")).toHaveTextContent("家族投資")
    expect(screen.getByRole("link", { name: "開新主題" })).toHaveAttribute("href", "/discussions/new?symbol=0050.TW")
    expect(api.listTopics).toHaveBeenCalledWith(expect.objectContaining({ scope: "all", symbol: "0050.TW" }))
    cleanup()
    renderApp("/stock/2317.TW?tab=discussions")
    expect(await screen.findByText("還沒有人討論鴻海", undefined, T)).toBeInTheDocument()
  })
})

describe("查看別人的資產：討論擋下（和群組一樣）", () => {
  it("清單、主題、開新主題、站方管理都是擋頁；個股頁沒有「討論」分頁", async () => {
    const { adapter } = mount()
    const dad = (await adapter.listDelegations()).received[0]!
    act(() => useViewAs.setState({ target: { delegation_id: dad.id, owner: dad.owner, scope: dad.scope, accounts: dad.accounts } }))
    for (const path of ["/discussions", "/discussions/top_p_etf", "/discussions/new"]) {
      renderApp(path)
      expect(await screen.findByText(/這裡是你自己的討論，結束查看後才能使用/, undefined, T)).toBeInTheDocument()
      cleanup()
    }
    renderApp("/admin/discussions")
    expect(await screen.findByText(/這裡是你自己的站方管理，結束查看後才能使用/, undefined, T)).toBeInTheDocument()
    expect(api.listTopics).not.toHaveBeenCalled()
    expect(api.listAdminReports).not.toHaveBeenCalled()
    cleanup()
    renderApp("/stock/2330.TW?tab=discussions")
    await screen.findByRole("tab", { name: "總覽" }, T)
    expect(screen.queryByRole("tab", { name: "討論" })).toBeNull()
    expect(screen.getByRole("tab", { name: "總覽" })).toHaveAttribute("aria-selected", "true")
  })
})

describe("手機：底部列是 帳本・群組・討論；AI 對話紀錄從「問 AI」的時鐘進去", () => {
  it("討論分頁在討論的每一頁都是選取的；「問 AI」裡的時鐘到紀錄頁（標題看得到）", async () => {
    const user = userEvent.setup()
    mount(named)
    const router = renderApp("/discussions/top_p_etf")
    const nav = await screen.findByRole("navigation", { name: "主要" }, T)
    expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual(["帳本", "群組", "討論"])
    expect(within(nav).getByRole("link", { name: "討論" })).toHaveAttribute("aria-current", "page")
    expect(within(nav).getByRole("link", { name: "討論" })).toHaveAttribute("href", "/discussions")
    expect(within(nav).queryByRole("link", { name: "紀錄" })).toBeNull()
    await user.click(screen.getByRole("button", { name: "問 AI" }))
    const dialog = await screen.findByRole("dialog", undefined, T)
    await user.click(within(dialog).getByRole("button", { name: "紀錄" }))
    await waitFor(() => expect(router.state.location.pathname).toBe("/history"), T)
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    const title = await screen.findByRole("heading", { level: 1, name: "紀錄" }, T)
    expect(title.closest("[class*='sr-only']")).toBeNull()
    expect(await screen.findByRole("button", { name: "發起新對話" }, T)).toBeInTheDocument()
  })

  it("桌面：頂部列是 帳本・群組・討論", async () => {
    desktop = true
    mount()
    renderApp("/discussions")
    const nav = await screen.findByRole("navigation", { name: "主要" }, T)
    expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual(["帳本", "群組", "討論"])
    expect(within(nav).getByRole("link", { name: "討論" })).toHaveAttribute("aria-current", "page")
    expect(within(nav).getByRole("link", { name: "帳本" })).not.toHaveAttribute("aria-current")
  })
})
