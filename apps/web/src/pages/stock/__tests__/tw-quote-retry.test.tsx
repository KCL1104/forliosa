import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api, ApiError } from "@/api"
import type { Quote } from "@/api/types"
import { formatPrice } from "@/lib/format"
import { createAppRouter } from "@/router"

// 走勢圖（lightweight-charts）在 jsdom 沒有 canvas 可以畫：換成一個看得到有沒有放的記號
vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => <div data-testid="price-chart" /> }))

/**
 * 台股個股頁第一次讀報價就遇到暫時的錯誤（後端重啟的 503、網路斷了）：先寫「沒有報價」，之後每分鐘再問一次，
 * 恢復了整頁自己換成有價格的樣子。4xx（真的沒有報價）不再問。
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
const tick = (ms = MINUTE) => act(async () => void vi.advanceTimersByTime(ms))

describe("台股個股頁：報價暫時讀不到", () => {
  it("第一次（含重試）都是 503：寫「沒有報價」；下一分鐘再問、恢復了就換成價格，再問的時候不閃", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const getQuote = api.getQuote
    const real = await getQuote("2330.TW")
    let down = true
    const pending: ((q: Quote) => void)[] = []
    const spy = vi.spyOn(api, "getQuote").mockImplementation((symbol) => {
      if (symbol !== "2330.TW") return getQuote(symbol)
      if (down) return Promise.reject(new ApiError(503, "service_unavailable", "暫時無法使用"))
      return new Promise<Quote>((r) => pending.push(r))
    })
    const calls = () => spy.mock.calls.filter(([s]) => s === "2330.TW").length

    renderApp("/stock/2330.TW")
    // 第一次加兩次重試（1 秒、2 秒後）都失敗：沒有報價，走勢圖不放
    await waitFor(() => expect(calls()).toBeGreaterThanOrEqual(3), T)
    expect(await screen.findByText("沒有報價", undefined, T)).toBeInTheDocument()
    await tick(5000)
    expect(screen.queryByTestId("price-chart")).toBeNull()
    const before = calls()

    // 後端恢復；下一分鐘再問。回來以前整頁還是「沒有報價」，不閃成「—」或走勢圖
    down = false
    await tick()
    await waitFor(() => expect(calls()).toBeGreaterThan(before), T)
    expect(screen.getByText("沒有報價")).toBeInTheDocument()
    expect(screen.queryByTestId("price-chart")).toBeNull()

    await act(async () => pending.forEach((r) => r(real)))
    await waitFor(() => expect(screen.queryByText("沒有報價")).toBeNull(), T)
    const ref = real.reference_price ?? real.prev_close
    expect(document.body.textContent).toContain(`參考價 ${formatPrice(ref, "TWSE")}`)
    expect(screen.getByTestId("price-chart")).toBeInTheDocument()
  }, 20_000)

  it("404（真的沒有報價）：寫「沒有報價」，不重試也不再問", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const getQuote = api.getQuote
    const spy = vi.spyOn(api, "getQuote").mockImplementation((symbol) =>
      symbol === "2330.TW" ? Promise.reject(new ApiError(404, "not_found", "沒有報價")) : getQuote(symbol),
    )
    const calls = () => spy.mock.calls.filter(([s]) => s === "2330.TW").length

    renderApp("/stock/2330.TW")
    expect(await screen.findByText("沒有報價", undefined, T)).toBeInTheDocument()
    await tick(5000)
    const asked = calls()
    await tick(10 * MINUTE)
    expect(calls()).toBe(asked)
  })
})
