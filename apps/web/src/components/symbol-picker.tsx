import { Command as CommandPrimitive } from "cmdk"
import { XIcon } from "lucide-react"
import { useId, useState } from "react"
import { useInstrumentSearch } from "@/api/queries"
import type { Instrument } from "@/api/types"
import { Button } from "@/components/ui/button"
import { marketTag } from "@/lib/labels"
import { cn } from "@/lib/utils"

/**
 * 代號搜尋（cmdk，支援中文股名）：交易表單與定期定額共用。
 * `accept` 過濾可選的商品（例如定期定額只收台股與 ETF），不符合的列出但不能選，並說明原因。
 */
export function SymbolPicker({
  value,
  onChange,
  invalid,
  accept,
  rejectReason,
  label = "搜尋股票",
}: {
  value: Instrument | null
  onChange: (i: Instrument | null) => void
  invalid?: boolean
  accept?: (i: Instrument) => boolean
  /** 不能選的原因（每一檔可以不同，例如持股的輸入：「幣別不同」「已經在上面」） */
  rejectReason?: string | ((i: Instrument) => string)
  /** 輸入框的無障礙名稱（cmdk 自己產生 id 與 label，外面的 htmlFor 對不上，所以名稱從這裡給） */
  label?: string
}) {
  const [q, setQ] = useState("")
  const [active, setActive] = useState("")
  const search = useInstrumentSearch(q)
  const listId = useId()
  if (value) {
    return (
      <div className="flex h-10 items-center gap-2 rounded-md border border-input bg-raised px-3 pointer-coarse:h-11">
        <span className="num font-semibold">{value.code}</span>
        <span className="min-w-0 flex-1 truncate">{value.name}</span>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="改選其他股票" onClick={() => onChange(null)}>
          <XIcon />
        </Button>
      </div>
    )
  }
  const results = search.data ?? []
  const selectable = results.filter((i) => !accept || accept(i))
  // 非同步結果：選取不在清單裡時改選第一個可選的，打字後直接按 Enter 就能選
  const selected = selectable.some((i) => i.symbol === active) ? active : (selectable[0]?.symbol ?? "")
  return (
    <CommandPrimitive shouldFilter={false} value={selected} onValueChange={setActive} label={label} className="relative">
      <CommandPrimitive.Input
        value={q}
        onValueChange={setQ}
        placeholder="代號或名稱，例如 2330、台積"
        aria-invalid={invalid}
        aria-controls={listId}
        className={cn(
          "h-10 w-full rounded-md border border-input bg-raised px-3 text-base outline-none pointer-coarse:text-[1rem] pointer-coarse:h-11 placeholder:text-ink-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-md",
          invalid && "border-destructive",
        )}
        autoComplete="off"
        enterKeyHint="search"
      />
      {q.trim() && (
        <CommandPrimitive.List id={listId} className="mt-1 max-h-56 overflow-y-auto rounded-md border bg-popover p-1 shadow-md">
          {!search.isFetching && results.length === 0 && (
            <CommandPrimitive.Empty className="px-2 py-3 text-md text-ink-2">找不到「{q.trim()}」</CommandPrimitive.Empty>
          )}
          {results.map((i) => {
            const ok = !accept || accept(i)
            return (
              <CommandPrimitive.Item
                key={i.symbol}
                value={i.symbol}
                disabled={!ok}
                onSelect={() => {
                  if (!ok) return
                  onChange(i)
                  setQ("")
                }}
                className="flex min-h-10 cursor-pointer items-center gap-3 rounded-sm px-2 text-md data-[disabled=true]:cursor-not-allowed data-[disabled=true]:text-ink-2 data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground pointer-coarse:min-h-11"
              >
                <span className="num w-14 shrink-0 font-semibold">{i.code}</span>
                <span className="min-w-0 flex-1 truncate">{i.name}</span>
                <span className="text-xs text-ink-2">{ok ? marketTag(i) : ((typeof rejectReason === "function" ? rejectReason(i) : rejectReason) ?? "不能選")}</span>
              </CommandPrimitive.Item>
            )
          })}
        </CommandPrimitive.List>
      )}
    </CommandPrimitive>
  )
}
