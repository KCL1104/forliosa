import { Link } from "@tanstack/react-router"
import { isCoverageNote } from "@/lib/data-notes"
import { appToday } from "@/api"
import { useChips, useCompany, useEvents, useNews, useOverview, useRevenue, useValuation } from "@/api/queries"
import type { InstrumentDetail, InstrumentOverview, MonthlyRevenue, Position, Quote, Valuation } from "@/api/types"
import { useReadOnly, useWho } from "@/api/view-as"
import { Section } from "@/components/section"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatNav, formatPremium } from "@/lib/etf-nav"
import { announcementHost, eventLabel, eventTitle, mergeAnnouncements, NEWS_CATEGORY_LABEL, type TimelineRow } from "@/lib/events"
import { formatCompact, formatDateShort, formatDaysUntil, formatMoney, formatNumber, formatPercent, formatPerShare, formatPrice, formatRevenueThousands, formatVolume } from "@/lib/format"
import { officialNews } from "@/lib/news"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { AboutCompany } from "../AboutCompany"
import { AnalystViewsCard } from "../AnalystViews"
import { EtfNavSection } from "../EtfNavSection"
import { NewsCoverage } from "../NewsCoverage"
import { useWidth } from "../month-ticks"
import { RelatedStocks } from "../RelatedStocks"
import { anchorOf, beforeSpan, labelsCollide, sourceNotes, useDatasetSources, valuationSpan, withoutKind } from "../text"
import { DateCell } from "@/components/date-cell"
import { Fig, KeyGrid, NotYet, type KeyItem } from "./kit"

/**
 * 總覽：三層。
 * 1. 分頁列正下方：一條密的格線鍵值帶——估值位置（股票）、行情與基本數字、月營收、籌碼（ETF 換成淨值與折溢價）。
 * 2. 事件：接下來的除息、營收、法說會與最近的官方公告，依日期排成一張聯絡簿。
 * 3. 安靜的參考：法人觀點（收合）、新聞報導（先 3 則）、關於〈公司〉、相關股票。
 * 資料來源不在各區塊寫，登記到頁尾（useSourceNote）。
 */
export function OverviewTab({ inst, quote, position }: { inst: InstrumentDetail; quote?: Quote; position: Position | null }) {
  const readOnly = useReadOnly()
  const band = useKeyBand(inst, quote)
  const company = useCompany(inst.symbol)
  // 只剩一兩格（美股沒有行情時只有近四季 EPS）：不在分頁列下面單獨畫一條兩條線夾著的細帶，併進「關於」的鍵值格。
  // 「關於」沒有資料可放時（公司資料載入失敗）才留在這裡寫成一行。
  const folded = band.sparse && (company.isLoading || !!company.data)
  return (
    <div className="flex flex-col">
      <KeyBand inst={inst} band={band} position={position} folded={folded} />
      {/* 鍵值帶整個沒有東西時（併到「關於」了），事件就是第一塊，上面不留 48px */}
      <Events inst={inst} position={position} className={band.empty || (folded && !band.notes) ? undefined : "mt-12"} />
      <div className="mt-14 flex flex-col gap-10">
        {/* 第三方的評等與目標價：個股才有（ETF 沒有分析師評等）；預設收合，展開才查 */}
        {inst.type === "stock" && !readOnly && <AnalystViewsCard key={inst.symbol} inst={inst} />}
        <NewsCoverage key={`news-${inst.symbol}`} inst={inst} />
        <AboutCompany key={`about-${inst.symbol}`} inst={inst} extra={folded ? band.cells : undefined} />
        <RelatedStocks key={`related-${inst.symbol}`} inst={inst} />
      </div>
    </div>
  )
}

// ── 第一層：鍵值帶 ───────────────────────────────────────

/** 鍵值帶的資料：總覽的行情與基本數字、月營收、籌碼（各自載入），只留有值的格子 */
function useKeyBand(inst: InstrumentDetail, quote: Quote | undefined) {
  const overview = useOverview(inst.symbol)
  const o = overview.data
  const us = inst.market === "US"
  const etf = inst.type === "etf"
  const valuation = useValuation(inst.symbol)
  const revenue = useRevenue(inst.symbol)
  const chips = useChips(inst.symbol, "1M")

  const showValuation = inst.type === "stock" && !us && !!valuation.data && valuation.data.per_multiples.length > 0
  const base = etf ? etfItems(inst, o, quote) : stockItems(inst, o, quote, { peInStrip: showValuation })
  const rev = !us && !etf ? revenueItems(revenue.data ?? []) : []
  const chip = !us && chips.data ? chipItems(inst, chips.data) : { items: [], note: null }
  // 只列有值的格子：資料源沒給的欄位不排一整片「—」（ETF 沒有本益比、有的股票沒有殖利率；美股沒有行情，報價下方已經說明）
  const cells = [...base, ...rev, ...chip.items].filter((it) => it.value !== "—")

  // 頁尾的資料來源：行情與估值（overview）、籌碼（融資融券、集保股權分散…）、月營收（shioaji-data 彙整的公開資訊觀測站資料）
  useSourceNote(sourceNotes(o?.sources))
  useSourceNote(sourceNotes(chip.items.length ? chips.data?.sources : null))
  useDatasetSources([rev.length > 0 && "shioaji-data/official"])

  const loading = overview.isLoading
  const notes = !!(o?.status.note || chip.note)
  return {
    cells,
    loading,
    showValuation,
    valuation: valuation.data,
    overviewEps: o?.eps_ttm ?? null,
    statusNote: o?.status.note ?? null,
    chipNote: chip.note,
    notes,
    nav: etf && !us,
    /** 只剩一兩格：不夠排成鍵值格 */
    sparse: !loading && !showValuation && cells.length > 0 && cells.length < 3,
    /** 什麼都沒有（沒有格子、估值那一行、說明與 ETF 淨值）：整個區塊不出現 */
    empty: !loading && !showValuation && cells.length === 0 && !notes && !(etf && !us),
  }
}

function KeyBand({ inst, band, position, folded }: { inst: InstrumentDetail; band: ReturnType<typeof useKeyBand>; position: Position | null; folded: boolean }) {
  const { cells } = band
  // 沒有東西可放（或那一兩格併到「關於」了、也沒有說明）：不留一個只有標題的空區塊
  if (band.empty || (folded && !band.notes)) return null
  return (
    <section id="ov-key" aria-labelledby="ov-key-title">
      <h2 id="ov-key-title" className="sr-only">
        關鍵數據
      </h2>
      {band.showValuation && (
        <ValuationStrip inst={inst} valuation={band.valuation!} overviewEps={band.overviewEps} overviewLoading={band.loading} position={position} />
      )}
      {band.loading ? (
        <Skeleton className="h-56 w-full rounded-sm" />
      ) : cells.length >= 3 ? (
        <KeyGrid items={cells} />
      ) : (
        // 只剩一兩格、而且「關於」放不了（公司資料沒有載入）：寫成一行，不在 3 欄格線裡留一格孤零零的
        cells.length > 0 &&
        !folded && (
          <p className="flex flex-wrap gap-x-6 gap-y-1 border-y border-rule py-3 text-base text-ink">
            {cells.map((it) => (
              <span key={it.label} title={it.title}>
                <span className="text-md text-ink-2">{it.label}</span> <span className="num">{it.value}</span>
              </span>
            ))}
          </p>
        )
      )}
      {band.notes && (
        <div className="mt-2 flex flex-col gap-0.5 text-sm">
          {band.statusNote && <p className="text-ink">{band.statusNote}</p>}
          {band.chipNote && <p className="text-ink-2">{band.chipNote}</p>}
        </div>
      )}
      {band.nav && <EtfNavSection inst={inst} variant="band" />}
    </section>
  )
}

const has = (n: number | null | undefined): n is number => n !== null && n !== undefined

function stockItems(inst: InstrumentDetail, o: InstrumentOverview | undefined, quote: Quote | undefined, { peInStrip }: { peInStrip: boolean }): KeyItem[] {
  const us = inst.market === "US"
  const p = (n: number | null | undefined) => formatPrice(n, inst.market, inst.type)
  // 每股金額：台股寫「元」，美股是 US$ 前綴；EPS 到分（和估值分頁同一個格式），股利照公告的位數
  const eps = (n: number) => formatPerShare(n, inst.market)
  const dividend = (n: number) => formatPerShare(n, inst.market, { dividend: true })
  // 參考價與漲跌停已經在報價下方；本益比在估值那一行（美股沒有那一行，留在格子裡）
  return [
    { label: "開盤", value: p(o?.open ?? quote?.open) },
    { label: "最高", value: p(o?.high ?? quote?.high) },
    { label: "最低", value: p(o?.low ?? quote?.low) },
    { label: "成交量", value: formatVolume(o?.volume ?? quote?.volume, inst.market, { compact: true }) },
    { label: "3 個月均量", value: formatVolume(o?.avg_volume_3m, inst.market, { compact: true }) },
    { label: "市值", value: has(o?.market_cap) ? `${us ? "US$" : ""}${formatCompact(o.market_cap)}` : "—" },
    ...(peInStrip ? [] : [{ label: "本益比", value: has(o?.pe) ? `${o.pe.toFixed(1)} 倍` : "—" }]),
    { label: "股價淨值比", value: has(o?.pb) ? `${o.pb.toFixed(2)} 倍` : "—" },
    { label: "殖利率", value: has(o?.dividend_yield) ? formatPercent(o.dividend_yield, { signed: false }) : "—" },
    { label: "近四季 EPS", value: has(o?.eps_ttm) ? eps(o.eps_ttm) : "—" },
    { label: "52 週區間", value: has(o?.low_52w) && has(o?.high_52w) ? `${p(o.low_52w)}–${p(o.high_52w)}` : "—" },
    { label: "最近現金股利", value: has(o?.last_cash_dividend) ? dividend(o.last_cash_dividend) : "—" },
    { label: "除息日", value: o?.ex_dividend_date ? formatDateShort(o.ex_dividend_date) : "—" },
  ]
}

/**
 * ETF 的鍵值：只放 ETF 有的欄位（淨值、折溢價、殖利率、配息、成交量…），
 * 不列本益比、股價淨值比、EPS 這些股票才有的數字；沒有值的格子由呼叫端濾掉。
 * 折溢價那格比較長（「溢價 0.14%」加日期），排在淨值、殖利率後面，手機上自己佔一列。
 */
function etfItems(inst: InstrumentDetail, o: InstrumentOverview | undefined, quote: Quote | undefined): KeyItem[] {
  const p = (n: number | null | undefined) => formatPrice(n, inst.market, inst.type)
  const n = o?.etf_nav
  const md = (d: string | null) => (d ? `（${formatDateShort(d, false)}）` : "")
  const nav = n && n.nav !== null ? n : null
  return [
    ...(nav ? [{ label: `淨值${md(nav.nav_date)}`, value: formatNav(nav.nav), title: nav.fund_name ?? undefined }] : []),
    { label: "殖利率", value: has(o?.dividend_yield) ? formatPercent(o.dividend_yield, { signed: false }) : "—" },
    ...(nav ? [{ label: `折溢價${md(nav.premium_date)}`, value: formatPremium(nav.premium_pct), wide: true }] : []),
    { label: "開盤", value: p(o?.open ?? quote?.open) },
    { label: "最高", value: p(o?.high ?? quote?.high) },
    { label: "最低", value: p(o?.low ?? quote?.low) },
    { label: "成交量", value: formatVolume(o?.volume ?? quote?.volume, inst.market, { compact: true }) },
    { label: "3 個月均量", value: formatVolume(o?.avg_volume_3m, inst.market, { compact: true }) },
    { label: "市值", value: has(o?.market_cap) ? formatCompact(o.market_cap) : "—" },
    { label: "52 週區間", value: has(o?.low_52w) && has(o?.high_52w) ? `${p(o.low_52w)}–${p(o.high_52w)}` : "—" },
    { label: "最近配息", value: has(o?.last_cash_dividend) ? formatPerShare(o.last_cash_dividend, inst.market, { dividend: true }) : "—" },
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
  // 資料源的空白格是 null：算不出就是「—」
  const change = (k: "margin_balance" | "short_balance") => {
    const now = m.length > 5 ? m.at(-1)![k] : null
    const before = m.length > 5 ? m.at(-6)![k] : null
    return now === null || before === null ? null : now - before
  }
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
        { label: "融資餘額", value: m.at(-1)?.margin_balance != null ? `${formatNumber(m.at(-1)!.margin_balance!)} 張` : "—" },
        { label: "融資・5 日", value: marginChange === null ? "—" : lot(marginChange), title: "近 5 個交易日的融資增減" },
        { label: "融券・5 日", value: change("short_balance") === null ? "—" : lot(change("short_balance")!), title: "近 5 個交易日的融券增減" },
        bigItem,
        ...(top ? [{ label: "外資持股", value: formatPercent(top.pct, { signed: false, decimals: 1 }), title: `證交所外資持股前 20 名第 ${top.rank} 名` }] : []),
      ],
      note: `上市${inst.type === "etf" ? " ETF " : "股票"}沒有逐檔三大法人資料${top ? `；外資持股是證交所前 20 名資料（第 ${top.rank} 名）` : ""}。`,
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

/** 本益比在這段期間的位置：0／25／50／75／100 百分位的刻度，刻度下是那個百分位的本益比 */
const TICKS = [0, 0.25, 0.5, 0.75, 1] as const

function quantile(sorted: number[], q: number): number {
  return sorted[Math.round(q * (sorted.length - 1))]!
}

/**
 * 估值位置（只說一次）：「本益比 20.8 倍，比 6/1 以來 96% 的日子貴。」＋整條寬的刻度尺。
 * 期間照資料實際的長度寫（滿 5 年才寫「過去 5 年」；商用模式的存檔從 2026-06-01 才開始累積），不滿 5 年時尺下放「資料累積中」。
 * 尺是 1px 鉛筆灰線、五個刻度（百分位），現在＝墨色實心點＋標籤，你的成本＝空心點（隱私模式不畫）。
 * 尺是 aria-hidden，成本與區間另外寫在句子裡給螢幕報讀器。
 * 位置的算法和後端相同：歷史本益比 ≤ 這個值的日子所佔比例。
 */
function ValuationStrip({
  inst,
  valuation: v,
  overviewEps,
  overviewLoading,
  position,
}: {
  inst: InstrumentDetail
  valuation: Valuation
  overviewEps: number | null
  overviewLoading: boolean
  position: Position | null
}) {
  const you = useWho("你")
  const privacy = usePrefs((s) => s.privacyMode)
  const pe = v.current.per
  const pct = v.current.per_percentile_5y
  // 近四季 EPS：用估值序列自己的（和本益比同一天），沒有才用 overview 的；兩個查詢各自載入，不能拿「還沒載入」當虧損
  const eps = v.series.at(-1)?.eps_ttm ?? overviewEps
  if (pe === null) {
    if (eps !== null && eps <= 0) {
      return (
        <p className="border-t border-rule py-3 text-base text-ink">
          近四季虧損，本益比沒有意義，改看
          <Link to="/stock/$symbol" params={{ symbol: inst.symbol }} search={{ tab: "valuation" }} resetScroll={false} className="underline decoration-ctl underline-offset-3 hover:decoration-ink">
            股價淨值比
          </Link>
          。
        </p>
      )
    }
    return overviewLoading ? <Skeleton className="mb-4 h-6 w-72 max-w-full" /> : null
  }
  const span = valuationSpan(v.series, appToday())
  const history = v.series.map((p) => p.per).filter((x): x is number => x !== null && x > 0).sort((a, b) => a - b)
  const costPe = position && !privacy && eps !== null && eps > 0 ? position.avg_cost / eps : null
  const costPct = costPe !== null && history.length ? history.filter((x) => x <= costPe).length / history.length : null
  // 成本比這段期間最便宜的那天還低（或比最貴的還高）時，點停在尺的端點，標籤要說清楚
  const costLabel =
    costPe === null || history.length === 0
      ? null
      : costPe < history[0]!
        ? `${you}的成本 ${costPe.toFixed(1)} 倍，低於${beforeSpan(span.label)}最低`
        : costPe > history.at(-1)!
          ? `${you}的成本 ${costPe.toFixed(1)} 倍，高於${beforeSpan(span.label)}最高`
          : `${you}的成本 ${costPe.toFixed(1)} 倍`
  const scale = pct !== null && history.length >= 2
  const ticks = scale ? TICKS.map((q) => quantile(history, q)) : []
  const accumulating = span.full ? null : (v.notes.find(isCoverageNote) ?? null)
  return (
    <div className="border-t border-rule pt-3 pb-4">
      <p className="text-base text-ink">
        本益比 <Fig>{pe.toFixed(1)}</Fig> 倍
        {pct !== null && (
          <>
            ，比{beforeSpan(span.label)} <Fig>{formatPercent(pct, { signed: false, decimals: 0 })}</Fig> 的日子貴
          </>
        )}
        。
        {scale && (
          <span className="sr-only">
            {span.label}最低 {ticks[0]!.toFixed(1)} 倍、最高 {ticks.at(-1)!.toFixed(1)} 倍。
          </span>
        )}
        {costLabel && <span className="sr-only">{costLabel}。</span>}
      </p>
      {scale && <PercentileScale now={pct} cost={costPct} costLabel={costLabel} ticks={ticks} />}
      {accumulating && <p className="mt-1 text-sm text-ink-2">{accumulating}</p>}
    </div>
  )
}

/** 標籤在兩端時往內對齊，不超出版面 */
const ANCHOR_CLASS = { 0: "translate-x-0", 0.5: "-translate-x-1/2", 1: "-translate-x-full" } as const
const anchor = (pos: number) => ANCHOR_CLASS[anchorOf(pos)]

function PercentileScale({ now, cost, costLabel, ticks }: { now: number; cost: number | null; costLabel: string | null; ticks: number[] }) {
  const [box, width] = useWidth<HTMLDivElement>()
  // 成本的標籤會和「現在」疊在一起時，放到刻度下面一行：用尺的實際寬度換算兩個標籤的像素範圍
  // （量到寬度之前——第一次繪製、測試環境——成本在區間外或兩點很近就先放第二行）
  const outside = cost !== null && (cost <= 0 || cost >= 1)
  const costBelow =
    cost !== null && !!costLabel && (width > 0 ? labelsCollide({ pos: now, text: "現在" }, { pos: cost, text: costLabel }, width) : outside || Math.abs(cost - now) < 0.22)
  const left = (q: number) => `${q * 100}%`
  return (
    <div ref={box} aria-hidden className={cn("relative mt-2 select-none", costBelow ? "h-[84px]" : "h-[62px]")}>
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

/** 官方公告：重大訊息、證交所公告；美股是 SEC 申報（8-K／10-Q／10-K） */
const official = (e: TimelineRow) => e.type === "announcement" || e.type === "material_info" || e.type === "sec_filing"

/**
 * 一張依日期排的表：最近 3 則官方公告（重大訊息、證交所公告、SEC 申報，連到原文）在前，接下來的 4 件事在後。
 * 日期格是聯絡簿的日期格；右欄是相對天數，持有時除息列寫可領金額。
 */
function Events({ inst, position, className }: { inst: InstrumentDetail; position: Position | null; className?: string }) {
  const you = useWho("你")
  const events = useEvents(inst.symbol)
  const news = useNews(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const today = appToday()
  const rows = mergeAnnouncements(events.data ?? [], officialNews(news.data))
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
        <Link
          to="/stock/$symbol"
          params={{ symbol: inst.symbol }}
          search={{ tab: "events" }}
          resetScroll={false}
          className="inline-flex h-8 items-center rounded-sm px-1 text-sm text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink pointer-coarse:h-11"
        >
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
        <NotYet className="border-t-0" title="目前沒有事件">
          {inst.market === "US" ? "沒有已公告的除息，最近也沒有 SEC 申報。" : "沒有已公告的除息、營收公布或法說會，最近 90 天也沒有官方公告。"}
        </NotYet>
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
  const label = announcement && e.category ? NEWS_CATEGORY_LABEL[e.category] : eventLabel(e)
  const when = formatDaysUntil(e.date, today)
  // 類別欄已經寫了「除息」，標題就不再重複（「除息 每股 5 元」→「每股 5 元」）；標題就是類別時寫說明，沒有說明就不寫類別
  const { title, kind } = withoutKind(eventTitle(e), label, e.detail)
  return (
    <li className={cn("grid grid-cols-[5.75rem_minmax(0,1fr)] items-baseline border-b border-rule sm:grid-cols-[7rem_6.5rem_minmax(0,1fr)_auto]", e.url && "relative hover:bg-hov")}>
      <DateCell date={e.date} pad="py-3" inline />
      <span className="py-3 pl-3 text-md text-ink-2 max-sm:hidden">{kind}</span>
      <span className="min-w-0 py-3 pl-3 sm:pl-0">
        {e.url ? (
          // 有原文的列：常駐的底線；連結撐滿整列（手機上整列都按得到，不只是字）
          <a href={e.url} target="_blank" rel="noreferrer" className="underline decoration-ctl underline-offset-3 after:absolute after:inset-0 hover:decoration-ink">
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
          {kind && `${kind}・`}
          {amount ? <span className="num text-ink">{amount}</span> : when}
        </span>
      </span>
      <span className={cn("num py-3 pl-3 text-right whitespace-nowrap max-sm:hidden", amount ? "text-md text-ink" : "text-sm text-ink-2")}>{amount ?? when}</span>
    </li>
  )
}

