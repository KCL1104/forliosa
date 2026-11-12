import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { Transaction, TransactionInput, TransactionSource } from "@/api/types"
import { dividendAsk } from "@/ai/runner"
import { SourceTag } from "@/components/finance"
import { isAutoSource, SOURCE_TAG } from "@/lib/labels"
import { autoEditNotice, isUnchangedEdit, replacedAutoDividend } from "@/lib/ledger-display"

const txn = (p: Partial<Transaction>): Transaction => ({
  id: "txn_1", account_id: "acc_1", symbol: "2330.TW", type: "cash_dividend", trade_date: "2026-09-16", quantity: 1500, price: 5,
  amount: 7500, fee: 0, tax: 0, health_insurance: 0, currency: "TWD", is_day_trade: false,
  note: "除息前一日持有 1,500 股 × 每股現金股利 5 元；發放日 2026-10-09", source: "auto", created_at: "2026-09-16T18:00:00+08:00", ...p,
})

describe("交易來源標示", () => {
  it("每種來源都有對應（自己記的不標示）", () => {
    const all: TransactionSource[] = ["manual", "import", "ai_draft", "auto", "auto_edited"]
    expect(all.map((s) => SOURCE_TAG[s]?.label ?? null)).toEqual([null, "匯入", "由 AI 建立", "自動", "自動・已修改"])
    expect(all.filter(isAutoSource)).toEqual(["auto", "auto_edited"])
  })
  it("自動入帳是淡墨細框（不是 AI 的紫色），可滑過看說明", () => {
    render(<SourceTag source="auto" />)
    const el = screen.getByText("自動")
    expect(el).toHaveClass("demo-tag", "text-ink-2")
    expect(el).not.toHaveClass("text-ai")
    expect(el.getAttribute("title")).toContain("除息日")
  })
  it("改過的標「自動・已修改」；AI 建立的是紫色文楷；自己記的什麼都沒有", () => {
    const { container } = render(
      <div>
        <SourceTag source="auto_edited" />
        <SourceTag source="ai_draft" />
        <SourceTag source="manual" />
      </div>,
    )
    expect(screen.getByText("自動・已修改")).toHaveClass("demo-tag")
    expect(screen.getByText("由 AI 建立")).toHaveClass("font-ai", "text-ai")
    expect(container.firstElementChild!.children).toHaveLength(2)
  })
})

describe("編輯自動入帳的股利", () => {
  it("說明：儲存後是自己的版本、刪除後不再自動入帳；改過的只說不再更新", () => {
    expect(autoEditNotice("auto")).toBe("系統在除息日自動記下這筆股利。儲存變更後就是你自己的版本，系統不會再更新；刪除後也不會再自動入帳。")
    expect(autoEditNotice("auto_edited")).toBe("這筆自動入帳的股利你改過，系統不會再更新它。")
    expect(autoEditNotice("manual")).toBeNull()
    expect(autoEditNotice("ai_draft")).toBeNull()
  })
  it("沒改任何欄位就不算修改（不送出，維持「自動」）", () => {
    const t = txn({})
    const body: TransactionInput = { account_id: t.account_id, symbol: t.symbol, type: t.type, trade_date: t.trade_date, quantity: 1500, price: 5, is_day_trade: false, note: t.note }
    expect(isUnchangedEdit(t, body)).toBe(true)
    expect(isUnchangedEdit(t, { ...body, note: "券商入帳 7,500" })).toBe(false)
    expect(isUnchangedEdit(t, { ...body, quantity: 1000 })).toBe(false)
    expect(isUnchangedEdit(t, { ...body, amount: undefined })).toBe(true)
  })
})

describe("AI 記台股股利", () => {
  it("找出會被取代的自動入帳（120 天內最近的一筆）", () => {
    const rows = [txn({ id: "a", trade_date: "2026-06-11" }), txn({ id: "b", trade_date: "2026-09-16" }), txn({ id: "c", trade_date: "2026-07-01", source: "manual" })]
    expect(replacedAutoDividend(rows, "2026-11-12")?.id).toBe("b")
    expect(replacedAutoDividend(rows, "2026-09-15")?.id).toBe("a")
    expect(replacedAutoDividend(rows, "2027-02-01")).toBeNull()
    expect(replacedAutoDividend([txn({ source: "auto_edited" })], "2026-11-12")).toBeNull()
  })
  it("「股利入帳」的提問：台股說明自動入帳，美股照常問金額", () => {
    expect(dividendAsk()).toContain("台股股利會在除息日自動入帳")
    expect(dividendAsk()).toContain("「AAPL 配息 2.6」")
    expect(dividendAsk("2330")).toMatch(/^2330 的股利會在除息日自動入帳/)
    expect(dividendAsk("VOO")).toBe("VOO 領了多少？例如「VOO 配息 2.6」。金額照存摺上的實際入帳數字就好。")
  })
})
