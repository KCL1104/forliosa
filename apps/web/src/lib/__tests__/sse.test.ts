import { createSseReader, type SseMessage } from "@/lib/sse"

describe("createSseReader", () => {
  const collect = () => {
    const messages: SseMessage[] = []
    const comments: string[] = []
    const retries: number[] = []
    const feed = createSseReader({ onMessage: (m) => messages.push(m), onComment: (c) => comments.push(c), onRetry: (ms) => retries.push(ms) })
    return { feed, messages, comments, retries }
  }

  it("reads ids, retry, comments and multi-line data", () => {
    const { feed, messages, comments, retries } = collect()
    feed('retry: 5000\n\nid: k3f9q2.1041\nevent: hello\ndata: {"v":1}\n\n: ping\n\nid: k3f9q2.1042\nevent: group.members\ndata: {"group_id":\ndata: "g1"}\n\n')
    expect(retries).toEqual([5000])
    expect(comments).toEqual(["ping"])
    expect(messages).toEqual([
      { event: "hello", data: '{"v":1}', id: "k3f9q2.1041" },
      { event: "group.members", data: '{"group_id":\n"g1"}', id: "k3f9q2.1042" },
    ])
  })

  it("handles CRLF, a CRLF split across chunks, and fields split anywhere", () => {
    const { feed, messages } = collect()
    const raw = 'id: a.1\r\nevent: ledger\r\ndata: {"account_id":"acc_1"}\r\n\r\nevent: me\rdata: {}\r\r'
    for (let i = 0; i < raw.length; i += 3) feed(raw.slice(i, i + 3))
    // a trailing lone CR might be the first half of a CRLF: it is held until the next chunk (here a heartbeat)
    feed(": ping\n\n")
    expect(messages).toEqual([
      { event: "ledger", data: '{"account_id":"acc_1"}', id: "a.1" },
      { event: "me", data: "{}" },
    ])
  })

  it("splits one byte at a time and keeps the value's own colons and spaces", () => {
    const { feed, messages } = collect()
    const raw = "event:x\ndata:  two spaces: kept\n\n"
    for (const ch of raw) feed(ch)
    expect(messages).toEqual([{ event: "x", data: " two spaces: kept" }])
  })

  it("does not dispatch blocks without data, and ignores unknown fields and bad retry values", () => {
    const { feed, messages, retries } = collect()
    feed("event: nothing\n\nfoo: bar\nretry: soon\n\nevent: e\ndata\n\n")
    expect(messages).toEqual([{ event: "e", data: "" }])
    expect(retries).toEqual([])
  })

  it("waits for the blank line before dispatching", () => {
    const { feed, messages } = collect()
    feed('event: ledger\ndata: {}\n')
    expect(messages).toEqual([])
    feed("\n")
    expect(messages).toHaveLength(1)
  })
})
