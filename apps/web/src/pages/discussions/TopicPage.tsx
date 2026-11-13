import { useParams, useSearch } from "@tanstack/react-router"
import { EllipsisIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { useDeleteWithUndo, useReplies, useToggleDiscussionReaction, useTopic } from "@/api/discussion-queries"
import { useViewer } from "@/api/queries"
import { ApiError, type DiscussionAuthor, type DiscussionTarget, type Reaction, type ReactionEmoji, type Topic } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PlainLink } from "@/app/links"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { UserAvatar } from "@/components/avatar"
import { DateCell } from "@/components/date-cell"
import { ReactionChips } from "@/components/reaction-chips"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { usePendingDeletes } from "@/lib/delete-later"
import { cn } from "@/lib/utils"
import type { TopicSearch } from "@/router"
import { authorName, clockTime, HIDDEN_NOTE, HIDDEN_NOTE_WITH_BODY, taipeiDay } from "./labels"
import { topicOrigin, useGoToOrigin, type Origin } from "./origin"
import { BackLink } from "./OriginLink"
import { PlainText } from "./PlainText"
import { ReplyComposer } from "./ReplyComposer"
import { ReportDialog } from "./ReportDialog"
import { DATE_COL, Disclaimer, MetaLine, StockTags } from "./TopicRows"

type Reporting = { target: DiscussionTarget; what: string }

/** 一行最長約 40 個中文字（欄本身比這個寬：格線、動作那一列、回覆框撐滿欄寬，字不撐滿） */
const LINE = "max-w-[40em]"
/** 主題自己的內文比回覆大一級（17px）：問題和回答不是同一種字 */
const TOPIC_TEXT = "text-lg leading-[1.75]"
/** 回覆的字：墨色，手機 16px、桌面 15px，行高 1.75（長一點的中文段落讀起來不擠） */
const REPLY_TEXT = "text-[1rem] leading-[1.75] lg:text-base lg:leading-[1.75]"
/** 一則發言的那一列：左邊日期格、右邊內容（和討論清單同一個左緣） */
const POST_ROW = "flex gap-3"

/**
 * 主題頁：← 從哪裡來的（討論／群組名／股票名）→ 主題（日期格｜標題、作者・公開或群組、標記的股票、內文、表情）
 * → 回覆（每一則：日期格｜作者、內文、表情）→ 回覆區 → 免責（公開）。
 * 和討論清單同一個欄寬、同一個左緣：每一則發言的日期與時間掛在左邊的日期格，字從清單標題的位置開始——主題頁就是打開的那一列。
 * 公開的主題不用登入就能讀（沒登入時表情只顯示計數、股票是純文字、回覆區是「登入後發言」）。
 * 查看別人的資產時擋下（和群組一樣）。
 */
export function TopicPage() {
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="討論" />
  return <TopicView />
}

function TopicView() {
  const { topicId } = useParams({ from: "/discussions/$topicId" })
  const search = useSearch({ from: "/discussions/$topicId" }) as TopicSearch
  const { signedIn } = useViewer()
  const topic = useTopic(topicId)
  const missing = topic.error instanceof ApiError && topic.error.status === 404
  // 從群組或個股的「討論」分頁來的：名稱要等主題載入才知道，載入前麵包屑先留空位（不先寫「討論」再跳成別的）
  const origin = topicOrigin(search, topic.data, { signedIn, settled: !topic.isPending })
  return (
    <PageFrame className="lg:pt-6">
      <div className="max-w-measure">
        <nav aria-label="位置" className="flex min-h-11 items-center text-sm">
          {origin && <BackLink origin={origin} />}
        </nav>
        {missing ? (
          <TopicMissing />
        ) : topic.isError ? (
          <ErrorState error={topic.error} onRetry={() => void topic.refetch()} />
        ) : !topic.data || !origin ? (
          <div className={cn(POST_ROW, "pt-2")} aria-busy="true" aria-label="主題載入中">
            <div className={DATE_COL} />
            <div className="flex min-w-0 flex-1 flex-col gap-3">
              <Skeleton className="h-9 w-3/4" />
              <Skeleton className="h-4 w-56" />
              <SkeletonLines rows={4} className="mt-4" />
            </div>
          </div>
        ) : (
          // 換到另一個主題時整個重建（開著的檢舉框、選單不會留到下一個主題）
          <Loaded key={topic.data.id} topic={topic.data} origin={origin} />
        )}
      </div>
    </PageFrame>
  )
}

function TopicMissing() {
  const { signedIn } = useViewer()
  return (
    <div className="flex flex-col items-start gap-3 py-6">
      <h1 className="text-2xl font-bold">找不到這個主題</h1>
      <p className="max-w-prose text-ink-2">
        主題可能已經刪除。群組裡的主題只有成員看得到{signedIn ? "；你可能已經不在那個群組裡。" : "，要先登入。"}
      </p>
      <PlainLink to="/discussions" className={buttonVariants({ variant: "outline" })}>
        回到討論
      </PlainLink>
    </div>
  )
}

function Loaded({ topic, origin }: { topic: Topic; origin: Origin }) {
  const { signedIn } = useViewer()
  const goToOrigin = useGoToOrigin()
  const replies = useReplies(topic.id)
  const react = useToggleDiscussionReaction(topic.id)
  const del = useDeleteWithUndo()
  // 剛按了刪除、通知還沒結束的回覆：先從畫面拿掉（按「復原」就回來）
  const pending = usePendingDeletes((s) => s.keys)
  const [reporting, setReporting] = useState<Reporting | null>(null)
  const loaded = replies.data?.pages.flatMap((p) => p.items) ?? []
  const items = loaded.filter((r) => !pending.has(`reply:${r.id}`))
  const replyCount = Math.max(0, topic.reply_count - (loaded.length - items.length))
  const isPublic = topic.scope === "public"
  /**
   * 回覆是舊到新、只能一頁一頁往後讀：自己剛送出的那一則在最後面。送出之後把後面還沒讀的頁都讀進來
   * （最多 20 頁），不然回覆很多的主題會看不到自己剛寫的。
   */
  const loadToEnd = async () => {
    let data = (await replies.refetch({ cancelRefetch: false })).data
    for (let i = 0; i < 20 && data?.pages.at(-1)?.next_cursor; i++) data = (await replies.fetchNextPage()).data
  }
  const toggle = (target: DiscussionTarget) => (emoji: ReactionEmoji, on: boolean) =>
    react.mutate(
      { target, emoji, on },
      { onError: (err) => toast.error(err instanceof ApiError && err.status === 404 ? "這則內容已經看不到了" : "表情沒有送出，請再試一次") },
    )
  const topicHidden = topic.status === "hidden"

  return (
    <article>
      <div className={cn(POST_ROW, "mt-1")}>
        <PostDate iso={topic.created_at} pad="py-1" />
        <div className="min-w-0 flex-1">
          <header>
            {/* 標題不用 balance（硬把兩行排成一樣長，會把「定期定額」這種詞從中間拆開）；pretty 只避免最後一行剩一兩個字 */}
            <h1 className="text-xl font-bold tracking-[-0.01em] [text-wrap:pretty] break-words sm:text-2xl lg:text-3xl">{topic.title}</h1>
            <MetaLine className="mt-2 text-md text-ink-2">
              <Byline author={topic.author} group={!isPublic} />
              {isPublic || !topic.group ? (
                <span>{isPublic ? "公開" : "群組"}</span>
              ) : (
                <span>
                  <PlainLink
                    to="/groups/$groupId"
                    params={{ groupId: topic.group.id }}
                    search={{ tab: "discussions" }}
                    // 觸控的可按範圍往上多（上面是標題，不能按），往下只多 4px：下面緊接著「標記」的連結，不互相蓋住
                    className="underline decoration-ctl decoration-1 underline-offset-4 hover:text-ink hover:decoration-ink pointer-coarse:pt-5 pointer-coarse:pb-1"
                  >
                    {topic.group.name}
                  </PlainLink>
                </span>
              )}
            </MetaLine>
            {topic.symbols.length > 0 && (
              <p className="mt-1 text-md text-ink-2">
                標記：
                <StockTags symbols={topic.symbols} linked={signedIn} touch="inline" className="text-ink" />
              </p>
            )}
          </header>

          <div className="mt-5">
            {topicHidden && <p className="text-md text-ink-2">{topic.body === null ? HIDDEN_NOTE : HIDDEN_NOTE_WITH_BODY}</p>}
            {topic.body !== null && <PlainText text={topic.body} className={cn(TOPIC_TEXT, LINE, topicHidden && "mt-2")} />}
          </div>

          <ContentActions
            className="mt-4"
            reactions={topic.reactions}
            // 被站方隱藏的內容：表情只顯示計數（不能再加）、不能檢舉
            canReact={signedIn && !topicHidden}
            onToggle={toggle(`topic:${topic.id}`)}
            onDelete={
              topic.can_delete
                ? () => {
                    del.topic(topic)
                    // 主題已經從畫面拿掉：回到來的地方（那裡的通知可以復原）
                    void goToOrigin(origin, { replace: true })
                  }
                : undefined
            }
            onReport={topic.can_report && !topicHidden ? () => setReporting({ target: `topic:${topic.id}`, what: "主題" }) : undefined}
            what="主題"
          />
        </div>
      </div>

      <Section title="回覆" titleId="topic-replies" aside={replyCount > 0 ? <span className="num">{replyCount} 則</span> : undefined} className="mt-10" bodyClassName="pt-0">
        {replies.isError ? (
          <ErrorState flush error={replies.error} onRetry={() => void replies.refetch()} />
        ) : !replies.data ? (
          <SkeletonLines rows={4} className="pt-4" />
        ) : items.length === 0 ? (
          <EmptyState flush title="還沒有回覆" />
        ) : (
          <ol aria-label="回覆">
            {items.map((r) => {
              const hidden = r.status === "hidden"
              return (
                <li key={r.id} className={cn(POST_ROW, "border-b border-rule py-3.5")}>
                  <PostDate iso={r.created_at} pad="-my-3.5 py-3.5" />
                  <div className="min-w-0 flex-1">
                    <div className="flex min-h-6 flex-wrap items-center gap-x-2 text-md text-ink-2">
                      <Byline author={r.author} group={!isPublic} />
                    </div>
                    <div className="mt-1">
                      {hidden && <p className="text-md text-ink-2">{r.body === null ? HIDDEN_NOTE : HIDDEN_NOTE_WITH_BODY}</p>}
                      {r.body !== null && <PlainText text={r.body} className={cn(REPLY_TEXT, LINE)} />}
                    </div>
                    <ContentActions
                      className="mt-1"
                      reactions={r.reactions}
                      canReact={signedIn && !hidden}
                      onToggle={toggle(`reply:${r.id}`)}
                      onDelete={r.can_delete ? () => del.reply(topic.id, r.id) : undefined}
                      onReport={r.can_report && !hidden ? () => setReporting({ target: `reply:${r.id}`, what: "回覆" }) : undefined}
                      what={`${authorName(r.author)}的回覆`}
                    />
                  </div>
                </li>
              )
            })}
          </ol>
        )}
        {replies.hasNextPage && (
          <Button variant="outline" className="mt-4" disabled={replies.isFetchingNextPage} onClick={() => void replies.fetchNextPage()}>
            {replies.isFetchingNextPage ? "載入中…" : "看更多回覆"}
          </Button>
        )}
      </Section>

      {/* 回覆區和每一則發言同一個左緣（日期格那一欄留白）；手機上那一欄只有 52px 的空白，回覆框改成撐滿整列，打字的地方才夠寬 */}
      <div className={cn(POST_ROW, "mt-6")}>
        <div aria-hidden className={cn(DATE_COL, "max-sm:hidden")} />
        <div className="min-w-0 flex-1">
          <ReplyComposer topic={topic} onPosted={() => void loadToEnd()} />
          {isPublic && <Disclaimer className="mt-8" />}
        </div>
      </div>

      {reporting && <ReportDialog target={reporting.target} what={reporting.what} onClose={() => setReporting(null)} />}
    </article>
  )
}

/**
 * 一則發言左邊的日期格（聯絡簿的那一格）：日期＋星期，下面是時間；貼著這一則的上緣，格線跟著這一則一樣高。
 * 手機是窄的三行（日期／星期／時間），和討論清單同一欄。
 */
function PostDate({ iso, pad }: { iso: string; pad: string }) {
  return (
    <DateCell date={taipeiDay(iso)} pad={pad} className={cn(DATE_COL, "justify-start")}>
      <time dateTime={iso} className="num mt-0.5 text-sm font-normal text-ink-2">
        <span className="sr-only">發表於</span>
        {clockTime(iso)}
      </time>
    </DateCell>
  )
}

/**
 * 作者。公開範圍只有公開暱稱（沒有頭像）；群組範圍和群組動態一樣有頭像與顯示名稱。
 * 自己的內容用字標示「（你）」；帳號已刪除、已離開群組的作者是淡墨。時間在左邊的日期格。
 */
function Byline({ author, group }: { author: DiscussionAuthor; group: boolean }) {
  const name = authorName(author)
  const known = author.name !== null && !(group && author.user_id === null)
  return (
    <span className="inline-flex min-w-0 items-center gap-x-2">
      {group && <UserAvatar name={name} url={author.avatar_url} size="sm" />}
      <span className="min-w-0">
        <span className={cn("text-md", known ? "font-medium text-ink" : "text-ink-2")}>{name}</span>
        {author.is_you && <span className="text-md text-ink [font-feature-settings:'halt'_1]">（你）</span>}
      </span>
    </span>
  )
}

/**
 * 一則內容（主題或回覆）底下的那一列：表情（方肩的小格＋「加表情」；不能按表情時只顯示計數）在左，
 * 右邊一個「更多動作」（⋯）收著「刪除」「檢舉」——每一則都重複的動作不再一排排寫出來；沒有可做的動作就沒有這顆。
 */
function ContentActions({
  reactions,
  canReact,
  onToggle,
  onDelete,
  onReport,
  what,
  className,
}: {
  reactions: Reaction[]
  /** 可以按表情（登入，而且這則沒有被站方隱藏）；否則只顯示計數 */
  canReact: boolean
  onToggle: (emoji: ReactionEmoji, on: boolean) => void
  onDelete?: () => void
  onReport?: () => void
  /** 這一則的稱呼（按鈕的無障礙名稱：「主題的更多動作」「阿土伯的回覆的更多動作」） */
  what: string
  className?: string
}) {
  const more = !!(onDelete || onReport)
  if (!canReact && reactions.length === 0 && !more) return null
  return (
    <div className={cn("flex min-h-9 flex-wrap items-center gap-x-4 gap-y-1", className)}>
      <ReactionChips reactions={reactions} onToggle={onToggle} readOnly={!canReact} />
      {more && (
        <DropdownMenu>
          <Tooltip>
            <TooltipTrigger
              render={
                <DropdownMenuTrigger
                  render={
                    <button
                      type="button"
                      aria-label={`${what}的更多動作`}
                      className="press -mr-2 ml-auto grid size-9 shrink-0 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink aria-expanded:bg-sel aria-expanded:text-ink pointer-coarse:size-11"
                    />
                  }
                />
              }
            >
              <EllipsisIcon aria-hidden className="size-5" />
            </TooltipTrigger>
            <TooltipContent>更多動作</TooltipContent>
          </Tooltip>
          <DropdownMenuContent align="end" className="w-36">
            {onDelete && <DropdownMenuItem onClick={onDelete}>刪除</DropdownMenuItem>}
            {onReport && <DropdownMenuItem onClick={onReport}>檢舉…</DropdownMenuItem>}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}

