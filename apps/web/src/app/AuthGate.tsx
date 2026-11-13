import { useQuery } from "@tanstack/react-query"
import { Navigate, useRouterState } from "@tanstack/react-router"
import { useEffect } from "react"
import { meQuery } from "@/api/queries"
import { ApiError } from "@/api/types"
import { Wordmark } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { claimLocalUserData } from "@/lib/local-data"
import { safeNext } from "@/lib/next-path"
import { cn } from "@/lib/utils"

/**
 * 登入閘門：先確認 `GET /me`，有 session 才渲染 App（其他請求不會先吃到一堆 401）。
 * - 開發模式連真實後端：沒有 session 時自動 `POST /auth/dev-login`（示範使用者，見 queries.ts 的 fetchMe）。
 * - 其他情況的 401：到登入頁（`/login?next=<現在的網址>`），登入後回到這裡。
 * - `signedOut`：這一頁不用登入就能讀（公開討論）——401 時不導到登入頁，改顯示它（精簡的外殼）。
 * Session 過期時，任何 401 都會重設 `me`（見 main.tsx），回到這裡。
 */
export function AuthGate({ children, signedOut }: { children: React.ReactNode; signedOut?: React.ReactNode }) {
  const me = useQuery(meQuery())
  const href = useRouterState({ select: (s) => s.location.href })
  const unauthorized = me.error instanceof ApiError && me.error.status === 401
  // 這台瀏覽器存著的 AI 對話如果是上一個人的，在畫面出來之前清掉（同一個人則保留）
  const userId = me.data?.id
  useEffect(() => {
    if (userId) claimLocalUserData(userId)
  }, [userId])

  if (me.data) return <>{children}</>
  if (unauthorized && signedOut) return <>{signedOut}</>
  if (unauthorized) {
    const next = safeNext(href)
    return <Navigate to="/login" search={next === "/" ? {} : { next }} replace />
  }
  if (me.isError) return <BackendUnreachable error={me.error} onRetry={() => void me.refetch()} />
  return <BootScreen />
}

/**
 * 還沒進到 App 的畫面（登入、載入中、連不上）：字標＋一欄內容，垂直置中。
 * `center`（登入頁）：內容也水平置中、欄窄一點（384px）——畫面上只有字標、標題和登入按鈕。
 */
export function AuthFrame({ children, center }: { children: React.ReactNode; center?: boolean }) {
  return (
    <main className={cn("mx-auto flex min-h-dvh w-full flex-col justify-center gap-6 px-5 py-10", center ? "max-w-sm items-center text-center" : "max-w-md")}>
      <Wordmark />
      {children}
    </main>
  )
}

function BootScreen() {
  return (
    <AuthFrame>
      <div className="flex flex-col gap-3" aria-busy="true" aria-label="載入中">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    </AuthFrame>
  )
}

export function BackendUnreachable({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <AuthFrame>
      <div role="alert" className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-[-0.01em]">連不上伺服器</h1>
        <p className="text-muted-foreground">
          {error instanceof ApiError ? error.message : "可能是網路不穩，或伺服器暫時沒有回應。"}
          {import.meta.env.DEV && "開發時請先在 apps/api 執行 uv run uvicorn forliosa.main:app --port 8000。"}
        </p>
        <Button variant="outline" className="self-start" onClick={onRetry}>
          重新連線
        </Button>
      </div>
    </AuthFrame>
  )
}
