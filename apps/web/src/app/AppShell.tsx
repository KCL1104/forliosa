import { Link, Outlet, useRouterState } from "@tanstack/react-router"
import { EyeIcon, EyeOffIcon, MonitorIcon, MoonIcon, PlusIcon, SearchIcon, SunIcon } from "lucide-react"
import { api } from "@/api"
import { useMe } from "@/api/queries"
import { Wordmark } from "@/components/brand"
import { DemoChop } from "@/components/chop"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Kbd } from "@/components/ui/kbd"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import type { ThemePreference } from "@/api/types"
import { CommandSearch } from "./CommandSearch"
import { isActivePath, MOBILE_TABS, NAV_AI, NAV_DATA, NAV_MAIN, type NavItem } from "./nav"
import { TradeFormHost } from "@/pages/transactions/TradeForm"
import { useUi } from "./ui-store"

const isDemo = api.kind === "mock"

export function AppShell() {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <Sidebar />
      <div className="flex min-w-0 flex-col">
        <TopBar />
        <main
          id="main"
          className="mx-auto w-full max-w-[1280px] flex-1 px-4 pt-5 pb-[calc(88px+env(safe-area-inset-bottom,0px))] sm:px-6 lg:px-8 lg:pt-6 lg:pb-16"
        >
          <Outlet />
        </main>
      </div>
      <MobileTabBar />
      <CommandSearch />
      <TradeFormHost />
    </div>
  )
}

function usePathname() {
  return useRouterState({ select: (s) => s.location.pathname })
}

function Sidebar() {
  const pathname = usePathname()
  const me = useMe()
  return (
    <div className="hidden bg-rail lg:block">
    <aside className="sticky top-0 flex h-dvh flex-col bg-rail text-rail-foreground" aria-label="主要導覽">
      <div className="flex h-16 items-center px-5">
        <Link to="/" className="rounded-md outline-offset-4" aria-label="Forliosa 首頁">
          <Wordmark />
        </Link>
      </div>
      <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 pt-2 pb-4">
        <NavGroup items={NAV_MAIN} pathname={pathname} />
        <NavGroup items={NAV_AI} pathname={pathname} />
        <NavGroup items={NAV_DATA} pathname={pathname} />
      </nav>
      <div className="flex items-center justify-between gap-2 border-t border-rail-border px-5 py-4 text-sm">
        <span className="min-w-0 truncate text-rail-muted">{me.data?.display_name ?? "　"}</span>
        {isDemo && <DemoChop tone="rail" />}
      </div>
    </aside>
    </div>
  )
}

function NavGroup({ items, pathname }: { items: NavItem[]; pathname: string }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((item) => {
        const active = isActivePath(pathname, item.to)
        return (
          <li key={item.to}>
            <Link
              to={item.to}
              aria-current={active ? "page" : undefined}
              className={cn(
                "press flex h-10 items-center gap-3 rounded-md px-3 text-md text-rail-muted outline-offset-[-2px] hover:bg-rail-active/60 hover:text-rail-foreground",
                active && "bg-rail-active font-medium text-rail-foreground",
              )}
            >
              <item.icon className="size-[18px] shrink-0" aria-hidden />
              <span className="flex-1">{item.label}</span>
              {item.milestone && <span className="text-xs text-rail-muted">{item.milestone}</span>}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

function TopBar() {
  const setSearchOpen = useUi((s) => s.setSearchOpen)
  const openTradeForm = useUi((s) => s.openTradeForm)
  return (
    <header className="safe-top sticky top-0 z-30 border-b border-hairline bg-background">
      <div className="mx-auto flex h-14 w-full max-w-[1280px] items-center gap-2 px-4 sm:px-6 lg:h-16 lg:px-8">
        <Link to="/" className="mr-1 rounded-md lg:hidden" aria-label="Forliosa 首頁">
          <Wordmark />
        </Link>
        <button
          type="button"
          onClick={() => setSearchOpen(true)}
          className="press hidden h-10 w-full max-w-md items-center gap-2.5 rounded-md border border-input bg-card px-3 text-left text-md text-muted-foreground hover:border-ring/60 md:flex"
        >
          <SearchIcon className="size-4 shrink-0" aria-hidden />
          <span className="flex-1 truncate">搜尋股票代號或名稱</span>
          <Kbd>⌘K</Kbd>
        </button>
        <div className="flex-1 md:hidden" />
        <div className="ml-auto flex items-center gap-1.5">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setSearchOpen(true)} aria-label="搜尋股票">
            <SearchIcon />
          </Button>
          <PrivacyToggle />
          <ThemeMenu />
          <Button className="ml-1 hidden sm:inline-flex" onClick={() => openTradeForm()}>
            <PlusIcon />
            記一筆
          </Button>
        </div>
      </div>
    </header>
  )
}

function PrivacyToggle() {
  const privacy = usePrefs((s) => s.privacyMode)
  const toggle = usePrefs((s) => s.togglePrivacy)
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant={privacy ? "secondary" : "ghost"}
            size="icon"
            onClick={toggle}
            aria-pressed={privacy}
            aria-label={privacy ? "關閉隱私模式（顯示金額）" : "開啟隱私模式（遮蔽金額與股數）"}
          >
            {privacy ? <EyeOffIcon /> : <EyeIcon />}
          </Button>
        }
      />
      <TooltipContent>{privacy ? "隱私模式開啟中：金額與股數已遮蔽" : "隱私模式：一鍵遮蔽金額與股數"}</TooltipContent>
    </Tooltip>
  )
}

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: typeof SunIcon }[] = [
  { value: "light", label: "淺色", icon: SunIcon },
  { value: "dark", label: "深色", icon: MoonIcon },
  { value: "system", label: "跟隨系統", icon: MonitorIcon },
]

function ThemeMenu() {
  const theme = usePrefs((s) => s.theme)
  const set = usePrefs((s) => s.set)
  const Current = THEME_OPTIONS.find((o) => o.value === theme)?.icon ?? MonitorIcon
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label="切換主題" />}>
        <Current />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>主題</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => set({ theme: v as ThemePreference })}>
          {THEME_OPTIONS.map((o) => (
            <DropdownMenuRadioItem key={o.value} value={o.value}>
              <o.icon className="size-4 text-muted-foreground" aria-hidden />
              {o.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function MobileTabBar() {
  const pathname = usePathname()
  return (
    <nav
      aria-label="主要分頁"
      className="safe-bottom fixed inset-x-0 bottom-0 z-30 border-t border-hairline bg-card lg:hidden"
    >
      <ul className="mx-auto grid max-w-lg grid-cols-5">
        {MOBILE_TABS.map((tab) => {
          const active =
            isActivePath(pathname, tab.to) ||
            (tab.to === "/more" && ["/transactions", "/performance", "/reports", "/groups", "/import", "/settings"].some((p) => isActivePath(pathname, p))) ||
            (tab.to === "/holdings" && pathname.startsWith("/stock/"))
          return (
            <li key={tab.to}>
              <Link
                to={tab.to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "press flex h-[60px] flex-col items-center justify-center gap-1 text-xs text-muted-foreground",
                  active && "font-medium text-primary",
                )}
              >
                <tab.icon className="size-[22px]" strokeWidth={active ? 2.2 : 1.8} aria-hidden />
                {tab.label}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
