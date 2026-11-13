import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent, redirect, type RouterHistory } from "@tanstack/react-router"
import type { QueryClient } from "@tanstack/react-query"
import { RootLayout } from "@/app/RootLayout"
import { NotFoundPage } from "@/pages/NotFoundPage"
import { LedgerPage } from "@/pages/ledger/LedgerPage"

/** 個股頁七個分頁：總覽・估值・財務・籌碼・股利・事件・討論 */
export const STOCK_TABS = ["overview", "valuation", "financials", "chips", "dividends", "events", "discussions"] as const
export type StockTab = (typeof STOCK_TABS)[number]

export const LEDGER_VIEWS = ["holdings", "transactions", "dividends", "performance"] as const
export type LedgerView = (typeof LEDGER_VIEWS)[number]
export interface LedgerSearch {
  view?: LedgerView
  /** 交易分段：只看某一檔（從個股頁「在帳本中查看」帶入） */
  symbol?: string
}

/** 群組頁的分頁：排行・動態・討論・持股・週報・分享・成員・頻道 */
export const GROUP_TABS = ["ranking", "feed", "discussions", "holdings", "digests", "share", "members", "channels"] as const
export type GroupTab = (typeof GROUP_TABS)[number]
export interface GroupSearch {
  tab?: GroupTab
  /** 動態：只看一位成員 */
  member?: string
}
export interface LoginSearch {
  next?: string
  error?: string
}
/** 討論清單：沒有 scope 是「全部」（公開＋我的群組）；`scope=public` 只看公開；`scope=group&group_id=` 只看一個群組 */
export interface DiscussionsSearch {
  scope?: "public" | "group"
  group_id?: string
  /** 預設依最後回覆排序；`new` 依發表時間 */
  sort?: "new"
}
/** 開新主題：預先選好發到哪裡（`scope`、`group_id`）與標記的股票（`symbol`） */
export interface NewTopicSearch {
  scope?: "public" | "group"
  group_id?: string
  symbol?: string
}
/** 站方管理：預設是待處理的檢舉；`status=resolved` 是已處理 */
export interface AdminDiscussionsSearch {
  status?: "resolved"
}
const text = (v: unknown) => (typeof v === "string" && v ? v : undefined)
/** `scope=group` 一定要有 `group_id`，否則當作沒有指定 */
const scopeSearch = (s: Record<string, unknown>): { scope?: "public" | "group"; group_id?: string } => {
  const group = text(s.group_id)
  if (s.scope === "group" && group) return { scope: "group", group_id: group }
  return { scope: s.scope === "public" ? "public" : undefined, group_id: undefined }
}

const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
})

const ledgerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: (s: Record<string, unknown>): LedgerSearch => ({
    view: LEDGER_VIEWS.includes(s.view as LedgerView) && s.view !== "holdings" ? (s.view as LedgerView) : undefined,
    symbol: typeof s.symbol === "string" && s.symbol ? s.symbol : undefined,
  }),
  component: LedgerPage,
})

const stockRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/stock/$symbol",
  validateSearch: (s: Record<string, unknown>): { tab?: StockTab } => ({
    tab: STOCK_TABS.includes(s.tab as StockTab) && s.tab !== "overview" ? (s.tab as StockTab) : undefined,
  }),
  component: lazyRouteComponent(() => import("@/pages/stock/StockPage"), "StockPage"),
})

const groupsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/groups",
  component: lazyRouteComponent(() => import("@/pages/groups/GroupsPage"), "GroupsPage"),
})

const groupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/groups/$groupId",
  validateSearch: (s: Record<string, unknown>): GroupSearch => ({
    tab: GROUP_TABS.includes(s.tab as GroupTab) && s.tab !== "ranking" ? (s.tab as GroupTab) : undefined,
    member: typeof s.member === "string" && s.member ? s.member : undefined,
  }),
  component: lazyRouteComponent(() => import("@/pages/groups/GroupPage"), "GroupPage"),
})

const memberRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/groups/$groupId/members/$userId",
  component: lazyRouteComponent(() => import("@/pages/groups/MemberPage"), "MemberPage"),
})

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (s: Record<string, unknown>): LoginSearch => ({
    next: typeof s.next === "string" && s.next ? s.next : undefined,
    error: typeof s.error === "string" && s.error ? s.error : undefined,
  }),
  component: lazyRouteComponent(() => import("@/pages/auth/LoginPage"), "LoginPage"),
})

const inviteRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/invite/$token",
  component: lazyRouteComponent(() => import("@/pages/groups/InvitePage"), "InvitePage"),
})

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: lazyRouteComponent(() => import("@/pages/history/HistoryPage"), "HistoryPage"),
})

const discussionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/discussions",
  validateSearch: (s: Record<string, unknown>): DiscussionsSearch => ({ ...scopeSearch(s), sort: s.sort === "new" ? "new" : undefined }),
  component: lazyRouteComponent(() => import("@/pages/discussions/DiscussionsPage"), "DiscussionsPage"),
})

const newTopicRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/discussions/new",
  validateSearch: (s: Record<string, unknown>): NewTopicSearch => ({ ...scopeSearch(s), symbol: text(s.symbol) }),
  component: lazyRouteComponent(() => import("@/pages/discussions/NewTopicPage"), "NewTopicPage"),
})

const topicRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/discussions/$topicId",
  component: lazyRouteComponent(() => import("@/pages/discussions/TopicPage"), "TopicPage"),
})

const adminDiscussionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/discussions",
  validateSearch: (s: Record<string, unknown>): AdminDiscussionsSearch => ({ status: s.status === "resolved" ? "resolved" : undefined }),
  component: lazyRouteComponent(() => import("@/pages/admin/AdminDiscussionsPage"), "AdminDiscussionsPage"),
})

const dataSourcesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/data-sources",
  component: lazyRouteComponent(() => import("@/pages/data-sources/DataSourcesPage"), "DataSourcesPage"),
})

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: lazyRouteComponent(() => import("@/pages/settings/SettingsPage"), "SettingsPage"),
})

/** 舊網址（第一版的側欄頁面）導回新的資訊架構 */
const legacy = (path: string, to: string, search?: LedgerSearch) =>
  createRoute({
    getParentRoute: () => rootRoute,
    path,
    beforeLoad: () => {
      throw redirect({ to, search, replace: true })
    },
  })

const routeTree = rootRoute.addChildren([
  ledgerRoute,
  stockRoute,
  groupsRoute,
  groupRoute,
  memberRoute,
  loginRoute,
  inviteRoute,
  historyRoute,
  discussionsRoute,
  newTopicRoute,
  topicRoute,
  adminDiscussionsRoute,
  settingsRoute,
  dataSourcesRoute,
  legacy("/holdings", "/"),
  legacy("/transactions", "/", { view: "transactions" }),
  legacy("/performance", "/", { view: "performance" }),
  legacy("/watchlist", "/"),
  legacy("/ai", "/history"),
  legacy("/reports", "/history"),
  legacy("/import", "/"),
  legacy("/more", "/settings"),
])

/** `history`：測試用記憶體歷史（預設是瀏覽器網址） */
export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    context: { queryClient },
    defaultPreload: "intent",
    scrollRestoration: true,
  })
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
