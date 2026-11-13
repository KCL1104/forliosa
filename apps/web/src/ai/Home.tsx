import { Fragment } from "react"
import { cn } from "@/lib/utils"
import { ThreadRows } from "./HistoryList"
import { bleed, bleedPad, quickActions } from "./panel-helpers"
import type { useAiRunner } from "./runner"
import { latestPendingDraftId, openDraft, usePendingCount } from "./store"
import type { AiContext } from "./suggestions"
import { useThreadList } from "./threads"
import type { Suggestion } from "./types"

type Runner = ReturnType<typeof useAiRunner>

/**
 * 面板裡的文字連結（常用動作、回答後的追問）：墨色字、鉛筆灰底線（對紙 3.2:1 以上，看得出可以按），
 * 滑過時底線變墨色
 */
export const textLink =
  "inline-flex min-h-9 items-center text-left text-ink underline decoration-ctl decoration-1 underline-offset-4 transition-[text-decoration-color] hover:decoration-ink pointer-coarse:min-h-11"

const MAX_ROWS = 3
const RECENT = 3

/**
 * 面板還沒有對話時：沒有問候、沒有說明字樣。整塊貼在輸入框正上方（輸入框固定在面板底部，開始對話時不會跳）。
 * - 最多 3 列一行一格的格線列：正在發生的事排前面——待簽名的草稿、扣款日的定期定額或補記——接著是依頁面與資料出現的建議。
 * - 一行依頁面出現的文字連結（帳本：記一筆交易・匯入對帳單・股利入帳）。
 * - 沒有建議也沒有動作的頁面（設定、資料來源、紀錄）：最近 3 段對話（標題＋相對時間），按下接著那段對話。
 *   桌面的紀錄頁不列（`hideRecent`）：那一頁本身就是完整的對話清單，旁邊的面板不重複一次。
 */
export function PanelHome({
  ctx,
  runner,
  suggestions,
  size,
  onShowHistory,
  hideRecent,
}: {
  ctx: AiContext
  runner: Runner
  suggestions: Suggestion[]
  size: "panel" | "screen"
  /** 「全部紀錄」：切到面板的紀錄；紀錄頁本身不需要 */
  onShowHistory?: () => void
  /** 不列「最近的對話」（桌面的紀錄頁：頁面已經列出所有對話） */
  hideRecent?: boolean
}) {
  const actions = quickActions(ctx)
  const pending = usePendingCount()
  // 待簽名那一列不算建議：設定頁有待簽名的草稿時，下面照樣列最近的對話
  const showRecent = !hideRecent && suggestions.length === 0 && actions.length === 0
  const threads = useThreadList({ enabled: showRecent })
  const screen = size === "screen"
  const rows = [
    ...(pending > 0 ? [{ key: "pending", text: `${pending} 筆草稿等你簽名`, run: () => openDraft(latestPendingDraftId()) }] : []),
    ...suggestions.map((s) => ({ key: `${s.kind}-${s.recurring?.planId ?? ""}-${s.recurring?.date ?? ""}`, text: s.text, run: () => runner.ask(s) })),
  ].slice(0, MAX_ROWS)
  const recent = showRecent ? threads.all.slice(0, RECENT) : []

  return (
    <div className="flex flex-col">
      {rows.length > 0 && (
        <ul aria-label="可以這樣問" className={cn("border-t border-rule", bleed[size])}>
          {rows.map((r) => (
            <li key={r.key}>
              <button
                type="button"
                onClick={r.run}
                className={cn(
                  "ruled-row flex w-full items-center py-3 text-left text-ink focus-visible:-outline-offset-2",
                  bleedPad[size],
                  screen ? "min-h-14 text-lg" : "min-h-[52px] text-base",
                )}
              >
                {r.text}
              </button>
            </li>
          ))}
        </ul>
      )}
      {actions.length > 0 && (
        <div role="group" aria-label="常用動作" className={cn("mt-2 flex flex-wrap items-center", screen ? "text-base" : "text-md")}>
          {actions.map((a, i) => (
            <Fragment key={a.key}>
              {i > 0 && (
                <span aria-hidden className="text-ink-2">
                  ・
                </span>
              )}
              <button type="button" onClick={() => runner.action(a.run, { code: a.code })} className={textLink}>
                {a.label}
              </button>
            </Fragment>
          ))}
        </div>
      )}
      {recent.length > 0 && (
        <div className={cn(rows.length > 0 && "mt-4")}>
          <div className={cn("form-head flex items-center justify-between gap-3", bleed[size], bleedPad[size], onShowHistory ? "pb-0.5" : "pb-2")}>
            <span>最近的對話</span>
            {onShowHistory && (
              <button type="button" onClick={onShowHistory} className={cn(textLink, "text-sm")}>
                全部紀錄
              </button>
            )}
          </div>
          <ThreadRows
            threads={recent}
            label="最近的對話"
            size={size}
            bleed
            onPick={(t) => threads.open(t, { onReplay: (text) => void runner.submit(text) })}
          />
        </div>
      )}
    </div>
  )
}
