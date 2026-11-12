import { useIsDesktop } from "@/hooks/use-media-query"
import { useAiContext } from "./context"
import { useAiRunner, type AiAction } from "./runner"
import { useAi } from "./store"

/**
 * 從頁面把事情交給 AI：桌面確保右側面板打開、手機打開全螢幕的「問 AI」，再執行動作或送出一句話。
 */
export function useAskAi() {
  const ctx = useAiContext()
  const runner = useAiRunner(ctx)
  const isDesktop = useIsDesktop()
  const reveal = () => {
    const s = useAi.getState()
    if (isDesktop) s.setPanelOpen(true)
    else s.setMobileOpen(true)
  }
  return {
    action: (kind: AiAction, opts?: { code?: string }) => {
      if (kind !== "form") reveal()
      runner.action(kind, opts)
    },
    submit: (text: string) => {
      reveal()
      void runner.submit(text)
    },
    /** 打開面板並捲到某份草稿 */
    showDraft: (id: string | null) => {
      reveal()
      const s = useAi.getState()
      const draft = id ? s.drafts[id] : undefined
      if (draft) {
        const thread = s.threads.find((t) => t.messages.some((m) => m.draftId === id || m.draftIds?.includes(id!)))
        if (thread) s.openThread(thread.id)
      }
      s.focusDraft(id)
      window.setTimeout(() => useAi.getState().focusDraft(null), 2400)
    },
    reveal,
  }
}
