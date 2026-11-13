import { describe, expect, it } from "vitest"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { ApiError, PERMANENT_UNTIL, type ForliosaApi } from "@/api/types"

/**
 * 討論串的 mock 和合約（docs/api-contract.md「討論串（2026-11-13）」）一致：
 * 誰能讀、作者欄位、公開暱稱、檢查順序（停權 → 暱稱 → 頻率）、隱藏、檢舉與站方管理、群組範圍的 404。
 * 時鐘可以換掉（`clock`），頻率限制與暱稱冷卻不用真的等。
 */
function fresh(options: MockOptions = {}) {
  let now = 1_000_000
  const api = createMockAdapter({ latency: [0, 0], clock: () => now, ...options })
  return { api, tick: (ms: number) => (now += ms) }
}
const named = (extra: MockOptions = {}) => fresh({ discussion: { publicName: "示範小資" }, ...extra })

async function failure(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError)
    return e as ApiError
  }
  throw new Error("expected the call to fail")
}
const titles = async (api: ForliosaApi, query: Parameters<ForliosaApi["listTopics"]>[0]) => (await api.listTopics(query)).items.map((t) => t.title)

describe("個人資料（GET /me 多三個欄位）", () => {
  it("示範使用者一開始沒有公開暱稱、是站方管理員、沒有停權", async () => {
    const me = await fresh().api.getMe()
    expect(me.public_name).toBeNull()
    expect(me.is_admin).toBe(true)
    expect(me.public_posting_suspended_until).toBeNull()
  })
  it("情境：已經有暱稱、被停權（時間是 UTC、Z 結尾、到秒）、不是管理員", async () => {
    expect((await named().api.getMe()).public_name).toBe("示範小資")
    const suspended = await fresh({ discussion: { publicName: "示範小資", suspended: true } }).api.getMe()
    expect(suspended.public_posting_suspended_until).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
    expect((await fresh({ discussion: { admin: false } }).api.getMe()).is_admin).toBe(false)
  })
})

describe("誰能讀", () => {
  it("公開的清單、主題與回覆不用登入就能讀；mine／can_* 都是 false、my_reactions 沒有", async () => {
    const { api } = fresh({ signedIn: false })
    const list = await api.listTopics({ scope: "public" })
    expect(list.items.length).toBe(8)
    expect(list.items.every((t) => t.scope === "public" && t.group === null && !t.mine)).toBe(true)
    const topic = await api.getTopic("top_p_etf")
    expect(topic).toMatchObject({ can_delete: false, can_report: false, can_reply: false, mine: false })
    expect(topic.reactions.every((r) => !r.mine)).toBe(true)
    const replies = await api.listReplies("top_p_etf")
    expect(replies.items.length).toBe(4)
    expect(replies.items.every((r) => !r.mine && !r.can_delete && !r.can_report)).toBe(true)
  })
  it("沒登入：scope=all／group、mine 與所有寫入是 401；用 id 打開群組主題是 404（不透露存在）", async () => {
    const { api } = fresh({ signedIn: false })
    expect((await failure(api.listTopics({ scope: "all" }))).status).toBe(401)
    expect((await failure(api.listTopics({ scope: "group", group_id: "grp_family" }))).status).toBe(401)
    expect((await failure(api.listTopics({ scope: "public", mine: true }))).status).toBe(401)
    expect((await failure(api.createReply("top_p_etf", { body: "嗨" }))).status).toBe(401)
    expect((await failure(api.addDiscussionReaction({ target: "topic:top_p_etf", emoji: "👍" }))).status).toBe(401)
    expect((await failure(api.reportDiscussion({ target: "topic:top_p_etf", reason: "spam" }))).status).toBe(401)
    expect((await failure(api.getTopic("top_g_dca"))).status).toBe(404)
    expect((await failure(api.listReplies("top_g_dca"))).status).toBe(404)
    expect((await failure(api.listAdminReports())).status).toBe(401)
  })
  it("群組主題只在「全部」和那個群組的篩選裡；公開的篩選、別的群組都看不到；不是成員的群組 404", async () => {
    const { api } = fresh()
    const family = "我把聯發科的交易補記好了"
    expect(await titles(api, { scope: "all" })).toContain(family)
    expect(await titles(api, { scope: "group", group_id: "grp_family" })).toEqual([family, "過年的紅包，要不要一起存 0056？", "這個月的定期定額，大家扣了嗎？"])
    expect(await titles(api, { scope: "public" })).not.toContain(family)
    expect(await titles(api, {})).not.toContain(family) // 預設是 public
    expect(await titles(api, { scope: "group", group_id: "grp_friends" })).toEqual(["下次聚餐，順便對一下今年的績效？"])
    expect((await failure(api.listTopics({ scope: "group", group_id: "grp_club" }))).status).toBe(404)
    expect((await failure(api.listTopics({ scope: "group" }))).status).toBe(422)
  })
  it("symbol 只列標記那一檔的；排序 active（最後回覆）與 new（發表時間）；cursor 分頁不重複不遺漏", async () => {
    const { api } = fresh()
    expect(await titles(api, { scope: "all", symbol: "2330.TW" })).toEqual(["台積電法說會前，大家怎麼配置？"])
    expect((await titles(api, { scope: "all", symbol: "0050" })).sort()).toEqual(["0050 要不要改買 006208？", "台積電法說會前，大家怎麼配置？", "這個月的定期定額，大家扣了嗎？", "高股息 ETF 要不要全部換成市值型？"].sort())
    expect(await titles(api, { scope: "public", symbol: "NOPE" })).toEqual([])
    const active = await titles(api, { scope: "public", sort: "active" })
    const created = await titles(api, { scope: "public", sort: "new" })
    expect(active.slice(0, 2)).toEqual(["台積電法說會前，大家怎麼配置？", "0050 要不要改買 006208？"])
    expect(created.slice(0, 3)).toEqual(["台積電法說會前，大家怎麼配置？", "00878 的殖利率，大家怎麼算？", "0050 要不要改買 006208？"])
    const seen: string[] = []
    let cursor: string | null = null
    do {
      const page = await api.listTopics({ scope: "all", limit: 5, cursor })
      expect(page.items.length).toBeLessThanOrEqual(5)
      seen.push(...page.items.map((t) => t.id))
      cursor = page.next_cursor
    } while (cursor)
    expect(seen.length).toBe(12)
    expect(new Set(seen).size).toBe(12)
    expect((await failure(api.listTopics({ scope: "public", cursor: "not-a-cursor" }))).status).toBe(422)
  })
})

describe("作者", () => {
  it("公開範圍只有 name（公開暱稱）與 is_you 兩個鍵——沒有 user_id、顯示名稱、頭像、email", async () => {
    const { api } = fresh()
    const topic = await api.getTopic("top_p_etf")
    expect(Object.keys(topic.author).sort()).toEqual(["is_you", "name"])
    expect(topic.author).toEqual({ name: "阿土伯", is_you: false })
    const replies = await api.listReplies("top_p_yield")
    for (const r of replies.items) expect(Object.keys(r.author).sort()).toEqual(["is_you", "name"])
    // 帳號刪除後 name 是 null，內容保留
    expect(replies.items[2]).toMatchObject({ author: { name: null, is_you: false }, body: "我都直接看每年實際入帳的金額。" })
    const text = JSON.stringify([topic, replies, await api.listTopics({ scope: "public" })])
    expect(text).not.toMatch(/usr_|avatar_url|display_name|@forliosa/)
  })
  it("群組範圍是顯示名稱＋user_id＋avatar_url；已離開的成員沒有身分；自己的是 is_you、mine、can_delete", async () => {
    const { api } = fresh()
    const topic = await api.getTopic("top_g_dca")
    expect(topic.author).toEqual({ name: "爸爸", is_you: false, user_id: "usr_dad", avatar_url: null })
    expect(topic.group).toEqual({ id: "grp_family", name: "家族投資" })
    // 群組範圍沒有檢舉；我是擁有者，可以刪別人的
    expect(topic).toMatchObject({ can_report: false, can_delete: true })
    const replies = await api.listReplies("top_g_dca")
    expect(replies.items[1]!.author).toEqual({ name: "已離開的成員", is_you: false, user_id: null, avatar_url: null })
    const mine = await api.getTopic("top_g_fix")
    expect(mine).toMatchObject({ mine: true, can_delete: true, author: { name: "示範使用者", is_you: true } })
    // 改顯示名稱後，群組裡的舊貼文顯示新名稱；公開的地方不會出現顯示名稱
    await api.updateMe({ display_name: "小明" })
    expect((await api.getTopic("top_g_fix")).author.name).toBe("小明")
  })
})

describe("公開暱稱", () => {
  it("規則：2–20 字、一行、不能含保留字（不分大小寫與全半形）→ 422；重複（不分大小寫與全半形）→ 409 public_name_taken", async () => {
    const { api } = fresh()
    for (const bad of ["a", "一", "  ", "這個暱稱實在是太長了超過二十個字就不可以用了喔", "兩行\n名字", "官方小編", "ＡＤＭＩＮ", "Forliosa 粉絲", "s y s t e m", "站方"]) {
      expect((await failure(api.setPublicName(bad))).status, bad).toBe(422)
    }
    const taken = await failure(api.setPublicName(" 阿土伯 "))
    expect(taken).toMatchObject({ status: 409, code: "public_name_taken" })
    expect((await api.getMe()).public_name).toBeNull()
  })
  it("第一次設定不算冷卻（打錯字可以馬上改一次），之後每改一次要等 7 天：409 public_name_cooldown 帶 retry_after_days", async () => {
    const { api, tick } = fresh()
    expect((await api.setPublicName(" 示範小姿 ")).public_name).toBe("示範小姿")
    expect((await api.setPublicName("示範小資")).public_name).toBe("示範小資")
    // 存成一模一樣的名字不算、不重新計時
    expect((await api.setPublicName("示範小資")).public_name).toBe("示範小資")
    const cooldown = await failure(api.setPublicName("示範小資二號"))
    expect(cooldown).toMatchObject({ status: 409, code: "public_name_cooldown" })
    expect(cooldown.extra.retry_after_days).toBe(7)
    tick(6 * 86_400_000 + 3_600_000)
    expect((await failure(api.setPublicName("示範小資二號"))).extra.retry_after_days).toBe(1)
    tick(86_400_000)
    expect((await api.setPublicName("示範小資二號")).public_name).toBe("示範小資二號")
  })
  it("改名後舊貼文顯示新暱稱", async () => {
    const { api } = named()
    const reply = await api.createReply("top_p_etf", { body: "我也是新的錢改買。" })
    expect(reply.author).toEqual({ name: "示範小資", is_you: true })
    await api.setPublicName("示範大資")
    const replies = await api.listReplies("top_p_etf")
    expect(replies.items.at(-1)!.author.name).toBe("示範大資")
  })
})

describe("發言", () => {
  it("沒有公開暱稱發公開內容 → 409 public_name_required；群組發言不需要公開暱稱", async () => {
    const { api } = fresh()
    expect(await failure(api.createReply("top_p_etf", { body: "嗨" }))).toMatchObject({ status: 409, code: "public_name_required" })
    expect(await failure(api.createTopic({ scope: "public", title: "標題", body: "內文" }))).toMatchObject({ status: 409, code: "public_name_required" })
    const reply = await api.createReply("top_g_dca", { body: "我也扣了。" })
    expect(reply.author).toMatchObject({ name: "示範使用者", is_you: true, user_id: "usr_01JDEMO" })
  })
  it("公開發言停權 → 403 posting_suspended 帶 until（先於公開暱稱與頻率）；群組發言不受影響", async () => {
    const { api } = fresh({ discussion: { publicName: null, suspended: true } })
    const err = await failure(api.createReply("top_p_etf", { body: "嗨" }))
    expect(err).toMatchObject({ status: 403, code: "posting_suspended" })
    expect(err.extra.until).toBe((await api.getMe()).public_posting_suspended_until)
    expect((await api.createReply("top_g_dca", { body: "群組照常可以發。" })).body).toBe("群組照常可以發。")
  })
  it("內文：CRLF 轉 LF、去掉行尾空白、連續空行最多 2 個、去掉頭尾空行；Tab、控制字元、空白內文、太長 → 422", async () => {
    const { api } = named()
    const reply = await api.createReply("top_p_etf", { body: "\r\n第一行  \r\n\r\n\r\n\r\n\r\n第二行  \n\n" })
    expect(reply.body).toBe("第一行\n\n\n第二行")
    for (const bad of ["", "   \n  ", "有\tTab", "零寬\u200b空白", "x".repeat(2001)]) {
      expect((await failure(api.createReply("top_g_dca", { body: bad }))).status, JSON.stringify(bad.slice(0, 8))).toBe(422)
    }
    expect((await failure(api.createTopic({ scope: "group", group_id: "grp_family", title: "兩行\n標題", body: "內文" }))).status).toBe(422)
    expect((await failure(api.createTopic({ scope: "group", group_id: "grp_family", title: "字".repeat(81), body: "內文" }))).status).toBe(422)
    expect((await failure(api.createTopic({ scope: "group", group_id: "grp_family", title: "標題", body: "字".repeat(5001) }))).status).toBe(422)
  })
  it("主題：最多 5 檔、要是商品主檔裡的代號（422 unknown_symbol）、重複的只留一個；public 帶 group_id → 422；不是成員的群組 404", async () => {
    const { api } = named()
    const topic = await api.createTopic({ scope: "public", title: " 新主題 ", body: "內文", symbols: ["2330", "2330.TW", "0050.TW"] })
    expect(topic).toMatchObject({ title: "新主題", scope: "public", group: null, mine: true, can_delete: true, can_report: false, can_reply: true, reply_count: 0, reactions: [] })
    expect(topic.symbols).toEqual([
      { symbol: "2330.TW", code: "2330", name: "台積電" },
      { symbol: "0050.TW", code: "0050", name: "元大台灣50" },
    ])
    expect(topic.created_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
    expect((await api.listTopics({ scope: "public", symbol: "2330.TW" })).items[0]!.id).toBe(topic.id)
    expect(await failure(api.createTopic({ scope: "group", group_id: "grp_family", title: "標題", body: "內文", symbols: ["NOPE"] }))).toMatchObject({ status: 422, code: "unknown_symbol" })
    expect((await failure(api.createTopic({ scope: "group", group_id: "grp_family", title: "標題", body: "內文", symbols: ["2330", "0050", "0056", "00878", "2454", "2317"] }))).status).toBe(422)
    expect((await failure(api.createTopic({ scope: "public", group_id: "grp_family", title: "標題", body: "內文" }))).status).toBe(422)
    expect((await failure(api.createTopic({ scope: "group", title: "標題", body: "內文" }))).status).toBe(422)
    expect((await failure(api.createTopic({ scope: "group", group_id: "grp_club", title: "標題", body: "內文" }))).status).toBe(404)
  })
  it("頻率：任兩則公開發言至少間隔 10 秒 → 429 rate_limited 帶 retry_after_seconds；群組發言沒有間隔", async () => {
    const { api, tick } = named()
    await api.createReply("top_p_etf", { body: "第一則" })
    const err = await failure(api.createReply("top_p_tsmc", { body: "第二則" }))
    expect(err).toMatchObject({ status: 429, code: "rate_limited" })
    expect(err.extra.retry_after_seconds).toBe(10)
    tick(4_000)
    expect((await failure(api.createTopic({ scope: "public", title: "標題", body: "內文" }))).extra.retry_after_seconds).toBe(6)
    // 群組不受公開的間隔影響
    await api.createReply("top_g_dca", { body: "群組一" })
    await api.createReply("top_g_dca", { body: "群組二" })
    tick(6_000)
    expect((await api.createReply("top_p_tsmc", { body: "第二則" })).body).toBe("第二則")
  })
  it("頻率：公開主題一天 5 則（滾動 24 小時）；刪掉主題不會把額度還回來", async () => {
    const { api, tick } = named()
    const ids: string[] = []
    for (let i = 0; i < 5; i++) {
      ids.push((await api.createTopic({ scope: "public", title: `主題 ${i}`, body: "內文" })).id)
      tick(60_000)
    }
    await api.deleteTopic(ids[0]!)
    const err = await failure(api.createTopic({ scope: "public", title: "第六則", body: "內文" }))
    expect(err).toMatchObject({ status: 429, code: "rate_limited" })
    // 最早那一則離開 24 小時的視窗才行：已經過了 5 分鐘
    expect(err.extra.retry_after_seconds).toBe(86_400 - 300)
    tick(86_400_000 - 300_000)
    expect((await api.createTopic({ scope: "public", title: "第六則", body: "內文" })).title).toBe("第六則")
  })
  it("回覆更新主題的最後活動時間與回覆數；刪掉回覆退回剩下最新的那一則", async () => {
    const { api } = named()
    const before = await api.getTopic("top_p_us")
    const reply = await api.createReply("top_p_us", { body: "兩種我都用過。" })
    const after = await api.getTopic("top_p_us")
    expect(after.reply_count).toBe(before.reply_count + 1)
    expect(after.last_activity_at).toBe(reply.created_at)
    expect((await api.listTopics({ scope: "public" })).items[0]!.id).toBe("top_p_us")
    await api.deleteReply(reply.id)
    expect((await api.getTopic("top_p_us")).last_activity_at).toBe(before.last_activity_at)
  })
  it("刪除：作者可以刪自己的；公開內容別人不能刪（站方管理員也不行，只能隱藏）；群組的擁有者可以刪成員的", async () => {
    const { api } = named()
    expect((await failure(api.deleteTopic("top_p_etf"))).status).toBe(403)
    expect((await failure(api.deleteReply("rep_p_etf_1"))).status).toBe(403)
    await api.deleteReply("rep_g_dca_1")
    expect((await api.listReplies("top_g_dca")).items.map((r) => r.id)).toEqual(["rep_g_dca_2", "rep_g_dca_3"])
    await api.deleteTopic("top_g_red")
    expect((await failure(api.getTopic("top_g_red"))).status).toBe(404)
    expect((await failure(api.listReplies("top_g_red"))).status).toBe(404)
  })
  it("刪除群組時，連同它的主題一起刪", async () => {
    const { api } = fresh()
    await api.deleteGroup("grp_family")
    expect((await failure(api.getTopic("top_g_dca"))).status).toBe(404)
    expect((await api.listTopics({ scope: "all" })).items.every((t) => t.group?.id !== "grp_family")).toBe(true)
  })
})

describe("表情", () => {
  it("PUT 重複呼叫不重複計、DELETE 收回；六個固定的表情以外 → 422；看不到的對象 404", async () => {
    const { api } = fresh()
    const count = async () => (await api.getTopic("top_p_us")).reactions
    expect(await count()).toEqual([{ emoji: "👀", count: 2, mine: false }])
    expect(await api.addDiscussionReaction({ target: "topic:top_p_us", emoji: "👀" })).toBeUndefined()
    await api.addDiscussionReaction({ target: "topic:top_p_us", emoji: "👀" })
    await api.addDiscussionReaction({ target: "topic:top_p_us", emoji: "👍" })
    expect(await count()).toEqual([
      { emoji: "👍", count: 1, mine: true },
      { emoji: "👀", count: 3, mine: true },
    ])
    await api.removeDiscussionReaction("topic:top_p_us", "👀")
    expect(await count()).toEqual([
      { emoji: "👍", count: 1, mine: true },
      { emoji: "👀", count: 2, mine: false },
    ])
    await api.addDiscussionReaction({ target: "reply:rep_p_us_1", emoji: "🎉" })
    expect((await api.listReplies("top_p_us")).items[0]!.reactions).toEqual([{ emoji: "🎉", count: 1, mine: true }])
    expect((await failure(api.addDiscussionReaction({ target: "topic:top_p_us", emoji: "💩" as never }))).status).toBe(422)
    expect((await failure(api.addDiscussionReaction({ target: "topic:top_nope", emoji: "👍" }))).status).toBe(404)
    expect((await failure(api.addDiscussionReaction({ target: "comment:1", emoji: "👍" }))).status).toBe(422)
  })
})

describe("隱藏", () => {
  it("被隱藏的回覆留在原位、body null；作者本人與站方管理員仍拿得到原文", async () => {
    const hidden = (items: { id: string; status: string; body: string | null }[]) => items.find((r) => r.id === "rep_p_tsmc_2")!
    const visitor = hidden((await fresh({ signedIn: false }).api.listReplies("top_p_tsmc")).items)
    expect(visitor).toMatchObject({ status: "hidden", body: null })
    const member = hidden((await fresh({ discussion: { admin: false } }).api.listReplies("top_p_tsmc")).items)
    expect(member).toMatchObject({ status: "hidden", body: null })
    const admin = hidden((await fresh().api.listReplies("top_p_tsmc")).items)
    expect(admin.status).toBe("hidden")
    expect(admin.body).toMatch(/保證獲利/)
    // 回覆數含被隱藏的
    expect((await fresh({ signedIn: false }).api.getTopic("top_p_tsmc")).reply_count).toBe(5)
  })
  it("被隱藏的主題不出現在任何清單；直接打開是佔位標題、body null、沒有標記、不能回覆（409 topic_hidden）", async () => {
    const { api } = named({ discussion: { publicName: "示範小資", admin: false } })
    expect(await titles(api, { scope: "all" })).not.toContain("免費飆股群組，今天開放加入")
    const topic = await api.getTopic("top_p_ad")
    expect(topic).toMatchObject({ status: "hidden", body: null, title: "（已被站方隱藏的主題）", symbols: [], can_reply: false })
    expect(await failure(api.createReply("top_p_ad", { body: "還在嗎" }))).toMatchObject({ status: 409, code: "topic_hidden" })
    // 站方管理員拿得到原本的標題與內文
    const admin = await fresh().api.getTopic("top_p_ad")
    expect(admin).toMatchObject({ status: "hidden", title: "免費飆股群組，今天開放加入" })
    expect(admin.body).toMatch(/加 LINE/)
  })
})

describe("檢舉", () => {
  it("只能檢舉公開的、別人的內容；同一人對同一則重複檢舉只算一次；note 最多 300 字", async () => {
    const { api } = named()
    expect((await api.getTopic("top_p_etf")).can_report).toBe(true)
    expect(await api.reportDiscussion({ target: "reply:rep_p_etf_1", reason: "other", note: "  離題  " })).toBeUndefined()
    await api.reportDiscussion({ target: "reply:rep_p_etf_1", reason: "spam" })
    const open = (await api.listAdminReports({ status: "open" })).items
    expect(open[0]).toMatchObject({ target: "reply:rep_p_etf_1", kind: "reply", topic_id: "top_p_etf", author_name: "定期定額派", report_count: 1, reasons: { other: 1 }, notes: ["離題"], status: "open", hidden: false })
    expect((await failure(api.reportDiscussion({ target: "topic:top_g_dca", reason: "spam" }))).status).toBe(422)
    const mine = await api.createReply("top_p_etf", { body: "自己的回覆" })
    expect(mine.can_report).toBe(false)
    expect((await failure(api.reportDiscussion({ target: `reply:${mine.id}`, reason: "spam" }))).status).toBe(422)
    expect((await failure(api.reportDiscussion({ target: "topic:top_p_etf", reason: "rude" as never }))).status).toBe(422)
    expect((await failure(api.reportDiscussion({ target: "topic:top_p_etf", reason: "other", note: "字".repeat(301) }))).status).toBe(422)
  })
  it("每人每小時 20 則新的檢舉 → 429 rate_limited 帶 retry_after_seconds", async () => {
    const { api, tick } = named()
    const targets = [
      ...(await api.listTopics({ scope: "public" })).items.map((t) => `topic:${t.id}`),
      ...["rep_p_etf_1", "rep_p_etf_2", "rep_p_etf_3", "rep_p_etf_4", "rep_p_tsmc_1", "rep_p_tsmc_3", "rep_p_tsmc_4", "rep_p_tsmc_5", "rep_p_yield_1", "rep_p_yield_2", "rep_p_day_1", "rep_p_day_2", "rep_p_odd_1"].map((id) => `reply:${id}`),
    ]
    expect(targets.length).toBe(21)
    for (const target of targets.slice(0, 20)) {
      await api.reportDiscussion({ target, reason: "other" })
      tick(1_000)
    }
    const err = await failure(api.reportDiscussion({ target: targets[20]!, reason: "other" }))
    expect(err).toMatchObject({ status: 429, code: "rate_limited" })
    expect(err.extra.retry_after_seconds).toBe(3_600 - 20)
  })
})

describe("站方管理（只管公開內容）", () => {
  it("不是管理員 → 404（讀與寫都是）", async () => {
    const { api } = fresh({ discussion: { admin: false } })
    expect((await failure(api.listAdminReports())).status).toBe(404)
    expect((await failure(api.listSuspensions())).status).toBe(404)
    expect((await failure(api.moderateDiscussion({ target: "reply:rep_p_tsmc_3", action: "hide" }))).status).toBe(404)
    expect((await failure(api.createSuspension({ target: "reply:rep_p_tsmc_3", days: 1 }))).status).toBe(404)
    expect((await failure(api.liftSuspension("sus_tout"))).status).toBe(404)
  })
  it("檢舉依對象彙整、依最近一次檢舉排序；不回傳 email、user_id；主題的 excerpt 是「標題｜內文」", async () => {
    const { api } = fresh()
    const open = await api.listAdminReports({ status: "open" })
    expect(open.items.map((r) => r.target)).toEqual(["reply:rep_p_tsmc_3", "reply:rep_p_div_2"])
    expect(open.items[1]).toMatchObject({ kind: "reply", author_name: "領息達人", topic_id: "top_p_div", report_count: 3, reasons: { solicitation: 2, spam: 1 }, notes: ["同一句話貼在好幾個主題"], status: "open", hidden: false })
    expect(open.items[1]!.first_reported_at).toBe("2026-11-06T02:30:00Z")
    const resolved = await api.listAdminReports({ status: "resolved" })
    expect(resolved.items.map((r) => r.target)).toEqual(["reply:rep_p_tsmc_2", "topic:top_p_ad"])
    expect(resolved.items[1]).toMatchObject({ kind: "topic", hidden: true, status: "resolved", report_count: 4 })
    expect(resolved.items[1]!.excerpt).toMatch(/^免費飆股群組，今天開放加入｜盤前給名單/)
    expect(JSON.stringify([open, resolved, await api.listSuspensions()])).not.toMatch(/usr_|@|email/)
  })
  it("hide 隱藏並把檢舉標為已處理；dismiss 不隱藏、標為已處理；unhide 重新公開；再被檢舉會回到待處理", async () => {
    const { api } = named()
    await api.moderateDiscussion({ target: "reply:rep_p_tsmc_3", action: "hide" })
    expect((await api.listAdminReports({ status: "open" })).items.map((r) => r.target)).toEqual(["reply:rep_p_div_2"])
    expect((await api.listAdminReports({ status: "resolved" })).items[0]).toMatchObject({ target: "reply:rep_p_tsmc_3", hidden: true, status: "resolved" })
    await api.moderateDiscussion({ target: "reply:rep_p_div_2", action: "dismiss" })
    expect((await api.listAdminReports({ status: "open" })).items).toEqual([])
    expect((await api.listReplies("top_p_div")).items[1]).toMatchObject({ status: "visible" })
    await api.moderateDiscussion({ target: "reply:rep_p_tsmc_3", action: "unhide" })
    expect((await api.listReplies("top_p_tsmc")).items[2]).toMatchObject({ status: "visible" })
    // 已處理過的對象再被別人檢舉：回到待處理，次數含已處理的
    await api.reportDiscussion({ target: "reply:rep_p_div_2", reason: "spam" })
    expect((await api.listAdminReports({ status: "open" })).items[0]).toMatchObject({ target: "reply:rep_p_div_2", report_count: 4, status: "open" })
    // 沒有人檢舉的公開內容也可以直接隱藏；群組內容對站方不存在
    await api.moderateDiscussion({ target: "topic:top_p_day", action: "hide" })
    expect(await titles(api, { scope: "public" })).not.toContain("定期定額的扣款日，選幾號有差嗎？")
    expect((await failure(api.moderateDiscussion({ target: "topic:top_g_dca", action: "hide" }))).status).toBe(404)
  })
  it("停權：days 必填（永久要明確傳 null）；對已停權的人再停權是更新同一筆；解除後不在清單裡", async () => {
    const { api } = fresh()
    expect(await api.listSuspensions()).toEqual([{ id: "sus_tout", public_name: "飆股情報站", until: "2026-12-11T14:30:00Z", reason: "重複張貼招攬訊息", created_at: "2026-11-11T14:30:00Z" }])
    expect((await failure(api.createSuspension({ target: "reply:rep_p_div_2" } as never))).status).toBe(422)
    expect((await failure(api.createSuspension({ target: "reply:rep_p_div_2", days: 3 as never }))).status).toBe(422)
    const s = await api.createSuspension({ target: "reply:rep_p_div_2", days: 7, reason: " 洗版 " })
    expect(s).toMatchObject({ public_name: "領息達人", reason: "洗版" })
    expect(Date.parse(s.until) - Date.parse(s.created_at)).toBe(7 * 86_400_000)
    const again = await api.createSuspension({ target: "reply:rep_p_div_2", days: null })
    expect(again).toMatchObject({ id: s.id, until: PERMANENT_UNTIL, reason: null })
    expect((await api.listSuspensions()).map((x) => x.id)).toEqual([s.id, "sus_tout"])
    // 作者帳號已刪除 → 422；群組內容 → 404
    expect((await failure(api.createSuspension({ target: "reply:rep_p_yield_3", days: 1 }))).status).toBe(422)
    expect((await failure(api.createSuspension({ target: "reply:rep_g_dca_1", days: 1 }))).status).toBe(404)
    expect(await api.liftSuspension("sus_tout")).toBeUndefined()
    expect((await api.listSuspensions()).map((x) => x.id)).toEqual([s.id])
    expect((await failure(api.liftSuspension("sus_nope"))).status).toBe(404)
  })
})

describe("查看別人的資產（X-Forliosa-View-As）", () => {
  it("討論的讀取以登入者本人回答；寫入是 read_only；站方管理的讀取不允許", async () => {
    const { useViewAs } = await import("@/api/view-as")
    const { api } = named()
    const dad = (await api.listDelegations()).received[0]!
    useViewAs.getState().set({ delegation_id: dad.id, owner: dad.owner, scope: dad.scope, accounts: dad.accounts })
    try {
      expect((await api.getTopic("top_g_fix")).mine).toBe(true)
      expect((await api.listTopics({ scope: "all" })).items.length).toBe(12)
      expect((await api.listReplies("top_g_fix")).items.length).toBe(1)
      expect(await failure(api.createReply("top_g_fix", { body: "嗨" }))).toMatchObject({ status: 403, code: "read_only" })
      expect(await failure(api.addDiscussionReaction({ target: "topic:top_g_fix", emoji: "👍" }))).toMatchObject({ status: 403, code: "read_only" })
      expect(await failure(api.listAdminReports())).toMatchObject({ status: 403, code: "view_as_not_allowed" })
      // 公開暱稱是查看者自己的事：不受查看模式影響
      expect((await api.setPublicName("示範小資")).public_name).toBe("示範小資")
    } finally {
      useViewAs.getState().set(null)
    }
  })
})
