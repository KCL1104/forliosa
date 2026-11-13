import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { aiApi, streamChat } from "@/ai/remote"
import { createHttpAdapter } from "@/api/http"
import { ApiError } from "@/api/types"
import { sameTarget, sendsViewAs, useViewAs, VIEW_AS_HEADER } from "@/api/view-as"
import { exitOnRevoked, scopeText, switchViewAs } from "@/app/view-as"
import { safeNext } from "@/lib/next-path"
import { oauthErrorText } from "@/lib/oauth-errors"

const dad = { delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "accounts" as const, accounts: [{ id: "acc_1", name: "元大－爸爸" }] }

/** 攔截 fetch，記下每個請求的標頭 */
function captureFetch() {
  const calls: { url: string; method: string; headers: Record<string, string> }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, method: init.method ?? "GET", headers: { ...(init.headers as Record<string, string>) } })
      return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } })
    }),
  )
  return calls
}

afterEach(() => {
  useViewAs.getState().set(null)
  vi.unstubAllGlobals()
})

describe("查看模式：API client 帶上 X-Forliosa-View-As", () => {
  it("查看中的請求都帶授權 id；自己的 /me、偏好、登入不帶；結束查看後都不帶", async () => {
    const calls = captureFetch()
    const api = createHttpAdapter("https://api.example.test")
    useViewAs.getState().set(dad)
    await api.getPortfolioSummary()
    await api.listTransactions({ limit: 50 })
    await api.createTransaction({ account_id: "acc_1", symbol: "2330.TW", type: "buy", trade_date: "2026-11-12", quantity: 1, price: 1 })
    await api.getMe()
    await api.updatePreferences({ theme: "dark" })
    await api.getAuthProviders()
    useViewAs.getState().set(null)
    await api.getPortfolioSummary()
    const header = (i: number) => calls[i]!.headers[VIEW_AS_HEADER]
    expect([0, 1, 2].map(header)).toEqual(["dlg_dad", "dlg_dad", "dlg_dad"])
    expect([3, 4, 5, 6].map(header)).toEqual([undefined, undefined, undefined, undefined])
    expect(calls.every((c) => c.url.startsWith("https://api.example.test/api/v1/"))).toBe(true)
  })

  it("Discord、Google 登入是整頁導到 API 主機，帶上 next", () => {
    const api = createHttpAdapter("https://api.example.test")
    expect(api.discordLoginUrl("/invite/abc")).toBe("https://api.example.test/api/v1/auth/discord/start?next=%2Finvite%2Fabc")
    expect(api.googleLoginUrl("/invite/abc")).toBe("https://api.example.test/api/v1/auth/google/start?next=%2Finvite%2Fabc")
  })

  it("哪些路徑是查看者自己的", () => {
    expect(["/me", "/me/preferences", "/auth/providers", "/auth/discord/start"].map((p) => sendsViewAs(p))).toEqual([false, false, false, false])
    expect(["/portfolio/summary", "/groups", "/watchlist", "/meta/attributions", "/mexico"].map((p) => sendsViewAs(p))).toEqual([true, true, true, true, true])
    // 讀自己收到的授權（更新橫幅的範圍）不帶；授權的寫入照樣帶（伺服器回 read_only）
    expect(sendsViewAs("/delegations", "GET")).toBe(false)
    expect(["POST", "PATCH", "DELETE"].map((m) => sendsViewAs(m === "POST" ? "/delegations" : "/delegations/dlg_1", m))).toEqual([true, true, true])
    expect(sendsViewAs("/delegations/candidates", "GET")).toBe(true)
  })

  it("查看中讀 GET /delegations 不帶標頭，改授權仍帶", async () => {
    const calls = captureFetch()
    const api = createHttpAdapter("https://api.example.test")
    useViewAs.getState().set(dad)
    await api.listDelegations()
    await api.deleteDelegation("dlg_dad")
    expect(calls.map((c) => [c.method, c.headers[VIEW_AS_HEADER]])).toEqual([
      ["GET", undefined],
      ["DELETE", "dlg_dad"],
    ])
  })

  it("AI 的請求（對話紀錄、刪除、SSE 對話）查看中也帶標頭，讓伺服器的白名單擋下", async () => {
    const calls = captureFetch()
    useViewAs.getState().set(dad)
    await aiApi.listThreads()
    await aiApi.deleteThread("thr_1")
    await streamChat({ thread_id: null, message: "我的持股會不會太集中？", page: { route: "/history", symbol: null }, privacy: false }, () => {})
    useViewAs.getState().set(null)
    await aiApi.listThreads()
    expect(calls.map((c) => [c.method, c.url.replace(/^.*\/api\/v1/, ""), c.headers[VIEW_AS_HEADER]])).toEqual([
      ["GET", "/ai/threads?limit=50", "dlg_dad"],
      ["DELETE", "/ai/threads/thr_1", "dlg_dad"],
      ["POST", "/ai/chat", "dlg_dad"],
      ["GET", "/ai/threads?limit=50", undefined],
    ])
  })
})

describe("查看模式：切換與退出", () => {
  it("切換時丟掉使用者資料的快取，保留行情", () => {
    const qc = new QueryClient()
    qc.setQueryData(["portfolio", "summary", "all"], { market_value: 1 })
    qc.setQueryData(["groups"], [])
    qc.setQueryData(["quote", "2330.TW"], { price: 1 })
    qc.setQueryData(["me"], { id: "usr_me" })
    switchViewAs(qc, dad)
    expect(useViewAs.getState().target?.delegation_id).toBe("dlg_dad")
    expect(qc.getQueryData(["portfolio", "summary", "all"])).toBeUndefined()
    expect(qc.getQueryData(["groups"])).toBeUndefined()
    expect(qc.getQueryData(["quote", "2330.TW"])).toEqual({ price: 1 })
    expect(qc.getQueryData(["me"])).toEqual({ id: "usr_me" })
  })

  it("403 delegation_revoked：退出查看模式、回首頁；其他錯誤不動", () => {
    const qc = new QueryClient()
    const home = vi.fn()
    useViewAs.getState().set(dad)
    expect(exitOnRevoked(new ApiError(403, "read_only", "唯讀"), qc, home)).toBe(false)
    expect(exitOnRevoked(new ApiError(404, "not_found", "找不到"), qc, home)).toBe(false)
    expect(useViewAs.getState().target).not.toBeNull()
    expect(exitOnRevoked(new ApiError(403, "delegation_revoked", "撤銷"), qc, home)).toBe(true)
    expect(useViewAs.getState().target).toBeNull()
    expect(home).toHaveBeenCalledTimes(1)
    // 已經退出了：之後同時失敗的請求不再重複處理
    expect(exitOnRevoked(new ApiError(403, "delegation_revoked", "撤銷"), qc, home)).toBe(false)
  })

  it("範圍文字", () => {
    expect(scopeText(dad)).toBe("元大－爸爸")
    expect(scopeText({ scope: "all", accounts: [] })).toBe("全部帳戶")
  })

  it("查看對象是否改了（範圍、帳戶、名稱）", () => {
    expect(sameTarget(dad, { ...dad, accounts: [...dad.accounts] })).toBe(true)
    expect(sameTarget(dad, { ...dad, scope: "all" })).toBe(false)
    expect(sameTarget(dad, { ...dad, accounts: [] })).toBe(false)
    expect(sameTarget(dad, { ...dad, accounts: [{ id: "acc_1", name: "元大－老爸" }] })).toBe(false)
    expect(sameTarget(dad, { ...dad, owner: { ...dad.owner, display_name: "老爸" } })).toBe(false)
  })
})

describe("登入", () => {
  it("next 只接受站內路徑（和後端同一個規則）", () => {
    expect(safeNext("/invite/abc")).toBe("/invite/abc")
    expect(safeNext("/groups/grp_1?tab=feed")).toBe("/groups/grp_1?tab=feed")
    expect(safeNext("//evil.com")).toBe("/")
    expect(safeNext("/\\evil.com")).toBe("/")
    expect(safeNext("/%2F%2Fevil.com")).toBe("/")
    expect(safeNext("https://evil.com")).toBe("/")
    expect(safeNext("/login?next=/x")).toBe("/")
    expect(safeNext(undefined)).toBe("/")
  })
  it("oauth_* 錯誤都有說明；不認得的當作 oauth_failed；沒有就不顯示", () => {
    for (const code of ["oauth_disabled", "oauth_denied", "oauth_state", "oauth_email_unverified", "oauth_email_conflict", "oauth_failed"]) {
      expect(oauthErrorText(code)).toBeTruthy()
    }
    expect(oauthErrorText("oauth_whatever")).toBe(oauthErrorText("oauth_failed"))
    expect(oauthErrorText(undefined)).toBeNull()
  })
})
