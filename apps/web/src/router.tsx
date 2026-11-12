import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent, redirect } from "@tanstack/react-router"
import type { QueryClient } from "@tanstack/react-query"
import { AppShell } from "@/app/AppShell"
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

const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: AppShell,
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

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: lazyRouteComponent(() => import("@/pages/history/HistoryPage"), "HistoryPage"),
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
  historyRoute,
  settingsRoute,
  legacy("/holdings", "/"),
  legacy("/transactions", "/", { view: "transactions" }),
  legacy("/performance", "/", { view: "performance" }),
  legacy("/watchlist", "/"),
  legacy("/ai", "/history"),
  legacy("/reports", "/history"),
  legacy("/import", "/"),
  legacy("/more", "/settings"),
])

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
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
