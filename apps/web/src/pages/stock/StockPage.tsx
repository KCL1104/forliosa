import NumberFlow from "@number-flow/react"
import { inText } from "@/lib/cjk"
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router"
import { ArrowLeftIcon, ArrowUpRightIcon, ChevronDownIcon, ChevronRightIcon } from "lucide-react"
import { lazy, Suspense, useState } from "react"
import { ApiError } from "@/api"
import { useInstrument, useOverview, usePosition, usePositionHistory, useQuote, useToggleWatch, useWatchlist, useWhy } from "@/api/queries"
import type { ClosedRound, InstrumentDetail, Position, Quote, Why } from "@/api/types"
import { Masked, Pct } from "@/components/finance"
import { holdingPeriod } from "@/lib/ledger-display"
import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import { useAskAi } from "@/ai/use-ask"
import { ScrollRow } from "@/components/scroll-row"
import { DemoTag } from "@/components/section"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { ErrorState } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, directionGlyph, formatDateShort, formatMoney, formatPercent, formatPrice, formatQuantity, toneClass } from "@/lib/format"
import { formatQuoteChange, limitPrices, limitState, quoteDecimals } from "@/lib/tick"
import { cn } from "@/lib/utils"
import type { StockTab } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { asOfLabel, closeDay, twseLiveQuoteUrl, withDayWord } from "@/lib/as-of"
import { useClose } from "@/hooks/use-close"
import { useSourceNote } from "@/hooks/use-source-note"
import { PriceChart } from "./PriceChart"
import { OverviewTab } from "./tabs/OverviewTab"
import { marketLine, sourceNotes, twOpenApi, useDatasetSources, withFigures } from "./text"
import { useReadOnly, useWho } from "@/api/view-as"
import { usePageTitle } from "@/app/page-title"

const ValuationTab = lazy(() => import("./tabs/ValuationTab").then((m) => ({ default: m.ValuationTab })))
const FinancialsTab = lazy(() => import("./tabs/FinancialsTab").then((m) => ({ default: m.FinancialsTab })))
const ChipsTab = lazy(() => import("./tabs/ChipsTab").then((m) => ({ default: m.ChipsTab })))
const DividendsTab = lazy(() => import("./tabs/DividendsTab").then((m) => ({ default: m.DividendsTab })))
const EventsTab = lazy(() => import("./tabs/EventsTab").then((m) => ({ default: m.EventsTab })))
const DiscussionsTab = lazy(() => import("./tabs/DiscussionsTab").then((m) => ({ default: m.DiscussionsTab })))

const TABS: { value: StockTab; label: string }[] = [
  { value: "overview", label: "總覽" },
  { value: "valuation", label: "估值" },
  { value: "financials", label: "財務" },
  { value: "chips", label: "籌碼" },
  { value: "dividends", label: "股利" },
  { value: "events", label: "事件" },
  { value: "discussions", label: "討論" },
]

/**
 * 個股頁：上半部共用（報價、「為什麼」那一行、我的部位、走勢圖），下半部七個分頁（最後一個是標記這檔股票的討論）。
 * 持有的人先看到自己：部位緊接在價格下，圖上有均價線與買賣點（隱私模式隱藏）。
 * 各區塊用到的資料來源登記到頁尾，整頁只有一個「資料來源與授權」。
 */
export function StockPage() {
  return (
    <SourcesProvider>
      <StockPageInner />
    </SourcesProvider>
  )
}

function StockPageInner() {
  const { symbol } = useParams({ from: "/stock/$symbol" })
  const search = useSearch({ from: "/stock/$symbol" })
  const navigate = useNavigate()
  // 查看別人的資產時沒有「討論」（討論是查看者自己的事，和群組一樣擋下）
  const readOnly = useReadOnly()
  const tabs = readOnly ? TABS.filter((t) => t.value !== "discussions") : TABS
  const tab: StockTab = search.tab && tabs.some((t) => t.value === search.tab) ? search.tab : "overview"
  const instrument = useInstrument(symbol)
  // 分頁標題：名稱＋代號（名稱還沒載入時先寫代號）
  usePageTitle(instrument.data ? `${instrument.data.name} ${instrument.data.code}` : symbol.replace(/\.(TW|TWO)$/, ""))
  const quote = useQuote(symbol)
  const position = usePosition(symbol)
  // 交易歷史：出清的回合與所有買賣點（未持有也會回）——圖上的 B／S／D 與「過去的持有」都用它
  const history = usePositionHistory(symbol)
  const rounds = history.data?.rounds ?? []

  if (instrument.isError) {
    const notFound = instrument.error instanceof ApiError && instrument.error.status === 404
    return (
      <div className="page-frame px-5 py-16 md:px-8 xl:px-14">
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
  // 沒有報價：只在價格那一格說一次；由價格算出來的區塊（走勢、估值、殖利率、未實現）都不出現
  const noQuote = quote.isError && !quote.data
  return (
    <div className="page-frame px-5 pt-1 pb-12 md:px-8 lg:pt-6 xl:px-14">
      {!inst ? (
        <HeaderSkeleton />
      ) : (
        <>
          <Breadcrumb inst={inst} held={!!position.data} />
          <QuoteHeader inst={inst} quote={quote.data} missing={quote.isError} />
          <WhyLine inst={inst} />
          {position.data ? (
            <PositionBlock inst={inst} position={position.data} rounds={rounds} priced={!noQuote} />
          ) : (
            rounds.length > 0 && <PastHolding inst={inst} rounds={rounds} />
          )}
          {/* 沒有報價（商用模式的美股）：價格那一格已經說了原因，走勢圖整塊不放，不再說一次 */}
          {!noQuote && <PriceChart inst={inst} quote={quote.data} position={position.data ?? null} markers={history.data?.markers} />}
        </>
      )}

      <div className="sticky top-(--sticky-top) z-20 -mx-5 mt-8 border-b border-rule bg-paper px-5 md:-mx-8 md:px-8 xl:-mx-14 xl:px-14">
        <ScrollRow role="tablist" aria-label="個股資料" className="gap-1">
          {tabs.map((t) => {
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
                  const i = tabs.findIndex((x) => x.value === tab)
                  const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
                  if (!d) return
                  e.preventDefault()
                  const next = tabs[(i + d + tabs.length) % tabs.length]!
                  void navigate({ to: "/stock/$symbol", params: { symbol }, search: { tab: next.value === "overview" ? undefined : next.value }, replace: true })
                  requestAnimationFrame(() => document.getElementById(`stock-tab-${next.value}`)?.focus())
                }}
                onClick={() => void navigate({ to: "/stock/$symbol", params: { symbol }, search: { tab: t.value === "overview" ? undefined : t.value }, replace: true, resetScroll: false })}
                // 和群組頁同一種分頁：手機上每個至少 44px 寬、平分整列，七個分頁在 393px 的螢幕上全部看得到（更窄才捲動）
                className="sel-tab -mb-px flex h-12 min-w-11 shrink-0 items-center justify-center px-1 text-base text-ink-2 max-sm:grow sm:px-3"
              >
                {t.label}
              </button>
            )
          })}
        </ScrollRow>
      </div>

      <div id="stock-tabpanel" role="tabpanel" aria-labelledby={`stock-tab-${tab}`} className="pt-6">
        {inst && (
          <Suspense fallback={<Skeleton className="h-72 w-full rounded-sm" />}>
            {tab === "overview" && <OverviewTab inst={inst} quote={quote.data} position={position.data ?? null} />}
            {tab === "valuation" && <ValuationTab inst={inst} position={position.data ?? null} noQuote={noQuote} />}
            {tab === "financials" && <FinancialsTab inst={inst} />}
            {tab === "chips" && <ChipsTab inst={inst} />}
            {tab === "dividends" && <DividendsTab inst={inst} quote={quote.data} position={position.data ?? null} />}
            {tab === "events" && <EventsTab inst={inst} position={position.data ?? null} markers={history.data?.markers ?? position.data?.markers ?? []} />}
            {tab === "discussions" && <DiscussionsTab inst={inst} />}
          </Suspense>
        )}
      </div>
      <SourcesFooter />
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
  // 查看別人的資產（唯讀）：不提供加入觀察、記一筆
  const readOnly = useReadOnly()
  const watching = (watch.data ?? []).some((w) => w.symbol === inst.symbol)
  const status = overview.data?.status
  return (
    <nav aria-label="位置" className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-2">
      <Link to="/" className="-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11">
        <ArrowLeftIcon aria-hidden className="size-4" />
        帳本
      </Link>
      <span className="num">{inst.code}</span>
      <span>{marketLine(inst)}</span>
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
      {!readOnly && <span className="ml-auto flex items-center gap-2">
        {/* 開關：開著時是選取語法 (b)（和隱私模式的眼睛同一種），不靠星號圖示表示狀態 */}
        {!held && (
          <Button
            variant="outline"
            size="sm"
            aria-pressed={watching}
            disabled={toggle.isPending}
            onClick={() => toggle.mutate({ symbol: inst.symbol, on: !watching })}
            className="sel-chip pointer-coarse:h-11"
          >
            {watching ? "觀察中" : "加入觀察"}
          </Button>
        )}
        <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={() => ask.action("trade", { code: inst.code })}>
          記一筆
        </Button>
      </span>}
    </nav>
  )
}

function QuoteHeader({ inst, quote, missing }: { inst: InstrumentDetail; quote?: Quote; missing?: boolean }) {
  // 報價下方的參考價、漲跌停每個分頁都看得到：資料集登記到頁尾（收盤價由走勢圖登記）
  const tw = twOpenApi(inst.market)
  useDatasetSources([!!quote && tw && `${tw}/reference`])
  // 台股與台股 ETF：沒有盤中即時報價，價格標「收盤價・日期」；盤中、或收盤後今天的還沒公布時，下面多一行說明
  const close = useClose(tw ? quote?.as_of : null)
  if (missing && !quote) {
    // 沒有報價（商用模式的美股）：整頁只在價格這一格說一次原因——不放一個大大的「—」，
    // 走勢圖、估值、殖利率這些由價格算出來的區塊不再各自重複這句話
    return (
      <header className="mt-1">
        <h1 className="text-2xl font-bold tracking-[-0.01em] lg:text-3xl">{inst.name}</h1>
        <p className="mt-1 flex min-h-12 items-center text-xl font-medium text-ink-2 lg:min-h-15">沒有報價</p>
        {inst.market === "US" && <p className="mt-1 max-w-prose text-base text-ink">美股沒有報價，所以沒有走勢和估值；持股以成本計值。</p>}
      </header>
    )
  }
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
        {/* 收盤價不是今天的（盤中、今天的還沒公布、假日）：寫明這是哪一天的漲跌，和帳本同一種寫法（「11/12 漲跌」） */}
        {tw && change !== null && close.day !== "今日" && <p className="num text-sm text-ink-2">{withDayWord("今日漲跌", close.day)}</p>}
        {atLimit && <span className={cn("demo-tag font-medium", atLimit === "up" ? "border-rise text-rise" : "border-fall text-fall")}>{atLimit === "up" ? "漲停" : "跌停"}</span>}
      </div>
      <p className="num mt-1 flex flex-wrap gap-x-4 text-sm text-ink-2">
        {tw && quote && closeDay(quote.as_of) ? (
          <span>
            <span className="text-ink">收盤價</span>・{formatDateShort(closeDay(quote.as_of)!)}
          </span>
        ) : (
          <span>{quote ? asOfLabel(quote.as_of) || "—" : "—"}</span>
        )}
        {ref !== null && (
          <span>
            參考價 <span className="text-ink">{formatPrice(ref, inst.market, inst.type)}</span>
          </span>
        )}
        {limits && (
          <span>
            漲停 <span className="text-ink">{formatPrice(limits.up, inst.market, inst.type)}</span>・跌停 <span className="text-ink">{formatPrice(limits.down, inst.market, inst.type)}</span>
          </span>
        )}
        {quote?.is_demo && <span className="sm:hidden">示範資料</span>}
      </p>
      {close.note && (
        // 只在需要時出現的一行：盤中（附證交所的連結——只是連結，本站不擷取那個網站）、收盤後今天的收盤價還沒公布
        <p className="mt-1 flex flex-wrap items-center text-sm text-ink-2">
          <span>{close.note}</span>
          {close.state === "open" && (
            <>
              <span aria-hidden>・</span>
            <a
              href={twseLiveQuoteUrl(inst.code, inst.market === "TPEX" ? "TPEX" : "TWSE")}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink pointer-coarse:min-h-11"
            >
              到證交所看即時報價
              <ArrowUpRightIcon aria-hidden className="size-3.5 shrink-0" />
              <span className="sr-only">（另開新視窗）</span>
            </a>
            </>
          )}
        </p>
      )}
    </header>
  )
}

/**
 * 「為什麼漲跌」：只在異常時出現，點了交給 AI 展開。
 * 句子是規則判斷的（漲跌幅、量、漲跌停…），所以是墨色 Noto Sans、數字 600；
 * 只有後端標 `ai: true`（模型改寫過的句子，見 api-contract「/why 新增欄位」）時才是石墨灰楷體。
 */
function WhyLine({ inst }: { inst: InstrumentDetail }) {
  const why = useWhy(inst.symbol)
  const quote = useQuote(inst.symbol)
  const ask = useAskAi()
  const readOnly = useReadOnly()
  useSourceNote(sourceNotes(why.data?.show ? why.data.sources : null))
  if (!why.data?.show || !why.data.headline) return null
  const d = direction(quote.data?.change_pct)
  const modelWritten = (why.data as Why & { ai?: boolean }).ai === true
  const headline = why.data.headline
  // 模型寫的句子和對話裡的回答同一套排版（`KaiText`：漢字收字距、數字和單位不拆行）；只有一行，所以用 20px
  const text = modelWritten ? <KaiText text={headline} /> : withFigures(headline)
  const voice = modelWritten ? cn("ai-voice", kaiSize.line) : "text-base text-ink"
  if (readOnly) return <p className={cn("mt-3 max-w-prose", voice)}>{text}</p>
  // 換行交給 text-wrap: balance（兩行一樣長，最後一行不會只剩「漲 ›」）；› 前面的 word joiner（U+2060）讓 › 不會自己掉到下一行。
  // › 的顏色跟句子：規則句是淡墨，只有模型寫的石墨灰楷體句子才用石墨灰
  return (
    <button
      type="button"
      onClick={() => ask.submit(`${inText(inst.name, "start")}今天為什麼${d === "down" ? "跌" : "漲"}？`)}
      className={cn(
        // 觸控時可按範圍上下各多 10px（合計 44px 以上）：看不見的 ::before，字的位置不動
        "press mt-3 block max-w-prose text-left text-balance underline-offset-4 hover:underline pointer-coarse:relative pointer-coarse:before:absolute pointer-coarse:before:inset-x-0 pointer-coarse:before:-inset-y-2.5 pointer-coarse:before:content-['']",
        modelWritten ? "hover:decoration-ai-rule" : "hover:decoration-ctl",
        voice,
      )}
    >
      {text}
      {"⁠"}
      <ChevronRightIcon aria-hidden className={cn("ml-0.5 inline size-[1em] align-[-0.125em]", modelWritten ? "text-ai" : "text-ink-2")} />
    </button>
  )
}

/**
 * 過去的持有：現在沒有持股、但曾經買過（已出清）。每個回合一列：持有期間、已實現損益、領過股利、手續費與稅。
 * 隱私模式遮蔽金額，保留百分比與日期。
 */
function PastHolding({ inst, rounds }: { inst: InstrumentDetail; rounds: ClosedRound[] }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number, signed = false) => (privacy ? <Masked /> : formatMoney(n, { signed }))
  return (
    <section aria-labelledby="past-title" className="mt-5 border-y border-rule">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pt-2.5">
        <h2 id="past-title" className="text-base font-bold">
          過去的持有
        </h2>
        <p className="text-md text-ink">{rounds.length > 1 ? `出清過 ${rounds.length} 次` : "已全部賣出"}，不在持倉裡。</p>
        <Link
          to="/"
          search={{ view: "transactions", symbol: inst.symbol }}
          className="ml-auto inline-flex h-9 items-center rounded-sm text-sm text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink pointer-coarse:h-11"
        >
          在帳本中查看
        </Link>
      </div>
      <ul>
        {rounds.map((r) => {
          const period = holdingPeriod(r)
          return (
            <li key={`${r.account_id}-${r.opened_at}`} className="border-t border-rule py-2.5 first:border-t-0">
              <dl className="num flex flex-wrap gap-x-5 gap-y-1.5 text-base sm:gap-x-7">
                <Item label="持有期間" value={<>{period.range}<span className="ml-1.5 text-md font-normal text-ink-2">{period.days}</span></>} />
                <Item
                  label="已實現"
                  value={
                    <span className="inline-flex items-baseline gap-1.5">
                      <span className={toneClass(direction(r.realized_pnl))}>{money(r.realized_pnl, true)}</span>
                      <Pct value={r.realized_pnl_pct} className="text-md" />
                    </span>
                  }
                />
                <Item label="領過股利" value={r.dividends_received ? money(r.dividends_received) : "—"} />
                <Item label="手續費與稅" value={money(r.fees_and_taxes)} />
              </dl>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** 我的部位：兩行（股數、均價、未實現、今日、已領股利）＋展開 */
function PositionBlock({ inst, position: p, rounds, priced = true }: { inst: InstrumentDetail; position: Position; rounds: ClosedRound[]; priced?: boolean }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const ask = useAskAi()
  const readOnly = useReadOnly()
  const me = useWho("我")
  const [open, setOpen] = useState(false)
  // 「今日」損益：收盤價的日期就是今天才寫「今日」，否則寫那個日期
  const quote = useQuote(inst.symbol, priced)
  const { day } = useClose(inst.market === "US" ? null : quote.data?.as_of)
  const money = (n: number, signed = false) => formatMoney(n, { signed })
  // 均價與成交價：和報價同一套小數位；美股寫 US$（帳本的金額是新台幣，價格是美元）
  const price = (n: number | null) => `${inst.market === "US" ? "US$" : ""}${formatPrice(n, inst.market, inst.type)}`
  if (privacy) {
    return (
      <section aria-label={`${me}的部位`} className="mt-5 flex min-h-12 items-center border-y border-rule text-md text-ink-2">
        持有中・隱私模式開啟，部位與圖上的均價、買賣點已隱藏。
      </section>
    )
  }
  const recent = [...p.markers].filter((m) => m.type === "buy" || m.type === "sell").sort((a, b) => b.date.localeCompare(a.date)).slice(0, 3)
  return (
    <section aria-label={`${me}的部位`} className="mt-5 border-y border-rule">
      <div className="flex items-center gap-3 py-2.5">
        <dl className="num flex min-w-0 flex-1 flex-wrap gap-x-5 gap-y-1.5 text-base sm:gap-x-7">
          <Item label="持有" value={formatQuantity(p.quantity, unit, inst.market)} />
          <Item label="均價" value={price(p.avg_cost)} />
          {/* 沒有報價時，未實現與今日是算不出來的：不放兩個「—」（價格那一格已經說了原因） */}
          {priced && (
            <Item
              label="未實現"
              value={
                <span className="inline-flex items-baseline gap-1.5">
                  <span className={toneClass(direction(p.unrealized_pnl))}>{money(p.unrealized_pnl, true)}</span>
                  <Pct value={p.unrealized_pnl_pct} className="text-md" />
                </span>
              }
            />
          )}
          {priced && <Item className="max-sm:hidden" label={day} value={<span className={toneClass(direction(p.day_change))}>{money(p.day_change, true)}</span>} />}
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
            {priced && <Item className="sm:hidden" label={day} value={<span className={toneClass(direction(p.day_change))}>{money(p.day_change, true)}</span>} />}
            <Item className="sm:hidden" label="已領股利" value={money(p.dividends_received)} />
            <Item label={priced ? "市值" : "市值（以成本計）"} value={money(p.market_value)} />
            <Item label="成本" value={money(p.cost_basis)} />
            <Item label="已實現" value={<span className={toneClass(direction(p.realized_pnl))}>{money(p.realized_pnl, true)}</span>} />
            {/* 兩欄的格子不留落單的半格：手機上沒有報價時前面是五格，「下次除息」撐滿那一列；「之前出清過」本來就佔一整列，放最後 */}
            <Item
              className={priced ? undefined : "max-sm:col-span-2"}
              label="下次除息"
              value={p.upcoming_dividend ? `${formatDateShort(p.upcoming_dividend.ex_dividend_date, false)}・約 ${money(p.upcoming_dividend.amount_estimate)}` : "未公告"}
            />
            {rounds.length > 0 && (
              <Item
                className="col-span-2"
                label="之前出清過"
                value={
                  <>
                    {rounds.length} 次・已實現{" "}
                    <span className={toneClass(direction(rounds.reduce((x, r) => x + r.realized_pnl, 0)))}>{money(rounds.reduce((x, r) => x + r.realized_pnl, 0), true)}</span>
                  </>
                }
              />
            )}
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
                    {m.quantity !== null ? formatQuantity(m.quantity, unit, inst.market) : ""} × {price(m.price)}
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to="/" search={{ view: "transactions", symbol: inst.symbol }} className={buttonVariants({ variant: "outline", size: "sm", className: "pointer-coarse:h-11" })}>
                在帳本中查看
              </Link>
              {!readOnly && (
                <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={() => ask.action("trade", { code: inst.code })}>
                  記一筆
                </Button>
              )}
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

