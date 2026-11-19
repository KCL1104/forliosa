import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import type { MarketReport } from "@/api/types"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { titleBody } from "./report-context"
import { ReportText } from "./ReportText"

/**
 * 報告的開頭：
 * 1. 一行 13px 淡墨：免責的一句・資料截至幾點；有更正時下一行墨色「已更正（11/18 09:10）：…」；有狀態時（AI 段落還在整理…）再一行。
 * 2. 報告名稱與日期（標題，20px 700：「盤前重點 11/18（三）」）→ 這一份的一句話（AI 寫的是 `.ai-voice` 的 AI line 20px；規則寫的是墨色）
 *    → 3 個重點（每點一段，點與點之間一條格線，句尾是出處號碼）。
 * 報告的名稱是標題，AI 寫的那一句接在下面：不在標題上面放小標（eyebrow）。
 */
export function ReportHeader({ report: r, headingLevel = 2 }: { report: MarketReport; headingLevel?: 1 | 2 }) {
  const H = headingLevel === 1 ? "h1" : "h2"
  const aiTitle = r.title_origin === "ai"
  const aiPoints = r.highlights_origin === "ai"
  const title = aiTitle ? r.title : titleBody(r.kind_label, r.title)
  return (
    <header className="flex flex-col">
      <p className="text-sm text-ink-2">
        {r.disclaimer_line}
        {" "}
        <span className="num whitespace-nowrap">{r.as_of_label}</span>
      </p>
      {r.corrections.map((c) => (
        <p key={c.at} className="mt-1 text-sm text-ink" data-correction="">
          <span className="num">已更正（{formatDateTime(c.at)}）</span>：{c.note}
        </p>
      ))}
      {r.status_line && (
        <p className="mt-1 text-sm text-ink" data-status-line="">
          {r.status_line}
        </p>
      )}
      <H className="num mt-5 font-print text-xl font-bold" data-report-heading="">
        {r.kind_label} {r.edition_label}
      </H>
      <p className={cn("mt-1 max-w-[46rem]", aiTitle ? cn("ai-voice", kaiSize.line) : "text-xl leading-normal text-ink")} data-report-title="">
        {aiTitle ? <KaiText text={title} /> : title}
      </p>
      {r.highlights.length > 0 && (
        <ul aria-label="重點" className="mt-3 max-w-[46rem] border-t border-rule">
          {r.highlights.map((p, i) => (
            <li key={i} className="border-b border-rule py-2.5">
              <ReportText p={p} ai={aiPoints} className={aiPoints ? kaiSize.page : "text-base leading-relaxed lg:text-[1rem]"} />
            </li>
          ))}
        </ul>
      )}
    </header>
  )
}
