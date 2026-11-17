import { useEffect } from "react"
import { useMarketReportStatus, useMarkReportsSeen } from "@/api/queries"
import { useReadOnly } from "@/api/view-as"

/**
 * 有沒有還沒看過的市場報告（導覽「市場」旁的小圓點；照 `ai/use-briefing-unread.ts`）。
 * 查看別人的資產時是 false：那是登入者自己的已讀紀錄。
 */
export function useReportsUnread(): boolean {
  const readOnly = useReadOnly()
  const status = useMarketReportStatus(!readOnly)
  return !readOnly && !!status.data?.unread
}

/** 打開「報告」分頁或一份報告 1.2 秒後記成看過（查看別人的資產時不記：伺服器會回唯讀） */
export const SEEN_AFTER_MS = 1200
export function useMarkReportsSeenOnOpen(active = true) {
  const readOnly = useReadOnly()
  const unread = useReportsUnread()
  const seen = useMarkReportsSeen()
  const { mutate } = seen
  useEffect(() => {
    if (!active || readOnly || !unread) return
    const t = window.setTimeout(() => mutate(), SEEN_AFTER_MS)
    return () => window.clearTimeout(t)
  }, [active, readOnly, unread, mutate])
}
