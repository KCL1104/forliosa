import { EllipsisIcon, SquarePenIcon, Trash2Icon } from "lucide-react"
import { useState } from "react"
import { api } from "@/api"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useAi } from "./store"
import type { Thread } from "./types"

/**
 * 紀錄：發起新對話、過去的對話、AI 任務。
 * M4 之前：對話存在這台瀏覽器；AI 任務是示範資料（排程在 M4 定義端點）。
 */
const SEEDED: Thread[] = [
  { id: "seed_why", title: "為什麼台積電今天漲 4.83%？", updatedAt: "2026-11-12T13:41:00+08:00", messages: [], seeded: true },
  { id: "seed_878", title: "00878 下次除息能領多少？", updatedAt: "2026-11-11T21:08:00+08:00", messages: [], seeded: true },
  { id: "seed_import", title: "幫我匯入 10 月永豐對帳單", updatedAt: "2026-11-08T10:15:00+08:00", messages: [], seeded: true },
  { id: "seed_conc", title: "我的持股會不會太集中？", updatedAt: "2026-11-02T22:30:00+08:00", messages: [], seeded: true },
]

interface Task {
  id: string
  title: string
  next: string
  paused?: boolean
}
const TASKS: Task[] = [
  { id: "task_checkup", title: "每週五盤後持倉健檢", next: "下次 11/13（五）14:30" },
  { id: "task_0050", title: "0050 定期定額提醒", next: "下次 11/19（四）扣款前一天" },
]

export function HistoryList({ compact, onOpen, onReplay }: { compact?: boolean; onOpen?: () => void; onReplay: (text: string) => void }) {
  // 面板裡已有 h2（問 AI／紀錄），清單標題用 h3；整頁時用 h2
  const H = compact ? "h3" : "h2"
  const threads = useAi((s) => s.threads)
  const openThread = useAi((s) => s.openThread)
  const newThread = useAi((s) => s.newThread)
  const deleteThread = useAi((s) => s.deleteThread)
  const [hidden, setHidden] = useState<string[]>([])
  const [tasks, setTasks] = useState<Task[]>(api.kind === "mock" ? TASKS : [])
  const seeded = api.kind === "mock" ? SEEDED.filter((t) => !hidden.includes(t.id) && !threads.some((x) => x.title === t.title)) : []
  const all = [...threads.filter((t) => t.messages.length > 0), ...seeded].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))

  const open = (t: Thread) => {
    if (t.seeded) {
      // 示範紀錄：用目前的資料重新問一次
      newThread()
      setHidden((h) => [...h, t.id])
      onOpen?.()
      onReplay(t.title)
      return
    }
    openThread(t.id)
    onOpen?.()
  }

  const row = cn("ruled-row flex min-h-[60px] items-center gap-2", compact ? "text-base" : "text-lg")

  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => {
          newThread()
          onOpen?.()
        }}
        className={cn("press -mx-2 flex items-center gap-3 rounded-sm px-2 text-left font-medium hover:bg-hov", compact ? "mt-4 h-11 text-base" : "mt-2 h-14 text-xl")}
      >
        <SquarePenIcon aria-hidden className={compact ? "size-5" : "size-6"} />
        發起新對話
      </button>

      <H className={cn("border-b border-rule pb-2 font-bold text-ink-2", compact ? "mt-6 text-sm" : "mt-9 text-base")}>對話</H>
      {all.length === 0 ? (
        <p className="py-4 text-md text-ink-2">還沒有對話。問過的問題和 AI 寫的草稿會留在這裡。</p>
      ) : (
        <ul>
          {all.map((t) => (
            <li key={t.id} className={row}>
              <button type="button" onClick={() => open(t)} className="min-w-0 flex-1 py-3 text-left">
                <span className="line-clamp-2">{t.title}</span>
                {!compact && <span className="num mt-0.5 block text-sm text-ink-2">{formatDateTime(t.updatedAt)}</span>}
              </button>
              <button
                type="button"
                aria-label={`刪除對話「${t.title}」`}
                onClick={() => (t.seeded ? setHidden((h) => [...h, t.id]) : deleteThread(t.id))}
                className="press grid size-11 shrink-0 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink"
              >
                <Trash2Icon aria-hidden className="size-5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <H className={cn("border-b border-rule pb-2 font-bold text-ink-2", compact ? "mt-8 text-sm" : "mt-11 text-base")}>AI 任務</H>
      {tasks.length === 0 ? (
        <p className="py-4 text-md text-ink-2">排定的健檢、提醒與報告會出現在這裡（M4 開放）。</p>
      ) : (
        <ul>
          {tasks.map((t) => (
            <li key={t.id} className={cn(row, "py-2")}>
              <div className="min-w-0 flex-1">
                <p className={cn(t.paused && "text-ink-2")}>{t.title}</p>
                <p className="num text-md text-ink-2">{t.paused ? "已暫停" : t.next}</p>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={<button type="button" aria-label={`${t.title}的選項`} className="press grid size-11 shrink-0 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink" />}
                >
                  <EllipsisIcon aria-hidden className="size-5" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => setTasks((ts) => ts.map((x) => (x.id === t.id ? { ...x, paused: !x.paused } : x)))}>
                    {t.paused ? "恢復" : "暫停"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setTasks((ts) => ts.filter((x) => x.id !== t.id))}>刪除</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </li>
          ))}
        </ul>
      )}
      {api.kind === "mock" && <p className="mt-3 text-xs text-ink-2">AI 任務是示範資料；排程在 M4 開放。</p>}
    </div>
  )
}
