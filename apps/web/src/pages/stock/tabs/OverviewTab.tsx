import { Link } from "@tanstack/react-router"
import { ArrowUpRightIcon, ChevronRightIcon } from "lucide-react"
import { api, appToday } from "@/api"
import { useChips, useEvents, useNews, useOverview, useRevenue, useValuation } from "@/api/queries"
import type { InstrumentDetail, MonthlyRevenue, Position, Quote } from "@/api/types"
import { DemoTag, Section } from "@/components/section"
import { Skeleton } from "@/components/ui/skeleton"
import { formatCompact, formatDateShort, formatDaysUntil, formatMoney, formatNumber, formatPercent, formatRevenueThousands, formatVolume } from "@/lib/format"
import { usePrefs } from "@/stores/prefs"
import { formatQuote } from "@/lib/tick"
import { KeyGrid, NotYet, Sources } from "./kit"

const BANDS = ["var(--band-1)", "var(--band-2)", "var(--band-3)", "var(--band-4)", "var(--band-5)"]

/** 總覽：關鍵數據、估值位置、月營收、籌碼摘要、接下來、新聞、公司 */
export function OverviewTab({ inst, quote, position }: { inst: InstrumentDetail; quote?: Quote; position: Position | null }) {
  const overview = useOverview(inst.symbol)
  const o = overview.data
  const us = inst.market === "US"
  const unit = us ? "US$" : ""
  const p = (n: number | null | undefined) => formatQuote(n, inst.market, inst.type)
  const items = [
    { label: "開盤", value: p(o?.open ?? quote?.open) },
    { label: "最高", value: p(o?.high ?? quote?.high) },
    { label: "最低", value: p(o?.low ?? quote?.low) },
    { label: "成交量", value: formatVolume(o?.volume ?? quote?.volume, inst.market, { compact: true }) },
    { label: "3 個月均量", value: formatVolume(o?.avg_volume_3m, inst.market, { compact: true }) },
    { label: "市值", value: o?.market_cap ? `${unit}${formatCompact(o.market_cap)}` : "—" },
    { label: "本益比", value: o?.pe !== null && o?.pe !== undefined ? `${o.pe.toFixed(1)} 倍` : "—", title: inst.type === "etf" ? "ETF 沒有本益比" : undefined },
    { label: "股價淨值比", value: o?.pb !== null && o?.pb !== undefined ? `${o.pb.toFixed(2)} 倍` : "—" },
    { label: "殖利率", value: o?.dividend_yield !== null && o?.dividend_yield !== undefined ? formatPercent(o.dividend_yield, { signed: false }) : "—" },
    { label: "近四季 EPS", value: o?.eps_ttm !== null && o?.eps_ttm !== undefined ? `${unit}${o.eps_ttm}` : "—" },
    { label: "52 週區間", value: o?.low_52w && o.high_52w ? `${p(o.low_52w)}–${p(o.high_52w)}` : "—" },
    { label: "參考價", value: p(o?.reference_price ?? quote?.reference_price ?? quote?.prev_close) },
    { label: "最近現金股利", value: o?.last_cash_dividend ? `${unit}${o.last_cash_dividend}` : "—" },
    { label: "除息日", value: o?.ex_dividend_date ? formatDateShort(o.ex_dividend_date) : "—" },
    { label: "漲停 / 跌停", value: o?.limit_up ? `${p(o.limit_up)} / ${p(o.limit_down)}` : us ? "美股無" : "—" },
  ]
  return (
    <div className="flex flex-col gap-10">
      <section aria-label="關鍵數據">
        {overview.isLoading ? <Skeleton className="h-56 w-full rounded-sm" /> : <KeyGrid items={items} />}
        {o?.status.note && <p className="mt-2 text-md text-ink">{o.status.note}</p>}
      </section>
      {inst.type === "stock" && !us && <ValuationSpot inst={inst} position={position} />}
      {inst.type === "etf" && !us && (
        <Section title="折溢價" titleId="ov-premium">
          <NotYet title="折溢價與追蹤誤差的資料來源還在確認">
            確認後這裡會顯示今天的市價與淨值差距、過去一年的折溢價區間。現在可以看「股利」分頁的歷年配息。
          </NotYet>
        </Section>
      )}
      <div className="grid gap-10 lg:grid-cols-2">
        {!us && inst.type === "stock" && <RevenueBrief symbol={inst.symbol} />}
        {!us && <ChipsBrief symbol={inst.symbol} />}
      </div>
      <Upcoming inst={inst} position={position} />
      <News symbol={inst.symbol} />
      <Company inst={inst} sources={o?.sources ?? inst.data_sources} />
    </div>
  )
}

function bandIndex(ratio: number, multiples: number[]): number {
  // 0..5 的連續位置：在第 i 與 i+1 倍數之間時為 i + 比例
  if (ratio <= multiples[0]!) return Math.max(0, ratio / multiples[0]!) * 0.5
  for (let i = 0; i < multiples.length - 1; i++) {
    if (ratio < multiples[i + 1]!) return 0.5 + i + (ratio - multiples[i]!) / (multiples[i + 1]! - multiples[i]!)
  }
  return Math.min(multiples.length, multiples.length - 0.5 + (ratio - multiples.at(-1)!) / multiples.at(-1)!)
}

/** 估值位置：一句話＋便宜→昂貴的色階條，標出「現在」與「你的成本」 */
function ValuationSpot({ inst, position }: { inst: InstrumentDetail; position: Position | null }) {
  const valuation = useValuation(inst.symbol)
  const overview = useOverview(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const v = valuation.data
  const eps = overview.data?.eps_ttm ?? null
  const pe = v?.current.per ?? null
  if (!v || v.per_multiples.length === 0) return null
  if (pe === null || !eps || eps <= 0) {
    return (
      <Section title="估值位置" titleId="ov-val" action={<MoreLink symbol={inst.symbol} tab="valuation" />}>
        <p className="ai-voice text-xl">近四季虧損，本益比沒有意義，改看股價淨值比。</p>
      </Section>
    )
  }
  const m = v.per_multiples
  const idx = m.findIndex((x) => pe < x)
  const bracket = idx === 0 ? `${m[0]} 倍以下` : idx === -1 ? `${m.at(-1)} 倍以上` : `${m[idx - 1]}–${m[idx]} 倍`
  const costPe = position ? position.avg_cost / eps : null
  const nowPos = (bandIndex(pe, m) / m.length) * 100
  const costPos = costPe !== null ? (bandIndex(costPe, m) / m.length) * 100 : null
  return (
    <Section title="估值位置" titleId="ov-val" action={<MoreLink symbol={inst.symbol} tab="valuation" />}>
      <p className="ai-voice text-xl leading-snug">
        本益比 {pe.toFixed(1)} 倍，在 {bracket}的帶
        {v.current.per_percentile_5y !== null && `；過去 5 年有 ${formatPercent(v.current.per_percentile_5y, { signed: false, decimals: 0 })} 的日子比現在便宜`}
        {costPe !== null && !privacy && `。你的成本約 ${costPe.toFixed(1)} 倍`}。
      </p>
      <div className="mt-4 max-w-xl">
        <div className="relative pt-6 pb-6">
          <div className="flex h-3 overflow-hidden" aria-hidden>
            {m.map((x, i) => (
              <span key={x} className="flex-1 border-r border-paper last:border-0" style={{ background: BANDS[i] }} />
            ))}
          </div>
          <span className="absolute top-0 -translate-x-1/2 text-center text-xs whitespace-nowrap text-ink" style={{ left: `${nowPos}%` }}>
            現在 ▼
          </span>
          {costPos !== null && !privacy && (
            <span className="absolute bottom-0 -translate-x-1/2 text-xs whitespace-nowrap text-ink-2" style={{ left: `${costPos}%` }}>
              △ 你的成本
            </span>
          )}
        </div>
        <div className="flex justify-between text-xs text-ink-2">
          <span>便宜（{m[0]} 倍）</span>
          <span>昂貴（{m.at(-1)} 倍）</span>
        </div>
      </div>
    </Section>
  )
}

function MoreLink({ symbol, tab, label = "看更多" }: { symbol: string; tab: "valuation" | "financials" | "chips" | "events" | "dividends"; label?: string }) {
  return (
    <Link to="/stock/$symbol" params={{ symbol }} search={{ tab }} resetScroll={false} className="inline-flex h-8 items-center gap-0.5 rounded-sm px-1 text-sm text-ink-2 hover:text-ink pointer-coarse:h-10">
      {label}
      <ChevronRightIcon aria-hidden className="size-4" />
    </Link>
  )
}

function growthStreak(rows: MonthlyRevenue[]): number {
  let n = 0
  for (let i = rows.length - 1; i >= 0; i--) {
    if ((rows[i]!.yoy_pct ?? 0) > 0) n++
    else break
  }
  return n
}

function RevenueBrief({ symbol }: { symbol: string }) {
  const revenue = useRevenue(symbol)
  const rows = (revenue.data ?? []).slice(-12)
  const last = rows.at(-1)
  if (revenue.isLoading) return <Skeleton className="h-40 w-full rounded-sm" />
  if (!last) return null
  const max = Math.max(...rows.map((r) => r.revenue))
  const streak = growthStreak(revenue.data ?? [])
  const month = Number(last.period.slice(5))
  return (
    <Section title="月營收" titleId="ov-rev" action={<MoreLink symbol={symbol} tab="financials" />}>
      <p className="num text-base">
        {month} 月 <span className="font-medium">{formatRevenueThousands(last.revenue)}</span>
        <span className="ml-3 text-ink-2">年增</span> {formatPercent(last.yoy_pct, { decimals: 1 })}
        <span className="ml-3 text-ink-2">月增</span> {formatPercent(last.mom_pct, { decimals: 1 })}
      </p>
      {streak >= 3 && <p className="ai-voice mt-1 text-lg">年增率連續 {streak} 個月是正的。</p>}
      <div className="mt-3 flex h-20 items-end gap-1" role="img" aria-label={`近 12 個月營收，最新 ${month} 月 ${formatRevenueThousands(last.revenue)}`}>
        {rows.map((r) => (
          <span key={r.period} className="flex-1" style={{ height: `${Math.max(4, (r.revenue / max) * 100)}%`, background: r === last ? "var(--ink)" : "var(--band-4)" }} title={`${r.period}：${formatRevenueThousands(r.revenue)}`} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-xs text-ink-2">
        <span>{rows[0]!.period.replace("-", "/")}</span>
        <span>{last.period.replace("-", "/")}</span>
      </div>
    </Section>
  )
}

function ChipsBrief({ symbol }: { symbol: string }) {
  const chips = useChips(symbol, "1M")
  const c = chips.data
  if (chips.isLoading) return <Skeleton className="h-40 w-full rounded-sm" />
  if (!c || c.institutional.length === 0) return null
  const last5 = c.institutional.slice(-5)
  const sum = (k: "foreign" | "trust" | "dealer") => last5.reduce((s, r) => s + r[k], 0)
  const m = c.margin
  const marginChange = m.length > 5 ? m.at(-1)!.margin_balance - m.at(-6)!.margin_balance : null
  const bigs = (c.major_holders?.buckets ?? []).filter((b) => /^1,?000/.test(b.label ?? b.level) && /以上/.test(b.label ?? b.level))
  const big = bigs.length ? { pct: bigs.reduce((s, b) => s + b.pct, 0) } : undefined
  const lot = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${formatCompact(Math.abs(n), 1)} 張`
  return (
    <Section title="籌碼" titleId="ov-chips" aside="近 5 個交易日" action={<MoreLink symbol={symbol} tab="chips" />}>
      <KeyGrid
        cols={2}
        className="lg:grid-cols-2"
        items={[
          { label: "外資", value: lot(sum("foreign")) },
          { label: "投信", value: lot(sum("trust")) },
          { label: "自營商", value: lot(sum("dealer")) },
          { label: "融資增減", value: marginChange === null ? "—" : lot(marginChange) },
          { label: "千張大戶", value: big ? formatPercent(big.pct, { signed: false, decimals: 1 }) : "—" },
          { label: "外資持股", value: c.foreign_holding_pct.length ? formatPercent(c.foreign_holding_pct.at(-1)!.pct, { signed: false, decimals: 1 }) : "—" },
        ]}
      />
    </Section>
  )
}

const EVENT_LABEL: Record<string, string> = {
  ex_dividend: "除息",
  dividend_payment: "股利發放",
  earnings: "法說會",
  revenue_release: "營收公布",
  material_info: "重大訊息",
  attention: "注意股",
  disposition: "處置",
  shareholder_meeting: "股東會",
}

function Upcoming({ inst, position }: { inst: InstrumentDetail; position: Position | null }) {
  const events = useEvents(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const today = appToday()
  const future = (events.data ?? []).filter((e) => e.date >= today).sort((a, b) => a.date.localeCompare(b.date)).slice(0, 4)
  if (events.isLoading) return <Skeleton className="h-28 w-full rounded-sm" />
  return (
    <Section title="接下來" titleId="ov-next" action={<MoreLink symbol={inst.symbol} tab="events" label="所有事件" />}>
      {future.length === 0 ? (
        <p className="text-md text-ink-2">目前沒有已公告的除息、營收公布或法說會。</p>
      ) : (
        <ul className="-mt-3">
          {future.map((e) => (
            <li key={`${e.date}-${e.type}-${e.title}`} className="grid grid-cols-[88px_1fr_auto] items-baseline gap-3 border-b border-rule py-2.5 sm:grid-cols-[120px_88px_1fr_auto]">
              <span className="num">
                {formatDateShort(e.date)}
                <span className="block text-xs text-ink-2 sm:hidden">{formatDaysUntil(e.date, today)}</span>
              </span>
              <span className="text-md text-ink-2 max-sm:hidden">{EVENT_LABEL[e.type] ?? e.type}</span>
              <span className="min-w-0">{e.title}</span>
              <span className="num text-right text-md">
                {e.amount_estimate !== null && position ? (
                  <>你可領約 {privacy ? "••••" : formatMoney(e.amount_estimate)}</>
                ) : (
                  <span className="text-ink-2 max-sm:hidden">{formatDaysUntil(e.date, today)}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function timeAgo(iso: string): string {
  const h = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 3_600_000))
  if (h < 1) return "剛剛"
  if (h < 24) return `${h} 小時前`
  const d = Math.round(h / 24)
  return d < 30 ? `${d} 天前` : formatDateShort(iso.slice(0, 10), false)
}

function News({ symbol }: { symbol: string }) {
  const news = useNews(symbol)
  const rows = (news.data ?? []).slice(0, 3)
  if (news.isLoading) return <Skeleton className="h-28 w-full rounded-sm" />
  return (
    <Section title="新聞" titleId="ov-news" action={api.kind === "mock" ? <DemoTag title="示範標題，不是真實新聞" /> : undefined}>
      {rows.length === 0 ? (
        <p className="text-md text-ink-2">目前沒有可顯示的新聞（只使用可合法轉載的來源）。</p>
      ) : (
        <ul className="-mt-3">
          {rows.map((n) => (
            <li key={n.url} className="border-b border-rule">
              <a href={n.url} target="_blank" rel="noreferrer" className="group flex items-baseline gap-3 py-3">
                <span className="min-w-0 flex-1 group-hover:underline">{n.title}</span>
                <span className="shrink-0 text-sm text-ink-2">
                  {n.source}・{timeAgo(n.published_at)}
                </span>
                <ArrowUpRightIcon aria-hidden className="size-3.5 shrink-0 self-center text-ink-2" />
                <span className="sr-only">（另開新視窗）</span>
              </a>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-ink-2">只列標題、來源與連結；內容以原文為準。</p>
    </Section>
  )
}

function Company({ inst, sources }: { inst: InstrumentDetail; sources: string[] }) {
  return (
    <Section title="公司" titleId="ov-company">
      {inst.summary && <p className="max-w-prose text-base">{inst.summary}</p>}
      <dl className="mt-3 grid max-w-prose gap-1 text-md">
        {inst.chain_stage && (
          <div className="flex gap-3">
            <dt className="w-20 shrink-0 text-ink-2">產業鏈</dt>
            <dd>{inst.chain_stage}</dd>
          </div>
        )}
        {inst.themes.length > 0 && (
          <div className="flex gap-3">
            <dt className="w-20 shrink-0 text-ink-2">題材</dt>
            <dd>{inst.themes.join("・")}</dd>
          </div>
        )}
        {inst.shares_outstanding && (
          <div className="flex gap-3">
            <dt className="w-20 shrink-0 text-ink-2">發行股數</dt>
            <dd className="num">{formatNumber(Math.round(inst.shares_outstanding / 1000))} 張</dd>
          </div>
        )}
      </dl>
      <Sources items={sources} />
    </Section>
  )
}
