import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent, redirect, type RouterHistory } from "@tanstack/react-router"
import type { QueryClient } from "@tanstack/react-query"
import { RootLayout } from "@/app/RootLayout"
import { NotFoundPage } from "@/pages/NotFoundPage"
import { LedgerPage } from "@/pages/ledger/LedgerPage"

/** 個股頁六個分頁：總覽・估值・財務・籌碼・股利・事件 */
export const STOCK_TABS = ["overview", "valuation", "financials", "chips", "dividends", "events"] as const
export type StockTab = (typeof STOCK_TABS)[number]

export const LEDGER_VIEWS = ["holdings", "transactions", "dividends", "performance"] as const
export type LedgerView = (typeof LEDGER_VIEWS)[number]
export interface LedgerSearch {
  view?: LedgerView
  /** 交易分段：只看某一檔（從個股頁「在帳本中查看」帶入） */
  symbol?: string
}

/** 群組頁的分頁：排行・動態・持股・週報・我的分享・成員・頻道 */
export const GROUP_TABS = ["ranking", "feed", "holdings", "digests", "share", "members", "channels"] as const
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
