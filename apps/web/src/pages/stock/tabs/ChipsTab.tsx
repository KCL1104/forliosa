import { MessageCircleQuestionIcon } from "lucide-react"
import { useState } from "react"
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { FOREIGN_FLOW_QUESTION } from "@/ai/suggestions"
import { useAskAi } from "@/ai/use-ask"
import { useChips } from "@/api/queries"
import type { Chips, ChipsRange, InstrumentDetail } from "@/api/types"
import { ChartTooltipBox, Legend } from "@/components/charts/chart-kit"
import { DemoTag, Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { AXIS_TICK, GRID_STROKE } from "@/lib/chart"
import { formatCompact, formatDate, formatDateShort, formatNumber, formatPercent } from "@/lib/format"
import { NotYet, Sources, TabLead } from "./kit"

const RANGES: { value: ChipsRange; label: string }[] = [
  { value: "1M", label: "1月" },
  { value: "3M", label: "3月" },
  { value: "6M", label: "6月" },
  { value: "1Y", label: "1年" },
]

/** 連續買超／賣超天數（最後一天往回數） */
function runOf(values: number[]): { side: "buy" | "sell" | null; days: number } {
  const last = values.at(-1)
  if (last === undefined || last === 0) return { side: null, days: 0 }
  const side = last > 0 ? "buy" : "sell"
  let days = 0
  for (let i = values.length - 1; i >= 0; i--) {
    if ((side === "buy" && values[i]! > 0) || (side === "sell" && values[i]! < 0)) days++
    else break
  }
  return { side, days }
}

function lead(c: Chips): string | null {
  const parts: string[] = []
  const f = runOf(c.institutional.map((r) => r.foreign))
  const t = runOf(c.institutional.map((r) => r.trust))
  if (t.days >= 3) parts.push(`投信連 ${t.days} 天${t.side === "buy" ? "買超" : "賣超"}`)
  if (f.days >= 3) parts.push(`外資連 ${f.days} 天${f.side === "buy" ? "買超" : "賣超"}`)
  return parts.length ? `${parts.join("，")}。` : null
}

/** 千張大戶（1,000 張以上）分級 */
const isBig = (b: { level: string; label?: string }) => /^1,?000/.test(b.label ?? b.level) && /以上/.test(b.label ?? b.level)

const lots = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${formatNumber(Math.abs(n))}`

/**
 * 上市股票的三大法人：沒有逐檔資料（證交所開放資料沒有，網站不能以程式下載），說明原因；
 * 個股可以直接問 AI 最近的外資動向（上網搜尋新聞，附來源與日期）。上櫃股票照常有櫃買的資料。
 */
function ListedInstitutional({ inst, notes }: { inst: InstrumentDetail; notes: string[] }) {
  const ask = useAskAi()
  return (
    <NotYet className="border-t-0 pt-0" title={`上市${inst.type === "etf" ? " ETF" : "股票"}不顯示逐檔三大法人`}>
      {notes.map((n) => (
        <p key={n}>{n}</p>
      ))}
      {inst.type === "stock" && (
        <Button variant="outline" size="sm" className="mt-3" onClick={() => ask.submit(FOREIGN_FLOW_QUESTION)}>
          <MessageCircleQuestionIcon aria-hidden className="text-ai" />
          {FOREIGN_FLOW_QUESTION}
        </Button>
      )}
    </NotYet>
  )
}

/** 籌碼：三大法人、融資融券、外資持股比、千張大戶（單位：張） */
export function ChipsTab({ inst }: { inst: InstrumentDetail }) {
  const [range, setRange] = useState<ChipsRange>("3M")
  const chips = useChips(inst.symbol, range)
  const listed = inst.market === "TWSE"
  if (inst.market === "US") {
    return <NotYet title="美股沒有台股的法人與融資融券資料">美股的機構持股（13F）一季公布一次，之後再評估是否加入。</NotYet>
  }
  if (chips.isError) return <ErrorState error={chips.error} onRetry={() => void chips.refetch()} />
  if (!chips.data) return <Skeleton className="h-96 w-full rounded-sm" />
  const c = chips.data
  if (c.institutional.length === 0 && c.margin.length === 0 && !c.major_holders) {
    return (
      <NotYet title="籌碼資料累積中">
        {c.notes?.length ? c.notes.map((n) => <p key={n}>{n}</p>) : "法人與融資融券在每天 20:00–21:00 更新。"}
      </NotYet>
    )
  }
  const recent = [...c.institutional].reverse().slice(0, 10)
  const sum = (k: "foreign" | "trust" | "dealer" | "total", n: number) => c.institutional.slice(-n).reduce((s, r) => s + r[k], 0)
  const lastDay = (c.institutional.at(-1) ?? c.margin.at(-1))?.t
  // 上市股票的說明放在三大法人的空狀態裡，頁尾的資料來源就不再重複
  const listedNotes = listed ? (c.notes ?? []).filter((n) => n.includes("上市股票")) : []
  const top20Notes = listed ? (c.notes ?? []).filter((n) => n.includes("前 20 名") && !listedNotes.includes(n)) : []
  const otherNotes = (c.notes ?? []).filter((n) => !listedNotes.includes(n) && !top20Notes.includes(n))
  const top = c.foreign_top20 ?? null
  return (
    <div className="flex flex-col gap-12">
      <div className="flex flex-wrap items-center gap-3">
        <RangeChips label="籌碼區間" value={range} options={RANGES} onChange={setRange} />
        <span className="text-sm text-ink-2">{lastDay ? `資料至 ${formatDate(lastDay)}・` : ""}單位：張</span>
        {c.is_demo && <DemoTag className="ml-auto" />}
      </div>
      <TabLead className="-mt-6 mb-0">{lead(c)}</TabLead>

      {listed ? (
        <Section title="三大法人買賣超" titleId="chips-inst">
          <ListedInstitutional inst={inst} notes={listedNotes} />
        </Section>
      ) : c.institutional.length === 0 ? (
        <NotYet title="三大法人資料累積中">{c.notes?.join(" ") ?? "法人買賣超在每天 20:00–21:00 更新。"}</NotYet>
      ) : (
      <Section title="三大法人買賣超" titleId="chips-inst" aside="每日合計">
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={c.institutional} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={40} tickFormatter={(t: string) => formatDateShort(t, false)} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatCompact(v, 1)} />
              <ReferenceLine y={0} stroke="var(--ctl)" />
              <Tooltip
                cursor={{ fill: "var(--hov)" }}
                content={({ active, payload }) => {
                  const r = active ? (payload?.[0]?.payload as Chips["institutional"][number] | undefined) : undefined
                  return r ? (
                    <ChartTooltipBox
                      title={formatDate(r.t)}
                      rows={[
                        { label: "外資", value: lots(r.foreign) },
                        { label: "投信", value: lots(r.trust) },
                        { label: "自營商", value: lots(r.dealer) },
                        { label: "合計", value: lots(r.total) },
                      ]}
                    />
                  ) : null
                }}
              />
              <Bar dataKey="total" maxBarSize={10} isAnimationActive={false}>
                {c.institutional.map((r) => (
                  <Cell key={r.t} fill={r.total >= 0 ? "var(--chart-mine)" : "var(--chart-bench)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <Legend className="mt-1" items={[{ label: "買超", color: "var(--chart-mine)" }, { label: "賣超", color: "var(--chart-bench)" }]} />
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-md">
            <thead>
              <tr className="border-b border-rule text-sm text-ink-2">
                <th scope="col" className="h-9 text-left font-normal">日期</th>
                <th scope="col" className="text-right font-normal">外資</th>
                <th scope="col" className="text-right font-normal">投信</th>
                <th scope="col" className="text-right font-normal">自營商</th>
                <th scope="col" className="text-right font-normal">合計</th>
              </tr>
            </thead>
            <tbody>
              <tr className="num border-b border-rule bg-hov">
                <th scope="row" className="h-10 text-left font-medium">近 5 日</th>
                <td className="text-right">{lots(sum("foreign", 5))}</td>
                <td className="text-right">{lots(sum("trust", 5))}</td>
                <td className="text-right">{lots(sum("dealer", 5))}</td>
                <td className="text-right font-medium">{lots(sum("total", 5))}</td>
              </tr>
              {recent.map((r) => (
                <tr key={r.t} className="num border-b border-rule">
                  <th scope="row" className="h-10 text-left font-normal text-ink-2">{formatDateShort(r.t)}</th>
                  <td className="text-right">{lots(r.foreign)}</td>
                  <td className="text-right">{lots(r.trust)}</td>
                  <td className="text-right">{lots(r.dealer)}</td>
                  <td className="text-right font-medium">{lots(r.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      )}

      <div className="grid gap-12 lg:grid-cols-2">
        <Section title="融資餘額" titleId="chips-margin" aside={c.margin.length ? `${formatNumber(c.margin.at(-1)!.margin_balance)} 張` : undefined}>
          <MiniLine data={c.margin.map((m) => ({ t: m.t, v: m.margin_balance }))} color="var(--chart-mine)" label="融資餘額" fmt={(v) => `${formatNumber(v)} 張`} />
        </Section>
        <Section title="融券餘額" titleId="chips-short" aside={c.margin.length ? `${formatNumber(c.margin.at(-1)!.short_balance)} 張` : undefined}>
          <MiniLine data={c.margin.map((m) => ({ t: m.t, v: m.short_balance }))} color="var(--chart-blue)" label="融券餘額" fmt={(v) => `${formatNumber(v)} 張`} />
        </Section>
        <Section
          title="外資持股比"
          titleId="chips-foreign"
          aside={
            // 上市股票只在最新一份前 20 名名單上才顯示（掉出名單時不拿以前在榜的持股比當現在的）
            listed
              ? top
                ? `${formatPercent(top.pct, { signed: false })}・前 20 名第 ${top.rank} 名`
                : undefined
              : c.foreign_holding_pct.length
                ? formatPercent(c.foreign_holding_pct.at(-1)!.pct, { signed: false })
                : undefined
          }
        >
          {listed ? (
            <ListedForeign inst={inst} chips={c} notes={top20Notes} />
          ) : (
            <MiniLine data={c.foreign_holding_pct.map((m) => ({ t: m.t, v: m.pct }))} color="var(--chart-mine)" label="外資持股比" fmt={(v) => formatPercent(v, { signed: false })} />
          )}
        </Section>
        <Section title="股權分散" titleId="chips-holders" aside={c.major_holders ? `集保 ${formatDateShort(c.major_holders.as_of)}` : undefined}>
          {!c.major_holders ? (
            <p className="text-md text-ink-2">還沒有股權分散資料（每週五公布）。</p>
          ) : (
            <ul className="-mt-3">
              {c.major_holders.buckets.map((b) => (
                <li key={b.level} className="grid grid-cols-[96px_1fr_64px] items-center gap-3 border-b border-rule py-2 text-md">
                  <span className={isBig(b) ? "font-medium" : "text-ink-2"}>{b.label ?? b.level}</span>
                  <span aria-hidden className="relative h-2 bg-hov">
                    <span className="absolute inset-y-0 left-0" style={{ width: `${b.pct * 100}%`, background: isBig(b) ? "var(--ink)" : "var(--band-4)" }} />
                  </span>
                  <span className="num text-right">{formatPercent(b.pct, { signed: false, decimals: 1 })}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <Sources items={[...otherNotes, ...c.sources]} />
    </div>
  )
}

/**
 * 上市股票的外資持股比：證交所開放資料只有「外資及陸資持股前 20 名」（MI_QFIIS_sort_20）。
 * 名列前 20 名時顯示持股比、名次與在榜日的走勢；其他上市股票說明為什麼沒有。
 */
function ListedForeign({ inst, chips, notes }: { inst: InstrumentDetail; chips: Chips; notes: string[] }) {
  const top = chips.foreign_top20
  if (!top) {
    return (
      <p className="text-md text-ink-2">
        證交所只公布外資持股比率前 20 名，{inst.name}目前不在名單上，所以不顯示外資持股比。
      </p>
    )
  }
  return (
    <>
      {chips.foreign_holding_pct.length >= 2 ? (
        <MiniLine data={chips.foreign_holding_pct.map((m) => ({ t: m.t, v: m.pct }))} color="var(--chart-mine)" label="外資持股比" fmt={(v) => formatPercent(v, { signed: false })} />
      ) : (
        <p className="num text-2xl font-medium">{formatPercent(top.pct, { signed: false })}</p>
      )}
      <p className="mt-2 text-md text-ink-2">
        {formatDateShort(top.as_of)} 名列證交所外資及陸資持股前 20 名第 {top.rank} 名。{notes.map((n) => (n.endsWith("。") ? n : `${n}。`)).join("")}
      </p>
    </>
  )
}

function MiniLine({ data, color, label, fmt }: { data: { t: string; v: number }[]; color: string; label: string; fmt: (v: number) => string }) {
  if (data.length < 2) return <p className="text-md text-ink-2">資料不足。</p>
  // 比率的變化很小時（例如外資持股 75.2%–75.5%），刻度要有一位小數才不會重複
  const values = data.map((d) => d.v)
  const pctDecimals = Math.max(...values) - Math.min(...values) < 0.03 ? 1 : 0
  return (
    <div className="h-[140px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID_STROKE} />
          <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={48} tickFormatter={(t: string) => formatDateShort(t, false)} />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56} domain={["auto", "auto"]} tickFormatter={(v: number) => (v < 1 ? formatPercent(v, { signed: false, decimals: pctDecimals }) : formatCompact(v, 1))} />
          <Tooltip
            cursor={{ stroke: "var(--ink-2)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const r = active ? (payload?.[0]?.payload as { t: string; v: number } | undefined) : undefined
              return r ? <ChartTooltipBox title={formatDate(r.t)} rows={[{ label, value: fmt(r.v) }]} /> : null
            }}
          />
          <Line dataKey="v" stroke={color} strokeWidth={1.75} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
