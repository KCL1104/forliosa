import { useMemo, useState } from "react"
import { Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { appToday } from "@/api"
import { useValuation } from "@/api/queries"
import { useWho } from "@/api/view-as"
import type { InstrumentDetail, Position, Valuation } from "@/api/types"
import { ChartTooltipBox, RangeChips } from "@/components/charts/chart-kit"
import { AXIS_TICK, GRID_STROKE } from "@/lib/chart"
import { DemoTag, Section as Panel } from "@/components/section"
import { usePrefs } from "@/stores/prefs"
import { EtfNavSection } from "../EtfNavSection"
import { MONTH_LABEL_WIDTH, monthTicks, useWidth } from "../month-ticks"
import { beforeSpan, twOpenApi, useDatasetSources, valuationSpan } from "../text"
import { Fig, NotYet } from "./kit"
import { useHowToRead } from "./how-to-read"
import { ChartSkeleton, ErrorState } from "@/components/states"
import { buildRiver, invalidRuns, type Mode } from "@/lib/valuation"
import { formatDate, formatNumber, formatPercent, formatPerShare, formatPrice, formatPriceLevel } from "@/lib/format"
import { cn } from "@/lib/utils"

const BAND_VARS = ["var(--band-1)", "var(--band-2)", "var(--band-3)", "var(--band-4)", "var(--band-5)"]

/**
 * 估值：本益比／股價淨值比河流圖、現在的倍數、殖利率走勢。
 * 全部由價格算出來：沒有報價（商用模式的美股）時只放一個空狀態，不再重複價格那一格說過的原因，也沒有殖利率走勢。
 * 「每條帶是…」「近 12 個月現金股利 ÷ 收盤價」這類術語說明收在「怎麼看 ⌄」裡，要看才打開。
 */
export function ValuationTab({ inst: instrument, position, noQuote = false }: { inst: InstrumentDetail; position: Position | null; noQuote?: boolean }) {
  const valuation = useValuation(instrument.symbol)
  const [mode, setMode] = useState<Mode>("per")
  // 估值序列沒有自己的 sources：收盤價與本益比、股價淨值比、殖利率的資料集（台股）登記到頁尾
  const tw = twOpenApi(instrument.market)
  const plotted = !!valuation.data?.series.length
  useDatasetSources([plotted && tw && `${tw}/price`, plotted && tw && `${tw}/valuation`])

  if (noQuote) {
    return <NotYet title="沒有報價，算不出估值">本益比、股價淨值比與殖利率都要用到股價。</NotYet>
  }
  if (valuation.isError) return <ErrorState error={valuation.error} onRetry={() => void valuation.refetch()} />
  if (!valuation.data) return <ChartSkeleton height={420} />
  const v = valuation.data
  const hasPer = v.per_multiples.length > 0 && v.series.some((p) => p.eps_ttm !== null)
  const hasPbr = v.pbr_multiples.length > 0 && v.series.some((p) => p.bvps !== null)

  if (!hasPer && !hasPbr) {
    return (
      <div className="flex flex-col gap-10">
        <NotYet title={instrument.type === "etf" ? "ETF 沒有本益比與股價淨值比河流圖" : "這檔還沒有估值資料"}>
          {instrument.type === "etf"
            ? instrument.market === "US"
              ? "ETF 是一籃子股票，沒有自己的每股盈餘與帳面淨值；美股目前也沒有可商用的配息資料來源。"
              : "ETF 是一籃子股票，沒有自己的每股盈餘與帳面淨值。下面是淨值與折溢價、殖利率走勢。"
            : "還沒有這檔的歷史每股盈餘與淨值資料。"}
        </NotYet>
        {instrument.type === "etf" && instrument.market !== "US" && <EtfNavSection inst={instrument} titleId="val-premium" />}
        <YieldPanel valuation={v} />
        <Notes notes={v.notes} />
      </div>
    )
  }
  const activeMode: Mode = mode === "per" && !hasPer ? "pbr" : mode === "pbr" && !hasPbr ? "per" : mode
  // 期間照資料實際的長度寫：商用模式的存檔從 2026-06-01 才開始累積，不能說成「近 5 年」
  const span = valuationSpan(v.series, appToday())
  // 後端的說明分兩種：狀態（「資料累積中…」）一直看得到；算法（「EPS = 收盤價 ÷ 本益比」）收進河流圖的「怎麼看 ⌄」
  const status = v.notes.filter((n) => n.startsWith("資料累積中"))
  const method = v.notes.filter((n) => !status.includes(n))
  // 估值位置（百分位）只在右邊「現在的本益比」說一次
  return (
    <div className="flex flex-col gap-5">
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
        <span className="text-sm text-ink-2">
          {span.full ? "近 5 年" : span.label}・{cadenceLabel(v)}
        </span>
        {v.is_demo && <DemoTag className="ml-auto" />}
      </div>
      <RiverPanel valuation={v} mode={activeMode} instrument={instrument} position={position} span={span.label} method={method} />
      <YieldPanel valuation={v} />
      <Notes notes={status} />
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

/** 後端的說明（數字的算法、EPS ≤ 0 留白、資料累積中等）：照原文放在圖表下面 */
function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null
  return (
    <ul className="flex flex-col gap-0.5 text-sm text-ink-2">
      {notes.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  )
}

function RiverPanel({
  valuation,
  mode,
  instrument,
  position,
  span,
  method,
}: {
  valuation: Valuation
  mode: Mode
  instrument: InstrumentDetail
  position: Position | null
  span: string
  method: string[]
}) {
  const privacy = usePrefs((s) => s.privacyMode)
  const you = useWho("你")
  const multiples = mode === "per" ? valuation.per_multiples : valuation.pbr_multiples
  const rows = useMemo(() => buildRiver(valuation.series, multiples, mode), [valuation.series, multiples, mode])
  const runs = useMemo(() => invalidRuns(rows), [rows])
  const last = rows.at(-1)
  const lastValid = [...rows].reverse().find((r) => r.base !== null && r.base > 0)
  const market = instrument.market
  const type = instrument.type
  const perShare = (n: number) => formatPerShare(n, market)
  const baseLabel = mode === "per" ? "近四季 EPS" : "每股淨值"
  const ratioLabel = mode === "per" ? "本益比" : "股價淨值比"
  const currentRatio = mode === "per" ? valuation.current.per : valuation.current.pbr
  const currentInvalid = !last || last.base === null || last.base <= 0
  const chartData = rows.map((r) => ({ t: r.t, close: r.close, ...Object.fromEntries(r.bands.map((b, i) => [`b${i}`, b])) }))
  const [box, width] = useWidth<HTMLDivElement>()
  const axis = monthTicks(rows.map((r) => r.t), Math.floor((width - 56) / MONTH_LABEL_WIDTH))
  const howTo = useHowToRead()

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
    <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_300px]">
      <Panel title={`${ratioLabel}河流圖`} titleId="river-title" bodyClassName="pt-1" action={howTo.toggle}>
        {howTo.panel(
          <>
            <p>
              每條帶是「{baseLabel} × 倍數」的股價，由下往上越來越貴（最下面到 {multiples[0]} 倍、最上面到 {multiples.at(-1)} 倍）；收盤價落在越上面的帶越貴。
            </p>
            {method.map((n) => (
              <p key={n} className="mt-1">
                {n.endsWith("。") ? n : `${n}。`}
              </p>
            ))}
          </>,
          "mb-2",
        )}
        <RiverLegend multiples={multiples} className="mb-1" />
        {runs.length > 0 && (
          <p className="mb-1 border-y border-rule py-2 text-sm">
            <span className="font-medium">{runs.map((r) => `${formatDate(r.from)}–${formatDate(r.to)}`).join("、")}</span>
            ：{baseLabel} ≤ 0，{ratioLabel}沒有意義，這段期間不畫區間。
          </p>
        )}
        <div ref={box} className="h-[340px] w-full sm:h-[380px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} ticks={axis.ticks} interval={0} tickFormatter={axis.format} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56} tickFormatter={(n: number) => formatNumber(n)} domain={[0, "auto"]} />
              {runs.map((r) => (
                <ReferenceArea key={r.from} x1={r.from} x2={r.to} fill="var(--hov)" fillOpacity={0.9} ifOverflow="extendDomain" />
              ))}
              {/* 帶與帶之間一條 1px 紙色線（每條帶的上緣）：相鄰的兩階不只靠色差分辨 */}
              {multiples.map((m, i) => (
                <Area
                  key={m}
                  dataKey={`b${i}`}
                  stackId="river"
                  type="linear"
                  fill={BAND_VARS[i] ?? BAND_VARS[4]}
                  fillOpacity={1}
                  stroke="var(--paper)"
                  strokeWidth={1}
                  isAnimationActive={false}
                  connectNulls={false}
                  activeDot={false}
                />
              ))}
              {/* 收盤價線底下墊一條紙色的寬線：深色模式最貴的一階很亮，墨色線落在上面也看得清楚 */}
              <Line dataKey="close" stroke="var(--paper)" strokeWidth={5} dot={false} isAnimationActive={false} activeDot={false} legendType="none" tooltipType="none" />
              <Line dataKey="close" stroke="var(--ink)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: "var(--paper)", strokeWidth: 2 }} />
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
                        { label: "收盤", value: formatPrice(r.close, market, type), color: "var(--ink)", shape: "line" },
                        { label: ratioLabel, value: r.ratio !== null ? `${r.ratio.toFixed(1)} 倍` : "不適用" },
                        { label: baseLabel, value: r.base !== null ? perShare(r.base) : "—" },
                        ...(valid
                          ? [...multiples].reverse().map((m) => ({ label: `${m} 倍`, value: formatPriceLevel(r.base! * m, market, type), color: BAND_VARS[multiples.indexOf(m)] }))
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
            <p className="text-2xl font-medium">不適用</p>
            <p className="text-md text-ink-2">
              {baseLabel}目前 ≤ 0（{last?.base !== null && last?.base !== undefined ? perShare(last.base) : "無資料"}），{ratioLabel}沒有意義。可改看股價淨值比或殖利率。
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <p className="hero-figure text-4xl font-medium">
                {currentRatio?.toFixed(1)}
                <span className="ml-1 text-lg font-medium text-ink-2">倍</span>
              </p>
              {bracket && <p className="mt-2 text-md text-ink">{bracket}</p>}
              {mode === "per" && valuation.current.per_percentile_5y !== null && (
                <p className="mt-1 text-md text-ink">
                  比{beforeSpan(span)} <Fig>{formatPercent(valuation.current.per_percentile_5y, { signed: false, decimals: 0 })}</Fig> 的日子貴。
                </p>
              )}
            </div>
            <dl className="flex flex-col gap-1 text-md">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-2">{baseLabel}</dt>
                <dd className="num">{perShare(last!.base!)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-2">收盤價</dt>
                <dd className="num">{formatPrice(last!.close, market, type)}</dd>
              </div>
            </dl>
            <table className="w-full text-md">
              <caption className="mb-1 text-left text-sm text-ink-2">各倍數對應的股價（今天）</caption>
              <tbody>
                {bandRows.map((row) =>
                  row.kind === "price" ? (
                    <tr key="price" aria-current="true" className="sel-row border-b border-rule font-bold text-ink">
                      <th scope="row" className="py-1.5 pl-2 text-left">現價</th>
                      <td className="num py-1.5 pr-2 text-right" colSpan={2}>{formatPrice(row.price, market, type)}</td>
                    </tr>
                  ) : (
                    <tr key={row.m} className="border-b border-rule last:border-0">
                      <th scope="row" className="py-1.5 pl-2 text-left font-normal">
                        <span className="inline-flex items-center gap-2">
                          <span aria-hidden className="size-2.5 rounded-xs ring-1 ring-ctl" style={{ background: BAND_VARS[row.idx] }} />
                          {row.m} 倍
                        </span>
                      </th>
                      <td className="num py-1.5 pr-2 text-right" colSpan={2}>{formatPriceLevel(row.price, market, type)}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            {position && mode === "per" && last?.base && last.base > 0 && (
              <p className="text-md text-ink">
                <span className="text-ink-2">{you}的均價</span>{" "}
                {privacy ? "••••" : `${formatPrice(position.avg_cost, market, type)}，約 ${(position.avg_cost / last.base).toFixed(1)} 倍`}
              </p>
            )}
          </div>
        )}
      </Panel>
    </div>
  )
}

function YieldPanel({ valuation }: { valuation: Valuation }) {
  const data = valuation.series.filter((p) => p.dividend_yield !== null).map((p) => ({ t: p.t, y: p.dividend_yield! }))
  const current = valuation.current.dividend_yield
  const [box, width] = useWidth<HTMLDivElement>()
  const axis = monthTicks(data.map((d) => d.t), Math.floor((width - 48) / MONTH_LABEL_WIDTH))
  const howTo = useHowToRead()
  return (
    <Panel
      title="殖利率走勢"
      titleId="yield-title"
      aside={current !== null && <span className="num text-md text-ink"><span className="text-ink-2">目前</span> {formatPercent(current, { signed: false })}</span>}
      action={data.length >= 2 ? howTo.toggle : undefined}
    >
      {data.length < 2 ? (
        <p className="text-md text-ink-2">還沒有足夠的配息資料可以畫殖利率走勢。</p>
      ) : (
        <>
          {howTo.panel(<p>殖利率＝近 12 個月現金股利 ÷ 收盤價。</p>, "mb-2")}
          <div ref={box} className="h-[180px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={GRID_STROKE} />
                <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} ticks={axis.ticks} interval={0} tickFormatter={axis.format} />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} tickFormatter={(n: number) => formatPercent(n, { signed: false, decimals: 1 })} />
                <Tooltip
                  cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
                  content={({ active, payload }) => {
                    const row = active ? (payload?.[0]?.payload as { t: string; y: number } | undefined) : undefined
                    return row ? <ChartTooltipBox title={formatDate(row.t)} rows={[{ label: "殖利率", value: formatPercent(row.y, { signed: false }) }]} /> : null
                  }}
                />
                <Line dataKey="y" stroke="var(--chart-mine)" strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: "var(--paper)", strokeWidth: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </Panel>
  )
}

/**
 * 河流圖的圖例：收盤價（墨色線）＋各倍數的色塊。色塊有 1px 鉛筆灰外框：深色模式最便宜的一階和頁面很接近，
 * 外框讓它在圖例裡也分得出來（圖上的帶與帶之間另有紙色分隔線）。
 */
function RiverLegend({ multiples, className }: { multiples: number[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 text-sm", className)}>
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-0.5 w-3.5 shrink-0 rounded-full bg-ink" />
        <span className="text-ink-2">收盤價</span>
      </li>
      {multiples.map((m, i) => (
        <li key={m} className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 shrink-0 rounded-xs ring-1 ring-ctl" style={{ background: BAND_VARS[i] ?? BAND_VARS[4] }} />
          <span className="text-ink-2">{m} 倍</span>
        </li>
      ))}
    </ul>
  )
}
