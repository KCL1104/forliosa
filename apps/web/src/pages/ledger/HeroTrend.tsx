import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import type { PerformancePoint } from "@/api/types"
import { PlainLink } from "@/app/links"
import { Masked } from "@/components/finance"
import { RangeChips } from "@/components/segmented"
import { Skeleton } from "@/components/ui/skeleton"
import { useLedgerClose } from "@/hooks/use-close"
import { useIsDesktop } from "@/hooks/use-media-query"
import { direction, directionGlyph, formatDateShort, formatMoney, formatPercent, toneClass } from "@/lib/format"
import {
  compactTicks,
  dateAxis,
  investedVisible,
  needsYear,
  RANGE_TITLE,
  rangeReturn,
  TREND_RANGES,
  trendDomain,
  trendState,
  trendWindow,
  type TrendRange,
} from "@/lib/trend-range"
import { cn } from "@/lib/utils"
import type { LedgerView } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { useLedgerPrefs } from "./ledger-prefs"
import { trendClipNote, trendMissingReason } from "./trend-reason"
import { useTrendRange } from "./use-trend-range"

/**
 * 總資產走勢（產品負責人 2026-11-17 選方案 B）：主數字正下方、和主欄一樣寬，手機與桌面同一個元件。
 * 由上到下：讀數（固定兩行）→ 圖（桌面 160px、手機 120px）→ 區間（靠左）→ 歷史短（2～6 個收盤）時的一行說明。
 * - 資料：一次 `usePerformance("ALL")`（不帶基準），區間在前端切（`lib/trend-range.ts`），換區間不再問伺服器。
 *   只用官方收盤價（存檔從 2026/11/12 起），不用 Yahoo 回補。
 * - 滑過、按住橫拖、方向鍵：讀數換成那一天的值；上面的大數字不變（永遠是最新收盤）。
 * - 自己畫 SVG（照 `ai/ChartCard.tsx`）：總資產 2px 墨色線、最後一點 8px 圓點＋2px 紙色外圈；
 *   投入本金 1.5px 鉛筆灰階梯線，縱軸只看總資產，投入本金不在範圍裡就不畫。
 * - 區間按鈕每個分段都放在這裡（整頁只有一排，績效分段跟著這一排；`useTrendChipsShown`）：
 *   這一塊的高度不跟著分段變，切分段時分段列不會上下跳。
 * - 畫得出走勢就放七顆區間按鈕（2026-11-17 負責人要求；歷史短時也放）。比資料長的區間畫全部的資料，標題照樣寫
 *   「近 3 個月」，第二行寫「只有 11/12 – 11/17 的資料」（`rangeExceedsData`），不讓人以為那是三個月的報酬。
 */

const TOP = 8
const AXIS = 22
const TICK_FONT = 12
/** 按住後橫向拖超過這麼多 px 才開始逐點看（直向照常捲動頁面） */
const DRAG_SLOP = 8

/** 12px 的字大約多寬（估計，用來留縱軸刻度的空間） */
function textWidth(s: string): number {
  let w = 0
  for (const ch of s) w += ch.charCodeAt(0) > 255 ? 12 : /[0-9]/.test(ch) ? 7 : /[.,\s/]/.test(ch) ? 3.6 : 7.6
  return Math.ceil(w)
}

function useWidth(fallback: number): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  // 第一次畫之前先量（不先用猜的寬度畫一次再跳）
  useLayoutEffect(() => {
    const w = Math.floor(ref.current?.clientWidth ?? 0)
    if (w > 0) setWidth(w)
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry!.contentRect.width)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

const pctText = (r: number) => formatPercent(Math.abs(r), { signed: false, decimals: Math.abs(r) >= 0.1 ? 1 : 2 })

/** 報酬：和主數字列的 Delta 同一套（漲跌色、▲▼、10% 以下兩位小數） */
function Ret({ value }: { value: number | null }) {
  const d = direction(value)
  return (
    <span className={cn("num whitespace-nowrap", toneClass(d))}>
      {directionGlyph(d)}
      {value === null ? "—" : pctText(value)}
      <span className="sr-only">{d === "up" ? "上漲" : d === "down" ? "下跌" : "持平"}</span>
    </span>
  )
}

/** 給螢幕報讀器的報酬（不念 ▲▼） */
function retSpeech(r: number | null): string {
  const d = direction(r)
  return r === null ? "算不出來" : d === "up" ? `上漲 ${pctText(r)}` : d === "down" ? `下跌 ${pctText(r)}` : "持平"
}

/**
 * 走勢畫不出來、而且後端說了原因時：一行淡墨原因，連到績效（手機也看得到；觸控 44px）。
 * 每個分段都放、一樣高（換分段時分段列不跳）；已經在績效分段時不連到自己，只是一行字。
 */
function TrendMissing({ reason, linked }: { reason: string; linked: boolean }) {
  const box = "inline-flex items-center text-sm text-ink-2 max-lg:min-h-11 pointer-coarse:min-h-11"
  return (
    <p className="mt-4 lg:mt-6">
      {linked ? (
        <PlainLink to="/" search={{ view: "performance" }} className={cn(box, "underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink")}>
          總資產走勢：{reason}
        </PlainLink>
      ) : (
        <span className={box}>總資產走勢：{reason}</span>
      )}
    </p>
  )
}

export function HeroTrend({ view }: { view: LedgerView }) {
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const { perf, range, setRange } = useTrendRange()
  const desktop = useIsDesktop()
  if (!showTrend || perf.isError) return null
  if (!perf.data) return <Skeleton aria-label="總資產走勢載入中" className="mt-6 h-[224px] w-full rounded-sm lg:mt-8 lg:h-[252px]" />
  const series = perf.data.series
  const notes = perf.data.notes ?? []
  const state = trendState(series.length)
  if (state === "missing") {
    const reason = trendMissingReason(notes)
    return reason ? <TrendMissing reason={reason} linked={view !== "performance"} /> : null
  }
  // 2～6 個收盤：區間按鈕下面一行說明（後端的原文＋目前幾個收盤日）。每個分段都寫同一句（高度不跟著分段變）；
  // 績效分段的說明因此不再重複這一句
  const clipNote = trendClipNote(perf.data)
  const shortNote =
    state === "short" ? (
      <>
        {/* 句號跟著前一段（折行時留在行尾，不會有「・」掛在行尾或開頭） */}
        {clipNote?.split(/(?<=，)/).map((part, i, parts) => (
          <span key={part} className="whitespace-nowrap">
            {part}
            {i === parts.length - 1 && "。"}
          </span>
        ))}
        <span className="whitespace-nowrap">目前 {series.length} 個收盤日</span>
      </>
    ) : null
  return (
    <TrendBand
      series={series}
      range={range}
      onRange={setRange}
      height={desktop ? 160 : 120}
      desktop={desktop}
      few={state === "short"}
      shortNote={shortNote}
    />
  )
}

function TrendBand({
  series,
  range,
  onRange,
  height,
  desktop,
  few,
  shortNote,
}: {
  series: PerformancePoint[]
  range: TrendRange
  onRange: (r: TrendRange) => void
  height: number
  desktop: boolean
  /** 2～6 個收盤：每一點一個圓點 */
  few: boolean
  shortNote: React.ReactNode
}) {
  const privacy = usePrefs((s) => s.privacyMode)
  const close = useLedgerClose()
  const [wrapRef, width] = useWidth(desktop ? 900 : 335)
  const [active, setActive] = useState<number | null>(null)
  const [fromKeys, setFromKeys] = useState(false)
  const drag = useRef<{ id: number; x: number; y: number; on: boolean } | null>(null)

  const win = useMemo(() => trendWindow(series, range), [series, range])
  const slice = win.points
  const n = slice.length
  const first = slice[0]!
  const last = slice[n - 1]!
  // 區間的起始日：和績效分段寫的期間同一天（1 月以上的第一點是前一個收盤，當基準畫，不算起始日）
  const from = slice[win.from]!
  const days = slice.map((p) => p.t)
  // 1 年的起始日是去年的同一天，要寫年份；比資料長時畫的是實際的那幾天，跨了年才寫
  const withYear = (range === "1Y" && !win.exceeds) || needsYear(days)
  const day = (t: string, weekday = false) => (withYear ? `${t.slice(0, 4)}/` : "") + formatDateShort(t, weekday)
  const title = range === "ALL" ? `${day(from.t)} 起` : RANGE_TITLE[range]
  // 第二行的期間。比資料長：照實寫只有哪幾天的資料（「只有」放最前面，320px 放不下被截斷時也還看得到）
  const span = `${day(from.t)} – ${day(last.t)}`
  const period = win.exceeds ? `只有 ${span} 的資料` : span
  const total = rangeReturn(win)

  const model = useMemo(() => {
    const { ticks, min, max } = trendDomain(slice.map((p) => p.market_value))
    const labels = compactTicks(ticks)
    const left = privacy ? 4 : Math.max(...labels.map(textWidth)) + 10
    const right = 6
    const plotW = Math.max(40, width - left - right)
    const plotH = height - TOP - AXIS
    const y = (v: number) => TOP + (1 - (v - min) / (max - min || 1)) * plotH
    // 每個收盤日等寬，週末與假日不留空（和個股走勢圖一樣）
    const x = (i: number) => left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW)
    const line = slice.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p.market_value).toFixed(1)}`).join("")
    const showInvested = investedVisible(slice, min, max)
    const invested = showInvested
      ? slice.map((p, i) => (i === 0 ? `M${x(0).toFixed(1)} ${y(p.net_invested).toFixed(1)}` : `H${x(i).toFixed(1)}V${y(p.net_invested).toFixed(1)}`)).join("")
      : null
    return { ticks, labels, left, plotW, plotH, y, x, line, invested }
  }, [slice, n, width, height, privacy])
  const { ticks, labels, left, plotW, plotH, y, x } = model

  // 橫軸：短區間只標起訖（起始日和讀數第二行同一天，基準收盤那一點不標）；三個月以上每月第一個交易日，放不下的跳過
  const axis = dateAxis(days)
  const xLabels: { i: number; text: string; anchor: "start" | "middle" | "end"; at: number }[] = []
  if (!axis.long) {
    const ends = [...new Set(axis.ticks.map((i) => (i === 0 ? win.from : i)))]
    for (const i of ends) {
      const text = withYear ? `${days[i]!.slice(0, 4)}/${axis.format(days[i]!)}` : axis.format(days[i]!)
      xLabels.push({ i, text, anchor: i === ends[0] && ends.length > 1 ? "start" : "end", at: x(i) })
    }
  } else {
    let lastEnd = -Infinity
    for (const i of axis.ticks) {
      const text = axis.format(days[i]!)
      const half = textWidth(text) / 2
      const at = Math.min(Math.max(x(i), left + half), width - half)
      if (at - half < lastEnd + 12) continue
      xLabels.push({ i, text, anchor: "middle", at })
      lastEnd = at + half
    }
  }

  const pick = (clientX: number, box: DOMRect) => {
    const px = clientX - box.left
    const i = n === 1 ? 0 : Math.round(((px - left) / plotW) * (n - 1))
    setActive(Math.max(0, Math.min(n - 1, i)))
    setFromKeys(false)
  }

  const onKey = (e: React.KeyboardEvent) => {
    let next: number | null | undefined
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") next = Math.max(0, Math.min(n - 1, (active ?? n - 1) + (e.key === "ArrowRight" ? 1 : -1)))
    else if (e.key === "Home") next = 0
    else if (e.key === "End") next = n - 1
    else if (e.key === "Escape" && active !== null) next = null
    if (next === undefined) return
    e.preventDefault()
    setActive(next)
    setFromKeys(next !== null)
  }

  const a = active !== null ? slice[active] : undefined
  // 最後一點：上市、上櫃的收盤日不同時照主數字列的寫法（「上市 11/16・上櫃 11/13 收盤」）
  const splitLabel = /上市.*上櫃|上櫃.*上市/.test(close.label) ? close.label.replace(/・盤中不更新$/, "") : null
  const activeDay = a ? (active === n - 1 && splitLabel ? splitLabel : `${day(a.t, true)}收盤`) : ""
  const activeRet = active !== null ? rangeReturn(win, active) : null
  const svgTitle = win.exceeds ? `${title}，${period}` : title
  const svgLabel = privacy
    ? `${svgTitle}，總資產報酬${retSpeech(total)}`
    : `${svgTitle}，總資產從 ${formatMoney(first.market_value)} 到 ${formatMoney(last.market_value)}，報酬${retSpeech(total)}`

  return (
    <section aria-label="總資產走勢" className="mt-6 lg:mt-8">
      {/* 讀數：固定兩行（高度不變，畫面不跳）；不做跟著游標跑的浮動框，手指不會擋住數字 */}
      <div className="h-11">
        {a ? (
          <>
            {/* 320px、上市與上櫃收盤日不同（「上市 11/17・上櫃 11/14 收盤」）時放不下：截斷的是日期，金額一定完整 */}
            <p className="num flex items-baseline gap-x-4 overflow-hidden text-base leading-6 whitespace-nowrap text-ink-2">
              <span className="min-w-0 truncate">{activeDay}</span>
              {privacy ? <Masked className="shrink-0 text-ink" /> : <span className="shrink-0 font-semibold text-ink">{formatMoney(a.market_value)}</span>}
            </p>
            {/* 隱私模式：遮住的「••••」和「・」連在一起分不開，改用空白隔開 */}
            <p className={cn("num flex items-baseline overflow-hidden text-sm leading-5 whitespace-nowrap text-ink-2", privacy && "gap-x-4")}>
              <span>投入本金 {privacy ? <Masked /> : formatMoney(a.net_invested)}</span>
              {!privacy && <span aria-hidden>・</span>}
              <span>
                報酬 <Ret value={activeRet} />
              </span>
            </p>
          </>
        ) : (
          <>
            <p className="flex items-baseline gap-x-4 overflow-hidden text-base leading-6 whitespace-nowrap text-ink">
              <span className="font-medium">{title}</span>
              <span className="text-ink-2">
                報酬 <Ret value={total} />
              </span>
            </p>
            <p className="num flex items-baseline gap-3 text-sm leading-5 whitespace-nowrap text-ink-2">
              <span className="min-w-0 truncate">{period}</span>
              {model.invested && (
                // 圖例只有一項：鉛筆灰階梯線是投入本金（墨色線就是總資產）
                <span className="ml-auto inline-flex shrink-0 items-center gap-1.5">
                  <span aria-hidden className="inline-block w-3.5 border-t-[1.5px] border-chart-bench" />
                  投入本金
                </span>
              )}
            </p>
          </>
        )}
      </div>

      <div
        ref={wrapRef}
        className="relative mt-2 touch-pan-y rounded-xs outline-offset-2 select-none [-webkit-touch-callout:none] focus-visible:outline-2 focus-visible:outline-ring"
        tabIndex={0}
        role="group"
        aria-label="總資產走勢：用左右方向鍵逐點看數字"
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
        onPointerDown={(e) => {
          if (e.pointerType === "mouse") return pick(e.clientX, e.currentTarget.getBoundingClientRect())
          // 觸控：先記下按的位置，橫向拖過門檻才開始逐點看（直向是捲動頁面，交給瀏覽器）
          drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, on: false }
        }}
        onPointerMove={(e) => {
          if (e.pointerType === "mouse") return pick(e.clientX, e.currentTarget.getBoundingClientRect())
          const d = drag.current
          if (!d || d.id !== e.pointerId) return
          if (!d.on) {
            const dx = Math.abs(e.clientX - d.x)
            const dy = Math.abs(e.clientY - d.y)
            if (dx < DRAG_SLOP || dx < dy) return
            d.on = true
            e.currentTarget.setPointerCapture?.(e.pointerId)
          }
          pick(e.clientX, e.currentTarget.getBoundingClientRect())
        }}
        onPointerUp={(e) => {
          if (e.pointerType === "mouse") return
          drag.current = null
          setActive(null)
        }}
        onPointerCancel={() => {
          drag.current = null
          setActive(null)
        }}
        onPointerLeave={(e) => {
          if (e.pointerType === "mouse") setActive(null)
        }}
      >
        <svg role="img" aria-label={svgLabel} width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block max-w-full overflow-visible">
          {ticks.map((v, i) => (
            <g key={v}>
              <line x1={left} x2={left + plotW} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth={1} />
              {/* 隱私模式：照樣畫線，但不標金額 */}
              {!privacy && (
                <text x={left - 8} y={y(v)} textAnchor="end" dominantBaseline="central" fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
                  {labels[i]}
                </text>
              )}
            </g>
          ))}
          {xLabels.map((l) => (
            <text key={l.i} x={l.at} y={height - 5} textAnchor={l.anchor} fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
              {l.text}
            </text>
          ))}

          {a && <line x1={x(active!)} x2={x(active!)} y1={TOP} y2={TOP + plotH} stroke="var(--ctl)" strokeWidth={1} />}

          {model.invested && <path d={model.invested} fill="none" stroke="var(--chart-bench)" strokeWidth={1.5} data-series="invested" />}
          <path d={model.line} fill="none" stroke="var(--chart-mine)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" data-series="total" />
          {/* 2～6 個收盤：每個收盤日一個 7px 圓點，2 點不會看起來像一條趨勢線 */}
          {few && slice.map((p, i) => <circle key={p.t} cx={x(i)} cy={y(p.market_value)} r={3.5} fill="var(--chart-mine)" data-point="close" />)}
          <circle cx={x(n - 1)} cy={y(last.market_value)} r={4} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={2} />
          {a && <circle cx={x(active!)} cy={y(a.market_value)} r={4} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={2} />}
        </svg>
        {/* 只在用鍵盤移動時念（滑鼠滑過不念） */}
        <p className="sr-only" aria-live="polite">
          {a && fromKeys ? `${activeDay}，總資產 ${privacy ? "已隱藏" : formatMoney(a.market_value)}，投入本金 ${privacy ? "已隱藏" : formatMoney(a.net_invested)}，報酬${retSpeech(activeRet)}` : ""}
        </p>
      </div>

      {/* 七顆一律放（比資料長的也可以選）；歷史短時說明在按鈕下面——按鈕的位置和歷史夠長以後一樣 */}
      <RangeChips className="mt-2" label="走勢區間" value={range} options={TREND_RANGES} onChange={onRange} />
      {shortNote && <p className="mt-1.5 text-sm text-ink-2">{shortNote}</p>}
    </section>
  )
}
