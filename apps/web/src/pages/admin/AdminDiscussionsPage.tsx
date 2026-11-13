import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { useId, useState } from "react"
import { toast } from "sonner"
import { useAdminReports, useCreateSuspension, useLiftSuspension, useModerate, useSuspensions } from "@/api/discussion-queries"
import { useViewer } from "@/api/queries"
import { ApiError, PERMANENT_UNTIL, REPORT_NOTE_MAX, REPORT_REASONS, type AdminReport, type Suspension, type SuspensionDays } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { PageHeader, Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
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
import { NotFoundPage } from "@/pages/NotFoundPage"
import { REASON_LABEL } from "@/pages/discussions/labels"
import { PostedTime } from "@/pages/discussions/PostedTime"
import type { AdminDiscussionsSearch } from "@/router"
import { usePageTitle } from "@/app/page-title"

type Status = "open" | "resolved"
type Confirm =
  | { kind: "hide" | "unhide" | "dismiss"; report: AdminReport }
  | { kind: "suspend"; report: AdminReport }
  | { kind: "lift"; suspension: Suspension }

const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")
const KIND_LABEL = { topic: "主題", reply: "回覆" } as const
const DAY_OPTIONS = [
  { value: "1", label: "1 天" },
  { value: "7", label: "7 天" },
  { value: "30", label: "30 天" },
  { value: "forever", label: "永久" },
] as const
type DayChoice = (typeof DAY_OPTIONS)[number]["value"]
const daysOf = (c: DayChoice): SuspensionDays => (c === "forever" ? null : (Number(c) as 1 | 7 | 30))
const authorOf = (name: string | null) => (name ? `「${name}」` : "這位作者")
const isPermanent = (until: string) => until === PERMANENT_UNTIL || until.startsWith("9999")

/**
 * 站方管理（只有站方管理員；其他人看到的是「找不到這個頁面」）：公開內容的檢舉與停權。
 * - 檢舉：依對象彙整的格線列（待處理｜已處理）——內容節錄、主題或回覆、作者的公開暱稱、各理由的次數、檢舉人的補充說明；
 *   動作是文字動作「隱藏」「不處理」「停權…」（已處理的是「取消隱藏」），每一個都先確認。
 * - 停權中：公開暱稱、到什麼時候、原因，外框按鈕「解除」。
 * 站方看不到群組內容，也拿不到 email 或 user id：停權是「停這則內容的作者」。
 */
export function AdminDiscussionsPage() {
  const readOnly = useReadOnly()
  const { user } = useViewer()
  usePageTitle(user?.is_admin ? "站方管理" : "找不到這個頁面")
  if (readOnly) return <ViewAsBlocked title="站方管理" />
  if (!user?.is_admin) return <NotFoundPage />
  return <Admin />
}

function Admin() {
  const search = useSearch({ from: "/admin/discussions" }) as AdminDiscussionsSearch
  const navigate = useNavigate()
  const status: Status = search.status === "resolved" ? "resolved" : "open"
  const reports = useAdminReports(status)
  const suspensions = useSuspensions()
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const items = reports.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <PageFrame>
      <div className="flex max-w-measure flex-col gap-10">
        <PageHeader title="站方管理" className="mb-0" />

        <Section
          title="檢舉"
          titleId="admin-reports"
          bodyClassName="pt-0"
          action={
            <RangeChips
              label="檢舉狀態"
              value={status}
              onChange={(v) => void navigate({ to: "/admin/discussions", search: { status: v === "resolved" ? "resolved" : undefined }, replace: true, resetScroll: false })}
              options={[
                { value: "open", label: "待處理" },
                { value: "resolved", label: "已處理" },
              ]}
            />
          }
        >
          {reports.isError ? (
            <ErrorState flush error={reports.error} onRetry={() => void reports.refetch()} />
          ) : !reports.data ? (
            <SkeletonLines rows={5} className="pt-4" />
          ) : items.length === 0 ? (
            <EmptyState flush title={status === "open" ? "沒有待處理的檢舉" : "還沒有處理過的檢舉"} />
          ) : (
            <ul aria-label={status === "open" ? "待處理的檢舉" : "已處理的檢舉"}>
              {items.map((r) => (
                <ReportRow key={r.target} report={r} onAction={setConfirm} />
              ))}
            </ul>
          )}
          {reports.hasNextPage && (
            <Button variant="outline" className="mt-4" disabled={reports.isFetchingNextPage} onClick={() => void reports.fetchNextPage()}>
              {reports.isFetchingNextPage ? "載入中…" : "看更多"}
            </Button>
          )}
        </Section>

        <Section title="停權中" titleId="admin-suspensions" bodyClassName="pt-0" aside={suspensions.data && suspensions.data.length > 0 ? <span className="num">{suspensions.data.length} 人</span> : undefined}>
          {suspensions.isError ? (
            <ErrorState flush error={suspensions.error} onRetry={() => void suspensions.refetch()} />
          ) : !suspensions.data ? (
            <SkeletonLines rows={2} className="pt-4" />
          ) : suspensions.data.length === 0 ? (
            <EmptyState flush title="目前沒有人被停權" />
          ) : (
            <ul aria-label="停權中">
              {suspensions.data.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule py-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium break-words">{s.public_name ?? "已刪除的帳號"}</p>
                    <p className="num mt-0.5 text-sm text-ink-2">
                      {isPermanent(s.until) ? (
                        "永久"
                      ) : (
                        <>
                          到 <PostedTime iso={s.until} />
                        </>
                      )}
                      {"・"}
                      <PostedTime iso={s.created_at} /> 起{s.reason && <span className="text-ink">・{s.reason}</span>}
                    </p>
                  </div>
                  <Button variant="outline" size="sm" aria-label={`解除${authorOf(s.public_name)}的停權`} onClick={() => setConfirm({ kind: "lift", suspension: s })}>
                    解除
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
    </PageFrame>
  )
}

/** 一個被檢舉的對象：節錄（連到那個主題）→ 作者・檢舉次數與理由・最早的檢舉時間 → 檢舉人的補充說明 → 文字動作 */
function ReportRow({ report: r, onAction }: { report: AdminReport; onAction: (c: Confirm) => void }) {
  const reasons = REPORT_REASONS.flatMap((k) => (r.reasons[k] ? [`${REASON_LABEL[k]} ${r.reasons[k]}`] : []))
  const what = `${authorOf(r.author_name)}的${KIND_LABEL[r.kind]}`
  return (
    <li className="border-b border-rule py-3.5">
      <div className="flex items-baseline gap-2">
        <span className="demo-tag shrink-0 text-ink-2">{KIND_LABEL[r.kind]}</span>
        {r.hidden && <span className="demo-tag shrink-0">已隱藏</span>}
      </div>
      <p className="mt-1.5 text-base break-words text-ink">{r.excerpt}</p>
      <p className="num mt-1 text-sm text-ink-2">
        <span className="text-ink">{r.author_name ?? "已刪除的帳號"}</span>
        {"・"}檢舉 {r.report_count} 次{reasons.length > 0 && `：${reasons.join("、")}`}
        {"・"}最早 <PostedTime iso={r.first_reported_at} />
      </p>
      {r.notes.length > 0 && (
        <ul aria-label="檢舉人的補充說明" className="mt-1.5 flex flex-col gap-0.5 text-md text-ink">
          {r.notes.map((n, i) => (
            <li key={i} className="break-words">
              「{n}」
            </li>
          ))}
        </ul>
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-5">
        {r.hidden ? (
          <button type="button" aria-label={`取消隱藏${what}`} onClick={() => onAction({ kind: "unhide", report: r })} className={textAction}>
            取消隱藏
          </button>
        ) : (
          <button type="button" aria-label={`隱藏${what}`} onClick={() => onAction({ kind: "hide", report: r })} className={textAction}>
            隱藏
          </button>
        )}
        {r.status === "open" && (
          <button type="button" aria-label={`不處理${what}的檢舉`} onClick={() => onAction({ kind: "dismiss", report: r })} className={textAction}>
            不處理
          </button>
        )}
        {r.author_name !== null && (
          <button type="button" aria-label={`停權${authorOf(r.author_name)}`} onClick={() => onAction({ kind: "suspend", report: r })} className={textAction}>
            停權…
          </button>
        )}
        <Link to="/discussions/$topicId" params={{ topicId: r.topic_id }} className={`${textAction} ml-auto`}>
          看主題 →
        </Link>
      </div>
    </li>
  )
}

function ConfirmDialog({ confirm, onClose }: { confirm: Confirm; onClose: () => void }) {
  const moderate = useModerate()
  const suspend = useCreateSuspension()
  const lift = useLiftSuspension()
  const [days, setDays] = useState<DayChoice>("7")
  const [reason, setReason] = useState("")
  const id = useId()
  const pending = moderate.isPending || suspend.isPending || lift.isPending
  const done = (message: string) => ({
    onSuccess: () => {
      toast.success(message)
      onClose()
    },
    onError: (err: unknown) => {
      toast.error("沒有完成", { description: errText(err) })
      onClose()
    },
  })
  let title: string
  let description: string
  let action: string
  let run: () => void
  if (confirm.kind === "lift") {
    const name = authorOf(confirm.suspension.public_name)
    title = `解除${name}的停權？`
    description = "對方可以立刻再發公開主題與回覆。"
    action = "解除"
    run = () => lift.mutate(confirm.suspension.id, done(`已解除${name}的停權`))
  } else {
    const r = confirm.report
    const what = KIND_LABEL[r.kind]
    const name = authorOf(r.author_name)
    if (confirm.kind === "hide") {
      title = `隱藏這則${what}？`
      description = `其他人會看到「這則內容已被站方隱藏」，作者仍看得到自己的原文。這則的 ${r.report_count} 次檢舉會標為已處理。`
      action = "隱藏"
      run = () => moderate.mutate({ target: r.target, action: "hide" }, done(`已隱藏這則${what}`))
    } else if (confirm.kind === "unhide") {
      title = `取消隱藏這則${what}？`
      description = "內容會重新公開，所有人都看得到。"
      action = "取消隱藏"
      run = () => moderate.mutate({ target: r.target, action: "unhide" }, done(`已取消隱藏這則${what}`))
    } else if (confirm.kind === "dismiss") {
      title = "不處理這些檢舉？"
      description = `內容維持公開，${r.report_count} 次檢舉標為已處理。之後有人再檢舉，會回到待處理。`
      action = "不處理"
      run = () => moderate.mutate({ target: r.target, action: "dismiss" }, done("已標為已處理"))
    } else {
      const choice = daysOf(days)
      title = `暫停${name}的公開發言？`
      description = "期間內對方不能發公開主題與回覆；群組裡的發言不受影響。對方已經在停權中的話，會改成這次選的期間。"
      action = choice === null ? "永久停權" : `停權 ${choice} 天`
      run = () =>
        suspend.mutate(
          { target: r.target, days: choice, ...(reason.trim() ? { reason: reason.trim() } : {}) },
          done(choice === null ? `已永久暫停${name}的公開發言` : `已暫停${name}的公開發言 ${choice} 天`),
        )
    }
  }
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {confirm.kind === "suspend" && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">期間</span>
              <RangeChips label="停權期間" value={days} onChange={setDays} options={DAY_OPTIONS} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${id}-reason`} className="text-sm font-medium">
                原因（選填）
              </label>
              <Input id={`${id}-reason`} value={reason} maxLength={REPORT_NOTE_MAX} autoComplete="off" aria-describedby={`${id}-reason-help`} onChange={(e) => setReason(e.target.value)} />
              {/* 原因會給被暫停的人看：提醒管理員照這個前提寫 */}
              <p id={`${id}-reason-help`} className="text-sm text-ink-2">
                對方會看到這句話。
              </p>
            </div>
          </div>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction disabled={pending} onClick={run}>
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
