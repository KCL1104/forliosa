import { cn } from "@/lib/utils"

/** recharts 共用設定：細線、淡格線、等寬刻度 */
export const AXIS_TICK = { fontSize: 12, fill: "var(--muted-foreground)" } as const
export const GRID_STROKE = "var(--chart-grid)"

export interface TooltipRow {
  label: string
  value: React.ReactNode
  color?: string
  /** 線條型系列用短線、面積型用方塊 */
  shape?: "line" | "square"
}

/** 圖表提示框：文字用文字色，系列色只出現在旁邊的小記號 */
export function ChartTooltipBox({ title, rows, className }: { title: React.ReactNode; rows: TooltipRow[]; className?: string }) {
  return (
    <div className={cn("min-w-40 rounded-lg border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md", className)}>
      <div className="mb-1 text-xs text-muted-foreground">{title}</div>
      <div className="flex flex-col gap-1">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center gap-2">
            {r.color && (
              <span
                aria-hidden
                className={cn("shrink-0", r.shape === "line" ? "h-0.5 w-3 rounded-full" : "size-2.5 rounded-[3px]")}
                style={{ background: r.color }}
              />
            )}
            <span className="flex-1 text-muted-foreground">{r.label}</span>
            <span className="num font-medium">{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** 圖例（≥ 2 個系列時一定要有）：記號＋名稱＋可選數值 */
export function Legend({ items, className }: { items: { label: string; color: string; value?: React.ReactNode; shape?: "line" | "square" }[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 text-sm", className)}>
      {items.map((i) => (
        <li key={i.label} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className={cn("shrink-0", i.shape === "line" ? "h-0.5 w-3.5 rounded-full" : "size-2.5 rounded-[3px]")}
            style={{ background: i.color }}
          />
          <span className="text-muted-foreground">{i.label}</span>
          {i.value !== undefined && <span className="num font-medium">{i.value}</span>}
        </li>
      ))}
    </ul>
  )
}

/** 區間選擇（章鈕）：1M／6M／YTD…，鍵盤可操作 */
export function RangeChips<T extends string>({
  value,
  options,
  onChange,
  label,
  className,
}: {
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
  className?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("no-scrollbar -mx-1 flex items-center gap-0.5 overflow-x-auto px-1", className)}>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "press h-8 shrink-0 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-offset-0 hover:bg-muted hover:text-foreground pointer-coarse:h-10",
              active && "bg-accent text-accent-foreground ring-1 ring-primary/30 ring-inset hover:bg-accent",
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/** 月份刻度：2026-03 → 3月、跨年時 2026 */
export function monthTick(t: string): string {
  const [y, m] = t.split("-")
  return m === "01" ? `${y}` : `${Number(m)}月`
}
