import { useEffect, useId, useMemo, useRef, useState } from "react"
import "@/components/charts/series.css"
import { ChartTooltipBox, Legend } from "@/components/charts/chart-kit"
import { DemoTag } from "@/components/section"
import { cn } from "@/lib/utils"
import {
  axisTicks,
  categories,
  chartForm,
  chartSummary,
  endLabel,
  spanDays,
  spreadLabels,
  tickLabel,
  timeLabel,
  valueAt,
  valueDomain,
  valueLabel,
} from "./chart-geometry"
import type { AiChart } from "./remote"

/** 多條線的分類色：固定順序（series.css，兩個主題各自驗過色弱可分辨） */
const SERIES_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"]

/**
 * 每條線的顏色與線型。顏色跟著「是誰」，不跟著排名：
 * - 只有一條線：墨色（標題已經說了畫的是什麼，不需要圖例）。
 * - 我的報酬率：墨色實線；基準：鉛筆灰虛線（和績效頁同一套）。
 * - 幾檔互相比較：分類色 1～5，照使用者說的順序。
 */
function seriesStyle(chart: AiChart, i: number): { color: string; dash?: string } {
  if (chart.series.length === 1) return { color: "var(--chart-mine)" }
  if (chart.kind === "performance") return i === 0 ? { color: "var(--chart-mine)" } : { color: "var(--chart-bench)", dash: "5 4" }
  return { color: SERIES_COLORS[i % SERIES_COLORS.length]! }
}

const HEIGHT = 188
const TOP = 10
const BOTTOM = 22
const TICK_FONT = 12

/** 12px 的字大約多寬（估計，用來留左右的空間；不量 DOM，伺服器端與測試也算得出來） */
function textWidth(s: string): number {
  let w = 0
  for (const ch of s) w += ch.charCodeAt(0) > 255 ? 12 : /[0-9]/.test(ch) ? 7 : /[.,\s]/.test(ch) ? 3.6 : ch === "%" ? 10.5 : 7.6
  return Math.ceil(w)
}

function useWidth(fallback: number): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
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

/**
 * 對話裡的圖卡：助理說要畫什麼，數字全部是後端讀的資料（`draw_chart`）。
 * 上下各一條格線（帳本不包卡片）；標題、圖例（兩條線以上）、圖、後端的說明與資料來源。
 * 滑過或用方向鍵看每一天的讀數；每條線的起訖另外給螢幕報讀器一句話。
 */
export function ChartCard({ chart }: { chart: AiChart }) {
  const titleId = useId()
  const [wrapRef, width] = useWidth(340)
  const [active, setActive] = useState<number | null>(null)
  const drawable = chart.series.filter((s) => s.points.length > 0)
  const form = chartForm(chart)
  const multi = chart.series.length > 1

  const model = useMemo(() => {
    if (drawable.length === 0) return null
    const { ticks, min, max } = valueDomain(chart, form)
    const step = ticks.length > 1 ? ticks[1]! - ticks[0]! : 1
    const labels = ticks.map((v) => tickLabel(chart, v, step))
    const left = Math.max(...labels.map(textWidth)) + 10
    const ends = form === "line" && multi ? chart.series.map(endLabel) : []
    const right = ends.length ? Math.max(...ends.map(textWidth)) + 14 : 10
    const plotW = Math.max(40, width - left - right)
    const plotH = HEIGHT - TOP - BOTTOM
    const y = (v: number) => TOP + (1 - (v - min) / (max - min || 1)) * plotH
    // 橫軸：日期用時間比例（兩個市場的交易日不同也對得上），月份／季別用類別
    const xs: string[] = chart.x === "date" ? [...new Set(chart.series.flatMap((s) => s.points.map((p) => p.t)))].sort() : categories(chart)
    let x: (t: string) => number
    if (chart.x === "date") {
      const t0 = Date.parse(xs[0]!)
      const t1 = Date.parse(xs[xs.length - 1]!)
      x = (t) => left + (t1 === t0 ? plotW / 2 : ((Date.parse(t) - t0) / (t1 - t0)) * plotW)
    } else if (form === "bar") {
      const band = plotW / xs.length
      x = (t) => left + (xs.indexOf(t) + 0.5) * band
    } else {
      x = (t) => left + (xs.length === 1 ? plotW / 2 : (xs.indexOf(t) / (xs.length - 1)) * plotW)
    }
    return { ticks, labels, step, left, right, plotW, plotH, y, x, xs, ends, min, max }
  }, [chart, drawable.length, form, multi, width])

  const note = (
    <>
      {chart.notes.length > 0 && (
        <ul className="mt-2 flex flex-col gap-0.5 text-sm text-ink-2">
          {chart.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {chart.sources.length > 0 && <p className="mt-1.5 text-xs text-ink-2">資料來源：{chart.sources.join("、")}</p>}
    </>
  )

  const head = (
    <figcaption className="flex items-baseline gap-2 text-md font-semibold text-ink">
      <span id={titleId} className="min-w-0">
        {chart.title}
      </span>
      {chart.is_demo && <DemoTag className="ml-auto shrink-0 font-normal" />}
    </figcaption>
  )

  if (!model) {
    return (
      <figure aria-labelledby={titleId} className="mt-4 border-y border-rule py-3">
        {head}
        <p className="mt-2 text-base text-ink">沒有資料可以畫。</p>
        {note}
      </figure>
    )
  }

  const { ticks, labels, left, right, plotW, plotH, y, x, xs } = model
  const wide = chart.x === "date" && spanDays(chart) > 300
  const xLabel = (t: string) => (wide ? t.slice(0, 7).replace("-", "/") : timeLabel(chart, t))
  const zeroY = model.min <= 0 && model.max >= 0 ? y(0) : null
  const activeT = active !== null ? xs[active] : undefined

  const lastOf = (s: AiChart["series"][number]) => s.points[s.points.length - 1]
  const endYs = model.ends.length
    ? spreadLabels(
        chart.series.map((s) => (lastOf(s) ? y(lastOf(s)!.v) : TOP)),
        14,
        TOP + 4,
        TOP + plotH - 2,
      )
    : []

  const pick = (clientX: number, box: DOMRect) => {
    const px = clientX - box.left
    let best = 0
    let dist = Infinity
    for (const [i, t] of xs.entries()) {
      const d = Math.abs(x(t) - px)
      if (d < dist) {
        dist = d
        best = i
      }
    }
    setActive(best)
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault()
      const cur = active ?? xs.length - 1
      setActive(Math.max(0, Math.min(xs.length - 1, cur + (e.key === "ArrowRight" ? 1 : -1))))
    } else if (e.key === "Home") {
      e.preventDefault()
      setActive(0)
    } else if (e.key === "End") {
      e.preventDefault()
      setActive(xs.length - 1)
    } else if (e.key === "Escape") {
      setActive(null)
    }
  }

  const rows =
    activeT === undefined
      ? []
      : chart.series.flatMap((s, i) => {
          const v = chart.x === "date" ? valueAt(s.points, activeT) : (s.points.find((p) => p.t === activeT)?.v ?? null)
          return v === null ? [] : [{ label: s.name, value: valueLabel(chart, v, s.symbol), color: seriesStyle(chart, i).color, shape: form === "bar" ? ("square" as const) : ("line" as const) }]
        })

  // 柱狀：每個類別一組，柱寬最多 24px，組內留 2px 的紙色間隔
  const band = form === "bar" ? plotW / xs.length : 0
  const barW = form === "bar" ? Math.max(3, Math.min(24, (band * 0.76) / chart.series.length - 2)) : 0

  return (
    <figure aria-labelledby={titleId} className="mt-4 border-y border-rule py-3">
      {head}
      {multi && (
        <Legend
          className="mt-1.5"
          items={chart.series.map((s, i) => ({
            label: s.name,
            color: seriesStyle(chart, i).color,
            shape: form === "bar" ? "square" : "line",
            value: lastOf(s) ? valueLabel(chart, lastOf(s)!.v, s.symbol) : undefined,
          }))}
        />
      )}
      <div
        ref={wrapRef}
        className="relative mt-2 touch-pan-y rounded-xs outline-offset-2 select-none focus-visible:outline-2 focus-visible:outline-ring"
        tabIndex={0}
        role="group"
        aria-label={`${chart.title}：用左右方向鍵逐點看數字`}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
        onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerDown={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setActive(null)}
      >
        <svg role="img" aria-label={chartSummary(chart)} width={width} height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} className="block max-w-full overflow-visible">
          {ticks.map((v, i) => (
            <g key={v}>
              <line x1={left} x2={left + plotW} y1={y(v)} y2={y(v)} stroke={v === 0 && zeroY !== null ? "var(--ctl)" : "var(--chart-grid)"} strokeWidth={1} />
              <text x={left - 6} y={y(v)} textAnchor="end" dominantBaseline="central" fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
                {labels[i]}
              </text>
            </g>
          ))}
          {axisTicks(xs).map((t) => {
            // 刻度的字置中在它的位置上，但整個字留在圖卡裡（頭尾不會被切掉）
            const text = xLabel(t)
            const half = textWidth(text) / 2
            return (
              <text key={t} x={Math.min(Math.max(x(t), half), width - half)} y={HEIGHT - 5} textAnchor="middle" fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
                {text}
              </text>
            )
          })}

          {form === "bar" && activeT !== undefined && <rect x={x(activeT) - band / 2} y={TOP} width={band} height={plotH} fill="var(--hov)" />}
          {form === "line" && activeT !== undefined && <line x1={x(activeT)} x2={x(activeT)} y1={TOP} y2={TOP + plotH} stroke="var(--ctl)" strokeWidth={1} />}

          {form === "bar"
            ? chart.series.map((s, i) => {
                const { color } = seriesStyle(chart, i)
                const offset = (i - (chart.series.length - 1) / 2) * (barW + 2)
                return (
                  <g key={s.name} fill={color}>
                    {s.points.map((p) => {
                      const base = y(0)
                      const top = y(p.v)
                      const h = Math.abs(base - top)
                      const r = Math.min(3, barW / 2, h)
                      const bx = x(p.t) + offset - barW / 2
                      // 資料那一端圓角、貼著基準線的一端是直角；負值往下長
                      const d =
                        p.v >= 0
                          ? `M${bx} ${base}V${top + r}Q${bx} ${top} ${bx + r} ${top}H${bx + barW - r}Q${bx + barW} ${top} ${bx + barW} ${top + r}V${base}Z`
                          : `M${bx} ${base}V${top - r}Q${bx} ${top} ${bx + r} ${top}H${bx + barW - r}Q${bx + barW} ${top} ${bx + barW} ${top - r}V${base}Z`
                      return <path key={p.t} d={d} />
                    })}
                  </g>
                )
              })
            : chart.series.map((s, i) => {
                const { color, dash } = seriesStyle(chart, i)
                const d = s.points.map((p, k) => `${k === 0 ? "M" : "L"}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`).join("")
                const last = lastOf(s)
                return (
                  <g key={s.name}>
                    {s.points.length > 1 && <path d={d} fill="none" stroke={color} strokeWidth={2} strokeDasharray={dash} strokeLinejoin="round" strokeLinecap="round" />}
                    {/* 類別軸的折線（月份、季別）每一期一個點；日期軸只標最後一點 */}
                    {chart.x !== "date" && s.points.length <= 24 && s.points.map((p) => <circle key={p.t} cx={x(p.t)} cy={y(p.v)} r={2.5} fill={color} />)}
                    {last && <circle cx={x(last.t)} cy={y(last.v)} r={4} fill={color} stroke="var(--background)" strokeWidth={2} />}
                  </g>
                )
              })}

          {model.ends.map((label, i) => {
            const s = chart.series[i]!
            const last = lastOf(s)
            if (!last) return null
            const ex = x(last.t)
            const ey = y(last.v)
            const ly = endYs[i]!
            return (
              <g key={s.name}>
                {Math.abs(ly - ey) > 3 && <path d={`M${ex + 5} ${ey}L${left + plotW + 8} ${ly}`} stroke="var(--ctl)" strokeWidth={1} fill="none" />}
                <text x={left + plotW + 10} y={ly} dominantBaseline="central" fontSize={TICK_FONT} fill="var(--ink-2)" className="num">
                  {label}
                </text>
              </g>
            )
          })}

          {form === "line" &&
            activeT !== undefined &&
            chart.series.map((s, i) => {
              const v = chart.x === "date" ? valueAt(s.points, activeT) : (s.points.find((p) => p.t === activeT)?.v ?? null)
              return v === null ? null : <circle key={s.name} cx={x(activeT)} cy={y(v)} r={4} fill={seriesStyle(chart, i).color} stroke="var(--background)" strokeWidth={2} />
            })}
        </svg>
        {activeT !== undefined && rows.length > 0 && (
          <div
            className={cn("pointer-events-none absolute top-1 z-10", x(activeT) > left + plotW / 2 ? "left-0" : "right-0")}
            style={x(activeT) > left + plotW / 2 ? { left } : { right }}
          >
            <ChartTooltipBox title={chart.x === "date" ? timeLabel(chart, activeT, true) : timeLabel(chart, activeT, true)} rows={rows} className="min-w-36" />
          </div>
        )}
        <p className="sr-only" aria-live="polite">
          {activeT !== undefined ? `${timeLabel(chart, activeT, true)}：${rows.map((r) => `${r.label} ${r.value}`).join("、")}` : ""}
        </p>
      </div>
      {note}
    </figure>
  )
}
