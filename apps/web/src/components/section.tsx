import { cn } from "@/lib/utils"

/**
 * 區塊卡片：細線框、10px 圓角、無陰影。首頁用得較寬鬆，細節頁用 dense。
 * 不巢狀：卡片裡不再放卡片。
 */
export function Panel({
  title,
  titleId,
  action,
  children,
  className,
  bodyClassName,
  aside,
  titleSize = "md",
}: {
  titleSize?: "md" | "lg"
  title?: React.ReactNode
  titleId?: string
  action?: React.ReactNode
  aside?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section aria-labelledby={titleId} className={cn("flex min-w-0 flex-col rounded-xl border bg-card text-card-foreground", className)}>
      {(title || action) && (
        <header className="flex min-h-12 items-center gap-3 px-4 pt-3 sm:px-5">
          {title && (
            <h2 id={titleId} className={cn("flex min-w-0 flex-1 items-center gap-2 font-semibold", titleSize === "lg" ? "text-xl" : "text-base")}>
              {title}
            </h2>
          )}
          {aside}
          {action && <div className="ml-auto flex shrink-0 items-center gap-1">{action}</div>}
        </header>
      )}
      <div className={cn("flex-1 px-4 pt-2 pb-4 sm:px-5", bodyClassName)}>{children}</div>
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
    <div className={cn("mb-5 flex flex-wrap items-end gap-x-6 gap-y-3", className)}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-[-0.01em]">{title}</h1>
          {meta}
        </div>
        {description && <p className="mt-1 max-w-prose text-md text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** 指標格：標籤＋數值＋補充 */
export function Stat({ label, value, sub, className }: { label: React.ReactNode; value: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold">{value}</dd>
      {sub && <dd className="text-sm text-muted-foreground">{sub}</dd>}
    </div>
  )
}
