import { describe, expect, it } from "vitest"
import { cleanAnswer, DISCLAIMER, dropAiHabits, groundingReason, markNeedle, parseGrounding, splitUngrounded, stripDisclaimer, tidyAnswer } from "@/ai/answer-text"
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
    expect(tidyAnswer("這是我用工具數字自行算的")).toBe("這是我用數字自行算的")
    expect(tidyAnswer("- 第一點\n\n- 第二點</cite>")).toBe("- 第一點\n- 第二點")
  })

  it("「無來源」的段落：整理過、拿掉格式記號之後，和畫面上的字對得上", () => {
    expect(markNeedle("- **除息**：006208 已公告 115 年 11 月 17 日除息（公開資訊觀測站）。", { year })).toBe("除息：006208 已公告 11/17 除息。")
  })
})

describe("dropAiHabits：模型談自己的固定寫法（2026-11-26 常見問題實測）", () => {
  it("開頭交代要做什麼的一行拿掉；只有這一行時不動", () => {
    expect(dropAiHabits("我先查兩檔的基本資料、估值與財報。\n\n兩檔各有優勢。")).toBe("兩檔各有優勢。")
    expect(dropAiHabits("我先查一下。")).toBe("我先查一下。")
    expect(dropAiHabits("台積電 11/26 收 2,145 元。")).toBe("台積電 11/26 收 2,145 元。")
  })

  it("說自己不替使用者決定：整句拿掉；接「，但…」只拿掉前半，後面的事實留著", () => {
    expect(dropAiHabits("我不能替你判斷現在該不該買。以下是台積電的資料。")).toBe("以下是台積電的資料。")
    expect(dropAiHabits("我不能替你決定要不要停損，但目前的數字是：你持有鴻海 5,000 股。")).toBe("目前的數字是：你持有鴻海 5,000 股。")
    expect(dropAiHabits("這沒有標準答案，要看你的投資期間。我不替你判斷好不好，但可以把幾個面向講清楚。")).toBe("這沒有標準答案，要看你的投資期間。")
    expect(dropAiHabits("我不能判斷現在適不適合進場，這要看你自己的資金。我可以提供的是目前的市場與你持股的事實。")).toBe("這要看你自己的資金。")
    expect(dropAiHabits("我不替你選一檔。這三檔的差別在配息。")).toBe("這三檔的差別在配息。")
    // 不是在說自己的不動
    expect(dropAiHabits("券商不能替你決定，法人也是。")).toBe("券商不能替你決定，法人也是。")
  })

  it("說自己不知道漲跌、也不替你挑（產品負責人 2026-11-27）：拿掉，後面的結論留著當第一句", () => {
    // 負責人截圖的那一則回答的第一句
    const seen = "下週要買什麼，漲跌沒辦法事先知道，我也不替你挑。下面是 11/30 到 12/4 已排定的事和市場焦點。重點是 11/30 台積電法說會。"
    expect(dropAiHabits(seen)).toBe("下面是 11/30 到 12/4 已排定的事和市場焦點。重點是 11/30 台積電法說會。")
    expect(dropAiHabits("明天哪檔會漲沒辦法預測。11/27 的重點在台達電除息。")).toBe("11/27 的重點在台達電除息。")
    expect(dropAiHabits("股價無法事先知道，但 11/27 有兩場法說會。")).toBe("但 11/27 有兩場法說會。")
    expect(dropAiHabits("我也不替你挑。這三檔的差別在配息。")).toBe("這三檔的差別在配息。")
    // 同一句前面有數字的那半句留著；不是在說漲跌的不動
    expect(dropAiHabits("台積電 11/27 收 2,145 元，之後的漲跌沒辦法事先知道。")).toBe("台積電 11/27 收 2,145 元。")
    expect(dropAiHabits("台積電 2,145 元之後的漲跌無法預測。")).toBe("台積電 2,145 元之後的漲跌無法預測。")
    expect(dropAiHabits("公司表示目前無法預測下一季的營收。")).toBe("公司表示目前無法預測下一季的營收。")
  })

  it("結尾的提議與交代資料的句子：寫完才拿；有數字的句子不動", () => {
    const answer = "集中度偏高。\n\n- 台積電佔 36%。\n\n如果你想看某一檔的走勢，告訴我股票代號就可以查。"
    expect(dropAiHabits(answer)).toBe("集中度偏高。\n\n- 台積電佔 36%。")
    expect(dropAiHabits(answer, { streaming: true })).toBe(answer)
    expect(dropAiHabits("外資連 9 天賣超。\n\n以上是媒體整理的外資買賣超統計，不是 Forliosa 的逐檔數據。")).toBe("外資連 9 天賣超。")
    expect(dropAiHabits("台股漲 2.5%。\n\n收盤數字以官方資料為準。")).toBe("台股漲 2.5%。")
    expect(dropAiHabits("最高到 4,410 元。這些是較早的消息，之後的調整以最新消息為準。")).toBe("最高到 4,410 元。")
    expect(dropAiHabits("你可以到帳本看殖利率，我可以幫你整理。")).toBe("")
    expect(dropAiHabits("如果想比較，可以再問我 3 個問題。")).toBe("如果想比較，可以再問我 3 個問題。")
    expect(dropAiHabits("目前沒有下一次除息日期的資料。")).toBe("目前沒有下一次除息日期的資料。")
  })

  it("第二輪實測：寫成文字的接著問、<br>、「…，我先查…」的開場、「以上…資料」的結尾", () => {
    expect(dropAiHabits('算不出來。\n\nsuggest_follow_ups({"questions": ["a？"]})')).toBe("算不出來。")
    expect(dropAiHabits("算不出來。\n\nsuggest_follow_ups({\"ques", { streaming: true })).toBe("算不出來。\n\n")
    expect(dropAiHabits("- 11/27 除權。\n\n<br>\n\n- 12/1 除息。")).toBe("- 11/27 除權。\n\n- 12/1 除息。")
    expect(dropAiHabits("判斷高股息 ETF 通常看殖利率，我先查幾檔常見的標的。\n\n選哪一檔，通常看選股邏輯。")).toBe("選哪一檔，通常看選股邏輯。")
    expect(dropAiHabits("- 神達 11/27 除權。\n\n以上日期與金額為官方公告資料。")).toBe("- 神達 11/27 除權。")
    // 日期只寫在這一句：留著
    expect(dropAiHabits("電子零組件最強。\n\n以上是 11/26 收盤數據。")).toBe("電子零組件最強。\n\n以上是 11/26 收盤數據。")
    expect(dropAiHabits("| 收盤（11/26） | 2,145 元 |\n\n以上是收盤後的官方資料，本益比為 11/26 的數字。")).toBe("| 收盤（11/26） | 2,145 元 |")
  })

  it("第三輪實測：句中的「我再找…」與結尾的「這裡不替你決定」", () => {
    expect(dropAiHabits("三檔的收盤價已查到，但費用目前沒有，我再找公開資料。這三檔差在選股方式。\n\n| a | b |")).toBe("這三檔差在選股方式。\n\n| a | b |")
    expect(dropAiHabits("- 美銀 11/17 重申 3,260 元。\n\n以上是目前能查到的資料。買或不買取決於你的持股比例，這裡不替你決定。")).toBe("- 美銀 11/17 重申 3,260 元。")
    expect(dropAiHabits("台股漲 2.5%。\n\n以上原因來自盤中報導，收盤後的完整原因目前沒有更多報導可引用。")).toBe("台股漲 2.5%。")
  })

  it("第四輪實測：對著沒說過的話認錯", () => {
    expect(
      dropAiHabits("你說的沒錯，我把 11/26 的走勢寫錯了。鴻海 11/26 收 216.5 元，漲 4.8%。下面的內容請以這個為準。\n\n- 11/25 一度跌停。"),
    ).toBe("鴻海 11/26 收 216.5 元，漲 4.8%。\n\n- 11/25 一度跌停。")
  })
})
