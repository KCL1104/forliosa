import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { useNavigate } from "@tanstack/react-router"
import { HistoryIcon, SquarePenIcon, XIcon } from "lucide-react"
import { useState } from "react"
import { appToday } from "@/api"
import { useInstrumentSearch } from "@/api/queries"
import { useMediaQuery } from "@/hooks/use-media-query"
import { marketTag } from "@/lib/labels"
import { cn } from "@/lib/utils"
import { UsageNote } from "./AiPanel"
import { Composer } from "./Composer"
import { useAiContext, useRouteKind } from "./context"
import { Conversation } from "./Conversation"
import { PanelHome } from "./Home"
import { composerPlaceholder } from "./panel-helpers"
import { parseIntent } from "./intent"
import { useAiRunner } from "./runner"
import { useAi, useCurrentThread } from "./store"
import { useAiSuggestions } from "./remote-hooks"

/**
 * 手機的「問 AI」：全螢幕。內容和桌面面板同一套；輸入框一直在底部（拇指按得到；桌面面板還沒有對話時輸入框在最上面），
 * 格線列的建議、一行文字連結（沒有建議的頁面是最近的對話）貼在它上方。
 * 搜尋股票在手機上住在這裡：輸入代號或名稱時，符合的股票一律列在輸入框「上方」——
 * iOS Safari 的鍵盤直接蓋在全螢幕的畫面上（不縮版面），列在輸入框下方會被鍵盤蓋住。
 * 對話紀錄：手機的底部列沒有「紀錄」分頁，從這裡右上角的時鐘到紀錄頁（`/history`；「全部紀錄」也是）。
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
  const [typing, setTyping] = useState("")
  const navigate = useNavigate()
  // 320 寬放不下「搜尋，或說：買 0050 2 張」（只看得到一半）：窄螢幕用短的提示
  const narrow = useMediaQuery("(max-width: 359px)")
  const newThread = useAi((s) => s.newThread)
  const route = useRouteKind()
  const intent = parseIntent(typing, appToday())
  const searchTerm = intent.kind === "lookup" || (intent.kind === "question" && typing.trim().length <= 6) ? typing.trim() : ""
  const search = useInstrumentSearch(searchTerm)
  const results = searchTerm ? (search.data ?? []).slice(0, 5) : []
  // 搜尋結果都在輸入框上方：首頁狀態取代建議與連結（同一套格線列，最多約建議區的高度）；對話中浮在輸入框上
  const home = !thread
  // 紀錄是一整頁（/history）：關掉問 AI、到那一頁；從那裡挑一段對話會再打開這個畫面
  const showHistory = () => {
    onClose()
    void navigate({ to: "/history" })
  }
  const homeResults = home && results.length > 0

  const resultList = results.length > 0 && (
    <ul
      className={cn(
        "shrink-0 overflow-y-auto overscroll-contain",
        home ? "-mx-5 max-h-[220px] border-t border-rule" : "mx-5 mb-2 max-h-[40dvh] rounded-md border border-rule bg-raised shadow-lift",
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
            <span className="shrink-0 text-sm text-ink-2">{marketTag(i)}</span>
          </button>
        </li>
      ))}
    </ul>
  )

  const iconButton = "press sel-chip grid size-11 place-items-center rounded-sm text-ink-2"

  return (
    <>
      <header className="flex shrink-0 items-center gap-1 border-b border-rule pt-[env(safe-area-inset-top,0px)] pr-3 pl-5">
        <DialogPrimitive.Title className="mr-auto flex h-[60px] items-center text-[1.375rem] font-bold">
          問 AI
        </DialogPrimitive.Title>
        {/* 三個圖示鈕同一個樣式（44px、方肩、淡墨，按下是淡墨底）；「紀錄」（時鐘）到紀錄頁 */}
        <button type="button" aria-label="新對話" onClick={() => newThread()} className={iconButton}>
          <SquarePenIcon aria-hidden className="size-[22px]" />
        </button>
        <button type="button" aria-label="對話紀錄" title="對話紀錄" onClick={showHistory} className={iconButton}>
          <HistoryIcon aria-hidden className="size-[22px]" />
        </button>
        <DialogPrimitive.Close aria-label="關閉" className={iconButton}>
          <XIcon aria-hidden className="size-[22px]" />
        </DialogPrimitive.Close>
      </header>

      {/*
        輸入框一直在底部：還沒有對話時，建議、連結（或最近的對話、搜尋結果）整塊貼在輸入框正上方（mt-auto），
        開始對話後從同一個位置往上長，輸入框不會跳。捲動區留 6px 下內距：最後一個連結的焦點外框不會被裁掉。
      */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-5 pb-1.5">
        <div className="mt-auto">
          {thread ? (
            <Conversation key={thread.id} thread={thread} runner={runner} size="screen" onNavigate={onClose} />
          ) : homeResults ? (
            resultList
          ) : (
            <PanelHome ctx={ctx} runner={runner} suggestions={suggestions} size="screen" onShowHistory={route.kind === "history" ? undefined : showHistory} />
          )}
        </div>
      </div>

      {!home && resultList}

      <div className="shrink-0 px-5 pt-2.5 pb-[max(12px,env(safe-area-inset-bottom,0px))]">
        <Composer
          variant="screen"
          placeholder={narrow ? "搜尋或提問" : composerPlaceholder(ctx, "screen")}
          onDraftChange={setTyping}
          onSubmit={(t) => void runner.submit(t)}
          onForm={() => runner.action("form")}
        />
        <UsageNote />
      </div>
    </>
  )
}
