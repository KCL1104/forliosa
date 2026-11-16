import { useId, useState } from "react"
import { toast } from "sonner"
import { useGrantMember, useMembers, useRevokeMember } from "@/api/discussion-queries"
import { ApiError, type AdminMember } from "@/api/types"
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
import { Input } from "@/components/ui/input"
import { textAction } from "@/components/text-action"
import { todayInTaipei } from "@/lib/format"
import { formatDay, monthLater } from "@/lib/membership"
import { AdminPage } from "./AdminPage"
import { GroupPasses } from "./AdminGroupPasses"
import { RangeChips } from "@/components/segmented"
import { useNavigate, useSearch } from "@tanstack/react-router"
import type { AdminMembersSearch } from "@/router"

const NOTE_MAX = 200
const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")

/**
 * 會員（`/admin/members`）：還沒有付款，由站方用 email 開通（對方要先登入過一次）。標題右邊切換「個人會員｜群組加值」
 * （`?kind=group`；群組加值包第一階段，`AdminGroupPasses.tsx`）。
 * 個人會員每天 30 題、每月約 US$8（2026-11-16 起；省錢模式到 1.25 倍才停），另有深度搜尋與每日收盤簡報；免費每天 3 題、約 US$1（省錢模式到兩倍）。
 * 最後一天過完自動回到免費；過期的也列在下面，方便續期。
 */
export function AdminMembersPage() {
  const search = useSearch({ strict: false }) as AdminMembersSearch
  const navigate = useNavigate()
  const kind = search.kind === "group" ? "group" : "member"
  return (
    <AdminPage
      title="會員"
      actions={
        <RangeChips
          label="種類"
          value={kind}
          onChange={(k) => void navigate({ to: "/admin/members", search: { kind: k === "group" ? "group" : undefined }, replace: true })}
          options={[
            { value: "member", label: "個人會員" },
            { value: "group", label: "群組加值" },
          ]}
        />
      }
    >
      {kind === "group" ? <GroupPasses /> : <Members />}
    </AdminPage>
  )
}

function Members() {
  const list = useMembers()
  const grant = useGrantMember()
  const today = todayInTaipei()
  const [email, setEmail] = useState("")
  const [until, setUntil] = useState(() => monthLater(today))
  const [note, setNote] = useState("")
  const [error, setError] = useState<{ field: "email" | "until"; message: string } | null>(null)
  const [revoking, setRevoking] = useState<AdminMember | null>(null)
  const id = useId()
  const rows = list.data ?? []

  const submit = () => {
    const e = email.trim()
    if (!e.includes("@")) {
      setError({ field: "email", message: "請輸入對方登入用的 email。" })
      return
    }
    if (until && until < today) {
      setError({ field: "until", message: "最後一天不能早於今天。" })
      return
    }
    setError(null)
    grant.mutate(
      { email: e, until: until || null, ...(note.trim() ? { note: note.trim() } : {}) },
      {
        onSuccess: (m) => {
          toast.success(`${m.display_name} 是會員了`, { description: m.until ? `到 ${formatDay(m.until)}。` : "沒有到期日。" })
          setEmail("")
          setNote("")
          setUntil(monthLater(today))
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 404) setError({ field: "email", message: err.message })
          else if (err instanceof ApiError && err.status === 422) setError({ field: "until", message: err.message })
          else toast.error("沒有開通", { description: errText(err) })
        },
      },
    )
  }

  const renew = (m: AdminMember) => {
    setEmail(m.email)
    setUntil(monthLater(today, m))
    setNote(m.note ?? "")
    setError(null)
    document.getElementById(`${id}-email`)?.focus()
  }

  return (
    <>
      <Section title="開通或續期" titleId="admin-grant">
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <p className="max-w-prose text-md text-ink">會員每天 30 題、有深度搜尋與每日收盤簡報；最後一天過完自動回到免費。對方要先登入過一次。</p>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-email`} className="text-sm font-medium">
              Email
            </label>
            <Input
              id={`${id}-email`}
              type="email"
              value={email}
              autoCapitalize="none"
              autoComplete="off"
              spellCheck={false}
              maxLength={320}
              aria-invalid={error?.field === "email" ? true : undefined}
              aria-describedby={error?.field === "email" ? `${id}-email-error` : undefined}
              onChange={(e) => {
                setEmail(e.target.value)
                if (error?.field === "email") setError(null)
              }}
              className="max-w-sm"
            />
            {error?.field === "email" && (
              <p id={`${id}-email-error`} role="alert" className="text-sm text-ink">
                {error.message}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-until`} className="text-sm font-medium">
              最後一天
            </label>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Input
                id={`${id}-until`}
                type="date"
                value={until}
                min={today}
                aria-invalid={error?.field === "until" ? true : undefined}
                aria-describedby={error?.field === "until" ? `${id}-until-error` : `${id}-until-hint`}
                onChange={(e) => {
                  setUntil(e.target.value)
                  if (error?.field === "until") setError(null)
                }}
                className="w-auto"
              />
              <button type="button" className={textAction} onClick={() => setUntil("")}>
                不設到期日
              </button>
            </div>
            {error?.field === "until" ? (
              <p id={`${id}-until-error`} role="alert" className="text-sm text-ink">
                {error.message}
              </p>
            ) : (
              <p id={`${id}-until-hint`} className="text-sm text-ink-2">
                {until ? `到 ${formatDay(until)} 為止（台北時間）。` : "沒有到期日，要取消時在下面按「取消會員」。"}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-note`} className="text-sm font-medium">
              備註（選填，只有站方看得到）
            </label>
            <Input id={`${id}-note`} value={note} maxLength={NOTE_MAX} autoComplete="off" placeholder="例如：11/16 轉帳 NT$490" onChange={(e) => setNote(e.target.value)} />
          </div>
          <Button type="submit" className="self-start" disabled={grant.isPending}>
            開通
          </Button>
        </form>
      </Section>

      <Section title="會員" titleId="admin-members" bodyClassName="pt-0" aside={rows.length > 0 ? <span className="num">{rows.filter((m) => m.active).length} 位</span> : undefined}>
        {list.isError ? (
          <ErrorState flush error={list.error} onRetry={() => void list.refetch()} />
        ) : !list.data ? (
          <SkeletonLines rows={3} className="pt-4" />
        ) : rows.length === 0 ? (
          <EmptyState flush title="還沒有會員" />
        ) : (
          <ul aria-label="會員">
            {rows.map((m) => (
              <MemberRow key={m.user_id} m={m} onRenew={() => renew(m)} onRevoke={() => setRevoking(m)} />
            ))}
          </ul>
        )}
      </Section>

      {revoking && <RevokeDialog member={revoking} onClose={() => setRevoking(null)} />}
    </>
  )
}

function MemberRow({ m, onRenew, onRevoke }: { m: AdminMember; onRenew: () => void; onRevoke: () => void }) {
  const term = m.until === null ? "沒有到期日" : m.active ? `到 ${formatDay(m.until)}` : `${formatDay(m.until)} 到期，已回到免費`
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule py-3">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{m.display_name}</p>
        <p className="text-sm break-all text-ink-2">{m.email}</p>
        <p className="num mt-0.5 text-sm text-ink-2">
          <span className={m.active ? "text-ink" : undefined}>{term}</span>
          {m.note && `・${m.note}`}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {m.until !== null && (
          <Button variant="outline" size="sm" aria-label={`幫 ${m.display_name} 續期`} onClick={onRenew}>
            續期
          </Button>
        )}
        {m.active && (
          <Button variant="outline" size="sm" aria-label={`取消 ${m.display_name} 的會員`} onClick={onRevoke}>
            取消會員
          </Button>
        )}
      </div>
    </li>
  )
}

function RevokeDialog({ member, onClose }: { member: AdminMember; onClose: () => void }) {
  const revoke = useRevokeMember()
  return (
    <AlertDialog open onOpenChange={(o) => !o && !revoke.isPending && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>取消 {member.display_name} 的會員？</AlertDialogTitle>
          <AlertDialogDescription>馬上回到免費：每天 3 題，沒有深度搜尋與每日收盤簡報。之後可以再開通。</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>保留</AlertDialogCancel>
          <AlertDialogAction
            disabled={revoke.isPending}
            onClick={() =>
              revoke.mutate(member.user_id, {
                onSuccess: () => {
                  toast.success(`${member.display_name} 回到免費`)
                  onClose()
                },
                onError: (err) => {
                  toast.error("沒有取消", { description: errText(err) })
                  onClose()
                },
              })
            }
          >
            取消會員
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
