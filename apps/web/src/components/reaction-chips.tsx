import { useState } from "react"
import { REACTION_EMOJIS, type Reaction, type ReactionEmoji } from "@/api/types"
import { textAction } from "@/components/text-action"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { EMOJI_LABEL } from "@/lib/labels"
import { cn } from "@/lib/utils"

/** 每一則都會重複的動作（加表情、留言、刪除、檢舉）：文字動作的安靜版——淡墨字＋常駐底線，滑過或展開時變墨色（觸控時的可按範圍見 textAction） */
export const QUIET_ACTION = "text-sm text-ink-2 hover:text-ink aria-expanded:text-ink aria-expanded:decoration-ink"

const CHIP = "inline-flex h-7 items-center gap-1 rounded-sm border border-rule px-2 text-sm text-ink-2 pointer-coarse:h-8 pointer-coarse:px-2.5"

/**
 * 表情（群組動態、週報、排行討論、討論串共用）：已經有人按的表情是方肩的小格（4px、1px 格線框、表情＋數字——
 * 和系統裡其他選項同一種方格，不是膠囊）；自己按過的用選取語法 (b)。旁邊的「加表情」打開六個固定的表情。
 * 這個元件只負責畫與回報按了哪一個；計數怎麼更新（樂觀更新、重新讀取）由外面決定。
 * `readOnly`（沒登入）：只顯示計數，不能按、沒有「加表情」。
 */
export function ReactionChips({
  reactions,
  onToggle,
  readOnly,
  className,
}: {
  reactions: Reaction[]
  /** `on`：按下之後這個表情是不是「我按過」 */
  onToggle?: (emoji: ReactionEmoji, on: boolean) => void
  readOnly?: boolean
  className?: string
}) {
  const [open, setOpen] = useState(false)
  if (readOnly) {
    if (reactions.length === 0) return null
    return (
      <ul aria-label="表情" className={cn("flex flex-wrap items-center gap-1.5", className)}>
        {reactions.map((r) => (
          <li key={r.emoji} className={CHIP}>
            <span aria-hidden>{r.emoji}</span>
            <span aria-hidden className="num">
              {r.count}
            </span>
            <span className="sr-only">{`${EMOJI_LABEL[r.emoji]} ${r.count}`}</span>
          </li>
        ))}
      </ul>
    )
  }
  const press = (emoji: ReactionEmoji) => onToggle?.(emoji, !reactions.find((r) => r.emoji === emoji)?.mine)
  return (
    <div className={cn("flex flex-wrap items-center gap-x-1.5", className)}>
      {reactions.map((r) => (
        // 觸控時按鈕本身 44px 高、至少 44px 寬，看得到的小格在裡面（選取語法 (b) 跟著 data-pressed）
        <button
          key={r.emoji}
          type="button"
          aria-pressed={r.mine}
          aria-label={`${EMOJI_LABEL[r.emoji]} ${r.count}${r.mine ? "，你按過" : ""}`}
          onClick={() => press(r.emoji)}
          className="press inline-flex items-center justify-center rounded-sm pointer-coarse:min-h-11 pointer-coarse:min-w-11"
        >
          <span data-pressed={r.mine ? "" : undefined} className={cn(CHIP, "sel-chip data-pressed:border-transparent")}>
            <span aria-hidden>{r.emoji}</span>
            <span className="num">{r.count}</span>
          </span>
        </button>
      ))}
      <Popover open={open} onOpenChange={setOpen}>
        {/* 和「留言」一樣是有字的文字動作（常駐底線），不放圖示 */}
        <PopoverTrigger render={<button type="button" className={cn(textAction, QUIET_ACTION, "ml-1.5 first:ml-0")} />}>加表情</PopoverTrigger>
        <PopoverContent className="w-auto flex-row gap-1 p-1.5" side="top" align="start">
          {REACTION_EMOJIS.map((e) => {
            const mine = reactions.find((r) => r.emoji === e)?.mine ?? false
            return (
              <button
                key={e}
                type="button"
                aria-pressed={mine}
                aria-label={EMOJI_LABEL[e]}
                title={EMOJI_LABEL[e]}
                onClick={() => {
                  press(e)
                  setOpen(false)
                }}
                className="press sel-chip grid size-9 place-items-center rounded-sm text-lg pointer-coarse:size-11"
              >
                {e}
              </button>
            )
          })}
        </PopoverContent>
      </Popover>
    </div>
  )
}
