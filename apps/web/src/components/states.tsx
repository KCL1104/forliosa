import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError } from "@/api/types"
import { cn } from "@/lib/utils"

/**
 * 空狀態與錯誤的同一種樣子（全站只有這一種，見 DESIGN.md「空狀態」）：
 * 上下各一條實線格線（沒有外框、沒有底色）、15px 墨色 600 標題、淡墨寫原因、最多一個動作。
 * 虛線在這個系統是「AI 草稿」，這裡不用。
 * `flush`：接在已經有格線的區塊標題下面時，不再畫上面那條線（標題的格線就是上面那條）。
 */
function StateBlock({
  title,
  children,
  action,
  flush,
  className,
  ...props
}: {
  title: string
  children?: React.ReactNode
  action?: React.ReactNode
  flush?: boolean
  className?: string
} & Omit<React.ComponentProps<"div">, "title" | "children" | "className">) {
  return (
    <div {...props} className={cn("flex flex-col items-start border-y border-rule py-5", flush && "border-t-0 pt-2", className)}>
      <p className="text-base font-semibold text-ink">{title}</p>
      {children && <div className="mt-1 max-w-prose text-md text-ink-2">{children}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

/** 錯誤狀態：說明問題＋可以做什麼（重新載入） */
export function ErrorState({
  error,
  onRetry,
  className,
  title = "這裡的資料沒有載入",
  retryLabel = "重新載入",
  flush,
}: {
  error: unknown
  onRetry?: () => void
  className?: string
  title?: string
  retryLabel?: string
  flush?: boolean
}) {
  const message =
    error instanceof ApiError
      ? error.status === 401
        ? "登入已過期，請重新登入後再試一次。"
        : error.message
      : "可能是網路不穩或伺服器暫時沒有回應。"
  return (
    <StateBlock
      role="alert"
      title={title}
      flush={flush}
      className={className}
      action={
        onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            {retryLabel}
          </Button>
        )
      }
    >
      {message}
    </StateBlock>
  )
}

/** 骨架：與實際內容同尺寸，不用置中轉圈 */
export function SkeletonLines({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2.5", className)} aria-busy="true" aria-label="載入中">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn("h-4", i === rows - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  )
}

export function ChartSkeleton({ height = 240, className }: { height?: number; className?: string }) {
  return <Skeleton className={cn("w-full rounded-sm", className)} style={{ height }} aria-label="圖表載入中" />
}

/** 空狀態：說明為什麼沒有、什麼時候會有，最多給一個現在能做的動作（outline 按鈕或文字連結） */
export function EmptyState({
  title,
  description,
  action,
  flush,
  className,
}: {
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
  flush?: boolean
  className?: string
}) {
  return (
    <StateBlock title={title} action={action} flush={flush} className={className}>
      {description}
    </StateBlock>
  )
}
