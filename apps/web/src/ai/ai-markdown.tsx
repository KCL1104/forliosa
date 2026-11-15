import { Lexer, type Token, type Tokens } from "marked"
import { Fragment } from "react"
import { decodeEntities as decode } from "@/components/markdown-sections"
import { cn } from "@/lib/utils"
import { KaiText } from "./kai-text"

/**
 * AI 回答的 Markdown（產品負責人 2026-11-15：回答預設用 Markdown，畫面正常顯示）。
 * 和服務條款的 `components/markdown.tsx` 同一種做法：marked 的詞法分析拿到結構，再用 React 節點畫；
 * 不用 `dangerouslySetInnerHTML`，原始 HTML 一律當成字，連結只接受 http(s)。版面為 400px 的面板與手機排得緊湊：
 * - 段落、清單（含巢狀、有序）、`###` 小標題（任何層級都畫成同一種小標題，沒有大標題）、表格（窄的時候可以橫向捲動）、
 *   引言、分隔線、粗體、斜體、刪除線、行內程式碼、連結。單一換行就是換行（`breaks`），和聊天的習慣一樣。
 * - 每一段字都經過 `KaiText`：數字和單位不在行尾拆開。
 * - `marks`：沒有附來源的段落（後端的 grounding）。在某一段字裡找到時，那段字下面一條點線、後面接 `mark(i)` 回傳的標記；
 *   跨越粗體等格式的段落找不到就略過，不硬塞。
 */
export function AiMarkdown({
  source,
  marks,
  mark,
  className,
}: {
  source: string
  /** 沒有附來源的段落文字（已整理過，和 source 用同一套整理） */
  marks?: string[]
  /** 第 i 個段落後面的標記 */
  mark?: (i: number) => React.ReactNode
  className?: string
}) {
  const tokens = new Lexer({ gfm: true, breaks: true }).lex(source)
  const ctx: Ctx = { marks: (marks ?? []).map((m) => m.trim()).filter(Boolean), mark, used: new Set() }
  return <div className={cn("ai-md", className)}>{blocks(tokens, ctx)}</div>
}

interface Ctx {
  marks: string[]
  mark?: (i: number) => React.ReactNode
  /** 已經標過的段落（同一段只標一次） */
  used: Set<number>
}

const LINK = "text-ink underline decoration-ctl decoration-1 underline-offset-4 hover:decoration-ink"

function blocks(tokens: Token[], ctx: Ctx): React.ReactNode {
  return tokens.map((t, i) => <Fragment key={i}>{block(t, ctx)}</Fragment>)
}

function block(t: Token, ctx: Ctx): React.ReactNode {
  switch (t.type) {
    case "space":
      return null
    case "heading":
      // 任何層級都是同一種小標題：比內文粗、不比內文大（面板很窄，大標題會把回答撐得很鬆）
      return <h3 className="mt-4 font-semibold text-ink first:mt-0">{inline((t as Tokens.Heading).tokens, ctx)}</h3>
    case "paragraph":
      return <p className="mt-3 first:mt-0">{inline((t as Tokens.Paragraph).tokens, ctx)}</p>
    case "text": {
      const x = t as Tokens.Text
      return x.tokens ? inline(x.tokens, ctx) : leaf(x.text, ctx)
    }
    case "list": {
      const l = t as Tokens.List
      const items = l.items.map((item, i) => (
        <li key={i} className="pl-0.5">
          {listItem(item, ctx)}
        </li>
      ))
      return l.ordered ? (
        <ol start={typeof l.start === "number" ? l.start : undefined} className="mt-2 flex list-decimal flex-col gap-1 pl-5 marker:text-ink-2 first:mt-0">
          {items}
        </ol>
      ) : (
        <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 marker:text-ink-2 first:mt-0">{items}</ul>
      )
    }
    case "table": {
      const tb = t as Tokens.Table
      return (
        <div className="mt-3 overflow-x-auto overscroll-x-contain first:mt-0">
          <table className="w-full border-collapse text-[0.9375em]">
            <thead>
              <tr>
                {tb.header.map((c, i) => (
                  <th key={i} scope="col" className="border-b border-print py-1.5 pr-3 text-left align-bottom text-[0.875em] font-normal whitespace-nowrap text-ink-2 last:pr-0">
                    {inline(c.tokens, ctx)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tb.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((c, i) => (
                    <td key={i} className={cn("num border-b border-rule py-1.5 pr-3 align-top last:pr-0", i === 0 && "font-medium")}>
                      {inline(c.tokens, ctx)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }
    case "blockquote":
      return <blockquote className="mt-3 border-l-2 border-rule pl-3 text-ink-2 first:mt-0">{blocks((t as Tokens.Blockquote).tokens, ctx)}</blockquote>
    case "hr":
      return <hr className="mt-4 border-rule" />
    case "code":
      return <pre className="mt-3 overflow-x-auto rounded-sm bg-sel p-2.5 text-sm whitespace-pre-wrap first:mt-0">{(t as Tokens.Code).text}</pre>
    case "html":
      return <p className="mt-3 first:mt-0">{leaf((t as Tokens.HTML).text, ctx)}</p>
    default:
      return "text" in t && typeof t.text === "string" ? <p className="mt-3 first:mt-0">{leaf(t.text, ctx)}</p> : null
  }
}

/** 清單的一項：第一行是字，後面可以接巢狀清單或段落 */
function listItem(item: Tokens.ListItem, ctx: Ctx): React.ReactNode {
  return item.tokens.map((t, i) => {
    if (t.type === "paragraph") return <Fragment key={i}>{inline((t as Tokens.Paragraph).tokens, ctx)}</Fragment>
    if (t.type === "text") return <Fragment key={i}>{block(t, ctx)}</Fragment>
    return <Fragment key={i}>{block(t, ctx)}</Fragment>
  })
}

function inline(tokens: Token[] | undefined, ctx: Ctx): React.ReactNode {
  return (tokens ?? []).map((t, i) => <Fragment key={i}>{span(t, ctx)}</Fragment>)
}

function span(t: Token, ctx: Ctx): React.ReactNode {
  switch (t.type) {
    case "strong":
      return <strong className="font-semibold text-ink">{inline((t as Tokens.Strong).tokens, ctx)}</strong>
    case "em":
      return <em>{inline((t as Tokens.Em).tokens, ctx)}</em>
    case "del":
      return <s>{inline((t as Tokens.Del).tokens, ctx)}</s>
    case "codespan":
      return <code className="num rounded-xs bg-sel px-1 text-[0.92em] [overflow-wrap:anywhere]">{decode((t as Tokens.Codespan).text)}</code>
    case "br":
      return <br />
    case "link": {
      const l = t as Tokens.Link
      // 只有 http(s) 會變成連結（另開新視窗）；其他（javascript: 之類、站內路徑）當成字
      if (!/^https?:\/\//i.test(l.href)) return inline(l.tokens, ctx)
      return (
        <a href={l.href} target="_blank" rel="noopener noreferrer" className={cn("break-words", LINK)}>
          {inline(l.tokens, ctx)}
          <span className="sr-only">（另開新視窗）</span>
        </a>
      )
    }
    case "image":
      return (t as Tokens.Image).text
    case "escape":
      return (t as Tokens.Escape).text
    case "text": {
      const x = t as Tokens.Text
      return x.tokens ? inline(x.tokens, ctx) : leaf(x.text, ctx)
    }
    default:
      return "text" in t && typeof t.text === "string" ? leaf(t.text, ctx) : null
  }
}

/** 一段字：數字和單位不拆行（`KaiText`）；沒有附來源的段落在這段字裡時，切出來加點線與標記 */
function leaf(raw: string, ctx: Ctx): React.ReactNode {
  const s = decode(raw)
  for (let i = 0; i < ctx.marks.length; i++) {
    if (ctx.used.has(i)) continue
    const needle = ctx.marks[i]!
    const at = s.indexOf(needle)
    if (at === -1) continue
    ctx.used.add(i)
    return (
      <>
        {leaf(s.slice(0, at), ctx)}
        <span>
          <span className="underline decoration-ctl decoration-dotted decoration-1 underline-offset-[5px]">
            <KaiText text={needle} />
          </span>
          {ctx.mark?.(i)}
        </span>
        {leaf(s.slice(at + needle.length), ctx)}
      </>
    )
  }
  return <KaiText text={s} />
}
