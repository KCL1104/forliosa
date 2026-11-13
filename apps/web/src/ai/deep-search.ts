import type { ForliosaApi, Instrument } from "@/api/types"
import { formatPercent, formatPrice } from "@/lib/format"
import { normalize } from "./intent"
import { DEEP_SEARCH_COST, type AiUsage, type Citation } from "./remote"

/**
 * 深度搜尋（輸入框的切換鈕）：這一題多查幾輪資料、寫成一份整理，算好幾題。
 * 連真實後端時由模型做（`POST /ai/chat` 的 `mode: "deep"`）；這裡是輸入框的那一句話，
 * 以及 mock 模式的示範整理（用 API 的示範資料組出同樣的版面：兩三句結論、短標題、每點一行、附來源）。
 */

/** 一次算幾題；`null`＝這個環境沒有深度搜尋（後端沒開網路搜尋），切換鈕不出現 */
export function deepSearchCost(usage: Pick<AiUsage, "deep_search_cost"> | undefined): number | null {
  if (!usage || usage.deep_search_cost === undefined) return DEEP_SEARCH_COST
  return usage.deep_search_cost
}

/** 切換鈕開著時輸入框下面的那一句（15px 墨色） */
export function deepSearchHint(cost: number): string {
  return `多查幾輪資料，寫成一份整理。算 ${cost} 題。`
}

/** 問句裡不是名稱的字 */
const NOISE = /(幫我|請|深入|深度|研究|分析|整理|搜尋|了解|瞭解|看看|一下|最近|的|怎麼樣|如何|前景|展望|基本面|風險|競爭|狀況|情況|值得|嗎|？|\?|。|，|,)/g

/** 問句裡的那一檔：先找代號，再把雜字拿掉後剩下的字當名稱 */
export function deepTarget(raw: string): string | null {
  const text = normalize(raw)
  const code = /\b(\d{4,6}[A-Za-z]?|[A-Z]{2,5})\b/.exec(text)?.[1]
  if (code) return code
  const name = text.replace(NOISE, " ").trim().split(/\s+/)[0]
  return name && name.length <= 12 ? name : null
}

const day = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`

export interface DeepReport {
  text: string
  citations: Citation[]
}

/**
 * mock 模式的示範整理。`fallback`：問句裡找不到股票時用的那一檔（個股頁上的那一檔）。
 * 找不到任何一檔時回一句說明，不編內容。
 */
export async function buildLocalDeepReport(
  question: string,
  deps: { api: ForliosaApi; resolve: (target: string) => Promise<Instrument | null>; fallback?: string | null },
): Promise<DeepReport> {
  const target = deepTarget(question)
  const inst = (target ? await deps.resolve(target) : null) ?? (deps.fallback ? await deps.resolve(deps.fallback) : null)
  if (!inst) return { text: "示範資料只能整理個股。問的時候寫上是哪一檔，例如「深入研究台積電」。", citations: [] }
  const { api } = deps
  const [quote, overview, revenue, financials, news] = await Promise.all([
    api.getQuote(inst.symbol).catch(() => null),
    api.getOverview(inst.symbol).catch(() => null),
    inst.type === "stock" && inst.market !== "US" ? api.getRevenue(inst.symbol).catch(() => []) : Promise.resolve([]),
    inst.type === "stock" ? api.getFinancials(inst.symbol, "quarterly").catch(() => null) : Promise.resolve(null),
    api.getNews(inst.symbol).catch(() => []),
  ])
  const move = (pct: number | null | undefined) => (pct == null ? null : `${pct >= 0 ? "上漲" : "下跌"} ${formatPercent(Math.abs(pct), { signed: false })}`)
  const groups: [string, string[]][] = []

  const business: string[] = []
  const latest = [...revenue].sort((a, b) => a.period.localeCompare(b.period)).at(-1)
  if (latest) {
    const yoy = latest.yoy_pct == null ? "" : `，比去年同月${latest.yoy_pct >= 0 ? "多" : "少"} ${formatPercent(Math.abs(latest.yoy_pct), { signed: false })}`
    business.push(`${latest.period.replace("-", " 年 ").replace(/^(\d{4}) 年 0?/, "$1 年 ")} 月營收 ${new Intl.NumberFormat("zh-TW").format(Math.round(latest.revenue / 100_000))} 億元${yoy}。`)
  }
  const eps = financials?.income.eps ?? []
  const lastEps = [...eps.keys()].reverse().find((i) => typeof eps[i] === "number")
  if (financials && lastEps !== undefined) business.push(`${financials.periods[lastEps]} 每股盈餘 ${eps[lastEps]} 元。`)
  if (business.length) groups.push(["營運", business])

  const price: string[] = []
  if (quote) {
    const when = quote.as_of ? `${day(quote.as_of)} ` : ""
    price.push(`${when}收盤 ${formatPrice(quote.price, inst.market, inst.type)}${move(quote.change_pct) ? `，${move(quote.change_pct)}` : ""}。`)
  }
  if (overview?.pe != null) price.push(`本益比 ${overview.pe.toFixed(1)} 倍。`)
  if (overview?.dividend_yield != null) price.push(`殖利率 ${formatPercent(overview.dividend_yield, { signed: false })}。`)
  if (price.length) groups.push(["股價與估值", price])

  const headlines = news.filter((n) => n.url).slice(0, 3)
  const citations: Citation[] = headlines.map((n) => ({ url: n.url, title: n.outlet ? `${n.outlet}：${n.title}` : n.title, cited_text: n.title }))
  if (headlines.length) groups.push(["最近的消息", headlines.map((n) => `${n.title}（${n.outlet ?? n.source}，${day(n.published_at)}）。`)])

  if (groups.length === 0) return { text: `示範資料裡沒有${inst.name}可以整理的內容。`, citations: [] }
  const lead = [
    quote ? `${inst.name}（${inst.code}）${quote.as_of ? `${day(quote.as_of)} ` : ""}收在 ${formatPrice(quote.price, inst.market, inst.type)}${move(quote.change_pct) ? `，${move(quote.change_pct)}` : ""}。` : `${inst.name}（${inst.code}）的整理如下。`,
    "這份整理用的是示範資料。",
  ].join("")
  const body = groups.slice(0, 3).map(([title, points]) => [title, ...points.map((p) => `・${p}`)].join("\n"))
  return { text: [lead, ...body].join("\n\n"), citations }
}
