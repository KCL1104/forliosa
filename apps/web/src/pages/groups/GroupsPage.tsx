import { Link, useNavigate } from "@tanstack/react-router"
import { ChevronRightIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { appToday } from "@/api"
import { useCreateGroup, useGroups } from "@/api/sharing-queries"
import { ApiError, type GroupSummary } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { ShareCopyButton, ShareSlip } from "@/components/share-card"
import { useShareCard } from "@/components/use-share-card"
import { PageHeader, Section } from "@/components/section"
import { SourcesFooter } from "@/components/sources"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { formatDateShort, formatDateTime } from "@/lib/format"
import { untilDay } from "@/lib/plan"
import { ROLE_LABEL } from "./labels"
import { FieldError } from "@/components/form-field"
import { usePageTitle } from "@/app/page-title"

/** 群組：我加入的群組＋建立群組；下面是可以貼到 LINE 的百分比分享卡 */
export function GroupsPage() {
  usePageTitle("群組")
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="群組" />
  return <Groups />
}

function Groups() {
  const groups = useGroups()
  const [creating, setCreating] = useState(false)
  return (
    <PageFrame>
      <PageHeader
        title="群組"
        actions={
          <Button onClick={() => setCreating(true)}>建立群組</Button>
        }
      />
      {groups.isError ? (
        <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
      ) : !groups.data ? (
        <SkeletonLines rows={4} />
      ) : groups.data.length === 0 ? (
        // 動作只有頁首的「建立群組」一個，這裡不再放第二顆
        <EmptyState title="還沒有加入任何群組" description="建立群組，把邀請連結傳給家人朋友。別人給你的邀請連結，點開就能加入。" />
      ) : (
        <ul aria-label="我的群組" className="border-t border-rule">
          {groups.data.map((g) => (
            <GroupRow key={g.id} g={g} />
          ))}
        </ul>
      )}
      {creating && <CreateGroupDialog onClose={() => setCreating(false)} />}
      <ShareCard />
      <SourcesFooter />
    </PageFrame>
  )
}

function GroupRow({ g }: { g: GroupSummary }) {
  return (
    <li>
      <Link
        to="/groups/$groupId"
        params={{ groupId: g.id }}
        className="ruled-row grid min-h-[72px] grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 py-3"
      >
        <span className="min-w-0">
          <span className="flex items-center gap-2">
            <span className="truncate text-lg font-medium">{g.name}</span>
            <span className="demo-tag text-ink-2">{ROLE_LABEL[g.my_role]}</span>
          </span>
          <span className="num mt-0.5 flex flex-wrap gap-x-3 text-sm text-ink-2">
            <span>{g.member_count} 位成員</span>
            {!g.ranking_enabled && <span>不排名次</span>}
            {g.latest_activity_at && <span>最近動態 {formatDateTime(g.latest_activity_at)}</span>}
            {g.plan?.tier === "boosted" && <span>{g.plan.until ? `加值到 ${untilDay(g.plan.until, appToday())}` : "加值"}</span>}
            {g.latest_daily_at && <span>日報 {formatDateShort(g.latest_daily_at.slice(0, 10), false)}</span>}
            {g.latest_digest_at && <span>週報 {formatDateShort(g.latest_digest_at.slice(0, 10), false)}</span>}
          </span>
        </span>
        <ChevronRightIcon aria-hidden className="size-5 text-ink-2" />
      </Link>
    </li>
  )
}

function CreateGroupDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateGroup()
  const navigate = useNavigate()
  const [name, setName] = useState("")
  const [touched, setTouched] = useState(false)
  const bad = name.trim().length < 1 || name.trim().length > 40
  const submit = () => {
    setTouched(true)
    if (bad) return
    create.mutate(name.trim(), {
      onSuccess: (g) => {
        toast.success(`已建立「${g.name}」`)
        onClose()
        void navigate({ to: "/groups/$groupId", params: { groupId: g.id }, search: { tab: "members" } })
      },
      onError: (err) => toast.error("沒有建立成功", { description: err instanceof ApiError ? err.message : undefined }),
    })
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>建立群組</DialogTitle>
          <DialogDescription>建立後產生邀請連結傳給家人朋友。每個人加入前會自己選要分享什麼。</DialogDescription>
        </DialogHeader>
        <form
          id="create-group"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
          className="flex flex-col gap-1.5"
        >
          <label htmlFor="group-name" className="print-label text-sm">
            群組名稱
          </label>
          <Input id="group-name" className="pointer-coarse:h-11" value={name} maxLength={40} autoFocus placeholder="例如：家族投資" aria-invalid={touched && bad} onChange={(e) => setName(e.target.value)} />
          {touched && bad && (
            <FieldError>請填 1 到 40 個字</FieldError>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" variant="sign" form="create-group" disabled={create.isPending}>
            {create.isPending ? "建立中…" : "建立群組"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 分享卡（`components/share-card.tsx`，帳本有加入群組時也放同一張）：卡片、需要時的說明、複製按鈕，下面一行是會複製的字 */
function ShareCard() {
  const data = useShareCard()
  return (
    <Section title="分享卡" titleId="g-card" className="mt-12">
      <ShareSlip data={data} />
      <ShareCopyButton data={data} className="mt-4" />
      {data.ready && <p className="mt-2 text-sm text-ink-2">「{data.line}」</p>}
    </Section>
  )
}
