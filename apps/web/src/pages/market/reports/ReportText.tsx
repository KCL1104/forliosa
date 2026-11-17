import { Fragment } from "react"
import { KaiText } from "@/ai/kai-text"
import type { ReportParagraph, ReportSentence } from "@/api/types"
import { cn } from "@/lib/utils"
import { jumpTo, useReport } from "./report-context"

/**
 * 一段報告的字：每一句後面是它的出處號碼（上標，12px 淡墨等寬數字，多個用逗號隔開），點了跳到最下面「來源」的那一條。
 * AI 寫的段用 `.ai-voice`＋`KaiText`（數字和單位不拆行）；規則寫的是一般的墨色字。
 * 畫面上絕不出現 F001、X003 這類編號：只有管理員檢視在每句後面多一段 12px 淡墨等寬的 refs。
 */
export function ReportText({ p, ai, className, as: Tag = "p" }: { p: ReportParagraph; ai: boolean; className?: string; as?: "p" | "span" }) {
  return (
    <Tag className={cn(ai && "ai-voice", className)}>
      {p.sentences.map((s, i) => (
        <Sentence key={i} s={s} ai={ai} />
      ))}
    </Tag>
  )
}

function Sentence({ s, ai }: { s: ReportSentence; ai: boolean }) {
  const { admin } = useReport()
  return (
    <>
      {ai ? <KaiText text={s.text} /> : s.text}
      <Cites cites={s.cites} />
      {admin && s.refs && s.refs.length > 0 && (
        <span data-refs="" className="ml-1 font-mono text-xs whitespace-nowrap text-ink-2">
          {s.refs.join(" ")}
        </span>
      )}
    </>
  )
}

/**
 * 出處號碼：觸控時每個號碼的可按範圍用看不見的 `::before` 放大（字的位置不變）。
 * 只有一個號碼時向左右各放大 18px（44×44 以上）；好幾個號碼並排時，各號碼左右多一點間距，
 * 放大的範圍只到自己的邊（第一個向左、最後一個向右再放大），所以相鄰的號碼不會互相蓋住、點哪個就是哪個。
 * 號碼本身是連到註腳的連結；回到原句的連結在註腳那一邊。
 */
export function Cites({ cites }: { cites: number[] }) {
  const { prefix } = useReport()
  if (cites.length === 0) return null
  return (
    <sup className="num ml-0.5 text-xs leading-none font-normal text-ink-2">
      {cites.map((n, i) => (
        <Fragment key={n}>
          {i > 0 && <span aria-hidden>,</span>}
          <a
            href={`#${prefix}fn-${n}`}
            data-fn-ref={n}
            aria-label={`出處 ${n}`}
            onClick={(e) => {
              e.preventDefault()
              jumpTo(`${prefix}fn-${n}`)
            }}
            className={cn(
              "relative rounded-xs px-px no-underline hover:text-ink focus-visible:outline-offset-1 pointer-coarse:before:absolute pointer-coarse:before:-inset-y-3.5 pointer-coarse:before:content-['']",
              cites.length === 1
                ? "pointer-coarse:before:-inset-x-[1.125rem]"
                : cn(
                    "pointer-coarse:px-2",
                    i === 0 ? "pointer-coarse:before:-left-[1.125rem]" : "pointer-coarse:before:left-0",
                    i === cites.length - 1 ? "pointer-coarse:before:-right-[1.125rem]" : "pointer-coarse:before:right-0",
                  ),
            )}
          >
            {n}
          </a>
        </Fragment>
      ))}
    </sup>
  )
}
