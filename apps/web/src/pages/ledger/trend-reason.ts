import { isCoverageNote } from "@/lib/data-notes"

/**
 * 帳本主數字列：近 1 個月走勢畫不出來的原因。
 * 只取後端 notes 明講的兩種——含美股（沒有報價）、資料還不夠；
 * 其他情況（載入失敗、沒有持股、notes 沒說）回傳 null，畫面不寫原因。
 */
export function trendMissingReason(notes: readonly string[]): string | null {
  if (notes.some((n) => n.includes("美股"))) return "含美股，算不出來"
  if (notes.some(isCoverageNote)) return "資料還不夠"
  return null
}
