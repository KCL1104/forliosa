import { Link } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { api } from "@/api"
import { useDividends, useHoldings, useRevenue, useValuation } from "@/api/queries"
import type { InstrumentDetail, Quote } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { AXIS_TICK, ChartTooltipBox, GRID_STROKE, monthTick } from "@/components/charts/chart-kit"
import { Chop, DemoChop, SoonChop } from "@/components/chop"
import { Money, Pct, Price, Quantity } from "@/components/finance"
import { Panel } from "@/components/section"
import { ChartSkeleton, EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import {
  formatCompact,
  formatDate,
  formatMoney,
  formatNumber,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatRevenueThousands,
} from "@/lib/format"
import { usePrefs } from "@/stores/prefs"
import { TYPE_LABEL } from "@/pages/transactions/TradeForm"

const MARKET_LABEL = { TWSE: "上市", TPEX: "上櫃", US: "美股" } as const

// ── 總覽 ─────────────────────────────────────────────────
export function OverviewTab({ instrument, quote }: { instrument: InstrumentDetail; quote?: Quote }) {
  const valuation = useValuation(instrument.symbol)
  const cur = valuation.data?.current
  const m = instrument.market
  const stats: [string, React.ReactNode][] = quote
    ? [
        ["開盤", <Price value={quote.open} market={m} />],
        ["最高", <Price value={quote.high} market={m} />],
        ["最低", <Price value={quote.low} market={m} />],
        ["昨收", <Price value={quote.prev_close} market={m} />],
        ["成交量", <span className="num">{m === "US" ? `${formatCompact(quote.volume)} 股` : `${formatNumber(Math.round(quote.volume / 1000))} 張`}</span>],
        ["市值", instrument.market_cap ? <span className="num">{m === "US" ? "US$" : "NT$"}{formatCompact(instrument.market_cap)}</span> : "—"],
        ["本益比", cur?.per != null ? <span className="num">{cur.per.toFixed(1)} 倍</span> : "—"],
        ["股價淨值比", cur?.pbr != null ? <span className="num">{cur.pbr.toFixed(2)} 倍</span> : "—"],
        ["殖利率", cur?.dividend_yield != null ? <span className="num">{formatPercent(cur.dividend_yield, { signed: false })}</span> : "—"],
      ]
    : []
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Panel title="關鍵數字" titleId="kv-title">
        {!quote ? (
          <SkeletonLines rows={5} />
        ) : (
          <dl className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
            {stats.map(([k, v]) => (
              <div key={k} className="flex flex-col gap-0.5 border-b border-hairline py-2.5">
                <dt className="text-sm text-muted-foreground">{k}</dt>
                <dd className="text-base font-medium">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </Panel>
      <Panel title="公司小卡" titleId="company-title">
        <div className="flex flex-col gap-4">
          <p className="max-w-prose text-md">{instrument.summary ?? "目前沒有這家公司的簡介。"}</p>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-md">
            <dt className="text-muted-foreground">市場</dt>
            <dd>{MARKET_LABEL[instrument.market]}{instrument.type === "etf" ? "・ETF" : ""}</dd>
            {instrument.industry && (
              <>
                <dt className="text-muted-foreground">產業</dt>
                <dd>{instrument.industry}</dd>
              </>
            )}
            {instrument.chain_stage && (
              <>
                <dt className="text-muted-foreground">產業鏈位置</dt>
                <dd>{instrument.chain_stage}</dd>
              </>
            )}
            {instrument.themes.length > 0 && (
              <>
                <dt className="text-muted-foreground">題材</dt>
                <dd className="flex flex-wrap gap-1.5">
                  {instrument.themes.map((t) => (
                    <span key={t} className="rounded-md border bg-muted/50 px-2 py-0.5 text-sm">{t}</span>
                  ))}
                </dd>
              </>
            )}
          </dl>
          <p className="text-xs text-muted-foreground">資料來源：{instrument.data_sources.join("；")}</p>
        </div>
      </Panel>
    </div>
  )
}

// ── 財務：月營收（兩張圖，不用雙軸） ─────────────────────────
export function FinancialsTab({ instrument }: { instrument: InstrumentDetail }) {
  const revenue = useRevenue(instrument.symbol)
  if (instrument.market === "US")
    return <EmptyState title="美股財務資料規劃中" description="目前財務分頁先支援台股月營收（公開資訊觀測站）。美股季報資料來源還在評估。" />
  if (instrument.type === "etf") return <EmptyState title="ETF 沒有月營收" description="ETF 不是公司，沒有營收與財報。可以看「股利」分頁的配息紀錄。" />
  if (revenue.isError) return <ErrorState error={revenue.error} onRetry={() => void revenue.refetch()} />
  if (!revenue.data) return <ChartSkeleton height={360} />
  const data = revenue.data.slice(-24)
  if (data.length === 0) return <EmptyState title="還沒有月營收資料" />
  const latest = data.at(-1)!
  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="月營收"
        titleId="rev-title"
        aside={<span className="text-sm text-muted-foreground">單位：新台幣</span>}
      >
        <dl className="mb-3 flex flex-wrap gap-x-8 gap-y-2">
          <div>
            <dt className="text-sm text-muted-foreground">{latest.period.replace("-", " 年 ")} 月營收</dt>
            <dd className="num text-xl font-semibold">{formatRevenueThousands(latest.revenue)}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">年增率</dt>
            <dd className="text-xl font-semibold"><Pct value={latest.yoy_pct} /></dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">月增率</dt>
            <dd className="text-xl font-semibold"><Pct value={latest.mom_pct} /></dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">今年累計年增</dt>
            <dd className="text-xl font-semibold"><Pct value={latest.ytd_yoy_pct} /></dd>
          </div>
        </dl>
        <div className="h-[220px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap={3}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="period" tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={monthTick} minTickGap={16} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={64} tickFormatter={(n: number) => formatCompact(n * 1000, 0)} />
              <Tooltip
                cursor={{ fill: "var(--muted)" }}
                content={({ active, payload }) => {
                  const r = active ? (payload?.[0]?.payload as (typeof data)[number] | undefined) : undefined
                  return r ? (
                    <ChartTooltipBox
                      title={r.period.replace("-", "/")}
                      rows={[
                        { label: "營收", value: formatRevenueThousands(r.revenue), color: "var(--chart-1)" },
                        { label: "年增率", value: formatPercent(r.yoy_pct) },
                        { label: "月增率", value: formatPercent(r.mom_pct) },
                      ]}
                    />
                  ) : null
                }}
              />
              <Bar dataKey="revenue" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                {data.map((r) => (
                  <Cell key={r.period} fill={r === latest ? "var(--chart-1)" : "var(--chart-6)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <h3 className="mt-4 text-md font-medium">年增率</h3>
        <div className="h-[140px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="period" tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={monthTick} minTickGap={16} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={64} tickFormatter={(n: number) => formatPercent(n, { decimals: 0 })} />
              <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeWidth={1} />
              <Tooltip
                cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
                content={({ active, payload }) => {
                  const r = active ? (payload?.[0]?.payload as (typeof data)[number] | undefined) : undefined
                  return r ? <ChartTooltipBox title={r.period.replace("-", "/")} rows={[{ label: "年增率", value: formatPercent(r.yoy_pct) }]} /> : null
                }}
              />
              <Line dataKey="yoy_pct" stroke="var(--chart-3)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <Panel title="月營收明細" titleId="rev-table">
        <div className="-mx-4 overflow-x-auto sm:-mx-5">
          <table className="w-full min-w-[560px] text-md">
            <thead className="border-b text-sm text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-2 text-left font-medium sm:px-5">月份</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">營收</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">月增</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">年增</th>
                <th scope="col" className="px-4 py-2 text-right font-medium sm:px-5">累計年增</th>
              </tr>
            </thead>
            <tbody>
              {[...data].reverse().slice(0, 12).map((r) => (
                <tr key={r.period} className="border-b border-hairline last:border-0">
                  <th scope="row" className="num px-4 py-2 text-left font-normal sm:px-5">{r.period.replace("-", "/")}</th>
                  <td className="num px-3 text-right">{formatRevenueThousands(r.revenue)}</td>
                  <td className="px-3 text-right"><Pct value={r.mom_pct} glyph={false} /></td>
                  <td className="px-3 text-right"><Pct value={r.yoy_pct} glyph={false} /></td>
                  <td className="px-4 text-right sm:px-5"><Pct value={r.ytd_yoy_pct} glyph={false} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">季 EPS、毛利率與三大報表重點會在 M2 後續版本加入。</p>
      </Panel>
    </div>
  )
}

// ── 股利 ─────────────────────────────────────────────────
export function DividendsTab({ instrument, quote, today }: { instrument: InstrumentDetail; quote?: Quote; today: string }) {
  const dividends = useDividends(instrument.symbol)
  if (dividends.isError) return <ErrorState error={dividends.error} onRetry={() => void dividends.refetch()} />
  if (!dividends.data) return <SkeletonLines rows={6} />
  const list = dividends.data
  if (list.length === 0) return <EmptyState title="沒有配息紀錄" description="這檔近年沒有發放現金或股票股利。" />
  const upcoming = list.filter((d) => d.ex_dividend_date && d.ex_dividend_date >= today)
  const byYear = new Map<number, number>()
  for (const d of list) byYear.set(d.year, (byYear.get(d.year) ?? 0) + d.cash_dividend)
  const years = [...byYear.entries()].sort((a, b) => a[0] - b[0]).map(([year, cash]) => ({ year: String(year), cash }))
  const unit = instrument.market === "US" ? "美元" : "元"
  return (
    <div className="flex flex-col gap-4">
      {upcoming.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-primary/30 bg-accent px-4 py-3">
          <Chop>即將除息</Chop>
          {upcoming.map((d) => (
            <span key={d.period} className="text-md">
              <span className="num font-medium">{formatDate(d.ex_dividend_date!)}</span> 除息，每股 <span className="num font-medium">{d.cash_dividend}</span> {unit}
              {quote && <span className="text-muted-foreground">（以現價計殖利率 {formatPercent(d.cash_dividend / quote.price, { signed: false })}）</span>}
            </span>
          ))}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Panel title="每年現金股利" titleId="div-year" aside={<span className="text-sm text-muted-foreground">每股（{unit}）</span>}>
          <div className="h-[220px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={years} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={GRID_STROKE} />
                <XAxis dataKey="year" tick={AXIS_TICK} tickLine={false} axisLine={false} />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={40} />
                <Tooltip
                  cursor={{ fill: "var(--muted)" }}
                  content={({ active, payload }) => {
                    const r = active ? (payload?.[0]?.payload as (typeof years)[number] | undefined) : undefined
                    return r ? <ChartTooltipBox title={`${r.year} 年`} rows={[{ label: "現金股利", value: `${r.cash.toFixed(2)} ${unit}`, color: "var(--chart-1)" }]} /> : null
                  }}
                />
                <Bar dataKey="cash" fill="var(--chart-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} maxBarSize={48} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">依股利所屬年度加總；季配息會合併為一年。</p>
        </Panel>
        <Panel title="配息紀錄" titleId="div-list">
          <div className="-mx-4 overflow-x-auto sm:-mx-5">
            <table className="w-full min-w-[480px] text-md">
              <thead className="border-b text-sm text-muted-foreground">
                <tr>
                  <th scope="col" className="px-4 py-2 text-left font-medium sm:px-5">期別</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">現金股利</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">股票股利</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">除息日</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium sm:px-5">發放日</th>
                </tr>
              </thead>
              <tbody>
                {list.map((d) => (
                  <tr key={d.period} className="border-b border-hairline last:border-0">
                    <th scope="row" className="num px-4 py-2 text-left font-normal sm:px-5">{d.period}</th>
                    <td className="num px-3 text-right">{d.cash_dividend.toFixed(d.cash_dividend < 1 ? 3 : 2)}</td>
                    <td className="num px-3 text-right text-muted-foreground">{d.stock_dividend ? d.stock_dividend.toFixed(2) : "—"}</td>
                    <td className="num px-3 text-right">{d.ex_dividend_date ? formatDate(d.ex_dividend_date) : "未配息"}</td>
                    <td className="num px-4 text-right sm:px-5">{d.payment_date ? formatDate(d.payment_date) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">填息天數會在除權息資料接上後提供（M2）。</p>
        </Panel>
      </div>
    </div>
  )
}

// ── 我的交易 ──────────────────────────────────────────────
export function MyTradesTab({ instrument }: { instrument: InstrumentDetail }) {
  const holdings = useHoldings()
  const unit = usePrefs((s) => s.quantityUnit)
  const openTradeForm = useUi((s) => s.openTradeForm)
  const txns = useQuery({
    queryKey: ["transactions", { symbol: instrument.symbol, limit: 200 }],
    queryFn: () => api.listTransactions({ symbol: instrument.symbol, limit: 200 }),
  })
  const h = holdings.data?.find((x) => x.symbol === instrument.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="我的持有"
        titleId="mine-title"
        action={
          <Button size="sm" variant="outline" onClick={() => openTradeForm({ symbol: instrument.symbol })}>
            <PlusIcon />
            記一筆 {instrument.name}
          </Button>
        }
      >
        {!holdings.data ? (
          <SkeletonLines rows={2} />
        ) : !h ? (
          <p className="text-md text-muted-foreground">目前沒有持有{instrument.name}。</p>
        ) : (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            <div><dt className="text-sm text-muted-foreground">股數</dt><dd className="text-lg font-semibold"><Quantity shares={h.quantity} market={h.market} /></dd></div>
            <div><dt className="text-sm text-muted-foreground">均價（含手續費）</dt><dd className="text-lg font-semibold"><Price value={h.avg_cost} market={h.market} /></dd></div>
            <div><dt className="text-sm text-muted-foreground">市值</dt><dd className="text-lg font-semibold"><Money value={h.market_value} /></dd></div>
            <div>
              <dt className="text-sm text-muted-foreground">未實現損益</dt>
              <dd className="flex flex-wrap items-baseline gap-x-2 text-lg font-semibold"><Money value={h.unrealized_pnl} signed tone /><Pct value={h.unrealized_pnl_pct} className="text-md" /></dd>
            </div>
          </dl>
        )}
      </Panel>
      <Panel title="交易紀錄" titleId="mine-list" aside={txns.data && <span className="text-sm text-muted-foreground">{txns.data.items.length} 筆</span>}>
        {txns.isError ? (
          <ErrorState error={txns.error} onRetry={() => void txns.refetch()} />
        ) : !txns.data ? (
          <SkeletonLines rows={4} />
        ) : txns.data.items.length === 0 ? (
          <p className="text-md text-muted-foreground">還沒有這檔的交易紀錄。</p>
        ) : (
          <ul className="flex flex-col divide-y divide-hairline">
            {txns.data.items.slice(0, 30).map((t) => (
              <li key={t.id} className="grid grid-cols-[88px_minmax(0,1fr)_auto] items-center gap-3 py-2 text-md">
                <span className="num text-muted-foreground">{formatDate(t.trade_date)}</span>
                <span className="flex min-w-0 items-center gap-2">
                  <Chop tone={t.type === "buy" || t.type === "sell" ? "ink" : "muted"}>{TYPE_LABEL[t.type]}</Chop>
                  <span className="num truncate">
                    {privacy ? "••••" : t.quantity !== null ? formatQuantity(t.quantity, unit, instrument.market) : ""}
                    {t.price !== null && t.type !== "split" ? ` @ ${formatPrice(t.price, instrument.market)}` : ""}
                  </span>
                </span>
                <span className="num text-right">{privacy ? "••••" : formatMoney(t.amount, { currency: t.currency })}</span>
              </li>
            ))}
          </ul>
        )}
        <Link to="/transactions" className="mt-3 inline-block text-sm text-primary underline-offset-4 hover:underline">
          到交易紀錄看全部
        </Link>
      </Panel>
    </div>
  )
}

// ── 即將推出 ──────────────────────────────────────────────
const COMING: Record<"chips" | "news" | "ai", { title: string; milestone: string; body: string; items: string[] }> = {
  chips: {
    title: "籌碼",
    milestone: "M2",
    body: "看法人與大戶怎麼動：資料來自證交所、櫃買中心與集保結算所。",
    items: ["三大法人每日買賣超與連買連賣天數", "融資融券餘額與使用率", "集保股權分散：千張大戶持股比例的週變化"],
  },
  news: {
    title: "新聞",
    milestone: "M2",
    body: "和這檔股票有關的新聞，依時間排序，標示來源。",
    items: ["個股新聞與公告", "重大訊息（公開資訊觀測站）", "與你持股相關的新聞會在 AI 盤後報告中摘要"],
  },
  ai: {
    title: "AI 報告",
    milestone: "M4",
    body: "由基本面、技術面、籌碼、新聞四位 AI 分析師分別研究，再進行多空辯論，最後整理成結論與風險。",
    items: ["最新報告與歷史版本", "每個數字都標示資料來源與日期", "同一檔同一天的報告所有人共用，節省費用"],
  },
}

export function ComingSoonTab({ kind }: { kind: "chips" | "news" | "ai" }) {
  const c = COMING[kind]
  return (
    <Panel title={c.title} titleId={`soon-${kind}`} aside={<SoonChop milestone={c.milestone} />}>
      <p className="max-w-prose text-md text-muted-foreground">{c.body}</p>
      <ul className="mt-3 flex max-w-prose flex-col gap-1.5 text-md">
        {c.items.map((i) => (
          <li key={i} className="flex gap-2"><span aria-hidden className="text-muted-foreground">・</span>{i}</li>
        ))}
      </ul>
      {kind === "ai" && <p className="mt-4 text-xs text-muted-foreground">AI 分析僅供參考，不構成投資建議。</p>}
    </Panel>
  )
}

export { DemoChop }
