import type { ForliosaApi } from "@/api/types"

/** 「2026-11-13」的隔天「2026-11-14」 */
function nextDay(ymd: string): string {
  const d = new Date(`${ymd}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
}

/**
 * 用收盤價記的賣出（「賣出／全部賣出」、AI 草稿沒寫日期與價格）記在哪一天。
 * - 台股（`closeDate` 是 null）：今天。
 * - 美股：那個收盤的紐約交易日（`closeDate`，和「用 11/13（美東）的收盤價」同一天）。但這個帳戶這一檔已經有更晚的交易時
 *   （例如台北今天剛記的買進），記在那天之前，後端依日期重算會說「賣出超過當時持有的股數」（422）——改記今天。
 *   查不到既有交易時也記今天（和改成紐約日期之前一樣）。
 * 使用者自己寫的日期不經過這裡，一律照寫的。
 */
export async function closeSellDate(
  api: Pick<ForliosaApi, "listTransactions">,
  { accountId, symbol, closeDate, today }: { accountId: string; symbol: string; closeDate: string | null; today: string },
): Promise<string> {
  if (!closeDate) return today
  try {
    const later = await api.listTransactions({ account_id: accountId, symbol, from: nextDay(closeDate), limit: 1 })
    return later.items.length > 0 ? today : closeDate
  } catch {
    return today
  }
}
