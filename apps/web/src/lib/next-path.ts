/**
 * 登入後要回去的網址（`next`）：和後端同一個規則（docs/m5-sharing-contract.md）——
 * 必須是站內路徑，不能是 `//evil.com`、`/\evil.com` 這種會被瀏覽器當成別的網站的寫法；不符合就回首頁。
 */
const NEXT_RE = /^\/(?![/\\])[\x21-\x7E]{0,511}$/

function decodeOnce(s: string): string | null {
  try {
    return decodeURIComponent(s)
  } catch {
    return null
  }
}

export function safeNext(next: string | null | undefined): string {
  if (!next) return "/"
  const decoded = decodeOnce(next)
  if (decoded === null) return "/"
  // 登入頁本身不當作回去的地方（避免迴圈）
  if (decoded === "/login" || decoded.startsWith("/login?")) return "/"
  return NEXT_RE.test(next) && NEXT_RE.test(decoded) ? next : "/"
}

/** 不需要登入的頁面（登入、邀請預覽）：不包在外殼與登入閘門裡 */
export function isPublicPath(path: string): boolean {
  return path === "/login" || path.startsWith("/invite/")
}
