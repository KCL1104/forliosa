import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, DEV_LOGIN } from "@/api"
import { meQuery, qk } from "@/api/queries"
import { useAuthProviders } from "@/api/sharing-queries"
import { ApiError } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { AuthFrame } from "@/app/AuthGate"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { safeNext } from "@/lib/next-path"
import { oauthErrorText } from "@/lib/oauth-errors"
import type { LoginSearch } from "@/router"
import { PlainLink } from "@/app/links"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { cn } from "@/lib/utils"

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
        <p role="alert" className="border-y border-rule py-2.5 text-base">
          {error}
        </p>
      )}
      {search.deleted && !error && (
        <p role="status" className="border-y border-rule py-2.5 text-base">
          你的帳號已經刪除。
        </p>
      )}
      {providers.isError ? (
        <ErrorState title="連不上伺服器" error={providers.error} onRetry={() => void providers.refetch()} retryLabel="重新連線" />
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
              用 Discord 登入
            </Button>
          ) : (
            <p className="text-ink-2">目前沒有開放登入。</p>
          )}
          {(providers.data.dev_login || DEV_LOGIN.form) && <DevLoginForm next={next} />}
        </div>
      )}
      {/* 登入就是同意：兩份文件不用登入就能讀 */}
      <p className="text-sm text-ink-2">
        登入即表示你同意
        <PlainLink to="/terms" className={cn(textAction, "mx-1 text-sm")}>
          服務條款
        </PlainLink>
        與
        <PlainLink to="/privacy" className={cn(textAction, "ml-1 text-sm")}>
          隱私權政策
        </PlainLink>
        。
      </p>
    </AuthFrame>
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
        <p className="text-sm text-ink-2">只在開發環境可用；示範使用者是 demo@forliosa.local。</p>
      </div>
      <Input id="dev-login-email" className="pointer-coarse:h-11" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      {devLogin.error && (
        <FieldError>{missing ? "這個伺服器沒有開放開發登入。" : devLogin.error.message}</FieldError>
      )}
      <Button type="submit" variant="outline" className="self-start" disabled={devLogin.isPending}>
        {devLogin.isPending ? "登入中…" : "以這個 Email 登入"}
      </Button>
    </form>
  )
}
