import type { Query, QueryClient, QueryKey } from "@tanstack/react-query"

/**
 * 即時更新的事件 → 要重新讀的查詢（docs/api-contract.md「即時更新（2026-11-17）」）。
 * 伺服器只說「什麼變了」（種類＋幾個 id），不給資料：這裡把它對到快取的 key，交給 TanStack Query 重新讀，
 * 權限與投影（分享設定、查看範圍、隱藏的討論）照舊由那些端點把關。
 *
 * 規則和「自己在這個分頁改了」用同一組 key（`api/queries.ts`、`api/sharing-queries.ts`、`api/discussion-queries.ts`
 * 的 mutation）：別人改的、自己在另一台裝置改的，和自己在這裡改的，重新讀的東西一樣。
 */

export type RealtimeTopic =
  | "ledger"
  | "ledger.viewas"
  | "recurring"
  | "watchlist"
  | "me"
  | "delegations"
  | "groups.list"
  | "group.meta"
  | "group.members"
  | "group.ledger"
  | "group.comments"
  | "group.reports"
  | "group.channels"
  | "group.invites"
  | "group.deleted"
  | "discussions.topic"
  | "discussions.list"
  | "ai.usage"
  | "ai.briefings"
  | "ai.threads"
  | "reports.seen"
  | "market.closes"
  | "market.overview"
  | "market.reports"
  | "admin.reports"
  | "admin.discussions"

/** 每個登入的人都會收到的種類（行情、公開討論）：先隨機等 0–1.5 秒再重新讀，大家不要同一秒一起問 */
export const BROADCAST_TOPICS: ReadonlySet<string> = new Set(["market.closes", "market.overview", "market.reports"])

/**
 * 一個動作：
 * - `invalidate`：這些查詢過期（畫面上有的重新讀）；`exact` 只對完全相同的 key，`match` 再篩一次
 * - `drop`：這些查詢沒有畫面在用的就丟掉（群組刪了）
 */
export type Action =
  | { kind: "invalidate"; key: QueryKey; exact?: boolean; match?: (key: QueryKey) => boolean; id: string }
  | { kind: "drop"; key: QueryKey; id: string }

const inv = (key: QueryKey, opts: { exact?: boolean; match?: (key: QueryKey) => boolean; tag?: string } = {}): Action => ({
  kind: "invalidate",
  key,
  ...(opts.exact ? { exact: true } : {}),
  ...(opts.match ? { match: opts.match } : {}),
  id: `i:${JSON.stringify(key)}${opts.exact ? ":exact" : ""}${opts.tag ? `:${opts.tag}` : ""}`,
})
const drop = (key: QueryKey): Action => ({ kind: "drop", key, id: `d:${JSON.stringify(key)}` })

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null)

/** 帳本：持股、總資產、績效、紀錄、個股事件、帳戶、減碼視窗的持股（和 `useInvalidatePortfolio` 一樣，再加帳戶與減碼） */
export function ledgerActions(): Action[] {
  return [inv(["portfolio"]), inv(["transactions"]), inv(["events"]), inv(["accounts"]), inv(["holdings"])]
}

/** 收盤價進來時重新讀的查詢（和 `hooks/use-close.ts` 的 CLOSE_QUERIES 一樣，再加上報價、群組裡用到價格的） */
const CLOSE_ROOTS = ["portfolio", "quote", "quotes", "watchlist", "market", "history", "valuation", "overview", "why", "daily-close", "holdings"]
const GROUP_PRICED = new Set(["leaderboard", "holdings", "shared"])

/** 群組的留言與表情：留言串、動態與週報的計數；排行當天那一串的計數（和 `useInvalidateDiscussion` 一樣） */
function commentActions(g: string, target: string | null): Action[] {
  const out: Action[] = [target ? inv(["groups", g, "comments", target]) : inv(["groups", g, "comments"]), inv(["groups", g, "feed"]), inv(["groups", g, "digests"])]
  if (!target || target.startsWith("leaderboard:")) out.push(inv(["groups", g, "leaderboard"]))
  return out
}

/** 討論清單：`["discussions","topics", scope, groupId, symbol, sort]`；「全部」（公開＋我的群組）兩種都要 */
function discussionListMatch(scope: string | null, groupId: string | null): (key: QueryKey) => boolean {
  return (key) => {
    const s = key[2]
    if (s === "all") return true
    if (scope === "group") return s === "group" && (!groupId || key[3] === groupId)
    if (scope === "public") return s === "public"
    return true
  }
}

export interface TopicContext {
  /** 正在查看的授權 id（沒有在查看時 null） */
  viewAs: string | null
}

/**
 * 一個事件要做的事。不認得的種類回空陣列（新版後端多了種類時舊頁面不做事，不是全部重抓）。
 * `data` 已經拿掉 `o`（分頁 id）。
 */
export function actionsFor(topic: string, data: Record<string, unknown>, ctx: TopicContext): Action[] {
  const g = str(data.group_id)
  switch (topic) {
    case "ledger":
      // 查看別人的資產時，畫面上是那個人的帳本：自己的帳本變了不用重新讀（回到自己的帳本時快取已經清掉）
      return ctx.viewAs ? [] : ledgerActions()
    case "ledger.viewas":
      // 查看橫幅上的帳戶名稱也跟著（`useSyncViewAsTarget` 讀的授權清單）
      return ctx.viewAs && ctx.viewAs === str(data.delegation_id) ? [...ledgerActions(), inv(["delegations"], { exact: true })] : []
    case "recurring":
      return [inv(["recurring"]), inv(["portfolio", "upcoming"]), inv(["transactions", "recurring-offers"])]
    case "watchlist":
      return [inv(["watchlist"])]
    case "me":
      // 方案（會員）變了：AI 用量的上限跟著變
      return [inv(["me"], { exact: true }), inv(["me", "group-passes"]), inv(["ai", "usage"])]
    case "delegations":
      return [inv(["delegations"]), ...(ctx.viewAs ? ledgerActions() : [])]
    case "groups.list":
      return [inv(["groups"], { exact: true }), inv(["delegations", "candidates"])]
    case "group.meta":
      return g ? [inv(["groups", g], { exact: true }), inv(["groups"], { exact: true }), inv(["groups", g, "leaderboard"])] : [inv(["groups"])]
    case "group.members":
      // 成員加入、離開、被移除、改名：群組的每一頁、這個群組的討論（清單、「全部」清單、開著的主題：離開的人不能再看）、
      // 授權的候選人與查看橫幅（顯示名稱）
      return g
        ? [
            inv(["groups", g]),
            inv(["groups"], { exact: true }),
            inv(["discussions", "topics"], { match: discussionListMatch("group", g), tag: `group:${g}` }),
            inv(["discussions", "topic"]),
            inv(["delegations", "candidates"]),
            inv(["delegations"], { exact: true }),
          ]
        : [inv(["groups"])]
    case "group.ledger":
      return g
        ? [inv(["groups", g, "feed"]), inv(["groups", g, "leaderboard"]), inv(["groups", g, "holdings"]), inv(["groups", g, "shared"]), inv(["groups"], { exact: true })]
        : []
    case "group.comments":
      return g ? commentActions(g, str(data.target)) : []
    case "group.reports":
      return g ? [inv(["groups", g, "digests"]), inv(["groups", g, "daily"]), inv(["groups"], { exact: true })] : []
    case "group.channels":
      return g ? [inv(["groups", g, "channels"]), inv(["groups", g], { exact: true })] : []
    case "group.invites":
      return g ? [inv(["groups", g, "invites"])] : []
    case "group.deleted":
      // 畫面上還開著這個群組的：重新讀（找不到，頁面自己顯示）；沒有在用的丟掉。群組的討論也一起刪了（清單、開著的主題）
      return g
        ? [drop(["groups", g]), inv(["groups", g]), inv(["groups"], { exact: true }), inv(["delegations"]), inv(["discussions", "topics"]), inv(["discussions", "topic"])]
        : [inv(["groups"]), inv(["discussions", "topics"]), inv(["discussions", "topic"])]
    case "discussions.topic": {
      const t = str(data.topic_id)
      return t ? [inv(["discussions", "topic", t])] : []
    }
    case "discussions.list": {
      const scope = str(data.scope)
      return [inv(["discussions", "topics"], { match: discussionListMatch(scope, g), tag: `${scope ?? "*"}:${g ?? ""}` })]
    }
    case "ai.usage":
      return [inv(["ai", "usage"])]
    case "ai.briefings":
      return [inv(["ai", "briefings"])]
    case "ai.threads":
      return [inv(["ai", "threads"])]
    case "reports.seen":
      return [inv(["market", "reports", "status"])]
    case "market.closes":
      return [
        ...CLOSE_ROOTS.map((r) => inv([r])),
        inv(["meta", "market-status"]),
        inv(["groups"], { match: (key) => GROUP_PRICED.has(String(key[2])), tag: "priced" }),
      ]
    case "market.overview":
      return [inv(["market", "overview"])]
    case "market.reports":
      // 管理後台的報告頁（只有管理員有這些查詢；其他人這一條什麼也不做）
      return [inv(["market", "reports"]), inv(["admin", "market-reports"])]
    case "admin.reports":
      return [inv(["admin", "market-reports"])]
    case "admin.discussions":
      return [inv(["discussions", "admin"]), inv(["admin", "overview"])]
    default:
      return []
  }
}

/**
 * 會因為別人或排程而變的資料（「活的」）：重新連線後可能漏了事件（`resync`）時，這些重新讀。
 * 不在這裡的（商品資料、財報、估值、新聞、搜尋…）有自己的過期時間，不必跟著重抓。
 */
const LIVE_ROOTS = new Set([
  "portfolio", "transactions", "holdings", "accounts", "recurring", "watchlist", "events",
  "quote", "quotes", "daily-close", "overview", "why", "market", "groups", "discussions", "delegations", "me", "admin",
])
const LIVE_AI = new Set(["usage", "briefings", "threads"])

export function isLiveKey(key: QueryKey): boolean {
  const root = String(key[0])
  if (LIVE_ROOTS.has(root)) return true
  if (root === "ai") return LIVE_AI.has(String(key[1]))
  if (root === "meta") return key[1] === "market-status"
  return false
}

/** 可能漏了事件：所有「活的」查詢過期（畫面上有的重新讀） */
export function resyncActions(): Action[] {
  return [{ kind: "invalidate", key: [], match: isLiveKey, id: "i:resync" }]
}

/**
 * 串流斷著時每 30 秒重新讀的：沒有自己定時重新讀的那些（群組、討論、帳本、帳戶、定期定額、AI、授權、市場報告）。
 * 報價、觀察清單、市場頁、市場狀態本來就有自己的間隔（串流斷著時照舊）。
 */
const FALLBACK_ROOTS = new Set(["groups", "discussions", "portfolio", "transactions", "accounts", "recurring", "delegations", "me"])
export function isFallbackKey(key: QueryKey): boolean {
  const root = String(key[0])
  if (FALLBACK_ROOTS.has(root)) return true
  if (root === "ai") return LIVE_AI.has(String(key[1]))
  if (root === "market") return key[1] === "reports"
  return false
}
export function fallbackActions(): Action[] {
  return [{ kind: "invalidate", key: [], match: isFallbackKey, id: "i:fallback" }]
}

/**
 * 套用動作。`refetch`：
 * - `active`：畫面上有的馬上重新讀（分頁在前景）
 * - `none`：只標成過期（分頁在背景：回到前景時再一起讀，見 controller）
 *
 * 同一批裡好幾個動作對到同一個查詢（例如 `ledger`＋`recurring` 都對到本週事項、`resync`＋任何事件）時，那個查詢只重新讀一次：
 * 先找出所有對到的查詢，再一次 `invalidateQueries`。逐一呼叫的話，第二次會取消第一次已經送出的請求再送一次，
 * 伺服器照樣把第一次做完（2026-11-17 和 API 速度工作合併時發現：一批事件會變成兩倍的請求、佔兩倍的連線）。
 */
export function applyActions(qc: QueryClient, actions: readonly Action[], refetch: "active" | "none"): Promise<unknown> {
  const cache = qc.getQueryCache()
  for (const a of actions) if (a.kind === "drop") qc.removeQueries({ queryKey: a.key, type: "inactive" })
  const matched = new Set<Query>()
  for (const a of actions) {
    if (a.kind !== "invalidate") continue
    const match = a.match
    for (const q of cache.findAll({ queryKey: a.key, ...(a.exact ? { exact: true } : {}), ...(match ? { predicate: (q: Query) => match(q.queryKey) } : {}) })) matched.add(q)
  }
  if (matched.size === 0) return Promise.resolve()
  return qc
    .invalidateQueries(
      { predicate: (q: Query) => matched.has(q), refetchType: refetch },
      // 正在讀的那一次可能是變更之前送出的：取消重讀（預設）。失敗的重新讀不往外丟（查詢自己記錯誤，401 由 QueryCache 處理）
      { throwOnError: false },
    )
    .catch(() => undefined)
}
