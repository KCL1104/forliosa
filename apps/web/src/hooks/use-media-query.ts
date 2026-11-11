import { useCallback, useSyncExternalStore } from "react"

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      const mq = window.matchMedia(query)
      mq.addEventListener("change", cb)
      return () => mq.removeEventListener("change", cb)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false)
}

/** 桌面版面（≥ 1024px）：左側欄＋對話框；以下為手機／平板：底部分頁＋抽屜 */
export const useIsDesktop = () => useMediaQuery("(min-width: 1024px)")
