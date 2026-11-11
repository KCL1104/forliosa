import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { useEffect, useRef, useState } from "react"
import { useHistory } from "@/api/queries"
import type { Candle, HistoryRange, Market } from "@/api/types"
import { Legend, RangeChips } from "@/components/charts/chart-kit"
import { DemoChop } from "@/components/chop"
import { ChartSkeleton, ErrorState } from "@/components/states"
import { useResolvedTheme } from "@/hooks/use-theme"
import { cssVarColor } from "@/lib/css-color"
import { formatDate, formatNumber, formatPrice, MINUS } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"

const RANGES: { value: HistoryRange; label: string }[] = [
  { value: "1M", label: "1M" },
  { value: "6M", label: "6M" },
  { value: "YTD", label: "YTD" },
  { value: "1Y", label: "1Y" },
  { value: "5Y", label: "5Y" },
  { value: "MAX", label: "全部" },
]
type Interval = "d" | "w" | "m"
const INTERVALS: { value: Interval; label: string }[] = [
  { value: "d", label: "日 K" },
  { value: "w", label: "週 K" },
  { value: "m", label: "月 K" },
]
const MAS = [
  { n: 5, color: "--chart-3", label: "MA5" },
  { n: 20, color: "--chart-1", label: "MA20" },
  { n: 60, color: "--chart-5", label: "MA60" },
] as const

const toTime = (t: string) => (Date.parse(`${t}T00:00:00Z`) / 1000) as UTCTimestamp

/** 日 K 聚合成週 K／月 K */
export function aggregate(candles: Candle[], interval: Interval): Candle[] {
  if (interval === "d") return candles
  const out: Candle[] = []
  const keyOf = (t: string) => {
    if (interval === "m") return t.slice(0, 7)
    const d = new Date(`${t}T00:00:00Z`)
    const monday = new Date(d)
    monday.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7))
    return monday.toISOString().slice(0, 10)
  }
  let cur: Candle | null = null
  let key = ""
  for (const c of candles) {
    const k = keyOf(c.t)
    if (!cur || k !== key) {
      if (cur) out.push(cur)
      cur = { ...c }
      key = k
    } else {
      cur.h = Math.max(cur.h, c.h)
      cur.l = Math.min(cur.l, c.l)
      cur.c = c.c
      cur.v += c.v
    }
  }
  if (cur) out.push(cur)
  return out
}

function movingAverage(candles: Candle[], n: number) {
  const out: { time: UTCTimestamp; value: number }[] = []
  let sum = 0
  candles.forEach((c, i) => {
    sum += c.c
    if (i >= n) sum -= candles[i - n]!.c
    if (i >= n - 1) out.push({ time: toTime(c.t), value: sum / n })
  })
  return out
}

export function KlineTab({ symbol, market }: { symbol: string; market: Market }) {
  const [range, setRange] = useState<HistoryRange>("6M")
  const [interval, setInterval] = useState<Interval>("d")
  const history = useHistory(symbol, range)
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const theme = useResolvedTheme()
  const convention = usePrefs((s) => s.colorConvention)
  const [hover, setHover] = useState<Candle | null>(null)

  const candles = aggregate(history.data?.candles ?? [], interval)
  const last = candles.at(-1)
  const shown = hover ?? last

  useEffect(() => {
    const el = containerRef.current
    if (!el || candles.length === 0) return
    const rise = cssVarColor("--rise")
    const fall = cssVarColor("--fall")
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: cssVarColor("--muted-foreground"),
        fontFamily: getComputedStyle(document.body).fontFamily,
        fontSize: 12,
        attributionLogo: true,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVarColor("--chart-grid") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.26 } },
      timeScale: { borderVisible: false, rightOffset: 2, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: {
        locale: "zh-TW",
        priceFormatter: (p: number) => formatPrice(p, market),
        dateFormat: "yyyy/MM/dd",
      },
    })
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: rise,
      downColor: fall,
      wickUpColor: rise,
      wickDownColor: fall,
      borderVisible: false,
      priceLineVisible: false,
    })
    candle.setData(candles.map((c) => ({ time: toTime(c.t), open: c.o, high: c.h, low: c.l, close: c.c })))
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false })
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    vol.setData(candles.map((c, i) => ({
      time: toTime(c.t),
      value: c.v,
      color: (i > 0 ? c.c >= candles[i - 1]!.c : c.c >= c.o) ? cssVarColor("--rise", 0.35) : cssVarColor("--fall", 0.35),
    })))
    for (const ma of MAS) {
      if (candles.length <= ma.n) continue
      const s = chart.addSeries(LineSeries, { color: cssVarColor(ma.color), lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
      s.setData(movingAverage(candles, ma.n))
    }
    chart.timeScale().fitContent()
    const byTime = new Map(candles.map((c) => [toTime(c.t), c]))
    chart.subscribeCrosshairMove((p) => setHover(p.time ? (byTime.get(p.time as UTCTimestamp) ?? null) : null))
    chartRef.current = chart
    return () => {
      chart.remove()
      chartRef.current = null
    }
    // 依資料、主題、漲跌慣例重建
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data, interval, theme, convention, market])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <RangeChips label="K 線週期" value={interval} options={INTERVALS} onChange={setInterval} />
        <span className="hidden h-5 w-px bg-border sm:block" aria-hidden />
        <RangeChips label="K 線區間" value={range} options={RANGES} onChange={setRange} />
        {history.data?.is_demo && <DemoChop className="ml-auto" />}
      </div>
      {shown && (
        <dl className="num flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-live="off">
          <div className="flex gap-1.5"><dt className="text-muted-foreground">{formatDate(shown.t)}</dt></div>
          {(["o", "h", "l", "c"] as const).map((k) => (
            <div key={k} className="flex gap-1.5">
              <dt className="text-muted-foreground">{{ o: "開", h: "高", l: "低", c: "收" }[k]}</dt>
              <dd>{formatPrice(shown[k], market)}</dd>
            </div>
          ))}
          <div className="flex gap-1.5">
            <dt className="text-muted-foreground">量</dt>
            <dd>{market === "US" ? formatNumber(shown.v) + " 股" : formatNumber(Math.round(shown.v / 1000)) + " 張"}</dd>
          </div>
        </dl>
      )}
      <Legend items={MAS.map((m) => ({ label: m.label, color: `var(${m.color})`, shape: "line" as const }))} />
      <div className={cn("relative h-[380px] w-full transition-opacity sm:h-[440px]", history.isPlaceholderData && "opacity-60")}>
        {history.isError ? (
          <ErrorState error={history.error} onRetry={() => void history.refetch()} />
        ) : candles.length === 0 ? (
          <ChartSkeleton height={420} />
        ) : (
          <div ref={containerRef} className="absolute inset-0" role="img" aria-label={`${symbol} K 線圖，最新收盤 ${last ? formatPrice(last.c, market) : MINUS}`} />
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        價格為未還原收盤價。K 線圖由 TradingView Lightweight Charts™ 繪製（Copyright © 2025 TradingView, Inc.，Apache-2.0）。
      </p>
    </div>
  )
}
