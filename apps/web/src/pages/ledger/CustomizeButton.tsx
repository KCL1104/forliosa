import { PinIcon, SlidersHorizontalIcon } from "lucide-react"
import { useRef, useState } from "react"
import { useHoldings } from "@/api/queries"
import { useReadOnly } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { ALL_COLUMNS, COLUMN_HINT, useLedgerPrefs } from "./ledger-prefs"
import { useColumnLabel } from "./use-column-label"

/**
 * 自訂：選欄位、隱藏走勢圖、釘選持股（存在這台瀏覽器）。最下面一條格線之後是「清除所有持倉…」（產品負責人 2026-11-17；
 * 確認框見 `ClearRecordsDialog`，主要入口在設定「帳號與資料」）：選單裡的破壞性動作放最後、上面一條格線、淡墨、不用紅色
 * （和「刪除這檔」「移出群組」同一套）。查看別人的資產時沒有。
 */
export function CustomizeButton({ className }: { className?: string }) {
  const columns = useLedgerPrefs((s) => s.columns)
  const toggleColumn = useLedgerPrefs((s) => s.toggleColumn)
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const setShowTrend = useLedgerPrefs((s) => s.setShowTrend)
  const pinned = useLedgerPrefs((s) => s.pinned)
  const togglePin = useLedgerPrefs((s) => s.togglePin)
  const reset = useLedgerPrefs((s) => s.reset)
  const holdings = useHoldings()
  const label = useColumnLabel()
  const readOnly = useReadOnly()
  const openClear = useUi((s) => s.openClearRecords)
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            ref={trigger}
            type="button"
            aria-label="自訂欄位與顯示"
            title="自訂"
            className={cn("press grid size-10 place-items-center rounded-sm border border-ctl text-ink-2 hover:bg-hov hover:text-ink aria-expanded:bg-hov", className)}
          />
        }
      >
        <SlidersHorizontalIcon aria-hidden className="size-[18px]" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 gap-0 p-0">
        {/* 不用 fieldset＋浮動的 legend：浮動佔滿整列時，後面的格線會被擠到右邊只剩一個字寬 */}
        <div role="group" aria-labelledby="ledger-columns-title" className="border-b border-rule px-4 py-3">
          <p id="ledger-columns-title" className="mb-2 text-sm font-bold text-ink">欄位</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            {ALL_COLUMNS.map((c) => (
              <label key={c} title={COLUMN_HINT[c]} className={cn("flex min-h-9 min-w-0 items-center gap-2 text-md pointer-coarse:min-h-11", c === "price" && "text-ink-2")}>
                <input type="checkbox" className="size-4 shrink-0 accent-[var(--ink)]" checked={columns.includes(c)} disabled={c === "price"} onChange={() => toggleColumn(c)} />
                {label(c)}
              </label>
            ))}
          </div>
        </div>
        <label className="flex min-h-12 items-center gap-2 border-b border-rule px-4 text-md">
          <input type="checkbox" className="size-4 shrink-0 accent-[var(--ink)]" checked={showTrend} onChange={(e) => setShowTrend(e.target.checked)} />
          顯示總資產走勢圖
        </label>
        <div className="px-4 py-3">
          <p className="mb-1 text-sm font-bold">釘選持股（排在最上面）</p>
          <ul className="max-h-56 overflow-y-auto">
            {(holdings.data ?? []).map((h) => {
              const on = pinned.includes(h.symbol)
              return (
                <li key={h.symbol}>
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() => togglePin(h.symbol)}
                    className="flex min-h-9 w-full items-center gap-2 rounded-sm px-1 text-left text-md hover:bg-hov pointer-coarse:min-h-11"
                  >
                    <PinIcon aria-hidden className={cn("size-4", on ? "fill-ink text-ink" : "text-ctl")} />
                    <span className="flex-1 truncate">{h.name}</span>
                    <span className="num text-sm text-ink-2">{h.code}</span>
                  </button>
                </li>
              )
            })}
          </ul>
          <button type="button" onClick={reset} className="mt-2 text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink pointer-coarse:min-h-11">
            還原預設
          </button>
        </div>
        {!readOnly && (
          <div className="border-t border-rule px-4 py-2">
            <button
              type="button"
              onClick={() => {
                // 先關選單（連結跟著卸載），確認框關掉後焦點回到「自訂」
                setOpen(false)
                openClear(trigger.current)
              }}
              className="flex min-h-9 w-full items-center text-left text-md text-ink-2 hover:text-ink pointer-coarse:min-h-11"
            >
              清除所有持倉…
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
