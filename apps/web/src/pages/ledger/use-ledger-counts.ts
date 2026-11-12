import { useQuery } from "@tanstack/react-query"
import { api } from "@/api"
import { useHoldings } from "@/api/queries"

/** 分段上的數字：持倉檔數、交易筆數、股利筆數（最多數到 500，超過顯示 500+） */
export function useLedgerCounts() {
  const holdings = useHoldings()
  const txns = useQuery({
    queryKey: ["transactions", "count"],
    queryFn: () => api.listTransactions({ limit: 500 }),
    staleTime: 60_000,
  })
  const items = txns.data?.items ?? []
  const more = !!txns.data?.next_cursor
  return {
    holdings: holdings.data?.length ?? null,
    transactions: txns.data ? (more ? null : items.length) : null,
    dividends: txns.data ? items.filter((t) => t.type === "cash_dividend" || t.type === "stock_dividend").length : null,
  }
}
