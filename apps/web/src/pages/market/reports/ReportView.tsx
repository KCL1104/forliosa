import { useId, useMemo, useState } from "react"
import type { MarketReport, ReportValidation } from "@/api/types"
import { DemoTag } from "@/components/section"
import { useIsDesktop } from "@/hooks/use-media-query"
import { problemText, ReportContext } from "./report-context"
import { ReportCalendar } from "./ReportCalendar"
import { ReportHeader } from "./ReportHeader"
import { ReportNumbers } from "./ReportNumbers"
import { ReportSection } from "./ReportSection"
import { ReportSources } from "./ReportSources"

/**
 * 一份市場報告（讀的頁面；市場頁的「報告」分頁、`/market/reports/<id>`、管理後台的盲測都用它）。由上到下（memo §2.0）：
 * 免責的一句與資料截至 → 名稱、一句話、3 個重點 → 數字欄 → 各段（資料／AI 依資料與報導整理；手機上可以收合）
 * → 行事曆 → 來源 → 完整的免責聲明與「由 Anthropic 的 Claude 模型撰寫」。
 * 整頁沒有卡片、陰影、圖示；紅綠只在漲跌的數字與橫條；字的閱讀寬度 46rem（類股的長圖可以到主欄寬）。
 * `admin`：管理員檢視——每句後面多一段 refs、被拿掉的段照樣顯示並寫原因、上面多一行規則驗證的摘要。
 * `prefix`：同一頁並排兩份時，註腳的錨點加前綴（`a-fn-3`）才不會撞名。
 */
export function ReportView({ report, admin = false, prefix = "" }: { report: MarketReport; admin?: boolean; prefix?: string }) {
  const isDesktop = useIsDesktop()
  // 手機上收著的段，使用者打開的（或點註腳回原句時打開的）
  const [opened, setOpened] = useState<Record<string, boolean>>({})
  const ctx = useMemo(() => ({ prefix, admin, openSection: (key: string) => setOpened((o) => ({ ...o, [key]: true })) }), [prefix, admin])
  const footerId = useId()
  return (
    <ReportContext.Provider value={ctx}>
      <article data-report-root={prefix} data-report-id={report.id} className="@container flex flex-col gap-10">
        <div className="flex flex-col gap-6">
          <ReportHeader report={report} />
          {admin && report.validation && <ValidationSummary v={report.validation} />}
          <ReportNumbers items={report.numbers} />
          {(report.notes.length > 0 || report.is_demo) && (
            <div className="flex flex-col gap-1">
              {report.is_demo && <DemoTag className="self-start" />}
              {report.notes.map((n) => (
                <p key={n} className="text-sm text-ink-2">
                  {n}
                </p>
              ))}
            </div>
          )}
        </div>
        {report.sections.map((s) => {
          const collapsible = !isDesktop && s.collapsed_mobile
          const open = !collapsible || !!opened[s.key]
          return <ReportSection key={s.key} section={s} open={open} collapsible={collapsible} onToggle={() => setOpened((o) => ({ ...o, [s.key]: !open }))} />
        })}
        {report.calendar && <ReportCalendar calendar={report.calendar} />}
        <ReportSources report={report} />
        <footer aria-labelledby={footerId} className="flex max-w-[46rem] flex-col gap-1.5 border-t border-rule pt-3">
          <h3 id={footerId} className="sr-only">
            免責聲明
          </h3>
          <p className="text-sm text-ink-2">{report.disclaimer_full}</p>
          {report.model_line && <p className="text-sm text-ink-2">{report.model_line}</p>}
        </footer>
      </article>
    </ReportContext.Provider>
  )
}

/** 管理員檢視的一行摘要：初稿有幾個問題、修正之後還剩幾個、拿掉幾段、有沒有跑合規判讀 */
function ValidationSummary({ v }: { v: ReportValidation }) {
  const parts = [
    `初稿問題 ${v.first_problems.length} 個`,
    v.revised ? `修正後 ${v.final_problems.length} 個` : "沒有修正",
    `拿掉 ${v.dropped.length} 段`,
    v.compliance_ran ? "合規判讀有跑" : "合規判讀沒有跑",
    ...(v.mentions_anthropic ? ["提到 Anthropic"] : []),
  ]
  const codes = [...new Set(v.first_problems.map((p) => p.code))]
  return (
    <div className="max-w-[46rem] border-y border-rule py-2.5" data-validation="">
      <p className="num text-sm text-ink">{parts.join("・")}</p>
      {codes.length > 0 && <p className="text-sm text-ink-2">初稿：{codes.map(problemText).join("、")}</p>}
    </div>
  )
}
