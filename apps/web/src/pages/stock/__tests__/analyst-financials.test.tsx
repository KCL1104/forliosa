import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { AnalystViewsCard } from "../AnalystViews"
import { FinancialsTab } from "../tabs/FinancialsTab"

/** Link 需要 router：只有一個根路由（產生的網址照樣是 /stock/…?tab=events） */
function renderInRouter(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}

const T = { timeout: 8000 }

beforeAll(() => {
  // 路由換頁時會捲到頂端；jsdom 沒有
  window.scrollTo = () => {}
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// 第一次載入 mock adapter 與路由比較慢：給長一點的時間
describe("法人觀點：查無報導／查不到時的下一步", { timeout: 20_000 }, () => {
  const disclaimer = "以下為媒體報導的第三方觀點，非 Forliosa 建議。"

  it("近期查無法人報導：一個「看公告」連到事件分頁（常駐底線的文字連結，觸控 44px）", async () => {
    vi.spyOn(api, "getAnalystViews").mockResolvedValue({ status: "ready", symbol: "2881.TW", as_of: "2026-11-12T09:12:00+08:00", items: [], disclaimer, notes: [] })
    const inst = await api.getInstrument("2881.TW")
    renderInRouter(<AnalystViewsCard inst={inst} />)
    fireEvent.click(await screen.findByRole("button", { name: /法人觀點/ }, T))
    await screen.findAllByText("近期查無法人報導", undefined, T)
    const link = screen.getByRole("link", { name: "看公告" })
    expect(link.getAttribute("href")).toBe("/stock/2881.TW?tab=events")
    expect(link.className).toMatch(/\bunderline\b/)
    expect(link.className).toMatch(/\bpointer-coarse:min-h-11\b/)
    // 只有一個動作：不另外放「問 AI」或「再查一次」
    expect(screen.queryByRole("button", { name: /問 AI|查詢近期法人觀點|再試一次/ })).toBeNull()
  })

  it("法人觀點暫時查不到：同一個「看公告」", async () => {
    vi.spyOn(api, "getAnalystViews").mockResolvedValue({ status: "unavailable", symbol: "2409.TW", disclaimer, notes: [] })
    const inst = await api.getInstrument("2409.TW")
    renderInRouter(<AnalystViewsCard inst={inst} />)
    fireEvent.click(await screen.findByRole("button", { name: /法人觀點/ }, T))
    await screen.findByText("法人觀點暫時查不到，稍後再打開看看。", undefined, T)
    expect(screen.getByRole("link", { name: "看公告" }).getAttribute("href")).toBe("/stock/2409.TW?tab=events")
  })

  it("有結果時沒有「看公告」", async () => {
    const inst = await api.getInstrument("2330.TW")
    renderInRouter(<AnalystViewsCard inst={inst} />)
    fireEvent.click(await screen.findByRole("button", { name: /法人觀點/ }, T))
    await screen.findByRole("table", { name: "法人觀點" }, T)
    expect(screen.queryByRole("link", { name: "看公告" })).toBeNull()
  })
})

describe("財報表：手機上一打開就看到最新一期", { timeout: 20_000 }, () => {
  it("捲到最右邊（最新一期），項目欄固定在左邊；換成年報也一樣", async () => {
    // jsdom 不排版：給捲動容器一個比內容窄的寬度
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(560)
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(343)
    const inst = await api.getInstrument("2330.TW")
    renderInRouter(<FinancialsTab inst={inst} />)
    const head = await screen.findByRole("columnheader", { name: "項目" }, T)
    const scroller = head.closest("table")!.parentElement!
    await waitFor(() => expect(scroller.scrollLeft).toBe(560 - 343))
    expect(head.className).toMatch(/\bsticky\b/)
    expect(head.className).toMatch(/\bleft-0\b/)
    expect(screen.getByRole("rowheader", { name: "EPS" }).className).toMatch(/\bsticky\b/)
    // 有數字捲到固定欄底下：容器標 data-scrolled（固定欄右邊多一條格線）
    expect(scroller).toHaveAttribute("data-scrolled")
    // 使用者往回捲：不會被拉回去，直到換期間
    scroller.scrollLeft = 0
    fireEvent.scroll(scroller)
    expect(scroller).not.toHaveAttribute("data-scrolled")
    expect(scroller.scrollLeft).toBe(0)
    fireEvent.click(screen.getByRole("radio", { name: "年" }))
    await waitFor(() => {
      const again = screen.getByRole("columnheader", { name: "項目" }).closest("table")!.parentElement!
      expect(again.scrollLeft).toBe(560 - 343)
    }, T)
  })
})
