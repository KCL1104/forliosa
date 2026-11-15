import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import { api, appToday } from "@/api"
import { useAiRunner } from "@/ai/runner"
import { useAi } from "@/ai/store"
import { usDay } from "@/lib/labels"

/**
 * 用一句話記帳、沒有寫價格：價格用最近的收盤價，成交日和那句說明同一天。
 * 美股的收盤是紐約的交易日（台北已經是隔天），台股照舊是今天。
 */
const reset = () => useAi.setState({ threads: [], drafts: {}, threadId: null, focusDraftId: null })
afterEach(() => act(reset))

function runner() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  return renderHook(() => useAiRunner({ route: "other" }), { wrapper }).result
}
const latestDraft = () => Object.values(useAi.getState().drafts).at(-1)!

describe("AI 草稿的成交日", () => {
  it("美股沒有寫價格與日期：用紐約那一天的收盤價，成交日也是那一天（不是台北的今天）", async () => {
    const quote = await api.getQuote("AAPL")
    expect(quote.trade_date).toBeTruthy()
    expect(quote.trade_date).not.toBe(appToday())
    const r = runner()
    await act(() => r.current.submit("買 AAPL 10 股"))
    const draft = latestDraft()
    expect(draft.notes).toContain(`沒有寫價格，先用 ${usDay(quote.trade_date!)}的收盤價 US$${quote.price.toFixed(2)}。`)
    expect(draft.input).toMatchObject({ symbol: "AAPL", type: "buy", quantity: 10, price: quote.price, trade_date: quote.trade_date })
  })

  it("美股自己寫了日期：照寫的日期", async () => {
    const r = runner()
    await act(() => r.current.submit("11/10 買 AAPL 10 股"))
    expect(latestDraft().input.trade_date).toBe("2026-11-10")
  })

  it("台股沒有寫價格與日期：成交日是今天", async () => {
    const r = runner()
    await act(() => r.current.submit("買 2330 1 張"))
    const draft = latestDraft()
    expect(draft.notes.some((n) => n.startsWith("沒有寫價格，先用最近收盤價"))).toBe(true)
    expect(draft.input).toMatchObject({ symbol: "2330.TW", type: "buy", trade_date: appToday() })
  })
})
