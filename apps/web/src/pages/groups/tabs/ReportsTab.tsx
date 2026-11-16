import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { useState } from "react"
import { appToday } from "@/api"
import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import { useDailyReports } from "@/api/sharing-queries"
import type { DailyReport, Group } from "@/api/types"
import { Pct } from "@/components/finance"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatDateShort, formatDateTime } from "@/lib/format"
import { codeOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import type { GroupSearch, GroupReport } from "@/router"
import { CommentsToggle, CommentThread, Reactions } from "../Discussion"
import { DigestsTab } from "./DigestsTab"

const FALLBACK_DISCLAIMER = "AI 分析僅供參考，不構成投資建議。"
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
      {kind === "weekly" ? <DigestsTab group={group} /> : <DailyReports group={group} query={daily} items={items} boosted={boosted} />}
    </div>
  )
}

function DailyReports({
  group,
  query,
  items,
  boosted,
}: {
  group: Group
  query: ReturnType<typeof useDailyReports>
  items: DailyReport[]
  boosted: boolean
}) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (query.isLoading) return <SkeletonLines rows={6} />
  if (items.length === 0) {
    return <EmptyState title="還沒有日報" description={boosted ? "每個交易日收盤價進來以後，整理當天的群組表現。" : undefined} />
  }
  return (
    <div className="flex flex-col gap-12">
      {!boosted && <p className="text-base text-ink">這個群組已經沒有加值，不會再有新的日報。</p>}
      {items.map((r, i) => (
        <DailyArticle key={r.id} r={r} groupId={group.id} latest={i === 0} />
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
 * 一則日報（照 2026-11-16 備忘錄的範例）：日期 → AI 寫的 2–4 句（黑體墨色 `.ai-voice`，少於 2 人分享報酬或收回時沒有）
 * → 數字：今日報酬與兩個對照｜共同持股與當天漲跌、當天的買賣、站內的連結（最新一則才有：「為什麼漲跌」與收盤重點都只有最新一天）
 * → 免責 → 表情與留言（後端有給才有）。數字由伺服器依目前的分享設定過濾，前端照樣畫。
 */
export function DailyArticle({ r, groupId, latest }: { r: DailyReport; groupId: string; latest: boolean }) {
  const [open, setOpen] = useState(false)
  const titleId = `daily-${r.id}`
  const threadId = `daily-thread-${r.id}`
  const f = r.facts
  // 「今日」只在那一天就是今天時寫（DESIGN.md：「今日」只在收盤價是今天的時候寫）
  const day = r.trade_date === appToday() ? "今日" : "當日"
  const dayWord = r.trade_date === appToday() ? "今天" : "當天"
  useSourceNote(r.sources)
  const discussable = r.comment_count !== undefined && r.reactions !== undefined
  return (
    <article aria-labelledby={titleId} className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end gap-x-3 gap-y-1 border-b border-rule pb-2">
        <h2 id={titleId} className="num text-xl font-bold">
          {formatDateShort(r.trade_date)} 日報
        </h2>
        <span className="num text-sm text-ink-2">{formatDateTime(r.created_at)}</span>
      </header>
      {r.status === "pending" && <p className="text-base text-ink">日報整理中。</p>}
      {r.summary && (
        <p className={cn("ai-voice max-w-prose", kaiSize.page)}>
          <KaiText text={r.summary} />
        </p>
      )}
      {f && (
        <div className="grid gap-x-10 gap-y-6 md:grid-cols-2">
          {(f.returns.length > 0 || f.benchmarks.length > 0) && (
            <div>
              <h3 className="text-sm text-ink-2">{day}報酬</h3>
              <ul className="mt-1">
                {f.returns.map((x) => (
                  <li key={x.user_id} className="flex h-10 items-center justify-between gap-4 border-b border-rule">
                    <span className="truncate">{x.display_name}</span>
                    {x.day_return_pct === null ? <span className="num text-ink-2">—</span> : <Pct value={x.day_return_pct} />}
                  </li>
                ))}
                {f.benchmarks.map((b) => (
                  <li key={b.symbol} className="flex h-10 items-center justify-between gap-4 border-b border-rule text-ink-2">
                    <span className="truncate">{b.name}</span>
                    {b.day_return_pct === null ? <span className="num">—</span> : <Pct value={b.day_return_pct} />}
                  </li>
                ))}
              </ul>
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
                      {c.day_change_pct === null ? <span className="num text-ink-2">—</span> : <Pct value={c.day_change_pct} />}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <h3 className="text-sm text-ink-2">{dayWord}的買賣</h3>
              <p className="mt-1">{f.trades.length > 0 ? f.trades.map((t) => `${t.side === "buy" ? "買進" : "賣出"} ${t.name}`).join("、") : "沒有"}</p>
            </div>
            {latest && f.why.length > 0 && (
              <div>
                <h3 className="text-sm text-ink-2">為什麼漲跌</h3>
                <p className="mt-1 flex flex-wrap gap-x-5">
                  {f.why.map((w) => (
                    <Link key={w.symbol} to="/stock/$symbol" params={{ symbol: w.symbol }} className={textAction}>
                      {w.name}
                    </Link>
                  ))}
                </p>
              </div>
            )}
            {latest && (
              <p>
                <Link to="/market" hash="market-summary" className={textAction}>
                  收盤重點 →
                </Link>
              </p>
            )}
          </div>
        </div>
      )}
      <p className="text-xs text-ink-2">{r.disclaimer || FALLBACK_DISCLAIMER}</p>
      {discussable && (
        <>
          <div className="flex flex-wrap items-center gap-x-4">
            <Reactions groupId={groupId} target={`daily:${r.id}`} reactions={r.reactions!} />
            <CommentsToggle count={r.comment_count!} open={open} onToggle={() => setOpen(!open)} controls={threadId} />
          </div>
          {open && <CommentThread id={threadId} groupId={groupId} target={`daily:${r.id}`} className="border-l border-rule pl-3" />}
        </>
      )}
    </article>
  )
}
