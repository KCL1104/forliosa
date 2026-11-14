import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowDownIcon, ArrowUpIcon, ChevronDownIcon, EllipsisIcon, PinIcon } from "lucide-react"
import { Fragment, useMemo, useState } from "react"
import { useHoldings, useIntraday, useWatchlist } from "@/api/queries"
import type { Holding, WatchItem } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { Masked, Pct } from "@/components/finance"
import { inText } from "@/lib/cjk"
import { DemoTag } from "@/components/section"
import { Sparkline } from "@/components/sparkline"
import { EmptyState, ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, formatMoney, formatPercent, formatPrice, formatQuantity, toneClass } from "@/lib/format"
import { codeOf, formatQuote, marketOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { unpricedHoldings } from "@/lib/ledger-display"
import { ClosedRounds } from "./ClosedRounds"
import { RecurringMark } from "./RecurringMark"
import { useActivePlans } from "./use-active-plans"
import { useLedgerPrefs, type HoldingColumn } from "./ledger-prefs"
import { useColumnLabel } from "./use-column-label"
import { useReadOnly } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { useStartReduce } from "@/pages/transactions/use-start-reduce"
import { SymbolRecords } from "./SymbolRecords"

type SortKey = "value" | "day_pct" | "day_change" | "unrealized" | "unrealized_pct" | "name"

/** 持倉：桌面 5 欄表格（可自訂、可排序）；手機兩行列（左名稱、代號・股數；右現價、今日漲跌） */
export function HoldingsView() {
  const holdings = useHoldings()
  const pinned = useLedgerPrefs((s) => s.pinned)
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "value", dir: "desc" })
  const rows = useMemo(() => {
    const list = [...(holdings.data ?? [])]
    const val = (h: Holding): number | string => {
      switch (sort.key) {
        case "name":
          return h.name
        case "day_pct":
          return h.day_change_pct ?? 0
        case "day_change":
          return h.day_change
        case "unrealized":
          return h.unrealized_pnl
        case "unrealized_pct":
          return h.unrealized_pnl_pct ?? 0
        default:
          return h.market_value
      }
    }
    list.sort((a, b) => {
      const pa = pinned.includes(a.symbol) ? 0 : 1
      const pb = pinned.includes(b.symbol) ? 0 : 1
      if (pa !== pb) return pa - pb
      const va = val(a)
      const vb = val(b)
      const c = typeof va === "string" ? va.localeCompare(vb as string, "zh-TW") : (va as number) - (vb as number)
      return sort.dir === "asc" ? c : -c
    })
    return list
  }, [holdings.data, pinned, sort])

  if (holdings.isError) return <ErrorState error={holdings.error} onRetry={() => void holdings.refetch()} />
  if (holdings.isLoading) return <RowsSkeleton />
  if (rows.length === 0) return (
    <>
      <EmptyLedger />
      <ClosedRounds />
    </>
  )

  return (
    <>
      <HoldingsTable rows={rows} sort={sort} onSort={setSort} pinned={pinned} />
      <HoldingsList rows={rows} pinned={pinned} />
      <UnpricedNote rows={rows} />
      <ClosedRounds />
    </>
  )
}

function UnpricedNote({ rows }: { rows: Holding[] }) {
  const list = unpricedHoldings(rows)
  if (list.length === 0) return null
  return (
    <p className="mt-2.5 text-base text-ink">
      {inText(list.map((h) => h.name).join("、"), "start")}沒有報價，照成本算。
    </p>
  )
}

function EmptyLedger() {
  const ask = useAskAi()
  const readOnly = useReadOnly()
  if (readOnly) return <EmptyState title="目前沒有持股" />
  // 空狀態兩條路：自己填，或跟 AI 說一句
  return (
    <EmptyState
      title="帳本還是空的"
      description="自己填第一筆，或跟 AI 說一句。"
      action={
        <div className="flex flex-wrap gap-2.5">
          <Button onClick={() => ask.action("form")}>記第一筆</Button>
          <Button variant="outline" onClick={() => ask.submit("買 0050 2 張 52.4")}>
            試試「買 0050 2 張 52.4」
          </Button>
        </div>
      }
    />
  )
}

function RowsSkeleton() {
  return (
    <div aria-busy="true" aria-label="持倉載入中">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="flex h-[72px] items-center gap-4 border-b border-rule lg:h-[60px]">
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-20" />
          </div>
          <Skeleton className="h-4 w-16" />
          <Skeleton className="hidden h-4 w-16 md:block" />
        </div>
      ))}
    </div>
  )
}

const SORTABLE: Partial<Record<HoldingColumn, SortKey>> = {
  day_pct: "day_pct",
  day_change: "day_change",
  value: "value",
  unrealized: "unrealized",
  unrealized_pct: "unrealized_pct",
}
const WIDTH: Record<HoldingColumn, string> = {
  price: "w-[150px]",
  day_pct: "w-[140px]",
  day_change: "w-[150px]",
  value: "w-[170px]",
  avg_cost: "w-[120px]",
  unrealized: "w-[150px]",
  unrealized_pct: "w-[110px]",
}

function HoldingsTable({ rows, sort, onSort, pinned }: { rows: Holding[]; sort: { key: SortKey; dir: "asc" | "desc" }; onSort: (s: { key: SortKey; dir: "asc" | "desc" }) => void; pinned: string[] }) {
  const columns = useLedgerPrefs((s) => s.columns)
  const navigate = useNavigate()
  const watch = useWatchlist()
  const readOnly = useReadOnly()
  const maxWeight = Math.max(...rows.map((h) => h.weight), 0.0001)
  const label = useColumnLabel()
  const header = (c: HoldingColumn) => {
    const key = SORTABLE[c]
    const active = key && sort.key === key
    return (
      <th key={c} scope="col" className={cn("h-10 text-right", WIDTH[c])} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
        {key ? (
          <button
            type="button"
            onClick={() => onSort({ key, dir: active && sort.dir === "desc" ? "asc" : "desc" })}
            className={cn("-mr-1 inline-flex h-8 items-center gap-0.5 rounded-sm px-1 hover:text-ink pointer-coarse:h-11", active && "text-ink")}
          >
            {label(c)}
            {/* 排序方向用箭頭（▲▼ 是價格漲跌的符號，不拿來表示排序） */}
            {active && (sort.dir === "desc" ? <ArrowDownIcon aria-hidden className="size-3.5" /> : <ArrowUpIcon aria-hidden className="size-3.5" />)}
          </button>
        ) : (
          label(c)
        )}
      </th>
    )
  }
  const go = (symbol: string) => void navigate({ to: "/stock/$symbol", params: { symbol } })
  const plans = useActivePlans()
  const [open, toggle] = useOpenRows()
  return (
    <table className="w-full border-collapse max-md:hidden" aria-label="持倉">
      <thead className="form-head">
        <tr>
          <th scope="col" className="h-10 text-left">
            名稱
          </th>
          {columns.map(header)}
          {/* 最右邊：動作選單（查看別人的資產時沒有）＋展開每一筆買賣 */}
          <th scope="col" className={readOnly ? "w-10" : "w-[76px]"}>
            <span className="sr-only">動作</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((h) => (
          <Fragment key={h.symbol}>
            <tr className="ruled-row cursor-pointer" onClick={() => go(h.symbol)}>
              <th scope="row" className="h-[60px] py-1.5 pr-3 text-left font-normal">
                {/* 名稱是連到個股頁的連結；定期定額標記是另一個連結（到設定），所以不包在一起 */}
                <span className="flex items-center gap-1.5 text-lg leading-snug font-medium">
                  <Link to="/stock/$symbol" params={{ symbol: h.symbol }} className="rounded-sm hover:underline" onClick={(e) => e.stopPropagation()}>
                    {h.name}
                  </Link>
                  {pinned.includes(h.symbol) && <PinIcon aria-label="已釘選" className="size-3.5 fill-ink-2 text-ink-2" />}
                  {plans.get(h.symbol) && <RecurringMark plans={plans.get(h.symbol)!} className="-my-1" />}
                </span>
                <span className="num block text-sm text-ink-2">
                  {h.code} ・ <QtyText h={h} />
                </span>
              </th>
              {columns.map((c) => (
                <td key={c} className="num text-right text-lg whitespace-nowrap">
                  <Cell c={c} h={h} maxWeight={maxWeight} />
                </td>
              ))}
              <td className="text-right" onClick={(e) => e.stopPropagation()}>
                <span className="-mr-2 flex items-center justify-end">
                  {!readOnly && <RowMenu h={h} />}
                  <ExpandButton h={h} open={open.has(h.symbol)} onToggle={() => toggle(h.symbol)} />
                </span>
              </td>
            </tr>
            {open.has(h.symbol) && (
              <tr>
                <td id={recordsId(h)} colSpan={columns.length + 2} className="border-b border-rule pb-3 pl-6">
                  <SymbolRecords symbol={h.symbol} code={h.code} name={h.name} market={h.market} type={h.type} price={h.price} actions />
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
      {/* 多一欄：持股那幾列最右邊的動作選單 */}
      {!readOnly && <WatchBody items={watch.data} columns={columns.length + 1} loading={watch.isLoading} />}
    </table>
  )
}

/** 這一檔的動作：加碼、減少持股、全部賣出（賣出不用開表單：只填股數，用最新的收盤價記） */
function RowMenu({ h }: { h: Holding }) {
  const openTradeForm = useUi((s) => s.openTradeForm)
  const reduce = useStartReduce()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label={`${h.name}的動作`}
            className="press grid size-9 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink aria-expanded:bg-sel aria-expanded:text-ink"
          />
        }
      >
        <EllipsisIcon aria-hidden className="size-5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuItem onClick={() => openTradeForm({ symbol: h.code })}>加碼</DropdownMenuItem>
        <DropdownMenuItem onClick={() => reduce(h.symbol)}>減少持股</DropdownMenuItem>
        <DropdownMenuItem onClick={() => reduce(h.symbol, true)}>全部賣出</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** 展開的列（可以同時打開好幾檔） */
function useOpenRows(): [Set<string>, (symbol: string) => void] {
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const toggle = (symbol: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  return [open, toggle]
}
const recordsId = (h: Holding) => `records-${h.code}`

/** 展開這一檔的每一筆買賣（日期、股數、價格、金額、買進後漲跌；每一筆可以修改、刪除） */
function ExpandButton({ h, open, onToggle, className }: { h: Holding; open: boolean; onToggle: () => void; className?: string }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={recordsId(h)}
      aria-label={open ? `收起${h.name}的每一筆買賣` : `展開${h.name}的每一筆買賣`}
      onClick={onToggle}
      className={cn("press grid size-9 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink pointer-coarse:size-11", className)}
    >
      <ChevronDownIcon aria-hidden className={cn("size-5 transition-transform duration-200", open && "rotate-180")} />
    </button>
  )
}

function QtyText({ h }: { h: Holding }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  return privacy ? <Masked /> : <>{formatQuantity(h.quantity, unit, h.market)}</>
}

const Dash = () => <span className="text-ink-2" title="沒有報價">—</span>

function Cell({ c, h, maxWeight }: { c: HoldingColumn; h: Holding; maxWeight: number }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number, signed = false) => (privacy ? <Masked /> : formatMoney(n, { signed, bare: true }))
  // 沒有報價（商用模式的美股）：今日與未實現不是真的 0，顯示「—」
  const unpriced = h.price === null
  switch (c) {
    case "price":
      return unpriced ? (
        <Dash />
      ) : (
        <>
          {h.currency === "USD" && <span className="mr-0.5 text-sm text-ink-2">US$</span>}
          {formatQuote(h.price, h.market, h.type)}
        </>
      )
    case "day_pct":
      return unpriced ? <Dash /> : <Pct value={h.day_change_pct} />
    case "day_change":
      return unpriced ? <Dash /> : <span className={toneClass(direction(h.day_change))}>{money(h.day_change, true)}</span>
    case "value":
      return (
        <span className="flex flex-col items-end">
          <span className="leading-tight" title={unpriced ? "沒有報價，照成本算" : undefined}>{money(h.market_value)}</span>
          <span className="mt-0.5 grid grid-cols-[48px_48px] items-center justify-end text-sm leading-tight text-ink-2">
            <span aria-hidden className="relative block h-[3px] w-12 bg-rule">
              <span className="absolute inset-y-0 left-0 bg-ink" style={{ width: `${(h.weight / maxWeight) * 100}%` }} />
            </span>
            {formatPercent(h.weight, { signed: false, decimals: 1 })}
          </span>
        </span>
      )
    case "avg_cost":
      return <>{privacy ? <Masked /> : formatPrice(h.avg_cost, h.market)}</>
    case "unrealized":
      return unpriced ? <Dash /> : <span className={toneClass(direction(h.unrealized_pnl))}>{money(h.unrealized_pnl, true)}</span>
    case "unrealized_pct":
      return unpriced ? <Dash /> : <Pct value={h.unrealized_pnl_pct} />
  }
}

function WatchBody({ items, columns, loading }: { items?: WatchItem[]; columns: number; loading: boolean }) {
  const navigate = useNavigate()
  const visible = useLedgerPrefs((s) => s.columns)
  if (loading) return null
  return (
    <tbody>
      <tr>
        <th scope="colgroup" colSpan={columns + 1} className="h-[72px] border-b border-print pt-7 text-left align-bottom">
          <span className="flex items-baseline gap-2 pb-2 text-base font-bold">
            觀察<span className="num text-sm font-normal text-ink-2">{items?.length ?? 0} 檔</span>
          </span>
        </th>
      </tr>
      {(items ?? []).length === 0 ? (
        <tr>
          <td colSpan={columns + 1} className="p-0">
            <WatchEmpty />
          </td>
        </tr>
      ) : (
        items!.map((w) => {
          const market = marketOf(w.symbol)
          const d = direction(w.quote?.change_pct ?? null)
          return (
            <tr key={w.symbol} className="ruled-row cursor-pointer" onClick={() => void navigate({ to: "/stock/$symbol", params: { symbol: w.symbol } })}>
              <th scope="row" className="h-[60px] py-1.5 pr-3 text-left font-normal">
                <div className="flex items-center justify-between gap-4 pr-1">
                  <Link to="/stock/$symbol" params={{ symbol: w.symbol }} className="group block rounded-sm whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    <span className="block text-lg leading-snug font-medium group-hover:underline">{w.name}</span>
                    <span className="num block text-sm text-ink-2">{codeOf(w.symbol)} ・ 觀察中</span>
                  </Link>
                  <Sparkline
                    values={w.sparkline.map((p) => p.price)}
                    baseline={w.sparkline_interval === "1d" ? null : (w.quote?.reference_price ?? w.quote?.prev_close ?? null)}
                    tone={d}
                    label={`${w.name}今日走勢：${d === "up" ? "上漲" : d === "down" ? "下跌" : "平盤"}`}
                  />
                </div>
              </th>
              {visible.map((c) => (
                <td key={c} className="num text-right text-lg whitespace-nowrap">
                  {c === "price" ? (
                    <>
                      {market === "US" && <span className="mr-0.5 text-sm text-ink-2">US$</span>}
                      {formatQuote(w.quote?.price, market)}
                    </>
                  ) : c === "day_pct" ? (
                    <Pct value={w.quote?.change_pct ?? null} />
                  ) : null}
                </td>
              ))}
              <td />
            </tr>
          )
        })
      )}
    </tbody>
  )
}

/** 觀察是空的：區塊標題的格線就是上面那條線 */
function WatchEmpty() {
  return <EmptyState className="border-t-0" title="還沒有觀察的股票" description="在個股頁按「加入觀察」。" />
}

/** 手機：兩行列 */
function HoldingsList({ rows, pinned }: { rows: Holding[]; pinned: string[] }) {
  const watch = useWatchlist()
  const readOnly = useReadOnly()
  const plans = useActivePlans()
  const label = useColumnLabel()
  const [open, toggle] = useOpenRows()
  return (
    <div className="md:hidden">
      <div className="form-head flex h-11 items-end justify-between pb-2">
        <span>持有 {rows.length} 檔</span>
        <span className="num">
          {label("price")}・{label("day_pct")}
        </span>
      </div>
      <ul aria-label="持倉">
        {rows.map((h) => (
          // 整列可點（名稱連結的 ::after 蓋滿整列）；定期定額標記與右邊的展開鈕浮在上面
          <li key={h.symbol}>
            <div className="ruled-row relative grid h-[72px] grid-cols-[1fr_auto_auto] content-center gap-y-0.5">
              <span className="flex min-w-0 items-center gap-1.5 text-lg leading-6 font-medium">
                <Link
                  to="/stock/$symbol"
                  params={{ symbol: h.symbol }}
                  className="truncate after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-ink"
                >
                  {h.name}
                </Link>
                {pinned.includes(h.symbol) && <PinIcon aria-label="已釘選" className="size-3.5 shrink-0 fill-ink-2 text-ink-2" />}
                {plans.get(h.symbol) && <RecurringMark plans={plans.get(h.symbol)!} className="z-10" />}
              </span>
              <span className="num text-right text-lg leading-6">
                {h.price === null ? <Dash /> : <>{h.currency === "USD" && "US$"}{formatQuote(h.price, h.market, h.type)}</>}
              </span>
              <span className="num text-sm leading-5 text-ink-2">
                {h.code} ・ <QtyText h={h} />
              </span>
              <span className="col-start-2 text-right text-base leading-5">
                {h.price === null ? <Dash /> : <Pct value={h.day_change_pct} />}
              </span>
              <ExpandButton h={h} open={open.has(h.symbol)} onToggle={() => toggle(h.symbol)} className="relative z-10 col-start-3 row-span-2 row-start-1 -mr-2.5 ml-1 self-center" />
            </div>
            {open.has(h.symbol) && (
              <div id={recordsId(h)} className="border-b border-rule pb-3">
                <SymbolRecords symbol={h.symbol} code={h.code} name={h.name} market={h.market} type={h.type} price={h.price} actions />
              </div>
            )}
          </li>
        ))}
      </ul>
      {!readOnly && (
        <>
      <h2 className="mt-9 flex h-11 items-end gap-2 border-b border-print pb-2 text-lg font-bold">
        觀察 <span className="num text-sm font-normal text-ink-2">{watch.data?.length ?? 0} 檔</span>
        {watch.data?.some((w) => w.quote?.is_demo ?? w.is_demo) && <DemoTag className="mb-0.5 ml-auto" />}
      </h2>
      {(watch.data ?? []).length === 0 && !watch.isLoading ? (
        <WatchEmpty />
      ) : (
        <ul aria-label="觀察">
          {(watch.data ?? []).map((w) => (
            <WatchRowMobile key={w.symbol} w={w} />
          ))}
        </ul>
      )}
        </>
      )}
    </div>
  )
}

function WatchRowMobile({ w }: { w: WatchItem }) {
  const market = marketOf(w.symbol)
  const d = direction(w.quote?.change_pct ?? null)
  // 自選本身就帶盤中點；沒有時改抓 intraday
  const fallback = useIntraday(w.symbol, w.sparkline.length < 2)
  const values = w.sparkline.length >= 2 ? w.sparkline.map((p) => p.price) : (fallback.data?.points ?? []).map((p) => p.price)
  return (
    <li>
      <Link to="/stock/$symbol" params={{ symbol: w.symbol }} className="ruled-row grid h-[72px] grid-cols-[1fr_76px_96px] content-center gap-x-3 gap-y-0.5">
        <span className="truncate text-lg leading-6 font-medium">{w.name}</span>
        <Sparkline className="col-start-2 row-span-2 row-start-1 self-center" width={76} height={32} values={values} baseline={w.sparkline_interval === "1d" ? null : (w.quote?.reference_price ?? w.quote?.prev_close ?? null)} tone={d} label={`${w.name}今日走勢`} />
        <span className="num col-start-3 row-start-1 text-right text-lg leading-6">
          {market === "US" && "US$"}
          {formatQuote(w.quote?.price, market)}
        </span>
        <span className="num col-start-1 row-start-2 text-sm leading-5 text-ink-2">{codeOf(w.symbol)}</span>
        <span className="col-start-3 row-start-2 text-right text-base leading-5">
          <Pct value={w.quote?.change_pct ?? null} />
        </span>
      </Link>
    </li>
  )
}
