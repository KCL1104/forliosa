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
import { ChevronDownIcon } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useHistory, useIntraday } from "@/api/queries"
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
import { useIsDesktop } from "@/hooks/use-media-query"
import { useResolvedTheme } from "@/hooks/use-theme"
import { useSourceNote } from "@/hooks/use-source-note"
import { cssVarColor } from "@/lib/css-color"
import { closeLabel } from "@/lib/as-of"
import { formatDate, formatNumber, formatPercent, formatPrice, formatPriceLevel } from "@/lib/format"
import { dayTime, importantMoments, movingAverage } from "@/lib/chart-math"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { NotYet } from "./tabs/kit"
import { sourceNotes } from "./text"

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

/** 圖表庫的顯名（Apache-2.0 的 NOTICE 要求標示並連到 TradingView）：登記到頁尾的資料來源 */
const CHART_LIBRARY = { name: "TradingView Lightweight Charts™", licence: "Apache-2.0", href: "https://www.tradingview.com/" }

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
 * 手機上工具列放在區間下面：讀數與圖緊接在價格與部位下面，第一屏就看得到圖（工具列是次要的）。
 * 沒有報價（商用模式的美股）時這個元件不出現（StockPage 不放），原因只在價格那一格說一次。
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
  const desktop = useIsDesktop()
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
  useSourceNote([CHART_LIBRARY, ...sourceNotes(history.data?.sources)])

  useEffect(() => {
    const el = box.current
    if (!el) return
    if (isIntraday ? points.length < 2 : candles.length < 2) return
    const rise = cssVarColor("--rise")
    const fall = cssVarColor("--fall")
    const ink = cssVarColor("--ink")
    const ink2 = cssVarColor("--ink-2")
    // 軸上的標籤（最後價、均價、參考價、十字線）：選取語法的底色——淺色是墨色實底，深色是格線藍底，不是白色實塊
    const labelBg = cssVarColor("--on-bg")
    const labelFg = cssVarColor("--on-fg")
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
      crosshair: { mode: CrosshairMode.Magnet, vertLine: { color: ink2, labelBackgroundColor: labelBg }, horzLine: { color: ink2, labelBackgroundColor: labelBg } },
      // 縱軸與十字線上的價格：和報價同一套小數位（Tick Decimal Rule），十字線落在任意價位時四捨五入到報價的位數
      localization: { locale: "zh-TW", priceFormatter: (p: number) => (comparing ? `${p >= 0 ? "+" : ""}${p.toFixed(1)}%` : formatPriceLevel(p, inst.market, inst.type)), dateFormat: "yyyy/MM/dd" },
      handleScroll: { vertTouchDrag: false },
    })

    if (isIntraday) {
      const ref = intraday.data?.reference_price ?? intraday.data?.prev_close ?? points[0]!.price
      const last = points.at(-1)!.price
      const line = chart.addSeries(LineSeries, { color: last >= ref ? rise : fall, lineWidth: 2, priceLineVisible: false, lastValueVisible: true })
      const axisLabel = { axisLabelColor: labelBg, axisLabelTextColor: labelFg }
      const us = inst.market === "US"
      line.setData(points.map((p) => ({ time: minuteTime(intraday.data!.date, p.t, us), value: p.price })))
      line.createPriceLine({ price: ref, color: ink2, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "參考價", ...axisLabel })
      if (showAvg) line.createPriceLine({ price: position!.avg_cost, color: ink, lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: true, title: "均價", ...axisLabel })
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
        : chart.addSeries(LineSeries, { color: ink, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, autoscaleInfoProvider })
    if (kind === "candle" && !comparing) main.setData(candles.map((c) => ({ time: dayTime(c.t), open: c.o, high: c.h, low: c.l, close: c.c })))
    else main.setData(candles.map((c) => ({ time: dayTime(c.t), value: c.c })))
    // 線圖的最後價：用價格線畫軸上的標籤（不畫線），底色跟著選取語法（線本身的顏色在深色是淡色，會變成白色實塊）
    const axisLabel = { axisLabelColor: labelBg, axisLabelTextColor: labelFg }
    if (!(kind === "candle" && !comparing)) {
      main.createPriceLine({ price: candles.at(-1)!.c, color: ink, lineVisible: false, axisLabelVisible: true, title: "", ...axisLabel })
    }

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
      if (showAvg && !comparing) main.createPriceLine({ price: position!.avg_cost, color: ink, lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: true, title: "均價", ...axisLabel })
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
  // 沒有日線（不是盤中的空狀態）：工具列、讀數都沒有意義，只留空狀態（不是固定高度的圖框）
  const blank = !isIntraday && empty && !history.isError
  const rangeReturn = !isIntraday && candles.length > 1 ? candles.at(-1)!.c / candles[0]!.c - 1 : null

  const price = (p: number | undefined) => formatPrice(p, inst.market, inst.type)
  // 沒有任何價格（這段期間沒有成交）：不放工具列與讀數，只留空狀態
  const toolbar = !blank && (
      <div className={cn("flex flex-wrap items-center gap-1.5 sm:gap-2", !desktop && "mt-3")}>
        <div role="radiogroup" aria-label="圖表類型" className="flex gap-0.5 rounded-sm border border-ctl p-0.5">
          {(["line", "candle"] as const).map((k) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={kind === k}
              disabled={isIntraday && k === "candle"}
              onClick={() => setKind(k)}
              // 觸控：外框裡的按鈕 40px 高，可按範圍用 ::before 上下各多 2px（蓋到外框的內距），合計 44px；一個字的「線」至少 44px 寬
              className="sel-chip relative h-7 rounded-xs px-2.5 text-sm text-ink-2 disabled:opacity-40 pointer-coarse:h-10 pointer-coarse:min-w-11 pointer-coarse:px-3.5 pointer-coarse:before:absolute pointer-coarse:before:inset-x-0 pointer-coarse:before:-inset-y-0.5 pointer-coarse:before:content-['']"
            >
              {k === "line" ? "線" : "K 線"}
            </button>
          ))}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="outline" size="sm" className="pointer-coarse:h-11" disabled={isIntraday} />}>
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
          <DropdownMenuTrigger render={<Button variant="outline" size="sm" className="pointer-coarse:h-11" disabled={isIntraday} />}>
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
        {/* 開關和「線／K 線」同一種外框：按下＝選取語法 (b)，◆ 是圖上標記的圖例 */}
        <div className="ml-auto flex rounded-sm border border-ctl p-0.5">
          <button
            type="button"
            aria-pressed={moments}
            disabled={isIntraday}
            onClick={() => setMoments(!moments)}
            className="press sel-chip relative inline-flex h-7 items-center gap-1.5 rounded-xs px-2.5 text-sm text-ink-2 disabled:opacity-40 pointer-coarse:h-10 pointer-coarse:before:absolute pointer-coarse:before:inset-x-0 pointer-coarse:before:-inset-y-0.5 pointer-coarse:before:content-['']"
          >
            <span aria-hidden className={cn(moments ? "text-chart-ochre" : "text-ctl")}>
              ◆
            </span>
            重要時刻
          </button>
        </div>
      </div>
  )

  return (
    <section aria-label="走勢圖" className="mt-6">
      {desktop && toolbar}

      {!blank && (
      <p className="num mt-2 flex min-h-5 flex-wrap gap-x-3 text-sm text-ink-2" aria-live="off">
        {readout && (
          <>
            <span>{isIntraday ? `今天 ${readout.t}` : formatDate(readout.t)}</span>
            {"o" in readout && readout.o !== undefined && kind === "candle" && (
              <span>
                開 {price(readout.o)} 高 {price(readout.h)} 低 {price(readout.l)}
              </span>
            )}
            <span className="text-ink">收 {price(readout.c)}</span>
            {readout.v !== undefined && <span>量 {inst.market === "US" ? `${formatNumber(readout.v)} 股` : `${formatNumber(Math.round(readout.v / 1000))} 張`}</span>}
            {hover?.moment !== undefined && <span className="text-ink">◆ 單日 {formatPercent(hover.moment)}</span>}
            {!hover && rangeReturn !== null && <span>區間 {formatPercent(rangeReturn)}</span>}
          </>
        )}
      </p>
      )}

      <div
        className={cn(
          "relative w-full transition-opacity",
          blank ? "" : "mt-1 h-[240px] lg:h-[320px]",
          (history.isPlaceholderData || compareHistory.isPlaceholderData) && "opacity-60",
        )}
      >
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

      {/* 連報價都沒有時（美股商用模式），換區間也不會有資料：區間也不放 */}
      {!(blank && !quote) && (
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
        <RangeChips label="區間" value={range} options={RANGES} onChange={setRange} />
        <p className="ml-auto flex flex-wrap gap-x-3 text-sm text-ink-2">
          {showMine && !isIntraday && !empty && (showAvg || marks.some((m) => candles.length > 0 && m.date >= candles[0]!.t)) && <span>B 買進・S 賣出・D 股利{showAvg && "・┈ 均價"}</span>}
          {moments && !isIntraday && momentList.length > 0 && <span>◆ 單日漲跌 ≥ 3%</span>}
          {comparing && <span>- - {COMPARES.find((c) => c.value === compare)?.label}</span>}
          {!comparing && kind === "candle" && mas.length > 0 && <span>{mas.map((n) => `MA${n}`).join("・")}</span>}
        </p>
      </div>
      )}
      {!desktop && toolbar}
      <DataNotes
        notes={!empty && !loading ? [...(!isIntraday ? [...(history.data?.notes ?? []), ...(compare !== "none" ? (compareHistory.data?.notes ?? []) : [])] : []), "價格為未還原收盤價。"] : []}
        className="mt-1"
      />
    </section>
  )
}

/** 這段期間沒有日線：商用模式是存檔還在累積，照後端的 notes 說明（空狀態：上下實線、墨色標題、淡墨原因） */
function NoHistory({ notes, us }: { notes: string[]; us: boolean }) {
  if (notes.length === 0) return <NotYet title="這段期間還沒有成交資料" />
  return (
    <NotYet title={us ? "美股走勢暫時沒有" : "走勢資料累積中"}>
      <DataNotes notes={notes} className="text-md" />
      {!us && <p className="mt-1">官方開放資料只有當天的收盤，從開始存檔那天起每個交易日累積一點，滿兩天就會畫出走勢。</p>}
    </NotYet>
  )
}

/**
 * 1 日（盤中）走勢：沒有。Forliosa 沒有盤中即時報價（合法取得要付費授權），價格都是收盤後公布的收盤價——
 * 和報價下面那一行、資料來源頁的說法一致；不承諾「加入觀察就會記錄盤中走勢」。給一個現在能看的（5 日）。
 * 後端有說明（notes）時照原文接在後面。
 */
function NoIntraday({ inst, quote, notes, onFiveDays }: { inst: InstrumentDetail; quote?: Quote; notes: string[]; onFiveDays: () => void }) {
  return (
    <NotYet
      className="h-full justify-center"
      title="沒有盤中走勢：價格是收盤後公布的收盤價"
      action={
        <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={onFiveDays}>
          看 5 日走勢
        </Button>
      }
    >
      <DataNotes notes={notes} className="text-md" />
      {quote && (
        <p className="num mt-1">
          {closeLabel(quote.as_of)}
          <span className="ml-2 text-ink">{formatPrice(quote.price, inst.market, inst.type)}</span>
        </p>
      )}
    </NotYet>
  )
}
