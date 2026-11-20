import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import { api } from "@/api"
import { DraftCard } from "@/ai/DraftCard"
import type { Draft } from "@/ai/types"
import { formatPercent, formatPrice } from "@/lib/format"

/**
 * 草稿卡（內頁重新設計 2026-11-21）：
 * - 右上角「草稿」標記，卡片前面不寫「幫你寫好了」這類句子（簽名後拿掉標記）
 * - 買賣一定有手續費那一格（賣出多一格交易稅）：沒填寫「沒填」，填了寫金額
 * - 成交價和那天的收盤價差 10% 以上時多一行事實「比 11/12 收盤價 72.40 低 27.6%」，不寫建議
 */
afterEach(cleanup)
const T = { timeout: 8000 }

function draft(p: Partial<Draft["input"]> = {}, status: Draft["status"] = "pending"): Draft {
  return {
    id: "dft_test",
    status,
    input: { account_id: "acc_1", symbol: "0050.TW", type: "buy", trade_date: "2026-11-12", quantity: 2000, price: 52.4, ...p },
    instrument: { symbol: "0050.TW", code: "0050", name: "元大台灣50", market: "TWSE", currency: "TWD" },
    preview: { gross: 104800, fee: 0, tax: 0, health_insurance: 0, net_cash: -104800, rules: [] },
    notes: [],
    createdAt: "2026-11-12T14:00:00+08:00",
  }
}

function renderCard(d: Draft) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DraftCard draft={d} onSign={() => {}} onUndo={() => {}} onRevise={() => {}} onDiscard={() => {}} />
    </QueryClientProvider>,
  )
}

describe("草稿卡：手續費、和收盤價差很多、草稿標記", { timeout: 20_000 }, () => {
  it("買進的價格比那天的收盤價低很多：多一行「比 11/12 收盤價 72.40 低 27.6%」；手續費沒填寫「沒填」；右上角是「草稿」", async () => {
    const close = (await api.getDailyClose("0050.TW", "2026-11-12")).close!
    expect(close).toBeGreaterThan(52.4 / 0.9)
    renderCard(draft())
    const card = screen.getByRole("article")
    const line = await within(card).findByText(/^比 11\/12 收盤價/, undefined, T)
    expect(line).toHaveTextContent(`比 11/12 收盤價 ${formatPrice(close, "TWSE")} 低 ${formatPercent(1 - 52.4 / close, { decimals: 1, signed: false })}`)
    // 只有事實，沒有建議
    expect(line.textContent).not.toMatch(/確認|打錯|建議|請/)
    const fee = within(card).getByText("手續費").closest("div")!
    expect(fee).toHaveTextContent("手續費沒填")
    expect(within(card).queryByText("交易稅")).toBeNull()
    expect(within(card).getByText("草稿")).toHaveAttribute("aria-hidden", "true")
    expect(within(card).getByRole("heading")).toHaveTextContent("草稿，尚未入帳")
    expect(card.textContent).not.toMatch(/幫你|寫好了/)
  })

  it("價格和收盤價差不到 10%：不多寫；填了手續費寫金額", async () => {
    const close = (await api.getDailyClose("0050.TW", "2026-11-12")).close!
    renderCard(draft({ price: close * 1.05, fee: 20 }))
    const card = screen.getByRole("article")
    // 等收盤價的查詢回來
    await new Promise((r) => setTimeout(r, 300))
    expect(within(card).queryByText(/^比 .*收盤/)).toBeNull()
    expect(within(card).getByText("手續費").closest("div")).toHaveTextContent(/手續費20/)
  })

  it("賣出：手續費與交易稅兩格；簽名後沒有「草稿」標記、也不再寫差多少", async () => {
    renderCard(draft({ type: "sell", fee: null, tax: null }))
    const card = screen.getByRole("article")
    expect(within(card).getByText("手續費").closest("div")).toHaveTextContent("手續費沒填")
    expect(within(card).getByText("交易稅").closest("div")).toHaveTextContent("交易稅沒填")
    cleanup()
    renderCard(draft({}, "signed"))
    const signed = screen.getByRole("article")
    expect(within(signed).queryByText("草稿")).toBeNull()
    await new Promise((r) => setTimeout(r, 300))
    expect(within(signed).queryByText(/^比 .*收盤/)).toBeNull()
  })
})
