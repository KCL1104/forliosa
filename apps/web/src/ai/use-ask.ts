import { toast } from "sonner"
import { viewAsId } from "@/api/view-as"
import { useQuietRoute } from "@/app/nav"
import { useIsDesktop } from "@/hooks/use-media-query"
import { useAiContext } from "./context"
import { useAiRunner, type AiAction } from "./runner"
import { openDraft, useAi } from "./store"

/**
 * 查看別人的資產時不用 AI（AI 面板沒有掛載，AI 也不讀被查看者的資料）。畫面上的 AI 動作都已隱藏，
 * 這裡是最後一道：萬一漏了，不在背景替查看者建立對話，只說明一句。
 */
function aiBlocked(): boolean {
  if (!viewAsId()) return false
  toast("查看別人的資產時不能使用 AI，結束查看後再問")
  return true
}

/**
 * 從頁面把事情交給 AI：桌面確保右側面板打開、手機打開全螢幕的「問 AI」，再執行動作或送出一句話。
 */
export function useAskAi() {
  const ctx = useAiContext()
  const runner = useAiRunner(ctx)
  const isDesktop = useIsDesktop()
  // 面板的開合在安靜的頁面（群組、設定、紀錄…）另外記：從這些頁面交給 AI 時，打開的是那一邊
  const quiet = useQuietRoute()
  const reveal = () => {
    const s = useAi.getState()
    if (isDesktop) s.setPanelOpen(true, quiet)
    else s.setMobileOpen(true)
  }
  return {
    action: (kind: AiAction, opts?: { code?: string }) => {
      if (aiBlocked()) return
      if (kind !== "form") reveal()
      runner.action(kind, opts)
    },
    submit: (text: string) => {
      if (aiBlocked()) return
      reveal()
      void runner.submit(text)
    },
    /** 打開面板並捲到某份草稿 */
    showDraft: (id: string | null) => {
      reveal()
      openDraft(id)
    },
    reveal,
  }
}
