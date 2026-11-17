import { QueryClient, QueryObserver, type QueryKey } from "@tanstack/react-query"
import { actionsFor, applyActions, BROADCAST_TOPICS, fallbackActions, isLiveKey, resyncActions, type TopicContext } from "@/realtime/topics"

/** 代表性的快取 key（和 api/queries.ts、sharing-queries.ts、discussion-queries.ts、ai/remote-hooks.ts 用的形狀一樣） */
const KEYS: QueryKey[] = [
  ["portfolio", "summary", "all"],
  ["portfolio", "upcoming", 7],
  ["transactions", "list", {}],
  ["events", "2330.TW"],
  ["accounts"],
  ["holdings", "reduce", "acc_1", "2330.TW"],
  ["recurring"],
  ["watchlist"],
  ["me"],
  ["me", "group-passes"],
  ["ai", "usage"],
  ["ai", "briefings", "latest"],
  ["ai", "threads"],
  ["ai", "suggestions", "/", null],
  ["delegations"],
  ["delegations", "candidates"],
  ["groups"],
  ["groups", "g1"],
  ["groups", "g1", "feed", "all"],
  ["groups", "g1", "leaderboard", "1M"],
  ["groups", "g1", "holdings"],
  ["groups", "g1", "shared", "u2"],
  ["groups", "g1", "comments", "feed:x"],
  ["groups", "g1", "comments", "leaderboard:2026-11-17"],
  ["groups", "g1", "digests"],
  ["groups", "g1", "daily"],
  ["groups", "g1", "channels"],
  ["groups", "g1", "invites"],
  ["groups", "g1", "share"],
  ["groups", "g2"],
  ["groups", "g2", "feed", "all"],
  ["groups", "g2", "leaderboard", "1M"],
  ["discussions", "topics", "public", "", "", "active"],
  ["discussions", "topics", "all", "", "", "active"],
  ["discussions", "topics", "group", "g1", "", "active"],
  ["discussions", "topics", "group", "g2", "", "active"],
  ["discussions", "topic", "tp1"],
  ["discussions", "topic", "tp1", "replies"],
  ["discussions", "topic", "tp2"],
  ["discussions", "admin", "reports", "open"],
  ["quote", "2330.TW"],
  ["quotes", "2330.TW"],
  ["daily-close", "2330.TW", "2026-11-17"],
  ["market", "overview"],
  ["market", "reports", "status"],
  ["market", "reports", "latest", "close"],
  ["meta", "market-status"],
  ["meta", "attributions"],
  ["history", "2330.TW", "1Y"],
  ["valuation", "2330.TW"],
  ["overview", "2330.TW"],
  ["why", "2330.TW"],
  ["instrument", "2330.TW"],
  ["news", "2330.TW"],
  ["admin", "market-reports", "overview"],
  ["admin", "overview"],
]

const LEDGER: QueryKey[] = [
  ["portfolio", "summary", "all"],
  ["portfolio", "upcoming", 7],
  ["transactions", "list", {}],
  ["events", "2330.TW"],
  ["accounts"],
  ["holdings", "reduce", "acc_1", "2330.TW"],
]
const G1_ALL = KEYS.filter((k) => k[0] === "groups" && k[1] === "g1")

const seeded = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  for (const k of KEYS) qc.setQueryData(k, { seeded: true })
  return qc
}
const invalidated = (qc: QueryClient) =>
  KEYS.filter((k) => qc.getQueryCache().find({ queryKey: k, exact: true })?.state.isInvalidated).map((k) => JSON.stringify(k)).sort()
const keys = (list: QueryKey[]) => list.map((k) => JSON.stringify(k)).sort()

async function run(topic: string, data: Record<string, unknown>, ctx: TopicContext = { viewAs: null }) {
  const qc = seeded()
  await applyActions(qc, actionsFor(topic, data, ctx), "none")
  return invalidated(qc)
}

describe("actionsFor: which cached queries each topic invalidates", () => {
  const cases: [string, string, Record<string, unknown>, TopicContext, QueryKey[]][] = [
    ["own ledger", "ledger", { account_id: "acc_1" }, { viewAs: null }, LEDGER],
    ["own ledger while viewing someone: nothing", "ledger", { account_id: "acc_1" }, { viewAs: "dlg_1" }, []],
    // 查看橫幅上的帳戶名稱也跟著（授權清單）
    ["viewed ledger, the delegation being viewed", "ledger.viewas", { delegation_id: "dlg_1" }, { viewAs: "dlg_1" }, [...LEDGER, ["delegations"]]],
    ["viewed ledger, another delegation", "ledger.viewas", { delegation_id: "dlg_2" }, { viewAs: "dlg_1" }, []],
    ["viewed ledger, not viewing", "ledger.viewas", { delegation_id: "dlg_1" }, { viewAs: null }, []],
    ["recurring", "recurring", {}, { viewAs: null }, [["recurring"], ["portfolio", "upcoming", 7]]],
    ["watchlist", "watchlist", {}, { viewAs: null }, [["watchlist"]]],
    ["me", "me", {}, { viewAs: null }, [["me"], ["me", "group-passes"], ["ai", "usage"]]],
    ["delegations", "delegations", {}, { viewAs: null }, [["delegations"], ["delegations", "candidates"]]],
    ["delegations while viewing", "delegations", {}, { viewAs: "dlg_1" }, [["delegations"], ["delegations", "candidates"], ...LEDGER]],
    ["groups.list", "groups.list", {}, { viewAs: null }, [["groups"], ["delegations", "candidates"]]],
    ["group.meta", "group.meta", { group_id: "g1" }, { viewAs: null }, [["groups", "g1"], ["groups"], ["groups", "g1", "leaderboard", "1M"]]],
    [
      // 離開、被移除的人：這個群組的討論（清單、「全部」清單、開著的主題）不能再看；改名：查看橫幅的名稱（授權清單）
      "group.members: the whole group, the list, the group's discussions, the delegations",
      "group.members",
      { group_id: "g1" },
      { viewAs: null },
      [
        ...G1_ALL,
        ["groups"],
        ["discussions", "topics", "group", "g1", "", "active"],
        ["discussions", "topics", "all", "", "", "active"],
        ["discussions", "topic", "tp1"],
        ["discussions", "topic", "tp1", "replies"],
        ["discussions", "topic", "tp2"],
        ["delegations", "candidates"],
        ["delegations"],
      ],
    ],
    [
      "group.ledger",
      "group.ledger",
      { group_id: "g1" },
      { viewAs: null },
      [["groups", "g1", "feed", "all"], ["groups", "g1", "leaderboard", "1M"], ["groups", "g1", "holdings"], ["groups", "g1", "shared", "u2"], ["groups"]],
    ],
    [
      "group.comments on a feed item",
      "group.comments",
      { group_id: "g1", target: "feed:x" },
      { viewAs: null },
      [["groups", "g1", "comments", "feed:x"], ["groups", "g1", "feed", "all"], ["groups", "g1", "digests"]],
    ],
    [
      "group.comments on the day's leaderboard thread",
      "group.comments",
      { group_id: "g1", target: "leaderboard:2026-11-17" },
      { viewAs: null },
      [["groups", "g1", "comments", "leaderboard:2026-11-17"], ["groups", "g1", "feed", "all"], ["groups", "g1", "digests"], ["groups", "g1", "leaderboard", "1M"]],
    ],
    ["group.reports", "group.reports", { group_id: "g1" }, { viewAs: null }, [["groups", "g1", "digests"], ["groups", "g1", "daily"], ["groups"]]],
    ["group.channels", "group.channels", { group_id: "g1" }, { viewAs: null }, [["groups", "g1", "channels"], ["groups", "g1"]]],
    ["group.invites", "group.invites", { group_id: "g1" }, { viewAs: null }, [["groups", "g1", "invites"]]],
    ["discussions.topic", "discussions.topic", { topic_id: "tp1" }, { viewAs: null }, [["discussions", "topic", "tp1"], ["discussions", "topic", "tp1", "replies"]]],
    [
      "discussions.list public",
      "discussions.list",
      { scope: "public" },
      { viewAs: null },
      [["discussions", "topics", "public", "", "", "active"], ["discussions", "topics", "all", "", "", "active"]],
    ],
    [
      "discussions.list of a group",
      "discussions.list",
      { scope: "group", group_id: "g1" },
      { viewAs: null },
      [["discussions", "topics", "group", "g1", "", "active"], ["discussions", "topics", "all", "", "", "active"]],
    ],
    ["ai.usage", "ai.usage", {}, { viewAs: null }, [["ai", "usage"]]],
    ["ai.briefings", "ai.briefings", {}, { viewAs: null }, [["ai", "briefings", "latest"]]],
    ["ai.threads", "ai.threads", {}, { viewAs: null }, [["ai", "threads"]]],
    ["reports.seen", "reports.seen", {}, { viewAs: null }, [["market", "reports", "status"]]],
    [
      "market.closes: prices everywhere, not the static data",
      "market.closes",
      { market: "TWSE", date: "2026-11-17" },
      { viewAs: null },
      [
        ["portfolio", "summary", "all"],
        ["portfolio", "upcoming", 7],
        ["holdings", "reduce", "acc_1", "2330.TW"],
        ["watchlist"],
        ["quote", "2330.TW"],
        ["quotes", "2330.TW"],
        ["daily-close", "2330.TW", "2026-11-17"],
        ["market", "overview"],
        ["market", "reports", "status"],
        ["market", "reports", "latest", "close"],
        ["meta", "market-status"],
        ["history", "2330.TW", "1Y"],
        ["valuation", "2330.TW"],
        ["overview", "2330.TW"],
        ["why", "2330.TW"],
        ["groups", "g1", "leaderboard", "1M"],
        ["groups", "g1", "holdings"],
        ["groups", "g1", "shared", "u2"],
        ["groups", "g2", "leaderboard", "1M"],
      ],
    ],
    ["market.overview", "market.overview", {}, { viewAs: null }, [["market", "overview"]]],
    [
      "market.reports",
      "market.reports",
      { report_id: "rpt_1", kind: "close" },
      { viewAs: null },
      [["market", "reports", "status"], ["market", "reports", "latest", "close"], ["admin", "market-reports", "overview"]],
    ],
    ["admin.reports", "admin.reports", {}, { viewAs: null }, [["admin", "market-reports", "overview"]]],
    ["admin.discussions", "admin.discussions", {}, { viewAs: null }, [["discussions", "admin", "reports", "open"], ["admin", "overview"]]],
    ["an unknown topic does nothing", "something.new", { group_id: "g1" }, { viewAs: null }, []],
    ["a group topic without its id does nothing", "group.ledger", {}, { viewAs: null }, []],
  ]

  it.each(cases)("%s", async (_name, topic, data, ctx, expected) => {
    expect(await run(topic, data, ctx)).toEqual(keys(expected))
  })

  it("group.deleted refetches what is on screen and drops the rest of that group (and its discussions)", async () => {
    const qc = seeded()
    const observer = new QueryObserver(qc, { queryKey: ["groups", "g1"], queryFn: () => Promise.reject(new Error("gone")), retry: false })
    const unsubscribe = observer.subscribe(() => {})
    await applyActions(qc, actionsFor("group.deleted", { group_id: "g1" }, { viewAs: null }), "none")
    expect(qc.getQueryCache().find({ queryKey: ["groups", "g1", "feed", "all"], exact: true })).toBeUndefined()
    expect(qc.getQueryCache().find({ queryKey: ["groups", "g1"], exact: true })?.state.isInvalidated).toBe(true)
    // 群組的討論也一起刪了：討論清單（含「全部」）與開著的主題重新讀；站方的檢舉清單只有公開討論，不動
    const discussions = KEYS.filter((k) => k[0] === "discussions" && k[1] !== "admin")
    expect(invalidated(qc)).toEqual(keys([["groups", "g1"], ["groups"], ["delegations"], ["delegations", "candidates"], ...discussions]))
    expect(qc.getQueryCache().find({ queryKey: ["groups", "g2"], exact: true })).toBeDefined()
    unsubscribe()
  })

  it("only market data and public lists are spread out in time", () => {
    expect([...BROADCAST_TOPICS].sort()).toEqual(["market.closes", "market.overview", "market.reports"])
  })
})

describe("resync and fallback", () => {
  it("resync invalidates every live root and leaves static data alone", async () => {
    const qc = seeded()
    await applyActions(qc, resyncActions(), "none")
    const stale = invalidated(qc)
    // 走勢圖與估值：收盤價進來時才變（`market.closes`），重新連線時不必跟著重抓
    const untouched = keys([["ai", "suggestions", "/", null], ["meta", "attributions"], ["instrument", "2330.TW"], ["news", "2330.TW"], ["history", "2330.TW", "1Y"], ["valuation", "2330.TW"]])
    expect(stale).toEqual(keys(KEYS).filter((k) => !untouched.includes(k)))
  })

  it("the fallback poll covers what has no polling of its own", async () => {
    const qc = seeded()
    await applyActions(qc, fallbackActions(), "none")
    const stale = invalidated(qc)
    for (const k of [["groups", "g1", "feed", "all"], ["discussions", "topic", "tp1"], ["portfolio", "summary", "all"], ["ai", "usage"], ["market", "reports", "status"], ["recurring"], ["me"]])
      expect(stale).toContain(JSON.stringify(k))
    // these already poll on their own interval while the stream is down
    for (const k of [["quote", "2330.TW"], ["watchlist"], ["market", "overview"], ["meta", "market-status"], ["instrument", "2330.TW"]])
      expect(stale).not.toContain(JSON.stringify(k))
  })

  it("isLiveKey", () => {
    expect(isLiveKey(["ai", "thread", "x"])).toBe(false)
    expect(isLiveKey(["ai", "briefings", "list"])).toBe(true)
    expect(isLiveKey(["meta", "market-status"])).toBe(true)
    expect(isLiveKey(["chips", "2330.TW", "3M"])).toBe(false)
  })

  it("refetches active queries right away, but only marks them stale in a background tab", async () => {
    const qc = seeded()
    const fn = vi.fn(() => Promise.resolve({ fresh: true }))
    const observer = new QueryObserver(qc, { queryKey: ["groups", "g1"], queryFn: fn, staleTime: Infinity })
    const unsubscribe = observer.subscribe(() => {})
    await applyActions(qc, actionsFor("group.meta", { group_id: "g1" }, { viewAs: null }), "none")
    expect(fn).not.toHaveBeenCalled()
    await applyActions(qc, actionsFor("group.meta", { group_id: "g1" }, { viewAs: null }), "active")
    expect(fn).toHaveBeenCalledTimes(1)
    expect(qc.getQueryData(["groups", "g1"])).toEqual({ fresh: true })
    unsubscribe()
  })
})
