import { Lexer, type Token, type Tokens } from "marked"
import { Fragment } from "react"
import { cn } from "@/lib/utils"

/**
 * 把我們自己的 Markdown 文件（服務條款、隱私權政策：`docs/legal/`）畫成這個系統的文件版面。
 * 用 marked 的詞法分析拿到結構，再用 React 節點畫（不用 `dangerouslySetInnerHTML`；原始 HTML 一律當成字）。
 * 版面：一欄好讀的寬度（一行約 40 個中文字），標題下面是印刷線，表格是格線表（手機上可以橫向捲動），沒有卡片。
 * 只支援這兩份文件用到的語法：標題、段落、清單（可巢狀）、表格、引言、分隔線、粗體、斜體、行內程式碼、連結。
 */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const tokens = new Lexer({ gfm: true }).lex(source)
  return <div className={cn("doc", className)}>{blocks(tokens)}</div>
}

/** 一行的寬度：約 40 個中文字（表格例外，可以用到整個欄寬） */
const LINE = "max-w-[40em]"
/** 草稿裡還沒填、還沒確認的地方（【待填：…】【待確認：…】）：淡底標出來，看得出這裡還是空的 */
const BLANK = /(【(?:待填|待確認)[^】]*】)/

function blocks(tokens: Token[]): React.ReactNode {
  return tokens.map((t, i) => <Fragment key={i}>{block(t)}</Fragment>)
}

function block(t: Token): React.ReactNode {
  switch (t.type) {
    case "space":
      return null
    case "heading": {
      const h = t as Tokens.Heading
      if (h.depth === 1) return <h1 className="text-2xl font-bold tracking-[-0.01em] [text-wrap:pretty] lg:text-3xl">{inline(h.tokens)}</h1>
      if (h.depth === 2) return <h2 className="mt-10 border-b border-print pb-2 text-xl font-bold [text-wrap:pretty]">{inline(h.tokens)}</h2>
      return <h3 className={cn("mt-6 text-base font-bold [text-wrap:pretty]", LINE)}>{inline(h.tokens)}</h3>
    }
    case "paragraph":
      return <p className={cn("mt-3", LINE)}>{inline((t as Tokens.Paragraph).tokens)}</p>
    case "text": {
      // 清單項目裡的一行字
      const x = t as Tokens.Text
      return x.tokens ? inline(x.tokens) : text(x.text)
    }
    case "list": {
      const l = t as Tokens.List
      const items = l.items.map((item, i) => (
        <li key={i} className="pl-1">
          {listItem(item)}
        </li>
      ))
      return l.ordered ? (
        <ol start={typeof l.start === "number" ? l.start : undefined} className={cn("mt-3 flex list-decimal flex-col gap-1.5 pl-6 marker:text-ink-2", LINE)}>
          {items}
        </ol>
      ) : (
        <ul className={cn("mt-3 flex list-disc flex-col gap-1.5 pl-5 marker:text-ink-2", LINE)}>{items}</ul>
      )
    }
    case "table": {
      const tb = t as Tokens.Table
      return (
        // 表格可以比一行字寬；手機上放不下時這一塊自己橫向捲動，頁面不跟著捲
        <div className="mt-4 overflow-x-auto" tabIndex={0} role="group" aria-label="表格">
          <table className="w-full min-w-[34rem] border-collapse text-md">
            <thead>
              <tr>
                {tb.header.map((c, i) => (
                  <th key={i} scope="col" className="border-b border-print py-2 pr-4 text-left align-bottom text-sm font-normal text-ink-2 last:pr-0">
                    {inline(c.tokens)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tb.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((c, i) => (
                    <td key={i} className={cn("border-b border-rule py-2.5 pr-4 align-top last:pr-0", i === 0 && "font-medium")}>
                      {inline(c.tokens)}
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
      // 引言：上下格線的一段淡墨字（沒有側邊色條）
      return <blockquote className={cn("mt-4 border-y border-rule py-3 text-md text-ink-2 *:first:mt-0", LINE)}>{blocks((t as Tokens.Blockquote).tokens)}</blockquote>
    case "hr":
      return <hr className="mt-8 border-rule" />
    case "code":
      return <pre className="mt-3 overflow-x-auto rounded-sm bg-sel p-3 text-sm">{(t as Tokens.Code).text}</pre>
    case "html":
      return <p className={cn("mt-3", LINE)}>{(t as Tokens.HTML).text}</p>
    default:
      return "text" in t && typeof t.text === "string" ? <p className={cn("mt-3", LINE)}>{t.text}</p> : null
  }
}

/** 清單的一項：第一行是字，後面可以接巢狀清單或段落 */
function listItem(item: Tokens.ListItem): React.ReactNode {
  return item.tokens.map((t, i) => {
    if (t.type === "text") return <Fragment key={i}>{block(t)}</Fragment>
    if (t.type === "paragraph") return <Fragment key={i}>{inline((t as Tokens.Paragraph).tokens)}</Fragment>
    return <Fragment key={i}>{block(t)}</Fragment>
  })
}

function inline(tokens: Token[] | undefined): React.ReactNode {
  return (tokens ?? []).map((t, i) => <Fragment key={i}>{span(t)}</Fragment>)
}

function span(t: Token): React.ReactNode {
  switch (t.type) {
    case "strong":
      return <strong className="font-semibold text-ink">{inline((t as Tokens.Strong).tokens)}</strong>
    case "em":
      return <em>{inline((t as Tokens.Em).tokens)}</em>
    case "del":
      return <s>{inline((t as Tokens.Del).tokens)}</s>
    case "codespan":
      return <code className="num rounded-xs bg-sel px-1 text-[0.92em]">{decode((t as Tokens.Codespan).text)}</code>
    case "br":
      return <br />
    case "link": {
      const l = t as Tokens.Link
      const external = /^(https?:|mailto:)/i.test(l.href)
      // 只有 http(s)、mailto 與站內路徑會變成連結；其他（javascript: 之類）當成字
      if (!external && !l.href.startsWith("/")) return inline(l.tokens)
      return (
        <a
          href={l.href}
          {...(external && !l.href.startsWith("mailto:") ? { target: "_blank", rel: "noopener noreferrer" } : {})}
          className="break-words text-ink underline decoration-ctl decoration-1 underline-offset-4 hover:decoration-ink"
        >
          {inline(l.tokens)}
        </a>
      )
    }
    case "escape":
      return (t as Tokens.Escape).text
    case "text": {
      const x = t as Tokens.Text
      return x.tokens ? inline(x.tokens) : text(x.text)
    }
    default:
      return "text" in t && typeof t.text === "string" ? text(t.text) : null
  }
}

/** marked 把字裡的 & < > " ' 轉成了 HTML 實體；我們用 React 節點畫，要還原成原本的字 */
function decode(s: string): string {
  return s.replace(/&(amp|lt|gt|quot|#39);/g, (_, e: string) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" })[e]!)
}

function text(raw: string): React.ReactNode {
  const s = decode(raw)
  if (!BLANK.test(s)) return s
  return s.split(BLANK).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="bg-sel px-0.5 text-ink">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}
