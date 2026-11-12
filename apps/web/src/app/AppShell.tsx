import { Link, Outlet, useRouterState } from "@tanstack/react-router"
import { EyeIcon, EyeOffIcon, HistoryIcon, NotebookTextIcon, PenToolIcon, SearchIcon, UsersIcon } from "lucide-react"
import { AiPanel } from "@/ai/AiPanel"
import { AiScreen } from "@/ai/AiScreen"
import { useAi, usePendingCount } from "@/ai/store"
import { Wordmark } from "@/components/brand"
import { Kbd } from "@/components/ui/kbd"
import { useIsDesktop } from "@/hooks/use-media-query"
import { cn } from "@/lib/utils"
import { TradeFormHost } from "@/pages/transactions/TradeForm"
import { usePrefs } from "@/stores/prefs"
import { AvatarMenu } from "./AvatarMenu"
import { CommandSearch } from "./CommandSearch"
import { useUi } from "./ui-store"

/**
 * 外殼（聯絡簿）：
 * - 桌面：頂部列（字標、帳本／群組、搜尋股票 ⌘K、隱私、頭像）＋主欄＋右側 AI 面板
 * - 手機：標題列（字標、隱私、頭像）＋浮動膠囊分頁「帳本｜群組｜紀錄」＋獨立的紫色「問 AI」
 */
export function AppShell() {
  const isDesktop = useIsDesktop()
  return (
    <div className="min-h-dvh bg-paper">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-sm focus:bg-act focus:px-3 focus:py-2 focus:text-act-fg">
        跳到主要內容
      </a>
      {isDesktop ? <TopBar /> : <MobileHeader />}
      <div className={cn(isDesktop && "flex items-start")}>
        <main id="main" tabIndex={-1} className={cn("min-w-0 flex-1 outline-none", !isDesktop && "pb-[calc(env(safe-area-inset-bottom,0px)+104px)]")}>
          <Outlet />
        </main>
        {isDesktop && <AiPanel />}
      </div>
      {!isDesktop && <Dock />}
      {!isDesktop && <AiScreen />}
      <CommandSearch />
      <TradeFormHost />
    </div>
  )
}

const NAV = [
  { to: "/", label: "帳本", match: (p: string) => p === "/" || p.startsWith("/stock") },
  { to: "/groups", label: "群組", match: (p: string) => p.startsWith("/groups") },
] as const

function PrivacyButton({ size = "desktop" }: { size?: "desktop" | "mobile" }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const toggle = usePrefs((s) => s.togglePrivacy)
  return (
    <button
      type="button"
      aria-pressed={privacy}
      aria-label={privacy ? "隱私模式開啟中：顯示金額" : "隱私模式：遮蔽金額"}
      title={privacy ? "顯示金額" : "遮蔽金額（截圖用）"}
      onClick={toggle}
      className={cn(
        "press grid place-items-center text-ink-2 hover:text-ink aria-pressed:text-ink",
        size === "desktop" ? "size-10 rounded-sm border border-transparent hover:border-rule aria-pressed:border-rule" : "size-11 rounded-full active:bg-hov",
      )}
    >
      {privacy ? <EyeOffIcon aria-hidden className={size === "desktop" ? "size-[18px]" : "size-[22px]"} /> : <EyeIcon aria-hidden className={size === "desktop" ? "size-[18px]" : "size-[22px]"} />}
    </button>
  )
}

function TopBar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const setSearchOpen = useUi((s) => s.setSearchOpen)
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center border-b border-rule bg-paper pr-7 pl-14">
      <Link to="/" aria-label="Forliosa 帳本" className="mr-8 rounded-sm">
        <Wordmark />
      </Link>
      <nav aria-label="主要" className="flex self-stretch">
        {NAV.map((n) => {
          const active = n.match(pathname)
          return (
            <Link
              key={n.to}
              to={n.to}
              aria-current={active ? "page" : undefined}
              className={cn(
                "-mb-px flex items-center border-b-2 px-3.5 text-base transition-colors",
                active ? "border-ink font-bold text-ink" : "border-transparent text-ink-2 hover:text-ink",
              )}
            >
              {n.label}
            </Link>
          )
        })}
      </nav>
      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        className="ml-12 flex h-10 w-[360px] items-center gap-2.5 rounded-sm border border-ctl bg-raised pr-2 pl-3 text-left text-ink-2 hover:border-ink-2"
        aria-label="搜尋股票（⌘K）"
      >
        <SearchIcon aria-hidden className="size-[18px]" />
        <span className="flex-1">搜尋股票</span>
        <Kbd>⌘K</Kbd>
      </button>
      <div className="ml-auto flex items-center gap-3">
        <PrivacyButton />
        <AvatarMenu />
      </div>
    </header>
  )
}

function MobileHeader() {
  return (
    <header className="flex h-[60px] items-center pt-[env(safe-area-inset-top,0px)] pr-2.5 pl-5" style={{ boxSizing: "content-box" }}>
      <Link to="/" aria-label="Forliosa 帳本" className="mr-auto rounded-sm">
        <Wordmark className="text-[1.375rem]" />
      </Link>
      <PrivacyButton size="mobile" />
      <AvatarMenu />
    </header>
  )
}

const TABS = [
  { to: "/", label: "帳本", icon: NotebookTextIcon, match: (p: string) => p === "/" || p.startsWith("/stock") },
  { to: "/groups", label: "群組", icon: UsersIcon, match: (p: string) => p.startsWith("/groups") },
  { to: "/history", label: "紀錄", icon: HistoryIcon, match: (p: string) => p.startsWith("/history") },
] as const

/** 浮動膠囊分頁＋獨立的「問 AI」 */
function Dock() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const setOpen = useAi((s) => s.setMobileOpen)
  const pending = usePendingCount()
  return (
    <>
      <div aria-hidden className="pointer-events-none fixed inset-x-0 bottom-0 z-20 h-[calc(env(safe-area-inset-bottom,0px)+108px)] bg-gradient-to-b from-transparent to-paper to-25%" />
      <div className="fixed inset-x-4 bottom-[calc(env(safe-area-inset-bottom,0px)+6px)] z-30 mx-auto flex h-16 max-w-[520px] gap-2">
        <nav aria-label="主要" className="flex flex-1 rounded-full border border-rule bg-raised shadow-lift">
          {TABS.map((t) => {
            const active = t.match(pathname)
            return (
              <Link
                key={t.to}
                to={t.to}
                aria-current={active ? "page" : undefined}
                className={cn("press flex flex-1 flex-col items-center justify-center gap-0.5 text-xs", active ? "font-bold text-ink" : "text-ink-2")}
              >
                <span className={cn("grid h-7 w-[52px] place-items-center rounded-full", active && "bg-sel")}>
                  <t.icon aria-hidden className="size-[22px]" />
                </span>
                {t.label}
              </Link>
            )
          })}
        </nav>
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={pending > 0 ? `問 AI（待簽名 ${pending} 筆）` : "問 AI"}
          className="press relative flex w-[86px] flex-col items-center justify-center gap-0.5 rounded-full border border-ai-rule bg-ai-wash text-sm font-bold text-ai shadow-lift"
        >
          <PenToolIcon aria-hidden className="size-[22px]" />
          問 AI
          {pending > 0 && (
            <span className="num absolute -top-1.5 right-1 grid h-5 min-w-5 place-items-center rounded-full bg-ai px-1 text-xs font-medium text-raised">{pending}</span>
          )}
        </button>
      </div>
    </>
  )
}
