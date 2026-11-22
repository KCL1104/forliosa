import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { appToday } from "@/api"
import { useMarketReportStatus } from "@/api/queries"
import { useDailyReports } from "@/api/sharing-queries"
import type { DailyReport, Group, ReportSummary } from "@/api/types"
import { Disclaimer } from "@/components/disclaimer"
import { InternalLink } from "@/components/internal-link"
import { Pct } from "@/components/finance"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { DataNotes } from "@/components/data-notes"
import { DemoTag } from "@/components/section"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatDateShort, formatDateTime } from "@/lib/format"
import { codeOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import type { GroupSearch, GroupReport } from "@/router"
import { DigestsTab } from "./DigestsTab"

const KINDS = [
  { value: "daily", label: "日報" },
  { value: "weekly", label: "週報" },
] as const satisfies readonly { value: GroupReport; label: string }[]

/**
 * 報告（原本的「週報」分頁，群組加值包第一階段改名；不加第九個分頁）：上面切換「日報｜週報」。
 * 日報只有加值群組有；免費群組（包括加值到期的）只看得到以前的日報，從來沒有日報的群組沒有切換、直接是週報。
 * 選了哪一個記在網址（`?tab=digests&report=weekly`），推播與連結可以直接打開那一個。
 */
export function ReportsTab({ group }: { group: Group }) {
  const search = useSearch({ from: "/groups/$groupId" }) as GroupSearch
  const navigate = useNavigate()
  const daily = useDailyReports(group.id)
  const items = daily.data?.pages.flatMap((p) => p.items) ?? []
  const boosted = group.plan?.tier === "boosted"
  // 還不知道有沒有以前的日報時先不畫切換（免費群組多半沒有，避免閃一下）
  const known = boosted || daily.isFetched || daily.isError
  const hasDaily = boosted || items.length > 0
  const kind: GroupReport = search.report ?? (hasDaily ? "daily" : "weekly")
  const setKind = (report: GroupReport) =>
    void navigate({ to: "/groups/$groupId", params: { groupId: group.id }, search: { tab: "digests", report }, replace: true, resetScroll: false })

  if (!known) return <SkeletonLines rows={6} />
  if (!hasDaily) return <DigestsTab group={group} />
  return (
    <div className="flex flex-col gap-6">
      <RangeChips label="報告" value={kind} onChange={setKind} options={KINDS} />
      {kind === "weekly" ? <DigestsTab group={group} /> : <DailyReports query={daily} items={items} boosted={boosted} />}
    </div>
  )
}

function DailyReports({
  query,
  items,
  boosted,
}: {
  query: ReturnType<typeof useDailyReports>
  items: DailyReport[]
  boosted: boolean
}) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (query.isLoading) return <SkeletonLines rows={6} />
  if (items.length === 0) {
    return <EmptyState title="還沒有日報" description={boosted ? "每個交易日收盤價進來後更新" : undefined} />
  }
  return <DailyList items={items} boosted={boosted} query={query} />
}

/**
 * 今天的盤前重點已經出來、最新一則日報是前一個交易日的：那一則就是推播裡的「昨日你的群組」（2026-11-17 市場報告；
 * 盤前推播把它接在盤前重點後面）。群組頁同樣這樣叫它，旁邊連到那一份盤前重點。報告本身人人相同，群組的數字只在這裡與推播裡。
 * 「前一個交易日」用伺服器給的 `prev_session`（跳過週末與台股休市日，和推播同一個算法），前端不自己推算。
 */
function useYesterdayPremarket(day: string | undefined): ReportSummary | null {
  const status = useMarketReportStatus()
  const pre = status.data?.available ? status.data.latest.find((s) => s.kind === "premarket") : undefined
  if (!day || !pre?.prev_session) return null
  return pre.prev_session === day ? pre : null
}

function DailyList({ items, boosted, query }: { items: DailyReport[]; boosted: boolean; query: ReturnType<typeof useDailyReports> }) {
  const premarket = useYesterdayPremarket(items[0]?.trading_day)
  return (
    <div className="flex flex-col gap-12">
      {!boosted && <p className="text-base text-ink">加值已結束，不再有新的日報</p>}
      {items.map((r, i) => (
        <DailyArticle key={r.id} r={r} latest={i === 0} premarket={i === 0 ? premarket : null} />
      ))}
      {query.hasNextPage && (
        <Button variant="outline" className="self-start" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
          {query.isFetchingNextPage ? "載入中…" : "較早的日報"}
        </Button>
      )}
    </div>
  )
}

/**
 * 一則日報（照 2026-11-16 備忘錄的範例）：日期 → 數字：今日報酬與兩個對照｜共同持股與那天的漲跌、那天的買賣（不寫是誰）、
 * 站內的連結（只有最新一則：個股頁的「為什麼漲跌」與市場頁的收盤重點都是最新一天的）→ 免責。
 * AI 寫的 2–4 句（`summary`）頁面不放（2026-11-22 評論：頁面只放標籤和數字，那一段把下面的表格再說一次）；
 * 後端照樣寫、推播照樣帶（盤前推播的「昨日你的群組」）。後端 `notes` 裡說 AI 摘要為什麼沒有的那幾句也不放。
 * 數字由伺服器依目前的成員與分享設定過濾，前端照樣畫，不自己推算。
 */
export function DailyArticle({ r, latest, premarket = null }: { r: DailyReport; latest: boolean; premarket?: ReportSummary | null }) {
  const titleId = `daily-${r.id}`
  const f = r.facts
  // 「今日」只在那一天就是今天時寫（DESIGN.md：「今日」只在收盤價是今天的時候寫）
  const today = r.trading_day === appToday()
  useSourceNote(r.sources)
  return (
    <article aria-labelledby={titleId} className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end gap-x-3 gap-y-1 border-b border-rule pb-2">
        <h2 id={titleId} className="num text-xl font-bold">
          {premarket ? "昨日你的群組" : `${formatDateShort(r.trading_day)} 日報`}
        </h2>
        <span className="num text-sm text-ink-2">
          {premarket && `${formatDateShort(r.trading_day)}・`}
          {formatDateTime(r.finished_at ?? r.created_at)}
        </span>
        {r.is_demo && <DemoTag />}
        {premarket && (
          <InternalLink href={`/market/reports/${premarket.id}`} className={cn(textAction, "ml-auto")}>
            {premarket.kind_label} {premarket.edition_label} →
          </InternalLink>
        )}
      </header>
      <DataNotes notes={r.notes.filter((n) => !isSummaryNote(n))} />
      <div className="grid gap-x-10 gap-y-6 md:grid-cols-2">
        {(f.returns.length > 0 || f.benchmarks.length > 0) && (
          <div>
            <h3 className="text-sm text-ink-2">{today ? "今日" : "當日"}報酬</h3>
            <ul className="mt-1">
              {f.returns.map((x) => (
                <li key={x.user_id} className="flex h-10 items-center justify-between gap-4 border-b border-rule">
                  <span className="truncate">{x.display_name}</span>
                  <DayPct value={x.day_return_pct} />
                </li>
              ))}
              {f.benchmarks.map((b) => (
                <li key={b.symbol} className="flex h-10 items-center justify-between gap-4 border-b border-rule text-ink-2">
                  <span className="truncate">{b.name}</span>
                  <DayPct value={b.day_return_pct} />
                </li>
              ))}
            </ul>
            {/* 開了報酬率、那天沒有數字的人（例如還沒記帳）：只寫人數，不畫一排「—」 */}
            {(f.returns_no_data ?? 0) > 0 && <p className="mt-1 text-sm text-ink-2">另 {f.returns_no_data} 人・沒有這天的資料</p>}
          </div>
        )}
        <div className="flex flex-col gap-4">
          {f.common_holdings.length > 0 && (
            <div>
              <h3 className="text-sm text-ink-2">共同持股</h3>
              <ul className="mt-1">
                {f.common_holdings.map((c) => (
                  <li key={c.symbol} className="flex min-h-10 items-center justify-between gap-4 border-b border-rule">
                    <span className="min-w-0">
                      {c.name} <span className="num text-ink-2">{codeOf(c.symbol)}</span>
                      <span className="num text-sm text-ink-2">（{c.holder_count} 人）</span>
                    </span>
                    <DayPct value={c.day_change_pct} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {/* 沒有人開交易動態時不知道有沒有買賣：整列不出現（不寫「沒有」） */}
          {(f.trades_shared ?? true) && (
            <div>
              <h3 className="text-sm text-ink-2">{today ? "今天" : "那天"}的買賣</h3>
              <p className="mt-1">
                {f.trades.length > 0
                  ? f.trades.map((t) => `${t.side === "buy" ? "買進" : "賣出"} ${t.name}${t.count > 1 ? `（${t.count} 筆）` : ""}`).join("、")
                  : "沒有"}
              </p>
            </div>
          )}
          {latest && f.why.length > 0 && (
            <div>
              <h3 className="text-sm text-ink-2">為什麼漲跌</h3>
              <p className="mt-0.5 flex flex-wrap gap-x-5">
                {f.why.map((w) => (
                  <Link key={w.symbol} to="/stock/$symbol" params={{ symbol: w.symbol }} className={textAction}>
                    {w.name}
                  </Link>
                ))}
              </p>
            </div>
          )}
          {latest && r.market_summary && (
            <p>
              <Link to="/market" hash="market-summary" className={textAction}>
                收盤重點 →
              </Link>
            </p>
          )}
        </div>
      </div>
      {/* 頁面上只有伺服器算的數字（AI 的段落不放）：全站那一句 */}
      <Disclaimer kind="short" />
    </article>
  )
}

/** 後端說 AI 摘要為什麼沒有（還在寫、收回、分享的人太少、沒寫成）的那幾句：頁面不放段落，這幾句也不放 */
const isSummaryNote = (n: string) => n.includes("摘要")

/**
 * 一天的漲跌：一位小數，和推播（含 AI 段落）一樣（備忘錄的格式）；不到 0.05% 算持平（後端 `DAILY_FLAT`），
 * 寫 0.0%、不畫箭頭，表格和推播的段落說的「幾個持平」才對得起來。算不出來是「—」（不說原因）。
 */
const DAILY_FLAT = 0.0005
function DayPct({ value }: { value: number | null }) {
  if (value === null) return <span className="num text-ink-2">—</span>
  return <Pct value={Math.abs(value) < DAILY_FLAT ? 0 : value} decimals={1} />
}
