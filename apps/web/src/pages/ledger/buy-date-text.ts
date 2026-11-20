import type { Candle, PickFrom } from "@/api/types"
import { closeGap, crossesOn, isFarFromCost } from "@/lib/buy-date"
import { formatPercent } from "@/lib/format"
import { recordDate } from "./symbol-records"

/**
 * 選買入日畫面（`BuyDatePicker.tsx`）的字（純函式，測試得到）。
 */

/** 選日期的畫面裡的日期：不寫星期（買很久的股票，星期幾沒有用；360px 的手機也放得下標記），不是今年的寫年份 */
export const pickDay = (t: string) => recordDate(t).replace(/（.）$/, "")

/** `pick_from` 的原因怎麼寫（和後端 `services/buy_date.py` 的 `REASON_TEXT` 一樣） */
export const PICK_FROM_REASON: Record<PickFrom["reason"], string> = { split: "股票分割", reduction: "減資", stock_dividend: "配股" }

/** 分割、減資、配股以前的日子不能選：一行，講事實——「2025/6/18 股票分割，之前的日子不能選」 */
export const pickFromLine = (p: PickFrom) => `${pickDay(p.date)} ${PICK_FROM_REASON[p.reason]}，之前的日子不能選`

/**
 * 讀數下面那一句：
 * - 帳本上的日期那天沒有收盤、選的是它前一個收盤日：照實說。
 * - 當天股價經過成本（最低 ≤ 成本 ≤ 最高）：寫那天的最低–最高，不寫收盤差幾 %——估計就是照這個找的，收盤離成本遠不代表估錯。
 * - 跳空越過成本：寫前一天與這天的價格。
 * - 都不是、而且收盤和成本差 3% 以上：「這天收盤 580，和你的成本 612 差 5.2%。」（15px 墨色）；差不多時一句淡墨。
 * 隱私模式（成本是自己的數字）：什麼都不寫——收盤加差幾 % 就算得出成本。
 */
export function readoutLine(
  candles: readonly Candle[],
  sel: number,
  opts: { cost: number; costText: string; price: (p: number) => string; lotDate: string; initialIdx: number; privacy: boolean },
): { text: string; strong: boolean } | null {
  const c = candles[sel]
  if (!c || opts.privacy) return null
  if (sel === opts.initialIdx && c.t !== opts.lotDate) return { text: `帳本上記的是 ${pickDay(opts.lotDate)}，那天沒有收盤，這是前一個交易日。`, strong: false }
  const { cost, costText, price } = opts
  if (c.l <= cost && cost <= c.h) return { text: `這天股價在 ${price(c.l)}–${price(c.h)} 之間，經過你的成本 ${costText}。`, strong: false }
  const prev = candles[sel - 1]
  if (prev && crossesOn(candles, sel, cost)) {
    const text = prev.h < cost ? `前一天最高 ${price(prev.h)}，這天最低 ${price(c.l)}，跳空越過你的成本 ${costText}。` : `前一天最低 ${price(prev.l)}，這天最高 ${price(c.h)}，跳空越過你的成本 ${costText}。`
    return { text, strong: false }
  }
  const gapText = formatPercent(Math.abs(closeGap(c.c, cost)), { signed: false, decimals: 1 })
  return isFarFromCost(c.c, cost) ? { text: `這天收盤 ${price(c.c)}，和你的成本 ${costText} 差 ${gapText}。`, strong: true } : { text: `這天收盤和你的成本 ${costText} 差 ${gapText}。`, strong: false }
}
