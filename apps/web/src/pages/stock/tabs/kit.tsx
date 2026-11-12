import { cn } from "@/lib/utils"

/** 分頁第一行：規則產生的一句話（紫色文楷＝AI 的聲音），沒有值得說的就不出現 */
export function TabLead({ children, className }: { children?: React.ReactNode; className?: string }) {
  if (!children) return null
  return <p className={cn("ai-voice mb-5 text-xl leading-snug", className)}>{children}</p>
}

/** 鍵值格：格線分隔，3 欄（手機 2 欄），數字等寬靠右 */
export function KeyGrid({ items, className, cols = 3 }: { items: { label: string; value: React.ReactNode; title?: string }[]; className?: string; cols?: 2 | 3 }) {
  return (
    <dl className={cn("grid grid-cols-2 gap-x-8 border-t border-rule", cols === 3 && "lg:grid-cols-3", className)}>
      {items.map((it) => (
        <div key={it.label} className="flex min-h-11 items-baseline justify-between gap-3 border-b border-rule py-2.5" title={it.title}>
          <dt className="text-md whitespace-nowrap text-ink-2">{it.label}</dt>
          <dd className="num text-right text-base">{it.value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** 設計過的空狀態：說明為什麼沒有、什麼時候會有 */
export function NotYet({ title, children, className }: { title: string; children?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("border-y border-dashed border-ctl py-5", className)}>
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-prose text-md text-ink-2">{children}</div>}
    </div>
  )
}

export function Sources({ items, className }: { items: string[]; className?: string }) {
  if (items.length === 0) return null
  return <p className={cn("mt-3 text-xs text-ink-2", className)}>資料來源：{items.join("；")}</p>
}
