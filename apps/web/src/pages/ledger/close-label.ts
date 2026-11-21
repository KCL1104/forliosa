import type { Holding } from "@/api/types"
import { BOARD_NAME, closeDay, ledgerBoardDays, type BoardDay } from "@/lib/as-of"
import { formatDateShort } from "@/lib/format"

type Priced = Pick<Holding, "market" | "price" | "price_date">

/**
 * 帳本總資產那一行的日期（內頁重新設計 2026-11-21）：「收盤價・11/12（四）」，和個股頁的價格標示（`closeLabel`）同一個寫法。
 * - 上市、上櫃的收盤日不同：「收盤價・上市 11/16・上櫃 11/13」——兩個日期不寫星期（手機上一行放得下）
 * - 盤中（`intraday`）：後面接「・盤中不更新」
 * - 只有美股有價格（`usDay`，紐約的交易日）：「收盤價・11/11（美東）」——不寫星期，也不套台股的盤中說明
 * - 不知道日期（還沒有任何收盤價）：空字串，那一行只有「總資產」
 */
export function heroCloseLabel({ boards, asOf, usDay, intraday }: { boards: readonly BoardDay[]; asOf: string | null | undefined; usDay: string | null; intraday: boolean }): string {
  if (usDay) return `收盤價・${formatDateShort(usDay, false)}（美東）`
  const days = boards.length ? boards.map((b) => b.day) : [closeDay(asOf)].filter((d): d is string => !!d)
  if (!days.length) return ""
  const same = days.every((d) => d === days[0])
  const when = same ? formatDateShort(days[0]!) : boards.map((b) => `${BOARD_NAME[b.board]} ${formatDateShort(b.day, false)}`).join("・")
  return `收盤價・${when}${intraday ? "・盤中不更新" : ""}`
}

/**
 * 今日損益那一盤的 meta：每個市場的收盤日分開寫（產品負責人 2026-11-21；美股的漲跌不說「今天」，DESIGN.md Copy〈美股的價格與日期〉）。
 * - 只有台股：「11/12（四）」；上市、上櫃的日期不同：「上市 11/16・上櫃 11/13」
 * - 只有美股：「11/11（美東）」
 * - 都有：「台股 11/12・美股 11/11（美東）」（上市、上櫃不同時「上市 11/16・上櫃 11/13・美股 11/11（美東）」）
 * 只看有收盤價的持股（沒有收盤價的不在那張圖上）；美股持股沒有 `price_date` 時只寫「美股（美東）」，不猜日期。
 */
export function pnlDates(rows: readonly Priced[], asOf: string | null | undefined): string {
  const priced = rows.filter((h) => h.price !== null)
  const us = priced.filter((h) => h.market === "US")
  const tw = ledgerBoardDays(
    priced.filter((h) => h.market !== "US"),
    asOf,
  )
  const usDays = us.map((h) => h.price_date).filter((d): d is string => !!d)
  const usDay = usDays.length ? usDays.reduce((a, b) => (b > a ? b : a)) : null
  const usDate = usDay ? `${formatDateShort(usDay, false)}（美東）` : null
  const twSame = tw.length > 0 && tw.every((b) => b.day === tw[0]!.day)
  const twText = !tw.length
    ? null
    : twSame
      ? us.length
        ? `台股 ${formatDateShort(tw[0]!.day, false)}`
        : formatDateShort(tw[0]!.day)
      : tw.map((b) => `${BOARD_NAME[b.board]} ${formatDateShort(b.day, false)}`).join("・")
  if (!us.length) return twText ?? ""
  if (!twText) return usDate ?? "美股（美東）"
  return `${twText}・${usDate ? `美股 ${usDate}` : "美股（美東）"}`
}
