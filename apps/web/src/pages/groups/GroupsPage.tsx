import { Link, useNavigate } from "@tanstack/react-router"
import { ChevronRightIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { appToday } from "@/api"
import { usePerformance, useSummary } from "@/api/queries"
import { useCreateGroup, useGroups } from "@/api/sharing-queries"
import { ApiError, type GroupSummary } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { DataNotes } from "@/components/data-notes"
import { PageHeader, Section } from "@/components/section"
import { SourcesFooter } from "@/components/sources"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { direction, directionGlyph, formatDateShort, formatDateTime, formatPercent, toneClass } from "@/lib/format"
import { isReferenceNote } from "@/lib/data-notes"
import { cn } from "@/lib/utils"
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

/**
 * 分享卡：只有百分比（今日、本月、總報酬），可以複製文字貼到 LINE。
 * 本月用到存檔開始以前的 Yahoo 參考價時（產品負責人 2026-11-18），卡片下面寫後端那一句，分享文字的本月後面也標上
 */
function ShareCard() {
  const summary = useSummary()
  const mtd = usePerformance("MTD")
  const s = summary.data
  const month = mtd.data ? mtd.data.twr : undefined
  const today = appToday()
  // 本月算不出來（有持股還沒有收盤價、資料還不夠）時，分享文字與卡片都不提本月：沒有的值不寫進句子（不出現「本月 —」）
  const monthKnown = month !== null && month !== undefined
  const noMonth = month === null
  const until = monthKnown ? (mtd.data?.reference_until ?? null) : null
  const referenceNote = until
    ? ((mtd.data?.notes ?? []).find(isReferenceNote) ?? `${until.replaceAll("-", "/")} 以前用 Yahoo 參考價計算，不是官方資料`)
    : null
  const monthText = monthKnown ? `本月 ${glyphPct(month)}${until ? `（${formatDateShort(until, false)} 以前用 Yahoo 參考價）` : ""}，` : ""
  const line = s
    ? `我今天 ${glyphPct(s.day_change_pct)}，${monthText}總報酬 ${glyphPct(s.total_return_pct)}（Forliosa ${formatDateShort(today, false)}）`
    : ""
  const cells: { label: React.ReactNode; key: string; value: number | null | undefined }[] = [
    { key: "day", label: "今日", value: s?.day_change_pct },
    ...(noMonth ? [] : [{ key: "month", label: "本月", value: month }]),
    // 手機三欄放不下括號：只寫「總報酬」（和手機排行的表頭一樣）
    { key: "total", label: <>總報酬<span className="max-sm:hidden">（含股利）</span></>, value: s?.total_return_pct },
  ]
  return (
    <Section title="分享卡" titleId="g-card" aside="只有百分比，沒有金額" className="mt-12">
      {/*
        一張印好的聯絡簿紙條（2026-11-20）：印刷線外框、字標＋日期格、表頭的印刷雙線、明體印刷藍的欄位名稱、大的百分比，
        下緣一行網址。這是唯一會離開 app 的東西（截圖貼到 LINE）：遮住字標也認得出來——靠印好的表格，不靠顏色。
      */}
      <figure className="max-w-lg border border-print bg-raised">
        {/* 表頭和下面的格子同一組欄：日期格的直線就是最後一格的分隔線（不會差幾 px） */}
        <div className={cn("form-head grid text-base", noMonth ? "grid-cols-2" : "grid-cols-3")}>
          <span className={cn("self-center py-3 pl-3 font-sans text-xl font-bold tracking-[-0.01em] text-ink sm:pl-4", !noMonth && "col-span-2")}>Forliosa</span>
          <span className="date-cell num flex items-baseline gap-0 border-e-0 border-l border-rule px-3 py-3 font-sans text-base sm:px-4">
            {formatDateShort(today, false)}
            <span className="weekday [font-feature-settings:'halt'_1]">{formatDateShort(today).slice(formatDateShort(today, false).length)}</span>
          </span>
        </div>
        <dl className={cn("grid", noMonth ? "grid-cols-2" : "grid-cols-3")}>
          {cells.map((c, i) => (
            <div key={c.key} className={cn("min-w-0 px-3 pt-4 pb-5 sm:px-4", i > 0 && "border-l border-rule")}>
              <dt className="print-label text-sm">{c.label}</dt>
              <dd className={cn("num mt-1.5 text-2xl leading-none font-medium sm:text-3xl", toneClass(direction(c.value)))}>{c.value === undefined || c.value === null ? "—" : glyphPct(c.value)}</dd>
            </div>
          ))}
        </dl>
        <figcaption className="border-t border-rule px-3 py-2 text-right text-xs text-ink-2 sm:px-4">forliosa.trade</figcaption>
      </figure>
      {/* 後端的說明自己就有冒號（「MSFT：還沒有收盤價，…」），前面用一句話接，不再疊一個冒號 */}
      {noMonth && <p className="mt-2 max-w-lg text-base text-ink">{monthMissing(mtd.data?.notes ?? [])}</p>}
      {referenceNote && <DataNotes className="mt-2 max-w-lg" notes={[referenceNote]} />}
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

/**
 * 本月算不出來的原因，一句話：有持股還沒有收盤價時「MSFT 還沒有收盤價，本月算不出來。」；其他原因照後端的說明。
 * （後端那句是「MSFT：還沒有收盤價，績效算不出來」——接在「本月算不出來」後面就講了兩次。美股收盤價沒開的環境是
 * 「AAPL、NVDA：美股沒有報價，含美股的績效算不出來」→「AAPL、NVDA 沒有報價，本月算不出來。」）
 */
function monthMissing(notes: string[]): string {
  for (const n of notes) {
    const m = /^(.+?)：(還沒有收盤價|美股沒有報價)/.exec(n)
    if (m) return `${m[1]} ${m[2] === "還沒有收盤價" ? "還沒有收盤價" : "沒有報價"}，本月算不出來。`
  }
  return notes[0] ? `本月算不出來。${withPeriod(notes[0])}` : "本月算不出來。"
}

/** 後端的說明沒有句點時補上（接在另一句後面） */
function withPeriod(note: string): string {
  return /[。！？]$/.test(note) ? note : `${note}。`
}
