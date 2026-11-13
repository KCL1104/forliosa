/**
 * 依頁面與資料自動出現的建議問題，以及本機的規則版回答（mock、離線；墨色 Noto Sans，不是模型寫的）。
 * 全部是純函式：只用使用者自己的資料計算，不做投資判斷、不捏造分析。
 * 介面上不加「本頁建議」「依頁面推薦」這類說明字樣（PRODUCT.md）。
 */
import { inText } from "@/lib/cjk"
import type {
  DividendRecord,
  Holding,
  InstrumentOverview,
  InstrumentType,
  Market,
  PortfolioSummary,
  Position,
  Quote,
  Valuation,
  Why,
} from "@/api/types"
import {
  daysBetween,
  directionGlyph,
  direction,
  formatDateShort,
  formatMoney,
  formatPercent,
  formatPrice,
  formatQuantity,
  MASK,
} from "@/lib/format"
import type { Answer, AnswerLink, Suggestion, SuggestionKind } from "./types"

export interface LedgerData {
  holdings: Holding[]
  summary?: PortfolioSummary
}

export interface StockData {
  symbol: string
  code: string
  name: string
  market: Market
  type: InstrumentType
  quote?: Quote
  overview?: InstrumentOverview
  position?: Position | null
  why?: Why
  valuation?: Valuation
  dividends?: DividendRecord[]
}

export type AiContext =
  | { route: "ledger"; ledger: LedgerData }
  | { route: "stock"; stock: StockData }
  | { route: "groups" }
  | { route: "other" }

const MAX = 3

/** 上市股票沒有逐檔三大法人、外資持股只有前 20 名（其他不顯示），外資動向改問 AI：上網搜尋新聞，附來源與日期 */
export const FOREIGN_FLOW_QUESTION = "最近外資對這檔的動向？"
export const isListedStock = (s: Pick<StockData, "market" | "type">) => s.market === "TWSE" && s.type === "stock"

/**
 * 「我的成本在河流圖哪裡」只在畫得出河流圖時問：台股個股、有本益比的倍數帶、現在有本益比。
 * 美股沒有可商用的行情，估值分頁沒有河流圖，不問。
 */
export const hasRiver = (s: Pick<StockData, "market" | "type" | "valuation" | "overview">) =>
  s.type === "stock" && s.market !== "US" && (s.valuation?.per_multiples.length ?? 0) > 0 && s.overview?.pe != null && (s.overview?.eps_ttm ?? 0) > 0

/** 價格與成本永遠帶單位：台股「1,085 元」，美股「US$143.41」（和「2,000 股」同一套，值後面接單位） */
export function priceText(p: number, market: Market): string {
  return market === "US" ? `US$${formatPrice(p, market)}` : `${formatPrice(p, market)} 元`
}

/** 單一持股權重門檻、前三大合計門檻、單一產業門檻：任一超過就出現「會不會太集中」 */
export const CONCENTRATION = { single: 0.15, top3: 0.45, industry: 0.4 } as const

export function concentrationStats(holdings: Holding[], summary?: PortfolioSummary) {
  const sorted = [...holdings].sort((a, b) => b.weight - a.weight)
  const top = sorted[0]
  const top3 = sorted.slice(0, 3).reduce((s, h) => s + h.weight, 0)
  const industry = summary?.allocation.by_industry.filter((s) => s.key !== "ETF")[0] ?? null
  return { top, top3, industry }
}

export function isConcentrated(holdings: Holding[], summary?: PortfolioSummary): boolean {
  const { top, top3, industry } = concentrationStats(holdings, summary)
  return (top?.weight ?? 0) >= CONCENTRATION.single || top3 >= CONCENTRATION.top3 || (industry?.weight ?? 0) >= CONCENTRATION.industry
}

export function ledgerSuggestions({ holdings, summary }: LedgerData, today: string): Suggestion[] {
  if (holdings.length === 0) {
    return [{ kind: "onboard", text: "怎麼用一句話記帳？" }]
  }
  const out: Suggestion[] = []
  if (holdings.some((h) => h.day_change < 0)) out.push({ kind: "drag", text: "今天誰拖累了我的報酬？" })
  else if (holdings.some((h) => h.day_change > 0)) out.push({ kind: "lift", text: "今天誰幫我賺最多？" })
  const soon = (summary?.upcoming_dividends ?? []).filter((d) => daysBetween(today, d.ex_dividend_date) <= 31)
  if (soon.length > 0) out.push({ kind: "dividends_next", text: "下個月我能領多少股利？" })
  if (isConcentrated(holdings, summary)) out.push({ kind: "concentration", text: "我的持股會不會太集中？" })
  return out.slice(0, MAX)
}

export function stockSuggestions(s: StockData, today: string): Suggestion[] {
  const out: Suggestion[] = []
  const pct = s.quote?.change_pct ?? null
  const held = !!s.position
  if (s.why?.show) {
    const d = direction(pct)
    out.push({ kind: "why_move", symbol: s.symbol, text: `${inText(s.name, "start")}今天為什麼${d === "down" ? "跌" : "漲"}？` })
  }
  if (isListedStock(s)) out.push({ kind: "foreign_flow", symbol: s.symbol, text: FOREIGN_FLOW_QUESTION })
  if (held) {
    const next = s.position?.upcoming_dividend
    if (next && daysBetween(today, next.ex_dividend_date) <= 31) out.push({ kind: "next_dividend", symbol: s.symbol, text: "這次除息我可以領多少？" })
    if (hasRiver(s)) out.push({ kind: "cost_on_river", symbol: s.symbol, text: "我的成本在河流圖哪裡？" })
    if (s.market !== "US") out.push({ kind: "add_one_lot", symbol: s.symbol, text: "加碼 1 張，均價會變多少？" })
  } else {
    if (s.type === "stock" && (s.overview?.pe ?? null) !== null) out.push({ kind: "is_expensive", symbol: s.symbol, text: "現在的本益比算貴嗎？" })
    if ((s.overview?.last_cash_dividend ?? 0) > 0) out.push({ kind: "if_hold_dividend", symbol: s.symbol, text: "持有 1 張一年能領多少股利？" })
  }
  return out.slice(0, MAX)
}

export function suggestionsFor(ctx: AiContext, today: string): Suggestion[] {
  if (ctx.route === "ledger") return ledgerSuggestions(ctx.ledger, today)
  if (ctx.route === "stock") return stockSuggestions(ctx.stock, today)
  if (ctx.route === "groups") return [{ kind: "group_share", text: "群組會分享我的哪些資料？" }]
  return []
}

// ── 問題分類：把自由輸入對到可以用資料回答的題目 ─────────────────────
export function classifyQuestion(text: string, ctx: AiContext): SuggestionKind | null {
  const t = text.replace(/\s/g, "")
  if (ctx.route === "stock") {
    if (/(為什麼|為何|原因).*(漲|跌)|怎麼(漲|跌)/.test(t)) return "why_move"
    if (isListedStock(ctx.stock) && /(外資|法人|投信|自營商)/.test(t) && /(動向|買|賣|進出|布局|佈局|調節|持股)/.test(t)) return "foreign_flow"
    if (/(加碼|攤平|均價)/.test(t) && ctx.stock.position) return "add_one_lot"
    if (/(成本).*(河流|本益比|位置)/.test(t) && ctx.stock.position) return "cost_on_river"
    if (/(除息|股利|配息).*(領|多少)/.test(t)) return ctx.stock.position ? "next_dividend" : "if_hold_dividend"
    if (/(貴|便宜|本益比|估值)/.test(t)) return "is_expensive"
  }
  if (ctx.route === "ledger") {
    if (/(拖累|誰.*跌|虧最多|賠最多)/.test(t)) return "drag"
    if (/(賺最多|誰.*漲|貢獻)/.test(t)) return "lift"
    if (/(股利|配息|除息).*(多少|領)/.test(t)) return "dividends_next"
    if (/(集中|分散|比重|佔比)/.test(t)) return "concentration"
    if (/(怎麼|如何).*(記帳|開始|記一筆)/.test(t)) return "onboard"
  }
  if (/(群組|分享)/.test(t)) return "group_share"
  return null
}

// ── 回答 ───────────────────────────────────────────────
const money = (n: number, privacy: boolean, signed = false) => (privacy ? MASK : formatMoney(n, { signed }))
/** 數字列（漲跌色）裡的百分比：▲4.83%／▼1.85% */
const pctGlyph = (r: number | null | undefined) => {
  const d = direction(r)
  return `${directionGlyph(d)}${formatPercent(r === null || r === undefined ? r : Math.abs(r), { signed: false })}`
}
/** 句子裡的漲跌用字：「上漲 4.83%」「下跌 1.85%」「平盤」；▲▼ 與漲跌色只放在數字列 */
const pctWords = (r: number | null | undefined) => {
  if (r === null || r === undefined || Number.isNaN(r)) return "—"
  const d = direction(r)
  if (d === "flat") return "平盤"
  return `${d === "up" ? "上漲" : "下跌"} ${formatPercent(Math.abs(r), { signed: false })}`
}

export interface AnswerInput {
  ctx: AiContext
  privacy: boolean
  today: string
  asOf?: string | null
}

export function answerFor(kind: SuggestionKind, { ctx, privacy, today, asOf }: AnswerInput): Answer | null {
  if (ctx.route === "ledger") return ledgerAnswer(kind, ctx.ledger, privacy, today, asOf ?? ctx.ledger.summary?.as_of)
  if (ctx.route === "stock") return stockAnswer(kind, ctx.stock, privacy, today, asOf ?? ctx.stock.quote?.as_of)
  if (kind === "group_share") return groupAnswer()
  return null
}

function groupAnswer(): Answer {
  return {
    text: "預設只分享報酬率的百分比。持股權重、金額、交易動態（可附成交價）和推播要你自己打開，在群組的「分享」分頁改；關掉後其他人馬上看不到。",
    links: [{ label: "到群組", to: "/groups" }],
  }
}

function ledgerAnswer(kind: SuggestionKind, { holdings, summary }: LedgerData, privacy: boolean, today: string, asOf?: string | null): Answer | null {
  switch (kind) {
    case "drag":
    case "lift": {
      const sign = kind === "drag" ? -1 : 1
      const movers = holdings.filter((h) => sign * h.day_change > 0).sort((a, b) => sign * (b.day_change - a.day_change)).slice(0, 3)
      if (movers.length === 0) return { text: kind === "drag" ? "今天沒有持股下跌。" : "今天沒有持股上漲。", asOf }
      const [first, second] = movers
      const text =
        `今天${kind === "drag" ? "拖累最多" : "貢獻最多"}的是${first!.name}（${pctWords(first!.day_change_pct)}）` +
        (second ? `，其次是${inText(second.name, "end")}（${pctWords(second.day_change_pct)}）。` : "。")
      return {
        text,
        rows: movers.map((h) => ({ label: h.name, value: money(h.day_change, privacy, true), tone: direction(h.day_change), hint: pctGlyph(h.day_change_pct) })),
        links: [{ label: `看${first!.name}`, to: "/stock/$symbol", params: { symbol: first!.symbol } }],
        asOf,
      }
    }
    case "dividends_next": {
      const soon = (summary?.upcoming_dividends ?? []).filter((d) => daysBetween(today, d.ex_dividend_date) <= 31)
      if (soon.length === 0) return { text: "接下來 31 天你的持股沒有除息。", links: [{ label: "看股利", to: "/", search: { view: "dividends" } }], asOf }
      const total = soon.reduce((s, d) => s + d.estimated_amount, 0)
      return {
        text: `接下來 31 天有 ${soon.length} 檔除息，依你目前的股數估算共約 ${money(total, privacy)}。實際以除息日前一天持有的股數為準。`,
        rows: soon.map((d) => ({ label: `${d.name}・${formatDateShort(d.ex_dividend_date)}`, value: money(d.estimated_amount, privacy), hint: `每股 ${d.cash_dividend} 元` })),
        links: [{ label: "看股利", to: "/", search: { view: "dividends" } }],
        asOf,
      }
    }
    case "concentration": {
      const { top, top3, industry } = concentrationStats(holdings, summary)
      if (!top) return null
      return {
        text:
          `最大的一檔是${inText(top.name, "end")}，佔 ${formatPercent(top.weight, { signed: false, decimals: 1 })}；前三大合計 ${formatPercent(top3, { signed: false, decimals: 1 })}` +
          (industry ? `；${industry.label}佔 ${formatPercent(industry.weight, { signed: false, decimals: 1 })}。` : "。"),
        rows: [...holdings].sort((a, b) => b.weight - a.weight).slice(0, 3).map((h) => ({ label: h.name, value: formatPercent(h.weight, { signed: false, decimals: 1 }) })),
        asOf,
      }
    }
    case "onboard":
      return {
        text: "直接打，例如「買 0050 2 張 52.4」。",
        followUps: ["買 0050 2 張 52.4"],
      }
    default:
      return null
  }
}

function stockAnswer(kind: SuggestionKind, s: StockData, privacy: boolean, today: string, asOf?: string | null): Answer | null {
  const link = (tab: string, label: string): AnswerLink => ({ label, to: "/stock/$symbol", params: { symbol: s.symbol }, search: { tab } })
  const listed = s.market === "TWSE"
  const us = s.market === "US"
  const currency = us ? "USD" : "TWD"
  const price = (n: number) => priceText(n, s.market)
  const cash = (n: number) => (privacy ? MASK : formatMoney(n, { currency }))
  switch (kind) {
    case "why_move": {
      if (!s.why?.show) {
        return { text: `${inText(s.name, "start")}今天的漲跌在平常的範圍內（${pctWords(s.quote?.change_pct)}），沒有出現異常的成交量${listed ? "" : "、法人"}或事件。`, links: [link("chips", "看籌碼")], asOf }
      }
      return {
        text: `${inText(s.name, "start")}今天${pctWords(s.quote?.change_pct)}：${s.why.headline ?? s.why.reasons[0]?.text ?? ""}。`,
        rows: s.why.reasons.map((r) => ({ label: r.text, value: "" })),
        links: [link("chips", listed ? "看籌碼" : "看法人買賣"), link("events", "看事件")],
        asOf: s.why.as_of ?? asOf,
        followUps: s.position ? ["加碼 1 張，均價會變多少？"] : ["現在的本益比算貴嗎？"],
      }
    }
    case "next_dividend": {
      const next = s.position?.upcoming_dividend
      if (!next) return { text: "目前還沒有公告下一次除息。", links: [link("dividends", "看股利紀錄")], asOf }
      const big = next.amount_estimate >= 20_000
      // 二代健保是台股股利的規則；美股股利不加這一句
      const nhi = us ? "" : big ? "單筆超過 2 萬元，會扣二代健保 2.11%。" : "單筆未達 2 萬元，不扣二代健保。"
      return {
        text: `${formatDateShort(next.ex_dividend_date)} 除息，以你目前的股數估算約 ${cash(next.amount_estimate)}。${nhi}`,
        links: [link("dividends", "看股利")],
        asOf,
      }
    }
    case "cost_on_river": {
      const eps = s.overview?.eps_ttm
      const pos = s.position
      const cost = pos ? `你的均價 ${privacy ? MASK : price(pos.avg_cost)}。` : ""
      // 畫不出河流圖時照實說（美股沒有可商用的行情；台股缺倍數帶或本益比），不引用不存在的圖
      if (us) return { text: `${cost}美股沒有報價，算不出本益比，也沒有河流圖。`, links: [link("financials", "看財務")], asOf }
      if (!pos || !eps || eps <= 0) return { text: "近四季 EPS ≤ 0，本益比沒有意義，可以改看股價淨值比。", links: [link("valuation", "看估值")], asOf }
      if (!hasRiver(s)) return { text: `${cost}這檔還沒有本益比河流圖。`, links: [link("valuation", "看估值")], asOf }
      const costPe = pos.avg_cost / eps
      const nowPe = s.overview?.pe ?? null
      const band = bandOf(costPe, s.valuation?.per_multiples ?? [])
      return {
        text:
          `你的均價 ${privacy ? MASK : price(pos.avg_cost)}，用近四季 EPS ${eps} 元換算是 ${privacy ? MASK : costPe.toFixed(1)} 倍本益比` +
          `${band ? `，落在河流圖${band}` : ""}${nowPe != null ? `；現在是 ${nowPe.toFixed(1)} 倍` : ""}。`,
        links: [link("valuation", "看河流圖")],
        asOf,
      }
    }
    case "add_one_lot": {
      const pos = s.position
      const now = s.quote?.price
      if (!pos || !now || us) return null
      const next = (pos.avg_cost * pos.quantity + now * 1000) / (pos.quantity + 1000)
      return {
        text: `以收盤價 ${price(now)}加碼 1 張，均價會從 ${privacy ? MASK : price(pos.avg_cost)}變成約 ${privacy ? MASK : price(Math.round(next * 100) / 100)}（不含手續費）。`,
        rows: [
          { label: "現在持有", value: privacy ? MASK : formatQuantity(pos.quantity, "lot", s.market) },
          { label: "加碼後", value: privacy ? MASK : formatQuantity(pos.quantity + 1000, "lot", s.market) },
        ],
        followUps: [`買 ${s.code} 1 張 ${now}`],
        asOf,
      }
    }
    case "is_expensive": {
      const pe = s.valuation?.current.per ?? s.overview?.pe ?? null
      const pct = s.valuation?.current.per_percentile_5y ?? null
      if (pe === null && us) return { text: "美股沒有報價，算不出本益比。", links: [link("financials", "看財務")], asOf }
      if (pe === null) return { text: "這檔沒有可用的本益比（ETF 或近四季虧損）。可以看殖利率與股價淨值比。", links: [link("valuation", "看估值")], asOf }
      const band = bandOf(pe, s.valuation?.per_multiples ?? [])
      return {
        text: `本益比 ${pe.toFixed(1)} 倍${band ? `，在河流圖${band}` : ""}${pct !== null ? `；過去 5 年有 ${formatPercent(pct, { signed: false, decimals: 0 })} 的日子比現在便宜` : ""}。`,
        links: [link("valuation", "看河流圖")],
        asOf,
      }
    }
    case "if_hold_dividend": {
      const yearAgo = new Date(Date.parse(`${today}T00:00:00Z`) - 365 * 86_400_000).toISOString().slice(0, 10)
      const lastYear = (s.dividends ?? []).filter((d) => d.ex_dividend_date && d.ex_dividend_date > yearAgo && d.ex_dividend_date <= today)
      const perShare = lastYear.reduce((sum, d) => sum + d.cash_dividend, 0)
      if (perShare <= 0) return { text: "過去一年沒有配息紀錄。", links: [link("dividends", "看股利")], asOf }
      const lot = us ? 1 : 1000
      const per = Math.round(perShare * 100) / 100
      return {
        text: `過去一年每股共配 ${us ? `US$${per}` : `${per} 元`}；持有 ${us ? "1 股" : "1 張"}一年約可領 ${formatMoney(perShare * lot, { currency })}。這是用過去的配息估算，未來不一定相同。`,
        links: [link("dividends", "看股利")],
        asOf,
      }
    }
    case "foreign_flow":
      // 本機規則版沒有網路搜尋：說明為什麼沒有數字、給現在看得到的資料（真實後端由 AI 搜尋新聞，附來源與日期）
      return {
        text: `${inText(s.name, "start")}沒有逐檔的外資買賣資料。`,
        links: [link("chips", "看融資融券"), link("events", "看公告")],
      }
    default:
      return null
  }
}

function bandOf(ratio: number, multiples: number[]): string | null {
  if (multiples.length === 0) return null
  const idx = multiples.findIndex((m) => ratio < m)
  if (idx === 0) return ` ${multiples[0]} 倍以下的帶`
  if (idx === -1) return ` ${multiples.at(-1)} 倍以上的帶`
  return ` ${multiples[idx - 1]}–${multiples[idx]} 倍的帶`
}

/** 沒辦法用資料回答的問題：誠實說明，並給最接近的手動路徑 */
export function fallbackAnswer(text: string, ctx: AiContext): Answer {
  const t = text.replace(/\s/g, "")
  const links: AnswerLink[] = []
  if (ctx.route === "stock") {
    const s = ctx.stock
    const tab = (k: string, label: string) => {
      if (!links.some((l) => l.search?.tab === k)) links.push({ label, to: "/stock/$symbol", params: { symbol: s.symbol }, search: { tab: k } })
    }
    // 美股沒有估值資料（沒有可商用的行情）：本益比相關的問題連到財務（SEC 的每股盈餘）
    if (/(本益比|估值|貴|便宜|河流)/.test(t)) {
      if (s.market === "US") tab("financials", "看財務")
      else tab("valuation", "看估值")
    }
    if (/(營收|財報|毛利|EPS|獲利)/i.test(t)) tab("financials", "看財務")
    if (/(法人|外資|投信|融資|融券|籌碼|大戶)/.test(t)) tab("chips", "看籌碼")
    if (/(股利|配息|除息|殖利率)/.test(t)) tab("dividends", "看股利")
    if (/(新聞|消息|事件|法說|股東會)/.test(t)) tab("events", "看事件")
    if (links.length === 0) tab("overview", `看${inText(s.name)}總覽`)
  } else {
    if (/(股利|配息|除息)/.test(t)) links.push({ label: "看股利", to: "/", search: { view: "dividends" } })
    if (/(績效|報酬|XIRR|TWR|回撤)/i.test(t)) links.push({ label: "看績效", to: "/", search: { view: "performance" } })
    if (/(交易|買|賣|紀錄)/.test(t)) links.push({ label: "看交易", to: "/", search: { view: "transactions" } })
    if (links.length === 0) links.push({ label: "看持倉", to: "/" })
  }
  return {
    text: "這題要查網路資料，現在沒辦法。",
    links: links.slice(0, 3),
  }
}
