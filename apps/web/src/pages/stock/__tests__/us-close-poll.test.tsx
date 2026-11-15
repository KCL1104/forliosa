import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api, ApiError } from "@/api"
import type { Position, Quote } from "@/api/types"
import { createAppRouter } from "@/router"

/**
 * 個股頁等美股收盤價補上（UsNoClose）：已經持有的每分鐘再問一次報價。
 * - 報價從 404 變成有資料：部位（以及整個 `["portfolio"]`）重抓，重抓完成前不顯示以成本算的舊未實現與今日
 * - 問了 30 分鐘還沒有就停，不再說「約 10 分鐘內補上」
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
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const T = { timeout: 8000 }
const MINUTE = 60_000
function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}
/** 讓每分鐘的計時器跑一輪，並等 React 把結果畫出來 */
const tick = (ms = MINUTE) => act(async () => void vi.advanceTimersByTime(ms))

/** 剛記進帳本的 MSFT：還沒有收盤價時以成本計值（未實現 0、今日 0） */
const atCost: Position = {
  quantity: 10, avg_cost: 500, cost_basis: 160_000, market_value: 160_000, unrealized_pnl: 0, unrealized_pnl_pct: 0,
  realized_pnl: 0, dividends_received: 0, day_change: 0, markers: [], upcoming_dividend: null, currency: "USD",
}
/** 收盤價補上之後：以收盤價計值 */
const priced: Position = { ...atCost, market_value: 166_400, unrealized_pnl: 6_400, unrealized_pnl_pct: 0.04, day_change: 3_200 }
const msftClose: Quote = {
  symbol: "MSFT", price: 520, prev_close: 510, change: 10, change_pct: 0.0196, open: 512, high: 522, low: 511, volume: 20_000_000,
  as_of: "2026-11-12T05:00:00+08:00", trade_date: "2026-11-11", is_realtime: false, is_demo: false, source: "databento-equs",
  reference_price: null, limit_up: null, limit_down: null,
}
const notFound = () => Promise.reject(new ApiError(404, "not_found", "沒有報價"))

describe("個股頁：美股收盤價補上之前與之後", () => {
  it("報價先 404（打開時與第一次再問），第二次再問有價格：部位重抓，重抓完成前不顯示舊的未實現，完成後是新的金額", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    // 收盤價補上了沒有（後端回補完成）：之前 /quote 一律 404
    let backfilled = false
    const getQuote = api.getQuote
    const quoteSpy = vi.spyOn(api, "getQuote").mockImplementation((symbol) => (symbol !== "MSFT" ? getQuote(symbol) : backfilled ? Promise.resolve(msftClose) : notFound()))
    // 收盤價補上以後讀部位：先不回，看重抓期間畫面上有什麼
    let release: (p: Position) => void = () => {}
    const refetched = new Promise<Position>((r) => (release = r))
    let positionAfter = 0
    vi.spyOn(api, "getPosition").mockImplementation((symbol) => {
      if (symbol !== "MSFT") return Promise.resolve(null)
      if (!backfilled) return Promise.resolve(atCost)
      positionAfter += 1
      return refetched
    })
    const quoteCalls = () => quoteSpy.mock.calls.filter(([s]) => s === "MSFT").length

    renderApp("/stock/MSFT")
    expect(await screen.findByText("還沒有收盤價", undefined, T)).toBeInTheDocument()
    expect(await screen.findByText("收盤價約 10 分鐘內補上，從 2024/07/01 起。", undefined, T)).toBeInTheDocument()
    const position = await screen.findByRole("region", { name: /的部位$/ }, T)
    expect(within(position).queryByText("未實現")).toBeNull()

    // 第一次再問：還是 404。再問的時候整頁不閃成「—」或以成本算的未實現
    const before = quoteCalls()
    await tick()
    await waitFor(() => expect(quoteCalls()).toBe(before + 1))
    expect(screen.getByText("還沒有收盤價")).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: /的部位$/ })).queryByText("未實現")).toBeNull()

    // 第二次再問：有價格了
    backfilled = true
    await tick()
    await screen.findByText("11/11 收盤（美東）", undefined, T)
    // 報價補上了：部位跟著重抓；重抓完成前不顯示以成本算的「未實現 NT$0」「11/11 NT$0」
    await waitFor(() => expect(positionAfter).toBeGreaterThan(0))
    expect(within(screen.getByRole("region", { name: /的部位$/ })).queryByText("未實現")).toBeNull()
    expect(screen.queryByText("還沒有收盤價")).toBeNull()

    await act(async () => release(priced))
    const block = screen.getByRole("region", { name: /的部位$/ })
    await waitFor(() => expect(within(block).getByText("未實現")).toBeInTheDocument())
    expect(block.textContent).toContain("+NT$6,400")
    expect(block.textContent).toContain("+NT$3,200")
    expect(block.textContent).not.toMatch(/以成本計/)
  })

  it("問了 30 分鐘還沒有收盤價：停止每分鐘再問，不再說「約 10 分鐘內補上」", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const getQuote = api.getQuote
    const spy = vi.spyOn(api, "getQuote").mockImplementation((symbol) => (symbol === "MSFT" ? notFound() : getQuote(symbol)))
    vi.spyOn(api, "getPosition").mockImplementation((symbol) => Promise.resolve(symbol === "MSFT" ? atCost : null))
    const calls = () => spy.mock.calls.filter(([s]) => s === "MSFT").length

    renderApp("/stock/MSFT")
    expect(await screen.findByText("收盤價約 10 分鐘內補上，從 2024/07/01 起。", undefined, T)).toBeInTheDocument()
    const before = calls()
    for (let i = 0; i < 29; i++) await tick()
    // 每分鐘問一次（整頁沒有因為再問而重新掛上，計時不會重來）
    await waitFor(() => expect(calls()).toBe(before + 29))
    expect(screen.getByText("收盤價約 10 分鐘內補上，從 2024/07/01 起。")).toBeInTheDocument()

    await tick()
    expect(await screen.findByText("暫時抓不到這檔的收盤價。", undefined, T)).toBeInTheDocument()
    expect(screen.queryByText(/10 分鐘內補上/)).toBeNull()
    expect(screen.getByText("還沒有收盤價")).toBeInTheDocument()
    const asked = calls()
    expect(asked).toBe(before + 30)
    await tick(10 * MINUTE)
    expect(calls()).toBe(asked)
  })
})
