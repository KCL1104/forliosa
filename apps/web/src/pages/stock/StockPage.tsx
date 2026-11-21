import { useStartReduce } from "@/pages/transactions/use-start-reduce"
import NumberFlow from "@number-flow/react"
import { inText } from "@/lib/cjk"
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router"
import { ArrowLeftIcon, ArrowUpRightIcon, ChevronDownIcon, ChevronRightIcon } from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { lazy, Suspense, useEffect, useState } from "react"
import { ApiError } from "@/api"
import { qk, useInstrument, useOverview, usePosition, usePositionHistory, useQuote, useToggleWatch, useWatchlist, useWhy } from "@/api/queries"
import type { ClosedRound, InstrumentDetail, Position, Quote, Why } from "@/api/types"
import { Masked, Pct } from "@/components/finance"
import { Tray } from "@/components/tray"
import { holdingPeriod } from "@/lib/ledger-display"
import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import { useAskAi } from "@/ai/use-ask"
import { ScrollRow } from "@/components/scroll-row"
import { DemoTag } from "@/components/section"
import { Disclaimer } from "@/components/disclaimer"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { ErrorState } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, directionGlyph, formatDateShort, formatMoney, formatPercent, formatPrice, formatQuantity, toneClass } from "@/lib/format"
import { formatQuoteChange, limitState, quoteDecimals } from "@/lib/tick"
import { quoteLimits } from "@/lib/limit-track"
import { cn } from "@/lib/utils"
import type { StockTab } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { SymbolRecords } from "@/pages/ledger/SymbolRecords"
import { asOfLabel, closeDay, twseLiveQuoteUrl, withDayWord } from "@/lib/as-of"
import { useClose } from "@/hooks/use-close"
import { useSourceNote } from "@/hooks/use-source-note"
import { LimitTrack } from "./LimitTrack"
import { PriceChart } from "./PriceChart"
import { OverviewTab, OverviewTrays } from "./tabs/OverviewTab"
import { marketLine, sourceNotes, twOpenApi, US_PRICE_KEY, useDatasetSources, useUsClosesServed, withFigures } from "./text"
import { usCloseLabel, usDay, usTradeDate } from "@/lib/labels"
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
 * 個股頁（產品負責人 2026-11-21：方向 C「圓桌」的結構、不要它的旁白）：名稱與代號（h1）在最上面，下面一盤一盤：
 * 收盤價與漲跌停軌道 → 我的持有 → 收盤價走勢 → 分頁（總覽・估值・財務・籌碼・股利・事件・討論）→（總覽）事件、相關股票、
 * 法人觀點、新聞報導、關於。頁面只有標籤和數字；句子只在 AI 面板（「為什麼」、公司簡介、法人觀點是 AI 寫的內容，照舊在原位）。
 * 持有的人先看到自己：持有緊接在價格下，圖上有均價線與買賣點（隱私模式隱藏）。
 * 各區塊用到的資料來源登記到頁尾，整頁只有一個「資料來源與授權」。
 */
export function StockPage() {
  return (
    <SourcesProvider>
      <StockPageInner />
    </SourcesProvider>
  )
}

/**
 * 美股的收盤價剛補上（報價從 404 變成有資料）時：部位、交易歷史、持股與總資產都是還沒有價格時以成本算的
 * （未實現 0、今日 0），整個 `["portfolio"]` 一起重抓。重抓完成以前回傳 true——這段時間不顯示舊的未實現與今日。
 */
function useRefreshOnFirstClose(symbol: string, noQuote: boolean, hasQuote: boolean): boolean {
  const qc = useQueryClient()
  // 哪一檔曾經沒有報價（換到別檔時不算）：render 時就記下，報價出現的那一次 render 已經知道要重抓
  const [waiting, setWaiting] = useState<string | null>(null)
  if (noQuote && waiting !== symbol) setWaiting(symbol)
  const due = !noQuote && hasQuote && waiting === symbol
  useEffect(() => {
    if (!due) return
    void qc.invalidateQueries({ queryKey: ["portfolio"] }).finally(() => setWaiting((w) => (w === symbol ? null : w)))
  }, [due, symbol, qc])
  return due
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
  // 沒有報價（還沒抓過收盤的美股）：只在價格那一格說一次；由價格算出來的區塊（走勢、估值、殖利率、未實現）都不出現。
  // 每分鐘再問一次的時候，查詢會短暫回到「載入中」（錯誤被清掉）：問過而且出錯過、還沒有資料，就還是沒有報價——
  // 不然整頁每分鐘閃一次「—」、以成本算的未實現與走勢圖
  const noQuote = !quote.data && (quote.isError || (quote.isFetching && quote.errorUpdateCount > 0))
  const refreshing = useRefreshOnFirstClose(symbol, noQuote, !!quote.data)

  if (instrument.isError) {
    const notFound = instrument.error instanceof ApiError && instrument.error.status === 404
    return (
      <div className="page-frame px-5 py-16 md:px-8 xl:px-14">
        {notFound ? (
          <div className="flex max-w-md flex-col items-start gap-3">
            <h1 className="font-print text-2xl font-bold">找不到「{symbol}」</h1>
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
    <div className="page-frame px-5 pt-1 pb-12 md:px-8 lg:pt-6 xl:px-14">
      {!inst ? (
        <HeaderSkeleton />
      ) : (
        <>
          <Breadcrumb inst={inst} held={!!position.data} />
          <StockTitle inst={inst} />
        </>
      )}

      {/* 托盤：寬的時候（主欄 ≥ 56rem）事件和相關股票並排（8＋4 欄），其他一盤一列；窄的時候一盤一列。
          每一盤同一種底色，盤與盤之間靠間距分開 */}
      <div className="@container mt-4 lg:mt-5">
        <div className="grid grid-cols-1 gap-tray-gap @4xl:grid-cols-12">
          {inst && <QuoteTray inst={inst} quote={quote.data} missing={noQuote} held={!!position.data} />}
          {inst &&
            (position.data ? (
              <HoldingTray inst={inst} position={position.data} rounds={rounds} priced={!noQuote && !refreshing} />
            ) : (
              rounds.length > 0 && <PastHolding inst={inst} rounds={rounds} />
            ))}
          {/* 還沒有收盤價（剛加入、還沒抓過的美股）：價格那一格已經說了，走勢圖整塊不放，不再說一次 */}
          {inst && !noQuote && <PriceChart inst={inst} quote={quote.data} position={position.data ?? null} markers={history.data?.markers} />}

          <Tray title="個股資料" titleHidden className="@4xl:col-span-12">
            {/* 分頁列在托盤的內容裡（不在 h2 裡）：黏在頂部列下面，只在這一盤看得到的時候；放不下時自己橫向捲動 */}
            <div className="sticky top-(--sticky-top) z-20 -mx-tray-pad -mt-tray-pad rounded-t-tray bg-paper px-tray-pad">
              <ScrollRow role="tablist" aria-label="個股資料" className="border-b border-rule sm:gap-1">
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
                        // 和按的一樣不捲回頂端（分頁列黏在上面時，用方向鍵換分頁不會跳走；2026-11-14 review）
                        void navigate({ to: "/stock/$symbol", params: { symbol }, search: { tab: next.value === "overview" ? undefined : next.value }, replace: true, resetScroll: false })
                        requestAnimationFrame(() => document.getElementById(`stock-tab-${next.value}`)?.focus())
                      }}
                      onClick={() => void navigate({ to: "/stock/$symbol", params: { symbol }, search: { tab: t.value === "overview" ? undefined : t.value }, replace: true, resetScroll: false })}
                      // 和群組頁同一種分頁：手機上每個至少 44px 寬、沒有間隔、平分整列——七個合計 308px，
                      // 393px 的手機托盤裡（321px）全部看得到；更窄的手機（320px）才捲動
                      className="sel-tab -mb-px flex h-12 min-w-11 shrink-0 items-center justify-center px-1 text-base text-ink-2 max-sm:grow sm:px-3"
                    >
                      {t.label}
                    </button>
                  )
                })}
              </ScrollRow>
            </div>
            <div id="stock-tabpanel" role="tabpanel" aria-labelledby={`stock-tab-${tab}`} className="pt-5">
              {inst ? (
                <Suspense fallback={<Skeleton className="h-72 w-full rounded-sm" />}>
                  {tab === "overview" && <OverviewTab inst={inst} quote={quote.data} position={position.data ?? null} />}
                  {tab === "valuation" && <ValuationTab inst={inst} position={position.data ?? null} noQuote={noQuote} />}
                  {tab === "financials" && <FinancialsTab inst={inst} />}
                  {tab === "chips" && <ChipsTab inst={inst} />}
                  {tab === "dividends" && <DividendsTab inst={inst} quote={quote.data} position={position.data ?? null} />}
                  {tab === "events" && <EventsTab inst={inst} position={position.data ?? null} markers={history.data?.markers ?? position.data?.markers ?? []} />}
                  {tab === "discussions" && <DiscussionsTab inst={inst} />}
                </Suspense>
              ) : (
                <Skeleton className="h-72 w-full rounded-sm" />
              )}
            </div>
          </Tray>
          {/* 總覽的其他托盤：事件、相關股票、法人觀點、新聞報導、關於（分頁托盤的兄弟，跟著版面的格子排） */}
          {inst && tab === "overview" && <OverviewTrays inst={inst} quote={quote.data} position={position.data ?? null} />}
        </div>
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
    </div>
  )
}

/**
 * 名稱與代號（h1，整頁第一個標題）＋市場・產業。名稱不截斷：長的 ETF 全名換行；
 * 代號是 h1 的一部分（螢幕閱讀器念「台積電 2330」），字小一級、淡墨，和名稱之間有空隙（C 的「台積電2330」黏在一起）。
 */
function StockTitle({ inst }: { inst: InstrumentDetail }) {
  return (
    <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <h1 className="min-w-0 font-print text-2xl font-bold [overflow-wrap:anywhere] lg:text-3xl">
        {inst.name}{" "}
        <span className="num ml-1 font-sans text-lg font-normal whitespace-nowrap text-ink-2 lg:ml-1.5 lg:text-xl">{inst.code}</span>
      </h1>
      <p className="text-sm text-ink-2">{marketLine(inst)}</p>
    </div>
  )
}

function Breadcrumb({ inst, held }: { inst: InstrumentDetail; held: boolean }) {
  const overview = useOverview(inst.symbol)
  const watch = useWatchlist()
  const toggle = useToggleWatch()
  const ask = useAskAi()
  const reduce = useStartReduce()
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
      {/* 代號與市場別寫在名稱那一行（`StockTitle`）：這一列只放返回、狀態與按鈕，任何一檔都不會把按鈕擠到下一行 */}
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
      {/* 320 寬放不下時按鈕掉到下一行：靠左，不懸在右邊 */}
      {!readOnly && <span className="ml-auto flex items-center gap-2 max-[359px]:ml-0">
        {/* 開關：開著時是單獨開關的實心記號（sel-toggle，和隱私模式同一種），不靠星號圖示表示狀態 */}
        {!held && (
          <Button
            variant="outline"
            size="sm"
            aria-pressed={watching}
            disabled={toggle.isPending}
            onClick={() => toggle.mutate({ symbol: inst.symbol, on: !watching })}
            className="sel-toggle pointer-coarse:h-11"
          >
            {watching ? "觀察中" : "加入觀察"}
          </Button>
        )}
        <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={() => ask.action("form", { code: inst.code })}>
          記一筆
        </Button>
        {/* 有持股時：賣出也在這裡（手機上不用先展開部位明細、往下捲；2026-11-14 第六次評分） */}
        {held && (
          <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={() => reduce(inst.symbol)}>
            減少持股
          </Button>
        )}
      </span>}
    </nav>
  )
}

/**
 * 收盤價那一盤：左邊是價格（收盤價・日期、漲跌、參考價；需要時多一行「預計…更新」或盤中的連結）與「為什麼」，
 * 右邊是漲跌停軌道（台股才有；美股沒有漲跌停，寫「昨收」）。托盤的標題只給螢幕閱讀器：第一行就是價格。
 * 托盤夠寬（≥ 42rem）時左右並排，窄的時候上下排。
 */
function QuoteTray({ inst, quote, missing, held = false }: { inst: InstrumentDetail; quote?: Quote; missing?: boolean; held?: boolean }) {
  // 報價下方的參考價、漲跌停每個分頁都看得到：資料集登記到頁尾（台股的收盤價由走勢圖登記）。
  // 美股的收盤價（Databento）在這裡就登記：走勢圖沒有畫出來的區間也要顯名
  const tw = twOpenApi(inst.market)
  const us = inst.market === "US"
  useDatasetSources([!!quote && tw && `${tw}/reference`, !!quote && us && US_PRICE_KEY])
  // 台股與台股 ETF：沒有盤中即時報價，價格標「收盤價・日期」；盤中、或收盤價還沒進來時，下面多一行說明
  // （還沒進來時寫這個市場預計幾點更新：上市、上櫃公布的時間不同）
  const close = useClose(tw ? quote?.as_of : null, inst.market)
  // 美股的收盤：紐約的交易日（as_of 是紐約 16:00，在台北已經是隔天早上，不寫台北的時刻）
  const usDate = us && quote ? usTradeDate(quote.trade_date, quote.as_of) : null
  if (missing && !quote) {
    // 沒有報價：整頁只在價格這一格說一次——不放一個大大的「—」，走勢圖、估值、殖利率這些由價格算出來的區塊不再各自重複
    return (
      <Tray title="收盤價" titleHidden className="@4xl:col-span-12">
        {us ? <UsNoClose key={inst.symbol} inst={inst} held={held} /> : <p className="flex min-h-12 items-center text-xl font-medium text-ink-2">沒有報價</p>}
      </Tray>
    )
  }
  const ref = quote?.reference_price ?? quote?.prev_close ?? null
  const limits = quoteLimits(quote, ref, inst.market, inst.type)
  const change = quote ? (quote.change ?? (ref !== null ? quote.price - ref : null)) : null
  const pct = quote ? (quote.change_pct ?? (ref ? quote.price / ref - 1 : null)) : null
  const d = direction(change)
  const atLimit = limitState(quote?.price, limits?.up, limits?.down)
  const digits = quote ? quoteDecimals(quote.price, inst.market, inst.type) : 0
  const track =
    quote && limits && ref !== null ? (
      <LimitTrack close={quote.price} reference={ref} up={limits.up} down={limits.down} low={quote.low} high={quote.high} market={inst.market} type={inst.type} />
    ) : null
  return (
    <Tray title="收盤價" titleHidden className="@4xl:col-span-12" bodyClassName="@container">
      <div className={cn("grid grid-cols-1 gap-y-4", track && "@2xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] @2xl:gap-x-10")}>
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <p className="hero-figure text-4xl font-medium tracking-[-0.015em] lg:text-[3rem] lg:leading-tight">
              {us && <span className="mr-1 text-xl font-normal text-ink-2">US$</span>}
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
            ) : usDate ? (
              // 美股：「11/13 收盤（美東）」——紐約的日期，不是台北的「11/14 05:00」
              <span className="text-ink">{usCloseLabel(usDate)}</span>
            ) : (
              <span>{quote ? asOfLabel(quote.as_of) || "—" : "—"}</span>
            )}
            {ref !== null && (
              // 美股沒有參考價（平盤價是台股的規則）：寫前一個交易日的收盤「昨收」，價格帶 US$
              <span>
                {us ? "昨收" : "參考價"} <span className="text-ink">{us && "US$"}{formatPrice(ref, inst.market, inst.type)}</span>
              </span>
            )}
            {/* 漲跌停軌道畫不出來時（資料對不起來：收盤落在漲跌停外面…），漲跌停照舊寫在這一行 */}
            {limits && !track && (
              <span>
                漲停 <span className="text-ink">{formatPrice(limits.up, inst.market, inst.type)}</span>・跌停 <span className="text-ink">{formatPrice(limits.down, inst.market, inst.type)}</span>
              </span>
            )}
            {quote?.is_demo && <span className="sm:hidden">示範資料</span>}
          </p>
          {close.note && (
            // 只在需要時出現的一行：盤中（附證交所的連結——只是連結，本站不擷取那個網站）、收盤價還沒進來（預計幾點更新）
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
          <WhyLine inst={inst} />
        </div>
        {track && (
          <section aria-labelledby={`limits-${inst.code}`} className="min-w-0 self-end">
            <h3 id={`limits-${inst.code}`} className="print-label mb-1 text-sm">
              漲跌停
            </h3>
            {track}
          </section>
        )}
      </div>
    </Tray>
  )
}

/** 等美股收盤價補上：每分鐘再問一次報價，最多問 30 分鐘（後端每 10 分鐘找一次新代號；Databento 不認得的代號一週後才再問） */
const US_CLOSE_POLL_MS = 60_000
const US_CLOSE_POLL_FOR_MS = 30 * 60_000

/**
 * 美股還沒有收盤價（產品負責人 2026-11-15）：美股的收盤（Databento）只抓有人觀察或持有的代號，剛加入的約 10 分鐘內
 * 補上 2024/07/01 以來的收盤。價格的位置寫「還沒有收盤價」，下一句照實說什麼時候會有——還沒加入的說要加入
 * （「加入觀察」就在上面的麵包屑），已經加入的說會補上；唯讀（查看別人的資產）時不教人加入。
 * 已經加入的每分鐘再問一次，問了 30 分鐘還沒有就停（資料源可能不認得這個代號，或暫時拒絕），不再說「約 10 分鐘內補上」。
 * 後端關掉美股收盤時（顯名清單沒有 Databento）只寫「沒有報價」，不承諾會補上。
 */
function UsNoClose({ inst, held }: { inst: InstrumentDetail; held: boolean }) {
  const served = useUsClosesServed()
  const watch = useWatchlist()
  const readOnly = useReadOnly()
  const qc = useQueryClient()
  const tracked = held || (watch.data ?? []).some((w) => w.symbol === inst.symbol)
  const [gaveUp, setGaveUp] = useState(false)
  // 已經加入、等收盤價補上：每分鐘再問一次報價（報價查詢出錯後自己不會再問），補上了整頁就換成有價格的樣子，不用重新整理
  useEffect(() => {
    if (!served || !tracked || gaveUp) return
    let waited = 0
    const timer = window.setInterval(() => {
      void qc.invalidateQueries({ queryKey: qk.quote(inst.symbol) })
      waited += US_CLOSE_POLL_MS
      if (waited >= US_CLOSE_POLL_FOR_MS) setGaveUp(true)
    }, US_CLOSE_POLL_MS)
    return () => window.clearInterval(timer)
  }, [served, tracked, gaveUp, qc, inst.symbol])
  return (
    <>
      <p className="mt-1 flex min-h-12 items-center text-xl font-medium text-ink-2 lg:min-h-15">{served ? "還沒有收盤價" : "沒有報價"}</p>
      {served && !readOnly && (
        <p className="mt-1 max-w-prose text-base text-ink">
          {!tracked
            ? "美股要在觀察清單或帳本裡才會抓收盤價。加入後約 10 分鐘內補上，從 2024/07/01 起。"
            : gaveUp
              ? "暫時抓不到這檔的收盤價。"
              : "收盤價約 10 分鐘內補上，從 2024/07/01 起。"}
        </p>
      )}
    </>
  )
}

/**
 * 「為什麼漲跌」：只在異常時出現，點了交給 AI 展開。
 * 句子是規則判斷的（漲跌幅、量、漲跌停…），所以是墨色 Noto Sans、數字 600；
 * 只有後端標 `ai: true`（模型改寫過的句子，見 api-contract「/why 新增欄位」）時才是黑體（墨色，`.ai-voice`）。
 * 模型寫的句子下面緊接一句 13px 淡墨的 `ai` 免責；規則判斷的句子是算出來的事實（漲跌幅、量），不加——頁尾的 `short` 已經涵蓋，
 * 最常看的頁首不重複同一句（2026-11-17 審查）。
 */
function WhyLine({ inst }: { inst: InstrumentDetail }) {
  const why = useWhy(inst.symbol)
  const quote = useQuote(inst.symbol)
  const ask = useAskAi()
  const readOnly = useReadOnly()
  useSourceNote(sourceNotes(why.data?.show ? why.data.sources : null))
  if (!why.data?.show || !why.data.headline) return null
  const d = direction(quote.data?.change_pct)
  // 美股的漲跌是紐約那一天的（台北已經是隔天）：問句寫日期，不寫「今天」
  const usDate = inst.market === "US" ? usTradeDate(why.data.trade_date ?? quote.data?.trade_date, why.data.as_of ?? quote.data?.as_of) : null
  // 名稱和日期之間空一格（「Apple 11/13（美東）」「輝達 11/13（美東）」）
  const lead = usDate ? `${inText(inst.name, "start").trimEnd()} ${usDay(usDate)}` : `${inText(inst.name, "start")}今天`
  const modelWritten = (why.data as Why & { ai?: boolean }).ai === true
  const headline = why.data.headline
  // 模型寫的句子和對話裡的回答同一套排版（`KaiText`：數字和單位不拆行）；只有一行，所以用 20px
  const text = modelWritten ? <KaiText text={headline} /> : withFigures(headline)
  const voice = modelWritten ? cn("ai-voice", kaiSize.line) : "text-base text-ink"
  // 觸控時按鈕的可按範圍往下多 10px：免責那一句離遠一點，不會被按成提問
  const note = modelWritten ? <Disclaimer kind="ai" className="mt-1 pointer-coarse:mt-3" /> : null
  if (readOnly)
    return (
      <>
        <p className={cn("mt-3 max-w-prose", voice)}>{text}</p>
        {note}
      </>
    )
  // 換行交給 text-wrap: balance（兩行一樣長，最後一行不會只剩「漲 ›」）；› 前面的 word joiner（U+2060）讓 › 不會自己掉到下一行。
  // › 是淡墨：規則句和模型寫的句子現在同一種字、同一個顏色（黑體、墨色）
  return (
    <>
      <button
        type="button"
        onClick={() => ask.submit(`${lead}為什麼${d === "down" ? "跌" : "漲"}？`)}
        className={cn(
          // 觸控時可按範圍上下各多 10px（合計 44px 以上）：看不見的 ::before，字的位置不動
          "press mt-3 block max-w-prose text-left text-balance underline-offset-4 hover:underline pointer-coarse:relative pointer-coarse:before:absolute pointer-coarse:before:inset-x-0 pointer-coarse:before:-inset-y-2.5 pointer-coarse:before:content-['']",
          "hover:decoration-ctl",
          voice,
        )}
      >
        {text}
        {"⁠"}
        <ChevronRightIcon aria-hidden className="ml-0.5 inline size-[1em] align-[-0.125em] text-ink-2" />
      </button>
      {note}
    </>
  )
}

/**
 * 過去的持有：現在沒有持股、但曾經買過（已出清）。每個回合一列：持有期間、已實現損益、領過股利、手續費與稅。
 * 標題旁的 meta 是「出清過 2 次」／「已全部賣出」（標籤，不寫「不在持倉裡」這種重述）。
 * 隱私模式遮蔽金額，保留百分比與日期。
 */
function PastHolding({ inst, rounds }: { inst: InstrumentDetail; rounds: ClosedRound[] }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number, signed = false) => (privacy ? <Masked /> : formatMoney(n, { signed }))
  return (
    <Tray
      title="過去的持有"
      meta={rounds.length > 1 ? `出清過 ${rounds.length} 次` : "已全部賣出"}
      className="@4xl:col-span-12"
      action={
        <Link
          to="/"
          search={{ view: "transactions", symbol: inst.symbol }}
          className="inline-flex h-9 items-center rounded-sm text-sm text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink -my-1 pointer-coarse:-my-2 pointer-coarse:h-11"
        >
          在帳本中查看
        </Link>
      }
    >
      <ul>
        {rounds.map((r) => {
          const period = holdingPeriod(r)
          return (
            <li key={`${r.account_id}-${r.opened_at}`} className="border-t border-rule py-2.5 first:border-t-0 first:pt-0">
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
    </Tray>
  )
}

/**
 * 我的持有（查看別人的資產時是「爸爸的持有」）：一行（持有、均價、未實現、今日、已領股利；手機只有前三個）＋「明細」展開
 * （今日與已領股利（手機）、市值、成本、已實現、下次除息，再來是每一筆買賣）。
 * 隱私模式：同一行，金額、股數與均價遮成 ••••，百分比照常；沒有「明細」（每一筆買賣會露出股數與價格）。
 */
function HoldingTray({ inst, position: p, rounds, priced = true }: { inst: InstrumentDetail; position: Position; rounds: ClosedRound[]; priced?: boolean }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const me = useWho("我")
  const [open, setOpen] = useState(false)
  // 「今日」損益：收盤價的日期就是今天才寫「今日」，否則寫那個日期。
  // 美股一律寫紐約的交易日（「11/13」）：那是紐約那一天的漲跌，不是台北的今天
  const quote = useQuote(inst.symbol, priced)
  const close = useClose(inst.market === "US" ? null : quote.data?.as_of, inst.market)
  const usDate = inst.market === "US" && quote.data ? usTradeDate(quote.data.trade_date, quote.data.as_of) : null
  const day = usDate ? formatDateShort(usDate, false) : close.day
  const hide = (v: React.ReactNode) => (privacy ? <Masked /> : v)
  const money = (n: number, signed = false) => formatMoney(n, { signed })
  // 均價與成交價：和報價同一套小數位；美股寫 US$（帳本的金額是新台幣，價格是美元）
  const price = (n: number | null) => `${inst.market === "US" ? "US$" : ""}${formatPrice(n, inst.market, inst.type)}`
  const details = !privacy
  return (
    <Tray
      title={`${me}的持有`}
      className="@4xl:col-span-12"
      action={
        details && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls="position-more"
            onClick={() => setOpen(!open)}
            className="press inline-flex h-9 items-center gap-0.5 rounded-sm px-1 text-sm text-ink hover:bg-hov -my-1 pointer-coarse:-my-2 pointer-coarse:h-11"
          >
            明細
            <ChevronDownIcon aria-hidden className={cn("size-4 text-ink-2 transition-transform duration-200", open && "rotate-180")} />
          </button>
        )
      }
    >
      <dl className="num flex min-w-0 flex-wrap gap-x-5 gap-y-1.5 text-base sm:gap-x-7">
        <Item label="持有" value={hide(formatQuantity(p.quantity, unit, inst.market))} />
        <Item label="均價" value={hide(price(p.avg_cost))} />
        {/* 沒有報價時，未實現與今日是算不出來的：不放兩個「—」（價格那一格已經說了原因） */}
        {priced && (
          <Item
            label="未實現"
            value={
              <span className="inline-flex items-baseline gap-1.5">
                <span className={toneClass(direction(p.unrealized_pnl))}>{hide(money(p.unrealized_pnl, true))}</span>
                <Pct value={p.unrealized_pnl_pct} className="text-md" />
              </span>
            }
          />
        )}
        {priced && <Item className={details ? "max-sm:hidden" : undefined} label={day} value={<span className={toneClass(direction(p.day_change))}>{hide(money(p.day_change, true))}</span>} />}
        <Item className={details ? "max-sm:hidden" : undefined} label="已領股利" value={hide(money(p.dividends_received))} />
      </dl>
      {details && open && (
        <div id="position-more" className="note-in mt-3 border-t border-rule pt-4">
          <dl className="num grid grid-cols-[repeat(2,minmax(0,1fr))] content-start gap-x-6 gap-y-2 text-md md:grid-cols-[repeat(4,minmax(0,1fr))]">
            {priced && <Item className="sm:hidden" label={day} value={<span className={toneClass(direction(p.day_change))}>{money(p.day_change, true)}</span>} />}
            <Item className="sm:hidden" label="已領股利" value={money(p.dividends_received)} />
            <Item label={priced ? "市值" : "市值（以成本計）"} value={money(p.market_value)} />
            <Item label="成本" value={money(p.cost_basis)} />
            <Item label="已實現" value={<span className={toneClass(direction(p.realized_pnl))}>{money(p.realized_pnl, true)}</span>} />
            {/* 兩欄的格子不留落單的半格：手機上沒有報價時前面是五格，「下次除息」撐滿那一列；「之前出清過」本來就佔一整列，放最後 */}
            <Item
              className={priced ? undefined : "max-sm:col-span-2"}
              label="下次除息"
              // 窄的手機上在日期和金額之間換行（各自不斷開），不撐寬頁面；不用「・」（換行後一行會以「・」結尾）
              value={
                p.upcoming_dividend ? (
                  <>
                    <span className="whitespace-nowrap">{formatDateShort(p.upcoming_dividend.ex_dividend_date, false)}</span> <wbr />
                    <span className="whitespace-nowrap">約 {money(p.upcoming_dividend.amount_estimate)}</span>
                  </>
                ) : (
                  "未公告"
                )
              }
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
          {/* 每一筆買賣（和持倉表展開的是同一份清單）：日期、股數、價格、金額、買進後漲跌；每一筆可以修改、刪除 */}
          <SymbolRecords
            className="mt-5"
            symbol={inst.symbol}
            code={inst.code}
            name={inst.name}
            market={inst.market}
            type={inst.type}
            price={priced ? (quote.data?.price ?? null) : null}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {/* 「記一筆」「減少持股」在標題列已經有，這裡不重複 */}
            <Link to="/" search={{ view: "transactions", symbol: inst.symbol }} className={buttonVariants({ variant: "outline", size: "sm", className: "pointer-coarse:h-11" })}>
              在帳本中查看
            </Link>
          </div>
        </div>
      )}
    </Tray>
  )
}

function Item({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 items-baseline gap-2", className)}>
      <dt className="print-label shrink-0 text-sm whitespace-nowrap">{label}</dt>
      <dd className="min-w-0 font-medium">{value}</dd>
    </div>
  )
}

