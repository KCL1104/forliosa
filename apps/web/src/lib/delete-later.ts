import { toast } from "sonner"
import { create } from "zustand"

/**
 * 可以復原的刪除（討論的回覆與主題；產品負責人 2026-11-13）：
 * 按下刪除 → 畫面上立刻拿掉 → 通知「已刪除…」附「復原」（和交易、對話紀錄同一種通知）→ 通知結束（逾時或滑掉）才真的送出刪除。
 * - 「復原」：什麼都沒送出，東西回到原位。
 * - 頁面在通知結束前被關掉或藏起來（切到別的分頁、鎖螢幕）：當下就送出（`keepalive`，頁面卸載後照樣送完），通知一起收掉。
 * - 送出失敗：東西放回原位，通知說沒有刪除。伺服器回 404（別的地方已經刪了）當成已經刪除。
 * 畫面用 `usePendingDeletes` 知道哪些東西正在等：清單與主題頁把它們濾掉。
 */

/** 通知停留多久（毫秒）：這段時間內可以復原 */
export const UNDO_MS = 6000

/** 畫面上先拿掉、還沒真的刪除的東西（鍵是合約的 target：`topic:<id>`、`reply:<id>`） */
export const usePendingDeletes = create<{ keys: ReadonlySet<string> }>(() => ({ keys: new Set<string>() }))

const hide = (key: string) => usePendingDeletes.setState((s) => ({ keys: new Set(s.keys).add(key) }))
const show = (key: string) =>
  usePendingDeletes.setState((s) => {
    if (!s.keys.has(key)) return s
    const keys = new Set(s.keys)
    keys.delete(key)
    return { keys }
  })

/** 還在等通知結束的刪除：頁面要離開時一次送出 */
const waiting = new Map<string, (leaving: boolean) => void>()

/** 頁面要關掉或藏起來了：還在等的刪除現在就送（`keepalive`） */
function flush() {
  for (const commit of [...waiting.values()]) commit(true)
}
if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flush)
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush()
  })
}

export interface DeleteLater {
  /** 合約的 target（`topic:<id>`、`reply:<id>`）：畫面用它把這一則先拿掉 */
  key: string
  /** 通知的標題：「已刪除回覆」「已刪除主題」 */
  title: string
  description?: string
  /** 真的送出刪除。`keepalive`：頁面正在離開 */
  send: (opts: { keepalive: boolean }) => Promise<unknown>
  /** 刪除成功之後（重新讀取清單）；它結束之前畫面上繼續濾掉這一則，不會閃回來 */
  onDeleted?: () => unknown
  /** 刪除失敗時通知的標題（東西已經放回原位） */
  failed: string
}

const gone = (err: unknown) => typeof err === "object" && err !== null && (err as { status?: unknown }).status === 404

export function deleteLater({ key, title, description, send, onDeleted, failed }: DeleteLater): void {
  // 同一則已經在等了（連按兩次）：不重複
  if (waiting.has(key)) return
  let settled = false
  hide(key)

  const deleted = async () => {
    try {
      await onDeleted?.()
      show(key)
    } catch {
      // 清單沒有重新讀成功：這一則繼續濾掉（它已經刪了，舊的快取裡還有）
    }
  }
  const commit = (leaving: boolean) => {
    if (settled) return
    settled = true
    waiting.delete(key)
    // 頁面要離開了，已經不能復原：通知收掉
    if (leaving) toast.dismiss(toastId)
    send({ keepalive: leaving }).then(deleted, (err: unknown) => {
      if (gone(err)) return void deleted()
      show(key)
      toast.error(failed, { description: err instanceof Error && err.message ? err.message : "請檢查網路後再試一次。" })
    })
  }
  waiting.set(key, commit)

  // `commit` 只會在這之後被呼叫（通知結束、頁面離開），那時 `toastId` 已經有值
  const toastId = toast(title, {
    description,
    duration: UNDO_MS,
    action: {
      label: "復原",
      onClick: () => {
        if (settled) return
        settled = true
        waiting.delete(key)
        show(key)
      },
    },
    onAutoClose: () => commit(false),
    onDismiss: () => commit(false),
  })
}
