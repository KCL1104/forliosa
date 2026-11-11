import { describe, expect, it } from "vitest"
import { computePreview } from "@/api/mock/fees"
import { ACCOUNTS } from "@/api/mock/ledger"
import { findInstrument } from "@/api/mock/instruments"
import type { ValuationPoint } from "@/api/types"
import { foldSlices } from "../allocation"
import { aggregate } from "../kline"
import { buildRiver, invalidRuns } from "../valuation"

const pt = (t: string, close: number, eps: number | null, bvps: number | null = 100): ValuationPoint => ({
  t, close, eps_ttm: eps, bvps, per: eps && eps > 0 ? close / eps : null, pbr: bvps ? close / bvps : null, dividend_yield: null,
})

describe("估值河流圖", () => {
  it("帶寬 = eps × 倍數，堆疊為差額", () => {
    const rows = buildRiver([pt("2026-01-01", 1000, 50)], [12, 16, 20], "per")
    expect(rows[0]!.bands).toEqual([600, 200, 200])
  })
  it("EPS ≤ 0 的期間整段留白，並找出連續區間", () => {
    const rows = buildRiver(
      [pt("2023-01-01", 20, 1), pt("2023-02-01", 18, -2), pt("2023-03-01", 17, -1), pt("2023-04-01", 19, 0.5)],
      [8, 12],
      "per",
    )
    expect(rows[1]!.bands).toEqual([null, null])
    expect(rows[2]!.bands).toEqual([null, null])
    expect(invalidRuns(rows)).toEqual([{ from: "2023-02-01", to: "2023-03-01" }])
  })
  it("股價淨值比用 bvps", () => {
    const rows = buildRiver([pt("2026-01-01", 1000, 50, 200)], [3, 4], "pbr")
    expect(rows[0]!.bands).toEqual([600, 200])
  })
})

describe("K 線聚合", () => {
  const c = (t: string, o: number, h: number, l: number, cl: number) => ({ t, o, h, l, c: cl, v: 1000 })
  it("週 K：同一週合併，開＝第一天、收＝最後一天", () => {
    const week = aggregate([c("2026-11-09", 10, 12, 9, 11), c("2026-11-10", 11, 15, 10, 14), c("2026-11-16", 14, 14, 13, 13)], "w")
    expect(week).toHaveLength(2)
    expect(week[0]).toMatchObject({ o: 10, h: 15, l: 9, c: 14, v: 2000 })
  })
  it("月 K", () => {
    expect(aggregate([c("2026-10-30", 1, 2, 1, 2), c("2026-11-02", 2, 3, 2, 3)], "m")).toHaveLength(2)
  })
})

describe("配置圖：超過 6 類合併為「其他」", () => {
  it("合併尾巴並保留權重總和", () => {
    const slices = Array.from({ length: 8 }, (_, i) => ({ key: `k${i}`, label: `L${i}`, value: 10 - i, weight: 0.1 }))
    const folded = foldSlices(slices)
    expect(folded).toHaveLength(6)
    expect(folded[5]!.label).toBe("其他 3 項")
    expect(folded[5]!.weight).toBeCloseTo(0.3)
  })
})

describe("示範稅費試算（與後端 domain/fees.py 規則一致）", () => {
  const tw = ACCOUNTS[0]!
  it("買進整股：0.1425% × 2.8 折，元以下捨去（api-contract 範例：426.93 → 426）", () => {
    const p = computePreview({ account_id: tw.id, symbol: "2330.TW", type: "buy", trade_date: "2026-11-11", quantity: 1000, price: 1070 }, tw, findInstrument("2330.TW"))
    expect(p.gross).toBe(1_070_000)
    expect(p.fee).toBe(426)
    expect(p.tax).toBe(0)
    expect(p.net_cash).toBe(-1_070_426)
    expect(p.rules).toEqual(["手續費 0.1425% × 2.8 折，元以下捨去", "證交稅：買進免稅"])
  })
  it("無折扣時整數金額不會因浮點誤差少 1 元", () => {
    const noDiscount = { ...tw, fee_discount: 1 }
    const p = computePreview({ account_id: tw.id, symbol: "2330.TW", type: "buy", trade_date: "2026-11-11", quantity: 1000, price: 1000 }, noDiscount, findInstrument("2330.TW"))
    expect(p.fee).toBe(1425)
  })
  it("零股低於最低手續費以零股最低計", () => {
    const p = computePreview({ account_id: tw.id, symbol: "0050.TW", type: "buy", trade_date: "2026-11-11", quantity: 10, price: 72.4 }, tw, findInstrument("0050.TW"))
    expect(p.fee).toBe(1)
  })
  it("賣出股票 0.3%、ETF 0.1%、當沖 0.15%", () => {
    const base = { account_id: tw.id, type: "sell" as const, trade_date: "2026-11-11", quantity: 1000, price: 100 }
    expect(computePreview({ ...base, symbol: "2317.TW" }, tw, findInstrument("2317.TW")).tax).toBe(300)
    expect(computePreview({ ...base, symbol: "0050.TW" }, tw, findInstrument("0050.TW")).tax).toBe(100)
    expect(computePreview({ ...base, symbol: "2317.TW", is_day_trade: true }, tw, findInstrument("2317.TW")).tax).toBe(150)
  })
  it("股利 ≥ NT$20,000 扣二代健保 2.11%", () => {
    const p = computePreview({ account_id: tw.id, symbol: "2330.TW", type: "cash_dividend", trade_date: "2026-11-11", quantity: 5000, price: 5 }, tw, findInstrument("2330.TW"))
    expect(p.gross).toBe(25_000)
    expect(p.health_insurance).toBe(528)
  })
})
