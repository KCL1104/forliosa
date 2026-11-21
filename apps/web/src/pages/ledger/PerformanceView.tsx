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
import { responseExceedsData, TREND_RANGES, trendState } from "@/lib/trend-range"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { niceTicks } from "@/ai/chart-geometry"
import { inText } from "@/lib/cjk"
import { useHowToRead } from "@/pages/stock/tabs/how-to-read"
import { useReadOnly, useWho } from "@/api/view-as"
import { isReferenceNote } from "@/lib/data-notes"
import { isUnpricedNote, trendClipNote, trendReferenceLine } from "./trend-reason"
import { useTrendChipsShown, useTrendRange } from "./use-trend-range"
import { touchesSpan, trendEstimatedText } from "./composition-text"
import { FundRankLine, MonthlyTable } from "./MonthlyTable"

/**
 * 算不出來、而且換區間或基準也沒有用：有持股還沒有收盤價（剛加入、還沒抓到收盤價的美股；後端的說明是
 * 「MSFT：還沒有收盤價，績效算不出來」，美股收盤價沒開時是「…：美股沒有報價，…」）
 */
function isBlocked(p: Performance | undefined, isError: boolean): boolean {
  return !!p && !isError && p.series.length < 2 && (p.notes ?? []).some(isUnpricedNote)
}

/**
 * 績效分段：報酬率與基準（總資產與投入本金的走勢在主數字下方，這裡不重複畫；產品負責人 2026-11-17）。
 * 區間和主數字下方的總資產走勢是同一個選擇（`useTrendRange`），整頁只有一排區間按鈕：
 * - 走勢下面有按鈕時（畫得出走勢就有，歷史短也有）就用那一排，這裡不放——每個分段都是同一排、同一個位置，
 *   換分段時分段列不會上下跳。
 * - 走勢沒有按鈕時（「自訂」關掉走勢、主數字或走勢讀不到、不到 2 個收盤）才在這裡的工具列放「績效區間」：七顆一律放，
 *   這個帳戶算得出績效（「全部」的序列有 2 個收盤以上）或讀不到時才放（讀不到時不讓區間沒辦法換），沒有「1日」。
 * - 區間比資料長（這個帳戶比較新，或存檔開始以前沒有 Yahoo 參考價）：後端從第一個收盤算起（「績效從 … 收盤開始算」），
 *   數字和走勢的一樣；期間照實寫「只有 2026/11/12 – 2026/11/17 的資料」（看這個帳戶「全部」的序列，而且回應真的從它的
 *   第一個收盤開始：`responseExceedsData`）。
 * - 存檔開始以前的日子用 Yahoo 參考價算（產品負責人 2026-11-18）：後端的 notes 有一句「… 以前用 Yahoo 參考價計算，
 *   不是官方資料」。走勢的區間按鈕下面已經寫了同一件事時（`trendReferenceLine`）這裡不再寫。
 */
export function PerformanceView() {
  // undefined＝全部帳戶
  const [account, setAccount] = useState<string | undefined>()
  const shared = useTrendChipsShown()
  // 首頁走勢的「全部」序列（全部帳戶）與這個帳戶的；兩個的區間是同一個選擇
  const home = useTrendRange().perf
  const own = useTrendRange(account)
  const range = own.range
  const ownSeries = own.perf.data?.series
  // 工具列的區間（走勢下面沒有按鈕時）：這個帳戶畫得出績效才放；讀不到時也放（不讓區間沒辦法換）
  const rangeOptions = shared ? [] : own.perf.isError || (ownSeries && trendState(ownSeries.length) !== "missing") ? TREND_RANGES : []
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
  // 歷史短時走勢的區間按鈕下面已經寫了後端那一句（「績效從 … 收盤開始算」，每個分段都寫）：這裡不再寫一次。
  // 走勢真的畫出來才算（`shared`：主數字讀不到時走勢不在，這一句就留在這裡）
  const trendNote = shared ? trendClipNote(home.data) : undefined
  // 走勢下面已經說了這個區間用到 Yahoo 參考價：這裡不再寫一次（全部帳戶的走勢涵蓋任何一個帳戶用到的日子）
  const heroSaysReference = shared && trendReferenceLine(home.data, range) !== null
  // 期間：看回應自己的區間（換區間時先留著上一個區間的數字，期間也跟著上一個）。回應真的從這個帳戶的第一個收盤開始才寫「只有」：
  // 切換帳戶時兩個查詢回來的先後不同，不會把新帳戶的「全部」和舊帳戶的區間湊在一起寫錯（`responseExceedsData`）
  const exceeds = !!p && responseExceedsData(p, ownSeries)
  // 資產組成（原型）只給自己看（決定 11）：查看別人的資產時，每月拆解、基金排名、估計的說明都不放
  const composition = readOnly ? undefined : p?.composition
  // 這個區間用到估計的買入日：指標下面一行說是哪幾天（和首頁走勢那一行同一個規則：含基準收盤，`trendEstimatedText`）。
  // 看這個帳戶「全部」的序列（區間的回應沒有基準收盤那一點）
  // 分好幾次匯入時每一次一段，一行列出來（「2024/7/29 – 2025/11/28、2026/9/1 – 2026/11/18」）
  const estimateText = composition?.estimated?.length && ownSeries ? trendEstimatedText(ownSeries, range, composition.estimated) : null

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        {!blocked && rangeOptions.length > 0 && <RangeChips label="績效區間" value={range} options={rangeOptions} onChange={own.setRange} />}
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
            {p.start_date && p.end_date && (exceeds ? `只有 ${formatDate(p.start_date)} – ${formatDate(p.end_date)} 的資料` : `${formatDate(p.start_date)} – ${formatDate(p.end_date)}`)}
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
          <DataNotes notes={p.notes?.filter((n) => n !== trendNote && !(heroSaysReference && isReferenceNote(n)))} />
          <div>
            {/* 資產組成只給自己看（決定 11）：查看別人的資產時傳 undefined，「含估計的買入日，不年化」也不寫 */}
            <Metrics p={p} composition={composition} />
            {/* 指標都含估計那一段時說一次（13px 淡墨）：報酬、和基準的差距、最大回撤、波動度都是照那段期間的估計持股算的 */}
            {estimateText && (
              <p className="mt-2 text-sm text-ink-2" data-metrics-estimate>
                這些數字含 {estimateText}，{estimateText.includes("、") ? "那幾段" : "那段"}期間用估計的買入日計算。
              </p>
            )}
          </div>
          {!readOnly && <FundRankLine r={p.fund_rank} />}
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
          {!readOnly && <MonthlyTable p={p} />}
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
 * 其他帳戶從上面的帳戶選單選。後端的原文在這個分段只說這一次（主數字下方那一行「總資產走勢：…」說的是走勢，
 * 每個分段都在、一樣高，在這個分段時不是連結）。
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
          : // 只留要知道的那個條件，短的寫法（2026-11-21 評論：「記下交易後，隔一個交易日就會出現」是在敘述介面）
            "要有兩個交易日的持股"
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

function Metrics({ p, composition }: { p: Performance; composition: Performance["composition"] }) {
  const you = useWho("你")
  // 基準比區間晚開始（存檔開始以前沒有資料的指數，從它的第一個收盤起算）：期間不同，不比多少
  const benchLate = p.series[0]?.benchmark_index === null && p.series.some((x) => x.benchmark_index !== null)
  const excess = !benchLate && p.twr !== null && p.benchmark?.twr != null ? p.twr - p.benchmark.twr : null
  // 資產組成（原型）：估計的那一段不算年化報酬（後端這時 xirr 是 null），說出原因。`composition` 是外面已經依「只給自己看」擋過的
  const estimated = p.xirr === null && touchesSpan(composition?.estimated, p.start_date, p.end_date)
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
      sub:
        p.xirr === null
          ? p.range === "1D" || p.range === "5D"
            ? "5 天以內不年化"
            : estimated
              ? "含估計的買入日，不年化"
              : "期間太短或現金流不足，無法計算"
          : "金額加權",
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
