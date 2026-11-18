import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent, redirect, type RouterHistory } from "@tanstack/react-router"
import type { QueryClient } from "@tanstack/react-query"
import { RootLayout } from "@/app/RootLayout"
import { NotFoundPage } from "@/pages/NotFoundPage"
import { LedgerPage } from "@/pages/ledger/LedgerPage"

/** 個股頁七個分頁：總覽・估值・財務・籌碼・股利・事件・討論 */
export const STOCK_TABS = ["overview", "valuation", "financials", "chips", "dividends", "events", "discussions"] as const
export type StockTab = (typeof STOCK_TABS)[number]

export const LEDGER_VIEWS = ["holdings", "transactions", "dividends", "performance", "allocation"] as const
export type LedgerView = (typeof LEDGER_VIEWS)[number]
export interface LedgerSearch {
  view?: LedgerView
  /** 交易分段：只看某一檔（從個股頁「在帳本中查看」帶入） */
  symbol?: string
}

/** 群組頁的分頁：排行・動態・討論・持股・報告・分享・成員・頻道（「報告」的值沿用 digests：以前的連結照樣打得開） */
export const GROUP_TABS = ["ranking", "feed", "discussions", "holdings", "digests", "share", "members", "channels"] as const
export type GroupTab = (typeof GROUP_TABS)[number]
/** 「報告」分頁的日報／週報 */
export type GroupReport = "daily" | "weekly"
export interface GroupSearch {
  tab?: GroupTab
  /** 動態：只看一位成員 */
  member?: string
  /** 報告：日報或週報（沒有時：有日報的群組是日報，其他是週報） */
  report?: GroupReport
}
export interface LoginSearch {
  next?: string
  error?: string
  /** 剛刪除帳號回到登入頁：寫一句「你的帳號已經刪除」 */
  deleted?: true
}
/** 討論清單：沒有 scope 是「全部」（公開＋我的群組）；`scope=public` 只看公開；`scope=group&group_id=` 只看一個群組 */
export interface DiscussionsSearch {
  scope?: "public" | "group"
  group_id?: string
  /** 預設依最後回覆排序；`new` 依發表時間 */
  sort?: "new"
}
/**
 * 從哪裡來的（主題頁與開新主題的麵包屑、「取消」回到那裡）：
 * - 沒有 `from`：討論清單——`scope`／`group_id`／`sort` 是清單當時的篩選與排序，回去時還在
 * - `from=group`：那個群組的「討論」分頁（主題頁：主題自己所屬的群組；開新主題：`group_id`）
 * - `from=stock`：那檔股票的「討論」分頁（`symbol`）
 */
export type DiscussionFrom = "group" | "stock"
/** 主題頁：只帶「從哪裡來的」 */
export interface TopicSearch extends DiscussionsSearch {
  from?: DiscussionFrom
  /** `from=stock` 時是那一檔 */
  symbol?: string
}
/** 開新主題：預先選好發到哪裡（`scope`、`group_id`）與標記的股票（`symbol`）；`from`、`sort` 是從哪裡來的 */
export interface NewTopicSearch extends DiscussionsSearch {
  symbol?: string
  from?: DiscussionFrom
}
/** 管理後台的「討論」：預設是待處理的檢舉；`status=resolved` 是已處理 */
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
const listSearch = (s: Record<string, unknown>): DiscussionsSearch => ({ ...scopeSearch(s), sort: s.sort === "new" ? "new" : undefined })
const fromSearch = (s: Record<string, unknown>): DiscussionFrom | undefined => (s.from === "group" || s.from === "stock" ? s.from : undefined)
/** 主題頁的網址參數：`from=group`、`from=stock&symbol=`，否則是清單的篩選與排序 */
const topicSearch = (s: Record<string, unknown>): TopicSearch => {
  const from = fromSearch(s)
  const symbol = text(s.symbol)
  if (from === "group") return { from }
  if (from === "stock" && symbol) return { from, symbol }
  return listSearch(s)
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

/** 市場報告的三種（盤前重點、盤後重點、市場週報） */
export const MARKET_REPORT_KINDS = ["premarket", "close", "weekly"] as const
export type MarketReportKind = (typeof MARKET_REPORT_KINDS)[number]
/** 市場頁：預設是「行情」（不寫進網址）；`tab=reports` 是「報告」分頁，`kind` 是選哪一種 */
export interface MarketSearch {
  tab?: "reports"
  kind?: MarketReportKind
}
const reportKind = (v: unknown): MarketReportKind | undefined => (MARKET_REPORT_KINDS.includes(v as MarketReportKind) ? (v as MarketReportKind) : undefined)

// 市場：收盤後的指數、類股、排行與重大訊息（登入後；首頁仍是帳本）；「報告」分頁是市場報告（2026-11-17）
const marketRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/market",
  validateSearch: (s: Record<string, unknown>): MarketSearch => (s.tab === "reports" ? { tab: "reports", kind: reportKind(s.kind) } : {}),
  component: lazyRouteComponent(() => import("@/pages/market/MarketPage"), "MarketPage"),
})

/** 一份市場報告（登入才看得到；沒有公開網址）：`version` 看舊版 */
export interface ReportSearch {
  version?: number
}
const marketReportRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/market/reports/$reportId",
  validateSearch: (s: Record<string, unknown>): ReportSearch => {
    const v = Number(s.version)
    return Number.isInteger(v) && v > 0 ? { version: v } : {}
  },
  component: lazyRouteComponent(() => import("@/pages/market/reports/ReportPage"), "ReportPage"),
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
    report: s.report === "daily" || s.report === "weekly" ? s.report : undefined,
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
    deleted: s.deleted === 1 || s.deleted === "1" || s.deleted === true ? true : undefined,
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
  validateSearch: listSearch,
  component: lazyRouteComponent(() => import("@/pages/discussions/DiscussionsPage"), "DiscussionsPage"),
})

const newTopicRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/discussions/new",
  validateSearch: (s: Record<string, unknown>): NewTopicSearch => ({ ...listSearch(s), symbol: text(s.symbol), from: fromSearch(s) }),
  component: lazyRouteComponent(() => import("@/pages/discussions/NewTopicPage"), "NewTopicPage"),
})

const topicRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/discussions/$topicId",
  validateSearch: topicSearch,
  component: lazyRouteComponent(() => import("@/pages/discussions/TopicPage"), "TopicPage"),
})

// 管理後台（站方管理員；其他人是「找不到這個頁面」）：外殼是 `app/AdminShell.tsx`，RootLayout 依路徑換上
const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin",
  component: lazyRouteComponent(() => import("@/pages/admin/AdminOverviewPage"), "AdminOverviewPage"),
})
const adminNewsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/news",
  component: lazyRouteComponent(() => import("@/pages/admin/AdminNewsPage"), "AdminNewsPage"),
})
/** 管理後台「會員」：個人會員（預設）或群組加值（`?kind=group`） */
export interface AdminMembersSearch {
  kind?: "group"
}
const adminMembersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/members",
  validateSearch: (s: Record<string, unknown>): AdminMembersSearch => ({ kind: s.kind === "group" ? "group" : undefined }),
  component: lazyRouteComponent(() => import("@/pages/admin/AdminMembersPage"), "AdminMembersPage"),
})
// 管理後台「市場報告」：狀態、盲測、最近的產生紀錄、三張手動維護的表
const adminReportsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/reports",
  component: lazyRouteComponent(() => import("@/pages/admin/AdminReportsPage"), "AdminReportsPage"),
})
/** 盲測一份報告的 A／B／C：`v` 是左邊（或手機上）看的那一個，`vs` 是寬螢幕右邊並排的那一個 */
export interface AdminTrialSearch {
  v?: "A" | "B" | "C"
  vs?: "A" | "B" | "C"
}
const variantLabel = (v: unknown) => (v === "A" || v === "B" || v === "C" ? v : undefined)
const adminTrialRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/reports/$reportId",
  validateSearch: (s: Record<string, unknown>): AdminTrialSearch => ({ v: variantLabel(s.v), vs: variantLabel(s.vs) }),
  component: lazyRouteComponent(() => import("@/pages/admin/AdminTrialComparePage"), "AdminTrialComparePage"),
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

// 服務條款、隱私權政策、免責聲明：不用登入就能讀（`lib/next-path.ts` 的 `isPublicReadPath`）
const termsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/terms",
  component: lazyRouteComponent(() => import("@/pages/legal/routes"), "TermsPage"),
})
const privacyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/privacy",
  component: lazyRouteComponent(() => import("@/pages/legal/routes"), "PrivacyPage"),
})
const disclaimerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/disclaimer",
  component: lazyRouteComponent(() => import("@/pages/legal/routes"), "DisclaimerPage"),
})

const routeTree = rootRoute.addChildren([
  ledgerRoute,
  stockRoute,
  marketRoute,
  marketReportRoute,
  groupsRoute,
  groupRoute,
  memberRoute,
  loginRoute,
  inviteRoute,
  historyRoute,
  discussionsRoute,
  newTopicRoute,
  topicRoute,
  adminRoute,
  adminDiscussionsRoute,
  adminNewsRoute,
  adminMembersRoute,
  adminReportsRoute,
  adminTrialRoute,
  settingsRoute,
  dataSourcesRoute,
  termsRoute,
  privacyRoute,
  disclaimerRoute,
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
