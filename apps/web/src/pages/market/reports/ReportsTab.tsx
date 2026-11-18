import { useNavigate } from "@tanstack/react-router"
import { useMarketReportLatest, useMarketReports, useMarketReportStatus } from "@/api/queries"
import { REPORT_KIND_LABEL, type ReportKind, type ReportSummary } from "@/api/types"
import { InternalLink } from "@/components/internal-link"
import { RangeChips } from "@/components/segmented"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { titleBody } from "./report-context"
import { ReportView } from "./ReportView"
import { useMarkReportsSeenOnOpen } from "./use-reports-unread"

const KINDS = [
  { value: "premarket", label: "盤前" },
  { value: "close", label: "盤後" },
  { value: "weekly", label: "週報" },
] as const satisfies readonly { value: ReportKind; label: string }[]
/** 還沒有這一種報告時，寫什麼時候會有 */
const WHEN: Record<ReportKind, string> = { premarket: "交易日 7:30 推出。", close: "交易日 16:00 推出。", weekly: "週日 18:00 推出。" }

/**
 * 市場頁的「報告」分頁：上面一組選項「盤前｜盤後｜週報」（選取語法 (b)，記在網址 `kind`；沒選時是最新發布的那一種），
 * 下面是那一種最新一份的全文，再下面「更早的報告」（日期・標題，整列連到那一份；先 10 份，「再看 10 份」）。
 * 打開 1.2 秒後記成看過（導覽「市場」旁的小圓點消失）。首頁（帳本）不放報告的入口。
 * 每一份都是對所有登入的人公開的同一份報告（盲測 2026-11-18 拿掉了）。
 */
export function ReportsTab({ kind: picked }: { kind?: ReportKind }) {
  const navigate = useNavigate()
  const status = useMarketReportStatus()
  const newest = [...(status.data?.latest ?? [])].sort((a, b) => b.published_at.localeCompare(a.published_at))[0]
  const kind: ReportKind = picked ?? newest?.kind ?? "premarket"
  const latest = useMarketReportLatest(kind)
  useMarkReportsSeenOnOpen()
  const setKind = (k: ReportKind) => void navigate({ to: "/market", search: { tab: "reports", kind: k }, replace: true, resetScroll: false })
  return (
    <div className="flex flex-col gap-8">
      <RangeChips label="報告種類" value={kind} onChange={setKind} options={KINDS} />
      {latest.isError ? (
        <ErrorState error={latest.error} onRetry={() => void latest.refetch()} />
      ) : latest.isPending ? (
        <SkeletonLines rows={8} />
      ) : latest.data ? (
        <ReportView report={latest.data} />
      ) : (
        <EmptyState title={`還沒有${REPORT_KIND_LABEL[kind]}`} description={WHEN[kind]} />
      )}
      <Earlier kind={kind} exclude={latest.data?.id} />
    </div>
  )
}

/** 更早的報告：一份一列（日期・標題），整列連到那一份；沒有更早的就不出現 */
function Earlier({ kind, exclude }: { kind: ReportKind; exclude?: string }) {
  const list = useMarketReports(kind)
  const items = (list.data?.pages.flatMap((p) => p.items) ?? []).filter((r) => r.id !== exclude)
  if (list.isError || items.length === 0) return null
  return (
    <Section title="更早的報告" titleId={`earlier-${kind}`} bodyClassName="pt-0">
      <ul className="max-w-[46rem]">
        {items.map((r) => (
          <EarlierRow key={r.id} r={r} />
        ))}
      </ul>
      {list.hasNextPage && (
        <button type="button" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} className={cn(textAction, "mt-2")}>
          {list.isFetchingNextPage ? "載入中…" : "再看 10 份"}
        </button>
      )}
    </Section>
  )
}

function EarlierRow({ r }: { r: ReportSummary }) {
  const tags = [r.has_ai ? null : "只有資料", r.corrected ? "已更正" : null].filter(Boolean)
  return (
    <li className="ruled-row relative grid grid-cols-[7.25rem_minmax(0,1fr)] items-baseline gap-x-3 py-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
      <span className="num text-sm text-ink-2">{r.edition_label}</span>
      <span className="min-w-0">
        <InternalLink href={`/market/reports/${r.id}`} className="rounded-xs text-base text-ink after:absolute after:inset-0 after:content-[''] focus-visible:outline-offset-4">
          {titleBody(r.kind_label, r.title)}
        </InternalLink>
        <span className="num block text-sm text-ink-2">
          {formatDateTime(r.published_at)}
          {tags.length > 0 && `・${tags.join("・")}`}
        </span>
      </span>
    </li>
  )
}
