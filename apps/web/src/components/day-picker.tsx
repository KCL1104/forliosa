import { cn } from "@/lib/utils"

/**
 * 每月扣款日（1–28，可複選）：7 欄的日期格，選取＝墨色實底（和區間、分段同一套語言）。
 * 一個 role=group，每格是 aria-pressed 的按鈕；方向鍵在格子之間移動。只到 28 日，因為每個月都有。
 */
export function DayOfMonthPicker({
  value,
  onChange,
  label = "每月扣款日",
  invalid,
  className,
}: {
  value: number[]
  onChange: (days: number[]) => void
  label?: string
  invalid?: boolean
  className?: string
}) {
  const toggle = (d: number) => onChange(value.includes(d) ? value.filter((x) => x !== d) : [...value, d].sort((a, b) => a - b))
  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, d: number) => {
    const delta = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 7, ArrowUp: -7 }[e.key]
    if (!delta) return
    e.preventDefault()
    const next = d + delta
    if (next < 1 || next > 28) return
    e.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[data-day="${next}"]`)?.focus()
  }
  return (
    <div role="group" aria-label={label} aria-invalid={invalid || undefined} className={cn("grid w-full max-w-[22rem] grid-cols-7 gap-1", className)}>
      {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => {
        const on = value.includes(d)
        return (
          <button
            key={d}
            type="button"
            data-day={d}
            aria-pressed={on}
            aria-label={`${d} 日`}
            onClick={() => toggle(d)}
            onKeyDown={(e) => onKeyDown(e, d)}
            className={cn(
              "press num grid h-9 place-items-center rounded-sm border text-md pointer-coarse:h-11",
              on ? "border-act bg-act font-medium text-act-fg" : "border-rule text-ink hover:border-ctl hover:bg-hov",
              invalid && !on && "border-ctl",
            )}
          >
            {d}
          </button>
        )
      })}
    </div>
  )
}
