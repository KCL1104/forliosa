import { useRouterState } from "@tanstack/react-router"

/**
 * 外殼的導覽設定：桌面頂部列、手機底部列、AI 面板預設收成窄欄的頁面，都只在這裡改。
 * 目的地：帳本・市場・群組・討論（市場是收盤後的市場資訊頁，產品負責人 2026-11-13）。
 * 新增一個目的地（例如 `/discussions`）：`NavItem["to"]` 加上那個路徑，在 `NAV_ITEMS`／`DOCK_TABS` 各加（或換掉）一行，
 * 需要 AI 面板預設收合的話，再在 `QUIET_ROUTES` 加一行。`AppShell` 的頂部列與底部列只照這裡畫，不用改。
 */
export interface NavItem {
  /** 路由的路徑（要是 router.tsx 裡有的路由，`<Link to>` 才過得了型別檢查） */
  to: "/" | "/market" | "/groups" | "/discussions"
  label: string
  /** 這個網址算不算在這個目的地裡（決定 `aria-current="page"`） */
  match: (pathname: string) => boolean
}

const under = (prefix: string) => (pathname: string) => pathname === prefix || pathname.startsWith(`${prefix}/`)

const LEDGER: NavItem = { to: "/", label: "帳本", match: (p) => p === "/" || under("/stock")(p) }
const MARKET: NavItem = { to: "/market", label: "市場", match: under("/market") }
const GROUPS: NavItem = { to: "/groups", label: "群組", match: under("/groups") }
const DISCUSSIONS: NavItem = { to: "/discussions", label: "討論", match: under("/discussions") }

/** 桌面頂部列的文字分頁 */
export const NAV_ITEMS: readonly NavItem[] = [LEDGER, MARKET, GROUPS, DISCUSSIONS]

/**
 * 手機底部列的文字分頁（右邊另外有一格「問 AI」）。AI 對話紀錄（`/history`）不在這裡：
 * 從「問 AI」畫面的時鐘進去（產品負責人 2026-11-13）。
 */
export const DOCK_TABS: readonly NavItem[] = [LEDGER, MARKET, GROUPS, DISCUSSIONS]

/**
 * 頭像選單裡的頁面（設定、資料來源與授權）：桌面在這些頁面時，頭像下面畫導覽的那條線（選取語法 (a)），
 * 選單裡對應的項目標 `aria-current="page"`。不是新的導覽項目。管理後台（`/admin`）不在頭像選單裡（2026-11-14 移出）。
 */
export const ACCOUNT_ROUTES: readonly string[] = ["/settings", "/data-sources"]
export const isAccountRoute = (pathname: string) => ACCOUNT_ROUTES.some((r) => under(r)(pathname))
/** 管理後台（`/admin`、`/admin/discussions`、`/admin/news`）：站方管理員用自己的外殼（`AdminShell`） */
export const isAdminPath = under("/admin")

/**
 * AI 沒什麼可說的頁面：桌面的 AI 面板預設收成 56px 的窄欄（群組清單、群組、成員、討論、設定、紀錄、資料來源）。
 * `/admin` 留在清單裡：不是站方管理員的人打開它時是一般外殼裡的「找不到這個頁面」。
 * AI 不讀討論、也不替人發言，所以討論頁也在這裡。帳本與個股頁不在這裡：面板照記住的開合狀態（預設開）。
 */
// 市場頁（2026-11-14 第六次評分）：面板開著只有三列最近的對話、下面一大片空白，預設收成窄欄
export const QUIET_ROUTES: readonly string[] = ["/groups", "/discussions", "/admin", "/settings", "/history", "/data-sources", "/terms", "/privacy", "/market"]
export const isQuietRoute = (pathname: string) => QUIET_ROUTES.some((r) => under(r)(pathname))

/**
 * 畫面上「正在顯示」的那一頁是不是安靜的頁面。用已經換上去的那組 matches（不是剛按下連結的網址）：
 * 面板的寬度和頁面內容在同一次畫面更新裡一起換，不會先變寬、再換內容。
 */
export function useQuietRoute(): boolean {
  return useRouterState({ select: (s) => isQuietRoute(s.matches[s.matches.length - 1]?.pathname ?? s.location.pathname) })
}
