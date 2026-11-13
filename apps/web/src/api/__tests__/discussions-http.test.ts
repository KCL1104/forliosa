import { afterEach, describe, expect, it, vi } from "vitest"
import { createHttpAdapter } from "@/api/http"
import { ApiError } from "@/api/types"
import { sendsViewAs, useViewAs, VIEW_AS_HEADER } from "@/api/view-as"

/**
 * 真實後端的 adapter：討論串的每個端點照合約（docs/api-contract.md「討論串（2026-11-13）」）的路徑、方法、參數與本文送出；
 * 錯誤物件裡的附加欄位（retry_after_seconds、until、retry_after_days）帶進 `ApiError.extra`；204 沒有內容。
 */
type Call = { method: string; path: string; body: unknown; headers: Record<string, string> }

function captureFetch(respond: (call: Call) => Response = () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } })) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      const call: Call = {
        method: init.method ?? "GET",
        path: decodeURIComponent(url.replace("https://api.example.test/api/v1", "")),
        body: init.body === undefined ? undefined : JSON.parse(init.body as string),
        headers: { ...(init.headers as Record<string, string>) },
      }
      calls.push(call)
      return respond(call)
    }),
  )
  return calls
}
const noContent = () => new Response(null, { status: 204 })
const errorResponse = (status: number, error: Record<string, unknown>) => new Response(JSON.stringify({ error }), { status, headers: { "Content-Type": "application/json" } })

afterEach(() => {
  useViewAs.getState().set(null)
  vi.unstubAllGlobals()
})

describe("討論串的 HTTP adapter", () => {
  it("主題與回覆：路徑、方法、查詢參數與本文照合約", async () => {
    const calls = captureFetch()
    const api = createHttpAdapter("https://api.example.test")
    await api.listTopics()
    await api.listTopics({ scope: "group", group_id: "grp_1", sort: "new", limit: 30, cursor: "abc" })
    await api.listTopics({ scope: "all", symbol: "2330.TW", mine: true, cursor: null })
    await api.listTopics({ scope: "public", mine: false })
    await api.createTopic({ scope: "public", title: "標題", body: "內文\n第二行", symbols: ["2330.TW", "0050.TW"] })
    await api.createTopic({ scope: "group", group_id: "grp_1", title: "標題", body: "內文" })
    await api.getTopic("top_1")
    await api.listReplies("top_1")
    await api.listReplies("top_1", { limit: 50, cursor: "next" })
    await api.createReply("top_1", { body: "回覆" })
    expect(calls.map((c) => [c.method, c.path, c.body])).toEqual([
      ["GET", "/discussions/topics", undefined],
      ["GET", "/discussions/topics?scope=group&group_id=grp_1&sort=new&limit=30&cursor=abc", undefined],
      ["GET", "/discussions/topics?scope=all&symbol=2330.TW&mine=true", undefined],
      ["GET", "/discussions/topics?scope=public", undefined],
      ["POST", "/discussions/topics", { scope: "public", title: "標題", body: "內文\n第二行", symbols: ["2330.TW", "0050.TW"] }],
      ["POST", "/discussions/topics", { scope: "group", group_id: "grp_1", title: "標題", body: "內文" }],
      ["GET", "/discussions/topics/top_1", undefined],
      ["GET", "/discussions/topics/top_1/replies", undefined],
      ["GET", "/discussions/topics/top_1/replies?limit=50&cursor=next", undefined],
      ["POST", "/discussions/topics/top_1/replies", { body: "回覆" }],
    ])
  })

  it("刪除、表情、檢舉回 204：沒有內容（表情收回的對象與表情放在查詢參數）", async () => {
    const calls = captureFetch(noContent)
    const api = createHttpAdapter("https://api.example.test")
    expect(await api.deleteTopic("top_1")).toBeUndefined()
    expect(await api.deleteReply("rep_1")).toBeUndefined()
    expect(await api.addDiscussionReaction({ target: "topic:top_1", emoji: "👍" })).toBeUndefined()
    expect(await api.removeDiscussionReaction("reply:rep_1", "🔥")).toBeUndefined()
    expect(await api.reportDiscussion({ target: "reply:rep_1", reason: "solicitation", note: "帶單" })).toBeUndefined()
    expect(await api.reportDiscussion({ target: "topic:top_1", reason: "other" })).toBeUndefined()
    expect(calls.map((c) => [c.method, c.path, c.body])).toEqual([
      ["DELETE", "/discussions/topics/top_1", undefined],
      ["DELETE", "/discussions/replies/rep_1", undefined],
      ["PUT", "/discussions/reactions", { target: "topic:top_1", emoji: "👍" }],
      ["DELETE", "/discussions/reactions?target=reply:rep_1&emoji=🔥", undefined],
      ["POST", "/discussions/reports", { target: "reply:rep_1", reason: "solicitation", note: "帶單" }],
      ["POST", "/discussions/reports", { target: "topic:top_1", reason: "other" }],
    ])
  })

  it("公開暱稱與站方管理；停權的 days 一定送出（永久是明確的 null）", async () => {
    const calls = captureFetch((c) => (c.method === "GET" || c.path.endsWith("/suspensions") || c.path.endsWith("/public-name") ? new Response(JSON.stringify({}), { status: 200 }) : noContent()))
    const api = createHttpAdapter("https://api.example.test")
    await api.setPublicName("示範小資")
    await api.listAdminReports()
    await api.listAdminReports({ status: "resolved", limit: 30, cursor: "c1" })
    await api.moderateDiscussion({ target: "reply:rep_1", action: "hide" })
    await api.listSuspensions()
    await api.createSuspension({ target: "reply:rep_1", days: 7, reason: "洗版" })
    await api.createSuspension({ target: "topic:top_1", days: null })
    await api.liftSuspension("sus_1")
    expect(calls.map((c) => [c.method, c.path, c.body])).toEqual([
      ["PUT", "/users/me/public-name", { public_name: "示範小資" }],
      ["GET", "/admin/discussions/reports", undefined],
      ["GET", "/admin/discussions/reports?status=resolved&limit=30&cursor=c1", undefined],
      ["POST", "/admin/discussions/moderation", { target: "reply:rep_1", action: "hide" }],
      ["GET", "/admin/discussions/suspensions", undefined],
      ["POST", "/admin/discussions/suspensions", { target: "reply:rep_1", days: 7, reason: "洗版" }],
      ["POST", "/admin/discussions/suspensions", { target: "topic:top_1", days: null }],
      ["DELETE", "/admin/discussions/suspensions/sus_1", undefined],
    ])
    // 永久停權：本文裡真的有 days 這個鍵
    expect(Object.keys(calls[6]!.body as object)).toContain("days")
  })

  it("錯誤物件裡的附加欄位帶進 ApiError.extra（和 code、message 同一層）", async () => {
    const api = createHttpAdapter("https://api.example.test")
    const fail = async (status: number, error: Record<string, unknown>, run: () => Promise<unknown>) => {
      captureFetch(() => errorResponse(status, error))
      const err = await run().then(
        () => null,
        (e: unknown) => e,
      )
      expect(err).toBeInstanceOf(ApiError)
      return err as ApiError
    }
    const limited = await fail(429, { code: "rate_limited", message: "發言太頻繁，請 8 秒後再試", retry_after_seconds: 8 }, () => api.createReply("top_1", { body: "x" }))
    expect(limited).toMatchObject({ status: 429, code: "rate_limited", message: "發言太頻繁，請 8 秒後再試", extra: { retry_after_seconds: 8 } })
    const suspended = await fail(403, { code: "posting_suspended", message: "你的公開發言已被站方暫停", until: "2026-11-20T04:00:00Z" }, () => api.createTopic({ scope: "public", title: "t", body: "b" }))
    expect(suspended.extra).toEqual({ until: "2026-11-20T04:00:00Z" })
    const cooldown = await fail(409, { code: "public_name_cooldown", message: "公開暱稱 7 天內只能改一次，3 天後可以再改", retry_after_days: 3 }, () => api.setPublicName("新暱稱"))
    expect(cooldown).toMatchObject({ status: 409, code: "public_name_cooldown", extra: { retry_after_days: 3 } })
    // 沒有附加欄位的錯誤：extra 是空的
    const missing = await fail(404, { code: "not_found", message: "找不到這個主題" }, () => api.getTopic("top_x"))
    expect(missing.extra).toEqual({})
  })

  it("查看別人的資產時：公開暱稱是查看者自己的端點，不帶 X-Forliosa-View-As；討論的其他請求照常帶（伺服器決定）", async () => {
    expect(sendsViewAs("/users/me/public-name", "PUT")).toBe(false)
    expect(["/discussions/topics", "/discussions/topics/top_1/replies", "/admin/discussions/reports"].map((p) => sendsViewAs(p))).toEqual([true, true, true])
    const calls = captureFetch()
    const api = createHttpAdapter("https://api.example.test")
    useViewAs.getState().set({ delegation_id: "dlg_dad", owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "all", accounts: [] })
    await api.setPublicName("示範小資")
    await api.listTopics({ scope: "public" })
    expect(calls.map((c) => c.headers[VIEW_AS_HEADER])).toEqual([undefined, "dlg_dad"])
  })
})
