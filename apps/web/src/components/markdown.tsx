import { Lexer, type Token, type Tokens } from "marked"
import { Fragment } from "react"
import { PlainLink } from "@/app/links"
import { decodeEntities as decode, sectionsOf } from "./markdown-sections"
import { cn } from "@/lib/utils"

/**
 * 把我們自己的 Markdown 文件（服務條款、隱私權政策：`docs/legal/`）畫成這個系統的文件版面。
 * 用 marked 的詞法分析拿到結構，再用 React 節點畫（不用 `dangerouslySetInnerHTML`；原始 HTML 一律當成字）。
 * 版面：一欄好讀的寬度（一行約 40 個中文字），標題下面是印刷線，表格是格線表，沒有卡片。
 * 只支援這兩份文件用到的語法：標題、段落、清單（可巢狀）、表格、引言、分隔線、粗體、斜體、行內程式碼、連結。
 *
 * - 每一節（`##`）有 id（`sec-3`；沒有編號的是 `sec-top`、`sec-i2`…）：目錄與「見第 N 節」可以連過去。
 * - 「第 N 節」變成頁內連結；`docLinks` 裡的文件名稱（〈隱私權政策〉）變成連到那一頁的連結，
 *   後面緊接的「第 N 節」連到那一頁的那一節。
 * - 表格在手機上不橫向捲動（捲到一半的字會被切掉，也看不出還有東西）：兩欄的表照欄寬換行；
 *   三欄以上的表在 640px 以下改成一列一塊——第一格是粗體標題，其餘每格一行「欄名：內容」。
 */
export function Markdown({
  source,
  className,
  docLinks,
  beforeFirstSection,
}: {
  source: string
  className?: string
  /** 文件名稱 → 站內路徑（`{ 隱私權政策: "/privacy" }`） */
  docLinks?: Record<string, string>
  /** 放在第一節（第一個 `##`）前面的東西：手機的目錄 */
  beforeFirstSection?: React.ReactNode
}) {
  const tokens = new Lexer({ gfm: true }).lex(source)
  const ctx: Ctx = { docLinks: docLinks ?? {}, sections: new Set(sectionsOf(tokens).map((s) => s.id)), heading: "" }
  return <div className={cn("doc", className)}>{blocks(tokens, ctx, beforeFirstSection)}</div>
}

interface Ctx {
  docLinks: Record<string, string>
  sections: Set<string>
  /** 目前所在那一節的標題（表格的名稱用） */
  heading: string
}

/** 一行的寬度：約 40 個中文字（表格例外，可以用到整個欄寬） */
const LINE = "max-w-[40em]"
/** 草稿裡還沒填、還沒確認的地方（【待填：…】【待確認：…】）：淡底標出來，看得出這裡還是空的 */
const BLANK = /(【(?:待填|待確認)[^】]*】)/
const LINK = "text-ink underline decoration-ctl decoration-1 underline-offset-4 hover:decoration-ink"

function blocks(tokens: Token[], ctx: Ctx, beforeFirstSection?: React.ReactNode): React.ReactNode {
  let h2 = 0
  const ids = [...ctx.sections]
  return tokens.map((t, i) => {
    let id: string | undefined
    let first = false
    if (t.type === "heading") {
      const h = t as Tokens.Heading
      if (h.depth === 2) {
        first = h2 === 0
        id = ids[h2++]
      }
      if (h.depth >= 2) ctx.heading = decode(h.text).replace(/\*\*/g, "")
    }
    return (
      <Fragment key={i}>
        {first && beforeFirstSection}
        {block(t, ctx, id)}
      </Fragment>
    )
  })
}

function block(t: Token, ctx: Ctx, id?: string): React.ReactNode {
  switch (t.type) {
    case "space":
      return null
    case "heading": {
      const h = t as Tokens.Heading
      if (h.depth === 1) return <h1 className="text-2xl font-bold tracking-[-0.01em] [text-wrap:pretty] lg:text-3xl">{inline(h.tokens, ctx)}</h1>
      // scroll-mt：從目錄或「見第 N 節」跳過來時，標題不會被固定的標題列蓋住
      if (h.depth === 2)
        return (
          <h2 id={id} className="mt-10 scroll-mt-20 border-b border-print pb-2 text-xl font-bold [text-wrap:pretty]">
            {inline(h.tokens, ctx)}
          </h2>
        )
      // 小節標題比內文（16px）大一階：17px 粗體
      return <h3 className={cn("mt-6 text-lg font-bold [text-wrap:pretty]", LINE)}>{inline(h.tokens, ctx)}</h3>
    }
    case "paragraph":
      return <p className={cn("mt-3", LINE)}>{inline((t as Tokens.Paragraph).tokens, ctx)}</p>
    case "text": {
      // 清單項目裡的一行字
      const x = t as Tokens.Text
      return x.tokens ? inline(x.tokens, ctx) : text(x.text, ctx)
    }
    case "list": {
      const l = t as Tokens.List
      const items = l.items.map((item, i) => (
        <li key={i} className="pl-1">
          {listItem(item, ctx)}
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
    case "table":
      return <Table table={t as Tokens.Table} ctx={ctx} />
    case "blockquote":
      // 引言：上下格線的一段淡墨字（沒有側邊色條）
      return <blockquote className={cn("mt-4 border-y border-rule py-3 text-md text-ink-2 *:first:mt-0", LINE)}>{blocks((t as Tokens.Blockquote).tokens, ctx)}</blockquote>
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

/**
 * 格線表。兩欄：一直是表格，欄位照寬度換行。三欄以上：640px 以上是表格；以下是一列一塊
 * （第一格粗體當標題，其餘每格一行「欄名：內容」），不橫向捲動。
 */
function Table({ table, ctx }: { table: Tokens.Table; ctx: Ctx }) {
  const wide = table.header.length > 2
  const label = ctx.heading ? `${ctx.heading}（表格）` : "表格"
  return (
    <>
      <table aria-label={label} className={cn("mt-4 w-full border-collapse text-md", wide && "max-sm:hidden")}>
        <thead>
          <tr>
            {table.header.map((c, i) => (
              <th key={i} scope="col" className="border-b border-print py-2 pr-4 text-left align-bottom text-sm font-normal text-ink-2 last:pr-0">
                {inline(c.tokens, ctx)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={r}>
              {row.map((c, i) => (
                <td key={i} className={cn("border-b border-rule py-2.5 pr-4 align-top [overflow-wrap:anywhere] last:pr-0", i === 0 && "font-medium", i === 0 && !wide && "w-[40%]")}>
                  {inline(c.tokens, ctx)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {wide && (
        <ul aria-label={label} className="mt-4 border-t border-print text-md sm:hidden">
          {table.rows.map((row, r) => (
            <li key={r} className="border-b border-rule py-3">
              <p className="font-semibold">{inline(row[0]?.tokens, ctx)}</p>
              <dl className="mt-1 flex flex-col gap-1">
                {row.slice(1).map((c, i) => (
                  <div key={i}>
                    <dt className="inline text-ink-2">{inline(table.header[i + 1]?.tokens, ctx)}：</dt>
                    <dd className="inline [overflow-wrap:anywhere]">{inline(c.tokens, ctx)}</dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

/** 清單的一項：第一行是字，後面可以接巢狀清單或段落 */
function listItem(item: Tokens.ListItem, ctx: Ctx): React.ReactNode {
  return item.tokens.map((t, i) => {
    if (t.type === "paragraph") return <Fragment key={i}>{inline((t as Tokens.Paragraph).tokens, ctx)}</Fragment>
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
      // 長的網域或路徑（static.cloudflareinsights.com）在窄螢幕要能斷行，不撐寬頁面
      return <code className="num rounded-xs bg-sel px-1 text-[0.92em] [overflow-wrap:anywhere]">{decode((t as Tokens.Codespan).text)}</code>
    case "br":
      return <br />
    case "link": {
      const l = t as Tokens.Link
      const external = /^(https?:|mailto:)/i.test(l.href)
      // 只有 http(s)、mailto 與站內路徑會變成連結；其他（javascript: 之類）當成字
      if (!external && !l.href.startsWith("/")) return inline(l.tokens, ctx)
      return (
        <a href={l.href} {...(external && !l.href.startsWith("mailto:") ? { target: "_blank", rel: "noopener noreferrer" } : {})} className={cn("break-words", LINK)}>
          {inline(l.tokens, ctx)}
        </a>
      )
    }
    case "escape":
      return (t as Tokens.Escape).text
    case "text": {
      const x = t as Tokens.Text
      return x.tokens ? inline(x.tokens, ctx) : text(x.text, ctx)
    }
    default:
      return "text" in t && typeof t.text === "string" ? text(t.text, ctx) : null
  }
}

/**
 * 一段字：標出【待填】，並把交叉引用變成連結——
 * 〈文件名稱〉（`docLinks` 裡有的）連到那一頁，緊接的「第 N 節」連到那一頁的那一節；其餘的「第 N 節」是頁內連結。
 */
function text(raw: string, ctx: Ctx): React.ReactNode {
  const s = decode(raw)
  const names = Object.keys(ctx.docLinks)
  const pattern = new RegExp(`(【(?:待填|待確認)[^】]*】${names.length ? `|〈(?:${names.join("|")})〉(?:\\s*第 \\d+(?:\\.\\d+)? 節)?` : ""}|第 \\d+(?:\\.\\d+)? 節)`)
  if (!pattern.test(s)) return s
  return s.split(pattern).map((part, i) => {
    if (i % 2 === 0) return part
    if (BLANK.test(part))
      return (
        <mark key={i} className="bg-sel px-0.5 text-ink">
          {part}
        </mark>
      )
    const doc = /^〈(.+?)〉/.exec(part)?.[1]
    const n = /第 (\d+)(?:\.\d+)? 節/.exec(part)?.[1]
    if (doc) {
      // 站內的另一份文件：SPA 導覽（那一頁載入後自己捲到那一節）
      return (
        <PlainLink key={i} to={ctx.docLinks[doc]!} hash={n ? `sec-${n}` : undefined} className={LINK}>
          {part}
        </PlainLink>
      )
    }
    // 頁內：這份文件真的有那一節才連
    if (!n || !ctx.sections.has(`sec-${n}`)) return part
    return (
      <a key={i} href={`#sec-${n}`} className={LINK}>
        {part}
      </a>
    )
  })
}
