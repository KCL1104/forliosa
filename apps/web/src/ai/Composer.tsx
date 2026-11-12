import { ArrowUpIcon, PlusIcon } from "lucide-react"
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { useAi } from "./store"

export interface ComposerHandle {
  focus: () => void
}

interface Props {
  onSubmit: (text: string) => void
  onAttach: (kind: "import" | "form") => void
  variant: "panel" | "screen"
  placeholder: string
  /** 手機：輸入時往上回報文字，用來即時搜尋股票 */
  onDraftChange?: (text: string) => void
}

/**
 * 輸入框是 AI 的主要入口：提問、記帳指令（「買 0050 2 張 52.4」）、搜尋（手機）。
 * Enter 送出、Shift+Enter 換行；⌘J 從任何地方聚焦（桌面）。
 */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer({ onSubmit, onAttach, variant, placeholder, onDraftChange }, ref) {
  const [text, setText] = useState("")
  const area = useRef<HTMLTextAreaElement>(null)
  const line = useRef<HTMLInputElement>(null)
  const seed = useAi((s) => s.composerSeed)
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
    onSubmit(t)
    setText("")
    onDraftChange?.("")
  }
  const change = (v: string) => {
    setText(v)
    onDraftChange?.(v)
  }
  const empty = text.trim().length === 0

  const attach = (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label="附件與其他記帳方式"
            className={cn(
              "press grid shrink-0 place-items-center text-ink-2 hover:text-ink",
              variant === "panel" ? "size-9 rounded-sm border border-rule hover:bg-hov" : "size-11 rounded-full text-ai",
            )}
          />
        }
      >
        <PlusIcon aria-hidden className={variant === "panel" ? "size-[18px]" : "size-[22px]"} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-56">
        <DropdownMenuItem onClick={() => onAttach("import")}>匯入對帳單（M3）</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onAttach("form")}>改用表單記一筆</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )

  if (variant === "screen") {
    return (
      <form
        className="flex h-14 items-center gap-1 rounded-full border border-ai-rule bg-ai-wash pr-1.5 pl-1.5 focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-ai"
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
          aria-label="搜尋股票、提問，或直接說：買 0050 2 張 52.4"
          enterKeyHint="send"
          autoComplete="off"
          className="h-full min-w-0 flex-1 bg-transparent text-lg text-ink caret-ai outline-none placeholder:text-ink-2"
        />
        <button
          type="submit"
          aria-label="送出"
          aria-disabled={empty}
          className={cn("press grid size-11 shrink-0 place-items-center rounded-full", empty ? "bg-rule text-ink-2" : "bg-ai text-raised")}
        >
          <ArrowUpIcon aria-hidden className="size-5" />
        </button>
      </form>
    )
  }

  return (
    <form
      className="rounded-md border border-act bg-raised px-3.5 pt-3 pb-2.5 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ink"
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
        className="block h-[54px] w-full resize-none bg-transparent leading-relaxed text-ink outline-none placeholder:text-ink-2"
      />
      <div className="mt-1.5 flex items-center gap-1">
        {attach}
        <span className="ml-auto mr-2 hidden text-xs text-ink-2 xl:inline">Enter 送出・Shift+Enter 換行</span>
        <button
          type="submit"
          aria-label="送出"
          disabled={empty}
          className="press grid size-9 place-items-center rounded-sm bg-act text-act-fg hover:bg-act-hover disabled:bg-rule disabled:text-ink-2"
        >
          <ArrowUpIcon aria-hidden className="size-[18px]" />
        </button>
      </div>
    </form>
  )
})
