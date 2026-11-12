import { Link } from "@tanstack/react-router"
import { ArrowUpRightIcon, CircleAlertIcon, CornerDownRightIcon } from "lucide-react"
import { useEffect, useRef } from "react"
import { useUi } from "@/app/ui-store"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { DraftCard } from "./DraftCard"
import type { Citation } from "./remote"
import type { useAiRunner } from "./runner"
import { useAi } from "./store"
import type { Answer, AnswerLink, Message, Thread } from "./types"

type Runner = ReturnType<typeof useAiRunner>

/** 對話：使用者的話靠右（格線小框），AI 的話是紫色文楷；草稿卡跟在 AI 的話後面 */
export function Conversation({ thread, runner, size = "panel", onNavigate }: { thread: Thread; runner: Runner; size?: "panel" | "screen"; onNavigate?: () => void }) {
  const drafts = useAi((s) => s.drafts)
  const focusDraftId = useAi((s) => s.focusDraftId)
  const endRef = useRef<HTMLDivElement>(null)
  const count = thread.messages.length
  const last = thread.messages[count - 1]
  // 串流時跟著新的字往下捲（每多約一行才捲一次）
  const growth = last?.streaming ? Math.floor((last.text?.length ?? 0) / 40) + (last.tools?.length ?? 0) : 0

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" })
  }, [count, growth])

  return (
    <div className="flex flex-col" aria-live="polite" aria-relevant="additions">
      {thread.messages.map((m) =>
        m.role === "user" ? (
          <p key={m.id} className="note-in mt-6 max-w-[85%] self-end rounded-sm border border-rule bg-raised px-3.5 py-1.5 text-base text-ink first:mt-2">
            <span className="sr-only">你說：</span>
            {m.text}
          </p>
        ) : (
          <div key={m.id} className="note-in mt-4 flex flex-col" aria-busy={m.streaming || undefined}>
            <span className="sr-only">AI：</span>
            {m.text && <p className={cn("ai-voice whitespace-pre-line", size === "screen" ? "text-[1.375rem] leading-normal" : "text-xl leading-normal")}>{m.text}</p>}
            {m.streaming && <StreamingLine message={m} />}
            {m.answer && <AnswerView answer={m.answer} runner={runner} size={size} onNavigate={onNavigate} />}
            {m.error && <ErrorNote code={m.error.code} message={m.error.message} size={size} />}
            {[m.draftId, ...(m.draftIds ?? [])].map((id) =>
              id && drafts[id] ? (
                <DraftCard
                  key={id}
                  draft={drafts[id]!}
                  focused={focusDraftId === id}
                  onSign={() => void runner.sign(id)}
                  onUndo={() => void runner.undo(id)}
                  onRevise={(p) => void runner.revise(id, p)}
                  onDiscard={() => runner.discard(id)}
                />
              ) : null,
            )}
            {!m.streaming && m.citations && m.citations.length > 0 && <Citations items={m.citations} />}
          </div>
        ),
      )}
      <div ref={endRef} />
    </div>
  )
}

/** 串流中：還沒有字時一個安靜的紫點；查資料時一行灰字（只在串流時出現） */
function StreamingLine({ message }: { message: Message }) {
  const running = [...(message.tools ?? [])].reverse().find((t) => t.status === "running")
  if (!running && message.text) return null
  return (
    <p className="mt-2 flex min-h-6 items-center gap-2 text-sm text-ink-2" role="status">
      <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-ai motion-safe:animate-pulse" />
      {running ? <span className="min-w-0 truncate">{running.label}…</span> : <span className="sr-only">回答中</span>}
    </p>
  )
}

/** 拒答是 AI 自己說的話（文楷）；額度、連線等狀況是一行說明 */
function ErrorNote({ code, message, size }: { code: string; message: string; size: "panel" | "screen" }) {
  if (code === "refusal") {
    return <p className={cn("ai-voice", size === "screen" ? "text-[1.375rem] leading-normal" : "text-xl leading-normal")}>{message}</p>
  }
  return (
    <p className="mt-2 flex items-start gap-2 text-md text-ink-2" role="status">
      <CircleAlertIcon aria-hidden className="mt-1 size-4 shrink-0" />
      <span>{message}</span>
    </p>
  )
}

function hostOf(url: string | null): string {
  if (!url) return ""
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return ""
  }
}

/** 引用的網路來源：回答下方一排小連結（標題＋網域；滑過看引用的原文） */
function Citations({ items }: { items: Citation[] }) {
  const seen = new Set<string>()
  const unique = items.filter((c) => {
    const key = c.url ?? c.title ?? c.cited_text
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  return (
    <div className="mt-3">
      <p className="text-xs text-ink-2">來源</p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {unique.slice(0, 8).map((c) => {
          const host = hostOf(c.url)
          const label = c.title || host || "來源"
          const body = (
            <>
              <span className="min-w-0 truncate">{label}</span>
              {host && host !== label && <span className="num shrink-0 text-xs text-ink-2">{host}</span>}
              {c.url && <ArrowUpRightIcon aria-hidden className="size-3.5 shrink-0 text-ink-2" />}
            </>
          )
          const cls = "inline-flex h-8 max-w-[16rem] items-center gap-1.5 rounded-sm border border-rule px-2.5 text-sm text-ink pointer-coarse:h-10"
          return (
            <li key={c.url ?? label} className="min-w-0">
              {c.url ? (
                <a href={c.url} target="_blank" rel="noopener noreferrer" title={c.cited_text || undefined} className={cn(cls, "press hover:border-ctl hover:bg-hov")}>
                  {body}
                </a>
              ) : (
                <span title={c.cited_text || undefined} className={cls}>
                  {body}
                </span>
              )}
            </li>
          )
        })}
      </ul>
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
