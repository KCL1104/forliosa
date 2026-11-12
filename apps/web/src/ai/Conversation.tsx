import { Link } from "@tanstack/react-router"
import { ArrowUpRightIcon, CircleAlertIcon } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useUi } from "@/app/ui-store"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { DISCLAIMER, groundingReason, splitUngrounded, stripDisclaimer, type UngroundedPassage } from "./answer-text"
import { useAiUsage } from "./remote-hooks"
import { DraftCard } from "./DraftCard"
import { textLink } from "./Home"
import type { Citation } from "./remote"
import type { useAiRunner } from "./runner"
import { useAi } from "./store"
import type { Answer, AnswerLink, Message, Thread } from "./types"

type Runner = ReturnType<typeof useAiRunner>

/**
 * 對話：使用者的話靠右（格線小框、墨色）；模型寫的話是紫色楷體，本機規則或範本寫的句子是墨色 Noto Sans；
 * 草稿卡跟在後面。
 */
export function Conversation({ thread, runner, size = "panel", onNavigate }: { thread: Thread; runner: Runner; size?: "panel" | "screen"; onNavigate?: () => void }) {
  const drafts = useAi((s) => s.drafts)
  const focusDraftId = useAi((s) => s.focusDraftId)
  // 免責聲明：這則回答的 done.disclaimer → /ai/usage 的 disclaimer → 常數
  const fallbackDisclaimer = useAiUsage().data?.disclaimer ?? DISCLAIMER
  const endRef = useRef<HTMLDivElement>(null)
  const count = thread.messages.length
  const last = thread.messages[count - 1]
  // 串流時跟著新的字往下捲（每多約一行才捲一次）；草稿卡與來源出現時也捲
  const growth = last?.streaming
    ? Math.floor((last.text?.length ?? 0) / 40) + (last.tools?.length ?? 0) * 100 + (last.draftIds?.length ?? 0) * 1000
    : -((last?.draftIds?.length ?? 0) + (last?.citations?.length ?? 0))

  useEffect(() => {
    // 只捲面板自己的捲動區：scrollIntoView 也會捲整頁（從個股頁的分頁按「問 AI」時，頁面會跳回頂端）
    const end = endRef.current
    const box = end?.closest<HTMLElement>(".overflow-y-auto")
    if (box) box.scrollTop = box.scrollHeight
    else end?.scrollIntoView({ block: "end" })
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
            {m.text &&
              ((m.model ?? !!thread.remoteId) ? (
                <AiText text={stripDisclaimer(m.text, m.disclaimer ?? fallbackDisclaimer)} ungrounded={m.ungrounded} size={size} />
              ) : (
                <RuleText text={m.text} size={size} />
              ))}
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
            {/* 免責只跟著回答（模型的回答、規則版回答）；草稿前的說明是照使用者的指令算的稅費，不是建議，不加 */}
            {!m.streaming && !m.error && (m.answer || (m.text && m.model !== false)) && (
              <p className="mt-2.5 text-xs text-ink-2">{m.disclaimer ?? fallbackDisclaimer}</p>
            )}
          </div>
        ),
      )}
      <div ref={endRef} />
    </div>
  )
}

/** 模型寫的字：楷體約 17px（手機 18px）、行高 1.8，長回答在 400px 的面板裡也讀得下去 */
const modelSize = { panel: "text-lg leading-[1.8]", screen: "text-[1.125rem] leading-[1.8]" } as const
/** 規則或範本寫的句子：墨色 Noto Sans，和介面的內文同一級 */
const ruleSize = { panel: "text-base leading-relaxed", screen: "text-[1rem] leading-relaxed" } as const

/**
 * 模型寫的話（紫色楷體）。後端標出「像事實、但沒有附來源」的段落時，段落下方一條淡淡的點線，
 * 後面接一個安靜的「無來源」小標記（淡墨，不用紅色）；按下展開說明。
 */
export function AiText({ text, ungrounded, size }: { text: string; ungrounded?: UngroundedPassage[]; size: "panel" | "screen" }) {
  const segments = splitUngrounded(text, ungrounded)
  return (
    <p className={cn("ai-voice whitespace-pre-line", modelSize[size])}>
      {segments.map((seg, i) =>
        seg.ungrounded ? (
          <span key={i}>
            <span className="underline decoration-ctl decoration-dotted decoration-1 underline-offset-[5px]">{seg.text}</span>
            <UngroundedMark passage={seg.ungrounded} />
          </span>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </p>
  )
}

/** 本機規則或範本寫的句子（草稿的說明、規則版的回答）：不是模型寫的，墨色 Noto Sans、不用紫色 */
function RuleText({ text, size }: { text: string; size: "panel" | "screen" }) {
  return <p className={cn("whitespace-pre-line text-ink", ruleSize[size])}>{text}</p>
}

function UngroundedMark({ passage }: { passage: UngroundedPassage }) {
  const [open, setOpen] = useState(false)
  const note = "這段沒有附來源，請自行查證。"
  const reason = groundingReason(passage.reason)
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        title={reason ? `${note}${reason}` : note}
        onClick={() => setOpen(!open)}
        className="mx-1 inline-flex h-5 translate-y-[-0.15em] items-center rounded-xs border border-ctl px-1.5 align-middle font-sans text-xs leading-none text-ink-2 hover:text-ink pointer-coarse:h-6"
      >
        無來源
      </button>
      {open && (
        <span role="note" className="my-1 block font-sans text-sm leading-snug text-ink-2">
          {note}
          {reason && <span className="ml-1">{reason}</span>}
        </span>
      )}
    </>
  )
}

/** 串流中：一個安靜的紫點；查資料時旁邊一行灰字（回答寫完就消失） */
function StreamingLine({ message }: { message: Message }) {
  const running = [...(message.tools ?? [])].reverse().find((t) => t.status === "running")
  return (
    <p className="mt-2 flex min-h-6 items-center gap-2 text-sm text-ink-2" role="status">
      <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-ai motion-safe:animate-pulse" />
      {running ? <span className="min-w-0 truncate">{running.label}…</span> : <span className="sr-only">回答中</span>}
    </p>
  )
}

/** 拒答是模型自己說的話（楷體）；額度、連線等狀況是一行說明 */
function ErrorNote({ code, message, size }: { code: string; message: string; size: "panel" | "screen" }) {
  if (code === "refusal") {
    return <p className={cn("ai-voice", modelSize[size])}>{message}</p>
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
      <p className="text-sm text-ink-2">來源</p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {unique.slice(0, 8).map((c) => {
          const host = hostOf(c.url)
          const label = c.title || host || "來源"
          const body = (
            <>
              <span className="min-w-0 truncate">{label}</span>
              {host && host !== label && <span className="num shrink-0 text-ink-2">{host}</span>}
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
      <RuleText text={answer.text} size={size} />
      {answer.rows && answer.rows.length > 0 && (
        <dl className="mt-3 border-t border-rule">
          {answer.rows.map((r) => (
            <div key={r.label} className="flex items-baseline justify-between gap-3 border-b border-rule py-2">
              <dt className="min-w-0 text-md text-ink">{r.label}</dt>
              {(r.value || r.hint) && (
                <dd className={cn("num shrink-0 text-md", r.tone === "up" ? "text-rise" : r.tone === "down" ? "text-fall" : "text-ink")}>
                  {r.value}
                  {/* 漲跌的百分比（▲▼）跟著漲跌色；其他補充（每股配息）是淡墨 */}
                  {r.hint && <span className={cn("ml-2 text-sm", r.tone !== "up" && r.tone !== "down" && "text-ink-2")}>{r.hint}</span>}
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
        <ul aria-label="接著問" className="mt-2 flex flex-col text-md">
          {answer.followUps.map((f) => (
            <li key={f}>
              <button type="button" onClick={() => void runner.submit(f)} className={textLink}>
                {f}
              </button>
            </li>
          ))}
        </ul>
      )}
      {answer.asOf && <p className="mt-2 text-sm text-ink-2">資料至 {formatDateTime(answer.asOf)}</p>}
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
