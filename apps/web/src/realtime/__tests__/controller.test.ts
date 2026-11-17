import { QueryClient, QueryObserver, type QueryKey } from "@tanstack/react-query"
import { DEBOUNCE_MS, FALLBACK_MS, HIDDEN_CLOSE_MS, RealtimeController, type RealtimeEnv } from "@/realtime/controller"
import { useRealtime } from "@/realtime/store"
import { resetTabHeader, TAB_HEADER, tabId, withTab } from "@/realtime/tab"
import { ev, fakeServer, hello } from "./fake-stream"

/** 前景／背景可以切換的假瀏覽器 */
function fakeEnv() {
  let visible = true
  const handlers = new Map<string, Set<() => void>>()
  const env: RealtimeEnv = {
    visible: () => visible,
    listen: (target, type, fn) => {
      const key = `${target}:${type}`
      if (!handlers.has(key)) handlers.set(key, new Set())
      handlers.get(key)!.add(fn)
      return () => handlers.get(key)!.delete(fn)
    },
  }
  const fire = (key: string) => handlers.get(key)?.forEach((fn) => fn())
  return {
    env,
    hide: () => {
      visible = false
      fire("doc:visibilitychange")
    },
    show: () => {
      visible = true
      fire("doc:visibilitychange")
    },
    focus: () => fire("win:focus"),
  }
}

/** 一個畫面上有在用的查詢（數它被讀了幾次） */
function watch(qc: QueryClient, key: QueryKey) {
  const fn = vi.fn(() => Promise.resolve({ at: Date.now() }))
  const observer = new QueryObserver(qc, { queryKey: key, queryFn: fn, staleTime: Infinity, retry: false })
  const unsubscribe = observer.subscribe(() => {})
  return { fn, unsubscribe }
}

const settle = (ms = 0) => vi.advanceTimersByTimeAsync(ms)

/** 讓時間過去，伺服器照常每 20 秒送心跳（不然看門狗 50 秒後會當作斷線重連） */
async function keepAlive(server: ReturnType<typeof fakeServer>, ms: number) {
  for (let t = 0; t < ms; t += 20_000) {
    await settle(Math.min(20_000, ms - t))
    server.latest().send(": ping\n\n")
  }
  await settle()
}

function setup(opts: { viewAs?: string | null; random?: () => number } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const server = fakeServer()
  const browser = fakeEnv()
  const controller = new RealtimeController({
    qc,
    open: server.open,
    viewAs: () => opts.viewAs ?? null,
    env: browser.env,
    random: opts.random ?? (() => 0),
  })
  return { qc, server, browser, controller }
}

beforeEach(() => {
  vi.useFakeTimers()
  resetTabHeader()
  useRealtime.setState({ status: "off", closesAt: 0 })
})
afterEach(() => {
  vi.useRealTimers()
})

describe("RealtimeController", () => {
  it("refetches what is on screen within the debounce, once per burst", async () => {
    const { qc, server, controller } = setup()
    const group = watch(qc, ["groups", "g1"])
    const other = watch(qc, ["groups", "g2"])
    await settle()
    expect(group.fn).toHaveBeenCalledTimes(1)
    controller.start()
    await settle()
    server.latest().send(hello("b1.1") + ev("b1.2", "group.members", { group_id: "g1" }) + ev("b1.3", "group.members", { group_id: "g1" }))
    await settle()
    expect(useRealtime.getState().status).toBe("open")
    expect(group.fn).toHaveBeenCalledTimes(1)
    await settle(DEBOUNCE_MS)
    expect(group.fn).toHaveBeenCalledTimes(2)
    expect(other.fn).toHaveBeenCalledTimes(1)
    controller.stop()
    expect(useRealtime.getState().status).toBe("off")
    group.unsubscribe()
    other.unsubscribe()
  })

  it("skips events this tab caused, and starts sending the tab header once connected", async () => {
    const { qc, server, controller } = setup()
    const ledger = watch(qc, ["portfolio", "summary", "all"])
    await settle()
    expect(withTab("POST", {})).toEqual({})
    controller.start()
    await settle()
    server.latest().send(hello("b1.1") + ev("b1.2", "ledger", { account_id: "acc_1", o: tabId }))
    await settle(DEBOUNCE_MS)
    expect(ledger.fn).toHaveBeenCalledTimes(1)
    expect(withTab("POST", {})).toEqual({ [TAB_HEADER]: tabId })
    expect(withTab("GET", {})).toEqual({})
    // another tab of the same person
    server.latest().send(ev("b1.3", "ledger", { account_id: "acc_1", o: "tOTHERTAB0000" }))
    await settle(DEBOUNCE_MS)
    expect(ledger.fn).toHaveBeenCalledTimes(2)
    controller.stop()
    ledger.unsubscribe()
  })

  it("while viewing someone, follows their ledger (ledger.viewas) and ignores the viewer's own", async () => {
    const { qc, server, controller } = setup({ viewAs: "dlg_1" })
    const ledger = watch(qc, ["portfolio", "summary", "all"])
    await settle()
    controller.start()
    await settle()
    server.latest().send(hello("b1.1") + ev("b1.2", "ledger", { account_id: "acc_mine" }))
    await settle(DEBOUNCE_MS)
    expect(ledger.fn).toHaveBeenCalledTimes(1)
    server.latest().send(ev("b1.3", "ledger.viewas", { delegation_id: "dlg_1" }))
    await settle(DEBOUNCE_MS)
    expect(ledger.fn).toHaveBeenCalledTimes(2)
    controller.stop()
    ledger.unsubscribe()
  })

  it("spreads market events over up to 1.5 s and records closes for useCloseRefresh", async () => {
    const { qc, server, controller } = setup({ random: () => 0.9 })
    const quote = watch(qc, ["quote", "2330.TW"])
    await settle()
    controller.start()
    await settle()
    server.latest().send(hello("b1.1") + ev("b1.2", "market.closes", { market: "TWSE", date: "2026-11-17" }))
    await settle()
    expect(useRealtime.getState().closesAt).toBeGreaterThan(0)
    await settle(1350 + DEBOUNCE_MS - 1)
    expect(quote.fn).toHaveBeenCalledTimes(1)
    await settle(1)
    expect(quote.fn).toHaveBeenCalledTimes(2)
    controller.stop()
    quote.unsubscribe()
  })

  it("in a background tab only marks queries stale, refetches them on return, and closes the stream after 2 minutes", async () => {
    const { qc, server, browser, controller } = setup()
    const group = watch(qc, ["groups", "g1"])
    await settle()
    controller.start()
    await settle()
    server.latest().send(hello("b1.1"))
    await settle()
    browser.hide()
    server.latest().send(ev("b1.2", "group.ledger", { group_id: "g1" }))
    await settle(DEBOUNCE_MS)
    expect(group.fn).toHaveBeenCalledTimes(1)
    expect(qc.getQueryState(["groups", "g1"])?.isInvalidated).toBe(false) // group.ledger does not touch ["groups", g] itself
    server.latest().send(ev("b1.3", "group.meta", { group_id: "g1" }))
    await settle(DEBOUNCE_MS)
    expect(group.fn).toHaveBeenCalledTimes(1)
    expect(qc.getQueryState(["groups", "g1"])?.isInvalidated).toBe(true)

    await keepAlive(server, HIDDEN_CLOSE_MS)
    expect(server.latest().aborted()).toBe(true)
    expect(server.open).toHaveBeenCalledTimes(1)
    expect(useRealtime.getState().status).toBe("paused")
    // nothing polls while hidden
    await settle(5 * 60_000)
    expect(group.fn).toHaveBeenCalledTimes(1)
    expect(server.open).toHaveBeenCalledTimes(1)

    browser.show()
    await settle()
    expect(group.fn).toHaveBeenCalledTimes(2)
    expect(server.open).toHaveBeenCalledTimes(2)
    expect(server.latest().last).toBe("b1.3")
    controller.stop()
    group.unsubscribe()
  })

  it("a resync on reconnect refetches every live query on screen, not static ones", async () => {
    const { qc, server, controller } = setup()
    const group = watch(qc, ["groups", "g1", "feed", "all"])
    const inst = watch(qc, ["instrument", "2330.TW"])
    await settle()
    controller.start()
    await settle()
    server.latest().send(hello("b2.1", "resync"))
    await settle(DEBOUNCE_MS)
    expect(group.fn).toHaveBeenCalledTimes(2)
    expect(inst.fn).toHaveBeenCalledTimes(1)
    controller.stop()
    group.unsubscribe()
    inst.unsubscribe()
  })

  it("a resync (everyone gets one after a deploy) is spread over 0–3 s", async () => {
    const { qc, server, controller } = setup({ random: () => 0.9 })
    const group = watch(qc, ["groups", "g1", "feed", "all"])
    await settle()
    controller.start()
    await settle()
    server.latest().send(hello("b2.1", "resync"))
    await settle(2700 - 1)
    expect(group.fn).toHaveBeenCalledTimes(1)
    await settle(1 + DEBOUNCE_MS)
    expect(group.fn).toHaveBeenCalledTimes(2)
    controller.stop()
    group.unsubscribe()
  })

  it("polls every 30 s while the stream is down and the tab is visible, and stops once it opens", async () => {
    const { qc, server, browser, controller } = setup()
    const feed = watch(qc, ["groups", "g1", "feed", "all"])
    const quote = watch(qc, ["quote", "2330.TW"])
    await settle()
    server.refuseNext(503, { "Retry-After": "600" })
    controller.start()
    await settle()
    expect(useRealtime.getState().status).toBe("down")
    await settle(FALLBACK_MS - 5000)
    expect(feed.fn).toHaveBeenCalledTimes(1)
    await settle(5000 + DEBOUNCE_MS)
    expect(feed.fn).toHaveBeenCalledTimes(2)
    // quotes keep their own interval; the fallback does not double them
    expect(quote.fn).toHaveBeenCalledTimes(1)
    await settle(FALLBACK_MS)
    expect(feed.fn).toHaveBeenCalledTimes(3)
    // hidden: no fallback polling
    browser.hide()
    await settle(2 * FALLBACK_MS)
    expect(feed.fn).toHaveBeenCalledTimes(3)
    browser.show()
    await settle()
    // the hold ends (600 s after start): reconnects, opens → a resync (it was down), then no more polling
    await settle(600_000)
    server.latest().send(hello("b1.1"))
    await settle(DEBOUNCE_MS)
    const after = feed.fn.mock.calls.length
    await keepAlive(server, 3 * FALLBACK_MS)
    expect(feed.fn.mock.calls.length).toBe(after)
    controller.stop()
    feed.unsubscribe()
    quote.unsubscribe()
  })

  it("on 401 refetches what is on screen (a real logout then reaches the login page through the normal 401 handling)", async () => {
    const { qc, server, controller } = setup()
    const ledger = watch(qc, ["portfolio", "summary", "all"])
    await settle()
    server.refuseNext(401)
    controller.start()
    await settle(DEBOUNCE_MS)
    expect(ledger.fn).toHaveBeenCalledTimes(2)
    expect(server.open).toHaveBeenCalledTimes(1)
    controller.stop()
    ledger.unsubscribe()
  })

  it("coming back to the tab retries at once instead of waiting out the backoff (but honours a server hold)", async () => {
    const { server, browser, controller } = setup({ random: () => 1 })
    for (let i = 0; i < 5; i++) server.failNext()
    controller.start()
    await settle(3000 + 3000 + 4000 + 8000 + 100)
    expect(server.open).toHaveBeenCalledTimes(5) // the next retry would be 16 s later
    browser.hide()
    browser.show()
    await settle()
    expect(server.open).toHaveBeenCalledTimes(6)
    controller.stop()

    const held = setup()
    held.server.refuseNext(503, { "Retry-After": "600" })
    held.controller.start()
    await settle()
    held.browser.hide()
    held.browser.show()
    await settle(1000)
    expect(held.server.open).toHaveBeenCalledTimes(1)
    held.controller.stop()
  })

  it("bye{replaced} waits for focus or for the tab to come back", async () => {
    const { server, browser, controller } = setup()
    controller.start()
    await settle()
    server.latest().send(hello("b1.1") + 'event: bye\ndata: {"reason":"replaced"}\n\n')
    await settle(60_000)
    expect(server.open).toHaveBeenCalledTimes(1)
    browser.focus()
    await settle()
    expect(server.open).toHaveBeenCalledTimes(2)
    controller.stop()
  })

  it("stop() closes the stream and cancels pending work", async () => {
    const { qc, server, controller } = setup()
    const group = watch(qc, ["groups", "g1"])
    await settle()
    controller.start()
    await settle()
    server.latest().send(hello("b1.1") + ev("b1.2", "group.meta", { group_id: "g1" }))
    await settle()
    controller.stop()
    await settle(10_000)
    expect(group.fn).toHaveBeenCalledTimes(1)
    expect(server.latest().aborted()).toBe(true)
    group.unsubscribe()
  })
})
