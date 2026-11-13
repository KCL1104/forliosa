import { Link, useRouterState } from "@tanstack/react-router"
import { Fragment } from "react"
import { useTopics, type TopicListFilter } from "@/api/discussion-queries"
import { useViewer } from "@/api/queries"
import { usePendingDeletes } from "@/lib/delete-later"
import type { TopicSummary, TopicSymbol } from "@/api/types"
import type { TopicSearch } from "@/router"
import { PlainLink } from "@/app/links"
import { DateCell } from "@/components/date-cell"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { safeNext } from "@/lib/next-path"
import { cn } from "@/lib/utils"
import { ABOUT_FORLIOSA, authorName, clockTime, DISCLAIMER, taipeiDay } from "./labels"
import { topicSearchFrom, type Origin } from "./origin"

/** 日期格那一欄：手機是窄的三行（日期／星期／時間，和交易列表同寬），標題才有地方寫；桌面一行日期＋一行時間。主題頁用同一欄 */
export const DATE_COL = "w-[3.25rem] shrink-0 lg:w-[6.5rem]"

/**
 * 一行用「・」隔開的 meta（作者・N 則回覆・標記的股票・群組）。每一項是一個不拆開的單位，放不下就整項換到下一行；
 * 「・」畫在每一項的前面、第一項的那一個被裁掉——所以換行之後行首、行尾都不會掛著一個「・」（`.meta-line`，globals.css）。
 */
export function MetaLine({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("meta-line", className)}>
      <div>{children}</div>
    </div>
  )
}

/**
 * 每個公開討論頁底部固定的一行（12px 淡墨）。沒登入的訪客在它下面多一行：Forliosa 是什麼＋「登入」
 * （登入後回到現在這一頁）——不然從搜尋或別人貼的連結進來的人，整頁沒有一句話說這是什麼地方。
 */
export function Disclaimer({ className }: { className?: string }) {
  const { signedIn } = useViewer()
  const next = safeNext(useRouterState({ select: (s) => s.location.href }))
  return (
    <div className={className}>
      <p className="text-xs text-ink-2">{DISCLAIMER}</p>
      {!signedIn && (
        <p className="mt-1 text-sm text-ink-2">
          {ABOUT_FORLIOSA}
          <Link to="/login" search={next === "/" ? {} : { next }} className={cn(textAction, "ml-2 text-sm")}>
            登入
          </Link>
        </p>
      )}
    </div>
  )
}

/**
 * 標記的股票（主題列的 meta、主題頁）：登入時是文字連結（常駐 ctl 色底線，連到個股頁），沒登入是純文字
 * （個股頁要登入）。名稱和代號之間是空白字元，底線才連成一條；一檔是一個不拆開的單位（放不下就整檔換到下一行）。
 * `touch`：觸控裝置上怎麼辦——
 * - `row`（清單列的 meta）：整列已經是一個連結，一行 13px 的字裡再塞幾個 44px 的可按範圍會緊貼在標題下面、容易按錯，
 *   所以觸控時股票只是字（不接收點按、沒有底線），按下去是打開主題；股票的連結在主題頁。滑鼠與鍵盤照常是連結。
 * - `inline`（主題頁）：連結上下各多 12px 的可按範圍（合計 44px 以上）。
 */
export function StockTags({ symbols, linked, touch, className }: { symbols: TopicSymbol[]; linked: boolean; touch: "row" | "inline"; className?: string }) {
  return (
    <>
      {symbols.map((s, i) => (
        <Fragment key={s.symbol}>
          {i > 0 && "、"}
          {linked ? (
            <Link
              to="/stock/$symbol"
              params={{ symbol: s.symbol }}
              className={cn(
                "relative inline-block underline decoration-ctl decoration-1 underline-offset-4 hover:text-ink hover:decoration-ink",
                touch === "row" ? "z-10 pointer-coarse:pointer-events-none pointer-coarse:no-underline" : "pointer-coarse:py-3",
                className,
              )}
            >
              {s.name} <span className="num">{s.code}</span>
            </Link>
          ) : (
            <span className={cn("inline-block", className)}>
              {s.name} <span className="num">{s.code}</span>
            </span>
          )}
        </Fragment>
      ))}
    </>
  )
}

/**
 * 主題清單（討論頁、個股的「討論」分頁、群組的「討論」分頁共用）：印好的表頭＋一列一格的格線列，不是卡片。
 * 每一列：聯絡簿的日期格（依排序是最後回覆或發表的時間）→ 標題（17px 墨色 500）→ 一行 13px 淡墨的 meta：
 * 作者・N 則回覆・標記的股票（文字連結）・群組名稱（群組範圍的主題）。整列都可以按（標題連結的 `::after` 蓋滿整列）；
 * 股票連結浮在上面（觸控時只是字，見 `StockTags`）。看更多＝下一頁。只要畫面上有公開內容，最下面固定一行免責。
 * 換篩選或排序時，新的清單回來之前先留著原本的列（不閃成骨架）。
 */
export function TopicRows({
  filter,
  origin,
  enabled = true,
  signedIn,
  showGroup = true,
  empty,
  className,
}: {
  filter: TopicListFilter
  /** 這份清單在哪裡（討論清單、群組或個股的「討論」分頁）：打開的主題用它回到這裡 */
  origin: Origin
  enabled?: boolean
  /** 沒登入：標記的股票是純文字（個股頁要登入） */
  signedIn: boolean
  /** 群組範圍的主題要不要寫群組名稱（群組自己的分頁裡不用） */
  showGroup?: boolean
  empty: { title: string; description?: React.ReactNode }
  className?: string
}) {
  const topics = useTopics(filter, enabled)
  // 剛按了刪除、通知還沒結束的主題：先從清單拿掉（按「復原」就回來）
  const pending = usePendingDeletes((s) => s.keys)
  const items = (topics.data?.pages.flatMap((p) => p.items) ?? []).filter((t) => !pending.has(`topic:${t.id}`))
  const byNew = filter.sort === "new"
  const search = topicSearchFrom(origin)
  return (
    <div className={cn("flex flex-col", className)}>
      {topics.isError ? (
        <ErrorState error={topics.error} onRetry={() => void topics.refetch()} />
      ) : !topics.data ? (
        <SkeletonLines rows={6} className="pt-2" />
      ) : items.length === 0 ? (
        <EmptyState title={empty.title} description={empty.description} />
      ) : (
        <>
          <div aria-hidden className="form-head flex gap-3 pb-2">
            <span className={DATE_COL}>{byNew ? "發表" : "最後回覆"}</span>
            <span>主題</span>
          </div>
          <ul aria-label="主題">
            {items.map((t) => (
              <TopicRow key={t.id} t={t} byNew={byNew} linked={signedIn} showGroup={showGroup} search={search} />
            ))}
          </ul>
          {topics.hasNextPage && (
            <Button variant="outline" className="mt-4 self-start" disabled={topics.isFetchingNextPage} onClick={() => void topics.fetchNextPage()}>
              {topics.isFetchingNextPage ? "載入中…" : "看更多"}
            </Button>
          )}
          {items.some((t) => t.scope === "public") && <Disclaimer className="mt-6" />}
        </>
      )}
    </div>
  )
}

function TopicRow({ t, byNew, linked, showGroup, search }: { t: TopicSummary; byNew: boolean; linked: boolean; showGroup: boolean; search: TopicSearch }) {
  const when = byNew ? t.created_at : t.last_activity_at
  return (
    <li className="ruled-row relative flex min-h-[72px] items-center gap-3 py-3">
      <DateCell date={taipeiDay(when)} pad="-my-3 py-3" className={DATE_COL}>
        <span className="num mt-0.5 text-sm font-normal text-ink-2">
          <span className="sr-only">{byNew ? "發表於" : "最後回覆"}</span>
          {clockTime(when)}
        </span>
      </DateCell>
      <div className="min-w-0 flex-1">
        <PlainLink
          to="/discussions/$topicId"
          params={{ topicId: t.id }}
          search={search}
          className="block rounded-xs text-lg font-medium text-ink after:absolute after:inset-0 focus-visible:-outline-offset-2"
        >
          <span className="line-clamp-3 [text-wrap:pretty] break-words">{t.title}</span>
        </PlainLink>
        <MetaLine className="mt-0.5 text-sm text-ink-2">
          <span>
            {authorName(t.author)}
            {t.author.is_you && <span className="text-ink [font-feature-settings:'halt'_1]">（你）</span>}
          </span>
          <span className="num">{t.reply_count > 0 ? `${t.reply_count} 則回覆` : "還沒有回覆"}</span>
          {t.symbols.length > 0 && (
            <span>
              <StockTags symbols={t.symbols} linked={linked} touch="row" />
            </span>
          )}
          {showGroup && t.group && <span>{t.group.name}</span>}
        </MetaLine>
      </div>
    </li>
  )
}
