import { Link } from "@tanstack/react-router"
import { ArrowRightIcon, FileUpIcon, PencilLineIcon } from "lucide-react"
import { useMemo, useState } from "react"
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts"
import { useHoldings, usePerformance, useSummary } from "@/api/queries"
import type { Holding, PerformanceRange, PortfolioSummary } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { DemoChop, SoonChop } from "@/components/chop"
import { Legend, RangeChips } from "@/components/charts/chart-kit"
import { ReturnChart } from "@/components/charts/ReturnChart"
import { FlowMoney, FlowPct, Money, Pct } from "@/components/finance"
import { Panel } from "@/components/section"
import { ChartSkeleton, EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, formatDateShort, formatDateTime, formatDaysUntil, formatPercent, toneClass } from "@/lib/format"
import { foldSlices } from "@/lib/allocation"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"

export function HomePage() {
  const summary = useSummary()
  const holdings = useHoldings()

  if (summary.isError) return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} className="mt-4" />

  const isEmpty = summary.data && holdings.data && holdings.data.length === 0

  return (
    <div className="flex flex-col gap-6">
      <h1 className="sr-only">總覽</h1>
      {isEmpty ? (
        <FirstRun />
      ) : (
        <>
          <Hero summary={summary.data} holdings={holdings.data} />
          <div className="grid gap-4 lg:grid-cols-3">
            <PerformancePanel className="lg:col-span-2" />
            <AiPanel />
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AllocationPanel summary={summary.data} />
            <DividendsPanel summary={summary.data} />
            <TopHoldingsPanel holdings={holdings.data} className="md:col-span-2 xl:col-span-1" />
          </div>
        </>
      )}
    </div>
  )
}

// ── Hero：總資產與今日損益 ─────────────────────────────────
function Hero({ summary, holdings }: { summary?: PortfolioSummary; holdings?: Holding[] }) {
  if (!summary) {
    return (
      <section className="grid gap-6 pt-1 lg:grid-cols-[minmax(0,1fr)_340px]" aria-busy="true" aria-label="載入資產摘要">
        <div className="flex flex-col gap-3">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-11 w-72 max-w-full" />
          <Skeleton className="h-7 w-64 max-w-full" />
        </div>
        <SkeletonLines rows={3} />
      </section>
    )
  }
  const movers = (holdings ?? [])
    .filter((h) => Math.abs(h.day_change) > 0)
    .sort((a, b) => Math.abs(b.day_change) - Math.abs(a.day_change))
    .slice(0, 4)
  const maxMove = Math.max(...movers.map((m) => Math.abs(m.day_change)), 1)

  return (
    <section aria-labelledby="hero-title" className="grid gap-x-10 gap-y-6 pt-1 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 id="hero-title" className="text-md font-medium text-muted-foreground">
            總資產
          </h2>
          <DemoChop show={summary.is_demo} />
          <span className="text-sm text-muted-foreground">{formatDateTime(summary.as_of)} 收盤</span>
        </div>
        <FlowMoney value={summary.market_value} className="hero-figure text-hero-sm font-semibold tracking-[-0.02em] sm:text-hero" />
        <dl className="grid grid-cols-1 gap-x-10 gap-y-4 sm:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="text-sm text-muted-foreground">今日損益</dt>
            <dd className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xl font-semibold">
              <FlowMoney value={summary.day_change} signed tone />
              <FlowPct value={summary.day_change_pct} className="text-lg" />
            </dd>
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="text-sm text-muted-foreground">總損益（含股利）</dt>
            <dd className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xl font-semibold">
              <FlowMoney value={summary.total_pnl} signed tone />
              <Pct value={summary.total_return_pct} className="text-lg" />
            </dd>
            <dd className="flex flex-wrap gap-x-3 text-sm text-muted-foreground">
              <span>
                未實現 <Money value={summary.unrealized_pnl} signed compact />
              </span>
              <span>
                已實現 <Money value={summary.realized_pnl} signed compact />
              </span>
              <span>
                股利 <Money value={summary.dividend_income} compact />
              </span>
            </dd>
          </div>
        </dl>
      </div>

      <div className="flex min-w-0 flex-col gap-2 lg:border-l lg:border-hairline lg:pl-8">
        <h3 className="text-md font-medium text-muted-foreground">今天誰影響最大</h3>
        {movers.length === 0 ? (
          <p className="text-md text-muted-foreground">今天持股都沒有漲跌。</p>
        ) : (
          <ul className="flex flex-col">
            {movers.map((h) => (
              <li key={h.symbol}>
                <Link
                  to="/stock/$symbol"
                  params={{ symbol: h.symbol }}
                  className="row-link grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-1.5"
                >
                  <span className="truncate text-md">
                    {h.name} <span className="num text-sm text-muted-foreground">{h.code}</span>
                  </span>
                  <Money value={h.day_change} signed tone compact className="text-md font-medium" />
                  <span className="col-span-2 mt-1 h-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                    <span
                      className={cn("block h-full rounded-full", direction(h.day_change) === "up" ? "bg-rise" : "bg-fall")}
                      style={{ width: `${Math.max((Math.abs(h.day_change) / maxMove) * 100, 4)}%` }}
                    />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

// ── 報酬走勢 ──────────────────────────────────────────────
type HomeRange = "1D" | "5D" | "1M" | "6M" | "YTD" | "1Y" | "ALL"
const HOME_RANGES: { value: HomeRange; label: string }[] = [
  { value: "1D", label: "1D" },
  { value: "5D", label: "5D" },
  { value: "1M", label: "1M" },
  { value: "6M", label: "6M" },
  { value: "YTD", label: "YTD" },
  { value: "1Y", label: "1Y" },
  { value: "ALL", label: "全部" },
]
/** API 沒有 1D／5D：以 1M 資料裁切（見 OPEN_QUESTIONS） */
const API_RANGE: Record<HomeRange, PerformanceRange> = { "1D": "1M", "5D": "1M", "1M": "1M", "6M": "6M", YTD: "YTD", "1Y": "1Y", ALL: "ALL" }

function PerformancePanel({ className }: { className?: string }) {
  const [range, setRange] = useState<HomeRange>("1Y")
  const [showBench, setShowBench] = useState(true)
  const perf = usePerformance(API_RANGE[range])
  const series = useMemo(() => {
    const s = perf.data?.series ?? []
    if (range === "1D") return s.slice(-2)
    if (range === "5D") return s.slice(-6)
    return s
  }, [perf.data, range])
  const first = series[0]
  const last = series.at(-1)
  const mine = first && last ? last.twr_index / first.twr_index - 1 : null
  const bench = first?.benchmark_index && last?.benchmark_index ? last.benchmark_index / first.benchmark_index - 1 : null
  const benchName = perf.data?.benchmark?.name ?? "元大台灣50"

  return (
    <Panel
      titleSize="lg"
      title="報酬走勢"
      titleId="perf-title"
      className={className}
      action={
        <Link to="/performance" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          績效分析
          <ArrowRightIcon />
        </Link>
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <RangeChips label="報酬區間" value={range} options={HOME_RANGES} onChange={setRange} />
        <label className="inline-flex h-8 cursor-pointer items-center gap-2 text-sm text-muted-foreground select-none">
          <input
            type="checkbox"
            checked={showBench}
            onChange={(e) => setShowBench(e.target.checked)}
            className="size-4 accent-[var(--primary)]"
          />
          疊加 {benchName}
        </label>
      </div>
      <Legend
        className="mt-3"
        items={[
          { label: "我的（時間加權）", color: "var(--chart-1)", shape: "line", value: <span className={toneClass(direction(mine))}>{formatPercent(mine)}</span> },
          ...(showBench ? [{ label: benchName, color: "var(--chart-2)", shape: "line" as const, value: formatPercent(bench) }] : []),
        ]}
      />
      <div className={cn("mt-2 transition-opacity", perf.isPlaceholderData && "opacity-60")}>
        {perf.isError ? (
          <ErrorState error={perf.error} onRetry={() => void perf.refetch()} />
        ) : !perf.data ? (
          <ChartSkeleton height={240} />
        ) : series.length < 2 ? (
          <div className="flex h-[240px] flex-col items-start justify-center gap-1 rounded-lg border border-dashed px-5">
            <p className="font-medium">走勢圖需要至少兩個交易日</p>
            <p className="text-md text-muted-foreground">剛開始追蹤的持股，下一個交易日收盤後就會出現報酬走勢。</p>
          </div>
        ) : (
          <ReturnChart series={series} showBenchmark={showBench} benchmarkName={benchName} height={240} />
        )}
      </div>
      {range === "1D" && (
        <p className="mt-2 text-sm text-muted-foreground">盤中走勢要等即時行情（M2）上線；現在先顯示昨收到今收。</p>
      )}
    </Panel>
  )
}

// ── AI 今日重點（M4） ─────────────────────────────────────
function AiPanel() {
  return (
    <Panel titleSize="lg" title="AI 今日重點" titleId="ai-title" aside={<SoonChop milestone="M4" />}>
      <p className="text-md text-muted-foreground">
        每個交易日收盤後，AI 會只根據你的持股，整理成三段重點。數字都來自資料查詢，並標示資料日期。
      </p>
      <ol className="mt-4 flex flex-col divide-y divide-hairline border-y border-hairline">
        {[
          ["漲跌原因", "哪幾檔影響今天的損益最多，為什麼"],
          ["法人動向", "三大法人對你持股的買賣超"],
          ["新聞重點", "和你持股有關、值得注意的消息"],
        ].map(([title, desc]) => (
          <li key={title} className="flex flex-col py-2.5">
            <span className="text-md font-medium">{title}</span>
            <span className="text-sm text-muted-foreground">{desc}</span>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-muted-foreground">AI 分析僅供參考，不構成投資建議。</p>
      <Link to="/ai" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-3")}>
        看看 AI 助理會做什麼
      </Link>
    </Panel>
  )
}

// ── 資產配置 ──────────────────────────────────────────────
type AllocKey = "by_type" | "by_market" | "by_industry" | "by_currency"
const ALLOC_TABS: { value: AllocKey; label: string }[] = [
  { value: "by_type", label: "類型" },
  { value: "by_market", label: "市場" },
  { value: "by_industry", label: "產業" },
  { value: "by_currency", label: "幣別" },
]
/** 分類色固定順序（dataviz：依實體、不依排名；第 6 塊一定是「其他」石灰） */
const SLICE_COLORS = ["var(--chart-1)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)", "var(--chart-2)"]

function AllocationPanel({ summary }: { summary?: PortfolioSummary }) {
  const [key, setKey] = useState<AllocKey>("by_type")
  const slices = summary ? foldSlices(summary.allocation[key]) : []
  return (
    <Panel titleSize="lg" title="資產配置" titleId="alloc-title">
      <RangeChips label="配置分類" value={key} options={ALLOC_TABS} onChange={setKey} />
      {!summary ? (
        <ChartSkeleton height={180} className="mt-3" />
      ) : (
        <div className="mt-3 grid grid-cols-[132px_minmax(0,1fr)] items-center gap-4">
          <div className="relative size-[132px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="value"
                  nameKey="label"
                  innerRadius={44}
                  outerRadius={64}
                  paddingAngle={slices.length > 1 ? 2 : 0}
                  stroke="var(--card)"
                  strokeWidth={2}
                  isAnimationActive={false}
                >
                  {slices.map((s, i) => (
                    <Cell key={s.key} fill={SLICE_COLORS[i % SLICE_COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-xs text-muted-foreground">{slices.length} 類</span>
            </div>
          </div>
          <ul className="flex min-w-0 flex-col gap-1.5">
            {slices.map((s, i) => (
              <li key={s.key} className="grid grid-cols-[10px_minmax(0,1fr)_auto] items-center gap-2 text-md">
                <span aria-hidden className="size-2.5 rounded-[3px]" style={{ background: SLICE_COLORS[i % SLICE_COLORS.length] }} />
                <span className="truncate" title={s.label}>
                  {s.label}
                </span>
                <span className="num font-medium">{formatPercent(s.weight, { signed: false, decimals: 1 })}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  )
}

// ── 即將除權息 ────────────────────────────────────────────
function DividendsPanel({ summary }: { summary?: PortfolioSummary }) {
  const today = summary?.as_of.slice(0, 10) ?? ""
  const list = summary?.upcoming_dividends ?? []
  return (
    <Panel titleSize="lg" title="即將除權息" titleId="div-title" aside={<span className="text-sm text-muted-foreground">60 天內</span>}>
      {!summary ? (
        <SkeletonLines rows={3} />
      ) : list.length === 0 ? (
        <p className="text-md text-muted-foreground">60 天內沒有持股要除權息。</p>
      ) : (
        <ul className="flex flex-col divide-y divide-hairline">
          {list.map((d) => (
            <li key={`${d.symbol}-${d.ex_dividend_date}`}>
              <Link
                to="/stock/$symbol"
                params={{ symbol: d.symbol }}
                search={{ tab: "dividends" }}
                className="row-link grid grid-cols-[64px_minmax(0,1fr)_auto] items-center gap-3 py-2.5"
              >
                <span className="flex flex-col leading-tight">
                  <span className="num text-md font-semibold">{formatDateShort(d.ex_dividend_date, false)}</span>
                  <span className="text-xs text-muted-foreground">{formatDaysUntil(d.ex_dividend_date, today)}</span>
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-md">{d.name}</span>
                  <span className="num block text-sm text-muted-foreground">每股 {d.cash_dividend} 元</span>
                </span>
                <span className="text-right">
                  <span className="block text-xs text-muted-foreground">預估入帳</span>
                  <Money value={d.estimated_amount} className="text-md font-medium" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

// ── 前五大持股 ────────────────────────────────────────────
function TopHoldingsPanel({ holdings, className }: { holdings?: Holding[]; className?: string }) {
  const top = (holdings ?? []).slice(0, 5)
  return (
    <Panel
      titleSize="lg"
      title="前五大持股"
      titleId="top-title"
      className={className}
      action={
        <Link to="/holdings" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          全部持股
          <ArrowRightIcon />
        </Link>
      }
    >
      {!holdings ? (
        <SkeletonLines rows={5} />
      ) : (
        <ul className="flex flex-col divide-y divide-hairline">
          {top.map((h) => (
            <li key={h.symbol}>
              <Link
                to="/stock/$symbol"
                params={{ symbol: h.symbol }}
                className="row-link grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-2"
              >
                <span className="min-w-0">
                  <span className="block truncate text-md" title={h.name}>
                    {h.name}
                  </span>
                  <span className="num block text-sm text-muted-foreground">
                    {h.code}・佔 {formatPercent(h.weight, { signed: false, decimals: 1 })}
                  </span>
                </span>
                <span className="flex flex-col items-end">
                  <Money value={h.market_value} compact className="text-md font-medium" />
                  <Pct value={h.day_change_pct} className="text-sm" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

// ── 首次使用 ──────────────────────────────────────────────
function FirstRun() {
  const openTradeForm = useUi((s) => s.openTradeForm)
  const privacy = usePrefs((s) => s.privacyMode)
  return (
    <section aria-labelledby="first-run-title" className="flex flex-col gap-6 py-4">
      <div className="max-w-xl">
        <h2 id="first-run-title" className="text-2xl font-semibold tracking-[-0.01em]">
          先把你的持股放進來
        </h2>
        <p className="mt-2 text-muted-foreground">
          Forliosa 會依台股規則算出真實報酬：手續費、證交稅、二代健保與股利都算進去。選一種開始，之後隨時可以混用。
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-5">
          <PencilLineIcon className="size-5 text-primary" aria-hidden />
          <div>
            <h3 className="text-lg font-semibold">輸入目前持股</h3>
            <p className="mt-1 text-md text-muted-foreground">最快上手。輸入每檔的股數與均價，從今天開始追蹤報酬。</p>
          </div>
          <Button className="self-start" onClick={() => openTradeForm()}>
            輸入第一檔持股
          </Button>
        </div>
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-5">
          <FileUpIcon className="size-5 text-muted-foreground" aria-hidden />
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold">匯入券商對帳單</h3>
            <SoonChop milestone="M3" />
          </div>
          <p className="text-md text-muted-foreground">上傳券商的 Excel、CSV 或 PDF 對帳單，系統辨識後由你逐筆確認入帳。</p>
          <Link to="/import" className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
            了解匯入方式
          </Link>
        </div>
      </div>
      {privacy && <p className="text-sm text-muted-foreground">隱私模式開啟中，輸入後的金額會先遮蔽。</p>}
      <EmptyState
        title="已經有交易紀錄？"
        description="逐筆輸入買賣、股利與配股，績效（時間加權報酬、XIRR）會最精確。"
        action={
          <Link to="/transactions" className={buttonVariants({ variant: "ghost", size: "sm" })}>
            到交易紀錄
            <ArrowRightIcon />
          </Link>
        }
      />
    </section>
  )
}
