import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { useNavigate } from "@tanstack/react-router"
import { ArrowUpRightIcon, HistoryIcon, XIcon } from "lucide-react"
import { useState } from "react"
import { appToday } from "@/api"
import { useInstrumentSearch } from "@/api/queries"
import { MARKET_LABEL } from "@/lib/labels"
import { cn } from "@/lib/utils"
import { MoreActions } from "./AiPanel"
import { DISCLAIMER, useActions, useGreeting } from "./panel-helpers"
import { Composer } from "./Composer"
import { useAiContext } from "./context"
import { Conversation } from "./Conversation"
import { HistoryList } from "./HistoryList"
import { parseIntent } from "./intent"
import { useAiRunner } from "./runner"
import { useAi, useCurrentThread } from "./store"
import { suggestionsFor } from "./suggestions"

/**
 * 手機的「問 AI」：全螢幕。大字問候、橫滑的建議卡、交給 AI 的動作、底部「搜尋或提問」。
 * 搜尋股票在手機上住在這裡：輸入代號或名稱時，上方即時列出符合的股票。
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
  const { hello, line } = useGreeting(ctx)
  const suggestions = suggestionsFor(ctx, appToday())
  const actions = useActions(ctx)
  const [view, setView] = useState<"chat" | "history">("chat")
  const [typing, setTyping] = useState("")
  const navigate = useNavigate()
  const intent = parseIntent(typing, appToday())
  const searchTerm = intent.kind === "lookup" || (intent.kind === "question" && typing.trim().length <= 6) ? typing.trim() : ""
  const search = useInstrumentSearch(searchTerm)
  const results = searchTerm ? (search.data ?? []).slice(0, 5) : []

  return (
    <>
      <header className="flex shrink-0 items-center gap-1 pt-[env(safe-area-inset-top,0px)] pr-3 pl-5">
        <DialogPrimitive.Title className="mr-auto flex h-[60px] items-center text-[1.375rem] font-bold">
          {view === "history" ? "紀錄" : "問 AI"}
        </DialogPrimitive.Title>
        <button
          type="button"
          aria-label={view === "history" ? "回到問 AI" : "紀錄與 AI 任務"}
          aria-pressed={view === "history"}
          onClick={() => setView(view === "history" ? "chat" : "history")}
          className="press grid size-11 place-items-center rounded-full text-ink-2 active:bg-rule"
        >
          <HistoryIcon aria-hidden className="size-[22px]" />
        </button>
        <DialogPrimitive.Close aria-label="關閉" className="press grid size-11 place-items-center rounded-full bg-hov text-ink active:bg-rule">
          <XIcon aria-hidden className="size-[22px]" />
        </DialogPrimitive.Close>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-6">
        {view === "history" ? (
          <HistoryList onOpen={() => setView("chat")} onReplay={(t) => void runner.submit(t)} />
        ) : thread ? (
          <Conversation key={thread.id} thread={thread} runner={runner} size="screen" onNavigate={onClose} />
        ) : (
          <div className="flex flex-col">
            <p className="ai-voice mt-7">
              <span className="block text-3xl leading-tight">{hello}</span>
              <span className="mt-2 block text-2xl leading-snug">{ctx.route === "stock" ? line : "帳本、個股、群組的事都可以問我。"}</span>
            </p>
            {suggestions.length > 0 && (
              <ul className="no-scrollbar -mx-5 mt-10 flex snap-x snap-mandatory scroll-px-5 gap-2.5 overflow-x-auto overscroll-x-contain px-5" aria-label="可以這樣問">
                {suggestions.map((s) => (
                  <li key={s.kind} className="snap-start">
                    <button
                      type="button"
                      onClick={() => runner.ask(s)}
                      className="press grid h-[156px] w-[156px] grid-rows-[1fr_auto] rounded-xl border border-rule bg-raised p-4 pr-3.5 pb-3.5 text-left text-lg leading-normal font-medium active:bg-hov"
                    >
                      <span>
                        {s.lines ? (
                          <>
                            {s.lines[0]}
                            <br />
                            {s.lines[1]}
                          </>
                        ) : (
                          s.text
                        )}
                      </span>
                      <span aria-hidden className="grid size-9 place-items-center justify-self-end rounded-full bg-hov text-ink-2">
                        <ArrowUpRightIcon className="size-[18px]" />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <h2 className="mt-11 text-base font-bold text-ink-2">交給 AI</h2>
            <div className="mt-3 flex flex-wrap gap-x-2 gap-y-3">
              {actions.map((a) => (
                <button key={a.key} type="button" onClick={() => runner.action(a.run, { code: a.code })} className="press relative h-10 rounded-full border border-ctl px-3 text-md whitespace-nowrap before:absolute before:inset-x-0 before:-inset-y-0.5 active:bg-hov">
                  {a.label}
                </button>
              ))}
              <MoreActions runner={runner} code={ctx.route === "stock" ? ctx.stock.code : undefined} className="relative h-10 rounded-full px-3 before:absolute before:inset-x-0 before:-inset-y-0.5 [&_svg]:hidden" />
            </div>
            <p className="mt-5 text-xs text-ink-2">{DISCLAIMER}</p>
          </div>
        )}
      </div>

      {results.length > 0 && (
        <ul className="mx-4 mb-2 max-h-[40dvh] overflow-y-auto rounded-xl border border-rule bg-raised shadow-lift" aria-label="股票搜尋結果">
          {results.map((i) => (
            <li key={i.symbol}>
              <button
                type="button"
                onClick={() => {
                  onClose()
                  void navigate({ to: "/stock/$symbol", params: { symbol: i.symbol } })
                }}
                className={cn("flex min-h-12 w-full items-center gap-3 border-b border-rule px-4 text-left last:border-0 active:bg-hov")}
              >
                <span className="num w-14 shrink-0 font-medium">{i.code}</span>
                <span className="min-w-0 flex-1 truncate">{i.name}</span>
                <span className="shrink-0 text-sm text-ink-2">{MARKET_LABEL[i.market]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="shrink-0 px-4 pt-1 pb-[max(12px,env(safe-area-inset-bottom,0px))]">
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
      </div>
    </>
  )
}
