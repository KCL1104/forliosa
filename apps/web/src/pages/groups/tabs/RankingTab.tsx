import { Link } from "@tanstack/react-router"
import { ArrowDownIcon } from "lucide-react"
import { useState } from "react"
import { useLeaderboard } from "@/api/sharing-queries"
import type { Group, Leaderboard, LeaderboardEntry, LeaderboardPeriod } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { DataNotes } from "@/components/data-notes"
import { Pct } from "@/components/finance"
import { DemoTag, Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
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
 * 排行：今日・本月・今年（可對照加權報酬指數與 0050）。名次依期間報酬排，所以期間報酬是主數字
 * （較大較粗；表頭墨色＋排序箭頭，桌面的表頭帶 aria-sort）；總報酬（含股利）是一般字級的一欄，不排名。兩個都有 ▲▼。
 * 只列出伺服器回來的人（沒開報酬率的人不在裡面，也不標「未分享」）；期間報酬算不出來是「—」，不說原因。
 * 沒有收盤價的持股（美股）不算進期間報酬，只在自己那一列標「不含美股」。
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
            {!b.ranked && <p className="text-base text-ink">這個群組不排名次，依加入順序列出。</p>}
            {b.entries.length === 0 ? (
              <EmptyState title="還沒有資料" />
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

/** 報酬率：null 顯示「—」（不說明原因；一般字重，不跟著主數字加粗） */
function Ret({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) {
    return (
      <span className={cn("num font-normal text-ink-2", className)}>
        —<span className="sr-only">沒有資料</span>
      </span>
    )
  }
  return <Pct value={value} className={className} />
}

/**
 * 成員名稱（連到成員頁）：連結撐滿所在的格子或整列（`after:inset-0`，容器要 `relative`），整列都按得到。
 * 自己的那一列用字標示——名字 700＋墨色「（你）」——不用底色（淡墨底是 hover／選取的語法）。
 */
function MemberName({ e, groupId, avatar = true }: { e: LeaderboardEntry; groupId: string; avatar?: boolean }) {
  return (
    <Link
      to="/groups/$groupId/members/$userId"
      params={{ groupId, userId: e.user_id }}
      className="group/name flex min-w-0 items-center gap-2.5 after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-ink"
    >
      {avatar && <UserAvatar name={e.display_name} url={e.avatar_url} size="sm" />}
      <span className="flex min-w-0 items-baseline">
        <span className={cn("truncate text-lg group-hover/name:underline", e.is_me ? "font-bold" : "font-medium")}>{e.display_name}</span>
        {e.is_me && <span className="shrink-0 text-sm font-medium text-ink">（你）</span>}
        {/* 期間報酬只算有收盤價的持股（和帳本的「今日」同一條規則）：只在自己那一列說 */}
        {e.is_me && e.excludes_unpriced && <span className="shrink-0 text-sm text-ink-2">不含美股</span>}
      </span>
    </Link>
  )
}

/** 排序中的欄位：墨色字＋箭頭（▲▼ 是價格漲跌的符號，不拿來表示排序） */
function SortedLabel({ children, sorted }: { children: React.ReactNode; sorted: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-0.5", sorted && "text-ink")}>
      {children}
      {sorted && <ArrowDownIcon aria-hidden className="size-3.5" />}
    </span>
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
          {/* 名次依這一欄由高到低排（不排名次的群組依加入順序，沒有箭頭） */}
          <th scope="col" className="h-10 w-44 text-right" aria-sort={board.ranked ? "descending" : undefined}>
            <SortedLabel sorted={board.ranked}>{label}報酬</SortedLabel>
          </th>
          <th scope="col" className="h-10 w-44 text-right">
            總報酬（含股利）
          </th>
        </tr>
      </thead>
      <tbody>
        {board.entries.map((e) => (
          <tr key={e.user_id} className="h-[60px] border-b border-rule">
            {board.ranked && <td className="num text-lg font-medium">{e.rank ?? ""}</td>}
            <th scope="row" className="relative pr-3 text-left font-normal">
              <MemberName e={e} groupId={groupId} />
            </th>
            <td className="text-right text-xl font-semibold">
              <Ret value={e.return_pct} />
            </td>
            <td className="text-right text-base">
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
            // 對照只有期間報酬：對齊上面的期間欄（一般字級，不和成員的主數字搶），總報酬欄留空
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

/**
 * 手機排行的欄：名次・成員・期間報酬（主數字）・總報酬。數字欄有最小寬、放不下時再長（三位數的報酬不會超出右緣）；
 * 表頭、每一列與對照都是同一個 grid 的 subgrid，所以欄寬變了也一起對齊。手機不放頭像，名字（和「（你）」）才放得下。
 */
const MOBILE_COLS = (ranked: boolean) =>
  ranked ? "grid-cols-[1.75rem_minmax(0,1fr)_minmax(5rem,auto)_minmax(4.25rem,auto)]" : "grid-cols-[minmax(0,1fr)_minmax(5rem,auto)_minmax(4.25rem,auto)]"
const SUB = "col-span-full grid grid-cols-subgrid"

function BoardList({ board, groupId }: { board: Leaderboard; groupId: string }) {
  const label = PERIOD_LABEL[board.period]
  return (
    <div className={cn("grid gap-x-3 md:hidden", MOBILE_COLS(board.ranked))}>
      {/* 印好的表頭；名次依期間報酬排，所以那一欄是墨色＋箭頭 */}
      <div aria-hidden className={cn("form-head h-10 items-end pb-2", SUB)}>
        {board.ranked && <span className="text-center">名次</span>}
        <span>成員</span>
        <span className="text-right">
          <SortedLabel sorted={board.ranked}>{label}</SortedLabel>
        </span>
        <span className="text-right">總報酬</span>
      </div>
      <ol aria-label={`${label}排行`} className={SUB}>
        {board.entries.map((e) => (
          <li key={e.user_id} className={cn("ruled-row relative min-h-16 items-center py-2", SUB)}>
            {board.ranked && <span className="num text-center text-lg font-medium">{e.rank ?? ""}</span>}
            <span className="min-w-0">
              <MemberName e={e} groupId={groupId} avatar={false} />
            </span>
            <span className="text-right text-lg font-semibold">
              <span className="sr-only">{label}報酬</span>
              <Ret value={e.return_pct} />
            </span>
            <span className="text-right text-base">
              <span className="sr-only">總報酬（含股利）</span>
              <Ret value={e.total_return_pct} />
            </span>
          </li>
        ))}
      </ol>
      {board.benchmarks.length > 0 && (
        <ul aria-label="對照" className={cn("mt-4", SUB)}>
          {board.benchmarks.map((x) => (
            // 對照只有期間報酬：對齊上面的期間欄，總報酬欄留空
            <li key={x.symbol} className={cn("h-11 items-center border-b border-rule text-base", SUB)}>
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
  return <p className="text-base text-ink">這段期間算不出你的報酬。美股沒有收盤價，不算在內。</p>
}

/** 當天排行的討論串（`leaderboard:<date>`）。排行的回應沒有表情計數，所以這裡只有留言（見 OPEN_QUESTIONS） */
function LeaderboardThread({ groupId, date }: { groupId: string; date: string }) {
  return (
    <Section title={`${formatDateShort(date)}的討論`} titleId="rank-thread">
      <CommentThread groupId={groupId} target={`leaderboard:${date}`} />
    </Section>
  )
}
