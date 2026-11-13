import type { OAuthErrorCode } from "@/api/types"

/**
 * 登入（Google、Discord）回來失敗時的說明（`/login?error=<code>`）。
 * 後端回來的代碼不分是哪一家，所以句子也不寫是哪一家。
 */
export const OAUTH_ERRORS: Record<OAuthErrorCode, string> = {
  oauth_disabled: "這個登入方式沒有開放。",
  oauth_denied: "你按了取消，所以沒有登入。",
  oauth_state: "登入逾時，或是從別的分頁開始的。請再按一次登入。",
  oauth_email_unverified: "這個帳號的 Email 還沒有驗證。請先到 Google 或 Discord 驗證 Email，再回來登入。",
  oauth_email_conflict: "這個 Email 已經連結到另一個登入帳號，請用原本那個帳號登入。",
  oauth_failed: "登入沒有完成，請再試一次。",
}

/** 沒有 error 參數時為 null；不認得的代碼當作 oauth_failed */
export function oauthErrorText(code: string | undefined): string | null {
  if (!code) return null
  return OAUTH_ERRORS[code as OAuthErrorCode] ?? OAUTH_ERRORS.oauth_failed
}
