import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { qk } from "@/api/queries"
import { useAiRunner } from "@/ai/runner"
import { useAi } from "@/ai/store"

/**
 * 「股利入帳」：AI 面板在每一頁只讀定期定額扣款（API 速度 2026-11-17），完整的本週事項沒讀過時，按下去才讀，
 * 美股的入帳一樣會提出來。
 */
const reset = () => useAi.setState({ threads: [], drafts: {}, threadId: null, focusDraftId: null })
afterEach(() => {
  act(reset)
  vi.restoreAllMocks()
})

function runner(qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  return renderHook(() => useAiRunner({ route: "other" }), { wrapper }).result
}

const AAPL = { date: "2026-11-19", type: "dividend_payment", symbol: "AAPL", title: "Apple 現金股利入帳", amount_estimate: 812.4, is_demo: false, sources: [] }

const lastAi = () => useAi.getState().threads[0]?.messages.filter((m) => m.role === "ai").at(-1)

describe("股利入帳", () => {
  it("本週事項還沒讀過：這時才讀，美股的入帳照樣提出來", async () => {
    const upcoming = vi.spyOn(api, "getUpcoming").mockResolvedValue([
      { date: "2026-11-19", type: "dividend_payment", symbol: "AAPL", title: "Apple 現金股利入帳", amount_estimate: 812.4, is_demo: false, sources: [] },
      { date: "2026-11-19", type: "dividend_payment", symbol: "2330.TW", title: "台積電 現金股利入帳", amount_estimate: 7000, is_demo: false, sources: [] },
    ] as never)
    const r = runner()
    act(() => r.current.action("dividend"))
    await waitFor(() => expect(lastAi()?.answer?.followUps).toEqual(["Apple 配息 812"]))
    expect(upcoming).toHaveBeenCalledWith(7)
  })

  it("帳本頁剛讀過的本週事項：直接用，不再讀一次", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(qk.upcoming(7), [AAPL])
    const upcoming = vi.spyOn(api, "getUpcoming").mockResolvedValue([] as never)
    const r = runner(qc)
    act(() => r.current.action("dividend"))
    await waitFor(() => expect(lastAi()?.answer?.followUps).toEqual(["Apple 配息 812"]))
    expect(upcoming).not.toHaveBeenCalled()
  })

  it("記了交易之後（本週事項失效、沒有頁面在看）：重讀，不提已經賣掉的持股", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(qk.upcoming(7), [AAPL])
    await act(() => qc.invalidateQueries({ queryKey: ["portfolio"] }))  // 例如在個股頁用 AI 草稿賣掉 AAPL
    const upcoming = vi.spyOn(api, "getUpcoming").mockResolvedValue([] as never)
    const r = runner(qc)
    act(() => r.current.action("dividend"))
    await waitFor(() => expect(lastAi()?.answer?.text).toContain("股利"))
    expect(upcoming).toHaveBeenCalledWith(7)
    expect(lastAi()?.answer?.followUps ?? []).toEqual([])
  })

  it("讀不到本週事項：照樣回答，只是不提入帳", async () => {
    vi.spyOn(api, "getUpcoming").mockRejectedValue(new Error("offline"))
    const r = runner()
    act(() => r.current.action("dividend"))
    await waitFor(() => expect(lastAi()?.answer?.text).toContain("股利"))
    expect(lastAi()?.answer?.followUps ?? []).toEqual([])
  })
})
