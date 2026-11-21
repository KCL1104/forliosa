import { useId, useMemo, useRef, useState } from "react"
import type { PerformanceComposition, PerformancePoint } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PlainLink } from "@/app/links"
import { Masked } from "@/components/finance"
import { RangeChips } from "@/components/segmented"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useLedgerClose } from "@/hooks/use-close"
import { useIsDesktop } from "@/hooks/use-media-query"
import { compositionAxis, dividendsByDay, estimatedRuns, fromZero, inSpans, profitBands, snapDividends, spanIndexes, totalPreFlow } from "@/lib/asset-composition"
import { direction, formatDateShort, formatMoney, toneClass } from "@/lib/format"
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
import { GAIN_LABEL, gainSpeech, INVESTED_RECOVERED, isRecovered, offChartCue, offChartSpeech, trendEstimatedText } from "./composition-text"
import { useLedgerPrefs } from "./ledger-prefs"
import { AXIS, COMP_TICKS, COMP_TOP, DIVIDEND_SNAP, DRAG_SLOP, flowPathOf, indexes, pathOf, retSpeech, textWidth, TICK_FONT, TOP, useWidth } from "./trend-chart"
import { trendClipNote, trendMissingReason, trendReferenceLine } from "./trend-reason"
import { TrendReturn as Ret } from "./TrendReturn"
import { useTrendRange } from "./use-trend-range"

/**
 * 總資產走勢（產品負責人 2026-11-17 選方案 B）：主數字正下方、和主欄一樣寬，手機與桌面同一個元件。
 * 由上到下：讀數（固定兩行）→ 圖（桌面 120px、手機 96px；資產組成的「估計」括線、股利記號那兩列在手機上另外加高，最多 114px）→ 區間（靠左）→ 歷史短（2～6 個收盤）時的一行說明。
 * 桌面的區間按鈕在讀數那一列的右邊（2026-11-19 選 B，首屏給持倉；DOM 順序照舊，只是格線換位置）。
 * - 資料：一次 `usePerformance("ALL")`（不帶基準），區間在前端切（`lib/trend-range.ts`），換區間不再問伺服器。
 *   存檔（2026/11/12 起）以後是官方收盤價；以前的日子用 Yahoo 回補換算成當時成交價（產品負責人 2026-11-18），
 *   區間用到那些日子時區間按鈕下面寫一行「11/11 以前用 Yahoo 參考價計算，不是官方資料」（後端的 `reference_until`）。
 * - 滑過、按住橫拖、方向鍵：讀數換成那一天的值；上面的大數字不變（永遠是最新收盤）。
 * - 自己畫 SVG（照 `ai/ChartCard.tsx`）：總資產 2px 墨色線＋底下淡出的墨色面積（和個股走勢圖同一個規格）、
 *   最後一點 8px 圓點＋2px 紙色外圈；投入本金 1.5px 鉛筆灰階梯線，縱軸只看總資產，投入本金不在範圍裡就不畫。
 * - 區間按鈕每個分段都放在這裡（整頁只有一排，績效分段跟著這一排；`useTrendChipsShown`）：
 *   這一塊的高度不跟著分段變，切分段時分段列不會上下跳。
 * - 畫得出走勢就放七顆區間按鈕（2026-11-17 負責人要求；歷史短時也放）。比資料長的區間畫全部的資料，標題照樣寫
 *   「近 3 個月」，第二行寫「只有 11/12 – 11/17 的資料」（`rangeExceedsData`），不讓人以為那是三個月的報酬。
 * - 資產組成 v2（原型，`docs/proposals/asset-composition.md` 附錄 A；後端給 `composition`、看自己的資產時才有，沒有時和上面一模一樣）：
 *   一張圖，沒有下面那一格、也沒有圖下面那一句（使用者 2026-11-19：只要圖）。
 *   - 高度：帳本裡有估計的那一段時，圖的上面留一列給「估計」括線；領過股利時，橫軸上面留一列給股利記號（看這個帳本有沒有，
 *     不看區間：換區間時圖不跳）。桌面照 main 是 120，兩列從畫圖的範圍裡分出來（畫圖的範圍 90 → 72）；手機（產品負責人
 *     2026-11-21 照提案的建議）圖加高那兩列的高度，畫圖的範圍和 main 一樣是 66（兩列都有時 114，沒有時照 main 96）。
 *   - 讀數下面一列圖例（金額跟著滑過的那一天；手機兩行兩欄）：讀數、圖例都在圖的上面，手指按著圖時擋不到數字。
 *     桌面的區間按鈕照 main 在讀數那一列的右邊，圖例那一列橫跨兩欄。
 *   - 「本金」開關（`ledger-prefs` 的 `showInvested`，預設開；和個股走勢圖的「重要時刻」同一種：字＋小號 `Switch`）：
 *     開的時候畫本金線與賺虧的塗色；關掉時只有總資產一條線（縱軸跟總資產、圖例只有總資產；股利記號與「估計」照舊）。
 *     寬的時候在圖例那一列的右邊（桌面在區間按鈕的正下方）；窄的時候在讀數第二行（期間）的右邊，不多佔一行。
 *   - **淡墨面積和賺虧塗色只畫一種**：本金開著時賺虧的塗色取代淡墨面積（兩層疊在一起，塗色會變髒、也分不出哪一層是什麼）；
 *     本金關掉時照 main 畫淡墨面積，看起來就是 main 的走勢（多了股利記號與「估計」）。
 *   - 本金是鉛筆灰階梯線（不填色）；總資產和本金之間塗淡色：總資產在本金線上面是賺的（漲的顏色）、下面是虧的（跌的顏色），
 *     兩條線交會的地方換顏色（`profitBands`）。顏色跟著紅漲綠跌／綠漲紅跌的設定，平塗、不漸層、不動畫。
 *   - 買進、賣出那一天，總資產線和本金線一起垂直跳一樣的金額（`flowPathOf`、`totalPreFlow`）：斜的部分只有價格的漲跌，
 *     每一個收盤日左邊塗的顏色就是那天收盤的賺或虧。
 *   - 縱軸：總資產自己的起伏夠大（至少是兩條線都放得下的範圍的 35%）時貼著兩條線；不然縱軸只跟總資產（和以前一樣），
 *     本金線超出圖的部分切掉、塗色畫到圖的邊緣（`compositionAxis`）。本金線在圖外：縱軸那一欄靠那一邊多一個記號——
 *     鉛筆灰的箭頭（本金線的顏色，朝圖外）＋本金的約略金額（「↓ 288萬」，和刻度同一種寫法），不寫句子（2026-11-21 評論）。
 *     下方的記號在圖的下緣下面（縱軸那一欄的這個位置是空的）；上方的記號在最上面，碰到的刻度字不寫（格線照畫）。不為了從 0 開始而從 0 開始。
 *   - 圖例兼金額（「— 本金 NT$…」「■ 目前價差 +NT$…」「❙ 股利」「— 總資產」；「全部」寫「價差」）：沒有滑過時是最後一天，
 *     滑過時是那一天；每一項的寬度撐到這段期間最寬的金額（滑過時不左右跳）。讀數第一行是日期與總資產，第二行是報酬。
 *     **價差**＝總資產－本金＝未實現＋已實現損益，不含股利（2026-11-21 評論：原本寫「賺的」，和上面的「總損益（含股利）」
 *     兩個都讀成「賺多少」、差的就是股利；改用台股的說法「價差」，和旁邊的「股利」一起就是總損益）。
 *   - 本金 ≤ 0（賣股票收到的錢已經和買股票花的一樣多或更多）：圖例、讀數、圖的說明寫「本金已收回」，不寫金額；價差照實寫（總資產－本金）。
 *     本金線畫在 0、塗色從 0 塗到總資產（`profitBands` 的 `floor`）；那幾天塗的高度比價差少（提案附錄 A）。0 在圖外時縱軸的記號寫「0」。
 *   - 領到股利的日子在橫軸上一個短直線（不疊進圖裡）；滑過那一天時讀數寫「領股利 NT$3,200」。
 *   - 照估計的買入日畫的那一段：線改成細線，上面一條標「估計」的括線，區間按鈕下面一行「… 用估計的買入日計算」；塗色照常。
 *     不用虛線（虛線是 AI 的草稿與比較基準）。
 */

/** 窄於這個寬度時圖例排成兩行兩欄（一行放不下四個圖例與開關）；本金開關也改放在讀數第二行的右邊 */
const STACK_BELOW = 640
/** 本金線在圖外的記號：箭頭的寬（含和金額之間的空隙）；金額和刻度字一樣靠右對齊在 `left − 8` */
const CUE_ARROW = 10
/** 記號的中心：下方的在圖的下緣下面 13px（刻度字最低到下緣下面 6px，不會碰到）；上方的固定在 12px */
const CUE_BELOW = 13
const CUE_ABOVE_Y = 12

/**
 * 走勢畫不出來、而且後端說了原因時：一行淡墨原因，連到績效（手機也看得到；觸控 44px）。
 * 每個分段都放、一樣高（換分段時分段列不跳）；已經在績效分段時不連到自己，只是一行字。
 */
function TrendMissing({ reason, linked, titled, className }: { reason: string; linked: boolean; titled: boolean; className?: string }) {
  const box = "inline-flex items-center text-sm text-ink-2 max-lg:min-h-11 pointer-coarse:min-h-11"
  // 手機的「總資產走勢」托盤：標題已經是「總資產走勢」，看得到的只寫原因；連結的名稱照樣是完整的（連結清單裡也聽得懂）
  const text = titled ? (
    <>
      <span className="sr-only">總資產走勢：</span>
      {reason}
    </>
  ) : (
    `總資產走勢：${reason}`
  )
  return (
    <p className={cn("mt-4 lg:mt-6", className)}>
      {linked ? (
        <PlainLink to="/" search={{ view: "performance" }} className={cn(box, "underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink")}>
          {text}
        </PlainLink>
      ) : (
        <span className={box}>{text}</span>
      )}
    </p>
  )
}

/**
 * `className`：外層的上邊距（桌面在總資產那一盤裡、接在數字下面；手機自己一盤時是 0）。
 * `titled`：放在標題已經是「總資產走勢」的托盤裡（手機），畫不出來的原因前面不再寫「總資產走勢：」。
 */
export function HeroTrend({ view, className, titled = false }: { view: LedgerView; className?: string; titled?: boolean }) {
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const { perf, range, setRange } = useTrendRange()
  const desktop = useIsDesktop()
  const readOnly = useReadOnly()
  if (!showTrend || perf.isError) return null
  if (!perf.data) return <Skeleton aria-label="總資產走勢載入中" className={cn("mt-6 h-[224px] w-full rounded-sm lg:mt-8 lg:h-[252px]", className)} />
  const series = perf.data.series
  const notes = perf.data.notes ?? []
  const state = trendState(series.length)
  if (state === "missing") {
    const reason = trendMissingReason(notes)
    return reason ? <TrendMissing reason={reason} linked={view !== "performance"} titled={titled} className={className} /> : null
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
  // 查看別人的資產時不放資產組成（先只給自己看；決定 11）
  const composition = readOnly ? undefined : perf.data.composition
  const props = {
    series,
    referenceUntil: perf.data.reference_until ?? null,
    composition,
    range,
    onRange: setRange,
    desktop,
    few: state === "short",
    shortNote,
  }
  // main 的高度（桌面 120、手機 96）；手機有「估計」括線、股利記號那兩列時加高（`TrendBand` 看這個帳本有沒有那兩列）
  return <TrendBand {...props} height={desktop ? 120 : 96} className={className} titled={titled} />
}

/** 縱軸刻度（資產組成）：負號用「−」、0 寫「0」（本金已收回時本金線畫在 0，v2 的刻度不會到負的） */
const signedTicks = (ticks: readonly number[]) => compactTicks(ticks).map((s, i) => (ticks[i] === 0 ? "0" : s.replace(/^-/, "−")))

/** 幾個字串裡畫出來最寬的那一個（估計；圖例每一項的寬度用它撐住，滑過時金額位數變了也不跳） */
const widestOf = (xs: readonly string[]) => xs.reduce((a, b) => (textWidth(b) > textWidth(a) ? b : a), "")

function TrendBand({
  series,
  referenceUntil,
  range,
  onRange,
  height: baseHeight,
  desktop,
  few,
  shortNote,
  composition,
  className,
  titled = false,
}: {
  series: PerformancePoint[]
  /** 後端的 `reference_until`：這一天（含）以前用 Yahoo 參考價估值 */
  referenceUntil: string | null
  /** 資產組成（原型）：舊版後端沒有，這時和 main 一模一樣 */
  composition?: PerformanceComposition
  range: TrendRange
  onRange: (r: TrendRange) => void
  /** main 的高度（桌面 120、手機 96）；手機有「估計」括線、股利記號那兩列時再加高 */
  height: number
  desktop: boolean
  /** 2～6 個收盤：每一點一個圓點 */
  few: boolean
  shortNote: React.ReactNode
  /** 外層的上邊距 */
  className?: string
  /** 在標題是「總資產走勢」的托盤裡：托盤本身就是那個區塊，這裡不再是另一個同名的 region */
  titled?: boolean
}) {
  const privacy = usePrefs((s) => s.privacyMode)
  const close = useLedgerClose()
  // 資產組成：畫不畫本金（本金線＋塗色）
  const investedOn = useLedgerPrefs((s) => s.showInvested)
  const setInvestedOn = useLedgerPrefs((s) => s.setShowInvested)
  const [wrapRef, width] = useWidth(desktop ? 900 : 335)
  const [active, setActive] = useState<number | null>(null)
  const [fromKeys, setFromKeys] = useState(false)
  const drag = useRef<{ id: number; x: number; y: number; on: boolean } | null>(null)
  const uid = useId().replace(/[^\w-]/g, "")
  // 塗色只塗在圖的範圍裡（本金在圖外時塗到圖的邊緣）
  const clipId = `trend-clip-${uid}`
  const switchId = `trend-invested-${uid}`

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
  // 本金那一層（本金線、塗色、本金與價差的圖例、縱軸的記號）：有資產組成而且開關打開
  const inv = !!comp && investedOn
  // 「全部」與區間比資料長：從 0 起算（和報酬的分母同一個規則，`fromZero`）——圖例寫「價差」，其他區間寫「目前價差」
  const whole = fromZero(win, range)
  // 股利對到收盤日（週末、假日領的算在下一個收盤日）。從基準收盤起算的區間，基準收盤那天的股利不算進區間（記號、圖例、讀數都不放）
  const markFrom = whole ? 0 : 1
  const snapped = useMemo(() => snapDividends(comp?.dividends ?? [], series.map((p) => p.t)), [comp, series])
  const divs = useMemo(() => {
    const inWindow = new Set(days.slice(markFrom))
    return dividendsByDay(snapped.filter((d) => inWindow.has(d.t)))
  }, [snapped, days, markFrom])
  const est = useMemo(() => spanIndexes(days, comp?.estimated), [days, comp])
  // 「估計」括線那一列、股利記號那一列：這個帳本有估計的那一段、領過股利才留（看整個帳本，不看區間：換區間時圖不跳）
  const bracketRow = !!comp?.estimated.length
  const dividendRow = snapped.length > 0
  // 手機（96px）：那兩列吃掉畫圖的範圍（66 → 48px），所以加高那兩列的高度，畫圖的範圍和 main 一樣（最多 114px）。桌面 120 不變
  const height = desktop ? baseHeight : baseHeight + (bracketRow ? COMP_TOP - TOP : 0) + (dividendRow ? COMP_TICKS : 0)
  // 窄的時候（手機）圖例排成兩行兩欄、本金開關在讀數第二行的右邊；本金開關關掉時高度照留（圖不會跳）
  const stacked = !!comp && width < STACK_BELOW

  const model = useMemo(() => {
    // 資產組成：金額先四捨五入到元（圖例的本金＋價差＝讀數的總資產）
    const vp = slice.map((p) => ({ v: Math.round(p.market_value), p: Math.round(p.net_invested) }))
    // 本金線畫在哪裡：本金已收回（≤ 0）的日子畫在 0（縱軸、縱軸的記號也看這條線）
    const floor = vp.map((q) => Math.max(q.p, 0))
    const axisMode = inv ? compositionAxis(vp.map((q, i) => ({ v: q.v, p: floor[i]! }))).mode : "total"
    const { ticks, min, max } = trendDomain(axisMode === "both" ? [...vp.map((q) => q.v), ...floor] : slice.map((p) => p.market_value))
    const labels = comp ? signedTicks(ticks) : compactTicks(ticks)
    // 縱軸只跟總資產、最後一天的本金線在圖外：寫在哪一邊（縱軸那一欄多一個記號：箭頭＋約略金額，隱私模式只有箭頭）
    const lastP = floor[n - 1]!
    const offChart: "above" | "below" | null = inv && axisMode === "total" ? (lastP < min ? "below" : lastP > max ? "above" : null) : null
    const cueText = offChart && !privacy ? offChartCue(lastP) : ""
    const cueW = offChart ? CUE_ARROW + (cueText ? textWidth(cueText) + 2 : 0) : 0
    const left = privacy ? (offChart ? 14 : 4) : Math.max(...labels.map(textWidth), cueW) + 10
    const right = 6
    const plotW = Math.max(40, width - left - right)
    const top = bracketRow ? COMP_TOP : TOP
    const plotH = height - top - (dividendRow ? COMP_TICKS : 0) - AXIS
    const y = (v: number) => top + (1 - (v - min) / (max - min || 1)) * plotH
    const cueY = offChart === "below" ? top + plotH + CUE_BELOW : CUE_ABOVE_Y
    // 上方的記號碰到的刻度字不寫（格線照畫）；下方的記號在圖的下緣下面，碰不到
    const tickShown = ticks.map((v) => offChart !== "above" || Math.abs(y(v) - cueY) >= 13)
    // 每個收盤日等寬，週末與假日不留空（和個股走勢圖一樣）；塗色的交會點在兩個收盤日之間，所以位置可以是小數
    const x = (i: number) => left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW)
    // 本金那一層開著：總資產線在買賣那一天和本金一起垂直跳（先斜到買賣以前的值）；其他時候和以前一樣的折線
    const pre = inv ? vp.map((_, i) => totalPreFlow(vp, i)) : null
    const totalPath = (idx: readonly number[]) =>
      pre ? flowPathOf(idx, x, (i) => y(vp[i]!.v), (i) => y(pre[i]!)) : pathOf(idx, x, (i) => y(slice[i]!.market_value))
    const all = indexes(0, n - 1)
    const line = totalPath(all)
    // 和個股走勢圖同一個規格：線底下一層淡出的墨色面積（收到圖的下緣）。本金那一層開著時不畫：賺虧的塗色取代它，不疊兩層
    const area = !inv && n > 1 ? `${line}L${x(n - 1).toFixed(1)} ${(top + plotH).toFixed(1)}L${x(0).toFixed(1)} ${(top + plotH).toFixed(1)}Z` : null
    // 本金線：本金那一層開著時一律畫（超出圖的部分切掉）；關掉時不畫；沒有資產組成時照以前（每一天都在縱軸的範圍裡才畫）
    const showInvested = inv || (!comp && investedVisible(slice, min, max))
    const invested = showInvested
      ? slice
          .map((p, i) => {
            // 資產組成：本金已收回的日子畫在 0
            const at = y(inv ? floor[i]! : p.net_invested).toFixed(1)
            return i === 0 ? `M${x(0).toFixed(1)} ${at}` : `H${x(i).toFixed(1)}V${at}`
          })
          .join("")
      : null
    // 估計的那幾段（每一次匯入一段）畫細線：從它前一天到它後一天（進出那一段的那一天也是估計的持股造成的）；其他的照常
    const runs = estimatedRuns(n, est)
    // 賺與虧的塗色：同一邊的多邊形放在同一個 path（相鄰的兩塊之間不會有接縫）。下緣是本金線（本金已收回時是 0）
    const bands = inv ? profitBands(vp, { floor: 0 }) : []
    const polygon = (pts: [number, number][]) => pts.map(([i, v], k) => `${k === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("") + "Z"
    const gain = bands.filter((b) => b.side === "gain").map((b) => polygon(b.points)).join("")
    const loss = bands.filter((b) => b.side === "loss").map((b) => polygon(b.points)).join("")
    // 本金線在圖外的記號：金額靠右對齊在刻度字的右緣（`left − 8`），箭頭在金額左邊；隱私模式只有箭頭
    const cue = offChart
      ? { side: offChart, text: cueText, x: left - 8, y: cueY, ax: cueText ? left - 8 - textWidth(cueText) - 2 - CUE_ARROW / 2 : left - 7 }
      : null
    return { ticks, labels, tickShown, left, plotW, plotH, top, y, x, line, area, totalPath, invested, runs, gain, loss, offChart, cue, vp }
  }, [slice, n, width, height, privacy, comp, inv, est, bracketRow, dividendRow])
  const { ticks, labels, tickShown, left, plotW, plotH, top, y, x, runs } = model

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
  // 圖例的金額：沒有滑過時是區間的最後一天，滑過時是那一天。價差＝總資產－本金（未實現＋已實現，不含股利）
  const shownAt = model.vp[active ?? n - 1]!
  const shownGain = shownAt.v - shownAt.p
  // 本金已收回（≤ 0）：不寫金額，寫「本金已收回」（滑過時看那一天）
  const shownRecovered = isRecovered(shownAt.p)
  // 沒有滑過、而且不是「全部」：圖例的價差是到最後一天累積的，不是這段期間的——寫「目前價差」（滑過時讀數有日期，不用）
  const gainLabel = `${!a && !whole ? "目前" : ""}${GAIN_LABEL}`
  // 有賺有虧：看收盤（有一天總資產在本金上面、有一天在下面），不看塗了哪幾種顏色
  const mixed = model.vp.some((q) => q.v > q.p) && model.vp.some((q) => q.v < q.p)
  const money = (v: number) => (privacy ? "已隱藏" : formatMoney(v))
  const endAt = model.vp[n - 1]!
  const endGain = endAt.v - endAt.p
  const endRecovered = isRecovered(endAt.p)
  const svgTitle = win.exceeds ? `${title}，${period}` : title
  // 圖的說明：本金那一層開著時念「資產組成」（決定 1 的名字）、最後一天的本金與價差（賺或虧），不靠顏色——有賺有虧、本金線在圖外也用字說；
  // 「本金只算還在股票裡的錢」（決定 5）畫面上不寫（使用者只要圖），寫在這裡。本金已收回：不念金額，為什麼、本金線畫在哪裡也念在這裡
  const compSpeech = inv
    ? "，資產組成：" +
      (privacy
        ? `最後一天${gainSpeech(endGain, null)}${endRecovered ? `，${INVESTED_RECOVERED}` : ""}`
        : `最後一天${endRecovered ? INVESTED_RECOVERED : `本金 ${formatMoney(endAt.p)}`}，${gainSpeech(endGain, formatMoney(Math.abs(endGain)))}`) +
      (mixed ? "，這段期間有賺有虧" : "") +
      (model.offChart && !endRecovered ? `，${offChartSpeech(model.offChart)}` : "") +
      "。本金是買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢" +
      (endRecovered ? `；賣股票收到的錢已經和買股票花的一樣多或更多，所以本金線畫在 0${model.offChart ? "，在圖的下方" : ""}` : "")
    : ""
  const svgLabel =
    (privacy
      ? `${svgTitle}，總資產報酬${retSpeech(total)}`
      : `${svgTitle}，總資產從 ${formatMoney(first.market_value)} 到 ${formatMoney(last.market_value)}，報酬${retSpeech(total)}`) + compSpeech
  // 估計的是哪幾天：含基準收盤（報酬的分母），和績效分段指標下面那一行同一個規則（`trendEstimatedText`）
  const estText = comp ? trendEstimatedText(series, range, comp.estimated) : null
  const hasDividends = divs.size > 0
  // 資產組成：領到股利的那一天（股利不算在總資產與價差裡，另外寫）
  const dividendItem =
    activeDividend > 0 ? (
      <span className="shrink-0 text-sm" data-dividend>
        領股利 {privacy ? <Masked /> : formatMoney(activeDividend)}
      </span>
    ) : null
  // 「估計」括線：每一段估計一條，標頭尾；太窄放不下字時字放在括線右邊（右邊也放不下就放左邊）。
  // 兩段靠太近、字會疊在一起時，後面那一段只畫括線不寫字（前面那一段的字已經說了）
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
  // 圖例（資產組成）：線或色塊的樣子＋名稱＋金額（滑過時是那一天的）。字是淡墨，金額墨色；顏色只在價差的金額上（價格造成的）
  const legendInvested = inv && (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap" data-legend="invested">
      <span aria-hidden className="inline-block w-3.5 shrink-0 -translate-y-[3px] border-t-[1.5px] border-chart-bench" />
      {shownRecovered ? INVESTED_RECOVERED : <>本金 {privacy ? <Masked /> : <span className="text-ink">{formatMoney(shownAt.p)}</span>}</>}
    </span>
  )
  // 價差的名字不分賺虧：正負號說方向。隱私模式只遮金額、留著正負號（以前的「賺的／虧的」在隱私模式也看得出方向）
  const gainTone = toneClass(direction(shownGain))
  const legendGain = inv && (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap" data-legend="gain">
      <span aria-hidden className={cn("inline-block size-2.5 shrink-0", shownGain >= 0 ? "bg-rise-tint" : "bg-fall-tint")} />
      {gainLabel}{" "}
      {privacy ? (
        <span className="inline-flex items-baseline">
          <span className={cn("font-medium", gainTone)}>{shownGain < 0 ? "−" : "+"}</span>
          <Masked />
        </span>
      ) : (
        <span className={cn("font-medium", gainTone)}>{formatMoney(shownGain, { signed: true })}</span>
      )}
    </span>
  )
  const legendDividend = hasDividends && (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap" data-legend="dividend">
      {/* 橫軸上的短直線是領到股利的日子 */}
      <span aria-hidden className="inline-block h-2.5 w-0.5 shrink-0 bg-ink-2" />
      股利
    </span>
  )
  const legendTotal = (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap" data-legend="total">
      <span aria-hidden className="inline-block w-3.5 shrink-0 -translate-y-[3px] border-t-2 border-chart-mine" />
      總資產
    </span>
  )
  // 本金、價差那兩項撐到這段期間最寬的金額（看不到、不佔高度）：滑過時金額的位數變了，後面的圖例不會左右跳。
  // 本金已收回的日子寫「本金已收回」（不寫金額）：有這種日子時也撐一個
  const widest = useMemo(
    () => ({
      invested: widestOf(model.vp.filter((q) => !isRecovered(q.p)).map((q) => formatMoney(q.p))),
      recovered: model.vp.some((q) => isRecovered(q.p)),
      gain: widestOf(model.vp.map((q) => formatMoney(q.v - q.p, { signed: true }))),
    }),
    [model.vp],
  )
  const sizer = (label: string, amount: string, signed = false) => (
    <span aria-hidden className="invisible inline-flex h-0 items-baseline gap-1.5 overflow-hidden whitespace-nowrap" data-legend-sizer>
      <span className="inline-block w-3.5 shrink-0" />
      {label}{" "}
      {privacy ? (
        <span className="inline-flex items-baseline">
          {signed && <span className="font-medium">+</span>}
          <Masked />
        </span>
      ) : (
        <span className="font-medium">{amount}</span>
      )}
    </span>
  )
  const gainSizer = sizer(`${whole ? "" : "目前"}${GAIN_LABEL}`, widest.gain, true)
  const investedSizers = (
    <>
      {widest.invested && sizer("本金", widest.invested)}
      {widest.recovered && (
        <span aria-hidden className="invisible inline-flex h-0 items-baseline gap-1.5 overflow-hidden whitespace-nowrap" data-legend-sizer>
          <span className="inline-block w-3.5 shrink-0" />
          {INVESTED_RECOVERED}
        </span>
      )}
    </>
  )
  // 「本金」開關：只有資產組成、看自己的資產時才有（`comp` 已經擋過）。和個股走勢圖的「重要時刻」同一種：字在前、小號開關在後，
  // 沒有外框、沒有圖示。觸控時按得到的範圍至少 44px 高（開關元件自己的 ::after）
  const investedSwitch = comp && (
    <span className="inline-flex shrink-0" data-invested-switch>
      <label htmlFor={switchId} className="inline-flex cursor-pointer items-center gap-2 text-sm leading-5 text-ink-2 select-none">
        本金
        <Switch id={switchId} size="sm" checked={investedOn} onCheckedChange={setInvestedOn} aria-describedby={`${switchId}-desc`} />
      </label>
      <span id={`${switchId}-desc`} className="sr-only">
        打開時，走勢圖畫本金線，總資產在本金上面塗賺的顏色、下面塗虧的顏色
      </span>
    </span>
  )
  // 圖例（資產組成）：讀數下面、圖的上面（手指按著圖時擋不到）。桌面橫跨區間按鈕那一欄（格線第二列）
  const legendPlace = "lg:col-span-2 lg:col-start-1 lg:row-start-2"
  // 窄（手機）：兩行兩欄（本金、價差｜股利、總資產），金額寫完整；本金開關關掉時只有一行，高度照留（圖不會跳）。
  // 本金線在圖外時圖例不另外寫（縱軸那一欄有記號）
  // 2026-11-21：托盤裡 320px 的手機只剩 248px，金額很大（上千億）時一行放不下——第二欄換到下一行（高度照最寬的金額定，滑過時不跳），不撐出畫面
  const gridBox = cn("num min-h-10 text-sm leading-5 text-ink-2", legendPlace)
  const legend = !comp ? null : stacked ? (
    !inv ? (
      <div className={cn(gridBox, "flex gap-x-4")} data-legend-grid>
        {legendDividend}
        {legendTotal}
      </div>
    ) : (
      <div className={cn(gridBox, "flex flex-wrap gap-x-5")} data-legend-grid>
        <div className="flex flex-col" data-legend-col>
          {legendInvested}
          {legendGain}
          {investedSizers}
          {gainSizer}
        </div>
        <div className="flex flex-col">
          {legendDividend}
          {legendTotal}
        </div>
      </div>
    )
  ) : (
    // 寬（桌面）：一行，本金開關在最右邊（桌面在區間按鈕的正下方）
    <div className={cn("num flex h-6 items-center gap-x-4 text-sm leading-5 text-ink-2", legendPlace)} data-legend-row>
      {inv && (
        <>
          <span className="inline-flex flex-col">
            {legendInvested}
            {investedSizers}
          </span>
          <span className="inline-flex flex-col">
            {legendGain}
            {gainSizer}
          </span>
        </>
      )}
      {legendDividend}
      {legendTotal}
      <span className="ml-auto">{investedSwitch}</span>
    </div>
  )

  return (
    <section aria-label={titled ? undefined : "總資產走勢"} className={cn("mt-5 lg:mt-6 lg:grid lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-x-6", className)}>
      {/* 讀數：固定兩行（高度不變，畫面不跳）；不做跟著游標跑的浮動框，手指不會擋住數字。
          資產組成而且窄（手機）時本金開關在第二行的右邊 */}
      <div className={cn("h-11 lg:col-start-1 lg:row-start-1", stacked && "relative")} data-readout>
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
              {comp && !stacked && dividendItem}
            </p>
            {comp ? (
              // 資產組成：第二行是報酬（本金、價差在下面的圖例，跟著這一天）；窄的時候領到的股利也在這一行，右邊留給本金開關
              <p className={cn("num flex items-baseline gap-x-4 overflow-hidden text-sm leading-5 whitespace-nowrap text-ink-2", stacked && "pr-18")}>
                <span className="shrink-0">
                  報酬 <Ret value={activeRet} />
                </span>
                {stacked && dividendItem}
              </p>
            ) : (
              // 隱私模式：遮住的「••••」和「・」連在一起分不開，改用空白隔開
              <p className={cn("num flex items-baseline overflow-hidden text-sm leading-5 whitespace-nowrap text-ink-2", privacy && "gap-x-4")}>
                <span>投入本金 {privacy ? <Masked /> : formatMoney(a.net_invested)}</span>
                {!privacy && <span aria-hidden>・</span>}
                <span>
                  報酬 <Ret value={activeRet} />
                </span>
              </p>
            )}
          </>
        ) : (
          <>
            <p className="flex items-baseline gap-x-4 overflow-hidden text-base leading-6 whitespace-nowrap text-ink">
              <span className="font-medium">{title}</span>
              <span className="text-ink-2">
                報酬 <Ret value={total} />
              </span>
            </p>
            <p className={cn("num flex items-baseline gap-3 text-sm leading-5 whitespace-nowrap text-ink-2", stacked && "pr-18")}>
              <span className="min-w-0 truncate">{period}</span>
              {!comp && model.invested && (
                // 圖例只有一項：鉛筆灰階梯線是投入本金（墨色線就是總資產）
                <span className="ml-auto inline-flex shrink-0 items-center gap-1.5">
                  <span aria-hidden className="inline-block w-3.5 border-t-[1.5px] border-chart-bench" />
                  投入本金
                </span>
              )}
            </p>
          </>
        )}
        {/* 手機的本金開關：讀數第二行（期間；滑過時是報酬）的右邊，不多佔一行，滑過時也在同一個位置 */}
        {stacked && <div className="absolute top-6 right-0 flex h-5 items-center">{investedSwitch}</div>}
      </div>

      {legend}

      <div
        ref={wrapRef}
        className={cn(
          "relative mt-2 touch-pan-y rounded-xs lg:col-span-2 outline-offset-2 select-none [-webkit-touch-callout:none] focus-visible:outline-2 focus-visible:outline-ring",
          comp ? "lg:row-start-3" : "lg:row-start-2",
        )}
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
          {inv && (
            <defs>
              <clipPath id={clipId}>
                <rect x={left} y={top} width={plotW} height={plotH} />
              </clipPath>
            </defs>
          )}
          {ticks.map((v, i) => (
            <g key={v}>
              <line x1={left} x2={left + plotW} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth={1} />
              {/* 隱私模式：照樣畫線，但不標金額。上方的本金記號碰到的刻度字不寫 */}
              {!privacy && tickShown[i] && (
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

          {/* 資產組成：總資產和本金之間塗淡色——上面是賺的（漲的顏色）、下面是虧的（跌的顏色）。平塗、沒有框線 */}
          {inv && (
            <g clipPath={`url(#${clipId})`} data-bands>
              {model.gain && <path d={model.gain} fill="var(--rise-tint)" stroke="none" data-band="gain" />}
              {model.loss && <path d={model.loss} fill="var(--fall-tint)" stroke="none" data-band="loss" />}
            </g>
          )}

          {a && <line x1={x(active!)} x2={x(active!)} y1={top} y2={top + plotH} stroke="var(--ctl)" strokeWidth={1} />}

          {/* 和個股走勢圖同一個規格：線底下淡出的墨色面積（上緣 10%、到下緣 0%）。本金那一層開著時賺虧的塗色取代它 */}
          {model.area && (
            <>
              <defs>
                <linearGradient id="hero-trend-area" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-mine)" stopOpacity={0.1} />
                  <stop offset="100%" stopColor="var(--chart-mine)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <path d={model.area} fill="url(#hero-trend-area)" data-series="area" />
            </>
          )}
          {model.invested && (
            <path d={model.invested} fill="none" stroke="var(--chart-bench)" strokeWidth={1.5} clipPath={inv ? `url(#${clipId})` : undefined} data-series="invested" />
          )}
          {est.length > 0 ? (
            // 估計的那幾段：同一個墨色、細一級（1px）；不用虛線（虛線是 AI 的草稿與比較基準）
            <g data-series="total">
              {runs.thick.map((r) => (
                <path key={`t${r[0]}`} d={model.totalPath(r)} fill="none" stroke="var(--chart-mine)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              ))}
              {runs.thin.map((r) => (
                <path key={`e${r[0]}`} d={model.totalPath(r)} fill="none" stroke="var(--chart-mine)" strokeWidth={1} strokeLinejoin="round" data-estimated />
              ))}
            </g>
          ) : (
            <path d={model.line} fill="none" stroke="var(--chart-mine)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" data-series="total" />
          )}
          {/* 2～6 個收盤：每個收盤日一個 7px 圓點，2 點不會看起來像一條趨勢線 */}
          {few && slice.map((p, i) => <circle key={p.t} cx={x(i)} cy={y(p.market_value)} r={3.5} fill="var(--chart-mine)" data-point="close" />)}
          <circle cx={x(n - 1)} cy={y(last.market_value)} r={4} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={2} />
          {a && <circle cx={x(active!)} cy={y(a.market_value)} r={4} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={2} />}

          {/* 本金線在圖外：縱軸那一欄靠那一邊一個記號——鉛筆灰的箭頭（本金線的顏色、1.5px，朝圖外）＋約略金額（和刻度字同一種寫法、靠右對齊） */}
          {model.cue && (
            <g data-off-chart={model.cue.side}>
              <g stroke="var(--chart-bench)" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" aria-hidden>
                {model.cue.side === "below" ? (
                  <>
                    <line x1={model.cue.ax} x2={model.cue.ax} y1={model.cue.y - 5} y2={model.cue.y + 4.5} />
                    <polyline points={`${model.cue.ax - 3},${model.cue.y + 1.5} ${model.cue.ax},${model.cue.y + 4.5} ${model.cue.ax + 3},${model.cue.y + 1.5}`} />
                  </>
                ) : (
                  <>
                    <line x1={model.cue.ax} x2={model.cue.ax} y1={model.cue.y + 5} y2={model.cue.y - 4.5} />
                    <polyline points={`${model.cue.ax - 3},${model.cue.y - 1.5} ${model.cue.ax},${model.cue.y - 4.5} ${model.cue.ax + 3},${model.cue.y - 1.5}`} />
                  </>
                )}
              </g>
              {model.cue.text && (
                <text x={model.cue.x} y={model.cue.y} textAnchor="end" dominantBaseline="central" fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
                  {model.cue.text}
                </text>
              )}
            </g>
          )}

          {/* 「估計」括線：每一段估計的頭尾各一個短直線，中間一條 1px 淡墨線（字是 HTML，蓋在線上） */}
          {brackets.map((b) => (
            <g key={`b${b.x1}`} stroke="var(--ink-2)" strokeWidth={1} data-bracket>
              <line x1={b.x1} x2={b.x2} y1={8.5} y2={8.5} />
              <line x1={b.x1 + 0.5} x2={b.x1 + 0.5} y1={4} y2={13} />
              <line x1={b.x2 - 0.5} x2={b.x2 - 0.5} y1={4} y2={13} />
            </g>
          ))}

          {/* 股利：領到的那一天在圖的下緣、橫軸的日期上面一個短直線（滑過的那一天是墨色、長一點） */}
          {comp &&
            days.map((t, i) =>
              divs.has(t) ? (
                <line
                  key={`d${t}`}
                  x1={x(i)}
                  x2={x(i)}
                  y1={top + plotH + (i === active ? 1 : 2)}
                  y2={top + plotH + COMP_TICKS - 1}
                  stroke={i === active ? "var(--chart-mine)" : "var(--ink-2)"}
                  strokeWidth={i === active ? 2 : 1.5}
                  data-dividend-mark
                />
              ) : null,
            )}
        </svg>
        {/* 「估計」括線的字（HTML，蓋在線上） */}
        {brackets.map((b) =>
          b.at === null ? null : (
            <span key={`l${b.x1}`} aria-hidden className="pointer-events-none absolute top-0 bg-background px-1 text-xs leading-[17px] text-ink-2" style={{ left: b.at }}>
              估計
            </span>
          ),
        )}
        {/* 只在用鍵盤移動時念（滑鼠滑過不念） */}
        <p className="sr-only" aria-live="polite">
          {a && fromKeys
            ? `${activeDay}${activeEst ? "（估計）" : ""}，總資產 ${money(a.market_value)}，` +
              (inv ? `${shownRecovered ? INVESTED_RECOVERED : `本金 ${money(shownAt.p)}`}，${gainSpeech(shownGain, money(Math.abs(shownGain)))}，` : comp ? "" : `投入本金 ${money(a.net_invested)}，`) +
              `報酬${retSpeech(activeRet)}` +
              (activeDividend > 0 ? `，領股利 ${money(activeDividend)}` : "")
            : ""}
        </p>
      </div>

      {/* 七顆一律放（比資料長的也可以選）；歷史短時說明在按鈕下面——按鈕的位置和歷史夠長以後一樣 */}
      <RangeChips className="mt-2 lg:col-start-2 lg:row-start-1 lg:mt-0 lg:self-start" label="走勢區間" value={range} options={TREND_RANGES} onChange={onRange} />
      {/* 圖下面不放拆解的句子（使用者 2026-11-19：只要圖）。只留資料說明：歷史短、估計的那幾天、Yahoo 參考價 */}
      {shortNote && <p className="mt-1.5 text-sm text-ink-2 lg:col-span-2">{shortNote}</p>}
      {estText && <p className="mt-1.5 text-sm text-ink-2 lg:col-span-2">{estText} 用估計的買入日計算</p>}
      {referenceLine && <p className="mt-1.5 text-sm text-ink-2 lg:col-span-2">{referenceLine}</p>}
    </section>
  )
}
