import { appNow } from "@/api"
import { ApiError, PERMANENT_UNTIL, type DiscussionAuthor, type ReportReason, type User } from "@/api/types"
import { formatDateShort, todayInTaipei, TZ } from "@/lib/format"

/** 每個公開討論頁底部固定的一行（合約） */
export const DISCLAIMER = "使用者言論，不代表本站立場，也不是投資建議。"

export { ABOUT_FORLIOSA } from "@/lib/about"

/** 公開暱稱的說明（選暱稱的地方、設定頁都用這一句；多久能改一次只有一種說法） */
export const PUBLIC_NAME_HELP = "公開討論只顯示這個名字，看不到你的顯示名稱和頭像。2 到 20 個字，7 天內只能改一次。"

/** 被站方隱藏的內容（主題的內文、回覆） */
export const HIDDEN_NOTE = "這則內容已被站方隱藏。"
/** 作者本人（與站方管理員）仍拿得到原文：說明下面的字只有自己看得到 */
export const HIDDEN_NOTE_WITH_BODY = "這則內容已被站方隱藏，其他人看不到下面的原文。"

export const REASON_LABEL: Record<ReportReason, string> = {
  spam: "廣告或洗版",
  solicitation: "招攬或帶單",
  abuse: "辱罵或騷擾",
  other: "其他",
}

/** 作者的名字：帳號刪除後 `name` 是 null */
export function authorName(author: DiscussionAuthor): string {
  return author.name ?? "已刪除的帳號"
}

/** 台北時間的「13:41」 */
export function clockTime(iso: string): string {
  return new Intl.DateTimeFormat("zh-TW", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso))
}

/** 台北時間的日期（YYYY-MM-DD） */
export function taipeiDay(iso: string): string {
  return todayInTaipei(new Date(iso))
}

/** 「11/12（四）13:02」（台北時間） */
export function postedAt(iso: string): string {
  return `${formatDateShort(taipeiDay(iso))}${clockTime(iso)}`
}

/** 「8 秒後」「約 3 分鐘後」「約 2 小時後」：頻率限制什麼時候解除 */
export function retryText(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.ceil(seconds))} 秒後`
  if (seconds < 3600) return `約 ${Math.ceil(seconds / 60)} 分鐘後`
  return `約 ${Math.ceil(seconds / 3600)} 小時後`
}

/**
 * 公開發言被站方暫停時的一句話（`until` 是 UTC 的 ISO 時間；永久是 `PERMANENT_UNTIL`）。
 * 站方有寫原因就一起說（`reason`，只有本人看得到）：只知道被停、不知道為什麼，下次還是會犯同樣的事。
 */
export function suspendedText(until: string | null | undefined, reason?: string | null): string {
  const why = reason?.trim().replace(/[。.!！\s]+$/, "")
  const tail = `${why ? `原因：${why}。` : ""}群組裡的發言不受影響。`
  if (!until) return `你的公開發言已被站方暫停。${tail}`
  if (until === PERMANENT_UNTIL || until.startsWith("9999")) return `你的公開發言已被站方永久暫停。${tail}`
  return `你的公開發言已被站方暫停到 ${postedAt(until)}。${tail}`
}

/** 公開發言現在是不是被站方暫停：回傳到什麼時候（`public_posting_suspended_until` 還沒到），沒有停權是 null */
export function suspendedUntil(user: User | null | undefined): string | null {
  const until = user?.public_posting_suspended_until
  return until && Date.parse(until) > appNow().getTime() ? until : null
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null)

/**
 * 發主題或回覆失敗時就地顯示的一句話：說哪裡不對、什麼時候可以再試（不是只有「失敗」）。
 * 內容留在輸入框裡，所以每一句都不需要再說「請重新輸入」。
 */
export function postErrorText(err: unknown, what: "主題" | "回覆"): string {
  if (!(err instanceof ApiError)) return `${what}沒有送出，內容還在。請檢查網路後再試一次。`
  switch (err.code) {
    case "rate_limited": {
      const seconds = num(err.extra.retry_after_seconds)
      return seconds === null ? "發言太頻繁，請稍後再送出。內容還在。" : `發言太頻繁，${retryText(seconds)}可以再送出。內容還在。`
    }
    case "posting_suspended":
      return suspendedText(str(err.extra.until), str(err.extra.reason))
    case "public_name_required":
      return "發公開內容前要先選一個公開暱稱。"
    case "topic_hidden":
      return "這個主題已被站方隱藏，不能再回覆。"
    case "unknown_symbol":
      return `標記的股票裡有找不到的代號（${err.message.replace(/^找不到商品：/, "")}），請移除後再送出。`
  }
  if (err.status === 401) return "登入已過期，請重新登入後再送出。"
  if (err.status === 404) return what === "回覆" ? "這個主題已經看不到了，回覆沒有送出。" : "找不到要發到的群組，你可能已經不在這個群組裡。"
  if (err.status === 422) return err.message
  return `${what}沒有送出，內容還在。${err.message}`
}

/** 設定或修改公開暱稱失敗時就地顯示的一句話 */
export function publicNameErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "暱稱沒有存起來，請檢查網路後再試一次。"
  if (err.code === "public_name_taken") return "這個暱稱已經有人用了，換一個試試。"
  if (err.code === "public_name_cooldown") {
    const days = num(err.extra.retry_after_days)
    return days === null ? "公開暱稱 7 天內只能改一次，請過幾天再改。" : `公開暱稱 7 天內只能改一次，${days} 天後可以再改。`
  }
  if (err.status === 401) return "登入已過期，請重新登入後再試一次。"
  return err.message
}

/** 檢舉失敗時就地顯示的一句話 */
export function reportErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "檢舉沒有送出，請檢查網路後再試一次。"
  if (err.code === "rate_limited") {
    const seconds = num(err.extra.retry_after_seconds)
    return seconds === null ? "檢舉太頻繁，請稍後再送出。" : `檢舉太頻繁，${retryText(seconds)}可以再送出。`
  }
  if (err.status === 404) return "這則內容已經看不到了。"
  if (err.status === 401) return "登入已過期，請重新登入後再試一次。"
  return err.message
}
