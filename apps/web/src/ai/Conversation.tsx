import { Link } from "@tanstack/react-router"
import { ArrowUpRightIcon, CornerDownRightIcon } from "lucide-react"
import { useEffect, useRef } from "react"
import { useUi } from "@/app/ui-store"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { DraftCard } from "./DraftCard"
import type { useAiRunner } from "./runner"
import { useAi } from "./store"
import type { Answer, AnswerLink, Thread } from "./types"

type Runner = ReturnType<typeof useAiRunner>

/** 對話：使用者的話靠右（格線小框），AI 的話是紫色文楷；草稿卡跟在 AI 的話後面 */
export function Conversation({ thread, runner, size = "panel", onNavigate }: { thread: Thread; runner: Runner; size?: "panel" | "screen"; onNavigate?: () => void }) {
  const drafts = useAi((s) => s.drafts)
  const focusDraftId = useAi((s) => s.focusDraftId)
  const endRef = useRef<HTMLDivElement>(null)
  const count = thread.messages.length

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" })
  }, [count])

  return (
    <div className="flex flex-col" aria-live="polite" aria-relevant="additions">
      {thread.messages.map((m) =>
        m.role === "user" ? (
          <p key={m.id} className="note-in mt-6 max-w-[85%] self-end rounded-sm border border-rule bg-raised px-3.5 py-1.5 text-base text-ink first:mt-2">
            <span className="sr-only">你說：</span>
            {m.text}
          </p>
        ) : (
          <div key={m.id} className="note-in mt-4 flex flex-col">
            <span className="sr-only">AI：</span>
            {m.text && <p className={cn("ai-voice whitespace-pre-line", size === "screen" ? "text-[1.375rem] leading-normal" : "text-xl leading-normal")}>{m.text}</p>}
            {m.answer && <AnswerView answer={m.answer} runner={runner} size={size} onNavigate={onNavigate} />}
            {m.draftId && drafts[m.draftId] && (
              <DraftCard
                draft={drafts[m.draftId]!}
                focused={focusDraftId === m.draftId}
                onSign={() => void runner.sign(m.draftId!)}
                onUndo={() => void runner.undo(m.draftId!)}
                onRevise={(p) => void runner.revise(m.draftId!, p)}
                onDiscard={() => runner.discard(m.draftId!)}
              />
            )}
          </div>
        ),
      )}
      <div ref={endRef} />
    </div>
  )
}

function AnswerView({ answer, runner, size, onNavigate }: { answer: Answer; runner: Runner; size: "panel" | "screen"; onNavigate?: () => void }) {
  return (
    <div className="flex flex-col">
      <p className={cn("ai-voice", size === "screen" ? "text-[1.375rem] leading-normal" : "text-xl leading-normal")}>{answer.text}</p>
      {answer.rows && answer.rows.length > 0 && (
        <dl className="mt-3 border-t border-rule">
          {answer.rows.map((r) => (
            <div key={r.label} className="flex items-baseline justify-between gap-3 border-b border-rule py-2">
              <dt className="min-w-0 text-md text-ink">{r.label}</dt>
              {(r.value || r.hint) && (
                <dd className={cn("num shrink-0 text-md", r.tone === "up" ? "text-rise" : r.tone === "down" ? "text-fall" : "text-ink")}>
                  {r.value}
                  {r.hint && <span className="ml-2 text-sm text-ink-2">{r.hint}</span>}
                </dd>
              )}
            </div>
          ))}
        </dl>
      )}
      {answer.links && answer.links.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {answer.links.map((l) => (
            <AnswerLinkButton key={l.label} link={l} onNavigate={onNavigate} />
          ))}
        </div>
      )}
      {answer.followUps && answer.followUps.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5">
          {answer.followUps.map((f) => (
            <li key={f}>
              <button type="button" onClick={() => void runner.submit(f)} className="press inline-flex min-h-9 items-center gap-1.5 text-left text-md text-ai hover:underline pointer-coarse:min-h-11">
                <CornerDownRightIcon aria-hidden className="size-4 shrink-0" />
                {f}
              </button>
            </li>
          ))}
        </ul>
      )}
      {answer.asOf && <p className="mt-2 text-xs text-ink-2">資料至 {formatDateTime(answer.asOf)}</p>}
    </div>
  )
}

const linkClass = "press inline-flex h-9 items-center gap-1 rounded-sm border border-ctl px-3 text-sm text-ink hover:bg-hov pointer-coarse:h-11"

function AnswerLinkButton({ link, onNavigate }: { link: AnswerLink; onNavigate?: () => void }) {
  const openTradeForm = useUi((s) => s.openTradeForm)
  if (link.to === "#trade-form") {
    return (
      <button type="button" className={linkClass} onClick={() => openTradeForm()}>
        {link.label}
      </button>
    )
  }
  return (
    <Link
      to={link.to as "/"}
      params={link.params as never}
      search={link.search as never}
      className={linkClass}
      onClick={onNavigate}
    >
      {link.label}
      <ArrowUpRightIcon aria-hidden className="size-3.5 text-ink-2" />
    </Link>
  )
}
