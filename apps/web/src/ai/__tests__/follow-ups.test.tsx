import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { Conversation } from "@/ai/Conversation"
import { applyChatEvent, followUpsOf, threadFromServer, type AiChart } from "@/ai/remote"
import type { useAiRunner } from "@/ai/runner"
import type { Message, Thread } from "@/ai/types"

/**
 * 接著問（產品負責人 2026-11-26）：模型最後給 2–3 個問題（`follow_ups` 事件、對話紀錄的 `follow_ups`），
 * 只顯示在最新一則寫完的回答下方，點了就問。
 */
const at = "2026-11-26T20:00:00+08:00"
const withQuery = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})
afterEach(cleanup)

describe("follow_ups 事件與對話紀錄", () => {
  const start: Message = { id: "m1", role: "ai", text: "11/27 的重點在台達電除息。", streaming: true, at }

  it("收下 2–3 題；壞掉或空的不改訊息", () => {
    const m = applyChatEvent(start, { event: "follow_ups", data: { questions: ["台達電配多少股利？", " 台積電法說會說了什麼？ ", "", 3 as never] } })
    expect(m.followUps).toEqual(["台達電配多少股利？", "台積電法說會說了什麼？"])
    expect(applyChatEvent(start, { event: "follow_ups", data: { questions: [] } })).toBe(start)
    expect(followUpsOf("台達電？")).toEqual([])
    expect(followUpsOf(["一", "二", "三", "四", "五", "六"])).toEqual(["一", "二", "三", "四", "五"])
  })

  it("重新打開對話時帶回來；舊的紀錄沒有這個欄位也沒關係", () => {
    const { thread } = threadFromServer({
      id: "thr_1",
      title: "明天",
      model: "m",
      created_at: at,
      updated_at: at,
      messages: [
        { id: "1", turn_id: "t", role: "user", text: "明天可以關注哪些個股？", citations: [], drafts: [], tools: [], error: null, at },
        { id: "2", turn_id: "t", role: "ai", text: "整理好了。", citations: [], drafts: [], tools: [], error: null, follow_ups: ["台達電配多少股利？"], at },
        { id: "3", turn_id: "u", role: "ai", text: "舊的。", citations: [], drafts: [], tools: [], error: null, at },
      ],
    })
    expect(thread.messages[1]!.followUps).toEqual(["台達電配多少股利？"])
    expect(thread.messages[2]!.followUps).toBeUndefined()
  })
})

describe("回答下方的圖表（產品負責人 2026-11-27：等回答寫完才出現）", () => {
  const runner = { submit: vi.fn() } as unknown as ReturnType<typeof useAiRunner>
  const chart: AiChart = {
    id: "cht_1", kind: "compare", title: "台積電、鴻海 漲跌幅（近 3 個月）", unit: "pct", currency: null, x: "date", range: "3M",
    series: [
      { name: "台積電", symbol: "2330.TW", points: [{ t: "2026-11-25", v: 0 }, { t: "2026-11-26", v: 0.01 }, { t: "2026-11-27", v: 0.02 }] },
      { name: "鴻海", symbol: "2317.TW", points: [{ t: "2026-11-25", v: 0 }, { t: "2026-11-26", v: -0.01 }, { t: "2026-11-27", v: -0.02 }] },
    ],
    notes: [], sources: ["臺灣證券交易所〈上市個股日成交資訊〉"], is_demo: false,
  }
  const show = (ai: Partial<Message>) =>
    withQuery(
      <Conversation
        thread={{ id: "t1", title: "t", updatedAt: at, messages: [{ id: "u1", role: "user", text: "下禮拜可以買什麼？", at }, { id: "a1", role: "ai", model: true, text: "", at, ...ai }] }}
        runner={runner}
      />,
    )
  const figure = () => screen.queryByRole("figure", { name: chart.title })

  it("圖的事件先到（模型先畫圖再寫回答）：還沒有字、或字還在寫的時候不放圖", () => {
    // 事件照樣收進訊息裡，只是先不畫
    const start: Message = { id: "a1", role: "ai", model: true, text: "", streaming: true, at }
    const got = applyChatEvent(start, { event: "chart", data: chart })
    expect(got.charts).toEqual([chart])
    const first = show(got)
    expect(figure()).toBeNull()
    first.unmount()
    show({ ...got, text: "11/30 到 12/4 的重點在台積電法說會" })
    expect(figure()).toBeNull()
  })

  it("回答寫完：圖在回答下面、接著問上面", () => {
    show({ text: "11/30 到 12/4 的重點在台積電法說會。", charts: [chart], followUps: ["台積電法說會說了什麼？"] })
    const fig = figure()!
    expect(fig).toBeInTheDocument()
    const answer = screen.getByText(/的重點在台積電法說會/)
    const list = screen.getByRole("list", { name: "接著問" })
    expect(answer.compareDocumentPosition(fig) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(fig.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("中途出錯的回答：已經畫好的圖照樣顯示", () => {
    show({ text: "11/30 到 12/4 的重點", charts: [chart], error: { code: "ai_unavailable", message: "AI 暫時沒有回應" } })
    expect(figure()).toBeInTheDocument()
  })
})

describe("回答下方的接著問", () => {
  const submit = vi.fn()
  const runner = { submit } as unknown as ReturnType<typeof useAiRunner>
  const thread = (messages: Message[]): Thread => ({ id: "t1", title: "t", updatedAt: at, messages })

  it("最新一則回答下方，點了就問；較早的回答與還在寫的回答不顯示", () => {
    withQuery(
      <Conversation
        thread={thread([
          { id: "u1", role: "user", text: "我有哪些持股？", at },
          { id: "a1", role: "ai", model: true, text: "你持有台積電。", followUps: ["台積電最近有什麼新聞？"], at },
          { id: "u2", role: "user", text: "明天可以關注哪些個股？", at },
          { id: "a2", role: "ai", model: true, text: "11/27 的重點在台達電除息。", followUps: ["台達電配多少股利？", "台積電法說會說了什麼？"], at },
        ])}
        runner={runner}
      />,
    )
    const lists = screen.getAllByRole("list", { name: "接著問" })
    expect(lists).toHaveLength(1)
    expect(screen.queryByText("台積電最近有什麼新聞？")).toBeNull()
    const buttons = within(lists[0]!).getAllByRole("button")
    expect(buttons.map((b) => b.textContent)).toEqual(["台達電配多少股利？", "台積電法說會說了什麼？"])
    fireEvent.click(buttons[0]!)
    expect(submit).toHaveBeenCalledWith("台達電配多少股利？")
    // 免責在接著問的下面（一段對話一次）
    const disclaimer = screen.getByText(/AI 只替你整理資訊/)
    expect(lists[0]!.compareDocumentPosition(disclaimer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 每一行前面一個淡墨的 ↳（不讀給螢幕閱讀器）
    expect(lists[0]!.querySelectorAll("svg[aria-hidden='true']")).toHaveLength(2)
  })

  it("緊接在回答下面、出處上面", () => {
    withQuery(
      <Conversation
        thread={thread([
          { id: "u1", role: "user", text: "台積電最近怎麼了？", at },
          {
            id: "a1",
            role: "ai",
            model: true,
            text: "台積電 11/26 收 2,145 元。",
            citations: [{ url: "https://www.cna.com.tw/news/1", title: "台積電法說會", cited_text: "x" }],
            followUps: ["台積電法說會說了什麼？", "台積電的本益比和過去五年比如何？", "台積電下次除息是什麼時候？"],
            at,
          },
        ])}
        runner={runner}
      />,
    )
    const list = screen.getByRole("list", { name: "接著問" })
    const source = screen.getByRole("link", { name: /台積電法說會/ })
    expect(list.compareDocumentPosition(source) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("還在寫、或出錯的回答不顯示", () => {
    withQuery(
      <Conversation
        thread={thread([
          { id: "u1", role: "user", text: "明天可以關注哪些個股？", at },
          { id: "a1", role: "ai", model: true, text: "11/27 的重點", streaming: true, followUps: ["台達電配多少股利？"], at },
        ])}
        runner={runner}
      />,
    )
    expect(screen.queryByRole("list", { name: "接著問" })).toBeNull()
  })
})
