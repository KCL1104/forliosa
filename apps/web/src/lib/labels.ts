import type { Market, TransactionType } from "@/api/types"

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
