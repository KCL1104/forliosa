import { useQuery } from "@tanstack/react-query"
import { appToday } from "@/api"
import { listTransactionsUpTo, useRecurringPlans, useUpcoming } from "@/api/queries"
import type { Draft, Suggestion } from "./types"
import type { RecurringPlan, Transaction, UpcomingItem } from "@/api/types"
import { codeOf } from "@/lib/tick"
import { useAi } from "./store"

/** 漏記的扣款：往回找幾天（不含今天） */
export const MISSED_WINDOW_DAYS = 7
/** 補記最多提幾筆（最舊的在前） */
export const MAX_MISSED = 3

/** 本週事項的定期定額標題「元大台灣50 定期定額 NT$5,000（…）」→ 名稱 */
function planName(u: UpcomingItem): string {
  return u.title.split(" 定期定額")[0]?.trim() || (u.symbol ? codeOf(u.symbol) : "")
}

// ── 日期（YYYY-MM-DD，以 UTC 計算避免時區偏移） ─────────────
const day = (d: string) => new Date(`${d}T00:00:00Z`)
const iso = (d: Date) => d.toISOString().slice(0, 10)
export function addDays(d: string, n: number): string {
  const x = day(d)
  x.setUTCDate(x.getUTCDate() + n)
  return iso(x)
}
/** 週末順延到星期一（國定假日由後端的 `POST /recurring/{id}/draft?date=` 依證交所休市日順延） */
function rollWeekend(d: string): string {
  let x = d
  while ([0, 6].includes(day(x).getUTCDay())) x = addDays(x, 1)
  return x
}
/** 「11/06」 */
export const monthDay = (d: string) => `${d.slice(5, 7)}/${d.slice(8, 10)}`

/** 計畫在 [from, to] 之間的每一次扣款：[計畫原本的日子, 扣款日]，依扣款日排序 */
export function planDebits(plan: Pick<RecurringPlan, "day_of_month" | "start_date" | "end_date">, from: string, to: string): [string, string][] {
  const out: [string, string][] = []
  // 從前一個月開始找：上個月底順延到這個月初的扣款也要算
  let month = addDays(`${from.slice(0, 7)}-01`, -1).slice(0, 7)
  while (month <= to.slice(0, 7)) {
    for (const d of plan.day_of_month) {
      const scheduled = `${month}-${String(d).padStart(2, "0")}`
      if (scheduled < plan.start_date || (plan.end_date && scheduled > plan.end_date)) continue
      const debit = rollWeekend(scheduled)
      if (debit >= from && debit <= to) out.push([scheduled, debit])
    }
    month = addDays(`${month}-28`, 5).slice(0, 7)
  }
  return out.sort((a, b) => a[1].localeCompare(b[1]))
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
    .filter((u) => !buysToday.some((t) => t.type === "buy" && t.symbol === u.symbol && t.trade_date === today && (!u.account_id || t.account_id === u.account_id)))
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

/**
 * 最近 7 天漏記的扣款（純函式，不含今天；今天的由 `recurringOffers` 提出）：
 * - 啟用中的計畫，扣款日落在 [今天 − 7, 今天)
 * - 同帳戶同一檔在扣款日（含）之後、這個計畫的下一次扣款之前沒有買進紀錄
 *   （下一次扣款已經記了，不代表這一次也記了）
 * - 這個計畫這一次扣款還沒寫過草稿（待簽名、簽了、捨棄了都算）
 * 最舊的在前，最多 3 筆。
 */
export function missedDebits(plans: RecurringPlan[], today: string, buys: Transaction[], drafts: Draft[]): Suggestion[] {
  const from = addDays(today, -MISSED_WINDOW_DAYS)
  const out: Suggestion[] = []
  for (const p of plans) {
    if (!p.active) continue
    const debits = planDebits(p, from, today)
    debits.forEach(([scheduled, debit], i) => {
      if (debit >= today) return
      const next = debits[i + 1]?.[1] ?? null
      const recorded = buys.some(
        (t) => t.type === "buy" && t.symbol === p.symbol && t.account_id === p.account_id && t.trade_date >= debit && (next === null || t.trade_date < next),
      )
      if (recorded) return
      if (drafts.some((d) => d.recurring?.planId === p.id && (d.recurring.date === debit || d.recurring.date === scheduled))) return
      const code = codeOf(p.symbol)
      out.push({
        kind: "recurring_draft",
        text: `補記 ${monthDay(debit)} 的 ${code} 定期定額`,
        lines: [`${monthDay(debit)} 扣款`, `補記 ${code} 定期定額`],
        symbol: p.symbol,
        recurring: { planId: p.id, scheduledDate: scheduled, date: debit, name: p.name, missed: true },
      })
    })
  }
  return out.sort((a, b) => a.recurring!.date.localeCompare(b.recurring!.date) || a.symbol!.localeCompare(b.symbol!)).slice(0, MAX_MISSED)
}

/**
 * AI 面板：扣款日當天提出「記下今天的定期定額」，最近 7 天漏記的提出「補記 11/06 的 0050 定期定額」；
 * 點了寫成草稿（簽名後才入帳）。今天的排最前面，補記的最舊在前。
 */
export function useRecurringOffers(): Suggestion[] {
  const today = appToday()
  const from = addDays(today, -MISSED_WINDOW_DAYS)
  const upcoming = useUpcoming(7)
  const plans = useRecurringPlans()
  const drafts = useAi((s) => s.drafts)
  const due = (upcoming.data ?? []).some((u) => u.type === "recurring" && u.date === today)
  const anyDebit = (plans.data ?? []).some((p) => p.active && planDebits(p, from, today).length > 0)
  // 放在 transactions 底下：記了一筆交易就重新檢查
  const buys = useQuery({
    enabled: due || anyDebit,
    queryKey: ["transactions", "recurring-offers", from, today],
    queryFn: () => listTransactionsUpTo({ type: "buy", from, to: today }, 1000),
    staleTime: 60_000,
  })
  if (!buys.data) return []
  const list = Object.values(drafts)
  return [
    ...(due ? recurringOffers(upcoming.data ?? [], today, buys.data.items, list) : []),
    ...missedDebits(plans.data ?? [], today, buys.data.items, list),
  ]
}
