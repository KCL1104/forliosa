import {
  ApiError,
  REACTION_EMOJIS,
  type Account,
  type Channels,
  type Comment,
  type Delegation,
  type DelegationCandidate,
  type DelegationInput,
  type DelegationList,
  type Digest,
  type FeedItem,
  type Group,
  type GroupHoldings,
  type GroupInvite,
  type GroupMember,
  type GroupRole,
  type GroupSummary,
  type InviteInput,
  type InvitePreview,
  type Leaderboard,
  type LeaderboardEntry,
  type LeaderboardPeriod,
  type Paged,
  type PushTarget,
  type Reaction,
  type ReactionEmoji,
  type ShareSettings,
  type SharedHolding,
  type SharedPortfolio,
  type TelegramLinkCode,
  type UserRef,
} from "../types"
import { sourceOf } from "./attributions"
import { ARCHIVE_START } from "./commercial"
import { findInstrument } from "./instruments"
import { addDays, closeOn, MOCK_TODAY, parseDay } from "./market"
import { PEOPLE, STATIC_PROFILES, type PeriodReturns, type RawTrade } from "./members"

/**
 * 分享（M5）的 mock：群組、授權查看、動態、留言與表情、週報、頻道。
 * 隱私規則和合約一樣（docs/api-contract.md「分享（M5）」）：
 * - 每次讀取時依「目前」的分享設定重新投影；沒開放的鍵不存在，不是 null 也不是 0。
 * - 沒開放的成員不出現在排行、動態、持股；`SharedPortfolio` 沒開任何項目時只回身分欄位。
 * - 不是成員 → 404 not_found；權限不足 → 403 forbidden；看不到的留言對象一律 404。
 */

export const DEFAULT_SHARE: ShareSettings = { returns: true, holdings: false, amounts: false, trades: false, trade_prices: false, push: false }

/** 一位成員可以分享的東西（我與爸爸從帳本算；其他人是固定的示範數字） */
export interface MemberSource {
  returns(): PeriodReturns
  holdings(): SharedHolding[]
  amounts(): { market_value: number; day_change: number; total_pnl: number }
  trades(): RawTrade[]
  week(weekStart: string): number | null
}

export interface SharingDeps {
  me(): UserRef
  signedIn(): boolean
  commercial: boolean
  myAccounts(): Account[]
  mine: MemberSource
  dad: MemberSource
  dadAccounts: Account[]
  /** 邀請連結的網址前綴 */
  origin(): string
}

interface MockMember {
  ref: UserRef
  role: GroupRole
  joined_at: string
  share: ShareSettings
}
interface MockInvite {
  id: string
  token: string
  expires_at: string
  multi_use: boolean
  uses: number
  revoked: boolean
  inviter: string
}
interface MockComment {
  id: string
  target: string
  user_id: string
  body: string
  created_at: string
}
interface MockDigest {
  id: string
  week_start: string
  week_end: string
  created_at: string
  status: Digest["status"]
  summary: string | null
}
interface MockDiscord {
  hint: string
  status: "active" | "disabled"
  disabled_reason: string | null
  notify_trades: boolean
  notify_digest: boolean
}
interface MockTelegram {
  chat_title: string
  status: "active" | "disabled"
  disabled_reason: string | null
  notify_trades: boolean
  notify_digest: boolean
}
interface MockGroup {
  id: string
  name: string
  ranking_enabled: boolean
  created_at: string
  members: MockMember[]
  /** 離開或被移除的人：留言顯示「已離開的成員」 */
  former: Set<string>
  invites: MockInvite[]
  comments: MockComment[]
  reactions: Map<string, Map<ReactionEmoji, Set<string>>>
  digests: MockDigest[]
  discord: MockDiscord | null
  telegram: MockTelegram | null
  telegramLink: { code: string; expires_at: string; linkAt: number } | null
}

const DISCLAIMER = "AI 分析僅供參考，不構成投資建議。"
/** 加權報酬指數的存檔起點（後端 CONTRACT_NOTES：證交所 2026-11-02 起） */
const INDEX_ARCHIVE_START = "2026-11-02"
const MAX_MEMBERS = 50
const MAX_GROUPS = 20

const r4 = (x: number | null): number | null => (x === null ? null : Math.round(x * 10000) / 10000)
const r2 = (x: number) => Math.round(x * 100) / 100

function prevTradingDay(day: string): string {
  let d = addDays(day, -1)
  while ([0, 6].includes(parseDay(d).getUTCDay())) d = addDays(d, -1)
  return d
}
/** 某天（含）之前最後一個交易日 */
function lastTradingDayOnOrBefore(day: string): string {
  let d = day
  while ([0, 6].includes(parseDay(d).getUTCDay())) d = addDays(d, -1)
  return d
}

/** 台北時間的 ISO 字串（+08:00） */
function isoTaipei(ms: number): string {
  return `${new Date(ms + 8 * 3600_000).toISOString().slice(0, 19)}+08:00`
}

const roleRank: Record<GroupRole, number> = { owner: 0, admin: 1, member: 2 }

export function createSharingStore(deps: SharingDeps, scenario: "default" | "empty" | "stress" = "default") {
  // mock 的時鐘：示範資料的「現在」是 11/12 13:30，之後每個動作往後一分鐘
  let clock = Date.parse("2026-11-12T13:30:00+08:00")
  const now = () => isoTaipei((clock += 60_000))
  let nextId = 100
  const id = (prefix: string) => `${prefix}_${++nextId}`

  const meId = () => deps.me().user_id
  const meRef = (): UserRef => ({ ...deps.me() })
  const member = (ref: UserRef, role: GroupRole, joined_at: string, share: Partial<ShareSettings>): MockMember => ({
    ref, role, joined_at, share: { ...DEFAULT_SHARE, ...share },
  })

  const groups: MockGroup[] = []
  const extraPeople: UserRef[] = []
  const delegations: { id: string; owner: UserRef; viewer: UserRef; scope: "all" | "accounts"; account_ids: string[]; created_at: string }[] = []

  if (scenario !== "empty") {
    const me = meRef()
    const family: MockGroup = {
      id: "grp_family", name: "家族投資", ranking_enabled: true, created_at: "2026-09-28T20:00:00+08:00",
      members: [
        member(me, "owner", "2026-09-28T20:00:00+08:00", { returns: true, holdings: true, trades: true }),
        member(PEOPLE.dad, "admin", "2026-09-28T20:40:00+08:00", { returns: true, holdings: true, amounts: true, trades: true, trade_prices: true, push: true }),
        member(PEOPLE.mom, "member", "2026-09-29T08:12:00+08:00", { returns: true, holdings: true }),
        member(PEOPLE.sis, "member", "2026-10-02T22:05:00+08:00", { returns: true, trades: true, push: true }),
        // 阿弟：所有開關都關（包括報酬率）
        member(PEOPLE.bro, "member", "2026-11-10T19:48:00+08:00", { returns: false }),
      ],
      former: new Set([PEOPLE.wang.user_id]),
      invites: [
        { id: "inv_family_open", token: "family-open", expires_at: "2026-11-16T21:00:00+08:00", multi_use: true, uses: 2, revoked: false, inviter: me.user_id },
        { id: "inv_family_bro", token: "family-bro", expires_at: "2026-11-17T19:30:00+08:00", multi_use: false, uses: 1, revoked: false, inviter: me.user_id },
      ],
      comments: [],
      reactions: new Map(),
      digests: [
        {
          id: "gdg_family_1102", week_start: "2026-11-02", week_end: "2026-11-06", created_at: "2026-11-07T20:06:00+08:00", status: "ready",
          summary: "這週群組整體小幅上漲，多數人的週報酬落在 0.6% 到 1.8% 之間，和 0050 差不多。共同持股仍以半導體為主，台積電是最多人持有的一檔；交易以 ETF 的定期定額買進為主，個股進出不多。",
        },
        {
          id: "gdg_family_1026", week_start: "2026-10-26", week_end: "2026-10-30", created_at: "2026-10-31T20:04:00+08:00", status: "ready",
          summary: "這週群組的表現有些分歧，有人小幅下跌、也有人小賺，整體和大盤接近持平。持股重疊集中在半導體與高股息 ETF；這週的買賣比前一週多，主要是零股與 ETF。",
        },
      ],
      discord: { hint: "…/x9Kd", status: "active", disabled_reason: null, notify_trades: true, notify_digest: true },
      telegram: null,
      telegramLink: null,
    }
    const friends: MockGroup = {
      id: "grp_friends", name: "大學同學", ranking_enabled: false, created_at: "2026-10-05T21:30:00+08:00",
      members: [
        member(PEOPLE.kai, "owner", "2026-10-05T21:30:00+08:00", { returns: true, holdings: true, trades: true, trade_prices: true }),
        member(PEOPLE.yun, "admin", "2026-10-05T21:42:00+08:00", { returns: true, holdings: true, trades: true }),
        member(PEOPLE.ming, "member", "2026-10-15T12:20:00+08:00", { returns: true }),
        member(me, "member", "2026-10-20T22:10:00+08:00", { returns: true }),
      ],
      former: new Set(),
      invites: [],
      comments: [],
      reactions: new Map(),
      digests: [],
      discord: null,
      telegram: { chat_title: "大學同學投資群", status: "disabled", disabled_reason: "Bot 已被移出 Telegram 群組", notify_trades: true, notify_digest: true },
      telegramLink: null,
    }
    const club: MockGroup = {
      id: "grp_club", name: "投資讀書會", ranking_enabled: true, created_at: "2026-08-01T19:00:00+08:00",
      members: [
        member(PEOPLE.lin, "owner", "2026-08-01T19:00:00+08:00", { returns: true, holdings: true }),
        member(PEOPLE.chen, "member", "2026-08-03T21:00:00+08:00", { returns: true }),
      ],
      former: new Set(),
      invites: [
        { id: "inv_club", token: "club-2026", expires_at: "2026-11-18T19:00:00+08:00", multi_use: true, uses: 1, revoked: false, inviter: PEOPLE.lin.user_id },
        { id: "inv_club_old", token: "club-expired", expires_at: "2026-11-01T19:00:00+08:00", multi_use: false, uses: 0, revoked: false, inviter: PEOPLE.lin.user_id },
      ],
      comments: [],
      reactions: new Map(),
      digests: [],
      discord: null,
      telegram: null,
      telegramLink: null,
    }
    groups.push(family, friends, club)

    const dadBuy = `trade:gfi_${PEOPLE.dad.user_id}_${MOCK_TODAY}_2330.TW_buy`
    const sisSell = `trade:gfi_${PEOPLE.sis.user_id}_2026-10-28_2603.TW_sell`
    const broBuy = `trade:gfi_${PEOPLE.bro.user_id}_2026-11-10_2603.TW_buy`
    family.comments.push(
      { id: "gcm_1", target: dadBuy, user_id: PEOPLE.sis.user_id, body: "又加碼台積電了！", created_at: `${MOCK_TODAY}T11:20:00+08:00` },
      { id: "gcm_2", target: dadBuy, user_id: PEOPLE.dad.user_id, body: "零股慢慢買，放著當退休金。", created_at: `${MOCK_TODAY}T11:34:00+08:00` },
      { id: "gcm_3", target: sisSell, user_id: PEOPLE.bro.user_id, body: "長榮賣掉了？", created_at: "2026-10-28T12:02:00+08:00" },
      { id: "gcm_4", target: `leaderboard:${MOCK_TODAY}`, user_id: PEOPLE.mom.user_id, body: "今天大家都紅的 🎉", created_at: `${MOCK_TODAY}T13:36:00+08:00` },
      { id: "gcm_5", target: "digest:gdg_family_1102", user_id: PEOPLE.dad.user_id, body: "這週定期定額照常扣，大家不用急。", created_at: "2026-11-07T21:10:00+08:00" },
      { id: "gcm_6", target: "digest:gdg_family_1102", user_id: PEOPLE.wang.user_id, body: "謝謝分享，我先退出了。", created_at: "2026-11-08T09:00:00+08:00" },
      // 阿弟沒開交易動態：這則留言的對象看不到（GET 留言 404，計數也不算）
      { id: "gcm_7", target: broBuy, user_id: PEOPLE.dad.user_id, body: "長榮又買？", created_at: "2026-11-10T20:00:00+08:00" },
    )
    family.reactions.set(dadBuy, new Map([["👍", new Set([PEOPLE.sis.user_id, PEOPLE.mom.user_id])], ["🔥", new Set([me.user_id])]]))
    family.reactions.set(`leaderboard:${MOCK_TODAY}`, new Map([["🎉", new Set([PEOPLE.mom.user_id, PEOPLE.dad.user_id, me.user_id])]]))
    family.reactions.set("digest:gdg_family_1102", new Map([["👍", new Set([PEOPLE.dad.user_id])]]))
    family.reactions.set(broBuy, new Map([["😮", new Set([PEOPLE.mom.user_id])]]))
    friends.comments.push({ id: "gcm_8", target: `trade:gfi_${PEOPLE.kai.user_id}_2026-11-11_2382.TW_buy`, user_id: PEOPLE.yun.user_id, body: "廣達一次兩張，猛", created_at: "2026-11-11T09:50:00+08:00" })

    delegations.push(
      { id: "dlg_dad", owner: PEOPLE.dad, viewer: me, scope: "accounts", account_ids: ["acc_dad_yuanta"], created_at: "2026-11-10T21:00:00+08:00" },
      { id: "dlg_mom", owner: me, viewer: PEOPLE.mom, scope: "all", account_ids: [], created_at: "2026-11-11T08:30:00+08:00" },
    )
  }

  // ── 存取 ──
  const requireSignedIn = () => {
    if (!deps.signedIn()) throw new ApiError(401, "unauthorized", "請先登入")
  }
  const notFound = () => new ApiError(404, "not_found", "找不到這個群組")
  const forbidden = () => new ApiError(403, "forbidden", "你沒有權限做這件事")
  const findMember = (g: MockGroup, userId: string) => g.members.find((m) => m.ref.user_id === userId)
  /** 我的名稱可以改（PATCH /me）：輸出時一律用最新的 */
  const refOf = (m: MockMember): UserRef => (m.ref.user_id === meId() ? meRef() : m.ref)
  /** 是成員才看得到：不是成員一律 404（不透露群組是否存在） */
  const memberGroup = (groupId: string): { g: MockGroup; me: MockMember } => {
    requireSignedIn()
    const g = groups.find((x) => x.id === groupId)
    const me = g && findMember(g, meId())
    if (!g || !me) throw notFound()
    return { g, me }
  }
  const atLeast = (m: MockMember, role: GroupRole) => {
    if (roleRank[m.role] > roleRank[role]) throw forbidden()
  }
  const myGroups = () => groups.filter((g) => findMember(g, meId()))

  const sourceFor = (userId: string): MemberSource | null => {
    if (userId === meId()) return deps.mine
    if (userId === PEOPLE.dad.user_id) return deps.dad
    const p = STATIC_PROFILES[userId]
    if (!p) return null
    return { returns: () => p.returns, holdings: () => p.holdings, amounts: () => p.amounts, trades: () => p.trades, week: (w) => p.weeks[w] ?? null }
  }

  // ── 投影 ──
  const leaderboardDates = (period: LeaderboardPeriod) => {
    const date = lastTradingDayOnOrBefore(MOCK_TODAY)
    let start: string
    if (period === "day") start = prevTradingDay(date)
    else if (period === "month") start = lastTradingDayOnOrBefore(addDays(`${date.slice(0, 7)}-01`, -1))
    else start = lastTradingDayOnOrBefore(`${Number(date.slice(0, 4)) - 1}-12-31`)
    const clipped = deps.commercial && start < ARCHIVE_START
    return { date, start: clipped ? ARCHIVE_START : start, clipped }
  }
  const benchmarkReturn = (symbol: string, start: string, end: string): number | null => {
    if (symbol === "^TAIEXTR" && deps.commercial && start < INDEX_ARCHIVE_START) return null
    const spec = findInstrument("0050.TW")!
    const base = closeOn(spec, start)
    const r = closeOn(spec, end) / base - 1
    // 示範：報酬指數以 0050 的走勢代替，含息所以略高一點
    return r4(symbol === "^TAIEXTR" ? r + 0.0007 : r)
  }

  const visibleFeed = (g: MockGroup): Omit<FeedItem, "comment_count" | "reactions">[] => {
    const from = addDays(MOCK_TODAY, -90)
    const items: Omit<FeedItem, "comment_count" | "reactions">[] = []
    for (const m of g.members) {
      if (m.share.trades) {
        const src = sourceFor(m.ref.user_id)
        const merged = new Map<string, RawTrade[]>()
        for (const t of src?.trades() ?? []) {
          if (t.trade_date < from || t.trade_date > MOCK_TODAY) continue
          const key = `${t.trade_date}_${t.symbol}_${t.side}`
          merged.set(key, [...(merged.get(key) ?? []), t])
        }
        for (const [key, rows] of merged) {
          const first = rows[0]!
          const qty = rows.reduce((s, r) => s + r.quantity, 0)
          const item: Omit<FeedItem, "comment_count" | "reactions"> = {
            id: `gfi_${m.ref.user_id}_${key}`, type: "trade", user_id: m.ref.user_id, display_name: refOf(m).display_name, avatar_url: refOf(m).avatar_url,
            side: first.side, symbol: first.symbol, name: findInstrument(first.symbol)?.name ?? first.symbol, trade_date: first.trade_date, count: rows.length,
            created_at: rows.map((r) => r.created_at).sort().at(-1)!,
          }
          // 只有開了 trade_prices 才有 price／currency 這兩個鍵（加權平均、不含費用）
          if (m.share.trade_prices) {
            item.price = Math.round((rows.reduce((s, r) => s + r.price * r.quantity, 0) / qty) * 100) / 100
            item.currency = first.currency
          }
          items.push(item)
        }
      }
      // 加入的事實每個人都看得到（建立者不算「加入」）
      if (m.joined_at > g.created_at) {
        items.push({ id: `gfi_join_${m.ref.user_id}`, type: "member_joined", user_id: m.ref.user_id, display_name: refOf(m).display_name, avatar_url: refOf(m).avatar_url, created_at: m.joined_at })
      }
    }
    const day = (x: { trade_date?: string; created_at: string }) => x.trade_date ?? x.created_at.slice(0, 10)
    return items.sort((a, b) => day(b).localeCompare(day(a)) || b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
  }

  const holdingsOf = (userId: string): SharedHolding[] =>
    (sourceFor(userId)?.holdings() ?? []).map((x) => ({ symbol: x.symbol, name: x.name, weight: Math.round(x.weight * 100) / 100 }))

  const overlap = (members: { symbols: string[] }[]) => {
    const bySymbol = new Map<string, number>()
    const byIndustry = new Map<string, number>()
    for (const m of members) {
      for (const s of new Set(m.symbols)) bySymbol.set(s, (bySymbol.get(s) ?? 0) + 1)
      const industries = new Set(
        m.symbols.map((s) => findInstrument(s)).filter((s) => s && s.market !== "US" && s.type === "stock" && s.industry).map((s) => s!.industry!),
      )
      for (const i of industries) byIndustry.set(i, (byIndustry.get(i) ?? 0) + 1)
    }
    const common = [...bySymbol]
      .filter(([, n]) => n >= 2)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([symbol, holder_count]) => ({ symbol, name: findInstrument(symbol)?.name ?? symbol, holder_count }))
    const industries = [...byIndustry].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-TW")).map(([industry, holder_count]) => ({ industry, holder_count }))
    return { common, industries }
  }

  /** 留言對象是否在目前的投影裡看得到 */
  const targetVisible = (g: MockGroup, target: string): boolean => {
    const [kind, ref] = [target.slice(0, target.indexOf(":")), target.slice(target.indexOf(":") + 1)]
    if (kind === "trade") return visibleFeed(g).some((i) => i.type === "trade" && i.id === ref)
    if (kind === "digest") return g.digests.some((d) => d.id === ref)
    if (kind === "leaderboard") return /^\d{4}-\d{2}-\d{2}$/.test(ref) && ref >= g.created_at.slice(0, 10) && ref <= MOCK_TODAY
    return false
  }
  const reactionsOf = (g: MockGroup, target: string): Reaction[] => {
    const map = g.reactions.get(target)
    if (!map) return []
    return REACTION_EMOJIS.filter((e) => (map.get(e)?.size ?? 0) > 0).map((emoji) => ({ emoji, count: map.get(emoji)!.size, mine: map.get(emoji)!.has(meId()) }))
  }
  const commentCount = (g: MockGroup, target: string) => g.comments.filter((c) => c.target === target).length

  const toGroup = (g: MockGroup, me: MockMember): Group => ({
    id: g.id, name: g.name, my_role: me.role, ranking_enabled: g.ranking_enabled, created_at: g.created_at,
    members: g.members.map((m): GroupMember => ({ ...refOf(m), role: m.role, joined_at: m.joined_at, is_me: m.ref.user_id === meId() })),
    my_share: { ...me.share },
    push_targets: pushTargets(g),
  })
  const pushTargets = (g: MockGroup): PushTarget[] => [
    ...(g.discord?.status === "active" ? [{ kind: "discord" as const, label: "Discord 頻道" }] : []),
    ...(g.telegram?.status === "active" ? [{ kind: "telegram" as const, label: g.telegram.chat_title }] : []),
  ]
  const paginate = <T>(rows: T[], limit: number, cursor?: string | null): Paged<T> => {
    const offset = cursor ? Number(cursor) : 0
    return { items: rows.slice(offset, offset + limit), next_cursor: offset + limit < rows.length ? String(offset + limit) : null }
  }
  const validShare = (s: ShareSettings) => {
    for (const k of ["returns", "holdings", "amounts", "trades", "trade_prices", "push"] as const) {
      if (typeof s?.[k] !== "boolean") throw new ApiError(422, "validation_error", "輸入資料格式錯誤：share")
    }
    return { returns: s.returns, holdings: s.holdings, amounts: s.amounts, trades: s.trades, trade_prices: s.trade_prices, push: s.push }
  }
  /** 移除成員時撤回所有可多次使用的邀請 */
  const leave = (g: MockGroup, userId: string) => {
    g.members = g.members.filter((m) => m.ref.user_id !== userId)
    g.former.add(userId)
    for (const inv of g.invites) if (inv.multi_use) inv.revoked = true
  }
  const inviteState = (token: string): { g: MockGroup; inv: MockInvite } => {
    for (const g of groups) {
      const inv = g.invites.find((i) => i.token === token)
      if (inv) {
        if (inv.revoked || inv.expires_at < isoTaipei(clock) || (!inv.multi_use && inv.uses >= 1)) {
          throw new ApiError(410, "invite_invalid", "這個邀請連結已經失效")
        }
        return { g, inv }
      }
    }
    throw new ApiError(404, "not_found", "找不到這個邀請連結")
  }
  const peopleIndex = () => {
    const map = new Map<string, UserRef>()
    for (const p of [...Object.values(PEOPLE), ...extraPeople]) map.set(p.user_id, p)
    return map
  }
  const delegationOut = (d: (typeof delegations)[number]): Delegation => {
    const ownerAccounts = d.owner.user_id === meId() ? deps.myAccounts() : d.owner.user_id === PEOPLE.dad.user_id ? deps.dadAccounts : []
    const accounts = (d.scope === "all" ? ownerAccounts : ownerAccounts.filter((a) => d.account_ids.includes(a.id))).map((a) => ({ id: a.id, name: a.name }))
    const owner = d.owner.user_id === meId() ? meRef() : d.owner
    const viewer = d.viewer.user_id === meId() ? meRef() : d.viewer
    return { id: d.id, owner, viewer, scope: d.scope, accounts, created_at: d.created_at }
  }
  const coMembers = (): UserRef[] => {
    const seen = new Map<string, UserRef>()
    for (const g of myGroups()) for (const m of g.members) if (m.ref.user_id !== meId() && !seen.has(m.ref.user_id)) seen.set(m.ref.user_id, m.ref)
    return [...seen.values()]
  }
  const checkAccounts = (scope: "all" | "accounts", ids: string[]) => {
    if (scope !== "all" && scope !== "accounts") throw new ApiError(422, "validation_error", "輸入資料格式錯誤：scope")
    if (scope === "accounts") {
      const mine = new Set(deps.myAccounts().map((a) => a.id))
      if (ids.length === 0 || ids.some((x) => !mine.has(x))) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：account_ids")
    }
  }

  return {
    // ── 授權查看 ──
    /** 授權查看：只有「別人授權給我、還有效」的才算；其他一律 delegation_revoked（不區分） */
    viewAsOwner(delegationId: string): { owner: UserRef; accountIds: string[] | "all" } {
      const d = delegations.find((x) => x.id === delegationId && x.viewer.user_id === meId())
      if (!d) throw new ApiError(403, "delegation_revoked", "這份授權已經撤銷或失效")
      return { owner: d.owner, accountIds: d.scope === "all" ? "all" : d.account_ids }
    },
    listDelegations(): DelegationList {
      requireSignedIn()
      return {
        granted: delegations.filter((d) => d.owner.user_id === meId()).map(delegationOut),
        received: delegations.filter((d) => d.viewer.user_id === meId()).map(delegationOut),
      }
    },
    listDelegationCandidates(): DelegationCandidate[] {
      requireSignedIn()
      return coMembers().map((p) => ({ ...p, delegation_id: delegations.find((d) => d.owner.user_id === meId() && d.viewer.user_id === p.user_id)?.id ?? null }))
    },
    createDelegation(body: DelegationInput): Delegation {
      requireSignedIn()
      const viewer = coMembers().find((p) => p.user_id === body.viewer_user_id)
      if (!viewer) throw new ApiError(404, "not_found", "找不到這位成員")
      if (delegations.some((d) => d.owner.user_id === meId() && d.viewer.user_id === viewer.user_id)) {
        throw new ApiError(409, "already_member", "已經授權給這位成員，請改用修改範圍")
      }
      checkAccounts(body.scope, body.account_ids ?? [])
      const d = { id: id("dlg"), owner: meRef(), viewer, scope: body.scope, account_ids: body.scope === "all" ? [] : [...body.account_ids], created_at: now() }
      delegations.push(d)
      return delegationOut(d)
    },
    updateDelegation(delegationId: string, patch: Pick<DelegationInput, "scope" | "account_ids">): Delegation {
      requireSignedIn()
      const d = delegations.find((x) => x.id === delegationId && x.owner.user_id === meId())
      if (!d) throw new ApiError(404, "not_found", "找不到這份授權")
      checkAccounts(patch.scope, patch.account_ids ?? [])
      d.scope = patch.scope
      d.account_ids = patch.scope === "all" ? [] : [...patch.account_ids]
      return delegationOut(d)
    },
    deleteDelegation(delegationId: string): void {
      requireSignedIn()
      const i = delegations.findIndex((x) => x.id === delegationId && (x.owner.user_id === meId() || x.viewer.user_id === meId()))
      if (i < 0) throw new ApiError(404, "not_found", "找不到這份授權")
      delegations.splice(i, 1)
    },

    // ── 群組 ──
    listGroups(): GroupSummary[] {
      requireSignedIn()
      return myGroups().map((g) => {
        const feed = visibleFeed(g)
        return {
          id: g.id, name: g.name, my_role: findMember(g, meId())!.role, member_count: g.members.length, ranking_enabled: g.ranking_enabled,
          latest_activity_at: feed[0]?.created_at ?? null,
          latest_digest_at: g.digests.find((d) => d.status === "ready")?.created_at ?? null,
        }
      })
    },
    createGroup(body: { name: string }): Group {
      requireSignedIn()
      const name = (body.name ?? "").trim()
      if (name.length < 1 || name.length > 40) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：name")
      if (myGroups().length >= MAX_GROUPS) throw new ApiError(409, "limit_reached", `每人最多加入 ${MAX_GROUPS} 個群組`)
      const at = now()
      const g: MockGroup = {
        id: id("grp"), name, ranking_enabled: true, created_at: at, members: [member(meRef(), "owner", at, {})], former: new Set(), invites: [],
        comments: [], reactions: new Map(), digests: [], discord: null, telegram: null, telegramLink: null,
      }
      groups.push(g)
      return toGroup(g, g.members[0]!)
    },
    getGroup(groupId: string): Group {
      const { g, me } = memberGroup(groupId)
      return toGroup(g, me)
    },
    updateGroup(groupId: string, patch: { name?: string; ranking_enabled?: boolean }): Group {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "admin")
      if (patch.ranking_enabled !== undefined) {
        atLeast(me, "owner")
        g.ranking_enabled = patch.ranking_enabled
      }
      if (patch.name !== undefined) {
        const name = patch.name.trim()
        if (name.length < 1 || name.length > 40) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：name")
        g.name = name
      }
      return toGroup(g, me)
    },
    deleteGroup(groupId: string): void {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      groups.splice(groups.indexOf(g), 1)
    },
    transferGroup(groupId: string, userId: string): Group {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      const to = findMember(g, userId)
      if (!to || to === me) throw new ApiError(404, "not_found", "找不到這位成員")
      to.role = "owner"
      me.role = "admin"
      return toGroup(g, me)
    },
    setMemberRole(groupId: string, userId: string, role: "admin" | "member"): Group {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      if (role !== "admin" && role !== "member") throw new ApiError(422, "validation_error", "輸入資料格式錯誤：role")
      const target = findMember(g, userId)
      if (!target) throw new ApiError(404, "not_found", "找不到這位成員")
      if (target.role === "owner") throw forbidden()
      target.role = role
      return toGroup(g, me)
    },
    removeMember(groupId: string, userId: string): void {
      const { g, me } = memberGroup(groupId)
      const target = findMember(g, userId)
      if (!target) throw new ApiError(404, "not_found", "找不到這位成員")
      if (target === me) {
        if (me.role === "owner") throw new ApiError(403, "forbidden", "擁有者要先把群組轉給別人才能離開")
      } else {
        atLeast(me, "admin")
        if (target.role === "owner" || (me.role === "admin" && target.role === "admin")) throw forbidden()
      }
      leave(g, userId)
    },
    createInvite(groupId: string, body: InviteInput): GroupInvite {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "admin")
      const expires = body.expires ?? "7d"
      if (expires !== "24h" && expires !== "7d") throw new ApiError(422, "validation_error", "輸入資料格式錯誤：expires")
      const token = `${g.id.replace("grp_", "")}-${(++nextId).toString(36)}${Math.random().toString(36).slice(2, 8)}`
      const created = now()
      const inv: MockInvite = {
        id: id("inv"), token, expires_at: isoTaipei(Date.parse(created) + (expires === "24h" ? 24 : 168) * 3600_000), multi_use: !!body.multi_use, uses: 0,
        revoked: false, inviter: meId(),
      }
      g.invites.push(inv)
      return { id: inv.id, url: `${deps.origin()}/invite/${token}`, expires_at: inv.expires_at, multi_use: inv.multi_use, uses: 0 }
    },
    listInvites(groupId: string): GroupInvite[] {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "admin")
      const at = isoTaipei(clock)
      return g.invites
        .filter((i) => !i.revoked && i.expires_at >= at && (i.multi_use || i.uses === 0))
        .map((i) => ({ id: i.id, expires_at: i.expires_at, multi_use: i.multi_use, uses: i.uses }))
    },
    revokeInvite(groupId: string, inviteId: string): void {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "admin")
      const inv = g.invites.find((i) => i.id === inviteId)
      if (!inv) throw new ApiError(404, "not_found", "找不到這個邀請")
      inv.revoked = true
    },
    getInvite(token: string): InvitePreview {
      const { g, inv } = inviteState(token)
      const inviter = peopleIndex().get(inv.inviter) ?? (inv.inviter === meId() ? meRef() : undefined)
      return {
        group_name: g.name,
        inviter_display_name: inviter?.display_name ?? "群組成員",
        status: deps.signedIn() && findMember(g, meId()) ? "member" : "valid",
      }
    },
    acceptInvite(token: string, share: ShareSettings): Group {
      requireSignedIn()
      const { g, inv } = inviteState(token)
      if (findMember(g, meId())) throw new ApiError(409, "already_member", "你已經是這個群組的成員")
      const settings = validShare(share)
      if (g.members.length >= MAX_MEMBERS) throw new ApiError(409, "limit_reached", `每個群組最多 ${MAX_MEMBERS} 位成員`)
      if (myGroups().length >= MAX_GROUPS) throw new ApiError(409, "limit_reached", `每人最多加入 ${MAX_GROUPS} 個群組`)
      inv.uses += 1
      const m: MockMember = { ref: meRef(), role: "member", joined_at: now(), share: settings }
      g.members.push(m)
      g.former.delete(meId())
      return toGroup(g, m)
    },
    getShare(groupId: string): ShareSettings {
      return { ...memberGroup(groupId).me.share }
    },
    putShare(groupId: string, share: ShareSettings): ShareSettings {
      const { me } = memberGroup(groupId)
      me.share = validShare(share)
      return { ...me.share }
    },

    // ── 排行、持股、成員分享 ──
    getLeaderboard(groupId: string, period: LeaderboardPeriod): Leaderboard {
      const { g } = memberGroup(groupId)
      if (!["day", "month", "year"].includes(period)) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：period")
      const { date, start, clipped } = leaderboardDates(period)
      const rows: LeaderboardEntry[] = g.members
        .filter((m) => m.share.returns)
        .map((m) => {
          const r = sourceFor(m.ref.user_id)?.returns()
          return { ...refOf(m), return_pct: r4(r?.[period] ?? null), total_return_pct: r4(r?.total ?? null), is_me: m.ref.user_id === meId() }
        })
      let entries = rows
      if (g.ranking_enabled) {
        entries = [...rows].sort((a, b) => (a.return_pct === null ? 1 : b.return_pct === null ? -1 : b.return_pct - a.return_pct))
        entries = entries.map((e, i) => {
          if (e.return_pct === null) return e
          // 四捨五入到 4 位後相同就並列（1、1、3）
          const rank = entries.findIndex((x) => x.return_pct === e.return_pct) + 1
          return { ...e, rank: rank > 0 ? rank : i + 1 }
        })
      }
      const benchmarks = [
        { symbol: "^TAIEXTR", name: "發行量加權股價報酬指數", return_pct: benchmarkReturn("^TAIEXTR", start, date) },
        { symbol: "0050.TW", name: "元大台灣50", return_pct: benchmarkReturn("0050.TW", start, date) },
      ]
      const notes: string[] = []
      if (clipped) notes.push(`資料累積中：自 ${ARCHIVE_START} 起存檔，今年從 ${ARCHIVE_START} 收盤起算`)
      if (benchmarks[0]!.return_pct === null) notes.push(`發行量加權股價報酬指數自 ${INDEX_ARCHIVE_START} 起存檔，期間起點更早時暫時無法比較`)
      return {
        period, date, start_date: start, as_of: "2026-11-12T13:30:00+08:00", ranked: g.ranking_enabled, entries, benchmarks, notes,
        sources: [sourceOf("twse-openapi/price"), sourceOf("tpex-openapi/price")], is_demo: !deps.commercial,
      }
    },
    getGroupHoldings(groupId: string): GroupHoldings {
      const { g } = memberGroup(groupId)
      const shared = g.members.filter((m) => m.share.holdings).map((m) => ({ ...refOf(m), holdings: holdingsOf(m.ref.user_id) }))
      const { common, industries } = overlap(shared.map((m) => ({ symbols: m.holdings.map((x) => x.symbol) })))
      return { members: shared, common, industries, is_demo: !deps.commercial }
    },
    getSharedPortfolio(groupId: string, userId: string): SharedPortfolio {
      const { g } = memberGroup(groupId)
      const m = findMember(g, userId)
      if (!m) throw new ApiError(404, "not_found", "找不到這位成員")
      const src = sourceFor(userId)
      const out: SharedPortfolio = { ...refOf(m), is_demo: !deps.commercial }
      if (src && m.share.returns) {
        const r = src.returns()
        out.returns = { day: r4(r.day), month: r4(r.month), year: r4(r.year), total: r4(r.total) }
      }
      if (src && m.share.holdings) out.holdings = holdingsOf(userId)
      if (src && m.share.amounts) {
        const a = src.amounts()
        out.amounts = { market_value: r2(a.market_value), day_change: r2(a.day_change), total_pnl: r2(a.total_pnl) }
      }
      return out
    },

    // ── 動態、留言、表情 ──
    getFeed(groupId: string, query: { limit?: number; cursor?: string | null; user_id?: string } = {}): Paged<FeedItem> {
      const { g } = memberGroup(groupId)
      const limit = query.limit ?? 30
      if (limit < 1 || limit > 100) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：limit")
      const rows = visibleFeed(g)
        .filter((i) => !query.user_id || i.user_id === query.user_id)
        .map((i) => ({ ...i, comment_count: commentCount(g, `trade:${i.id}`), reactions: i.type === "trade" ? reactionsOf(g, `trade:${i.id}`) : [] }))
      return paginate(rows, limit, query.cursor)
    },
    listComments(groupId: string, target: string, query: { limit?: number; cursor?: string | null } = {}): Paged<Comment> {
      const { g, me } = memberGroup(groupId)
      if (!targetVisible(g, target)) throw new ApiError(404, "not_found", "找不到這個對象")
      const names = peopleIndex()
      const rows = g.comments
        .filter((c) => c.target === target)
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
        .map((c): Comment => {
          const current = findMember(g, c.user_id)
          const ref = c.user_id === meId() ? meRef() : names.get(c.user_id)
          return current
            ? { id: c.id, target: c.target, user_id: c.user_id, display_name: ref?.display_name ?? current.ref.display_name, body: c.body, created_at: c.created_at, can_delete: c.user_id === meId() || roleRank[me.role] <= roleRank.admin }
            : { id: c.id, target: c.target, user_id: null, display_name: "已離開的成員", body: c.body, created_at: c.created_at, can_delete: roleRank[me.role] <= roleRank.admin }
        })
      return paginate(rows, query.limit ?? 50, query.cursor)
    },
    createComment(groupId: string, body: { target: string; body: string }): Comment {
      const { g } = memberGroup(groupId)
      const text = (body.body ?? "").trim()
      if (text.length < 1 || text.length > 500) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：body")
      if (!targetVisible(g, body.target)) throw new ApiError(404, "not_found", "找不到這個對象")
      const c: MockComment = { id: id("gcm"), target: body.target, user_id: meId(), body: text, created_at: now() }
      g.comments.push(c)
      return { id: c.id, target: c.target, user_id: c.user_id, display_name: deps.me().display_name, body: c.body, created_at: c.created_at, can_delete: true }
    },
    deleteComment(groupId: string, commentId: string): void {
      const { g, me } = memberGroup(groupId)
      const c = g.comments.find((x) => x.id === commentId)
      if (!c || !targetVisible(g, c.target)) throw new ApiError(404, "not_found", "找不到這則留言")
      if (c.user_id !== meId() && roleRank[me.role] > roleRank.admin) throw forbidden()
      g.comments = g.comments.filter((x) => x !== c)
    },
    addReaction(groupId: string, body: { target: string; emoji: ReactionEmoji }): void {
      const { g } = memberGroup(groupId)
      if (!REACTION_EMOJIS.includes(body.emoji)) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：emoji")
      if (!targetVisible(g, body.target)) throw new ApiError(404, "not_found", "找不到這個對象")
      const map = g.reactions.get(body.target) ?? new Map<ReactionEmoji, Set<string>>()
      map.set(body.emoji, new Set([...(map.get(body.emoji) ?? []), meId()]))
      g.reactions.set(body.target, map)
    },
    removeReaction(groupId: string, target: string, emoji: ReactionEmoji): void {
      const { g } = memberGroup(groupId)
      if (!REACTION_EMOJIS.includes(emoji)) throw new ApiError(422, "validation_error", "輸入資料格式錯誤：emoji")
      if (!targetVisible(g, target)) throw new ApiError(404, "not_found", "找不到這個對象")
      g.reactions.get(target)?.get(emoji)?.delete(meId())
    },

    // ── 週報 ──
    listDigests(groupId: string, query: { limit?: number; cursor?: string | null } = {}): Paged<Digest> {
      const { g } = memberGroup(groupId)
      const rows = [...g.digests]
        .sort((a, b) => b.week_start.localeCompare(a.week_start))
        .map((d): Digest => {
          // facts 讀取時依「目前」的成員身分與開關過濾
          const start = prevTradingDay(d.week_start)
          const withReturns = g.members.filter((m) => m.share.returns)
          const withHoldings = g.members.filter((m) => m.share.holdings)
          const { common, industries } = overlap(withHoldings.map((m) => ({ symbols: holdingsOf(m.ref.user_id).map((x) => x.symbol) })))
          const trades = g.members
            .filter((m) => m.share.trades)
            .reduce((n, m) => n + (sourceFor(m.ref.user_id)?.trades() ?? []).filter((t) => t.trade_date >= d.week_start && t.trade_date <= d.week_end).length, 0)
          return {
            id: d.id, status: d.status, week_start: d.week_start, week_end: d.week_end, created_at: d.created_at, summary: d.summary,
            facts:
              d.status === "ready"
                ? {
                    returns: withReturns.map((m) => ({ user_id: m.ref.user_id, display_name: refOf(m).display_name, week_return_pct: r4(sourceFor(m.ref.user_id)?.week(d.week_start) ?? null) })),
                    benchmarks: [
                      { symbol: "^TAIEXTR", name: "發行量加權股價報酬指數", week_return_pct: benchmarkReturn("^TAIEXTR", start, d.week_end) },
                      { symbol: "0050.TW", name: "元大台灣50", week_return_pct: benchmarkReturn("0050.TW", start, d.week_end) },
                    ],
                    common_holdings: common,
                    industries,
                    trades_count: trades,
                  }
                : null,
            disclaimer: DISCLAIMER,
            sources: [sourceOf("twse-openapi/price")],
            comment_count: commentCount(g, `digest:${d.id}`),
            reactions: reactionsOf(g, `digest:${d.id}`),
          }
        })
      return paginate(rows, query.limit ?? 8, query.cursor)
    },

    // ── 頻道 ──
    getChannels(groupId: string): Channels {
      const { g, me } = memberGroup(groupId)
      // 示範：產生連結碼約 6 秒後，當作 owner 已在 Telegram 群組傳了 /link
      if (g.telegramLink && Date.now() >= g.telegramLink.linkAt) {
        g.telegram = { chat_title: `${g.name}群`, status: "active", disabled_reason: null, notify_trades: true, notify_digest: true }
        g.telegramLink = null
      }
      const owner = me.role === "owner"
      return {
        discord: g.discord
          ? { configured: true, status: g.discord.status, disabled_reason: g.discord.disabled_reason, ...(owner ? { webhook_hint: g.discord.hint } : {}), notify_trades: g.discord.notify_trades, notify_digest: g.discord.notify_digest }
          : { configured: false, status: null, disabled_reason: null, ...(owner ? { webhook_hint: null } : {}), notify_trades: true, notify_digest: true },
        telegram: g.telegram
          ? { configured: true, status: g.telegram.status, disabled_reason: g.telegram.disabled_reason, chat_title: g.telegram.chat_title, notify_trades: g.telegram.notify_trades, notify_digest: g.telegram.notify_digest }
          : { configured: false, status: null, disabled_reason: null, chat_title: null, notify_trades: true, notify_digest: true },
        telegram_available: true,
      }
    },
    putDiscord(groupId: string, body: { webhook_url: string; notify_trades: boolean; notify_digest: boolean }): void {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      let url: URL
      try {
        url = new URL(body.webhook_url)
      } catch {
        throw new ApiError(422, "validation_error", "輸入資料格式錯誤：webhook_url")
      }
      const m = /^\/api\/webhooks\/(\d+)\/([\w-]+)$/.exec(url.pathname)
      if (url.protocol !== "https:" || !["discord.com", "discordapp.com"].includes(url.hostname) || url.port || url.username || url.password || !m) {
        throw new ApiError(422, "validation_error", "輸入資料格式錯誤：webhook_url")
      }
      // 示範：token 含 fail 時當作測試訊息送不出去
      if (m[2]!.includes("fail")) throw new ApiError(422, "webhook_failed", "測試訊息送不出去，請確認 webhook 網址還有效")
      g.discord = { hint: `…/${m[2]!.slice(-4)}`, status: "active", disabled_reason: null, notify_trades: !!body.notify_trades, notify_digest: !!body.notify_digest }
    },
    patchDiscord(groupId: string, patch: { notify_trades?: boolean; notify_digest?: boolean }): void {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      if (!g.discord) throw new ApiError(404, "not_found", "還沒有設定 Discord 頻道")
      Object.assign(g.discord, patch)
    },
    deleteDiscord(groupId: string): void {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      g.discord = null
    },
    linkTelegram(groupId: string): TelegramLinkCode {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      const code = String(100000 + ((clock / 60_000) % 900000)).slice(0, 6)
      const expires_at = isoTaipei(clock + 10 * 60_000)
      g.telegramLink = { code, expires_at, linkAt: Date.now() + 6000 }
      return { code, bot_username: "forliosa_bot", expires_at }
    },
    patchTelegram(groupId: string, patch: { notify_trades?: boolean; notify_digest?: boolean }): void {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      if (!g.telegram) throw new ApiError(404, "not_found", "還沒有連結 Telegram 群組")
      Object.assign(g.telegram, patch)
    },
    deleteTelegram(groupId: string): void {
      const { g, me } = memberGroup(groupId)
      atLeast(me, "owner")
      g.telegram = null
      g.telegramLink = null
    },
  }
}

export type SharingStore = ReturnType<typeof createSharingStore>
