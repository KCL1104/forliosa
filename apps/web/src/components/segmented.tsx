import { cn } from "@/lib/utils"

/**
 * 區間選擇（1日…全部、季／年…）：role=radiogroup，方向鍵切換。
 * 選取＝墨色實底（和帳本分段同一套語言）。
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
  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, i: number) => {
    const delta = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const next = options[(i + delta + options.length) % options.length]!
    onChange(next.value)
    const group = e.currentTarget.parentElement
    requestAnimationFrame(() => group?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus())
  }
  return (
    <div role="radiogroup" aria-label={label} className={cn("no-scrollbar -mx-1 flex items-center gap-0.5 overflow-x-auto px-1 py-0.5", className)}>
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
              "press h-8 shrink-0 rounded-sm px-2.5 text-sm text-ink-2 hover:bg-hov hover:text-ink pointer-coarse:h-11 pointer-coarse:px-3",
              active && "bg-act font-medium text-act-fg hover:bg-act hover:text-act-fg",
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * 分段（帳本：持倉・交易・股利・績效）：1px 鉛筆灰外框、選取＝墨色實底。
 * role=tablist；方向鍵切換。
 */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  className,
  controls,
}: {
  value: T
  options: readonly { value: T; label: string; count?: number | null }[]
  onChange: (v: T) => void
  label: string
  className?: string
  controls?: string
}) {
  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, i: number) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const next = options[(i + delta + options.length) % options.length]!
    onChange(next.value)
    const group = e.currentTarget.parentElement
    requestAnimationFrame(() => group?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus())
  }
  return (
    <div role="tablist" aria-label={label} className={cn("flex gap-1 rounded-md border border-ctl p-1", className)}>
      {options.map((o, i) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            id={`tab-${o.value}`}
            aria-selected={active}
            aria-controls={controls}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => onKeyDown(e, i)}
            onClick={() => onChange(o.value)}
            className={cn(
              "press relative flex h-[34px] items-center justify-center gap-1.5 rounded-sm px-4 text-base text-ink-2 hover:bg-hov hover:text-ink before:absolute before:inset-x-0 before:-inset-y-1 max-lg:h-[38px] max-lg:flex-1 max-lg:px-2",
              active && "bg-act font-medium text-act-fg hover:bg-act hover:text-act-fg",
            )}
          >
            {o.label}
            {o.count !== undefined && o.count !== null && <span className="num text-sm font-normal opacity-85 max-lg:hidden">{o.count}</span>}
          </button>
        )
      })}
    </div>
  )
}
