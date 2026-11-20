import { useRef, useState } from "react"
import type { MarketOverview } from "@/api/types"
import { CentreBars, type CentreBarRow } from "@/components/centre-bars"
import { Tray, type TrayTint } from "@/components/tray"
import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useWidth } from "./use-width"

/** 一欄的時候先只列漲最多與跌最多的各幾個 */
const HEAD = 5
/** 一欄至少這麼寬才多分一欄：七個字的名稱（電腦及週邊設備）、最短的橫條、「▼10.00%」，加上欄距 */
const COLUMN_MIN = 300
const COLUMN_GAP = 32
const MAX_COLUMNS = 3

/** 托盤的 meta：日期・上漲幾個・下跌幾個（持平的有才寫）。數字照清單算，不另外寫 */
function sectorMeta(sectors: NonNullable<MarketOverview["sectors"]>): string {
  const up = sectors.items.filter((s) => s.change_pct > 0).length
  const down = sectors.items.filter((s) => s.change_pct < 0).length
  const flat = sectors.items.length - up - down
  return [formatDateShort(sectors.date, false), `上漲 ${up}`, `下跌 ${down}`, ...(flat > 0 ? [`持平 ${flat}`] : [])].join("・")
}

/**
 * 類股：證交所各類股指數當天的漲跌幅，由高到低，畫成中線橫條（`CentreBars`：中線固定在中間、漲往右、跌往左）。
 * 托盤的 meta 是日期與上漲、下跌的類股數（「11/12・上漲 16・下跌 16」，照清單算）。
 * 托盤裡放得下幾欄就分幾欄（一欄至少 300px，最多三欄；一欄讀完接下一欄），每欄一張 `CentreBars`、共用同一個比例。
 * 只放得下一欄時（手機）先列漲最多與跌最多的各 5 個，文字鈕「全部 N 個類股」展開。
 */
export function SectorList({ sectors, tint, className }: { sectors: NonNullable<MarketOverview["sectors"]>; tint?: TrayTint; className?: string }) {
  const [bodyRef, width] = useWidth<HTMLDivElement>()
  const trayRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const rows: CentreBarRow[] = sectors.items.map((s) => ({ id: s.index_name, label: s.name, value: s.change_pct }))
  const scale = Math.max(0, ...rows.map((r) => Math.abs(r.value)))
  const columns = Math.max(1, Math.min(MAX_COLUMNS, Math.floor((width + COLUMN_GAP) / (COLUMN_MIN + COLUMN_GAP)), rows.length))
  const collapsible = columns === 1 && rows.length > HEAD * 2 + 1
  const shown = collapsible && !open ? [...rows.slice(0, HEAD), ...rows.slice(-HEAD)] : rows
  const per = Math.ceil(shown.length / columns)
  const chunks = Array.from({ length: columns }, (_, c) => shown.slice(c * per, (c + 1) * per)).filter((c) => c.length > 0)
  const toggle = () => {
    // 收起來時把托盤捲回畫面：不會被留在清單原本的下面
    if (open) trayRef.current?.scrollIntoView({ block: "nearest", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" })
    setOpen((v) => !v)
  }
  return (
    <div ref={trayRef} className={cn("min-w-0 scroll-mt-(--sticky-top)", className)}>
      <Tray title="類股" meta={sectorMeta(sectors)} tint={tint} className="h-full">
        <div ref={bodyRef} className={cn("grid gap-x-8", columns === 2 && "grid-cols-2", columns === 3 && "grid-cols-3")}>
          {chunks.map((c, n) => (
            <CentreBars key={n} rows={c} unit="pct" scale={scale} />
          ))}
        </div>
        {collapsible && (
          <button
            type="button"
            aria-expanded={open}
            onClick={toggle}
            className="mt-1 inline-flex min-h-11 items-center text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink"
          >
            {open ? "只看漲跌最多的" : `全部 ${rows.length} 個類股`}
          </button>
        )}
      </Tray>
    </div>
  )
}
