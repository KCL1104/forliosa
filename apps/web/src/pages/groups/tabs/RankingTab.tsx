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
 * 排行：今日・本月・今年（可對照加權報酬指數與 0050），另一欄總報酬（含股利）不排名。
 * 只列出伺服器回來的人（沒開報酬率的人不在裡面，也不標「未分享」）；期間報酬算不出來是「—」，不說原因。
 * 下面是當天排行的討論串。
 */
export function RankingTab({ group }: { group: Group }) {
  const [period, setPeriod] = useState<LeaderboardPeriod>("day")
  const board = useLeaderboard(group.id, period)
  const b = board.data
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
            {b.sources.length > 0 && (
              <ul className="flex flex-col gap-0.5 text-xs text-ink-2">
                {b.sources.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            )}
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
      <thead>
        <tr className="text-sm text-ink-2">
          {board.ranked && (
            <th scope="col" className="h-10 w-16 border-b border-rule text-left font-normal">
              名次
            </th>
          )}
          <th scope="col" className="h-10 border-b border-rule text-left font-normal">
            成員
          </th>
          <th scope="col" className="h-10 w-40 border-b border-rule text-right font-normal">
            {label}報酬
          </th>
          <th scope="col" className="h-10 w-48 border-b border-rule text-right font-normal">
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
            <td className="text-right text-base text-ink-2">
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
              <th scope="row" className="text-left text-base font-normal text-ink-2">
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

function BoardList({ board, groupId }: { board: Leaderboard; groupId: string }) {
  const label = PERIOD_LABEL[board.period]
  return (
    <div className="md:hidden">
      <ol aria-label={`${label}排行`} className="border-t border-rule">
        {board.entries.map((e) => (
          <li
            key={e.user_id}
            className={cn("grid min-h-[72px] items-center gap-x-3 border-b border-rule py-2", board.ranked ? "grid-cols-[auto_minmax(0,1fr)_auto]" : "grid-cols-[minmax(0,1fr)_auto]", e.is_me && "bg-hov")}
          >
            {board.ranked && <span className="num w-6 text-center text-lg font-medium">{e.rank ?? ""}</span>}
            <span className="min-w-0">
              <MemberName e={e} groupId={groupId} />
              <span className="mt-0.5 flex items-baseline gap-1.5 pl-[38px] text-sm text-ink-2">
                總報酬 <Ret value={e.total_return_pct} />
              </span>
            </span>
            <Ret value={e.return_pct} className="text-lg" />
          </li>
        ))}
      </ol>
      {board.benchmarks.length > 0 && (
        <ul aria-label="對照" className="mt-4">
          {board.benchmarks.map((x) => (
            <li key={x.symbol} className="flex h-11 items-center justify-between border-b border-rule text-base">
              <span className="text-ink-2">{x.name}</span>
              <Ret value={x.return_pct} />
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
