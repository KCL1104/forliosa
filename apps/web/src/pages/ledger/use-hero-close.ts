import { useHoldings, useSummary } from "@/api/queries"
import { useLedgerClose } from "@/hooks/use-close"
import { ledgerBoardDays, ledgerUsCloseDay } from "@/lib/as-of"
import { heroCloseLabel } from "./close-label"

/**
 * 帳本的收盤標示：`label` 是總資產那一行的「收盤價・11/12（四）」（`heroCloseLabel`）；`note`（預計幾點更新）與
 * `day`（「今日」或日期，持倉表頭與今日損益的標題用同一個）照 `useLedgerClose`。
 */
export function useHeroClose(): { label: string; note: string | null; day: string } {
  const close = useLedgerClose()
  const summary = useSummary().data
  const holdings = useHoldings().data
  const usDay = ledgerUsCloseDay(summary, holdings)
  const label = heroCloseLabel({
    boards: ledgerBoardDays(holdings, summary?.as_of),
    asOf: summary?.as_of,
    usDay,
    intraday: close.label.endsWith("盤中不更新"),
  })
  return { label, note: close.note, day: close.day }
}
