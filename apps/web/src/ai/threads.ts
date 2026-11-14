import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api } from "@/api"
import { aiRemote } from "./remote"
import { aiKeys, useRemoteThreadActions, useRemoteThreads } from "./remote-hooks"
import { useAi } from "./store"
import type { Thread } from "./types"

/**
 * 過去的對話（紀錄頁、面板的紀錄、沒有建議的頁面上「最近的對話」共用同一份）。
 * 連真實後端時來自 `/ai/threads`（跨裝置）；mock 模式存在這台瀏覽器，另有幾則示範紀錄（打開時用目前的資料重新問）。
 */
const SEEDED: Thread[] = [
  { id: "seed_why", title: "為什麼台積電今天漲 4.83%？", updatedAt: "2026-11-12T13:41:00+08:00", messages: [], seeded: true },
  { id: "seed_878", title: "00878 下次除息能領多少？", updatedAt: "2026-11-11T21:08:00+08:00", messages: [], seeded: true },
  { id: "seed_import", title: "補記 10 月的 0050 定期定額", updatedAt: "2026-11-08T10:15:00+08:00", messages: [], seeded: true },
  { id: "seed_conc", title: "我的持股會不會太集中？", updatedAt: "2026-11-02T22:30:00+08:00", messages: [], seeded: true },
]

/**
 * 設定頁「刪除全部 AI 對話」：伺服器上的全部刪掉（`DELETE /ai/threads`；草稿保留，已簽名草稿記下的交易留在帳本），
 * 再清掉這台瀏覽器上的對話與草稿（和登出一樣），mock 的示範紀錄也藏起來。不能復原，所以沒有「復原」。
 */
export function useDeleteAllThreads() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.deleteAiThreads(),
    onSuccess: () => {
      useAi.getState().clearConversations(api.kind === "mock" ? SEEDED.map((t) => t.id) : [])
      qc.setQueryData(aiKeys.threads, { items: [], next_cursor: null })
      qc.removeQueries({ queryKey: ["ai", "thread"] })
      void qc.invalidateQueries({ queryKey: aiKeys.threads })
    },
  })
}

export function useThreadList({ enabled = true }: { enabled?: boolean } = {}) {
  const threads = useAi((s) => s.threads)
  const hidden = useAi((s) => s.hiddenThreadIds)
  const remote = useRemoteThreads(enabled)
  const remoteActions = useRemoteThreadActions()
  const seeded = api.kind === "mock" ? SEEDED.filter((t) => !hidden.includes(t.id) && !threads.some((x) => x.title === t.title)) : []
  const all: Thread[] = aiRemote
    ? (remote.data?.items ?? [])
        .filter((t) => !hidden.includes(t.id))
        .map((t): Thread => ({ id: t.id, remoteId: t.id, title: t.title, updatedAt: t.updated_at, messages: [] }))
    : [...threads.filter((t) => t.messages.length > 0), ...seeded].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))

  /** 接著那段對話：本機的直接打開；後端的先打開再載入；示範紀錄用目前的資料重新問一次 */
  const open = (t: Thread, opts: { onOpen?: () => void; onReplay: (text: string) => void }) => {
    const s = useAi.getState()
    if (t.remoteId) {
      opts.onOpen?.()
      remoteActions.open(t.remoteId).catch((err: unknown) => toast.error("對話打不開", { description: err instanceof Error ? err.message : "請再試一次" }))
      return
    }
    if (t.seeded) {
      s.newThread()
      s.setThreadHidden(t.id, true)
      opts.onOpen?.()
      opts.onReplay(t.title)
      return
    }
    s.openThread(t.id)
    opts.onOpen?.()
  }

  /**
   * 刪除＋「復原」（和交易一樣是 Sonner 通知）：本機的對話馬上刪、復原時放回去；
   * 後端的對話先藏起來，通知關掉（逾時或滑掉）才真的刪，復原就只是再顯示。
   */
  const remove = (t: Thread) => {
    const s = useAi.getState()
    if (t.remoteId) {
      const id = t.remoteId
      let settled = false
      s.setThreadHidden(id, true)
      const commit = () => {
        if (settled) return
        settled = true
        remoteActions.remove(id).then(
          () => useAi.getState().setThreadHidden(id, false),
          (err: unknown) => {
            useAi.getState().setThreadHidden(id, false)
            toast.error("沒有刪除", { description: err instanceof Error ? err.message : "請再試一次" })
          },
        )
      }
      toast("已刪除對話", {
        description: t.title,
        action: {
          label: "復原",
          onClick: () => {
            settled = true
            useAi.getState().setThreadHidden(id, false)
          },
        },
        onAutoClose: commit,
        onDismiss: commit,
      })
      return
    }
    if (t.seeded) {
      s.setThreadHidden(t.id, true)
      toast("已刪除對話", { description: t.title, action: { label: "復原", onClick: () => useAi.getState().setThreadHidden(t.id, false) } })
      return
    }
    s.deleteThread(t.id)
    toast("已刪除對話", { description: t.title, action: { label: "復原", onClick: () => useAi.getState().restoreThread(t) } })
  }

  return {
    all,
    loading: aiRemote && remote.isPending,
    error: aiRemote && remote.isError,
    retry: () => void remote.refetch(),
    open,
    remove,
  }
}
