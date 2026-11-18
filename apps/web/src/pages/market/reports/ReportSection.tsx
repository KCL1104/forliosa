import { ChevronDownIcon } from "lucide-react"
import { useId, useState } from "react"
import { ChartCard } from "@/ai/ChartCard"
import { SPLIT_BARS } from "@/ai/bars-layout"
import { kaiSize } from "@/ai/kai-size"
import type { ReportBlock, ReportSection as Spec, ReportTable as TableSpec } from "@/api/types"
import { RangeChips } from "@/components/segmented"
import { cn } from "@/lib/utils"
import { problemText } from "./report-context"
import { ReportTable } from "./ReportTable"
import { ReportText } from "./ReportText"

const AI_LABEL = "AI 依資料與報導整理"

function isAiBlock(b: ReportBlock): boolean {
  return b.type === "text" || b.type === "items" || (b.type === "chart" && b.caption != null)
}

/** 一段裡要畫的東西：一個區塊，或相鄰、同一個 `tab_group` 的幾張表（窄的主欄一次看一張） */
type Unit = { kind: "block"; block: ReportBlock; index: number } | { kind: "tabs"; group: string; tables: TableSpec[]; index: number }

function sectionUnits(blocks: readonly ReportBlock[]): Unit[] {
  const out: Unit[] = []
  blocks.forEach((b, index) => {
    const group = b.type === "table" ? (b.table.tab_group ?? null) : null
    const last = out[out.length - 1]
    if (b.type === "table" && group) {
      if (last?.kind === "tabs" && last.group === group) last.tables.push(b.table)
      else out.push({ kind: "tabs", group, tables: [b.table], index })
      return
    }
    out.push({ kind: "block", block: b, index })
  })
  // 一組只有一張表時照一般的表畫（沒有分頁）
  return out.map((u) => (u.kind === "tabs" && u.tables.length === 1 ? { kind: "block", block: { type: "table", table: u.tables[0]! }, index: u.index } : u))
}

/** 分頁的名稱（RangeChips 的 aria-label） */
const TAB_GROUP_LABEL: Record<string, string> = { movers: "排行", otc_movers: "上櫃排行", margin: "融資增減" }

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
        {sectionUnits(section.blocks).map((u) =>
          u.kind === "tabs" ? <TableTabs key={u.index} group={u.group} tables={u.tables} /> : <Block key={u.index} block={u.block} ai={ai} mark={u.index === firstAi} />,
        )}
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
      // 類股（32 類）用整個主欄寬，在寬的主欄排兩欄（`HBarsChart`）；其他的圖和字一樣寬
      const wide = b.chart.kind === "bars" && (b.chart.bars?.length ?? 0) > SPLIT_BARS
      return (
        <div className={cn("flex flex-col", !wide && "max-w-[46rem]")}>
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

/**
 * 相鄰、同一個 `tab_group` 的表（排行的漲幅｜跌幅｜成交值、融資的增加｜減少）：主欄 < 896px 時上面一組 `RangeChips`
 * （選取語法 (b)），一次只顯示選的那一張；寬的主欄並排（3 張時欄寬 1:1:1.4）。
 * 幾張表的規則一樣時只寫一次：在分頁鈕下面、緊接著表，前面是這一組的名稱（墨色「排行」），不會被讀成上一張表的附註。
 * 並排時各表的標題列等高（subgrid 兩列：標題｜表），標題換成兩行的那一張，表頭也和旁邊的對齊。
 */
function TableTabs({ group, tables }: { group: string; tables: TableSpec[] }) {
  const [picked, setSelected] = useState(tables[0]!.id)
  // 新的一版換了表（即時更新）：選的那一張不在了就回到第一張，窄的主欄不會一張都不顯示
  const selected = tables.some((t) => t.id === picked) ? picked : tables[0]!.id
  const rule = tables.every((t) => t.rule === tables[0]!.rule) ? tables[0]!.rule : null
  const cols = tables.length === 3 ? "@4xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)]" : tables.length === 2 ? "@4xl:grid-cols-2" : "@4xl:grid-cols-3"
  const name = TAB_GROUP_LABEL[group] ?? "表"
  return (
    <div className="flex flex-col gap-2" data-table-tabs={group}>
      <RangeChips
        className="@4xl:hidden"
        label={name}
        value={selected}
        options={tables.map((t) => ({ value: t.id, label: t.tab_label ?? t.title }))}
        onChange={setSelected}
      />
      {rule && (
        <p className="max-w-[46rem] text-sm text-ink-2" data-tabs-rule="">
          <span className="mr-2 font-medium text-ink">{name}</span>
          {rule}
        </p>
      )}
      <div className={cn("@4xl:grid @4xl:grid-rows-[auto_1fr] @4xl:gap-x-6", cols)}>
        {tables.map((t) => (
          <div key={t.id} data-tab-panel={t.id} className={cn("max-w-[46rem] min-w-0 @4xl:row-span-2 @4xl:grid @4xl:grid-rows-subgrid", t.id !== selected && "hidden")}>
            <ReportTable table={rule ? { ...t, rule: null } : t} aligned />
          </div>
        ))}
      </div>
    </div>
  )
}
