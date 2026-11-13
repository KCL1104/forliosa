import { Trash2Icon } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import { useComments, useCreateComment, useDeleteComment, useToggleReaction } from "@/api/sharing-queries"
import { ApiError, REACTION_EMOJIS, type CommentTarget, type Reaction, type ReactionEmoji } from "@/api/types"
import { SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Textarea } from "@/components/ui/textarea"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { EMOJI_LABEL } from "./labels"

/** 每一則動態都會重複的動作（加表情、留言）：文字動作的安靜版——淡墨字＋常駐底線，滑過或展開時變墨色 */
const QUIET_ACTION = "text-sm text-ink-2 hover:text-ink aria-expanded:text-ink aria-expanded:decoration-ink"

/**
 * 表情：已經有人按的表情（數字；自己按過的用選取語法 (b)），旁邊的「加表情」打開六個固定的表情。
 * 按下立即反映，伺服器回來後以伺服器的計數為準。
 */
export function Reactions({ groupId, target, reactions, className }: { groupId: string; target: CommentTarget; reactions: Reaction[]; className?: string }) {
  const toggle = useToggleReaction(groupId)
  // 樂觀更新：只在伺服器資料還是同一份時套用
  const [local, setLocal] = useState<{ base: Reaction[]; next: Reaction[] } | null>(null)
  const [open, setOpen] = useState(false)
  const shown = local && local.base === reactions ? local.next : reactions
  const press = (emoji: ReactionEmoji) => {
    const cur = shown.find((r) => r.emoji === emoji)
    const on = !cur?.mine
    const next = REACTION_EMOJIS.map((e) => {
      const r = shown.find((x) => x.emoji === e)
      if (e !== emoji) return r
      const count = (r?.count ?? 0) + (on ? 1 : -1)
      return count > 0 ? { emoji: e, count, mine: on } : undefined
    }).filter((x): x is Reaction => !!x)
    setLocal({ base: reactions, next })
    toggle.mutate(
      { target, emoji, on },
      {
        onError: (err) => {
          setLocal(null)
          toast.error(err instanceof ApiError && err.status === 404 ? "這則內容已經看不到了" : "表情沒有送出，請再試一次")
        },
      },
    )
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-x-1.5", className)}>
      {shown.map((r) => (
        // 觸控時按鈕本身 44px 高，看得到的小框在裡面（選取語法 (b) 跟著 data-pressed）
        <button
          key={r.emoji}
          type="button"
          aria-pressed={r.mine}
          aria-label={`${EMOJI_LABEL[r.emoji]} ${r.count}${r.mine ? "，你按過" : ""}`}
          onClick={() => press(r.emoji)}
          className="press inline-flex items-center rounded-full pointer-coarse:min-h-11"
        >
          <span
            data-pressed={r.mine ? "" : undefined}
            className="sel-chip inline-flex h-7 items-center gap-1 rounded-full border border-rule px-2 text-sm text-ink-2 data-pressed:border-transparent pointer-coarse:h-8 pointer-coarse:px-2.5"
          >
            <span aria-hidden>{r.emoji}</span>
            <span className="num">{r.count}</span>
          </span>
        </button>
      ))}
      <Popover open={open} onOpenChange={setOpen}>
        {/* 和「留言」一樣是有字的文字動作（常駐底線），不放圖示 */}
        <PopoverTrigger render={<button type="button" className={cn(textAction, QUIET_ACTION, "ml-1.5 first:ml-0")} />}>加表情</PopoverTrigger>
        <PopoverContent className="w-auto flex-row gap-1 p-1.5" side="top" align="start">
          {REACTION_EMOJIS.map((e) => {
            const mine = shown.find((r) => r.emoji === e)?.mine ?? false
            return (
              <button
                key={e}
                type="button"
                aria-pressed={mine}
                aria-label={EMOJI_LABEL[e]}
                title={EMOJI_LABEL[e]}
                onClick={() => {
                  press(e)
                  setOpen(false)
                }}
                className="press sel-chip grid size-9 place-items-center rounded-sm text-lg pointer-coarse:size-11"
              >
                {e}
              </button>
            )
          })}
        </PopoverContent>
      </Popover>
    </div>
  )
}

/** 「留言 N」：按下展開留言串 */
export function CommentsToggle({ count, open, onToggle, controls }: { count: number; open: boolean; onToggle: () => void; controls: string }) {
  return (
    <button type="button" aria-expanded={open} aria-controls={controls} onClick={onToggle} className={cn(textAction, QUIET_ACTION)}>
      {/* 一段文字（不是 flex 的兩個子元素），底線才連成一條 */}
      <span>{count > 0 ? <>留言 <span className="num">{count}</span></> : "留言"}</span>
    </button>
  )
}

/** 一個對象的留言串（舊到新）＋留言框；對象看不到時（404）安靜說明 */
export function CommentThread({ groupId, target, id, className }: { groupId: string; target: CommentTarget; id?: string; className?: string }) {
  const comments = useComments(groupId, target)
  const remove = useDeleteComment(groupId)
  const gone = comments.error instanceof ApiError && comments.error.status === 404
  return (
    <div id={id} className={cn("flex flex-col gap-2", className)}>
      {comments.isLoading ? (
        <SkeletonLines rows={2} />
      ) : gone ? (
        <p className="text-md text-ink-2">這則內容已經看不到了。</p>
      ) : comments.isError ? (
        <p className="text-md text-ink-2">留言沒有載入，請稍後再試。</p>
      ) : (
        <>
          {(comments.data?.items ?? []).length > 0 && (
            <ul className="flex flex-col">
              {comments.data!.items.map((c) => (
                <li key={c.id} className="group flex items-start gap-2 py-1.5">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink-2">
                      <span className={cn("font-medium", c.user_id ? "text-ink" : "text-ink-2")}>{c.display_name}</span>
                      <time dateTime={c.created_at} className="num ml-2">
                        {formatDateTime(c.created_at)}
                      </time>
                    </p>
                    <p className="text-base break-words whitespace-pre-wrap">{c.body}</p>
                  </div>
                  {c.can_delete && (
                    <DeleteComment
                      pending={remove.isPending}
                      onConfirm={() =>
                        remove.mutate(
                          { commentId: c.id, target },
                          { onSuccess: () => toast.success("已刪除留言"), onError: () => toast.error("留言沒有刪除，請再試一次") },
                        )
                      }
                    />
                  )}
                </li>
              ))}
            </ul>
          )}
          <CommentComposer groupId={groupId} target={target} />
        </>
      )}
    </div>
  )
}

/** 刪除留言的確認鈕：桌面是小按鈕，觸控時 44px 高 */
const CONFIRM_TOUCH = "pointer-coarse:h-11 pointer-coarse:px-3 pointer-coarse:text-sm"

function DeleteComment({ onConfirm, pending }: { onConfirm: () => void; pending: boolean }) {
  const [confirming, setConfirming] = useState(false)
  if (confirming) {
    return (
      <span className="flex shrink-0 items-center gap-1">
        <Button size="xs" variant="outline" className={CONFIRM_TOUCH} disabled={pending} onClick={onConfirm}>
          刪除
        </Button>
        <Button size="xs" variant="ghost" className={CONFIRM_TOUCH} onClick={() => setConfirming(false)}>
          取消
        </Button>
      </span>
    )
  }
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label="刪除這則留言"
            onClick={() => setConfirming(true)}
            className="grid size-7 shrink-0 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink pointer-coarse:size-11"
          />
        }
      >
        <Trash2Icon aria-hidden className="size-4" />
      </TooltipTrigger>
      <TooltipContent>刪除這則留言</TooltipContent>
    </Tooltip>
  )
}

const MAX = 500

function CommentComposer({ groupId, target }: { groupId: string; target: CommentTarget }) {
  const create = useCreateComment(groupId)
  const [body, setBody] = useState("")
  const inputId = useId()
  const text = body.trim()
  const submit = () => {
    if (!text || text.length > MAX || create.isPending) return
    create.mutate(
      { target, body: text },
      {
        onSuccess: () => setBody(""),
        onError: (err) => toast.error(err instanceof ApiError && err.status === 404 ? "這則內容已經看不到了" : "留言沒有送出，內容還在", { description: err instanceof ApiError ? err.message : undefined }),
      },
    )
  }
  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <label htmlFor={inputId} className="sr-only">
        留言
      </label>
      <Textarea
        id={inputId}
        value={body}
        maxLength={MAX}
        rows={1}
        placeholder="留言…"
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            submit()
          }
        }}
        className="min-h-10 rounded-sm border-ctl bg-raised py-2 text-base md:text-base pointer-coarse:min-h-11 pointer-coarse:py-2.5"
      />
      <Button type="submit" variant="outline" disabled={!text || create.isPending}>
        送出
      </Button>
      {body.length > MAX - 50 && <span className="num shrink-0 self-center text-xs text-ink-2">{`${body.length}/${MAX}`}</span>}
    </form>
  )
}
