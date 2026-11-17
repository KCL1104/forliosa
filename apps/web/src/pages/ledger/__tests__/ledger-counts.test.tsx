import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { useLedgerCounts } from "../use-ledger-counts"

/**
 * 「紀錄」分頁上的筆數（API 速度 2026-11-17）：一支 `GET /transactions/counts`，不再依序讀 3 頁交易來數。
 * 超過 500 筆時和之前一樣不寫數字。
 */
function counts() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  return renderHook(() => useLedgerCounts(), { wrapper }).result
}

afterEach(() => vi.restoreAllMocks())

describe("帳本分段上的筆數", () => {
  it("一支計數端點，不讀交易清單", async () => {
    const list = vi.spyOn(api, "listTransactions")
    vi.spyOn(api, "getTransactionCounts").mockResolvedValue({ transactions: 42, dividends: 7, by_type: { buy: 35, cash_dividend: 7 } })
    const r = counts()
    await waitFor(() => expect(r.current.transactions).toBe(42))
    expect(r.current.dividends).toBe(7)
    expect(list).not.toHaveBeenCalled()
  })

  it("超過 500 筆：兩個都不寫數字（和之前一樣）", async () => {
    vi.spyOn(api, "getTransactionCounts").mockResolvedValue({ transactions: 501, dividends: 30, by_type: { buy: 471, cash_dividend: 30 } })
    const r = counts()
    await waitFor(() => expect(api.getTransactionCounts).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(r.current.transactions).toBeNull()
    expect(r.current.dividends).toBeNull()
  })

  it("剛好 500 筆照寫", async () => {
    vi.spyOn(api, "getTransactionCounts").mockResolvedValue({ transactions: 500, dividends: 12, by_type: { buy: 488, cash_dividend: 12 } })
    const r = counts()
    await waitFor(() => expect(r.current.transactions).toBe(500))
    expect(r.current.dividends).toBe(12)
  })
})
