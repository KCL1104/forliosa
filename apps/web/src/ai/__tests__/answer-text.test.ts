import { describe, expect, it } from "vitest"
import { cleanAnswer, DISCLAIMER, groundingReason, parseGrounding, splitUngrounded, stripDisclaimer } from "@/ai/answer-text"
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
  it("後端的固定文字「AI 回答僅供參考，非投資建議。」", () => {
    expect(stripDisclaimer("好的。\nAI 回答僅供參考，非投資建議。", "AI 回答僅供參考，非投資建議。")).toBe("好的。")
    expect(stripDisclaimer("好的。\nAI 回答僅供參考，非投資建議。")).toBe("好的。")
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
  it("後端的 GroundingItem（index、start／end、reason 代碼、signals）", () => {
    const t = "台積電今天上漲。董事會批准投資 Anthropic 與 OpenAI。"
    const items = parseGrounding({ items: [{ index: 1, start: 8, end: t.length, text: "董事會批准投資 Anthropic 與 OpenAI。", reason: "uncited_news_claim", signals: ["verb:批准"] }] })
    const seg = splitUngrounded(t, items)
    expect(seg[1]).toMatchObject({ text: "董事會批准投資 Anthropic 與 OpenAI。" })
    expect(groundingReason("uncited_news_claim")).toBe("像新聞敘述，但沒有對到任何引用的來源。")
    expect(groundingReason("some_new_code")).toBe("")
    expect(groundingReason("引用沒有涵蓋這句")).toBe("引用沒有涵蓋這句")
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
  it("off_topic（離題婉拒）照一般回答顯示：沒有來源、沒有無來源標記", () => {
    const usage = { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, web_search_requests: 0, web_fetch_requests: 0 }
    let m: Message = { id: "m2", role: "ai", text: "", streaming: true, at: "2026-11-12T13:40:00+08:00" }
    m = applyChatEvent(m, { event: "text", data: { delta: "這個我幫不上忙；想聊你的持股或台股都可以。" } })
    m = applyChatEvent(m, { event: "done", data: { thread_id: "t", turn_id: "u", model: "m", stop_reason: "off_topic", usage, disclaimer: "AI 回答僅供參考，非投資建議。" } })
    expect(m).toMatchObject({ streaming: false, disclaimer: "AI 回答僅供參考，非投資建議。", text: "這個我幫不上忙；想聊你的持股或台股都可以。" })
    expect(m.citations).toBeUndefined()
    expect(m.ungrounded).toBeUndefined()
    expect(m.error).toBeUndefined()
  })
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

describe("cleanAnswer：模型寫出 Markdown 符號時，畫面上不出現那些符號", () => {
  it("粗體、底線、反引號的記號拿掉，字留著", () => {
    expect(cleanAnswer("**結論：持股集中在半導體。** 台積電占 35.7%")).toBe("結論：持股集中在半導體。 台積電占 35.7%")
    expect(cleanAnswer("__前三大__合計 `72.6%`")).toBe("前三大合計 72.6%")
  })

  it("行首的標題記號拿掉；- 與 * 條列換成「・」，已經是「・」的不重複", () => {
    expect(cleanAnswer("## 重點\n- 台積電 35.7%\n* 鴻海 21.9%\n・0050 15.0%\n• 環球晶")).toBe("重點\n・台積電 35.7%\n・鴻海 21.9%\n・0050 15.0%\n・環球晶")
    expect(cleanAnswer("・**單一個股：** 台積電 35.7%")).toBe("・單一個股： 台積電 35.7%")
  })

  it("串流到一半（後半的記號還沒到）也不露出星號", () => {
    expect(cleanAnswer("**結論：持股集")).toBe("結論：持股集")
  })

  it("[文字](網址) 只留文字；一般的字、負號、乘號與 ▲▼ 不動", () => {
    expect(cleanAnswer("詳見[證交所公告](https://www.twse.com.tw/x)。")).toBe("詳見證交所公告。")
    const plain = "今天賠，帳上市值下跌 80,062 元（▼1.44%）。\n均價 692.61 × 1,500 股；-3.5% 到 +2.1%"
    expect(cleanAnswer(plain)).toBe(plain)
  })

  it("標出「無來源」的段落：回答清過符號之後仍然對得上", () => {
    const raw = "・**除息：** 006208 已公告 11/17 除息。\n其他內容"
    const segments = splitUngrounded(cleanAnswer(raw), [{ text: "・**除息：** 006208 已公告 11/17 除息。", reason: "uncited_news_claim" }])
    expect(segments.find((x) => x.ungrounded)?.text).toBe("・除息： 006208 已公告 11/17 除息。")
  })
})
