import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { appToday } from "@/api"
import { useDividends } from "@/api/queries"
import type { InstrumentDetail, Position, Quote } from "@/api/types"
import { ChartTooltipBox } from "@/components/charts/chart-kit"
import { DemoTag, Section } from "@/components/section"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { AXIS_TICK, GRID_STROKE } from "@/lib/chart"
import { formatDateShort, formatMoney, formatPercent } from "@/lib/format"
import { usePrefs } from "@/stores/prefs"
import { KeyGrid, TabLead } from "./kit"

/** 股利：我的（已領、下次可領、二代健保）＋歷年配息 */
export function DividendsTab({ inst, quote, position }: { inst: InstrumentDetail; quote?: Quote; position: Position | null }) {
  const dividends = useDividends(inst.symbol)
  const privacy = usePrefs((s) => s.privacyMode)
  const today = appToday()
  if (dividends.isError) return <ErrorState error={dividends.error} onRetry={() => void dividends.refetch()} />
  if (!dividends.data) return <Skeleton className="h-80 w-full rounded-sm" />
  const rows = dividends.data
  const us = inst.market === "US"
  const cur = us ? "USD" : "TWD"
  const unit = us ? "US$" : ""
  const yearAgo = `${Number(today.slice(0, 4)) - 1}${today.slice(4)}`
  const ttm = rows.filter((d) => d.ex_dividend_date && d.ex_dividend_date > yearAgo && d.ex_dividend_date <= today).reduce((s, d) => s + d.cash_dividend, 0)
  const next = rows.filter((d) => d.ex_dividend_date && d.ex_dividend_date >= today && d.cash_dividend > 0).sort((a, b) => a.ex_dividend_date!.localeCompare(b.ex_dividend_date!))[0]
  const perYear = new Map<number, number>()
  for (const d of rows) perYear.set(d.year, (perYear.get(d.year) ?? 0) + d.cash_dividend)
  const years = [...perYear.entries()].sort((a, b) => a[0] - b[0]).map(([year, cash]) => ({ year: String(year), cash: Math.round(cash * 1000) / 1000 }))
  const freq = rows.filter((d) => d.ex_dividend_date && d.ex_dividend_date > yearAgo && d.ex_dividend_date <= today).length
  const yieldNow = quote && ttm > 0 ? ttm / quote.price : null
  const money = (n: number) => (privacy ? "••••" : formatMoney(n, { currency: "TWD" }))
  const lot = us ? 1 : 1000

  if (rows.length === 0) {
    // 美股沒有可商用的配息來源（後端與商用 mock 都回空陣列）：不能說成「沒有配過息」
    return (
      <p className="border-y border-rule py-6 text-md text-ink-2">
        {us ? `美股目前沒有可商用的配息資料來源，這裡還不能顯示${inst.name}的配息。` : `${inst.name}過去沒有配息紀錄。`}
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-12">
      <div>
        <TabLead>
          {next ? `${formatDateShort(next.ex_dividend_date!)} 除息，每股 ${unit}${next.cash_dividend} 元。` : ttm > 0 ? `過去一年每股共配 ${unit}${Math.round(ttm * 100) / 100} 元。` : null}
        </TabLead>
        <KeyGrid
          items={[
            { label: "近一年現金股利", value: ttm > 0 ? `${unit}${Math.round(ttm * 1000) / 1000}` : "—" },
            { label: "殖利率（近一年）", value: yieldNow !== null ? formatPercent(yieldNow, { signed: false }) : "—" },
            { label: "配息頻率", value: freq >= 4 ? "季配" : freq === 2 ? "半年配" : freq === 1 ? "年配" : freq > 0 ? `一年 ${freq} 次` : "—" },
            { label: "下次除息", value: next ? formatDateShort(next.ex_dividend_date!) : "未公告" },
            { label: "下次發放", value: next?.payment_date ? formatDateShort(next.payment_date) : "—" },
            { label: "最近一期", value: rows[0] ? `${rows[0].period}・${unit}${rows[0].cash_dividend}` : "—" },
          ]}
        />
      </div>

      <Section title={position ? "我的股利" : "如果持有"} titleId="div-mine">
        {position ? (
          <KeyGrid
            items={[
              { label: "已領（扣二代健保）", value: money(position.dividends_received) },
              { label: "下次可領", value: position.upcoming_dividend ? `約 ${money(position.upcoming_dividend.amount_estimate)}` : "未公告" },
              {
                label: "二代健保",
                value: position.upcoming_dividend ? (position.upcoming_dividend.amount_estimate >= 20_000 ? "會扣 2.11%" : "未達 2 萬，不扣") : "—",
              },
            ]}
          />
        ) : (
          <p className="text-base">
            持有 {us ? "1 股" : "1 張"}，以過去一年的配息估算，一年約可領 <span className="num font-medium">{ttm > 0 ? formatMoney(ttm * lot, { currency: cur }) : "—"}</span>。
            <span className="text-ink-2">未來配息不一定相同。</span>
          </p>
        )}
      </Section>

      <Section title="歷年現金股利" titleId="div-years" aside={`每股（${us ? "美元" : "元"}）`} action={rows.some((d) => d.is_demo) ? <DemoTag /> : undefined}>
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={years} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="year" tick={AXIS_TICK} tickLine={false} axisLine={false} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={44} />
              <Tooltip
                cursor={{ fill: "var(--hov)" }}
                content={({ active, payload }) => {
                  const r = active ? (payload?.[0]?.payload as { year: string; cash: number } | undefined) : undefined
                  return r ? <ChartTooltipBox title={`${r.year} 年`} rows={[{ label: "現金股利", value: `${unit}${r.cash}` }]} /> : null
                }}
              />
              <Bar dataKey="cash" fill="var(--chart-mine)" maxBarSize={36} radius={[2, 2, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title="配息紀錄" titleId="div-list">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-md">
            <thead>
              <tr className="border-b border-rule text-sm text-ink-2">
                <th scope="col" className="h-9 text-left font-normal">期別</th>
                <th scope="col" className="text-right font-normal">現金股利</th>
                <th scope="col" className="text-right font-normal">股票股利</th>
                <th scope="col" className="text-right font-normal">除息日</th>
                <th scope="col" className="text-right font-normal">發放日</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.period} className="num border-b border-rule">
                  <th scope="row" className="h-10 text-left font-normal">
                    {d.period}
                    {d.ex_dividend_date && d.ex_dividend_date >= today && <span className="ml-2 text-sm text-ink-2">即將除息</span>}
                  </th>
                  <td className="text-right">{d.cash_dividend ? `${unit}${d.cash_dividend}` : "—"}</td>
                  <td className="text-right">{d.stock_dividend ? d.stock_dividend : "—"}</td>
                  <td className="text-right">{d.ex_dividend_date ? formatDateShort(d.ex_dividend_date, false) : "—"}</td>
                  <td className="text-right">{d.payment_date ? formatDateShort(d.payment_date, false) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  )
}
