import { readMockPolicy } from "@/api/mock/commercial"
import type { ForliosaApi, HistoryRange, Instrument, PerformanceRange } from "@/api/types"
import { formatPercent, formatRevenueThousands } from "@/lib/format"
import { normalize } from "./intent"
import type { AiChart } from "./remote"

/**
 * 本機規則版的「畫圖」（mock 模式與後端沒有 AI 時）：認得「畫 0050 的走勢」「比較 2330 和 2317」
 * 「畫台積電的月營收」這類句子，用 API 的資料組出和後端 `draw_chart` 同樣形狀的圖卡。
 * 連真實後端時不走這裡：畫什麼由模型決定、數字由伺服器讀。
 */

export type ChartRange = "1M" | "3M" | "6M" | "YTD" | "1Y" | "5Y"

export interface ChartIntent {
  kind: AiChart["kind"]
  /** 代號或名稱（照使用者說的順序）；performance 沒有 */
  targets: string[]
  range: ChartRange
}

export const RANGE_LABELS: Record<ChartRange, string> = { "1M": "近 1 個月", "3M": "近 3 個月", "6M": "近 6 個月", YTD: "今年以來", "1Y": "近 1 年", "5Y": "近 5 年" }

const DRAW = /(畫|圖表|走勢圖|線圖|折線圖|柱狀圖|作圖)/
const COMPARE = /(比較|對比|比一比|\bvs\.?\b|pk)/i
/** 不是商品名稱的字：動詞、量詞、時間、圖的種類 */
const NOISE =
  /(幫我|請|畫出|畫個|畫一張|畫|圖表|走勢圖|折線圖|線圖|柱狀圖|作圖|比較|對比|比一比|一下|看看|這|最近|過去|近|今年以來|今年|半年|一年|五年|兩年|三個月|六個月|一個月|\d+\s*個月|\d+\s*年|月營收|營收|每季|每股盈餘|EPS|eps|收盤價|股價|走勢|趨勢|表現|漲跌幅|漲跌|報酬率|績效|的|圖|張)/g
const SPLIT = /[\s,、，;；/&]+|還有|\bvs\.?\b|\bpk\b/i
/** 「台積電和鴻海」的連接詞；開頭就是這個字的是名稱的一部分（和碩、和泰車） */
const JOIN = /[和與跟及]/

export function chartRange(text: string): ChartRange {
  const t = normalize(text).replace(/\s/g, "")
  if (/(五年|5年)/.test(t)) return "5Y"
  if (/(一年|1年|12個月|十二個月)/.test(t)) return "1Y"
  if (/今年/.test(t)) return "YTD"
  if (/(三個月|3個月|一季)/.test(t)) return "3M"
  if (/(一個月|1個月)/.test(t)) return "1M"
  return "6M"
}

/** 「畫／比較」的句子 → 要畫什麼；不是要畫圖的句子回 null（交給其他規則） */
export function parseChartIntent(raw: string): ChartIntent | null {
  const text = normalize(raw)
  const flat = text.replace(/\s/g, "")
  const draws = DRAW.test(flat)
  const compares = COMPARE.test(text)
  if (!draws && !compares) return null
  const range = chartRange(text)
  if (/(我的|投資組合|帳本).*(報酬率|績效|走勢)|績效圖/.test(flat)) return draws ? { kind: "performance", targets: [], range } : null
  const targets = [
    ...new Set(
      text
        .replace(NOISE, " ")
        .split(SPLIT)
        .flatMap((tok) => (tok && tok.search(JOIN) > 0 ? tok.split(JOIN) : [tok]))
        .map((s) => s?.trim())
        .filter((s): s is string => !!s && s.length <= 12 && /[0-9A-Za-z一-鿿]/.test(s) && !/^[和與跟及]$/.test(s)),
    ),
  ].slice(0, 5)
  if (targets.length === 0) return null
  if (/營收/.test(flat)) return { kind: "revenue", targets, range }
  if (/(eps|每股盈餘)/i.test(flat)) return { kind: "eps", targets, range }
  if (targets.length >= 2) return { kind: "compare", targets, range }
  return draws ? { kind: "price", targets, range } : null
}

const HISTORY_RANGE: Record<ChartRange, HistoryRange> = { "1M": "1M", "3M": "6M", "6M": "6M", YTD: "YTD", "1Y": "1Y", "5Y": "5Y" }
const PERFORMANCE_RANGE: Record<ChartRange, PerformanceRange> = { "1M": "1M", "3M": "3M", "6M": "6M", YTD: "YTD", "1Y": "1Y", "5Y": "ALL" }

function monthsAgo(today: string, n: number): string {
  const d = new Date(`${today}T00:00:00Z`)
  d.setUTCMonth(d.getUTCMonth() - n)
  return d.toISOString().slice(0, 10)
}

type Points = AiChart["series"][number]["points"]

async function closes(api: ForliosaApi, inst: Instrument, range: ChartRange, today: string): Promise<{ points: Points; notes: string[]; sources: string[]; isDemo: boolean }> {
  const h = await api.getHistory(inst.symbol, HISTORY_RANGE[range])
  const from = range === "3M" ? monthsAgo(today, 3) : ""
  return {
    points: h.candles.filter((c) => c.t >= from).map((c) => ({ t: c.t, v: c.c })),
    notes: h.notes ?? [],
    sources: h.sources ?? [],
    isDemo: h.is_demo,
  }
}

const names = (items: { name: string }[]) => items.map((i) => i.name).join("、")
const uniq = (items: string[]) => [...new Set(items)]

/** 每條線最多留這麼多點（和後端同一個上限的精神：長的區間取樣，不截斷） */
function sample(points: Points, cap: number): Points {
  if (points.length <= cap) return points
  const step = (points.length - 1) / (cap - 1)
  const idx = [...new Set(Array.from({ length: cap }, (_, i) => Math.round(i * step)))]
  return idx.map((i) => points[i]!)
}

export type LocalChart = { chart: AiChart; text: string } | { chart: null; text: string }

/**
 * 用 API 的資料組圖卡。`resolve` 把使用者說的代號或名稱對到商品（找不到回 null）。
 * 回傳的 `text` 是本機規則寫的一句話（墨色 Noto Sans，不是模型寫的）。
 */
export async function buildLocalChart(
  intent: ChartIntent,
  deps: { api: ForliosaApi; resolve: (target: string) => Promise<Instrument | null>; today: string; newId: (prefix: string) => string },
): Promise<LocalChart> {
  const { api, today } = deps
  const id = deps.newId("cht")
  const label = RANGE_LABELS[intent.range]
  const done = (chart: Omit<AiChart, "id" | "series" | "notes" | "sources"> & { series: AiChart["series"]; notes: string[]; sources: string[] }, text: string): LocalChart => {
    const cap = Math.max(40, Math.floor(480 / Math.max(1, chart.series.length)))
    return { chart: { ...chart, id, series: chart.series.map((s) => ({ ...s, points: sample(s.points, cap) })), notes: uniq(chart.notes), sources: uniq(chart.sources) }, text }
  }

  if (intent.kind === "performance") {
    const perf = await api.getPerformance({ range: PERFORMANCE_RANGE[intent.range] })
    if (perf.series.length < 2) return { chart: null, text: perf.notes?.[0] ? `${perf.notes[0]}。` : "帳本的資料不到兩個交易日，畫不出報酬率。" }
    const series: AiChart["series"] = [{ name: "我的報酬率", symbol: null, points: perf.series.map((p) => ({ t: p.t, v: Number((p.twr_index - 1).toFixed(6)) })) }]
    if (perf.benchmark && perf.series.every((p) => p.benchmark_index !== null)) {
      series.push({ name: perf.benchmark.name, symbol: perf.benchmark.symbol, points: perf.series.map((p) => ({ t: p.t, v: Number((p.benchmark_index! - 1).toFixed(6)) })) })
    }
    const title = series.length > 1 ? `我的報酬率與${perf.benchmark!.name}（${label}）` : `我的報酬率（${label}）`
    return done(
      { kind: "performance", title, unit: "pct", currency: null, x: "date", range: intent.range, series, notes: [...(perf.notes ?? []), "報酬率是時間加權報酬率；基準含股利"], sources: ["帳本紀錄"], is_demo: perf.is_demo },
      `${label}${series.map((s) => `${s.name === "我的報酬率" ? "我的報酬率" : s.name} ${formatPercent(s.points.at(-1)!.v)}`).join("、")}。`,
    )
  }

  const found: Instrument[] = []
  const missing: string[] = []
  for (const t of intent.targets) {
    const inst = await deps.resolve(t)
    if (!inst) missing.push(t)
    else if (!found.some((f) => f.symbol === inst.symbol)) found.push(inst)
  }
  if (found.length === 0) return { chart: null, text: `找不到「${missing.join("、")}」。換個代號試試，例如 0050、2330。` }
  const notes = missing.map((m) => `找不到「${m}」，沒有畫`)

  if (intent.kind === "price" || (intent.kind === "compare" && found.length === 1)) {
    const inst = found[0]!
    const c = await closes(api, inst, intent.range, today)
    if (c.points.length < 2) return { chart: null, text: c.notes[0] ? `${inst.name}：${c.notes[0]}，畫不出走勢。` : `${inst.name}的收盤價不到兩天，畫不出走勢。` }
    return done(
      { kind: "price", title: `${inst.name} 收盤價（${label}）`, unit: "price", currency: inst.currency, x: "date", range: intent.range, series: [{ name: inst.name, symbol: inst.symbol, points: c.points }], notes: [...notes, ...c.notes, "收盤價沒有還原權息，除權息日會有缺口"], sources: c.sources, is_demo: c.isDemo },
      `${label}${inst.name} ${formatPercent(c.points.at(-1)!.v / c.points[0]!.v - 1)}。`,
    )
  }

  if (intent.kind === "compare") {
    const lines: { inst: Instrument; points: Points }[] = []
    const sources: string[] = []
    let isDemo = false
    for (const inst of found) {
      const c = await closes(api, inst, intent.range, today)
      if (c.points.length < 2) {
        notes.push(`${inst.name}：${c.notes[0] ?? "收盤價不到兩天"}，沒有畫`)
        continue
      }
      lines.push({ inst, points: c.points })
      notes.push(...c.notes)
      sources.push(...c.sources)
      isDemo ||= c.isDemo
    }
    if (lines.length < 2) return { chart: null, text: notes[0] ? `${notes[0]}。要比較至少需要兩檔有收盤價的商品。` : "要比較至少需要兩檔有收盤價的商品。" }
    const base = lines.map((l) => l.points[0]!.t).sort().at(-1)!
    const series = lines.map(({ inst, points }) => {
      const kept = points.filter((p) => p.t >= base)
      const first = kept[0]!.v
      return { name: inst.name, symbol: inst.symbol, points: kept.map((p) => ({ t: p.t, v: Number((p.v / first - 1).toFixed(6)) })) }
    })
    return done(
      { kind: "compare", title: `${names(series)} 漲跌幅（${label}）`, unit: "pct", currency: null, x: "date", range: intent.range, series, notes: [...notes, "漲跌幅只算價格變動，不含股利"], sources, is_demo: isDemo },
      `${label}${series.map((s) => `${s.name} ${formatPercent(s.points.at(-1)!.v)}`).join("、")}。`,
    )
  }

  // 月營收、每季每股盈餘：類別軸
  const series: AiChart["series"] = []
  const sources: string[] = []
  for (const inst of found) {
    if (intent.kind === "revenue") {
      const rows = inst.type === "stock" && inst.market !== "US" ? [...(await api.getRevenue(inst.symbol))].sort((a, b) => a.period.localeCompare(b.period)).slice(-24) : []
      if (rows.length === 0) notes.push(`${inst.name} 沒有月營收資料`)
      else series.push({ name: inst.name, symbol: inst.symbol, points: rows.map((r) => ({ t: r.period, v: r.revenue })) })
    } else {
      const f = inst.type === "stock" ? await api.getFinancials(inst.symbol, "quarterly") : null
      const pairs = (f?.periods ?? []).map((p, i) => ({ t: p, v: f!.income.eps[i] })).filter((p): p is { t: string; v: number } => typeof p.v === "number").slice(-8)
      if (pairs.length === 0) notes.push(`${inst.name} 沒有每股盈餘資料`)
      else {
        series.push({ name: inst.name, symbol: inst.symbol, points: pairs })
        sources.push(...(f?.sources ?? []))
      }
    }
  }
  if (series.length === 0) return { chart: null, text: `${notes.join("；")}。` }
  const revenue = intent.kind === "revenue"
  return done(
    {
      kind: intent.kind,
      title: `${names(series)} ${revenue ? "月營收" : "每季每股盈餘"}`,
      unit: revenue ? "amount_k" : "eps",
      currency: revenue ? "TWD" : found[0]!.currency,
      x: revenue ? "month" : "quarter",
      range: null,
      series,
      notes,
      sources,
      // mock 的商用模式模擬真實資料（畫面上不標「示範資料」）；個人模式才標
      is_demo: api.kind === "mock" && readMockPolicy() === "personal",
    },
    // 一句事實（最新一期），不是「畫好了」這種流程話：圖卡的標題已經說了畫的是什麼
    series
      .map((s) => {
        const last = s.points.at(-1)!
        return revenue ? `${s.name} ${periodLabel(String(last.t))}營收 ${formatRevenueThousands(last.v)} 元` : `${s.name} ${last.t} 每股盈餘 ${last.v.toFixed(2)} 元`
      })
      .join("、") + "。",
  )
}

/** 月營收的期別：「2026-10」→「10 月」 */
function periodLabel(period: string): string {
  const m = /^\d{4}-(\d{2})/.exec(period)
  return m ? `${Number(m[1])} 月` : period
}
