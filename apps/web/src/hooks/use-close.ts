import { appToday, marketNow } from "@/api"
import { useMarketStatus } from "@/api/queries"
import { closeNote, closeState, dayWord, type CloseState } from "@/lib/as-of"

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
