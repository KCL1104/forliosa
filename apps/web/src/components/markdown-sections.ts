import { Lexer, type Token, type Tokens } from "marked"

/** marked 把字裡的 & < > " ' 轉成了 HTML 實體；我們用 React 節點畫，要還原成原本的字 */
export function decodeEntities(s: string): string {
  return s.replace(/&(amp|lt|gt|quot|#39);/g, (_, e: string) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" })[e]!)
}

export interface DocSection {
  id: string
  /** 標題的字（含編號：「3. 帳號」） */
  title: string
}

/** 文件的每一節（`##`），給目錄用；id 和畫面上標題的 id 相同 */
export function docSections(source: string): DocSection[] {
  return sectionsOf(new Lexer({ gfm: true }).lex(source))
}

export function sectionsOf(tokens: Token[]): DocSection[] {
  let unnumbered = 0
  return tokens
    .filter((t): t is Tokens.Heading => t.type === "heading" && (t as Tokens.Heading).depth === 2)
    .map((h) => {
      const title = decodeEntities(h.text).replace(/\*\*/g, "")
      const n = /^(\d+)[.、]/.exec(title)?.[1]
      const id = n ? `sec-${n}` : unnumbered++ === 0 ? "sec-top" : `sec-i${unnumbered}`
      return { id, title }
    })
}
