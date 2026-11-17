import { ChevronDownIcon } from "lucide-react"
import { useId } from "react"
import { ChartCard } from "@/ai/ChartCard"
import { kaiSize } from "@/ai/kai-size"
import type { ReportBlock, ReportSection as Spec } from "@/api/types"
import { cn } from "@/lib/utils"
import { problemText } from "./report-context"
import { ReportTable } from "./ReportTable"
import { ReportText } from "./ReportText"

const AI_LABEL = "AI 依資料與報導整理"

function isAiBlock(b: ReportBlock): boolean {
  return b.type === "text" || b.type === "items" || (b.type === "chart" && b.caption != null)
}

/**
 * 報告的一段：段標題（17px 600）＋右邊 13px 淡墨的來歷（「資料」或「AI 依資料與報導整理」）。
 * 有伺服器的圖或表的段，來歷寫「資料」；這種段裡的 AI 文字，在開始的地方另外標一行 13px 淡墨「AI 依資料與報導整理」
 * （舊的版本伺服器還寫成 AI，前端照區塊自己判斷）。只有 AI 文字的段，來歷才寫「AI 依資料與報導整理」。
 * 手機上 `collapsed_mobile` 的段預設收著，標題本身是按鈕（`aria-expanded`）；桌面一律展開、沒有收合鈕。
 * AI 寫的字是 `.ai-voice`（墨色黑體），資料區塊（圖、表、說明）是墨色的印刷字。
 * 管理員檢視：被拿掉的段照樣顯示，標題下一行墨色「這一段被拿掉：原因」。
 */
export function ReportSection({ section, open, collapsible, onToggle }: { section: Spec; open: boolean; collapsible: boolean; onToggle: () => void }) {
  const titleId = useId()
  const bodyId = useId()
  const ai = section.origin === "ai"
  const mixed = ai && section.blocks.some((b) => b.type === "table" || b.type === "chart")
  const label = mixed ? "資料" : section.origin_label
  const firstAi = mixed ? section.blocks.findIndex(isAiBlock) : -1
  return (
    <section aria-labelledby={titleId} data-section-key={section.key} data-collapsed={collapsible && !open ? "true" : "false"} className="flex flex-col">
      <header className="flex min-h-11 items-end gap-3 border-b border-print pb-2">
        {collapsible ? (
          <h3 className="min-w-0 flex-1">
            <button
              type="button"
              id={titleId}
              aria-expanded={open}
              aria-controls={bodyId}
              onClick={onToggle}
              className="-my-2 flex min-h-11 w-full items-center gap-2 rounded-xs py-2 text-left text-lg font-semibold"
            >
              {section.title}
              <ChevronDownIcon aria-hidden className={cn("size-4 shrink-0 text-ink-2 transition-transform", open && "rotate-180")} />
            </button>
          </h3>
        ) : (
          <h3 id={titleId} className="min-w-0 flex-1 text-lg font-semibold">
            {section.title}
          </h3>
        )}
        <span className="shrink-0 text-sm text-ink-2">{label}</span>
      </header>
      {section.dropped && (
        <p className="mt-2 text-base font-medium text-ink">這一段被拿掉：{section.dropped.reasons.map(problemText).join("、")}</p>
      )}
      <div id={bodyId} hidden={!open} className="flex flex-col gap-5 pt-3 [&>div:first-child_figure]:border-t-0 [&>div:first-child_figure]:pt-1 [&>p:first-child]:border-t-0 [&>p:first-child]:pt-0">
        {section.blocks.map((b, i) => (
          <Block key={i} block={b} ai={ai} mark={i === firstAi} />
        ))}
      </div>
    </section>
  )
}

/** 圖表之間的 AI 文字從這裡開始（13px 淡墨，和段標旁的來歷同一種字） */
function AiMark({ className }: { className?: string }) {
  return <p className={cn("text-sm text-ink-2", className)}>{AI_LABEL}</p>
}

function Block({ block: b, ai, mark }: { block: ReportBlock; ai: boolean; mark: boolean }) {
  switch (b.type) {
    case "text":
      return (
        <div className="flex max-w-[46rem] flex-col gap-3">
          {mark && <AiMark className="-mb-1" />}
          {b.paragraphs.map((p, i) => (
            <ReportText key={i} p={p} ai={ai} className={kaiSize.page} />
          ))}
        </div>
      )
    case "items":
      return (
        <div className="flex max-w-[46rem] flex-col gap-2">
          {mark && <AiMark />}
          <ul className="border-t border-rule">
            {b.items.map((item, i) => (
              <li key={i} className="flex flex-col gap-1 border-b border-rule py-3">
                <p className="text-base font-medium">{item.title}</p>
                {item.meta && <p className="num text-sm text-ink-2">{item.meta}</p>}
                {item.paragraphs.map((p, k) => (
                  <ReportText key={k} p={p} ai={ai} className={cn(kaiSize.page, "mt-1")} />
                ))}
              </li>
            ))}
          </ul>
        </div>
      )
    case "chart": {
      // 類股（32 類）在寬的主欄排兩欄；其他的圖和字一樣寬
      const wide = b.chart.kind === "bars" && (b.chart.bars?.length ?? 0) > 12
      return (
        <div className={cn("flex flex-col", wide ? "@3xl:[&_[data-chart-bars]]:columns-2 @3xl:[&_[data-chart-bars]]:gap-x-10 [&_[data-chart-bars]>li]:break-inside-avoid" : "max-w-[46rem]")}>
          <div className="-mt-4">
            <ChartCard chart={b.chart} />
          </div>
          {b.caption && mark && <AiMark className="mt-2 max-w-[46rem]" />}
          {b.caption && <ReportText p={b.caption} ai={ai} className={cn(kaiSize.page, mark ? "mt-1" : "mt-2", "max-w-[46rem]")} />}
        </div>
      )
    }
    case "table":
      return (
        <div className="max-w-[46rem]">
          <ReportTable table={b.table} />
        </div>
      )
    case "note":
      return <p className="max-w-[46rem] border-y border-rule py-2.5 text-base text-ink">{b.text}</p>
  }
}
