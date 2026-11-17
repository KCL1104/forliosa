import { useMutation } from "@tanstack/react-query"
import { api, appToday } from "@/api"
import { ApiError } from "@/api/types"
import { retryText } from "@/pages/discussions/labels"

/** 把匯出的資料存成檔案（`forliosa-export-YYYYMMDD.json`）：在瀏覽器裡做一個暫時的下載連結按下去 */
function saveAsFile(data: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }))
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 下載開始之後再釋放（馬上釋放的話有些瀏覽器會存到空檔）
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export function exportErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "沒有匯出成功，請檢查網路後再試一次。"
  if (err.code === "rate_limited") {
    const seconds = typeof err.extra.retry_after_seconds === "number" ? err.extra.retry_after_seconds : null
    return seconds === null ? "匯出太頻繁，請稍後再試。" : `匯出太頻繁，${retryText(seconds)}可以再試。`
  }
  if (err.status === 401) return "登入已過期，請重新登入後再試一次。"
  return err.message
}

/**
 * 匯出我的資料（`GET /me/export`）並下載成檔案：設定「帳號與資料」的「匯出」和清除所有持倉的「先匯出資料」用同一個。
 * `onSaved`：檔案交給瀏覽器之後（設定頁通知「已下載匯出檔」；確認框裡就地寫，不讓通知蓋在對話框上）
 */
export function useExportMe(onSaved?: () => void) {
  return useMutation({
    mutationFn: () => api.exportMe(),
    onSuccess: (data) => {
      saveAsFile(data, `forliosa-export-${appToday().replaceAll("-", "")}.json`)
      onSaved?.()
    },
  })
}
