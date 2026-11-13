import { useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useId, useState } from "react"
import { toast } from "sonner"
import { useCreateReply } from "@/api/discussion-queries"
import { qk, useViewer } from "@/api/queries"
import { ApiError, REPLY_BODY_MAX, type Topic, type User } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { bodyProblem, charCount } from "@/lib/discussion-text"
import { clearDraft, parseReplyDraft, readDraft, replyDraftKey, writeDraft } from "@/lib/drafts"
import { cn } from "@/lib/utils"
import { postErrorText, suspendedText, suspendedUntil } from "./labels"
import { PublicNamePrompt } from "./PublicNamePrompt"

/**
 * 「你用什麼名字發言」那一行：公開範圍是公開暱稱（旁邊「改」連到設定），群組範圍是顯示名稱＋群組名稱。
 * 發言前就看得到，不會發出去才發現用的是另一個名字。
 */
export function PostingAs({ user, scope, groupName, className }: { user: User; scope: "public" | "group"; groupName?: string; className?: string }) {
  return (
    <p className={cn("text-sm text-ink-2", className)}>
      {scope === "public" ? (
        <>
          以「<span className="text-ink">{user.public_name}</span>」公開發言
          <Link to="/settings" hash="profile" className={cn(textAction, "ml-2 text-sm pointer-coarse:before:-inset-x-4")}>
            改
          </Link>
        </>
      ) : (
        <>
          以「<span className="text-ink">{user.display_name}</span>」在「{groupName ?? "群組"}」發言
        </>
      )}
    </p>
  )
}

/**
 * 主題頁最下面的回覆區，依狀況只出現一種：
 * - 沒登入：「登入後發言」（登入後回到這個主題）
 * - 主題被站方隱藏：一行說明，不能回覆
 * - 公開主題、公開發言被暫停：一行說明到什麼時候
 * - 公開主題、還沒有公開暱稱：選暱稱的一欄表單（選好之後就是回覆框）
 * - 其他：回覆框（跟著內容長高、沒有拖曳把手）＋「以○○發言」＋簽名格語法的「回覆」
 * 送出失敗的原因就地寫在回覆框下面（頻率限制會說多久之後可以再送），內容留著。
 * 還沒送出的字邊打邊存（這個分頁、一個主題一份，`lib/drafts.ts`）：按了「改」去設定、按上一頁、重新整理再回來都還在；
 * 送出成功才清掉。回來時框裡是還原的草稿，旁邊有一個安靜的「清除草稿」。
 */
export function ReplyComposer({ topic, onPosted, className }: { topic: Topic; /** 回覆送出之後（主題頁用來把後面的回覆都讀進來） */ onPosted?: () => void; className?: string }) {
  const { user } = useViewer()
  if (!user) {
    return (
      <p className={className}>
        <Link to="/login" search={{ next: `/discussions/${topic.id}` }} className={textAction}>
          登入後發言
        </Link>
      </p>
    )
  }
  if (topic.status === "hidden" || !topic.can_reply) return <p className={cn("text-md text-ink-2", className)}>這個主題已被站方隱藏，不能再回覆。</p>
  if (topic.scope === "public") {
    const until = suspendedUntil(user)
    if (until) return <p className={cn("max-w-prose text-md text-ink", className)}>{suspendedText(until)}</p>
    if (!user.public_name) return <PublicNamePrompt className={className} />
  }
  // 一個主題（一個人）一個回覆框：從一個主題直接跳到另一個時整個重建，框裡的字與草稿不會串到別的主題
  return <ReplyForm key={`${user.id}:${topic.id}`} topic={topic} user={user} onPosted={onPosted} className={className} />
}

function ReplyForm({ topic, user, onPosted, className }: { topic: Topic; user: User; onPosted?: () => void; className?: string }) {
  const create = useCreateReply(topic.id)
  const qc = useQueryClient()
  const draftKey = replyDraftKey(user.id, topic.id)
  // 回到這個主題時，上次沒送出的字還在
  const [body, setBody] = useState(() => readDraft(draftKey, parseReplyDraft) ?? "")
  // 框裡的字是還原的草稿（不是這次打的）：顯示「清除草稿」，一開始打字就收起來
  const [restored, setRestored] = useState(() => body !== "")
  const [error, setError] = useState<string | null>(null)
  const id = useId()
  const count = charCount(body)
  useEffect(() => {
    writeDraft(draftKey, parseReplyDraft(body))
  }, [draftKey, body])
  const submit = () => {
    if (create.isPending) return
    const problem = bodyProblem(body, REPLY_BODY_MAX, "回覆")
    if (problem) return setError(problem)
    setError(null)
    create.mutate(body, {
      onSuccess: () => {
        setBody("")
        setRestored(false)
        clearDraft(draftKey)
        toast.success("已送出回覆")
        onPosted?.()
      },
      onError: (err) => {
        setError(postErrorText(err, "回覆"))
        // 伺服器說還沒有公開暱稱、或已被停權：重新讀個人資料，回覆區換成對應的狀態
        if (err instanceof ApiError && (err.code === "public_name_required" || err.code === "posting_suspended")) void qc.invalidateQueries({ queryKey: qk.me })
      },
    })
  }
  return (
    <form
      aria-label="回覆這個主題"
      className={cn("flex flex-col gap-2", className)}
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <label htmlFor={id} className="sr-only">
        回覆內容
      </label>
      <Textarea
        id={id}
        value={body}
        rows={3}
        placeholder="寫下你的回覆…"
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => {
          setBody(e.target.value)
          setRestored(false)
          if (error) setError(null)
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            submit()
          }
        }}
        // 跟著內容自己長高（field-sizing-content），不需要右下角的原生拖曳把手
        className="min-h-24 resize-none border-ctl bg-raised px-3 py-2.5 text-base leading-[1.7] md:text-base"
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <PostingAs user={user} scope={topic.scope} groupName={topic.group?.name} className="mr-auto" />
        {restored && (
          <button
            type="button"
            className={cn(textAction, "text-sm text-ink-2 hover:text-ink")}
            onClick={() => {
              setBody("")
              setRestored(false)
              setError(null)
            }}
          >
            清除草稿
          </button>
        )}
        {count > REPLY_BODY_MAX - 200 && <span className={cn("num text-sm", count > REPLY_BODY_MAX ? "font-medium text-ink" : "text-ink-2")}>{`${count}/${REPLY_BODY_MAX}`}</span>}
        {/* 放不下而換到下一行時也靠右（簽名格固定在右下角） */}
        <Button type="submit" variant="sign" disabled={create.isPending} className="ml-auto">
          {create.isPending ? "送出中…" : "回覆"}
        </Button>
      </div>
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </form>
  )
}
