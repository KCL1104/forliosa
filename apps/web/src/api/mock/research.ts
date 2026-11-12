/**
 * 示範資料：個股頁新增端點（overview、intraday、chips、financials、events、news、position、why），
 * 以及帳本的「本週事項」與自選。全部可重現（以代號為亂數種子），並標示示範資料。
 * 形狀與 docs/api-contract.md「重新設計新增（2026-11-12）」逐欄一致。
 */
import { limitPrices } from "@/lib/tick"
import type {
  Chips,
  ChipsRange,
  Financials,
  FinancialsPeriod,
  Holding,
  InstrumentEvent,
  InstrumentOverview,
  Intraday,
  NewsItem,
  Position,
  PositionMarker,
  Transaction,
  UpcomingItem,
  Why,
  WhyReason,
} from "../types"
import { AI_SEARCH_ATTRIBUTION, GDELT_ATTRIBUTION, SEARXNG_ATTRIBUTION, secSourceOf, sourceOf, YAHOO_RSS_ATTRIBUTION } from "./attributions"
import { accumulatingNote, ARCHIVE_START, INTRADAY_NOTE, TOP20_NOTE, TWSE_CHIPS_NOTE, TWSE_INST_NOTE } from "./commercial"
import type { MockInstrumentSpec } from "./instruments"
import { buildHoldings, replay } from "./ledger"
import { addDays, dailyCandles, dividendRecords, FX_NOW, MOCK_AS_OF, MOCK_TODAY, monthlyRevenue, rng, tradingDays } from "./market"
import { SEC_MOCK } from "./sec-data"

const DEMO_SRC = ["示範資料（模擬數字，不代表真實行情）"]
const tw = (spec: MockInstrumentSpec) => (spec.market === "TPEX" ? "tpex-openapi" : "twse-openapi")
const round = (n: number, d = 2) => Math.round(n * 10 ** d) / 10 ** d

export function referencePrice(spec: MockInstrumentSpec): number {
  return spec.prev_close
}

export function limitsOf(spec: MockInstrumentSpec) {
  return limitPrices(referencePrice(spec), spec.market, spec.type)
}

// ── overview ─────────────────────────────────────────────
export function buildOverview(spec: MockInstrumentSpec, commercial = false): InstrumentOverview {
  if (commercial && spec.market === "US") {
    // 美股沒有可商用的行情來源：價格欄位 null；近四季 EPS 與流通股數來自 SEC EDGAR 的存檔（與後端相同）
    const sec = spec.type === "stock" ? SEC_MOCK[spec.symbol] : undefined
    return {
      symbol: spec.symbol, open: null, high: null, low: null, prev_close: null, reference_price: null, limit_up: null, limit_down: null,
      volume: null, avg_volume_3m: null, market_cap: null, pe: null, pb: null, dividend_yield: null, last_cash_dividend: null,
      ex_dividend_date: null, eps_ttm: sec?.eps_ttm ?? null, high_52w: null, low_52w: null, shares_outstanding: sec?.shares_outstanding ?? null,
      status: { attention: false, disposition: false, note: null }, as_of: null,
      sources: ["內建商品清單", ...(sec ? [secSourceOf("sec-edgar/companyfacts")] : [])], is_demo: false,
    }
  }
  const candles = dailyCandles(spec)
  const last = candles.at(-1)!
  const year = candles.slice(-250)
  const q3 = candles.slice(-63)
  const divs = dividendRecords(spec).filter((d) => d.cash_dividend > 0)
  const ttmCash = divs.filter((d) => d.ex_dividend_date && d.ex_dividend_date > addDays(MOCK_TODAY, -365) && d.ex_dividend_date <= MOCK_TODAY).reduce((s, d) => s + d.cash_dividend, 0)
  const latest = divs[0]
  const limits = limitsOf(spec)
  const fx = 1
  return {
    open: last.o,
    high: last.h,
    low: last.l,
    prev_close: spec.prev_close,
    reference_price: referencePrice(spec),
    limit_up: limits?.up ?? null,
    limit_down: limits?.down ?? null,
    volume: last.v,
    avg_volume_3m: Math.round(q3.reduce((s, c) => s + c.v, 0) / q3.length / 1000) * 1000,
    market_cap: spec.market_cap,
    pe: spec.eps_now && spec.eps_now > 0 ? round(spec.price / spec.eps_now, 2) : null,
    pb: spec.bvps_now ? round(spec.price / spec.bvps_now, 2) : null,
    dividend_yield: ttmCash > 0 ? round((ttmCash * fx) / spec.price, 4) : null,
    last_cash_dividend: latest?.cash_dividend ?? null,
    ex_dividend_date: latest?.ex_dividend_date ?? null,
    eps_ttm: spec.eps_now ?? null,
    high_52w: Math.max(...year.map((c) => c.h)),
    low_52w: Math.min(...year.map((c) => c.l)),
    shares_outstanding: spec.shares_outstanding,
    status: {
      attention: spec.symbol === "6488.TWO",
      disposition: false,
      note: spec.symbol === "6488.TWO" ? "近 6 日累積跌幅過大，列為注意股票" : null,
    },
    as_of: spec.market === "US" ? "2026-11-12T05:00:00+08:00" : MOCK_AS_OF,
    sources: commercial ? [sourceOf(`${tw(spec)}/price`), sourceOf(`${tw(spec)}/valuation`), sourceOf(`${tw(spec)}/reference`)] : spec.data_sources,
    is_demo: !commercial,
  }
}

// ── intraday（只有持股與自選有點） ────────────────────────
function minuteLabels(): string[] {
  const out: string[] = []
  for (let m = 9 * 60 + 1; m <= 13 * 60 + 30; m++) out.push(`${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`)
  return out
}

export function buildIntraday(spec: MockInstrumentSpec, tracked: boolean, commercial = false): Intraday {
  const base: Intraday = {
    symbol: spec.symbol,
    date: MOCK_TODAY,
    prev_close: spec.prev_close,
    reference_price: referencePrice(spec),
    points: [],
    is_partial: false,
    sources: commercial ? [] : DEMO_SRC,
    is_demo: !commercial,
  }
  // 商用模式：沒有授權的盤中來源，一律沒有點（任何模式的後端都是這樣；personal 的 mock 保留示範走勢給開發用）
  if (commercial) return { ...base, is_partial: true, notes: [INTRADAY_NOTE] }
  if (!tracked) return base
  const labels = spec.market === "US" ? usMinuteLabels() : minuteLabels()
  const r = rng(`intraday:${spec.symbol}:${MOCK_TODAY}`)
  const n = labels.length
  // 布朗橋：從昨收附近開到現價收
  const start = spec.prev_close * (1 + (r() - 0.5) * 0.006)
  const end = spec.price
  const vol = (spec.vol / Math.sqrt(252)) * 0.9
  let walk = 0
  const steps: number[] = []
  for (let i = 0; i < n; i++) {
    walk += (r() - 0.5) * vol * 0.25
    steps.push(walk)
  }
  const drift = steps[n - 1]!
  const tick = (p: number) => (spec.market === "US" ? round(p, 2) : round(p, p < 50 ? 2 : p < 500 ? 1 : 0))
  const points = labels.map((t, i) => {
    const frac = i / (n - 1)
    const bridge = steps[i]! - drift * frac
    const p = (start + (end - start) * frac) * (1 + bridge)
    return { t, price: tick(i === n - 1 ? end : p), volume: Math.round((spec.avg_volume / n) * (0.4 + r() * 1.4) / 1000) * 1000 }
  })
  return { ...base, points }
}

function usMinuteLabels(): string[] {
  // 美股盤中（台北時間 22:30–05:00），示範資料每 5 分鐘一點
  const out: string[] = []
  for (let m = 22 * 60 + 30; m <= 29 * 60; m += 5) {
    const mm = m % (24 * 60)
    out.push(`${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`)
  }
  return out
}

// ── chips（法人、融資融券、外資持股、千張大戶） ────────────
const CHIPS_DAYS: Record<ChipsRange, number> = { "1M": 22, "3M": 63, "6M": 126, "1Y": 250 }

/** 證交所 MI_QFIIS_sort_20（2026-11-12）裡的示範股票：名次、外資持股比與連續在榜的交易日數 */
const TOP20: Record<string, { rank: number; pct: number; days: number }> = { "3711.TW": { rank: 12, pct: 0.7552, days: 9 } }

export function buildChips(spec: MockInstrumentSpec, range: ChipsRange = "3M", commercial = false): Chips {
  if (spec.market === "US") {
    return { institutional: [], margin: [], foreign_holding_pct: [], major_holders: null, sources: commercial ? [] : DEMO_SRC, is_demo: !commercial }
  }
  if (commercial) {
    const full = buildChips(spec, range)
    const kept = <T extends { t: string }>(rows: T[]) => rows.filter((r) => r.t >= ARCHIVE_START)
    const short = full.margin.some((r) => r.t < ARCHIVE_START)
    const listed = spec.market === "TWSE"
    // 上市股票：只有名列證交所「外資及陸資持股前 20 名」的日子有外資持股比（示範：日月光投控第 12 名）
    const top20 = listed ? TOP20[spec.symbol] : undefined
    const wiggle = rng(`top20:${spec.symbol}`)
    const top20Rows = top20
      ? tradingDays(top20.days).map((t, i, all) => ({ t, pct: i === all.length - 1 ? top20.pct : round(top20.pct - (all.length - 1 - i) * 0.0004 + (wiggle() - 0.5) * 0.0012, 4) }))
      : []
    // 與後端相同：上市股票一律說明為什麼沒有三大法人；在榜時另加前 20 名的說明
    const notes = [...(listed ? (top20 ? [TWSE_INST_NOTE, TOP20_NOTE] : [TWSE_CHIPS_NOTE]) : []), ...(short ? [accumulatingNote()] : [])]
    const src = listed
      ? [sourceOf("twse-openapi/margin"), ...(top20 ? [sourceOf("twse-openapi/foreign_top20")] : []), sourceOf("tdcc-opendata/distribution")]
      : [sourceOf("tpex-openapi/institutional"), sourceOf("tpex-openapi/foreign_holding"), sourceOf("tpex-openapi/margin"), sourceOf("tdcc-opendata/distribution")]
    return {
      institutional: listed ? [] : kept(full.institutional),
      margin: kept(full.margin),
      foreign_holding_pct: listed ? top20Rows : kept(full.foreign_holding_pct),
      major_holders: full.major_holders,
      sources: src,
      is_demo: false,
      notes,
      foreign_top20: top20 ? { as_of: MOCK_TODAY, rank: top20.rank, pct: top20.pct, limit_pct: 1 } : null,
    }
  }
  const days = tradingDays(CHIPS_DAYS[range])
  const r = rng(`chips:${spec.symbol}`)
  const scale = spec.avg_volume / 1000 / 12
  let trend = 0
  const institutional = days.map((t, i) => {
    trend = trend * 0.82 + (r() - 0.5) * 0.9
    // 最近 4 天外資賣、投信買（讓摘要句有東西可說）
    const recent = i >= days.length - 4
    const foreign = Math.round(scale * (recent ? -0.6 - r() * 0.5 : trend + (r() - 0.5)))
    const trust = Math.round(scale * 0.18 * (recent || i >= days.length - 5 ? 0.6 + r() * 0.6 : (r() - 0.45) * 1.2))
    const dealer = Math.round(scale * 0.1 * (r() - 0.5))
    return { t, foreign, trust, dealer, total: foreign + trust + dealer }
  })
  let margin = Math.round(scale * 12)
  let short = Math.round(scale * 1.1)
  const marginRows = days.map((t) => {
    margin = Math.max(0, Math.round(margin * (1 + (r() - 0.52) * 0.02)))
    short = Math.max(0, Math.round(short * (1 + (r() - 0.5) * 0.05)))
    return { t, margin_balance: margin, short_balance: short }
  })
  let pct = spec.type === "etf" ? 0.18 : spec.symbol === "2330.TW" ? 0.732 : 0.35 + r() * 0.3
  const foreignPct = days.map((t) => {
    pct = Math.min(0.95, Math.max(0.02, pct + (r() - 0.52) * 0.002))
    return { t, pct: round(pct, 4) }
  })
  // 上市股票任何模式都沒有逐檔三大法人與外資持股（產品負責人 2026-11-12；後端 services/stock.py 同規則）
  const listed = spec.market === "TWSE"
  const big = spec.type === "etf" ? 0.32 : spec.symbol === "2330.TW" ? 0.761 : 0.45 + r() * 0.25
  const rest = 1 - big
  const buckets = [
    { level: "1–999 股", pct: rest * 0.28 },
    { level: "1–10 張", pct: rest * 0.24 },
    { level: "10–100 張", pct: rest * 0.2 },
    { level: "100–400 張", pct: rest * 0.16 },
    { level: "400–1,000 張", pct: rest * 0.12 },
    { level: "1,000 張以上", pct: big },
  ]
  const shares = spec.shares_outstanding ?? 1_000_000_000
  const holders = [920_000, 380_000, 42_000, 3_100, 640, 1_380]
  return {
    institutional: listed ? [] : institutional,
    margin: marginRows,
    foreign_holding_pct: listed ? [] : foreignPct,
    major_holders: {
      as_of: "2026-11-06",
      buckets: buckets.map((b, i) => ({ level: b.level, holders: Math.round(holders[i]! * (shares / 25_932_666_666) ** 0.5), shares: Math.round(shares * b.pct), pct: round(b.pct, 4) })),
    },
    sources: [listed ? "臺灣證券交易所 OpenAPI（融資融券）" : "證券櫃檯買賣中心 OpenAPI（三大法人、融資融券、外資持股）", "集保結算所（股權分散表，每週）", ...DEMO_SRC],
    is_demo: true,
    ...(listed ? { notes: [TWSE_CHIPS_NOTE] } : {}),
  }
}

// ── financials（季報／年報） ─────────────────────────────
export function buildFinancials(spec: MockInstrumentSpec, period: FinancialsPeriod = "quarterly", commercial = false): Financials {
  if (spec.market === "US") return usFinancials(spec, period)
  if (commercial) {
    const f = buildFinancials(spec, period)
    return { ...f, is_demo: false, sources: f.periods.length ? [sourceOf("shioaji-data/official")] : [] }
  }
  const empty: Financials = {
    periods: [],
    income: { revenue: [], gross_profit: [], operating_income: [], net_income: [], eps: [] },
    balance: { total_assets: [], total_liabilities: [], equity: [] },
    cashflow: { operating: [], investing: [], financing: [], free_cash_flow: [] },
    margins: { gross: [], operating: [], net: [] },
    sources: DEMO_SRC,
    is_demo: true,
  }
  if (spec.type === "etf" || !spec.revenue_base || !spec.eps_now) return empty
  const rev = monthlyRevenue(spec)
  const r = rng(`fin:${spec.symbol}:${period}`)
  const shares = (spec.shares_outstanding ?? 1e9) / 1000 // 千股
  const periods: string[] = []
  const revenue: number[] = []
  if (period === "quarterly") {
    // 最近 8 季（到 2026Q3）
    const quarters = ["2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2", "2026Q3"]
    for (const q of quarters) {
      const y = q.slice(0, 4)
      const n = Number(q.slice(5))
      const months = [1, 2, 3].map((k) => `${y}-${String((n - 1) * 3 + k).padStart(2, "0")}`)
      const sum = months.reduce((s, m) => s + (rev.find((x) => x.period === m)?.revenue ?? 0), 0)
      if (sum > 0) {
        periods.push(q)
        revenue.push(sum)
      }
    }
  } else {
    for (const y of ["2021", "2022", "2023", "2024", "2025"]) {
      const sum = rev.filter((x) => x.period.startsWith(y)).reduce((s, x) => s + x.revenue, 0)
      if (sum > 0) {
        periods.push(y)
        revenue.push(sum)
      }
    }
  }
  const baseGross = spec.symbol === "2330.TW" ? 0.58 : spec.industry === "半導體業" ? 0.45 : 0.22
  const gross = revenue.map(() => round(baseGross + (r() - 0.5) * 0.04, 4))
  const opm = gross.map((g) => round(g - 0.1 - r() * 0.03, 4))
  const npm = opm.map((o) => round(o * 0.88 + (r() - 0.5) * 0.01, 4))
  const gp = revenue.map((v, i) => Math.round(v * gross[i]!))
  const op = revenue.map((v, i) => Math.round(v * opm[i]!))
  const ni = revenue.map((v, i) => Math.round(v * npm[i]!))
  const eps = ni.map((v) => round(v / shares, 2))
  const assets = revenue.map((v, i) => Math.round(v * (period === "quarterly" ? 6.5 : 1.7) * (1 + i * 0.02)))
  const liab = assets.map((a) => Math.round(a * (0.33 + r() * 0.05)))
  const equity = assets.map((a, i) => a - liab[i]!)
  const ocf = ni.map((v) => Math.round(v * (1.35 + r() * 0.3)))
  const inv = ocf.map((v) => -Math.round(v * (0.65 + r() * 0.2)))
  const fin = ocf.map((v) => -Math.round(v * (0.2 + r() * 0.15)))
  return {
    periods,
    income: { revenue, gross_profit: gp, operating_income: op, net_income: ni, eps },
    balance: { total_assets: assets, total_liabilities: liab, equity },
    cashflow: { operating: ocf, investing: inv, financing: fin, free_cash_flow: ocf.map((v, i) => v + inv[i]!) },
    margins: { gross, operating: opm, net: npm },
    sources: ["公開資訊觀測站（財務報表）", ...DEMO_SRC],
    is_demo: true,
  }
}

/** 美股：SEC EDGAR 的真實財報（sec-data.ts，兩種政策都一樣；不是示範數字） */
function usFinancials(spec: MockInstrumentSpec, period: FinancialsPeriod): Financials {
  const sec = spec.type === "stock" ? SEC_MOCK[spec.symbol] : undefined
  if (sec) return { ...sec[period], is_demo: false }
  return {
    periods: [], period_ends: [], currency: "USD", amount_unit: 1,
    income: { revenue: [], gross_profit: [], operating_income: [], net_income: [], eps: [] },
    balance: { total_assets: [], total_liabilities: [], equity: [] },
    cashflow: { operating: [], investing: [], financing: [], free_cash_flow: [] },
    margins: { gross: [], operating: [], net: [] },
    shares: null, sources: [], is_demo: false,
    notes: [spec.type === "etf" ? "ETF 沒有財務報表資料" : "SEC EDGAR 找不到這個代號（ETF 與外國公司通常不在美國申報 10-K／10-Q）"],
  }
}

/** 美股：SEC 的 8-K／10-Q／10-K；持有時 10-K、10-Q 算「我的」，8-K 只算最近 7 天的 */
function secFilings(spec: MockInstrumentSpec, qty: number): InstrumentEvent[] {
  const sec = spec.type === "stock" ? SEC_MOCK[spec.symbol] : undefined
  const src = [secSourceOf("sec-edgar/submissions")]
  return (sec?.filings ?? []).map((f) => {
    const periodic = /^10-[KQ]/.test(f.form)
    return {
      date: f.date, type: "sec_filing" as const, form: f.form, title: f.title, detail: f.detail || null, url: f.url,
      mine: qty > 0 && (periodic || f.date >= addDays(MOCK_TODAY, -7)), amount_estimate: null, estimated: false, period: null, sources: src,
    }
  })
}

// ── events ───────────────────────────────────────────────
/** 官方公告（示範標題）：重大訊息與證交所新聞。事件的 material_info 和 /news 的重大訊息是同一則（與後端相同） */
const ANNOUNCEMENTS: Record<string, [date: string, category: "material_info" | "exchange_news", title: string][]> = {
  "2330.TW": [
    ["2026-11-11", "material_info", "代子公司 TSMC Arizona 公告取得機器設備"],
    ["2026-10-30", "material_info", "公告本公司董事會決議資本預算案"],
    ["2026-10-21", "exchange_news", "臺灣證券交易所公告 115 年第 4 季臺灣 50 指數成分股定期審核結果"],
  ],
  "6488.TWO": [["2026-11-12", "exchange_news", "證券櫃檯買賣中心公告：環球晶（6488）列為注意股票"]],
}

function announcementsOf(spec: MockInstrumentSpec) {
  if (spec.market === "US") return []
  return ANNOUNCEMENTS[spec.symbol] ?? [["2026-11-05", "material_info", `${spec.name}公告董事會重要決議`] as const]
}

const MOPS_URL = "https://mops.twse.com.tw/mops/#/web/t05st01"
const TWSE_NEWS_URL = "https://www.twse.com.tw/zh/news/newsList.html"

export function buildEvents(spec: MockInstrumentSpec, holding: Holding | undefined, commercial = false): InstrumentEvent[] {
  const out: InstrumentEvent[] = []
  const qty = holding?.quantity ?? 0
  const fx = spec.currency === "USD" ? FX_NOW : 1
  const src = commercial ? [sourceOf(`${tw(spec)}/ex_dividend`)] : DEMO_SRC
  // 美股沒有可商用的股利資料；SEC 申報是真實資料，兩種政策都有
  if (spec.market === "US") out.push(...secFilings(spec, qty))
  if (commercial && spec.market === "US") return out.sort((a, b) => b.date.localeCompare(a.date))
  for (const d of dividendRecords(spec)) {
    if (d.ex_dividend_date && d.cash_dividend > 0) {
      const future = d.ex_dividend_date >= MOCK_TODAY
      out.push({
        date: d.ex_dividend_date,
        type: "ex_dividend",
        title: `除息 每股 ${d.cash_dividend} 元`,
        detail: `${d.period} 現金股利`,
        url: null,
        mine: qty > 0 && future,
        amount_estimate: qty > 0 && future ? round(d.cash_dividend * qty * fx, 0) : null,
        estimated: false,
        period: d.period,
        sources: src,
      })
    }
    if (d.payment_date && d.cash_dividend > 0) {
      out.push({ date: d.payment_date, type: "dividend_payment", title: "股利發放", detail: `${d.period} 現金股利入帳`, url: null, mine: false, amount_estimate: null, estimated: false, period: d.period, sources: src })
    }
  }
  if (spec.market !== "US" && spec.type !== "etf") {
    const mops = commercial ? [sourceOf(`${tw(spec)}/material_info`)] : DEMO_SRC
    const rule = ["Forliosa 規則計算"]
    const revenue = monthlyRevenue(spec)
    // 月營收：已公布的用實際日期（月營收資料集第一次出現的日期），還沒公布的用法定期限（每月 10 日，預估）
    for (const [date, period, actual] of [
      ["2026-08-07", "2026-07", true], ["2026-09-09", "2026-08", true], ["2026-10-08", "2026-09", true], ["2026-11-06", "2026-10", true],
      ["2026-12-10", "2026-11", false], ["2027-01-10", "2026-12", false],
    ] as const) {
      const m = Number(period.slice(5))
      const rev = revenue.find((r) => r.period === period)
      out.push({
        date, type: "revenue_release", period, url: actual ? MOPS_URL : null, mine: qty > 0, amount_estimate: null, estimated: !actual,
        title: actual ? `公布 ${m} 月營收` : `${m} 月營收公布期限（預估）`,
        detail: actual && rev ? `${m} 月營收 ${new Intl.NumberFormat("zh-TW").format(rev.revenue)} 千元，年增 ${rev.yoy_pct === null ? "—" : `${(rev.yoy_pct * 100).toFixed(1)}%`}` : actual ? null : "尚未偵測到實際公布日：每月 10 日前公布上個月營收（法定期限）",
        sources: actual ? mops : rule,
      })
    }
    // 財報：董事會通過財報的重大訊息日期；還沒公布的季報用法定期限
    for (const [date, period, actual] of [["2026-05-14", "2026Q1", true], ["2026-08-13", "2026Q2", true], ["2026-11-11", "2026Q3", true]] as const) {
      out.push({
        date, type: "earnings", period, url: actual ? MOPS_URL : null, mine: qty > 0, amount_estimate: null, estimated: !actual,
        title: `${period} 財報`, detail: "董事會通過財務報告（重大訊息）", sources: mops,
      })
    }
    // 法說會：重大訊息第 12 款，日期是開會當天
    for (const [date, period] of [["2026-07-16", "2026Q2"], ["2026-10-16", "2026Q3"], ["2027-01-15", "2026Q4"]] as const) {
      out.push({ date, type: "investor_conference", period, url: MOPS_URL, mine: qty > 0, amount_estimate: null, estimated: false, title: `${period} 法說會`, detail: "法人說明會（簡報與影音見公開資訊觀測站）", sources: mops })
    }
    out.push({ date: "2026-06-03", type: "shareholder_meeting", title: "股東常會", detail: null, url: null, mine: false, amount_estimate: null, estimated: false, period: null, sources: mops })
    for (const [date, category, title] of announcementsOf(spec)) {
      if (category === "material_info") out.push({ date, type: "material_info", title, detail: null, url: null, mine: false, amount_estimate: null, estimated: false, period: null, sources: mops })
    }
  }
  if (spec.symbol === "6488.TWO") {
    out.push({ date: MOCK_TODAY, type: "attention", title: "列為注意股票", detail: "近 6 日累積跌幅過大", url: null, mine: qty > 0, amount_estimate: null, estimated: false, period: null, sources: commercial ? [sourceOf("tpex-openapi/attention")] : DEMO_SRC })
  }
  return out.sort((a, b) => b.date.localeCompare(a.date))
}

// ── news：官方公告（重大訊息、證交所新聞），再加新聞報導（媒體原標題＋媒體＋時間＋原文連結） ─────────────
// 示範標題：虛構的媒體（名稱都有「示範」）、中性的標題、連到 example.com——不掛真實媒體的名字，
// 也不寫人事、個資、訴訟這類敏感事件（真實的標題只會來自後端的新聞 worker）。
// [標題, 媒體, 網址, 幾小時前, 收集方式, 只有日期]
type MockMedia = [title: string, outlet: string, url: string, hoursAgo: number, source?: "GDELT" | "SearXNG" | "AI 搜尋" | "Yahoo股市", dateOnly?: boolean]
const DEMO_NEWS_URL = "https://example.com/demo-news"
const MEDIA: Record<string, MockMedia[]> = {
  "2330.TW": [
    ["台積電先進封裝產能擴充 示範新聞標題", "示範財經日報", `${DEMO_NEWS_URL}/2330-1`, 1],
    ["台積電海外新廠進度說明 示範新聞標題", "示範新聞網", `${DEMO_NEWS_URL}/2330-2`, 2],
    ["法人看半導體供應鏈 台積電列觀察名單（示範）", "示範商業時報", `${DEMO_NEWS_URL}/2330-3`, 3],
    ["台積電月營收公布 市場關注年增率（示範）", "示範晚報", `${DEMO_NEWS_URL}/2330-4`, 5, "SearXNG"],
    ["晶圓代工產業動態整理：台積電篇（示範）", "示範產業週刊", `${DEMO_NEWS_URL}/2330-5`, 6],
    ["AI 伺服器需求與台積電資本支出（示範）", "示範新聞網", `${DEMO_NEWS_URL}/2330-6`, 9],
    ["台積電董事會例行會議 示範新聞標題", "示範財經日報", `${DEMO_NEWS_URL}/2330-7`, 20],
    ["半導體設備交期與台積電供應鏈（示範）", "示範電子報", `${DEMO_NEWS_URL}/2330-8`, 26, "SearXNG"],
    ["台積電先進製程時程整理（示範）", "示範科技新聞", `${DEMO_NEWS_URL}/2330-9`, 30],
    ["台積電歐洲廠進度與車用晶片需求（示範）", "示範商業時報", `${DEMO_NEWS_URL}/2330-10`, 44],
    ["TSMC capex outlook: a sample headline", "Demo Markets Daily", `${DEMO_NEWS_URL}/2330-11`, 52],
    ["台積電 ADR 與台股期貨夜盤（示範）", "示範財經網", `${DEMO_NEWS_URL}/2330-12`, 70, "AI 搜尋", true],
  ],
  "2454.TW": [
    ["聯發科新晶片出貨展望（示範）", "示範財經日報", `${DEMO_NEWS_URL}/2454-1`, 4],
    ["聯發科車用晶片布局整理（示範）", "示範新聞網", `${DEMO_NEWS_URL}/2454-2`, 30, "SearXNG"],
  ],
  "6488.TWO": [
    ["環球晶海外新廠進度（示範）", "示範商業時報", `${DEMO_NEWS_URL}/6488-1`, 7],
    ["矽晶圓庫存與報價動態（示範）", "示範財經網", `${DEMO_NEWS_URL}/6488-2`, 50, "AI 搜尋", true],
  ],
  NVDA: [
    ["Nvidia earnings preview: a sample headline", "Demo Markets Daily", `${DEMO_NEWS_URL}/nvda-1`, 2],
    ["AI chip demand and Nvidia's data center sales (sample)", "Demo Tech Wire", `${DEMO_NEWS_URL}/nvda-2`, 6],
    ["What analysts watch in Nvidia's guidance (sample)", "Demo Business Review", `${DEMO_NEWS_URL}/nvda-3`, 18],
    ["輝達財報前 台廠供應鏈動態（示範）", "示範財經日報", `${DEMO_NEWS_URL}/nvda-4`, 28],
  ],
}
/** personal 模式另有 Yahoo股市 RSS（條款限非商用）：保留「Yahoo股市」與原始媒體 */
const MEDIA_PERSONAL: Record<string, MockMedia[]> = {
  "2330.TW": [["台積電相關新聞（Yahoo股市 RSS 示範）", "示範財經網", `${DEMO_NEWS_URL}/yahoo-2330-1`, 4, "Yahoo股市"]],
}

const MEDIA_SOURCE: Record<string, string> = { GDELT: GDELT_ATTRIBUTION, SearXNG: SEARXNG_ATTRIBUTION, "AI 搜尋": AI_SEARCH_ATTRIBUTION, Yahoo股市: YAHOO_RSS_ATTRIBUTION }

function mediaOf(spec: MockInstrumentSpec, commercial: boolean): NewsItem[] {
  const rows = [...(MEDIA[spec.symbol] ?? []), ...(commercial ? [] : (MEDIA_PERSONAL[spec.symbol] ?? []))]
  return rows.map(([title, outlet, url, hoursAgo, source = "GDELT", dateOnly = false]) => {
    // 和後端一樣用台北時間（+08:00）；只有日期的是當天 00:00
    const local = new Date(Date.parse(MOCK_AS_OF) - hoursAgo * 3_600_000 + 8 * 3_600_000).toISOString().slice(0, 19)
    return {
      published_at: `${dateOnly ? `${local.slice(0, 10)}T00:00:00` : local}+08:00`,
      title,
      source,
      outlet,
      url,
      category: "media" as const,
      date_only: dateOnly,
      sources: [MEDIA_SOURCE[source]!],
    }
  })
}

export function buildNews(spec: MockInstrumentSpec, commercial = false): NewsItem[] {
  const official: NewsItem[] = announcementsOf(spec).map(([date, category, title], i) => ({
    published_at: `${date}T${category === "material_info" ? `17:${String(30 - i * 7).padStart(2, "0")}:00` : "00:00:00"}+08:00`,
    title,
    source: "公告",
    outlet: null,
    url: category === "material_info" ? MOPS_URL : TWSE_NEWS_URL,
    category,
    date_only: false,
    sources: commercial
      ? [sourceOf(category === "material_info" ? `${tw(spec)}/material_info` : "twse-openapi/news")]
      : DEMO_SRC,
  }))
  official.sort((a, b) => b.published_at.localeCompare(a.published_at))
  const media = mediaOf(spec, commercial).sort((a, b) => b.published_at.localeCompare(a.published_at))
  // 與後端相同：先列官方公告，再列新聞報導
  return [...official, ...media]
}

// ── position ─────────────────────────────────────────────
export function buildPosition(spec: MockInstrumentSpec, txns: Transaction[], commercial = false): Position | null {
  const holding = buildHoldings(txns, undefined, commercial).find((h) => h.symbol === spec.symbol)
  if (!holding) return null
  const mine = txns.filter((t) => t.symbol === spec.symbol)
  const state = replay(mine)
  const markers: PositionMarker[] = mine
    .filter((t) => ["buy", "sell", "cash_dividend", "stock_dividend"].includes(t.type))
    .map((t) => ({
      date: t.trade_date,
      type: t.type === "cash_dividend" ? "dividend" : (t.type as PositionMarker["type"]),
      quantity: t.quantity,
      price: t.price,
      amount: t.amount,
    }))
  const fx = spec.currency === "USD" ? FX_NOW : 1
  const next = dividendRecords(spec)
    .filter((d) => d.ex_dividend_date && d.ex_dividend_date >= MOCK_TODAY && d.cash_dividend > 0)
    .sort((a, b) => a.ex_dividend_date!.localeCompare(b.ex_dividend_date!))[0]
  return {
    quantity: holding.quantity,
    avg_cost: holding.avg_cost,
    cost_basis: holding.cost_basis,
    market_value: holding.market_value,
    unrealized_pnl: holding.unrealized_pnl,
    unrealized_pnl_pct: holding.unrealized_pnl_pct,
    realized_pnl: round(state.realizedTwd),
    dividends_received: round(state.dividendsTwd),
    day_change: holding.day_change,
    markers,
    upcoming_dividend: next && !(commercial && spec.market === "US") ? { ex_dividend_date: next.ex_dividend_date!, amount_estimate: round(next.cash_dividend * holding.quantity * fx, 0) } : null,
    currency: spec.currency,
    as_of: MOCK_AS_OF,
    // 美股的台幣金額用到匯率：後端一併列出匯率資料集的顯名聲明（商用模式是中央銀行的收盤匯率）
    sources: ["本系統帳本", ...(spec.currency === "USD" ? [commercial ? sourceOf("cbc-opendata/fx") : "示範資料（模擬）"] : [])],
    is_demo: !commercial,
  }
}

// ── why（規則判斷，M4 前用模板句） ─────────────────────────
export function buildWhy(spec: MockInstrumentSpec): Why {
  const candles = dailyCandles(spec)
  const last = candles.at(-1)!
  const prior = candles.slice(-21, -1)
  const avgVol = prior.reduce((s, c) => s + c.v, 0) / Math.max(prior.length, 1)
  const ref = referencePrice(spec)
  const pct = spec.price / ref - 1
  const reasons: WhyReason[] = []
  const pctText = `${pct > 0 ? "▲" : "▼"}${Math.abs(pct * 100).toFixed(2)}%`
  if (Math.abs(pct) >= 0.03) reasons.push({ kind: "price_move", text: `今天${pct > 0 ? "上漲" : "下跌"} ${pctText}，超過 ±3%` })
  const volRatio = last.v / avgVol
  if (volRatio >= 2 || (spec.symbol === "2330.TW" && Math.abs(pct) >= 0.03)) {
    reasons.push({ kind: "volume", text: `成交量是近 20 日均量的 ${Math.max(volRatio, 2.1).toFixed(1)} 倍` })
  }
  const limits = limitsOf(spec)
  if (limits && spec.price >= limits.up) reasons.push({ kind: "limit_up", text: "收在漲停" })
  if (limits && spec.price <= limits.down) reasons.push({ kind: "limit_down", text: "收在跌停" })
  if (spec.symbol === "6488.TWO") reasons.push({ kind: "attention", text: "今天列為注意股票（近 6 日累積跌幅過大）" })
  if (spec.symbol === "2330.TW" && reasons.length > 0) reasons.push({ kind: "sector", text: "半導體類股同步上漲" })
  const show = reasons.some((x) => x.kind !== "sector")
  return {
    show,
    headline: show ? reasons.filter((x) => x.kind !== "price_move").map((x) => x.text).slice(0, 2).join("，") || reasons[0]!.text : null,
    reasons: show ? reasons : [],
    as_of: MOCK_AS_OF,
  }
}

// ── 本週事項 ─────────────────────────────────────────────
/** 除息、股利入帳（持股）＋定期定額扣款（由計畫算出，見 recurring.ts） */
export function buildUpcoming(holdings: Holding[], specOf: (s: string) => MockInstrumentSpec | undefined, days = 7, recurring: UpcomingItem[] = [], commercial = false): UpcomingItem[] {
  const end = addDays(MOCK_TODAY, days)
  const out: UpcomingItem[] = []
  for (const h of holdings) {
    const spec = specOf(h.symbol)
    if (!spec) continue
    if (commercial && spec.market === "US") continue
    const fx = h.currency === "USD" ? FX_NOW : 1
    const src = commercial ? [sourceOf(`${tw(spec)}/ex_dividend`)] : DEMO_SRC
    for (const d of dividendRecords(spec)) {
      if (d.cash_dividend <= 0) continue
      if (d.ex_dividend_date && d.ex_dividend_date >= MOCK_TODAY && d.ex_dividend_date <= end) {
        out.push({ date: d.ex_dividend_date, type: "ex_dividend", symbol: h.symbol, title: `${h.code} 除息`, amount_estimate: round(d.cash_dividend * h.quantity * fx, 0), is_demo: !commercial, sources: src })
      }
      if (d.payment_date && d.payment_date > MOCK_TODAY && d.payment_date <= end && d.ex_dividend_date && d.ex_dividend_date < MOCK_TODAY) {
        out.push({ date: d.payment_date, type: "dividend_payment", title: `${h.code} 股利入帳`, symbol: h.symbol, amount_estimate: round(d.cash_dividend * h.quantity * fx * (h.currency === "USD" ? 0.7 : 1), 0), is_demo: !commercial, sources: src })
      }
    }
  }
  out.push(...recurring.filter((r) => r.date >= MOCK_TODAY && r.date <= end))
  return out.sort((a, b) => a.date.localeCompare(b.date))
}
