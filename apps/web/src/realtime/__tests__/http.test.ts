import { createHttpAdapter } from "@/api/http"
import { useViewAs } from "@/api/view-as"
import { enableTabHeader, resetTabHeader, TAB_HEADER, tabId } from "@/realtime/tab"

/** 即時更新在真實後端 adapter 上的兩件事：打開串流的請求、寫入帶上分頁 id（docs/api-contract.md「即時更新（2026-11-17）」） */
type Call = { url: string; init: RequestInit }

function captureFetch() {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init })
      return new Response(null, { status: 204 })
    }),
  )
  return calls
}

afterEach(() => {
  resetTabHeader()
  useViewAs.getState().set(null)
  vi.unstubAllGlobals()
})

describe("realtime over the HTTP adapter", () => {
  it("opens GET /events with the cookie, `last` as a query parameter and no custom header (no CORS preflight)", async () => {
    const calls = captureFetch()
    const api = createHttpAdapter("https://api.example.test")
    const signal = new AbortController().signal
    await api.openEvents!(null, signal)
    await api.openEvents!("k3f9q2.1041", signal)
    expect(calls.map((c) => c.url)).toEqual(["https://api.example.test/api/v1/events", "https://api.example.test/api/v1/events?last=k3f9q2.1041"])
    expect(calls[0]!.init).toMatchObject({ credentials: "include", headers: { Accept: "text/event-stream" }, cache: "no-store", signal })
  })

  it("never sends the view-as header on the stream (always the viewer's own)", async () => {
    const calls = captureFetch()
    useViewAs.getState().set({ delegation_id: "dlg_1", owner: { user_id: "u2", display_name: "爸爸", avatar_url: null }, scope: "all", accounts: [] })
    await createHttpAdapter("https://api.example.test").openEvents!(null, new AbortController().signal)
    expect(Object.keys(calls[0]!.init.headers as Record<string, string>)).toEqual(["Accept"])
  })

  it("writes carry the tab id only after the stream has connected once; reads and page-unload requests never do", async () => {
    const calls = captureFetch()
    const api = createHttpAdapter("https://api.example.test")
    await api.addWatch("2330.TW")
    expect((calls[0]!.init.headers as Record<string, string>)[TAB_HEADER]).toBeUndefined()
    enableTabHeader()
    await api.addWatch("2330.TW")
    await api.getWatchlist().catch(() => undefined)
    await api.deleteReply("rep_1", { keepalive: true })
    const tabs = calls.map((c) => (c.init.headers as Record<string, string>)[TAB_HEADER])
    expect(tabs).toEqual([undefined, tabId, undefined, undefined])
    expect(tabId).toMatch(/^[A-Za-z0-9_-]{8,32}$/)
  })
})
