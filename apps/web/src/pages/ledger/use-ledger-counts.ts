import { useQuery } from "@tanstack/react-query"
import { api } from "@/api"
import { useHoldings } from "@/api/queries"

/** 筆數超過這個數字時不寫數字（之前前端最多讀 500 筆來數，超過就只顯示分頁名稱：沿用） */
const MAX_SHOWN = 500

/**
 * 分段上的數字：持倉檔數、交易筆數、股利筆數。
 * 筆數用 `GET /transactions/counts`（一句 GROUP BY）；之前是依序讀最多 3 頁、每頁 200 筆交易來數。
 */
export function useLedgerCounts() {
  const holdings = useHoldings()
  const counts = useQuery({
    // 放在 ["transactions"] 底下：記了、改了、刪了交易就重新讀
    queryKey: ["transactions", "count"],
    queryFn: () => api.getTransactionCounts(),
    staleTime: 60_000,
  })
  const c = counts.data
  const shown = c ? c.transactions <= MAX_SHOWN : false
  return {
    holdings: holdings.data?.length ?? null,
    transactions: c && shown ? c.transactions : null,
    // 和之前一樣：超過 500 筆時股利筆數也不寫數字
    dividends: c && shown ? c.dividends : null,
  }
}
