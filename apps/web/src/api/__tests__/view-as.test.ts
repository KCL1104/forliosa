import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { createHttpAdapter } from "@/api/http"
import { ApiError } from "@/api/types"
import { sendsViewAs, useViewAs, VIEW_AS_HEADER } from "@/api/view-as"
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

  it("Discord 登入是整頁導到 API 主機，帶上 next", () => {
    const api = createHttpAdapter("https://api.example.test")
    expect(api.discordLoginUrl("/invite/abc")).toBe("https://api.example.test/api/v1/auth/discord/start?next=%2Finvite%2Fabc")
  })

  it("哪些路徑是查看者自己的", () => {
    expect(["/me", "/me/preferences", "/auth/providers", "/auth/discord/start"].map(sendsViewAs)).toEqual([false, false, false, false])
    expect(["/portfolio/summary", "/groups", "/watchlist", "/meta/attributions", "/mexico"].map(sendsViewAs)).toEqual([true, true, true, true, true])
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
