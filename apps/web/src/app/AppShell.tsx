import { Link, Outlet, useRouterState } from "@tanstack/react-router"
import { EyeIcon, EyeOffIcon, SearchIcon } from "lucide-react"
import { useReadOnly, useViewingAs } from "@/api/view-as"
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
import { PlainLink } from "./links"
import { useUi } from "./ui-store"
import { useViewAsControls } from "./view-as"
import { MOBILE_BANNER_HEIGHT, ViewAsBanner } from "./ViewAsBanner"

/**
 * 外殼（聯絡簿）：
 * - 桌面：頂部列（字標、帳本／群組、搜尋股票 ⌘K、隱私、頭像）＋主欄＋右側 AI 面板
 * - 手機：標題列（字標、隱私、頭像）＋底部列（簿子的下緣：平的、滿版、上緣印刷雙線）——
 *   文字分頁「帳本｜群組｜紀錄」＋右邊一格紫色的「問 AI」（和簽名格同一種方格）
 * - 查看別人的資產（唯讀）：頂部「正在查看 ○○ 的資產（唯讀）」橫幅；AI 面板、全域 AI 輸入與「問 AI」都不出現，
 *   手機的「問 AI」那一格換成墨色的「結束查看」，橫幅黏在畫面頂端。
 * - `aria-current="page"` 只在導覽上（頂部列、底部列）；字標是一般連結（PlainLink）。
 *   `--sticky-top` 是頁面裡 sticky 分頁列的位置：桌面是頂部列（＋橫幅）的高度，手機查看中是橫幅的高度。
 */
export function AppShell() {
  const isDesktop = useIsDesktop()
  const readOnly = useReadOnly()
  const stickyTop = isDesktop ? (readOnly ? "6.5rem" : "4rem") : readOnly ? MOBILE_BANNER_HEIGHT : "0px"
  return (
    <div className="min-h-dvh bg-paper" style={{ "--sticky-top": stickyTop } as React.CSSProperties}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-sm focus:bg-act focus:px-3 focus:py-2 focus:text-act-fg">
        跳到主要內容
      </a>
      {isDesktop ? <TopBar /> : <MobileHeader />}
      {!isDesktop && <ViewAsBanner className="sticky top-0 z-30" />}
      <div className={cn(isDesktop && "flex items-start")}>
        <main id="main" tabIndex={-1} className={cn("min-w-0 flex-1 outline-none", !isDesktop && "pb-[calc(env(safe-area-inset-bottom,0px)+var(--dock-h))]")}>
          <Outlet />
        </main>
        {isDesktop && !readOnly && <AiPanel />}
      </div>
      {!isDesktop && <Dock />}
      {!isDesktop && !readOnly && <AiScreen />}
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
      // 開著＝選取語法 (b)：on-bg 底＋on-fg 字＋內框（淺色是墨色方塊、深色是格線藍底）
      className={cn("press sel-chip grid place-items-center rounded-sm text-ink-2", size === "desktop" ? "size-10" : "size-11 active:bg-hov")}
    >
      {privacy ? <EyeOffIcon aria-hidden className={size === "desktop" ? "size-[18px]" : "size-[22px]"} /> : <EyeIcon aria-hidden className={size === "desktop" ? "size-[18px]" : "size-[22px]"} />}
    </button>
  )
}

function TopBar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const setSearchOpen = useUi((s) => s.setSearchOpen)
  return (
    <div className="sticky top-0 z-30">
      <header className="flex h-16 items-center border-b border-rule bg-paper pr-7 pl-14">
        <PlainLink to="/" aria-label="Forliosa 帳本" className="mr-8 inline-flex min-h-11 items-center rounded-sm">
          <Wordmark />
        </PlainLink>
        <nav aria-label="主要" className="flex self-stretch">
          {NAV.map((n) => {
            const active = n.match(pathname)
            return (
              <Link
                key={n.to}
                to={n.to}
                aria-current={active ? "page" : undefined}
                className="sel-tab -mb-px flex items-center px-3.5 text-base text-ink-2"
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
      <ViewAsBanner />
    </div>
  )
}

function MobileHeader() {
  return (
    <header className="flex h-[60px] items-center pt-[env(safe-area-inset-top,0px)] pr-2.5 pl-5" style={{ boxSizing: "content-box" }}>
      <PlainLink to="/" aria-label="Forliosa 帳本" className="mr-auto inline-flex min-h-11 items-center rounded-sm">
        <Wordmark className="text-[1.375rem]" />
      </PlainLink>
      <PrivacyButton size="mobile" />
      <AvatarMenu />
    </header>
  )
}

const TABS = [
  { to: "/", label: "帳本", match: (p: string) => p === "/" || p.startsWith("/stock") },
  { to: "/groups", label: "群組", match: (p: string) => p.startsWith("/groups") },
  { to: "/history", label: "紀錄", match: (p: string) => p.startsWith("/history") },
] as const

/**
 * 手機底部列：簿子的下緣。平的、滿版、紙色，上緣一條印刷雙線；不浮起、沒有膠囊、沒有陰影、沒有漸層。
 * 左邊三個文字分頁（選取語法 (a)：墨色、700、2px 墨色線壓在上緣的雙線上），
 * 右邊一格「問 AI」：和簽名格同一種方格（直角、內縮細框），用 AI 的紫色；有待簽名的草稿時，格子裡多一行「待簽名 N 筆」。
 * 查看別人的資產時，那一格換成墨色的「結束查看」。
 */
function Dock() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const setOpen = useAi((s) => s.setMobileOpen)
  const pending = usePendingCount()
  const viewing = useViewingAs()
  const { exit } = useViewAsControls()
  return (
    <div className="dock">
      {/* 和頁面同一個版心：「問 AI」格的右緣對齊內容的右緣（20px；768 以上 32px） */}
      <div className="mx-auto flex h-(--dock-h) max-w-[1180px] items-center gap-3 pr-5 md:pr-8">
        <nav aria-label="主要" className="flex flex-1 self-stretch">
          {TABS.map((t) => {
            const active = t.match(pathname)
            return (
              <Link
                key={t.to}
                to={t.to}
                aria-current={active ? "page" : undefined}
                className="sel-tab-top relative flex flex-1 items-center justify-center pb-0.5 text-lg text-ink-2 focus-visible:-outline-offset-2 active:bg-hov"
              >
                {t.label}
              </Link>
            )
          })}
        </nav>
        {viewing ? (
          <button
            type="button"
            onClick={exit}
            aria-label={`正在查看${viewing.owner.display_name}的資產（唯讀），結束查看`}
            className="sign-box h-12 w-[5.25rem] text-md"
          >
            結束查看
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label={pending > 0 ? `問 AI（待簽名 ${pending} 筆）` : "問 AI"}
            className="ask-box h-12 w-[5.25rem] text-base"
          >
            {/* 和簽名格一樣兩行：上面一行小字（有待簽名的草稿時才有），下面一行粗體 */}
            {pending > 0 && <span className="num text-xs leading-none font-normal">待簽名 {pending} 筆</span>}
            <span className={pending > 0 ? "text-md leading-tight" : undefined}>問 AI</span>
          </button>
        )}
      </div>
    </div>
  )
}
