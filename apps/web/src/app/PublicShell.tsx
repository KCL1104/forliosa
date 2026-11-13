import { Link, Outlet, useRouterState } from "@tanstack/react-router"
import { Wordmark } from "@/components/brand"
import { buttonVariants } from "@/components/ui/button"
import { safeNext } from "@/lib/next-path"
import { PlainLink } from "./links"

/**
 * 沒登入時看公開討論用的外殼：只有字標和「登入」。
 * 沒有 AI 面板、沒有底部列、沒有連到帳本的東西（那些都要登入）；字標連到討論清單。
 * 版面：桌面頂部列 64px（底下一條格線），手機標題列 60px；字標和「登入」放在和內容同一個版心裡，左右緣對齊下面的內容；
 * 沒有底部列，所以 `--dock-h` 是 0，頁面裡 sticky 的東西貼齊畫面頂端（`--sticky-top`）。
 */
export function PublicShell() {
  const href = useRouterState({ select: (s) => s.location.href })
  const next = safeNext(href)
  return (
    <div className="min-h-dvh bg-paper" style={{ "--sticky-top": "0px", "--dock-h": "0px" } as React.CSSProperties}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-sm focus:bg-act focus:px-3 focus:py-2 focus:text-act-fg">
        跳到主要內容
      </a>
      {/* 和內容同一個版心（page-frame）：字標的左緣、「登入」的右緣對齊下面的內容 */}
      <header className="pt-[env(safe-area-inset-top,0px)] lg:border-b lg:border-rule">
        <div className="page-frame flex h-[60px] items-center px-5 md:px-8 lg:h-16 xl:px-14">
          <PlainLink to="/discussions" aria-label="Forliosa 討論" className="mr-auto inline-flex min-h-11 items-center rounded-sm">
            <Wordmark className="max-lg:text-[1.375rem]" />
          </PlainLink>
          <Link to="/login" search={next === "/" ? {} : { next }} className={buttonVariants({ variant: "outline" })}>
            登入
          </Link>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="min-w-0 outline-none">
        <Outlet />
      </main>
    </div>
  )
}
