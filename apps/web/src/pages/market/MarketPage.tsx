import { useMarketOverview } from "@/api/queries"
import type { MarketOverview } from "@/api/types"
import { PageFrame } from "@/app/PageFrame"
import { usePageTitle } from "@/app/page-title"
import { DataNotes } from "@/components/data-notes"
import { DemoTag, PageHeader } from "@/components/section"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { EmptyState, ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useIndexCloseNote, useMarketCloseNote } from "@/hooks/use-close"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatDateShort } from "@/lib/format"
import { Announcements } from "./Announcements"
import { IndexStrip } from "./IndexStrip"
import { Movers } from "./Movers"
import { SectorList } from "./SectorList"
import { SummaryBlock } from "./SummaryBlock"
import { UsBlock } from "./UsBlock"

/**
 * 市場：收盤後的市場資訊（產品負責人 2026-11-13；登入後另開一頁，首頁仍是帳本）。
 * 由上到下：指數 → AI 收盤重點（有才出現）→ 類股漲跌 → 排行 → 美股（SPY、DIA、ONEQ 與美股新聞；有才出現）→ 重大訊息。
 * 只有收盤後的資料：沒有盤中、沒有海外指數本身（美股只列追蹤指數的 ETF）、沒有加密貨幣。
 * 每一塊自己帶日期（各交易所公布的時間不同；美股是紐約的日期）。上市或上櫃的收盤價還沒進來時，標題旁寫預計幾點更新。
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
              <CloseNote asOf={data.as_of} />
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

/**
 * 收盤價還沒進來時，接在標題旁的日期後面寫預計幾點更新（上市、上櫃各自的時間；和帳本主數字旁同一種寫法）。
 * 手機自己一行。只在需要時出現。
 */
function CloseNote({ asOf }: { asOf: string | null }) {
  const note = useMarketCloseNote(asOf)
  if (!note) return null
  return (
    <span className="num text-sm whitespace-nowrap text-ink-2 max-sm:basis-full sm:-ml-2.5">
      <span aria-hidden className="max-sm:hidden">
        ・
      </span>
      {note}
    </span>
  )
}

/**
 * 指數那一排下面：上市個股的收盤價已經進來、加權指數還沒有時（證交所下午的指數檔被擋；晚上那一批沒有指數），
 * 指數預計什麼時候更新（「加權指數預計明天清晨 5:20–5:45 更新」）。只在需要時出現，自己一行。
 */
function IndexCloseNote() {
  const note = useIndexCloseNote()
  if (!note) return null
  return <p className="num text-sm text-ink-2">{note}</p>
}

function MarketBody({ data }: { data: MarketOverview }) {
  useSourceNote(data.sources)
  const us = data.us && (data.us.items.length > 0 || data.us.news.length > 0) ? data.us : null
  const empty = data.indices.length === 0 && !data.sectors && !data.movers && !data.announcements && !data.summary && !us
  if (empty) return <EmptyState title="還沒有資料" />
  return (
    <div className="@container flex flex-col gap-10">
      {data.indices.length > 0 && (
        <div className="flex flex-col gap-2">
          <IndexStrip indices={data.indices} />
          <IndexCloseNote />
        </div>
      )}
      {data.summary && <SummaryBlock summary={data.summary} />}
      {data.sectors && <SectorList sectors={data.sectors} />}
      {data.movers && <Movers movers={data.movers} />}
      {us && <UsBlock us={us} />}
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
