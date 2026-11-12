import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * 聯絡簿的日期格（`.date-cell`）：日期（墨色 500）＋星期（12px 淡墨），右邊一條格線。
 * 撐滿整列的高度（`-my-*` 抵掉列的上下內距，`pad` 傳同樣的值），一列接一列時格線連成一條直線。
 * 排法：
 * - 預設：手機日期與星期上下兩行、桌面一行（給很窄的欄，例如交易列表的 3.25rem）
 * - `inline`：任何寬度都一行（欄夠寬時，例如股利清單的 88px 欄）
 * - `stacked`：任何寬度都兩行
 * 星期的全形括號用 `halt`（半寬），兩行時星期的左緣和日期對齊，一行時不多佔空白。
 */
export function DateCell({
  date,
  pad = "-my-2.5 py-2.5",
  stacked,
  inline,
  children,
  className,
}: {
  date: string
  pad?: string
  stacked?: boolean
  inline?: boolean
  children?: React.ReactNode
  className?: string
}) {
  const md = formatDateShort(date, false)
  const weekday = formatDateShort(date).slice(md.length) // 「（四）」
  const layout = stacked ? "stacked" : inline ? "inline" : "responsive"
  return (
    <span className={cn("date-cell flex flex-col justify-center self-stretch leading-tight", pad, className)}>
      <span className={cn("flex", layout === "stacked" && "flex-col", layout === "inline" && "items-baseline", layout === "responsive" && "flex-col lg:flex-row lg:items-baseline")}>
        {md}
        <span className={cn("weekday [font-feature-settings:'halt'_1]", layout !== "inline" && "mt-0.5", layout === "responsive" && "lg:mt-0")}>{weekday}</span>
      </span>
      {children}
    </span>
  )
}
