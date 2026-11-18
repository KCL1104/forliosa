import { useId } from "react"
import { donutArcs, type AllocRow } from "@/lib/allocation"
import { cn } from "@/lib/utils"

/** 分類色：series-1…5（固定順序，照清單的位置，不循環）；「其他」是鉛筆灰加斜線（和玫瑰色在色弱時分不開，斜線是第二層編碼） */
const toneFill = (tone: AllocRow["tone"], hatchId: string) => (tone === "other" || tone === null ? `url(#${hatchId})` : `var(--series-${tone + 1})`)

/** 「其他」的斜線（圓環與清單的色塊同一個圖樣）：鉛筆灰底、紙色細斜線 */
function Hatch({ id }: { id: string }) {
  return (
    <pattern id={id} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
      <rect width="5" height="5" fill="var(--chart-bench)" />
      <rect width="1.25" height="5" fill="var(--paper)" />
    </pattern>
  )
}

const useHatchId = () => `alloc-hatch-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`

/** 清單的色塊（和圓環同一個顏色；「其他」同樣有斜線） */
export function Swatch({ tone, className }: { tone: AllocRow["tone"]; className?: string }) {
  const hatchId = useHatchId()
  if (tone === null) return null
  return (
    <svg aria-hidden viewBox="0 0 10 10" className={cn("block size-2.5 shrink-0 overflow-hidden rounded-[2px]", className)}>
      {tone === "other" && (
        <defs>
          <Hatch id={hatchId} />
        </defs>
      )}
      <rect width="10" height="10" fill={toneFill(tone, hatchId)} />
    </svg>
  )
}

/**
 * 配置的圓環（自己畫的 SVG，不載 recharts）：12 點鐘開始、順時針、照清單的順序；塊與塊之間 2px 紙色空隙（dataviz 的 surface gap）。
 * 清單才是要讀的東西（每一塊的名稱、百分比、金額都印在清單上），圓環對螢幕報讀器隱藏。
 * 滑過清單的一列或圓環的一塊：其他塊變淡，中間換成那一塊的名稱與百分比；平常中間是幾檔與總市值（隱私模式遮金額）。
 */
export function AllocationDonut({
  rows,
  active,
  onActive,
  center,
  activeCenter,
  className,
}: {
  rows: AllocRow[]
  active: string | null
  onActive: (key: string | null) => void
  center: React.ReactNode
  activeCenter?: React.ReactNode
  className?: string
}) {
  const hatchId = useHatchId()
  const arcs = donutArcs(rows)
  return (
    <div aria-hidden className={cn("relative aspect-square shrink-0", className)} data-testid="allocation-donut">
      <svg viewBox="-2 -2 204 204" className="block size-full overflow-visible" onPointerLeave={() => onActive(null)}>
        <defs>
          <Hatch id={hatchId} />
        </defs>
        {arcs.map((a) => (
          <path
            key={a.key}
            d={a.d}
            fill={toneFill(a.tone, hatchId)}
            fillRule="evenodd"
            stroke="var(--paper)"
            strokeWidth={2}
            strokeLinejoin="round"
            className={cn("transition-opacity duration-150", active !== null && active !== a.key && "opacity-30")}
            onPointerEnter={() => onActive(a.key)}
          />
        ))}
      </svg>
      <div className="pointer-events-none absolute inset-[22%] flex flex-col items-center justify-center text-center">
        {active !== null && activeCenter ? activeCenter : center}
      </div>
    </div>
  )
}
