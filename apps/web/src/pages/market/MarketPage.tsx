import { useMarketOverview } from "@/api/queries"
import type { MarketOverview } from "@/api/types"
import { PageFrame } from "@/app/PageFrame"
import { usePageTitle } from "@/app/page-title"
import { DataNotes } from "@/components/data-notes"
import { DemoTag, PageHeader } from "@/components/section"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { EmptyState, ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatDateShort } from "@/lib/format"
import { Announcements } from "./Announcements"
import { IndexStrip } from "./IndexStrip"
import { Movers } from "./Movers"
import { SectorList } from "./SectorList"
import { SummaryBlock } from "./SummaryBlock"

/**
 * 市場：收盤後的市場資訊（產品負責人 2026-11-13；登入後另開一頁，首頁仍是帳本）。
 * 由上到下：指數 → AI 收盤重點（有才出現）→ 類股漲跌 → 排行 → 重大訊息。只有官方的收盤後資料：
 * 沒有盤中、沒有海外指數、美股與加密貨幣。每一塊自己帶日期（各交易所公布的時間不同）。
 * 查看別人的資產時照常可看：這一頁沒有個人資料。
 */
export function MarketPage() {
  usePageTitle("市場")
  return (
    <SourcesProvider>
      <Market />
    </SourcesProvider>
  )
}

function Market() {
  const q = useMarketOverview()
  const data = q.data
  return (
    <PageFrame>
      <PageHeader
        title="市場"
        className="mb-4 lg:mb-6"
        meta={
          data && (
            <>
              {data.as_of && <span className="num text-sm text-ink-2">{formatDateShort(data.as_of, false)} 收盤</span>}
              {data.is_demo && <DemoTag />}
            </>
          )
        }
      />
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !data ? (
        <MarketSkeleton />
      ) : (
        <MarketBody data={data} />
      )}
      <SourcesFooter />
    </PageFrame>
  )
}

function MarketBody({ data }: { data: MarketOverview }) {
  useSourceNote(data.sources)
  const empty = data.indices.length === 0 && !data.sectors && !data.movers && !data.announcements && !data.summary
  if (empty) return <EmptyState title="還沒有資料" />
  return (
    <div className="@container flex flex-col gap-10">
      {data.indices.length > 0 && <IndexStrip indices={data.indices} />}
      {data.summary && <SummaryBlock summary={data.summary} />}
      {data.sectors && <SectorList sectors={data.sectors} />}
      {data.movers && <Movers movers={data.movers} />}
      {data.announcements && <Announcements announcements={data.announcements} />}
      <DataNotes notes={data.notes} />
    </div>
  )
}

function MarketSkeleton() {
  return (
    <div aria-busy="true" aria-label="市場資料載入中" className="flex flex-col gap-10">
      <div className="grid gap-x-8 gap-y-4 border-y border-rule py-4 md:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="flex flex-col gap-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-7 w-32" />
            <Skeleton className="h-4 w-28" />
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-3">
        <Skeleton className="h-6 w-28" />
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    </div>
  )
}
