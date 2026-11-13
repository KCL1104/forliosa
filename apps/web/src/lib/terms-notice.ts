import { formatDate, formatDateShort } from "@/lib/format"

/**
 * 條款更新那一行的句子。站方有填生效日（`TERMS_EFFECTIVE_DATE`）與變更摘要（`TERMS_SUMMARY`）就寫出來：
 * 服務條款承諾生效前 14 天公告，只寫「已更新」的話，看不出改了什麼、哪一天開始算。
 * - 生效日還沒到：「12/1 起適用新版服務條款與隱私權政策：〈摘要〉。」
 * - 生效日到了或過了：「服務條款與隱私權政策在 12/1 更新：〈摘要〉。」
 * - 沒有生效日：「服務條款與隱私權政策已更新：〈摘要〉。」沒有摘要就只有前半句。
 * 日期不是今年時寫出年份。
 */
export function termsNoticeText(effectiveDate: string | null | undefined, summary: string | null | undefined, today: string): string {
  const what = summary?.trim().replace(/[。.\s]+$/, "")
  const tail = what ? `：${what}。` : "。"
  if (!effectiveDate) return `服務條款與隱私權政策已更新${tail}`
  const day = effectiveDate.slice(0, 4) === today.slice(0, 4) ? formatDateShort(effectiveDate, false) : formatDate(effectiveDate)
  return effectiveDate > today ? `${day} 起適用新版服務條款與隱私權政策${tail}` : `服務條款與隱私權政策在 ${day} 更新${tail}`
}
