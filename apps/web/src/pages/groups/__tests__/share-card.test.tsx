import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { createAppRouter } from "@/router"

/**
 * 群組頁的分享卡（今日、本月、總報酬）：本月用到存檔開始以前的 Yahoo 參考價時（產品負責人 2026-11-18），
 * 卡片下面寫後端那一句，複製到 LINE 的文字也在本月後面標上；本月都是官方收盤時都不寫（2026-11-18 審查）。
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
})

const T = { timeout: 8000 }
const NOTE = "2026/11/11 以前用 Yahoo 參考價計算，不是官方資料"

function renderGroups() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: ["/groups"] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

/** 本月（MTD）的回應換成用到參考價的版本 */
function monthWithReference(on: boolean) {
  const real = api.getPerformance.bind(api)
  vi.spyOn(api, "getPerformance").mockImplementation(async (q) => {
    const p = await real(q)
    if (q.range !== "MTD") return p
    return on ? { ...p, twr: 0.0321, reference_until: "2026-11-11", notes: [NOTE] } : { ...p, twr: 0.0321, reference_until: null, notes: [] }
  })
}

describe("分享卡的本月用到 Yahoo 參考價", { timeout: 20_000 }, () => {
  it("卡片下面寫那一句，分享文字的本月後面標上", async () => {
    monthWithReference(true)
    renderGroups()
    const card = (await screen.findByRole("heading", { name: "分享卡" }, T)).closest("section")!
    expect(await within(card).findByText(NOTE, undefined, T)).toBeInTheDocument()
    expect(await within(card).findByText(/本月 .+3\.21%（11\/11 以前用 Yahoo 參考價），總報酬/, undefined, T)).toBeInTheDocument()
  })

  it("本月都是官方收盤：不寫", async () => {
    monthWithReference(false)
    renderGroups()
    const card = (await screen.findByRole("heading", { name: "分享卡" }, T)).closest("section")!
    expect(await within(card).findByText(/本月 .+3\.21%，總報酬/, undefined, T)).toBeInTheDocument()
    expect(within(card).queryByText(/Yahoo/)).toBeNull()
  })
})
