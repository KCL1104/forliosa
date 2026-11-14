import type { Account, TradePreview, TransactionInput } from "../types"
import type { MockInstrumentSpec } from "./instruments"

/**
 * 示範用的稅費規則：與後端 `apps/api/src/forliosa/domain/fees.py` 相同（規則字串也相同），
 * 讓 mock 與真實 API 的試算結果一致。
 * - 台股手續費：floor(成交金額 × 0.1425% × 折扣)，元以下捨去；低於最低手續費以最低計（未滿 1,000 股用零股最低）
 *   例：1,070,000 × 0.1425% × 0.28 = 426.93 → 426（docs/api-contract.md 的範例）
 * - 美股手續費：成交金額 × 費率 × 折扣，四捨五入到分；低於最低以最低計
 * - 證交稅（賣出）：股票 0.3%、ETF 0.1%、當沖 0.15%（至 2027-12-31），元以下捨去；美股無
 * - 二代健保：單筆股利 ≥ NT$20,000 扣 2.11%（元以下四捨五入）；美股股利預扣 30%
 */
export const TW_FEE_RATE = 0.001425
export const NHI_RATE = 0.0211
export const NHI_THRESHOLD = 20000
const DAY_TRADE_SUNSET = "2027-12-31"

const round2 = (n: number) => Math.round(n * 100) / 100
/** 元以下捨去（加一點點容差，避免 0.1425% 這類小數的浮點誤差讓整數變成 x.9999） */
export const truncate = (n: number) => Math.floor(n + 1e-9)

function pctLabel(rate: number) {
  return `${Number((rate * 100).toFixed(6))}%`
}

function discountLabel(discount: number) {
  if (discount >= 1) return "無折扣"
  return `${Number((discount * 10).toFixed(4))} 折`
}

function money(n: number, currency: "TWD" | "USD" = "TWD") {
  const prefix = currency === "USD" ? "US$" : "NT$"
  return `${prefix}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n)}`
}

/**
 * 稅費試算（與後端 `services/transactions.compute` 相同）。
 * 2026-11-14 起買賣**不自動算手續費與證交稅**（產品負責人：填的價格就是成本，要精準的話自己填）：
 * 使用者新記的交易用 `auto: false`；`auto: true` 只給示範帳本的種子資料（模擬改規則之前就存好的交易，帶著當時算好的費用）。
 */
export function computePreview(
  body: TransactionInput,
  account: Account | undefined,
  spec: MockInstrumentSpec | undefined,
  { auto = true }: { auto?: boolean } = {},
): TradePreview {
  const qty = body.quantity ?? 0
  const price = body.price ?? 0
  const isUS = spec ? spec.market === "US" : account?.currency === "USD"
  const rules: string[] = []

  if ((body.type === "buy" || body.type === "sell") && !auto) {
    const gross = body.amount ?? round2(qty * price)
    const fee = body.fee ?? 0
    const tax = body.type === "sell" ? (body.tax ?? 0) : (body.tax ?? 0)
    if (body.fee != null) rules.push(`手續費：自己填的 ${money(fee, isUS ? "USD" : "TWD")}`)
    if (body.type === "sell" && body.tax != null) rules.push(`交易稅：自己填的 ${money(tax, isUS ? "USD" : "TWD")}`)
    const net = body.type === "buy" ? -(gross + fee) : gross - fee - tax
    return { gross, fee, tax, health_insurance: 0, net_cash: round2(net), rules }
  }

  if (body.type === "buy" || body.type === "sell") {
    const gross = body.amount ?? round2(qty * price)
    const feeRate = account?.fee_rate ?? TW_FEE_RATE
    const discount = account?.fee_discount ?? 1
    let fee: number
    if (body.fee != null) {
      fee = body.fee
      rules.push(`手續費：使用者輸入 ${money(fee, isUS ? "USD" : "TWD")}`)
    } else if (!isUS) {
      const odd = qty < 1000
      const minFee = odd ? (account?.min_fee_odd_lot ?? 1) : (account?.min_fee ?? 20)
      fee = truncate(gross * feeRate * discount)
      rules.push(`手續費 ${pctLabel(feeRate)} × ${discountLabel(discount)}，元以下捨去`)
      if (gross > 0 && fee < minFee) {
        fee = minFee
        rules.push(`低於${odd ? "零股最低手續費" : "最低手續費"}，以 ${money(minFee)} 計`)
      }
    } else if (feeRate <= 0) {
      fee = Math.max(0, account?.min_fee ?? 0)
      rules.push("美股手續費：帳戶未設定費率（以 0 計）")
    } else {
      fee = round2(gross * feeRate * discount)
      rules.push(`美股手續費 ${pctLabel(feeRate)} × ${discountLabel(discount)}`)
      const minFee = account?.min_fee ?? 0
      if (fee < minFee) {
        fee = minFee
        rules.push(`低於最低手續費，以 ${money(minFee, "USD")} 計`)
      }
    }

    let tax = 0
    if (body.type === "sell") {
      if (body.tax != null) {
        tax = body.tax
        rules.push(`證交稅：使用者輸入 ${money(tax, isUS ? "USD" : "TWD")}`)
      } else if (isUS) {
        rules.push("美股無證交稅")
      } else {
        const isEtf = spec?.type === "etf"
        let rate = 0.003
        let rule = "證交稅：股票 0.3%"
        if (isEtf) {
          rate = 0.001
          rule = `證交稅：ETF 0.1%${body.is_day_trade ? "（ETF 當沖稅率相同）" : ""}`
        } else if (body.is_day_trade && body.trade_date <= DAY_TRADE_SUNSET) {
          rate = 0.0015
          rule = `證交稅：當沖減半 0.15%（優惠至 ${DAY_TRADE_SUNSET}）`
        }
        tax = truncate(gross * rate)
        rules.push(`${rule}，元以下捨去`)
      }
    } else {
      rules.push(isUS ? "美股無證交稅" : "證交稅：買進免稅")
    }
    const net = body.type === "buy" ? -(gross + fee) : gross - fee - tax
    return { gross, fee, tax, health_insurance: 0, net_cash: round2(net), rules }
  }

  if (body.type === "cash_dividend") {
    const gross = body.amount ?? (isUS ? truncate(qty * price * 100) / 100 : truncate(qty * price))
    if (body.amount == null) rules.push(`股利 = ${qty} 股 × ${price} 元`)
    let tax = 0
    let nhi = 0
    if (isUS) {
      tax = round2(gross * 0.3)
      rules.push("美股股利預扣稅 30%", "二代健保：海外股利不適用")
    } else {
      if (gross >= NHI_THRESHOLD) {
        nhi = Math.round(Math.min(gross, 10_000_000) * NHI_RATE)
        rules.push("二代健保：單筆股利 ≥ NT$20,000，扣 2.11%（元以下四捨五入）")
      } else {
        rules.push("二代健保：單筆股利未達 NT$20,000，免扣")
      }
      rules.push("股利所得稅：不計入績效（申報時另行試算）")
    }
    if (body.health_insurance != null) nhi = body.health_insurance
    if (body.tax != null) tax = body.tax
    const fee = body.fee ?? 0
    return { gross, fee, tax, health_insurance: nhi, net_cash: round2(gross - tax - nhi - fee), rules }
  }

  const amount = body.amount ?? 0
  const outflow = body.type === "withdrawal" || body.type === "fee" || body.type === "tax"
  return { gross: amount, fee: 0, tax: 0, health_insurance: 0, net_cash: outflow ? -amount : amount, rules }
}
