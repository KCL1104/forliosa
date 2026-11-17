import type { AiChart } from "@/ai/remote"
import {
  ApiError,
  REPORT_KIND_LABEL,
  type AdminReportRun,
  type AdminReportsOverview,
  type AdminTrial,
  type MacroEvent,
  type MacroEventInput,
  type MarketReport,
  type NyseHoliday,
  type NyseHolidayInput,
  type Paged,
  type ReportBlock,
  type ReportCalendar,
  type ReportCalendarRow,
  type ReportEdition,
  type ReportFootnote,
  type ReportItem,
  type ReportKind,
  type ReportNumberItem,
  type ReportParagraph,
  type ReportSection,
  type ReportSentence,
  type ReportsConfigPatch,
  type ReportsConfigResult,
  type ReportsMode,
  type ReportsStatus,
  type ReportSummary,
  type ReportTable,
  type ReportTone,
  type ReportVariant,
  type TrialMetrics,
  type TrialReveal,
  type TrialRevealRow,
  type UsEarning,
  type UsEarningInput,
  type WriterSetting,
} from "../types"
import { addDays, parseDay } from "./market"

/**
 * 市場報告的示範資料（mock 模式；合約 §12、§14、§17）。形狀和後端一樣，**數字與報導都是假的**（媒體是「示範通訊社」這類虛構名稱，
 * 連到 example.com）。報告依示範資料的「現在」產生：盤前 07:25、盤後 15:55（23:45 補表）、週報週日 18:00。
 *
 * 情境（網址 `?mreport=`，記在 sessionStorage）：
 * - `trial`（預設，和正式環境剛上線一樣）：盲測中（第 3／5 個交易日），報告只有站方管理員看得到；目前那一版是只有資料的版本，
 *   A／B／C 在管理後台
 * - `public`：盲測做完、揭曉、對全站公開；三種報告都有 AI 版。最新的盤後重點有一則更正、有一份只有資料、有一份官方加權指數沒進來
 * - `pending`：public，但最新的盤前重點 AI 段落還在整理（只有資料的版本）
 * - `off`：伺服器沒有開市場報告
 */
export type MockReportsScenario = "trial" | "public" | "pending" | "off"

export function readMockReports(): MockReportsScenario | undefined {
  if (typeof window === "undefined") return undefined
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("mreport")
    if (fromUrl === "trial") window.sessionStorage.removeItem("forliosa:mock-mreport")
    else if (fromUrl === "public" || fromUrl === "pending" || fromUrl === "off") window.sessionStorage.setItem("forliosa:mock-mreport", fromUrl)
    const saved = window.sessionStorage.getItem("forliosa:mock-mreport")
    return saved === "public" || saved === "pending" || saved === "off" ? saved : undefined
  } catch {
    return undefined
  }
}

// ── 日期 ─────────────────────────────────────────────
const WEEK = "日一二三四五六"
const wd = (d: string) => WEEK[parseDay(d).getUTCDay()]!
const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`
const mdw = (d: string) => `${md(d)}（${wd(d)}）`
const isWeekday = (d: string) => ![0, 6].includes(parseDay(d).getUTCDay())
const prevTrading = (d: string) => {
  let x = addDays(d, -1)
  while (!isWeekday(x)) x = addDays(x, -1)
  return x
}
const nextTrading = (d: string) => {
  let x = addDays(d, 1)
  while (!isWeekday(x)) x = addDays(x, 1)
  return x
}
const at = (d: string, hm: string) => `${d}T${hm}:00+08:00`
/** 示範的存檔從這一天開始（圖與多期間報酬的「10/26 起」） */
const ARCHIVE_FROM = "2026-10-26"

// ── 數字與字 ────────────────────────────────────────
function rng(seed: string): () => number {
  let x = [...seed].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % 2147483648
  return () => {
    x = (x * 1103515245 + 12345) % 2147483648
    return x / 2147483648
  }
}
const between = (r: () => number, lo: number, hi: number, nd = 4) => Number((lo + r() * (hi - lo)).toFixed(nd))
const fmt = (v: number, nd = 2) => new Intl.NumberFormat("en-US", { minimumFractionDigits: nd, maximumFractionDigits: nd }).format(Math.abs(v))
const pct = (f: number) => {
  const q = Math.round(f * 10000) / 100
  return q === 0 ? "0.00%" : `${q > 0 ? "▲" : "▼"}${fmt(q)}%`
}
const arrow = (v: number, nd = 2) => (Math.abs(v) < 10 ** -nd / 2 ? "平盤" : `${v > 0 ? "▲" : "▼"}${fmt(v, nd)}`)
const signed = (v: number, nd = 0, unit = "") => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(v, nd)}${unit}`
const tone = (v: number): ReportTone => (v > 0 ? "rise" : v < 0 ? "fall" : "flat")
const cellTone = (v: number) => (v > 0 ? ("rise" as const) : v < 0 ? ("fall" as const) : null)
const rise = (v: number) => (v >= 0 ? "上漲" : "下跌")

const DISCLAIMER_AI = "AI 依公開資料與媒體報導整理，報告本文人人相同，可能有錯；Forliosa 不是投資顧問，不提供投資建議。"
const DISCLAIMER_DATA = "依公開資料整理，報告本文人人相同；Forliosa 不是投資顧問，不提供投資建議。"
const DISCLAIMER_FULL =
  "這份報告由 AI 依公開資料與媒體報導整理，報告本文人人相同，不針對任何人的持股或財務狀況。Forliosa 只替你整理資訊，不是投資顧問；這份報告不是投資建議，也不推薦買賣任何股票。內容可能有錯，請以原始來源為準。標「估算」的數字是 Forliosa 自己算的。"
const MODEL_LINE = "這份報告的 AI 段落由 Anthropic 的 Claude 模型撰寫。"
const ORIGIN = { data: "資料", ai: "AI 依資料與報導整理" } as const
const PENDING_LINE = "AI 段落還在整理，這是只有資料的版本。"
const NO_AI_LINE = "這一份沒有 AI 段落，只有資料。"
const TRIAL_LINE = "盲測中：AI 段落的三個版本在管理後台比較。"
const lic = (name: string) => `${name}（2026），依政府資料開放授權條款第 1 版`
const LIC = {
  index: lic("臺灣證券交易所〈每日收盤行情－大盤統計資訊〉"),
  price: lic("臺灣證券交易所〈上市個股日成交資訊〉"),
  tpex: lic("證券櫃檯買賣中心〈櫃買指數與上櫃股票行情〉"),
  taifex: lic("臺灣期貨交易所〈三大法人期貨與選擇權部位〉"),
  fx: lic("中央銀行〈銀行間新臺幣對美元收盤匯率〉"),
  filings: lic("臺灣證券交易所〈上市公司每日重大訊息〉"),
  us: "美股收盤價：Databento（Nasdaq NLS Plus 官方合併收盤）",
}
const MANUAL_LINE = "美股休市、總經數據與美股財報的時間：Forliosa 自行整理，每列連回官方頁面"

// ── 編號與註腳（和伺服器的組裝一樣：依第一次出現的順序編號，同一個資料集＋同一天合成一個註腳） ──
type Ref =
  | { kind: "data"; group: string; label: string }
  | { kind: "web" | "research"; outlet: string; title: string; url: string; date_label: string }
  | { kind: "calendar" | "filing"; label: string; url: string | null; date_label: string | null }
type Reg = Map<string, Ref>
const S = (text: string, ...refs: string[]): ReportSentence => ({ text, cites: [], refs })
const P = (...sentences: ReportSentence[]): ReportParagraph => ({ sentences })

function paragraphsOf(r: MarketReport): ReportParagraph[] {
  const out: ReportParagraph[] = [...r.highlights]
  for (const s of r.sections) {
    for (const b of s.blocks) {
      if (b.type === "text") out.push(...b.paragraphs)
      else if (b.type === "items") for (const i of b.items) out.push(...i.paragraphs)
      else if (b.type === "chart" && b.caption) out.push(b.caption)
    }
  }
  return out
}

/** refs → 註腳號碼、註腳清單、來源裡的報導（只放被引用的） */
function assemble(r: MarketReport, reg: Reg): MarketReport {
  const numberOf = new Map<string, number>()
  const footnotes: ReportFootnote[] = []
  const keyOf = (id: string) => {
    const ref = reg.get(id)
    return ref?.kind === "data" ? `data:${ref.group}` : id
  }
  for (const p of paragraphsOf(r)) {
    for (const s of p.sentences) {
      const cites = new Set<number>()
      for (const id of s.refs ?? []) {
        const ref = reg.get(id)
        if (!ref) continue
        const key = keyOf(id)
        let n = numberOf.get(key)
        if (n === undefined) {
          n = footnotes.length + 1
          numberOf.set(key, n)
          footnotes.push(
            ref.kind === "data"
              ? { n, kind: "data", label: ref.label, outlet: null, url: null, date_label: null }
              : "title" in ref
                ? { n, kind: ref.kind, label: ref.title, outlet: ref.outlet, url: ref.url, date_label: ref.date_label }
                : { n, kind: ref.kind, label: ref.label, outlet: null, url: ref.url, date_label: ref.date_label },
          )
        }
        cites.add(n)
      }
      s.cites = [...cites].sort((a, b) => a - b)
    }
  }
  const web = footnotes.filter((f) => f.kind === "web" && f.url && f.outlet).map((f) => ({ n: f.n, outlet: f.outlet!, title: f.label, url: f.url!, published_label: f.date_label ?? "" }))
  return { ...r, footnotes, sources: { ...r.sources, web } }
}

/** 一般使用者看到的樣子：沒有 refs、沒有被拿掉的段、沒有 validation */
export function publicView(r: MarketReport): MarketReport {
  const strip = (p: ReportParagraph): ReportParagraph => ({ sentences: p.sentences.map(({ text, cites }) => ({ text, cites })) })
  const block = (b: ReportBlock): ReportBlock =>
    b.type === "text"
      ? { ...b, paragraphs: b.paragraphs.map(strip) }
      : b.type === "items"
        ? { ...b, items: b.items.map((i) => ({ ...i, paragraphs: i.paragraphs.map(strip) })) }
        : b.type === "chart"
          ? { ...b, caption: b.caption ? strip(b.caption) : null }
          : b
  const out: MarketReport = {
    ...r,
    highlights: r.highlights.map(strip),
    sections: r.sections.filter((s) => !s.dropped).map((s) => ({ ...s, blocks: s.blocks.map(block) })),
  }
  delete out.validation
  return out
}

// ── 共用的圖、表 ──────────────────────────────────────
const chart = (c: Partial<AiChart> & Pick<AiChart, "id" | "kind" | "title" | "unit" | "x">): AiChart => ({
  currency: null, range: null, series: [], notes: [], sources: [], is_demo: false, ...c,
})
const section = (key: string, title: string, origin: "data" | "ai", blocks: ReportBlock[], collapsed_mobile = false): ReportSection => ({
  key, title, origin, origin_label: ORIGIN[origin], collapsed_mobile, blocks,
})
const table = (t: Partial<ReportTable> & Pick<ReportTable, "id" | "title" | "columns" | "rows">): ReportTable => ({
  rule: null, fold_after: null, empty_text: null, note: null, source_labels: [], ...t,
})
const col = (key: string, label: string, align: "left" | "right" = "right", num = align === "right") => ({ key, label, align, num })
const stockHref = (code: string) => `/stock/${code}.TW`

/** 交易日（只排除週末），舊到新，`to` 以前（含）最多 n 天、不早於 `from` */
function tradingDays(to: string, n: number, from = ARCHIVE_FROM): string[] {
  const out: string[] = []
  let d = to
  while (out.length < n && d >= from) {
    if (isWeekday(d)) out.unshift(d)
    d = addDays(d, -1)
  }
  return out
}

const SECTOR_NAMES = [
  "水泥", "食品", "塑膠", "紡織纖維", "電機機械", "電器電纜", "化學", "生技醫療", "玻璃陶瓷", "造紙", "鋼鐵", "橡膠", "汽車", "半導體",
  "電腦及週邊設備", "光電", "通信網路", "電子零組件", "電子通路", "資訊服務", "其他電子", "建材營造", "航運", "觀光餐旅", "金融保險",
  "貿易百貨", "油電燃氣", "綠能環保", "數位雲端", "運動休閒", "居家生活", "其他",
]
/** 主要由一檔構成的類股（不進前 3／後 3 的文字排名，圖上寫集中度） */
const CONCENTRATED: Record<string, string> = { 半導體: "主要由台積電構成（約 77%）", 玻璃陶瓷: "主要由台玻構成（約 92%）", 油電燃氣: "主要由台塑化構成（約 89%）" }
interface Stock {
  code: string
  name: string
  close: number
  pct: number
  /** 點數貢獻（估算） */
  contrib: number
  value: number
}
const TOP10: [string, string, number, number][] = [
  ["2330", "台積電", 1035, 0.28], ["2454", "聯發科", 1420, 0.045], ["2317", "鴻海", 228.5, 0.04], ["2308", "台達電", 1015, 0.033],
  ["2382", "廣達", 302.5, 0.016], ["2881", "富邦金", 98.6, 0.017], ["3711", "日月光投控", 168, 0.012], ["2412", "中華電", 131.5, 0.013],
  ["2603", "長榮", 192, 0.0088], ["3443", "創意", 1610, 0.0081],
]
const MOVERS: [string, string, number][] = [
  ["2409", "友達", 14.65], ["2328", "廣宇", 48.2], ["3008", "大立光", 2315], ["6505", "台塑化", 41.3], ["1802", "台玻", 28.75],
  ["2002", "中鋼", 21.4], ["2615", "萬海", 76.9], ["3034", "聯詠", 412], ["2357", "華碩", 618], ["2379", "瑞昱", 512],
]

interface Day {
  d: string
  taiex: number
  taiexChg: number
  taiexPct: number
  tr: number
  tpex: number
  tpexChg: number
  tpexPct: number
  up: number
  flat: number
  down: number
  lu: number
  ld: number
  turnover: number
  sectors: { name: string; pct: number }[]
  top10: Stock[]
  gainers: Stock[]
  losers: Stock[]
  oi: number
  oiChg: number
  pc: number
  usd: number
  usdChg: number
  otcInst: number
}

/** 一個交易日的假數字（同一天每次一樣） */
function day(d: string): Day {
  const r = rng(`day:${d}`)
  const taiexPct = between(r, -0.018, 0.016)
  const prev = 26_400 + between(r, 0, 900, 2)
  const taiexChg = Number((prev * taiexPct).toFixed(2))
  const tpexPct = between(r, -0.015, 0.015)
  const tpexPrev = 265 + between(r, 0, 12, 2)
  const breadthUp = taiexPct > 0
  const up = Math.round(breadthUp ? between(r, 520, 760, 0) : between(r, 220, 420, 0))
  const down = Math.round(breadthUp ? between(r, 220, 420, 0) : between(r, 520, 760, 0))
  const sectors = SECTOR_NAMES.map((name) => ({ name, pct: Number((taiexPct * 0.8 + between(r, -0.012, 0.012)).toFixed(4)) })).sort((a, b) => b.pct - a.pct)
  const top10 = TOP10.map(([code, name, close, w]) => {
    const p = Number((taiexPct + between(r, -0.01, 0.01)).toFixed(4))
    return { code, name, close: Math.round(close * (1 + p) * 100) / 100, pct: p, contrib: Math.round(prev * w * p), value: Math.round(between(r, 40, 900, 0)) }
  })
  const movers = MOVERS.map(([code, name, close]) => ({ code, name, close, pct: between(r, -0.1, 0.1), contrib: 0, value: Math.round(between(r, 10, 300, 0)) }))
  const sorted = [...movers].sort((a, b) => b.pct - a.pct)
  const oi = -Math.round(between(r, 18_000, 42_000, 0))
  return {
    d, taiex: Number((prev + taiexChg).toFixed(2)), taiexChg, taiexPct,
    tr: Number(((prev + taiexChg) * 1.913).toFixed(2)),
    tpex: Number((tpexPrev * (1 + tpexPct)).toFixed(2)), tpexChg: Number((tpexPrev * tpexPct).toFixed(2)), tpexPct,
    up, flat: Math.round(between(r, 40, 90, 0)), down, lu: Math.round(between(r, 2, 14, 0)), ld: Math.round(between(r, 0, 9, 0)),
    turnover: Math.round(between(r, 3600, 5600, 0)), sectors, top10,
    gainers: sorted.slice(0, 5).map((s) => ({ ...s, pct: Math.abs(s.pct) })),
    losers: sorted.slice(-5).reverse().map((s) => ({ ...s, pct: -Math.abs(s.pct) })),
    oi, oiChg: Math.round(between(r, -3000, 3000, 0)), pc: between(r, 0.92, 1.28, 4), usd: between(r, 31.1, 31.6, 3), usdChg: between(r, -0.08, 0.08, 3),
    otcInst: between(r, -45, 45, 1),
  }
}

interface UsDay {
  d: string
  etfs: { key: string; label: string; sub: string; price: number; pct: number }[]
}
function usDay(d: string): UsDay {
  const r = rng(`us:${d}`)
  return {
    d,
    etfs: [
      { key: "spy", label: "SPY", sub: "追蹤 S&P 500", price: 683.41, pct: between(r, -0.012, 0.012) },
      { key: "dia", label: "DIA", sub: "追蹤道瓊工業指數", price: 471.86, pct: between(r, -0.012, 0.012) },
      { key: "oneq", label: "ONEQ", sub: "追蹤那斯達克綜合指數", price: 87.94, pct: between(r, -0.015, 0.015) },
      { key: "smh", label: "SMH", sub: "半導體 ETF", price: 312.6, pct: between(r, -0.025, 0.02) },
      { key: "tsm", label: "台積電 ADR", sub: "TSM", price: 296.1, pct: between(r, -0.025, 0.02) },
    ].map((e) => ({ ...e, price: Number((e.price * (1 + e.pct)).toFixed(2)) })),
  }
}

/** G1：加權指數收盤（存檔起） */
function g1(d: string, title: string): AiChart {
  const days = tradingDays(d, 60)
  return chart({
    id: "G1", kind: "line", title, unit: "index", x: "date", since: `${md(days[0]!)} 起`,
    series: [{ name: "加權指數", symbol: null, points: days.map((t) => ({ t, v: day(t).taiex })) }],
    sources: [LIC.index],
  })
}
/** G2：上市 32 類的漲跌幅（集中度高的寫在名稱下面） */
function g2(sectors: { name: string; pct: number }[], title: string): AiChart {
  return chart({
    id: "G2", kind: "bars", title, unit: "pct", x: "category",
    bars: sectors.map((s) => ({ label: s.name, value: s.pct, display: pct(s.pct), tone: s.pct > 0 ? "rise" : s.pct < 0 ? "fall" : "ink", sub: CONCENTRATED[s.name] ?? null })),
    notes: ["證交所的類股指數；不含電子工業與 4 個舊的綜合類股"], sources: [LIC.index],
  })
}
/** G3：市值前 10 的點數貢獻（估算）＋其餘合計，官方漲跌點數在下面一行 */
function g3(x: Day, title: string): AiChart {
  const top = x.top10.reduce((a, s) => a + s.contrib, 0)
  const rest = Math.round(x.taiexChg - top)
  return chart({
    id: "G3", kind: "bars", title, unit: "points", x: "category", estimate: true,
    bars: [
      ...x.top10.map((s) => ({ label: s.name, value: s.contrib, display: signed(s.contrib, 0, " 點"), tone: s.contrib >= 0 ? ("rise" as const) : ("fall" as const), href: stockHref(s.code) })),
      { label: "其餘合計", value: rest, display: signed(rest, 0, " 點"), tone: "pencil" as const, sub: "市值前 10 以外的上市普通股" },
    ],
    reference: { label: "官方漲跌", display: signed(x.taiexChg, 2, " 點") },
    notes: ["Forliosa 估算：前一日加權指數 × 前一日市值權重 × 漲跌幅"], sources: [LIC.index, LIC.price],
  })
}
function g4(x: Day, title: string): AiChart {
  const rows: [string, number, "rise" | "fall" | "ink"][] = [["上漲", x.up, "rise"], ["平盤", x.flat, "ink"], ["下跌", x.down, "fall"], ["漲停", x.lu, "rise"], ["跌停", x.ld, "fall"]]
  return chart({
    id: "G4", kind: "bars", title, unit: "count", x: "category",
    bars: rows.map(([label, n, t]) => ({ label, value: n, display: `${fmt(n, 0)} 家`, tone: t })),
    notes: ["上市普通股；漲跌以當天參考價計，漲跌停以官方漲跌停價計"], sources: [LIC.price],
  })
}
function g5(d: string, stocks: Stock[], title: string): AiChart {
  const days = tradingDays(d, 22)
  return chart({
    id: "G5", kind: "compare", title, unit: "pct", x: "date", range: "1M",
    series: stocks.slice(0, 5).map((s, i) => {
      const r = rng(`g5:${s.code}`)
      let v = 0
      return { name: s.name, symbol: `${s.code}.TW`, points: days.map((t, k) => ({ t, v: k === 0 ? 0 : Number((v += between(r, -0.02, 0.022 - i * 0.002)).toFixed(4)) })) }
    }),
    notes: ["漲跌幅只算價格變動，不含股利"], sources: [LIC.price],
  })
}
function g6(us: UsDay, title: string): AiChart {
  return chart({
    id: "G6", kind: "bars", title, unit: "pct", x: "category",
    bars: us.etfs.map((e) => ({ label: e.label, value: e.pct, display: pct(e.pct), tone: e.pct >= 0 ? ("rise" as const) : ("fall" as const), sub: e.sub })),
    notes: ["ETF 與 ADR 的漲跌，不是指數點數"], sources: [LIC.us],
  })
}
function g7(d: string, title: string): AiChart {
  const days = tradingDays(d, 21)
  const pts = days.map((t) => ({ t, v: day(t).oi }))
  return chart({
    id: "G7", kind: "columns", title, unit: "lots", x: "day",
    series: [
      { name: "淨未平倉", symbol: null, points: pts.slice(1) },
      { name: "較前一日", symbol: null, points: pts.slice(1).map((p, i) => ({ t: p.t, v: p.v - pts[i]!.v })), hidden: true },
    ],
    notes: ["正值是淨多單，負值是淨空單"], sources: [LIC.taifex],
  })
}

const STOCK_COLS = [col("stock", "股票", "left"), col("close", "收盤"), col("pct", "漲跌幅")]
const stockCells = (s: Stock) => ({ stock: { text: `${s.name}（${s.code}）` }, close: { text: fmt(s.close, s.close >= 500 ? 0 : 2) }, pct: { text: pct(s.pct), tone: cellTone(s.pct) } })
const RULE_MOVERS = "範圍：市值前 200 名或 300 億元以上；排除創新板、全額交割、處置股"
function t2(x: Day, period: string): ReportTable[] {
  return [
    table({
      id: "T2-top10", title: `市值前 10・${period}`, rule: "上市普通股，依收盤市值；點數貢獻是 Forliosa 估算", columns: [...STOCK_COLS, col("contrib", "點數貢獻")],
      rows: x.top10.map((s) => ({ cells: { ...stockCells(s), contrib: { text: signed(s.contrib, 0, " 點"), sub: "估算" } }, href: stockHref(s.code) })),
      fold_after: 5, source_labels: [LIC.price],
    }),
    table({ id: "T2-gainers", title: "漲幅前 5", rule: RULE_MOVERS, columns: STOCK_COLS, rows: x.gainers.map((s) => ({ cells: stockCells(s), href: stockHref(s.code) })), source_labels: [LIC.price] }),
    table({ id: "T2-losers", title: "跌幅前 5", rule: RULE_MOVERS, columns: STOCK_COLS, rows: x.losers.map((s) => ({ cells: stockCells(s), href: stockHref(s.code) })), source_labels: [LIC.price] }),
    table({
      id: "T2-value", title: "成交值前 10", rule: "上市普通股，依成交金額", columns: [...STOCK_COLS, col("value", "成交值")],
      rows: [...x.top10].sort((a, b) => b.value - a.value).map((s) => ({ cells: { ...stockCells(s), value: { text: `${fmt(s.value, 0)} 億元` } }, href: stockHref(s.code) })),
      fold_after: 5, source_labels: [LIC.price],
    }),
  ]
}

// ── 行事曆 ──────────────────────────────────────────
const calRow = (r: Partial<ReportCalendarRow> & Pick<ReportCalendarRow, "title" | "kind" | "kind_label">): ReportCalendarRow => ({
  time_label: null, sectors: [], symbol: null, href: null, url: null, source_label: "證交所重大訊息", ...r,
})
const conference = (time: string, code: string, name: string, sector: string) =>
  calRow({ time_label: time, title: `${name} 法說會`, kind: "investor_conference", kind_label: "法說會", sectors: [sector], symbol: `${code}.TW`, href: stockHref(code) })
const exDiv = (code: string, name: string, cash: string, sector: string) =>
  calRow({ title: `${name} 除息，每股 ${cash} 元`, kind: "ex_dividend", kind_label: "除息", sectors: [sector], symbol: `${code}.TW`, href: stockHref(code), source_label: "證交所除權除息預告" })
const etfDiv = (code: string, name: string, cash: string) =>
  calRow({ title: `${name}（${code}）除息，每單位 ${cash} 元`, kind: "ex_dividend", kind_label: "ETF 除息", symbol: `${code}.TW`, href: stockHref(code), source_label: "證交所除權除息預告" })
const usCpi = () =>
  calRow({ time_label: "台北 21:30", title: "美國 10 月消費者物價指數", kind: "macro", kind_label: "總經數據", sectors: ["金融保險"], url: "https://www.bls.gov/cpi/", source_label: "美國勞工統計局（Forliosa 整理）" })
const usEarn = (us: string, tw: string, company: string, ticker: string, sector: string) =>
  calRow({ time_label: `美東 ${md(us)} 盤後（台北 ${md(tw)} 清晨）`, title: `${company}（${ticker}）財報`, kind: "us_earnings", kind_label: "美股財報", sectors: [sector], source_label: "公司投資人關係網站（Forliosa 整理）" })

function folded(label: string, rows: ReportCalendarRow[]) {
  return { label: `${label} ${rows.length} ${label.includes("法說") ? "家" : label.includes("訊息") ? "則" : "檔"}`, count: rows.length, rows }
}

// ── 報告的骨架 ────────────────────────────────────────
interface Build {
  id: string
  kind: ReportKind
  d: string
  /** 有 AI 段落 */
  ai: boolean
  edition: ReportEdition
  version: number
  published: string
  first: string
  statusLine?: string | null
  dropped?: { key: string; reasons: string[] }[]
  corrections?: { at: string; note: string }[]
  /** 官方加權指數沒進來（盤後） */
  indexMissing?: boolean
  /** 23:45 的補表 */
  tables?: boolean
  demo: boolean
  /** 盲測的不同撰寫設定：同一份資料、略有不同的寫法 */
  flavor?: number
}

function frame(b: Build, rest: Omit<MarketReport, "id" | "kind" | "kind_label" | "edition_date" | "version" | "edition" | "has_ai" | "published_at" | "first_published_at" | "disclaimer_line" | "disclaimer_full" | "model_line" | "corrections" | "status_line" | "is_demo" | "footnotes">): MarketReport {
  const sections = rest.sections.map((s) => {
    const drop = b.dropped?.find((x) => x.key === s.key)
    return drop ? { ...s, dropped: { reasons: drop.reasons } } : s
  })
  return {
    id: b.id, kind: b.kind, kind_label: REPORT_KIND_LABEL[b.kind], edition_date: b.d, version: b.version, edition: b.edition, has_ai: b.ai,
    published_at: b.published, first_published_at: b.first,
    disclaimer_line: b.ai ? DISCLAIMER_AI : DISCLAIMER_DATA, disclaimer_full: DISCLAIMER_FULL, model_line: b.ai ? MODEL_LINE : null,
    corrections: b.corrections ?? [], status_line: b.statusLine ?? null, is_demo: b.demo, footnotes: [],
    ...rest,
    sections,
    validation: b.ai
      ? {
          first_problems: b.dropped?.length ? [{ code: "number_subject_mismatch", path: `sections.${b.dropped[0]!.key}[0].sentences[1]` }, { code: "date_not_sourced", path: "highlights[2]" }] : [],
          final_problems: b.dropped?.length ? [{ code: "number_subject_mismatch", path: `sections.${b.dropped[0]!.key}[0].sentences[1]` }] : [],
          dropped: (b.dropped ?? []).map((x) => ({ section: x.key, reasons: x.reasons })),
          revised: !!b.dropped?.length,
          compliance_ran: true,
          mentions_anthropic: false,
        }
      : null,
  }
}

// ── 盤前重點 ──────────────────────────────────────────
function premarket(b: Build): MarketReport {
  const D = b.d
  const prev = prevTrading(D)
  const us = usDay(prev)
  const x = day(prev)
  const [spy, dia, oneq, smh, tsm] = us.etfs as [UsDay["etfs"][number], UsDay["etfs"][number], UsDay["etfs"][number], UsDay["etfs"][number], UsDay["etfs"][number]]
  const usLabel = `美股 ${md(us.d)}`
  const reg: Reg = new Map()
  const fUs = (id: string) => reg.set(id, { kind: "data", group: `us:${us.d}`, label: `Databento 美股收盤 ${usLabel}` })
  ;["F001", "F002", "F003", "F004", "F005"].forEach(fUs)
  reg.set("F006", { kind: "data", group: `fx:${prev}`, label: `央行〈新臺幣對美元收盤匯率〉${md(prev)}` })
  reg.set("F007", { kind: "data", group: `taifex:${prev}`, label: `期交所〈三大法人期貨部位〉${md(prev)}` })
  reg.set("F008", { kind: "data", group: `taifex:${prev}`, label: `期交所〈三大法人期貨部位〉${md(prev)}` })
  reg.set("F009", { kind: "data", group: `pc:${prev}`, label: `期交所〈選擇權 P/C 比〉${md(prev)}` })
  reg.set("F010", { kind: "data", group: `tpex:${prev}`, label: `櫃買中心〈櫃買指數〉${md(prev)}` })
  reg.set("C001", { kind: "calendar", label: `聯發科法說會 ${mdw(D)} 14:00`, url: null, date_label: md(D) })
  reg.set("C002", { kind: "calendar", label: `中華電除息 ${mdw(D)}`, url: null, date_label: md(D) })
  reg.set("C005", { kind: "calendar", label: `美國勞工統計局〈消費者物價指數〉${mdw(nextTrading(D))} 公布`, url: "https://www.bls.gov/cpi/", date_label: md(nextTrading(D)) })
  reg.set("X001", { kind: "web", outlet: "示範通訊社", title: "美股半導體類股收低（示範報導）", url: "https://example.com/demo-news/us-semis", date_label: `${md(D)} 05:42` })
  reg.set("X002", { kind: "web", outlet: "Demo Wire", title: "Tech gains lift Wall Street (sample)", url: "https://example.com/demo-news/us-close", date_label: `${md(D)} 05:15` })
  reg.set("X003", { kind: "web", outlet: "示範財經網", title: "美國通膨數據公布前的觀察（示範報導）", url: "https://example.com/demo-news/cpi-preview", date_label: `${md(D)} 06:20` })
  const ai = b.ai
  const f = b.flavor ?? 0

  const numbers: ReportNumberItem[] = [
    ...us.etfs.map((e) => ({ key: e.key, label: e.label, value: `US$${fmt(e.price)}`, change: pct(e.pct), tone: tone(e.pct), date_label: usLabel, estimate: false, note: null })),
    { key: "usdtwd", label: "美元兌新台幣", value: fmt(x.usd, 3), change: arrow(x.usdChg, 3), tone: tone(x.usdChg), date_label: md(prev), estimate: false, note: null },
    { key: "tx_oi", label: "外資台指期淨未平倉", value: `${signed(x.oi, 0)} 口`, change: `較前一日 ${signed(x.oiChg, 0, " 口")}`, tone: null, date_label: md(prev), estimate: false, note: null },
    { key: "pc", label: "P/C 未平倉比", value: `${fmt(x.pc * 100)}%`, change: null, tone: null, date_label: md(prev), estimate: false, note: null },
  ]
  const g6c = g6(us, `美股 ETF 與台積電 ADR（${usLabel}）`)
  const g7c = g7(prev, "外資台指期淨未平倉（近 20 個交易日）")
  const evening = table({
    id: "T-evening", title: `昨晚才到的資料（${md(prev)}）`,
    columns: [col("item", "項目", "left"), col("value", "數值")],
    rows: [
      { cells: { item: { text: "櫃買指數" }, value: { text: `${fmt(x.tpex)} ${pct(x.tpexPct)}`, tone: cellTone(x.tpexPct) } } },
      { cells: { item: { text: "上櫃上漲／下跌家數" }, value: { text: `${Math.round(x.up * 0.6)} 家／${Math.round(x.down * 0.6)} 家` } } },
      { cells: { item: { text: "外資台指期淨未平倉" }, value: { text: `${signed(x.oi)} 口`, sub: `較前一日 ${signed(x.oiChg, 0, " 口")}` } } },
      { cells: { item: { text: "上櫃三大法人合計" }, value: { text: `${signed(x.otcInst, 1, " 億元")}`, sub: "估算金額（股數 × 收盤價）" } } },
      { cells: { item: { text: "P/C 未平倉比" }, value: { text: `${fmt(x.pc * 100)}%` } } },
      { cells: { item: { text: "美元兌新台幣" }, value: { text: fmt(x.usd, 3) } } },
    ],
    source_labels: [LIC.tpex, LIC.taifex, LIC.fx],
  })
  const calendar: ReportCalendar = {
    title: "今日行事曆",
    groups: [
      {
        date: D, date_label: mdw(D),
        rows: [conference("14:00", "2454", "聯發科", "半導體"), conference("15:30", "2317", "鴻海", "其他電子"), exDiv("2412", "中華電", "1.2", "通信網路")],
        folded: [
          folded("ETF 除息", [etfDiv("00878", "國泰永續高股息", "0.42"), etfDiv("00919", "群益台灣精選高息", "0.54"), etfDiv("0056", "元大高股息", "0.85")]),
          folded("受邀參加法說會", [conference("10:00", "2409", "友達", "光電"), conference("13:30", "2328", "廣宇", "電子零組件")]),
          folded("其他重大訊息", Array.from({ length: 6 }, (_, i) => calRow({ time_label: `${String(8 + i).padStart(2, "0")}:${i % 2 ? "30" : "05"}`, title: ["董事會決議股利分派", "取得機器設備", "更換會計主管", "自結合併營收", "背書保證金額達公告標準", "召開股東常會"][i]!, kind: "filing", kind_label: "重大訊息" }))),
        ],
      },
      { date: nextTrading(D), date_label: mdw(nextTrading(D)), rows: [usCpi()], folded: [] },
    ],
    empty_text: null,
    source_labels: ["證交所重大訊息", "證交所除權除息預告", "美國勞工統計局（Forliosa 整理）"],
  }
  const n100 = 2

  const title = ai
    ? f === 1
      ? `半導體 ETF SMH ${usLabel} ${pct(smh.pct)}，${mdw(D)} 聯發科法說會`
      : `${usLabel} SMH ${pct(smh.pct)}、台積電 ADR ${pct(tsm.pct)}，${mdw(D)} ${n100} 家法說會`
    : `盤前重點 ${mdw(D)}：${usLabel} 收盤與今日行事曆`
  const highlights = ai
    ? [
        P(S(`${usLabel} 收盤，SPY ${pct(spy.pct)}、ONEQ ${pct(oneq.pct)}，SMH ${pct(smh.pct)}。`, "F001", "F003", "F004")),
        P(S(`〔示範通訊社〕報導，${usLabel} 半導體類股${rise(smh.pct)}，台積電 ADR ${pct(tsm.pct)}。`, "X001", "F005")),
        P(S(`已排定：${mdw(D)} 市值前 100 公司中有 ${n100} 家舉行法說會，中華電除息。`, "C001", "C002")),
      ]
    : [
        P(S(`美股 ETF（${usLabel} 收盤）：SPY ${pct(spy.pct)}、ONEQ ${pct(oneq.pct)}、SMH ${pct(smh.pct)}、台積電 ADR ${pct(tsm.pct)}`, "F001", "F003", "F004", "F005")),
        P(S(`${mdw(D)}：市值前 100 中 1 家除息、${n100} 家法說會`, "C001", "C002")),
        P(S(`外資台指期淨未平倉（${md(prev)}）：${signed(x.oi, 0, " 口")}，較前一日 ${signed(x.oiChg, 0, " 口")}`, "F007", "F008")),
      ]
  const sections: ReportSection[] = [
    section("overnight", "隔夜要聞", ai ? "ai" : "data", [
      ...(ai
        ? [{
            type: "text" as const,
            paragraphs: [
              P(S(`${usLabel} 收盤，SPY ${pct(spy.pct)}，DIA ${pct(dia.pct)}，ONEQ ${pct(oneq.pct)}。`, "F001", "F002", "F003"), S(`〔Demo Wire〕報導，${usLabel} 科技股走高，工業股走低。`, "X002")),
              P(S(`半導體 ETF SMH ${usLabel} ${pct(smh.pct)}，台積電 ADR ${pct(tsm.pct)}。`, "F004", "F005"), S(`〔示範通訊社〕報導，${usLabel} 記憶體類股受財測影響走弱。`, "X001")),
              P(S(`〔示範財經網〕報導市場關注美國 10 月消費者物價指數，數據 ${mdw(nextTrading(D))} 公布。`, "X003", "C005")),
            ],
          }]
        : []),
      { type: "chart", chart: g6c, caption: null, chart_of_day: false },
    ]),
    section("evening", "昨晚才到的資料", ai ? "ai" : "data", [
      { type: "table", table: evening },
      ...(ai
        ? [{
            type: "text" as const,
            paragraphs: [
              P(S(`櫃買指數 ${mdw(prev)} 收 ${fmt(x.tpex)} 點，${pct(x.tpexPct)}。`, "F010"), S(`外資台指期淨未平倉 ${md(prev)} 為 ${signed(x.oi, 0, " 口")}，較前一日 ${signed(x.oiChg, 0, " 口")}。`, "F007", "F008")),
            ],
          }]
        : []),
    ], true),
    ...(ai
      ? [section("watch", "今天市場在看什麼", "ai", [{
          type: "items",
          items: [
            { title: "聯發科法說會", meta: "14:00・半導體", paragraphs: [P(S(`已排定：聯發科（2454）${mdw(D)} 14:00 舉行法說會。`, "C001"), S("這件事和半導體類股的關係是，聯發科是半導體類股市值第二大的公司。", "C001"))] },
            { title: "美國 10 月消費者物價指數", meta: `台北 ${md(nextTrading(D))} 21:30・金融保險`, paragraphs: [P(S(`已排定：美國勞工統計局 ${mdw(nextTrading(D))} 公布 10 月消費者物價指數。`, "C005"), S("〔示範財經網〕報導市場關注通膨數字與利率的關係。", "X003"))] },
            ...(f === 2 ? [] : [{ title: "中華電除息", meta: "通信網路", paragraphs: [P(S(`已排定：中華電（2412）${mdw(D)} 除息，每股 1.2 元。`, "C002"))] } satisfies ReportItem]),
          ],
        }], true)]
      : []),
    section("charts", "圖", ai ? "ai" : "data", [
      { type: "chart", chart: g7c, caption: null, chart_of_day: false },
      ...(ai
        ? [{
            type: "chart" as const,
            chart: g2(x.sectors, `上市類股漲跌（${md(prev)}）`),
            caption: P(S(`${mdw(prev)} 上市類股中，${x.sectors[0]!.name}類 ${pct(x.sectors[0]!.pct)} 最多。`, "F010")),
            chart_of_day: true,
          }]
        : []),
    ], true),
  ]
  return assemble(
    frame(b, {
      edition_label: mdw(D), period: { start: D, end: D }, next_period: null,
      as_of: at(D, "06:55"), as_of_label: `資料截至 ${md(D)} 06:55`,
      title, title_origin: ai ? "ai" : "rules", highlights, highlights_origin: ai ? "ai" : "rules",
      numbers, sections, calendar,
      sources: { data: [LIC.us, LIC.tpex, LIC.taifex, LIC.fx, LIC.filings], web: [], disagreements: [], manual: [MANUAL_LINE] },
      notes: [],
    }),
    reg,
  )
}

// ── 盤後重點 ──────────────────────────────────────────
function close(b: Build): MarketReport {
  const D = b.d
  const x = day(D)
  const reg: Reg = new Map()
  const fIdx = (id: string) => reg.set(id, { kind: "data", group: `index:${D}`, label: `證交所〈每日收盤行情－大盤統計〉${md(D)}` })
  ;["F001", "F002", "F003", "F004"].forEach(fIdx)
  reg.set("F005", { kind: "data", group: `tpex:${D}`, label: `櫃買中心〈櫃買指數〉${md(D)}` })
  reg.set("F006", { kind: "data", group: `price:${D}`, label: `證交所〈上市個股日成交資訊〉${md(D)}（Forliosa 加總）` })
  reg.set("F007", { kind: "data", group: `price:${D}`, label: `證交所〈上市個股日成交資訊〉${md(D)}（Forliosa 加總）` })
  reg.set("F040", { kind: "data", group: `index:${D}`, label: `證交所〈每日收盤行情－大盤統計〉${md(D)}` })
  reg.set("F041", { kind: "data", group: `profile:${D}`, label: "公司基本資料（已發行股數）× 收盤價，Forliosa 計算" })
  reg.set("C001", { kind: "calendar", label: `美國勞工統計局〈消費者物價指數〉${mdw(nextTrading(D))} 公布`, url: "https://www.bls.gov/cpi/", date_label: md(nextTrading(D)) })
  reg.set("N001", { kind: "filing", label: `台積電重大訊息：董事會決議股利分派（${md(D)} 14:32）`, url: null, date_label: md(D) })
  reg.set("X001", { kind: "web", outlet: "示範通訊社", title: "台股收盤：權值股走勢分歧（示範報導）", url: "https://example.com/demo-news/tw-close", date_label: `${md(D)} 13:52` })
  reg.set("X002", { kind: "web", outlet: "示範日報", title: "上市三大法人買賣超（示範報導）", url: "https://example.com/demo-news/tw-inst", date_label: `${md(D)} 15:32` })
  reg.set("W001", { kind: "research", outlet: "示範財經網", title: "台積電股價變動與報導整理（示範報導）", url: "https://example.com/demo-news/tsmc-why", date_label: `${md(D)} 14:05` })
  const ai = b.ai
  const f = b.flavor ?? 0
  const top = x.top10[0]!
  const second = x.top10[1]!
  const eligible = x.sectors.filter((s) => !CONCENTRATED[s.name])
  const best = eligible.slice(0, 3)
  const worst = eligible.slice(-3).reverse()
  const semi = x.sectors.find((s) => s.name === "半導體")!
  const inst = Number((x.taiexPct * 9200).toFixed(2))

  const numbers: ReportNumberItem[] = [
    ...(b.indexMissing
      ? [{ key: "mcap", label: "上市市值變化", value: pct(x.taiexPct), change: null, tone: tone(x.taiexPct), date_label: md(D), estimate: true, note: "官方加權指數尚未取得" }]
      : [
          { key: "taiex", label: "加權指數", value: fmt(x.taiex), change: `${arrow(x.taiexChg)} ${pct(x.taiexPct)}`, tone: tone(x.taiexPct), date_label: md(D), estimate: false, note: null },
          { key: "tr", label: "報酬指數", value: fmt(x.tr), change: pct(x.taiexPct), tone: tone(x.taiexPct), date_label: md(D), estimate: false, note: null },
        ]),
    { key: "tpex", label: "櫃買指數", value: fmt(x.tpex), change: `${arrow(x.tpexChg)} ${pct(x.tpexPct)}`, tone: tone(x.tpexPct), date_label: md(D), estimate: false, note: null },
    { key: "breadth", label: "上市上漲／下跌", value: `${x.up}／${x.down} 家`, change: null, tone: null, date_label: md(D), estimate: false, note: null },
    { key: "limits", label: "漲停／跌停", value: `${x.lu}／${x.ld} 家`, change: null, tone: null, date_label: md(D), estimate: false, note: null },
    { key: "turnover", label: "上市成交金額", value: `${fmt(x.turnover, 0)} 億元`, change: null, tone: null, date_label: md(D), estimate: !b.tables, note: null },
  ]
  const indexLine = b.indexMissing ? `上市市值估算 ${pct(x.taiexPct)}` : `加權指數 ${pct(x.taiexPct)}，收 ${fmt(x.taiex)} 點`
  const title = ai
    ? f === 1
      ? `加權指數${rise(x.taiexChg)} ${fmt(x.taiexChg)} 點，${top.name}點數貢獻約 ${signed(top.contrib)} 點`
      : `加權指數 ${pct(x.taiexPct)}，上市 ${x.down} 家下跌、${x.up} 家上漲`
    : `盤後重點 ${mdw(D)}：${indexLine}`
  const highlights = ai
    ? [
        b.indexMissing
          ? P(S(`上市市值 ${mdw(D)} 估算 ${pct(x.taiexPct)}，官方加權指數尚未取得。`, "F006"))
          : P(S(`加權指數 ${mdw(D)} 收 ${fmt(x.taiex)} 點，${arrow(x.taiexChg)} 點，${pct(x.taiexPct)}。`, "F001", "F002", "F003")),
        P(S(`上市普通股上漲 ${x.up} 家、下跌 ${x.down} 家，漲停 ${x.lu} 家、跌停 ${x.ld} 家。`, "F006", "F007")),
        P(S(`〔示範日報〕報導，上市三大法人 ${md(D)} 合計${inst >= 0 ? "買超" : "賣超"} ${fmt(Math.abs(inst))} 億元。`, "X002")),
      ]
    : [
        P(S(b.indexMissing ? `上市市值估算 ${md(D)} ${pct(x.taiexPct)}；官方加權指數尚未取得` : `加權指數 ${md(D)} 收 ${fmt(x.taiex)} 點，${arrow(x.taiexChg)} 點（${pct(x.taiexPct)}）`, "F001", "F002", "F003")),
        P(S(`上漲 ${x.up} 家、下跌 ${x.down} 家；漲停 ${x.lu} 家、跌停 ${x.ld} 家`, "F006", "F007")),
        P(S(`點數貢獻最大：${top.name} 約 ${signed(top.contrib)} 點（估算）`, "F041")),
      ]
  const stockParas = [top, second, x.top10[2]!].map((s, i) =>
    P(
      S(`${s.name}（${s.code}）${pct(s.pct)}，收 ${fmt(s.close, s.close >= 500 ? 0 : 2)} 元，點數貢獻約 ${signed(s.contrib)} 點（估算）。`, "F041"),
      ...(i === 0 ? [S("〔示範財經網〕報導，台積電的股價變動和外資期貨部位調整有關。", "W001")] : []),
    ),
  )
  const sections: ReportSection[] = [
    section("what_happened", "今天發生什麼", ai ? "ai" : "data", [
      ...(ai
        ? [{
            type: "text" as const,
            paragraphs: [
              P(
                b.indexMissing
                  ? S(`上市市值 ${mdw(D)} 估算 ${pct(x.taiexPct)}。`, "F006")
                  : S(`加權指數 ${mdw(D)} 收 ${fmt(x.taiex)} 點，${arrow(x.taiexChg)} 點，${pct(x.taiexPct)}；報酬指數同樣 ${pct(x.taiexPct)}。`, "F001", "F002", "F003", "F004"),
                S(`Forliosa 加總上市成交金額約 ${fmt(x.turnover, 0)} 億元。`, "F006"),
              ),
              P(S(`〔示範通訊社〕報導，${md(D)} 權值股走勢分歧，電子股${rise(semi.pct)}、傳產股走勢不一。`, "X001")),
              ...(f === 2 ? [] : [P(S(`櫃買指數收 ${fmt(x.tpex)} 點，${pct(x.tpexPct)}。`, "F005"))]),
            ],
          }]
        : []),
      b.indexMissing
        ? { type: "note" as const, text: "官方加權指數尚未取得，數字欄的上市市值變化是 Forliosa 估算。" }
        : { type: "chart" as const, chart: g1(D, "加權指數收盤"), caption: null, chart_of_day: false },
    ]),
    section("sectors", "類股", ai ? "ai" : "data", [
      { type: "chart", chart: g2(x.sectors, `上市類股漲跌（${md(D)}）`), caption: null, chart_of_day: false },
      ...(ai
        ? [{
            type: "text" as const,
            paragraphs: [
              P(S(`漲幅前 3 類是${best.map((s) => `${s.name}類 ${pct(s.pct)}`).join("、")}。`, "F040"), S(`跌幅前 3 類是${worst.map((s) => `${s.name}類 ${pct(s.pct)}`).join("、")}。`, "F040")),
              P(S(`半導體類 ${pct(semi.pct)}，主要由台積電構成（約 77%）。`, "F040", "F041")),
            ],
          }]
        : []),
    ], true),
    section("stocks", "權值股與個股", ai ? "ai" : "data", [
      { type: "chart", chart: g3(x, `市值前 10 的點數貢獻（${md(D)}）`), caption: null, chart_of_day: false },
      ...t2(x, md(D)).map((t) => ({ type: "table" as const, table: t })),
      ...(ai ? [{ type: "text" as const, paragraphs: stockParas }] : []),
    ], true),
    section("chips", "籌碼", ai ? "ai" : "data", [
      ...(ai ? [{ type: "text" as const, paragraphs: [P(S(`〔示範日報〕報導，上市三大法人 ${md(D)} 合計${inst >= 0 ? "買超" : "賣超"} ${fmt(Math.abs(inst))} 億元。`, "X002"))] }] : []),
      { type: "note" as const, text: "上市三大法人沒有開放資料，只能引用媒體報導。" },
      ...(b.tables
        ? [{
            type: "table" as const,
            table: table({
              id: "T7", title: `期貨三大法人（${md(D)}）`, columns: [col("who", "法人", "left"), col("oi", "台指期淨未平倉"), col("chg", "較前一日")],
              rows: [
                { cells: { who: { text: "外資及陸資" }, oi: { text: `${signed(x.oi)} 口` }, chg: { text: `${signed(x.oiChg)} 口` } } },
                { cells: { who: { text: "投信" }, oi: { text: "+8,412 口" }, chg: { text: "+215 口" } } },
                { cells: { who: { text: "自營商" }, oi: { text: "−2,106 口" }, chg: { text: "−388 口" } } },
              ],
              source_labels: [LIC.taifex],
            }),
          }]
        : []),
    ], true),
    section("tonight", "盤後重大訊息與今晚要看的", ai ? "ai" : "data", [
      ...(ai
        ? [{
            type: "items" as const,
            items: [
              { title: "台積電董事會決議股利分派", meta: `${md(D)} 14:32・半導體`, paragraphs: [P(S(`台積電（2330）${mdw(D)} 14:32 公告董事會決議股利分派。`, "N001"))] },
              { title: "美國 10 月消費者物價指數", meta: `台北 ${md(nextTrading(D))} 21:30・金融保險`, paragraphs: [P(S(`已排定：美國勞工統計局 ${mdw(nextTrading(D))} 公布 10 月消費者物價指數。`, "C001"))] },
            ],
          }]
        : [{ type: "note" as const, text: `${md(D)} 14:00 以後到資料截止，市值前 100 公司有 1 則重大訊息。` }]),
    ], true),
    // 今日圖：AI 從選單挑一張（漲跌家數），配 2–3 句說明
    ...(ai && f !== 2
      ? [section("chart_of_day", "今日圖", "ai", [{
          type: "chart",
          chart: g4(x, `上市漲跌家數（${md(D)}）`),
          caption: P(S(`${mdw(D)} 上市普通股下跌 ${x.down} 家，上漲 ${x.up} 家。`, "F006", "F007"), S(`跌停 ${x.ld} 家，漲停 ${x.lu} 家。`, "F007")),
          chart_of_day: true,
        }], true)]
      : []),
    ...(b.tables
      ? [section("otc", "上櫃", "data", [
          {
            type: "table",
            table: table({
              id: "T6", title: `上櫃類股（${md(D)}）`, rule: "Forliosa 依產業別計算，不是官方指數；2 家以下的產業不列", columns: [col("name", "產業", "left"), col("n", "家數"), col("pct", "漲跌幅")],
              rows: x.sectors.slice(0, 8).map((s, i) => ({ cells: { name: { text: s.name }, n: { text: `${12 + i * 7}` }, pct: { text: pct(s.pct * 1.2), tone: cellTone(s.pct) } } })),
              fold_after: 5, source_labels: [LIC.tpex],
            }),
          },
        ], true)]
      : []),
  ]
  return assemble(
    frame(b, {
      edition_label: mdw(D), period: { start: D, end: D }, next_period: null,
      as_of: at(D, b.tables ? "23:45" : "15:40"), as_of_label: `資料截至 ${md(D)} ${b.tables ? "23:45" : "15:40"}`,
      title, title_origin: ai ? "ai" : "rules", highlights, highlights_origin: ai ? "ai" : "rules",
      numbers, sections,
      calendar: {
        title: `${md(nextTrading(D))} 行事曆`,
        groups: [{ date: nextTrading(D), date_label: mdw(nextTrading(D)), rows: [usCpi(), usEarn(D, nextTrading(D), "示範網通", "DEMO", "通信網路")], folded: [] }],
        empty_text: null, source_labels: ["美國勞工統計局（Forliosa 整理）", "公司投資人關係網站（Forliosa 整理）"],
      },
      sources: {
        data: [LIC.index, LIC.price, LIC.tpex, ...(b.tables ? [LIC.taifex] : []), LIC.filings],
        web: [],
        disagreements: ai ? [{ text: `示範財經網寫上市三大法人${inst >= 0 ? "買超" : "賣超"} ${fmt(Math.abs(inst) + 0.01)} 億元，示範日報寫 ${fmt(Math.abs(inst))} 億元；本報告以示範日報為準。` }] : [],
        manual: [MANUAL_LINE],
      },
      notes: b.indexMissing ? ["官方加權指數尚未取得，上市的漲跌是 Forliosa 依個股市值估算。"] : [],
    }),
    reg,
  )
}

// ── 市場週報 ──────────────────────────────────────────
function weekly(b: Build): MarketReport {
  const S0 = b.d
  const start = addDays(S0, -6)
  const end = addDays(S0, -2)
  const nStart = addDays(S0, 1)
  const nEnd = addDays(S0, 5)
  const days = tradingDays(end, 5, start)
  const first = day(days[0]!)
  const last = day(end)
  const weekPct = Number(((last.taiex - (first.taiex - first.taiexChg)) / (first.taiex - first.taiexChg)).toFixed(4))
  const weekPts = Number((last.taiex - (first.taiex - first.taiexChg)).toFixed(2))
  const tpexWeek = Number((days.reduce((a, t) => a + day(t).tpexPct, 0)).toFixed(4))
  const turnover = days.reduce((a, t) => a + day(t).turnover, 0)
  const weekSectors = SECTOR_NAMES.map((name) => ({ name, pct: Number(days.reduce((a, t) => a + day(t).sectors.find((s) => s.name === name)!.pct, 0).toFixed(4)) })).sort((a, b) => b.pct - a.pct)
  const eligible = weekSectors.filter((s) => !CONCENTRATED[s.name])
  const us = usDay(addDays(S0, -2))
  const usWeek: UsDay = { d: us.d, etfs: us.etfs.map((e, i) => ({ ...e, pct: Number((e.pct * 2.2 + (i - 2) * 0.003).toFixed(4)) })) }
  const reg: Reg = new Map()
  const fWeek = (id: string) => reg.set(id, { kind: "data", group: `index:${end}`, label: `證交所〈每日收盤行情－大盤統計〉${md(start)}–${md(end)}` })
  ;["F001", "F002", "F003"].forEach(fWeek)
  reg.set("F004", { kind: "data", group: `turnover:${end}`, label: `證交所〈每日市場成交資訊〉${md(start)}–${md(end)}` })
  reg.set("F020", { kind: "data", group: `index:${end}`, label: `證交所〈每日收盤行情－大盤統計〉${md(start)}–${md(end)}` })
  reg.set("F030", { kind: "data", group: `us:${us.d}`, label: `Databento 美股收盤 美股 ${md(addDays(start, -1))}–${md(us.d)}` })
  reg.set("F031", { kind: "data", group: `taifex:${end}`, label: `期交所〈三大法人期貨部位〉${md(end)}` })
  reg.set("C001", { kind: "calendar", label: `聯發科法說會 ${mdw(addDays(S0, -4))}`, url: null, date_label: md(addDays(S0, -4)) })
  reg.set("C010", { kind: "calendar", label: `美國勞工統計局〈消費者物價指數〉${mdw(addDays(nStart, 3))} 公布`, url: "https://www.bls.gov/cpi/", date_label: md(addDays(nStart, 3)) })
  reg.set("C011", { kind: "calendar", label: `經濟部〈外銷訂單統計〉${mdw(addDays(nStart, 4))} 公布`, url: "https://www.moea.gov.tw/", date_label: md(addDays(nStart, 4)) })
  reg.set("X001", { kind: "web", outlet: "示範通訊社", title: "台股一週回顧（示範報導）", url: "https://example.com/demo-news/tw-week", date_label: `${md(end)} 14:10` })
  reg.set("X002", { kind: "web", outlet: "示範日報", title: "外資一週買賣超（示範報導）", url: "https://example.com/demo-news/tw-inst-week", date_label: `${md(end)} 15:40` })
  reg.set("X003", { kind: "web", outlet: "示範財經網", title: "AI 伺服器供應鏈的觀察（示範報導）", url: "https://example.com/demo-news/ai-servers", date_label: `${md(addDays(end, -1))} 09:30` })
  reg.set("X004", { kind: "web", outlet: "Demo Wire", title: "Chip stocks end the week mixed (sample)", url: "https://example.com/demo-news/us-week", date_label: `${md(addDays(S0, -1))} 05:30` })
  const ai = b.ai
  const instWeek = Number((weekPct * 18000).toFixed(2))
  const sumWeek = (name: string) => Number(days.reduce((a, t) => a + day(t).top10.find((s) => s.name === name)!.contrib, 0))
  const weekDay: Day = { ...last, taiexChg: weekPts, top10: last.top10.map((s) => ({ ...s, contrib: sumWeek(s.name), pct: Number((s.pct * 2.1).toFixed(4)) })) }

  const numbers: ReportNumberItem[] = [
    { key: "taiex_w", label: "加權指數週漲跌", value: pct(weekPct), change: `${arrow(weekPts)} 點`, tone: tone(weekPct), date_label: `${md(start)}–${md(end)}`, estimate: false, note: null },
    { key: "tpex_w", label: "櫃買指數週漲跌", value: pct(tpexWeek), change: null, tone: tone(tpexWeek), date_label: `${md(start)}–${md(end)}`, estimate: false, note: null },
    { key: "mcap", label: "上市總市值", value: "71.42 兆元", change: pct(weekPct), tone: tone(weekPct), date_label: md(end), estimate: true, note: null },
    { key: "turnover_w", label: "全週成交金額", value: `${fmt(turnover, 0)} 億元`, change: null, tone: null, date_label: `${md(start)}–${md(end)}`, estimate: false, note: null },
    { key: "top_ind", label: "成交金額前三產業", value: "半導體・電腦及週邊・電子零組件", change: null, tone: null, date_label: `${md(start)}–${md(end)}`, estimate: false, note: "Forliosa 依個股成交金額加總" },
  ]
  const nm = (s: string) => `${md(s)}`
  const returnsRow = (name: string, w: number, oneMonth: number | null, since: number) => ({
    cells: {
      name: { text: name },
      d1: { text: pct(w / 4), tone: cellTone(w) },
      w1: { text: pct(w), tone: cellTone(w) },
      m1: oneMonth === null ? { text: "—" } : { text: pct(oneMonth), tone: cellTone(oneMonth) },
      since: { text: pct(since), tone: cellTone(since) },
    },
  })
  const returns = table({
    id: "T3", title: "多期間報酬", columns: [col("name", "項目", "left"), col("d1", "1 日"), col("w1", "1 週"), col("m1", "1 個月"), col("since", `${nm(ARCHIVE_FROM)} 起`)],
    rows: [
      returnsRow("加權指數", weekPct, null, weekPct * 1.6),
      returnsRow("報酬指數", weekPct, null, weekPct * 1.65),
      returnsRow("櫃買指數", tpexWeek, null, tpexWeek * 1.4),
      ...weekSectors.map((s) => returnsRow(s.name, s.pct, null, s.pct * 1.5)),
    ],
    fold_after: 6, note: `1 個月的比較約 ${md(addDays(ARCHIVE_FROM, 31))} 以後才有`, source_labels: [LIC.index, LIC.tpex],
  })
  const title = ai ? `加權指數一週 ${pct(weekPct)}，${eligible[0]!.name}類一週 ${pct(eligible[0]!.pct)} 最多` : `市場週報 ${md(start)}–${md(end)}：加權指數週 ${pct(weekPct)}`
  const highlights = ai
    ? [
        P(S(`加權指數 ${md(start)}–${md(end)} ${pct(weekPct)}，${arrow(weekPts)} 點。`, "F001", "F002")),
        P(S(`全週上市成交金額 ${fmt(turnover, 0)} 億元。`, "F004")),
        P(S(`〔示範日報〕報導，外資 ${md(start)}–${md(end)} 在集中市場${instWeek >= 0 ? "買超" : "賣超"} ${fmt(Math.abs(instWeek))} 億元。`, "X002")),
        P(S(`已排定：美國 10 月消費者物價指數 ${mdw(addDays(nStart, 3))} 公布。`, "C010")),
      ]
    : [
        P(S(`加權指數週 ${pct(weekPct)}（${arrow(weekPts)} 點）`, "F001", "F002")),
        P(S(`全週成交金額 ${fmt(turnover, 0)} 億元`, "F004")),
        P(S(`週漲幅最大：${eligible[0]!.name}類 ${pct(eligible[0]!.pct)}；最小：${eligible.at(-1)!.name}類 ${pct(eligible.at(-1)!.pct)}`, "F020")),
      ]
  const sections: ReportSection[] = [
    ...(ai
      ? [section("summary", "這一週", "ai", [{ type: "text", paragraphs: [P(S(`加權指數 ${md(start)}–${md(end)} ${pct(weekPct)}，櫃買指數 ${pct(tpexWeek)}。`, "F001", "F003"), S(`類股中${eligible[0]!.name}類一週 ${pct(eligible[0]!.pct)} 最多，${eligible.at(-1)!.name}類 ${pct(eligible.at(-1)!.pct)} 最少。`, "F020"))] }])]
      : []),
    section("market_week", "上週大盤", ai ? "ai" : "data", [
      ...(ai ? [{ type: "text" as const, paragraphs: [P(S(`加權指數 ${md(end)} 收 ${fmt(last.taiex)} 點，一週 ${arrow(weekPts)} 點。`, "F001", "F002"), S("〔示範通訊社〕報導，這一週電子權值股與金融股走勢分歧。", "X001"))] }] : []),
      { type: "chart", chart: g1(end, "加權指數收盤"), caption: null, chart_of_day: false },
    ]),
    section("returns", "多期間報酬", "data", [{ type: "table", table: returns }], true),
    section("sectors_week", "類股一週", ai ? "ai" : "data", [
      { type: "chart", chart: g2(weekSectors, `上市類股一週漲跌（${md(start)}–${md(end)}）`), caption: null, chart_of_day: false },
      ...(ai ? [{ type: "text" as const, paragraphs: [P(S(`一週漲幅前 3 類是${eligible.slice(0, 3).map((s) => `${s.name}類 ${pct(s.pct)}`).join("、")}。`, "F020")), P(S(`半導體類一週 ${pct(weekSectors.find((s) => s.name === "半導體")!.pct)}，主要由台積電構成（約 77%）。`, "F020"))] }] : []),
    ], true),
    section("stocks_week", "權值股與個股", ai ? "ai" : "data", [
      { type: "chart", chart: g3(weekDay, `市值前 10 的週點數貢獻（${md(start)}–${md(end)}）`), caption: null, chart_of_day: false },
      ...t2(weekDay, `${md(start)}–${md(end)}`).slice(0, 3).map((t) => ({ type: "table" as const, table: t })),
      { type: "chart", chart: g5(end, weekDay.top10, "權值前 5 近 1 個月漲跌幅"), caption: null, chart_of_day: false },
      ...(ai ? [{ type: "text" as const, paragraphs: [P(S(`${weekDay.top10[0]!.name}（${weekDay.top10[0]!.code}）一週點數貢獻約 ${signed(weekDay.top10[0]!.contrib)} 點（估算）。`, "F020"))] }] : []),
    ], true),
    section("chips_week", "籌碼", ai ? "ai" : "data", [
      { type: "chart", chart: g7(end, "外資台指期淨未平倉（近 20 個交易日）"), caption: null, chart_of_day: false },
      ...(ai ? [{ type: "text" as const, paragraphs: [P(S(`外資台指期淨未平倉 ${md(end)} 為 ${signed(last.oi, 0, " 口")}。`, "F031"), S(`〔示範日報〕報導，外資這一週在集中市場${instWeek >= 0 ? "買超" : "賣超"} ${fmt(Math.abs(instWeek))} 億元。`, "X002"))] }] : []),
    ], true),
    section("global_week", "國際", ai ? "ai" : "data", [
      { type: "chart", chart: g6(usWeek, `美股 ETF 與台積電 ADR 一週（美股 ${md(addDays(start, -1))}–${md(us.d)}）`), caption: null, chart_of_day: false },
      ...(ai ? [{ type: "text" as const, paragraphs: [P(S(`SMH 美股 ${md(addDays(start, -1))}–${md(us.d)} ${pct(usWeek.etfs[3]!.pct)}，台積電 ADR ${pct(usWeek.etfs[4]!.pct)}。`, "F030"), S("〔Demo Wire〕報導，半導體股這一週漲跌互見。", "X004"))] }] : []),
    ], true),
    ...(ai
      ? [
          section("last_week_review", "上週行事曆回顧", "ai", [{
            type: "items",
            items: [{ title: "聯發科法說會", meta: `${md(addDays(S0, -4))}・半導體`, paragraphs: [P(S(`聯發科（2454）${mdw(addDays(S0, -4))} 舉行法說會。`, "C001"), S("〔示範通訊社〕報導，法說會的內容以產品組合的說明為主。", "X001"))] }],
          }], true),
          section("themes", "市場關注的主題", "ai", [{
            type: "items",
            items: [
              { title: "AI 伺服器供應鏈", meta: "電腦及週邊設備・電子零組件", paragraphs: [P(S("〔示範財經網〕報導市場關注 AI 伺服器的出貨時程。", "X003"), S("這件事和電腦及週邊設備類股的關係是，伺服器代工廠多在這一類。", "X003"))] },
              { title: "美國通膨數據", meta: `${md(addDays(nStart, 3))}・金融保險`, paragraphs: [P(S(`已排定：美國 10 月消費者物價指數 ${mdw(addDays(nStart, 3))} 公布。`, "C010"))] },
              { title: "外銷訂單", meta: `${md(addDays(nStart, 4))}・電子零組件`, paragraphs: [P(S(`已排定：經濟部 ${mdw(addDays(nStart, 4))} 公布 10 月外銷訂單統計。`, "C011"))] },
            ],
          }], true),
          section("risks", "可能讓關注點改變的事", "ai", [{ type: "text", paragraphs: [P(S(`已排定：美國 10 月消費者物價指數 ${mdw(addDays(nStart, 3))} 公布。`, "C010"), S("〔示範財經網〕報導市場關注數據和利率的關係。", "X003"))] }], true),
        ]
      : []),
  ]
  return assemble(
    frame(b, {
      edition_label: `${md(start)}–${md(end)} 回顧`, period: { start, end }, next_period: { start: nStart, end: nEnd },
      as_of: at(S0, "16:30"), as_of_label: `資料截至 ${md(S0)} 16:30`,
      title, title_origin: ai ? "ai" : "rules", highlights, highlights_origin: ai ? "ai" : "rules",
      numbers, sections,
      calendar: {
        title: `下週行事曆 ${md(nStart)}–${md(nEnd)}`,
        groups: [
          { date: nStart, date_label: mdw(nStart), rows: [conference("14:00", "2382", "廣達", "電腦及週邊設備")], folded: [folded("其他重大訊息", [calRow({ title: "公告本公司取得機器設備", kind: "filing", kind_label: "重大訊息" }), calRow({ title: "本公司 10 月份自結合併營收", kind: "filing", kind_label: "重大訊息" })])] },
          { date: addDays(nStart, 2), date_label: mdw(addDays(nStart, 2)), rows: [calRow({ time_label: "13:30", title: "台指期貨、台指選擇權 11 月契約最後結算日", kind: "settlement", kind_label: "結算", source_label: "期交所規則（Forliosa 計算）" })], folded: [folded("ETF 除息", [etfDiv("00878", "國泰永續高股息", "0.42"), etfDiv("0056", "元大高股息", "0.85")])] },
          { date: addDays(nStart, 3), date_label: mdw(addDays(nStart, 3)), rows: [usCpi()], folded: [] },
          { date: addDays(nStart, 4), date_label: mdw(addDays(nStart, 4)), rows: [calRow({ time_label: "16:00", title: "10 月外銷訂單統計", kind: "macro", kind_label: "總經數據", sectors: ["電子零組件"], url: "https://www.moea.gov.tw/", source_label: "經濟部（Forliosa 整理）" })], folded: [] },
        ],
        empty_text: null, source_labels: ["證交所重大訊息", "期交所規則（Forliosa 計算）", "美國勞工統計局（Forliosa 整理）", "經濟部（Forliosa 整理）"],
      },
      sources: { data: [LIC.index, LIC.price, LIC.tpex, LIC.taifex, LIC.us], web: [], disagreements: [], manual: [MANUAL_LINE] },
      notes: [],
    }),
    reg,
  )
}

const BUILDERS: Record<ReportKind, (b: Build) => MarketReport> = { premarket, close, weekly }

// ── 盲測的設定 ─────────────────────────────────────────
const TRIAL_DAILY: WriterSetting[] = [{ model: "claude-sonnet-5-5", effort: "high" }, { model: "claude-opus-5-5", effort: "medium" }, { model: "claude-opus-5-5", effort: "high" }]
const TRIAL_WEEKLY: WriterSetting[] = [{ model: "claude-opus-5-5", effort: "medium" }, { model: "claude-opus-5-5", effort: "high" }, { model: "claude-opus-5-5", effort: "xhigh" }]
const LABELS: ReportVariant[] = ["A", "B", "C"]
const sameWriter = (a: WriterSetting, b: WriterSetting) => a.model === b.model && a.effort === b.effort
const DEFAULT_WRITER: WriterSetting = { model: "claude-opus-5-5", effort: "high" }
const MODELS = new Set(["claude-opus-5-5", "claude-sonnet-5-5"])
const EFFORTS = new Set(["low", "medium", "high", "xhigh"])

interface MockVariant {
  writer: WriterSetting
  status: "ok" | "running" | "data_only"
  finished_at: string | null
  on_time: boolean
  seconds: number | null
  cost: number
  report: MarketReport | null
  metrics: TrialMetrics | null
}
interface MockReport {
  id: string
  kind: ReportKind
  d: string
  visibility: "admin" | "public"
  trial: boolean
  versions: MarketReport[]
  /** 一般使用者看到的那一版（`versions` 的索引） */
  current: number
  first: string
  variants: Partial<Record<ReportVariant, MockVariant>>
}
interface Live {
  run: AdminReportRun
}

const PUBLISH: Record<ReportKind, { data: string; ai: string }> = { premarket: { data: "06:55", ai: "07:25" }, close: { data: "14:10", ai: "15:55" }, weekly: { data: "16:30", ai: "18:00" } }
const KIND_ORDER: Record<ReportKind, number> = { weekly: 2, close: 1, premarket: 0 }

export interface MarketReportsDeps {
  now(): Date
  isAdmin(): boolean
  signedIn(): boolean
  /** personal 模式：示範資料標記 */
  demo: boolean
}

export function createMarketReportsStore(deps: MarketReportsDeps, scenario: MockReportsScenario = "trial") {
  const enabled = scenario !== "off"
  const nowIso = () => {
    const t = deps.now().getTime()
    return new Date(t + 8 * 3_600_000).toISOString().slice(0, 19) + "+08:00"
  }
  const today = nowIso().slice(0, 10)
  const nowAt = nowIso()
  const pub = scenario === "public" || scenario === "pending"
  let mode: ReportsMode = pub ? "public" : "trial"
  let writers: Record<ReportKind, WriterSetting | null> = pub
    ? { premarket: { model: "claude-opus-5-5", effort: "high" }, close: { model: "claude-opus-5-5", effort: "high" }, weekly: { model: "claude-opus-5-5", effort: "high" } }
    : { premarket: null, close: null, weekly: null }
  // 盲測：public 情境在 10/26 起做完（10/26–10/30 五個交易日＋11/1 週報）並揭曉；trial 情境從今天往前兩個交易日開始
  const trialStart = pub ? "2026-10-26" : prevTrading(prevTrading(today))
  let revealedAt: string | null = pub ? "2026-11-02T10:12:00+08:00" : null
  let seenAt: string | null = null
  const votes = new Map<string, { preferred: ReportVariant; note: string }>()
  const reports: MockReport[] = []
  const live: Live[] = []

  /** 哪些日子出了哪些報告（只到現在為止）：盤前與盤後是交易日、週報是週日 */
  const editions: { kind: ReportKind; d: string }[] = []
  for (let d = pub ? "2026-10-26" : trialStart; d <= today; d = addDays(d, 1)) {
    if (isWeekday(d)) {
      if (at(d, PUBLISH.premarket.data) <= nowAt) editions.push({ kind: "premarket", d })
      if (at(d, PUBLISH.close.data) <= nowAt) editions.push({ kind: "close", d })
    } else if (parseDay(d).getUTCDay() === 0 && at(d, PUBLISH.weekly.data) <= nowAt) editions.push({ kind: "weekly", d })
  }
  // 盲測：從開始那天起的 5 個交易日（往後數）
  const trialDays = new Set<string>()
  for (let d = trialStart; trialDays.size < 5; d = addDays(d, 1)) if (isWeekday(d)) trialDays.add(d)
  const firstWeekly = editions.find((e) => e.kind === "weekly" && e.d >= trialStart)?.d
  const isTrialEdition = (kind: ReportKind, d: string) => (kind === "weekly" ? d === firstWeekly : trialDays.has(d))
  const latestOf = (kind: ReportKind) => [...editions].reverse().find((e) => e.kind === kind)?.d

  for (const { kind, d } of editions) {
    const id = `mrp_${kind}_${d.replaceAll("-", "")}`
    const trial = isTrialEdition(kind, d)
    const base = { id, kind, d, demo: deps.demo }
    const first = at(d, PUBLISH[kind].data)
    const aiTime = at(d, PUBLISH[kind].ai)
    const versions: MarketReport[] = []
    const add = (b: Omit<Build, "id" | "kind" | "d" | "demo" | "version" | "first">) => {
      versions.push(BUILDERS[kind]({ ...base, ...b, version: versions.length + 1, first }))
    }
    const isLatest = latestOf(kind) === d
    // 只有資料的那一版（每一份都先有）
    const aiDone = aiTime <= nowAt
    const pendingNow = scenario === "pending" && isLatest && kind === "premarket"
    add({ ai: false, edition: "data", published: first, statusLine: trial ? TRIAL_LINE : aiDone && !pendingNow ? NO_AI_LINE : PENDING_LINE })
    const variants: MockReport["variants"] = {}
    if (trial) {
      // 每一份重新打亂 A／B／C 對到哪一組設定
      const order = [...(kind === "weekly" ? TRIAL_WEEKLY : TRIAL_DAILY)]
      const r = rng(`shuffle:${id}`)
      for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(r() * (i + 1))
        ;[order[i], order[j]] = [order[j]!, order[i]!]
      }
      order.forEach((writer, i) => {
        const label = LABELS[i]!
        const sonnet = writer.model === "claude-sonnet-5-5"
        const running = !aiDone && isLatest
        const dataOnly = !running && sonnet && kind === "premarket" && editions.filter((e) => e.kind === "premarket" && isTrialEdition("premarket", e.d)).at(1)?.d === d
        const dropped = !running && !dataOnly && sonnet ? [{ key: kind === "premarket" ? "watch" : kind === "close" ? "sectors" : "themes", reasons: ["number_subject_mismatch", "修正後仍有問題"] }] : undefined
        const seconds = running ? null : Math.round(between(rng(`${id}:${label}`), sonnet ? 140 : writer.effort === "medium" ? 210 : 330, sonnet ? 260 : writer.effort === "medium" ? 420 : 760, 0))
        const finished = running ? null : new Date(Date.parse(aiTime) - 600_000 + (seconds ?? 0) * 1000).toISOString().replace(/\.\d+Z$/, "Z")
        const onTime = !running && (seconds ?? 0) < 700
        const report = running
          ? null
          : BUILDERS[kind]({ ...base, version: 1, first, ai: !dataOnly, edition: dataOnly ? "data" : "ai", published: aiTime, dropped, flavor: i, statusLine: dataOnly ? NO_AI_LINE : null })
        variants[label] = {
          writer, status: running ? "running" : dataOnly ? "data_only" : "ok", finished_at: finished, on_time: onTime, seconds,
          cost: sonnet ? 0.62 : writer.effort === "medium" ? 1.08 : writer.effort === "high" ? 1.46 : 2.31,
          report,
          metrics: running
            ? null
            : {
                policy_violations: 0, subject_mismatches: dropped ? 1 : 0, inferred_dates: dropped ? 1 : 0, dropped_sections: dropped?.length ?? 0,
                revised: !!dropped, data_only: dataOnly, on_time: onTime, seconds, fallback_used: false, refusal_category: dataOnly ? "cyber" : null,
              },
        }
      })
      if (pub) votes.set(id, { preferred: (Object.entries(variants).find(([, v]) => v?.writer.model === "claude-opus-5-5" && v.writer.effort === "high")?.[0] ?? "A") as ReportVariant, note: "" })
      else if (d === trialStart && kind === "premarket") votes.set(id, { preferred: "B", note: "標題比較好讀" })
    } else if (aiDone && !pendingNow) {
      // 一般的 AI 版；最早的一份盤後沒有 AI 段落（資料版）、一份官方指數沒進來
      const missing = kind === "close" && d === "2026-11-04"
      const noAi = kind === "close" && d === "2026-11-06"
      if (!noAi) add({ ai: true, edition: "ai", published: aiTime, indexMissing: missing })
      if (kind === "close" && at(d, "23:45") <= nowAt) add({ ai: !noAi, edition: "tables", published: at(d, "23:45"), tables: true, indexMissing: missing, statusLine: noAi ? NO_AI_LINE : null })
      // 最新的盤後重點有一則更正
      if (kind === "close" && isLatest && pub) {
        const note = "「上市成交金額」原本沒有標「估算」，已補上。"
        add({ ai: true, edition: "correction", published: at(nextTrading(d), "09:10"), tables: at(d, "23:45") <= nowAt, corrections: [{ at: at(nextTrading(d), "09:10"), note }] })
      }
      if (!noAi) {
        live.push({
          run: {
            id: `mrr_${id.slice(4)}`, report_id: id, kind, edition_label: kind === "weekly" ? versions[0]!.edition_label : mdw(d), variant: null, purpose: "live", attempt: 1,
            status: "ok", step: "done", started_at: at(d, kind === "premarket" ? "07:00" : kind === "close" ? "15:41" : "16:52"),
            seconds: kind === "weekly" ? 612 : 318, stop_reason: "end_turn", fallback_used: d === "2026-11-05" && kind === "close", problems: kind === "premarket" ? 1 : 0,
            cost_usd: kind === "weekly" ? 2.38 : 1.42, model: "claude-opus-5-5", effort: "high",
          },
        })
      }
    }
    reports.push({ id, kind, d, visibility: trial || !pub ? "admin" : "public", trial, versions, current: versions.length - 1, first, variants })
  }

  // ── 手動表 ──
  let nyse: NyseHoliday[] = [
    { date: "2026-11-26", name: "感恩節", kind: "closed", close_time_et: null, source_url: "https://www.nyse.com/markets/hours-calendars", verified_at: "2026-11-17T10:20:00+08:00" },
    { date: "2026-11-27", name: "感恩節隔天", kind: "early_close", close_time_et: "13:00", source_url: "https://www.nyse.com/markets/hours-calendars", verified_at: "2026-11-17T10:20:00+08:00" },
    { date: "2026-12-24", name: "聖誕夜", kind: "early_close", close_time_et: "13:00", source_url: "https://www.nyse.com/markets/hours-calendars", verified_at: "2026-11-17T10:20:00+08:00" },
    { date: "2026-12-25", name: "聖誕節", kind: "closed", close_time_et: null, source_url: "https://www.nyse.com/markets/hours-calendars", verified_at: "2026-11-17T10:20:00+08:00" },
    { date: "2027-01-01", name: "元旦", kind: "closed", close_time_et: null, source_url: "https://www.nyse.com/markets/hours-calendars", verified_at: null },
    { date: "2027-01-18", name: "金恩紀念日", kind: "closed", close_time_et: null, source_url: "https://www.nyse.com/markets/hours-calendars", verified_at: null },
  ]
  let macro: MacroEvent[] = [
    { id: "mac_1", event_date: "2026-11-13", local_time: "08:30", tz: "America/New_York", country: "US", title: "10 月消費者物價指數", agency: "美國勞工統計局", official_url: "https://www.bls.gov/cpi/", sectors: ["金融保險"], note: "" },
    { id: "mac_2", event_date: "2026-11-17", local_time: "08:30", tz: "America/New_York", country: "US", title: "10 月零售銷售", agency: "美國普查局", official_url: "https://www.census.gov/retail/", sectors: ["貿易百貨"], note: "" },
    { id: "mac_3", event_date: "2026-11-20", local_time: "16:00", tz: "Asia/Taipei", country: "TW", title: "10 月外銷訂單統計", agency: "經濟部統計處", official_url: "https://www.moea.gov.tw/", sectors: ["電子零組件"], note: "" },
  ]
  let earnings: UsEarning[] = [
    { id: "use_1", symbol: "DEMO", company: "示範網通", report_date: "2026-11-12", timing: "amc", time_et: "16:05", official_url: null, sectors: ["通信網路"], note: "示範資料" },
    { id: "use_2", symbol: "DEMO2", company: "示範晶片", report_date: "2026-11-19", timing: "amc", time_et: null, official_url: null, sectors: ["半導體"], note: "示範資料" },
  ]
  let manualSeq = 10

  // ── 可見性 ──
  const requireSignedIn = () => {
    if (!deps.signedIn()) throw new ApiError(401, "unauthorized", "請先登入")
  }
  const requireAdmin = () => {
    requireSignedIn()
    if (!deps.isAdmin()) throw new ApiError(404, "not_found", "找不到這個頁面")
  }
  const visible = () => (enabled ? reports.filter((r) => r.visibility === "public" || deps.isAdmin()) : [])
  const order = (a: MockReport, b: MockReport) => b.d.localeCompare(a.d) || KIND_ORDER[b.kind] - KIND_ORDER[a.kind] || b.id.localeCompare(a.id)
  const summary = (r: MockReport): ReportSummary => {
    const c = r.versions[r.current]!
    return { id: r.id, kind: r.kind, kind_label: c.kind_label, edition_date: r.d, edition_label: c.edition_label, title: c.title, has_ai: c.has_ai, published_at: c.published_at, corrected: c.corrections.length > 0 }
  }
  const find = (id: string) => {
    const r = visible().find((x) => x.id === id)
    if (!r) throw new ApiError(404, "not_found", "找不到這份報告")
    return r
  }
  const trialReports = () => reports.filter((r) => r.trial)
  const trialProgress = () => {
    const tr = trialReports()
    const daily = tr.filter((r) => r.kind !== "weekly" && Object.values(r.variants).every((v) => v && v.status !== "running")).length
    const weeklyDone = tr.some((r) => r.kind === "weekly" && Object.values(r.variants).every((v) => v && v.status !== "running"))
    const daysDone = new Set(tr.filter((r) => r.kind !== "weekly").map((r) => r.d)).size
    return { daily, weeklyDone, daysDone, finished: daily >= 10 && weeklyDone }
  }
  const trialSpend = () => trialReports().reduce((a, r) => a + Object.values(r.variants).reduce((b, v) => b + (v && v.status !== "running" ? v.cost : 0), 0), 0) + 0.38 * trialReports().length
  const monthSpend = () => live.filter((l) => l.run.started_at.slice(0, 7) === today.slice(0, 7)).reduce((a, l) => a + (l.run.cost_usd ?? 0), 0)

  const reveal = (): TrialReveal => {
    const kinds = (["premarket", "close", "weekly"] as const).map((kind) => {
      const tr = trialReports().filter((r) => r.kind === kind)
      const writersOf = kind === "weekly" ? TRIAL_WEEKLY : TRIAL_DAILY
      const rows: TrialRevealRow[] = writersOf.map((w) => {
        const vs = tr.flatMap((r) => Object.entries(r.variants).filter(([, v]) => v && sameWriter(v.writer, w)).map(([label, v]) => ({ label, v: v!, r })))
        const done = vs.filter((x) => x.v.metrics)
        const n = Math.max(1, done.length)
        const sum = (f: (m: TrialMetrics) => number) => done.reduce((a, x) => a + f(x.v.metrics!), 0)
        const row = {
          writer: w, reports: done.length, votes: vs.filter((x) => votes.get(x.r.id)?.preferred === x.label).length,
          policy_violations: sum((m) => m.policy_violations), subject_mismatches: sum((m) => m.subject_mismatches), inferred_dates: sum((m) => m.inferred_dates),
          dropped_sections: sum((m) => m.dropped_sections), on_time_rate: done.filter((x) => x.v.on_time).length / n,
          avg_cost_usd: Number((done.reduce((a, x) => a + x.v.cost, 0) / n).toFixed(2)), avg_seconds: Math.round(sum((m) => m.seconds ?? 0) / n),
        }
        const passed = done.length > 0 && row.policy_violations === 0 && (row.subject_mismatches + row.inferred_dates) / n <= 1 && row.dropped_sections / n <= 1 && row.on_time_rate >= 0.8 && !done.some((x) => x.v.metrics!.data_only)
        return { ...row, passed }
      })
      const ok = rows.filter((x) => x.passed).sort((a, b) => a.avg_cost_usd - b.avg_cost_usd)
      return { kind, kind_label: REPORT_KIND_LABEL[kind], rows, suggested: ok[0]?.writer ?? null }
    })
    return { revealed_at: revealedAt ?? nowAt, kinds }
  }

  const officialHost = (url: string) => {
    try {
      const h = new URL(url).hostname.replace(/^www\./, "")
      const OK = ["federalreserve.gov", "bls.gov", "bea.gov", "census.gov", "treasury.gov", "home.treasury.gov", "dol.gov", "dgbas.gov.tw", "stat.gov.tw", "ndc.gov.tw", "mof.gov.tw", "moea.gov.tw", "cbc.gov.tw", "ecb.europa.eu", "boj.or.jp"]
      return new URL(url).protocol === "https:" && OK.some((d) => h === d || h.endsWith(`.${d}`))
    } catch {
      return false
    }
  }
  // 和伺服器一樣：欄位名在 `error.details.field`
  const field = (name: string, message: string) => new ApiError(422, "validation_error", message, { details: { field: name } })

  return {
    /** 群組頻道的三個開關只在對全站公開時出現 */
    publicMode: () => enabled && mode === "public",

    status(): ReportsStatus {
      requireSignedIn()
      const vis = visible().sort(order)
      const latest = (["premarket", "close", "weekly"] as const).flatMap((k) => {
        const r = vis.find((x) => x.kind === k)
        return r ? [summary(r)] : []
      })
      const newest = [...vis].sort((a, b) => b.first.localeCompare(a.first))[0]
      const unread = !!newest && (seenAt ? newest.first > seenAt : Date.parse(nowAt) - Date.parse(newest.first) < 24 * 3_600_000)
      return { available: vis.length > 0, mode: deps.isAdmin() && enabled ? mode : null, unread, latest }
    },
    list(query: { kind?: ReportKind; limit?: number; cursor?: string | null } = {}): Paged<ReportSummary> {
      requireSignedIn()
      const all = visible().filter((r) => !query.kind || r.kind === query.kind).sort(order)
      const offset = query.cursor ? Number(atob(query.cursor)) || 0 : 0
      const limit = Math.min(Math.max(query.limit ?? 20, 1), 50)
      const items = all.slice(offset, offset + limit).map(summary)
      return { items, next_cursor: offset + limit < all.length ? btoa(String(offset + limit)) : null }
    },
    latest(kind?: ReportKind): MarketReport | null {
      requireSignedIn()
      const r = visible().filter((x) => !kind || x.kind === kind).sort(order)[0]
      return r ? publicView(r.versions[r.current]!) : null
    },
    get(id: string, version?: number): MarketReport {
      requireSignedIn()
      const r = find(id)
      const v = version ? r.versions.find((x) => x.version === version) : r.versions[r.current]
      if (!v) throw new ApiError(404, "not_found", "找不到這一版")
      return publicView(v)
    },
    seen(): void {
      requireSignedIn()
      seenAt = nowAt
    },

    // ── 管理後台 ──
    overview(): AdminReportsOverview {
      requireAdmin()
      const p = trialProgress()
      const spend = monthSpend()
      const tier = spend >= 80 ? "data_only" : spend >= 72 ? "sonnet" : spend >= 56 ? "medium" : "normal"
      const trialRuns: AdminReportRun[] = trialReports().flatMap((r) =>
        Object.entries(r.variants).map(([label, v]) => ({
          id: `mrr_${r.id.slice(4)}_${label}`, report_id: r.id, kind: r.kind, edition_label: r.versions[0]!.edition_label, variant: label as ReportVariant, purpose: "trial" as const,
          attempt: 1, status: v!.status === "running" ? ("running" as const) : v!.status, step: v!.status === "running" ? "write" : "done",
          started_at: at(r.d, r.kind === "premarket" ? "07:00" : r.kind === "close" ? "15:41" : "16:52"), seconds: v!.seconds,
          stop_reason: v!.status === "data_only" ? "refusal" : v!.status === "running" ? null : "end_turn", fallback_used: false,
          problems: v!.metrics ? v!.metrics.subject_mismatches + v!.metrics.inferred_dates : 0,
          cost_usd: revealedAt ? v!.cost : null, model: revealedAt ? v!.writer.model : null, effort: revealedAt ? v!.writer.effort : null,
        })),
      )
      const runs = [...live.map((l) => l.run), ...trialRuns].sort((a, b) => b.started_at.localeCompare(a.started_at) || (a.variant ?? "").localeCompare(b.variant ?? "")).slice(0, 20)
      const upcoming = nyse.filter((h) => h.date >= today).sort((a, b) => a.date.localeCompare(b.date))[0]
      const in14 = (d: string) => d >= today && d <= addDays(today, 14)
      return {
        enabled, mode,
        writers: Object.fromEntries((["premarket", "close", "weekly"] as const).map((k) => [k, !revealedAt ? null : writers[k] ? { ...writers[k]!, source: "admin" as const } : { ...DEFAULT_WRITER, source: "default" as const }])) as AdminReportsOverview["writers"],
        trial_running: !revealedAt && !p.finished,
        month: { label: `${today.slice(0, 4)} 年 ${Number(today.slice(5, 7))} 月`, spend_usd: Number(spend.toFixed(2)), budget_usd: 80, tier },
        trial: { spend_usd: Number(trialSpend().toFixed(2)), budget_usd: 45, days_done: Math.min(5, p.daysDone), days_total: 5, weekly_done: p.weeklyDone, started_on: trialStart, revealed_at: revealedAt, finished: p.finished },
        key: { slot: 4, status: "ok", note: null },
        runs,
        manual: {
          nyse_next: upcoming ? { date: upcoming.date, name: upcoming.name, kind: upcoming.kind } : null,
          nyse_unverified: nyse.filter((h) => !h.verified_at).length,
          macro_next_14d: macro.filter((m) => in14(m.event_date)).length,
          earnings_next_14d: earnings.filter((e) => in14(e.report_date)).length,
        },
      }
    },
    config(patch: ReportsConfigPatch): ReportsConfigResult {
      requireAdmin()
      for (const [k, w] of Object.entries(patch.writers ?? {})) {
        if (w && (!MODELS.has(w.model) || !EFFORTS.has(w.effort))) throw field(`writers.${k}`, "模型只能選 Opus 5.5 或 Sonnet 5.5，effort 只能選 low 到 xhigh。")
      }
      const switching = patch.mode === "public" && mode !== "public"
      if (patch.mode) mode = patch.mode
      if (patch.writers) writers = { ...writers, ...patch.writers }
      return { mode, writers, notice: switching ? "之後的新報告會對所有登入的人公開，並推播到有開的群組。" : null }
    },
    trial(): AdminTrial {
      requireAdmin()
      const p = trialProgress()
      return {
        days_done: Math.min(5, p.daysDone), days_total: 5, weekly_done: p.weeklyDone, finished: p.finished,
        reports: trialReports().sort(order).map((r) => ({
          report_id: r.id, kind: r.kind, edition_date: r.d, edition_label: r.versions[0]!.edition_label,
          variants: LABELS.map((label) => {
            const v = r.variants[label]!
            return {
              label, status: v.status, finished_at: v.finished_at, on_time: v.status === "running" ? null : v.on_time,
              metrics: v.metrics ? { ...v.metrics, ...(revealedAt ? { cost_usd: v.cost } : {}) } : null,
              ...(revealedAt ? { writer: v.writer } : {}),
            }
          }),
          my_vote: votes.get(r.id) ?? null,
        })),
        reveal: revealedAt ? reveal() : null,
      }
    },
    variant(reportId: string, label: ReportVariant): MarketReport {
      requireAdmin()
      const r = reports.find((x) => x.id === reportId && x.trial)
      const v = r?.variants[label]
      if (!r || !v) throw new ApiError(404, "not_found", "找不到這個版本")
      if (!v.report) throw new ApiError(409, "variant_running", "這個版本還在寫。")
      return v.report
    },
    vote(reportId: string, body: { preferred: ReportVariant; note?: string }): void {
      requireAdmin()
      if (!reports.some((x) => x.id === reportId && x.trial)) throw new ApiError(404, "not_found", "找不到這份報告")
      if (!LABELS.includes(body.preferred)) throw field("preferred", "請選 A、B 或 C。")
      votes.set(reportId, { preferred: body.preferred, note: (body.note ?? "").slice(0, 500) })
    },
    reveal(body: { force?: boolean } = {}): TrialReveal {
      requireAdmin()
      const p = trialProgress()
      if (!p.finished && !body.force) throw new ApiError(409, "trial_unfinished", `盲測還沒做完（${p.daily}/10 份日報、週報 ${p.weeklyDone ? 1 : 0}/1）。`)
      revealedAt ??= nowAt
      return reveal()
    },
    correction(reportId: string, body: { note: string; drop_sections?: string[] }): MarketReport {
      requireAdmin()
      const r = reports.find((x) => x.id === reportId)
      if (!r) throw new ApiError(404, "not_found", "找不到這份報告")
      const note = body.note.trim()
      if (note.length < 1 || note.length > 200) throw field("note", "更正說明要 1 到 200 個字。")
      const c = r.versions[r.current]!
      const next: MarketReport = {
        ...c, version: r.versions.length + 1, edition: "correction", published_at: nowAt,
        corrections: [...c.corrections, { at: nowAt, note }],
        sections: c.sections.filter((s) => !(body.drop_sections ?? []).includes(s.key)),
      }
      r.versions.push(next)
      r.current = r.versions.length - 1
      return publicView(next)
    },
    rebuild(body: { kind: ReportKind; edition_date: string }): void {
      requireAdmin()
      if (!reports.some((r) => r.kind === body.kind && r.d === body.edition_date)) throw new ApiError(404, "not_found", "那一天沒有這種報告")
    },
    nyseList(): NyseHoliday[] {
      requireAdmin()
      return [...nyse].sort((a, b) => a.date.localeCompare(b.date))
    },
    nysePut(date: string, body: NyseHolidayInput): NyseHoliday {
      requireAdmin()
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw field("date", "日期要寫成 2026-11-26。")
      if (!body.name.trim()) throw field("name", "請寫休市的原因，例如「感恩節」。")
      if (body.kind === "early_close" && !/^\d{2}:\d{2}$/.test(body.close_time_et ?? "")) throw field("close_time_et", "提早收盤要寫收盤時間（美東），例如 13:00。")
      if (!/^https:\/\/(www\.)?nyse\.com\//.test(body.source_url)) throw field("source_url", "只能連到 NYSE 的官方頁面（nyse.com）。")
      const row: NyseHoliday = { date, name: body.name.trim(), kind: body.kind, close_time_et: body.kind === "early_close" ? body.close_time_et ?? null : null, source_url: body.source_url, verified_at: body.verified ? nowAt : null }
      nyse = [...nyse.filter((h) => h.date !== date), row]
      return row
    },
    nyseDelete(date: string): void {
      requireAdmin()
      if (!nyse.some((h) => h.date === date)) throw new ApiError(404, "not_found", "找不到這一天")
      nyse = nyse.filter((h) => h.date !== date)
    },
    macroList(): MacroEvent[] {
      requireAdmin()
      return [...macro].sort((a, b) => a.event_date.localeCompare(b.event_date))
    },
    macroAdd(body: MacroEventInput): MacroEvent {
      requireAdmin()
      if (!/^\d{4}-\d{2}-\d{2}$/.test(body.event_date)) throw field("event_date", "日期要寫成 2026-11-13。")
      if (!body.title.trim()) throw field("title", "請寫數據名稱，例如「10 月消費者物價指數」。")
      if (!body.agency.trim()) throw field("agency", "請寫公布的機關。")
      if (!officialHost(body.official_url)) throw field("official_url", "只能連到官方網站（例如 bls.gov、dgbas.gov.tw）。")
      const row: MacroEvent = { id: `mac_${++manualSeq}`, event_date: body.event_date, local_time: body.local_time || null, tz: body.tz, country: body.country, title: body.title.trim(), agency: body.agency.trim(), official_url: body.official_url, sectors: body.sectors ?? [], note: body.note ?? "" }
      macro = [...macro, row]
      return row
    },
    macroDelete(id: string): void {
      requireAdmin()
      if (!macro.some((m) => m.id === id)) throw new ApiError(404, "not_found", "找不到這一列")
      macro = macro.filter((m) => m.id !== id)
    },
    earningsList(): UsEarning[] {
      requireAdmin()
      return [...earnings].sort((a, b) => a.report_date.localeCompare(b.report_date))
    },
    earningsAdd(body: UsEarningInput): UsEarning {
      requireAdmin()
      if (!/^[A-Z.]{1,10}$/.test(body.symbol.trim().toUpperCase())) throw field("symbol", "請寫美股代號，例如 NVDA。")
      if (!body.company.trim()) throw field("company", "請寫公司名稱。")
      if (!/^\d{4}-\d{2}-\d{2}$/.test(body.report_date)) throw field("report_date", "日期要寫成 2026-11-19（美東）。")
      if (body.official_url && !/^https:\/\//.test(body.official_url)) throw field("official_url", "網址要用 https:// 開頭。")
      const row: UsEarning = { id: `use_${++manualSeq}`, symbol: body.symbol.trim().toUpperCase(), company: body.company.trim(), report_date: body.report_date, timing: body.timing, time_et: body.time_et || null, official_url: body.official_url || null, sectors: body.sectors ?? [], note: body.note ?? "" }
      earnings = [...earnings, row]
      return row
    },
    earningsDelete(id: string): void {
      requireAdmin()
      if (!earnings.some((e) => e.id === id)) throw new ApiError(404, "not_found", "找不到這一列")
      earnings = earnings.filter((e) => e.id !== id)
    },
  }
}

export type MarketReportsStore = ReturnType<typeof createMarketReportsStore>
/** 測試用：直接拿到三種報告的 AI 版（管理員形式） */
export function buildMockReport(kind: ReportKind, d: string, opts: Partial<Build> = {}): MarketReport {
  return BUILDERS[kind]({ id: `mrp_${kind}_${d.replaceAll("-", "")}`, kind, d, ai: true, edition: "ai", version: 1, published: at(d, PUBLISH[kind].ai), first: at(d, PUBLISH[kind].data), demo: false, ...opts })
}
