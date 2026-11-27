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
 *    → 重點。
 * 報告的名稱是標題，AI 寫的那一句接在下面：不在標題上面放小標（eyebrow）。
 *
 * 重點有兩種（伺服器給哪一種就畫哪一種）：
 * - `brief`（2026-11-27）：每天同一個位置的欄位，一列一格——左邊印好的欄位名稱（「為什麼」「位置」「量」，`print-label`），
 *   右邊寫上去的一段（AI 寫的是 `.ai-voice`，規則算的是墨色黑體），列與列之間一條格線。和聯絡簿的表格同一種語法：
 *   印好的欄位名稱＋寫上去的字。欄位名稱的欄寬固定（3 個字），每一列的字從同一條線開始，掃一眼就找得到「位置」那一列。
 * - `highlights`（舊的版本、週報）：3–5 點，每點一段，點與點之間一條格線。
 */
export function ReportHeader({ report: r, headingLevel = 2 }: { report: MarketReport; headingLevel?: 1 | 2 }) {
  const H = headingLevel === 1 ? "h1" : "h2"
  const aiTitle = r.title_origin === "ai"
  const aiPoints = r.highlights_origin === "ai"
  const title = aiTitle ? r.title : titleBody(r.kind_label, r.title)
  const brief = r.brief ?? []
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
      {brief.length > 0 ? (
        <dl aria-label="重點" className="mt-3 max-w-[46rem] border-t border-rule" data-report-brief="">
          {brief.map((row) => {
            const ai = row.origin === "ai"
            return (
              <div key={row.key} data-brief={row.key} className="grid grid-cols-[3.25rem_minmax(0,1fr)] items-baseline gap-x-3 border-b border-rule py-2.5">
                <dt className="print-label text-md">{row.label}</dt>
                <dd>
                  {/* 規則算的列和 AI 寫的列同一個字級與行高：五列讀起來是同一張表 */}
                  <ReportText p={row.paragraph} ai={ai} className={kaiSize.page} />
                </dd>
              </div>
            )
          })}
        </dl>
      ) : r.highlights.length > 0 && (
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
