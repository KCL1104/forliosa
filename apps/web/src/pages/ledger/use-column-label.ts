import { useSummary } from "@/api/queries"
import { useClose } from "@/hooks/use-close"
import { withDayWord } from "@/lib/as-of"
import { COLUMN_LABEL, type HoldingColumn } from "./ledger-prefs"

/**
 * 持倉的欄位名稱（表頭、手機的表頭、自訂選單）：「今日漲跌」「今日損益」的「今日」跟著收盤價的日期——
 * 帳本用的收盤價是今天的才寫「今日」，否則寫那個日期（「11/12 漲跌」）。沒有盤中即時報價，不能把昨天的漲跌寫成今天的。
 */
export function useColumnLabel(): (c: HoldingColumn) => string {
  const { day } = useClose(useSummary().data?.as_of)
  return (c) => withDayWord(COLUMN_LABEL[c], day)
}
