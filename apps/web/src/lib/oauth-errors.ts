import type { OAuthErrorCode } from "@/api/types"

/** Discord callback 失敗時的說明（`/login?error=<code>`） */
export const OAUTH_ERRORS: Record<OAuthErrorCode, string> = {
  oauth_disabled: "Discord 登入目前沒有開放。",
  oauth_denied: "你在 Discord 按了取消，所以沒有登入。",
  oauth_state: "登入逾時，或是從別的分頁開始的。請再按一次「用 Discord 登入」。",
  oauth_email_unverified: "你的 Discord 帳號 Email 還沒有驗證。請先到 Discord 驗證 Email，再回來登入。",
  oauth_email_conflict: "這個 Email 已經連結到另一個 Discord 帳號，請改用原本那個 Discord 帳號登入。",
  oauth_failed: "Discord 登入沒有完成，請再試一次。",
}

/** 沒有 error 參數時為 null；不認得的代碼當作 oauth_failed */
export function oauthErrorText(code: string | undefined): string | null {
  if (!code) return null
  return OAUTH_ERRORS[code as OAuthErrorCode] ?? OAUTH_ERRORS.oauth_failed
}
