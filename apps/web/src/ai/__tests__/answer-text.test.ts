import { describe, expect, it } from "vitest"
import { DISCLAIMER, parseGrounding, splitUngrounded, stripDisclaimer } from "@/ai/answer-text"
import { applyChatEvent } from "@/ai/remote"
import type { Message } from "@/ai/types"

describe("免責聲明由介面固定顯示：模型最後一行同樣的話不重複", () => {
  it("最後一行就是免責聲明：整行拿掉", () => {
    expect(stripDisclaimer(`台積電今天上漲 4.8%。\n${DISCLAIMER}`)).toBe("台積電今天上漲 4.8%。")
    expect(stripDisclaimer("台積電今天上漲。\n\n僅供參考，非投資建議。\n")).toBe("台積電今天上漲。")
  })
  it("同一行有資料時間：保留時間，只拿掉免責那一句", () => {
    expect(stripDisclaimer("鴻海今天平盤。\n資料至 11/12 13:30，僅供參考，非投資建議。")).toBe("鴻海今天平盤。\n資料至 11/12 13:30")
  })
  it("後端給的 disclaimer 文字優先比對", () => {
    expect(stripDisclaimer("好的。\n以上內容不構成任何建議。", "以上內容不構成任何建議。")).toBe("好的。")
  })
  it("沒有免責聲明、或只是句中提到「投資建議」：不動", () => {
    const t = "我不能給投資建議，但可以說明你的持股。"
    expect(stripDisclaimer(t)).toBe(t)
    expect(stripDisclaimer("")).toBe("")
  })
})

describe("無來源段落", () => {
  const text = "台積電 10 月營收年增 59.7%。外資連四天賣超。這是你的第三大持股。"
  it("依文字找到段落並切成片段；位置對不上時改用文字比對", () => {
    const seg = splitUngrounded(text, [{ text: "外資連四天賣超。", reason: "沒有引用", start: 0, end: 3 }])
    expect(seg.map((s) => s.text).join("")).toBe(text)
    expect(seg.filter((s) => s.ungrounded).map((s) => s.text)).toEqual(["外資連四天賣超。"])
  })
  it("start／end 正確時用位置；找不到的段落略過，不改動文字", () => {
    const start = text.indexOf("這是")
    const seg = splitUngrounded(text, [{ text: "這是你的第三大持股。", start, end: start + 10 }, { text: "不存在的一句" }])
    expect(seg).toHaveLength(2)
    expect(seg[1]).toMatchObject({ text: "這是你的第三大持股。" })
    expect(splitUngrounded(text, [])).toEqual([{ text }])
  })
  it("重疊的段落只標一次", () => {
    const seg = splitUngrounded(text, [{ text: "外資連四天賣超。" }, { text: "連四天賣超" }])
    expect(seg.filter((s) => s.ungrounded)).toHaveLength(1)
  })
  it("grounding 事件的資料容錯：{items}、陣列、單一物件、壞資料", () => {
    expect(parseGrounding({ items: [{ text: "A", reason: "r", start: 1, end: 2 }] })).toEqual([{ text: "A", reason: "r", start: 1, end: 2 }])
    expect(parseGrounding([{ passage: "B" }])).toEqual([{ text: "B", reason: null, start: null, end: null }])
    expect(parseGrounding({ text: "C" })).toHaveLength(1)
    expect(parseGrounding({ items: [{ text: "  " }, 3, null] })).toEqual([])
    expect(parseGrounding(null)).toEqual([])
  })
})

describe("串流 reducer：grounding 與 done.disclaimer", () => {
  const base: Message = { id: "m1", role: "ai", text: "外資連四天賣超。", streaming: true, at: "2026-11-12T13:40:00+08:00" }
  it("grounding 累加段落並去重", () => {
    const once = applyChatEvent(base, { event: "grounding", data: { items: [{ text: "外資連四天賣超。", reason: "沒有引用" }] } })
    const twice = applyChatEvent(once, { event: "grounding", data: { items: [{ text: "外資連四天賣超。" }, { text: "另一句" }] } })
    expect(twice.ungrounded?.map((u) => u.text)).toEqual(["外資連四天賣超。", "另一句"])
    expect(applyChatEvent(base, { event: "grounding", data: { items: [] } })).toBe(base)
  })
  it("done 帶 disclaimer 時存在訊息上，並結束串流", () => {
    const usage = { input_tokens: 1, output_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, web_search_requests: 0, web_fetch_requests: 0 }
    const done = applyChatEvent(base, { event: "done", data: { thread_id: "t", turn_id: "u", model: "m", stop_reason: "end_turn", usage, disclaimer: "AI 回答僅供參考。" } })
    expect(done).toMatchObject({ streaming: false, disclaimer: "AI 回答僅供參考。" })
    const noText = applyChatEvent(base, { event: "done", data: { thread_id: "t", turn_id: "u", model: "m", stop_reason: "end_turn", usage } })
    expect(noText.disclaimer).toBeUndefined()
  })
})
