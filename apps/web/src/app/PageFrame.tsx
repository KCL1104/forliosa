import { cn } from "@/lib/utils"

/**
 * 每一頁的外框：一個版心、一個左緣（和帳本、個股頁相同）。
 * 最大寬 1180px、左右 20px（手機）／32px（768 以上）／56px（1280 以上）；頂端 12px／40px（桌面）。
 * 置中用 `.page-frame`（globals.css）：桌面的 AI 面板收成窄欄時，左緣留在面板開著時的位置，只有右邊變寬。
 * 有麵包屑（「← 群組」）的頁面傳 `lg:pt-6`：麵包屑那一列本身有 44px 高，第一行字的位置和帳本差不多。
 * 表單類的頁面（設定、資料來源）在裡面自己限制閱讀寬度，左緣不變。
 */
export function PageFrame({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("page-frame px-5 pt-3 pb-10 md:px-8 lg:pt-10 xl:px-14 xl:pb-14", className)} {...props} />
}
