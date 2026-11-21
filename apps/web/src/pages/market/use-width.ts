import { useLayoutEffect, useRef, useState } from "react"

/**
 * 一個元素的內容寬度（px）：類股要分幾欄由它決定（每一欄是一張 `CentreBars`，欄數要在 JS 裡知道才能切清單）。
 * 掛上時先量一次（`useLayoutEffect`，畫出來之前就換好，不會先閃一下一欄）；之後跟著 `ResizeObserver` 換。
 * 量不到（測試環境）時是 0。
 */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(Math.floor(el.getBoundingClientRect().width))
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.floor(entry.contentRect.width))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}
