/**
 * 帳本相關的顯示規則（純函式，元件與測試共用）：出清回合（依年份分組）、沒有報價的持股、本週事項的一句話、定期定額。
 */
import type { ClosedRound, Holding, RecurringPlan, UpcomingItem } from "@/api/types"
import { formatDate, formatMoney } from "@/lib/format"
import { codeOf } from "@/lib/tick"

/** 持有期間：「2024/01/10 – 2025/02/20」與「持有 407 天」（當沖的回合是「當天出清」） */
export function holdingPeriod(r: Pick<ClosedRound, "opened_at" | "closed_at" | "holding_days">): { range: string; days: string } {
  return {
    range: r.opened_at === r.closed_at ? formatDate(r.opened_at) : `${formatDate(r.opened_at)} – ${formatDate(r.closed_at)}`,
    days: r.holding_days === 0 ? "當天出清" : `持有 ${r.holding_days.toLocaleString("zh-TW")} 天`,
  }
}

/** 已出清的回合合計（已實現損益只加總，報酬率不加總） */
export function closedTotals(rounds: ClosedRound[]) {
  return {
    symbols: new Set(rounds.map((r) => r.symbol)).size,
    realized: rounds.reduce((s, r) => s + r.realized_pnl, 0),
  }
}

export interface ClosedYear {
  /** 出清的年份（`closed_at` 的西元年） */
  year: string
  rounds: ClosedRound[]
  /** 這一年出清的回合已實現損益合計 */
  realized: number
  symbols: number
}

/** 已出清依出清年份分組：新的年份在前，年內依出清日新到舊 */
export function closedByYear(rounds: ClosedRound[]): ClosedYear[] {
  const by = new Map<string, ClosedRound[]>()
  for (const r of rounds) {
    const y = r.closed_at.slice(0, 4)
    by.set(y, [...(by.get(y) ?? []), r])
  }
  return [...by.entries()]
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([year, list]) => {
      const sorted = [...list].sort((a, b) => b.closed_at.localeCompare(a.closed_at) || a.symbol.localeCompare(b.symbol))
      return { year, rounds: sorted, ...closedTotals(sorted) }
    })
}

/** 沒有報價的持股（商用模式的美股）：以成本計值，現價與漲跌顯示「—」 */
export function unpricedHoldings<T extends Pick<Holding, "name" | "price" | "market">>(rows: T[]): T[] {
  return rows.filter((h) => h.price === null)
}

/** 本週事項的一句話。定期定額的標題本身含金額（後端），所以由欄位組成，隱私模式才不會露出金額 */
export function upcomingText(u: UpcomingItem, privacy: boolean): string {
  const amount = u.amount_estimate
  if (u.type === "recurring") {
    const what = `${u.symbol ? codeOf(u.symbol) : ""} 定期定額${u.scheduled_date && u.scheduled_date !== u.date ? "（遇休市順延）" : ""}`.trim()
    return amount === null ? what : `${what}・${privacy ? "••••" : formatMoney(amount)}`
  }
  if (amount === null) return u.title
  if (privacy) return `${u.title}・預估 ••••`
  return `${u.title}・預估 ${formatMoney(amount, { signed: true })}`
}

export function upcomingShort(u: UpcomingItem): string {
  return u.type === "recurring" ? `${u.symbol ? codeOf(u.symbol) : ""} 定期定額`.trim() : u.title
}

/** 計畫的狀態：啟用中（有下一次扣款）、已暫停、已結束 */
export function planStatus(p: Pick<RecurringPlan, "active" | "end_date" | "next_date">, today: string): "active" | "paused" | "ended" {
  if (p.end_date && p.end_date < today) return "ended"
  if (!p.active) return "paused"
  return p.next_date ? "active" : "ended"
}

/** 每月扣款日的說明文字：[6, 19] →「每月 6、19 日」 */
export function daysLabel(days: number[]): string {
  const sorted = [...days].sort((a, b) => a - b)
  return sorted.length === 0 ? "還沒選扣款日" : `每月 ${sorted.join("、")} 日`
}

/** 持倉上的定期定額標記：只算啟用中的計畫，依代號分組（同一檔可以有多個帳戶的計畫） */
export function activePlansBySymbol(plans: RecurringPlan[], today: string): Map<string, RecurringPlan[]> {
  const out = new Map<string, RecurringPlan[]>()
  for (const p of plans) {
    if (planStatus(p, today) !== "active") continue
    out.set(p.symbol, [...(out.get(p.symbol) ?? []), p])
  }
  return out
}

/** 標記的說明：「定期定額：每月 6、19 日 NT$5,000」；隱私模式遮金額 */
export function recurringLabel(plans: Pick<RecurringPlan, "day_of_month" | "amount">[], privacy: boolean): string {
  return `定期定額：${plans.map((p) => `${daysLabel(p.day_of_month)} ${privacy ? "••••" : formatMoney(p.amount)}`).join("；")}`
}
