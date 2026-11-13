import { useSyncExternalStore } from "react"

function subscribe(onChange: () => void) {
  const vv = window.visualViewport
  if (!vv) return () => {}
  vv.addEventListener("resize", onChange)
  vv.addEventListener("scroll", onChange)
  return () => {
    vv.removeEventListener("resize", onChange)
    vv.removeEventListener("scroll", onChange)
  }
}
const snapshot = () => {
  const vv = window.visualViewport
  return vv ? `${Math.round(vv.height)},${Math.round(vv.offsetTop)}` : ""
}

/**
 * 看得到的那一塊畫面（visual viewport）的高度與位置。螢幕鍵盤打開時，iOS Safari 不縮版面、只縮這一塊（還可能往下捲）：
 * 滿版的面板照這個高度與位置擺，內容才不會被鍵盤蓋住。瀏覽器沒有這個 API 時回傳 null（用 100dvh）。
 */
export function useVisualViewport(): { height: number; top: number } | null {
  const value = useSyncExternalStore(subscribe, snapshot, () => "")
  if (!value) return null
  const [height, top] = value.split(",").map(Number)
  return { height: height!, top: top! }
}
