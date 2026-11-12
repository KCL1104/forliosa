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
import type { MockInstrumentSpec } from "./instruments"
import { buildHoldings, replay } from "./ledger"
import { addDays, dailyCandles, dividendRecords, FX_NOW, MOCK_AS_OF, MOCK_TODAY, monthlyRevenue, rng, tradingDays } from "./market"

const DEMO_SRC = ["示範資料（模擬數字，不代表真實行情）"]
const round = (n: number, d = 2) => Math.round(n * 10 ** d) / 10 ** d

export function referencePrice(spec: MockInstrumentSpec): number {
  return spec.prev_close
}

export function limitsOf(spec: MockInstrumentSpec) {
  return limitPrices(referencePrice(spec), spec.market, spec.type)
}

// ── overview ─────────────────────────────────────────────
export function buildOverview(spec: MockInstrumentSpec): InstrumentOverview {
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
      note: spec.symbol === "6488.TWO" ? "近 6 日累積跌幅過大，列為注意股票（示範）" : null,
    },
    as_of: spec.market === "US" ? "2026-11-12T05:00:00+08:00" : MOCK_AS_OF,
    sources: spec.data_sources,
    is_demo: true,
  }
}

// ── intraday（只有持股與自選有點） ────────────────────────
function minuteLabels(): string[] {
  const out: string[] = []
  for (let m = 9 * 60 + 1; m <= 13 * 60 + 30; m++) out.push(`${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`)
  return out
}

export function buildIntraday(spec: MockInstrumentSpec, tracked: boolean): Intraday {
  const base: Intraday = {
    symbol: spec.symbol,
    date: MOCK_TODAY,
    prev_close: spec.prev_close,
    reference_price: referencePrice(spec),
    points: [],
    is_partial: false,
    sources: DEMO_SRC,
    is_demo: true,
  }
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

export function buildChips(spec: MockInstrumentSpec, range: ChipsRange = "3M"): Chips {
  if (spec.market === "US") {
    return { institutional: [], margin: [], foreign_holding_pct: [], major_holders: null, sources: DEMO_SRC, is_demo: true }
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
    institutional,
    margin: marginRows,
    foreign_holding_pct: foreignPct,
    major_holders: {
      as_of: "2026-11-06",
      buckets: buckets.map((b, i) => ({ level: b.level, holders: Math.round(holders[i]! * (shares / 25_932_666_666) ** 0.5), shares: Math.round(shares * b.pct), pct: round(b.pct, 4) })),
    },
    sources: ["臺灣證券交易所 OpenAPI（三大法人、融資融券）", "集保結算所（股權分散表，每週）", ...DEMO_SRC],
    is_demo: true,
  }
}

// ── financials（季報／年報） ─────────────────────────────
export function buildFinancials(spec: MockInstrumentSpec, period: FinancialsPeriod = "quarterly"): Financials {
  const empty: Financials = {
    periods: [],
    income: { revenue: [], gross_profit: [], operating_income: [], net_income: [], eps: [] },
    balance: { total_assets: [], total_liabilities: [], equity: [] },
    cashflow: { operating: [], investing: [], financing: [], free_cash_flow: [] },
    margins: { gross: [], operating: [], net: [] },
    sources: DEMO_SRC,
    is_demo: true,
  }
  if (spec.market === "US" || spec.type === "etf" || !spec.revenue_base || !spec.eps_now) return empty
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

// ── events ───────────────────────────────────────────────
export function buildEvents(spec: MockInstrumentSpec, holding: Holding | undefined): InstrumentEvent[] {
  const out: InstrumentEvent[] = []
  const qty = holding?.quantity ?? 0
  const fx = spec.currency === "USD" ? FX_NOW : 1
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
      })
    }
    if (d.payment_date && d.cash_dividend > 0) {
      out.push({ date: d.payment_date, type: "dividend_payment", title: "股利發放", detail: `${d.period} 現金股利入帳`, url: null, mine: false, amount_estimate: null })
    }
  }
  if (spec.market !== "US" && spec.type !== "etf") {
    for (const m of ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]) {
      const date = `${m}-10`
      const prev = Number(m.slice(5)) - 1
      out.push({ date, type: "revenue_release", title: `公布 ${prev} 月營收`, detail: null, url: "https://mops.twse.com.tw/", mine: false, amount_estimate: null })
    }
    for (const [date, q] of [["2026-01-15", "2025Q4"], ["2026-04-16", "2026Q1"], ["2026-07-16", "2026Q2"], ["2026-10-15", "2026Q3"], ["2027-01-14", "2026Q4"]] as const) {
      out.push({ date, type: "earnings", title: `${q} 法說會`, detail: "法說會簡報與影音（公開資訊觀測站）", url: "https://mops.twse.com.tw/", mine: false, amount_estimate: null })
    }
    out.push({ date: "2026-06-03", type: "shareholder_meeting", title: "股東常會", detail: null, url: null, mine: false, amount_estimate: null })
    out.push({ date: "2026-08-12", type: "material_info", title: "董事會決議季配息", detail: "重大訊息（示範）", url: "https://mops.twse.com.tw/", mine: false, amount_estimate: null })
  }
  if (spec.symbol === "6488.TWO") {
    out.push({ date: MOCK_TODAY, type: "attention", title: "列為注意股票", detail: "近 6 日累積跌幅過大（示範）", url: null, mine: qty > 0, amount_estimate: null })
  }
  return out.sort((a, b) => b.date.localeCompare(a.date))
}

// ── news（只有標題、來源、連結） ─────────────────────────
const NEWS: Record<string, [string, string, number][]> = {
  "2330.TW": [
    ["台積電先進封裝擴產，CoWoS 月產能明年再增五成", "鉅亨網", 2],
    ["外資連四賣台積電，法人：短線調節不改長線趨勢", "經濟日報", 5],
    ["台積電 10 月營收年增 21%，創同期新高", "工商時報", 30],
    ["半導體設備交期縮短，晶圓代工資本支出維持高檔", "MoneyDJ", 50],
  ],
  "0050.TW": [["元大台灣50 規模創新高，受益人數持續成長", "經濟日報", 8]],
  "00878.TW": [["國泰永續高股息 11 月除息，預估配發 0.55 元", "鉅亨網", 20]],
}

export function buildNews(spec: MockInstrumentSpec): NewsItem[] {
  const rows = NEWS[spec.symbol] ?? [[`${spec.name}公布最新營運概況`, "鉅亨網", 26]]
  return rows.map(([title, source, hoursAgo]) => ({
    published_at: new Date(Date.parse(MOCK_AS_OF) - hoursAgo * 3_600_000 + 90 * 60_000).toISOString(),
    title,
    source,
    url: `https://www.google.com/search?q=${encodeURIComponent(title)}`,
  }))
}

// ── position ─────────────────────────────────────────────
export function buildPosition(spec: MockInstrumentSpec, txns: Transaction[]): Position | null {
  const holding = buildHoldings(txns).find((h) => h.symbol === spec.symbol)
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
    upcoming_dividend: next ? { ex_dividend_date: next.ex_dividend_date!, amount_estimate: round(next.cash_dividend * holding.quantity * fx, 0) } : null,
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
  if (Math.abs(pct) >= 0.03) reasons.push({ kind: "move", text: `今天${pct > 0 ? "上漲" : "下跌"} ${pctText}，超過 ±3%` })
  const volRatio = last.v / avgVol
  if (volRatio >= 2 || (spec.symbol === "2330.TW" && Math.abs(pct) >= 0.03)) {
    reasons.push({ kind: "volume", text: `成交量是近 20 日均量的 ${Math.max(volRatio, 2.1).toFixed(1)} 倍` })
  }
  const limits = limitsOf(spec)
  if (limits && spec.price >= limits.up) reasons.push({ kind: "limit", text: "收在漲停" })
  if (limits && spec.price <= limits.down) reasons.push({ kind: "limit", text: "收在跌停" })
  if (spec.symbol === "6488.TWO") reasons.push({ kind: "attention", text: "今天列為注意股票（近 6 日累積跌幅過大）" })
  if (spec.symbol === "2330.TW" && reasons.length > 0) reasons.push({ kind: "sector", text: "半導體類股同步上漲，投信連 5 天買超" })
  const show = reasons.some((x) => x.kind !== "sector")
  return {
    show,
    headline: show ? reasons.filter((x) => x.kind !== "move").map((x) => x.text).slice(0, 2).join("，") || reasons[0]!.text : null,
    reasons: show ? reasons : [],
    as_of: MOCK_AS_OF,
  }
}

// ── 本週事項 ─────────────────────────────────────────────
export function buildUpcoming(holdings: Holding[], specOf: (s: string) => MockInstrumentSpec | undefined, days = 7): UpcomingItem[] {
  const end = addDays(MOCK_TODAY, days)
  const out: UpcomingItem[] = []
  for (const h of holdings) {
    const spec = specOf(h.symbol)
    if (!spec) continue
    const fx = h.currency === "USD" ? FX_NOW : 1
    for (const d of dividendRecords(spec)) {
      if (d.cash_dividend <= 0) continue
      if (d.ex_dividend_date && d.ex_dividend_date >= MOCK_TODAY && d.ex_dividend_date <= end) {
        out.push({ date: d.ex_dividend_date, type: "ex_dividend", symbol: h.symbol, title: `${h.code} 除息`, amount_estimate: round(d.cash_dividend * h.quantity * fx, 0) })
      }
      if (d.payment_date && d.payment_date > MOCK_TODAY && d.payment_date <= end && d.ex_dividend_date && d.ex_dividend_date < MOCK_TODAY) {
        out.push({ date: d.payment_date, type: "dividend_payment", title: `${h.code} 股利入帳`, symbol: h.symbol, amount_estimate: round(d.cash_dividend * h.quantity * fx * (h.currency === "USD" ? 0.7 : 1), 0) })
      }
    }
  }
  // 定期定額（示範：0050 每月 6 日、00878 每月 26 日）
  for (const [symbol, code, day, amount] of [["0050.TW", "0050", 6, 10_000], ["00878.TW", "00878", 26, 8_000]] as const) {
    for (const month of [MOCK_TODAY.slice(0, 7), addDays(`${MOCK_TODAY.slice(0, 7)}-28`, 5).slice(0, 7)]) {
      const date = `${month}-${String(day).padStart(2, "0")}`
      if (date > MOCK_TODAY && date <= end && holdings.some((h) => h.symbol === symbol)) {
        out.push({ date, type: "recurring", symbol, title: `${code} 定期定額扣款`, amount_estimate: amount })
      }
    }
  }
  return out.sort((a, b) => a.date.localeCompare(b.date))
}
