import { useEffect, useId, useRef, useState } from "react"
import { useUpdateAllocationLimits } from "@/api/queries"
import { ApiError, type AllocationLimits } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer"
import { limitText, parseLimit } from "@/lib/allocation"
import { cn } from "@/lib/utils"

/** 輸入框的字：0.3 → "30"、0.125 → "12.5"；沒設是空的 */
const toText = (v: number | null) => (v === null ? "" : String(Math.round(v * 1000) / 10))

/** 自己設的上限，一行：「單一個股 30%・單一產業 50%」；沒設的寫「沒設」 */
export function LimitValues({ limits, className }: { limits: AllocationLimits; className?: string }) {
  return (
    <span className={cn("num inline-flex flex-wrap items-baseline gap-x-3.5 gap-y-0.5", className)}>
      <span className="whitespace-nowrap">
        <span className="mr-1.5 text-sm text-ink-2">單一個股</span>
        {limits.holding === null ? <span className="text-ink-2">沒設</span> : limitText(limits.holding)}
      </span>
      <span className="whitespace-nowrap">
        <span className="mr-1.5 text-sm text-ink-2">單一產業</span>
        {limits.industry === null ? <span className="text-ink-2">沒設</span> : limitText(limits.industry)}
      </span>
    </span>
  )
}

/** 桌面的編輯區（「修改」按鈕的 aria-controls） */
export const LIMITS_EDITOR_ID = "allocation-limits-editor"

/**
 * 設定上限的表單（產品負責人 2026-11-18：預設不標示，使用者自己設了才標）：單一個股、單一產業兩個百分比，空的＝不設。
 * 桌面直接在集中度下面展開（不跳對話框）；手機是底部抽屜。儲存＝整組取代；「清除上限」兩個都不設。
 * 打開時焦點在第一格（抽屜也是，和記一筆一樣）。抽屜關閉的動畫期間表單還在（不先縮成只剩標題再滑走）；
 * 每次打開都是新的表單（key），上次沒存的字不留。
 */
export function LimitsEditor({ limits, mode, open, onClose }: { limits: AllocationLimits; mode: "inline" | "sheet"; open: boolean; onClose: () => void }) {
  const [round, setRound] = useState(0)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setRound((r) => r + 1)
  }
  if (mode === "sheet") {
    return (
      <Drawer open={open} onOpenChange={(o) => !o && onClose()} repositionInputs={false}>
        <DrawerContent>
          <DrawerHeader className="pb-0">
            <DrawerTitle>設定上限</DrawerTitle>
            <DrawerDescription>超過時，配置和 AI 都會標出來。</DrawerDescription>
          </DrawerHeader>
          <LimitsForm key={round} limits={limits} onDone={onClose} className="safe-bottom px-4 pb-4" />
        </DrawerContent>
      </Drawer>
    )
  }
  if (!open) return null
  return (
    <section id={LIMITS_EDITOR_ID} aria-labelledby="limits-title" className="border-b border-rule pt-4 pb-5">
      <h3 id="limits-title" className="text-lg font-bold">
        設定上限
      </h3>
      <p className="mt-1 text-base text-ink">超過時，配置和 AI 都會標出來。</p>
      <LimitsForm limits={limits} onDone={onClose} inline />
    </section>
  )
}

function LimitsForm({ limits, onDone, inline, className }: { limits: AllocationLimits; onDone: () => void; inline?: boolean; className?: string }) {
  const [holding, setHolding] = useState(toText(limits.holding))
  const [industry, setIndustry] = useState(toText(limits.industry))
  const [submitted, setSubmitted] = useState(false)
  const save = useUpdateAllocationLimits()
  const first = useRef<HTMLInputElement>(null)
  const second = useRef<HTMLInputElement>(null)
  const errorId = useId()
  const h = parseLimit(holding)
  const i = parseLimit(industry)
  const invalid = h === undefined || i === undefined
  // 打開就可以輸入：桌面展開、手機抽屜都把焦點放在第一格（Vaul 預設不移焦點，Tab 會跑到後面的頁面）
  useEffect(() => {
    first.current?.focus()
  }, [])

  const submit = (next: AllocationLimits) =>
    save.mutate(next, { onSuccess: () => onDone() })
  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (invalid) {
      // 焦點移到第一個有錯的欄位（和記一筆、匯入一樣）
      const bad = h === undefined ? first : second
      bad.current?.focus()
      return
    }
    submit({ holding: h, industry: i })
  }
  const error = save.error instanceof ApiError ? save.error.message : save.error ? "沒有存到，請再試一次。" : null
  const hasAny = limits.holding !== null || limits.industry !== null

  return (
    <form
      noValidate
      onSubmit={onSubmit}
      onKeyDown={(e) => {
        if (inline && e.key === "Escape") {
          e.preventDefault()
          onDone()
        }
      }}
      className={className}
    >
      <div className={cn("mt-4 border-t border-rule", inline && "lg:grid lg:grid-cols-2 lg:gap-x-8")}>
        <LimitField ref={first} label="單一個股" hint="每一檔佔總市值，ETF 不算" value={holding} onChange={setHolding} invalid={submitted && h === undefined} errorId={errorId} />
        <LimitField ref={second} label="單一產業" hint="不含 ETF" value={industry} onChange={setIndustry} invalid={submitted && i === undefined} errorId={errorId} />
      </div>
      {submitted && invalid && (
        <FieldError id={errorId} className="mt-2">
          上限要在 1% 到 100% 之間，或留空不設。
        </FieldError>
      )}
      {error && <FieldError className="mt-2">{error}</FieldError>}
      <div className={cn("mt-5 flex items-center gap-2", inline ? "flex-wrap justify-end gap-x-3" : "flex-col items-stretch")}>
        {inline && hasAny && (
          <button type="button" className={cn(textAction, "mr-auto")} disabled={save.isPending} onClick={() => submit({ holding: null, industry: null })}>
            清除上限
          </button>
        )}
        <div className={cn("flex gap-2", !inline && "w-full")}>
          <Button type="button" variant="outline" className={cn(!inline && "flex-1")} onClick={onDone}>
            取消
          </Button>
          <Button type="submit" variant="sign" className={cn(!inline && "flex-1")} disabled={save.isPending}>
            {save.isPending ? "儲存中…" : "儲存"}
          </Button>
        </div>
        {!inline && hasAny && (
          <button type="button" className={cn(textAction, "mx-auto mt-2")} disabled={save.isPending} onClick={() => submit({ holding: null, industry: null })}>
            清除上限
          </button>
        )}
      </div>
    </form>
  )
}

function LimitField({
  ref,
  label,
  hint,
  value,
  onChange,
  invalid,
  errorId,
}: {
  ref?: React.Ref<HTMLInputElement>
  label: string
  hint: string
  value: string
  onChange: (v: string) => void
  invalid: boolean
  /** 錯誤訊息的 id：這一格有錯時用 aria-describedby 指過去 */
  errorId: string
}) {
  const id = useId()
  return (
    <div className="grid min-h-16 grid-cols-[minmax(0,1fr)_7.5rem] items-center gap-3 border-b border-rule py-2">
      {/* 欄位名稱帶「百分比」：畫面上的「%」只是字尾（aria-hidden），報讀器要知道填的是 30 不是 0.3 */}
      <label htmlFor={id} className="text-base text-ink">
        {label}
        <span className="sr-only">（百分比）</span>
        <small className="block text-sm text-ink-2">{hint}</small>
      </label>
      <span className="flex h-11 items-center rounded-sm border border-ctl bg-raised pr-3 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ink has-[[aria-invalid=true]]:border-ink lg:h-10 pointer-coarse:h-11">
        <input
          ref={ref}
          id={id}
          inputMode="decimal"
          enterKeyHint="done"
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="不設"
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? errorId : undefined}
          className="num h-full w-full min-w-0 bg-transparent pl-3 text-right text-base outline-none placeholder:text-ink-2 pointer-coarse:text-[1rem]"
        />
        <span aria-hidden className="ml-1.5 text-ink-2">
          %
        </span>
      </span>
    </div>
  )
}
