import type { PerformanceMonth, PerformancePoint } from "@/api/types"
import type { TrendRange } from "@/lib/trend-range"

/**
 * 資產組成（原型；`docs/proposals/asset-composition.md`）：本金＋賺的（或－虧的）＝總資產。
 * - 本金：買股票花的錢減掉賣股票收到的錢（和走勢的 `net_invested` 同一個數字；股利不扣）。程式裡有些地方還叫「投入本金」。
 * - 賺的／虧的（程式裡叫累積損益、`profit`）：總資產（持股市值）減本金。不含股利：股利另外列（領到的那一天一個記號）。
 * - 賣出讓本金下降、賺的不變（app 不記現金：賣出收到的錢不在總資產裡）。
 * 這裡只有純函式：首頁走勢的塗色（v2）、估計的那幾段、股利的記號、mock 的每月拆解都用它。
 */

/** 累積損益：總資產減投入本金 */
export const profitOf = (p: Pick<PerformancePoint, "market_value" | "net_invested">) => p.market_value - p.net_invested

export interface Span {
  from: string
  until: string
}

/** 估計的那幾段（`composition.estimated`）：每一次匯入一段，由舊到新；沒有估計的買進時是空的 */
export type Spans = readonly Span[] | null | undefined

/** 一天在不在估計的那一段裡（頭尾都含） */
export const inSpan = (t: string, span: Span | null | undefined) => !!span && t >= span.from && t <= span.until

/** 一天在不在任何一段估計裡 */
export const inSpans = (t: string, spans: Spans) => !!spans && spans.some((s) => inSpan(t, s))

/**
 * 估計的那幾段和畫出來的這幾天重疊的部分（在 `days` 裡的位置，頭尾都含），由舊到新；連在一起的（中間沒有不是估計的一天）算一段。
 * 沒有重疊是空的。`days` 由舊到新。
 */
export function spanIndexes(days: readonly string[], spans: Spans): { first: number; last: number }[] {
  const out: { first: number; last: number }[] = []
  if (!spans?.length) return out
  for (let i = 0; i < days.length; i++) {
    if (!inSpans(days[i]!, spans)) continue
    const run = out.at(-1)
    if (run && run.last === i - 1) run.last = i
    else out.push({ first: i, last: i })
  }
  return out
}

/**
 * 總資產線哪幾段畫細線（估計）、哪幾段照常（在 `n` 個點裡的位置）：每一段估計從它前一天畫到它後一天
 * （進出那一段的那一天也是估計的持股造成的），其他的照常；照常的那幾段和細線在交界的那一點接起來。
 */
export function estimatedRuns(n: number, est: readonly { first: number; last: number }[]): { thin: number[][]; thick: number[][] } {
  const range = (a: number, b: number) => (b < a ? [] : Array.from({ length: b - a + 1 }, (_, k) => a + k))
  const thin = est.map((e) => range(Math.max(0, e.first - 1), Math.min(n - 1, e.last + 1)))
  const thick: number[][] = []
  let from = 0
  for (const e of est) {
    thick.push(range(from, e.first - 1))
    from = e.last + 1
  }
  thick.push(range(from, n - 1))
  return { thin, thick: thick.filter((r) => r.length > 1) }
}

/**
 * 區間從 0 起算嗎（和 `trendWindow` 的 `base` 同一個規則）：「全部」、區間比資料長（`exceeds`）時，報酬的分母是 1——
 * 區間從資料的第一個收盤以前算起，所以錢也從 0 算起（首頁走勢的圖例寫「賺的」、股利從第一筆算）；其他區間從基準收盤（`points[0]`）算起。
 */
export const fromZero = (win: { exceeds?: boolean }, range: TrendRange) => range === "ALL" || !!win.exceeds

/**
 * 總資產走勢（v2，一張圖）裡塗色的那幾塊：總資產在本金線上面的部分是賺的、下面的部分是虧的。
 * - `points`：每個收盤日的總資產（`v`）與本金（`p`），由舊到新。
 * - **買進、賣出當作兩條線在那一天一起垂直跳**：本金是階梯線（第 i−1 天到第 i 天之間是第 i−1 天的本金，到第 i 天才跳）；
 *   總資產在這一段裡只畫價格的漲跌——斜到第 i 天「買賣以前」的值 `v[i] − (p[i] − p[i−1])`，到第 i 天再和本金一起垂直跳
 *   同樣的金額（`totalPreFlow`；畫面上的總資產線也照這樣畫）。所以每一個收盤日的左邊，塗的顏色就是那天收盤的賺或虧
 *   （`v[i] − p[i]`），垂直跳的時候賺的多少不變。不這樣做的話，買賣金額比當時的賺賠大的那一天會有一塊顏色相反的三角形
 *   （例如整批賣出那一天，收盤明明都是賺的，中間卻塗成虧）。
 * - 每一段裡兩條線最多交會一次，交會點用比例算出來：在那一點換顏色（不是在收盤日上換），兩塊剛好接在兩條線交會的地方。
 * - 回傳一塊一塊的多邊形，座標是「第幾個收盤（可以是小數）」與金額；同一邊連在一起的是同一塊。兩條線重疊（面積 0）的那幾段不畫。
 * - `floor`（首頁走勢 v2 傳 0）：塗色的下緣（本金線）不低於這個金額——本金 ≤ 0 時畫面寫「本金已收回」，本金線畫在 0、塗色從 0 塗到總資產。
 *   總資產那一邊照舊用真的本金算（`totalPreFlow`：買賣那一天照樣和真的本金一起垂直跳），只有下緣被墊高。總資產不會是負的，
 *   所以本金 ≤ 0 的日子一定是賺的，每一個收盤的顏色＝`v − max(p, floor)` 的正負號，也就是真的賺的（`v − p`）的正負號；
 *   代價是那幾天塗的高度（`v`）比圖例寫的賺的（`v − p`）少了 `−p`（提案附錄 A 寫了這一點）。
 */
export type BandSide = "gain" | "loss"
export interface ProfitBand {
  side: BandSide
  /** 多邊形的頂點：沿著總資產由左到右，再沿著本金由右到左（封閉） */
  points: [number, number][]
}

/** 第 i 天買賣以前的總資產（`v[i] − (p[i] − p[i−1])`）：總資產線在第 i−1 天到第 i 天之間斜到這裡，再垂直跳到收盤的值 */
export const totalPreFlow = (points: readonly { v: number; p: number }[], i: number) => (i === 0 ? points[0]!.v : points[i]!.v - (points[i]!.p - points[i - 1]!.p))

export function profitBands(points: readonly { v: number; p: number }[], opts: { floor?: number } = {}): ProfitBand[] {
  const { floor } = opts
  // 塗色的下緣：本金（有 `floor` 時不低於它）
  const baseOf = (p: number) => (floor === undefined ? p : Math.max(p, floor))
  const out: ProfitBand[] = []
  let run: { side: BandSide; upper: [number, number][]; lower: [number, number][] } | null = null
  const close = () => {
    if (run) out.push({ side: run.side, points: [...run.upper, ...run.lower.reverse()] })
    run = null
  }
  // 一小段：總資產從 (x0, v0) 斜到 (x1, v1)，本金平平的是 c
  const add = (side: BandSide, x0: number, v0: number, x1: number, v1: number, c: number) => {
    const upper = run?.upper.at(-1)
    const lower = run?.lower.at(-1)
    if (run && run.side === side && upper && lower && upper[0] === x0) {
      // 接著上一段：那一天有買賣時，上緣（總資產）和下緣（本金）各多一段垂直的邊，跳一樣的金額
      if (upper[1] !== v0) run.upper.push([x0, v0])
      if (lower[1] !== c) run.lower.push([x0, c])
      run.upper.push([x1, v1])
      run.lower.push([x1, c])
      return
    }
    close()
    run = { side, upper: [[x0, v0], [x1, v1]], lower: [[x0, c], [x1, c]] }
  }
  for (let k = 1; k < points.length; k++) {
    const c = baseOf(points[k - 1]!.p)
    const a = points[k - 1]!.v
    // 這一段的終點是第 k 天買賣以前的值：d1 就是第 k 天收盤真正的賺賠（v[k] − p[k]），和下一段的起點 d0 一樣。
    // 有 `floor` 而且本金碰到它時兩者的大小可以不一樣（下緣跳的和總資產跳的不一樣多），正負號一樣（見上面）
    const b = totalPreFlow(points, k)
    const d0 = a - c
    const d1 = b - c
    if (d0 === 0 && d1 === 0) {
      close()
      continue
    }
    if (d0 >= 0 && d1 >= 0) add("gain", k - 1, a, k, b, c)
    else if (d0 <= 0 && d1 <= 0) add("loss", k - 1, a, k, b, c)
    else {
      // 這一段裡交會：總資產＝本金的那一點
      const xm = k - 1 + d0 / (d0 - d1)
      add(d0 > 0 ? "gain" : "loss", k - 1, a, xm, c, c)
      add(d0 > 0 ? "loss" : "gain", xm, c, k, b, c)
    }
  }
  close()
  return out
}

/**
 * 總資產走勢（v2）的縱軸要不要把本金也放進來：總資產自己在這段期間的起伏，至少是「兩條線都放得下」所需範圍的 35%（`threshold`）時，
 * 縱軸貼著兩條線（`both`）；不到時縱軸只跟總資產（`total`，和以前一樣）——本金差太遠，硬放進來總資產的起伏會被壓扁。
 * 只看這段期間的資料，和滑到哪一天無關（滑過時縱軸不跳）。兩條線都是平的時是 `both`。
 */
export const AXIS_FIT_THRESHOLD = 0.35

export function compositionAxis(points: readonly { v: number; p: number }[], threshold = AXIS_FIT_THRESHOLD): { mode: "both" | "total"; ratio: number } {
  if (points.length === 0) return { mode: "total", ratio: 1 }
  let vLo = Infinity
  let vHi = -Infinity
  let lo = Infinity
  let hi = -Infinity
  for (const { v, p } of points) {
    vLo = Math.min(vLo, v)
    vHi = Math.max(vHi, v)
    lo = Math.min(lo, v, p)
    hi = Math.max(hi, v, p)
  }
  const ratio = hi > lo ? (vHi - vLo) / (hi - lo) : 1
  return { mode: ratio >= threshold ? "both" : "total", ratio }
}

/** 一天領了多少股利（同一天好幾筆加起來）；沒有是 0 */
export function dividendsByDay(dividends: readonly { t: string; amount: number }[]): Map<string, number> {
  const out = new Map<string, number>()
  for (const d of dividends) out.set(d.t, (out.get(d.t) ?? 0) + d.amount)
  return out
}

/**
 * 股利的日期對到收盤日：週末、假日（沒有收盤）領的，算在下一個收盤日（記號、滑過的讀數、拆解的句子都用這一天，才對得起來）。
 * `days` 是序列的收盤日（由舊到新）；最後一個收盤以後的不列。同一天好幾筆加起來。
 */
export function snapDividends(dividends: readonly { t: string; amount: number }[], days: readonly string[]): { t: string; amount: number }[] {
  const out = new Map<string, number>()
  for (const d of dividends) {
    let lo = 0
    let hi = days.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (days[mid]! < d.t) lo = mid + 1
      else hi = mid
    }
    const day = days[lo]
    if (day === undefined) continue
    out.set(day, (out.get(day) ?? 0) + d.amount)
  }
  return [...out].map(([t, amount]) => ({ t, amount }))
}

/** 每月拆解用的一天（和績效序列同樣的欄位） */
export type MonthPoint = Pick<PerformancePoint, "t" | "market_value" | "net_invested" | "twr_index" | "benchmark_index">

/**
 * 每個月的拆解（績效分段「每月報酬率」）：一個月一列，由新到舊。
 * - `points`：這個區間的收盤（由舊到新）；`base`：區間第一個收盤的前一個收盤（區間從第一筆開始時是 null，當成 0）。
 * - 加碼或拿回＝投入本金的變化；這個月的損益＝累積損益的變化（不含股利）；報酬率＝時間加權（`twr_index` 相除）；
 *   和基準差多少用 `benchmark_index`（沒有時是 null）。
 * - 估計的那幾段（`estimated`，每一次匯入一段）裡的收盤不列：整個月都在估計裡的月份略過（算進 `skipped`），只有一部分在裡面的月份
 *   只算真實紀錄的那幾天（一段估計切在月中時，前後兩部分各一列）。
 * - `whole`：這一列是不是整個月（前一個收盤在上個月、而且月底以後還有收盤）；不是的話畫面寫出它算的是哪幾天。
 * - 從第一筆開始（`base` 是 null）的第一個月：自己的報酬含第一天（分母是 1），基準在第一天以前沒有收盤可以當分母，
 *   兩邊算的天數不一樣——那個月和基準的差距是 null（畫面寫「—」），不拿不同的期間比。
 * - `importDays`（暫定，產品負責人還沒決定；見提案附錄 A）：匯入時找不到買入日、用匯入那天記的買進——成本到那天收盤的漲跌
 *   全部算在那一天。那一天（對到它當天或下一個收盤日）所在的月份整個不列，另外數（`skippedImport`）。
 *   要拿掉這條規則：不傳 `importDays` 就好。
 */
export function monthlyBreakdown(
  points: readonly MonthPoint[],
  opts: { base: MonthPoint | null; estimated?: Spans; importDays?: readonly string[] },
): { months: PerformanceMonth[]; skipped: number; skippedImport: number } {
  const zero: MonthPoint | null = points[0] ? { t: "", market_value: 0, net_invested: 0, twr_index: 1, benchmark_index: null } : null
  // 匯入那天對到的收盤日所在的月份（匯入在週末時，漲跌算在下一個收盤日）；對到基準收盤或更早的（在這個區間以前）不算
  const importMonths = new Set(
    (opts.importDays ?? []).flatMap((d) => (opts.base && opts.base.t >= d ? [] : (points.find((p) => p.t >= d)?.t.slice(0, 7) ?? []))),
  )
  const groups: { month: string; est: boolean; from: number; to: number }[] = []
  points.forEach((p, i) => {
    const month = p.t.slice(0, 7)
    const est = inSpans(p.t, opts.estimated)
    const g = groups.at(-1)
    if (g && g.month === month && g.est === est) g.to = i
    else groups.push({ month, est, from: i, to: i })
  })
  const realMonths = new Set(groups.filter((g) => !g.est).map((g) => g.month))
  const skipped = new Set(groups.filter((g) => g.est && !realMonths.has(g.month)).map((g) => g.month)).size
  const skippedImport = [...realMonths].filter((m) => importMonths.has(m)).length
  const months: PerformanceMonth[] = []
  for (const g of groups) {
    if (g.est || importMonths.has(g.month)) continue
    const base = g.from > 0 ? points[g.from - 1]! : (opts.base ?? zero)
    const last = points[g.to]!
    if (!base) continue
    const startsAtMonth = !!base.t && base.t.slice(0, 7) < g.month
    const next = points[g.to + 1]
    const endsAtMonth = !!next && next.t.slice(0, 7) > g.month
    const twr = base.twr_index ? last.twr_index / base.twr_index - 1 : null
    const bench = base.benchmark_index && last.benchmark_index !== null ? last.benchmark_index / base.benchmark_index - 1 : null
    months.push({
      month: g.month,
      from: points[g.from]!.t,
      to: last.t,
      whole: startsAtMonth && endsAtMonth,
      flows: round2(last.net_invested - base.net_invested),
      pnl: round2(profitOf(last) - profitOf(base)),
      twr: twr === null ? null : round6(twr),
      benchmark_twr: bench === null ? null : round6(bench),
    })
  }
  return { months: months.reverse(), skipped, skippedImport }
}

const round2 = (n: number) => Math.round(n * 100) / 100
const round6 = (n: number) => Math.round(n * 1e6) / 1e6
