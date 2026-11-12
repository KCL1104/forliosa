import { Fragment } from "react"
import { cn } from "@/lib/utils"
import { quickActions } from "./panel-helpers"
import type { useAiRunner } from "./runner"
import { latestPendingDraftId, openDraft, usePendingCount } from "./store"
import type { AiContext } from "./suggestions"
import type { Suggestion } from "./types"

type Runner = ReturnType<typeof useAiRunner>

/**
 * 面板裡的文字連結（常用動作、回答後的追問）：墨色字、鉛筆灰底線（對紙 3.2:1 以上，看得出可以按），
 * 滑過時底線變墨色
 */
export const textLink =
  "inline-flex min-h-9 items-center text-left text-ink underline decoration-ctl decoration-1 underline-offset-4 transition-[text-decoration-color] hover:decoration-ink pointer-coarse:min-h-11"

const MAX_ROWS = 3

/**
 * 面板還沒有對話時：沒有問候、沒有說明字樣。最多 3 列一行一格的格線列，左右延伸到面板邊緣
 * （hover 底色滿版、文字對齊內文）：正在發生的事排前面——待簽名的草稿、扣款日的定期定額或補記——
 * 接著是依頁面與資料出現的建議。下面一行依頁面出現的文字連結（帳本：記一筆交易・匯入對帳單・股利入帳）。
 * 輸入框緊接在下面（由面板排）。
 */
export function PanelHome({ ctx, runner, suggestions, size }: { ctx: AiContext; runner: Runner; suggestions: Suggestion[]; size: "panel" | "screen" }) {
  const actions = quickActions(ctx)
  const pending = usePendingCount()
  const screen = size === "screen"
  const rows = [
    ...(pending > 0 ? [{ key: "pending", text: `${pending} 筆草稿等你簽名`, run: () => openDraft(latestPendingDraftId()) }] : []),
    ...suggestions.map((s) => ({ key: `${s.kind}-${s.recurring?.planId ?? ""}-${s.recurring?.date ?? ""}`, text: s.text, run: () => runner.ask(s) })),
  ].slice(0, MAX_ROWS)
  return (
    <div className="flex flex-col">
      {rows.length > 0 && (
        <ul aria-label="可以這樣問" className={screen ? "-mx-5" : "-mx-7 xl:-ml-8"}>
          {rows.map((r) => (
            <li key={r.key}>
              <button
                type="button"
                onClick={r.run}
                className={cn(
                  "ruled-row flex w-full items-center py-3 text-left text-ink focus-visible:-outline-offset-2",
                  screen ? "min-h-14 px-5 text-lg" : "min-h-[52px] px-7 text-base xl:pl-8",
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
    </div>
  )
}
