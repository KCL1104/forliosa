import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { sk, usePutShare } from "@/api/sharing-queries"
import type { Group, ShareSettings } from "@/api/types"

/**
 * 「我的分享」的開關：每次送出完整的六個開關。連續切兩個（先開金額、再關交易動態）時，
 * 兩筆 PUT 不能並行——後發先至的話，舊的那筆最後寫入，剛關掉的交易動態又被打開（動態裡又看得到自己的買賣）。
 */
const START: ShareSettings = { returns: true, holdings: true, amounts: false, trades: true, trade_prices: false, push: false }
const GROUP = { id: "grp_test", name: "測試群", my_share: START } as unknown as Group

afterEach(() => vi.restoreAllMocks())

describe("usePutShare：照按的順序一次送一筆", () => {
  it("第二筆等第一筆完成才送；開關立即反應、中途不重抓；最後伺服器是最後按的設定", async () => {
    let server: ShareSettings = START
    const sent: ShareSettings[] = []
    const finish: (() => void)[] = []
    vi.spyOn(api, "putShare").mockImplementation((_id, share) => {
      sent.push(share)
      return new Promise((resolve) => finish.push(() => resolve((server = share))))
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    qc.setQueryData(sk.group(GROUP.id), GROUP)
    const invalidate = vi.spyOn(qc, "invalidateQueries")
    const { result } = renderHook(() => usePutShare(GROUP.id), {
      wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
    })

    const amountsOn = { ...START, amounts: true }
    const tradesOff = { ...amountsOn, trades: false }
    act(() => result.current.mutate(amountsOn))
    act(() => result.current.mutate(tradesOff))

    // 開關立即反應（不等伺服器）
    await waitFor(() => expect(qc.getQueryData<Group>(sk.group(GROUP.id))?.my_share).toEqual(tradesOff))
    // 只送出第一筆；第二筆排隊
    await waitFor(() => expect(sent).toEqual([amountsOn]))

    // 第一筆完成：才送第二筆；還有一筆在路上，不重抓（重抓會拿到交易動態還開著的舊設定）
    act(() => finish.shift()!())
    await waitFor(() => expect(sent).toEqual([amountsOn, tradesOff]))
    expect(invalidate).not.toHaveBeenCalled()
    expect(qc.getQueryData<Group>(sk.group(GROUP.id))?.my_share).toEqual(tradesOff)

    // 最後一筆完成：伺服器是最後按的設定，整組重抓一次
    act(() => finish.shift()!())
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1))
    expect(server).toEqual(tradesOff)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: sk.group(GROUP.id) })
  })

  it("第一筆失敗、第二筆還在排隊：不還原到第一次點之前；最後依伺服器重抓", async () => {
    const sent: ShareSettings[] = []
    const settle: ((ok: boolean) => void)[] = []
    vi.spyOn(api, "putShare").mockImplementation((_id, share) => {
      sent.push(share)
      return new Promise((resolve, reject) => settle.push((ok) => (ok ? resolve(share) : reject(new Error("network")))))
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    qc.setQueryData(sk.group(GROUP.id), GROUP)
    const invalidate = vi.spyOn(qc, "invalidateQueries")
    const { result } = renderHook(() => usePutShare(GROUP.id), {
      wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
    })
    const amountsOn = { ...START, amounts: true }
    const tradesOff = { ...amountsOn, trades: false }
    act(() => result.current.mutate(amountsOn))
    act(() => result.current.mutate(tradesOff))
    await waitFor(() => expect(sent).toEqual([amountsOn]))

    act(() => settle.shift()!(false))
    await waitFor(() => expect(sent).toEqual([amountsOn, tradesOff]))
    // 交易動態不會跳回開著
    expect(qc.getQueryData<Group>(sk.group(GROUP.id))?.my_share).toEqual(tradesOff)
    expect(invalidate).not.toHaveBeenCalled()

    act(() => settle.shift()!(true))
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1))
  })
})
