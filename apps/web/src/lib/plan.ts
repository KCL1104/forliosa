import type { GroupPlan, UserPlan } from "@/api/types"

/**
 * 方案的寫法（產品負責人 2026-11-16，群組加值包第一階段）：日期是最後一天（YYYY-MM-DD，台北）。
 * 今年的寫「12/31」，不是今年的寫「2027/1/31」。
 */
export function untilDay(ymd: string, today: string): string {
  const [y, m, d] = ymd.split("-")
  const md = `${Number(m)}/${Number(d)}`
  return y === today.slice(0, 4) ? md : `${y}/${md}`
}

/** 到期的加值在設定頁還列多久（天）：付款人看得出加值已經結束 */
export const ENDED_PASS_DAYS = 30

/** 最後一天 `ymd` 已過、而且在 `days` 天以內（`today` 是台北的今天） */
export function endedWithin(ymd: string, today: string, days = ENDED_PASS_DAYS): boolean {
  const diff = (Date.parse(`${today}T00:00:00Z`) - Date.parse(`${ymd}T00:00:00Z`)) / 86_400_000
  return diff > 0 && diff <= days
}

/** 自己的方案（設定頁；決定 14）：「會員，到 12/31」、沒有到期日的「會員」（站方管理員也是）、「免費」 */
export function userPlanLabel(plan: Pick<UserPlan, "tier" | "until">, today: string): string {
  if (plan.tier !== "member") return "免費"
  return plan.until ? `會員，到 ${untilDay(plan.until, today)}` : "會員"
}

/** 群組的方案（群組設定那一列）：「加值到 12/31・上限 50 人」「免費・上限 5 人」；舊版後端沒有 plan 時不寫 */
export function groupPlanLabel(plan: Pick<GroupPlan, "tier" | "until" | "member_cap">, today: string): string {
  const head = plan.tier === "boosted" ? (plan.until ? `加值到 ${untilDay(plan.until, today)}` : "加值") : "免費"
  return `${head}・上限 ${plan.member_cap} 人`
}

/** 人數到了（或超過）上限：不能再加人（到期不踢人，所以可能超過） */
export function groupFull(memberCount: number, plan: Pick<GroupPlan, "member_cap"> | null | undefined): boolean {
  return !!plan && memberCount >= plan.member_cap
}
