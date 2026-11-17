import { InternalLink } from "@/components/internal-link"
import { cn } from "@/lib/utils"
import type { AiChart } from "./remote"

type Bar = NonNullable<AiChart["bars"]>[number]

/** 橫條的顏色：漲跌色 40%（和市場頁的類股同一種）、墨色、鉛筆灰（「其餘合計」） */
const BAR_BG: Record<Bar["tone"], string> = {
  rise: "bg-rise/40",
  fall: "bg-fall/40",
  ink: "bg-ink/35",
  pencil: "bg-chart-bench/55",
}

/** 這一條的顏色：0（持平）一律墨色；伺服器給了認不得的 tone（例如 flat）也當墨色 */
const toneOf = (b: Bar): Bar["tone"] => (b.value === 0 || !(b.tone in BAR_BG) ? "ink" : b.tone)

/** 右邊的數字：價格造成的（漲跌幅、點數）才用漲跌色；家數、口數是墨色（紅綠只給價格）；0 是墨色 */
function displayTone(chart: AiChart, b: Bar): string {
  if (chart.unit !== "pct" && chart.unit !== "points") return "text-ink"
  const t = toneOf(b)
  return t === "rise" ? "text-rise" : t === "fall" ? "text-fall" : "text-ink"
}

/**
 * 以零為軸的雙向橫條（市場報告的類股、點數貢獻、漲跌家數、美股 ETF；畫法同市場頁的 `SectorList`）：
 * 每列是名稱（下面一行 13px 淡墨的補充：集中度、「其餘合計」的說明）、一條橫條、右邊印好的數字。
 * 零軸是 1px 的 `ctl` 線；有正有負時軸在中間，只有正的在左邊、只有負的在右邊；長度依最大的絕對值縮放、高 8px。
 * 數字是主角，橫條只幫忙比大小，所以沒有提示框（橫條對螢幕報讀器隱藏，每列念名稱與數字）。
 * 有 `href` 的整列連到那一頁（個股頁）。
 */
export function HBarsChart({ chart }: { chart: AiChart }) {
  const bars = chart.bars ?? []
  if (bars.length === 0) return <p className="mt-2 text-base text-ink">沒有資料可以畫。</p>
  const max = Math.max(...bars.map((b) => Math.abs(b.value)), 1e-9)
  const pos = bars.some((b) => b.value > 0)
  const neg = bars.some((b) => b.value < 0)
  // 零軸的位置（從左邊算的百分比）與一邊可以用的寬度
  const axis = pos && neg ? 50 : neg ? 100 : 0
  const span = pos && neg ? 50 : 100
  return (
    <ul className="mt-2" data-chart-bars="">
      {bars.map((b, i) => {
        const width = b.value === 0 ? 0 : Math.max(1.5, (Math.abs(b.value) / max) * span)
        const row = (
          <>
            <span className="min-w-0 truncate text-base">{b.label}</span>
            <span aria-hidden className="relative h-2">
              <span className="absolute -inset-y-1 w-px bg-ctl" style={axis === 100 ? { right: 0 } : { left: `${axis}%` }} />
              {width > 0 && (
                <span
                  data-bar-tone={toneOf(b)}
                  className={cn("absolute inset-y-0 rounded-[1px]", BAR_BG[toneOf(b)])}
                  style={b.value > 0 ? { left: `${axis}%`, width: `${width}%` } : { right: `${100 - axis}%`, width: `${width}%` }}
                />
              )}
            </span>
            <span className={cn("num text-right text-base whitespace-nowrap", displayTone(chart, b))}>{b.display}</span>
            {/* 補充（集中度、「其餘合計」的說明）自己一行，橫跨名稱與橫條兩欄：不被名稱那一欄擠成兩三行 */}
            {b.sub && <span className="col-span-2 -mt-1 text-sm leading-5 text-ink-2">{b.sub}</span>}
          </>
        )
        const grid = "grid min-h-10 grid-cols-[minmax(5.5em,10em)_minmax(2.5rem,1fr)_minmax(4.5rem,auto)] items-center gap-x-3 py-1.5"
        return (
          <li key={`${b.label}-${i}`} className="border-b border-rule last:border-b-0">
            {b.href ? (
              <InternalLink href={b.href} className={cn(grid, "ruled-row -mb-px rounded-xs border-b-0 focus-visible:outline-offset-[-2px]")}>
                {row}
              </InternalLink>
            ) : (
              <div className={grid}>{row}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
