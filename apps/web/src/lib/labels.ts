import type { InstrumentType, Market, ReactionEmoji, TransactionSource, TransactionType } from "@/api/types"
import { formatDateShort, formatPrice } from "@/lib/format"

/** 表情的念法（螢幕閱讀器與滑過說明）：群組與討論串共用 */
export const EMOJI_LABEL: Record<ReactionEmoji, string> = {
  "👍": "讚",
  "🎉": "恭喜",
  "🔥": "厲害",
  "😮": "驚訝",
  "😢": "難過",
  "👀": "關注",
}

/** 績效比較基準：設定與績效頁可選的項目（後端也接受任何商品代號） */
export const BENCHMARK_OPTIONS: { value: string; label: string; description: string }[] = [
  { value: "0050.TW", label: "元大台灣50", description: "0050 含息報酬（除息日股利再投入）" },
  { value: "^TAIEXTR", label: "加權報酬指數", description: "發行量加權股價報酬指數（含息），證交所編製" },
  { value: "006208.TW", label: "富邦台50", description: "006208 含息報酬" },
  // VOO 是追蹤 S&P 500 的 ETF，不是指數本身；美股股利沒有資料，所以只是價格報酬
  { value: "VOO", label: "VOO（追蹤 S&P 500）", description: "VOO 的價格報酬，不含股利（美股股利沒有資料）" },
]

export function benchmarkLabel(symbol: string): string {
  return BENCHMARK_OPTIONS.find((o) => o.value === symbol)?.label ?? symbol
}

/** 市場簡稱 */
export const MARKET_LABEL: Record<Market, string> = { TWSE: "上市", TPEX: "上櫃", US: "美股" }

/**
 * 搜尋結果右側的市場標示。`served`：後端有沒有提供美股收盤價（`useUsClosesServed`）。
 * 有提供時美股一律 `has_quote: true`（還沒抓到的只是 `/quote` 404，搜尋結果分不出來），只寫「美股」；
 * 沒有提供時美股是 `has_quote: false`，寫「美股・沒有報價」——不承諾會補上。
 * 有報價的搜尋結果另外寫市場與產業（`marketLine`，和麵包屑同一套）。
 */
export function marketTag(i: { market: Market; has_quote?: boolean }, served: boolean): string {
  return i.has_quote === false && !served ? `${MARKET_LABEL[i.market]}・沒有報價` : MARKET_LABEL[i.market]
}

/**
 * 美股的產業名稱是英文（資料源原文）。麵包屑與搜尋結果只在對得到台股產業別的時候寫中文——同一個詞，美股和台股讀起來一樣
 * （「半導體業」是證交所的產業別名稱）；對不到的不自己翻譯，只寫「美股」。原文仍在「關於」的鍵值格裡。
 */
const US_INDUSTRY_ZH: Readonly<Record<string, string>> = { Semiconductors: "半導體業" }

/** 市場與產業：「上市・半導體業」「上櫃・ETF」「美股・半導體業」「美股」（麵包屑、⌘K 的搜尋結果） */
export function marketLine(inst: { market: Market; type: InstrumentType; industry: string | null }): string {
  const market = MARKET_LABEL[inst.market]
  if (inst.type === "etf") return `${market}・ETF`
  const industry = inst.market === "US" ? US_INDUSTRY_ZH[inst.industry ?? ""] : inst.industry
  return industry ? `${market}・${industry}` : market
}

/**
 * 美股收盤屬於哪一個交易日（產品負責人 2026-11-15，Databento 的收盤）：一律是紐約的日期。報價的 `as_of` 是紐約 16:00，
 * 在台北已經是隔天早上——不能拿台北的日期或時刻說這是哪一天的收盤。
 * 給 `trade_date`（報價、為什麼）或 `price_date`（持股）；舊版後端沒有這個欄位時由 `as_of` 換算成紐約的日期。
 */
export function usTradeDate(date: string | null | undefined, asOf?: string | null): string | null {
  if (date) return date
  if (!asOf || Number.isNaN(Date.parse(asOf))) return null
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(asOf))
}

/** 美股的交易日：「11/13（美東）」（「Apple 11/13（美東）上漲 1.20%」） */
export const usDay = (date: string) => `${formatDateShort(date, false)}（美東）`

/** 美股收盤的標示：「11/13 收盤（美東）」 */
export const usCloseLabel = (date: string) => `${formatDateShort(date, false)} 收盤（美東）`

/** 美股的價格一定帶 US$：「US$356.27」 */
export const usd = (p: number | null | undefined) => (p === null || p === undefined ? "—" : `US$${formatPrice(p, "US")}`)

/** 交易類型（zh-TW） */
export const TYPE_LABEL: Record<TransactionType, string> = {
  buy: "買進",
  sell: "賣出",
  cash_dividend: "現金股利",
  stock_dividend: "股票股利",
  split: "分割",
  capital_reduction: "減資",
  deposit: "存入",
  withdrawal: "提出",
  fee: "手續費",
  tax: "稅",
  interest: "利息",
}

/**
 * 交易來源的標示（`null` = 不標示）。`ai` 用石墨灰（AI 做的事；固定標籤，不用楷體），其他是淡墨細框小字。
 * 自動入帳是系統依規則記的，不是 AI：不用石墨灰。
 */
export const SOURCE_TAG: Record<TransactionSource, { label: string; title?: string; ai?: boolean } | null> = {
  manual: null,
  import: { label: "匯入", title: "從對帳單匯入" },
  ai_draft: { label: "由 AI 建立", ai: true },
  auto: { label: "自動", title: "系統在除息日依前一天收盤的持股自動入帳" },
  auto_edited: { label: "自動・已修改", title: "自動入帳後你改過，系統不會再更新這筆" },
}

/** 系統自動入帳的股利（含使用者改過的） */
export function isAutoSource(source: TransactionSource): boolean {
  return source === "auto" || source === "auto_edited"
}
