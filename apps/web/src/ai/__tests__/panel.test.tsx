import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeAll, describe, expect, it, vi } from "vitest"
import { Conversation } from "@/ai/Conversation"
import { quickActions } from "@/ai/panel-helpers"
import type { useAiRunner } from "@/ai/runner"
import type { AiContext, StockData } from "@/ai/suggestions"
import type { Thread } from "@/ai/types"

const stock = (p: Partial<StockData>): AiContext => ({
  route: "stock",
  stock: { symbol: "2330.TW", code: "2330", name: "台積電", market: "TWSE", type: "stock", ...p },
})

describe("面板的常用動作：一行文字連結，只放這一頁真的能做的事", () => {
  it("帳本：記一筆交易・匯入對帳單・股利入帳", () => {
    expect(quickActions({ route: "ledger", ledger: { holdings: [] } }).map((a) => a.label)).toEqual(["記一筆交易", "匯入對帳單", "股利入帳"])
  })
  it("個股頁：記一筆這一檔（台股用名稱、美股用代號），有持股才有股利入帳；不放還沒開放的到價提醒", () => {
    const held = quickActions(stock({ position: { quantity: 1500 } as StockData["position"] }))
    expect(held.map((a) => [a.label, a.run, a.code])).toEqual([
      ["記一筆台積電", "trade", "2330"],
      ["股利入帳", "dividend", "2330"],
    ])
    expect(quickActions(stock({ symbol: "AAPL", code: "AAPL", name: "Apple", market: "US", position: null })).map((a) => a.label)).toEqual(["記一筆 AAPL"])
  })
  it("群組與其他頁（設定、資料來源、紀錄）：沒有常用動作", () => {
    expect(quickActions({ route: "groups" })).toEqual([])
    expect(quickActions({ route: "other" })).toEqual([])
  })
})

describe("對話的兩支筆：模型寫的字是紫色楷體，規則或範本寫的句子是墨色 Noto Sans", () => {
  const runner = { submit: async () => undefined } as unknown as ReturnType<typeof useAiRunner>
  // jsdom 沒有 scrollIntoView（對話捲到最新一則）
  beforeAll(() => {
    Element.prototype.scrollIntoView = vi.fn()
  })
  const at = "2026-11-12T13:41:00+08:00"
  const view = (thread: Thread) =>
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Conversation thread={thread} runner={runner} />
      </QueryClientProvider>,
    )

  it("模型串流的回答用楷體；草稿的說明與規則版回答不用", () => {
    view({
      id: "t1",
      title: "q",
      updatedAt: at,
      messages: [
        { id: "u1", role: "user", text: "台積電今天怎麼了？", at },
        { id: "a1", role: "ai", model: true, text: "台積電今天上漲。", at },
        { id: "a2", role: "ai", model: false, text: "我照你說的算好了稅費，簽名後才會入帳。", at },
        { id: "a3", role: "ai", answer: { text: "今天拖累最多的是環球晶。", followUps: ["我的持股會不會太集中？"] }, at },
      ],
    })
    expect(screen.getByText("台積電今天上漲。").closest("p")).toHaveClass("ai-voice")
    for (const t of ["我照你說的算好了稅費，簽名後才會入帳。", "今天拖累最多的是環球晶。"]) {
      expect(screen.getByText(t).closest("p")).not.toHaveClass("ai-voice")
      expect(screen.getByText(t).closest("p")).toHaveClass("text-ink")
    }
    // 使用者的話是墨色 Noto Sans；追問是墨色文字連結，不是紫色
    expect(screen.getByText("台積電今天怎麼了？").closest("p")).not.toHaveClass("ai-voice")
    const follow = screen.getByRole("button", { name: "我的持股會不會太集中？" })
    expect(follow.className).toMatch(/text-ink/)
    expect(follow.className).not.toMatch(/text-ai/)
  })

  it("舊紀錄沒有標記時：連後端的對話視為模型寫的，本機的對話視為規則版", () => {
    view({ id: "t2", remoteId: "thr_1", title: "q", updatedAt: at, messages: [{ id: "a1", role: "ai", text: "後端的回答。", at }] })
    expect(screen.getByText("後端的回答。").closest("p")).toHaveClass("ai-voice")
    view({ id: "t3", title: "q", updatedAt: at, messages: [{ id: "a2", role: "ai", text: "本機的說明。", at }] })
    expect(screen.getByText("本機的說明。").closest("p")).not.toHaveClass("ai-voice")
  })
})
