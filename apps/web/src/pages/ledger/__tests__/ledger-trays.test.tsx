import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"

/**
 * 帳本的托盤（內頁重新設計，產品負責人 2026-11-21 選方向 C「圓桌」的結構、不要它的旁白）：
 * 總資產 → 持倉（已出清在同一盤）→（手機）總資產走勢 → 今日損益 → 分享卡＋觀察清單 → 本週事項。
 * 頁面只有標籤和數字：沒有頁首的一句話、標題是名詞、沒有說話人。測試環境是手機的版面（matchMedia 一律 false）。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(() => usePrefs.setState({ privacyMode: false }))
})

const T = { timeout: 8000 }

function renderLedger(path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

const trayNames = () => [...document.querySelectorAll<HTMLElement>("section.tray")].map((s) => s.querySelector("h2")!.textContent)

describe("帳本的托盤", { timeout: 20_000 }, () => {
  it("順序：總資產 → 持倉 → 總資產走勢（手機）→ 今日損益 → 分享卡 → 觀察清單 → 本週事項；相鄰的托盤不同色", async () => {
    renderLedger()
    await screen.findByRole("list", { name: "觀察清單" }, T)
    await screen.findByRole("region", { name: "分享卡" }, T)
    await screen.findByRole("region", { name: "本週事項" }, T)
    expect(trayNames()).toEqual(["總資產", "持倉", "總資產走勢", "今日損益", "分享卡", "觀察清單", "本週事項"])
    const tints = [...document.querySelectorAll<HTMLElement>("section.tray")].map((s) => s.dataset.tint)
    for (let i = 1; i < tints.length; i++) expect(tints[i]).not.toBe(tints[i - 1])
    // 已出清在持倉那一盤裡（不另外一盤）
    expect(await within(screen.getByRole("region", { name: "持倉" })).findByText("已出清", undefined, T)).toBeInTheDocument()
  })

  it("沒有頁首的一句話、沒有說話人；總資產那一行寫「收盤價・11/12（四）」", async () => {
    renderLedger()
    const hero = await screen.findByRole("region", { name: "總資產" }, T)
    expect(await within(hero).findByText("收盤價・", { exact: false }, T)).toBeInTheDocument()
    expect(hero.textContent).toMatch(/收盤價・11\/12（四）/)
    const main = document.body.textContent ?? ""
    expect(main).not.toMatch(/今天帳本|大多來自|Forliosa：|收盤後整理|幫你寫好了/)
  })

  it("今日損益：由賺最多排到賠最多、金額帶正負號；meta 分開寫台股與美股的日期（美股寫美東，不說今天）", async () => {
    const holdings = (await api.getHoldings()).filter((h) => h.price !== null)
    renderLedger()
    const tray = await screen.findByRole("region", { name: /損益$/ }, T)
    const rows = within(tray).getAllByRole("listitem")
    const expected = [...holdings].sort((a, b) => b.day_change - a.day_change)
    expect(rows).toHaveLength(expected.length)
    expect(rows[0]).toHaveTextContent(expected[0]!.name)
    expect(rows.at(-1)).toHaveTextContent(expected.at(-1)!.name)
    const meta = tray.querySelector("header p")!.textContent!
    if (holdings.some((h) => h.market === "US") && holdings.some((h) => h.market !== "US")) expect(meta).toMatch(/^台股 \d+\/\d+・美股 \d+\/\d+（美東）$/)
    expect(tray.textContent).not.toMatch(/今天/)
  })

  it("隱私模式：今日損益的金額遮起來，橫條照畫", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderLedger()
    const tray = await screen.findByRole("region", { name: /損益$/ }, T)
    expect(tray.textContent).not.toMatch(/NT\$\d/)
    expect(tray.querySelectorAll("[data-bar]").length).toBeGreaterThan(0)
  })

  it("分享卡：只有百分比，沒有說明句；「複製分享文字」在標題列", async () => {
    renderLedger()
    const card = await screen.findByRole("region", { name: "分享卡" }, T)
    expect(card.textContent).not.toMatch(/只有百分比|沒有金額|NT\$/)
    expect(within(card.querySelector("header")!).getByRole("button", { name: "複製分享文字" })).toBeInTheDocument()
  })

  it("一檔都沒有收盤價時沒有今日損益那一盤", async () => {
    const real = api.getHoldings.bind(api)
    vi.spyOn(api, "getHoldings").mockImplementation(async (...args) => (await real(...args)).map((h) => ({ ...h, price: null })))
    renderLedger()
    await screen.findByRole("list", { name: "觀察清單" }, T)
    expect(screen.queryByRole("region", { name: /損益$/ })).toBeNull()
  })
})
