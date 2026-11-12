import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { Composer } from "@/ai/Composer"
import { Conversation } from "@/ai/Conversation"
import { PanelHome } from "@/ai/Home"
import { quickActions } from "@/ai/panel-helpers"
import type { useAiRunner } from "@/ai/runner"
import { useAi } from "@/ai/store"
import type { AiContext, StockData } from "@/ai/suggestions"
import type { Draft, Thread } from "@/ai/types"

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

describe("免責只跟著回答：草稿說明（照使用者的指令算的稅費）不加", () => {
  const runner = { submit: async () => undefined } as unknown as ReturnType<typeof useAiRunner>
  beforeAll(() => {
    Element.prototype.scrollIntoView = vi.fn()
  })
  const at = "2026-11-12T13:41:00+08:00"
  it("模型的回答、規則版回答各有一行免責；草稿說明沒有", () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Conversation
          thread={{
            id: "t4",
            title: "q",
            updatedAt: at,
            messages: [
              { id: "a1", role: "ai", model: true, text: "台積電今天上漲。", disclaimer: "模型回答的免責。", at },
              { id: "a2", role: "ai", answer: { text: "今天拖累最多的是環球晶。" }, disclaimer: "規則版回答的免責。", at },
              { id: "a3", role: "ai", model: false, text: "我照你說的算好了稅費，簽名後才會入帳。", disclaimer: "草稿說明的免責。", at },
            ],
          }}
          runner={runner}
        />
      </QueryClientProvider>,
    )
    expect(screen.getByText("模型回答的免責。")).toBeInTheDocument()
    expect(screen.getByText("規則版回答的免責。")).toBeInTheDocument()
    expect(screen.queryByText("草稿說明的免責。")).not.toBeInTheDocument()
  })
})

describe("輸入框的鍵盤提示：畫面上只在有焦點時出現，螢幕閱讀器一直讀得到", () => {
  it("textarea 用 aria-describedby 指到「Enter 送出，Shift+Enter 換行」", () => {
    render(<Composer variant="panel" placeholder="提出問題" onSubmit={() => undefined} onAttach={() => undefined} />)
    const box = screen.getByRole("textbox", { name: "提出問題或下指令" })
    expect(box).toHaveAccessibleDescription("Enter 送出，Shift+Enter 換行")
  })
})

describe("面板首頁：待簽名的草稿排在第一列", () => {
  const at = "2026-11-12T13:41:00+08:00"
  const draft = (id: string, createdAt: string): Draft => ({
    id,
    status: "pending",
    input: { type: "buy" } as Draft["input"],
    instrument: { symbol: "0050.TW", code: "0050", name: "元大台灣50", market: "TWSE", currency: "TWD" },
    notes: [],
    createdAt,
  })
  const runner = { ask: vi.fn(), action: vi.fn() } as unknown as ReturnType<typeof useAiRunner>
  const suggestions = [
    { kind: "drag" as const, text: "今天誰拖累了我的報酬？" },
    { kind: "dividends_next" as const, text: "下個月我能領多少股利？" },
    { kind: "concentration" as const, text: "我的持股會不會太集中？" },
  ]
  afterEach(() => {
    vi.useRealTimers()
    act(() => useAi.setState({ threads: [], drafts: {}, threadId: null, focusDraftId: null }))
  })

  it("沒有待簽名：只有建議（最多 3 列）", () => {
    render(<PanelHome ctx={{ route: "ledger", ledger: { holdings: [] } }} runner={runner} suggestions={suggestions} size="panel" />)
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(suggestions.map((s) => s.text))
  })

  it("有待簽名：第一列「N 筆草稿等你簽名」，仍然最多 3 列；按下打開最新那份草稿所在的對話", () => {
    vi.useFakeTimers()
    act(() =>
      useAi.setState({
        drafts: { d_old: draft("d_old", "2026-11-12T09:00:00+08:00"), d_new: draft("d_new", "2026-11-12T10:00:00+08:00") },
        threads: [
          { id: "thr_old", title: "買 0050", updatedAt: at, messages: [{ id: "m1", role: "ai", draftId: "d_old", at }] },
          { id: "thr_new", title: "買 0050", updatedAt: at, messages: [{ id: "m2", role: "ai", draftId: "d_new", at }] },
        ],
        threadId: null,
      }),
    )
    render(<PanelHome ctx={{ route: "ledger", ledger: { holdings: [] } }} runner={runner} suggestions={suggestions} size="panel" />)
    const rows = screen.getAllByRole("listitem").map((li) => li.textContent)
    expect(rows).toEqual(["2 筆草稿等你簽名", "今天誰拖累了我的報酬？", "下個月我能領多少股利？"])
    fireEvent.click(screen.getByRole("button", { name: "2 筆草稿等你簽名" }))
    expect(useAi.getState().threadId).toBe("thr_new")
    expect(useAi.getState().focusDraftId).toBe("d_new")
  })
})
