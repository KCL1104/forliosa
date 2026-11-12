import { Link, useNavigate } from "@tanstack/react-router"
import { ChevronRightIcon, CopyIcon, PlusIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { appToday } from "@/api"
import { usePerformance, useSummary } from "@/api/queries"
import { useCreateGroup, useGroups } from "@/api/sharing-queries"
import { ApiError, type GroupSummary } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { PageHeader, Section } from "@/components/section"
import { ErrorState, SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { direction, directionGlyph, formatDateShort, formatDateTime, formatPercent, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { ROLE_LABEL } from "./labels"

/** 群組：我加入的群組＋建立群組；下面是可以貼到 LINE 的百分比分享卡 */
export function GroupsPage() {
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
          <Button onClick={() => setCreating(true)}>
            <PlusIcon />
            建立群組
          </Button>
        }
      />
      {groups.isError ? (
        <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
      ) : !groups.data ? (
        <SkeletonLines rows={4} />
      ) : groups.data.length === 0 ? (
        <div className="border-y border-rule py-8">
          <p className="text-lg font-medium">還沒有加入任何群組</p>
          <p className="mt-1 max-w-prose text-ink-2">建立一個群組，再把邀請連結傳給家人朋友；收到別人的邀請連結時，點開就能加入。</p>
          <Button className="mt-4" variant="outline" onClick={() => setCreating(true)}>
            <PlusIcon />
            建立群組
          </Button>
        </div>
      ) : (
        <ul aria-label="我的群組" className="border-t border-rule">
          {groups.data.map((g) => (
            <GroupRow key={g.id} g={g} />
          ))}
        </ul>
      )}
      {creating && <CreateGroupDialog onClose={() => setCreating(false)} />}
      <ShareCard />
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
          <DialogTitle className="text-lg font-bold">建立群組</DialogTitle>
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
          <label htmlFor="group-name" className="text-sm font-medium">
            群組名稱
          </label>
          <Input id="group-name" value={name} maxLength={40} autoFocus placeholder="例如：家族投資" aria-invalid={touched && bad} onChange={(e) => setName(e.target.value)} />
          {touched && bad && (
            <p role="alert" className="text-sm text-destructive">
              請填 1 到 40 個字
            </p>
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

/** 分享卡：只有百分比（今日、本月、總報酬），可以複製文字貼到 LINE */
function ShareCard() {
  const summary = useSummary()
  const mtd = usePerformance("MTD")
  const s = summary.data
  const month = mtd.data ? mtd.data.twr : undefined
  const today = appToday()
  const line = s
    ? `我今天 ${glyphPct(s.day_change_pct)}，本月 ${month === undefined || month === null ? "—" : glyphPct(month)}，總報酬 ${glyphPct(s.total_return_pct)}（Forliosa ${formatDateShort(today, false)}）`
    : ""
  const cells: { label: string; value: number | null | undefined }[] = [
    { label: "今日", value: s?.day_change_pct },
    { label: "本月", value: month },
    { label: "總報酬（含股利）", value: s?.total_return_pct },
  ]
  return (
    <Section title="分享卡" titleId="g-card" aside="只有百分比，沒有金額" className="mt-12">
      <figure className="max-w-md border border-rule bg-raised">
        <div className="flex items-baseline justify-between border-b border-rule px-5 py-3">
          <span className="text-lg font-bold">Forliosa</span>
          <span className="num text-sm text-ink-2">{formatDateShort(today)}</span>
        </div>
        <dl className="grid grid-cols-3">
          {cells.map((c, i) => (
            <div key={c.label} className={cn("px-3 py-4 sm:px-4", i > 0 && "border-l border-rule")}>
              <dt className="text-sm text-ink-2">{c.label}</dt>
              <dd className={cn("num mt-1 text-xl font-medium sm:text-2xl", toneClass(direction(c.value)))}>{c.value === undefined || c.value === null ? "—" : glyphPct(c.value)}</dd>
            </div>
          ))}
        </dl>
      </figure>
      {month === null && mtd.data?.notes?.[0] && <p className="mt-2 max-w-md text-sm text-ink-2">本月：{mtd.data.notes[0]}</p>}
      <Button
        variant="outline"
        className="mt-4"
        disabled={!s}
        onClick={() => {
          void navigator.clipboard?.writeText(line).then(
            () => toast.success("已複製，可以貼到 LINE"),
            () => toast.error("沒有複製成功", { description: line }),
          )
        }}
      >
        <CopyIcon />
        複製分享文字
      </Button>
      {s && <p className="mt-2 text-sm text-ink-2">「{line}」</p>}
    </Section>
  )
}

function glyphPct(r: number | null): string {
  const d = direction(r)
  return `${directionGlyph(d)}${formatPercent(r === null ? null : Math.abs(r), { signed: false, decimals: Math.abs(r ?? 0) >= 0.1 ? 1 : 2 })}`
}
