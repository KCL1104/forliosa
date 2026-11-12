import { Link } from "@tanstack/react-router"
import { useState } from "react"
import { useLeaderboard } from "@/api/sharing-queries"
import type { Group, Leaderboard, LeaderboardEntry, LeaderboardPeriod } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { DataNotes } from "@/components/data-notes"
import { Pct } from "@/components/finance"
import { DemoTag, Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { ErrorState, SkeletonLines } from "@/components/states"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"
import { CommentThread } from "../Discussion"
import { PERIOD_LABEL } from "../labels"

const PERIODS: { value: LeaderboardPeriod; label: string }[] = [
  { value: "day", label: "今日" },
  { value: "month", label: "本月" },
  { value: "year", label: "今年" },
]

/**
 * 排行：今日・本月・今年（可對照加權報酬指數與 0050），另一欄總報酬（含股利）不排名，和期間報酬一樣大（不是小字第二行）。
 * 只列出伺服器回來的人（沒開報酬率的人不在裡面，也不標「未分享」）；期間報酬算不出來是「—」，不說原因。
 * 下面是當天排行的討論串。
 */
export function RankingTab({ group }: { group: Group }) {
  const [period, setPeriod] = useState<LeaderboardPeriod>("day")
  const board = useLeaderboard(group.id, period)
  const b = board.data
  // 資料來源放到頁尾（一頁一次），不在排行下面逐條列出
  useSourceNote(b?.sources)
  return (
    <div className="flex flex-col gap-10">
      <section aria-labelledby="rank-title" className="flex flex-col gap-3">
        <h2 id="rank-title" className="sr-only">
          排行
        </h2>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <RangeChips label="期間" value={period} onChange={setPeriod} options={PERIODS} />
          {b && (
            <p className="num text-sm text-ink-2">
              {formatDateShort(b.start_date, false)} 收盤 → {formatDateShort(b.date, false)} 收盤
              {b.is_demo && <DemoTag className="ml-2" />}
            </p>
          )}
        </div>
        {board.isError ? (
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        ) : !b ? (
          <SkeletonLines rows={5} />
        ) : (
          <>
            {!b.ranked && <p className="text-md text-ink-2">這個群組不排名次，依加入順序列出。</p>}
            {b.entries.length === 0 ? (
              <p className="border-y border-rule py-6 text-ink-2">還沒有資料。</p>
            ) : (
              <>
                <BoardTable board={b} groupId={group.id} />
                <BoardList board={b} groupId={group.id} />
              </>
            )}
            <MyNullNote entries={b.entries} />
            <DataNotes notes={b.notes} />
          </>
        )}
      </section>
      {b && <LeaderboardThread groupId={group.id} date={b.date} />}
    </div>
  )
}

/** 期間報酬：null 顯示「—」（不說明原因） */
function Ret({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) {
    return (
      <span className={cn("num text-ink-2", className)}>
        —<span className="sr-only">沒有資料</span>
      </span>
    )
  }
  return <Pct value={value} className={className} />
}

function MemberName({ e, groupId }: { e: LeaderboardEntry; groupId: string }) {
  return (
    <Link to="/groups/$groupId/members/$userId" params={{ groupId, userId: e.user_id }} className="flex min-w-0 items-center gap-2.5 hover:underline">
      <UserAvatar name={e.display_name} url={e.avatar_url} size="sm" />
      <span className="truncate text-lg font-medium">{e.display_name}</span>
      {e.is_me && <span className="shrink-0 text-sm text-ink-2">（你）</span>}
    </Link>
  )
}

function BoardTable({ board, groupId }: { board: Leaderboard; groupId: string }) {
  const label = PERIOD_LABEL[board.period]
  return (
    <table className="w-full border-collapse max-md:hidden" aria-label={`${label}排行`}>
      <thead className="form-head">
        <tr>
          {board.ranked && (
            <th scope="col" className="h-10 w-16 text-left">
              名次
            </th>
          )}
          <th scope="col" className="h-10 text-left">
            成員
          </th>
          <th scope="col" className="h-10 w-40 text-right">
            {label}報酬
          </th>
          <th scope="col" className="h-10 w-48 text-right">
            總報酬（含股利）<span className="sr-only">，不排名</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {board.entries.map((e) => (
          <tr key={e.user_id} className={cn("h-[60px] border-b border-rule", e.is_me && "bg-hov")}>
            {board.ranked && <td className="num text-lg font-medium">{e.rank ?? ""}</td>}
            <th scope="row" className="pr-3 text-left font-normal">
              <MemberName e={e} groupId={groupId} />
            </th>
            <td className="text-right text-lg">
              <Ret value={e.return_pct} />
            </td>
            <td className="text-right text-lg font-medium">
              <Ret value={e.total_return_pct} />
            </td>
          </tr>
        ))}
      </tbody>
      {board.benchmarks.length > 0 && (
        <tbody>
          <tr>
            <th scope="colgroup" colSpan={board.ranked ? 4 : 3} className="h-12 border-b border-rule pt-4 text-left align-bottom text-sm font-normal text-ink-2">
              對照
            </th>
          </tr>
          {board.benchmarks.map((x) => (
            <tr key={x.symbol} className="h-12 border-b border-rule">
              {board.ranked && <td />}
              <th scope="row" className="text-left text-base font-normal">
                {x.name}
              </th>
              <td className="text-right text-base">
                <Ret value={x.return_pct} />
              </td>
              <td />
            </tr>
          ))}
        </tbody>
      )}
    </table>
  )
}

/** 手機排行的欄：名次・成員・期間報酬・總報酬（兩個數字欄固定寬，對齊） */
const MOBILE_COLS = (ranked: boolean) => (ranked ? "grid-cols-[1.75rem_minmax(0,1fr)_4.75rem_5.25rem]" : "grid-cols-[minmax(0,1fr)_4.75rem_5.25rem]")

function BoardList({ board, groupId }: { board: Leaderboard; groupId: string }) {
  const label = PERIOD_LABEL[board.period]
  return (
    <div className="md:hidden">
      {/* 印好的表頭：兩個數字一樣大，總報酬（含股利）在最右邊 */}
      <div aria-hidden className={cn("form-head grid h-10 items-end gap-x-3 pb-2", MOBILE_COLS(board.ranked))}>
        {board.ranked && <span className="text-center">名次</span>}
        <span>成員</span>
        <span className="text-right">{label}</span>
        <span className="text-right">總報酬</span>
      </div>
      <ol aria-label={`${label}排行`}>
        {board.entries.map((e) => (
          <li key={e.user_id} className={cn("grid min-h-16 items-center gap-x-3 border-b border-rule py-2", MOBILE_COLS(board.ranked), e.is_me && "bg-hov")}>
            {board.ranked && <span className="num text-center text-lg font-medium">{e.rank ?? ""}</span>}
            <span className="min-w-0">
              <MemberName e={e} groupId={groupId} />
            </span>
            <span className="text-right text-lg">
              <span className="sr-only">{label}報酬</span>
              <Ret value={e.return_pct} />
            </span>
            <span className="text-right text-lg font-medium">
              <span className="sr-only">總報酬（含股利）</span>
              <Ret value={e.total_return_pct} />
            </span>
          </li>
        ))}
      </ol>
      {board.benchmarks.length > 0 && (
        <ul aria-label="對照" className="mt-4">
          {board.benchmarks.map((x) => (
            // 對照只有期間報酬：對齊上面的期間欄，總報酬欄留空
            <li key={x.symbol} className={cn("grid h-11 items-center gap-x-3 border-b border-rule text-base", MOBILE_COLS(board.ranked))}>
              {board.ranked && <span />}
              <span className="truncate">{x.name}</span>
              <span className="text-right">
                <span className="sr-only">{label}報酬</span>
                <Ret value={x.return_pct} />
              </span>
              <span />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 只對我自己說明為什麼我的期間報酬是「—」（別人的不說明） */
function MyNullNote({ entries }: { entries: LeaderboardEntry[] }) {
  const me = entries.find((e) => e.is_me)
  if (!me || me.return_pct !== null) return null
  return <p className="text-md text-ink-2">你的持股裡有沒有收盤價的股票（例如美股），期間報酬算不出來；總報酬照常列出。</p>
}

/** 當天排行的討論串（`leaderboard:<date>`）。排行的回應沒有表情計數，所以這裡只有留言（見 OPEN_QUESTIONS） */
function LeaderboardThread({ groupId, date }: { groupId: string; date: string }) {
  return (
    <Section title={`${formatDateShort(date)}的討論`} titleId="rank-thread">
      <CommentThread groupId={groupId} target={`leaderboard:${date}`} />
    </Section>
  )
}
