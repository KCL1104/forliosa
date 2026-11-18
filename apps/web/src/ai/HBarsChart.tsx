import { useEffect, useId, useRef, useState } from "react"
import { InternalLink } from "@/components/internal-link"
import { textAction } from "@/components/text-action"
import { cn } from "@/lib/utils"
import { barScale, foldPlan, labelEm, SPLIT_BARS } from "./bars-layout"
import type { AiChart, AiChartBar as Bar } from "./remote"

/** 橫條的顏色：漲跌色 40%（和市場頁的類股同一種）、墨色（成交比重、法人買超）、鉛筆灰（「其餘合計」、法人賣超） */
const BAR_BG: Record<Bar["tone"], string> = {
  rise: "bg-rise/40",
  fall: "bg-fall/40",
  ink: "bg-ink/35",
  pencil: "bg-chart-bench/55",
}

/** 這一條的顏色：0（持平）一律墨色；伺服器給了認不得的 tone（例如 flat）也當墨色 */
const toneOf = (b: Bar): Bar["tone"] => (b.value === 0 || !(b.tone in BAR_BG) ? "ink" : b.tone)

/** 右邊的數字：價格造成的（漲跌幅、點數）才用漲跌色；家數、口數、比重、金額是墨色（紅綠只給價格）；0 是墨色 */
function displayTone(chart: AiChart, b: Bar): string {
  if (chart.unit !== "pct" && chart.unit !== "points") return "text-ink"
  const t = toneOf(b)
  return t === "rise" ? "text-rise" : t === "fall" ? "text-fall" : "text-ink"
}

type Entry =
  | { kind: "bar"; at: number; bar: Bar; folded: boolean }
  | { kind: "group"; at: number; label: string; folded: boolean }
  | { kind: "gap"; at: number; count: number }

/**
 * 以零為軸的雙向橫條（市場報告的類股、點數貢獻、規模與風格、成交比重、上櫃法人、美股 ETF；畫法同市場頁的 `SectorList`）：
 * 每列是名稱（下面一行 13px 淡墨的補充：家數、集中度、「其餘合計」的說明）、一條橫條、右邊印好的數字。
 * 零軸是 1px 的 `ctl` 線，位置見 `barScale`；長度依最大的絕對值縮放、高 8px。
 * 數字是主角，橫條只幫忙比大小，所以沒有提示框（橫條對螢幕報讀器隱藏，每列念名稱與數字）。有 `href` 的整列連到那一頁（個股頁）。
 *
 * v2（2026-11-18）：
 * - `bench`：橫條欄一條 1px 鉛筆灰虛線，上面 12px 淡墨標「加權 ▼2.31%」；第二行的字底下鋪紙色，線遇到字會斷開。
 * - `fold`：主欄 < 768px 時先列前 N、`keep`、後 N，中間一行淡墨「⋯ 另 17 類」，下面文字鈕「全部 32 類」；≥ 768px 全部列出。
 *   門檻和兩欄排同一個：672–767px（iPad 直式的主欄）不會整串單欄列出 32 類（那是全站最長的版本）。
 *   按「收起」時把圖捲回畫面（`block: "nearest"`，減少動態時不用平滑捲動）：收掉約 1,000px，不然讀者會被留在圖的下面。
 * - 超過 12 條（32 類）時主欄 ≥ 768px 排兩欄，兩半同一個比例、同一個名稱寬度（零軸對齊），各有自己的虛線。
 * - `aside_label`：右邊多一欄 13px 淡墨等寬數字（「較前一日」的「+2.2」），欄名只在頂端寫一次。
 * - `group`：換組時插一行 12px 淡墨小標（「大小型股」）。
 */
export function HBarsChart({ chart }: { chart: AiChart }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const collapsing = useRef(false)
  useEffect(() => {
    if (open || !collapsing.current) return
    collapsing.current = false
    const el = rootRef.current
    const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ;(el?.closest("figure") ?? el)?.scrollIntoView?.({ block: "nearest", behavior: reduce ? "auto" : "smooth" })
  }, [open])
  const bars = chart.bars ?? []
  if (bars.length === 0) return <p className="mt-2 text-base text-ink">沒有資料可以畫。</p>

  const bench = chart.bench ?? null
  const { axis, k } = barScale([...bars.map((b) => b.value), ...(bench ? [bench.value] : [])])
  const benchX = bench ? Math.min(100, Math.max(0, axis + bench.value * k)) : null
  const aside = !!chart.aside_label
  const shown = foldPlan(bars, chart.fold)
  const split = bars.length > SPLIT_BARS
  const n = bars.length

  // 一列一個項目：橫條、分組小標、收起來的那一段（「⋯ 另 17 類」）
  const entries: Entry[] = []
  let group: string | null = null
  bars.forEach((b, i) => {
    const folded = shown ? !shown[i] : false
    if (shown && folded && (i === 0 || shown[i - 1])) {
      let j = i
      while (j < n && !shown[j]) j++
      entries.push({ kind: "gap", at: i, count: j - i })
    }
    const g = b.group ?? null
    if (g && g !== group) {
      let j = i
      while (j < n && (bars[j]!.group ?? null) === g) j++
      entries.push({ kind: "group", at: i, label: g, folded: !!shown && shown.slice(i, j).every((s) => !s) })
    }
    group = g
    entries.push({ kind: "bar", at: i, bar: b, folded })
  })

  const half = split ? Math.ceil(n / 2) : n
  const halves = split ? [entries.filter((e) => e.at < half), entries.filter((e) => e.at >= half)] : [entries]
  const nameCol = split ? `minmax(0,${Math.min(10, Math.max(...bars.map((b) => labelEm(b.label))) + 0.25).toFixed(2)}em)` : "minmax(0,max-content)"
  const cols = `${nameCol} minmax(2.5rem,1fr) minmax(4.5rem,auto)${aside ? " minmax(2.75rem,auto)" : ""}`
  const listIds = halves.map((_, h) => `${id}-bars-${h}`)
  const hidden = (folded: boolean) => folded && !open && "@max-3xl:hidden"

  /** 一列的虛線段：放在橫條欄（grid 的第 2 欄）、蓋滿整列（含下面的格線），各列接成一條；畫在橫條與字的下面 */
  const benchSeg =
    benchX === null ? null : (
      <span aria-hidden data-bench-line="" className="pointer-events-none absolute inset-x-0 top-0 -bottom-px" style={{ gridColumn: "2 / 3" }}>
        <span className="absolute inset-y-0 border-l border-dashed border-chart-bench" style={{ left: `${benchX}%` }} />
      </span>
    )

  const row = (b: Bar) => {
    const width = b.value === 0 ? 0 : Math.max(1.5, Math.abs(b.value) * k)
    return (
      <>
        <span className="max-w-[10em] min-w-0 truncate text-base">{b.label}</span>
        <span aria-hidden className="relative h-2">
          <span className="absolute -inset-y-1 w-px bg-ctl" style={axis === 100 ? { right: 0 } : { left: `${axis}%` }} />
          {width > 0 && (
            <span
              data-bar-tone={toneOf(b)}
              className={cn("absolute inset-y-0 rounded-[1px]", BAR_BG[toneOf(b)])}
              style={b.value > 0 ? { left: `${axis}%`, width: `${width}%` } : { right: `${100 - axis}%`, width: `${width}%` }}
            />
          )}
        </span>
        <span className={cn("num text-right text-base whitespace-nowrap", displayTone(chart, b))}>{b.display}</span>
        {aside && (
          <span className="num text-right text-sm whitespace-nowrap text-ink-2" data-bar-aside="">
            <span className="sr-only">{chart.aside_label} </span>
            {b.aside ?? "—"}
          </span>
        )}
        {/* 補充（家數、集中度、成交值最大的一檔、「其餘合計」的說明）自己一行，橫跨名稱、橫條與數字三欄（手機上一行放得下）；
            字底下鋪紙色，虛線遇到字會斷開 */}
        {b.sub && (
          <span className="col-span-3 -mt-1 text-sm leading-5 text-ink-2">
            {benchX !== null ? <span className="relative bg-paper pr-1">{b.sub}</span> : b.sub}
          </span>
        )}
      </>
    )
  }

  const renderEntry = (e: Entry, last: boolean, firstHalf: boolean) => {
    // 兩欄排的上半欄，最後一列在窄的主欄（上下接著下半欄）要有格線
    const rule = cn("border-b border-rule", last && (split && firstHalf ? "@3xl:border-b-0" : "border-b-0"))
    if (e.kind === "gap") {
      return (
        <li key={`gap-${e.at}`} data-bar-gap="" className={cn("relative col-span-full grid grid-cols-subgrid py-1.5 text-sm text-ink-2", rule, open ? "hidden" : "@3xl:hidden")}>
          {benchSeg}
          <span className="col-span-full">⋯ 另 {e.count} 類</span>
        </li>
      )
    }
    if (e.kind === "group") {
      return (
        <li key={`group-${e.at}`} data-bar-group="" className={cn("relative col-span-full grid grid-cols-subgrid pt-2.5 pb-0.5 text-xs text-ink-2 first:pt-0", rule, hidden(e.folded))}>
          {benchSeg}
          <span className="col-span-full">{e.label}</span>
        </li>
      )
    }
    const b = e.bar
    // 每列用整張圖的欄（subgrid）：名稱欄是最長的名稱那麼寬（最多 10em，再長就截斷），剩下的都給橫條，
    // 手機上橫條才比得出大小；各列的零軸對齊。可以按的列在觸控時至少 44px 高。
    const grid = cn("col-span-full grid min-h-10 grid-cols-subgrid items-center py-1.5", b.href && "pointer-coarse:min-h-11")
    return (
      <li key={`${b.label}-${e.at}`} data-fold={e.folded ? "hidden" : undefined} className={cn("relative col-span-full grid grid-cols-subgrid", rule, hidden(e.folded))}>
        {benchSeg}
        {b.href ? (
          <InternalLink href={b.href} className={cn(grid, "ruled-row -mb-px rounded-xs border-b-0 focus-visible:outline-offset-[-2px]")}>
            {row(b)}
          </InternalLink>
        ) : (
          <div className={grid}>{row(b)}</div>
        )}
      </li>
    )
  }

  // 頂端一列：虛線的標籤（置中在線上，鋪紙色）與右側欄的欄名。兩欄排時下半欄也有，窄的主欄（上下接著）只留上面那一個
  const head = (h: number) =>
    benchX !== null || aside ? (
      <li aria-hidden={benchX === null ? true : undefined} className={cn("col-span-full grid h-5 grid-cols-subgrid items-end text-xs leading-[1.125rem] text-ink-2", h > 0 && "hidden @3xl:grid")}>
        <span />
        <span className="relative h-full">
          {bench && benchX !== null && (
            <span data-bench-label="" className="num absolute top-0 -translate-x-1/2 bg-paper px-1 whitespace-nowrap" style={{ left: `${benchX}%` }}>
              {bench.label}
            </span>
          )}
        </span>
        <span />
        {aside && <span className="text-right whitespace-nowrap">{chart.aside_label}</span>}
      </li>
    ) : null

  return (
    <>
      <div ref={rootRef} className={cn("mt-2", split && "@3xl:grid @3xl:grid-cols-2 @3xl:gap-x-10")}>
        {halves.map((list, h) => (
          <ul key={h} id={listIds[h]} className="grid gap-x-3 text-base" style={{ gridTemplateColumns: cols }} data-chart-bars="">
            {head(h)}
            {list.map((e, i) => renderEntry(e, i === list.length - 1, h === 0))}
          </ul>
        ))}
      </div>
      {shown && (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listIds.join(" ")}
          onClick={() => {
            collapsing.current = open
            setOpen((v) => !v)
          }}
          className={cn(textAction, "mt-1 @3xl:hidden")}
        >
          {open ? "收起" : `全部 ${n} 類`}
        </button>
      )}
    </>
  )
}
