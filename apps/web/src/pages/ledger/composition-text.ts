import type { PerformanceMonth, PerformancePoint } from "@/api/types"
import { spanIndexes, type Spans } from "@/lib/asset-composition"
import { formatDateShort } from "@/lib/format"
import { needsYear, trendWindow, type TrendRange } from "@/lib/trend-range"

/**
 * 資產組成（原型）畫面上的字（純函式，測試得到）：估計那一段的說明、每月拆解的月份與期間。
 * 寫法照 DESIGN.md〈說明文字怎麼寫〉：講事實、一句一件事、日期和走勢的讀數同一套（跨年、1 年寫年份）。
 */

/**
 * 圖裡的小字用的約略金額（和縱軸刻度同一種寫法）：「296萬」「1.25億」「−50萬」；1 萬以下寫整數。
 * 本金在圖外時那一行「本金 296萬，在圖的下方」用它（準確的金額在圖例與下面那一句）。
 */
export function roughMoney(v: number): string {
  const sign = v < 0 ? "−" : ""
  const a = Math.abs(v)
  if (a >= 1e8) return `${sign}${Number((a / 1e8).toFixed(2))}億`
  if (a >= 1e4) return `${sign}${Math.round(a / 1e4).toLocaleString("zh-TW")}萬`
  return `${sign}${Math.round(a).toLocaleString("zh-TW")}`
}

/**
 * 本金 ≤ 0（賣股票收到的錢已經和買股票花的一樣多或更多）：首頁走勢 v2 的圖例、滑過的讀數、圖的說明、圖裡那一行都不寫金額，
 * 寫「本金已收回」（使用者 2026-11-19；負的本金看不懂）。賺的照實寫（總資產－本金），本金線畫在 0。
 * 本金開關關掉時沒有本金；每月表格的本金增減照舊寫金額。金額先四捨五入到元再判斷（和畫面上的數字一致）。
 */
export const INVESTED_RECOVERED = "本金已收回"
export const isRecovered = (invested: number) => invested <= 0

/** 本金在圖外（縱軸只跟總資產）時圖裡那一行：「本金 296萬，在圖的下方」；隱私模式不寫金額 */
export function offChartText(invested: number, side: "above" | "below", privacy: boolean): string {
  const where = side === "below" ? "在圖的下方" : "在圖的上方"
  return privacy ? `本金${where}` : `本金 ${roughMoney(invested)}，${where}`
}

/** 「8/14」；`withYear` 時「2024/8/14」 */
export const dayText = (t: string, withYear: boolean) => (withYear ? `${t.slice(0, 4)}/` : "") + formatDateShort(t, false)

/**
 * 走勢下面那一行：畫出來的這幾天裡，照估計的買入日算的是哪幾天——「2024/7/29 – 2025/11/28 用估計的買入日計算」；
 * 好幾段（分好幾次匯入）時一行列出來：「2024/7/29 – 2025/11/28、2026/9/1 – 2026/11/18 用估計的買入日計算」。
 * 只寫畫出來的部分（區間只碰到一部分時寫重疊的部分）；沒碰到是 null。
 */
export function estimatedLine(spans: Spans, days: readonly string[], withYear: boolean): string | null {
  const text = estimatedRangeText(spans, days, withYear)
  return text ? `${text} 用估計的買入日計算` : null
}

/**
 * 畫出來的這幾天裡估計的是哪幾天：「2024/7/29 – 2025/11/28」（只有一天時「8/14」），好幾段用頓號連起來；沒碰到是 null。
 * 連在一起的幾天算一段（`spanIndexes`）。
 */
export function estimatedRangeText(spans: Spans, days: readonly string[], withYear: boolean): string | null {
  const runs = spanIndexes(days, spans)
  if (runs.length === 0) return null
  return runs
    .map(({ first, last }) => {
      const from = days[first]!
      const until = days[last]!
      // 只有一天：不寫「8/14 – 8/14」
      return from === until ? dayText(from, withYear) : `${dayText(from, withYear)} – ${dayText(until, withYear)}`
    })
    .join("、")
}

/**
 * 一個區間裡估計的是哪幾天（首頁走勢那一行、績效分段指標下面那一行用同一個規則）：看這個區間畫出來的每一點，**含基準收盤**——
 * 基準收盤是區間報酬的分母，那天的總資產也是照估計的持股算的（和 Yahoo 參考價那一行同一個規則）。日期寫法和走勢的讀數一樣
 * （1 年、跨年寫年份）。`series` 是「全部」的序列。
 */
export function trendEstimatedText(series: readonly Pick<PerformancePoint, "t" | "twr_index">[], range: TrendRange, spans: Spans): string | null {
  if (!spans?.length || series.length === 0) return null
  const win = trendWindow(series, range)
  const days = win.points.map((p) => p.t)
  const withYear = (range === "1Y" && !win.exceeds) || needsYear(days)
  return estimatedRangeText(spans, days, withYear)
}

/** 估計的任何一段和 [start, end] 有沒有重疊（績效分段：這個區間有沒有用到估計的買入日） */
export function touchesSpan(spans: Spans, start: string | null, end: string | null): boolean {
  return !!spans && !!start && !!end && spans.some((s) => s.from <= end && s.until >= start)
}

/**
 * 每月拆解的月份：都在今年時「11 月」，跨年時「2025/12」（和走勢橫軸的「2026/07」同一種寫法，不補 0）。
 * `years`：表上有沒有別的年份。
 */
export function monthLabel(month: string, years: boolean): string {
  const [y, m] = month.split("-")
  return years ? `${y}/${Number(m)}` : `${Number(m)} 月`
}

/** 不是整個月的那一列算的是哪幾天：「10/12 – 10/30」（只有一天時「11/12」） */
export function monthSpanText(m: Pick<PerformanceMonth, "from" | "to" | "whole">): string | null {
  if (m.whole) return null
  return m.from === m.to ? formatDateShort(m.from, false) : `${formatDateShort(m.from, false)} – ${formatDateShort(m.to, false)}`
}

/** 報酬率和基準差幾個百分點：「多 0.45 個百分點」「少 1.20 個百分點」；算不出來是 null */
export function benchmarkGap(m: Pick<PerformanceMonth, "twr" | "benchmark_twr">): { word: "多" | "少"; points: string } | null {
  if (m.twr === null || m.benchmark_twr === null) return null
  const gap = (m.twr - m.benchmark_twr) * 100
  return { word: gap >= 0 ? "多" : "少", points: Math.abs(gap).toFixed(2) }
}

/** 「今年贏過」或「7/1 以來贏過」：比較的期間從今年第一週開始才說「今年」 */
export function fundRankPeriod(start: string, today: string): string {
  const sameYear = start.slice(0, 4) === today.slice(0, 4)
  if (sameYear && start.slice(5, 7) === "01" && Number(start.slice(8, 10)) <= 7) return "今年"
  return `${sameYear ? "" : `${start.slice(0, 4)}/`}${formatDateShort(start, false)} 以來`
}
