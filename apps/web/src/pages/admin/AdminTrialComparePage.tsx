import { useNavigate, useParams, useSearch } from "@tanstack/react-router"
import { ArrowLeftIcon } from "lucide-react"
import { useAdminReportsTrial, useAdminReportVariant } from "@/api/discussion-queries"
import { ApiError, REPORT_KIND_LABEL, type ReportVariant, type TrialReport } from "@/api/types"
import { PlainLink } from "@/app/links"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { useMediaQuery } from "@/hooks/use-media-query"
import { ReportView } from "@/pages/market/reports/ReportView"
import type { AdminTrialSearch } from "@/router"
import { AdminPage } from "./AdminPage"
import { writerText } from "./report-labels"

const LABELS: ReportVariant[] = ["A", "B", "C"]

/**
 * 盲測：一份報告的 A／B／C（`/admin/reports/<id>?v=A&vs=B`）。管理員形式——每句後面多一段 refs、被拿掉的段照樣顯示並寫原因。
 * 寬螢幕（≥ 1280px）兩欄並排：左邊 `v`、右邊 `vs`，各自上面一組「A｜B｜C」；較窄時一次看一個。
 * 揭曉前不寫是哪個模型（標籤每份重新打亂）。
 */
export function AdminTrialComparePage() {
  const { reportId } = useParams({ from: "/admin/reports/$reportId" })
  const search = useSearch({ from: "/admin/reports/$reportId" }) as AdminTrialSearch
  const navigate = useNavigate()
  const trial = useAdminReportsTrial()
  const wide = useMediaQuery("(min-width: 1280px)")
  const report = trial.data?.reports.find((r) => r.report_id === reportId)
  const ready = (l: ReportVariant) => !!report?.variants.find((v) => v.label === l && v.status !== "running" && v.status !== "pending")
  const left = search.v ?? LABELS.find(ready) ?? "A"
  const right = search.vs ?? LABELS.find((l) => l !== left && ready(l)) ?? (left === "A" ? "B" : "A")
  const go = (patch: AdminTrialSearch) => void navigate({ to: "/admin/reports/$reportId", params: { reportId }, search: { v: left, vs: right, ...patch }, replace: true, resetScroll: false })
  const title = report ? `${REPORT_KIND_LABEL[report.kind]} ${report.edition_label}・盲測` : "盲測"
  return (
    <AdminPage title={title} wide>
      <nav aria-label="位置" className="-mt-6 flex min-h-11 items-center text-sm">
        <PlainLink to="/admin/reports" className="-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11">
          <ArrowLeftIcon aria-hidden className="size-4" />
          市場報告
        </PlainLink>
      </nav>
      {trial.isError ? (
        <ErrorState error={trial.error} onRetry={() => void trial.refetch()} />
      ) : !trial.data ? (
        <SkeletonLines rows={8} />
      ) : !report ? (
        <EmptyState title="找不到這份盲測" />
      ) : (
        <div className={wide ? "grid grid-cols-2 gap-x-12" : ""}>
          <Column report={report} label={left} onPick={(v) => go({ v })} prefix="a-" />
          {wide && <Column report={report} label={right} onPick={(vs) => go({ vs })} prefix="b-" />}
        </div>
      )}
    </AdminPage>
  )
}

function Column({ report, label, onPick, prefix }: { report: TrialReport; label: ReportVariant; onPick: (l: ReportVariant) => void; prefix: string }) {
  const meta = report.variants.find((v) => v.label === label)
  const ready = !!meta && meta.status !== "running" && meta.status !== "pending"
  const q = useAdminReportVariant(report.report_id, label, ready)
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule pb-3">
        <RangeChips label={`${prefix === "a-" ? "左邊" : "右邊"}看哪一個版本`} value={label} onChange={onPick} options={LABELS.map((l) => ({ value: l, label: l }))} />
        <span className="num text-sm text-ink-2">
          {meta?.on_time === false ? "遲了" : meta?.on_time ? "準時" : ""}
          {meta?.writer && `・${writerText(meta.writer)}`}
          {meta?.metrics?.cost_usd != null && `・US$${meta.metrics.cost_usd.toFixed(2)}`}
        </span>
      </div>
      {!ready ? (
        <EmptyState title="這個版本還在寫" />
      ) : q.isError ? (
        q.error instanceof ApiError && q.error.status === 409 ? <EmptyState title="這個版本還在寫" /> : <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !q.data ? (
        <SkeletonLines rows={10} />
      ) : (
        <ReportView report={q.data} admin prefix={prefix} />
      )}
    </div>
  )
}
