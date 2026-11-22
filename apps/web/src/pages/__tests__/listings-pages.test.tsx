import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { useAi } from "@/ai/store"
import { useUi } from "@/app/ui-store"
import { createAppRouter } from "@/router"

/**
 * 商品清單補上全部台股 ETF 與 SEC 的美股（待決定事項 1-4、1-5）：搜尋結果的美股只標「美股」（收盤價關著時「美股・沒有報價」），
 * 只有英文名的美股（MSFT）與收盤檔裡的 ETF（00981A）個股頁都打得開。
 * 美股的收盤（Databento，產品負責人 2026-11-15）只抓有人觀察或持有的代號：還沒加入的照實說加入後會補上。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null })
beforeEach(() => act(resetAi))
afterEach(() => {
  cleanup()
  act(resetAi)
  // 搜尋框的開關在模組層級的 store：上一個測試開著沒關的話，下一頁整個被對話框蓋住（aria-hidden）
  act(() => useUi.getState().setSearchOpen(false))
  vi.restoreAllMocks()
})

/** 後端有沒有在提供美股收盤：`/meta/attributions` 有沒有 Databento 的收盤（後端關掉時整筆不列） */
const US_PRICE_KEY = "databento-equs/price"
function usCloses(served: boolean) {
  const get = api.getAttributions
  vi.spyOn(api, "getAttributions").mockImplementation(async () => {
    const a = await get()
    const rest = a.datasets.filter((d) => d.key !== US_PRICE_KEY)
    const databento = {
      key: US_PRICE_KEY, agency: "Databento", dataset: "US Equities Summary（EQUS.SUMMARY，Nasdaq NLS Plus 官方合併收盤）", url: "https://databento.com/",
      used_for: "美股收盤價", year: 2026, license: "Databento", license_url: "https://databento.com/", commercial: true,
      attribution: "Databento〈US Equities Summary（EQUS.SUMMARY，Nasdaq NLS Plus 官方合併收盤）〉（2026），資料由 Databento 提供",
    }
    return { ...a, datasets: served ? [...rest, databento] : rest }
  })
}

const T = { timeout: 8000 }
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

describe("搜尋：美股收盤價開著時美股只標「美股」，關著時標「美股・沒有報價」；收盤檔的 ETF 搜得到", () => {
  it("輸入 tsla（還沒抓過收盤）：開著時 has_quote 一律 true，那一列只寫「美股」——還沒有收盤價只在個股頁價格那一格說；按下去打開個股頁", async () => {
    usCloses(true)
    const user = userEvent.setup()
    const router = renderApp("/")
    await user.click(await screen.findByRole("button", { name: "搜尋股票" }, T))
    const dialog = await screen.findByRole("dialog", { name: "搜尋股票與功能" }, T)
    await user.type(within(dialog).getByRole("combobox"), "tsla")
    const hit = await within(dialog).findByRole("option", { name: /TSLA/ }, T)
    expect(hit.textContent).toContain("Tesla, Inc.")
    expect(hit.textContent).toMatch(/美股$/)
    expect(hit.textContent).not.toMatch(/還沒有收盤價|沒有報價/)
    await user.click(hit)
    await waitFor(() => expect(router.state.location.pathname).toBe("/stock/TSLA"))
  })

  it("美股收盤價關著（後端的美股 has_quote=false）：寫「美股・沒有報價」，不寫「還沒有收盤價」（不承諾會補上）", async () => {
    usCloses(false)
    const search = api.searchInstruments
    vi.spyOn(api, "searchInstruments").mockImplementation(async (q) => (await search(q)).map((i) => (i.market === "US" ? { ...i, has_quote: false } : i)))
    const user = userEvent.setup()
    renderApp("/")
    await user.click(await screen.findByRole("button", { name: "搜尋股票" }, T))
    const dialog = await screen.findByRole("dialog", { name: "搜尋股票與功能" }, T)
    await user.type(within(dialog).getByRole("combobox"), "tsla")
    const hit = await within(dialog).findByRole("option", { name: /TSLA/ }, T)
    await waitFor(() => expect(hit.textContent).toContain("美股・沒有報價"))
    expect(hit.textContent).not.toContain("還沒有收盤價")
  })

  it("輸入 00981：主動式 ETF 那一列寫「上市・ETF」", async () => {
    const user = userEvent.setup()
    renderApp("/")
    await user.click(await screen.findByRole("button", { name: "搜尋股票" }, T))
    const dialog = await screen.findByRole("dialog", { name: "搜尋股票與功能" }, T)
    await user.type(within(dialog).getByRole("combobox"), "00981")
    const hit = await within(dialog).findByRole("option", { name: /00981A/ }, T)
    expect(hit.textContent).toContain("主動統一台股增長")
    expect(hit.textContent).toContain("上市・ETF")
  })
})

describe("個股頁", () => {
  it("MSFT（SEC 代號表，只有英文名、沒有人觀察）：顯示名稱與「還沒有收盤價」，照實說加入觀察或記進帳本後會補上", async () => {
    usCloses(true)
    renderApp("/stock/MSFT")
    expect(await screen.findByText("還沒有收盤價", undefined, T)).toBeInTheDocument()
    expect((await screen.findAllByText("MICROSOFT CORP", undefined, T)).length).toBeGreaterThan(0)
    expect(await screen.findByText(/^美股要在觀察清單或帳本裡才會抓收盤價。加入後約 10 分鐘內補上/, undefined, T)).toBeInTheDocument()
    // 舊的說法（美股沒有報價、持股照成本算）不再出現；走勢圖整塊不放
    expect(document.body.textContent).not.toMatch(/美股沒有報價|持股照成本算/)
    expect(screen.queryByRole("region", { name: "走勢圖" })).toBeNull()
  })

  it("加入觀察之後：改說會補上，不再教人加入", async () => {
    usCloses(true)
    const user = userEvent.setup()
    renderApp("/stock/MSFT")
    await screen.findByText("還沒有收盤價", undefined, T)
    try {
      await user.click(await screen.findByRole("button", { name: "加入觀察" }, T))
      expect(await screen.findByText("收盤價約 10 分鐘內補上，從 2024/07/01 起。", undefined, T)).toBeInTheDocument()
      expect(screen.queryByText(/要在觀察清單或帳本裡/)).toBeNull()
    } finally {
      // mock 的觀察清單在這個檔案裡是共用的：還原
      await api.removeWatch("MSFT")
    }
  })

  it("後端關掉美股收盤時（顯名清單沒有 Databento）：只寫「沒有報價」，不承諾會補上", async () => {
    usCloses(false)
    renderApp("/stock/MSFT")
    await screen.findAllByText("MICROSOFT CORP", undefined, T)
    await waitFor(() => expect(screen.getByText("沒有報價")).toBeInTheDocument())
    expect(screen.queryByText(/補上/)).toBeNull()
  })

  it("00981A（收盤檔的 ETF）：有收盤價", async () => {
    renderApp("/stock/00981A.TW")
    expect((await screen.findAllByText("主動統一台股增長", undefined, T)).length).toBeGreaterThan(0)
    expect(screen.queryByText("沒有報價")).toBeNull()
  })
})

describe("資料來源頁：存檔開始以前的歷史日線不寫廠商名（產品負責人 2026-11-22）", () => {
  it("後端開著回補時：寫「非官方」，沒有 Yahoo 的名字，也沒有連到它的網站或條款", async () => {
    const get = api.getAttributions
    vi.spyOn(api, "getAttributions").mockImplementation(async () => {
      const a = await get()
      const history = {
        key: "yahoo-history", agency: "非官方資料", dataset: "存檔開始以前的歷史日線", url: null, used_for: "走勢圖",
        year: 2026, license: "非官方資料", license_url: null, commercial: false, attribution: "存檔開始以前的歷史日線（非官方資料）",
      }
      return { ...a, datasets: [...a.datasets, history] }
    })
    const user = userEvent.setup()
    renderApp("/data-sources?auth=signed-in")
    expect(await screen.findByText(/用的是非官方的歷史日線/, undefined, T)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /^非官方資料/ }))
    expect(screen.getByText("存檔開始以前的歷史日線（非官方資料）")).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/Yahoo Finance/)
    expect([...document.querySelectorAll("a")].some((el) => /yahoo/i.test(el.getAttribute("href") ?? ""))).toBe(false)
  })
})
