import { ChevronDownIcon } from "lucide-react"
import { useId, useState } from "react"
import { cn } from "@/lib/utils"

/**
 * 「怎麼看 ⌄」：術語的說明（「每條帶是…」「近 12 個月現金股利 ÷ 收盤價」）預設收著，要看才打開。
 * 和草稿卡的「怎麼算的 ⌄」同一種語法（小字、常駐底線、⌄ 打開時轉向），只是墨色（不是 AI 的東西）。
 * 開關和說明可以放在不同地方（開關在區塊標題右邊、說明在內容最上面），所以是一個 hook。
 */
export function useHowToRead(label = "怎麼看") {
  const [open, setOpen] = useState(false)
  const id = useId()
  const toggle = (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={id}
      onClick={() => setOpen(!open)}
      className="group inline-flex min-h-8 items-end gap-0.5 rounded-xs pb-px text-sm text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink pointer-coarse:min-h-11"
    >
      {label}
      <ChevronDownIcon aria-hidden className={cn("mb-0.5 size-3.5 transition-transform duration-150 motion-reduce:transition-none", open && "rotate-180")} />
    </button>
  )
  const panel = (children: React.ReactNode, className?: string) => (
    <div id={id} hidden={!open} className={cn("max-w-prose text-sm text-ink-2", className)}>
      {children}
    </div>
  )
  return { open, toggle, panel }
}
