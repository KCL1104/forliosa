import { useQuery } from "@tanstack/react-query"
import { appToday } from "@/api"
import { listTransactionsUpTo } from "@/api/queries"
import type { Transaction } from "@/api/types"
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

/**
 * 一筆買進的均價（產品負責人 2026-11-17：「每次買進都要顯示出買進均價（手續費幫我算進去）」）：
 * (股數 × 成交價 ＋ 這一筆的手續費) ÷ 股數，和後端帳本算成本的方式一樣（`domain/ledger.py`：買進成本 ＝ 成交金額 ＋ 手續費）。
 * 沒填手續費存的就是 0（後端與「記一筆」都不自動估），所以均價就是成交價——用 0 算，不另外寫字。
 * 美股的手續費和價格都是美元。不是買進、或缺股數或價格時是 null。
 */
export function buyAverage(t: Pick<Transaction, "type" | "quantity" | "price" | "fee">): number | null {
  if (t.type !== "buy" || !t.quantity || t.quantity <= 0 || t.price === null) return null
  const fee = t.fee > 0 ? t.fee : 0
  return (t.quantity * t.price + fee) / t.quantity
}

/**
 * 目前持有的這一批裡，有沒有哪一筆買進填了手續費：有才在均價旁邊寫「含手續費」（沒填的以 0 計，不寫一個不存在的費用）。
 * 照日期（同一天照建立的先後）走一遍股數：買進加、賣出減，配股加、分割與減資照比例；股數歸零（出清過）就重新算，
 * 之前那一輪的手續費不算進現在的均價。先進先出時已經賣掉的那一筆仍算有（少見，寫「含手續費」也不會錯成別的數字）。
 */
export function feeInHolding(items: Transaction[]): boolean {
  const ordered = [...items].sort((x, y) => x.trade_date.localeCompare(y.trade_date) || x.created_at.localeCompare(y.created_at))
  let held = 0
  let fee = false
  for (const t of ordered) {
    const q = t.quantity ?? 0
    switch (t.type) {
      case "buy":
        held += q
        if (t.fee > 0) fee = true
        break
      case "sell":
        held -= q
        break
      case "stock_dividend":
        // 存的是配發的股數；舊資料沒有股數時照每股配股（元）÷ 面額 10 元算
        held += q > 0 ? q : Math.floor((held * (t.price ?? 0)) / 10)
        break
      case "split":
        held *= q > 0 ? q : 1
        break
      case "capital_reduction":
        held -= held * q
        break
    }
    if (held <= 1e-9) {
      held = 0
      fee = false
    }
  }
  return fee
}
