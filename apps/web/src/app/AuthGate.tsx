import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { LogInIcon, RotateCcwIcon } from "lucide-react"
import { useState } from "react"
import { api, DEV_LOGIN } from "@/api"
import { meQuery, qk } from "@/api/queries"
import { ApiError } from "@/api/types"
import { Wordmark } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"

/**
 * 登入閘門：先確認 `GET /me`，有 session 才渲染 App（其他請求不會先吃到一堆 401）。
 * - 開發模式連真實後端：沒有 session 時自動 `POST /auth/dev-login`（示範使用者，見 queries.ts 的 fetchMe）。
 * - 其他情況的 401：說明正式登入尚未推出；開發／staging 建置附上開發登入表單。
 * Session 過期時，任何 401 都會重設 `me`（見 main.tsx），回到這裡。
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient()
  const me = useQuery(meQuery())
  const unauthorized = me.error instanceof ApiError && me.error.status === 401
  const devLogin = useMutation({
    mutationFn: (email: string) => api.devLogin({ email }),
    onSuccess: (user) => {
      qc.setQueryData(qk.me, user)
      // 登入前快取的任何東西（例如 session 過期時的 401）都重新抓
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== qk.me[0] })
    },
  })

  if (me.data) return <>{children}</>
  if (unauthorized) {
    return <SignInRequired onDevLogin={(email) => devLogin.mutate(email)} pending={devLogin.isPending} error={devLogin.error} />
  }
  if (me.isError) return <BackendUnreachable error={me.error} onRetry={() => void me.refetch()} />
  return <BootScreen />
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-6 px-4 py-10">
      <Wordmark />
      {children}
    </main>
  )
}

function BootScreen() {
  return (
    <Frame>
      <div className="flex flex-col gap-3" aria-busy="true" aria-label="載入中">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    </Frame>
  )
}

function BackendUnreachable({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <Frame>
      <div role="alert" className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-[-0.01em]">連不上伺服器</h1>
        <p className="text-muted-foreground">
          {error instanceof ApiError ? error.message : "可能是網路不穩，或後端還沒啟動。"}
          {import.meta.env.DEV && "開發時請先在 apps/api 執行 uv run uvicorn forliosa.main:app --port 8000。"}
        </p>
        <Button variant="outline" className="self-start" onClick={onRetry}>
          <RotateCcwIcon />
          重新連線
        </Button>
      </div>
    </Frame>
  )
}

/**
 * 401：還沒有 session。
 * TODO(auth): 正式登入（Email magic link、Google OAuth）完成後，這裡放正式的登入方式；
 * 後端 `FORLIOSA_ENV=prod` 時開發登入是關閉的，所以目前的正式環境無法登入。
 */
function SignInRequired({ onDevLogin, pending, error }: { onDevLogin: (email: string) => void; pending: boolean; error: Error | null }) {
  const [email, setEmail] = useState<string>(DEV_LOGIN.email)
  const devLoginMissing = error instanceof ApiError && error.status === 404
  return (
    <Frame>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-[-0.01em]">請先登入</h1>
        <p className="text-muted-foreground">
          你的帳本、持股與績效只有登入後才看得到。正式的登入方式（Email、Google）還在開發中，目前只有開發環境可以登入。
        </p>
      </div>
      {DEV_LOGIN.form && (
        <form
          className="flex flex-col gap-3 rounded-sm border border-rule bg-raised p-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (email.trim()) onDevLogin(email.trim())
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="dev-login-email" className="text-md font-medium">
              開發登入
            </label>
            <p className="text-sm text-muted-foreground">只在後端 FORLIOSA_ENV=dev 時可用；示範使用者是 demo@forliosa.local。</p>
          </div>
          <Input id="dev-login-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {devLoginMissing ? "這個後端沒有開放開發登入（FORLIOSA_ENV 不是 dev）。" : error.message}
            </p>
          )}
          <Button type="submit" className="self-start" disabled={pending}>
            <LogInIcon />
            {pending ? "登入中…" : "以這個 Email 登入"}
          </Button>
        </form>
      )}
    </Frame>
  )
}
