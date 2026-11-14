import { useQuery } from "@tanstack/react-query"
import { appToday } from "@/api"
import { listTransactionsUpTo } from "@/api/queries"
import { formatDateShort } from "@/lib/format"

/** 一次最多讀幾筆這一檔的交易（判斷有沒有配股或分割也用這一批） */
const RECORDS_READ = 500
/** 配股、股票分割、減資之後股價被稀釋：買進價和現在的股價不能直接比 */
export const DILUTING = new Set(["stock_dividend", "split", "capital_reduction"])

/** 這一檔的交易（`["transactions", …]` 開頭：新增、修改、刪除交易之後一起重抓） */
export function useSymbolTransactions(symbol: string) {
  return useQuery({
    queryKey: ["transactions", "symbol-records", symbol],
    queryFn: () => listTransactionsUpTo({ symbol }, RECORDS_READ),
  })
}

/** 「8/6（二）」；不是今年的寫出年份「2025/3/15（六）」 */
export function recordDate(date: string, today = appToday()): string {
  const short = formatDateShort(date)
  return date.slice(0, 4) === today.slice(0, 4) ? short : `${date.slice(0, 4)}/${short}`
}
