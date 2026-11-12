import NumberFlow from "@number-flow/react"
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router"
import { ArrowLeftIcon, ChevronDownIcon, PlusIcon, StarIcon } from "lucide-react"
import { lazy, Suspense, useState } from "react"
import { ApiError } from "@/api"
import { useInstrument, useOverview, usePosition, useQuote, useToggleWatch, useWatchlist, useWhy } from "@/api/queries"
import type { InstrumentDetail, Position, Quote } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { DemoTag } from "@/components/section"
import { ErrorState } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, directionGlyph, formatDateShort, formatMoney, formatPercent, formatPrice, formatQuantity, toneClass } from "@/lib/format"
import { MARKET_LABEL } from "@/lib/labels"
import { formatQuote, formatQuoteChange, limitPrices, limitState, quoteDecimals } from "@/lib/tick"
import { cn } from "@/lib/utils"
import type { StockTab } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { asOfLabel } from "@/lib/as-of"
import { PriceChart } from "./PriceChart"
import { OverviewTab } from "./tabs/OverviewTab"

const ValuationTab = lazy(() => import("./tabs/ValuationTab").then((m) => ({ default: m.ValuationTab })))
const FinancialsTab = lazy(() => import("./tabs/FinancialsTab").then((m) => ({ default: m.FinancialsTab })))
const ChipsTab = lazy(() => import("./tabs/ChipsTab").then((m) => ({ default: m.ChipsTab })))
const DividendsTab = lazy(() => import("./tabs/DividendsTab").then((m) => ({ default: m.DividendsTab })))
const EventsTab = lazy(() => import("./tabs/EventsTab").then((m) => ({ default: m.EventsTab })))

const TABS: { value: StockTab; label: string }[] = [
  { value: "overview", label: "總覽" },
  { value: "valuation", label: "估值" },
  { value: "financials", label: "財務" },
  { value: "chips", label: "籌碼" },
  { value: "dividends", label: "股利" },
  { value: "events", label: "事件" },
]

/**
 * 個股頁：上半部共用（報價、「為什麼」那一行、我的部位、走勢圖），下半部六個分頁。
 * 持有的人先看到自己：部位緊接在價格下，圖上有均價線與買賣點（隱私模式隱藏）。
 */
export function StockPage() {
  const { symbol } = useParams({ from: "/stock/$symbol" })
  const search = useSearch({ from: "/stock/$symbol" })
  const navigate = useNavigate()
  const tab: StockTab = search.tab ?? "overview"
  const instrument = useInstrument(symbol)
  const quote = useQuote(symbol)
  const position = usePosition(symbol)

  if (instrument.isError) {
    const notFound = instrument.error instanceof ApiError && instrument.error.status === 404
    return (
      <div className="mx-auto w-full max-w-[1180px] px-5 py-16 md:px-8 xl:px-14">
        {notFound ? (
          <div className="flex max-w-md flex-col items-start gap-3">
            <h1 className="text-2xl font-bold">找不到「{symbol}」</h1>
            <p className="text-ink-2">代號可能打錯了。台股用 2330、0050 這樣的代號，美股用 AAPL、NVDA。</p>
            <Link to="/" className={buttonVariants({ variant: "outline" })}>
              回到帳本
            </Link>
          </div>
        ) : (
          <ErrorState error={instrument.error} onRetry={() => void instrument.refetch()} />
        )}
      </div>
    )
  }
  const inst = instrument.data
  return (
    <div className="mx-auto w-full max-w-[1180px] px-5 pt-1 pb-12 md:px-8 lg:pt-6 xl:px-14">
      {!inst ? (
        <HeaderSkeleton />
      ) : (
        <>
          <Breadcrumb inst={inst} held={!!position.data} />
          <QuoteHeader inst={inst} quote={quote.data} />
          <WhyLine inst={inst} />
          {position.data && <PositionBlock inst={inst} position={position.data} />}
          <PriceChart inst={inst} quote={quote.data} position={position.data ?? null} />
        </>
      )}

      <div className="sticky top-0 z-20 -mx-5 mt-8 border-b border-rule bg-paper px-5 md:-mx-8 md:px-8 lg:top-16 xl:-mx-14 xl:px-14">
        <div role="tablist" aria-label="個股資料" className="no-scrollbar flex gap-1 overflow-x-auto">
          {TABS.map((t) => {
            const active = t.value === tab
            return (
              <button
                key={t.value}
                type="button"
                role="tab"
                id={`stock-tab-${t.value}`}
                aria-selected={active}
                aria-controls="stock-tabpanel"
                tabIndex={active ? 0 : -1}
                onKeyDown={(e) => {
                  const i = TABS.findIndex((x) => x.value === tab)
                  const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
                  if (!d) return
                  e.preventDefault()
                  const next = TABS[(i + d + TABS.length) % TABS.length]!
                  void navigate({ to: "/stock/$symbol", params: { symbol }, search: { tab: next.value === "overview" ? undefined : next.value }, replace: true })
                  requestAnimationFrame(() => document.getElementById(`stock-tab-${next.value}`)?.focus())
                }}
                onClick={() => void navigate({ to: "/stock/$symbol", params: { symbol }, search: { tab: t.value === "overview" ? undefined : t.value }, replace: true, resetScroll: false })}
                className={cn(
                  "-mb-px flex h-12 shrink-0 items-center border-b-2 px-3 text-base transition-colors",
                  active ? "border-ink font-bold text-ink" : "border-transparent text-ink-2 hover:text-ink",
                )}
              >
                {t.label}
              </button>
            )
          })}
        </div>
      </div>

      <div id="stock-tabpanel" role="tabpanel" aria-labelledby={`stock-tab-${tab}`} className="pt-6">
        {inst && (
          <Suspense fallback={<Skeleton className="h-72 w-full rounded-sm" />}>
            {tab === "overview" && <OverviewTab inst={inst} quote={quote.data} position={position.data ?? null} />}
            {tab === "valuation" && <ValuationTab inst={inst} position={position.data ?? null} />}
            {tab === "financials" && <FinancialsTab inst={inst} />}
            {tab === "chips" && <ChipsTab inst={inst} />}
            {tab === "dividends" && <DividendsTab inst={inst} quote={quote.data} position={position.data ?? null} />}
            {tab === "events" && <EventsTab inst={inst} position={position.data ?? null} />}
          </Suspense>
        )}
      </div>
    </div>
  )
}

function HeaderSkeleton() {
  return (
    <div aria-busy="true" aria-label="報價載入中" className="flex flex-col gap-3 pt-4">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-12 w-64" />
      <Skeleton className="mt-6 h-72 w-full rounded-sm" />
    </div>
  )
}

function Breadcrumb({ inst, held }: { inst: InstrumentDetail; held: boolean }) {
  const overview = useOverview(inst.symbol)
  const watch = useWatchlist()
  const toggle = useToggleWatch()
  const ask = useAskAi()
  const watching = (watch.data ?? []).some((w) => w.symbol === inst.symbol)
  const status = overview.data?.status
  return (
    <nav aria-label="位置" className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-2">
      <Link to="/" className="-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11">
        <ArrowLeftIcon aria-hidden className="size-4" />
        帳本
      </Link>
      <span className="num">{inst.code}</span>
      <span>
        {MARKET_LABEL[inst.market]}
        {inst.type === "etf" ? "・ETF" : inst.industry ? `・${inst.industry}` : ""}
      </span>
      {status?.attention && (
        <span className="demo-tag border-ink font-medium" title={status.note ?? undefined}>
          注意股
        </span>
      )}
      {status?.disposition && (
        <span className="demo-tag border-ink font-medium" title={status.note ?? undefined}>
          處置中
        </span>
      )}
      {inst.is_demo && <DemoTag className="max-sm:hidden" />}
      <span className="ml-auto flex items-center gap-2">
        {!held && (
          <Button
            variant="outline"
            size="sm"
            aria-pressed={watching}
            disabled={toggle.isPending}
            onClick={() => toggle.mutate({ symbol: inst.symbol, on: !watching })}
          >
            <StarIcon className={cn(watching && "fill-ink")} />
            {watching ? "觀察中" : "加入觀察"}
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => ask.action("trade", { code: inst.code })}>
          <PlusIcon />
          記一筆
        </Button>
      </span>
    </nav>
  )
}

function QuoteHeader({ inst, quote }: { inst: InstrumentDetail; quote?: Quote }) {
  const ref = quote?.reference_price ?? quote?.prev_close ?? null
  const limits = quote && quote.limit_up !== undefined && quote.limit_up !== null ? { up: quote.limit_up, down: quote.limit_down ?? null } : limitPrices(ref, inst.market, inst.type)
  const change = quote ? (quote.change ?? (ref !== null ? quote.price - ref : null)) : null
  const pct = quote ? (quote.change_pct ?? (ref ? quote.price / ref - 1 : null)) : null
  const d = direction(change)
  const atLimit = limitState(quote?.price, limits?.up, limits?.down)
  const digits = quote ? quoteDecimals(quote.price, inst.market, inst.type) : 0
  return (
    <header className="mt-1">
      <h1 className="text-2xl font-bold tracking-[-0.01em] lg:text-3xl">{inst.name}</h1>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="hero-figure text-4xl font-medium tracking-[-0.015em] lg:text-[3rem] lg:leading-tight">
          {inst.market === "US" && <span className="mr-1 text-xl font-normal text-ink-2">US$</span>}
          {quote ? <NumberFlow value={quote.price} locales="zh-TW" format={{ minimumFractionDigits: digits, maximumFractionDigits: digits }} /> : "—"}
        </p>
        <p className={cn("num text-xl font-medium", toneClass(d))}>
          {change === null ? (
            <span className="text-ink-2">—</span>
          ) : (
            <>
              {directionGlyph(d)}
              {formatQuoteChange(change, quote!.price, inst.market, inst.type)}
              <span className="ml-3">
                {directionGlyph(d)}
                {formatPercent(pct === null ? null : Math.abs(pct), { signed: false })}
              </span>
              <span className="sr-only">{d === "up" ? "上漲" : d === "down" ? "下跌" : "持平"}</span>
            </>
          )}
        </p>
        {atLimit && <span className={cn("demo-tag font-medium", atLimit === "up" ? "border-rise text-rise" : "border-fall text-fall")}>{atLimit === "up" ? "漲停" : "跌停"}</span>}
      </div>
      <p className="num mt-1 flex flex-wrap gap-x-3 text-sm text-ink-2">
        <span>{quote ? asOfLabel(quote.as_of) || "—" : "—"}</span>
        {ref !== null && <span>參考價 {formatQuote(ref, inst.market, inst.type)}</span>}
        {limits && (
          <span>
            漲停 {formatQuote(limits.up, inst.market, inst.type)} ・ 跌停 {formatQuote(limits.down, inst.market, inst.type)}
          </span>
        )}
        {quote?.is_demo && <span className="sm:hidden">示範資料</span>}
      </p>
    </header>
  )
}

/** 「為什麼漲跌」：只在異常時出現（紫色文楷），點了交給 AI 展開 */
function WhyLine({ inst }: { inst: InstrumentDetail }) {
  const why = useWhy(inst.symbol)
  const quote = useQuote(inst.symbol)
  const ask = useAskAi()
  if (!why.data?.show || !why.data.headline) return null
  const d = direction(quote.data?.change_pct)
  return (
    <button
      type="button"
      onClick={() => ask.submit(`${inst.name}今天為什麼${d === "down" ? "跌" : "漲"}？`)}
      className="ai-voice press mt-3 block max-w-full text-left text-lg leading-snug hover:underline hover:decoration-ai-rule hover:underline-offset-4 lg:text-xl"
    >
      {why.data.headline} ›
    </button>
  )
}

/** 我的部位：兩行（股數、均價、未實現、今日、已領股利）＋展開 */
function PositionBlock({ inst, position: p }: { inst: InstrumentDetail; position: Position }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const ask = useAskAi()
  const [open, setOpen] = useState(false)
  const money = (n: number, signed = false) => formatMoney(n, { signed })
  if (privacy) {
    return (
      <section aria-label="我的部位" className="mt-5 flex min-h-12 items-center border-y border-rule text-md text-ink-2">
        持有中・隱私模式開啟，部位與圖上的均價、買賣點已隱藏。
      </section>
    )
  }
  const recent = [...p.markers].filter((m) => m.type === "buy" || m.type === "sell").sort((a, b) => b.date.localeCompare(a.date)).slice(0, 3)
  return (
    <section aria-label="我的部位" className="mt-5 border-y border-rule">
      <div className="flex items-center gap-3 py-2.5">
        <dl className="num flex min-w-0 flex-1 flex-wrap gap-x-5 gap-y-1.5 text-base sm:gap-x-7">
          <Item label="持有" value={formatQuantity(p.quantity, unit, inst.market)} />
          <Item label="均價" value={formatPrice(p.avg_cost, inst.market)} />
          <Item
            label="未實現"
            value={
              <span className={toneClass(direction(p.unrealized_pnl))}>
                {money(p.unrealized_pnl, true)}
                <span className="ml-1.5 text-md">{formatPercent(p.unrealized_pnl_pct)}</span>
              </span>
            }
          />
          <Item className="max-sm:hidden" label="今日" value={<span className={toneClass(direction(p.day_change))}>{money(p.day_change, true)}</span>} />
          <Item className="max-sm:hidden" label="已領股利" value={money(p.dividends_received)} />
        </dl>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="position-more"
          aria-label={open ? "收起部位明細" : "展開部位明細"}
          onClick={() => setOpen(!open)}
          className="press grid size-10 shrink-0 place-items-center self-start rounded-full text-ink-2 hover:bg-hov hover:text-ink pointer-coarse:size-11"
        >
          <ChevronDownIcon aria-hidden className={cn("size-5 transition-transform duration-200", open && "rotate-180")} />
        </button>
      </div>
      {open && (
        <div id="position-more" className="note-in grid gap-x-10 gap-y-4 border-t border-rule py-4 md:grid-cols-2">
          <dl className="num grid grid-cols-2 gap-x-6 gap-y-2 text-md">
            <Item className="sm:hidden" label="今日" value={<span className={toneClass(direction(p.day_change))}>{money(p.day_change, true)}</span>} />
            <Item className="sm:hidden" label="已領股利" value={money(p.dividends_received)} />
            <Item label="市值" value={money(p.market_value)} />
            <Item label="成本" value={money(p.cost_basis)} />
            <Item label="已實現" value={<span className={toneClass(direction(p.realized_pnl))}>{money(p.realized_pnl, true)}</span>} />
            <Item
              label="下次除息"
              value={p.upcoming_dividend ? `${formatDateShort(p.upcoming_dividend.ex_dividend_date, false)}・約 ${money(p.upcoming_dividend.amount_estimate)}` : "未公告"}
            />
          </dl>
          <div>
            <p className="text-sm text-ink-2">最近的交易</p>
            <ul className="mt-1">
              {recent.map((m) => (
                <li key={`${m.date}-${m.type}-${m.quantity}`} className="num flex justify-between gap-3 border-b border-rule py-1.5 text-md">
                  <span>
                    {formatDateShort(m.date)} {m.type === "buy" ? "買進" : "賣出"}
                  </span>
                  <span className="text-ink-2">
                    {m.quantity !== null ? formatQuantity(m.quantity, unit, inst.market) : ""} × {formatPrice(m.price, inst.market)}
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to="/" search={{ view: "transactions", symbol: inst.symbol }} className={buttonVariants({ variant: "outline", size: "sm" })}>
                在帳本中查看 ›
              </Link>
              <Button variant="outline" size="sm" onClick={() => ask.action("trade", { code: inst.code })}>
                記一筆
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

function Item({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-baseline gap-2 whitespace-nowrap", className)}>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  )
}

