import { useQuery } from "@tanstack/react-query"
import { listTransactionsUpTo, useHoldings } from "@/api/queries"

/** 分段上的數字：持倉檔數、交易筆數、股利筆數（最多數到 500，超過顯示 500+） */
export function useLedgerCounts() {
  const holdings = useHoldings()
  const txns = useQuery({
    queryKey: ["transactions", "count"],
    // 後端每頁最多 200 筆：分頁讀到 500 筆為止
    queryFn: () => listTransactionsUpTo({}, 500),
    staleTime: 60_000,
  })
  const items = txns.data?.items ?? []
  const more = !!txns.data?.more
  return {
    holdings: holdings.data?.length ?? null,
    transactions: txns.data ? (more ? null : items.length) : null,
    // 超過 500 筆時只讀了最新的 500 筆：股利筆數不準，不寫數字（和交易筆數一樣）
    dividends: txns.data && !more ? items.filter((t) => t.type === "cash_dividend" || t.type === "stock_dividend").length : null,
  }
}
