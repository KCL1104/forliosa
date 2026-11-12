import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { useNavigate } from "@tanstack/react-router"
import { HistoryIcon, XIcon } from "lucide-react"
import { useState } from "react"
import { appToday } from "@/api"
import { useInstrumentSearch } from "@/api/queries"
import { MARKET_LABEL } from "@/lib/labels"
import { cn } from "@/lib/utils"
import { UsageNote } from "./AiPanel"
import { Composer } from "./Composer"
import { useAiContext } from "./context"
import { Conversation } from "./Conversation"
import { HistoryList } from "./HistoryList"
import { PanelHome } from "./Home"
import { parseIntent } from "./intent"
import { useAiRunner } from "./runner"
import { useAi, useCurrentThread } from "./store"
import { useAiSuggestions } from "./remote-hooks"

/**
 * 手機的「問 AI」：全螢幕。和桌面面板同一套：格線列的建議、一行文字連結、緊接著輸入框；有對話時輸入框固定在底部。
 * 搜尋股票在手機上住在這裡：輸入代號或名稱時，符合的股票一律列在輸入框「上方」——
 * iOS Safari 的鍵盤直接蓋在全螢幕的畫面上（不縮版面），列在輸入框下方會被鍵盤蓋住。
 */
export function AiScreen() {
  const open = useAi((s) => s.mobileOpen)
  const setOpen = useAi((s) => s.setMobileOpen)
  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Popup
          className="fixed inset-0 z-50 flex flex-col bg-paper text-ink outline-none transition-[transform,opacity] duration-300 ease-[var(--ease-drawer)] data-[ending-style]:translate-y-6 data-[ending-style]:opacity-0 data-[starting-style]:translate-y-6 data-[starting-style]:opacity-0"
        >
          {open && <ScreenBody onClose={() => setOpen(false)} />}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

function ScreenBody({ onClose }: { onClose: () => void }) {
  const ctx = useAiContext()
  const runner = useAiRunner(ctx)
  const thread = useCurrentThread()
  const suggestions = useAiSuggestions(ctx)
  const [view, setView] = useState<"chat" | "history">("chat")
  const [typing, setTyping] = useState("")
  const navigate = useNavigate()
  const intent = parseIntent(typing, appToday())
  const searchTerm = intent.kind === "lookup" || (intent.kind === "question" && typing.trim().length <= 6) ? typing.trim() : ""
  const search = useInstrumentSearch(searchTerm)
  const results = searchTerm ? (search.data ?? []).slice(0, 5) : []
  // 還沒有對話：建議、連結和輸入框由上往下緊接著排；有對話時輸入框固定在底部。
  // 搜尋結果都在輸入框上方：首頁狀態取代建議與連結（同一套格線列，最多約建議區的高度，輸入框不會跳）；對話中浮在輸入框上
  const home = view === "chat" && !thread
  const homeResults = home && results.length > 0

  const resultList = results.length > 0 && (
    <ul
      className={cn(
        "shrink-0 overflow-y-auto overscroll-contain",
        home ? "-mx-5 max-h-[220px]" : "mx-5 mb-2 max-h-[40dvh] rounded-md border border-rule bg-raised shadow-lift",
      )}
      aria-label="股票搜尋結果"
    >
      {results.map((i) => (
        <li key={i.symbol}>
          <button
            type="button"
            onClick={() => {
              onClose()
              void navigate({ to: "/stock/$symbol", params: { symbol: i.symbol } })
            }}
            className={cn(
              "flex min-h-12 w-full items-center gap-3 border-b border-rule text-left active:bg-hov focus-visible:-outline-offset-2",
              home ? "px-5 text-lg" : "px-4 last:border-0",
            )}
          >
            {/* 代號欄放得下 6 碼（006208）：17px 時 64px */}
            <span className={cn("num shrink-0 font-medium", home ? "w-16" : "w-14")}>{i.code}</span>
            <span className="min-w-0 flex-1 truncate">{i.name}</span>
            <span className="shrink-0 text-sm text-ink-2">{MARKET_LABEL[i.market]}</span>
          </button>
        </li>
      ))}
    </ul>
  )

  return (
    <>
      <header className="flex shrink-0 items-center gap-1 border-b border-rule pt-[env(safe-area-inset-top,0px)] pr-3 pl-5">
        <DialogPrimitive.Title className="mr-auto flex h-[60px] items-center text-[1.375rem] font-bold">
          {view === "history" ? "紀錄" : "問 AI"}
        </DialogPrimitive.Title>
        <button
          type="button"
          aria-label="紀錄與 AI 任務"
          aria-pressed={view === "history"}
          onClick={() => setView(view === "history" ? "chat" : "history")}
          className="press sel-chip grid size-11 place-items-center rounded-full text-ink-2"
        >
          <HistoryIcon aria-hidden className="size-[22px]" />
        </button>
        <DialogPrimitive.Close aria-label="關閉" className="press grid size-11 place-items-center rounded-full bg-hov text-ink active:bg-rule">
          <XIcon aria-hidden className="size-[22px]" />
        </DialogPrimitive.Close>
      </header>

      {/* 首頁狀態留 6px 下內距：最後一個連結的焦點外框（外推 4px）不會被捲動區裁掉 */}
      <div className={cn("min-h-0 overflow-y-auto overscroll-contain px-5", home ? "shrink pb-1.5" : "flex-1 pb-6")}>
        {view === "history" ? (
          <HistoryList onOpen={() => setView("chat")} onReplay={(t) => void runner.submit(t)} />
        ) : thread ? (
          <Conversation key={thread.id} thread={thread} runner={runner} size="screen" onNavigate={onClose} />
        ) : homeResults ? (
          resultList
        ) : (
          <PanelHome ctx={ctx} runner={runner} suggestions={suggestions} size="screen" />
        )}
      </div>

      {!home && resultList}

      <div className={cn("shrink-0 px-5", home ? "pt-2.5" : "pt-1 pb-[max(12px,env(safe-area-inset-bottom,0px))]")}>
        <Composer
          variant="screen"
          placeholder="搜尋或提問"
          onDraftChange={setTyping}
          onSubmit={(t) => {
            setView("chat")
            void runner.submit(t)
          }}
          onAttach={(k) => runner.action(k)}
        />
        <UsageNote />
      </div>
    </>
  )
}
