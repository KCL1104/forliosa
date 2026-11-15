import { isCoverageNote } from "@/lib/data-notes"

/**
 * 後端 notes 說「有持股沒有收盤價，所以算不出來」的那一句：剛加入、還沒抓到收盤價的美股
 * （「MSFT：還沒有收盤價，績效算不出來」）；美股收盤價沒開的環境是「AAPL：美股沒有報價，含美股的績效算不出來」。
 * 「持股期間有幾天沒有收盤價」是資料還不夠，不算這一種。
 */
export function isUnpricedNote(note: string): boolean {
  return /還沒有收盤價|沒有報價/.test(note)
}

/**
 * 帳本主數字列：近 1 個月走勢畫不出來的原因。
 * 只取後端 notes 明講的兩種——有持股還沒有收盤價、資料還不夠；
 * 其他情況（載入失敗、沒有持股、notes 沒說）回傳 null，畫面不寫原因。
 */
export function trendMissingReason(notes: readonly string[]): string | null {
  if (notes.some(isUnpricedNote)) return "有持股還沒有收盤價"
  if (notes.some(isCoverageNote)) return "資料還不夠"
  return null
}
