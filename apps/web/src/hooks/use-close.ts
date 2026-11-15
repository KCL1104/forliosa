import { appToday, marketNow } from "@/api"
import { useHoldings, useMarketStatus, useSummary } from "@/api/queries"
import { closeNote, closeState, dayWord, ledgerAsOf, ledgerUsCloseDay, type CloseState } from "@/lib/as-of"
import { formatDateShort } from "@/lib/format"
import { usCloseLabel } from "@/lib/labels"

/**
 * 一個收盤價（報價或帳本的 `as_of`）現在該怎麼標：
 * - `state`／`note`：盤中、收盤後今天的還沒公布時多一行說明；其他時候沒有（見 lib/as-of.ts）
 * - `day`：「今日」損益、「今日漲跌」的那個詞——收盤價的日期就是今天才寫「今日」，否則寫那個日期（「11/12」）
 * 市場狀態大約每分鐘更新一次；還沒載入時不加說明，「今天」先用本機的台北日期。
 */
export function useClose(asOf: string | null | undefined): { state: CloseState; note: string | null; day: string } {
  const market = useMarketStatus().data?.tw
  const state = closeState(market, asOf, marketNow())
  return { state, note: closeNote(state, asOf), day: dayWord(asOf, market?.date ?? appToday()) }
}

/**
 * 帳本（全部帳戶）的收盤：主數字旁的那一行（`label`）和「今日」損益、「今日漲跌」的那個詞（`day`）。
 * - 有台股的價格：照台股（「11/12 收盤・盤中不更新」「今日」或「11/12」）
 * - 只有美股有價格（`ledgerUsCloseDay`）：紐約的交易日「11/13 收盤（美東）」與「11/13」——那是紐約那一天的收盤，
 *   不套台股的盤中／還沒公布，也不寫「今日」
 */
export function useLedgerClose(): { label: string; day: string } {
  const summary = useSummary().data
  const holdings = useHoldings().data
  const close = useClose(summary?.as_of)
  const us = ledgerUsCloseDay(summary, holdings)
  if (us) return { label: usCloseLabel(us), day: formatDateShort(us, false) }
  return { label: ledgerAsOf(close.state, summary?.as_of), day: close.day }
}
