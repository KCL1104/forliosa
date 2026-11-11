import { useMemo, useState } from "react"
import { Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { useValuation } from "@/api/queries"
import type { InstrumentDetail, Valuation } from "@/api/types"
import { ChartTooltipBox, Legend, RangeChips } from "@/components/charts/chart-kit"
import { AXIS_TICK, GRID_STROKE } from "@/lib/chart"
import { DemoChop } from "@/components/chop"
import { Panel } from "@/components/section"
import { ChartSkeleton, EmptyState, ErrorState } from "@/components/states"
import { buildRiver, invalidRuns, type Mode } from "@/lib/valuation"
import { formatDate, formatNumber, formatPercent, formatPrice, formatPriceLevel } from "@/lib/format"

const BAND_VARS = ["var(--band-1)", "var(--band-2)", "var(--band-3)", "var(--band-4)", "var(--band-5)"]

export function ValuationTab({ instrument }: { instrument: InstrumentDetail }) {
  const valuation = useValuation(instrument.symbol)
  const [mode, setMode] = useState<Mode>("per")

  if (valuation.isError) return <ErrorState error={valuation.error} onRetry={() => void valuation.refetch()} />
  if (!valuation.data) return <ChartSkeleton height={420} />
  const v = valuation.data
  const hasPer = v.per_multiples.length > 0 && v.series.some((p) => p.eps_ttm !== null)
  const hasPbr = v.pbr_multiples.length > 0 && v.series.some((p) => p.bvps !== null)

  if (!hasPer && !hasPbr) {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title={instrument.type === "etf" ? "ETF 沒有本益比與股價淨值比河流圖" : "這檔還沒有估值資料"}
          description={
            instrument.type === "etf"
              ? "ETF 是一籃子股票，沒有自己的每股盈餘與淨值。可以改看下方的殖利率走勢，或到「股利」分頁看歷年配息。"
              : "我們還沒有這檔的歷史每股盈餘與淨值資料。"
          }
        />
        <YieldPanel valuation={v} />
        <Notes notes={v.notes} />
      </div>
    )
  }
  const activeMode: Mode = mode === "per" && !hasPer ? "pbr" : mode === "pbr" && !hasPbr ? "per" : mode
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <RangeChips
          label="估值方式"
          value={activeMode}
          onChange={setMode}
          options={[
            ...(hasPer ? [{ value: "per" as const, label: "本益比河流圖" }] : []),
            ...(hasPbr ? [{ value: "pbr" as const, label: "股價淨值比河流圖" }] : []),
          ]}
        />
        <span className="text-sm text-muted-foreground">近 5 年・{cadenceLabel(v)}</span>
        {v.is_demo && <DemoChop className="ml-auto" />}
      </div>
      <RiverPanel valuation={v} mode={activeMode} instrument={instrument} />
      <YieldPanel valuation={v} />
      <Notes notes={v.notes} />
    </div>
  )
}

/** 資料頻率：真實資料是每個交易日，示範資料是每週 */
function cadenceLabel(v: Valuation): string {
  const first = v.series[0]
  const last = v.series.at(-1)
  if (!first || !last || v.series.length < 2) return "每個交易日"
  const days = (Date.parse(last.t) - Date.parse(first.t)) / 86_400_000 / (v.series.length - 1)
  return days > 4 ? "每週" : "每個交易日"
}

/** 後端的說明（資料來源、EPS ≤ 0 留白等）：來源必須標示 */
function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null
  return (
    <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
      {notes.map((n) => (
        <li key={n}>・{n}</li>
      ))}
    </ul>
  )
}

function RiverPanel({ valuation, mode, instrument }: { valuation: Valuation; mode: Mode; instrument: InstrumentDetail }) {
  const multiples = mode === "per" ? valuation.per_multiples : valuation.pbr_multiples
  const rows = useMemo(() => buildRiver(valuation.series, multiples, mode), [valuation.series, multiples, mode])
  const runs = useMemo(() => invalidRuns(rows), [rows])
  const last = rows.at(-1)
  const lastValid = [...rows].reverse().find((r) => r.base !== null && r.base > 0)
  const market = instrument.market
  const unit = market === "US" ? "US$" : "NT$"
  const baseLabel = mode === "per" ? "近四季 EPS" : "每股淨值"
  const ratioLabel = mode === "per" ? "本益比" : "股價淨值比"
  const currentRatio = mode === "per" ? valuation.current.per : valuation.current.pbr
  const currentInvalid = !last || last.base === null || last.base <= 0
  const chartData = rows.map((r) => ({ t: r.t, close: r.close, ...Object.fromEntries(r.bands.map((b, i) => [`b${i}`, b])) }))

  // 目前所在區間
  const bracket = (() => {
    if (currentRatio === null || currentInvalid) return null
    const idx = multiples.findIndex((m) => currentRatio < m)
    if (idx === 0) return `低於 ${multiples[0]} 倍（最便宜的區間以下）`
    if (idx === -1) return `高於 ${multiples.at(-1)} 倍（最貴的區間以上）`
    return `介於 ${multiples[idx - 1]} 倍與 ${multiples[idx]} 倍之間`
  })()
  const bandPrices = lastValid ? multiples.map((m, idx) => ({ kind: "band" as const, m, idx, price: lastValid.base! * m })) : []
  // 由貴到便宜排列，並把「現價」插在對應位置
  const bandRows: ({ kind: "band"; m: number; idx: number; price: number } | { kind: "price"; price: number })[] = []
  let placed = false
  for (const b of [...bandPrices].reverse()) {
    if (!placed && last && last.close >= b.price) {
      bandRows.push({ kind: "price", price: last.close })
      placed = true
    }
    bandRows.push(b)
  }
  if (!placed && last) bandRows.push({ kind: "price", price: last.close })

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <Panel title={`${ratioLabel}河流圖`} titleId="river-title" bodyClassName="pt-1">
        <p className="mb-2 max-w-prose text-sm text-muted-foreground">
          每一條帶是「{baseLabel} × 倍數」換算出的股價。股價線落在越上面的帶，代表用{ratioLabel}來看越貴。
        </p>
        <Legend
          className="mb-1"
          items={[
            { label: "收盤價", color: "var(--foreground)", shape: "line" },
            ...multiples.map((m, i) => ({ label: `${m} 倍`, color: BAND_VARS[i] ?? BAND_VARS[4]! })),
          ]}
        />
        {runs.length > 0 && (
          <p className="mb-1 rounded-md bg-muted px-3 py-2 text-sm">
            <span className="font-medium">{runs.map((r) => `${formatDate(r.from)}–${formatDate(r.to)}`).join("、")}</span>
            ：{baseLabel} ≤ 0，{ratioLabel}沒有意義，這段期間不畫區間。
          </p>
        )}
        <div className="h-[340px] w-full sm:h-[380px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={56} tickFormatter={(t: string) => t.slice(0, 7).replace("-", "/")} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56} tickFormatter={(n: number) => formatNumber(n)} domain={[0, "auto"]} />
              {runs.map((r) => (
                <ReferenceArea key={r.from} x1={r.from} x2={r.to} fill="var(--muted)" fillOpacity={0.9} ifOverflow="extendDomain" />
              ))}
              {multiples.map((m, i) => (
                <Area
                  key={m}
                  dataKey={`b${i}`}
                  stackId="river"
                  type="linear"
                  fill={BAND_VARS[i] ?? BAND_VARS[4]}
                  fillOpacity={1}
                  stroke="var(--card)"
                  strokeWidth={1}
                  isAnimationActive={false}
                  connectNulls={false}
                  activeDot={false}
                />
              ))}
              <Line dataKey="close" stroke="var(--foreground)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }} />
              <Tooltip
                cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
                content={({ active, label }) => {
                  if (!active) return null
                  const r = rows.find((x) => x.t === label)
                  if (!r) return null
                  const valid = r.base !== null && r.base > 0
                  return (
                    <ChartTooltipBox
                      title={formatDate(r.t)}
                      rows={[
                        { label: "收盤", value: formatPrice(r.close, market), color: "var(--foreground)", shape: "line" },
                        { label: ratioLabel, value: r.ratio !== null ? `${r.ratio.toFixed(1)} 倍` : "不適用" },
                        { label: baseLabel, value: r.base !== null ? `${unit}${r.base.toFixed(2)}` : "—" },
                        ...(valid
                          ? [...multiples].reverse().map((m) => ({ label: `${m} 倍`, value: formatPriceLevel(r.base! * m, market), color: BAND_VARS[multiples.indexOf(m)] }))
                          : []),
                      ]}
                    />
                  )
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title={`現在的${ratioLabel}`} titleId="river-now">
        {currentInvalid ? (
          <div className="flex flex-col gap-2">
            <p className="text-2xl font-semibold">不適用</p>
            <p className="text-md text-muted-foreground">
              {baseLabel}目前 ≤ 0（{last?.base !== null && last?.base !== undefined ? `${unit}${last.base.toFixed(2)}` : "無資料"}），{ratioLabel}沒有意義。可改看股價淨值比或殖利率。
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <p className="hero-figure text-hero-sm font-semibold">
                {currentRatio?.toFixed(1)}
                <span className="ml-1 text-lg font-medium text-muted-foreground">倍</span>
              </p>
              {bracket && <p className="mt-2 text-md">{bracket}</p>}
              {mode === "per" && valuation.current.per_percentile_5y !== null && (
                <p className="mt-1 text-md text-muted-foreground">
                  過去 5 年有 <span className="num font-medium text-foreground">{formatPercent(valuation.current.per_percentile_5y, { signed: false, decimals: 0 })}</span> 的時間本益比比現在低。
                </p>
              )}
            </div>
            <dl className="flex flex-col gap-1 text-md">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">{baseLabel}</dt>
                <dd className="num">{unit}{last!.base!.toFixed(2)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">收盤價</dt>
                <dd className="num">{formatPrice(last!.close, market)}</dd>
              </div>
            </dl>
            <table className="w-full text-md">
              <caption className="mb-1 text-left text-sm text-muted-foreground">各倍數對應的股價（今天）</caption>
              <tbody>
                {bandRows.map((row) =>
                  row.kind === "price" ? (
                    <tr key="price" className="border-b border-hairline bg-accent font-semibold text-accent-foreground">
                      <th scope="row" className="py-1.5 pl-2 text-left">現價</th>
                      <td className="num py-1.5 pr-2 text-right" colSpan={2}>{formatPrice(row.price, market)}</td>
                    </tr>
                  ) : (
                    <tr key={row.m} className="border-b border-hairline last:border-0">
                      <th scope="row" className="py-1.5 pl-2 text-left font-normal">
                        <span className="inline-flex items-center gap-2">
                          <span aria-hidden className="size-2.5 rounded-[3px] ring-1 ring-border" style={{ background: BAND_VARS[row.idx] }} />
                          {row.m} 倍
                        </span>
                      </th>
                      <td className="num py-1.5 pr-2 text-right" colSpan={2}>{formatPriceLevel(row.price, market)}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

function YieldPanel({ valuation }: { valuation: Valuation }) {
  const data = valuation.series.filter((p) => p.dividend_yield !== null).map((p) => ({ t: p.t, y: p.dividend_yield! }))
  const current = valuation.current.dividend_yield
  return (
    <Panel
      title="殖利率走勢"
      titleId="yield-title"
      aside={current !== null && <span className="num text-md">目前 {formatPercent(current, { signed: false })}</span>}
    >
      {data.length < 2 ? (
        <p className="text-md text-muted-foreground">還沒有足夠的配息資料可以畫殖利率走勢。</p>
      ) : (
        <>
          <p className="mb-2 text-sm text-muted-foreground">近 12 個月現金股利 ÷ 收盤價。</p>
          <div className="h-[180px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={GRID_STROKE} />
                <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={56} tickFormatter={(t: string) => t.slice(0, 7).replace("-", "/")} />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} tickFormatter={(n: number) => formatPercent(n, { signed: false, decimals: 1 })} />
                <Tooltip
                  cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
                  content={({ active, payload }) => {
                    const row = active ? (payload?.[0]?.payload as { t: string; y: number } | undefined) : undefined
                    return row ? <ChartTooltipBox title={formatDate(row.t)} rows={[{ label: "殖利率", value: formatPercent(row.y, { signed: false }) }]} /> : null
                  }}
                />
                <Line dataKey="y" stroke="var(--chart-1)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </Panel>
  )
}
