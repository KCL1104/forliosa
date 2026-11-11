import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { PerformancePoint } from "@/api/types"
import { formatDateShort, formatPercent } from "@/lib/format"
import { AXIS_TICK, ChartTooltipBox, GRID_STROKE } from "./chart-kit"

interface Row {
  t: string
  mine: number
  bench: number | null
}

/**
 * 報酬走勢：我的（TWR 指數）與基準，兩者都換算成「相對起點的 %」放在同一個軸上
 * （dataviz：不用雙軸；以共同基期指數化）。
 */
export function ReturnChart({
  series,
  showBenchmark,
  benchmarkName,
  height = 240,
}: {
  series: PerformancePoint[]
  showBenchmark: boolean
  benchmarkName: string
  height?: number
}) {
  const base = series[0]
  const rows: Row[] = series.map((p) => ({
    t: p.t,
    mine: base ? p.twr_index / base.twr_index - 1 : 0,
    bench: p.benchmark_index !== null && base?.benchmark_index ? p.benchmark_index / base.benchmark_index - 1 : null,
  }))
  const spanDays = rows.length
  const tickFmt = (t: string) => (spanDays > 260 ? t.slice(0, 7).replace("-", "/") : formatDateShort(t, false))

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="mineFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.16} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={GRID_STROKE} />
          <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={48} tickFormatter={tickFmt} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={52}
            tickFormatter={(v: number) => formatPercent(v, { decimals: 0 })}
            domain={["auto", "auto"]}
          />
          <Tooltip
            cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const row = active ? (payload?.[0]?.payload as Row | undefined) : undefined
              if (!row) return null
              return (
                <ChartTooltipBox
                  title={formatDateShort(row.t)}
                  rows={[
                    { label: "我的報酬", value: formatPercent(row.mine), color: "var(--chart-1)", shape: "line" },
                    ...(showBenchmark && row.bench !== null
                      ? [{ label: benchmarkName, value: formatPercent(row.bench), color: "var(--chart-2)", shape: "line" as const }]
                      : []),
                  ]}
                />
              )
            }}
          />
          <Area
            type="monotone"
            dataKey="mine"
            stroke="var(--chart-1)"
            strokeWidth={2}
            fill="url(#mineFill)"
            isAnimationActive={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
          />
          {showBenchmark && (
            <Line
              type="monotone"
              dataKey="bench"
              stroke="var(--chart-2)"
              strokeWidth={1.75}
              dot={false}
              isAnimationActive={false}
              activeDot={{ r: 3.5, strokeWidth: 2, stroke: "var(--card)" }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
