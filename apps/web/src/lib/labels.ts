import type { Market, TransactionType } from "@/api/types"

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
