import { useId } from "react"
import type { MarketReport, ReportFootnote } from "@/api/types"
import { jumpTo, useReport } from "./report-context"

/**
 * 來源（報告的最下面，免責聲明之前）：
 * - 出處：依號碼一條一條列（和每一句後面的上標號碼對得起來）；號碼本身是「回到原句」的連結。
 *   報導寫「媒體・標題（連到原文、另開視窗）・時間」，資料寫資料集與日期。
 * - 媒體數字不一致時，寫哪一家寫多少、本報告以哪一家為準。
 * - 資料的授權顯名、自己整理的行事曆怎麼來的。
 */
export function ReportSources({ report }: { report: MarketReport }) {
  const titleId = useId()
  const { sources, footnotes } = report
  const nothing = footnotes.length === 0 && sources.data.length === 0 && sources.disagreements.length === 0 && sources.manual.length === 0
  if (nothing) return null
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-4">
      <header className="flex min-h-11 items-end border-b border-print pb-2">
        <h3 id={titleId} className="text-lg font-semibold">
          來源
        </h3>
      </header>
      {footnotes.length > 0 && (
        <div>
          <h4 className="text-sm text-ink-2">出處</h4>
          <ol className="mt-1">
            {footnotes.map((f) => (
              <Footnote key={f.n} f={f} />
            ))}
          </ol>
        </div>
      )}
      {sources.disagreements.length > 0 && (
        <div>
          <h4 className="text-sm text-ink-2">媒體的數字不一致</h4>
          <ul className="mt-1 flex flex-col gap-1">
            {sources.disagreements.map((d, i) => (
              <li key={i} className="text-md text-ink">
                {d.text}
              </li>
            ))}
          </ul>
        </div>
      )}
      {sources.data.length > 0 && (
        <div>
          <h4 className="text-sm text-ink-2">資料</h4>
          <ul className="mt-1 flex flex-col gap-0.5">
            {sources.data.map((d) => (
              <li key={d} className="text-sm break-words text-ink-2">
                {d}
              </li>
            ))}
          </ul>
        </div>
      )}
      {sources.manual.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {sources.manual.map((m) => (
            <li key={m} className="text-sm text-ink-2">
              {m}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** 資料與重大訊息的註腳，名稱本身就帶日期（「證交所〈每日收盤行情－大盤統計〉11/16」），不再接一次日期 */
const DATED_LABEL: ReadonlySet<ReportFootnote["kind"]> = new Set(["data", "filing"])

/** 一條出處：號碼（回到原句）＋內容 */
function Footnote({ f }: { f: ReportFootnote }) {
  const { prefix, openSection } = useReport()
  const back = () => {
    // 原句可能在手機上收著的段裡：先打開那一段，下一個畫面再捲過去
    const root = document.querySelector(`[data-report-root="${prefix}"]`)
    const ref = root?.querySelector<HTMLElement>(`[data-fn-ref="${f.n}"]`)
    if (!ref) return
    const section = ref.closest<HTMLElement>("[data-section-key]")
    if (section?.dataset.collapsed === "true") openSection(section.dataset.sectionKey!)
    if (!ref.id) ref.id = `${prefix}fnref-${f.n}`
    requestAnimationFrame(() => jumpTo(ref.id))
  }
  return (
    <li id={`${prefix}fn-${f.n}`} tabIndex={-1} className="grid grid-cols-[2rem_minmax(0,1fr)] items-baseline border-b border-rule py-2 text-md outline-offset-2">
      <a
        href={`#${prefix}fnref-${f.n}`}
        aria-label={`回到出處 ${f.n} 的原句`}
        onClick={(e) => {
          e.preventDefault()
          back()
        }}
        className="num relative self-start rounded-xs text-ink-2 underline decoration-ctl underline-offset-4 hover:text-ink hover:decoration-ink pointer-coarse:before:absolute pointer-coarse:before:-inset-x-3 pointer-coarse:before:-inset-y-3.5 pointer-coarse:before:content-['']"
      >
        {f.n}
      </a>
      <span className="min-w-0 break-words">
        {f.outlet && <span className="text-ink-2">{f.outlet}・</span>}
        {f.url ? (
          <a href={f.url} target="_blank" rel="noopener noreferrer" className="text-ink underline decoration-ctl underline-offset-4 hover:decoration-ink">
            {f.label}
            <span className="text-ink-2"> ↗</span>
            <span className="sr-only">（另開新視窗）</span>
          </a>
        ) : (
          <span className="text-ink">{f.label}</span>
        )}
        {f.date_label && !DATED_LABEL.has(f.kind) && <span className="num text-ink-2">・{f.date_label}</span>}
      </span>
    </li>
  )
}
