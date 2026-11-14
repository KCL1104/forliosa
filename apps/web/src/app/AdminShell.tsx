import { Link, Outlet, useRouterState } from "@tanstack/react-router"
import { useViewer } from "@/api/queries"
import { useReadOnly } from "@/api/view-as"
import { Wordmark } from "@/components/brand"
import { buttonVariants } from "@/components/ui/button"
import { useIsDesktop } from "@/hooks/use-media-query"
import { cn } from "@/lib/utils"
import { AppShell } from "./AppShell"
import { PlainLink } from "./links"

/** 管理後台的分頁：總覽・討論・新聞下架 */
const ADMIN_TABS = [
  { to: "/admin", label: "總覽", match: (p: string) => p === "/admin" || p === "/admin/" },
  { to: "/admin/discussions", label: "討論", match: (p: string) => p.startsWith("/admin/discussions") },
  { to: "/admin/news", label: "新聞下架", match: (p: string) => p.startsWith("/admin/news") },
] as const

/**
 * `/admin*` 的外殼：站方管理員（而且不是在查看別人的資產）才是管理後台自己的外殼；
 * 其他人照一般的外殼，頁面自己顯示「找不到這個頁面」（或查看中的擋頁）——不讓人從外框看出這裡有東西。
 */
export function AdminGate() {
  const { user } = useViewer()
  const readOnly = useReadOnly()
  return user?.is_admin && !readOnly ? <AdminShell /> : <AppShell />
}

/**
 * 管理後台（站方管理員；2026-11-14 從頭像選單移出來）：和帳本分開的一個小外殼。
 * 頁首：字標｜管理後台、分頁（總覽・討論・新聞下架；選取語法 (a)）、外框按鈕「回到帳本」。
 * 桌面分頁在頁首那一列；手機頁首下面再一列分頁。沒有 AI 面板、搜尋、隱私與底部列。
 */
function AdminShell() {
  const isDesktop = useIsDesktop()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const tabs = ADMIN_TABS.map((t) => (
    <Link
      key={t.to}
      to={t.to}
      aria-current={t.match(pathname) ? "page" : undefined}
      className="sel-tab -mb-px flex items-center px-3 text-base whitespace-nowrap text-ink-2 focus-visible:-outline-offset-2 lg:px-3.5"
    >
      {t.label}
    </Link>
  ))
  return (
    <div className="min-h-dvh bg-paper" style={{ "--sticky-top": isDesktop ? "4rem" : "0px", "--dock-h": "0px" } as React.CSSProperties}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-sm focus:bg-act focus:px-3 focus:py-2 focus:text-act-fg">
        跳到主要內容
      </a>
      <header className="border-b border-rule bg-paper pt-[env(safe-area-inset-top,0px)] lg:sticky lg:top-0 lg:z-30">
        <div className="page-frame px-5 md:px-8 xl:px-14">
          <div className="flex h-[60px] items-center gap-3 lg:h-16">
            <PlainLink to="/admin" aria-label="管理後台總覽" className="inline-flex min-h-11 items-center rounded-sm">
              <Wordmark className="max-lg:text-[1.375rem]" />
            </PlainLink>
            <span className="border-l border-rule pl-3 text-base whitespace-nowrap text-ink-2">管理後台</span>
            {isDesktop && (
              <nav aria-label="管理後台" className="ml-8 flex self-stretch">
                {tabs}
              </nav>
            )}
            <Link to="/" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "ml-auto focus-visible:outline-solid")}>
              回到帳本
            </Link>
          </div>
          {!isDesktop && (
            <nav aria-label="管理後台" className="-ml-3 flex h-11 overflow-x-auto">
              {tabs}
            </nav>
          )}
        </div>
      </header>
      <main id="main" tabIndex={-1} className="min-w-0 outline-none">
        <Outlet />
      </main>
    </div>
  )
}
