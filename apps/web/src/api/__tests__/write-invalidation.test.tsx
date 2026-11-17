import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import {
  qk,
  useClearRecords,
  useCommitPositions,
  useCreateTransactionBatch,
  useDeleteHolding,
  useDeleteTransactionBatch,
} from "@/api/queries"
import { ApiError } from "@/api/types"

/**
 * API 速度（2026-11-17）多了兩個前端快取：AI 面板在每一頁讀的「只有定期定額扣款」的本週事項（`qk.upcomingRecurring`），
 * 和帳本「紀錄」分頁的筆數（`["transactions", "count"]`，改讀 `GET /transactions/counts`）。
 * 之後合併進來的寫入（匯入對帳單、匯入庫存與以券商為準、刪除這檔、清除所有持倉、整批復原）都要讓它們和持股、總資產一起重讀。
 */
const WATCHED = [
  qk.summary(),
  qk.holdings(),
  qk.upcoming(7),
  qk.upcomingRecurring(7),
  ["transactions", "count"],
  qk.performance("ALL"),
] as const

function seeded() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  for (const key of WATCHED) qc.setQueryData([...key], { seeded: true })
  qc.setQueryData([...qk.recurring], [])
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  return { qc, wrapper }
}

const invalidated = (qc: QueryClient) => WATCHED.map((key) => [key.join("/"), qc.getQueryState([...key])?.isInvalidated])
const allInvalidated = WATCHED.map((key) => [key.join("/"), true])

afterEach(() => {
  vi.restoreAllMocks()
})

describe("新的寫入之後，API 速度加上的快取也重讀", () => {
  it("刪除這檔（一起暫停定期定額）", async () => {
    vi.spyOn(api, "deleteHolding").mockResolvedValue({ account_id: "a", symbol: "2330.TW", deleted: 3, plans_paused: 1, plans_running: 0 })
    const { qc, wrapper } = seeded()
    const { result } = renderHook(() => useDeleteHolding(), { wrapper })
    await act(() => result.current.mutateAsync({ accountId: "a", symbol: "2330.TW", pausePlans: true }))
    expect(invalidated(qc)).toEqual(allInvalidated)
    expect(qc.getQueryState([...qk.recurring])?.isInvalidated).toBe(true)
  })

  it("清除所有持倉，以及別的分頁已經清掉（404 no_records）時", async () => {
    vi.spyOn(api, "clearRecords").mockResolvedValue({ account_id: null, deleted: 9, symbols: 3, plans_paused: 0, plans_running: 1 })
    let { qc, wrapper } = seeded()
    const ok = renderHook(() => useClearRecords(), { wrapper })
    await act(() => ok.result.current.mutateAsync({ accountId: null }))
    expect(invalidated(qc)).toEqual(allInvalidated)

    vi.spyOn(api, "clearRecords").mockRejectedValue(new ApiError(404, "no_records", "沒有任何紀錄", { plans_paused: 1, plans_running: 0 }))
    ;({ qc, wrapper } = seeded())
    const gone = renderHook(() => useClearRecords(), { wrapper })
    await act(() => gone.result.current.mutateAsync({ accountId: "a", pausePlans: true }).catch(() => undefined))
    expect(invalidated(qc)).toEqual(allInvalidated)
    expect(qc.getQueryState([...qk.recurring])?.isInvalidated).toBe(true)
  })

  it("匯入庫存（含以券商為準）", async () => {
    vi.spyOn(api, "commitPositions").mockResolvedValue({
      dry_run: false, batch_id: "imp_1", trade_date: "2026-11-17", created: ["txn_1"], replaced: [{ symbol: "2330.TW", deleted: 3 }],
      auto_dividends_added: 0,
    })
    const { qc, wrapper } = seeded()
    const { result } = renderHook(() => useCommitPositions(), { wrapper })
    await act(() => result.current.mutateAsync({ account_id: "a", rows: [{ symbol: "2330.TW", quantity: 1000, price: 500, replace: true }] }))
    expect(invalidated(qc)).toEqual(allInvalidated)
  })

  it("匯入對帳單與整批復原", async () => {
    vi.spyOn(api, "createTransactionBatch").mockResolvedValue({ dry_run: false, batch_id: "imp_2", created: [], auto_dividends_added: 0 } as never)
    vi.spyOn(api, "deleteTransactionBatch").mockResolvedValue({ deleted: 2 } as never)
    let { qc, wrapper } = seeded()
    const write = renderHook(() => useCreateTransactionBatch(), { wrapper })
    await act(() => write.result.current.mutateAsync({ account_id: "a", dry_run: false, rows: [] } as never))
    expect(invalidated(qc)).toEqual(allInvalidated)
    ;({ qc, wrapper } = seeded())
    const undo = renderHook(() => useDeleteTransactionBatch(), { wrapper })
    await act(() => undo.result.current.mutateAsync("imp_2"))
    expect(invalidated(qc)).toEqual(allInvalidated)
  })
})
