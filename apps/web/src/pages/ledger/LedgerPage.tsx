import NumberFlow from "@number-flow/react"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"
import { lazy, Suspense, useEffect } from "react"
import { createPortal } from "react-dom"
import { api } from "@/api"
import { useHoldings, usePerformance, useSummary, useUpcoming } from "@/api/queries"
import type { PortfolioSummary } from "@/api/types"
import { usePanelSlot } from "@/ai/panel-slot"
import { useAskAi } from "@/ai/use-ask"
import { latestPendingDraftId, usePendingCount } from "@/ai/store"
import { Masked } from "@/components/finance"
import { DateCell } from "@/components/date-cell"
import { DemoTag } from "@/components/section"
import { Segmented } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, directionGlyph, formatMoney, formatPercent, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import type { LedgerSearch, LedgerView } from "@/router"
import { CustomizeButton } from "./CustomizeButton"
import { HoldingsView } from "./HoldingsView"
import { useLedgerCounts } from "./use-ledger-counts"
import { useLedgerClose } from "@/hooks/use-close"
import { useIsDesktop } from "@/hooks/use-media-query"
import { SourcesFooter } from "@/components/data-notes"
import { upcomingShort, upcomingText } from "@/lib/ledger-display"
import { useReadOnly } from "@/api/view-as"
import { PlainLink } from "@/app/links"
import { useUi } from "@/app/ui-store"
import { useCanImport } from "@/pages/transactions/import/access"
import { PageFrame } from "@/app/PageFrame"
import { usePageTitle } from "@/app/page-title"
import { HeroTrend } from "./HeroTrend"
import { useLedgerPrefs } from "./ledger-prefs"

const TransactionsView = lazy(() => import("./TransactionsView").then((m) => ({ default: m.TransactionsView })))
const DividendsView = lazy(() => import("./DividendsView").then((m) => ({ default: m.DividendsView })))
const PerformanceView = lazy(() => import("./PerformanceView").then((m) => ({ default: m.PerformanceView })))
const AllocationView = lazy(() => import("./AllocationView").then((m) => ({ default: m.AllocationView })))

/**
 * 分段：持倉・紀錄・績效・配置（產品負責人 2026-11-14：只需要記買進，賣出與股利不用特別去記——交易和股利
 * 併成「紀錄」，想查才點；2026-11-18 加第 4 段「配置」，延遲載入，帳本首頁不會變重）。網址的 `view` 不變：
 * `transactions`、`dividends` 都屬於「紀錄」，在分段裡面用兩個小分頁切換。順序也是數字鍵 1–4 的對應。
 */
type Segment = "holdings" | "records" | "performance" | "allocation"
const SEGMENT_KEYS: readonly Segment[] = ["holdings", "records", "performance", "allocation"]
const segmentOf = (view: LedgerView): Segment => (view === "transactions" || view === "dividends" ? "records" : view)
const viewOf = (segment: Segment): LedgerView => (segment === "records" ? "transactions" : segment)

/**
 * 帳本（首頁）。首屏給持倉（產品負責人 2026-11-19 選 B／C2）：
 * - 桌面：主數字（總資產旁是今日與總損益）→ 總資產走勢（區間按鈕在讀數那一列右邊）→ 分段 → 清單；本週事項在 AI 面板標題下面
 *   （面板收著或看對話紀錄時接在清單後面）。
 * - 手機：主數字 → 分段 → 清單 → 走勢 → 本週事項；績效分段的走勢在分段列與內容之間（走勢的區間就是績效的區間）。
 */
export function LedgerPage() {
  const search = useSearch({ from: "/" }) as LedgerSearch
  const navigate = useNavigate()
  const view: LedgerView = search.view ?? "holdings"
  const segment = segmentOf(view)
  usePageTitle("帳本")
  const summary = useSummary()
  // 總資產走勢的序列（「全部」、不帶基準，和 HeroTrend 同一個查詢）和主數字同時開始讀，兩個都回來才一起換掉主數字的骨架：
  // 走勢一出現就是最後的大小（一張圖、或歷史短時的一行原因），不會先放一塊整張圖大的骨架再收成一行、把下面整片往上拉
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const trendPerf = usePerformance("ALL")
  const heroReady = !!summary.data && (!showTrend || !!trendPerf.data || trendPerf.isError)
  const counts = useLedgerCounts()
  const pending = usePendingCount()
  const ask = useAskAi()
  // 查看別人的資產（唯讀）：沒有待簽名的草稿（那是自己的 AI）
  const readOnly = useReadOnly()
  const canImport = useCanImport()
  const openImport = useUi((s) => s.openImport)
  const isDesktop = useIsDesktop()
  // 面板的本頁欄位只在桌面、面板開著、不是看對話紀錄時存在（`ai/panel-slot.ts`）
  const panelSlot = usePanelSlot((s) => s.el)
  const trend = heroReady ? <HeroTrend view={view} /> : null

  const setView = (v: LedgerView) => void navigate({ to: "/", search: (s: LedgerSearch) => ({ ...s, view: v === "holdings" ? undefined : v, symbol: v === "transactions" ? s.symbol : undefined }), replace: true })

  // 數字鍵 1–4 切換分段（持倉・紀錄・績效・配置）：焦點在輸入框、選單、對話框裡，或同時按著修飾鍵時不動作
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return
      const segment = SEGMENT_KEYS[["1", "2", "3", "4"].indexOf(e.key)]
      if (!segment) return
      const next = viewOf(segment)
      const t = e.target instanceof Element ? e.target : null
      if (t?.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], [role="combobox"]')) return
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) return
      e.preventDefault()
      void navigate({ to: "/", search: (s: LedgerSearch) => ({ ...s, view: next === "holdings" ? undefined : next, symbol: next === "transactions" ? s.symbol : undefined }), replace: true })
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [navigate])

  return (
    <PageFrame>
      <h1 className="sr-only">帳本</h1>
      {summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : (
        <Hero summary={heroReady ? summary.data : undefined} />
      )}
      {/* 總資產走勢（產品負責人 2026-11-17 選方案 B；「自訂」可以整塊關掉）。首屏給持倉（2026-11-19 選 B／C2）：
          桌面在主數字正下方；手機在內容下面——績效分段例外，走勢的區間就是績效的區間，放在分段列與內容之間 */}
      {isDesktop && trend}

      <div className="mt-5 flex items-center gap-4 lg:mt-8">
        <Segmented
          label="帳本內容"
          value={segment}
          onChange={(v) => setView(viewOf(v))}
          controls="ledger-view"
          className="max-lg:flex-1"
          options={[
            { value: "holdings", label: "持倉", count: counts.holdings, shortcut: "1" },
            { value: "records", label: "紀錄", shortcut: "2" },
            { value: "performance", label: "績效", shortcut: "3" },
            { value: "allocation", label: "配置", shortcut: "4" },
          ]}
        />
        {pending > 0 && !readOnly && (
          <button
            type="button"
            onClick={() => {
              const id = latestPendingDraftId()
              ask.showDraft(id)
            }}
            className="press hidden h-8 items-center rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3 text-sm font-medium text-ai hover:border-ai lg:inline-flex"
            aria-label={`待簽名 ${pending} 筆：到 AI 面板的草稿確認`}
          >
            待簽名 {pending} 筆
          </button>
        )}
        {/* 手動記一筆：直接開輸入框（用一句話記的入口在 AI 面板）。手機放在分段旁邊的「＋」。
            匯入（2026-11-17）：開了匯入的帳號在記一筆左邊多一顆「匯入」，先選匯入庫存或對帳單（原本藏在記一筆、AI「＋」裡，朋友找不到） */}
        {!readOnly && (
          <>
            {canImport && (
              <Button variant="outline" className="ml-auto max-lg:hidden" onClick={() => openImport()}>
                匯入
              </Button>
            )}
            <Button variant="outline" className={cn("max-lg:hidden", !canImport && "ml-auto")} onClick={() => ask.action("form")}>
              記一筆
            </Button>
            <div className="flex shrink-0 gap-2 self-stretch lg:hidden">
              {/* 400px 以下放不下四段＋匯入＋「＋」（360px 的分段會斷成直排），匯入改從記一筆裡的「匯入庫存或對帳單」進去 */}
              {canImport && (
                <button type="button" onClick={() => openImport()} className="press grid place-items-center rounded-sm border border-ctl px-3 text-base text-ink hover:bg-hov max-[400px]:hidden">
                  匯入
                </button>
              )}
              <button type="button" aria-label="記一筆" onClick={() => ask.action("form")} className="press grid w-11 place-items-center rounded-sm border border-ctl text-ink hover:bg-hov">
                <PlusIcon aria-hidden className="size-5" />
              </button>
            </div>
          </>
        )}
        {view === "holdings" && <CustomizeButton className={cn("max-lg:hidden", readOnly && "ml-auto")} />}
      </div>
      {pending > 0 && !readOnly && (
        <button
          type="button"
          onClick={() => ask.showDraft(latestPendingDraftId())}
          className="press mt-3 flex h-11 w-full items-center justify-between rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3.5 text-base font-medium text-ai lg:hidden"
        >
          待簽名 {pending} 筆
          <span aria-hidden className="font-normal">→</span>
        </button>
      )}

      {!isDesktop && view === "performance" && trend}
      <div id="ledger-view" role="tabpanel" aria-labelledby={`tab-${segment}`} className="mt-5 lg:mt-5">
        {segment === "records" && (
          // 紀錄裡的兩個小分頁：交易（買進、賣出與其他）、股利（台股的現金股利與配股是系統在除息日自動記的）
          <div role="tablist" aria-label="紀錄的內容" className="mb-4 flex gap-5 border-b border-rule">
            {([["transactions", "交易", counts.transactions], ["dividends", "股利", counts.dividends]] as const).map(([v, label, count]) => (
              <button
                key={v}
                type="button"
                role="tab"
                id={`subtab-${v}`}
                aria-selected={view === v}
                aria-controls="ledger-records"
                tabIndex={view === v ? 0 : -1}
                onClick={() => setView(v)}
                onKeyDown={(e) => {
                  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return
                  e.preventDefault()
                  setView(v === "transactions" ? "dividends" : "transactions")
                  const list = e.currentTarget.parentElement
                  requestAnimationFrame(() => list?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus())
                }}
                className={cn("sel-tab -mb-px inline-flex min-h-10 items-baseline gap-1.5 text-base text-ink-2 pointer-coarse:min-h-11", view === v && "active")}
              >
                {label}
                {count != null && <span className="num text-sm font-normal text-ink-2">{count}</span>}
              </button>
            ))}
          </div>
        )}
        {view === "holdings" ? (
          <HoldingsView />
        ) : (
          <Suspense fallback={<Skeleton className="h-64 w-full rounded-sm" />}>
            {segment === "records" && (
              <div id="ledger-records" role="tabpanel" aria-labelledby={`subtab-${view}`}>
                {view === "transactions" ? <TransactionsView symbol={search.symbol} /> : <DividendsView />}
              </div>
            )}
            {view === "performance" && <PerformanceView />}
            {view === "allocation" && <AllocationView />}
          </Suspense>
        )}
      </div>
      {!isDesktop && view !== "performance" && <div className="mt-3">{trend}</div>}
      {/* 本週事項：桌面 AI 面板開著時放在面板標題下面（本頁欄位）；面板收著、看對話紀錄、手機時接在內容後面 */}
      {panelSlot ? createPortal(<WeekLine variant="panel" />, panelSlot) : <WeekLine />}
      <SourcesFooter />
    </PageFrame>
  )
}

function BigTotal({ value }: { value: number }) {
  const privacy = usePrefs((s) => s.privacyMode)
  return (
    <p className="hero-figure mt-1 flex items-baseline text-4xl font-medium tracking-[-0.015em] text-ink lg:mt-1.5 lg:text-big lg:tracking-[-0.02em]">
      <span className="mr-1.5 text-lg font-normal tracking-normal text-ink-2 lg:mr-2 lg:text-2xl">NT$</span>
      {privacy ? (
        <Masked className="tracking-[0.2em] text-ink" />
      ) : (
        <NumberFlow value={value} locales="zh-TW" format={{ maximumFractionDigits: 0 }} aria-label={formatMoney(value)} />
      )}
    </p>
  )
}

function Delta({ amount, pct, className }: { amount: number; pct: number | null; className?: string }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const d = direction(amount)
  return (
    // 金額與百分比各自不換行；手機上放不下一行時，百分比整個換到下一行
    <span className={cn("num inline-flex flex-wrap items-baseline gap-x-2 [&>*]:whitespace-nowrap", toneClass(d), className)}>
      {privacy ? <Masked /> : <span>{formatMoney(amount, { signed: true })}</span>}
      {/* 百分比和金額同一個字級；▲▼ 跟著字級（不另外縮小） */}
      <span>
        {directionGlyph(direction(pct))}
        {formatPercent(pct === null ? null : Math.abs(pct), { signed: false, decimals: Math.abs(pct ?? 0) >= 0.1 ? 1 : 2 })}
      </span>
      <span className="sr-only">{d === "up" ? "上漲" : d === "down" ? "下跌" : "持平"}</span>
    </span>
  )
}

/**
 * 主數字（手機與桌面同一套）：標籤一行 → 總資產大字 → 今日、總損益（含股利）。沒有卡片、沒有展開鈕。
 * 桌面（2026-11-19）：今日與總損益疊成兩行放在總資產右邊，今日 32px（「今天賺賠多少」是最常看的）、總損益 18px；
 * 手機：兩行、標籤對齊成一欄，今日 20px。滑過走勢時這裡的數字不變。
 */
function Hero({ summary }: { summary?: PortfolioSummary }) {
  const holdings = useHoldings()
  // 沒有盤中即時報價：總資產旁寫的是收盤價的日期（上市、上櫃日期不同時分開寫）；盤中多半句「盤中不更新」，
  // 收盤價還沒進來時多一句預計幾點更新。「今日」只在每個市場的收盤價都是今天的時候寫。
  // 只有美股有價格時是紐約的交易日（「11/13 收盤（美東）」「11/13」），不套台股的說明
  const close = useLedgerClose()
  if (!summary) return <HeroSkeleton />
  // 手機：dt／dd 直接是格線的格子（display: contents），標籤一欄、數字一欄；桌面：一項一組排成一行。
  // 主欄 52rem 以上（`@container`，和持倉表同一條線）：今日與總損益疊成兩行放在總資產右邊；
  // 比較窄的桌面（1024–1350px 開著 AI 面板）並排會把「今日」擠成直排，所以照舊排在總資產下面一行
  const item = "contents lg:flex lg:items-baseline lg:gap-2.5"
  // 還沒記過任何東西（沒有市值、沒有成本、也沒有已實現的損益）：今日與總損益都是 NT$0 0.00%，只是一排雜訊，不放
  const blank = summary.market_value === 0 && summary.cost_basis === 0 && summary.total_pnl === 0
  return (
    <div className="@container min-w-0 max-lg:mt-1.5">
      <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-ink-2">
        <b className="print-label text-base">總資產</b>
        <span className="num whitespace-nowrap">{close.label}</span>
        {summary.is_demo && <DemoTag title={demoTitle(holdings.data)} />}
        {/* 在等的收盤價預計幾點進來（只在需要時）：桌面接在日期後面（「11/12 收盤・今天的預計下午 2:00–2:30 更新」），
            手機自己一行，日期那一行不會被擠到換行 */}
        {close.note && (
          <span className="num whitespace-nowrap max-sm:basis-full sm:-ml-2.5">
            <span aria-hidden className="max-sm:hidden">
              ・
            </span>
            {close.note}
          </span>
        )}
      </p>
      <div className="lg:@min-[52rem]:flex lg:@min-[52rem]:items-end lg:@min-[52rem]:gap-x-14">
      <BigTotal value={summary.market_value} />
      {!blank && (
      <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 lg:mt-3 lg:flex lg:flex-wrap lg:gap-x-12 lg:gap-y-2 lg:@min-[52rem]:mt-0 lg:@min-[52rem]:mb-1.5 lg:@min-[52rem]:flex-col lg:@min-[52rem]:gap-y-1">
        <div className={item}>
          <dt className="num print-label text-sm">{close.day}</dt>
          <dd className="text-xl font-medium lg:text-2xl lg:@min-[52rem]:text-3xl">
            <Delta amount={summary.day_change} pct={summary.day_change_pct} />
          </dd>
        </div>
        <div className={item}>
          <dt className="print-label text-sm">總損益（含股利）</dt>
          <dd className="text-lg font-medium">
            <Delta amount={summary.total_pnl} pct={summary.total_return_pct} />
          </dd>
        </div>
      </dl>
      )}
      </div>
    </div>
  )
}

function demoTitle(holdings?: { name: string; is_demo: boolean }[]) {
  const names = (holdings ?? []).filter((h) => h.is_demo).map((h) => h.name)
  return api.kind === "mock" ? "目前沒有連到伺服器，所有數字都是示範資料" : names.length ? `含示範報價：${names.join("、")}` : "含示範資料"
}

function HeroSkeleton() {
  return (
    <div aria-busy="true" aria-label="總資產載入中" className="flex flex-col gap-3 pt-2">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-14 w-80 max-w-full" />
      <Skeleton className="h-5 w-96 max-w-full" />
    </div>
  )
}

/**
 * 本週 N 件事：除息、股利入帳、定期定額（規則計算，不是 AI 簡報）。
 * 一行格線列（上下各一條格線）：聯絡簿的日期格 → 最近的一件事 →「本週 N 件事 →」。
 * 連到股利分段；它不是導覽，不標 aria-current（PlainLink）。
 * `panel`：桌面 AI 面板標題下面的本頁欄位（2026-11-19 選 B，首屏給持倉）——面板窄，兩行：事情一行、「本週 N 件事 →」一行，
 * 左右和面板的內距對齊、只有下緣一條格線（上緣是面板標題的線）。
 */
function WeekLine({ variant = "inline" }: { variant?: "inline" | "panel" }) {
  const upcoming = useUpcoming(7)
  const privacy = usePrefs((s) => s.privacyMode)
  const items = upcoming.data ?? []
  const panel = variant === "panel"
  if (upcoming.isLoading) return <Skeleton className={panel ? "h-[60px] w-full rounded-none" : "mt-5 h-[52px] w-full rounded-none lg:mt-6"} />
  // 讀不到就不放這一行（不寫成「接下來 7 天沒有…」騙人；2026-11-14 review）
  if (upcoming.isError) return null
  const first = items[0]
  const label = first ? `本週 ${items.length} 件事，查看全部` : "接下來 7 天沒有除息或入帳，查看股利"
  if (panel)
    return (
      <PlainLink
        to="/"
        search={{ view: "dividends" }}
        className="grid min-h-[60px] grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 border-b border-rule py-2 pr-7 pl-7 text-base text-ink hover:bg-hov active:bg-hov xl:pl-8"
        aria-label={label}
      >
        {first ? (
          <>
            <DateCell date={first.date} pad="-my-2 py-2" className="w-24" />
            <span className="min-w-0">
              <span className="block truncate" title={upcomingText(first, privacy)}>
                {upcomingText(first, privacy)}
              </span>
              <span className="block text-sm text-ink-2">本週 {items.length} 件事 →</span>
            </span>
          </>
        ) : (
          <span className="col-span-2">
            <span className="block text-ink-2">接下來 7 天沒有除息、入帳或定期定額</span>
            <span className="block text-sm text-ink-2">股利 →</span>
          </span>
        )}
      </PlainLink>
    )
  return (
    <PlainLink
      to="/"
      search={{ view: "dividends" }}
      className="mt-5 grid min-h-[52px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 border-y border-rule py-2 text-base text-ink hover:bg-hov active:bg-hov lg:mt-6"
      aria-label={label}
    >
      {first ? (
        <>
          <DateCell date={first.date} pad="-my-2 py-2" className="w-[3.25rem] lg:w-24" />
          <span className="min-w-0 truncate">
            <span className="max-lg:hidden">{upcomingText(first, privacy)}</span>
            <span className="lg:hidden">{upcomingShort(first)}</span>
          </span>
          <span className="text-sm whitespace-nowrap text-ink-2">本週 {items.length} 件事 →</span>
        </>
      ) : (
        <>
          <span className="col-span-2 text-ink-2">接下來 7 天沒有除息、入帳或定期定額</span>
          <span className="text-sm whitespace-nowrap text-ink-2">股利 →</span>
        </>
      )}
    </PlainLink>
  )
}
