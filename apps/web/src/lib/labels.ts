import type { Market, ReactionEmoji, TransactionSource, TransactionType } from "@/api/types"

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
  { value: "VOO", label: "S&P 500（VOO）", description: "VOO 含息報酬（美股為示範資料）" },
]

export function benchmarkLabel(symbol: string): string {
  return BENCHMARK_OPTIONS.find((o) => o.value === symbol)?.label ?? symbol
}

/** 市場簡稱 */
export const MARKET_LABEL: Record<Market, string> = { TWSE: "上市", TPEX: "上櫃", US: "美股" }

/** 搜尋結果右側的市場標示；沒有報價的（商用模式的美股）寫「美股・沒有報價」 */
export function marketTag(i: { market: Market; has_quote?: boolean }): string {
  return i.has_quote === false ? `${MARKET_LABEL[i.market]}・沒有報價` : MARKET_LABEL[i.market]
}

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
