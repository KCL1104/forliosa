import { Link } from "@tanstack/react-router"
import { appToday } from "@/api"
import { useChips, useEvents, useNews, useOverview, useRevenue, useValuation } from "@/api/queries"
import type { InstrumentDetail, InstrumentOverview, MonthlyRevenue, Position, Quote, Valuation } from "@/api/types"
import { useReadOnly, useWho } from "@/api/view-as"
import { Section } from "@/components/section"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatNav, formatPremium } from "@/lib/etf-nav"
import { announcementHost, eventLabel, eventTitle, mergeAnnouncements, NEWS_CATEGORY_LABEL, type TimelineRow } from "@/lib/events"
import { formatCompact, formatDateShort, formatDaysUntil, formatMoney, formatNumber, formatPercent, formatRevenueThousands, formatVolume } from "@/lib/format"
import { officialNews } from "@/lib/news"
import { formatQuote } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { AboutCompany } from "../AboutCompany"
import { AnalystViewsCard } from "../AnalystViews"
import { EtfNavSection } from "../EtfNavSection"
import { NewsCoverage } from "../NewsCoverage"
import { RelatedStocks } from "../RelatedStocks"
import { sourceNotes } from "../text"
import { DateCell, Fig, KeyGrid, type KeyItem } from "./kit"

/**
 * 總覽：三層。
 * 1. 分頁列正下方：一條密的格線鍵值帶——估值位置（股票）、行情與基本數字、月營收、籌碼（ETF 換成淨值與折溢價）。
 * 2. 事件：接下來的除息、營收、法說會與最近的官方公告，依日期排成一張聯絡簿。
 * 3. 安靜的參考：法人觀點（收合）、新聞報導（先 3 則）、關於〈公司〉、相關股票。
 * 資料來源不在各區塊寫，登記到頁尾（useSourceNote）。
 */
export function OverviewTab({ inst, quote, position }: { inst: InstrumentDetail; quote?: Quote; position: Position | null }) {
  const readOnly = useReadOnly()
  return (
    <div className="flex flex-col">
      <KeyBand inst={inst} quote={quote} position={position} />
      <Events inst={inst} position={position} className="mt-12" />
      <div className="mt-14 flex flex-col gap-10">
        {/* 第三方的評等與目標價：個股才有（ETF 沒有分析師評等）；預設收合，展開才查 */}
        {inst.type === "stock" && !readOnly && <AnalystViewsCard key={inst.symbol} inst={inst} />}
        <NewsCoverage key={`news-${inst.symbol}`} inst={inst} />
        <AboutCompany key={`about-${inst.symbol}`} inst={inst} />
        <RelatedStocks key={`related-${inst.symbol}`} inst={inst} />
      </div>
    </div>
  )
}

// ── 第一層：鍵值帶 ───────────────────────────────────────

function KeyBand({ inst, quote, position }: { inst: InstrumentDetail; quote?: Quote; position: Position | null }) {
  const overview = useOverview(inst.symbol)
  const o = overview.data
  const us = inst.market === "US"
  const etf = inst.type === "etf"
  const valuation = useValuation(inst.symbol)
  const revenue = useRevenue(inst.symbol)
  const chips = useChips(inst.symbol, "1M")
  useSourceNote(sourceNotes(o?.sources))

  const showValuation = inst.type === "stock" && !us && !!valuation.data && valuation.data.per_multiples.length > 0
  // 美股（商用模式沒有可商用的行情）：報價下方已經說明，格子只列有值的欄位，不排一整片「—」
  const base = (etf ? etfItems(inst, o, quote) : stockItems(inst, o, quote, { peInStrip: showValuation })).filter((it) => !us || it.value !== "—")
  const rev = !us && !etf ? revenueItems(revenue.data ?? []) : []
  const chip = !us && chips.data ? chipItems(inst, chips.data) : { items: [], note: null }
  const cells = [...base, ...rev, ...chip.items]

  return (
    <section id="ov-key" aria-label="關鍵數據">
      {showValuation && <ValuationStrip inst={inst} valuation={valuation.data!} eps={o?.eps_ttm ?? null} position={position} />}
      {overview.isLoading ? (
        <Skeleton className="h-56 w-full rounded-sm" />
      ) : (
        cells.length > 0 && <KeyGrid items={cells} />
      )}
      {(o?.status.note || chip.note) && (
        <div className="mt-2 flex flex-col gap-0.5 text-sm">
          {o?.status.note && <p className="text-ink">{o.status.note}</p>}
          {chip.note && <p className="text-ink-2">{chip.note}</p>}
        </div>
      )}
      {etf && !us && <EtfNavSection inst={inst} variant="band" />}
    </section>
  )
}

const has = (n: number | null | undefined): n is number => n !== null && n !== undefined

function stockItems(inst: InstrumentDetail, o: InstrumentOverview | undefined, quote: Quote | undefined, { peInStrip }: { peInStrip: boolean }): KeyItem[] {
  const us = inst.market === "US"
  const unit = us ? "US$" : ""
  const p = (n: number | null | undefined) => formatQuote(n, inst.market, inst.type)
  // 參考價與漲跌停已經在報價下方；本益比在估值那一行（美股沒有那一行，留在格子裡）
  return [
    { label: "開盤", value: p(o?.open ?? quote?.open) },
    { label: "最高", value: p(o?.high ?? quote?.high) },
    { label: "最低", value: p(o?.low ?? quote?.low) },
    { label: "成交量", value: formatVolume(o?.volume ?? quote?.volume, inst.market, { compact: true }) },
    { label: "3 個月均量", value: formatVolume(o?.avg_volume_3m, inst.market, { compact: true }) },
    { label: "市值", value: has(o?.market_cap) ? `${unit}${formatCompact(o.market_cap)}` : "—" },
    ...(peInStrip ? [] : [{ label: "本益比", value: has(o?.pe) ? `${o.pe.toFixed(1)} 倍` : "—" }]),
    { label: "股價淨值比", value: has(o?.pb) ? `${o.pb.toFixed(2)} 倍` : "—" },
    { label: "殖利率", value: has(o?.dividend_yield) ? formatPercent(o.dividend_yield, { signed: false }) : "—" },
    { label: "近四季 EPS", value: has(o?.eps_ttm) ? `${unit}${o.eps_ttm}` : "—" },
    { label: "52 週區間", value: has(o?.low_52w) && has(o?.high_52w) ? `${p(o.low_52w)}–${p(o.high_52w)}` : "—" },
    { label: "最近現金股利", value: has(o?.last_cash_dividend) ? `${unit}${o.last_cash_dividend}` : "—" },
    { label: "除息日", value: o?.ex_dividend_date ? formatDateShort(o.ex_dividend_date) : "—" },
  ]
}

/**
 * ETF 的鍵值：只放 ETF 有的欄位（淨值、折溢價、殖利率、配息、成交量…），
 * 不列本益比、股價淨值比、EPS 這些股票才有的數字；資料源沒給市值時不列市值。
 */
function etfItems(inst: InstrumentDetail, o: InstrumentOverview | undefined, quote: Quote | undefined): KeyItem[] {
  const p = (n: number | null | undefined) => formatQuote(n, inst.market, inst.type)
  const n = o?.etf_nav
  const md = (d: string | null) => (d ? `（${formatDateShort(d, false)}）` : "")
  const nav: KeyItem[] =
    n && n.nav !== null
      ? [
          { label: `淨值${md(n.nav_date)}`, value: formatNav(n.nav), title: n.fund_name ?? undefined },
          { label: `折溢價${md(n.premium_date)}`, value: formatPremium(n.premium_pct) },
        ]
      : []
  return [
    ...nav,
    { label: "殖利率", value: has(o?.dividend_yield) ? formatPercent(o.dividend_yield, { signed: false }) : "—" },
    { label: "開盤", value: p(o?.open ?? quote?.open) },
    { label: "最高", value: p(o?.high ?? quote?.high) },
    { label: "最低", value: p(o?.low ?? quote?.low) },
    { label: "成交量", value: formatVolume(o?.volume ?? quote?.volume, inst.market, { compact: true }) },
    { label: "3 個月均量", value: formatVolume(o?.avg_volume_3m, inst.market, { compact: true }) },
    ...(has(o?.market_cap) ? [{ label: "市值", value: formatCompact(o.market_cap) }] : []),
    { label: "52 週區間", value: has(o?.low_52w) && has(o?.high_52w) ? `${p(o.low_52w)}–${p(o.high_52w)}` : "—" },
    { label: "最近配息", value: has(o?.last_cash_dividend) ? `${o.last_cash_dividend}` : "—" },
    { label: "除息日", value: o?.ex_dividend_date ? formatDateShort(o.ex_dividend_date) : "—" },
  ]
}

function growthStreak(rows: MonthlyRevenue[]): number {
  let n = 0
  for (let i = rows.length - 1; i >= 0; i--) {
    if ((rows[i]!.yoy_pct ?? 0) > 0) n++
    else break
  }
  return n
}

/** 月營收：最新一個月、年增（連續成長幾個月併在同一格）、月增 */
function revenueItems(rows: MonthlyRevenue[]): KeyItem[] {
  const last = rows.at(-1)
  if (!last) return []
  const month = Number(last.period.slice(5))
  const streak = growthStreak(rows)
  // 年增那格帶著「連 N 個月」比較長，手機上佔滿一列，所以排在最後
  return [
    { label: `${month} 月營收`, value: formatRevenueThousands(last.revenue) },
    { label: "營收月增", value: formatPercent(last.mom_pct, { decimals: 1 }) },
    {
      label: "營收年增",
      value: (
        <>
          {formatPercent(last.yoy_pct, { decimals: 1 })}
          {streak >= 3 && <span className="ml-1.5 text-md text-ink-2">連 {streak} 個月</span>}
        </>
      ),
      title: streak >= 3 ? `年增率連續 ${streak} 個月是正的` : undefined,
      wide: streak >= 3,
    },
  ]
}

/** 籌碼（近 5 個交易日）：上市股票沒有逐檔三大法人，只列融資融券、千張大戶（與前 20 名的外資持股） */
function chipItems(inst: InstrumentDetail, c: NonNullable<ReturnType<typeof useChips>["data"]>): { items: KeyItem[]; note: string | null } {
  const listed = inst.market === "TWSE"
  if (!listed && c.institutional.length === 0) return { items: [], note: null }
  const m = c.margin
  const change = (k: "margin_balance" | "short_balance") => (m.length > 5 ? m.at(-1)![k] - m.at(-6)![k] : null)
  const marginChange = change("margin_balance")
  const bigs = (c.major_holders?.buckets ?? []).filter((b) => /^1,?000/.test(b.label ?? b.level) && /以上/.test(b.label ?? b.level))
  const big = bigs.length ? bigs.reduce((s, b) => s + b.pct, 0) : null
  const lot = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${formatCompact(Math.abs(n), 1)} 張`
  const bigItem: KeyItem = { label: "千張大戶", value: big !== null ? formatPercent(big, { signed: false, decimals: 1 }) : "—" }
  if (listed) {
    if (m.length === 0 && big === null) return { items: [], note: null }
    const top = c.foreign_top20 ?? null
    return {
      items: [
        { label: "融資餘額", value: m.length ? `${formatNumber(m.at(-1)!.margin_balance)} 張` : "—" },
        { label: "融資・5 日", value: marginChange === null ? "—" : lot(marginChange), title: "近 5 個交易日的融資增減" },
        { label: "融券・5 日", value: change("short_balance") === null ? "—" : lot(change("short_balance")!), title: "近 5 個交易日的融券增減" },
        bigItem,
        ...(top ? [{ label: "外資持股", value: formatPercent(top.pct, { signed: false, decimals: 1 }), title: `證交所外資持股前 20 名第 ${top.rank} 名` }] : []),
      ],
      note: `上市${inst.type === "etf" ? " ETF " : "股票"}不顯示逐檔三大法人${top ? `；外資持股是證交所前 20 名資料（第 ${top.rank} 名）` : ""}。`,
    }
  }
  const last5 = c.institutional.slice(-5)
  const sum = (k: "foreign" | "trust" | "dealer") => last5.reduce((s, r) => s + r[k], 0)
  return {
    items: [
      { label: "外資・5 日", value: lot(sum("foreign")), title: "近 5 個交易日的外資買賣超" },
      { label: "投信・5 日", value: lot(sum("trust")), title: "近 5 個交易日的投信買賣超" },
      { label: "自營商・5 日", value: lot(sum("dealer")), title: "近 5 個交易日的自營商買賣超" },
      { label: "融資・5 日", value: marginChange === null ? "—" : lot(marginChange), title: "近 5 個交易日的融資增減" },
      bigItem,
      { label: "外資持股", value: c.foreign_holding_pct.length ? formatPercent(c.foreign_holding_pct.at(-1)!.pct, { signed: false, decimals: 1 }) : "—" },
    ],
    note: null,
  }
}

/** 本益比在過去 5 年的位置：0／25／50／75／100 百分位的刻度，刻度下是那個百分位的本益比 */
const TICKS = [0, 0.25, 0.5, 0.75, 1] as const

function quantile(sorted: number[], q: number): number {
  return sorted[Math.round(q * (sorted.length - 1))]!
}

/**
 * 估值位置（只說一次）：「本益比 20.8 倍，比過去 5 年 96% 的日子貴。」＋整條寬的刻度尺。
 * 尺是 1px 鉛筆灰線、五個刻度（百分位），現在＝墨色實心點＋標籤，你的成本＝空心點（隱私模式不畫）。
 * 位置的算法和後端相同：歷史本益比 ≤ 這個值的日子所佔比例。
 */
function ValuationStrip({ inst, valuation: v, eps, position }: { inst: InstrumentDetail; valuation: Valuation; eps: number | null; position: Position | null }) {
  const you = useWho("你")
  const privacy = usePrefs((s) => s.privacyMode)
  const pe = v.current.per
  const pct = v.current.per_percentile_5y
  if (pe === null || !eps || eps <= 0) {
    return (
      <p className="border-t border-rule py-3 text-base text-ink">
        近四季虧損，本益比沒有意義，改看
        <Link to="/stock/$symbol" params={{ symbol: inst.symbol }} search={{ tab: "valuation" }} resetScroll={false} className="underline underline-offset-3 hover:decoration-2">
          股價淨值比
        </Link>
        。
      </p>
    )
  }
  const history = v.series.map((p) => p.per).filter((x): x is number => x !== null && x > 0).sort((a, b) => a - b)
  const costPe = position && !privacy ? position.avg_cost / eps : null
  const costPct = costPe !== null && history.length ? history.filter((x) => x <= costPe).length / history.length : null
  // 成本比 5 年裡最便宜的那天還低（或比最貴的還高）時，點停在尺的端點，標籤要說清楚
  const costLabel =
    costPe === null
      ? null
      : costPe < history[0]!
        ? `${you}的成本 ${costPe.toFixed(1)} 倍，低於 5 年最低`
        : costPe > history.at(-1)!
          ? `${you}的成本 ${costPe.toFixed(1)} 倍，高於 5 年最高`
          : `${you}的成本 ${costPe.toFixed(1)} 倍`
  const scale = pct !== null && history.length >= 2
  return (
    <div className="border-t border-rule pt-3 pb-4">
      <p className="text-base text-ink">
        本益比 <Fig>{pe.toFixed(1)}</Fig> 倍
        {pct !== null && (
          <>
            ，比過去 5 年 <Fig>{formatPercent(pct, { signed: false, decimals: 0 })}</Fig> 的日子貴
          </>
        )}
        。
      </p>
      {scale && <PercentileScale now={pct} cost={costPct} costLabel={costLabel} ticks={TICKS.map((q) => quantile(history, q))} />}
    </div>
  )
}

/** 位置在兩端時標籤往內對齊，不超出版面 */
const anchor = (pos: number) => (pos < 0.08 ? "translate-x-0" : pos > 0.92 ? "-translate-x-full" : "-translate-x-1/2")

function PercentileScale({ now, cost, costLabel, ticks }: { now: number; cost: number | null; costLabel: string | null; ticks: number[] }) {
  // 兩個標籤太近時，成本的標籤放到刻度下面一行
  const costBelow = cost !== null && Math.abs(cost - now) < 0.22
  const left = (q: number) => `${q * 100}%`
  return (
    <div aria-hidden className={cn("relative mt-2 select-none", costBelow ? "h-[84px]" : "h-[62px]")}>
      {/* 標籤列 */}
      <span className={cn("absolute top-0 text-sm font-medium whitespace-nowrap text-ink", anchor(now))} style={{ left: left(now) }}>
        現在
      </span>
      {cost !== null && costLabel && (
        <span
          className={cn("absolute text-sm whitespace-nowrap text-ink", anchor(cost), costBelow ? "top-[64px]" : "top-0")}
          style={{ left: left(cost) }}
        >
          {costLabel}
        </span>
      )}
      {/* 尺：1px 線＋五個刻度 */}
      <span className="absolute inset-x-0 top-[30px] h-px bg-ctl" />
      {TICKS.map((q) => (
        <span key={q} className="absolute top-[30px] h-[7px] w-px -translate-x-1/2 bg-ctl first:translate-x-0 last:-translate-x-full" style={{ left: left(q) }} />
      ))}
      {ticks.map((value, i) => (
        <span key={TICKS[i]} className={cn("num absolute top-[40px] text-sm whitespace-nowrap text-ink-2", anchor(TICKS[i]!))} style={{ left: left(TICKS[i]!) }}>
          {value.toFixed(1)}
          {(i === 0 || i === ticks.length - 1) && " 倍"}
        </span>
      ))}
      {/* 現在：墨色實心點＋短柄；成本：空心點 */}
      <span className="absolute top-[20px] h-[11px] w-0.5 -translate-x-1/2 bg-ink" style={{ left: left(now) }} />
      <span className="absolute top-[30px] size-[11px] -translate-1/2 rounded-full bg-ink ring-2 ring-paper" style={{ left: left(now) }} />
      {cost !== null && costLabel && (
        <>
          {!costBelow && <span className="absolute top-[20px] h-[11px] w-px -translate-x-1/2 bg-ink" style={{ left: left(cost) }} />}
          <span className="absolute top-[30px] size-[11px] -translate-1/2 rounded-full border-2 border-ink bg-paper" style={{ left: left(cost) }} />
        </>
      )}
    </div>
  )
}

// ── 第二層：事件（接下來＋最近的公告） ───────────────────

/**
 * 一張依日期排的表：最近 3 則官方公告（重大訊息、證交所公告，連到原文）在前，接下來的 4 件事在後。
 * 日期格是聯絡簿的日期格；右欄是相對天數，持有時除息列寫可領金額。
 */
function Events({ inst, position, className }: { inst: InstrumentDetail; position: Position | null; className?: string }) {
  const you = useWho("你")
  const events = useEvents(inst.symbol)
  const news = useNews(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const today = appToday()
  const rows = mergeAnnouncements(events.data ?? [], officialNews(news.data))
  const official = (e: TimelineRow) => e.type === "announcement" || e.type === "material_info"
  const past = rows
    .filter((e) => e.date < today && official(e))
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 3)
    .reverse()
  const future = rows
    .filter((e) => e.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 4)
  const shown = [...past, ...future]
  useSourceNote(sourceNotes([...new Set(shown.flatMap((e) => e.sources ?? []))]))

  return (
    <Section
      title="事件"
      titleId="ov-events"
      className={className}
      action={
        <Link to="/stock/$symbol" params={{ symbol: inst.symbol }} search={{ tab: "events" }} resetScroll={false} className="inline-flex h-8 items-center rounded-sm px-1 text-sm text-ink-2 hover:text-ink hover:underline pointer-coarse:h-10">
          所有事件
        </Link>
      }
      bodyClassName="pt-0"
    >
      {events.isLoading ? (
        <Skeleton className="mt-3 h-40 w-full rounded-sm" />
      ) : events.isError ? (
        <ErrorState className="mt-3" error={events.error} onRetry={() => void events.refetch()} />
      ) : shown.length === 0 ? (
        <p className="pt-3 text-md text-ink-2">目前沒有已公告的除息、營收公布或法說會，最近 90 天也沒有官方公告。</p>
      ) : (
        <ol>
          {shown.map((e) => (
            <EventRow key={`${e.date}-${e.type}-${e.title}`} e={e} today={today} amount={e.amount_estimate !== null && position ? `${you}可領約 ${privacy ? "••••" : formatMoney(e.amount_estimate)}` : null} />
          ))}
        </ol>
      )}
      {news.isError && !news.data && <ErrorState className="mt-3" title="公告沒有載入" error={news.error} onRetry={() => void news.refetch()} />}
    </Section>
  )
}

function EventRow({ e, today, amount }: { e: TimelineRow; today: string; amount: string | null }) {
  const announcement = e.type === "announcement" || e.type === "material_info"
  const kind = announcement && e.category ? NEWS_CATEGORY_LABEL[e.category] : eventLabel(e)
  const when = formatDaysUntil(e.date, today)
  const title = eventTitle(e)
  return (
    <li className="grid grid-cols-[5.75rem_minmax(0,1fr)] items-baseline border-b border-rule sm:grid-cols-[7rem_6.5rem_minmax(0,1fr)_auto]">
      <DateCell date={e.date} className="self-stretch py-3" />
      <span className="py-3 pl-3 text-md text-ink-2 max-sm:hidden">{kind}</span>
      <span className="min-w-0 py-3 pl-3 sm:pl-0">
        {e.url ? (
          <a href={e.url} target="_blank" rel="noreferrer" className="underline-offset-3 hover:underline">
            {title}
            <span className="sr-only">（在{announcementHost(e.url)}查看，另開新視窗）</span>
          </a>
        ) : (
          title
        )}
        {e.estimated && (
          <span className="demo-tag ml-2 align-[0.1em]" title="還沒看到實際公布日，先以法定期限顯示">
            預估
          </span>
        )}
        <span className="mt-0.5 block text-sm text-ink-2 sm:hidden">
          {kind}・{amount ? <span className="num text-ink">{amount}</span> : when}
        </span>
      </span>
      <span className={cn("num py-3 pl-3 text-right whitespace-nowrap max-sm:hidden", amount ? "text-md text-ink" : "text-sm text-ink-2")}>{amount ?? when}</span>
    </li>
  )
}

