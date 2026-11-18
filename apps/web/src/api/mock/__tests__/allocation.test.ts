import { afterEach, describe, expect, it } from "vitest"
import { createMockAdapter } from "@/api/mock/adapter"
import { classify, twEtfClass } from "@/api/mock/allocation"
import { ApiError, type AllocationGrouping } from "@/api/types"
import { useViewAs } from "@/api/view-as"

/** 持倉配置的 mock 要和後端一樣（docs/api-contract.md「持倉配置」、apps/api/tests/api/test_allocation.py） */
const GROUPS: AllocationGrouping[] = ["holding", "industry", "market", "account", "currency", "type"]
const sum = (xs: { value: number }[]) => xs.reduce((s, x) => s + x.value, 0)

afterEach(() => useViewAs.getState().set(null))

describe("GET /portfolio/allocation（mock）", () => {
  const api = createMockAdapter({ latency: [0, 0] })

  it("每一種分組加起來都等於帳本的總市值（和持股同一個價格、匯率）", async () => {
    const [a, holdings, summary] = await Promise.all([api.getAllocation(), api.getHoldings(), api.getPortfolioSummary()])
    const total = sum(holdings.map((h) => ({ value: h.market_value })))
    expect(a.market_value).toBeCloseTo(total, 1)
    expect(a.market_value).toBeCloseTo(summary.market_value, 1)
    for (const g of GROUPS) expect(sum(a.groups[g])).toBeCloseTo(a.market_value, 0)
    // 每一檔和持股一一對應
    expect(a.groups.holding.map((s) => s.key).sort()).toEqual(holdings.map((h) => h.symbol).sort())
  })

  it("只看一個帳戶：和那個帳戶的持股、總資產對得起來；「帳戶」那一組在全部帳戶時就是各帳戶的總市值", async () => {
    const all = await api.getAllocation()
    const accounts = await api.listAccounts()
    for (const acc of accounts) {
      const [a, holdings, summary] = await Promise.all([api.getAllocation(acc.id), api.getHoldings(acc.id), api.getPortfolioSummary(acc.id)])
      expect(a.account_id).toBe(acc.id)
      expect(a.market_value).toBeCloseTo(sum(holdings.map((h) => ({ value: h.market_value }))), 1)
      expect(a.market_value).toBeCloseTo(summary.market_value, 1)
      expect(all.groups.account.find((s) => s.key === acc.id)!.value).toBeCloseTo(a.market_value, 0)
      expect(a.groups.account).toHaveLength(1)
    }
  })

  it("分類：ETF 分類別、不看穿；美股 12 類；最大產業不含 ETF；summary 的 by_industry 沒有「ETF」「其他」", async () => {
    const a = await api.getAllocation()
    const industry = new Map(a.groups.industry.map((s) => [s.key, s]))
    expect(industry.get("etf_tw_equity")!.symbols).toEqual(expect.arrayContaining(["0050.TW", "00878.TW"]))
    expect(industry.get("etf_tw_equity")!.is_etf).toBe(true)
    expect(industry.get("etf_foreign_equity")!.symbols).toEqual(["VOO"])
    expect(industry.get("us_semis")!.label).toBe("美股半導體")
    expect(industry.get("us_tech")!.symbols).toEqual(["AAPL"])
    expect(a.concentration.top_industry).toMatchObject({ key: "半導體業" })
    const summary = await api.getPortfolioSummary()
    expect(summary.allocation.by_industry.map((s) => s.key)).not.toContain("ETF")
    expect(summary.allocation.by_industry.map((s) => s.key)).not.toContain("其他")
    expect(summary.allocation.by_account?.length).toBe(2)
    expect(summary.concentration).toEqual(a.concentration)
    expect(a.groups.type.map((s) => s.label).sort()).toEqual(["ETF", "股票"])
  })

  it("台股 ETF 的類別：代號字尾先，再看是不是上市", () => {
    expect(["00679B", "00632R", "00631L", "00981A", "00635U", "00981T", "0050", "006201"].map((c) => twEtfClass(c, c === "006201" ? "TPEX" : "TWSE"))).toEqual([
      "etf_bond", "etf_leveraged", "etf_leveraged", "etf_active", "etf_futures", "etf_balanced", "etf_tw_equity", "etf_other",
    ])
    expect(classify({ code: "MSFT", market: "US", type: "stock", industry: null, name: "Microsoft" }).industry).toBe("us_tech")
    expect(classify({ code: "ZZZZ", market: "US", type: "stock", industry: null, name: "Zzzz Inc" })).toMatchObject({ industry: "unclassified", label: "未分類" })
    expect(classify({ code: "TQQQ", market: "US", type: "etf", industry: null, name: "ProShares UltraPro QQQ" }).industry).toBe("etf_leveraged")
  })

  it("集中度只寫事實；預設沒有上限、也不標示", async () => {
    const a = await api.getAllocation()
    const c = a.concentration
    expect(c.limits).toEqual({ holding: null, industry: null })
    expect(c.over_limits).toEqual([])
    expect(c.holdings_count).toBe(a.groups.holding.length)
    expect(c.top_holding).toMatchObject({ symbol: a.groups.holding[0]!.key })
    expect(c.top5_weight).toBeCloseTo(a.groups.holding.slice(0, 5).reduce((s, x) => s + x.weight, 0), 3)
    expect(a.can_edit_limits).toBe(true)
  })
})

describe("PUT /portfolio/allocation/limits（mock）", () => {
  it("設了上限才標示：單一個股只看個股（ETF 不算），單一產業不算 ETF；整組取代、null 清掉", async () => {
    const api = createMockAdapter({ latency: [0, 0] })
    expect(await api.putAllocationLimits({ holding: 0.05, industry: 0.3 })).toEqual({ holding: 0.05, industry: 0.3 })
    const a = await api.getAllocation()
    const holdingOver = a.concentration.over_limits.filter((o) => o.kind === "holding")
    const etfs = new Set(a.groups.holding.filter((s) => s.is_etf).map((s) => s.key))
    expect(holdingOver.length).toBeGreaterThan(0)
    expect(holdingOver.every((o) => !etfs.has(o.key) && o.weight > 0.05)).toBe(true)
    expect(a.concentration.over_limits.filter((o) => o.kind === "industry").map((o) => o.key)).toEqual(["半導體業"])
    // summary 的集中度同一份
    expect((await api.getPortfolioSummary()).concentration).toEqual(a.concentration)
    expect(await api.putAllocationLimits({ holding: null, industry: 0.6 })).toEqual({ holding: null, industry: 0.6 })
    const b = await api.getAllocation()
    expect(b.concentration.over_limits).toEqual([])
  })

  it("超出 1%–100% 是 422", async () => {
    const api = createMockAdapter({ latency: [0, 0] })
    for (const bad of [{ holding: 0, industry: null }, { holding: 1.5, industry: null }, { holding: null, industry: -0.1 }]) {
      await expect(api.putAllocationLimits(bad)).rejects.toMatchObject({ status: 422 })
    }
  })

  it("查看別人的資產：看得到配置與授權者的上限，不能改（403 read_only）", async () => {
    const api = createMockAdapter({ latency: [0, 0] })
    const delegations = await api.listDelegations()
    const dad = delegations.received.find((d) => d.owner.display_name === "爸爸")!
    useViewAs.getState().set({ delegation_id: dad.id, owner: dad.owner, scope: dad.scope, accounts: dad.accounts })
    const a = await api.getAllocation()
    expect(a.can_edit_limits).toBe(false)
    expect(a.groups.holding.length).toBeGreaterThan(0)
    for (const g of GROUPS) expect(sum(a.groups[g])).toBeCloseTo(a.market_value, 0)
    const err = await api.putAllocationLimits({ holding: 0.3, industry: null }).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe("read_only")
  })
})
