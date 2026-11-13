import { Trash2Icon } from "lucide-react"
import { DateCell } from "@/components/date-cell"
import { EmptyState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { TZ, todayInTaipei } from "@/lib/format"
import { relativeTime } from "@/lib/news"
import { cn } from "@/lib/utils"
import { bleed, bleedPad } from "./panel-helpers"
import { useAi } from "./store"
import { useThreadList } from "./threads"
import type { Thread } from "./types"

/** 台北時間的「13:41」 */
function clock(iso: string): string {
  return new Intl.DateTimeFormat("zh-TW", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso))
}

/**
 * 紀錄：發起新對話（一般按鈕）、過去的對話（刪除後可以復原）。
 * 整頁（紀錄頁）是一張印好表頭的表：第一欄是聯絡簿的日期格（日期＋時間），整列都可以按；
 * 面板裡（`compact`）是一行一格的格線列：標題＋相對時間。
 */
export function HistoryList({ compact, onOpen, onReplay }: { compact?: boolean; onOpen?: () => void; onReplay: (text: string) => void }) {
  const newThread = useAi((s) => s.newThread)
  const list = useThreadList()
  const pick = (t: Thread) => list.open(t, { onOpen, onReplay })

  return (
    <div className="flex flex-col">
      <Button
        variant="outline"
        className={cn("self-start", compact ? "mt-4" : "mt-1")}
        onClick={() => {
          newThread()
          onOpen?.()
        }}
      >
        發起新對話
      </Button>

      {list.loading ? (
        <p className={cn("text-base text-ink", compact ? "mt-4" : "mt-8")} role="status">
          正在載入對話…
        </p>
      ) : list.error ? (
        <p className={cn("text-base text-ink", compact ? "mt-4" : "mt-8")}>
          對話紀錄暫時載入不了。
          <button type="button" onClick={list.retry} className="press ml-1 inline-flex min-h-9 items-center text-ink underline decoration-ctl underline-offset-4 hover:decoration-ink pointer-coarse:min-h-11">
            再試一次
          </button>
        </p>
      ) : list.all.length === 0 ? (
        <EmptyState className={compact ? "mt-4" : "mt-8"} title="還沒有對話" />
      ) : compact ? (
        <ThreadRows threads={list.all} onPick={pick} onRemove={list.remove} bleed className="mt-4 border-t border-rule" />
      ) : (
        <ThreadTable threads={list.all} onPick={pick} onRemove={list.remove} />
      )}

      <p className="mt-3 text-sm text-ink-2">對話紀錄保留 30 天。</p>
    </div>
  )
}

/**
 * 一行一格的對話列（面板的紀錄、沒有建議的頁面上「最近的對話」）：標題＋相對時間（淡墨），整列都可以按。
 * 有 `onRemove` 時右邊多一個刪除圖示鈕（滑過有說明）。
 */
export function ThreadRows({
  threads,
  onPick,
  onRemove,
  size = "panel",
  className,
  label = "對話",
  bleed: edge,
}: {
  threads: Thread[]
  onPick: (t: Thread) => void
  onRemove?: (t: Thread) => void
  size?: "panel" | "screen"
  className?: string
  label?: string
  /** 左右延伸到面板邊緣（和建議的格線列一樣） */
  bleed?: boolean
}) {
  const now = new Date()
  const screen = size === "screen"
  return (
    <ul aria-label={label} className={cn(edge && bleed[size], className)}>
      {threads.map((t) => (
        <li key={t.id} className={cn("ruled-row relative flex items-center gap-3", edge && bleedPad[size], screen ? "min-h-14" : "min-h-[52px]")}>
          <button
            type="button"
            onClick={() => onPick(t)}
            className={cn(
              "min-w-0 flex-1 truncate py-3 text-left text-ink after:absolute after:inset-0 focus-visible:-outline-offset-2",
              screen ? "text-lg" : "text-base",
            )}
          >
            {t.title}
          </button>
          <span className="num shrink-0 text-sm text-ink-2">{relativeTime(t.updatedAt, now)}</span>
          {onRemove && <RemoveButton thread={t} onRemove={onRemove} className="relative z-10 -mr-2" />}
        </li>
      ))}
    </ul>
  )
}

/** 紀錄頁：印好的表頭（日期・對話），日期格是日期＋時間，整列都可以按 */
function ThreadTable({ threads, onPick, onRemove }: { threads: Thread[]; onPick: (t: Thread) => void; onRemove: (t: Thread) => void }) {
  return (
    <div className="mt-8">
      <div aria-hidden className="form-head flex gap-3 pb-2">
        <span className="w-[5.75rem] shrink-0 lg:w-[6.5rem]">日期</span>
        <span>對話</span>
      </div>
      <ul aria-label="對話">
        {threads.map((t) => (
          <li key={t.id} className="ruled-row relative flex min-h-16 items-center gap-3 py-2.5">
            <DateCell date={todayInTaipei(new Date(t.updatedAt))} inline className="w-[5.75rem] shrink-0 lg:w-[6.5rem]">
              <span className="num mt-0.5 text-sm font-normal text-ink-2">{clock(t.updatedAt)}</span>
            </DateCell>
            <button
              type="button"
              onClick={() => onPick(t)}
              className="min-w-0 flex-1 text-left text-base text-ink after:absolute after:inset-0 focus-visible:-outline-offset-2 lg:text-lg"
            >
              <span className="line-clamp-2">{t.title}</span>
            </button>
            <RemoveButton thread={t} onRemove={onRemove} className="relative z-10" />
          </li>
        ))}
      </ul>
    </div>
  )
}

function RemoveButton({ thread, onRemove, className }: { thread: Thread; onRemove: (t: Thread) => void; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={`刪除對話「${thread.title}」`}
            onClick={() => onRemove(thread)}
            className={cn("press grid size-11 shrink-0 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink", className)}
          />
        }
      >
        <Trash2Icon aria-hidden className="size-[18px]" />
      </TooltipTrigger>
      <TooltipContent>刪除對話</TooltipContent>
    </Tooltip>
  )
}
