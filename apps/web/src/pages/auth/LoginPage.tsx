import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { LogInIcon, RotateCcwIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { api, DEV_LOGIN } from "@/api"
import { meQuery, qk } from "@/api/queries"
import { useAuthProviders } from "@/api/sharing-queries"
import { ApiError } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { AuthFrame } from "@/app/AuthGate"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { safeNext } from "@/lib/next-path"
import { oauthErrorText } from "@/lib/oauth-errors"
import type { LoginSearch } from "@/router"

/** 登入：用 Discord 登入（第一次登入就建立帳號）；開發環境另有開發登入 */
export function LoginPage() {
  const search = useSearch({ from: "/login" }) as LoginSearch
  const next = safeNext(search.next)
  const navigate = useNavigate()
  const me = useQuery(meQuery())
  const providers = useAuthProviders()
  const error = oauthErrorText(search.error)

  // 已經登入（例如從書籤回到登入頁）：直接回去
  const signedIn = !!me.data && !error
  useEffect(() => {
    if (signedIn) void navigate({ href: next, replace: true })
  }, [signedIn, next, navigate])
  if (signedIn) return null

  return (
    <AuthFrame>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-[-0.01em]">登入</h1>
        <p className="text-ink-2">{next.startsWith("/invite/") ? "登入後回到邀請，選好要分享什麼再加入群組。" : "第一次用 Discord 登入時會自動建立帳號。"}</p>
      </div>
      {error && (
        <p role="alert" className="border-l-2 border-ink py-1 pl-3 text-base">
          {error}
        </p>
      )}
      {providers.isError ? (
        <BackendUnreachableInline error={providers.error} onRetry={() => void providers.refetch()} />
      ) : !providers.data ? (
        <Skeleton className="h-11 w-full" />
      ) : (
        <div className="flex flex-col gap-4">
          {providers.data.discord ? (
            <Button
              size="lg"
              className="w-full"
              onClick={() => {
                // 先離開查看模式：登入的是自己
                useViewAs.getState().set(null)
                window.location.assign(api.discordLoginUrl(next))
              }}
            >
              <LogInIcon />
              用 Discord 登入
            </Button>
          ) : (
            <p className="text-ink-2">目前沒有開放登入。</p>
          )}
          {(providers.data.dev_login || DEV_LOGIN.form) && <DevLoginForm next={next} />}
        </div>
      )}
    </AuthFrame>
  )
}

function BackendUnreachableInline({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3">
      <div>
        <p className="font-medium">連不上伺服器</p>
        <p className="text-md text-ink-2">{error instanceof ApiError ? error.message : "可能是網路不穩，或後端還沒啟動。"}</p>
      </div>
      <Button variant="outline" onClick={onRetry}>
        <RotateCcwIcon />
        重新連線
      </Button>
    </div>
  )
}

/** 開發登入（後端只在 FORLIOSA_ENV=dev 開放） */
function DevLoginForm({ next }: { next: string }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [email, setEmail] = useState<string>(DEV_LOGIN.email)
  const devLogin = useMutation({
    mutationFn: (value: string) => api.devLogin({ email: value }),
    onSuccess: (user) => {
      qc.setQueryData(qk.me, user)
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== qk.me[0] })
      void navigate({ href: next, replace: true })
    },
  })
  const missing = devLogin.error instanceof ApiError && devLogin.error.status === 404
  return (
    <form
      className="flex flex-col gap-3 border-t border-rule pt-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (email.trim()) devLogin.mutate(email.trim())
      }}
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="dev-login-email" className="text-md font-medium">
          開發登入
        </label>
        <p className="text-sm text-ink-2">只在後端 FORLIOSA_ENV=dev 時可用；示範使用者是 demo@forliosa.local。</p>
      </div>
      <Input id="dev-login-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      {devLogin.error && (
        <p role="alert" className="text-sm text-destructive">
          {missing ? "這個後端沒有開放開發登入（FORLIOSA_ENV 不是 dev）。" : devLogin.error.message}
        </p>
      )}
      <Button type="submit" variant="outline" className="self-start" disabled={devLogin.isPending}>
        {devLogin.isPending ? "登入中…" : "以這個 Email 登入"}
      </Button>
    </form>
  )
}
