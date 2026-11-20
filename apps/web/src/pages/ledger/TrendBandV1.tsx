import { useMemo, useRef, useState } from "react"
import type { PerformanceComposition, PerformancePoint } from "@/api/types"
import { useSummary } from "@/api/queries"
import { Masked } from "@/components/finance"
import { RangeChips } from "@/components/segmented"
import { useLedgerClose } from "@/hooks/use-close"
import { decompose, dividendsByDay, estimatedRuns, fromZero, inSpans, profitDomain, snapDividends, spanIndexes } from "@/lib/asset-composition"
import { direction, formatDateShort, formatMoney, toneClass } from "@/lib/format"
import { compactTicks, dateAxis, investedVisible, needsYear, RANGE_TITLE, rangeReturn, TREND_RANGES, trendDomain, trendWindow, type TrendRange } from "@/lib/trend-range"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { CompositionLine } from "./CompositionLine"
import { trendEstimatedText } from "./composition-text"
import { AXIS, COMP_TICKS, COMP_TOP, DIVIDEND_SNAP, DRAG_SLOP, indexes, pathOf, retSpeech, textWidth, TICK_FONT, TOP, useWidth } from "./trend-chart"
import { trendReferenceLine } from "./trend-reason"
import { TrendReturn as Ret } from "./TrendReturn"

/**
 * 資產組成的走勢 v1（留著給產品負責人比較；網址 `?composition=v1`，見 `trend-chart.ts` 的 `readCompositionChart`）：
 * 圖下面多一格「組成」，和上面共用橫軸：從區間的基準收盤起，投入本金變了多少（鉛筆灰階梯線）、損益多少（墨色線，不含股利），
 * 兩條都從 0 開始、同一個縱軸。上面那一格和改版以前一樣（縱軸只看總資產，投入本金不在範圍裡就不畫）。
 * 預設的是 v2（`HeroTrend.tsx` 的 `TrendBand`：一張圖，本金線＋賺虧塗色）。這個檔案是 v1 原樣搬過來的，
 * 下面那一句拆解（`CompositionLine`）和 v2 共用，所以用的是 v2 的說法（本金、賺的／虧的）。
 * 不要 v1 了：刪掉這個檔案和 `HeroTrend.tsx` 裡選版本的那一行。
 */

/** 兩格之間、組成那一格的標籤列 */
const COMP_GAP = 6
const COMP_STRIP = 20

/** 組成那一格的刻度：0 寫「0」，其他照縱軸的精簡寫法（「120萬」「−50萬」） */
function profitTickLabel(v: number): string {
  if (v === 0) return "0"
  return `${v < 0 ? "−" : ""}${compactTicks([Math.abs(v)])[0]}`
}

export function TrendBandV1({
  series,
  referenceUntil,
  range,
  onRange,
  height,
  desktop,
  few,
  shortNote,
  composition,
}: {
  series: PerformancePoint[]
  /** 後端的 `reference_until`：這一天（含）以前用 Yahoo 參考價估值 */
  referenceUntil: string | null
  /** 資產組成（原型）：舊版後端沒有，這時和以前一模一樣 */
  composition?: PerformanceComposition
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
  // 資產組成：「全部」的拆解寫全部領過的股利（主數字的 `dividend_income`）
  const lifetimeDividends = useSummary().data?.dividend_income ?? null
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
  const days = useMemo(() => slice.map((p) => p.t), [slice])
  // 1 年的起始日是去年的同一天，要寫年份；比資料長時畫的是實際的那幾天，跨了年才寫
  const withYear = (range === "1Y" && !win.exceeds) || needsYear(days)
  const day = (t: string, weekday = false) => (withYear ? `${t.slice(0, 4)}/` : "") + formatDateShort(t, weekday)
  const title = range === "ALL" ? `${day(from.t)} 起` : RANGE_TITLE[range]
  // 第二行的期間。比資料長：照實寫只有哪幾天的資料（「只有」放最前面，320px 放不下被截斷時也還看得到）
  const span = `${day(from.t)} – ${day(last.t)}`
  const period = win.exceeds ? `只有 ${span} 的資料` : span
  const total = rangeReturn(win)
  // 區間用到存檔開始以前的 Yahoo 參考價：區間按鈕下面一行（和績效分段同一句，那邊就不再寫）
  const referenceLine = trendReferenceLine({ series, reference_until: referenceUntil }, range, withYear)

  // 資產組成：股利（每天一筆）、估計的那一段在這幾天裡的位置
  const comp = composition
  // 「全部」與區間比資料長：從 0 起算、寫現在的組成（和報酬的分母同一個規則，`fromZero`）
  const whole = fromZero(win, range)
  // 股利對到收盤日（週末、假日領的算在下一個收盤日）。從基準收盤起算的區間，基準收盤那天的股利不算進區間——
  // 句子不算，記號、圖例、滑過的讀數也不放，三樣對得起來
  const markFrom = whole ? 0 : 1
  const snapped = useMemo(() => snapDividends(comp?.dividends ?? [], series.map((p) => p.t)), [comp, series])
  const divs = useMemo(() => {
    const inWindow = new Set(days.slice(markFrom))
    return dividendsByDay(snapped.filter((d) => inWindow.has(d.t)))
  }, [snapped, days, markFrom])
  const est = useMemo(() => spanIndexes(days, comp?.estimated), [days, comp])
  // 窄的時候（手機）組成那一格的標籤分兩行、金額寫完整（一行放不下，不截斷數字）
  const narrow = width < 480
  const strip = narrow ? COMP_STRIP * 2 : COMP_STRIP

  const model = useMemo(() => {
    const { ticks, min, max } = trendDomain(slice.map((p) => p.market_value))
    const labels = compactTicks(ticks)
    // 組成那一格（只有資產組成時）：從區間的基準收盤起，投入本金變了多少（加碼／拿回）、損益多少，兩條都從 0 開始、同一個縱軸。
    // 「全部」從 0 起算（第一筆以前什麼都沒有），所以就是現在的投入本金與累積損益。
    // 不直接畫累積損益對 0：短的區間累積損益變化小，對 0 畫會是一條平線（和把投入本金算進總資產縱軸同一個問題）
    // 金額先四捨五入到元再相減（和下面那一句 `decompose` 同一個算法）：標籤和句子的數字一樣，總資產＝本金＋損益
    const base0 = whole || !slice[0] ? { inv: 0, mv: 0 } : { inv: Math.round(slice[0].net_invested), mv: Math.round(slice[0].market_value) }
    const flows = comp ? slice.map((p) => Math.round(p.net_invested) - base0.inv) : []
    const profits = comp ? slice.map((p, i) => Math.round(p.market_value) - base0.mv - flows[i]!) : []
    const pd = comp ? profitDomain([...profits, ...flows]) : null
    const pLabels = pd ? pd.ticks.map(profitTickLabel) : []
    const left = privacy ? 4 : Math.max(...[...labels, ...pLabels].map(textWidth)) + 10
    const right = 6
    const plotW = Math.max(40, width - left - right)
    const top = comp ? COMP_TOP : TOP
    const paneH = comp ? (desktop ? 48 : 36) : 0
    const plotH = comp ? height - top - COMP_GAP - strip - paneH - COMP_TICKS - AXIS : height - TOP - AXIS
    const y = (v: number) => top + (1 - (v - min) / (max - min || 1)) * plotH
    // 每個收盤日等寬，週末與假日不留空（和個股走勢圖一樣）
    const x = (i: number) => left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW)
    const all = indexes(0, n - 1)
    const line = pathOf(all, x, (i) => y(slice[i]!.market_value))
    const showInvested = investedVisible(slice, min, max)
    const invested = showInvested
      ? slice.map((p, i) => (i === 0 ? `M${x(0).toFixed(1)} ${y(p.net_invested).toFixed(1)}` : `H${x(i).toFixed(1)}V${y(p.net_invested).toFixed(1)}`)).join("")
      : null
    // 組成那一格
    const paneTop = top + plotH + COMP_GAP + strip
    const yp = pd ? (v: number) => paneTop + (1 - (v - pd.min) / (pd.max - pd.min || 1)) * paneH : () => 0
    // 估計的那幾段（每一次匯入一段）畫細線：從它前一天到它後一天（進出那一段的那一天也是估計的持股造成的）；其他的照常
    const runs = estimatedRuns(n, est)
    // 投入本金的變化：和上面的投入本金同一種鉛筆灰階梯線
    const flowLine = pd ? slice.map((_, i) => (i === 0 ? `M${x(0).toFixed(1)} ${yp(flows[0]!).toFixed(1)}` : `H${x(i).toFixed(1)}V${yp(flows[i]!).toFixed(1)}`)).join("") : null
    return { ticks, labels, left, plotW, plotH, top, y, x, line, invested, pd, pLabels, paneTop, paneH, yp, profits, flows, flowLine, runs }
  }, [slice, n, width, height, privacy, comp, est, desktop, whole, strip])
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
    let i = Math.max(0, Math.min(n - 1, n === 1 ? 0 : Math.round(((px - left) / plotW) * (n - 1))))
    // 股利的記號只有 2px 寬：滑到附近（5px 以內）就對到領股利的那一天，讀數才看得到金額
    if (divs.size > 0 && !divs.has(days[i]!)) {
      let best = -1
      for (let j = 0; j < n; j++) {
        if (!divs.has(days[j]!)) continue
        const dist = Math.abs(x(j) - px)
        if (dist <= DIVIDEND_SNAP && (best < 0 || dist < Math.abs(x(best) - px))) best = j
      }
      if (best >= 0) i = best
    }
    setActive(i)
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
  // 估計的那一段裡的日子：讀數第一行多一個「估計」標記，自己一格、不會被截斷（截斷的只有日期，金額與標記一定完整）
  const activeEst = !!a && inSpans(a.t, comp?.estimated)
  const activeDay = a ? (active === n - 1 && splitLabel ? splitLabel : `${day(a.t, true)}收盤`) : ""
  const activeRet = active !== null ? rangeReturn(win, active) : null
  // 資產組成：滑過那一天的股利（日期已對到收盤日；從基準收盤起算的區間不含基準收盤那天）
  const activeDividend = a ? (divs.get(a.t) ?? 0) : 0
  // 組成那一格的標籤：「全部」與區間比資料長是現在的投入本金與累積損益，其他區間是從區間開始的加碼（或拿回）與損益
  const levels = whole
  const shownProfit = comp ? Math.round(model.profits[active ?? n - 1]!) : null
  const shownFlows = comp ? Math.round(model.flows[active ?? n - 1]!) : null
  const flowWord = (v: number) => (levels ? "投入本金" : v > 0 ? "加碼" : v < 0 ? "拿回" : "沒有加碼或拿回")
  const profitWord = levels ? "累積損益" : "損益"
  // 投入本金（現在的組成）照實帶正負號——賣出拿回的比投入的多時是負的；加碼／拿回的方向已經在字裡，金額不帶號
  const flowAmount = (v: number) => (levels ? v : Math.abs(v))
  const compSpeech = (f: number, p: number, hidden: boolean) =>
    `資產組成：${flowWord(f)}${!levels && f === 0 ? "" : ` ${hidden ? "已隱藏" : formatMoney(flowAmount(f))}`}，${profitWord} ${hidden ? "已隱藏" : formatMoney(p, { signed: true })}`
  const svgTitle = win.exceeds ? `${title}，${period}` : title
  const svgLabel = privacy
    ? `${svgTitle}，總資產報酬${retSpeech(total)}`
    : `${svgTitle}，總資產從 ${formatMoney(first.market_value)} 到 ${formatMoney(last.market_value)}，報酬${retSpeech(total)}` +
      (comp ? `，${compSpeech(Math.round(model.flows[n - 1]!), Math.round(model.profits[n - 1]!), false)}` : "")
  // 區間按鈕下面：拆解的一句話（股利用對到收盤日的日期）、估計那一段的說明（資產組成才有）
  const decomposition = comp ? decompose(win, range, snapped, { lifetimeDividends }) : null
  // 估計的是哪幾天：含基準收盤（報酬的分母），和績效分段指標下面那一行同一個規則（`trendEstimatedText`）
  const estText = comp ? trendEstimatedText(series, range, comp.estimated) : null
  const hasDividends = divs.size > 0
  // 手機（窄）而且有資產組成：讀數三行，股利與圖例放第三行
  const tall = !!comp && narrow
  // 資產組成：領到股利的那一天（股利不算在總資產與累積損益裡，另外寫）
  const dividendItem =
    activeDividend > 0 ? (
      <span className="shrink-0 text-sm" data-dividend>
        領股利 {privacy ? <Masked /> : formatMoney(activeDividend)}
      </span>
    ) : null
  const { runs, pd, paneTop, paneH, yp, top } = model
  // 「估計」括線：每一段估計一條，標頭尾；太窄放不下字時字放在括線右邊（右邊也放不下就放左邊）。
  // 兩段靠太近、字會疊在一起時，後面那一段只畫括線不寫字
  const brackets: { x1: number; x2: number; at: number | null }[] = []
  {
    const labelW = 34
    let lastEnd = -Infinity
    for (const e of est) {
      const x1 = x(e.first)
      const x2 = x(e.last)
      const inside = x2 - x1 >= labelW + 16
      const at = inside ? x1 + 6 : x2 + labelW + 6 <= width ? x2 + 4 : Math.max(0, x1 - labelW - 4)
      const fits = at >= lastEnd + 4
      brackets.push({ x1, x2, at: fits ? at : null })
      if (fits) lastEnd = at + labelW
    }
  }

  return (
    <section aria-label="總資產走勢" className="mt-6 lg:mt-8">
      {/* 讀數：固定高度（畫面不跳）；不做跟著游標跑的浮動框，手指不會擋住數字。
          手機上有資產組成時三行（`tall`）：股利與圖例放第三行，第一行的日期、「估計」、金額才放得下（320px 也不會只剩一個字） */}
      <div className={tall ? "h-16" : "h-11"} data-readout>
        {a ? (
          <>
            {/* 320px、上市與上櫃收盤日不同（「上市 11/17・上櫃 11/14 收盤」）時放不下：截斷的是日期，金額一定完整 */}
            <p className={cn("num flex items-baseline overflow-hidden text-base leading-6 whitespace-nowrap text-ink-2", comp ? "gap-x-3" : "gap-x-4")}>
              {/* 估計那一段的日子：標記放在日期前面、自己一格（`shrink-0`），手機上被截斷的是日期，不是「估計」 */}
              {activeEst && (
                <span className="status-tag shrink-0 self-center" data-estimated-day>
                  估計
                </span>
              )}
              <span className="min-w-0 truncate">{activeDay}</span>
              {privacy ? <Masked className="shrink-0 text-ink" /> : <span className="shrink-0 font-semibold text-ink">{formatMoney(a.market_value)}</span>}
              {!tall && dividendItem}
            </p>
            {/* 隱私模式：遮住的「••••」和「・」連在一起分不開，改用空白隔開 */}
            <p className={cn("num flex items-baseline overflow-hidden text-sm leading-5 whitespace-nowrap text-ink-2", privacy && "gap-x-4")}>
              <span>投入本金 {privacy ? <Masked /> : formatMoney(a.net_invested)}</span>
              {!privacy && <span aria-hidden>・</span>}
              <span>
                報酬 <Ret value={activeRet} />
              </span>
            </p>
            {tall && <p className="num flex items-baseline overflow-hidden text-sm leading-5 whitespace-nowrap text-ink-2">{dividendItem}</p>}
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
              {!tall && (model.invested || hasDividends) && (
                <span className={cn("inline-flex shrink-0 items-center gap-3", !tall && "ml-auto")}>
                  {model.invested && (
                    // 鉛筆灰階梯線是投入本金（墨色線就是總資產）
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden className="inline-block w-3.5 border-t-[1.5px] border-chart-bench" />
                      投入本金
                    </span>
                  )}
                  {hasDividends && (
                    // 資產組成：橫軸上的短直線是領到股利的日子
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden className="inline-block h-2 w-0.5 bg-ink-2" />
                      股利
                    </span>
                  )}
                </span>
              )}
            </p>
            {tall && (
              <p className="num flex items-baseline gap-3 text-sm leading-5 whitespace-nowrap text-ink-2">
                {(model.invested || hasDividends) && (
                <span className={cn("inline-flex shrink-0 items-center gap-3", !tall && "ml-auto")}>
                  {model.invested && (
                    // 鉛筆灰階梯線是投入本金（墨色線就是總資產）
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden className="inline-block w-3.5 border-t-[1.5px] border-chart-bench" />
                      投入本金
                    </span>
                  )}
                  {hasDividends && (
                    // 資產組成：橫軸上的短直線是領到股利的日子
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden className="inline-block h-2 w-0.5 bg-ink-2" />
                      股利
                    </span>
                  )}
                </span>
              )}
              </p>
            )}
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

          {a && <line x1={x(active!)} x2={x(active!)} y1={top} y2={pd ? paneTop + paneH : top + plotH} stroke="var(--ctl)" strokeWidth={1} />}

          {model.invested && <path d={model.invested} fill="none" stroke="var(--chart-bench)" strokeWidth={1.5} data-series="invested" />}
          {est.length > 0 ? (
            // 估計的那幾段：同一個墨色、細一級（1px）；不用虛線（虛線是 AI 的草稿與比較基準）
            <g data-series="total">
              {runs.thick.map((r) => (
                <path key={`t${r[0]}`} d={pathOf(r, x, (i) => y(slice[i]!.market_value))} fill="none" stroke="var(--chart-mine)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              ))}
              {runs.thin.map((r) => (
                <path key={`e${r[0]}`} d={pathOf(r, x, (i) => y(slice[i]!.market_value))} fill="none" stroke="var(--chart-mine)" strokeWidth={1} strokeLinejoin="round" data-estimated />
              ))}
            </g>
          ) : (
            <path d={model.line} fill="none" stroke="var(--chart-mine)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" data-series="total" />
          )}
          {/* 2～6 個收盤：每個收盤日一個 7px 圓點，2 點不會看起來像一條趨勢線 */}
          {few && slice.map((p, i) => <circle key={p.t} cx={x(i)} cy={y(p.market_value)} r={3.5} fill="var(--chart-mine)" data-point="close" />)}
          <circle cx={x(n - 1)} cy={y(last.market_value)} r={4} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={2} />
          {a && <circle cx={x(active!)} cy={y(a.market_value)} r={4} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={2} />}

          {/* 「估計」括線：每一段估計的頭尾各一個短直線，中間一條 1px 淡墨線（字是 HTML，蓋在線上） */}
          {brackets.map((b) => (
            <g key={`b${b.x1}`} stroke="var(--ink-2)" strokeWidth={1} data-bracket>
              <line x1={b.x1} x2={b.x2} y1={8.5} y2={8.5} />
              <line x1={b.x1 + 0.5} x2={b.x1 + 0.5} y1={4} y2={13} />
              <line x1={b.x2 - 0.5} x2={b.x2 - 0.5} y1={4} y2={13} />
            </g>
          ))}

          {/* 組成那一格（資產組成）：投入本金的變化與損益，都從 0 開始；刻度只標 0 和離 0 最遠那一邊。
              0 那一條和其他格線同一個顏色（`chart-grid`）：用鉛筆灰的話，在 1 月、3 月貼著 0 的投入本金階梯線（也是灰的）會看不出來 */}
          {pd && (
            <g data-pane="profit">
              {pd.ticks.map((v, i) => (
                <line key={v} x1={left} x2={left + plotW} y1={yp(v)} y2={yp(v)} stroke="var(--chart-grid)" strokeWidth={1} data-tick={v === 0 ? "zero" : i} />
              ))}
              {!privacy &&
                pd.ticks.map((v, i) => (
                  <text key={`l${v}`} x={left - 8} y={yp(v)} textAnchor="end" dominantBaseline="central" fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
                    {model.pLabels[i]}
                  </text>
                ))}
              {model.flowLine && <path d={model.flowLine} fill="none" stroke="var(--chart-bench)" strokeWidth={1.5} data-series="flows" />}
              {est.length > 0 ? (
                <>
                  {runs.thick.map((r) => (
                    <path key={`t${r[0]}`} d={pathOf(r, x, (i) => yp(model.profits[i]!))} fill="none" stroke="var(--chart-mine)" strokeWidth={1.5} strokeLinejoin="round" />
                  ))}
                  {runs.thin.map((r) => (
                    <path key={`e${r[0]}`} d={pathOf(r, x, (i) => yp(model.profits[i]!))} fill="none" stroke="var(--chart-mine)" strokeWidth={1} strokeLinejoin="round" />
                  ))}
                </>
              ) : (
                <path d={pathOf(indexes(0, n - 1), x, (i) => yp(model.profits[i]!))} fill="none" stroke="var(--chart-mine)" strokeWidth={1.5} strokeLinejoin="round" data-series="profit" />
              )}
              {few && model.profits.map((v, i) => <circle key={days[i]} cx={x(i)} cy={yp(v)} r={2.5} fill="var(--chart-mine)" />)}
              <circle cx={x(n - 1)} cy={yp(model.profits[n - 1]!)} r={3} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={1.5} />
              {a && <circle cx={x(active!)} cy={yp(model.profits[active!]!)} r={3} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={1.5} />}
              {/* 股利：領到的那一天在橫軸上方一個短直線（滑過的那一天是墨色、長一點） */}
              {days.map((t, i) =>
                divs.has(t) ? (
                  <line
                    key={`d${t}`}
                    x1={x(i)}
                    x2={x(i)}
                    y1={paneTop + paneH + (i === active ? 1 : 2)}
                    y2={paneTop + paneH + COMP_TICKS - 1}
                    stroke={i === active ? "var(--chart-mine)" : "var(--ink-2)"}
                    strokeWidth={i === active ? 2 : 1.5}
                    data-dividend-mark
                  />
                ) : null,
              )}
            </g>
          )}
        </svg>
        {/* 資產組成的字（HTML，蓋在圖上）：「估計」括線的字、組成那一格的標籤與金額 */}
        {brackets.map((b) =>
          b.at === null ? null : (
            <span key={`l${b.x1}`} aria-hidden className="pointer-events-none absolute top-0 bg-background px-1 text-xs leading-[17px] text-ink-2" style={{ left: b.at }}>
              估計
            </span>
          ),
        )}
        {pd && shownProfit !== null && shownFlows !== null && (
          // 組成那一格的標籤兼圖例：線的樣子＋名稱＋金額（滑過時是那一天的）。字是墨色或淡墨，顏色只在線的樣子上。
          // 和讀數同一條左緣。寬的時候一行；窄的時候（手機，`narrow`）兩項各一行、金額寫完整——不截斷數字（320px 一行放不下兩項）
          <div
            aria-hidden
            className={cn("num pointer-events-none absolute flex text-sm leading-5 text-ink-2", narrow ? "flex-col" : "flex-row items-baseline gap-x-4")}
            style={{ left: 0, top: paneTop - strip, right: 0 }}
            data-composition-label
          >
            <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
              <span className="inline-block w-3 shrink-0 -translate-y-[3px] border-t-[1.5px] border-chart-bench" />
              {flowWord(shownFlows)}
              {(levels || shownFlows !== 0) && (privacy ? <Masked /> : <span className="text-ink">{formatMoney(flowAmount(shownFlows))}</span>)}
            </span>
            <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
              <span className="inline-block w-3 shrink-0 -translate-y-[3px] border-t-[1.5px] border-chart-mine" />
              {profitWord}
              {privacy ? <Masked /> : <span className={cn("font-medium", toneClass(direction(shownProfit)))}>{formatMoney(shownProfit, { signed: true })}</span>}
            </span>
          </div>
        )}
        {/* 只在用鍵盤移動時念（滑鼠滑過不念） */}
        <p className="sr-only" aria-live="polite">
          {a && fromKeys
            ? `${activeDay}${activeEst ? "（估計）" : ""}，總資產 ${privacy ? "已隱藏" : formatMoney(a.market_value)}，投入本金 ${privacy ? "已隱藏" : formatMoney(a.net_invested)}，報酬${retSpeech(activeRet)}` +
              (shownProfit !== null && shownFlows !== null ? `，${compSpeech(shownFlows, shownProfit, privacy)}` : "") +
              (activeDividend > 0 ? `，領股利 ${privacy ? "已隱藏" : formatMoney(activeDividend)}` : "")
            : ""}
        </p>
      </div>

      {/* 七顆一律放（比資料長的也可以選）；歷史短時說明在按鈕下面——按鈕的位置和歷史夠長以後一樣 */}
      <RangeChips className="mt-2" label="走勢區間" value={range} options={TREND_RANGES} onChange={onRange} />
      {/* 資產組成：這段期間的拆解（15px 墨色，要讀的句子），估計那一段的說明和其他資料說明同一層。
          「資產組成」這個名字放在無障礙名稱（群組）：畫面上加一個小標會擠到主數字下面這一塊，所以不放 */}
      {decomposition && (
        <div role="group" aria-label="資產組成">
          <CompositionLine d={decomposition} privacy={privacy} className="mt-2" />
        </div>
      )}
      {shortNote && <p className="mt-1.5 text-sm text-ink-2">{shortNote}</p>}
      {estText && <p className="mt-1.5 text-sm text-ink-2">{estText} 用估計的買入日計算</p>}
      {referenceLine && <p className="mt-1.5 text-sm text-ink-2">{referenceLine}</p>}
    </section>
  )
}
