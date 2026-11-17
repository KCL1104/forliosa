import { Link, useParams, useSearch } from "@tanstack/react-router"
import { useMarketReport, useMarketReportStatus } from "@/api/queries"
import { ApiError } from "@/api/types"
import { PageFrame } from "@/app/PageFrame"
import { usePageTitle } from "@/app/page-title"
import { PageHeader } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { buttonVariants } from "@/components/ui/button"
import type { ReportSearch } from "@/router"
import { MarketTabs } from "./MarketTabs"
import { ReportView } from "./ReportView"
import { useMarkReportsSeenOnOpen } from "./use-reports-unread"

/**
 * 一份市場報告（`/market/reports/<id>`；推播的連結打開這一頁）：外框和市場頁一樣，分頁列選在「報告」。
 * 要登入才看得到（沒有公開網址）；試跑期間只有站方管理員看得到，其他人是「找不到這份報告」。
 * `?version=` 看舊版（例如更正之前的那一版），上面一行說這是舊版、連到最新的一版。
 */
export function ReportPage() {
  const { reportId } = useParams({ from: "/market/reports/$reportId" })
  const { version } = useSearch({ from: "/market/reports/$reportId" }) as ReportSearch
  const q = useMarketReport(reportId, version)
  const status = useMarketReportStatus()
  usePageTitle(q.data ? `${q.data.kind_label} ${q.data.edition_label}` : "市場報告")
  useMarkReportsSeenOnOpen(!!q.data)
  const missing = q.error instanceof ApiError && q.error.status === 404
  return (
    <PageFrame>
      <PageHeader title="市場" className="mb-4 lg:mb-6" />
      {status.data?.available && <MarketTabs tab="reports" kind={q.data?.kind} detail />}
      <div id="market-tabpanel" role="tabpanel" aria-labelledby="market-tab-reports">
        {missing ? (
          <EmptyState
            title="找不到這份報告"
            description="可能已經超過保存的兩年，或還沒有對所有人公開。"
            action={
              <Link to="/market" className={buttonVariants({ variant: "outline", size: "sm" })}>
                回到市場
              </Link>
            }
          />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !q.data ? (
          <SkeletonLines rows={10} />
        ) : (
          <div className="flex flex-col gap-4">
            {version && (
              <p className="border-y border-rule py-2.5 text-base text-ink">
                這是第 {q.data.version} 版。{" "}
                <Link to="/market/reports/$reportId" params={{ reportId }} search={{}} className={textAction}>
                  看最新的一版
                </Link>
              </p>
            )}
            <ReportView report={q.data} />
          </div>
        )}
      </div>
    </PageFrame>
  )
}
