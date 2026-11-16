import type { AdminMember } from "@/api/types"

/** 管理後台「會員」頁的日期計算（`pages/admin/AdminMembersPage.tsx`）。日期都是 YYYY-MM-DD（台北）。 */

/** YYYY-MM-DD 加幾天（UTC 計算，不受時區影響） */
function addDays(ymd: string, days: number): string {
  const d = new Date(`${ymd}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** 下個月的同一天（沒有那一天就是月底） */
function addMonth(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number) as [number, number, number]
  const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate()
  return new Date(Date.UTC(y, m, Math.min(d, last))).toISOString().slice(0, 10)
}

/**
 * 多一個月的最後一天：還是會員就從原本的最後一天往後接，否則從今天開始（11/15 開通 → 12/14）。
 * 沒有到期日的會員不需要續期。
 */
export function monthLater(today: string, current?: Pick<AdminMember, "active" | "until">): string {
  const start = current?.active && current.until ? addDays(current.until, 1) : today
  return addDays(addMonth(start), -1)
}

export function formatDay(ymd: string): string {
  const [y, m, d] = ymd.split("-")
  return `${y}/${Number(m)}/${Number(d)}`
}
