import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import type { ForliosaApi } from "@/api/types"
import { jumpTo, ReportContext, titleBody } from "@/pages/market/reports/report-context"
import { ReportNumbers } from "@/pages/market/reports/ReportNumbers"
import { Cites } from "@/pages/market/reports/ReportText"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 市場報告審查修正（2026-11-17）：資料版的完整免責不提 AI、更早的報告不重複日期、數字欄只在「、」後換行、
 * 觸控時相鄰的出處號碼不互相蓋住、跳回原句不改 Tab 順序、從報告頁用方向鍵換分頁焦點不掉、
 * 盲測並排只挑看得了的版本、頻道開關的說明照實際送法、群組頁的「昨日」用伺服器的前一個交易日、管理員可以更正。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
})
let wide = false
beforeEach(() => {
  wide = false
  window.matchMedia = ((query: string) => ({
    matches: wide && /min-width: 1280px|min-width: 1024px/.test(query), media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
  act(resetAi)
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null, ownerId: null })
afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
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
  return { adapter, spies }
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

const report = async () => (await screen.findByRole("heading", { level: 2, name: /^(盤前重點|盤後重點|市場週報) / }, T)).closest("article")!

describe("報告的字", () => {
  it("規則寫的標題拿掉「報告名稱＋日期：」，週報也一樣；AI 的標題不動", () => {
    expect(titleBody("盤前重點", "盤前重點 10/30（五）：美股 10/29 收盤與今日行事曆")).toBe("美股 10/29 收盤與今日行事曆")
    expect(titleBody("市場週報", "市場週報 11/16–11/20：加權指數週 ▲1.20%")).toBe("加權指數週 ▲1.20%")
    expect(titleBody("盤後重點", "加權指數跌 6.03%，收 41,040.08 點")).toBe("加權指數跌 6.03%，收 41,040.08 點")
    expect(titleBody("盤後重點", "盤後重點 11/16（一）")).toBe("盤後重點 11/16（一）")
  })

  it("資料版：最上面與最下面都不說是 AI 寫的；更早的報告不重複日期", async () => {
    mount({ reports: "pending" })
    renderApp("/market?tab=reports&kind=premarket")
    const article = await report()
    const footer = article.querySelector("footer")!
    expect(footer.textContent).toMatch(/^免責聲明這份報告依公開資料整理/)
    expect(footer.textContent).not.toMatch(/AI|媒體報導/)
    const earlier = (await screen.findByRole("heading", { name: "更早的報告" }, T)).closest("section")!
    for (const link of within(earlier).getAllByRole("link")) expect(link.textContent).not.toMatch(/^盤前重點 \d/)
  })

  it("數字欄：一串名稱只在「、」之後換行", () => {
    render(<ReportNumbers items={[{ key: "top_industries", label: "成交金額前三產業", value: "半導體業、電腦及週邊設備業、電子零組件業", change: null, tone: null, date_label: "11/16–11/20", estimate: false, note: null }]} />)
    const spans = [...document.querySelectorAll("[data-number=top_industries] span.inline-block")].map((s) => s.textContent)
    expect(spans).toEqual(["半導體業、", "電腦及週邊設備業、", "電子零組件業"])
  })

  it("觸控時並排的出處號碼：放大的範圍只到自己的邊，第一個向左、最後一個向右；只有一個時左右都放大", () => {
    const ctx = { prefix: "", admin: false, openSection: () => {} }
    render(
      <ReportContext.Provider value={ctx}>
        <Cites cites={[1, 2, 3]} />
        <Cites cites={[4]} />
      </ReportContext.Provider>,
    )
    const [a, b, c, d] = [...document.querySelectorAll<HTMLAnchorElement>("a[data-fn-ref]")]
    expect(a!.className).toMatch(/pointer-coarse:before:-left-\[1\.125rem\]/)
    expect(a!.className).toMatch(/pointer-coarse:before:right-0/)
    expect(b!.className).toMatch(/pointer-coarse:before:left-0/)
    expect(b!.className).toMatch(/pointer-coarse:before:right-0/)
    expect(c!.className).toMatch(/pointer-coarse:before:-right-\[1\.125rem\]/)
    for (const x of [a, b, c]) expect(x!.className).not.toMatch(/-inset-x-/)
    expect(d!.className).toMatch(/pointer-coarse:before:-inset-x-\[1\.125rem\]/)
  })

  it("跳到出處再跳回原句：原句的連結不被拿出 Tab 順序；不能聚焦的元素只暫時加 tabindex", () => {
    document.body.innerHTML = `<a id="fnref-1" href="#fn-1">1</a><div id="box">x</div>`
    jumpTo("fnref-1")
    expect(document.getElementById("fnref-1")!.hasAttribute("tabindex")).toBe(false)
    expect(document.activeElement?.id).toBe("fnref-1")
    jumpTo("box")
    const box = document.getElementById("box")!
    expect(box.getAttribute("tabindex")).toBe("-1")
    box.blur()
    expect(box.hasAttribute("tabindex")).toBe(false)
  })
})

describe("分頁列", () => {
  it("報告頁上用方向鍵換到「行情」：換頁後焦點在新的分頁上，不會掉到 body", async () => {
    mount({ reports: "public" })
    const router = renderApp("/market/reports/mrp_close_20261111")
    await report()
    const tab = within(await screen.findByRole("tablist", { name: "市場內容" }, T)).getByRole("tab", { name: "報告" })
    tab.focus()
    fireEvent.keyDown(tab, { key: "ArrowLeft" })
    await waitFor(() => expect(router.state.location.pathname).toBe("/market"), T)
    await waitFor(() => expect(document.activeElement?.id).toBe("market-tab-quotes"), T)
  })
})

describe("盲測並排", () => {
  it("只發了資料版的版本不當成看得了：右邊挑看得了的；選到它時寫為什麼，不是錯誤", async () => {
    wide = true
    const { adapter } = mount()
    const trial = await adapter.getAdminReportsTrial()
    const row = trial.reports.find((r) => r.variants.some((v) => v.published === false && v.status === "data_only"))!
    const none = row.variants.find((v) => v.published === false)!.label
    const ok = row.variants.filter((v) => v.published !== false).map((v) => v.label)
    renderApp(`/admin/reports/${row.report_id}?v=${ok[0]}`)
    const groups = await screen.findAllByRole("radiogroup", {}, T)
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["左邊看哪一個版本", "右邊看哪一個版本"])
    expect(within(groups[1]!).getByRole("radio", { name: ok[1]! })).toHaveAttribute("aria-checked", "true")
    fireEvent.click(within(groups[1]!).getByRole("radio", { name: none }))
    expect(await screen.findByText("這個版本沒有 AI 版（只發了資料版或沒有跑完）", {}, T)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /重新載入|重試/ })).toBeNull()
  })

  it("一欄的時候分頁的名稱不寫「左邊」", async () => {
    const { adapter } = mount()
    const trial = await adapter.getAdminReportsTrial()
    renderApp(`/admin/reports/${trial.reports[0]!.report_id}`)
    const [group] = await screen.findAllByRole("radiogroup", {}, T)
    expect(group).toHaveAttribute("aria-label", "看哪一個版本")
  })
})

describe("管理員更正", () => {
  it("報告頁最下面「更正這一份」：寫說明、勾標題，送出後標題換回規則寫的、上面多一行已更正", async () => {
    const { spies } = mount({ reports: "public" })
    renderApp("/market/reports/mrp_premarket_20261111")
    const article = await report()
    expect(article.querySelector("[data-report-title]")!.closest("p")!.className).toMatch(/ai-voice/)
    fireEvent.click(await screen.findByRole("button", { name: "更正這一份" }, T))
    const dialog = await screen.findByRole("dialog", {}, T)
    fireEvent.change(within(dialog).getByLabelText("更正說明"), { target: { value: "標題的日期寫錯" } })
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "標題（換回規則寫的）" }))
    fireEvent.click(within(dialog).getByRole("button", { name: "送出更正" }))
    await waitFor(() => expect(spies.addReportCorrection).toHaveBeenCalledWith("mrp_premarket_20261111", { note: "標題的日期寫錯", drop_sections: ["title"] }), T)
    await waitFor(() => expect(screen.getByText(/標題的日期寫錯/)).toBeInTheDocument(), T)
    await waitFor(() => expect(document.querySelector("[data-report-title]")!.className).not.toMatch(/ai-voice/), T)
  })

  it("一般使用者沒有更正的動作", async () => {
    mount({ reports: "public", discussion: { admin: false } })
    renderApp("/market/reports/mrp_premarket_20261111")
    await report()
    expect(screen.queryByRole("button", { name: "更正這一份" })).toBeNull()
  })
})

describe("群組", () => {
  it("報告公開、週報與盤前推播都開：週報與日報的說明寫併在市場報告裡送", async () => {
    mount({ reports: "public" })
    renderApp("/groups/grp_family?tab=channels")
    const discord = (await screen.findByRole("heading", { name: "Discord" }, T)).closest("section")!
    await within(discord).findByRole("switch", { name: "市場週報（週日 18:00）" }, T)
    expect(within(discord).getByText("群組 AI 週報併在週日 18:00 的市場週報裡送；那天沒有市場週報時，21:30 單獨送。")).toBeInTheDocument()
    expect(within(discord).queryByText("每週六晚上的群組 AI 週報。")).toBeNull()
  })

  it("「昨日你的群組」依伺服器的 prev_session，不用前端推算平日", async () => {
    const { adapter } = mount({ reports: "public", market: "open" })
    const status = await adapter.getMarketReportStatus()
    const pre = status.latest.find((s) => s.kind === "premarket")!
    expect(pre.prev_session).toBe("2026-11-12")
    // 伺服器說前一個交易日是別天（例如中間有休市日）：不叫「昨日」
    vi.spyOn(api, "getMarketReportStatus").mockResolvedValue({ ...status, latest: status.latest.map((s) => (s.kind === "premarket" ? { ...s, prev_session: "2026-11-11" } : s)) })
    renderApp("/groups/grp_family?tab=digests")
    expect(await screen.findByRole("heading", { level: 2, name: "11/12（四） 日報" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { level: 2, name: "昨日你的群組" })).toBeNull()
  })
})
