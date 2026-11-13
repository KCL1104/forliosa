import { HistoryIcon, PanelRightCloseIcon, SquarePenIcon } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
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

/**
 * 桌面右側 AI 面板（約 400px，可收合成 56px 的窄欄）。開合由 `AppShell` 決定（`useAiPanelOpen`）：
 * 帳本與個股頁照記住的狀態，AI 沒什麼可說的頁面預設是窄欄。
 */
export function AiPanel({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const pending = usePendingCount()
  const composer = useRef<ComposerHandle>(null)
  const setOpen = useRef(onOpenChange)
  useEffect(() => {
    setOpen.current = onOpenChange
  })

  // ⌘J：打開面板並聚焦輸入框
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "j" || e.key === "J") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen.current(true)
        requestAnimationFrame(() => composer.current?.focus())
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  if (!open) {
    return (
      <aside aria-label="問 AI（已收合）" className="sticky top-16 flex h-[calc(100dvh-4rem)] w-14 shrink-0 flex-col items-center gap-2 border-l border-rule pt-4">
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                onClick={() => onOpenChange(true)}
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
  return <PanelBody composerRef={composer} onCollapse={() => onOpenChange(false)} />
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

  // 還沒有對話：輸入框在最上面，建議接在它下面（面板不再是上面一大片空白、東西全擠在底部）。
  // 有對話之後輸入框在底部，對話往上長。
  const atTop = !thread
  // 輸入框換位置時 DOM 節點會被搬動、焦點會掉：如果是在面板裡操作造成的（送出、按建議、新對話），把焦點放回輸入框。
  // 從頁面打開一段對話（帳本的「待簽名」、紀錄頁）不搶焦點。
  const touched = useRef(0)
  const touch = () => {
    touched.current = Date.now()
  }
  const wasAtTop = useRef(atTop)
  useLayoutEffect(() => {
    if (wasAtTop.current === atTop) return
    wasAtTop.current = atTop
    if (Date.now() - touched.current < 1500) composerRef.current?.focus()
  }, [atTop, composerRef])

  const composer = (
    <div key="composer" className={cn("shrink-0 px-7 xl:pr-7 xl:pl-8", atTop ? "py-4" : "pt-2.5 pb-5")}>
      <Composer
        ref={composerRef}
        variant="panel"
        placeholder={composerPlaceholder(ctx, "panel")}
        onSubmit={(t) => {
          setView("chat")
          void runner.submit(t)
        }}
        onForm={() => runner.action("form")}
      />
      <UsageNote />
    </div>
  )
  // 捲動區留 6px 下內距：最後一個連結的焦點外框不會被裁掉
  const body = (
    <div key="body" className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-7 pb-1.5 xl:pr-7 xl:pl-8">
      {view === "history" ? (
        <HistoryList compact onOpen={() => setView("chat")} onReplay={(t) => void runner.submit(t)} />
      ) : thread ? (
        // 對話從輸入框正上方往上長（mt-auto）：內容與輸入框之間沒有大片空白
        <div className="mt-auto">
          <Conversation key={thread.id} thread={thread} runner={runner} />
        </div>
      ) : (
        <PanelHome
          ctx={ctx}
          runner={runner}
          suggestions={suggestions}
          size="panel"
          onShowHistory={route.kind === "history" ? undefined : () => setView("history")}
          // 紀錄頁本身就是完整的對話清單：旁邊的面板不再列「最近的對話」
          hideRecent={route.kind === "history"}
        />
      )}
    </div>
  )

  return (
    <aside
      aria-label="問 AI"
      onPointerDownCapture={touch}
      onKeyDownCapture={touch}
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

      {/* 兩塊都有 key：換順序時 React 搬節點，不重新掛載（輸入框裡打到一半的字還在） */}
      {atTop ? [composer, body] : [body, composer]}
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
