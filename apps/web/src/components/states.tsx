import { RotateCcwIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError } from "@/api/types"
import { cn } from "@/lib/utils"

/** 錯誤狀態：說明問題＋可以做什麼 */
export function ErrorState({
  error,
  onRetry,
  className,
  title = "這裡的資料沒有載入",
}: {
  error: unknown
  onRetry?: () => void
  className?: string
  title?: string
}) {
  const message =
    error instanceof ApiError
      ? error.status === 401
        ? "登入已過期，請重新登入後再試一次。"
        : error.message
      : "可能是網路不穩或伺服器暫時沒有回應。"
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-3 rounded-xl border border-dashed p-5", className)}>
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-md text-muted-foreground">{message}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCcwIcon />
          重新載入
        </Button>
      )}
    </div>
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
  return <Skeleton className={cn("w-full rounded-lg", className)} style={{ height }} aria-label="圖表載入中" />
}

/** 空狀態：說明這裡會出現什麼，並給一個下一步 */
export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col items-start gap-3 rounded-xl border border-dashed p-6", className)}>
      <div className="flex flex-col gap-1">
        <p className="font-medium">{title}</p>
        {description && <p className="max-w-prose text-md text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  )
}
