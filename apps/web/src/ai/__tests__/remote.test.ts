import { describe, expect, it } from "vitest"
import { applyChatEvent, createSseParser, draftFromServer, threadFromServer, type ChatEvent, type ServerDraft } from "@/ai/remote"
import { usageNote } from "@/ai/remote-hooks"
import type { Message } from "@/ai/types"

const draft = (p: Partial<ServerDraft> = {}): ServerDraft => ({
  id: "drf_1",
  status: "pending",
  input: { account_id: "acc_1", symbol: "0050.TW", type: "buy", trade_date: "2026-11-12", quantity: 2000, price: 52.4, source: "ai_draft" },
  instrument: { symbol: "0050.TW", code: "0050", name: "元大台灣50", market: "TWSE", currency: "TWD" },
  preview: { gross: 104800, fee: 41, tax: 0, health_insurance: 0, net_cash: -104841, rules: [] },
  notes: [],
  account: { id: "acc_1", name: "永豐" },
  transaction_id: null,
  created_at: "2026-11-12T14:05:00+08:00",
  ...p,
})

describe("createSseParser", () => {
  it("parses events split across chunks, CRLF and multi-line data", () => {
    const got: ChatEvent[] = []
    const feed = createSseParser((e) => got.push(e))
    const raw =
      'event: thread\r\ndata: {"id":"thr_1","title":"hi","created":true}\r\n\r\n' +
      'event: text\ndata: {"delta":"台積"}\n\n' +
      'event: text\ndata: {"delta":\ndata: "電"}\n\n' +
      "event: broken\ndata: {not json\n\n" +
      'event: done\ndata: {"thread_id":"thr_1","turn_id":"trn","model":"m","stop_reason":"end_turn","usage":{}}\n\n'
    for (let i = 0; i < raw.length; i += 7) feed(raw.slice(i, i + 7))
    expect(got.map((e) => e.event)).toEqual(["thread", "text", "text", "done"])
    expect(got[2]).toEqual({ event: "text", data: { delta: "電" } })
  })
})

describe("applyChatEvent", () => {
  const start: Message = { id: "m1", role: "ai", text: "", streaming: true, at: "" }

  it("accumulates text, tools, citations and drafts, then ends", () => {
    const events: ChatEvent[] = [
      { event: "text", data: { delta: "台積電" } },
      { event: "tool", data: { id: "t1", name: "web_search", status: "running", label: "搜尋網路：台積電" } },
      { event: "tool", data: { id: "t1", name: "web_search", status: "done", label: "搜尋網路：台積電" } },
      { event: "citation", data: { url: "https://cna.com.tw/a", title: "中央社", cited_text: "x" } },
      { event: "citation", data: { url: "https://cna.com.tw/a", title: "中央社", cited_text: "x" } },
      { event: "draft", data: draft() },
      { event: "text", data: { delta: "今天上漲。" } },
      { event: "done", data: { thread_id: "thr", turn_id: "t", model: "m", stop_reason: "end_turn", usage: {} as never } },
    ]
    const m = events.reduce(applyChatEvent, start)
    expect(m.text).toBe("台積電今天上漲。")
    expect(m.tools).toEqual([{ id: "t1", name: "web_search", label: "搜尋網路：台積電", status: "done" }])
    expect(m.citations).toHaveLength(1)
    expect(m.draftIds).toEqual(["drf_1"])
    expect(m.streaming).toBe(false)
  })

  it("drops streamed text on a refusal and keeps it on other errors", () => {
    const partial = { ...start, text: "這個" }
    expect(applyChatEvent(partial, { event: "error", data: { code: "refusal", message: "沒辦法回答" } })).toMatchObject({ text: "", error: { code: "refusal" } })
    expect(applyChatEvent(partial, { event: "error", data: { code: "ai_busy", message: "忙碌" } })).toMatchObject({ text: "這個", error: { code: "ai_busy" } })
  })
})

describe("server mapping", () => {
  it("gives cash drafts a cash instrument", () => {
    const d = draftFromServer(draft({ instrument: null, input: { account_id: "a", symbol: null, type: "deposit", trade_date: "2026-11-12", quantity: null, price: null, amount: 10000, currency: "TWD" } }))
    expect(d.instrument.name).toBe("現金")
    expect(d.remote).toBe(true)
  })

  it("turns a thread detail into panel messages and drafts", () => {
    const { thread, drafts } = threadFromServer({
      id: "thr_9",
      title: "買 0050",
      model: "claude-haiku-5-5",
      created_at: "",
      updated_at: "2026-11-12T14:00:00+08:00",
      messages: [
        { id: "1", turn_id: "t", role: "user", text: "買 0050 2 張", citations: [], drafts: [], tools: [], error: null, at: "" },
        { id: "4", turn_id: "t", role: "ai", text: "草稿好了", citations: [], drafts: [draft()], tools: [], error: null, at: "" },
      ],
    })
    expect(thread.remoteId).toBe("thr_9")
    expect(thread.messages.map((m) => m.role)).toEqual(["user", "ai"])
    expect(thread.messages[1]!.draftIds).toEqual(["drf_1"])
    expect(drafts.map((d) => d.id)).toEqual(["drf_1"])
  })
})

describe("usageNote", () => {
  it("speaks only when the quota is nearly used up", () => {
    expect(usageNote(undefined)).toBeNull()
    expect(usageNote({ messages_remaining: 30, tokens_remaining: 1e6 })).toBeNull()
    expect(usageNote({ messages_remaining: 3, tokens_remaining: 1e6 })).toBe("今天還可以問 3 題。")
    expect(usageNote({ messages_remaining: 0, tokens_remaining: 1e6 })).toContain("用完")
    expect(usageNote({ messages_remaining: null, tokens_remaining: null })).toBeNull()
    // 所有金鑰都不能用（503 ai_unavailable）：安靜的一句，不是錯誤畫面
    expect(usageNote({ messages_remaining: 40, tokens_remaining: 1e6, available: false })).toContain("AI 暫時無法使用")
  })
})
