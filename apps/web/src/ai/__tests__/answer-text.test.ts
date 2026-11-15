import { describe, expect, it } from "vitest"
import { cleanAnswer, DISCLAIMER, groundingReason, markNeedle, parseGrounding, splitUngrounded, stripDisclaimer, tidyAnswer } from "@/ai/answer-text"
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

describe("回答是 Markdown（產品負責人 2026-11-15）：顯示前只換舊的條列、藏起串流中落單的星號", () => {
  it("Markdown 原樣保留；舊的「・」「•」條列換成 `- `", () => {
    const md = "**結論**：持股集中在半導體。\n- 台積電 35.7%\n1. 鴻海\n| 代號 | 漲跌 |\n|---|---|\n| 2330 | ▲0.4% |"
    expect(cleanAnswer(md)).toBe(md)
    expect(cleanAnswer("・台積電 35.7%\n• 環球晶")).toBe("- 台積電 35.7%\n- 環球晶")
  })

  it("串流到一半（後半的 ** 還沒到）：最後一個落單的 ** 先拿掉；寫完之後不動", () => {
    expect(cleanAnswer("**結論：持股集", { streaming: true })).toBe("結論：持股集")
    expect(cleanAnswer("**結論**：持股集中", { streaming: true })).toBe("**結論**：持股集中")
  })
})

describe("tidyAnswer：模型固定的小毛病交給程式整理", () => {
  const year = 2026
  it("民國年與「2026年11月12日」→ 月/日；不是今年才寫年份；「今（13）日」→「13 日」", () => {
    expect(tidyAnswer("將於 115 年 12 月 21 日終止上市，2026年11月12日公布。", { year })).toBe("將於 12/21 終止上市，11/12 公布。")
    expect(tidyAnswer("2025年12月31日封關", { year })).toBe("2025/12/31封關")
    expect(tidyAnswer("台股今（13）日開高，今（12日）收黑", { year })).toBe("台股13 日開高，12 日收黑")
  })

  it("括號裡交代出處的說明拿掉；括號裡是資料時間或代號的不動；Markdown 連結不動", () => {
    expect(tidyAnswer("12/21 終止上市（公開資訊觀測站）。淨值為負（PChome 新聞 11/11、鏡週刊 11/12）。")).toBe("12/21 終止上市。淨值為負。")
    expect(tidyAnswer("漲 7.01%（資料來自工具）。外資賣超（資料來源：Yahoo 股市）。")).toBe("漲 7.01%。外資賣超。")
    expect(tidyAnswer("收 2350 元（11/13 收盤資料），台積電（2330）")).toBe("收 2350 元（11/13 收盤資料），台積電（2330）")
    expect(tidyAnswer("見[鉅亨新聞](https://news.cnyes.com/a)")).toBe("見[鉅亨新聞](https://news.cnyes.com/a)")
  })

  it("照貼回來的出處清單（整行就是引用的標題）與「資料來源：」行拿掉", () => {
    const titles = ["公告本公司有價證券將於115年12月21日終止上市", "台揚財報淨值為負數12/21終止上市 股價跳空跌停"]
    const raw = "台揚跌停。\n\n公開資訊觀測站，11/10：公告本公司有價證券將於115年12月21日終止上市\n- 11/11：台揚財報淨值為負數12/21終止上市 股價跳空跌停\n資料來源：PChome"
    expect(tidyAnswer(raw, { titles, year })).toBe("台揚跌停。\n")
  })

  it("說到「工具」的片語換掉；清單之間的空行與漏出來的 <cite> 拿掉", () => {
    expect(tidyAnswer("工具資料顯示近四季虧損。0050 的股利目前工具沒有顯示。")).toBe("資料顯示近四季虧損。0050 的股利目前沒有。")
    expect(tidyAnswer("工具顯示近四季 EPS 小於 0。估值工具沒有提供數字，依工具資料自行計算")).toBe("資料顯示近四季 EPS 小於 0。目前沒有數字，依資料自行計算")
    expect(tidyAnswer("- 第一點\n\n- 第二點</cite>")).toBe("- 第一點\n- 第二點")
  })

  it("「無來源」的段落：整理過、拿掉格式記號之後，和畫面上的字對得上", () => {
    expect(markNeedle("- **除息**：006208 已公告 115 年 11 月 17 日除息（公開資訊觀測站）。", { year })).toBe("除息：006208 已公告 11/17 除息。")
  })
})
