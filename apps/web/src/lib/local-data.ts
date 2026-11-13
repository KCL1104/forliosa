import { useAi } from "@/ai/store"
import { useViewAs } from "@/api/view-as"

/**
 * 這台瀏覽器上屬於「登入的那個人」的東西：AI 對話與草稿（localStorage）、還沒送出的回覆與新主題（sessionStorage）、
 * 正在查看誰的資產。登出、刪除帳號時清掉——下一個在這台電腦登入的人不會看到。
 * 顯示偏好（主題、漲跌顏色）是這台裝置的設定，不清。
 */
export function clearLocalUserData(): void {
  useAi.getState().forget()
  useViewAs.getState().set(null)
  try {
    const s = window.sessionStorage
    for (const key of Object.keys(s)) if (key.startsWith("forliosa:draft:")) s.removeItem(key)
  } catch {
    // sessionStorage 不可用：沒有東西可清
  }
}

/** 登入後：這台瀏覽器的 AI 對話如果是別人留下的就清掉（同一個人則原樣保留） */
export function claimLocalUserData(userId: string): void {
  useAi.getState().claim(userId)
}
