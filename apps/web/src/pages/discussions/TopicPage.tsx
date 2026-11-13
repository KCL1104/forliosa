import { Link, useNavigate, useParams } from "@tanstack/react-router"
import { ArrowLeftIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { useDeleteReply, useDeleteTopic, useReplies, useToggleDiscussionReaction, useTopic } from "@/api/discussion-queries"
import { useViewer } from "@/api/queries"
import { ApiError, type DiscussionAuthor, type DiscussionTarget, type Reaction, type ReactionEmoji, type Reply, type Topic } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PlainLink } from "@/app/links"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { UserAvatar } from "@/components/avatar"
import { QUIET_ACTION, ReactionChips } from "@/components/reaction-chips"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { authorName, HIDDEN_NOTE, HIDDEN_NOTE_WITH_BODY } from "./labels"
import { PlainText } from "./PlainText"
import { PostedTime } from "./PostedTime"
import { ReplyComposer } from "./ReplyComposer"
import { ReportDialog } from "./ReportDialog"
import { Disclaimer, StockTags } from "./TopicRows"

type Confirm = { kind: "topic"; replyCount: number } | { kind: "reply"; reply: Reply }
type Reporting = { target: DiscussionTarget; what: string }

/** 讀的行長：內文、回覆、回覆框同一欄，最寬 68ch（約 38 個中文字） */
const MEASURE = "w-full max-w-[68ch]"
/** 內文與回覆的字：墨色，手機 16px、桌面 15px，行高 1.75（長一點的中文段落讀起來不擠） */
const BODY_TEXT = "text-[1rem] leading-[1.75] lg:text-base lg:leading-[1.75]"

/**
 * 主題頁：← 討論 → 標題 → 作者・時間・公開或群組名稱 → 標記的股票 → 內文 → 表情 → 回覆（格線列）→ 回覆區 → 免責（公開）。
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
  const topic = useTopic(topicId)
  const missing = topic.error instanceof ApiError && topic.error.status === 404
  return (
    <PageFrame className="lg:pt-6">
      <nav aria-label="位置" className="flex min-h-11 items-center text-sm">
        <PlainLink to="/discussions" className="-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11">
          <ArrowLeftIcon aria-hidden className="size-4" />
          討論
        </PlainLink>
      </nav>
      {missing ? (
        <TopicMissing />
      ) : topic.isError ? (
        <ErrorState error={topic.error} onRetry={() => void topic.refetch()} />
      ) : !topic.data ? (
        <div className={cn(MEASURE, "flex flex-col gap-3 pt-2")} aria-busy="true" aria-label="主題載入中">
          <Skeleton className="h-9 w-3/4" />
          <Skeleton className="h-4 w-56" />
          <SkeletonLines rows={4} className="mt-4" />
        </div>
      ) : (
        <Loaded topic={topic.data} />
      )}
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
      <Link to="/discussions" className={buttonVariants({ variant: "outline" })}>
        回到討論
      </Link>
    </div>
  )
}

function Loaded({ topic }: { topic: Topic }) {
  const { signedIn } = useViewer()
  const navigate = useNavigate()
  const replies = useReplies(topic.id)
  const react = useToggleDiscussionReaction(topic.id)
  const deleteTopic = useDeleteTopic()
  const deleteReply = useDeleteReply(topic.id)
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [reporting, setReporting] = useState<Reporting | null>(null)
  const items = replies.data?.pages.flatMap((p) => p.items) ?? []
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

  return (
    <article className={MEASURE}>
      <header className="mt-1">
        <h1 className="text-2xl font-bold tracking-[-0.01em] break-words lg:text-3xl">{topic.title}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 text-md text-ink-2">
          <Byline author={topic.author} at={topic.created_at} group={!isPublic} where={isPublic ? "公開" : (topic.group?.name ?? "群組")} />
        </div>
        {topic.symbols.length > 0 && (
          <p className="mt-1 text-md text-ink-2">
            標記：
            <StockTags symbols={topic.symbols} linked={signedIn} touch="inline" className="text-ink" />
          </p>
        )}
      </header>

      <div className="mt-5">
        {topic.status === "hidden" && <p className="text-md text-ink-2">{topic.body === null ? HIDDEN_NOTE : HIDDEN_NOTE_WITH_BODY}</p>}
        {topic.body !== null && <PlainText text={topic.body} className={cn(BODY_TEXT, topic.status === "hidden" && "mt-2")} />}
      </div>

      <ContentActions
        className="mt-4"
        reactions={topic.reactions}
        signedIn={signedIn}
        onToggle={toggle(`topic:${topic.id}`)}
        onDelete={topic.can_delete ? () => setConfirm({ kind: "topic", replyCount: topic.reply_count }) : undefined}
        onReport={topic.can_report ? () => setReporting({ target: `topic:${topic.id}`, what: "主題" }) : undefined}
        what="主題"
      />

      <Section title="回覆" titleId="topic-replies" aside={topic.reply_count > 0 ? <span className="num">{topic.reply_count} 則</span> : undefined} className="mt-10" bodyClassName="pt-0">
        {replies.isError ? (
          <ErrorState flush error={replies.error} onRetry={() => void replies.refetch()} />
        ) : !replies.data ? (
          <SkeletonLines rows={4} className="pt-4" />
        ) : items.length === 0 ? (
          <EmptyState flush title="還沒有回覆" />
        ) : (
          <ol aria-label="回覆">
            {items.map((r) => (
              <li key={r.id} className="border-b border-rule py-3.5">
                <div className="flex flex-wrap items-center gap-x-2 text-sm text-ink-2">
                  <Byline author={r.author} at={r.created_at} group={!isPublic} />
                </div>
                <div className="mt-1">
                  {r.status === "hidden" && <p className="text-md text-ink-2">{r.body === null ? HIDDEN_NOTE : HIDDEN_NOTE_WITH_BODY}</p>}
                  {r.body !== null && <PlainText text={r.body} className={BODY_TEXT} />}
                </div>
                <ContentActions
                  className="mt-1"
                  reactions={r.reactions}
                  signedIn={signedIn}
                  onToggle={toggle(`reply:${r.id}`)}
                  onDelete={r.can_delete ? () => setConfirm({ kind: "reply", reply: r }) : undefined}
                  onReport={r.can_report ? () => setReporting({ target: `reply:${r.id}`, what: "回覆" }) : undefined}
                  what={`${authorName(r.author)}的回覆`}
                />
              </li>
            ))}
          </ol>
        )}
        {replies.hasNextPage && (
          <Button variant="outline" className="mt-4" disabled={replies.isFetchingNextPage} onClick={() => void replies.fetchNextPage()}>
            {replies.isFetchingNextPage ? "載入中…" : "看更多回覆"}
          </Button>
        )}
      </Section>

      <ReplyComposer topic={topic} onPosted={() => void loadToEnd()} className="mt-6" />
      {isPublic && <Disclaimer className="mt-8" />}

      {confirm && (
        <AlertDialog open onOpenChange={(o) => !o && setConfirm(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{confirm.kind === "topic" ? "刪除這個主題？" : "刪除這則回覆？"}</AlertDialogTitle>
              <AlertDialogDescription>
                {confirm.kind === "topic"
                  ? confirm.replyCount > 0
                    ? `主題和底下的 ${confirm.replyCount} 則回覆會一起刪除，不能復原。`
                    : "刪除後不能復原。"
                  : "刪除後不能復原。"}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                disabled={deleteTopic.isPending || deleteReply.isPending}
                onClick={() => {
                  if (confirm.kind === "topic") {
                    deleteTopic.mutate(topic.id, {
                      onSuccess: () => {
                        toast.success("已刪除主題")
                        void navigate({ to: "/discussions", replace: true })
                      },
                      onError: () => {
                        toast.error("主題沒有刪除，請再試一次")
                        setConfirm(null)
                      },
                    })
                  } else {
                    deleteReply.mutate(confirm.reply.id, {
                      onSuccess: () => {
                        toast.success("已刪除回覆")
                        setConfirm(null)
                      },
                      onError: () => {
                        toast.error("回覆沒有刪除，請再試一次")
                        setConfirm(null)
                      },
                    })
                  }
                }}
              >
                刪除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
      {reporting && <ReportDialog target={reporting.target} what={reporting.what} onClose={() => setReporting(null)} />}
    </article>
  )
}

/**
 * 作者＋時間。公開範圍只有公開暱稱（沒有頭像）；群組範圍和群組動態一樣有頭像與顯示名稱。
 * 自己的內容用字標示「（你）」；帳號已刪除、已離開群組的作者是淡墨。
 * `where`（主題的那一行）：時間後面接「・公開」或「・群組名稱」，和時間是同一段字。
 */
function Byline({ author, at, group, where }: { author: DiscussionAuthor; at: string; group: boolean; where?: string }) {
  const name = authorName(author)
  const known = author.name !== null && !(group && author.user_id === null)
  return (
    <>
      {group && <UserAvatar name={name} url={author.avatar_url} size="sm" />}
      <span>
        <span className={cn("text-md", known ? "font-medium text-ink" : "text-ink-2")}>{name}</span>
        {author.is_you && <span className="text-md text-ink">（你）</span>}
      </span>
      <span>
        <PostedTime iso={at} />
        {where && `・${where}`}
      </span>
    </>
  )
}

/**
 * 一則內容（主題或回覆）底下的那一列：表情（方肩的小格＋「加表情」；沒登入只顯示計數）在左，
 * 「刪除」「檢舉」在右——文字動作的安靜版，一直看得到（不是滑過才出現），沒有權限的就不出現。
 */
function ContentActions({
  reactions,
  signedIn,
  onToggle,
  onDelete,
  onReport,
  what,
  className,
}: {
  reactions: Reaction[]
  signedIn: boolean
  onToggle: (emoji: ReactionEmoji, on: boolean) => void
  onDelete?: () => void
  onReport?: () => void
  /** 這一則的稱呼（按鈕的無障礙名稱：「刪除主題」「檢舉阿土伯的回覆」） */
  what: string
  className?: string
}) {
  if (!signedIn && reactions.length === 0) return null
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-1", className)}>
      <ReactionChips reactions={reactions} onToggle={onToggle} readOnly={!signedIn} />
      {(onDelete || onReport) && (
        <div className="ml-auto flex items-center gap-x-5">
          {onDelete && (
            <button type="button" aria-label={`刪除${what}`} onClick={onDelete} className={cn(textAction, QUIET_ACTION)}>
              刪除
            </button>
          )}
          {onReport && (
            <button type="button" aria-label={`檢舉${what}`} onClick={onReport} className={cn(textAction, QUIET_ACTION)}>
              檢舉
            </button>
          )}
        </div>
      )}
    </div>
  )
}
