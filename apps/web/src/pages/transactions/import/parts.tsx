import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useState } from "react"
import type { ImportPage } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { bodyClass, footerClass } from "./layout"

/** 匯入庫存與匯入對帳單共用的畫面零件：選好的檔案一列、要送出的圖、讀取中、今天還剩幾次（規則在 `./read-utils`） */

/** 額度剩不多、用完時的一行 */
export function QuotaLine({ left, limit, unit = "次" }: { left: number | null; limit: number | null; unit?: string }) {
  if (left === 0) return <p className="text-base text-ink">今天的 {limit} {unit}用完了，明天再匯入。</p>
  if (left !== null && left <= 3) return <p className="text-sm text-ink-2">今天還可以匯入 {left} {unit}。</p>
  return null
}

export function FileRow({ name, status, error, onRemove }: { name: string; status: string | null; error?: string; onRemove: () => void }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule py-2 last:border-b-0">
      <span className="min-w-0 flex-1 truncate text-base text-ink">{name}</span>
      {status && <span className="num text-sm text-ink-2">{status}</span>}
      <button type="button" onClick={onRemove} className={textAction} aria-label={`移除 ${name}`}>
        移除
      </button>
      {error && <FieldError className="w-full">{error}</FieldError>}
    </li>
  )
}


/** 「看要送出的 2 頁」：塗過之後、實際送出去的圖 */
export function Preview({ pages, unit }: { pages: ImportPage[]; unit: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="inline-flex min-h-9 items-center gap-1 text-md text-ink underline decoration-ctl underline-offset-4 hover:decoration-ink pointer-coarse:min-h-11"
      >
        看要送出的 {pages.length} {unit}
        <ChevronDownIcon aria-hidden className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div id={id} className="mt-2 flex max-h-[50dvh] flex-col gap-2 overflow-y-auto">
          {pages.map((p, i) => (
            <img key={i} src={`data:${p.media_type};base64,${p.data}`} alt={`要送出的第 ${i + 1} ${unit}`} className="w-full border border-rule" />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * 讀取中：「正在讀 2 頁…」、已經過了幾秒、取消。實測 10–40 秒（匯入對帳單，同一個模型）；
 * 超過 45 秒照實說比平常久，不假裝快好了。
 */
export function Reading({ label, sheet, onCancel }: { label: string; sheet: boolean; onCancel: () => void }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [])
  return (
    <>
      <div className={cn(bodyClass(sheet), "flex flex-col items-start gap-1.5 py-6")} aria-busy="true">
        <p className="text-lg font-medium text-ink" role="status">
          {label}
        </p>
        <p className="num text-sm text-ink-2">
          {seconds > 45 ? `比平常久，已經 ${seconds} 秒，還在讀。` : `通常要 10 到 40 秒${seconds >= 3 ? `，已經 ${seconds} 秒` : ""}。`}
        </p>
      </div>
      <div className={footerClass(sheet)}>
        <Button type="button" variant="outline" className={cn("ml-auto", sheet ? "flex-1" : "min-w-24")} onClick={onCancel}>
          取消
        </Button>
      </div>
    </>
  )
}
