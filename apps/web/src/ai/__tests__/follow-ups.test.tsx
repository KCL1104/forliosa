import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { Conversation } from "@/ai/Conversation"
import { applyChatEvent, followUpsOf, threadFromServer } from "@/ai/remote"
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
