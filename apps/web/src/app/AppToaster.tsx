import { Toaster } from "@/components/ui/sonner"
import { useIsDesktop } from "@/hooks/use-media-query"

/**
 * 通知的位置。桌面：上方置中。手機：底部列的上方——附「復原」的通知要在拇指按得到的地方，
 * 也不會蓋住對話框的標題（放在最上面時，離剛才按的按鈕一個螢幕遠，還蓋住對話框）。
 * 88px：高過底部列（60px）與「問 AI」的輸入框。
 */
export function AppToaster() {
  const desktop = useIsDesktop()
  const bottom = { bottom: "calc(env(safe-area-inset-bottom, 0px) + 88px)" }
  // 同一個 Toaster，只換位置（視窗跨過 1024px 時，畫面上的通知不會不見）
  return (
    <Toaster
      position={desktop ? "top-center" : "bottom-center"}
      offset={desktop ? { top: "calc(env(safe-area-inset-top, 0px) + 12px)" } : bottom}
      mobileOffset={desktop ? undefined : bottom}
    />
  )
}
