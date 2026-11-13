import { useQueryClient } from "@tanstack/react-query"
import { holdingsQuery } from "@/api/queries"
import { useUi } from "@/app/ui-store"

/**
 * 「減少持股」「全部賣出」的入口都用這個：沒有收盤價的持股（商用模式的美股）用不了收盤價，
 * 直接開完整表單——已選賣出、帳戶帶入，全部賣出時股數先填好（2026-11-14 第七次評分：原本是一個按不下去的對話框）。
 */
export function useStartReduce() {
  const qc = useQueryClient()
  const openReduce = useUi((s) => s.openReduce)
  const openTradeForm = useUi((s) => s.openTradeForm)
  return (symbol: string, all = false) => {
    const h = qc.getQueryData(holdingsQuery().queryKey)?.find((x) => x.symbol === symbol)
    if (h && h.price === null) {
      const one = h.account_ids.length === 1
      openTradeForm({ symbol: h.code, full: true, sell: true, prefill: { accountId: h.account_ids[0], quantity: all && one ? h.quantity : undefined } })
      return
    }
    openReduce(symbol, all)
  }
}
