import { direction, directionGlyph, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { pctText } from "./trend-chart"

/** 走勢讀數裡的報酬：和主數字列的 Delta 同一套（漲跌色、▲▼、10% 以下兩位小數） */
export function TrendReturn({ value }: { value: number | null }) {
  const d = direction(value)
  return (
    <span className={cn("num whitespace-nowrap", toneClass(d))}>
      {directionGlyph(d)}
      {value === null ? "—" : pctText(value)}
      <span className="sr-only">{d === "up" ? "上漲" : d === "down" ? "下跌" : "持平"}</span>
    </span>
  )
}
