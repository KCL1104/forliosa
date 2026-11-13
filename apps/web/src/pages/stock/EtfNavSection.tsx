import { ChevronDownIcon } from "lucide-react"
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { useOverview } from "@/api/queries"
import type { EtfNav, InstrumentDetail, NavPoint } from "@/api/types"
import { ChartTooltipBox } from "@/components/charts/chart-kit"
import { Section } from "@/components/section"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { type ChartDay, chartDays, formatNav, formatPremium, NAV_MIN_POINTS, spanLabel } from "@/lib/etf-nav"
import { AXIS_TICK } from "@/lib/chart"
import { formatDate, formatDateShort, formatPercent, formatPrice } from "@/lib/format"
import { KeyGrid, NotYet } from "./tabs/kit"
import { sourceNotes } from "./text"

const TRACKING_ERROR = "追蹤誤差不提供：標的指數的每日資料沒有開放授權。"
const md = (d: string) => formatDateShort(d, false)

/**
 * 淨值與折溢價（台股 ETF）：金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉＋同一天的官方收盤價。
 * 折溢價不是價格漲跌，所以全部用墨色與文字「溢價／折價」，不用紅綠、不加 ▲▼。
 * - `section`（估值分頁）：自己的區塊標題＋淨值・收盤・折溢價三格＋走勢。
 * - `band`（總覽的鍵值帶）：淨值與折溢價已經在鍵值格裡，這裡只接著放走勢、說明與逐日數字（標題安靜）。
 * 資料來源登記到頁尾。
 */
export function EtfNavSection({ inst, titleId, variant = "section" }: { inst: InstrumentDetail; titleId?: string; variant?: "section" | "band" }) {
  const overview = useOverview(inst.symbol)
  const n = overview.data?.etf_nav
  useSourceNote(sourceNotes(n?.sources))
  if (overview.isLoading) return <Skeleton className="h-40 w-full rounded-sm" />
  if (!n) return null
  if (variant === "band") {
    const id = titleId ?? "ov-premium"
    return (
      <section aria-labelledby={id} className="mt-6">
        <h3 id={id} className="text-md font-medium text-ink">
          折溢價走勢
        </h3>
        {n.nav === null ? (
          <div className="mt-1 flex flex-col gap-0.5 text-sm text-ink-2">
            <p className="text-ink">{n.notes[0] ?? "還沒有這檔 ETF 的淨值"}</p>
            <p>{TRACKING_ERROR}</p>
          </div>
        ) : (
          <NavBody inst={inst} n={n} figures={false} />
        )}
      </section>
    )
  }
  return (
    <Section title="淨值與折溢價" titleId={titleId ?? "val-premium"}>
      {n.nav === null ? <NotYet title={n.notes[0] ?? "還沒有這檔 ETF 的淨值"}>{TRACKING_ERROR}</NotYet> : <NavBody inst={inst} n={n} />}
    </Section>
  )
}

function NavBody({ inst, n, figures = true }: { inst: InstrumentDetail; n: EtfNav; figures?: boolean }) {
  const price = (v: number | null | undefined) => formatPrice(v, inst.market, inst.type)
  const at = n.history.at(-1)
  const sameDay = n.premium_date !== null && n.premium_date === n.nav_date && n.premium_date === n.close_date
  const chart = n.history.length >= NAV_MIN_POINTS
  return (
    <>
      {/* 區塊標題下的格線就是格子的上緣：不再畫第二條 */}
      {figures && (
        <KeyGrid
          className="-mt-3 border-t-0"
          items={[
            { label: n.nav_date ? `淨值（${md(n.nav_date)}）` : "淨值", value: formatNav(n.nav), title: n.fund_name ?? undefined },
            { label: n.close_date ? `收盤（${md(n.close_date)}）` : "收盤", value: price(n.close) },
            { label: n.premium_date ? `折溢價（${md(n.premium_date)}）` : "折溢價", value: formatPremium(n.premium_pct), wide: true },
          ]}
        />
      )}
      {at && !sameDay && n.nav_date && n.close_date && (
        <p className="mt-2 max-w-prose text-md text-ink">
          最新的淨值是 {md(n.nav_date)}、收盤是 {md(n.close_date)}；折溢價用兩者都有的 {md(at.t)} 計算（收盤 {price(at.close)}、淨值 {formatNav(at.nav)}）。
        </p>
      )}
      {chart && <PremiumChart points={n.history} missing={n.history_missing} price={price} />}
      <div className="mt-2 flex flex-col gap-0.5 text-sm text-ink-2">
        {n.notes.map((note) => (
          <p key={note}>{note}</p>
        ))}
        <p>{TRACKING_ERROR}</p>
      </div>
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

function PremiumChart({ points, missing, price }: { points: NavPoint[]; missing: string[]; price: (v: number) => string }) {
  const ticks = ticksFor(points)
  const lo = points.reduce((a, p) => (p.premium_pct < a.premium_pct ? p : a))
  const hi = points.reduce((a, p) => (p.premium_pct > a.premium_pct ? p : a))
  const last = points.at(-1)!
  const span = spanLabel(points, missing)
  const summary = `${span}的折溢價：最低 ${formatPremium(lo.premium_pct)}（${md(lo.t)}），最高 ${formatPremium(hi.premium_pct)}（${md(hi.t)}），${md(last.t)} ${formatPremium(last.premium_pct)}`
  return (
    <figure className="mt-3">
      <figcaption className="text-sm text-ink-2">{span}</figcaption>
      <div className="mt-2 h-[132px] w-full" role="img" aria-label={summary}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartDays(points, missing)} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
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
                const d = active ? (payload?.[0]?.payload as ChartDay | undefined) : undefined
                if (!d) return null
                const p = d.point
                return (
                  <ChartTooltipBox
                    title={formatDate(d.t)}
                    rows={
                      p
                        ? [
                            { label: "折溢價", value: formatPremium(p.premium_pct) },
                            { label: "收盤", value: price(p.close) },
                            { label: "淨值", value: formatNav(p.nav) },
                          ]
                        : [{ label: "折溢價", value: "沒有資料" }]
                    }
                  />
                )
              }}
            />
            <Line dataKey="premium_pct" connectNulls={false} stroke="var(--ink)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: "var(--paper)", strokeWidth: 2 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="num mt-1 text-sm text-ink">
        <span className="text-ink-2">區間</span> {formatPremium(lo.premium_pct)}
        <span className="text-ink-2">（{md(lo.t)}）到</span> {formatPremium(hi.premium_pct)}
        <span className="text-ink-2">（{md(hi.t)}）</span>
      </p>
    </figure>
  )
}

/** 逐日數字（新的在前）：圖表的文字版，預設收合 */
function DailyTable({ inst, points }: { inst: InstrumentDetail; points: NavPoint[] }) {
  const price = (v: number) => formatPrice(v, inst.market, inst.type)
  return (
    <details className="group mt-1">
      {/* 和「怎麼看 ⌄」同一種：墨色、常駐 ctl 底線，⌄ 打開時轉向 */}
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-0.5 rounded-sm text-sm text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink [&::-webkit-details-marker]:hidden">
        逐日數字（{points.length} 天）
        <ChevronDownIcon aria-hidden className="size-3.5 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
      </summary>
      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-md">
          <thead className="form-head sticky top-0 bg-paper">
            <tr>
              <th scope="col" className="h-10 text-left">日期</th>
              <th scope="col" className="h-10 text-right">收盤</th>
              <th scope="col" className="h-10 text-right">淨值</th>
              <th scope="col" className="h-10 text-right">折溢價</th>
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
