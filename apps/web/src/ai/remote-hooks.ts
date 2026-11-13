import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useRouterState } from "@tanstack/react-router"
import { appToday } from "@/api"
import { aiApi, aiRemote, threadFromServer } from "./remote"
import { useRecurringOffers } from "./recurring-offer"
import { useAi } from "./store"
import { suggestionsFor, type AiContext } from "./suggestions"
import type { Suggestion, SuggestionKind } from "./types"

export const aiKeys = {
  suggestions: (route: string, symbol: string | null) => ["ai", "suggestions", route, symbol] as const,
  usage: ["ai", "usage"] as const,
  threads: ["ai", "threads"] as const,
}

/** 建議問題：連真實後端時用 `/ai/suggestions`（規則版，不呼叫模型），載入前與 mock 模式用本機規則 */
export function useAiSuggestions(ctx: AiContext): Suggestion[] {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const symbol = ctx.route === "stock" ? ctx.stock.symbol : null
  const q = useQuery({
    enabled: aiRemote,
    queryKey: aiKeys.suggestions(pathname, symbol),
    queryFn: () => aiApi.getSuggestions(pathname, symbol),
    staleTime: 60_000,
  })
  // 扣款日當天的定期定額草稿排在最前面（帳本，或該檔的個股頁）
  const offers = useRecurringOffers().filter((o) => ctx.route === "ledger" || (ctx.route === "stock" && o.symbol === ctx.stock.symbol))
  const local = suggestionsFor(ctx, appToday())
  const base: Suggestion[] =
    !aiRemote || !q.data
      ? local
      : q.data.questions.map((x) => ({
          kind: x.kind as SuggestionKind,
          text: x.text,
          symbol: x.symbol ?? undefined,
        }))
  return [...offers, ...base].slice(0, 3)
}

/** 今天的提問數與本月用量（mock 模式為 undefined） */
export function useAiUsage() {
  return useQuery({ enabled: aiRemote, queryKey: aiKeys.usage, queryFn: () => aiApi.getUsage(), staleTime: 30_000 })
}

/** 輸入框下方的一行：剩不多時提醒，用完時說明 */
export function usageNote(u: { messages_remaining: number | null; tokens_remaining: number | null; available?: boolean } | undefined): string | null {
  if (!u) return null
  if (u.available === false) return "AI 暫時無法使用；記帳指令仍會寫成草稿。"
  if (u.messages_remaining === 0 || u.tokens_remaining === 0) return "今天的提問額度用完了，明天再繼續。"
  if (u.messages_remaining !== null && u.messages_remaining <= 5) return `今天還可以問 ${u.messages_remaining} 題。`
  return null
}

/** 後端的對話清單；`enabled: false` 時不發請求（面板首頁只在要列最近的對話時才需要） */
export function useRemoteThreads(enabled = true) {
  return useQuery({ enabled: aiRemote && enabled, queryKey: aiKeys.threads, queryFn: () => aiApi.listThreads(), staleTime: 15_000 })
}

/** 打開、刪除後端的對話 */
export function useRemoteThreadActions() {
  const qc = useQueryClient()
  return {
    async open(remoteId: string) {
      const s = useAi.getState()
      const local = s.threads.find((t) => t.remoteId === remoteId)
      if (local) s.openThread(local.id)
      const detail = await qc.fetchQuery({ queryKey: ["ai", "thread", remoteId], queryFn: () => aiApi.getThread(remoteId), staleTime: 0 })
      const streaming = useAi.getState().threads.find((t) => t.remoteId === remoteId)?.messages.some((m) => m.streaming)
      if (streaming) return // 正在回答中：不要用伺服器的舊版本蓋掉
      const { thread, drafts } = threadFromServer(detail)
      useAi.getState().loadThread(local ? { ...thread, id: local.id } : thread, drafts)
    },
    async remove(remoteId: string) {
      await aiApi.deleteThread(remoteId)
      useAi.getState().removeRemote(remoteId)
      void qc.invalidateQueries({ queryKey: aiKeys.threads })
    },
  }
}
