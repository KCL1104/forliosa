import type { ReportNumberItem } from "@/api/types"
import { cn } from "@/lib/utils"

/**
 * 寬的時候一列幾格：4 格以下一列排完；5、6 格排成 3 欄；更多排成 4 欄。
 * 每一列的第一格不畫左邊的直線；第二列起每一格上面一條格線（最後一列不滿也只畫到有格子的地方，最下面一條是整條的）。
 */
function columns(n: number): string {
  if (n <= 1) return ""
  if (n === 2) return "@2xl:grid-cols-2 @2xl:[&>*:nth-child(2n+1)]:border-l-0 @2xl:[&>*:nth-child(2n+1)]:pl-0 @2xl:[&>*:nth-child(n+3)]:border-t"
  if (n === 3 || n === 5 || n === 6) return "@2xl:grid-cols-3 @2xl:[&>*:nth-child(3n+1)]:border-l-0 @2xl:[&>*:nth-child(3n+1)]:pl-0 @2xl:[&>*:nth-child(n+4)]:border-t"
  return "@2xl:grid-cols-4 @2xl:[&>*:nth-child(4n+1)]:border-l-0 @2xl:[&>*:nth-child(4n+1)]:pl-0 @2xl:[&>*:nth-child(n+5)]:border-t"
}

/**
 * 數字欄（伺服器寫好的字，前端不重算）：和市場頁的指數那一列同一種印好的格子——
 * 寬的時候一列一列的格子（上下格線、格與格之間一條直線），窄的時候是兩行列（名稱・日期｜數值・漲跌）。
 * 每格：名稱・日期（13px 淡墨；Forliosa 自己算的在名稱後面加「估算」）、數值（24px 500；比較長的字是 17px）、
 * 漲跌（漲跌色與 ▲▼；法人的口數、家數不用紅綠）。
 */
export function ReportNumbers({ items }: { items: ReportNumberItem[] }) {
  if (items.length === 0) return null
  return (
    <ul aria-label="數字" className={cn("border-t border-rule @2xl:grid @2xl:border-b", columns(items.length))}>
      {items.map((n) => {
        const long = n.value.length > 12
        return (
          <li
            key={n.key}
            data-number={n.key}
            className={cn(
              // 窄：兩行列
              "flex min-h-16 items-center justify-between gap-x-4 border-b border-rule py-2",
              // 寬：一格，格與格之間一條直線
              "@2xl:block @2xl:min-h-0 @2xl:border-b-0 @2xl:border-l @2xl:py-3.5 @2xl:pr-4 @2xl:pl-4",
            )}
          >
            <div className="min-w-0 shrink-0 @2xl:shrink">
              <p className="text-base leading-6 @2xl:text-sm @2xl:leading-5 @2xl:text-ink-2">
                {n.label}
                {n.estimate && <span className="ml-1.5 text-sm text-ink-2">估算</span>}
              </p>
              <p className="num text-sm leading-5 text-ink-2">{n.date_label}</p>
            </div>
            <div className="min-w-0 text-right @2xl:mt-1 @2xl:text-left">
              <p className={cn("num font-medium", long ? "text-base leading-6 @2xl:text-lg" : "text-lg leading-6 @2xl:text-2xl @2xl:leading-8")}>{n.value}</p>
              {n.change && (
                <p className={cn("num text-base leading-5 whitespace-nowrap", n.tone === "rise" ? "text-rise" : n.tone === "fall" ? "text-fall" : "text-ink-2")}>
                  {n.change}
                  {(n.tone === "rise" || n.tone === "fall") && <span className="sr-only">{n.tone === "rise" ? "（上漲）" : "（下跌）"}</span>}
                </p>
              )}
              {n.note && <p className="text-sm text-ink-2">{n.note}</p>}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
