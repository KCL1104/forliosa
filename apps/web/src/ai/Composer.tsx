import { ArrowUpIcon, PlusIcon } from "lucide-react"
import { toast } from "sonner"
import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState } from "react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { deepSearchCost, deepSearchHint } from "./deep-search"
import { useAiUsage } from "./remote-hooks"
import { currentThreadStreaming, useAi } from "./store"

export interface ComposerHandle {
  focus: () => void
}

interface Props {
  onSubmit: (text: string) => void
  /** 「＋」：改用表單記一筆 */
  onForm: () => void
  variant: "panel" | "screen"
  placeholder: string
  /** 手機：輸入時往上回報文字，用來即時搜尋股票 */
  onDraftChange?: (text: string) => void
}

/**
 * 輸入框是 AI 的主要入口：提問、記帳指令（「買 0050 2 張 52.4」）、搜尋（手機）。提示字依頁面（`composerPlaceholder`）。
 * Enter 送出、Shift+Enter 換行；⌘J 從任何地方聚焦（桌面）。
 * 「深度搜尋」是一個切換鈕（文字、`aria-pressed`）：開著時下一題多查幾輪資料、寫成一份整理，算好幾題；
 * 輸入框下面多一句話說這件事，送出後自動關掉（`runner.submit` 讀 `deepNext` 之後清掉）。
 */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer({ onSubmit, onForm, variant, placeholder, onDraftChange }, ref) {
  const [text, setText] = useState("")
  const area = useRef<HTMLTextAreaElement>(null)
  const hintId = useId()
  const line = useRef<HTMLInputElement>(null)
  const seed = useAi((s) => s.composerSeed)
  const deep = useAi((s) => s.deepNext)
  const setDeep = useAi((s) => s.setDeepNext)
  // 一次算幾題（後端說的；mock 模式用預設）。null＝這個環境沒有深度搜尋，不放切換鈕
  const deepCost = deepSearchCost(useAiUsage().data)
  useImperativeHandle(ref, () => ({ focus: () => (variant === "panel" ? area.current : line.current)?.focus() }), [variant])

  useEffect(() => {
    if (!seed) return
    setText(seed.text)
    onDraftChange?.(seed.text)
    const el = variant === "panel" ? area.current : line.current
    el?.focus()
    requestAnimationFrame(() => el?.setSelectionRange(seed.text.length, seed.text.length))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.nonce])

  const send = () => {
    const t = text.trim()
    if (!t) return
    // 上一則還在回答：問題留在框裡，不清掉（原本清掉之後才被拒絕，打的字就不見了；2026-11-14 review）
    if (currentThreadStreaming()) {
      toast("等這一則回答完再問下一題")
      return
    }
    onSubmit(t)
    setText("")
    onDraftChange?.("")
  }
  const change = (v: string) => {
    setText(v)
    onDraftChange?.(v)
  }
  const empty = text.trim().length === 0

  // 「＋」只有一件事：打開表單記一筆（匯入對帳單還沒有，還沒有的功能不出現；只有一項就不做成選單）
  const attach = (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label="用表單記一筆"
            onClick={onForm}
            className={cn(
              "press grid shrink-0 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink",
              variant === "panel" ? "size-9 pointer-coarse:size-11" : "size-11",
            )}
          />
        }
      >
        <PlusIcon aria-hidden className={variant === "panel" ? "size-[18px]" : "size-5"} />
      </TooltipTrigger>
      <TooltipContent>用表單記一筆</TooltipContent>
    </Tooltip>
  )

  // 「深度搜尋」：文字的切換鈕，不放圖示。關著時 1px 控制框（和「篩選」同一種小格），開著時選取語法 (b)（淡墨底＋墨色字）
  const deepToggle =
    deepCost === null ? null : (
      <button
        type="button"
        aria-pressed={deep}
        onClick={() => setDeep(!deep)}
        className={cn("press sel-chip inline-flex shrink-0 items-center rounded-sm px-2.5 text-ink-2", !deep && "shadow-[inset_0_0_0_1px_var(--ctl)]", variant === "panel" ? "h-9 text-sm pointer-coarse:h-11" : "h-11 text-base")}
      >
        深度搜尋
      </button>
    )
  // 開著時輸入框下面的一句話（要讀的句子：15px 墨色）
  const deepHint = deep && deepCost !== null ? <p className={cn("text-base text-ink", variant === "panel" ? "mt-2.5" : "min-w-0")}>{deepSearchHint(deepCost)}</p> : null

  if (variant === "screen") {
    return (
      <>
        <form
          className="flex h-14 items-center gap-1.5 rounded-md border border-act bg-raised px-1.5 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ink"
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
        >
          {attach}
          <input
            ref={line}
            value={text}
            onChange={(e) => change(e.target.value)}
            placeholder={placeholder}
            aria-label="搜尋股票、提問或下指令"
            enterKeyHint="send"
            autoComplete="off"
            className="h-full min-w-0 flex-1 bg-transparent px-1 text-lg text-ink outline-none placeholder:text-ink-2"
          />
          <button
            type="submit"
            aria-label="送出"
            aria-disabled={empty}
            className={cn("press grid size-11 shrink-0 place-items-center rounded-sm", empty ? "bg-rule text-ink-2 dark:bg-transparent dark:shadow-[inset_0_0_0_1px_var(--ctl)]" : "bg-act text-act-fg")}
          >
            <ArrowUpIcon aria-hidden className="size-5" />
          </button>
        </form>
        {/* 手機的一行輸入框放不下這顆鈕：放在輸入框下面一列，開著時那句話接在右邊（放不下就換行） */}
        {deepToggle && (
          // 切換鈕關著時有框：框的左緣對齊輸入框的左緣（不再往左拉）
          <div className="mt-2 flex flex-wrap items-center gap-x-2.5">
            {deepToggle}
            {deepHint}
          </div>
        )}
      </>
    )
  }

  return (
    <>
      <form
        className="group rounded-md border border-act bg-raised px-3.5 pt-3 pb-2.5 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ink"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
        aria-label="問 AI"
      >
        <textarea
          ref={area}
          value={text}
          onChange={(e) => change(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send()
            }
          }}
          rows={2}
          placeholder={placeholder}
          aria-label="提出問題或下指令"
          aria-describedby={hintId}
          className="block h-[54px] w-full resize-none bg-transparent leading-relaxed text-ink outline-none placeholder:text-ink-2"
        />
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            {attach}
            {deepToggle}
          </div>
          <div className="flex items-center gap-3">
            {/* 鍵盤提示只在輸入框有焦點時出現；螢幕閱讀器從 aria-describedby 讀到同一句（這裡 Enter 是送出，不是換行） */}
            {/* 旁邊多了「深度搜尋」之後整句放不下（面板 400px）：畫面上只留「Enter 送出」，完整的一句仍由 aria-describedby 讀出 */}
            <span aria-hidden className="hidden text-sm whitespace-nowrap text-ink-2 xl:group-focus-within:inline">
              {deepToggle ? "Enter 送出" : "Enter 送出・Shift+Enter 換行"}
            </span>
            <span id={hintId} className="sr-only">
              Enter 送出，Shift+Enter 換行
            </span>
            <button
              type="submit"
              aria-label="送出"
              disabled={empty}
              className="press grid size-9 place-items-center rounded-sm bg-act text-act-fg hover:bg-act-hover disabled:bg-rule disabled:text-ink-2 dark:disabled:bg-transparent dark:disabled:shadow-[inset_0_0_0_1px_var(--ctl)] pointer-coarse:size-11"
            >
              <ArrowUpIcon aria-hidden className="size-[18px]" />
            </button>
          </div>
        </div>
      </form>
      {deepHint}
    </>
  )
})
