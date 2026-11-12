import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * 分頁第一行：規則算出來的一句話（不是模型寫的），所以是墨色 Noto Sans、關鍵數字 600；
 * 沒有值得說的就不出現。數字用 `<Fig>` 包起來。
 */
export function TabLead({ children, className }: { children?: React.ReactNode; className?: string }) {
  if (!children) return null
  return <p className={cn("mb-4 max-w-prose text-base text-ink", className)}>{children}</p>
}

/** 規則句子裡的關鍵數字：600、等寬 */
export function Fig({ children }: { children: React.ReactNode }) {
  return <span className="num font-semibold">{children}</span>
}

/** 鍵值格：格線分隔，3 欄（手機 2 欄），數字等寬靠右；`wide` 的格子在手機佔滿一列（值比較長時） */
export function KeyGrid({ items, className, cols = 3 }: { items: KeyItem[]; className?: string; cols?: 2 | 3 }) {
  return (
    <dl className={cn("grid grid-cols-2 gap-x-8 border-t border-rule", cols === 3 && "lg:grid-cols-3", className)}>
      {items.map((it) => (
        <div key={it.label} className={cn("flex min-h-11 items-baseline justify-between gap-3 border-b border-rule py-2.5", it.wide && "max-lg:col-span-2")} title={it.title}>
          <dt className="text-md whitespace-nowrap text-ink-2">{it.label}</dt>
          <dd className="num text-right text-base text-ink">{it.value}</dd>
        </div>
      ))}
    </dl>
  )
}
export type KeyItem = { label: string; value: React.ReactNode; title?: string; wide?: boolean }

/** 設計過的空狀態：說明為什麼沒有、什麼時候會有 */
export function NotYet({ title, children, className }: { title: string; children?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("border-y border-dashed border-ctl py-5", className)}>
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-prose text-md text-ink-2">{children}</div>}
    </div>
  )
}

/**
 * 總覽第三層（新聞、關於、相關股票、法人觀點）的區塊：標題 17px、底下一條格線，比第二層安靜。
 * 沒有說明段落；動作放右邊。
 */
export function QuietSection({
  title,
  titleId,
  action,
  children,
  className,
}: {
  title: React.ReactNode
  titleId: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section aria-labelledby={titleId} className={cn("flex min-w-0 flex-col", className)}>
      <header className="flex min-h-10 items-end gap-3 border-b border-rule pb-2">
        <h2 id={titleId} className="min-w-0 text-lg font-bold">
          {title}
        </h2>
        {action && <div className="ml-auto flex shrink-0 items-center">{action}</div>}
      </header>
      <div className="pt-1">{children}</div>
    </section>
  )
}

/** 聯絡簿的日期格：「12/10」墨色 500＋「（四）」12px 淡墨，右邊一條格線（`.date-cell`） */
export function DateCell({ date, className }: { date: string; className?: string }) {
  const full = formatDateShort(date)
  const i = full.indexOf("（")
  return (
    <span className={cn("date-cell", className)}>
      {i < 0 ? full : full.slice(0, i)}
      {i >= 0 && <span className="weekday">{full.slice(i)}</span>}
    </span>
  )
}
