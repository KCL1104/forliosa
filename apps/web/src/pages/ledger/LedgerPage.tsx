import NumberFlow from "@number-flow/react"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"
import { lazy, Suspense, useEffect } from "react"
import { createPortal } from "react-dom"
import { api } from "@/api"
import { useHoldings, usePerformance, useSummary, useUpcoming } from "@/api/queries"
import { useGroups } from "@/api/sharing-queries"
import type { PortfolioSummary } from "@/api/types"
import { usePanelSlot } from "@/ai/panel-slot"
import { useAskAi } from "@/ai/use-ask"
import { latestPendingDraftId, usePendingCount } from "@/ai/store"
import { Masked } from "@/components/finance"
import { DateCell } from "@/components/date-cell"
import { DemoTag } from "@/components/section"
import { Segmented } from "@/components/segmented"
import { ShareCopyButton, ShareSlip } from "@/components/share-card"
import { useShareCard } from "@/components/use-share-card"
import { ErrorState } from "@/components/states"
import { Tray } from "@/components/tray"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, directionGlyph, formatMoney, formatPercent, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import type { LedgerSearch, LedgerView } from "@/router"
import { CustomizeButton } from "./CustomizeButton"
import { HoldingsView } from "./HoldingsView"
import { useLedgerCounts } from "./use-ledger-counts"
import { useIsDesktop } from "@/hooks/use-media-query"
import { SourcesFooter } from "@/components/data-notes"
import { SourcesProvider } from "@/components/sources"
import { upcomingShort, upcomingText } from "@/lib/ledger-display"
import { useReadOnly } from "@/api/view-as"
import { PlainLink } from "@/app/links"
import { useUi } from "@/app/ui-store"
import { useCanImport } from "@/pages/transactions/import/access"
import { PageFrame } from "@/app/PageFrame"
import { usePageTitle } from "@/app/page-title"
import { HeroTrend } from "./HeroTrend"
import { useHeroTrendShown } from "./use-trend-range"
import { useLedgerPrefs } from "./ledger-prefs"
import { TodayPnl } from "./TodayPnl"
import { useHeroClose } from "./use-hero-close"
import { WatchList } from "./WatchList"

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
const SEGMENT_TITLE: Record<Segment, string> = { holdings: "持倉", records: "紀錄", performance: "績效", allocation: "配置" }
const segmentOf = (view: LedgerView): Segment => (view === "transactions" || view === "dividends" ? "records" : view)
const viewOf = (segment: Segment): LedgerView => (segment === "records" ? "transactions" : segment)

/**
 * 帳本（首頁）。內頁重新設計（產品負責人 2026-11-21 選方向 C「圓桌」的結構，不要它的旁白）：一組一組放在托盤裡，
 * 頁面只有標籤和數字。由上到下：
 * 1. 總資產（印好的「總資產」＋「收盤價・11/12（四）」、總資產大字、今日、總損益）；桌面接著總資產走勢，同一盤
 * 2. 分段（持倉・紀錄・績效・配置）與內容；持倉下面直接是已出清（同一盤）
 * 3. 手機：總資產走勢自己一盤，在內容後面（首屏給持倉，2026-11-19）；績效分段時在分段列與內容之間
 * 4. 持倉分段才有：今日損益（每一檔的中線橫條，在持倉後面，不把持倉擠出第一屏）→ 分享卡（有加入群組時）＋觀察清單
 * 5. 本週事項：桌面 AI 面板開著時放在面板標題下面（`ai/panel-slot.ts`）；其他時候是最後一盤
 * 首屏給持倉（2026-11-19）照舊：1440×900 至少 5 列、1280×800 至少 3 列、iPhone 15 至少 3 列。
 */
export function LedgerPage() {
  const search = useSearch({ from: "/" }) as LedgerSearch
  const navigate = useNavigate()
  const view: LedgerView = search.view ?? "holdings"
  const segment = segmentOf(view)
  usePageTitle("帳本")
  const summary = useSummary()
  const holdings = useHoldings()
  // 總資產走勢的序列（「全部」、不帶基準，和 HeroTrend 同一個查詢）和主數字同時開始讀，兩個都回來才一起換掉主數字的骨架：
  // 走勢一出現就是最後的大小（一張圖、或歷史短時的一行原因），不會先放一塊整張圖大的骨架再收成一行、把下面整片往上拉
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const trendPerf = usePerformance("ALL")
  const heroReady = !!summary.data && (!showTrend || !!trendPerf.data || trendPerf.isError)
  const trendShown = useHeroTrendShown() && heroReady
  const counts = useLedgerCounts()
  const pending = usePendingCount()
  const ask = useAskAi()
  // 查看別人的資產（唯讀）：沒有待簽名的草稿（那是自己的 AI），也沒有分享卡與觀察清單（那是自己的）
  const readOnly = useReadOnly()
  // 空的帳本（持倉這一段、一檔都沒有）：空狀態本身就有「記第一筆／匯入」，工具列的匯入、記一筆、自訂先不放（動作不重複）
  const emptyHoldings = view === "holdings" && counts.holdings === 0
  const canImport = useCanImport()
  const openImport = useUi((s) => s.openImport)
  const isDesktop = useIsDesktop()
  // 面板的本頁欄位只在桌面、面板開著、不是看對話紀錄時存在（`ai/panel-slot.ts`）
  const panelSlot = usePanelSlot((s) => s.el)
  // 分享卡：和群組頁同一張；帳本上只在有加入群組、帳本不是空的時候放
  const groups = useGroups(!readOnly)
  const blank = !!summary.data && isBlank(summary.data)
  const shareShown = !readOnly && !blank && (groups.data?.length ?? 0) > 0
  const holdingsTab = segment === "holdings"

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

  // 哪幾盤放出來：手機的總資產走勢自己一盤；今日損益、分享卡、觀察清單只在持倉分段
  const phoneTrend = !isDesktop && view !== "performance" && trendShown
  const todayShown = holdingsTab && (holdings.data ?? []).some((h) => h.price !== null)
  const lowerShown = holdingsTab && !readOnly

  const toolbar = (
    <div className="flex w-full min-w-0 items-center gap-4">
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
          onClick={() => ask.showDraft(latestPendingDraftId())}
          className="press hidden h-8 items-center rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3 text-sm font-medium text-ai hover:border-ai lg:inline-flex"
          aria-label={`待簽名 ${pending} 筆：到 AI 面板的草稿確認`}
        >
          待簽名 {pending} 筆
        </button>
      )}
      {/* 手動記一筆：直接開輸入框（用一句話記的入口在 AI 面板）。手機放在分段旁邊的「＋」。
          匯入（2026-11-17）：開了匯入的帳號在記一筆左邊多一顆「匯入」，先選匯入庫存或對帳單 */}
      {!readOnly && !emptyHoldings && (
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
            {/* 400px 以下放不下四段＋匯入＋「＋」（分段會斷成直排），匯入改從記一筆裡的「匯入庫存或對帳單」進去 */}
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
      {view === "holdings" && !emptyHoldings && <CustomizeButton className={cn("max-lg:hidden", readOnly && "ml-auto")} />}
    </div>
  )

  return (
    // 資產組成原型：績效分段「贏過幾成的台股基金」把基金淨值的來源登記到頁尾（沒有登記任何來源時頁尾和以前一樣是一個連結）
    <SourcesProvider>
      {/* 托盤自己有內距：版心頂端和托盤之間的距離一樣（手機 12px、桌面 16px），首屏留給持倉 */}
      <PageFrame className="lg:pt-4">
        <h1 className="sr-only">帳本</h1>
        <div className="@container flex flex-col gap-tray-gap">
          {summary.isError ? (
            <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
          ) : (
            // 第一行是印好的「總資產」：標題只給螢幕閱讀器
            <Tray title="總資產" titleHidden>
              <Hero summary={heroReady ? summary.data : undefined} />
              {/* 總資產走勢（產品負責人 2026-11-17 選方案 B；「自訂」可以整塊關掉）：桌面在主數字正下方、同一盤 */}
              {isDesktop && heroReady && <HeroTrend view={view} className="lg:mt-4" />}
            </Tray>
          )}

          {/* 分段與內容：分頁列在標題列的動作位置、撐滿整列（標題只給螢幕閱讀器，就是現在這一段的名稱） */}
          <Tray title={SEGMENT_TITLE[segment]} titleHidden action={toolbar} className="[&>header>div]:ml-0 [&>header>div]:flex-1">
            {pending > 0 && !readOnly && (
              <button
                type="button"
                onClick={() => ask.showDraft(latestPendingDraftId())}
                className="press mb-3 flex h-11 w-full items-center justify-between rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3.5 text-base font-medium text-ai lg:hidden"
              >
                待簽名 {pending} 筆
                <span aria-hidden className="font-normal">
                  →
                </span>
              </button>
            )}
            {/* 手機的績效分段：走勢的區間就是績效的區間，放在分段列與內容之間 */}
            {!isDesktop && view === "performance" && heroReady && <HeroTrend view={view} className="mt-0 mb-5" />}
            <div id="ledger-view" role="tabpanel" aria-labelledby={`tab-${segment}`}>
              {segment === "records" && (
                // 紀錄裡的兩個小分頁：交易（買進、賣出與其他）、股利（台股的現金股利與配股是系統在除息日自動記的）
                <div role="tablist" aria-label="紀錄的內容" className="mb-4 flex gap-5 border-b border-rule">
                  {(
                    [
                      ["transactions", "交易", counts.transactions],
                      ["dividends", "股利", counts.dividends],
                    ] as const
                  ).map(([v, label, count]) => (
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
          </Tray>

          {/* 手機：總資產走勢自己一盤，在內容後面（首屏給持倉，2026-11-19） */}
          {phoneTrend && (
            <Tray title="總資產走勢">
              <HeroTrend view={view} titled className="mt-0" />
            </Tray>
          )}

          {todayShown && <TodayPnl />}
          {lowerShown && (
            // 寬的時候分享卡與觀察清單並排（分享卡寬一點：三格百分比要放得下「總報酬（含股利）」），同一列等高
            <div className={cn("grid gap-tray-gap", shareShown && "@min-[56rem]:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]")}>
              {shareShown && <ShareTray />}
              <WatchList />
            </div>
          )}
          {/* 本週事項：桌面 AI 面板開著時放在面板標題下面（本頁欄位）；面板收著、看對話紀錄、手機時是最後一盤 */}
          {!panelSlot && <WeekLine />}
        </div>
        {panelSlot && createPortal(<WeekLine variant="panel" />, panelSlot)}
        <SourcesFooter />
      </PageFrame>
    </SourcesProvider>
  )
}

/** 還沒記過任何東西（沒有市值、沒有成本、也沒有已實現的損益） */
const isBlank = (s: PortfolioSummary) => s.market_value === 0 && s.cost_basis === 0 && s.total_pnl === 0

/** 分享卡（和群組頁同一張，`components/share-card.tsx`）：只有百分比；「複製分享文字」在標題列 */
function ShareTray() {
  const data = useShareCard()
  return (
    <Tray title="分享卡" action={<ShareCopyButton data={data} size="sm" />} className="h-full">
      <ShareSlip data={data} />
    </Tray>
  )
}

function BigTotal({ value }: { value: number }) {
  const privacy = usePrefs((s) => s.privacyMode)
  // 幾個字（數字與千分位，負數多一個號）：上千億的帳本在 320px 的手機上也不會撐出畫面——字放不下時照這一盤的寬度縮小
  // （一個字約 0.6em；手機最大 36px、桌面 64px，扣掉前面的「NT$」）
  const chars = formatMoney(value, { bare: true }).length
  return (
    // 數字捲動的遮罩在數字上下各留 0.25em 的空白（NumberFlow 的 --number-flow-mask-height），負的上下邊距抵掉：
    // 數字的位置和大小不變，只是那兩塊看不見的空白不再把持倉往下推（桌面 32px、手機 18px）
    <p
      style={{ "--hero-chars": chars } as React.CSSProperties}
      className="hero-figure mt-1 flex items-baseline text-[length:min(2.25rem,calc((100cqi_-_2.75rem)/(var(--hero-chars)*0.6)))] leading-[1.1] font-medium tracking-[-0.015em] text-ink lg:mt-1.5 lg:text-[length:min(4rem,calc((100cqi_-_3.5rem)/(var(--hero-chars)*0.6)))] lg:leading-[1.05] lg:tracking-[-0.02em] [&>number-flow-react]:-my-[0.25em]"
    >
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
 * 主數字（手機與桌面同一套）：標籤一行（印好的「總資產」＋「收盤價・11/12（四）」）→ 總資產大字 → 今日、總損益（含股利）。
 * 沒有卡片、沒有展開鈕。滑過走勢時這裡的數字不變。
 * - 桌面、這一盤 40rem 以上（1280px 開著 AI 面板也是）：今日與總損益疊成兩行放在總資產右邊——今日 24px，52rem 以上 32px
 *   （「今天賺賠多少」是最常看的），總損益 18px；數字太長放不下時整組換到總資產下面（flex-wrap），不會擠成直排。
 * - 比較窄的桌面（1024px 開著 AI 面板）：照舊排在總資產下面一行，今日 24px。
 * - 手機：兩行、標籤對齊成一欄，今日 20px。
 */
function Hero({ summary }: { summary?: PortfolioSummary }) {
  const holdings = useHoldings()
  // 沒有盤中即時報價：總資產旁寫的是收盤價的日期（上市、上櫃日期不同時分開寫）；盤中多半句「盤中不更新」，
  // 收盤價還沒進來時多一句預計幾點更新。「今日」只在每個市場的收盤價都是今天的時候寫。
  // 只有美股有價格時是紐約的交易日（「收盤價・11/13（美東）」「11/13」），不套台股的說明
  const close = useHeroClose()
  if (!summary) return <HeroSkeleton />
  // 手機：dt／dd 直接是格線的格子（display: contents），標籤一欄、數字一欄；桌面：一項一組排成一行。
  const item = "contents lg:flex lg:items-baseline lg:gap-2.5"
  // 還沒記過任何東西：今日與總損益都是 NT$0 0.00%，只是一排雜訊，不放
  const blank = isBlank(summary)
  return (
    <div className="@container min-w-0">
      <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-ink-2">
        {/* 托盤的標題（螢幕閱讀器）已經是「總資產」：這裡印出來的字不再念一次 */}
        <b aria-hidden className="print-label text-base">
          總資產
        </b>
        {/* 只在「・」後面換行（keep-all：中文字之間不斷開；市場名稱和日期之間是不換行的空白），320px 也不撐出畫面 */}
        {close.label && <span className="num [word-break:keep-all]">{close.label.replaceAll(" ", " ")}</span>}
        {summary.is_demo && <DemoTag title={demoTitle(holdings.data)} />}
        {/* 在等的收盤價預計幾點進來（只在需要時）：桌面接在日期後面（「收盤價・11/12（四）・今天的預計下午 2:00–2:30 更新」），
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
      <div className="lg:@min-[40rem]:flex lg:@min-[40rem]:flex-wrap lg:@min-[40rem]:items-end lg:@min-[40rem]:gap-x-8 lg:@min-[52rem]:gap-x-14">
        <BigTotal value={summary.market_value} />
        {!blank && (
          // 20rem 以下（320px 的手機，托盤裡 248px）：標籤在上、數字在下，金額太大時也不撐出畫面
          <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 @max-[20rem]:grid-cols-1 @max-[20rem]:gap-y-0 lg:mt-3 lg:flex lg:flex-wrap lg:gap-x-12 lg:gap-y-2 lg:@min-[40rem]:mt-0 lg:@min-[40rem]:flex-col lg:@min-[40rem]:gap-y-1">
            <div className={item}>
              <dt className="num print-label text-sm whitespace-nowrap">{close.day}</dt>
              {/* 手機：托盤裡只剩 321px（iPhone 15），20px 會讓金額和百分比斷成兩行——22rem 以下 18px */}
              <dd className="text-lg font-medium max-lg:@min-[22rem]:text-xl lg:text-2xl lg:@min-[52rem]:text-3xl">
                <Delta amount={summary.day_change} pct={summary.day_change_pct} />
              </dd>
            </div>
            <div className={item}>
              <dt className="print-label text-sm whitespace-nowrap">總損益（含股利）</dt>
              {/* 手機 22rem 以下、桌面 40–52rem 並排時（1280px 開著 AI 面板）16px，其他時候 18px */}
              <dd className="text-base font-medium max-lg:@min-[22rem]:text-lg lg:text-lg lg:@min-[40rem]:text-base lg:@min-[52rem]:text-lg">
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
    <div aria-busy="true" aria-label="總資產載入中" className="flex flex-col gap-3">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-14 w-80 max-w-full" />
      <Skeleton className="h-5 w-96 max-w-full" />
    </div>
  )
}

/**
 * 本週 N 件事：除息、股利入帳、定期定額（規則計算，不是 AI 簡報）。一列，不是對話：
 * 聯絡簿的日期格 → 最近的一件事 →「本週 N 件事 →」。連到股利分段；它不是導覽，不標 aria-current（PlainLink）。
 * 事情的字不截斷：放不下就換行（內頁重新設計 2026-11-21：名稱不截斷）。
 * - `panel`：桌面 AI 面板標題下面的本頁欄位（2026-11-19 選 B，首屏給持倉）——面板窄，兩行：事情一行、「本週 N 件事 →」一行，
 *   左右和面板的內距對齊、只有下緣一條格線（上緣是面板標題的線）。
 * - `inline`：面板收著、看對話紀錄、手機時，帳本的最後一盤（標題「本週事項」只給螢幕閱讀器：那一列自己就寫了「本週 N 件事」）。
 */
function WeekLine({ variant = "inline" }: { variant?: "inline" | "panel" }) {
  const upcoming = useUpcoming(7)
  const privacy = usePrefs((s) => s.privacyMode)
  const items = upcoming.data ?? []
  const panel = variant === "panel"
  if (upcoming.isLoading) return <Skeleton className={panel ? "h-[60px] w-full rounded-none" : "h-[84px] w-full rounded-tray"} />
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
              <span className="block [overflow-wrap:anywhere]">{upcomingText(first, privacy)}</span>
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
    <Tray title="本週事項" titleHidden>
      <PlainLink
        to="/"
        search={{ view: "dividends" }}
        className="-my-2 grid min-h-[52px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 rounded-xs py-2 text-base text-ink hover:bg-hov active:bg-hov"
        aria-label={label}
      >
        {first ? (
          <>
            <DateCell date={first.date} pad="-my-2 py-2" className="w-[3.25rem] lg:w-24" />
            <span className="min-w-0 [overflow-wrap:anywhere]">
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
    </Tray>
  )
}
