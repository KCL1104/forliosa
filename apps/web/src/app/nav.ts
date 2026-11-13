import { useRouterState } from "@tanstack/react-router"

/**
 * 外殼的導覽設定：桌面頂部列、手機底部列、AI 面板預設收成窄欄的頁面，都只在這裡改。
 * 新增一個目的地（例如 `/discussions`）：`NavItem["to"]` 加上那個路徑，在 `NAV_ITEMS`／`DOCK_TABS` 各加（或換掉）一行，
 * 需要 AI 面板預設收合的話，再在 `QUIET_ROUTES` 加一行。`AppShell` 的頂部列與底部列只照這裡畫，不用改。
 */
export interface NavItem {
  /** 路由的路徑（要是 router.tsx 裡有的路由，`<Link to>` 才過得了型別檢查） */
  to: "/" | "/groups" | "/history"
  label: string
  /** 這個網址算不算在這個目的地裡（決定 `aria-current="page"`） */
  match: (pathname: string) => boolean
}

const under = (prefix: string) => (pathname: string) => pathname === prefix || pathname.startsWith(`${prefix}/`)

const LEDGER: NavItem = { to: "/", label: "帳本", match: (p) => p === "/" || under("/stock")(p) }
const GROUPS: NavItem = { to: "/groups", label: "群組", match: under("/groups") }
const HISTORY: NavItem = { to: "/history", label: "紀錄", match: under("/history") }

/** 桌面頂部列的文字分頁 */
export const NAV_ITEMS: readonly NavItem[] = [LEDGER, GROUPS]

/** 手機底部列的文字分頁（右邊另外有一格「問 AI」） */
export const DOCK_TABS: readonly NavItem[] = [LEDGER, GROUPS, HISTORY]

/**
 * 頭像選單裡的頁面（設定、資料來源與授權）：桌面在這些頁面時，頭像下面畫導覽的那條線（選取語法 (a)），
 * 選單裡對應的項目標 `aria-current="page"`。不是新的導覽項目。
 */
export const ACCOUNT_ROUTES: readonly string[] = ["/settings", "/data-sources"]
export const isAccountRoute = (pathname: string) => ACCOUNT_ROUTES.some((r) => under(r)(pathname))

/**
 * AI 沒什麼可說的頁面：桌面的 AI 面板預設收成 56px 的窄欄（群組清單、群組、成員、設定、紀錄、資料來源）。
 * 帳本與個股頁不在這裡：面板照記住的開合狀態（預設開）。
 */
export const QUIET_ROUTES: readonly string[] = ["/groups", "/settings", "/history", "/data-sources"]
export const isQuietRoute = (pathname: string) => QUIET_ROUTES.some((r) => under(r)(pathname))

/**
 * 畫面上「正在顯示」的那一頁是不是安靜的頁面。用已經換上去的那組 matches（不是剛按下連結的網址）：
 * 面板的寬度和頁面內容在同一次畫面更新裡一起換，不會先變寬、再換內容。
 */
export function useQuietRoute(): boolean {
  return useRouterState({ select: (s) => isQuietRoute(s.matches[s.matches.length - 1]?.pathname ?? s.location.pathname) })
}
