import {
  ArrowUpRightIcon,
  EllipsisIcon,
  HistoryIcon,
  MessageCircleQuestionIcon,
  PanelRightCloseIcon,
  PanelRightOpenIcon,
  PenLineIcon,
  SquarePenIcon,
  StarIcon,
  XIcon,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useToggleWatch, useUpcoming, useWatchlist } from "@/api/queries"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Composer, type ComposerHandle } from "./Composer"
import { DISCLAIMER, useActions, useGreeting } from "./panel-helpers"
import { useAiContext, useRouteKind } from "./context"
import { Conversation } from "./Conversation"
import { HistoryList } from "./HistoryList"
import { useAiRunner } from "./runner"
import { useAi, useCurrentThread, usePendingCount } from "./store"
import { useAiSuggestions, useAiUsage, usageNote } from "./remote-hooks"
import type { AiContext } from "./suggestions"
import type { Suggestion } from "./types"

/** 桌面右側 AI 面板（約 400px，可收合，記得開合狀態） */
export function AiPanel() {
  const open = useAi((s) => s.panelOpen)
  const setOpen = useAi((s) => s.setPanelOpen)
  const pending = usePendingCount()
  const composer = useRef<ComposerHandle>(null)

  // ⌘J：打開面板並聚焦輸入框
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "j" || e.key === "J") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        useAi.getState().setPanelOpen(true)
        requestAnimationFrame(() => composer.current?.focus())
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  if (!open) {
    return (
      <aside aria-label="問 AI（已收合）" className="sticky top-16 flex h-[calc(100dvh-4rem)] w-14 flex-col items-center gap-2 border-l border-rule pt-4">
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                onClick={() => setOpen(true)}
                aria-label={pending > 0 ? `展開 AI 面板（待簽名 ${pending} 筆）` : "展開 AI 面板"}
                className="press relative grid size-10 place-items-center rounded-sm text-ai hover:bg-ai-wash"
              />
            }
          >
            <PanelRightOpenIcon aria-hidden className="size-5" />
            {pending > 0 && <span className="num absolute -top-1 -right-1 grid h-5 min-w-5 place-items-center rounded-full border border-dashed border-ai-rule bg-ai-wash px-1 text-xs text-ai">{pending}</span>}
          </TooltipTrigger>
          <TooltipContent side="left">展開問 AI（⌘J）</TooltipContent>
        </Tooltip>
      </aside>
    )
  }
  return <PanelBody composerRef={composer} onCollapse={() => setOpen(false)} />
}

function PanelBody({ composerRef, onCollapse }: { composerRef: React.RefObject<ComposerHandle | null>; onCollapse: () => void }) {
  const ctx = useAiContext()
  const runner = useAiRunner(ctx)
  const thread = useCurrentThread()
  const newThread = useAi((s) => s.newThread)
  const [view, setView] = useState<"chat" | "history">("chat")
  const route = useRouteKind()
  useUpcoming(7)

  return (
    <aside
      aria-label="問 AI"
      className="sticky top-16 flex h-[calc(100dvh-4rem)] w-[340px] shrink-0 flex-col xl:w-[400px] before:pointer-events-none before:absolute before:inset-y-0 before:left-0 before:w-1 before:border-x before:border-rule"
    >
      <header className="flex h-14 shrink-0 items-center gap-0.5 border-b border-rule pr-4 pl-7">
        <h2 className="mr-auto flex items-center gap-2 text-base font-bold">
          <PenLineIcon aria-hidden className="size-[18px] text-ai" />
          {view === "history" ? "紀錄" : "問 AI"}
        </h2>
        <IconButton label="新對話" onClick={() => { newThread(); setView("chat") }}>
          <SquarePenIcon aria-hidden className="size-[18px]" />
        </IconButton>
        <IconButton label={view === "history" ? "回到對話" : "紀錄與 AI 任務"} pressed={view === "history"} onClick={() => setView(view === "history" ? "chat" : "history")}>
          {view === "history" ? <XIcon aria-hidden className="size-[18px]" /> : <HistoryIcon aria-hidden className="size-[18px]" />}
        </IconButton>
        <IconButton label="收合 AI 面板" onClick={onCollapse}>
          <PanelRightCloseIcon aria-hidden className="size-[18px]" />
        </IconButton>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-7 pb-4 xl:pr-7 xl:pl-8">
        {view === "history" ? (
          <HistoryList compact onOpen={() => setView("chat")} onReplay={(t) => void runner.submit(t)} />
        ) : thread ? (
          <Conversation key={thread.id} thread={thread} runner={runner} />
        ) : (
          <PanelHome ctx={ctx} runner={runner} routeKind={route.kind} />
        )}
      </div>

      <div className="shrink-0 px-7 pb-5 xl:pr-7 xl:pl-8">
        <Composer
          ref={composerRef}
          variant="panel"
          placeholder={ctx.route === "stock" ? `問${ctx.stock.name}的事，或說：買 ${ctx.stock.code} 1 張` : "提出問題，或直接說：買 0050 2 張 52.4"}
          onSubmit={(t) => {
            setView("chat")
            void runner.submit(t)
          }}
          onAttach={(k) => runner.action(k)}
        />
        <FooterNote />
      </div>
    </aside>
  )
}

/**
 * 輸入框下方一行：還沒有對話時是免責聲明（對話中每則回答下方已經固定顯示）；提問額度快用完時多一句。
 */
export function FooterNote({ className }: { className?: string }) {
  const note = usageNote(useAiUsage().data)
  const inThread = !!useCurrentThread()
  if (inThread && !note) return null
  return (
    <p className={cn("mt-2.5 text-xs text-ink-2", className)}>
      {!inThread && DISCLAIMER}
      {note && <span className={cn("text-ink", !inThread && "ml-1")}>{note}</span>}
    </p>
  )
}

function IconButton({ label, onClick, children, pressed }: { label: string; onClick: () => void; children: React.ReactNode; pressed?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={label}
            aria-pressed={pressed}
            onClick={onClick}
            className="press grid size-9 place-items-center rounded-sm border border-transparent text-ink-2 hover:border-rule hover:text-ink aria-pressed:border-rule aria-pressed:text-ink"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function PanelHome({ ctx, runner, routeKind }: { ctx: AiContext; runner: ReturnType<typeof useAiRunner>; routeKind: string }) {
  const { hello, line } = useGreeting(ctx)
  const suggestions = useAiSuggestions(ctx)
  const actions = useActions(ctx)
  return (
    <div className="flex flex-col">
      <p className="ai-voice mt-9 text-2xl leading-snug">
        {hello}
        {line}
      </p>
      {suggestions.length > 0 && (
        <ul className="mt-6 grid gap-2.5">
          {suggestions.map((s) => (
            <li key={`${s.kind}-${s.recurring?.planId ?? ""}`}>
              <SuggestionButton s={s} onAsk={() => runner.ask(s)} />
            </li>
          ))}
        </ul>
      )}
      <div role="group" aria-label="常用動作" className="mt-8 grid grid-cols-2 gap-2">
        {actions.map((a) => (
          <button key={a.key} type="button" onClick={() => runner.action(a.run, { code: a.code })} className="press ctl inline-flex h-10 items-center gap-2 px-3 text-md whitespace-nowrap">
            <a.icon aria-hidden className="size-4 text-ink-2" />
            {a.label}
          </button>
        ))}
        {routeKind === "stock" && ctx.route === "stock" && !ctx.stock.position && <WatchAction symbol={ctx.stock.symbol} />}
        <MoreActions runner={runner} code={ctx.route === "stock" ? ctx.stock.code : undefined} />
      </div>
    </div>
  )
}

export function SuggestionButton({ s, onAsk }: { s: Suggestion; onAsk: () => void }) {
  return (
    <button
      type="button"
      onClick={onAsk}
      className="press flex h-[52px] w-full items-center justify-between gap-3 rounded-md border border-rule bg-raised pr-3.5 pl-4 text-left text-base text-ink hover:border-ctl"
    >
      <span className="min-w-0 truncate">{s.text}</span>
      <MessageCircleQuestionIcon aria-hidden className="size-[18px] shrink-0 text-ai" />
    </button>
  )
}

function WatchAction({ symbol }: { symbol: string }) {
  const list = useWatchlist()
  const toggle = useToggleWatch()
  const on = (list.data ?? []).some((w) => w.symbol === symbol)
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={toggle.isPending}
      onClick={() => toggle.mutate({ symbol, on: !on })}
      className="press ctl inline-flex h-10 items-center gap-2 px-3 text-md whitespace-nowrap"
    >
      <StarIcon aria-hidden className={cn("size-4", on ? "fill-ink text-ink" : "text-ink-2")} />
      {on ? "觀察中" : "加入觀察"}
    </button>
  )
}

export function MoreActions({ runner, code, className }: { runner: ReturnType<typeof useAiRunner>; code?: string; className?: string }) {
  const togglePrivacy = usePrefs((s) => s.togglePrivacy)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<button type="button" className={cn("press ctl inline-flex h-10 items-center gap-2 px-3 text-md whitespace-nowrap", className)} />}
      >
        <EllipsisIcon aria-hidden className="size-4 text-ink-2" />
        更多
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem onClick={() => runner.action("form", { code })}>
          改用表單記一筆
          <ArrowUpRightIcon aria-hidden className="ml-auto size-3.5 text-ink-2" />
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => runner.action("alert")}>設定到價提醒</DropdownMenuItem>
        <DropdownMenuItem onClick={() => runner.action("checkup")}>排定持倉健檢</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={togglePrivacy}>切換隱私模式</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
