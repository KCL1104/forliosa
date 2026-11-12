import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate, useParams } from "@tanstack/react-router"
import { LogInIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { meQuery } from "@/api/queries"
import { useAcceptInvite, useInvitePreview } from "@/api/sharing-queries"
import { ApiError, type ShareSettings } from "@/api/types"
import { useViewAs } from "@/api/view-as"
import { AuthFrame } from "@/app/AuthGate"
import { switchViewAs } from "@/app/view-as"
import { ErrorState, SkeletonLines } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { DEFAULT_SHARE } from "./labels"
import { ShareToggles } from "./ShareToggles"

/**
 * 邀請連結 `/invite/:token`：不需登入就能預覽（群組名稱、誰邀請的）。
 * 沒登入 → 到登入頁（登入後回到這裡）；已登入 → 先選分享（預設只開報酬率）再加入。
 */
export function InvitePage() {
  const { token } = useParams({ from: "/invite/$token" })
  const qc = useQueryClient()
  // 邀請是自己的事：查看別人的資產時打開邀請，先回到自己的身分
  useEffect(() => {
    if (useViewAs.getState().target) switchViewAs(qc, null)
  }, [qc])
  const preview = useInvitePreview(token)
  const me = useQuery({ ...meQuery(), retry: false })
  const signedOut = me.error instanceof ApiError && me.error.status === 401
  const err = preview.error instanceof ApiError ? preview.error : null

  return (
    <AuthFrame>
      {preview.isLoading || (!signedOut && me.isLoading) ? (
        <SkeletonLines rows={4} />
      ) : err?.status === 404 ? (
        <Gone title="找不到這個邀請連結" body="請確認連結是否完整，或向邀請你的人要一個新的。" signedIn={!!me.data} />
      ) : err?.status === 410 ? (
        <Gone title="這個邀請已經失效" body="邀請可能過期、被撤回，或已經用完。請向邀請你的人要一個新的連結。" signedIn={!!me.data} />
      ) : preview.isError ? (
        <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
      ) : preview.data ? (
        <>
          <header className="flex flex-col gap-1.5">
            <p className="text-base text-ink-2">{preview.data.inviter_display_name} 邀請你加入</p>
            <h1 className="text-3xl font-bold tracking-[-0.01em]">{preview.data.group_name}</h1>
          </header>
          {preview.data.status === "member" ? (
            <div className="flex flex-col items-start gap-3">
              <p>你已經是這個群組的成員。</p>
              <Link to="/groups" className={buttonVariants({ variant: "outline" })}>
                到群組
              </Link>
            </div>
          ) : signedOut ? (
            <SignInFirst token={token} />
          ) : (
            <ChooseAndJoin token={token} groupName={preview.data.group_name} />
          )}
        </>
      ) : null}
    </AuthFrame>
  )
}

function Gone({ title, body, signedIn }: { title: string; body: string; signedIn: boolean }) {
  return (
    <div className="flex flex-col items-start gap-3">
      <h1 className="text-2xl font-bold">{title}</h1>
      <p className="text-ink-2">{body}</p>
      {signedIn && (
        <Link to="/" className={buttonVariants({ variant: "outline" })}>
          回到帳本
        </Link>
      )}
    </div>
  )
}

function SignInFirst({ token }: { token: string }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-ink-2">加入前會先讓你選要分享什麼；預設只分享報酬率的百分比，不會分享金額。</p>
      <Link to="/login" search={{ next: `/invite/${token}` }} className={buttonVariants({ size: "lg", className: "w-full" })}>
        <LogInIcon />
        登入後加入
      </Link>
    </div>
  )
}

/** 加入前先選分享：送出時帶上這六個開關（伺服器要求本人確認） */
function ChooseAndJoin({ token, groupName }: { token: string; groupName: string }) {
  const [share, setShare] = useState<ShareSettings>(DEFAULT_SHARE)
  const accept = useAcceptInvite(token)
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const join = () => {
    setError(null)
    accept.mutate(share, {
      onSuccess: (g) => {
        toast.success(`已加入「${g.name}」`)
        void navigate({ to: "/groups/$groupId", params: { groupId: g.id } })
      },
      onError: (err) => {
        if (err instanceof ApiError && err.code === "already_member") {
          void navigate({ to: "/groups" })
          return
        }
        setError(
          err instanceof ApiError && err.status === 410
            ? "這個邀請剛剛失效了，請向邀請你的人要一個新的連結。"
            : err instanceof ApiError && err.code === "limit_reached"
              ? `沒辦法加入：${err.message}`
              : err instanceof ApiError
                ? err.message
                : "沒有加入成功，請再試一次。",
        )
      },
    })
  }
  return (
    <section aria-labelledby="invite-share" className="flex flex-col gap-4">
      <div>
        <h2 id="invite-share" className="text-lg font-bold">
          你要在「{groupName}」分享什麼？
        </h2>
        <p className="mt-1 text-md text-ink-2">只對這個群組有效，加入後隨時可以在「我的分享」修改。</p>
      </div>
      <ShareToggles value={share} onChange={setShare} idPrefix="invite" />
      {error && (
        <p role="alert" className="text-base text-destructive">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="lg" variant="sign" onClick={join} disabled={accept.isPending}>
          {accept.isPending ? "加入中…" : "加入群組"}
        </Button>
        <Link to="/" className={buttonVariants({ size: "lg", variant: "ghost" })}>
          先不要
        </Link>
      </div>
    </section>
  )
}
