import type { RecurringPlan, Transaction } from "@/api/types"
import { formatNumber } from "@/lib/format"
import { planStatus } from "@/lib/ledger-display"

/** 「刪除這檔」確認框（`DeleteHoldingDialog`）用的小工具 */

const TRADE_TYPES = new Set(["buy", "sell"])
const DIVIDEND_TYPES = new Set(["cash_dividend", "stock_dividend"])

/** 「包括 5 筆買賣、2 筆股利。」：只有一種時不寫（標題的筆數就是那一種） */
export function recordBreakdown(rows: Pick<Transaction, "type">[]): string | null {
  const trades = rows.filter((t) => TRADE_TYPES.has(t.type)).length
  const dividends = rows.filter((t) => DIVIDEND_TYPES.has(t.type)).length
  const other = rows.length - trades - dividends
  const parts = [
    trades > 0 && `${formatNumber(trades)} 筆買賣`,
    dividends > 0 && `${formatNumber(dividends)} 筆股利`,
    other > 0 && `${formatNumber(other)} 筆其他紀錄`,
  ].filter(Boolean)
  return parts.length > 1 ? `包括 ${parts.join("、")}。` : null
}

/**
 * 這個帳戶這一檔還在進行的定期定額：和持倉上的標記、後端回應的 `plans_running` 同一個判斷（啟用中、結束日沒過、還有下一次扣款日）
 */
export function runningPlans(plans: RecurringPlan[], accountId: string | undefined, symbol: string, today: string): RecurringPlan[] {
  return plans.filter((p) => p.account_id === accountId && p.symbol === symbol && planStatus(p, today) === "active")
}
