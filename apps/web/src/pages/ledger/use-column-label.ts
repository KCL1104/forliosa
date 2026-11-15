import { useLedgerClose } from "@/hooks/use-close"
import { withDayWord } from "@/lib/as-of"
import { COLUMN_LABEL, type HoldingColumn } from "./ledger-prefs"

/**
 * 持倉的欄位名稱（表頭、手機的表頭、自訂選單）：「今日漲跌」「今日損益」的「今日」跟著收盤價的日期——
 * 帳本用的收盤價是今天的才寫「今日」，否則寫那個日期（「11/12 漲跌」）。沒有盤中即時報價，不能把昨天的漲跌寫成今天的。
 * 只有美股有價格時是紐約的交易日（「11/13 漲跌」），和主數字同一個判斷（`useLedgerClose`）。
 */
export function useColumnLabel(): (c: HoldingColumn) => string {
  const { day } = useLedgerClose()
  return (c) => withDayWord(COLUMN_LABEL[c], day)
}
