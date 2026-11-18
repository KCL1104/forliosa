import type { Account, AllocationGroupSlice, AllocationGrouping, AllocationLimits, AllocationSlice, Concentration, Holding, OverLimit } from "../types"

/**
 * 持倉配置的 mock（和後端 `services/allocation.py` 同一套規則，見 docs/api-contract.md「持倉配置」）：
 * - 產業：台股個股用官方產業別；美股 12 類（示範只有新聞對照表裡的大型公司，SEC 代號表的美股沒有 SIC → 未分類）；
 *   ETF 分類別、不看穿成分股；判斷不了的是「未分類」。
 * - 集中度只寫事實；上限是使用者自己設的（系統沒有預設門檻），單一個股上限只看個股、單一產業上限不算 ETF 與未分類。
 */

export const ETF_CLASSES: Record<string, string> = {
  etf_tw_equity: "國內股票型 ETF",
  etf_foreign_equity: "海外股票型 ETF",
  etf_bond: "債券 ETF",
  etf_leveraged: "槓桿／反向 ETF",
  etf_active: "主動式 ETF",
  etf_futures: "期貨 ETF",
  etf_balanced: "平衡型 ETF",
  etf_other: "ETF（未分類）",
}
const US_SECTORS: Record<string, string> = {
  us_semis: "美股半導體",
  us_tech: "美股科技",
  us_comm: "美股通訊服務",
  us_consumer_disc: "美股非必需消費",
  us_staples: "美股必需消費",
  us_health: "美股醫療保健",
  us_financials: "美股金融",
  us_industrials: "美股工業",
  us_energy: "美股能源",
  us_materials: "美股原物料",
  us_utilities: "美股公用事業",
  us_real_estate: "美股房地產",
}
/** 新聞類股的對照表（後端 `news.taxonomy.US_SECTOR_BY_TICKER` 的一部分） */
const US_SECTOR_BY_TICKER: Record<string, string> = {
  NVDA: "us_semis", AMD: "us_semis", AVGO: "us_semis", MU: "us_semis",
  AAPL: "us_tech", MSFT: "us_tech", ORCL: "us_tech",
  GOOGL: "us_comm", META: "us_comm", NFLX: "us_comm",
  AMZN: "us_consumer_disc", TSLA: "us_consumer_disc",
  WMT: "us_staples", COST: "us_staples", KO: "us_staples",
}
/** 內建的美股 ETF（海外股票型）與台股 ETF（國內股票型） */
const US_ETF_CODES = new Set(["VOO", "QQQ", "SPY", "DIA", "ONEQ", "SMH"])
const TW_BUILTIN_ETFS = new Set(["0050", "0056", "00878", "006208", "00919", "00929", "00713"])

export const UNCLASSIFIED = "unclassified"
const MARKET_LABELS: Record<string, string> = { TWSE: "上市", TPEX: "上櫃", US: "美股" }
const CURRENCY_LABELS: Record<string, string> = { TWD: "新台幣", USD: "美元" }
const TYPE_LABELS: Record<string, string> = { stock: "股票", etf: "ETF" }

export interface Klass {
  type: "stock" | "etf"
  industry: string
  label: string
}

/** 台股 ETF：代號字尾先（L、R 槓桿反向；U 期貨；B、D 債券；T 平衡；A 主動），再看基金類型（示範：上市的算國內股票型） */
export function twEtfClass(code: string, market: string): string {
  const c = code.toUpperCase()
  const letter = /[A-Z]$/.test(c) ? c.at(-1)! : ""
  if (letter === "L" || letter === "R") return "etf_leveraged"
  if (letter === "U") return "etf_futures"
  if (letter === "B" || letter === "D") return "etf_bond"
  if (letter === "T") return "etf_balanced"
  if (letter === "A") return "etf_active"
  if (TW_BUILTIN_ETFS.has(c) || market === "TWSE") return "etf_tw_equity"
  return "etf_other"
}

export function classify(h: Pick<Holding, "code" | "market" | "type" | "industry" | "name">): Klass {
  const etf = (key: string): Klass => ({ type: "etf", industry: key, label: ETF_CLASSES[key]! })
  if (h.market === "US") {
    if (h.type === "etf") {
      if (/\b(?:ULTRAPRO|ULTRASHORT|[1-3]X|LEVERAGED|INVERSE)\b/i.test(h.name)) return etf("etf_leveraged")
      if (/\b(?:BONDS?|TREASURY|TREASURIES)\b/i.test(h.name)) return etf("etf_bond")
      return etf(US_ETF_CODES.has(h.code) ? "etf_foreign_equity" : "etf_other")
    }
    const sector = US_SECTOR_BY_TICKER[h.code.toUpperCase()]
    return sector ? { type: "stock", industry: sector, label: US_SECTORS[sector]! } : { type: "stock", industry: UNCLASSIFIED, label: "未分類" }
  }
  if (h.type === "etf") return etf(twEtfClass(h.code, h.market))
  return h.industry && h.industry !== "ETF" ? { type: "stock", industry: h.industry, label: h.industry } : { type: "stock", industry: UNCLASSIFIED, label: "未分類" }
}

const r2 = (n: number) => Math.round(n * 100) / 100
const r4 = (n: number) => Math.round(n * 10000) / 10000

type Members = Map<string, Map<string, number>>

function add(m: Members, key: string, symbol: string, v: number) {
  const inner = m.get(key) ?? new Map<string, number>()
  inner.set(symbol, (inner.get(symbol) ?? 0) + v)
  m.set(key, inner)
}

function slices(m: Members, label: (k: string) => string, total: number, isEtf: (k: string) => boolean): AllocationGroupSlice[] {
  return [...m.entries()]
    .map(([key, inner]) => {
      const value = [...inner.values()].reduce((a, b) => a + b, 0)
      return {
        key,
        label: label(key),
        value: r2(value),
        weight: total ? r4(value / total) : 0,
        is_etf: isEtf(key),
        symbols: [...inner.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([s]) => s),
        raw: value,
      }
    })
    .sort((a, b) => b.raw - a.raw || a.key.localeCompare(b.key))
    .map(({ raw: _raw, ...s }) => s)
}

/**
 * 六種分組＋集中度。`holdings`：這次範圍裡的持股（和 `GET /portfolio/holdings` 同一批）；
 * `byAccount`：每一檔在每個帳戶的市值（帳戶那一組用）；`accounts`：帳戶名稱。
 */
export function allocationOf(
  holdings: Holding[],
  byAccount: Map<string, Map<string, number>>,
  accounts: Account[],
  limits: AllocationLimits,
): { groups: Record<AllocationGrouping, AllocationGroupSlice[]>; concentration: Concentration; total: number } {
  const total = holdings.reduce((a, h) => a + h.market_value, 0)
  const klass = new Map(holdings.map((h) => [h.symbol, classify(h)]))
  const m: Record<AllocationGrouping, Members> = { holding: new Map(), industry: new Map(), market: new Map(), account: new Map(), currency: new Map(), type: new Map() }
  const industryLabels = new Map<string, string>()
  for (const h of holdings) {
    const k = klass.get(h.symbol)!
    add(m.holding, h.symbol, h.symbol, h.market_value)
    add(m.industry, k.industry, h.symbol, h.market_value)
    industryLabels.set(k.industry, k.label)
    add(m.market, h.market, h.symbol, h.market_value)
    add(m.currency, h.currency, h.symbol, h.market_value)
    add(m.type, k.type, h.symbol, h.market_value)
    for (const [acc, v] of byAccount.get(h.symbol) ?? []) add(m.account, acc, h.symbol, v)
  }
  const names = new Map(holdings.map((h) => [h.symbol, h.name]))
  const accountNames = new Map(accounts.map((a) => [a.id, a.name]))
  const groups: Record<AllocationGrouping, AllocationGroupSlice[]> = {
    holding: slices(m.holding, (k) => names.get(k) ?? k, total, (k) => klass.get(k)?.type === "etf"),
    industry: slices(m.industry, (k) => industryLabels.get(k) ?? k, total, (k) => k in ETF_CLASSES),
    market: slices(m.market, (k) => MARKET_LABELS[k] ?? k, total, () => false),
    account: slices(m.account, (k) => accountNames.get(k) ?? k, total, () => false),
    currency: slices(m.currency, (k) => CURRENCY_LABELS[k] ?? k, total, () => false),
    type: slices(m.type, (k) => TYPE_LABELS[k] ?? k, total, (k) => k === "etf"),
  }

  // 集中度：和後端一樣，比例用沒有四捨五入的數字比
  const ordered = [...holdings].sort((a, b) => b.market_value - a.market_value || a.symbol.localeCompare(b.symbol))
  const ratio = (v: number) => (total ? v / total : 0)
  const sum = (hs: Holding[]) => hs.reduce((a, h) => a + h.market_value, 0)
  const industries = new Map<string, number>()
  let etf = 0
  for (const h of ordered) {
    const k = klass.get(h.symbol)!
    if (k.type === "etf") etf += h.market_value
    else if (k.industry !== UNCLASSIFIED) industries.set(k.industry, (industries.get(k.industry) ?? 0) + h.market_value)
  }
  const ranked = [...industries.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  const over: OverLimit[] = []
  if (limits.holding !== null) {
    for (const h of ordered) {
      const w = ratio(h.market_value)
      if (klass.get(h.symbol)!.type === "stock" && w > limits.holding) over.push({ kind: "holding", key: h.symbol, label: h.name, weight: r4(w), limit: limits.holding })
    }
  }
  if (limits.industry !== null) {
    for (const [key, v] of ranked) {
      const w = ratio(v)
      if (w > limits.industry) over.push({ kind: "industry", key, label: industryLabels.get(key) ?? key, weight: r4(w), limit: limits.industry })
    }
  }
  const top = ordered[0]
  const concentration: Concentration = {
    holdings_count: ordered.length,
    top_holding: top && total ? { symbol: top.symbol, name: top.name, weight: r4(ratio(top.market_value)), is_etf: klass.get(top.symbol)!.type === "etf" } : null,
    top3_weight: r4(ratio(sum(ordered.slice(0, 3)))),
    top5_weight: r4(ratio(sum(ordered.slice(0, 5)))),
    top_industry: ranked[0] && total ? { key: ranked[0][0], label: industryLabels.get(ranked[0][0]) ?? ranked[0][0], weight: r4(ratio(ranked[0][1])) } : null,
    etf_weight: r4(ratio(etf)),
    limits: { ...limits },
    over_limits: over,
  }
  return { groups, concentration, total }
}

/** `/portfolio/summary` 的 `allocation.by_*`：同一套分類，只有 `{key, label, value, weight}` */
export function summaryAllocation(groups: Record<AllocationGrouping, AllocationGroupSlice[]>) {
  const plain = (xs: AllocationGroupSlice[]): AllocationSlice[] => xs.map(({ key, label, value, weight }) => ({ key, label, value, weight }))
  return {
    by_market: plain(groups.market),
    by_industry: plain(groups.industry),
    by_currency: plain(groups.currency),
    by_type: plain(groups.type),
    by_account: plain(groups.account),
  }
}

/** 上限：0.01–1（1%–100%），存到小數第 4 位；null＝不設。超出範圍和後端一樣是 422 */
export function validLimit(v: unknown): v is number | null {
  return v === null || (typeof v === "number" && Number.isFinite(v) && v >= 0.01 && v <= 1)
}
