import { cn } from "@/lib/utils"

/**
 * 分段選擇（Segmented）：區間、分類、設定值。role=radiogroup，鍵盤 Tab 可達、Enter／Space 選擇。
 */
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
