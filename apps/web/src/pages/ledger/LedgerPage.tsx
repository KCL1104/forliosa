import NumberFlow from "@number-flow/react"
import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { CalendarDaysIcon, ChevronDownIcon, ChevronRightIcon, PenLineIcon } from "lucide-react"
import { lazy, Suspense, useState } from "react"
import { api } from "@/api"
import { useHoldings, usePerformance, useSummary, useUpcoming } from "@/api/queries"
import type { PortfolioSummary } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { useAi, usePendingCount } from "@/ai/store"
import { Masked } from "@/components/finance"
import { DemoTag } from "@/components/section"
import { Segmented } from "@/components/segmented"
import { Sparkline } from "@/components/sparkline"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsDesktop } from "@/hooks/use-media-query"
import { direction, directionGlyph, formatDateShort, formatMoney, formatPercent, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import type { LedgerSearch, LedgerView } from "@/router"
import { CustomizeButton } from "./CustomizeButton"
import { HoldingsView } from "./HoldingsView"
import { useLedgerPrefs } from "./ledger-prefs"
import { useLedgerCounts } from "./use-ledger-counts"
import { asOfLabel } from "@/lib/as-of"
import { SourcesFooter } from "@/components/data-notes"
import { upcomingShort, upcomingText } from "@/lib/ledger-display"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { trendMissingReason } from "./trend-reason"

const TransactionsView = lazy(() => import("./TransactionsView").then((m) => ({ default: m.TransactionsView })))
const DividendsView = lazy(() => import("./DividendsView").then((m) => ({ default: m.DividendsView })))
const PerformanceView = lazy(() => import("./PerformanceView").then((m) => ({ default: m.PerformanceView })))

/** 帳本（首頁）：主數字 → 本週事項 → 分段（持倉・交易・股利・績效）→ 清單 */
export function LedgerPage() {
  const search = useSearch({ from: "/" }) as LedgerSearch
  const navigate = useNavigate()
  const view: LedgerView = search.view ?? "holdings"
  const summary = useSummary()
  const counts = useLedgerCounts()
  const pending = usePendingCount()
  const ask = useAskAi()
  const isDesktop = useIsDesktop()
  // 查看別人的資產（唯讀）：沒有待簽名的草稿（那是自己的 AI）
  const readOnly = useReadOnly()

  const setView = (v: LedgerView) => void navigate({ to: "/", search: (s: LedgerSearch) => ({ ...s, view: v === "holdings" ? undefined : v, symbol: v === "transactions" ? s.symbol : undefined }), replace: true })

  return (
    <PageFrame>
      <h1 className="sr-only">帳本</h1>
      {summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : isDesktop ? (
        <HeroDesktop summary={summary.data} />
      ) : (
        <HeroMobile summary={summary.data} />
      )}
      <WeekLine />

      <div className="mt-3.5 flex items-center gap-4 lg:mt-11">
        <Segmented
          label="帳本內容"
          value={view}
          onChange={setView}
          controls="ledger-view"
          className="max-lg:flex-1"
          options={[
            { value: "holdings", label: "持倉", count: counts.holdings },
            { value: "transactions", label: "交易", count: counts.transactions },
            { value: "dividends", label: "股利", count: counts.dividends },
            { value: "performance", label: "績效" },
          ]}
        />
        {pending > 0 && !readOnly && (
          <button
            type="button"
            onClick={() => {
              const id = Object.values(useAi.getState().drafts).find((d) => d.status === "pending")?.id ?? null
              ask.showDraft(id)
            }}
            className="press hidden h-8 items-center gap-1.5 rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3 text-sm font-medium text-ai hover:border-ai lg:inline-flex"
            aria-label={`待簽名 ${pending} 筆：到 AI 面板的草稿確認`}
          >
            <PenLineIcon aria-hidden className="size-[15px]" />
            待簽名 {pending} 筆
          </button>
        )}
        {view === "holdings" && <CustomizeButton className="ml-auto max-lg:hidden" />}
      </div>
      {pending > 0 && !readOnly && (
        <button
          type="button"
          onClick={() => ask.showDraft(Object.values(useAi.getState().drafts).find((d) => d.status === "pending")?.id ?? null)}
          className="press mt-3 flex h-11 w-full items-center gap-2 rounded-sm border border-dashed border-ai-rule bg-ai-wash px-3.5 text-base font-medium text-ai lg:hidden"
        >
          <PenLineIcon aria-hidden className="size-4" />
          待簽名 {pending} 筆
          <ChevronRightIcon aria-hidden className="ml-auto size-4" />
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

function BigTotal({ value, size }: { value: number; size: "desktop" | "mobile" }) {
  const privacy = usePrefs((s) => s.privacyMode)
  return (
    <p className={cn("hero-figure flex items-baseline font-medium text-ink", size === "desktop" ? "mt-1.5 text-big tracking-[-0.02em]" : "mt-1.5 text-4xl tracking-[-0.015em]")}>
      <span className={cn("font-normal tracking-normal text-ink-2", size === "desktop" ? "mr-2 text-2xl" : "mr-1 text-lg")}>NT$</span>
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
    <span className={cn("num inline-flex items-baseline gap-2 whitespace-nowrap", toneClass(d), className)}>
      {privacy ? <Masked /> : formatMoney(amount, { signed: true })}
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
    <Link to="/" search={{ view: "performance" }} className="mb-1.5 shrink-0 text-right text-sm text-ink-2 underline-offset-3 hover:text-ink hover:underline">
      近 1 個月走勢：{reason}
    </Link>
  )
}

function HeroDesktop({ summary }: { summary?: PortfolioSummary }) {
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const holdings = useHoldings()
  const trend = useTrend()
  const privacy = usePrefs((s) => s.privacyMode)
  if (!summary) return <HeroSkeleton />
  const up = (trend.values.at(-1) ?? 0) >= (trend.values[0] ?? 0)
  const missingReason = trendMissingReason(trend.notes)
  return (
    <div className="flex items-end justify-between gap-8">
      <div className="min-w-0">
        <p className="flex items-center gap-2.5 text-sm text-ink-2">
          <b className="text-base font-medium text-ink">總資產</b>
          {asOfLabel(summary.as_of)}
          {summary.is_demo && <DemoTag title={demoTitle(holdings.data)} />}
        </p>
        <BigTotal value={summary.market_value} size="desktop" />
        <dl className="mt-3.5 flex flex-wrap gap-x-12 gap-y-2">
          <div className="flex items-baseline gap-2.5">
            <dt className="text-sm text-ink-2">今日</dt>
            <dd className="text-lg font-medium">
              <Delta amount={summary.day_change} pct={summary.day_change_pct} />
            </dd>
          </div>
          <div className="flex items-baseline gap-2.5">
            <dt className="text-sm text-ink-2">總損益（含股利）</dt>
            <dd className="text-lg font-medium">
              <Delta amount={summary.total_pnl} pct={summary.total_return_pct} />
            </dd>
          </div>
        </dl>
      </div>
      {showTrend && trend.values.length < 2 && !trend.loading && !trend.isError && missingReason && <TrendMissing reason={missingReason} />}
      {showTrend && trend.values.length > 1 && (
        <figure className="mb-1.5 text-right" aria-label={`近 1 個月總資產走勢：${up ? "上升" : "下降"}`}>
          {privacy ? (
            <div className="grid h-10 w-[168px] place-items-center text-sm text-ink-2">走勢已隱藏</div>
          ) : (
            <Sparkline values={trend.values} baseline={trend.values[0]} width={168} height={40} tone="ink" dot label={`近 1 個月總資產走勢：${up ? "上升" : "下降"}`} />
          )}
          <figcaption className="mt-1.5 text-sm text-ink-2">近 1 個月</figcaption>
        </figure>
      )}
    </div>
  )
}

function HeroMobile({ summary }: { summary?: PortfolioSummary }) {
  const [open, setOpen] = useState(false)
  const showTrend = useLedgerPrefs((s) => s.showTrend)
  const holdings = useHoldings()
  const trend = useTrend()
  const privacy = usePrefs((s) => s.privacyMode)
  if (!summary) return <HeroSkeleton />
  const asOf = asOfLabel(summary.as_of).replace(/ \d\d:\d\d 收盤$/, " 收盤")
  return (
    <section aria-label="總資產" className="mt-3 rounded-xl border border-rule bg-raised py-[18px] pr-3 pl-5">
      <div className="grid grid-cols-[1fr_auto] items-center">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-base text-ink-2">
            總資產・{asOf}
            {summary.is_demo && <DemoTag title={demoTitle(holdings.data)} />}
          </p>
          <BigTotal value={summary.market_value} size="mobile" />
          <p className="mt-1.5 text-lg font-medium">
            <Delta amount={summary.day_change} pct={summary.day_change_pct} className="flex-row-reverse" />
            <span className="ml-2 font-normal text-ink-2">今天</span>
          </p>
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="hero-more"
          aria-label={open ? "收起總損益與走勢" : "展開總損益與走勢"}
          onClick={() => setOpen(!open)}
          className="press grid size-11 place-items-center rounded-full bg-hov text-ink"
        >
          <ChevronDownIcon aria-hidden className={cn("size-[22px] transition-transform duration-200", open && "rotate-180")} />
        </button>
      </div>
      {open && (
        <div id="hero-more" className="note-in mt-4 flex items-end justify-between gap-4 border-t border-rule pt-3.5">
          <dl>
            <dt className="text-sm text-ink-2">總損益（含股利）</dt>
            <dd className="mt-0.5 text-lg font-medium">
              <Delta amount={summary.total_pnl} pct={summary.total_return_pct} />
            </dd>
          </dl>
          {showTrend && trend.values.length > 1 && !privacy && (
            <figure className="text-right">
              <Sparkline values={trend.values} baseline={trend.values[0]} width={120} height={34} tone="ink" dot label="近 1 個月總資產走勢" />
              <figcaption className="mt-1 text-xs text-ink-2">近 1 個月</figcaption>
            </figure>
          )}
        </div>
      )}
    </section>
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

/** 本週 N 件事：除息、股利入帳、定期定額（規則計算，不是 AI 簡報） */
function WeekLine() {
  const upcoming = useUpcoming(7)
  const privacy = usePrefs((s) => s.privacyMode)
  const items = upcoming.data ?? []
  if (upcoming.isLoading) return <Skeleton className="mt-9 h-[52px] w-full rounded-none" />
  const first = items[0]
  return (
    <Link
      to="/"
      search={{ view: "dividends" }}
      className="mt-2 flex min-h-12 items-center gap-2 py-2 text-base text-ink hover:bg-hov lg:mt-9 lg:min-h-[52px] lg:border-y lg:border-rule lg:pr-2 lg:pl-0.5 lg:text-base"
      aria-label={first ? `本週 ${items.length} 件事，查看全部` : "接下來 7 天沒有除息或入帳，查看股利"}
    >
      <CalendarDaysIcon aria-hidden className="hidden size-[18px] text-ink-2 lg:block" />
      {first ? (
        <span className="min-w-0 truncate">
          <b className="font-medium">
            <span className="lg:hidden">本週：</span>
            <span className="max-lg:hidden">本週 {items.length} 件事：</span>
          </b>
          <time dateTime={first.date} className="num font-medium lg:mr-2">
            {formatDateShort(first.date)}
          </time>
          <span className="max-lg:hidden">{upcomingText(first, privacy)}</span>
          <span className="lg:hidden">{upcomingShort(first)}</span>
        </span>
      ) : (
        <span className="text-ink-2">接下來 7 天沒有除息、入帳或定期定額</span>
      )}
      <ChevronRightIcon aria-hidden className="ml-auto size-[18px] shrink-0 text-ink-2" />
    </Link>
  )
}


