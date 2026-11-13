import { Link, Outlet, useRouterState } from "@tanstack/react-router"
import { Wordmark } from "@/components/brand"
import { buttonVariants } from "@/components/ui/button"
import { safeNext } from "@/lib/next-path"
import { cn } from "@/lib/utils"
import { PlainLink } from "./links"

/**
 * 沒登入時的外殼：字標（連到首頁的介紹頁）、「討論」（公開討論的清單）和「登入」。
 * 沒有搜尋、隱私、頭像、AI 面板、底部列，也沒有任何連到帳本的東西（那些都要登入）。
 * - 讀的頁面（公開討論、條款）：桌面頂部列 64px（底下一條格線），手機標題列 60px；字標和「登入」放在和內容同一個欄寬裡
 *   （`max-w-measure`）：字標對齊內容的左緣、「登入」對齊內容的右緣，不會遠遠掛在畫面最右邊；「登入」是外框按鈕。
 * - 首頁（`home`）：內容用整個版心，所以頁首也是整個版心；「登入」是這一頁唯一的動作——墨色的主要按鈕，
 *   頁首跟著捲動停在最上面（手機上三個示範畫面要捲好幾屏，「登入」一直按得到，不必在頁尾再放一顆）。
 * 沒有底部列，所以 `--dock-h` 是 0，頁面裡 sticky 的東西貼齊畫面頂端（`--sticky-top`）。
 * `children`：不放的話是路由的內容（`<Outlet />`）；首頁傳介紹頁（那個網址的路由內容是帳本，要登入）。
 */
export function PublicShell({ home, children }: { home?: boolean; children?: React.ReactNode }) {
  const href = useRouterState({ select: (s) => s.location.href })
  const next = safeNext(href)
  return (
    <div className="min-h-dvh bg-paper" style={{ "--sticky-top": "0px", "--dock-h": "0px" } as React.CSSProperties}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-sm focus:bg-act focus:px-3 focus:py-2 focus:text-act-fg">
        跳到主要內容
      </a>
      {/* 和內容同一個版心（page-frame）；讀的頁面再限到欄寬（max-w-measure）：字標的左緣、「登入」的右緣對齊下面的內容 */}
      <header className={cn("pt-[env(safe-area-inset-top,0px)]", home ? "sticky top-0 z-30 border-b border-rule bg-paper" : "lg:border-b lg:border-rule")}>
        <div className="page-frame px-5 md:px-8 xl:px-14">
          <div className={cn("flex h-[60px] items-center lg:h-16", !home && "max-w-measure")}>
            <PlainLink to="/" aria-label="Forliosa 首頁" className="mr-3 inline-flex min-h-11 items-center rounded-sm lg:mr-5">
              <Wordmark className="max-lg:text-[1.375rem]" />
            </PlainLink>
            {/*
              選取語法 (a)：桌面在討論的清單或主題頁時是墨色 700＋2px 墨色線（壓在頁首下緣的格線上）。
              手機的頁首沒有那條格線，線沒有地方靠：人已經在討論裡時這個連結不顯示（頁面標題就寫著「討論」，主題頁有「← 討論」）。
            */}
            <nav aria-label="主要" className="mr-auto flex self-stretch">
              <Link to="/discussions" className="sel-tab -mb-px flex items-center px-3 text-base text-ink-2 max-lg:aria-[current=page]:hidden">
                討論
              </Link>
            </nav>
            {/* `focus-visible:outline-solid`：`buttonVariants` 的 `outline-none` 會把鍵盤焦點框的線型也關掉（Tailwind v4），這裡補回來 */}
            <Link to="/login" search={next === "/" ? {} : { next }} className={cn(buttonVariants({ variant: home ? "default" : "outline" }), "focus-visible:outline-solid")}>
              登入
            </Link>
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="min-w-0 outline-none">
        {children ?? <Outlet />}
      </main>
    </div>
  )
}
