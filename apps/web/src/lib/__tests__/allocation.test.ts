import { describe, expect, it } from "vitest"
import type { AllocationGroupSlice, Concentration, PortfolioAllocation } from "@/api/types"
import { allocationRows, donutArcs, etfClassLabel, ETF_KEY, foldRows, limitOf, limitText, noIndustryText, OTHER_KEY, overNote, parseLimit, rowsFor, topN } from "../allocation"

const slice = (key: string, label: string, value: number, p: Partial<AllocationGroupSlice> = {}): AllocationGroupSlice => ({
  key, label, value, weight: value / 1000, is_etf: false, symbols: [key], ...p,
})
const conc = (p: Partial<Concentration> = {}): Concentration => ({
  holdings_count: 4, top_holding: { symbol: "2330.TW", name: "台積電", weight: 0.4, is_etf: false }, top3_weight: 0.85, top5_weight: 1,
  top_industry: { key: "半導體業", label: "半導體業", weight: 0.55 }, etf_weight: 0.3, limits: { holding: null, industry: null }, over_limits: [], ...p,
})
const alloc = (c: Concentration = conc()): PortfolioAllocation => ({
  as_of: "2026-11-12T13:30:00+08:00", account_id: null, market_value: 1000, fx: { USD: 32.47 }, valued_at_cost: [], can_edit_limits: true, is_demo: false, concentration: c,
  groups: {
    holding: [
      slice("2330.TW", "台積電", 400),
      slice("0050.TW", "元大台灣50", 200, { is_etf: true }),
      slice("2454.TW", "聯發科", 150),
      slice("VOO", "Vanguard S&P 500 ETF", 100, { is_etf: true }),
      slice("XYZ", "Xyz Corp", 150),
    ],
    industry: [
      slice("半導體業", "半導體業", 550, { symbols: ["2330.TW", "2454.TW"] }),
      slice("etf_tw_equity", "國內股票型 ETF", 200, { is_etf: true, symbols: ["0050.TW"] }),
      slice("unclassified", "未分類", 150, { symbols: ["XYZ"] }),
      slice("etf_foreign_equity", "海外股票型 ETF", 100, { is_etf: true, symbols: ["VOO"] }),
    ],
    market: [slice("TWSE", "上市", 750, { symbols: ["2330.TW", "0050.TW", "2454.TW"] }), slice("US", "美股", 250, { symbols: ["XYZ", "VOO"] })],
    account: [slice("acc_1", "永豐・一般", 1000, { symbols: ["2330.TW", "0050.TW", "2454.TW", "XYZ", "VOO"] })],
    currency: [slice("TWD", "新台幣", 750), slice("USD", "美元", 250)],
    type: [slice("stock", "股票", 700), slice("etf", "ETF", 300, { is_etf: true })],
  },
})

describe("配置的列（產品負責人 2026-11-18）", () => {
  it("每一檔：第二行是代號；上限只畫在個股上（ETF 不算個股）；超過看後端的 over_limits", () => {
    const a = alloc(conc({ limits: { holding: 0.3, industry: null }, over_limits: [{ kind: "holding", key: "2330.TW", label: "台積電", weight: 0.4, limit: 0.3 }] }))
    const rows = rowsFor(a, "holding")
    expect(rows.map((r) => r.sub)).toEqual(["2330", "0050", "2454", "VOO", "XYZ"])
    expect(rows.map((r) => r.limit)).toEqual([0.3, null, 0.3, null, 0.3])
    expect(rows.map((r) => r.over)).toEqual([true, false, false, false, false])
  })

  it("產業：ETF 類別收在一列「ETF」底下（不算進產業、名稱去掉「ETF」），未分類沒有上限；照大小排", () => {
    const a = alloc(conc({ limits: { holding: null, industry: 0.5 }, over_limits: [{ kind: "industry", key: "半導體業", label: "半導體業", weight: 0.55, limit: 0.5 }] }))
    const rows = rowsFor(a, "industry")
    expect(rows.map((r) => r.key)).toEqual(["半導體業", ETF_KEY, "unclassified"])
    const etf = rows[1]!
    expect(etf).toMatchObject({ label: "ETF", sub: "不算進產業", value: 300, limit: null, over: false })
    expect(etf.kids!.map((k) => [k.label, k.sub])).toEqual([["國內股票型", "0050"], ["海外股票型", "VOO"]])
    expect(rows[0]).toMatchObject({ sub: "台積電、聯發科", limit: 0.5, over: true })
    expect(rows[2]).toMatchObject({ label: "未分類", limit: null })
  })

  it("其他分組：第二行是幾檔，沒有上限", () => {
    expect(rowsFor(alloc(), "market").map((r) => [r.label, r.sub, r.limit])).toEqual([["上市", "3 檔", null], ["美股", "2 檔", null]])
  })

  it("最多 5 塊有顏色；多出 1 塊時不叫「其他 1 檔」（自己一列、鉛筆灰）；多出 2 塊以上併成「其他 N 檔」，點開看裡面", () => {
    const many = (n: number) => Array.from({ length: n }, (_, i) => ({ key: `k${i}`, label: `L${i}`, sub: "", value: 100 - i, weight: (100 - i) / 1000, limit: null, over: false, tone: null }))
    const six = foldRows(many(6), "holding")
    expect(six.map((r) => r.tone)).toEqual([0, 1, 2, 3, 4, "other"])
    expect(six[5]!.label).toBe("L5")
    const eight = foldRows(many(8), "holding")
    expect(eight).toHaveLength(6)
    expect(eight[5]).toMatchObject({ key: OTHER_KEY, label: "其他 3 檔", sub: "L5、L6、L7", value: 95 + 94 + 93, tone: "other" })
    expect(eight[5]!.kids!.map((k) => k.key)).toEqual(["k5", "k6", "k7"])
    expect(foldRows(many(8), "industry")[5]!.label).toBe("其他 3 項")
    // 加起來還是總數
    expect(eight.reduce((s, r) => s + r.value, 0)).toBe(many(8).reduce((s, r) => s + r.value, 0))
  })

  it("allocationRows：5 檔以內全部有顏色", () => {
    expect(allocationRows(alloc(), "holding").map((r) => r.tone)).toEqual([0, 1, 2, 3, 4])
  })

  it("圓環：照金額分一整圈；只有一塊時是完整的圓環", () => {
    const arcs = donutArcs([
      { key: "a", value: 600, tone: 0 },
      { key: "b", value: 300, tone: 1 },
      { key: "c", value: 100, tone: "other" },
    ])
    const sweep = arcs.reduce((s, a) => s + (a.end - a.start), 0)
    expect(sweep).toBeCloseTo(Math.PI * 2, 6)
    expect(arcs[0]!.start).toBeCloseTo(-Math.PI / 2)
    expect(arcs[0]!.end - arcs[0]!.start).toBeCloseTo(Math.PI * 2 * 0.6)
    const one = donutArcs([{ key: "a", value: 5, tone: 0 }])
    expect(one).toHaveLength(1)
    expect(one[0]!.d.match(/M/g)).toHaveLength(2)
    expect(donutArcs([])).toEqual([])
  })
})

describe("集中度與上限的寫法", () => {
  it("前 N 大：6 檔以上前 5 大，4–5 檔前 3 大，3 檔以下不放", () => {
    expect(topN(conc({ holdings_count: 9, top5_weight: 0.78 }))).toEqual({ n: 5, weight: 0.78 })
    expect(topN(conc({ holdings_count: 5, top3_weight: 0.7 }))).toEqual({ n: 3, weight: 0.7 })
    expect(topN(conc({ holdings_count: 3 }))).toBeNull()
  })
  it("超過上限：最大的那一個超過寫「超過你設定的 30%」；別的超過寫「2 檔超過…」；沒設不寫", () => {
    expect(overNote(conc(), "holding")).toBeNull()
    const one = conc({ limits: { holding: 0.3, industry: null }, over_limits: [{ kind: "holding", key: "2330.TW", label: "台積電", weight: 0.4, limit: 0.3 }] })
    expect(overNote(one, "holding")).toEqual({ long: "超過你設定的 30%", short: "超過上限 30%", onTop: true })
    const two = conc({
      top_holding: { symbol: "0050.TW", name: "元大台灣50", weight: 0.45, is_etf: true },
      limits: { holding: 0.2, industry: null },
      over_limits: [
        { kind: "holding", key: "2330.TW", label: "台積電", weight: 0.4, limit: 0.2 },
        { kind: "holding", key: "2454.TW", label: "聯發科", weight: 0.25, limit: 0.2 },
      ],
    })
    expect(overNote(two, "holding")).toEqual({ long: "2 檔超過你設定的 20%", short: "2 檔超過上限", onTop: false })
    // 最大一檔也在超過的清單裡：小標可以接在它後面
    const both = conc({ limits: { holding: 0.2, industry: null }, over_limits: [two.over_limits[0]!, two.over_limits[1]!] })
    expect(overNote(both, "holding")).toEqual({ long: "2 檔超過你設定的 20%", short: "2 檔超過上限", onTop: true })
  })
  it("最大一檔是 ETF、超過的是個股：不能把「超過上限」接在 ETF 後面（onTop 是 false）", () => {
    const etfTop = conc({
      top_holding: { symbol: "0050.TW", name: "元大台灣50", weight: 0.45, is_etf: true },
      limits: { holding: 0.3, industry: null },
      over_limits: [{ kind: "holding", key: "2330.TW", label: "台積電", weight: 0.32, limit: 0.3 }],
    })
    expect(overNote(etfTop, "holding")).toEqual({ long: "1 檔超過你設定的 30%", short: "1 檔超過上限", onTop: false })
    // 產業：最大產業和超過的產業出自同一批，有超過就一定是最大的那個
    const ind = conc({ limits: { holding: null, industry: 0.5 }, over_limits: [{ kind: "industry", key: "半導體業", label: "半導體業", weight: 0.55, limit: 0.5 }] })
    expect(overNote(ind, "industry")).toEqual({ long: "超過你設定的 50%", short: "超過上限 50%", onTop: true })
  })
  it("最大產業空白：全是 ETF 才寫「都是 ETF」，ETF 加上沒有產業資料的個股寫「沒有產業資料」", () => {
    expect(noIndustryText(conc({ top_industry: null, etf_weight: 1 }))).toBe("都是 ETF")
    expect(noIndustryText(conc({ top_industry: null, etf_weight: 0.6 }))).toBe("沒有產業資料")
    expect(noIndustryText(conc({ top_industry: null, etf_weight: 0 }))).toBe("沒有產業資料")
  })
  it("上限的數字與輸入", () => {
    expect(limitText(0.3)).toBe("30%")
    expect(limitText(0.125)).toBe("12.5%")
    expect(parseLimit("30")).toBe(0.3)
    expect(parseLimit(" 12.5% ")).toBe(0.125)
    expect(parseLimit("")).toBeNull()
    expect(parseLimit("0")).toBeUndefined()
    expect(parseLimit("101")).toBeUndefined()
    expect(parseLimit("三十")).toBeUndefined()
    expect(limitOf("holding", { holding: 0.3, industry: null })).toEqual({ kind: "holding", value: 0.3 })
    expect(limitOf("industry", { holding: 0.3, industry: null })).toBeNull()
    expect(limitOf("market", { holding: 0.3, industry: 0.5 })).toBeNull()
  })
  it("ETF 類別在「ETF」底下的名稱", () => {
    expect(etfClassLabel("國內股票型 ETF")).toBe("國內股票型")
    expect(etfClassLabel("槓桿／反向 ETF")).toBe("槓桿／反向")
    expect(etfClassLabel("ETF（未分類）")).toBe("未分類")
  })
})
