/**
 * 還沒送出的字（主題頁的回覆框、開新主題的表單）：邊打邊存在 sessionStorage（這個分頁），離開再回來時還原，
 * 送出成功後清掉。產品負責人 2026-11-13：不做編輯，但打到一半的字不能因為按了「改」「取消」或上一頁就不見。
 * - 鍵含使用者 id：同一個分頁換一個人登入，不會看到上一個人的草稿。
 * - 一個主題一份回覆草稿（互不相干）；開新主題只有一份。
 * - 存不了（隱私模式、容量滿、sessionStorage 被關掉）就當作沒有草稿，不影響輸入。
 */
const PREFIX = "forliosa:draft:"

export const replyDraftKey = (userId: string, topicId: string) => `${PREFIX}${userId}:reply:${topicId}`
export const newTopicDraftKey = (userId: string) => `${PREFIX}${userId}:new-topic`

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage
  } catch {
    return null
  }
}

/** 讀一份草稿；沒有、讀不了、或形狀不對（`parse` 回 null）都是 null */
export function readDraft<T>(key: string, parse: (raw: unknown) => T | null): T | null {
  try {
    const text = storage()?.getItem(key)
    return text ? parse(JSON.parse(text)) : null
  } catch {
    return null
  }
}

/** 存一份草稿；`null` 是清掉 */
export function writeDraft(key: string, value: unknown): void {
  try {
    const s = storage()
    if (!s) return
    if (value === null || value === undefined) s.removeItem(key)
    else s.setItem(key, JSON.stringify(value))
  } catch {
    // 存不了就算了：字還在輸入框裡
  }
}

export const clearDraft = (key: string) => writeDraft(key, null)

// ── 回覆 ──
/** 回覆的草稿就是一段字；只有空白不算草稿 */
export const parseReplyDraft = (raw: unknown): string | null => (typeof raw === "string" && raw.trim() ? raw : null)

// ── 開新主題 ──
/** 標記的股票：只留畫面要用的三個欄位 */
export interface DraftTag {
  symbol: string
  code: string
  name: string
}
export interface NewTopicDraft {
  /** `public`、`group:<id>`，或還沒選（null） */
  dest: string | null
  title: string
  body: string
  tags: DraftTag[]
  /** 從個股頁帶來、被使用者拿掉的那一檔（回來時不要又自動標回去） */
  removedPreset: string | null
}

const isTag = (t: unknown): t is DraftTag =>
  typeof t === "object" && t !== null && (["symbol", "code", "name"] as const).every((k) => typeof (t as Record<string, unknown>)[k] === "string")

/** 表單有沒有值得留下來的東西：標題、內文或標記（只選了發到哪裡不算——那是要緊的選擇，不替使用者記著） */
export const hasTopicContent = (d: Pick<NewTopicDraft, "title" | "body" | "tags">) => !!d.title.trim() || !!d.body.trim() || d.tags.length > 0

export function parseNewTopicDraft(raw: unknown): NewTopicDraft | null {
  if (typeof raw !== "object" || raw === null) return null
  const r = raw as Record<string, unknown>
  const draft: NewTopicDraft = {
    dest: typeof r.dest === "string" ? r.dest : null,
    title: typeof r.title === "string" ? r.title : "",
    body: typeof r.body === "string" ? r.body : "",
    tags: Array.isArray(r.tags) ? r.tags.filter(isTag).map(({ symbol, code, name }) => ({ symbol, code, name })) : [],
    removedPreset: typeof r.removedPreset === "string" ? r.removedPreset : null,
  }
  return hasTopicContent(draft) ? draft : null
}
