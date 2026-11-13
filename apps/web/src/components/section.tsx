import { cn } from "@/lib/utils"

/**
 * 區塊（聯絡簿）：沒有卡片外框，只有標題下一條印刷線（--print；列與列之間的格線是 --rule）。格線就是結構。
 * 標題上方留白比下方多。區塊標題全站同一級：20px 700（帳本、個股、群組、成員、設定、資料來源都用這個元件）；
 * 只有個股總覽第三層的參考區塊（`QuietSection`）是 17px。
 */
export function Section({
  title,
  titleId,
  action,
  children,
  className,
  bodyClassName,
  aside,
  id,
}: {
  title?: React.ReactNode
  titleId?: string
  action?: React.ReactNode
  aside?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
  /** 網址錨點（設定頁的 #accounts、#recurring、#delegations） */
  id?: string
}) {
  return (
    <section id={id} aria-labelledby={titleId} className={cn("flex min-w-0 flex-col", className)}>
      {(title || action) && (
        <header className="flex min-h-11 flex-wrap items-end gap-x-3 gap-y-1 border-b border-print pb-2">
          {title && (
            <h2 id={titleId} className="flex min-w-0 items-baseline gap-2 text-xl font-bold">
              {title}
            </h2>
          )}
          {aside && <div className="text-sm text-ink-2">{aside}</div>}
          {action && <div className="ml-auto flex shrink-0 items-center gap-1">{action}</div>}
        </header>
      )}
      <div className={cn("pt-3", bodyClassName)}>{children}</div>
    </section>
  )
}

/** 頁首：標題＋一句說明＋動作 */
export function PageHeader({
  title,
  description,
  actions,
  meta,
  className,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  meta?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("mb-6 flex flex-wrap items-end gap-x-6 gap-y-3", className)}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-2xl font-bold tracking-[-0.01em] lg:text-3xl">{title}</h1>
          {meta}
        </div>
        {description && <p className="mt-1.5 max-w-prose text-base text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** 指標格：標籤＋數值＋補充 */
export function Stat({ label, value, sub, className }: { label: React.ReactNode; value: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="num text-xl font-medium">{value}</dd>
      {sub && <dd className="text-sm text-ink-2">{sub}</dd>}
    </div>
  )
}

/** 示範資料：細框小字（資料狀態，不是品牌） */
export function DemoTag({ className, title }: { className?: string; title?: string }) {
  return (
    <span className={cn("demo-tag", className)} title={title ?? "這裡的數字是示範資料，不代表真實行情"}>
      示範資料
    </span>
  )
}
