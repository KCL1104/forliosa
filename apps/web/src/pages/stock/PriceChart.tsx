import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  PriceScaleMode,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts"
import { ChevronDownIcon, StarIcon } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useHistory, useIntraday, useToggleWatch, useWatchlist } from "@/api/queries"
import type { HistoryRange, InstrumentDetail, Position, PositionMarker, Quote } from "@/api/types"
import { DataNotes } from "@/components/data-notes"
import { RangeChips } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { useResolvedTheme } from "@/hooks/use-theme"
import { cssVarColor } from "@/lib/css-color"
import { formatDate, formatNumber, formatPercent, formatPrice } from "@/lib/format"
import { formatQuote } from "@/lib/tick"
import { dayTime, importantMoments, movingAverage } from "@/lib/chart-math"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"

export type ChartRange = "1D" | HistoryRange
const RANGES: { value: ChartRange; label: string }[] = [
  { value: "1D", label: "1日" },
  { value: "5D", label: "5日" },
  { value: "1M", label: "1月" },
  { value: "6M", label: "6月" },
  { value: "YTD", label: "今年" },
  { value: "1Y", label: "1年" },
  { value: "5Y", label: "5年" },
  { value: "MAX", label: "全部" },
]
const MAS = [
  { n: 5, color: "--chart-ochre", label: "MA5" },
  { n: 20, color: "--chart-blue", label: "MA20" },
  { n: 60, color: "--chart-bench", label: "MA60" },
] as const
const COMPARES = [
  { value: "none", label: "不比較" },
  { value: "^TAIEXTR", label: "加權報酬指數" },
  { value: "0050.TW", label: "元大台灣50" },
] as const

/** 台北時間的「09:01」當成 UTC 顯示（圖表軸以 UTC 呈現） */
const minuteTime = (date: string, hm: string, us: boolean) => {
  let day = date
  if (us && hm < "12:00") day = new Date(Date.parse(`${date}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10)
  return (Date.parse(`${day}T${hm}:00Z`) / 1000) as UTCTimestamp
}

/**
 * 走勢圖：工具列（類型・比較・指標・重要時刻）＋區間。
 * 買進 B／賣出 S／股利 D 標記來自交易歷史（`position/history`，出清後也有）；持有時另有均價虛線。隱私模式全部隱藏。
 * 1 日線需要授權的盤中行情：商用模式沒有點，顯示說明（後端的 notes）。存檔不足時圖下照實寫出 notes。
 */
export function PriceChart({ inst, quote, position, markers }: { inst: InstrumentDetail; quote?: Quote; position: Position | null; markers?: PositionMarker[] }) {
  const [rangeChoice, setRange] = useState<ChartRange | null>(null)
  const range: ChartRange = rangeChoice ?? (position ? "6M" : "1M")
  const [kind, setKind] = useState<"line" | "candle">("line")
  const [compare, setCompare] = useState<string>("none")
  const [mas, setMas] = useState<number[]>([5, 20, 60])
  const [volume, setVolume] = useState(true)
  const [moments, setMoments] = useState(true)
  const privacy = usePrefs((s) => s.privacyMode)
  const theme = useResolvedTheme()
  const convention = usePrefs((s) => s.colorConvention)
  const isIntraday = range === "1D"
  const history = useHistory(inst.symbol, isIntraday ? "5D" : range)
  const compareHistory = useHistory(compare === "none" ? inst.symbol : compare, isIntraday ? "5D" : range)
  const intraday = useIntraday(inst.symbol, isIntraday)
  const box = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<{ t: string; o?: number; h?: number; l?: number; c: number; v?: number; moment?: number } | null>(null)

  const candles = useMemo(() => history.data?.candles ?? [], [history.data])
  const momentList = useMemo(() => (isIntraday ? [] : importantMoments(candles)), [candles, isIntraday])
  const comparing = compare !== "none" && !isIntraday && !!compareHistory.data && compareHistory.data.symbol !== inst.symbol
  const marks = markers ?? position?.markers ?? []
  const showMine = (!!position || marks.length > 0) && !privacy
  const showAvg = !!position && !privacy
  const points = intraday.data?.points ?? []

  useEffect(() => {
    const el = box.current
    if (!el) return
    if (isIntraday ? points.length < 2 : candles.length < 2) return
    const rise = cssVarColor("--rise")
    const fall = cssVarColor("--fall")
    const ink = cssVarColor("--ink")
    const ink2 = cssVarColor("--ink-2")
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: ink2,
        fontFamily: getComputedStyle(document.body).fontFamily,
        fontSize: 12,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVarColor("--chart-grid") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: volume && !isIntraday ? 0.24 : 0.08 }, mode: comparing ? PriceScaleMode.Percentage : PriceScaleMode.Normal },
      timeScale: { borderVisible: false, rightOffset: 2, fixLeftEdge: true, fixRightEdge: true, timeVisible: isIntraday, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Magnet, vertLine: { color: ink2, labelBackgroundColor: ink }, horzLine: { color: ink2, labelBackgroundColor: ink } },
      localization: { locale: "zh-TW", priceFormatter: (p: number) => (comparing ? `${p >= 0 ? "+" : ""}${p.toFixed(1)}%` : formatQuote(p, inst.market, inst.type)), dateFormat: "yyyy/MM/dd" },
      handleScroll: { vertTouchDrag: false },
    })

    if (isIntraday) {
      const ref = intraday.data?.reference_price ?? intraday.data?.prev_close ?? points[0]!.price
      const last = points.at(-1)!.price
      const line = chart.addSeries(LineSeries, { color: last >= ref ? rise : fall, lineWidth: 2, priceLineVisible: false, lastValueVisible: true })
      const us = inst.market === "US"
      line.setData(points.map((p) => ({ time: minuteTime(intraday.data!.date, p.t, us), value: p.price })))
      line.createPriceLine({ price: ref, color: ink2, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "參考價" })
      if (showAvg) line.createPriceLine({ price: position!.avg_cost, color: ink, lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: true, title: "均價" })
      chart.timeScale().fitContent()
      const byTime = new Map(points.map((p) => [minuteTime(intraday.data!.date, p.t, us), p]))
      chart.subscribeCrosshairMove((e) => {
        const p = e.time ? byTime.get(e.time as UTCTimestamp) : undefined
        setHover(p ? { t: p.t, c: p.price, v: p.volume } : null)
      })
      return () => chart.remove()
    }

    // 持有時把均價納入縱軸範圍，均價線才看得到
    const autoscaleInfoProvider = (original: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
      const r = original()
      if (!r || !showAvg || comparing) return r
      const avg = position!.avg_cost
      return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, avg), maxValue: Math.max(r.priceRange.maxValue, avg) } }
    }
    const main =
      kind === "candle" && !comparing
        ? chart.addSeries(CandlestickSeries, { upColor: rise, downColor: fall, wickUpColor: rise, wickDownColor: fall, borderVisible: false, priceLineVisible: false, autoscaleInfoProvider })
        : chart.addSeries(LineSeries, { color: ink, lineWidth: 2, priceLineVisible: false, autoscaleInfoProvider })
    if (kind === "candle" && !comparing) main.setData(candles.map((c) => ({ time: dayTime(c.t), open: c.o, high: c.h, low: c.l, close: c.c })))
    else main.setData(candles.map((c) => ({ time: dayTime(c.t), value: c.c })))

    if (comparing) {
      const cmp = chart.addSeries(LineSeries, { color: cssVarColor("--chart-bench"), lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: true })
      const from = candles[0]!.t
      cmp.setData(compareHistory.data!.candles.filter((c) => c.t >= from).map((c) => ({ time: dayTime(c.t), value: c.c })))
    }
    if (volume) {
      const vol = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false })
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
      vol.setData(candles.map((c, i) => ({ time: dayTime(c.t), value: c.v, color: (i > 0 ? c.c >= candles[i - 1]!.c : c.c >= c.o) ? cssVarColor("--rise", 0.3) : cssVarColor("--fall", 0.3) })))
    }
    if (!comparing) {
      for (const ma of MAS) {
        if (!mas.includes(ma.n) || candles.length <= ma.n) continue
        const s = chart.addSeries(LineSeries, { color: cssVarColor(ma.color), lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        s.setData(movingAverage(candles, ma.n))
      }
    }

    const markers: SeriesMarker<Time>[] = []
    const times = candles.map((c) => c.t)
    const snapTo = (d: string) => times.find((t) => t >= d)
    if (showMine) {
      for (const m of marks) {
        const t = snapTo(m.date)
        if (!t || m.date < times[0]!) continue
        if (m.type === "buy") markers.push({ time: dayTime(t), position: "belowBar", color: ink, shape: "arrowUp", text: "B" })
        else if (m.type === "sell") markers.push({ time: dayTime(t), position: "aboveBar", color: ink, shape: "arrowDown", text: "S" })
        else markers.push({ time: dayTime(t), position: "aboveBar", color: ink2, shape: "circle", text: "D", size: 0.6 })
      }
      if (showAvg && !comparing) main.createPriceLine({ price: position!.avg_cost, color: ink, lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: true, title: "均價" })
    }
    if (moments) {
      for (const m of momentList) markers.push({ time: dayTime(m.t), position: m.ret >= 0 ? "aboveBar" : "belowBar", color: cssVarColor("--chart-ochre"), shape: "circle", size: 0, text: "◆" })
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number))
    if (markers.length) createSeriesMarkers(main, markers)

    chart.timeScale().fitContent()
    const byTime = new Map(candles.map((c) => [dayTime(c.t), c]))
    const momentByDay = new Map(momentList.map((m) => [m.t, m.ret]))
    chart.subscribeCrosshairMove((e) => {
      const c = e.time ? byTime.get(e.time as UTCTimestamp) : undefined
      setHover(c ? { ...c, moment: momentByDay.get(c.t) } : null)
    })
    return () => chart.remove()
    // 依資料、主題、慣例與選項重建（圖表庫不吃 CSS 變數）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data, compareHistory.data, intraday.data, kind, comparing, mas, volume, moments, showMine, showAvg, marks, theme, convention, isIntraday, inst.market])

  const last = candles.at(-1)
  const readout = hover ?? (isIntraday ? (points.length ? { t: points.at(-1)!.t, c: points.at(-1)!.price } : null) : last ? { ...last } : null)
  const loading = isIntraday ? intraday.isLoading : history.isLoading
  const empty = isIntraday ? !intraday.isLoading && points.length < 2 : !history.isLoading && candles.length < 2
  const rangeReturn = !isIntraday && candles.length > 1 ? candles.at(-1)!.c / candles[0]!.c - 1 : null

  return (
    <section aria-label="走勢圖" className="mt-6">
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="圖表類型" className="flex rounded-sm border border-ctl p-0.5">
          {(["line", "candle"] as const).map((k) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={kind === k}
              disabled={isIntraday && k === "candle"}
              onClick={() => setKind(k)}
              className={cn("h-7 rounded-[3px] px-2.5 text-sm text-ink-2 disabled:opacity-40 pointer-coarse:h-10 pointer-coarse:px-3", kind === k && "bg-act text-act-fg")}
            >
              {k === "line" ? "線" : "K 線"}
            </button>
          ))}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="outline" size="sm" disabled={isIntraday} />}>
            比較{compare !== "none" && `：${COMPARES.find((c) => c.value === compare)?.label}`}
            <ChevronDownIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-52">
            <DropdownMenuGroup>
              <DropdownMenuLabel>和誰比較（以區間起點為 0%）</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={compare} onValueChange={(v) => setCompare(v as string)}>
                {COMPARES.filter((c) => c.value !== inst.symbol).map((c) => (
                  <DropdownMenuRadioItem key={c.value} value={c.value}>
                    {c.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="outline" size="sm" disabled={isIntraday} />}>
            指標
            <ChevronDownIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-44">
            {MAS.map((m) => (
              <DropdownMenuCheckboxItem key={m.n} checked={mas.includes(m.n)} onCheckedChange={(on) => setMas(on ? [...mas, m.n] : mas.filter((x) => x !== m.n))}>
                <span aria-hidden className="h-0.5 w-3.5 rounded-full" style={{ background: `var(${m.color})` }} />
                {m.label}
              </DropdownMenuCheckboxItem>
            ))}
            <DropdownMenuCheckboxItem checked={volume} onCheckedChange={setVolume}>
              成交量
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <button
          type="button"
          aria-pressed={moments}
          disabled={isIntraday}
          onClick={() => setMoments(!moments)}
          className="press ml-auto inline-flex h-8 items-center gap-1.5 rounded-sm px-2 text-sm text-ink-2 hover:bg-hov aria-pressed:text-ink disabled:opacity-40 pointer-coarse:h-10"
        >
          <span aria-hidden className={cn(moments ? "text-chart-ochre" : "text-ctl")}>
            ◆
          </span>
          重要時刻
        </button>
      </div>

      <p className="num mt-2 flex min-h-5 flex-wrap gap-x-3 text-sm text-ink-2" aria-live="off">
        {readout && (
          <>
            <span>{isIntraday ? `今天 ${readout.t}` : formatDate(readout.t)}</span>
            {"o" in readout && readout.o !== undefined && kind === "candle" && (
              <span>
                開 {formatPrice(readout.o, inst.market)} 高 {formatPrice(readout.h, inst.market)} 低 {formatPrice(readout.l, inst.market)}
              </span>
            )}
            <span className="text-ink">收 {formatPrice(readout.c, inst.market)}</span>
            {readout.v !== undefined && <span>量 {inst.market === "US" ? `${formatNumber(readout.v)} 股` : `${formatNumber(Math.round(readout.v / 1000))} 張`}</span>}
            {hover?.moment !== undefined && <span className="text-ink">◆ 單日 {formatPercent(hover.moment)}</span>}
            {!hover && rangeReturn !== null && <span>區間 {formatPercent(rangeReturn)}</span>}
          </>
        )}
      </p>

      <div className={cn("relative mt-1 h-[240px] w-full transition-opacity lg:h-[320px]", (history.isPlaceholderData || compareHistory.isPlaceholderData) && "opacity-60")}>
        {(isIntraday ? intraday.isError : history.isError) ? (
          <ErrorState error={isIntraday ? intraday.error : history.error} onRetry={() => void (isIntraday ? intraday.refetch() : history.refetch())} />
        ) : loading ? (
          <Skeleton className="h-full w-full rounded-sm" />
        ) : empty ? (
          isIntraday ? (
            <NoIntraday inst={inst} quote={quote} notes={intraday.data?.notes ?? []} onFiveDays={() => setRange("5D")} />
          ) : (
            <NoHistory notes={history.data?.notes ?? []} us={inst.market === "US"} />
          )
        ) : (
          <div ref={box} className="absolute inset-0" role="img" aria-label={`${inst.name}走勢圖，${RANGES.find((r) => r.value === range)?.label}${rangeReturn !== null ? `，區間 ${formatPercent(rangeReturn)}` : ""}`} />
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
        <RangeChips label="區間" value={range} options={RANGES} onChange={setRange} />
        <p className="ml-auto flex flex-wrap gap-x-3 text-xs text-ink-2">
          {showMine && !isIntraday && !empty && (showAvg || marks.some((m) => candles.length > 0 && m.date >= candles[0]!.t)) && <span>B 買進・S 賣出・D 股利{showAvg && "・┈ 均價"}</span>}
          {moments && !isIntraday && momentList.length > 0 && <span>◆ 單日漲跌 ≥ 3%</span>}
          {comparing && <span>- - {COMPARES.find((c) => c.value === compare)?.label}</span>}
          {!comparing && kind === "candle" && mas.length > 0 && <span>{mas.map((n) => `MA${n}`).join("・")}</span>}
        </p>
      </div>
      {!isIntraday && !empty && <DataNotes notes={[...(history.data?.notes ?? []), ...(compare !== "none" ? (compareHistory.data?.notes ?? []) : [])]} className="mt-1 text-xs" />}
      <p className="mt-1 text-xs text-ink-2">價格為未還原收盤價。圖表由 TradingView Lightweight Charts™ 繪製。</p>
    </section>
  )
}

/** 這段期間沒有日線：商用模式是存檔還在累積（或美股沒有可商用的來源），照後端的 notes 說明 */
function NoHistory({ notes, us }: { notes: string[]; us: boolean }) {
  if (notes.length === 0) return <p className="grid h-full place-items-center text-md text-ink-2">這段期間還沒有成交資料。</p>
  return (
    <div className="flex h-full flex-col items-start justify-center gap-2 border-y border-dashed border-rule px-1">
      <p className="font-medium">{us ? "美股走勢暫時沒有" : "走勢資料累積中"}</p>
      <DataNotes notes={notes} className="max-w-prose text-md" />
      {!us && <p className="max-w-prose text-md text-ink-2">官方開放資料只提供當天的收盤，所以從開始存檔那天起每個交易日累積一點；累積兩天以上就會畫出走勢。</p>}
    </div>
  )
}

function NoIntraday({ inst, quote, notes, onFiveDays }: { inst: InstrumentDetail; quote?: Quote; notes: string[]; onFiveDays: () => void }) {
  const watch = useWatchlist()
  const toggle = useToggleWatch()
  const watching = (watch.data ?? []).some((w) => w.symbol === inst.symbol)
  if (notes.length > 0) {
    // 後端說明為什麼沒有（只用可商用來源時沒有授權的盤中資料）：照實顯示，並給一個現在能看的
    return (
      <div className="flex h-full flex-col items-start justify-center gap-2 border-y border-dashed border-rule px-1">
        <p className="font-medium">盤中走勢需要授權行情，目前提供收盤後資料</p>
        <DataNotes notes={notes} className="max-w-prose text-md" />
        {quote && (
          <p className="num text-md text-ink-2">
            最近收盤 {formatQuote(quote.price, inst.market, inst.type)}
            {quote.as_of && `（${formatDate(quote.as_of.slice(0, 10))}）`}
          </p>
        )}
        <Button variant="outline" size="sm" className="mt-1" onClick={onFiveDays}>
          看 5 日走勢
        </Button>
      </div>
    )
  }
  return (
    <div className="flex h-full flex-col items-start justify-center gap-3 border-y border-dashed border-rule px-1">
      <p className="font-medium">1 日走勢只有持股與觀察清單會記錄</p>
      <p className="max-w-prose text-md text-ink-2">
        {watching
          ? "已經在觀察中，下一次盤中就會開始累積每分鐘的走勢。"
          : `加入觀察後，盤中每分鐘會記下${inst.name}的價格。現在可以先看 5 日或 1 月。`}
        {quote && ` 目前 ${formatPrice(quote.price, inst.market)}。`}
      </p>
      {!watching && (
        <Button variant="outline" size="sm" disabled={toggle.isPending} onClick={() => toggle.mutate({ symbol: inst.symbol, on: true })}>
          <StarIcon />
          加入觀察
        </Button>
      )}
    </div>
  )
}
