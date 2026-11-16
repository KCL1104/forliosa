import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { qk } from "@/api/queries"
import type { MarketStatus, TwClose } from "@/api/types"
import { useCloseRefresh } from "../use-close"

/**
 * 收盤價一進來，帳本自己更新（不跳通知；產品負責人 2026-11-16）：`market-status` 的 `tw.closes` 有一個市場的收盤價進來了，
 * 就讓帳本、報價、觀察清單與市場頁重新讀。
 */
const close = (market: TwClose["market"], o: Partial<TwClose> = {}): TwClose => ({
  market, session: "2026-11-16", stored: false, latest: "2026-11-13", interim: false,
  expected_from: "2026-11-16T14:00:00+08:00", expected_to: "2026-11-16T14:30:00+08:00", ...o,
})
const status = (closes: TwClose[]): MarketStatus => ({ tw: { date: "2026-11-16", is_trading_day: true, is_open: false, open: "09:00", close: "13:30", closes } })

afterEach(() => vi.restoreAllMocks())

function setup(first: MarketStatus) {
  let current = first
  vi.spyOn(api, "getMarketStatus").mockImplementation(async () => current)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, "invalidateQueries")
  renderHook(() => useCloseRefresh(), { wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> })
  const next = async (s: MarketStatus) => {
    current = s
    await qc.refetchQueries({ queryKey: qk.marketStatus })
  }
  const invalidated = () => invalidate.mock.calls.map(([f]) => JSON.stringify(f?.queryKey))
  return { qc, next, invalidated, invalidate }
}

describe("useCloseRefresh", () => {
  it("上市的收盤價進來了：帳本、報價、觀察清單、市場頁都重新讀", async () => {
    const t = setup(status([close("TWSE"), close("TPEX")]))
    await waitFor(() => expect(api.getMarketStatus).toHaveBeenCalled())
    // 第一次讀到：不算變（不重新讀）
    await new Promise((r) => setTimeout(r, 20))
    expect(t.invalidate).not.toHaveBeenCalled()
    await t.next(status([close("TWSE", { stored: true, latest: "2026-11-16", expected_from: null, expected_to: null }), close("TPEX")]))
    await waitFor(() => expect(t.invalidated()).toEqual(expect.arrayContaining(['["portfolio"]', '["quote"]', '["watchlist"]', '["market"]'])))
  })

  it("沒有變（只是每分鐘再問一次、或時間窗換了）：不重新讀", async () => {
    const t = setup(status([close("TWSE"), close("TPEX")]))
    await waitFor(() => expect(api.getMarketStatus).toHaveBeenCalled())
    await t.next(status([close("TWSE"), close("TPEX")]))
    await t.next(status([close("TWSE", { expected_from: "2026-11-16T20:30:00+08:00", expected_to: "2026-11-16T23:45:00+08:00" }), close("TPEX")]))
    await new Promise((r) => setTimeout(r, 20))
    expect(t.invalidate).not.toHaveBeenCalled()
  })

  it("舊版後端（沒有 closes）：什麼都不做", async () => {
    const old: MarketStatus = { tw: { date: "2026-11-16", is_trading_day: true, is_open: false, open: "09:00", close: "13:30" } }
    const t = setup(old)
    await waitFor(() => expect(api.getMarketStatus).toHaveBeenCalled())
    await t.next({ tw: { ...old.tw, is_open: true } })
    await new Promise((r) => setTimeout(r, 20))
    expect(t.invalidate).not.toHaveBeenCalled()
  })
})
