import { useId, useState } from "react"
import { toast } from "sonner"
import { useBlockDomain, useBlockedDomains, useUnblockDomain } from "@/api/discussion-queries"
import { ApiError, type BlockedDomain } from "@/api/types"
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
import { formatDateTime } from "@/lib/format"
import { AdminPage } from "./AdminPage"

const REASON_MAX = 200
const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")

type Confirm = { kind: "block"; domain: string; reason: string } | { kind: "unblock"; domain: string }

/**
 * 新聞下架（`/admin/news`）：依網域封鎖新聞標題（含子網域）。封鎖時刪掉已存的標題，之後也不再收；
 * 解除封鎖不會把刪掉的找回來。寫在伺服器設定（`NEWS_BLOCKED_DOMAINS`）的只列出來，這裡不能解除。
 */
export function AdminNewsPage() {
  return (
    <AdminPage title="新聞下架">
      <News />
    </AdminPage>
  )
}

function News() {
  const list = useBlockedDomains()
  const [domain, setDomain] = useState("")
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const id = useId()
  const rows = list.data ?? []
  return (
    <>
      <Section title="封鎖一個網域" titleId="admin-block">
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            const d = domain.trim()
            if (!d) {
              setError("請輸入網域，例如 example.com。")
              return
            }
            setError(null)
            setConfirm({ kind: "block", domain: d, reason: reason.trim() })
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-domain`} className="text-sm font-medium">
              網域
            </label>
            <Input
              id={`${id}-domain`}
              value={domain}
              placeholder="example.com"
              inputMode="url"
              autoCapitalize="none"
              autoComplete="off"
              spellCheck={false}
              maxLength={300}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${id}-domain-error` : undefined}
              onChange={(e) => {
                setDomain(e.target.value)
                if (error) setError(null)
              }}
              className="max-w-sm"
            />
            {error && (
              <p id={`${id}-domain-error`} role="alert" className="text-sm text-ink">
                {error}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-reason`} className="text-sm font-medium">
              原因（選填）
            </label>
            <Input id={`${id}-reason`} value={reason} maxLength={REASON_MAX} autoComplete="off" onChange={(e) => setReason(e.target.value)} />
          </div>
          <Button type="submit" className="self-start">
            封鎖
          </Button>
        </form>
      </Section>

      <Section title="封鎖中" titleId="admin-blocked" bodyClassName="pt-0" aside={rows.length > 0 ? <span className="num">{rows.length} 個</span> : undefined}>
        {list.isError ? (
          <ErrorState flush error={list.error} onRetry={() => void list.refetch()} />
        ) : !list.data ? (
          <SkeletonLines rows={3} className="pt-4" />
        ) : rows.length === 0 ? (
          <EmptyState flush title="沒有封鎖的網域" />
        ) : (
          <ul aria-label="封鎖中的網域">
            {rows.map((d) => (
              <BlockedRow key={d.domain} d={d} onUnblock={() => setConfirm({ kind: "unblock", domain: d.domain })} />
            ))}
          </ul>
        )}
      </Section>

      {confirm && (
        <ConfirmDialog
          confirm={confirm}
          onClose={() => setConfirm(null)}
          onBlocked={() => {
            setDomain("")
            setReason("")
          }}
          onInvalid={setError}
        />
      )}
    </>
  )
}

function BlockedRow({ d, onUnblock }: { d: BlockedDomain; onUnblock: () => void }) {
  const meta = [d.created_at ? `${formatDateTime(d.created_at)} 加入` : null, d.from_env ? "寫在伺服器設定" : null].filter(Boolean).join("・")
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule py-3">
      <div className="min-w-0 flex-1">
        <p className="font-medium break-all">{d.domain}</p>
        <p className="num mt-0.5 text-sm text-ink-2">
          {meta}
          {d.reason && (
            <span className="text-ink">
              {meta && "・"}
              {d.reason}
            </span>
          )}
        </p>
      </div>
      {!d.from_env && (
        <Button variant="outline" size="sm" aria-label={`解除封鎖 ${d.domain}`} onClick={onUnblock}>
          解除
        </Button>
      )}
    </li>
  )
}

function ConfirmDialog({
  confirm,
  onClose,
  onBlocked,
  onInvalid,
}: {
  confirm: Confirm
  onClose: () => void
  onBlocked: () => void
  onInvalid: (message: string) => void
}) {
  const block = useBlockDomain()
  const unblock = useUnblockDomain()
  const pending = block.isPending || unblock.isPending
  const failed = (err: unknown) => {
    if (err instanceof ApiError && err.status === 422) onInvalid(err.message)
    else toast.error("沒有完成", { description: errText(err) })
    onClose()
  }
  const isBlock = confirm.kind === "block"
  const run = () => {
    if (confirm.kind === "block") {
      block.mutate(
        { domain: confirm.domain, ...(confirm.reason ? { reason: confirm.reason } : {}) },
        {
          onSuccess: (r) => {
            toast.success(`已封鎖 ${r.domain}`, { description: r.deleted_headlines > 0 ? `刪掉 ${r.deleted_headlines} 則標題。` : "沒有存過的標題。" })
            onBlocked()
            onClose()
          },
          onError: failed,
        },
      )
    } else {
      unblock.mutate(confirm.domain, {
        onSuccess: () => {
          toast.success(`已解除封鎖 ${confirm.domain}`)
          onClose()
        },
        onError: failed,
      })
    }
  }
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{isBlock ? `封鎖 ${confirm.domain}？` : `解除封鎖 ${confirm.domain}？`}</AlertDialogTitle>
          <AlertDialogDescription>
            {isBlock
              ? "這個網域和子網域已經存的標題會刪掉，之後也不再收。解除封鎖不會把刪掉的找回來。"
              : "之後會再收這個網域的新聞。之前刪掉的標題不會回來。"}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction disabled={pending} onClick={run}>
            {isBlock ? "封鎖" : "解除"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
