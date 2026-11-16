import type { UserPlan } from "@/api/types"

/**
 * 方案的寫法（產品負責人 2026-11-16，群組加值包第一階段）：日期是最後一天（YYYY-MM-DD，台北）。
 * 今年的寫「12/31」，不是今年的寫「2027/1/31」。
 */
export function untilDay(ymd: string, today: string): string {
  const [y, m, d] = ymd.split("-")
  const md = `${Number(m)}/${Number(d)}`
  return y === today.slice(0, 4) ? md : `${y}/${md}`
}

/** 自己的方案（設定頁；決定 14）：「會員，到 12/31」、沒有到期日的「會員」（站方管理員也是）、「免費」 */
export function userPlanLabel(plan: Pick<UserPlan, "tier" | "until">, today: string): string {
  if (plan.tier !== "member") return "免費"
  return plan.until ? `會員，到 ${untilDay(plan.until, today)}` : "會員"
}
