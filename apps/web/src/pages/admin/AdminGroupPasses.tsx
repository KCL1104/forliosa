import { useId, useState } from "react"
import { toast } from "sonner"
import { useGrantGroupPass, useGroupPasses, useRevokeGroupPass, useUpdateGroupPass } from "@/api/discussion-queries"
import { ApiError, type AdminGroupPass } from "@/api/types"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { todayInTaipei } from "@/lib/format"
import { formatDay, monthLater } from "@/lib/membership"

const NOTE_MAX = 200
const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")
/** 最後一天最多 5 年後（後端 `until_too_far`；打錯成 9999 年時日曆就選不到） */
const maxUntil = (today: string) => new Date(Date.parse(`${today}T00:00:00Z`) + 5 * 365 * 86_400_000).toISOString().slice(0, 10)

/**
 * 群組加值（`/admin/members?kind=group`；群組加值包第一階段，還沒有付款）：站方用付款人的 email 開通，到最後一天為止。
 * 付款人在自己擁有的群組的設定裡選要用在哪個群組；站方也可以直接填群組編號（付款人要是那個群組的擁有者）。
 * 站方只看得到付款人與群組編號，看不到群組名稱與內容。過期的也列出：「延長」改最後一天，「停止」馬上回到免費（不移出成員）；
 * 停止的紀錄照樣留著、列成已到期（做帳與退款用，隱私權政策 §7），之後也可以再延長。
 */
export function GroupPasses() {
  const list = useGroupPasses()
  const grant = useGrantGroupPass()
  const today = todayInTaipei()
  const [email, setEmail] = useState("")
  const [until, setUntil] = useState(() => monthLater(today))
  const [groupId, setGroupId] = useState("")
  const [note, setNote] = useState("")
  const [error, setError] = useState<{ field: "email" | "until" | "group"; message: string } | null>(null)
  const [extending, setExtending] = useState<AdminGroupPass | null>(null)
  const [revoking, setRevoking] = useState<AdminGroupPass | null>(null)
  const id = useId()
  const rows = list.data ?? []

  const submit = () => {
    const e = email.trim()
    if (!e.includes("@")) {
      setError({ field: "email", message: "請輸入付款人登入用的 email。" })
      return
    }
    if (!until || until < today) {
      setError({ field: "until", message: "最後一天不能早於今天。" })
      return
    }
    setError(null)
    grant.mutate(
      { email: e, until, ...(note.trim() ? { note: note.trim() } : {}), ...(groupId.trim() ? { group_id: groupId.trim() } : {}) },
      {
        onSuccess: (p) => {
          toast.success(`開給 ${p.display_name ?? e} 了`, { description: `到 ${formatDay(p.until ?? until)}。${p.group_id ? "已經用在那個群組。" : "對方在群組設定裡選要用在哪個群組。"}` })
          setEmail("")
          setNote("")
          setGroupId("")
          setUntil(monthLater(today))
        },
        onError: (err) => {
          if (err instanceof ApiError && err.code === "user_not_found") setError({ field: "email", message: err.message })
          else if (err instanceof ApiError && (err.code === "group_not_found" || err.code === "not_group_owner")) setError({ field: "group", message: err.message })
          else if (err instanceof ApiError && err.status === 422) setError({ field: "until", message: err.message })
          else toast.error("沒有開通", { description: errText(err) })
        },
      },
    )
  }

  const field = (name: "email" | "until" | "group") => ({
    "aria-invalid": error?.field === name ? true : undefined,
    "aria-describedby": error?.field === name ? `${id}-${name}-error` : name === "email" ? undefined : `${id}-${name}-hint`,
  })
  const fieldError = (name: "email" | "until" | "group") =>
    error?.field === name && (
      <p id={`${id}-${name}-error`} role="alert" className="text-sm text-ink">
        {error.message}
      </p>
    )

  return (
    <>
      <Section title="開通群組加值" titleId="admin-pass-grant">
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <p className="max-w-prose text-md text-ink">
            加值的群組人數上限比較高，每個交易日有 AI 日報。付款人在自己擁有的群組裡選要用在哪個群組；最後一天過完回到免費，不會移出成員。對方要先登入過一次。
          </p>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-email`} className="text-sm font-medium">
              付款人的 Email
            </label>
            <Input
              id={`${id}-email`}
              type="email"
              value={email}
              autoCapitalize="none"
              autoComplete="off"
              spellCheck={false}
              maxLength={320}
              {...field("email")}
              onChange={(e) => {
                setEmail(e.target.value)
                if (error?.field === "email") setError(null)
              }}
              className="max-w-sm"
            />
            {fieldError("email")}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-until`} className="text-sm font-medium">
              最後一天
            </label>
            <Input
              id={`${id}-until`}
              type="date"
              value={until}
              min={today}
              max={maxUntil(today)}
              {...field("until")}
              onChange={(e) => {
                setUntil(e.target.value)
                if (error?.field === "until") setError(null)
              }}
              className="w-auto self-start"
            />
            {fieldError("until") || (
              <p id={`${id}-until-hint`} className="text-sm text-ink-2">
                {until ? `到 ${formatDay(until)} 為止（台北時間）。` : "請選最後一天。"}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-group`} className="text-sm font-medium">
              群組編號（選填）
            </label>
            <Input
              id={`${id}-group`}
              value={groupId}
              maxLength={32}
              autoCapitalize="none"
              autoComplete="off"
              spellCheck={false}
              placeholder="grp_…"
              {...field("group")}
              onChange={(e) => {
                setGroupId(e.target.value)
                if (error?.field === "group") setError(null)
              }}
              className="num max-w-sm"
            />
            {fieldError("group") || (
              <p id={`${id}-group-hint`} className="text-sm text-ink-2">
                群組網址 /groups/ 後面那一段。不填就由付款人自己選。
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-note`} className="text-sm font-medium">
              備註（選填，只有站方看得到）
            </label>
            <Input id={`${id}-note`} value={note} maxLength={NOTE_MAX} autoComplete="off" placeholder="例如：11/16 轉帳 NT$149" onChange={(e) => setNote(e.target.value)} />
          </div>
          <Button type="submit" className="self-start" disabled={grant.isPending}>
            開通
          </Button>
        </form>
      </Section>

      <Section
        title="群組加值"
        titleId="admin-passes"
        bodyClassName="pt-0"
        aside={rows.length > 0 ? <span className="num">{rows.filter((p) => p.active).length} 個加值中</span> : undefined}
      >
        {list.isError ? (
          <ErrorState flush error={list.error} onRetry={() => void list.refetch()} />
        ) : !list.data ? (
          <SkeletonLines rows={3} className="pt-4" />
        ) : rows.length === 0 ? (
          <EmptyState flush title="還沒有群組加值" />
        ) : (
          <ul aria-label="群組加值">
            {rows.map((p) => (
              <PassRow key={p.id} p={p} onExtend={() => setExtending(p)} onRevoke={() => setRevoking(p)} />
            ))}
          </ul>
        )}
      </Section>

      {extending && <ExtendDialog pass={extending} onClose={() => setExtending(null)} />}
      {revoking && <RevokeDialog pass={revoking} onClose={() => setRevoking(null)} />}
    </>
  )
}

const who = (p: AdminGroupPass) => p.display_name ?? "已刪除的帳號"

function PassRow({ p, onExtend, onRevoke }: { p: AdminGroupPass; onExtend: () => void; onRevoke: () => void }) {
  const term = !p.until ? "沒有最後一天" : p.active ? `到 ${formatDay(p.until)}` : `${formatDay(p.until)} 到期`
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule py-3">
      <div className="min-w-0 flex-1">
        <p className={p.payer_user_id ? "font-medium" : "font-medium text-ink-2"}>{who(p)}</p>
        {p.email && <p className="text-sm break-all text-ink-2">{p.email}</p>}
        <p className="num mt-0.5 text-sm text-ink-2">
          <span className={p.active ? "text-ink" : undefined}>{term}</span>・{p.group_id ? `群組 ${p.group_id}` : "還沒選群組"}
          {p.note && `・${p.note}`}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" aria-label={`延長 ${who(p)} 的群組加值`} onClick={onExtend}>
          延長
        </Button>
        {p.active && (
          <Button variant="outline" size="sm" aria-label={`停止 ${who(p)} 的群組加值`} onClick={onRevoke}>
            停止
          </Button>
        )}
      </div>
    </li>
  )
}

/** 延長（改最後一天；還在加值就從原本的最後一天往後接一個月，過期的從今天起算）、改備註 */
function ExtendDialog({ pass, onClose }: { pass: AdminGroupPass; onClose: () => void }) {
  const update = useUpdateGroupPass()
  const today = todayInTaipei()
  const [until, setUntil] = useState(() => monthLater(today, pass))
  const [note, setNote] = useState(pass.note ?? "")
  const [error, setError] = useState<string | null>(null)
  const id = useId()
  const save = () => {
    if (!until || until < today) {
      setError("最後一天不能早於今天。")
      return
    }
    update.mutate(
      { id: pass.id, patch: { until, note: note.trim() || null } },
      {
        onSuccess: (p) => {
          toast.success(`${who(p)} 的群組加值到 ${formatDay(p.until ?? until)}`)
          onClose()
        },
        onError: (err) => (err instanceof ApiError && err.status === 422 ? setError(err.message) : toast.error("沒有延長", { description: errText(err) })),
      },
    )
  }
  return (
    <Dialog open onOpenChange={(o) => !o && !update.isPending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>延長 {who(pass)} 的群組加值</DialogTitle>
          <DialogDescription>{pass.until ? `現在${pass.active ? "到" : "在"} ${formatDay(pass.until)}${pass.active ? "" : " 到期"}。` : "沒有最後一天。"}</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            save()
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-until`} className="text-sm font-medium">
              最後一天
            </label>
            <Input
              id={`${id}-until`}
              type="date"
              value={until}
              min={today}
              max={maxUntil(today)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${id}-until-error` : undefined}
              onChange={(e) => {
                setUntil(e.target.value)
                setError(null)
              }}
              className="w-auto self-start"
            />
            {error && (
              <p id={`${id}-until-error`} role="alert" className="text-sm text-ink">
                {error}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-note`} className="text-sm font-medium">
              備註（選填）
            </label>
            <Input id={`${id}-note`} value={note} maxLength={NOTE_MAX} autoComplete="off" onChange={(e) => setNote(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              取消
            </Button>
            <Button type="submit" variant="sign" disabled={update.isPending}>
              {update.isPending ? "儲存中…" : "儲存"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RevokeDialog({ pass, onClose }: { pass: AdminGroupPass; onClose: () => void }) {
  const revoke = useRevokeGroupPass()
  return (
    <AlertDialog open onOpenChange={(o) => !o && !revoke.isPending && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>停止 {who(pass)} 的群組加值？</AlertDialogTitle>
          <AlertDialogDescription>
            {pass.group_id ? "那個群組馬上回到免費：日報停止，人數超過上限時不能再加人，不會移出成員。" : "還沒用在群組，停止後付款人就不能再選。"}
            這筆紀錄會留著、列成已到期，之後可以再延長。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>保留</AlertDialogCancel>
          <AlertDialogAction
            disabled={revoke.isPending}
            onClick={() =>
              revoke.mutate(pass.id, {
                onSuccess: () => {
                  toast.success(`已停止 ${who(pass)} 的群組加值`)
                  onClose()
                },
                onError: (err) => {
                  toast.error("沒有停止", { description: errText(err) })
                  onClose()
                },
              })
            }
          >
            停止加值
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
