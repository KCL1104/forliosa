import { ChevronDownIcon } from "lucide-react"
import { useId, useState } from "react"
import type { ReportCalendar as Spec, ReportCalendarRow } from "@/api/types"
import { InternalLink } from "@/components/internal-link"
import { cn } from "@/lib/utils"

/**
 * 行事曆（今日行事曆、下週行事曆…；都是已排定的事）：依日期分組，每列是時間（13px 淡墨等寬）｜標題（15px）＋類別與相關類股（13px 淡墨）。
 * 同一天裡的 ETF 除息、受邀法說會、市值前 100 以外的重大訊息收成一列（「ETF 除息 25 檔」），可以展開——手機上才不會被淹沒。
 * 個股連到個股頁（站內）；總經數據連到官方頁面（另開視窗，有 ↗）。
 */
export function ReportCalendar({ calendar }: { calendar: Spec }) {
  const titleId = useId()
  return (
    <section aria-labelledby={titleId} data-section-key="calendar" className="flex flex-col">
      <header className="flex min-h-11 items-end gap-3 border-b border-print pb-2">
        <h3 id={titleId} className="min-w-0 flex-1 text-lg font-semibold">
          {calendar.title}
        </h3>
        {/* 手機上長標題（「盤後與下個交易日行事曆（11/17–11/18）」）不能把「資料」擠成直排 */}
        <span className="shrink-0 text-sm text-ink-2">資料</span>
      </header>
      {calendar.groups.length === 0 ? (
        <p className="py-3 text-base text-ink">{calendar.empty_text ?? "這段期間沒有已排定的事件。"}</p>
      ) : (
        <div className="flex flex-col">
          {calendar.groups.map((g) => (
            <div key={g.date} className="flex flex-col">
              <h4 className="num pt-4 pb-1 text-base font-medium">{g.date_label}</h4>
              <ul className="border-t border-rule">
                {g.rows.map((r, i) => (
                  <CalRow key={`${r.title}-${i}`} row={r} />
                ))}
                {g.folded.map((f) => (
                  <Folded key={f.label} label={f.label} rows={f.rows} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {calendar.source_labels.length > 0 && <p className="mt-2 text-xs text-ink-2">資料來源：{calendar.source_labels.join("、")}</p>}
    </section>
  )
}

function CalRow({ row }: { row: ReportCalendarRow }) {
  const meta = [row.kind_label, ...row.sectors].filter(Boolean).join("・")
  return (
    <li className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 border-b border-rule py-2.5 sm:grid-cols-[7.5rem_minmax(0,1fr)]">
      <span className="num pt-0.5 text-sm text-ink-2">{row.time_label ?? "—"}</span>
      <span className="min-w-0">
        <span className="block text-base">
          {row.href ? (
            <InternalLink href={row.href} className="rounded-xs underline decoration-ctl underline-offset-4 hover:decoration-ink pointer-coarse:py-2.5">
              {row.title}
            </InternalLink>
          ) : (
            row.title
          )}
        </span>
        <span className="block text-sm text-ink-2">
          {meta}
          {row.url && (
            <>
              {meta && "・"}
              <a
                href={row.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${row.title}的官方頁面（另開新視窗）`}
                className="rounded-xs underline decoration-ctl underline-offset-4 hover:text-ink hover:decoration-ink pointer-coarse:inline-block pointer-coarse:py-3"
              >
                官方頁面 ↗
              </a>
            </>
          )}
        </span>
      </span>
    </li>
  )
}

function Folded({ label, rows }: { label: string; rows: ReportCalendarRow[] }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <li className="border-b border-rule last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="grid min-h-11 w-full grid-cols-[5.5rem_minmax(0,1fr)_auto] items-center gap-x-3 py-2 text-left hover:bg-hov sm:grid-cols-[7.5rem_minmax(0,1fr)_auto]"
      >
        <span aria-hidden />
        <span className="text-base text-ink">{label}</span>
        <ChevronDownIcon aria-hidden className={cn("size-4 text-ink-2 transition-transform", open && "rotate-180")} />
      </button>
      <ul id={id} hidden={!open} className="border-t border-rule [&>li:last-child]:border-b-0">
        {rows.map((r, i) => (
          <CalRow key={`${r.title}-${i}`} row={r} />
        ))}
      </ul>
    </li>
  )
}
