import { useState } from "react"
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { useDividends, useFinancials, useRevenue } from "@/api/queries"
import type { Financials, FinancialsPeriod, InstrumentDetail, MonthlyRevenue } from "@/api/types"
import { ChartTooltipBox } from "@/components/charts/chart-kit"
import { DemoTag, Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { AXIS_TICK, GRID_STROKE, monthTick } from "@/lib/chart"
import { formatCompact, formatDate, formatDateShort, formatNumber, formatPercent, formatPerShare, formatRevenueThousands } from "@/lib/format"
import { cn } from "@/lib/utils"
import { DataNotes } from "@/components/data-notes"
import { useSourceNote } from "@/hooks/use-source-note"
import { sourceNotes, useDatasetSources } from "../text"
import { Fig, NotYet, TabLead } from "./kit"

/**
 * 財務：月營收（放最上面）→ 季報／年報 → 資產負債與現金流。ETF 改成「成分股與配息」。
 * 美股：SEC EDGAR 的 10-Q／10-K（美元、公司會計年度），沒有月營收。
 */
export function FinancialsTab({ inst }: { inst: InstrumentDetail }) {
  if (inst.market === "US") {
    if (inst.type === "etf") {
      return (
        <NotYet title="ETF 沒有自己的財報">
          持股與費用率請看發行商公告。
        </NotYet>
      )
    }
    return <Statements symbol={inst.symbol} />
  }
  if (inst.type === "etf") return <EtfHoldings inst={inst} />
  return (
    <div className="flex flex-col gap-12">
      <Revenue symbol={inst.symbol} />
      <Statements symbol={inst.symbol} />
    </div>
  )
}

function streak(rows: MonthlyRevenue[]): number {
  let n = 0
  for (let i = rows.length - 1; i >= 0 && (rows[i]!.yoy_pct ?? 0) > 0; i--) n++
  return n
}

function Revenue({ symbol }: { symbol: string }) {
  const revenue = useRevenue(symbol)
  // 月營收沒有自己的 sources：數字來自 shioaji-data 彙整的公開資訊觀測站資料，登記到頁尾
  useDatasetSources([!!revenue.data?.length && "shioaji-data/official"])
  if (revenue.isError) return <ErrorState error={revenue.error} onRetry={() => void revenue.refetch()} />
  if (revenue.isLoading) return <Skeleton className="h-80 w-full rounded-sm" />
  const all = revenue.data ?? []
  if (all.length === 0) return <NotYet title="沒有月營收資料">這檔沒有在公開資訊觀測站公告月營收。</NotYet>
  const rows = all.slice(-24)
  const last = rows.at(-1)!
  const n = streak(all)
  const data = rows.map((r) => ({ ...r, yi: r.revenue / 1e5 }))
  return (
    <Section title="月營收" titleId="fin-rev" aside="單位：新台幣">
      <TabLead>
        {n >= 2 ? (
          <>
            {Number(last.period.slice(5))} 月營收年增 <Fig>{formatPercent(last.yoy_pct, { decimals: 0 })}</Fig>，連續 <Fig>{n}</Fig> 個月成長。
          </>
        ) : null}
      </TabLead>
      <div className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID_STROKE} />
            <XAxis dataKey="period" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={24} tickFormatter={monthTick} />
            <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => `${formatNumber(v)} 億`} />
            <Tooltip
              cursor={{ fill: "var(--hov)" }}
              content={({ active, payload }) => {
                const r = active ? (payload?.[0]?.payload as MonthlyRevenue | undefined) : undefined
                return r ? <ChartTooltipBox title={r.period.replace("-", "/")} rows={[{ label: "營收", value: formatRevenueThousands(r.revenue) }, { label: "年增", value: formatPercent(r.yoy_pct) }]} /> : null
              }}
            />
            <Bar dataKey="yi" fill="var(--chart-mine)" maxBarSize={22} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-4 text-sm text-ink-2">年增率（和去年同月比）</p>
      <div className="h-[120px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID_STROKE} />
            <XAxis dataKey="period" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={24} tickFormatter={monthTick} />
            <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatPercent(v, { decimals: 0 })} />
            <ReferenceLine y={0} stroke="var(--ctl)" />
            <Line dataKey="yoy_pct" stroke="var(--chart-blue)" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-md">
          <caption className="sr-only">近 12 個月營收</caption>
          <thead>
            <tr className="form-head">
              <th scope="col" className="h-10 text-left">月份</th>
              <th scope="col" className="h-10 text-right">營收</th>
              <th scope="col" className="h-10 text-right">月增</th>
              <th scope="col" className="h-10 text-right">年增</th>
              <th scope="col" className="h-10 text-right">累計年增</th>
            </tr>
          </thead>
          <tbody>
            {[...rows].reverse().slice(0, 12).map((r) => (
              <tr key={r.period} className="num border-b border-rule">
                <th scope="row" className="h-10 text-left font-normal">{r.period.replace("-", "/")}</th>
                <td className="text-right">{formatRevenueThousands(r.revenue)}</td>
                <td className="text-right">{formatPercent(r.mom_pct, { decimals: 1 })}</td>
                <td className="text-right">{formatPercent(r.yoy_pct, { decimals: 1 })}</td>
                <td className="text-right">{formatPercent(r.ytd_yoy_pct, { decimals: 1 })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

const ROWS: { label: string; pick: (f: Financials) => (number | null)[]; kind: "money" | "pct" | "eps" }[] = [
  { label: "營收", pick: (f) => f.income.revenue, kind: "money" },
  { label: "毛利率", pick: (f) => f.margins.gross, kind: "pct" },
  { label: "營業利益率", pick: (f) => f.margins.operating, kind: "pct" },
  { label: "淨利率", pick: (f) => f.margins.net, kind: "pct" },
  { label: "稅後淨利", pick: (f) => f.income.net_income, kind: "money" },
  { label: "EPS", pick: (f) => f.income.eps, kind: "eps" },
  { label: "總資產", pick: (f) => f.balance.total_assets, kind: "money" },
  { label: "負債比", pick: (f) => f.balance.total_liabilities.map((l, i) => (l !== null && f.balance.total_assets[i] ? l / f.balance.total_assets[i]! : null)), kind: "pct" },
  { label: "營業現金流", pick: (f) => f.cashflow.operating, kind: "money" },
  { label: "自由現金流", pick: (f) => f.cashflow.free_cash_flow, kind: "money" },
]

function Statements({ symbol }: { symbol: string }) {
  const [period, setPeriod] = useState<FinancialsPeriod>("quarterly")
  const fin = useFinancials(symbol, period)
  const f = fin.data
  useSourceNote(sourceNotes(f?.sources))
  // 台股金額是新台幣千元；美股（SEC EDGAR）是美元，期間是公司的會計年度
  const usd = f?.currency === "USD"
  const unit = f?.amount_unit ?? 1000
  const fmt = (v: number | null, kind: "money" | "pct" | "eps") =>
    v === null ? "—" : kind === "money" ? formatCompact(v * unit, 0) : kind === "pct" ? formatPercent(v, { signed: false, decimals: 1 }) : formatNumber(v, 2)
  // 對去年同季（季報）或前一年（年報）
  const lag = period === "quarterly" ? 4 : 1
  const shown = f ? f.periods.slice(-(period === "quarterly" ? 4 : 5)) : []
  const offset = f ? f.periods.length - shown.length : 0
  const lastIdx = f ? f.periods.length - 1 : 0
  const epsNow = f?.income.eps[lastIdx] ?? null
  const epsPrev = f && lastIdx - lag >= 0 ? (f.income.eps[lastIdx - lag] ?? null) : null
  const ends = f?.period_ends ?? []
  return (
    <Section
      title="財報"
      titleId="fin-statements"
      aside={usd ? "單位：美元；EPS 為稀釋每股盈餘（美元）" : "單位：新台幣；EPS 元"}
      action={<RangeChips label="期間" value={period} onChange={setPeriod} options={[{ value: "quarterly", label: "季" }, { value: "annual", label: "年" }]} />}
    >
      {fin.isError ? (
        <ErrorState error={fin.error} onRetry={() => void fin.refetch()} />
      ) : !f ? (
        <Skeleton className="h-72 w-full rounded-sm" />
      ) : f.periods.length === 0 ? (
        <NotYet title={usd ? "目前沒有這家公司的 SEC 財報" : "財報資料累積中"}>{f.notes?.join(" ")}</NotYet>
      ) : (
        <>
          <TabLead>
            {epsNow !== null && epsPrev !== null && epsPrev > 0 ? (
              <>
                {f.periods[lastIdx]} EPS <Fig>{formatPerShare(epsNow, usd ? "US" : "TWSE")}</Fig>，{period === "quarterly" ? "比去年同季" : "比前一年"}
                {epsNow >= epsPrev ? "成長" : "減少"} <Fig>{formatPercent(Math.abs(epsNow / epsPrev - 1), { signed: false, decimals: 0 })}</Fig>。
              </>
            ) : null}
          </TabLead>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-md">
              <thead>
                <tr className="form-head">
                  <th scope="col" className="h-10 text-left">
                    項目
                  </th>
                  {shown.map((p, i) => {
                    const end = usd ? ends[offset + i] : null
                    return (
                      <th key={p} scope="col" className={cn("num h-10 text-right", end && "pt-1.5 pb-2.5")}>
                        {p}
                        {/* 美股的會計年度不一定跟日曆年：標出這一期結束的日期 */}
                        {end && <span className="block">至 {formatDate(end)}</span>}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((r) => {
                  const col = r.pick(f)
                  return (
                    <tr key={r.label} className="num border-b border-rule">
                      <th scope="row" className="h-10 text-left font-normal">
                        {r.label}
                      </th>
                      {shown.map((p, i) => (
                        <td key={p} className="text-right">
                          {fmt(col[offset + i] ?? null, r.kind)}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {/* 說明（會計年度、單位、推算方式）照原文放在表下；資料來源登記到頁尾 */}
          <div className="mt-2 flex flex-wrap items-start gap-3">
            {f.is_demo && <DemoTag />}
            <DataNotes notes={f.notes} />
          </div>
        </>
      )}
    </Section>
  )
}

function EtfHoldings({ inst }: { inst: InstrumentDetail }) {
  const dividends = useDividends(inst.symbol)
  const rows = (dividends.data ?? []).filter((d) => d.cash_dividend > 0).slice(0, 8)
  return (
    <div className="flex flex-col gap-10">
      <Section title="收益分配" titleId="etf-dist" aside="每單位配息（元）">
        {dividends.isLoading ? (
          <Skeleton className="h-40 w-full rounded-sm" />
        ) : rows.length === 0 ? (
          <p className="text-base text-ink">沒有配息紀錄。</p>
        ) : (
          <ul className="-mt-3">
            {rows.map((d) => (
              <li key={d.period} className="num grid grid-cols-[1fr_auto_auto] gap-4 border-b border-rule py-2.5 text-md">
                <span>{d.period}</span>
                <span className="text-ink-2">{d.ex_dividend_date ? `除息 ${formatDateShort(d.ex_dividend_date)}` : "—"}</span>
                <span className="w-16 text-right font-medium">{d.cash_dividend}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  )
}
