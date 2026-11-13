import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { Composer } from "@/ai/Composer"
import { kaiRuns } from "@/ai/answer-text"
import { AiText, Conversation } from "@/ai/Conversation"
import { PanelHome } from "@/ai/Home"
import { composerPlaceholder, quickActions } from "@/ai/panel-helpers"
import type { useAiRunner } from "@/ai/runner"
import { useAi } from "@/ai/store"
import type { AiContext, StockData } from "@/ai/suggestions"
import type { Draft, Thread } from "@/ai/types"

const withQuery = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const stock = (p: Partial<StockData>): AiContext => ({
  route: "stock",
  stock: { symbol: "2330.TW", code: "2330", name: "台積電", market: "TWSE", type: "stock", ...p },
})

describe("面板的常用動作：一行文字連結，只放這一頁真的能做的事", () => {
  it("帳本：沒有常用動作（「記一筆」在工具列，台股股利自動入帳）", () => {
    expect(quickActions({ route: "ledger", ledger: { holdings: [] } })).toEqual([])
  })
  it("個股頁：只有持有美股時有「股利入帳」（美股股利沒有來源）；「記一筆」在標題列，不放第二條", () => {
    expect(quickActions(stock({ position: { quantity: 1500 } as StockData["position"] }))).toEqual([])
    expect(quickActions(stock({ symbol: "AAPL", code: "AAPL", name: "Apple", market: "US", position: null }))).toEqual([])
    const us = quickActions(stock({ symbol: "AAPL", code: "AAPL", name: "Apple", market: "US", position: { quantity: 40 } as StockData["position"] }))
    expect(us.map((a) => [a.label, a.run, a.code])).toEqual([["股利入帳", "dividend", "AAPL"]])
  })
  it("群組與其他頁（設定、資料來源、紀錄）：沒有常用動作", () => {
    expect(quickActions({ route: "groups" })).toEqual([])
    expect(quickActions({ route: "other" })).toEqual([])
  })
})

describe("對話的兩支筆：模型寫的字是石墨灰楷體，規則或範本寫的句子是墨色 Noto Sans", () => {
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
        { id: "a2", role: "ai", model: false, text: "照你說的算好了稅費，你看一下。", at },
        { id: "a3", role: "ai", answer: { text: "今天拖累最多的是環球晶。", followUps: ["我的持股會不會太集中？"] }, at },
      ],
    })
    expect(screen.getByText("台積電今天上漲。").closest("p")).toHaveClass("ai-voice")
    for (const t of ["照你說的算好了稅費，你看一下。", "今天拖累最多的是環球晶。"]) {
      expect(screen.getByText(t).closest("p")).not.toHaveClass("ai-voice")
      expect(screen.getByText(t).closest("p")).toHaveClass("text-ink")
    }
    // 使用者的話是墨色 Noto Sans；追問是墨色文字連結，不是石墨灰
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

describe("免責只跟著回答，一段對話只出現一次：在最新一則回答下方；草稿說明（照使用者的指令算的稅費）不加", () => {
  const runner = { submit: async () => undefined } as unknown as ReturnType<typeof useAiRunner>
  beforeAll(() => {
    Element.prototype.scrollIntoView = vi.fn()
  })
  const at = "2026-11-12T13:41:00+08:00"
  const view = (messages: Thread["messages"]) =>
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Conversation thread={{ id: "t4", title: "q", updatedAt: at, messages }} runner={runner} />
      </QueryClientProvider>,
    )

  it("兩則回答＋草稿說明：只有最新那則回答（規則版）下方有免責；較早的模型回答與草稿說明沒有", () => {
    view([
      { id: "a1", role: "ai", model: true, text: "台積電今天上漲。", disclaimer: "模型回答的免責。", at },
      { id: "a2", role: "ai", answer: { text: "今天拖累最多的是環球晶。" }, disclaimer: "規則版回答的免責。", at },
      { id: "a3", role: "ai", model: false, text: "照你說的算好了稅費，你看一下。", disclaimer: "草稿說明的免責。", at },
    ])
    expect(screen.getByText("規則版回答的免責。")).toBeInTheDocument()
    expect(screen.queryByText("模型回答的免責。")).not.toBeInTheDocument()
    expect(screen.queryByText("草稿說明的免責。")).not.toBeInTheDocument()
  })

  it("最新的回答還在寫：先不出現免責（也不留在上一則下面）", () => {
    view([
      { id: "a1", role: "ai", model: true, text: "第一則。", disclaimer: "第一則的免責。", at },
      { id: "u2", role: "user", text: "再問一次", at },
      { id: "a2", role: "ai", model: true, text: "寫到一半", streaming: true, at },
    ])
    expect(screen.queryByText("第一則的免責。")).not.toBeInTheDocument()
    expect(screen.queryByText("AI 回答僅供參考，非投資建議。")).not.toBeInTheDocument()
  })
})

describe("回答的出處與連結：出處是編號的註腳；只有離開本站的連結有 ↗，站內的去處用 →", () => {
  const runner = { submit: async () => undefined } as unknown as ReturnType<typeof useAiRunner>
  beforeAll(() => {
    Element.prototype.scrollIntoView = vi.fn()
  })
  const at = "2026-11-12T13:41:00+08:00"

  it("出處：一個標籤＋編號清單（標題 — 網域），標題是另開新視窗的連結；沒有「來源」框框", () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Conversation
          thread={{
            id: "t5",
            title: "q",
            updatedAt: at,
            messages: [
              {
                id: "a1",
                role: "ai",
                model: true,
                text: "台積電今天上漲 4.83%。",
                citations: [
                  { url: "https://mops.twse.com.tw/", title: "公開資訊觀測站", cited_text: "營收" },
                  { url: "https://www.example.com/news/1", title: "外資連三買", cited_text: "" },
                  { url: "https://mops.twse.com.tw/", title: "公開資訊觀測站", cited_text: "重複的不再列" },
                ],
                at,
              },
            ],
          }}
          runner={runner}
        />
      </QueryClientProvider>,
    )
    const list = screen.getByRole("list", { name: "出處" })
    const items = within(list).getAllByRole("listitem")
    expect(items.map((li) => li.textContent)).toEqual(["1公開資訊觀測站（另開新視窗） — mops.twse.com.tw", "2外資連三買（另開新視窗） — example.com"])
    const link = within(items[0]!).getByRole("link", { name: /公開資訊觀測站/ })
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("title", "營收")
    expect(screen.queryByText("來源")).not.toBeInTheDocument()
  })
})

describe("模型回答的排版：漢字片段收字距，數字和單位連成一段", () => {
  it("切成漢字、數字（含單位）、其他", () => {
    expect(kaiRuns("台積電今天上漲 4.83%，收在 1,085 元，帳上多了 NT$75,000。")).toEqual([
      { kind: "han", text: "台積電今天上漲" },
      { kind: "plain", text: " " },
      { kind: "num", text: "4.83%" },
      { kind: "han", text: "，收在" },
      { kind: "plain", text: " " },
      { kind: "num", text: "1,085 元" },
      { kind: "han", text: "，帳上多了" },
      { kind: "plain", text: " " },
      { kind: "num", text: "NT$75,000" },
      { kind: "han", text: "。" },
    ])
    // 「1 張」「500 股」各自一段（中間可以換行）；換行不會被吃進數字裡
    expect(kaiRuns("持有 1 張 500 股\n−NT$1,056").filter((r) => r.kind === "num").map((r) => r.text)).toEqual(["1 張", "500 股", "−NT$1,056"])
    expect(kaiRuns("12\n元").map((r) => r.kind)).toEqual(["num", "plain", "han"])
  })

  it("模型的回答用片段排：數字與單位是不斷行的一段", () => {
    render(<AiText text="收在 1,085 元。" size="panel" />)
    const num = screen.getByText("1,085 元")
    expect(num).toHaveClass("kai-num")
    expect(num.closest("p")).toHaveClass("ai-voice")
    expect(screen.getByText("。")).toHaveClass("kai-han")
  })
})

describe("輸入框的鍵盤提示：畫面上只在有焦點時出現，螢幕閱讀器一直讀得到", () => {
  it("textarea 用 aria-describedby 指到「Enter 送出，Shift+Enter 換行」", () => {
    withQuery(<Composer variant="panel" placeholder="提出問題" onSubmit={() => undefined} onForm={() => undefined} />)
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
    withQuery(<PanelHome ctx={{ route: "ledger", ledger: { holdings: [] } }} runner={runner} suggestions={suggestions} size="panel" />)
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
    withQuery(<PanelHome ctx={{ route: "ledger", ledger: { holdings: [] } }} runner={runner} suggestions={suggestions} size="panel" />)
    const rows = screen.getAllByRole("listitem").map((li) => li.textContent)
    expect(rows).toEqual(["2 筆草稿等你簽名", "今天誰拖累了我的報酬？", "下個月我能領多少股利？"])
    fireEvent.click(screen.getByRole("button", { name: "2 筆草稿等你簽名" }))
    expect(useAi.getState().threadId).toBe("thr_new")
    expect(useAi.getState().focusDraftId).toBe("d_new")
  })
})

describe("沒有建議的頁面（設定、資料來源、紀錄）：輸入框上方是最近 3 段對話，按下接著那段對話", () => {
  const runner = { ask: vi.fn(), action: vi.fn(), submit: vi.fn() } as unknown as ReturnType<typeof useAiRunner>
  const t = (id: string, title: string, updatedAt: string): Thread => ({ id, title, updatedAt, messages: [{ id: `m_${id}`, role: "user", text: title, at: updatedAt }] })
  afterEach(() => {
    act(() => useAi.setState({ threads: [], drafts: {}, threadId: null, hiddenThreadIds: [] }))
  })

  it("依更新時間列出最近 3 段（含 mock 的示範紀錄），有「全部對話」；按下打開那段對話", () => {
    act(() => useAi.setState({ threads: [t("thr_a", "我自己問過的問題", new Date().toISOString())], threadId: null }))
    const showHistory = vi.fn()
    withQuery(<PanelHome ctx={{ route: "other" }} runner={runner} suggestions={[]} size="panel" onShowHistory={showHistory} />)
    const list = screen.getByRole("list", { name: "最近的對話" })
    const rows = within(list).getAllByRole("listitem")
    expect(rows).toHaveLength(3)
    expect(rows[0]!.textContent).toMatch(/^我自己問過的問題剛剛$/)
    fireEvent.click(within(rows[0]!).getByRole("button", { name: "我自己問過的問題" }))
    expect(useAi.getState().threadId).toBe("thr_a")
    fireEvent.click(screen.getByRole("button", { name: "全部對話" }))
    expect(showHistory).toHaveBeenCalled()
  })

  it("有建議或常用動作的頁面不列最近的對話", () => {
    withQuery(<PanelHome ctx={{ route: "groups" }} runner={runner} suggestions={[{ kind: "group_share", text: "群組會分享我的哪些資料？" }]} size="panel" />)
    expect(screen.queryByRole("list", { name: "最近的對話" })).not.toBeInTheDocument()
  })
})

describe("輸入框的提示字依頁面：只有帳本與個股頁給交易的例子，美股用「股」", () => {
  it("帳本、台股、美股、其他頁", () => {
    expect(composerPlaceholder({ route: "ledger", ledger: { holdings: [] } }, "panel")).toBe("提出問題，或直接說：買 0050 2 張 52.4")
    expect(composerPlaceholder(stock({}), "panel")).toBe("問台積電的事，或說：買 2330 1 張")
    const aapl = stock({ symbol: "AAPL", code: "AAPL", name: "Apple", market: "US" })
    expect(composerPlaceholder(aapl, "panel")).toBe("問 AAPL 的事，或說：買 AAPL 10 股")
    expect(composerPlaceholder(aapl, "screen")).toBe("搜尋，或說：買 AAPL 10 股")
    for (const ctx of [{ route: "groups" }, { route: "other" }] as AiContext[]) {
      expect(composerPlaceholder(ctx, "panel")).not.toMatch(/買|張/)
      expect(composerPlaceholder(ctx, "screen")).not.toMatch(/買|張/)
    }
  })
})
