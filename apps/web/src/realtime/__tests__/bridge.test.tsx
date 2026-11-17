import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, waitFor } from "@testing-library/react"
import { api } from "@/api"
import { qk } from "@/api/queries"
import { RealtimeBridge } from "@/realtime/RealtimeBridge"
import { useRealtime } from "@/realtime/store"

/** mock 模式（測試與 `pnpm dev`）沒有串流：橋什麼都不連，狀態留在 off，各個查詢照原本的間隔重新讀 */
describe("RealtimeBridge in mock mode", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("opens nothing and leaves the status off", async () => {
    expect(api.kind).toBe("mock")
    expect(api.openEvents).toBeUndefined()
    const fetchSpy = vi.fn()
    vi.stubGlobal("fetch", fetchSpy)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(qk.me, await api.getMe())
    render(
      <QueryClientProvider client={qc}>
        <RealtimeBridge />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(useRealtime.getState().status).toBe("off"))
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
