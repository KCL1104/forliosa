import type { Account, TradePreview, TransactionInput } from "../types"
import type { MockInstrumentSpec } from "./instruments"

/**
 * 示範用的台股稅費規則（後端才是正式實作；這裡只為了讓 mock 預估合理）。
 * - 手續費：成交金額 × 0.1425% × 折扣，四捨五入（與 api-contract 範例一致），低於最低手續費以最低計（零股另計）
 * - 證交稅（賣出）：股票 0.3%、ETF 0.1%、當沖 0.15%
 * - 二代健保：單筆股利 ≥ NT$20,000 扣 2.11%
 * - 美股股利：預扣 30% 稅
 */
export const TW_FEE_RATE = 0.001425
export const NHI_RATE = 0.0211
export const NHI_THRESHOLD = 20000

const round2 = (n: number) => Math.round(n * 100) / 100

function discountLabel(discount: number) {
  if (discount >= 1) return "無折扣"
  const zhe = Math.round(discount * 100) / 10
  return `${zhe} 折`
}

export function computePreview(
  body: TransactionInput,
  account: Account | undefined,
  spec: MockInstrumentSpec | undefined,
): TradePreview {
  const qty = body.quantity ?? 0
  const price = body.price ?? 0
  const isUS = account?.currency === "USD" || spec?.market === "US"
  const rules: string[] = []

  if (body.type === "buy" || body.type === "sell") {
    const gross = isUS ? round2(qty * price) : Math.round(qty * price)
    const feeRate = account?.fee_rate ?? TW_FEE_RATE
    const discount = account?.fee_discount ?? 1
    const isOdd = !isUS && qty % 1000 !== 0
    const minFee = isOdd ? (account?.min_fee_odd_lot ?? 1) : (account?.min_fee ?? 20)
    // 折扣後手續費：依 api-contract 範例（1,070,000 × 0.1425% × 2.8 折 = 427）四捨五入；券商實務可能捨去，見 OPEN_QUESTIONS
    let fee = isUS ? round2(gross * feeRate * discount) : Math.round(gross * feeRate * discount)
    const usedMin = gross > 0 && fee < minFee
    if (usedMin) fee = minFee
    rules.push(`手續費 ${(feeRate * 100).toFixed(4).replace(/0+$/, "")}% × ${discountLabel(discount)}`)
    if (usedMin) rules.push(`低於最低手續費，以 ${isUS ? "US$" : "NT$"}${minFee} 計${isOdd ? "（零股）" : ""}`)

    let tax = 0
    if (body.type === "sell" && !isUS) {
      const isEtf = spec?.type === "etf"
      const rate = body.is_day_trade && !isEtf ? 0.0015 : isEtf ? 0.001 : 0.003
      tax = Math.floor(gross * rate)
      rules.push(
        body.is_day_trade && !isEtf
          ? "證交稅：當沖 0.15%（減半優惠至 2027-12-31）"
          : `證交稅：${isEtf ? "ETF 0.1%" : "股票 0.3%"}`,
      )
    } else if (body.type === "buy") {
      rules.push(isUS ? "美股買進：無證交稅" : "證交稅：買進免稅")
    } else {
      rules.push("美股賣出：無證交稅")
    }
    if (body.fee != null) fee = body.fee
    if (body.tax != null) tax = body.tax
    const net = body.type === "buy" ? -(gross + fee) : gross - fee - tax
    return { gross, fee, tax, health_insurance: 0, net_cash: isUS ? round2(net) : net, rules }
  }

  if (body.type === "cash_dividend") {
    const gross = body.amount ?? (isUS ? round2(qty * price) : Math.round(qty * price))
    let tax = 0
    let nhi = 0
    if (isUS) {
      tax = round2(gross * 0.3)
      rules.push("美股股利：預扣 30% 稅")
    } else if (gross >= NHI_THRESHOLD) {
      nhi = Math.round(gross * NHI_RATE)
      rules.push("二代健保補充保費：單筆股利 ≥ NT$20,000，扣 2.11%")
    } else {
      rules.push("單筆股利未達 NT$20,000，不扣二代健保")
    }
    if (body.health_insurance != null) nhi = body.health_insurance
    if (body.tax != null) tax = body.tax
    return { gross, fee: 0, tax, health_insurance: nhi, net_cash: round2(gross - tax - nhi), rules }
  }

  const amount = body.amount ?? 0
  const outflow = body.type === "withdrawal" || body.type === "fee" || body.type === "tax"
  return { gross: amount, fee: 0, tax: 0, health_insurance: 0, net_cash: outflow ? -amount : amount, rules }
}
