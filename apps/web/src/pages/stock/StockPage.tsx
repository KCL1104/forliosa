import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router"
import { MessageSquareTextIcon, StarIcon } from "lucide-react"
import { lazy, Suspense } from "react"
import { useInstrument, useQuote } from "@/api/queries"
import { DemoChop } from "@/components/chop"
import { FlowMoney, PriceChange } from "@/components/finance"
import { ChartSkeleton, ErrorState } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ApiError } from "@/api/types"
import { formatDateTime, formatVolume } from "@/lib/format"
import { MARKET_LABEL } from "@/lib/labels"
import { cn } from "@/lib/utils"
import type { StockTab } from "@/router"
import { useWatchlist } from "@/stores/watchlist"
import { ComingSoonTab, DividendsTab, FinancialsTab, MyTradesTab, OverviewTab } from "./tabs/OtherTabs"
import { ValuationTab } from "./tabs/ValuationTab"

const KlineTab = lazy(() => import("./tabs/KlineTab").then((m) => ({ default: m.KlineTab })))

const TABS: { value: StockTab; label: string; soon?: boolean }[] = [
  { value: "overview", label: "總覽" },
  { value: "kline", label: "K 線" },
  { value: "valuation", label: "估值" },
  { value: "financials", label: "財務" },
  { value: "dividends", label: "股利" },
  { value: "mine", label: "我的交易" },
  { value: "chips", label: "籌碼", soon: true },
  { value: "news", label: "新聞", soon: true },
  { value: "ai", label: "AI 報告", soon: true },
]

const SOURCE_LABEL: Record<string, string> = {
  twse_mis: "證交所 MIS",
  "twse-mis": "證交所 MIS",
  "shioaji-data": "shioaji-data",
  finmind: "FinMind",
  twse_openapi: "證交所 OpenAPI",
  tpex_openapi: "櫃買中心 OpenAPI",
  demo: "示範資料",
  mock: "示範資料",
}

/** 報價來源（可能是多個合併，例如 shioaji-data+finmind） */
function sourceLabel(source: string): string {
  return [...new Set(source.split("+").map((s) => SOURCE_LABEL[s] ?? s))].join("＋")
}

export function StockPage() {
  const { symbol } = useParams({ from: "/stock/$symbol" })
  const { tab = "overview" } = useSearch({ from: "/stock/$symbol" })
  const navigate = useNavigate({ from: "/stock/$symbol" })
  const instrument = useInstrument(symbol)
  const quote = useQuote(symbol)
  const watch = useWatchlist()
  const starred = watch.symbols.includes(symbol)

  if (instrument.isError) {
    const notFound = instrument.error instanceof ApiError && instrument.error.status === 404
    return notFound ? (
      <div className="flex max-w-md flex-col items-start gap-3 py-12">
        <h1 className="text-2xl font-semibold">找不到「{symbol}」</h1>
        <p className="text-muted-foreground">代號可能打錯了。台股上市用 2330.TW、上櫃用 6488.TWO、美股直接用代號（AAPL）。</p>
        <Link to="/" className={buttonVariants({ variant: "outline" })}>回到總覽</Link>
      </div>
    ) : (
      <ErrorState error={instrument.error} onRetry={() => void instrument.refetch()} className="mt-4" />
    )
  }
  const i = instrument.data
  const q = quote.data
  const today = q?.as_of?.slice(0, 10) ?? ""

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            {i ? (
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h1 className={cn("min-w-0 font-semibold tracking-[-0.01em] break-words", i.name.length > 12 ? "text-xl sm:text-2xl" : "text-2xl")}>{i.name}</h1>
                <span className="num text-lg text-muted-foreground">{i.code}</span>
                <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  {MARKET_LABEL[i.market]}
                  {i.type === "etf" ? "・ETF" : i.industry ? `・${i.industry}` : ""}
                </span>
              </div>
            ) : (
              <Skeleton className="h-8 w-48" />
            )}
            <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
              {q && i ? (
                <>
                  <FlowMoney value={q.price} currency={i.currency} decimals={i.market === "US" || q.price < 1000 ? 2 : 0} publicValue className="hero-figure text-hero-sm font-semibold tracking-[-0.02em]" />
                  <PriceChange change={q.change} pct={q.change_pct} market={i.market} className="text-lg font-medium" />
                </>
              ) : (
                <Skeleton className="h-10 w-64" />
              )}
            </div>
            {q && i && (
              <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                <span>{q.is_realtime ? "即時" : "收盤"}・{formatDateTime(q.as_of)}（台北時間）</span>
                <span>成交量 <span className="num">{formatVolume(q.volume, i.market)}</span></span>
                {q.source && <span>來源 {sourceLabel(q.source)}</span>}
                {q.is_demo && <DemoChop />}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant={starred ? "secondary" : "outline"} onClick={() => watch.toggle(symbol)} aria-pressed={starred}>
              <StarIcon className={cn(starred && "fill-current text-amber")} />
              {starred ? "已加入自選" : "加入自選"}
            </Button>
            <Popover>
              <PopoverTrigger render={<Button variant="outline" />}>
                <MessageSquareTextIcon />
                問 AI
              </PopoverTrigger>
              <PopoverContent className="w-72 text-md" align="end">
                <p className="font-medium">AI 助理即將推出（M4）</p>
                <p className="mt-1 text-muted-foreground">
                  之後在這裡按「問 AI」，助理會自動帶入{i?.name ?? "這檔股票"}的報價、估值與你的持有成本，回答時標示資料日期。
                </p>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </header>

      <Tabs value={tab} onValueChange={(v) => void navigate({ search: { tab: v as StockTab }, replace: true })}>
        <div className="sticky top-14 z-20 -mx-4 border-b border-hairline bg-background px-4 sm:-mx-6 sm:px-6 lg:top-16 lg:-mx-8 lg:px-8">
          <TabsList variant="line" className="no-scrollbar h-11 w-full justify-start gap-1 overflow-x-auto">
            {TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="h-11 shrink-0 flex-none px-3 text-md">
                {t.label}
                {t.soon && <span className="text-xs font-normal">即將推出</span>}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        {i ? (
          <>
            <TabsContent value="overview" className="pt-4"><OverviewTab instrument={i} quote={q} /></TabsContent>
            <TabsContent value="kline" className="pt-4">
              <Suspense fallback={<ChartSkeleton height={440} />}>
                <KlineTab symbol={i.symbol} market={i.market} />
              </Suspense>
            </TabsContent>
            <TabsContent value="valuation" className="pt-4"><ValuationTab instrument={i} /></TabsContent>
            <TabsContent value="financials" className="pt-4"><FinancialsTab instrument={i} /></TabsContent>
            <TabsContent value="dividends" className="pt-4"><DividendsTab instrument={i} quote={q} today={today} /></TabsContent>
            <TabsContent value="mine" className="pt-4"><MyTradesTab instrument={i} /></TabsContent>
            <TabsContent value="chips" className="pt-4"><ComingSoonTab kind="chips" /></TabsContent>
            <TabsContent value="news" className="pt-4"><ComingSoonTab kind="news" /></TabsContent>
            <TabsContent value="ai" className="pt-4"><ComingSoonTab kind="ai" /></TabsContent>
          </>
        ) : (
          <ChartSkeleton height={360} className="mt-4" />
        )}
      </Tabs>
    </div>
  )
}
