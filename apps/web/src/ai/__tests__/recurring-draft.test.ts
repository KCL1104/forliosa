import { describe, expect, it } from "vitest"
import type { RecurringDraft } from "@/api/types"
import { recurringDraftCopy } from "@/ai/runner"

const draft = (p: Partial<RecurringDraft> & { price?: number } = {}): RecurringDraft => {
  const { price = 50, ...rest } = p
  return {
    plan_id: "rcp_1", scheduled_date: "2026-11-06", date: "2026-11-06", name: "元大台灣50", amount: 5000,
    price_as_of: "2026-11-06",
    transaction: {
      account_id: "acc_1", symbol: "0050.TW", type: "buy", trade_date: "2026-11-06", quantity: 100, price,
      note: "定期定額 NT$5,000（11/6）", source: "ai_draft",
    },
    preview: { gross: 5000, fee: 2, tax: 0, health_insurance: 0, net_cash: -5002, rules: [] },
    is_demo: false,
    ...rest,
  }
}
const missed = { planId: "rcp_1", scheduledDate: "2026-11-06", date: "2026-11-06", name: "元大台灣50", missed: true }

describe("定期定額草稿的說明", () => {
  it("補記：有那天的收盤價就說「那天的收盤價」", () => {
    const c = recurringDraftCopy(draft(), missed)
    expect(c.tradeDate).toBe("2026-11-06")
    // 訊息只說事實（哪一天、還沒記）；怎麼估的寫在草稿卡的說明行，不講兩次
    expect(c.text).toBe("11/6 是元大台灣50 定期定額的扣款日，帳本裡還沒有這一筆。")
    expect(c.notes[0]).toContain("以 11/6 收盤價 50.00 估算股數")
  })
  it("補記：後端沒有那天的收盤價、改用最近收盤價時照實說", () => {
    const c = recurringDraftCopy(draft({ price_as_of: "2026-11-11", price: 52.4 }), missed)
    expect(c.notes[0]).toContain("以 11/11 收盤價 52.40 估算股數")
  })
  it("示範價格（is_demo）不說成收盤價", () => {
    const c = recurringDraftCopy(draft({ is_demo: true }), missed)
    expect(c.text).not.toContain("收盤價")
    expect(c.notes[0]).toContain("以示範價格 50.00 估算股數（不是真實行情")
    expect(c.notes[0]).not.toContain("收盤價")
    const today = recurringDraftCopy(draft({ is_demo: true }), { ...missed, missed: false })
    expect(today.text).toBe("今天是元大台灣50 定期定額的扣款日。")
    expect(today.notes[0]).toContain("以示範價格 50.00 估算股數")
  })
})
