import NumberFlow from "@number-flow/react"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { lazy, Suspense, useEffect } from "react"
import { api } from "@/api"
import { useHoldings, usePerformance, useSummary, useUpcoming } from "@/api/queries"
import type { PortfolioSummary } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { useAi, usePendingCount } from "@/ai/store"
import { Masked } from "@/components/finance"
import { DateCell } from "@/components/date-cell"
import { DemoTag } from "@/components/section"
import { Segmented } from "@/components/segmented"
import { Sparkline } from "@/components/sparkline"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, directionGlyph, formatMoney, formatPercent, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import type { LedgerSearch, LedgerView } from "@/router"
import { CustomizeButton } from "./CustomizeButton"
import { HoldingsView } from "./HoldingsView"
import { useLedgerPrefs } from "./ledger-prefs"
import { useLedgerCounts } from "./use-ledger-counts"
import { ledgerAsOf } from "@/lib/as-of"
import { useClose } from "@/hooks/use-close"
import { SourcesFooter } from "@/components/data-notes"
import { upcomingShort, upcomingText } from "@/lib/ledger-display"
import { useReadOnly } from "@/api/view-as"
import { PlainLink } from "@/app/links"
import { PageFrame } from "@/app/PageFrame"
import { trendMissingReason } from "./trend-reason"

const TransactionsView = lazy(() => import("./TransactionsView").then((m) => ({ default: m.TransactionsView })))
const DividendsView = lazy(() => import("./DividendsView").then((m) => ({ default: m.DividendsView })))
const PerformanceView = lazy(() => import("./PerformanceView").then((m) => ({ default: m.PerformanceView })))

/** 分段的順序，也是數字鍵 1–4 的對應（和 router 的 LEDGER_VIEWS 相同；不從 router 匯入值，避免循環匯入） */
const VIEW_KEYS: readonly LedgerView[] = ["holdings", "transactions", "dividends", "performance"]

/** 帳本（首頁）：主數字 → 本週事項 → 分段（持倉・交易・股利・績效）→ 清單 */
export function LedgerPage() {
  const search = useSearch({ from: "/" }) as LedgerSearch
  const navigate = useNavigate()
  const view: LedgerView = search.view ?? "holdings"
  const summary = useSummary()
  const counts = useLedgerCounts()
  const pending = usePendingCount()
  const ask = useAskAi()
  // 查看別人的資產（唯讀）：沒有待簽名的草稿（那是自己的 AI）
  const readOnly = useReadOnly()

  const setView = (v: LedgerView) => void navigate({ to: "/", search: (s: LedgerSearch) => ({ ...s, view: v === "holdings" ? undefined : v, symbol: v === "transactions" ? s.symbol : undefined }), replace: true })

  // 數字鍵 1–4 切換分段（持倉・交易・股利・績效）：焦點在輸入框、選單、對話框裡，或同時按著修飾鍵時不動作
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return
      const next = VIEW_KEYS[["1", "2", "3", "4"].indexOf(e.key)]
      if (!next) return
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
        <Hero summary={summary.data} view={view} />
      )}
      <WeekLine />

      <div className="mt-5 flex items-center gap-4 lg:mt-11">
        <Segmented
          label="帳本內容"
          value={view}
          onChange={setView}
          controls="ledger-view"
          className="max-lg:flex-1"
          options={[
            { value: "holdings", label: "持倉", count: counts.holdings, shortcut: "1" },
            { value: "transactions", label: "交易", count: counts.transactions, shortcut: "2" },
            { value: "dividends", label: "股利", count: counts.dividends, shortcut: "3" },
            { value: "performance", label: "績效", shortcut: "4" },
          ]}
        />
        {pending > 0 && !readOnly && (
          <button
            type="button"
            onClick={() => {
              const id = Object.values(useAi.getState().drafts).find((d) => d.status === "pending")?.id ?? null
              ask.showDraft(id)
            }}
            className="press hidden h-8 items-center rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3 text-sm font-medium text-ai hover:border-ai lg:inline-flex"
            aria-label={`待簽名 ${pending} 筆：到 AI 面板的草稿確認`}
          >
            待簽名 {pending} 筆
          </button>
        )}
        {view === "holdings" && <CustomizeButton className="ml-auto max-lg:hidden" />}
      </div>
      {pending > 0 && !readOnly && (
        <button
          type="button"
          onClick={() => ask.showDraft(Object.values(useAi.getState().drafts).find((d) => d.status === "pending")?.id ?? null)}
          className="press mt-3 flex h-11 w-full items-center justify-between rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3.5 text-base font-medium text-ai lg:hidden"
        >
          待簽名 {pending} 筆
          <span aria-hidden className="font-normal">→</span>
        </button>
      )}

      <div id="ledger-view" role="tabpanel" aria-labelledby={`tab-${view}`} className="mt-5 lg:mt-5">
        {view === "holdings" ? (
          <HoldingsView />
        ) : (
          <Suspense fallback={<Skeleton className="h-64 w-full rounded-sm" />}>
            {view === "transactions" && <TransactionsView symbol={search.symbol} />}
            {view === "dividends" && <DividendsView />}
            {view === "performance" && <PerformanceView />}
          </Suspense>
        )}
      </div>
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

function useTrend() {
  const perf = usePerformance("1M")
  const values = (perf.data?.series ?? []).map((p) => p.market_value)
  return { values, loading: perf.isLoading, isError: perf.isError, notes: perf.data?.notes ?? [] }
}

/** 走勢畫不出來、而且後端說了原因時：右半邊一行說明，連到績效（那裡有完整說明與「只看新台幣帳戶」）。 */
function TrendMissing({ reason }: { reason: string }) {
  return (
    <PlainLink
      to="/"
      search={{ view: "performance" }}
      className="mb-1.5 shrink-0 text-right text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink max-lg:hidden"
    >
      近 1 個月走勢：{reason}
    </PlainLink>
  )
}

/**
 * 主數字（手機與桌面同一套）：標籤一行 → 總資產大字 → 今日、總損益（含股利）。沒有卡片、沒有展開鈕。
 * 桌面：今日與總損益排成一行，右邊是近 1 個月走勢（畫不出來時是一行原因）。
 * 手機：兩行、標籤對齊成一欄；有走勢時是第三行。
 */
function Hero({ summary, view }: { summary?: PortfolioSummary; view: LedgerView }) {
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const holdings = useHoldings()
  const trend = useTrend()
  const privacy = usePrefs((s) => s.privacyMode)
  // 沒有盤中即時報價：總資產旁寫的是收盤價的日期（盤中、今天的還沒公布時多半句說明），「今日」只在收盤價是今天的時候寫
  const close = useClose(summary?.as_of)
  if (!summary) return <HeroSkeleton />
  const up = (trend.values.at(-1) ?? 0) >= (trend.values[0] ?? 0)
  const missingReason = trendMissingReason(trend.notes)
  const hasTrend = showTrend && trend.values.length > 1
  const trendLabel = `近 1 個月總資產走勢：${up ? "上升" : "下降"}`
  // 手機：dt／dd 直接是格線的格子（display: contents），標籤一欄、數字一欄；桌面：一項一組排成一行
  const item = "contents lg:flex lg:items-baseline lg:gap-2.5"
  return (
    <div className="flex items-end justify-between gap-8 max-lg:mt-1.5">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-ink-2">
          <b className="text-base font-medium text-ink">總資產</b>
          <span className="num whitespace-nowrap">{ledgerAsOf(close.state, summary.as_of)}</span>
          {summary.is_demo && <DemoTag title={demoTitle(holdings.data)} />}
        </p>
        <BigTotal value={summary.market_value} />
        <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 lg:mt-3.5 lg:flex lg:flex-wrap lg:gap-x-12 lg:gap-y-2">
          <div className={item}>
            <dt className="num text-sm text-ink-2">{close.day}</dt>
            <dd className="text-lg font-medium">
              <Delta amount={summary.day_change} pct={summary.day_change_pct} />
            </dd>
          </div>
          <div className={item}>
            <dt className="text-sm text-ink-2">總損益（含股利）</dt>
            <dd className="text-lg font-medium">
              <Delta amount={summary.total_pnl} pct={summary.total_return_pct} />
            </dd>
          </div>
          {hasTrend && !privacy && (
            <div className="contents lg:hidden">
              <dt className="text-sm text-ink-2">近 1 個月</dt>
              <dd className="self-center">
                <Sparkline values={trend.values} baseline={trend.values[0]} width={120} height={28} tone="ink" dot label={trendLabel} />
              </dd>
            </div>
          )}
        </dl>
      </div>
      {/* 走勢畫不出來的原因連到績效；已經在績效分段時不重複（那裡有完整的說明） */}
      {showTrend && view !== "performance" && trend.values.length < 2 && !trend.loading && !trend.isError && missingReason && <TrendMissing reason={missingReason} />}
      {hasTrend && (
        <figure className="mb-1.5 text-right max-lg:hidden" aria-label={trendLabel}>
          {privacy ? (
            <div className="grid h-10 w-[168px] place-items-center text-sm text-ink-2">走勢已隱藏</div>
          ) : (
            <Sparkline values={trend.values} baseline={trend.values[0]} width={168} height={40} tone="ink" dot label={trendLabel} />
          )}
          <figcaption className="mt-1.5 text-sm text-ink-2">近 1 個月</figcaption>
        </figure>
      )}
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
 */
function WeekLine() {
  const upcoming = useUpcoming(7)
  const privacy = usePrefs((s) => s.privacyMode)
  const items = upcoming.data ?? []
  if (upcoming.isLoading) return <Skeleton className="mt-5 h-[52px] w-full rounded-none lg:mt-9" />
  const first = items[0]
  return (
    <PlainLink
      to="/"
      search={{ view: "dividends" }}
      className="mt-5 grid min-h-[52px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 border-y border-rule py-2 text-base text-ink hover:bg-hov active:bg-hov lg:mt-9"
      aria-label={first ? `本週 ${items.length} 件事，查看全部` : "接下來 7 天沒有除息或入帳，查看股利"}
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
