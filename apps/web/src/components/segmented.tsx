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
  // WAI-ARIA radiogroup：只有選取中的項目可 Tab，方向鍵切換
  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, i: number) => {
    const delta = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const next = options[(i + delta + options.length) % options.length]!
    onChange(next.value)
    const group = e.currentTarget.parentElement
    requestAnimationFrame(() => (group?.querySelector<HTMLButtonElement>('[aria-checked="true"]'))?.focus())
  }
  return (
    <div role="radiogroup" aria-label={label} className={cn("no-scrollbar -mx-1 flex items-center gap-0.5 overflow-x-auto px-1", className)}>
      {options.map((o, i) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active || (!options.some((x) => x.value === value) && i === 0) ? 0 : -1}
            onKeyDown={(e) => onKeyDown(e, i)}
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
