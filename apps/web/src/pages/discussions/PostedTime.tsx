import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"
import { clockTime, taipeiDay } from "./labels"

/**
 * 發言的時間：「11/12（四）13:02」（台北時間），等寬數字、不拆行。
 * 星期的全形括號用 `halt`（半寬），和日期格裡的星期同一種寫法——一行字裡不會空出兩個全形的空白。
 */
export function PostedTime({ iso, className }: { iso: string; className?: string }) {
  const day = taipeiDay(iso)
  const md = formatDateShort(day, false)
  const weekday = formatDateShort(day).slice(md.length)
  return (
    <time dateTime={iso} className={cn("num whitespace-nowrap", className)}>
      {md}
      <span className="[font-feature-settings:'halt'_1]">{weekday}</span> {clockTime(iso)}
    </time>
  )
}
