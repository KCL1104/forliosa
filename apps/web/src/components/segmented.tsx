import { ScrollRow } from "@/components/scroll-row"
import { cn } from "@/lib/utils"

/**
 * 區間選擇（1日…全部、季／年…）：role=radiogroup，方向鍵切換。
 * 選取＝選取語法 (b)（`sel-chip`：淺色墨色實底；深色格線藍底＋內框）。
 * 放不下時橫向捲動（ScrollRow）：被遮住的一邊淡出，選取中的選項捲進畫面。
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
    <ScrollRow role="radiogroup" aria-label={label} className={cn("-mx-1 items-center gap-0.5 px-1 py-0.5", className)}>
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
            className="press sel-chip h-8 shrink-0 rounded-sm px-2.5 text-sm text-ink-2 pointer-coarse:h-11 pointer-coarse:px-3"
          >
            {o.label}
          </button>
        )
      })}
    </ScrollRow>
  )
}

/**
 * 分段（帳本：持倉・交易・股利・績效）：1px 鉛筆灰外框，選取＝選取語法 (b)（`sel-chip`）。
 * role=tablist；方向鍵切換。觸控與手機版面每一段 44px 高。
 * `shortcut`：這一段的鍵盤快速鍵（由頁面自己處理按鍵；這裡只用 `aria-keyshortcuts` 告訴輔助科技）。
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
  options: readonly { value: T; label: string; count?: number | null; shortcut?: string }[]
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
    <div role="tablist" aria-label={label} className={cn("flex gap-1 rounded-md border border-ctl p-1 max-lg:p-[3px]", className)}>
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
            aria-keyshortcuts={o.shortcut}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => onKeyDown(e, i)}
            onClick={() => onChange(o.value)}
            className="press sel-chip relative flex h-[34px] items-center justify-center gap-1.5 rounded-sm px-4 text-base text-ink-2 before:absolute before:inset-x-0 before:-inset-y-1 max-lg:h-11 max-lg:flex-1 max-lg:px-2 pointer-coarse:h-11"
          >
            {o.label}
            {o.count !== undefined && o.count !== null && <span className="num text-sm font-normal opacity-85 max-lg:hidden">{o.count}</span>}
          </button>
        )
      })}
    </div>
  )
}
