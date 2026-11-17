import { create } from "zustand"

/**
 * 即時更新的狀態（一個分頁一份）：
 * - `off`：沒有即時更新（mock 模式、沒登入）——頁面照原本的間隔重新讀
 * - `connecting`：連線中；`open`：連上了；`down`：斷了，等一下自動重連（這段時間 controller 每 30 秒重新讀）
 * - `paused`：分頁在背景太久而先關掉，或被同一個人更新的分頁取代；回到前景時再連
 * 畫面上不顯示（不加「即時」標示）；只用來決定各個查詢還要不要自己定時重新讀。
 */
export type RealtimeStatus = "off" | "connecting" | "open" | "down" | "paused"

interface RealtimeState {
  status: RealtimeStatus
  /** 最近一次收到 `market.closes` 的時間（毫秒）：`useCloseRefresh` 不再重複重新讀 */
  closesAt: number
}

export const useRealtime = create<RealtimeState>()(() => ({ status: "off", closesAt: 0 }))

export function setRealtimeStatus(status: RealtimeStatus): void {
  if (useRealtime.getState().status !== status) useRealtime.setState({ status })
}

export function markClosesEvent(at = Date.now()): void {
  useRealtime.setState({ closesAt: at })
}

/** 串流連著嗎（React hook）：連著時，伺服器有變化會通知，查詢不必自己定時問 */
export function useRealtimeOpen(): boolean {
  return useRealtime((s) => s.status === "open")
}

/**
 * 定時重新讀的間隔：串流連著時用 `whenOpen`（預設不定時讀），斷著或沒有即時更新時用原本的 `ms`。
 * 用法：`refetchInterval: useLiveInterval(60_000)`。
 */
export function useLiveInterval(ms: number, whenOpen: number | false = false): number | false {
  return useRealtimeOpen() ? whenOpen : ms
}
