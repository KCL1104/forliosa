import { Link, useNavigate } from "@tanstack/react-router"
import { PinIcon } from "lucide-react"
import { useMemo, useState } from "react"
import { useHoldings, useIntraday, useWatchlist } from "@/api/queries"
import type { Holding, WatchItem } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { Masked, Pct } from "@/components/finance"
import { DemoTag } from "@/components/section"
import { Sparkline } from "@/components/sparkline"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, formatMoney, formatPercent, formatPrice, formatQuantity, toneClass } from "@/lib/format"
import { codeOf, formatQuote, marketOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { COLUMN_LABEL, useLedgerPrefs, type HoldingColumn } from "./ledger-prefs"

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
  if (rows.length === 0) return <EmptyLedger />

  return (
    <>
      <HoldingsTable rows={rows} sort={sort} onSort={setSort} pinned={pinned} />
      <HoldingsList rows={rows} pinned={pinned} />
    </>
  )
}

function EmptyLedger() {
  const ask = useAskAi()
  return (
    <div className="border-y border-rule py-8">
      <p className="text-lg font-medium">帳本還是空的</p>
      <p className="mt-1 max-w-prose text-ink-2">跟 AI 說一句就能記下第一筆，例如「買 0050 2 張 52.4」。它會先算好手續費和稅寫成草稿，你簽名後才入帳。</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button onClick={() => ask.submit("買 0050 2 張 52.4")}>試試「買 0050 2 張 52.4」</Button>
        <Button variant="outline" onClick={() => ask.action("form")}>
          改用表單記一筆
        </Button>
      </div>
    </div>
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
  const maxWeight = Math.max(...rows.map((h) => h.weight), 0.0001)
  const header = (c: HoldingColumn) => {
    const key = SORTABLE[c]
    const active = key && sort.key === key
    return (
      <th key={c} scope="col" className={cn("h-10 border-b border-rule text-right text-sm font-normal text-ink-2", WIDTH[c])} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
        {key ? (
          <button
            type="button"
            onClick={() => onSort({ key, dir: active && sort.dir === "desc" ? "asc" : "desc" })}
            className={cn("inline-flex h-8 items-center gap-1 rounded-sm px-1 hover:text-ink", active && "text-ink")}
          >
            {COLUMN_LABEL[c]}
            {active && <span aria-hidden className="text-[0.7em]">{sort.dir === "desc" ? "▼" : "▲"}</span>}
          </button>
        ) : (
          COLUMN_LABEL[c]
        )}
      </th>
    )
  }
  const go = (symbol: string) => void navigate({ to: "/stock/$symbol", params: { symbol } })
  return (
    <table className="w-full border-collapse max-md:hidden" aria-label="持倉">
      <thead>
        <tr>
          <th scope="col" className="h-10 border-b border-rule text-left text-sm font-normal text-ink-2">
            名稱
          </th>
          {columns.map(header)}
        </tr>
      </thead>
      <tbody>
        {rows.map((h) => (
          <tr key={h.symbol} className="ruled-row cursor-pointer" onClick={() => go(h.symbol)}>
            <th scope="row" className="h-[60px] py-1.5 pr-3 text-left font-normal">
              <Link to="/stock/$symbol" params={{ symbol: h.symbol }} className="group block rounded-sm" onClick={(e) => e.stopPropagation()}>
                <span className="flex items-center gap-1.5 text-lg leading-snug font-medium group-hover:underline">
                  {h.name}
                  {pinned.includes(h.symbol) && <PinIcon aria-label="已釘選" className="size-3.5 fill-ink-2 text-ink-2" />}
                </span>
                <span className="num block text-sm text-ink-2">
                  {h.code} ・ <QtyText h={h} />
                </span>
              </Link>
            </th>
            {columns.map((c) => (
              <td key={c} className="num text-right text-lg whitespace-nowrap">
                <Cell c={c} h={h} maxWeight={maxWeight} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
      <WatchBody items={watch.data} columns={columns.length} loading={watch.isLoading} />
    </table>
  )
}

function QtyText({ h }: { h: Holding }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  return privacy ? <Masked /> : <>{formatQuantity(h.quantity, unit, h.market)}</>
}

function Cell({ c, h, maxWeight }: { c: HoldingColumn; h: Holding; maxWeight: number }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number, signed = false) => (privacy ? <Masked /> : formatMoney(n, { signed, bare: true }))
  switch (c) {
    case "price":
      return (
        <>
          {h.currency === "USD" && <span className="mr-0.5 text-sm text-ink-2">US$</span>}
          {formatQuote(h.price, h.market, h.type)}
        </>
      )
    case "day_pct":
      return <Pct value={h.day_change_pct} />
    case "day_change":
      return <span className={toneClass(direction(h.day_change))}>{money(h.day_change, true)}</span>
    case "value":
      return (
        <span className="flex flex-col items-end">
          <span className="leading-tight">{money(h.market_value)}</span>
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
      return <span className={toneClass(direction(h.unrealized_pnl))}>{money(h.unrealized_pnl, true)}</span>
    case "unrealized_pct":
      return <Pct value={h.unrealized_pnl_pct} />
  }
}

function WatchBody({ items, columns, loading }: { items?: WatchItem[]; columns: number; loading: boolean }) {
  const navigate = useNavigate()
  const visible = useLedgerPrefs((s) => s.columns)
  if (loading) return null
  return (
    <tbody>
      <tr>
        <th scope="colgroup" colSpan={columns + 1} className="h-[72px] border-b border-rule pt-7 text-left align-bottom">
          <span className="flex items-baseline gap-2 pb-2 text-base font-bold">
            觀察<span className="num text-sm font-normal text-ink-2">{items?.length ?? 0} 檔</span>
          </span>
        </th>
      </tr>
      {(items ?? []).length === 0 ? (
        <tr>
          <td colSpan={columns + 1} className="border-b border-rule py-4 text-md text-ink-2">
            還沒有觀察的股票。在個股頁按「加入觀察」，這裡會列出今天的走勢。
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
                  <Link to="/stock/$symbol" params={{ symbol: w.symbol }} className="group block rounded-sm" onClick={(e) => e.stopPropagation()}>
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
            </tr>
          )
        })
      )}
    </tbody>
  )
}

/** 手機：兩行列 */
function HoldingsList({ rows, pinned }: { rows: Holding[]; pinned: string[] }) {
  const watch = useWatchlist()
  return (
    <div className="md:hidden">
      <div className="flex h-11 items-end justify-between border-b border-rule pb-2 text-sm text-ink-2">
        <span>持有 {rows.length} 檔</span>
        <span>現價・今日漲跌</span>
      </div>
      <ul aria-label="持倉">
        {rows.map((h) => (
          <li key={h.symbol}>
            <Link to="/stock/$symbol" params={{ symbol: h.symbol }} className="ruled-row grid h-[72px] grid-cols-[1fr_auto] content-center gap-y-0.5">
              <span className="flex items-center gap-1.5 truncate text-lg leading-6 font-medium">
                {h.name}
                {pinned.includes(h.symbol) && <PinIcon aria-label="已釘選" className="size-3.5 shrink-0 fill-ink-2 text-ink-2" />}
              </span>
              <span className="num text-right text-lg leading-6">
                {h.currency === "USD" && "US$"}
                {formatQuote(h.price, h.market, h.type)}
              </span>
              <span className="num text-sm leading-5 text-ink-2">
                {h.code} ・ <QtyText h={h} />
              </span>
              <span className="text-right text-base leading-5">
                <Pct value={h.day_change_pct} />
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <h2 className="mt-9 flex h-11 items-end gap-2 border-b border-rule pb-2 text-lg font-bold">
        觀察 <span className="num text-sm font-normal text-ink-2">{watch.data?.length ?? 0} 檔</span>
        {watch.data?.some((w) => w.quote?.is_demo ?? w.is_demo) && <DemoTag className="mb-0.5 ml-auto" />}
      </h2>
      {(watch.data ?? []).length === 0 && !watch.isLoading ? (
        <p className="py-4 text-md text-ink-2">還沒有觀察的股票。在個股頁按「加入觀察」，這裡會列出今天的走勢。</p>
      ) : (
        <ul aria-label="觀察">
          {(watch.data ?? []).map((w) => (
            <WatchRowMobile key={w.symbol} w={w} />
          ))}
        </ul>
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
