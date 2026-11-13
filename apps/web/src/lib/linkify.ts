export type TextPart = { kind: "text"; text: string } | { kind: "link"; text: string; href: string }

/**
 * `http(s)://` 開頭，到空白、引號、角括號或全形標點為止——中文句子裡網址後面常常直接接「，」「。」「）」，
 * 那些不是網址的一部分（網址裡的中文字，例如維基百科的條目名稱，照樣算）。
 */
const URL_RE = /https?:\/\/[^\s<>"'`，。、；：！？（）「」『』【】《》〈〉〔〕]+/gi
/** 網址後面常跟著的半形標點不算在網址裡（句號、逗號、冒號、驚嘆號、問號、刪節號…） */
const TRAILING = /[.,;:!?…’”]+$/u

/** 尾巴的右括號：網址裡沒有對應的左括號時不算在網址裡（「(見 https://example.com/a)」） */
function trimBrackets(url: string): string {
  let out = url
  for (;;) {
    const last = out.at(-1)
    const open = last === ")" ? "(" : last === "]" ? "[" : null
    if (!open || out.split(open).length > out.split(last!).length - 1) return out
    out = out.slice(0, -1)
  }
}

/**
 * 把純文字切成「文字」與「連結」兩種片段：只有 `http://`、`https://` 的網址變成連結。
 * 純函式、不產生 HTML：畫面（`PlainText`）用 React 節點渲染（文字節點會自動跳脫），所以使用者貼的 `<script>`、
 * `javascript:` 之類都只是字。
 */
export function linkParts(text: string): TextPart[] {
  const parts: TextPart[] = []
  let at = 0
  for (const m of text.matchAll(URL_RE)) {
    let url = m[0]
    for (;;) {
      const next = trimBrackets(url.replace(TRAILING, ""))
      if (next === url) break
      url = next
    }
    let href: string
    try {
      const parsed = new URL(url)
      if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") || !parsed.hostname) continue
      href = parsed.href
    } catch {
      continue
    }
    const start = m.index
    if (start > at) parts.push({ kind: "text", text: text.slice(at, start) })
    parts.push({ kind: "link", text: url, href })
    at = start + url.length
  }
  if (at < text.length) parts.push({ kind: "text", text: text.slice(at) })
  return parts
}
