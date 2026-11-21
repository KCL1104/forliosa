import { useSearch } from "@tanstack/react-router"
import { useMarketOverview, useMarketReportStatus } from "@/api/queries"
import type { MarketOverview } from "@/api/types"
import type { MarketSearch } from "@/router"
import { MarketTabs, type MarketTab } from "./reports/MarketTabs"
import { ReportsTab } from "./reports/ReportsTab"
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
 * 由上到下：指數 → AI 收盤重點（有才出現）→ 類股漲跌 → 排行 → 美股（SPY、DIA、ONEQ 與美股新聞；有才出現）→ 重大訊息，
 * 每一塊是一盤托盤（2026-11-21，見 `MarketBody`）。頁面只有標籤和數字：沒有頁首的一句話、沒有說明行（DESIGN.md〈Copy〉）。
 * 有市場報告可看時（登入的人都看得到；2026-11-18 起不再有盲測），標題下面多一列分頁「行情｜報告」（`?tab=reports&kind=`）。
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
  const search = useSearch({ from: "/market" }) as MarketSearch
  const status = useMarketReportStatus()
  // 「報告」分頁只在有報告可看的時候出現；沒有時整頁和以前一樣，沒有分頁列
  const available = !!status.data?.available
  const tab: MarketTab = available && search.tab === "reports" ? "reports" : "quotes"
  const q = useMarketOverview()
  const data = q.data
  return (
    <PageFrame>
      <PageHeader
        title="市場"
        className="mb-4 lg:mb-6"
        meta={
          tab === "quotes" &&
          data && (
            <>
              {data.as_of && <span className="num text-sm text-ink-2">{formatDateShort(data.as_of, false)} 收盤</span>}
              {data.is_demo && <DemoTag />}
              <CloseNote asOf={data.as_of} />
            </>
          )
        }
      />
      {available && <MarketTabs tab={tab} kind={search.kind} />}
      <div id="market-tabpanel" role={available ? "tabpanel" : undefined} aria-labelledby={available ? `market-tab-${tab}` : undefined}>
        {tab === "reports" ? (
          <ReportsTab kind={search.kind} />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !data ? (
          <MarketSkeleton />
        ) : (
          <MarketBody data={data} />
        )}
      </div>
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
 * 指數那一盤的最下面：上市個股的收盤價已經進來、加權指數還沒有時（證交所下午的指數檔被擋；晚上那一批沒有指數），
 * 指數預計什麼時候更新（「加權指數預計明天清晨 5:20–5:45 更新」）。只在需要時出現，自己一行。
 */
function IndexCloseNote() {
  const note = useIndexCloseNote()
  if (!note) return null
  return <p className="num mt-3 text-sm text-ink-2">{note}</p>
}

/**
 * 行情：一盤一盤的托盤（產品負責人 2026-11-21 採方向 C 的結構）。主欄 ≥ 1024px 時排成 12 欄的格子：
 *   指數（整列）→ 收盤重點（4）＋類股（8）→ 排行（整列）→ 美股（7）＋重大訊息（5）。
 * 並排的兩盤只有一盤時，那一盤佔整列；更窄時一盤一列，順序不變（DOM 的順序就是讀的順序）。
 * 每一盤同一種底色（產品負責人 2026-11-21：托盤只留一種底色），盤與盤之間靠間距分開。
 */
function MarketBody({ data }: { data: MarketOverview }) {
  useSourceNote(data.sources)
  const us = data.us && (data.us.items.length > 0 || data.us.news.length > 0) ? data.us : null
  const empty = data.indices.length === 0 && !data.sectors && !data.movers && !data.announcements && !data.summary && !us
  if (empty) return <EmptyState title="還沒有資料" />
  const top = !!data.summary && !!data.sectors
  const bottom = !!us && !!data.announcements
  return (
    <div className="@container">
      <div className="grid grid-cols-1 gap-tray-gap @5xl:grid-cols-12">
        {data.indices.length > 0 && <IndexStrip indices={data.indices} note={<IndexCloseNote />} className="@5xl:col-span-12" />}
        {data.summary && <SummaryBlock summary={data.summary} className={top ? "@5xl:col-span-4" : "@5xl:col-span-12"} />}
        {data.sectors && <SectorList sectors={data.sectors} className={top ? "@5xl:col-span-8" : "@5xl:col-span-12"} />}
        {data.movers && <Movers movers={data.movers} className="@5xl:col-span-12" />}
        {us && <UsBlock us={us} className={bottom ? "@5xl:col-span-7" : "@5xl:col-span-12"} />}
        {data.announcements && <Announcements announcements={data.announcements} className={bottom ? "@5xl:col-span-5" : "@5xl:col-span-12"} />}
      </div>
      <DataNotes notes={data.notes} className="mt-4" />
    </div>
  )
}

function MarketSkeleton() {
  return (
    <div aria-busy="true" aria-label="市場資料載入中" className="flex flex-col gap-tray-gap">
      <div className="tray flex flex-col gap-2">
        <Skeleton className="h-5 w-28" />
        <Skeleton className="h-10 w-44" />
        <Skeleton className="h-5 w-36" />
      </div>
      <div className="tray flex flex-col gap-3">
        <Skeleton className="h-6 w-28" />
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    </div>
  )
}
