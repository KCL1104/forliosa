/**
 * AI 回答文字的兩個顯示規則（純函式，方便測試）：
 * 1. 免責聲明由介面固定顯示（`done.disclaimer`，沒有時用常數）。模型自己在最後一行寫了同樣的話時，從文字裡拿掉，
 *    避免畫面上出現兩次；同一行裡的資料時間（「資料至 11/12 13:30」）保留。
 * 2. 「無來源」：後端的 `grounding` 事件列出像事實陳述、卻沒有附來源的段落，切成片段讓畫面在段落後面加上安靜的標記。
 */

/** 與後端 `done.disclaimer`／`/ai/usage.disclaimer` 相同的固定文字（後端沒送時用） */
export const DISCLAIMER = "AI 回答僅供參考，非投資建議。"

/** 後端 AI 無法使用（503 `ai_unavailable`：沒有金鑰、所有金鑰停用或額度用完）時的一句話 */
export const AI_UNAVAILABLE = "AI 暫時無法使用，請稍後再試。"

/** 「僅供參考，非投資建議。」「AI 分析僅供參考，不構成投資建議」這類句子（可在一行的結尾） */
const DISCLAIMER_TAIL = /[，,。．\s]*(?:以上)?(?:內容|資訊|分析|回答|AI\s*分析|AI\s*回答)?(?:僅供參考)[，,、\s]*(?:並)?(?:非|不構成|不代表|不是)(?:任何)?投資建議[。．.!！]*\s*$/

export function stripDisclaimer(text: string, disclaimer: string = DISCLAIMER): string {
  const trimmed = text.replace(/\s+$/, "")
  if (!trimmed) return text
  const lines = trimmed.split("\n")
  const last = lines[lines.length - 1]!
  const exact = disclaimer.trim()
  let rest: string | null = null
  if (exact && last.trim() === exact) rest = ""
  else if (exact && last.trim().endsWith(exact)) rest = last.trim().slice(0, -exact.length)
  else if (DISCLAIMER_TAIL.test(last)) rest = last.replace(DISCLAIMER_TAIL, "")
  if (rest === null) return text
  rest = rest.replace(/[，,、\s]+$/, "")
  const head = lines.slice(0, -1)
  const out = rest ? [...head, rest] : head
  return out.join("\n").replace(/\s+$/, "")
}

/** 沒有附來源的段落（`grounding` 事件的一項；後端欄位以 text 為主，start／end 是選填的字元位置） */
export interface UngroundedPassage {
  text: string
  reason?: string | null
  start?: number | null
  end?: number | null
}

export interface TextSegment {
  text: string
  /** 這一段後面要加「無來源」標記 */
  ungrounded?: UngroundedPassage
}

/**
 * 把回答切成片段：每個沒有來源的段落成為一段（帶標記），其他文字原樣。
 * 先用 start／end（位置要和 text 對得上），對不上就在文字裡找 text；找不到的段落略過，不硬塞。
 */
export function splitUngrounded(text: string, passages: UngroundedPassage[] | undefined): TextSegment[] {
  if (!passages?.length || !text) return [{ text }]
  const spans: { start: number; end: number; p: UngroundedPassage }[] = []
  for (const p of passages) {
    const needle = (p.text ?? "").trim()
    if (!needle) continue
    let start = -1
    if (typeof p.start === "number" && typeof p.end === "number" && p.end > p.start && text.slice(p.start, p.end).trim() === needle) {
      start = p.start + text.slice(p.start, p.end).indexOf(needle)
    } else {
      let from = 0
      // 同一句出現多次時取第一個還沒被標過的位置
      for (;;) {
        const at = text.indexOf(needle, from)
        if (at === -1) break
        if (!spans.some((s) => at < s.end && at + needle.length > s.start)) {
          start = at
          break
        }
        from = at + 1
      }
    }
    if (start === -1) continue
    const end = start + needle.length
    if (spans.some((s) => start < s.end && end > s.start)) continue
    spans.push({ start, end, p })
  }
  if (spans.length === 0) return [{ text }]
  spans.sort((a, b) => a.start - b.start)
  const out: TextSegment[] = []
  let cursor = 0
  for (const s of spans) {
    if (s.start > cursor) out.push({ text: text.slice(cursor, s.start) })
    out.push({ text: text.slice(s.start, s.end), ungrounded: s.p })
    cursor = s.end
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) })
  return out
}

/** `grounding` 事件的資料：容錯解析 `{items: [...]}`、陣列，或單一物件 */
export function parseGrounding(data: unknown): UngroundedPassage[] {
  const raw = Array.isArray(data) ? data : data && typeof data === "object" && Array.isArray((data as { items?: unknown }).items) ? (data as { items: unknown[] }).items : data ? [data] : []
  return raw.flatMap((x): UngroundedPassage[] => {
    if (!x || typeof x !== "object") return []
    const o = x as Record<string, unknown>
    const text = typeof o.text === "string" ? o.text : typeof o.passage === "string" ? o.passage : ""
    if (!text.trim()) return []
    return [{
      text,
      reason: typeof o.reason === "string" ? o.reason : null,
      start: typeof o.start === "number" ? o.start : null,
      end: typeof o.end === "number" ? o.end : null,
    }]
  })
}

/** grounding 的 reason 代碼（後端 `ai/grounding.py`）→ 給人看的話；認不得的代碼不顯示 */
const REASON_TEXT: Record<string, string> = {
  uncited_news_claim: "像新聞敘述，但沒有對到任何引用的來源。",
}

export function groundingReason(reason: string | null | undefined): string {
  const r = (reason ?? "").trim()
  if (!r) return ""
  if (REASON_TEXT[r]) return REASON_TEXT[r]
  return /^[a-z0-9_:-]+$/i.test(r) ? "" : r
}
