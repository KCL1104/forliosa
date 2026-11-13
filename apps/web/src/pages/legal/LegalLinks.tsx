import { PlainLink } from "@/app/links"

/**
 * 「服務條款」「隱私權政策」兩個文字連結（登入頁、沒登入的頁尾、設定頁、條款更新的那一行共用）；`className` 套在每一個連結上。
 * 單獨一個檔：條款頁本身帶著兩份文件的全文，只有打開條款頁時才載入，不能讓這兩個連結把全文帶進每一頁。
 */
export function LegalLinks({ className }: { className?: string }) {
  return (
    <>
      <PlainLink to="/terms" className={className}>
        服務條款
      </PlainLink>
      <PlainLink to="/privacy" className={className}>
        隱私權政策
      </PlainLink>
    </>
  )
}
