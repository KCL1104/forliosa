import { HistoryIcon, PanelRightCloseIcon, SquarePenIcon } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useUpcoming } from "@/api/queries"
import { cn } from "@/lib/utils"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { AskAiIcon } from "./ask-icon"
import { Composer, type ComposerHandle } from "./Composer"
import { useAiContext, useRouteKind } from "./context"
import { Conversation } from "./Conversation"
import { HistoryList } from "./HistoryList"
import { PanelHome } from "./Home"
import { composerPlaceholder } from "./panel-helpers"
import { useAiRunner } from "./runner"
import { useAi, useCurrentThread, usePendingCount } from "./store"
import { useAiSuggestions, useAiUsage, usageNote } from "./remote-hooks"

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
                className="press relative grid size-10 place-items-center rounded-sm text-ai hover:bg-ai-wash pointer-coarse:size-11"
              />
            }
          >
            <AskAiIcon aria-hidden className="size-5" />
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
  const suggestions = useAiSuggestions(ctx)
  const route = useRouteKind()
  const [view, setView] = useState<"chat" | "history">("chat")
  useUpcoming(7)

  return (
    <aside
      aria-label="問 AI"
      className="sticky top-16 flex h-[calc(100dvh-4rem)] w-[340px] shrink-0 flex-col xl:w-[400px] before:pointer-events-none before:absolute before:inset-y-0 before:left-0 before:z-10 before:w-1 before:border-x before:border-rule"
    >
      <header className="flex h-14 shrink-0 items-center gap-0.5 border-b border-rule pr-4 pl-7 xl:pl-8">
        <h2 className="mr-auto flex items-center gap-2 text-base font-bold">
          <AskAiIcon aria-hidden className="size-[18px] text-ai" />
          {view === "history" ? "紀錄" : "問 AI"}
        </h2>
        <IconButton label="新對話" onClick={() => { newThread(); setView("chat") }}>
          <SquarePenIcon aria-hidden className="size-[18px]" />
        </IconButton>
        <IconButton label="紀錄" pressed={view === "history"} onClick={() => setView(view === "history" ? "chat" : "history")}>
          <HistoryIcon aria-hidden className="size-[18px]" />
        </IconButton>
        <IconButton label="收合 AI 面板" onClick={onCollapse}>
          <PanelRightCloseIcon aria-hidden className="size-[18px]" />
        </IconButton>
      </header>

      {/*
        輸入框一直在面板底部：還沒有對話時，建議、連結（或最近的對話）整塊貼在輸入框正上方（mt-auto）；
        開始對話後，對話從同一個位置往上長，輸入框不會跳。捲動區留 6px 下內距：最後一個連結的焦點外框不會被裁掉。
      */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-7 pb-1.5 xl:pr-7 xl:pl-8">
        {view === "history" ? (
          <HistoryList compact onOpen={() => setView("chat")} onReplay={(t) => void runner.submit(t)} />
        ) : (
          <div className="mt-auto">
            {thread ? (
              <Conversation key={thread.id} thread={thread} runner={runner} />
            ) : (
              <PanelHome
                ctx={ctx}
                runner={runner}
                suggestions={suggestions}
                size="panel"
                onShowHistory={route.kind === "history" ? undefined : () => setView("history")}
              />
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 px-7 pt-2.5 pb-5 xl:pr-7 xl:pl-8">
        <Composer
          ref={composerRef}
          variant="panel"
          placeholder={composerPlaceholder(ctx, "panel")}
          onSubmit={(t) => {
            setView("chat")
            void runner.submit(t)
          }}
          onAttach={(k) => runner.action(k)}
        />
        <UsageNote />
      </div>
    </aside>
  )
}

/**
 * 輸入框下方：只在提問額度剩 5 題以內、用完或 AI 暫時無法使用時出現一行。
 * 免責聲明不放這裡：每則 AI 回答下方已經固定顯示。
 */
export function UsageNote({ className }: { className?: string }) {
  const note = usageNote(useAiUsage().data)
  if (!note) return null
  return <p className={cn("mt-2.5 text-sm text-ink", className)}>{note}</p>
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
            className="press sel-chip grid size-9 place-items-center rounded-sm text-ink-2 pointer-coarse:size-11"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}
