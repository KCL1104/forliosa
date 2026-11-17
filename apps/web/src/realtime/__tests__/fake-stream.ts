/** 測試用的 `GET /events`：每一次 `open` 是一條可以從測試裡寫入、關掉的串流 */
export interface FakeConn {
  last: string | null
  send: (text: string) => void
  close: () => void
  aborted: () => boolean
}

export function fakeServer() {
  const conns: FakeConn[] = []
  const queued: (() => Promise<Response>)[] = []
  const enc = new TextEncoder()
  const open = vi.fn((last: string | null, signal: AbortSignal): Promise<Response> => {
    const next = queued.shift()
    if (next) return next()
    let ctrl!: ReadableStreamDefaultController<Uint8Array>
    let done = false
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        ctrl = c
      },
    })
    const conn: FakeConn = {
      last,
      send: (text) => {
        if (!done) ctrl.enqueue(enc.encode(text))
      },
      close: () => {
        if (!done) {
          done = true
          ctrl.close()
        }
      },
      aborted: () => signal.aborted,
    }
    signal.addEventListener("abort", () => {
      if (!done) {
        done = true
        ctrl.error(new DOMException("aborted", "AbortError"))
      }
    })
    conns.push(conn)
    return Promise.resolve(new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }))
  })
  return {
    open,
    conns,
    /** 下一次 `open` 回這個狀態碼（JSON 錯誤；`error` 換掉錯誤物件的欄位） */
    refuseNext(status: number, headers: Record<string, string> = {}, error: Record<string, unknown> = {}) {
      queued.push(() => Promise.resolve(new Response(JSON.stringify({ error: { code: `http_${status}`, message: "x", ...error } }), { status, headers })))
    },
    /** 下一次 `open` 網路失敗 */
    failNext() {
      queued.push(() => Promise.reject(new TypeError("Failed to fetch")))
    },
    latest(): FakeConn {
      return conns[conns.length - 1]!
    },
  }
}

export const hello = (id: string, replay: "none" | "replayed" | "resync" = "none") =>
  `retry: 5000\n\nid: ${id}\nevent: hello\ndata: {"v":1,"boot":"${id.split(".")[0]}","heartbeat":20,"replay":"${replay}"}\n\n`
export const ev = (id: string, topic: string, data: Record<string, unknown>) => `id: ${id}\nevent: ${topic}\ndata: ${JSON.stringify(data)}\n\n`
export const bye = (reason: string) => `event: bye\ndata: {"reason":"${reason}"}\n\n`
