import { useState } from "react"
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { useAccounts, useHoldings, usePerformance } from "@/api/queries"
import type { Holding, Performance } from "@/api/types"
import { BenchmarkSelect } from "@/components/benchmark-select"
import { usePrefSetter } from "@/hooks/use-pref-setter"
import { ChartTooltipBox, Legend, RangeChips } from "@/components/charts/chart-kit"
import { AXIS_TICK, GRID_STROKE, monthTick } from "@/lib/chart"
import { ReturnChart } from "@/components/charts/ReturnChart"
import { Pct } from "@/components/finance"
import { DemoTag, Section as Panel } from "@/components/section"
import { ChartSkeleton, EmptyState, ErrorState } from "@/components/states"
import { DataNotes } from "@/components/data-notes"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip as Tip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { direction, formatCompact, formatDate, formatMoney, formatNumber, formatPercent, MASK, toneClass } from "@/lib/format"
import { TREND_RANGES } from "@/lib/trend-range"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { niceTicks } from "@/ai/chart-geometry"
import { inText } from "@/lib/cjk"
import { useHowToRead } from "@/pages/stock/tabs/how-to-read"
import { useReadOnly, useWho } from "@/api/view-as"
import { isUnpricedNote } from "./trend-reason"
import { useTrendRange } from "./use-trend-range"

/**
 * 算不出來、而且換區間或基準也沒有用：有持股還沒有收盤價（剛加入、還沒抓到收盤價的美股；後端的說明是
 * 「MSFT：還沒有收盤價，績效算不出來」，美股收盤價沒開時是「…：美股沒有報價，…」）
 */
function isBlocked(p: Performance | undefined, isError: boolean): boolean {
  return !!p && !isError && p.series.length < 2 && (p.notes ?? []).some(isUnpricedNote)
}

/**
 * 績效分段：報酬率與基準（總資產與投入本金的走勢在主數字下方，這裡不重複畫；產品負責人 2026-11-17）。
 * 區間和主數字下方的總資產走勢是同一個選擇（`useTrendRange`）：整頁只有一排區間按鈕——在這個分段時放在這裡的工具列，
 * 上面的走勢跟著換、自己不放按鈕。可以選的區間也一樣：資料撐得起來的才放（看這個帳戶「全部」的序列），沒有「1日」。
 */
export function PerformanceView() {
  // undefined＝全部帳戶
  const [account, setAccount] = useState<string | undefined>()
  const trend = useTrendRange(account)
  const range = trend.range
  // 可以選的區間：讀到「全部」的序列才知道；讀不到時全部列出（不讓區間沒辦法換）
  const rangeOptions = trend.known ? TREND_RANGES.filter((r) => trend.ranges.includes(r.value)) : trend.perf.isError ? TREND_RANGES : []
  const accounts = useAccounts()
  // 查看別人的資產：基準用授權者的（伺服器決定），不送自己的偏好
  const readOnly = useReadOnly()
  const me = useWho("我")
  const prefBenchmark = usePrefs((s) => s.benchmark)
  const benchmark = readOnly ? undefined : prefBenchmark
  const setPref = usePrefSetter()
  const accountOptions = accounts.data ?? []
  // 美股也有收盤價（2026-11-15）：全部帳戶照常算得出來，不再自動改看新台幣帳戶
  const perf = usePerformance(range, account, benchmark)
  const holdings = useHoldings(account)
  const p = perf.data
  // 算不出來、而且換區間或基準也沒有用（有持股還沒有收盤價）：區間與比較基準不放，只留帳戶——那是唯一有用的控制項
  const blocked = isBlocked(p, perf.isError)

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        {!blocked && rangeOptions.length > 0 && <RangeChips label="績效區間" value={range} options={rangeOptions} onChange={trend.setRange} />}
        <Select
          value={account ?? "all"}
          onValueChange={(v) => setAccount(v === "all" ? undefined : (v as string))}
          items={[{ value: "all", label: "全部帳戶" }, ...accountOptions.map((a) => ({ value: a.id, label: a.name }))]}
        >
          <SelectTrigger size="sm" className="min-w-36 pointer-coarse:data-[size=sm]:h-11" aria-label="帳戶">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部帳戶</SelectItem>
            {accountOptions.map((a) => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
          </SelectContent>
        </Select>
        {/* 查看別人的資產：基準由授權者決定，名稱在圖例裡；這裡不放沒有控制項的標籤 */}
        {!blocked && !readOnly && (
          <span className="inline-flex items-center gap-2 text-sm text-ink-2">
            比較基準
            <BenchmarkSelect size="sm" className="min-w-44 pointer-coarse:data-[size=sm]:h-11" value={prefBenchmark} onChange={(v) => setPref({ benchmark: v })} />
          </span>
        )}
        {/* 期間（計算方式在最下面的「計算方式」） */}
        {(p?.start_date && p.end_date) || p?.is_demo ? (
          <p className="num flex items-center gap-2 text-sm text-ink-2 lg:ml-auto">
            {p.start_date && p.end_date && `${formatDate(p.start_date)} – ${formatDate(p.end_date)}`}
            {p.is_demo && <DemoTag title={holdings.data?.some((h) => h.is_demo) ? "含示範資料" : undefined} />}
          </p>
        ) : null}
      </div>

      {perf.isError ? (
        <ErrorState error={perf.error} onRetry={() => void perf.refetch()} />
      ) : !p ? (
        <>
          <div className="grid grid-cols-2 border-t border-rule lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => <div key={i} className="border-b border-rule py-4"><Skeleton className="h-4 w-20" /><Skeleton className="mt-2 h-7 w-24" /></div>)}
          </div>
          <ChartSkeleton height={300} />
        </>
      ) : p.series.length < 2 ? (
        <NotEnough p={p} blocked={blocked} account={account} accounts={accountOptions} holdings={holdings.data} onAccount={setAccount} />
      ) : (
        <div className={cn("flex flex-col gap-4 transition-opacity", perf.isPlaceholderData && "opacity-60")}>
          <DataNotes notes={p.notes} />
          <Metrics p={p} />
          <Panel title="與基準比較" titleId="cmp-title">
            <Legend
              className="mb-2"
              items={[
                { label: `${me}的（時間加權）`, color: "var(--chart-mine)", shape: "line", value: <Pct value={p.twr} /> },
                { label: p.benchmark?.name ?? "基準", color: "var(--chart-bench)", shape: "line", value: formatPercent(p.benchmark?.twr) },
              ]}
            />
            {p.benchmark && p.benchmark.twr === null && (
              <p className="mb-2 text-base text-ink">「{p.benchmark.name}」這段期間沒有資料，不能比較。</p>
            )}
            <ReturnChart series={p.series} showBenchmark benchmarkName={p.benchmark?.name ?? "基準"} mineLabel={`${me}的報酬`} height={300} />
          </Panel>
          <div className="grid gap-10 xl:grid-cols-2">
            <DividendsByMonth p={p} />
            <RealizedByYear p={p} />
          </div>
          <Definitions />
        </div>
      )}
    </div>
  )
}

/**
 * 算不出績效時（空狀態，全站同一種）：標題＋後端 notes 的原文說明為什麼（商用模式：存檔不足、有持股還沒有收盤價），
 * 最多一個現在能做的事——有持股還沒有收盤價時，只看一個沒有那幾檔的帳戶（有持股、每一檔都有收盤價的第一個帳戶）；
 * 其他帳戶從上面的帳戶選單選。原因在這一頁只說這一次（主數字下方的「總資產走勢：…」在績效分段不出現）。
 */
function NotEnough({ p, blocked, account, accounts, holdings, onAccount }: { p: Performance; blocked: boolean; account?: string; accounts: { id: string; name: string }[]; holdings?: Holding[]; onAccount: (id: string) => void }) {
  const notes = p.notes ?? []
  const other = blocked && !account ? pricedAccount(accounts, holdings) : undefined
  return (
    <EmptyState
      // 這個分段的最後一塊：下面那條線是頁尾（資料來源）的上緣格線，不重複畫、不夾一段空白
      className="border-b-0 pb-0"
      title={notes.length ? "算不出績效" : "資料還不夠計算績效"}
      description={
        // 後端的原文，一則一行（放在空狀態的說明段落裡，所以用 span 不用清單）
        notes.length
          ? [...new Set(notes)].map((n) => (
              <span key={n} className="block">
                {n}
              </span>
            ))
          : "至少需要兩個交易日的持股資料。記下交易後，隔一個交易日就會出現。"
      }
      action={
        other ? (
          <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={() => onAccount(other.id)}>
            只看「{other.name}」
          </Button>
        ) : undefined
      }
    />
  )
}

/** 有持股、而且每一檔都有收盤價的第一個帳戶（沒有收盤價的持股在哪些帳戶，看持股的 `account_ids`） */
function pricedAccount<A extends { id: string }>(accounts: A[], holdings?: Holding[]): A | undefined {
  if (!holdings) return undefined
  const unpriced = new Set(holdings.filter((h) => h.price === null).flatMap((h) => h.account_ids))
  if (unpriced.size === 0) return undefined
  const held = new Set(holdings.filter((h) => h.price !== null).flatMap((h) => h.account_ids))
  return accounts.find((a) => held.has(a.id) && !unpriced.has(a.id))
}

function Metrics({ p }: { p: Performance }) {
  const you = useWho("你")
  const excess = p.twr !== null && p.benchmark?.twr != null ? p.twr - p.benchmark.twr : null
  const items: { label: string; help: string; value: React.ReactNode; sub?: React.ReactNode }[] = [
    {
      label: "時間加權報酬（TWR）",
      help: "不受存入、提出的影響，適合和基準比。",
      value: <Pct value={p.twr} />,
      sub: excess !== null && (
        // 和基準的差距不是價格漲跌：不用紅綠，用「多／少」說方向
        // 報酬率相減是「個百分點」，不是百分比；中文名稱前後不加空白（英數字的名稱才加）
        <span>
          比{inText(p.benchmark?.name ?? "基準")}
          {excess >= 0 ? "多" : "少"} <span className="num font-medium text-ink">{(Math.abs(excess) * 100).toFixed(2)}</span> 個百分點
        </span>
      ),
    },
    {
      label: "年化 XIRR",
      help: `算進每一筆投入與取回的時間，是${you}實際的年化報酬。`,
      value: p.xirr === null ? <span className="text-ink-2">—</span> : <Pct value={p.xirr} />,
      sub: p.xirr === null ? (p.range === "1D" || p.range === "5D" ? "5 天以內不年化" : "期間太短或現金流不足，無法計算") : "金額加權",
    },
    {
      label: "最大回撤",
      help: "期間內從最高點往下跌的最大幅度（以時間加權指數計算）。",
      value: <span className="num">{formatPercent(p.max_drawdown)}</span>,
    },
    {
      label: "年化波動度",
      help: "每日報酬的標準差 × √252。數字越大，帳面起伏越大。",
      value: <span className="num">{formatPercent(p.volatility, { signed: false })}</span>,
      sub: "每日報酬年化",
    },
  ]
  return (
    <dl className="grid grid-cols-1 border-t border-rule min-[420px]:grid-cols-2 lg:grid-cols-4">
      {items.map((m) => (
        <div key={m.label} className="flex flex-col gap-1 border-b border-rule py-4 pr-4 min-[420px]:[&:nth-child(odd)]:border-r min-[420px]:[&:nth-child(even)]:pl-4 lg:border-r lg:pl-4 lg:first:pl-0 lg:last:border-r-0">
          <dt className="text-sm text-ink-2">
            <Tip>
              <TooltipTrigger render={<span className="cursor-help underline decoration-dotted underline-offset-4">{m.label}</span>} />
              <TooltipContent className="max-w-64">{m.help}</TooltipContent>
            </Tip>
          </dt>
          <dd className="text-2xl font-semibold">{m.value}</dd>
          {m.sub && <dd className="text-sm text-ink-2">{m.sub}</dd>}
        </div>
      ))}
    </dl>
  )
}

function DividendsByMonth({ p }: { p: Performance }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const total = p.dividends_by_month.reduce((s, d) => s + d.amount, 0)
  return (
    <Panel title="每月股利" titleId="divm-title" aside={<span className="num text-md text-ink-2">{privacy ? MASK : `合計 ${formatMoney(total)}`}</span>}>
      {p.dividends_by_month.length === 0 ? (
        <p className="text-base text-ink">這段期間沒有收到股利。</p>
      ) : privacy ? (
        <p className="py-10 text-center text-base text-ink">隱私模式開啟中，金額圖表已隱藏。</p>
      ) : (
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={p.dividends_by_month} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="month" tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={monthTick} minTickGap={12} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56} {...amountAxis(0, Math.max(...p.dividends_by_month.map((d) => d.amount)))} />
              <Tooltip
                cursor={{ fill: "var(--muted)" }}
                content={({ active, payload }) => {
                  const r = active ? (payload?.[0]?.payload as { month: string; amount: number } | undefined) : undefined
                  return r ? <ChartTooltipBox title={r.month.replace("-", "/")} rows={[{ label: "股利（已扣二代健保）", value: formatMoney(r.amount), color: "var(--chart-mine)" }]} /> : null
                }}
              />
              <Bar dataKey="amount" fill="var(--chart-mine)" radius={[2, 2, 0, 0]} maxBarSize={28} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  )
}

function RealizedByYear({ p }: { p: Performance }) {
  const privacy = usePrefs((s) => s.privacyMode)
  return (
    <Panel title="每年已實現損益" titleId="real-title">
      {p.realized_by_year.length === 0 ? (
        <p className="text-base text-ink">這段期間沒有賣出，沒有已實現損益。</p>
      ) : p.realized_by_year.length === 1 ? null : privacy ? (
        // 只有一年時不畫圖：一根柱子的半版圖只是把下面那一行再畫一次
        <p className="py-10 text-center text-base text-ink">隱私模式開啟中，金額圖表已隱藏。</p>
      ) : (
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={p.realized_by_year.map((r) => ({ ...r, year: String(r.year) }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID_STROKE} />
              <XAxis dataKey="year" tick={AXIS_TICK} tickLine={false} axisLine={false} />
              <YAxis
                tick={AXIS_TICK}
                tickLine={false}
                axisLine={false}
                width={64}
                {...amountAxis(Math.min(0, ...p.realized_by_year.map((r) => r.amount)), Math.max(0, ...p.realized_by_year.map((r) => r.amount)))}
              />
              <ReferenceLine y={0} stroke="var(--muted-foreground)" />
              <Tooltip
                cursor={{ fill: "var(--muted)" }}
                content={({ active, payload }) => {
                  const r = active ? (payload?.[0]?.payload as { year: string; amount: number } | undefined) : undefined
                  return r ? <ChartTooltipBox title={`${r.year} 年`} rows={[{ label: "已實現損益", value: formatMoney(r.amount, { signed: true }) }]} /> : null
                }}
              />
              <Bar dataKey="amount" radius={[2, 2, 0, 0]} maxBarSize={48} isAnimationActive={false}>
                {p.realized_by_year.map((r) => (
                  <Cell key={r.year} fill={r.amount >= 0 ? "var(--rise)" : "var(--fall)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <ul className={cn("flex flex-wrap gap-x-4", p.realized_by_year.length === 1 ? "text-base" : "mt-2 text-sm")}>
        {p.realized_by_year.map((r) => (
          <li key={r.year} className="num">
            <span className="text-ink-2">{r.year} 年：</span>
            <span className={toneClass(direction(r.amount))}>
              {privacy ? MASK : formatMoney(r.amount, { signed: true })}
              <span className="sr-only">{direction(r.amount) === "up" ? "獲利" : direction(r.amount) === "down" ? "虧損" : ""}</span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

/** 「計算方式 ⌄」：和「怎麼看 ⌄」「怎麼算的 ⌄」同一種開關（不用瀏覽器的 ▶；觸控 44px） */
function Definitions() {
  const how = useHowToRead("計算方式")
  return (
    <div className="border-y border-rule py-2">
      {how.toggle}
      {how.panel(
      <div className="mt-2 mb-1 flex flex-col gap-2 text-base text-ink">
        <p>價格用未還原收盤價；股利另以交易紀錄計入。</p>
        <p>投資組合價值是每天收盤後所有持股的市值（美股依中央銀行公布的當日新臺幣對美元收盤匯率換算成新台幣），不含現金部位。</p>
        <p>每日報酬 = （當日市值 + 當日流出）÷（前一日市值 + 當日流入）− 1。買進成本（含手續費）視為開盤前流入；賣出淨收入與現金股利（扣二代健保）視為收盤後流出。</p>
        <p>時間加權報酬（TWR）把每日報酬連乘；XIRR 以投資人的現金流（買進為負、賣出與股利為正、期末市值為正）求年化內部報酬率；最大回撤以 TWR 指數計算。</p>
      </div>,
      )}
    </div>
  )
}

/** 金額的縱軸：整齊的刻度（1、2、2.5、5 × 10ⁿ）；同一條軸只用一種寫法——10 萬以下寫整數，以上寫「萬」 */
function amountAxis(lo: number, hi: number): { ticks: number[]; domain: [number, number]; tickFormatter: (n: number) => string } {
  const ticks = niceTicks(lo, hi)
  const big = Math.max(...ticks.map(Math.abs)) >= 100_000
  return { ticks, domain: [ticks[0]!, ticks.at(-1)!], tickFormatter: (n) => (big ? formatCompact(n, 1) : formatNumber(n)) }
}
