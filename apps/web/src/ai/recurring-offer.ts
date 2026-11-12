import { useQuery } from "@tanstack/react-query"
import { api, appToday } from "@/api"
import { useUpcoming } from "@/api/queries"
import type { Draft, Suggestion } from "./types"
import type { Transaction, UpcomingItem } from "@/api/types"
import { codeOf } from "@/lib/tick"
import { useAi } from "./store"

/** 本週事項的定期定額標題「元大台灣50 定期定額 NT$5,000（…）」→ 名稱 */
function planName(u: UpcomingItem): string {
  return u.title.split(" 定期定額")[0]?.trim() || (u.symbol ? codeOf(u.symbol) : "")
}

/**
 * 今天要扣款、還沒記下的定期定額（純函式）：
 * - 今天的 `recurring` 本週事項
 * - 同帳戶同一檔今天還沒有買進紀錄
 * - 這個計畫今天還沒寫過草稿（簽了、捨棄了都算，不重複提）
 */
export function recurringOffers(upcoming: UpcomingItem[], today: string, buysToday: Transaction[], drafts: Draft[]): Suggestion[] {
  return upcoming
    .filter((u) => u.type === "recurring" && u.date === today && u.plan_id && u.symbol)
    .filter((u) => !buysToday.some((t) => t.type === "buy" && t.symbol === u.symbol && (!u.account_id || t.account_id === u.account_id)))
    .filter((u) => !drafts.some((d) => d.recurring?.planId === u.plan_id && d.recurring?.date === u.date))
    .map((u) => {
      const code = codeOf(u.symbol!)
      return {
        kind: "recurring_draft" as const,
        text: `記下今天的 ${code} 定期定額`,
        lines: ["今天扣款", `記下 ${code} 定期定額`] as [string, string],
        symbol: u.symbol!,
        recurring: { planId: u.plan_id!, scheduledDate: u.scheduled_date ?? u.date, date: u.date, name: planName(u) },
      }
    })
}

/** AI 面板：扣款日當天提出「記下今天的定期定額」，點了寫成草稿（簽名後才入帳） */
export function useRecurringOffers(): Suggestion[] {
  const today = appToday()
  const upcoming = useUpcoming(7)
  const drafts = useAi((s) => s.drafts)
  const due = (upcoming.data ?? []).some((u) => u.type === "recurring" && u.date === today)
  // 放在 transactions 底下：記了一筆交易就重新檢查
  const buys = useQuery({
    enabled: due,
    queryKey: ["transactions", "recurring-today", today],
    queryFn: () => api.listTransactions({ type: "buy", from: today, to: today, limit: 100 }),
    staleTime: 60_000,
  })
  if (!due || !buys.data) return []
  return recurringOffers(upcoming.data ?? [], today, buys.data.items, Object.values(drafts))
}
