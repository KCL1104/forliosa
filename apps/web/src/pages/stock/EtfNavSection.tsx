import { ChevronDownIcon } from "lucide-react"
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { useOverview } from "@/api/queries"
import type { EtfNav, InstrumentDetail, NavPoint } from "@/api/types"
import { ChartTooltipBox } from "@/components/charts/chart-kit"
import { Section } from "@/components/section"
import { Skeleton } from "@/components/ui/skeleton"
import { formatNav, formatPremium, NAV_MIN_POINTS } from "@/lib/etf-nav"
import { AXIS_TICK } from "@/lib/chart"
import { formatDate, formatDateShort, formatPercent } from "@/lib/format"
import { formatQuote } from "@/lib/tick"
import { KeyGrid, NotYet, Sources } from "./tabs/kit"

const TRACKING_ERROR = "追蹤誤差不提供：標的指數的每日資料沒有開放授權。"
const md = (d: string) => formatDateShort(d, false)

/**
 * 淨值與折溢價（台股 ETF）：金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉＋同一天的官方收盤價。
 * 折溢價不是價格漲跌，所以全部用墨色與文字「溢價／折價」，不用紅綠、不加 ▲▼。
 */
export function EtfNavSection({ inst, titleId = "ov-premium" }: { inst: InstrumentDetail; titleId?: string }) {
  const overview = useOverview(inst.symbol)
  const n = overview.data?.etf_nav
  if (overview.isLoading) return <Skeleton className="h-40 w-full rounded-sm" />
  if (!n) return null
  return (
    <Section title="淨值與折溢價" titleId={titleId}>
      {n.nav === null ? (
        <NotYet title={n.notes[0] ?? "還沒有這檔 ETF 的淨值"}>{TRACKING_ERROR}</NotYet>
      ) : (
        <NavBody inst={inst} n={n} />
      )}
      <Sources items={n.sources} />
    </Section>
  )
}

function NavBody({ inst, n }: { inst: InstrumentDetail; n: EtfNav }) {
  const price = (v: number | null | undefined) => formatQuote(v, inst.market, inst.type)
  const at = n.history.at(-1)
  const sameDay = n.premium_date !== null && n.premium_date === n.nav_date && n.premium_date === n.close_date
  const chart = n.history.length >= NAV_MIN_POINTS
  return (
    <>
      <KeyGrid
        items={[
          { label: n.nav_date ? `淨值（${md(n.nav_date)}）` : "淨值", value: formatNav(n.nav), title: n.fund_name ?? undefined },
          { label: n.close_date ? `收盤（${md(n.close_date)}）` : "收盤", value: price(n.close) },
          { label: n.premium_date ? `折溢價（${md(n.premium_date)}）` : "折溢價", value: formatPremium(n.premium_pct), wide: true },
        ]}
      />
      {at && !sameDay && n.nav_date && n.close_date && (
        <p className="mt-3 max-w-prose text-md text-ink">
          最新的淨值是 {md(n.nav_date)}、收盤是 {md(n.close_date)}；折溢價用兩者都有的 {md(at.t)} 計算（收盤 {price(at.close)}、淨值 {formatNav(at.nav)}）。
        </p>
      )}
      {chart && <PremiumChart points={n.history} price={price} />}
      {n.notes.map((note) => (
        <p key={note} className="mt-3 text-md text-ink-2">
          {note}
        </p>
      ))}
      <p className="mt-3 text-md text-ink-2">{TRACKING_ERROR}</p>
      {n.history.length > 0 && <DailyTable inst={inst} points={n.history} />}
    </>
  )
}

/** 0 軸是「淨值」；刻度取到 0.1% 並一定含 0 */
function ticksFor(points: NavPoint[]): number[] {
  const values = points.map((p) => p.premium_pct)
  const lo = Math.min(0, Math.floor(Math.min(...values) * 1000) / 1000)
  const hi = Math.max(0, Math.ceil(Math.max(...values) * 1000) / 1000)
  return [...new Set([lo, 0, hi])].sort((a, b) => a - b)
}

function PremiumChart({ points, price }: { points: NavPoint[]; price: (v: number) => string }) {
  const ticks = ticksFor(points)
  const lo = points.reduce((a, p) => (p.premium_pct < a.premium_pct ? p : a))
  const hi = points.reduce((a, p) => (p.premium_pct > a.premium_pct ? p : a))
  const last = points.at(-1)!
  const summary = `近 ${points.length} 個交易日的折溢價，${md(points[0]!.t)} 到 ${md(last.t)}：最低 ${formatPremium(lo.premium_pct)}（${md(lo.t)}），最高 ${formatPremium(hi.premium_pct)}（${md(hi.t)}），${md(last.t)} ${formatPremium(last.premium_pct)}`
  return (
    <figure className="mt-5">
      <figcaption className="text-md text-ink">近 {points.length} 個交易日</figcaption>
      <div className="mt-2 h-[132px] w-full" role="img" aria-label={summary}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={64} tickFormatter={(t: string) => md(t)} />
            <YAxis
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={false}
              width={48}
              domain={[ticks[0]!, ticks.at(-1)!]}
              ticks={ticks}
              tickFormatter={(v: number) => (v === 0 ? "淨值" : formatPercent(v, { decimals: 1 }))}
            />
            <ReferenceLine y={0} stroke="var(--ctl)" strokeWidth={1} />
            <Tooltip
              cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
              content={({ active, payload }) => {
                const p = active ? (payload?.[0]?.payload as NavPoint | undefined) : undefined
                return p ? (
                  <ChartTooltipBox
                    title={formatDate(p.t)}
                    rows={[
                      { label: "折溢價", value: formatPremium(p.premium_pct) },
                      { label: "收盤", value: price(p.close) },
                      { label: "淨值", value: formatNav(p.nav) },
                    ]}
                  />
                ) : null
              }}
            />
            <Line dataKey="premium_pct" stroke="var(--ink)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: "var(--paper)", strokeWidth: 2 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-sm text-ink-2">
        區間 {formatPremium(lo.premium_pct)}（{md(lo.t)}）到 {formatPremium(hi.premium_pct)}（{md(hi.t)}）
      </p>
    </figure>
  )
}

/** 逐日數字（新的在前）：圖表的文字版，預設收合 */
function DailyTable({ inst, points }: { inst: InstrumentDetail; points: NavPoint[] }) {
  const price = (v: number) => formatQuote(v, inst.market, inst.type)
  return (
    <details className="group mt-2">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1 rounded-sm text-sm text-ink-2 hover:text-ink [&::-webkit-details-marker]:hidden">
        逐日數字（{points.length} 天）
        <ChevronDownIcon aria-hidden className="size-4 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
      </summary>
      <div className="max-h-72 overflow-y-auto border-t border-rule">
        <table className="w-full text-md">
          <thead className="sticky top-0 bg-paper text-sm text-ink-2">
            <tr className="border-b border-rule">
              <th scope="col" className="py-2 text-left font-normal">日期</th>
              <th scope="col" className="py-2 text-right font-normal">收盤</th>
              <th scope="col" className="py-2 text-right font-normal">淨值</th>
              <th scope="col" className="py-2 text-right font-normal">折溢價</th>
            </tr>
          </thead>
          <tbody className="num">
            {[...points].reverse().map((p) => (
              <tr key={p.t} className="border-b border-rule">
                <th scope="row" className="py-2 text-left font-normal">{md(p.t)}</th>
                <td className="py-2 text-right">{price(p.close)}</td>
                <td className="py-2 text-right">{formatNav(p.nav)}</td>
                <td className="py-2 text-right">{formatPremium(p.premium_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
