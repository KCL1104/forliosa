import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { ACCOUNT_DELETE_CONFIRMATION, ApiError, type ForliosaApi } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { Markdown } from "@/components/markdown"
import { Toaster } from "@/components/ui/sonner"
import { replyDraftKey } from "@/lib/drafts"
import { hardNavigate } from "@/lib/hard-nav"
import { claimLocalUserData, clearLocalUserData } from "@/lib/local-data"
import { isPublicReadPath } from "@/lib/next-path"
import { termsNoticeText } from "@/lib/terms-notice"
import { isDraft, stripReviewNote } from "@/pages/legal/legal-text"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))
vi.mock("@/lib/hard-nav", () => ({ hardNavigate: vi.fn() }))

/**
 * 上線前的帳號功能：服務條款與隱私權政策的頁面（不用登入就能讀、草稿標示）、登入頁的同意文字、條款更新的那一行、
 * 設定頁的「帳號與資料」（匯出、刪除帳號）、登出或換人登入時清掉這台瀏覽器上的對話與草稿。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  Element.prototype.setPointerCapture ??= () => {}
  Element.prototype.releasePointerCapture ??= () => {}
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
  vi.mocked(hardNavigate).mockClear()
  act(() => {
    resetAi()
    useViewAs.setState({ target: null })
  })
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

const thread = (id: string) => ({ id, title: "台積電怎麼看", updatedAt: new Date().toISOString(), messages: [] })

describe("Markdown（條款文件的版面）", () => {
  const SOURCE = [
    "# 標題",
    "",
    "第一段有**粗體**與 `代號`，連到 <https://forliosa.trade> 和 [站內](/privacy)。",
    "",
    "## 第一節",
    "",
    "- 第一點",
    "  - 巢狀的一點",
    "- 生效日期：【待填：生效日期】",
    "",
    "1. 一",
    "2. 二",
    "",
    "| 對象 | 做什麼 |",
    "|---|---|",
    "| Railway | 主機 & 資料庫 |",
    "",
    "<script>alert(1)</script>",
    "",
    "[壞連結](javascript:alert(1))",
  ].join("\n")

  it("標題、清單、表格、連結照文件的結構畫；原始 HTML 與危險的連結只是字", () => {
    const { container } = render(<Markdown source={SOURCE} />)
    expect(screen.getByRole("heading", { level: 1, name: "標題" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { level: 2, name: "第一節" }).className).toMatch(/\bborder-print\b/)
    expect(screen.getByText("粗體").tagName).toBe("STRONG")
    expect(screen.getByText("代號").tagName).toBe("CODE")
    // 清單：兩層；有序清單另外一個
    const lists = screen.getAllByRole("list")
    expect(lists).toHaveLength(3)
    expect(within(lists[0]!).getByText("巢狀的一點")).toBeInTheDocument()
    expect(container.querySelector("ol")!.children).toHaveLength(2)
    // 表格：表頭是欄標題，內容裡的 & 還原成字
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["對象", "做什麼"])
    expect(screen.getByRole("cell", { name: "主機 & 資料庫" })).toBeInTheDocument()
    // 連結：站外另開新視窗、站內不另開；javascript: 不是連結
    const external = screen.getByRole("link", { name: "https://forliosa.trade" })
    expect(external).toHaveAttribute("target", "_blank")
    expect(external).toHaveAttribute("rel", "noopener noreferrer")
    expect(screen.getByRole("link", { name: "站內" })).not.toHaveAttribute("target")
    expect(screen.queryByRole("link", { name: "壞連結" })).toBeNull()
    expect(screen.getByText("壞連結")).toBeInTheDocument()
    // 原始 HTML 不會變成元素
    expect(container.querySelector("script")).toBeNull()
    expect(container.textContent).toContain("<script>alert(1)</script>")
    // 還沒填的地方標出來
    expect(screen.getByText("【待填：生效日期】").tagName).toBe("MARK")
  })

  it("節有 id；「第 N 節」是頁內連結；這份文件沒有那一節就只是字", () => {
    const md = "# 文件\n\n## 1. 第一節\n\n見第 2 節，另見第 9 節。\n\n## 2. 第二節\n\n內文"
    render(<Markdown source={md} />)
    expect(screen.getByRole("heading", { level: 2, name: "1. 第一節" })).toHaveAttribute("id", "sec-1")
    expect(screen.getByRole("heading", { level: 2, name: "2. 第二節" })).toHaveAttribute("id", "sec-2")
    expect(screen.getByRole("link", { name: "第 2 節" })).toHaveAttribute("href", "#sec-2")
    // 這份文件沒有第 9 節：不做成壞掉的連結
    expect(screen.queryByRole("link", { name: "第 9 節" })).toBeNull()
  })

  it("表格：兩欄的照欄寬換行（沒有最小寬度）；三欄以上在手機改成一列一塊（欄名：內容），不橫向捲動", () => {
    const two = "## 7. 保存多久\n\n| 資料 | 保存期間 |\n|---|---|\n| 登入狀態 | 30 天 |\n"
    const { container, unmount } = render(<Markdown source={two} />)
    const table = screen.getByRole("table", { name: "7. 保存多久（表格）" })
    expect(table.className).not.toMatch(/min-w-|max-sm:hidden/)
    expect(container.querySelector("ul")).toBeNull()
    expect(container.querySelector(".overflow-x-auto")).toBeNull()
    unmount()
    const four = "## 4. 廠商\n\n| 廠商 | 做什麼 | 會經手什麼 | 所在地 |\n|---|---|---|---|\n| Railway | 主機 | 全部資料 | 新加坡 |\n"
    render(<Markdown source={four} />)
    // 桌面是表格（手機藏起來）；手機是清單（桌面藏起來）
    expect(screen.getByRole("table", { name: "4. 廠商（表格）" })).toHaveClass("max-sm:hidden")
    const list = screen.getByRole("list", { name: "4. 廠商（表格）" })
    expect(list).toHaveClass("sm:hidden")
    const row = within(list).getByRole("listitem")
    expect(row.textContent).toBe("Railway做什麼：主機會經手什麼：全部資料所在地：新加坡")
  })

  it("草稿的判斷與給審閱者看的引言", () => {
    expect(isDraft("生效日期：【待填：生效日期】")).toBe(true)
    expect(isDraft("生效日期：2026-12-01")).toBe(false)
    expect(stripReviewNote("> 本文件是草稿，供律師審閱。\n> 第二行\n\n# 標題\n\n> 內文裡的引言留著")).toBe("# 標題\n\n> 內文裡的引言留著")
    expect(stripReviewNote("# 標題")).toBe("# 標題")
  })
})

describe("服務條款與隱私權政策的頁面", () => {
  it("不用登入就能讀（精簡的外殼）；還有待填的項目時標示草稿；兩份互相連結", async () => {
    expect(isPublicReadPath("/terms") && isPublicReadPath("/privacy")).toBe(true)
    expect(isPublicReadPath("/settings")).toBe(false)
    mount({ signedIn: false })
    const router = renderApp("/privacy")
    expect(await screen.findByRole("heading", { level: 1, name: /隱私權政策/ }, T)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/privacy") // 沒有被導到登入頁
    expect(screen.getByRole("note")).toHaveTextContent("草稿：這份文件還在審閱，有些項目還沒填，尚未生效。")
    // 給審閱者的那段引言不在頁面上
    expect(screen.queryByText(/供產品負責人與律師審閱/)).toBeNull()
    expect(screen.getByRole("link", { name: "Forliosa 討論" })).toBeInTheDocument()
    expect(screen.queryByRole("navigation", { name: "主要" })).toBeNull()
    const other = within(screen.getByRole("article")).getByRole("link", { name: "服務條款" })
    expect(other).toHaveAttribute("href", "/terms")
    cleanup()
    mount()
    renderApp("/terms")
    expect(await screen.findByRole("heading", { level: 1, name: /服務條款/ }, T)).toBeInTheDocument()
    expect(within(screen.getByRole("article")).getByRole("link", { name: "隱私權政策" })).toHaveAttribute("href", "/privacy")
    // 登入後是一般的外殼
    expect(screen.getByRole("navigation", { name: "主要" })).toBeInTheDocument()
  })

  it("分頁標題是文件名稱；有目錄（每一節一個頁內連結）；〈隱私權政策〉第 N 節連到那一頁的那一節；草稿日期不顯示", async () => {
    mount()
    renderApp("/terms")
    expect(await screen.findByRole("heading", { level: 1, name: /服務條款/ }, T)).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe("服務條款｜Forliosa"))
    const toc = screen.getByRole("navigation", { name: "目錄" })
    expect(within(toc).getByRole("link", { name: "重點先講" })).toHaveAttribute("href", "#sec-top")
    expect(within(toc).getByRole("link", { name: "6. 討論區規則" })).toHaveAttribute("href", "#sec-6")
    expect(screen.getByRole("heading", { level: 2, name: "6. 討論區規則" })).toHaveAttribute("id", "sec-6")
    const article = screen.getByRole("article")
    expect(within(article).getByRole("link", { name: "〈隱私權政策〉第 6 節" })).toHaveAttribute("href", "/privacy#sec-6")
    expect(within(article).getAllByRole("link", { name: "第 9 節" })[0]).toHaveAttribute("href", "#sec-9")
    expect(within(article).queryByText(/草稿日期/)).toBeNull()
  })

  it("登入頁：登入即表示同意，連到兩份文件；剛刪除帳號回來時寫一句", async () => {
    mount({ signedIn: false })
    renderApp("/login")
    const consent = (await screen.findByText(/登入即表示你同意/, undefined, T)).closest("p")!
    // 只有登入的那一塊：一句話說 Forliosa 是什麼、兩種登入方式（一樣重的外框按鈕，Google 在前）、沒有示範畫面
    expect(screen.getByText("Forliosa 是以台股為主的持倉帳本，可以看績效、查個股、問 AI，也能和親友開群組。")).toHaveClass("text-base", "text-ink")
    expect(screen.queryByRole("figure")).toBeNull()
    const buttons = await screen.findAllByRole("button", { name: /登入$/ }, T)
    expect(buttons.map((b) => b.textContent)).toEqual(["用 Google 登入", "用 Discord 登入"])
    for (const b of buttons) expect(b.className).toMatch(/border-ctl/)
    expect(screen.getByText(/第一次登入會自動建立帳號。兩種方式用同一個 Email，會是同一個帳號。/)).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe("登入｜Forliosa"))
    expect(within(consent).getByRole("link", { name: "服務條款" })).toHaveAttribute("href", "/terms")
    expect(within(consent).getByRole("link", { name: "隱私權政策" })).toHaveAttribute("href", "/privacy")
    expect(screen.queryByText("你的帳號已經刪除。")).toBeNull()
    cleanup()
    renderApp("/login?deleted=1")
    expect(await screen.findByText("你的帳號已經刪除。", undefined, T)).toHaveAttribute("role", "status")
  })

  it("登入頁：只開一種登入方式時是墨色的主要按鈕；按下整頁導到那一家的登入網址", async () => {
    mount({ signedIn: false })
    vi.mocked(api.getAuthProviders).mockResolvedValue({ discord: false, google: true, dev_login: false })
    const assign = vi.fn()
    vi.stubGlobal("location", { ...window.location, assign })
    try {
      const user = userEvent.setup()
      renderApp("/login?next=%2Fgroups")
      const only = await screen.findByRole("button", { name: "用 Google 登入" }, T)
      expect(screen.queryByRole("button", { name: "用 Discord 登入" })).toBeNull()
      expect(only.className).toMatch(/bg-act/)
      expect(screen.getByText("第一次登入會自動建立帳號。")).toBeInTheDocument()
      await user.click(only)
      expect(assign).toHaveBeenCalledWith(api.googleLoginUrl("/groups"))
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("沒登入的公開討論頁尾：Forliosa 是什麼那一行後面有兩份文件的連結", async () => {
    mount({ signedIn: false })
    renderApp("/discussions")
    await screen.findByText("台積電法說會前，大家怎麼配置？", undefined, T)
    const about = screen.getByText(/Forliosa 是以台股為主/).closest("p")!.parentElement!
    expect(within(about).getByRole("link", { name: "服務條款" })).toHaveAttribute("href", "/terms")
    expect(within(about).getByRole("link", { name: "隱私權政策" })).toHaveAttribute("href", "/privacy")
  })
})

describe("條款更新那一行的句子", () => {
  it("有生效日與摘要就寫出來；生效日過了換一種說法；不是今年寫年份；都沒有就是原本那一句", () => {
    const today = "2026-11-13"
    expect(termsNoticeText("2026-12-01", "新增匯出資料的說明。", today)).toBe("12/1 起適用新版服務條款與隱私權政策：新增匯出資料的說明。")
    expect(termsNoticeText("2026-12-01", null, today)).toBe("12/1 起適用新版服務條款與隱私權政策。")
    expect(termsNoticeText("2026-11-01", "改了管轄法院", today)).toBe("服務條款與隱私權政策在 11/1 更新：改了管轄法院。")
    expect(termsNoticeText("2027-01-15", null, today)).toBe("2027/01/15 起適用新版服務條款與隱私權政策。")
    expect(termsNoticeText(null, "新增匯出資料的說明", today)).toBe("服務條款與隱私權政策已更新：新增匯出資料的說明。")
    expect(termsNoticeText(null, null, today)).toBe("服務條款與隱私權政策已更新。")
  })
})

describe("條款更新的那一行", () => {
  it("目前的版本和同意過的不同：一行說明＋兩個連結＋「知道了」；按了之後記下版本、不再出現", async () => {
    const user = userEvent.setup()
    mount({ terms: { current: "2026-12-01", accepted: "2026-11-13" } })
    renderApp("/settings")
    const notice = await screen.findByRole("status", undefined, T)
    expect(notice).toHaveTextContent("服務條款與隱私權政策已更新。")
    expect(within(notice).getByRole("link", { name: "服務條款" })).toHaveAttribute("href", "/terms")
    expect(within(notice).getByRole("link", { name: "隱私權政策" })).toHaveAttribute("href", "/privacy")
    await user.click(within(notice).getByRole("button", { name: "知道了" }))
    await waitFor(() => expect(api.acceptTerms).toHaveBeenCalledWith("2026-12-01"), T)
    await waitFor(() => expect(screen.queryByText("服務條款與隱私權政策已更新。")).toBeNull(), T)
  })

  it("沒有啟用版本、或已經同意目前的版本：不出現", async () => {
    mount()
    renderApp("/settings")
    await screen.findByRole("heading", { level: 1, name: "設定" }, T)
    expect(screen.queryByText("服務條款與隱私權政策已更新。")).toBeNull()
    cleanup()
    mount({ terms: { current: "2026-12-01", accepted: "2026-12-01" } })
    renderApp("/settings")
    await screen.findByRole("heading", { level: 1, name: "設定" }, T)
    expect(screen.queryByText("服務條款與隱私權政策已更新。")).toBeNull()
  })

  it("從來沒同意過（版本啟用之前就有的帳號）：也會出現", async () => {
    mount({ terms: { current: "2026-12-01" } })
    renderApp("/")
    expect(await screen.findByText("服務條款與隱私權政策已更新。", undefined, T)).toBeInTheDocument()
  })
})

describe("設定：帳號與資料", () => {
  it("匯出我的資料：下載一個 JSON 檔（檔名有日期）；太頻繁時就地說多久之後可以再試", async () => {
    const user = userEvent.setup()
    mount()
    const createUrl = vi.fn((blob: Blob) => (void blob, "blob:forliosa-export"))
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: vi.fn() })
    const clicks: { href: string; download: string }[] = []
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push({ href: this.href, download: this.download })
    })
    renderApp("/settings")
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    await user.click(within(section).getByRole("button", { name: "匯出" }))
    await waitFor(() => expect(clicks).toHaveLength(1), T)
    expect(clicks[0]!.download).toMatch(/^forliosa-export-\d{8}\.json$/)
    expect(clicks[0]!.href).toBe("blob:forliosa-export")
    const blob = createUrl.mock.calls[0]![0]
    expect(blob.type).toBe("application/json")
    const data = JSON.parse(await blob.text()) as { format_version: number; profile: { email: string }; transactions: unknown[] }
    expect(data.format_version).toBe(1)
    expect(data.profile.email).toBe("demo@forliosa.local")
    expect(data.transactions.length).toBeGreaterThan(0)
    expect(await screen.findByText("已下載匯出檔", undefined, T)).toBeInTheDocument()
    // 伺服器說太頻繁
    vi.mocked(api.exportMe).mockRejectedValueOnce(new ApiError(429, "rate_limited", "匯出太頻繁", { retry_after_seconds: 1500 }))
    await user.click(within(section).getByRole("button", { name: "匯出" }))
    expect(await within(section).findByRole("alert", undefined, T)).toHaveTextContent("匯出太頻繁，約 25 分鐘後可以再試。")
    expect(clicks).toHaveLength(1)
  })

  it("刪除帳號：說清楚刪掉什麼、留下什麼；要輸入那句話才能按；成功後清掉這台瀏覽器的對話與草稿、回到登入頁", async () => {
    const user = userEvent.setup()
    mount()
    act(() => useAi.setState({ ownerId: "usr_01JDEMO", threads: [thread("thr_1")] }))
    window.sessionStorage.setItem(replyDraftKey("usr_01JDEMO", "top_p_etf"), JSON.stringify("沒送出的回覆"))
    renderApp("/settings")
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    await user.click(within(section).getByRole("button", { name: "刪除帳號…" }))
    const dialog = await screen.findByRole("dialog", undefined, T)
    expect(within(dialog).getByRole("heading", { name: "刪除帳號？" })).toBeInTheDocument()
    expect(dialog).toHaveTextContent("刪除之後不能復原")
    expect(dialog).toHaveTextContent("所有券商帳戶與交易")
    expect(dialog).toHaveTextContent("作者會顯示成「已刪除的帳號」")
    const confirm = within(dialog).getByRole("button", { name: "永久刪除帳號" })
    expect(confirm).toBeDisabled()
    const input = within(dialog).getByRole("textbox", { name: `請輸入「${ACCOUNT_DELETE_CONFIRMATION}」` })
    await user.type(input, "刪除我的帳")
    expect(confirm).toBeDisabled()
    // 伺服器失敗：什麼都沒刪，就地說明，對話與草稿都還在
    await user.type(input, "號")
    expect(confirm).toBeEnabled()
    vi.mocked(api.deleteMe).mockRejectedValueOnce(new ApiError(500, "internal", "伺服器錯誤"))
    await user.click(confirm)
    expect(await within(dialog).findByRole("alert", undefined, T)).toHaveTextContent("帳號沒有刪除，資料都還在。伺服器錯誤")
    expect(hardNavigate).not.toHaveBeenCalled()
    expect(useAi.getState().threads).toHaveLength(1)
    // 再按一次：成功
    await user.click(confirm)
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/login?deleted=1"), T)
    expect(api.deleteMe).toHaveBeenLastCalledWith(ACCOUNT_DELETE_CONFIRMATION)
    expect(useAi.getState().threads).toEqual([])
    expect(useAi.getState().ownerId).toBeNull()
    expect(window.sessionStorage.getItem(replyDraftKey("usr_01JDEMO", "top_p_etf"))).toBeNull()
  })

  it("取消或關閉：什麼都沒送出；區塊裡有兩份文件的連結", async () => {
    const user = userEvent.setup()
    mount()
    renderApp("/settings")
    const section = await screen.findByRole("region", { name: "帳號與資料" }, T)
    expect(within(section).getByRole("link", { name: "服務條款" })).toHaveAttribute("href", "/terms")
    expect(within(section).getByRole("link", { name: "隱私權政策" })).toHaveAttribute("href", "/privacy")
    await user.click(within(section).getByRole("button", { name: "刪除帳號…" }))
    const dialog = await screen.findByRole("dialog", undefined, T)
    await user.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), T)
    expect(api.deleteMe).not.toHaveBeenCalled()
  })
})

describe("這台瀏覽器上的對話與草稿是誰的", () => {
  it("同一個人再登入：對話留著；換一個人登入：清掉上一個人的", () => {
    act(() => {
      claimLocalUserData("usr_a")
      useAi.setState({ threads: [thread("thr_1")], threadId: "thr_1" })
      claimLocalUserData("usr_a")
    })
    expect(useAi.getState().threads).toHaveLength(1)
    act(() => claimLocalUserData("usr_b"))
    expect(useAi.getState().threads).toEqual([])
    expect(useAi.getState().threadId).toBeNull()
    expect(useAi.getState().ownerId).toBe("usr_b")
  })

  it("還沒記過是誰的（舊版留下的紀錄）：算現在登入的這個人的", () => {
    act(() => {
      useAi.setState({ ownerId: null, threads: [thread("thr_old")] })
      claimLocalUserData("usr_a")
    })
    expect(useAi.getState().threads).toHaveLength(1)
    expect(useAi.getState().ownerId).toBe("usr_a")
  })

  it("登出、刪除帳號：對話、草稿、查看中的對象都清掉；裝置的顯示偏好不動", () => {
    window.sessionStorage.setItem(replyDraftKey("usr_a", "top_1"), JSON.stringify("草稿"))
    window.sessionStorage.setItem("forliosa:mock-auth", "signed-in")
    act(() => {
      useAi.setState({ ownerId: "usr_a", threads: [thread("thr_1")], panelOpen: false })
      clearLocalUserData()
    })
    expect(useAi.getState().threads).toEqual([])
    expect(useAi.getState().ownerId).toBeNull()
    expect(useAi.getState().panelOpen).toBe(false) // 面板開合是這台裝置的設定
    expect(window.sessionStorage.getItem(replyDraftKey("usr_a", "top_1"))).toBeNull()
    expect(window.sessionStorage.getItem("forliosa:mock-auth")).toBe("signed-in")
    expect(useViewAs.getState().target).toBeNull()
  })
})
