import { useMemo } from "react"
import { useClosedPositions, useHoldings, useWatchlist } from "@/api/queries"

/**
 * 代號 → 名稱。交易紀錄只有代號；名稱從目前的持股、出清過的回合與觀察清單來
 * （買賣過的股票不是還持有就是出清了）。查不到時由呼叫端只顯示代號，不猜名稱。
 */
export function useSymbolNames(): ReadonlyMap<string, string> {
  const holdings = useHoldings()
  const closed = useClosedPositions()
  const watch = useWatchlist()
  return useMemo(() => {
    const names = new Map<string, string>()
    for (const w of watch.data ?? []) names.set(w.symbol, w.name)
    for (const r of closed.data ?? []) names.set(r.symbol, r.name)
    for (const h of holdings.data ?? []) names.set(h.symbol, h.name)
    return names
  }, [holdings.data, closed.data, watch.data])
}
