/**
 * 這個分頁的 id（即時更新，docs/api-contract.md「即時更新（2026-11-17）」）：寫入的請求帶上 `X-Forliosa-Tab`，
 * 伺服器把它放在這次變更的事件裡（只給同一個人自己的連線，欄位 `o`）。收到 `o` 是自己的事件就略過：
 * 這個分頁送出變更時，mutation 已經讓同一組資料重新讀了。
 *
 * 標頭等即時更新的串流第一次連上之後才開始帶：還沒有 `/events` 的舊版後端，CORS 不允許這個標頭，
 * 先帶上的話每個寫入都會在預檢被擋（前端比後端先部署的那幾分鐘）。沒帶標頭只是少了略過，同一組資料多讀一次。
 */
export const TAB_HEADER = "X-Forliosa-Tab"

const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

function makeTabId(): string {
  const bytes = new Uint8Array(15)
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") crypto.getRandomValues(bytes)
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  // 伺服器只收 [A-Za-z0-9_-]{8,32}
  return `t${Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join("")}`
}

export const tabId: string = makeTabId()

let headerOn = false

/** 串流連上了（伺服器有即時更新，也允許這個標頭）：之後的寫入帶上分頁 id */
export function enableTabHeader(): void {
  headerOn = true
}

/** 測試用 */
export function resetTabHeader(): void {
  headerOn = false
}

/** 寫入（不是 GET）的請求加上分頁 id */
export function withTab(method: string, headers: Record<string, string>): Record<string, string> {
  if (!headerOn || method.toUpperCase() === "GET" || method.toUpperCase() === "HEAD") return headers
  return { ...headers, [TAB_HEADER]: tabId }
}
