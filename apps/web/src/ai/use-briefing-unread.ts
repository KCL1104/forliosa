import { useLatestBriefing } from "@/api/queries"
import { useReadOnly } from "@/api/view-as"

/** 還沒看過最新的收盤簡報（查看別人的資產時不問：那是登入者自己的 AI 內容） */
export function useBriefingUnread(): boolean {
  const readOnly = useReadOnly()
  const latest = useLatestBriefing(!readOnly)
  return !readOnly && !!latest.data && !latest.data.read
}
