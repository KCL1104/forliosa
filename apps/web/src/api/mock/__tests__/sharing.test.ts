import { afterEach, describe, expect, it } from "vitest"
import { createMockAdapter } from "@/api/mock/adapter"
import { ApiError, type ForliosaApi } from "@/api/types"
import { useViewAs } from "@/api/view-as"

/**
 * mock 的分享投影要和合約一樣（docs/api-contract.md「分享（M5）」）：
 * 沒開放的鍵不存在、沒開放的人不出現、看不到的留言對象 404、查看模式的路由白名單。
 */
const fresh = () => createMockAdapter({ latency: [0, 0] })

async function codeOf(p: Promise<unknown>): Promise<string> {
  try {
    await p
    return "ok"
  } catch (e) {
    if (e instanceof ApiError) return `${e.status} ${e.code}`
    throw e
  }
}

const viewAs = (id: string | null) =>
  useViewAs.getState().set(id ? { delegation_id: id, owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null }, scope: "accounts", accounts: [] } : null)

afterEach(() => viewAs(null))

describe("排行：只列開了報酬率的成員", () => {
  it("沒開的人（阿弟）不在裡面；我有美股：只算有收盤價的持股、照樣有名次，只在我那一列標 excludes_unpriced", async () => {
    const api = fresh()
    const b = await api.getLeaderboard("grp_family", "day")
    const names = b.entries.map((e) => e.display_name)
    expect(names).not.toContain("阿弟")
    expect(names).toEqual(expect.arrayContaining(["爸爸", "媽媽", "姊姊", "示範使用者"]))
    const me = b.entries.find((e) => e.is_me)!
    expect(me.return_pct).not.toBeNull()
    expect(me.rank).toBeGreaterThan(0)
    expect(me.excludes_unpriced).toBe(true)
    expect(b.entries.filter((e) => !e.is_me).every((e) => !e.excludes_unpriced)).toBe(true)
    expect(b.entries.filter((e) => e.rank).length).toBe(4)
    expect(b.benchmarks.map((x) => x.symbol)).toEqual(["^TAIEXTR", "0050.TW"])
    expect(JSON.stringify(b)).not.toContain("未分享")
  })
  it("擁有者關掉排行：ranked false、沒有 rank 鍵、依加入順序", async () => {
    const api = fresh()
    const b = await api.getLeaderboard("grp_friends", "month")
    expect(b.ranked).toBe(false)
    expect(b.entries.every((e) => !("rank" in e))).toBe(true)
    expect(b.entries.map((e) => e.display_name)).toEqual(["阿凱", "小芸", "志明", "示範使用者"])
  })
  it("關掉自己的報酬率，立刻從排行消失", async () => {
    const api = fresh()
    const share = await api.getShare("grp_family")
    await api.putShare("grp_family", { ...share, returns: false })
    const b = await api.getLeaderboard("grp_family", "day")
    expect(b.entries.some((e) => e.is_me)).toBe(false)
  })
})

describe("成員分享（SharedPortfolio）：沒開放的鍵不存在", () => {
  it("什麼都沒開的人只有身分欄位", async () => {
    const p = await fresh().getSharedPortfolio("grp_family", "usr_bro")
    expect(Object.keys(p).sort()).toEqual(["avatar_url", "display_name", "is_demo", "user_id"])
  })
  it("只開報酬率與持股：沒有 amounts 鍵；持股只有名稱與權重（四捨五入到 0.01）", async () => {
    const p = await fresh().getSharedPortfolio("grp_family", "usr_mom")
    expect("amounts" in p).toBe(false)
    expect(p.returns).toBeDefined()
    for (const h of p.holdings!) {
      expect(Object.keys(h).sort()).toEqual(["name", "symbol", "weight"])
      expect(Math.round(h.weight * 100) / 100).toBe(h.weight)
    }
  })
  it("全開的人有 amounts（市值、今日損益、總損益）", async () => {
    const p = await fresh().getSharedPortfolio("grp_family", "usr_dad")
    expect(Object.keys(p.amounts!).sort()).toEqual(["day_change", "market_value", "total_pnl"])
  })
  it("不是這個群組的成員：404", async () => {
    expect(await codeOf(fresh().getSharedPortfolio("grp_family", "usr_kai"))).toBe("404 not_found")
  })
})

describe("交易動態", () => {
  it("只有開了 trades 的人；價格只在開了 trade_prices 時才有 price／currency 鍵；最近 90 天；合併同一天同一檔", async () => {
    const api = fresh()
    const feed = await api.getFeed("grp_family", { limit: 100 })
    const trades = feed.items.filter((i) => i.type === "trade")
    expect(new Set(trades.map((i) => i.display_name))).toEqual(new Set(["爸爸", "姊姊", "示範使用者"]))
    for (const t of trades) {
      if (t.user_id === "usr_dad") expect(typeof t.price).toBe("number")
      else expect("price" in t || "currency" in t).toBe(false)
      expect(t.trade_date! >= "2026-08-14").toBe(true)
    }
    const dad0050 = trades.find((t) => t.user_id === "usr_dad" && t.symbol === "0050.TW" && t.trade_date === "2026-11-06")!
    expect(dad0050.count).toBe(2)
    // 阿弟沒開交易動態：只有「加入了群組」
    expect(feed.items.filter((i) => i.user_id === "usr_bro").map((i) => i.type)).toEqual(["member_joined"])
    expect(Object.keys(feed.items.find((i) => i.type === "member_joined")!)).not.toContain("symbol")
  })
  it("關掉 trades：自己的動態立刻消失；重新打開又出現（最近 90 天）", async () => {
    const api = fresh()
    const share = await api.getShare("grp_family")
    const mine = async () => (await api.getFeed("grp_family", { limit: 100 })).items.filter((i) => i.type === "trade" && i.user_id === "usr_01JDEMO").length
    expect(await mine()).toBeGreaterThan(0)
    await api.putShare("grp_family", { ...share, trades: false })
    expect(await mine()).toBe(0)
    await api.putShare("grp_family", { ...share, trades: true })
    expect(await mine()).toBeGreaterThan(0)
  })
})

describe("留言與表情", () => {
  it("看不到的對象（沒開交易動態的人的交易）一律 404，不存在的也一樣", async () => {
    const api = fresh()
    expect(await codeOf(api.listComments("grp_family", "trade:gfi_usr_bro_2026-11-10_2603.TW_buy"))).toBe("404 not_found")
    expect(await codeOf(api.listComments("grp_family", "trade:gfi_nope"))).toBe("404 not_found")
    expect(await codeOf(api.createComment("grp_family", { target: "trade:gfi_usr_bro_2026-11-10_2603.TW_buy", body: "嗨" }))).toBe("404 not_found")
  })
  it("離開群組的人的留言顯示「已離開的成員」、user_id 為 null", async () => {
    const page = await fresh().listComments("grp_family", "digest:gdg_family_1102")
    const left = page.items.find((c) => c.user_id === null)!
    expect(left.display_name).toBe("已離開的成員")
  })
  it("表情只有六個；重複按不重複計；收回", async () => {
    const api = fresh()
    const target = "trade:gfi_usr_dad_2026-11-12_2330.TW_buy"
    expect(await codeOf(api.addReaction("grp_family", { target, emoji: "💩" as never }))).toBe("422 validation_error")
    await api.addReaction("grp_family", { target, emoji: "👍" })
    await api.addReaction("grp_family", { target, emoji: "👍" })
    const item = async () => (await api.getFeed("grp_family", { limit: 100 })).items.find((i) => `trade:${i.id}` === target)!
    expect((await item()).reactions.find((r) => r.emoji === "👍")).toEqual({ emoji: "👍", count: 3, mine: true })
    await api.removeReaction("grp_family", target, "👍")
    expect((await item()).reactions.find((r) => r.emoji === "👍")).toEqual({ emoji: "👍", count: 2, mine: false })
  })
})

describe("群組：存在與權限", () => {
  it("不是成員：一律 404（不透露群組是否存在）", async () => {
    const api = fresh()
    expect(await codeOf(api.getGroup("grp_club"))).toBe("404 not_found")
    expect(await codeOf(api.getLeaderboard("grp_club", "day"))).toBe("404 not_found")
    expect(await codeOf(api.getGroup("grp_nope"))).toBe("404 not_found")
  })
  it("成員但權限不足：403（一般成員不能產生邀請、改頻道）", async () => {
    const api = fresh()
    expect(await codeOf(api.createInvite("grp_friends", { expires: "7d", multi_use: false }))).toBe("403 forbidden")
    expect(await codeOf(api.patchTelegram("grp_friends", { notify_trades: false }))).toBe("403 forbidden")
  })
  it("webhook_hint 只有擁有者看得到", async () => {
    const api = fresh()
    expect((await api.getChannels("grp_family")).discord.webhook_hint).toBe("…/x9Kd")
    expect("webhook_hint" in (await api.getChannels("grp_friends")).discord).toBe(false)
  })
  it("Discord webhook：主機與路徑不對是 422 validation_error；測試訊息失敗是 422 webhook_failed", async () => {
    const api = fresh()
    const put = (url: string) => api.putDiscord("grp_family", { webhook_url: url, notify_trades: true, notify_digest: true })
    expect(await codeOf(put("https://evil.example.com/api/webhooks/1/abc"))).toBe("422 validation_error")
    expect(await codeOf(put("https://discord.com:8443/api/webhooks/1/abc"))).toBe("422 validation_error")
    expect(await codeOf(put("https://discord.com/api/webhooks/1/fail-token"))).toBe("422 webhook_failed")
    expect(await codeOf(put("https://discord.com/api/webhooks/123/abcdWXYZ"))).toBe("ok")
    expect((await api.getChannels("grp_family")).discord.webhook_hint).toBe("…/WXYZ")
  })
})

describe("邀請", () => {
  it("沒登入可以預覽；加入要登入；選好分享才加入；已是成員 409；失效 410；不存在 404", async () => {
    const api = fresh()
    await api.logout()
    expect(await api.getInvite("club-2026")).toEqual({ group_name: "投資讀書會", inviter_display_name: "林老師", status: "valid" })
    expect(await codeOf(api.acceptInvite("club-2026", { returns: true, holdings: false, amounts: false, trades: false, trade_prices: false, push: false }))).toBe("401 unauthorized")
    await api.devLogin({ email: "demo@forliosa.local", display_name: "示範使用者" })
    const share = { returns: true, holdings: false, amounts: false, trades: true, trade_prices: false, push: false }
    const g = await api.acceptInvite("club-2026", share)
    expect(g.my_share).toEqual(share)
    expect(g.my_role).toBe("member")
    expect((await api.getInvite("club-2026")).status).toBe("member")
    expect(await codeOf(api.acceptInvite("club-2026", share))).toBe("409 already_member")
    expect(await codeOf(api.getInvite("club-expired"))).toBe("410 invite_invalid")
    expect(await codeOf(api.getInvite("nope"))).toBe("404 not_found")
  })
  it("移除成員時，可以多人使用的邀請一起撤回", async () => {
    const api = fresh()
    expect((await api.listInvites("grp_family")).some((i) => i.multi_use)).toBe(true)
    await api.removeMember("grp_family", "usr_bro")
    expect((await api.listInvites("grp_family")).some((i) => i.multi_use)).toBe(false)
  })
  it("擁有者要先轉移才能離開；轉移後原擁有者變管理員", async () => {
    const api = fresh()
    expect(await codeOf(api.removeMember("grp_family", "usr_01JDEMO"))).toBe("403 forbidden")
    await api.transferGroup("grp_family", "usr_dad")
    const g = await api.getGroup("grp_family")
    expect(g.my_role).toBe("admin")
    expect(g.members.find((m) => m.user_id === "usr_dad")!.role).toBe("owner")
  })
})

describe("授權查看", () => {
  it("只能授權給同群組的人；已授權 409；指定帳戶必須是自己的", async () => {
    const api = fresh()
    const candidates = await api.listDelegationCandidates()
    expect(candidates.map((c) => c.display_name)).not.toContain("林老師")
    expect(candidates.find((c) => c.user_id === "usr_mom")!.delegation_id).toBe("dlg_mom")
    expect(await codeOf(api.createDelegation({ viewer_user_id: "usr_lin", scope: "all", account_ids: [] }))).toBe("404 not_found")
    expect(await codeOf(api.createDelegation({ viewer_user_id: "usr_mom", scope: "all", account_ids: [] }))).toBe("409 already_member")
    expect(await codeOf(api.createDelegation({ viewer_user_id: "usr_sis", scope: "accounts", account_ids: ["acc_dad_yuanta"] }))).toBe("422 validation_error")
    const d = await api.createDelegation({ viewer_user_id: "usr_sis", scope: "accounts", account_ids: ["acc_01JSINOPAC"] })
    expect(d.accounts).toEqual([{ id: "acc_01JSINOPAC", name: "永豐・一般" }])
  })

  it("查看模式：白名單的 GET 以授權者、只算範圍內的帳戶；寫入 read_only；其他 view_as_not_allowed；行情忽略標頭", async () => {
    const api: ForliosaApi = fresh()
    viewAs("dlg_dad")
    expect((await api.listAccounts()).map((a) => a.name)).toEqual(["元大・爸爸"])
    const holdings = await api.getHoldings()
    expect(holdings.map((h) => h.symbol)).not.toContain("0056.TW") // 富邦・退休金不在範圍內
    expect((await api.listTransactions({ limit: 200 })).items.every((t) => t.account_id === "acc_dad_yuanta")).toBe(true)
    expect(await codeOf(api.getHoldings("acc_dad_fubon"))).toBe("404 not_found")
    expect(await codeOf(api.createTransaction({ account_id: "acc_dad_yuanta", symbol: "2330.TW", type: "buy", trade_date: "2026-11-12", quantity: 1, price: 1 }))).toBe(
      "403 read_only",
    )
    expect(await codeOf(api.getWatchlist())).toBe("403 view_as_not_allowed")
    expect(await codeOf(api.listGroups())).toBe("403 view_as_not_allowed")
    expect(await codeOf(api.listRecurring())).toBe("403 view_as_not_allowed")
    expect(await codeOf(api.getQuote("2330.TW"))).toBe("ok")
    expect((await api.getMe()).display_name).toBe("示範使用者")
    // 自己收到的授權（不帶標頭，橫幅用來更新範圍）照常讀；改授權仍是 read_only
    expect((await api.listDelegations()).received.map((d) => d.id)).toEqual(["dlg_dad"])
    expect(await codeOf(api.deleteDelegation("dlg_dad"))).toBe("403 read_only")
  })

  it("授權不存在或被撤銷：一律 403 delegation_revoked（行情照常）", async () => {
    const api = fresh()
    viewAs("dlg_nope")
    expect(await codeOf(api.getPortfolioSummary())).toBe("403 delegation_revoked")
    expect(await codeOf(api.createTransaction({ account_id: "x", symbol: null, type: "deposit", trade_date: "2026-11-12", quantity: null, price: null, amount: 1 }))).toBe(
      "403 delegation_revoked",
    )
    expect(await codeOf(api.getQuote("2330.TW"))).toBe("ok")
    viewAs(null)
    await api.deleteDelegation("dlg_dad")
    viewAs("dlg_dad")
    expect(await codeOf(api.listAccounts())).toBe("403 delegation_revoked")
  })
})
