import { useState } from "react"
import { useQuietRoute } from "@/app/nav"
import { useAi, usePanelBusy } from "./store"

/**
 * 桌面 AI 面板現在開不開（`AppShell` 用它決定面板與主欄的版面）：
 * - 帳本、個股頁：記住的開合（`panelOpen`，預設開）。
 * - AI 沒什麼可說的頁面（app/nav.ts 的 `QUIET_ROUTES`）：預設 56px 的窄欄；使用者在這類頁面自己打開後（`quietPanelOpen`），
 *   換到別的安靜頁面也開著。
 * - 換到另一種頁面的那一刻，面板開著而且裡面有事（開著一段對話、草稿等簽名）：不因為換頁收起來（`held`），
 *   直到使用者自己收合；下一次換到另一種頁面時重新判斷。重新整理後直接落在安靜的頁面、而且有草稿等簽名時也開著。
 * 換頁的判斷寫在 render 裡（不是 effect）：面板不會先收成窄欄、下一個畫面再打開，裡面的對話與輸入到一半的字也不會被卸載。
 */
export function useAiPanelOpen(): { open: boolean; setOpen: (open: boolean) => void } {
  const quiet = useQuietRoute()
  const panelOpen = useAi((s) => s.panelOpen)
  const quietPanelOpen = useAi((s) => s.quietPanelOpen)
  const busy = usePanelBusy()
  const [at, setAt] = useState(() => ({ quiet, held: quiet && busy }))
  let held = at.held
  if (at.quiet !== quiet) {
    const wasOpen = (at.quiet ? quietPanelOpen : panelOpen) || at.held
    held = wasOpen && busy
    setAt({ quiet, held })
  }
  return {
    open: (quiet ? quietPanelOpen : panelOpen) || held,
    setOpen: (open) => {
      if (!open) setAt({ quiet, held: false })
      useAi.getState().setPanelOpen(open, quiet)
    },
  }
}
