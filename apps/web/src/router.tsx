import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router"
import type { QueryClient } from "@tanstack/react-query"
import { AppShell } from "@/app/AppShell"
import { NotFoundPage } from "@/pages/NotFoundPage"
import { HomePage } from "@/pages/home/HomePage"
import { HoldingsPage } from "@/pages/holdings/HoldingsPage"

export const STOCK_TABS = ["overview", "kline", "valuation", "financials", "dividends", "mine", "chips", "news", "ai"] as const
export type StockTab = (typeof STOCK_TABS)[number]

const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: AppShell,
  notFoundComponent: NotFoundPage,
})

const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: HomePage })

export interface HoldingsSearch {
  account?: string
  market?: "TWSE" | "TPEX" | "US"
}
const holdingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/holdings",
  validateSearch: (s: Record<string, unknown>): HoldingsSearch => ({
    account: typeof s.account === "string" ? s.account : undefined,
    market: s.market === "TWSE" || s.market === "TPEX" || s.market === "US" ? s.market : undefined,
  }),
  component: HoldingsPage,
})

const stockRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/stock/$symbol",
  validateSearch: (s: Record<string, unknown>): { tab?: StockTab } => ({
    tab: STOCK_TABS.includes(s.tab as StockTab) ? (s.tab as StockTab) : undefined,
  }),
  component: lazyRouteComponent(() => import("@/pages/stock/StockPage"), "StockPage"),
})

const transactionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/transactions",
  component: lazyRouteComponent(() => import("@/pages/transactions/TransactionsPage"), "TransactionsPage"),
})

const performanceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/performance",
  component: lazyRouteComponent(() => import("@/pages/performance/PerformancePage"), "PerformancePage"),
})

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: lazyRouteComponent(() => import("@/pages/settings/SettingsPage"), "SettingsPage"),
})

const placeholder = <P extends string>(path: P, name: "WatchlistPage" | "AiPage" | "ReportsPage" | "GroupsPage" | "ImportPage" | "MorePage") =>
  createRoute({
    getParentRoute: () => rootRoute,
    path,
    component: lazyRouteComponent(() => import("@/pages/placeholders/ComingSoonPages"), name),
  })

const routeTree = rootRoute.addChildren([
  homeRoute,
  holdingsRoute,
  stockRoute,
  transactionsRoute,
  performanceRoute,
  settingsRoute,
  placeholder("/watchlist", "WatchlistPage"),
  placeholder("/ai", "AiPage"),
  placeholder("/reports", "ReportsPage"),
  placeholder("/groups", "GroupsPage"),
  placeholder("/import", "ImportPage"),
  placeholder("/more", "MorePage"),
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
