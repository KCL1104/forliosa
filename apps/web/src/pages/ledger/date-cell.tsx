import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * 聯絡簿的日期格（`.date-cell`）：日期（墨色 500）＋星期（12px 淡墨），右邊一條格線。
 * 撐滿整列的高度（`-my-*` 抵掉列的上下內距，`pad` 傳同樣的值），一列接一列時格線連成一條直線。
 * `stacked`：日期與星期上下兩行（手機，或桌面也要窄欄時）；預設手機兩行、桌面一行。
 */
export function DateCell({ date, pad = "-my-2.5 py-2.5", stacked, children, className }: { date: string; pad?: string; stacked?: boolean; children?: React.ReactNode; className?: string }) {
  const md = formatDateShort(date, false)
  const weekday = formatDateShort(date).slice(md.length) // 「（四）」
  return (
    <span className={cn("date-cell flex flex-col justify-center self-stretch leading-tight", pad, className)}>
      <span className={cn("flex flex-col", !stacked && "lg:flex-row lg:items-baseline")}>
        {md}
        <span className={cn("weekday mt-0.5", !stacked && "lg:mt-0")}>{weekday}</span>
      </span>
      {children}
    </span>
  )
}
