import { HOLD_MS, RealtimeClient, type RealtimeEvent } from "@/realtime/client"
import type { RealtimeStatus } from "@/realtime/store"
import { bye, ev, fakeServer, hello } from "./fake-stream"

function setup(random = () => 0.5) {
  const server = fakeServer()
  const events: RealtimeEvent[] = []
  const statuses: RealtimeStatus[] = []
  const onResync = vi.fn()
  const onUnauthorized = vi.fn()
  const client = new RealtimeClient({
    open: server.open,
    onEvent: (e) => events.push(e),
    onResync,
    onStatus: (s) => statuses.push(s),
    onUnauthorized,
    random,
  })
  return { server, client, events, statuses, onResync, onUnauthorized }
}

/** 讓 fetch、讀串流的 promise 跑完（假時鐘往前一點點） */
const settle = (ms = 0) => vi.advanceTimersByTimeAsync(ms)

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe("RealtimeClient", () => {
  it("opens, reads hello, events and heartbeats, and remembers the last id", async () => {
    const { server, client, events, statuses, onResync } = setup()
    client.start()
    await settle()
    expect(server.open).toHaveBeenCalledWith(null, expect.any(AbortSignal))
    server.latest().send(hello("b1.10"))
    server.latest().send(": ping\n\n")
    server.latest().send(ev("b1.11", "group.members", { group_id: "g1" }))
    await settle()
    expect(statuses).toEqual(["connecting", "open"])
    expect(events).toEqual([{ topic: "group.members", data: { group_id: "g1" } }])
    expect(client.lastEventId).toBe("b1.11")
    // the first connection of the page: nothing was missed
    expect(onResync).not.toHaveBeenCalled()
    client.stop()
    expect(server.latest().aborted()).toBe(true)
    expect(statuses.at(-1)).toBe("off")
  })

  it("reconnects with backoff after the stream drops, sending the last id; a replay needs no resync", async () => {
    const { server, client, statuses, onResync } = setup(() => 1)
    client.start()
    await settle()
    server.latest().send(hello("b1.5") + ev("b1.6", "ledger", { account_id: "acc_1" }))
    await settle()
    server.latest().close()
    await settle()
    expect(statuses.at(-1)).toBe("down")
    expect(server.open).toHaveBeenCalledTimes(1)
    await settle(3000) // first retry: up to 3 s (random = 1 → 3 s; spread out after a deploy)
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(server.latest().last).toBe("b1.6")
    server.latest().send(hello("b1.6", "replayed"))
    await settle()
    expect(statuses.at(-1)).toBe("open")
    expect(onResync).not.toHaveBeenCalled()
    client.stop()
  })

  it("asks for a resync when the server cannot replay, or when the first connection only came after a failure", async () => {
    const a = setup()
    a.client.start()
    await settle()
    a.server.latest().send(hello("b1.5"))
    await settle()
    a.server.latest().close()
    await settle(30_000)
    a.server.latest().send(hello("b2.1", "resync"))
    await settle()
    expect(a.onResync).toHaveBeenCalledTimes(1)
    a.client.stop()

    const b = setup()
    b.server.failNext()
    b.client.start()
    await settle(30_000)
    expect(b.server.open).toHaveBeenCalledTimes(2)
    b.server.latest().send(hello("b1.1", "none"))
    await settle()
    expect(b.onResync).toHaveBeenCalledTimes(1)
    b.client.stop()
  })

  it("backs off exponentially with full jitter, capped at 30 s, and resets after a stable connection", async () => {
    const { server, client } = setup(() => 1)
    for (let i = 0; i < 8; i++) server.failNext()
    client.start()
    await settle()
    const times: number[] = []
    let calls = server.open.mock.calls.length
    for (let t = 0; t < 200_000; t += 250) {
      await settle(250)
      if (server.open.mock.calls.length > calls) {
        calls = server.open.mock.calls.length
        times.push(Date.now())
      }
      if (calls === 9) break
    }
    const gaps = times.map((t, i) => (i === 0 ? t : t - times[i - 1]!))
    // started at 0: 3 s (the first retries are spread over 0–3 s), 3 s, 4 s, 8 s, 16 s, then 30 s cap
    expect(gaps.slice(1)).toEqual([3000, 4000, 8000, 16_000, 30_000, 30_000, 30_000])
    // the 9th attempt succeeds and stays up 30 s: the next drop retries within 3 s again
    server.latest().send(hello("b1.1"))
    await settle(30_000)
    server.latest().close()
    await settle(2999)
    const before = server.open.mock.calls.length
    await settle(1)
    expect(server.open.mock.calls.length).toBe(before + 1)
    client.stop()
  })

  it("stops on 401 and tells the app; retries only after the hold", async () => {
    const { server, client, onUnauthorized, statuses } = setup()
    server.refuseNext(401)
    client.start()
    await settle()
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(statuses.at(-1)).toBe("down")
    await settle(HOLD_MS - 1000)
    expect(server.open).toHaveBeenCalledTimes(1)
    client.kick() // coming back online does not override the hold
    await settle()
    expect(server.open).toHaveBeenCalledTimes(1)
    await settle(1000)
    expect(server.open).toHaveBeenCalledTimes(2)
    client.stop()
  })

  it("honours Retry-After on 503 and 429", async () => {
    const { server, client } = setup(() => 0)
    server.refuseNext(503, { "Retry-After": "15" })
    server.refuseNext(429, { "Retry-After": "7" })
    client.start()
    await settle(14_999)
    expect(server.open).toHaveBeenCalledTimes(1)
    await settle(1)
    expect(server.open).toHaveBeenCalledTimes(2)
    await settle(6_999)
    expect(server.open).toHaveBeenCalledTimes(2)
    await settle(1)
    expect(server.open).toHaveBeenCalledTimes(3)
    client.stop()
  })

  it("bye{rotate}: reconnects within a second with the last id", async () => {
    const { server, client, onResync } = setup(() => 0.99)
    client.start()
    await settle()
    server.latest().send(hello("b1.3") + bye("rotate"))
    await settle()
    expect(server.latest().aborted()).toBe(true)
    await settle(990)
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(server.latest().last).toBe("b1.3")
    server.latest().send(hello("b1.3", "replayed"))
    await settle()
    expect(onResync).not.toHaveBeenCalled()
    client.stop()
  })

  it("bye{replaced}: stays paused until resumed", async () => {
    const { server, client, statuses } = setup()
    client.start()
    await settle()
    server.latest().send(hello("b1.3") + bye("replaced"))
    await settle(10 * 60_000)
    expect(statuses.at(-1)).toBe("paused")
    expect(client.replaced).toBe(true)
    expect(server.open).toHaveBeenCalledTimes(1)
    client.resume()
    await settle()
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(server.latest().last).toBe("b1.3")
    client.stop()
  })

  it("bye{unauthorized}: checks once more; a 401 then holds and tells the app", async () => {
    const { server, client, onUnauthorized } = setup(() => 0.5)
    client.start()
    await settle()
    server.latest().send(hello("b1.3") + bye("unauthorized"))
    server.refuseNext(401)
    await settle(1499)
    expect(server.open).toHaveBeenCalledTimes(1)
    await settle(1) // 1 s + 0.5 × 1 s
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    await settle(HOLD_MS - 1000)
    expect(server.open).toHaveBeenCalledTimes(2)
    client.stop()
  })

  it("bye{unauthorized} after this browser signed in again (the old session was replaced): reconnects, no hold", async () => {
    const { server, client, onUnauthorized, statuses, onResync } = setup(() => 0)
    client.start()
    await settle()
    server.latest().send(hello("b1.3") + bye("unauthorized"))
    await settle(1000)
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(server.latest().last).toBe("b1.3") // the new cookie is already in the browser
    server.latest().send(hello("b1.3", "replayed"))
    await settle()
    expect(statuses.at(-1)).toBe("open")
    expect(onUnauthorized).not.toHaveBeenCalled()
    expect(onResync).not.toHaveBeenCalled()
    client.stop()
  })

  it("reads how long to wait from the JSON when Retry-After is hidden (a cross-origin API)", async () => {
    const { server, client } = setup(() => 0)
    server.refuseNext(503, {}, { code: "realtime_busy", retry_after_seconds: 15 })
    client.start()
    await settle(14_999)
    expect(server.open).toHaveBeenCalledTimes(1)
    await settle(1)
    expect(server.open).toHaveBeenCalledTimes(2)
    client.stop()
  })

  it("realtime_off (the server switched realtime off) holds 10 minutes, header or not", async () => {
    const { server, client } = setup(() => 0)
    server.refuseNext(503, {}, { code: "realtime_off" })
    client.start()
    await settle(HOLD_MS - 1)
    expect(server.open).toHaveBeenCalledTimes(1)
    client.kick() // coming back online does not override it
    await settle()
    expect(server.open).toHaveBeenCalledTimes(1)
    await settle(1)
    expect(server.open).toHaveBeenCalledTimes(2)
    client.stop()
  })

  it("a silent connection (no heartbeat for 2.5× the interval) is dropped and reopened", async () => {
    const { server, client, statuses } = setup(() => 0)
    client.start()
    await settle()
    server.latest().send(hello("b1.1"))
    await settle(49_000)
    expect(server.latest().aborted()).toBe(false)
    server.latest().send(": ping\n\n") // a heartbeat re-arms the watchdog
    await settle(49_000)
    expect(server.latest().aborted()).toBe(false)
    await settle(1_000)
    expect(server.conns[0]!.aborted()).toBe(true)
    expect(statuses).toContain("down")
    await settle(250)
    expect(server.open).toHaveBeenCalledTimes(2)
    client.stop()
  })

  it("kick() reconnects a stream that has been silent for 1.5 heartbeats (a laptop that slept), not a healthy one", async () => {
    const { server, client } = setup(() => 0)
    client.start()
    await settle()
    server.latest().send(hello("b1.1"))
    await settle(20_000)
    client.kick()
    await settle()
    expect(server.latest().aborted()).toBe(false)
    await settle(11_000) // 31 s since the last byte
    client.kick()
    await settle(250)
    expect(server.conns[0]!.aborted()).toBe(true)
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(server.latest().last).toBe("b1.1")
    client.stop()
  })

  it("pause closes the stream and keeps the id; resume reconnects with it", async () => {
    const { server, client, statuses } = setup()
    client.start()
    await settle()
    server.latest().send(hello("b1.1") + ev("b1.2", "me", {}))
    await settle()
    client.pause()
    expect(statuses.at(-1)).toBe("paused")
    expect(server.latest().aborted()).toBe(true)
    await settle(60 * 60_000)
    expect(server.open).toHaveBeenCalledTimes(1)
    client.resume()
    await settle()
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(server.latest().last).toBe("b1.2")
    client.stop()
  })

  it("ignores malformed frames and the default message event", async () => {
    const { server, client, events } = setup()
    client.start()
    await settle()
    server.latest().send(hello("b1.1") + "event: ledger\ndata: {not json\n\n" + "data: {}\n\n" + ev("b1.2", "me", {}))
    await settle()
    expect(events).toEqual([{ topic: "me", data: {} }])
    client.stop()
  })
})
