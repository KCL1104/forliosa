import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { ArrowDownIcon, ArrowUpIcon, ChevronRightIcon, PlusIcon } from "lucide-react"
import { useMemo, useState } from "react"
import { useAccounts, useHoldings } from "@/api/queries"
import type { Holding, Market } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { DemoChop } from "@/components/chop"
import { RangeChips } from "@/components/charts/chart-kit"
import { Money, Pct, Price, Quantity } from "@/components/finance"
import { PageHeader } from "@/components/section"
import { EmptyState, ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/api"
import { formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { HoldingsSearch } from "@/router"

type SortKey = "name" | "market_value" | "day_change_pct" | "unrealized_pnl" | "unrealized_pnl_pct" | "weight"
const MARKETS: { value: "ALL" | Market; label: string }[] = [
  { value: "ALL", label: "全部" },
  { value: "TWSE", label: "上市" },
  { value: "TPEX", label: "上櫃" },
  { value: "US", label: "美股" },
]
const MARKET_LABEL: Record<Market, string> = { TWSE: "上市", TPEX: "上櫃", US: "美股" }

export function HoldingsPage() {
  const search = useSearch({ from: "/holdings" }) as HoldingsSearch
  const navigate = useNavigate({ from: "/holdings" })
  const accounts = useAccounts()
  const holdings = useHoldings(search.account)
  const openTradeForm = useUi((s) => s.openTradeForm)
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "market_value", dir: "desc" })

  const market = search.market ?? "ALL"
  const rows = useMemo(() => {
    const list = (holdings.data ?? []).filter((h) => market === "ALL" || h.market === market)
    const dir = sort.dir === "asc" ? 1 : -1
    return [...list].sort((a, b) => (sort.key === "name" ? a.code.localeCompare(b.code) * dir : (a[sort.key] - b[sort.key]) * dir))
  }, [holdings.data, market, sort])

  const totals = useMemo(() => {
    const mv = rows.reduce((s, h) => s + h.market_value, 0)
    const cost = rows.reduce((s, h) => s + h.cost_basis, 0)
    const day = rows.reduce((s, h) => s + h.day_change, 0)
    return { mv, cost, day, pnl: mv - cost, pnlPct: cost ? (mv - cost) / cost : 0, dayPct: mv - day ? day / (mv - day) : 0 }
  }, [rows])

  const setFilter = (patch: Partial<HoldingsSearch>) => void navigate({ search: (s: HoldingsSearch) => ({ ...s, ...patch }), replace: true })
  const accountName = accounts.data?.find((a) => a.id === search.account)?.name

  return (
    <div>
      <PageHeader
        title="持股"
        meta={api.kind === "mock" && <DemoChop />}
        description="所有券商帳戶合併計算，均價含買進手續費（移動平均）。"
        actions={
          <Button onClick={() => openTradeForm()} variant="outline">
            <PlusIcon />
            記一筆
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-3">
        <Select
          value={search.account ?? "all"}
          onValueChange={(v) => setFilter({ account: v === "all" ? undefined : (v as string) })}
          items={[{ value: "all", label: "全部帳戶" }, ...(accounts.data ?? []).map((a) => ({ value: a.id, label: a.name }))]}
        >
          <SelectTrigger size="sm" className="min-w-36" aria-label="篩選帳戶">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部帳戶</SelectItem>
            {(accounts.data ?? []).map((a) => (
              <SelectItem key={a.id} value={a.id}>
                {a.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <RangeChips label="篩選市場" value={market} options={MARKETS} onChange={(v) => setFilter({ market: v === "ALL" ? undefined : v })} />
        {holdings.data && (
          <span className="text-sm text-muted-foreground md:ml-auto">
            {rows.length} 檔・市值 <Money value={totals.mv} compact />
          </span>
        )}
      </div>

      {holdings.isError ? (
        <ErrorState error={holdings.error} onRetry={() => void holdings.refetch()} />
      ) : !holdings.data ? (
        <HoldingsSkeleton />
      ) : holdings.data.length === 0 ? (
        <EmptyState
          title={search.account ? `「${accountName ?? "這個帳戶"}」還沒有持股` : "還沒有持股"}
          description="輸入目前持股（股數與均價）就能開始追蹤；之後再補交易紀錄也可以。"
          action={<Button onClick={() => openTradeForm()}>輸入第一檔持股</Button>}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title={`沒有${MARKET_LABEL[market as Market]}的持股`}
          description={search.account ? `「${accountName}」在這個市場沒有部位。` : undefined}
          action={
            <Button variant="outline" size="sm" onClick={() => setFilter({ market: undefined, account: undefined })}>
              清除篩選
            </Button>
          }
        />
      ) : (
        <>
          <HoldingsTable rows={rows} totals={totals} sort={sort} onSort={setSort} />
          <HoldingCards rows={rows} />
        </>
      )}
    </div>
  )
}

function SortHeader({ label, k, sort, onSort, align = "right", className }: { label: React.ReactNode; k: SortKey; sort: { key: SortKey; dir: "asc" | "desc" }; onSort: (s: { key: SortKey; dir: "asc" | "desc" }) => void; align?: "left" | "right"; className?: string }) {
  const active = sort.key === k
  return (
    <th scope="col" aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} className={cn("px-3 py-2 font-medium", align === "right" ? "text-right" : "text-left", className)}>
      <button
        type="button"
        onClick={() => onSort({ key: k, dir: active && sort.dir === "desc" ? "asc" : "desc" })}
        className={cn("inline-flex items-center gap-1 rounded-sm hover:text-foreground", active && "text-foreground", align === "right" && "flex-row-reverse")}
      >
        {label}
        {active ? (sort.dir === "asc" ? <ArrowUpIcon className="size-3.5" aria-hidden /> : <ArrowDownIcon className="size-3.5" aria-hidden />) : <span className="size-3.5" />}
      </button>
    </th>
  )
}

function HoldingsTable({
  rows,
  totals,
  sort,
  onSort,
}: {
  rows: Holding[]
  totals: { mv: number; day: number; pnl: number; pnlPct: number; dayPct: number }
  sort: { key: SortKey; dir: "asc" | "desc" }
  onSort: (s: { key: SortKey; dir: "asc" | "desc" }) => void
}) {
  const navigate = useNavigate()
  const go = (h: Holding) => void navigate({ to: "/stock/$symbol", params: { symbol: h.symbol } })
  return (
    <div className="hidden overflow-x-auto rounded-xl border bg-card md:block">
      <table className="w-full min-w-[960px] border-collapse text-md">
        <caption className="sr-only">持股明細，點選列可看個股</caption>
        <thead className="border-b text-sm text-muted-foreground">
          <tr>
            <SortHeader label="名稱" k="name" sort={sort} onSort={onSort} align="left" className="sticky left-0 z-10 bg-card pl-4" />
            <th scope="col" className="px-3 py-2 text-right font-medium">股數</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">均價</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">現價</th>
            <SortHeader label="今日" k="day_change_pct" sort={sort} onSort={onSort} />
            <SortHeader label="市值" k="market_value" sort={sort} onSort={onSort} />
            <SortHeader label="未實現損益" k="unrealized_pnl" sort={sort} onSort={onSort} />
            <SortHeader label="報酬率" k="unrealized_pnl_pct" sort={sort} onSort={onSort} />
            <SortHeader label="佔比" k="weight" sort={sort} onSort={onSort} />
            <th scope="col" className="px-3 py-2 pr-4 text-right font-medium">
              <Tooltip>
                <TooltipTrigger render={<span className="cursor-help underline decoration-dotted underline-offset-4">AI 訊號</span>} />
                <TooltipContent>持倉健檢上線（M4）後，這裡會顯示 AI 對每檔的提醒。</TooltipContent>
              </Tooltip>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => (
            <tr
              key={h.symbol}
              tabIndex={0}
              onClick={() => go(h)}
              onKeyDown={(e) => e.key === "Enter" && go(h)}
              className="group cursor-pointer border-b border-hairline last:border-0 hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-offset-[-2px]"
            >
              <th scope="row" className="sticky left-0 z-10 max-w-[240px] bg-card py-2.5 pr-3 pl-4 text-left font-normal group-hover:bg-[color-mix(in_oklch,var(--card),var(--muted)_60%)]">
                <Link to="/stock/$symbol" params={{ symbol: h.symbol }} className="block min-w-0" onClick={(e) => e.stopPropagation()} tabIndex={-1}>
                  <span className="block truncate font-medium" title={h.name}>{h.name}</span>
                  <span className="num block text-sm text-muted-foreground">
                    {h.code}・{MARKET_LABEL[h.market]}
                    {h.type === "etf" ? "・ETF" : ""}
                  </span>
                </Link>
              </th>
              <td className="px-3 text-right"><Quantity shares={h.quantity} market={h.market} /></td>
              <td className="px-3 text-right text-muted-foreground"><Price value={h.avg_cost} market={h.market} /></td>
              <td className="px-3 text-right"><Price value={h.price} market={h.market} /></td>
              <td className="px-3 text-right"><Pct value={h.day_change_pct} /></td>
              <td className="px-3 text-right font-medium"><Money value={h.market_value} /></td>
              <td className="px-3 text-right"><Money value={h.unrealized_pnl} signed tone /></td>
              <td className="px-3 text-right"><Pct value={h.unrealized_pnl_pct} /></td>
              <td className="px-3 text-right">
                <span className="num">{formatPercent(h.weight, { signed: false, decimals: 1 })}</span>
              </td>
              <td className="px-3 pr-4 text-right text-muted-foreground">—</td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t bg-muted/40 text-md">
          <tr>
            <th scope="row" className="sticky left-0 bg-[color-mix(in_oklch,var(--card),var(--muted)_40%)] py-2.5 pl-4 text-left font-medium">合計</th>
            <td colSpan={3} />
            <td className="px-3 text-right"><Pct value={totals.dayPct} /></td>
            <td className="px-3 text-right font-semibold"><Money value={totals.mv} /></td>
            <td className="px-3 text-right font-medium"><Money value={totals.pnl} signed tone /></td>
            <td className="px-3 text-right"><Pct value={totals.pnlPct} /></td>
            <td className="px-3 text-right num">100%</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

/** 手機：表格收合成卡片，只留關鍵欄位，點進個股頁看完整資料 */
function HoldingCards({ rows }: { rows: Holding[] }) {
  return (
    <ul className="flex flex-col divide-y divide-hairline rounded-xl border bg-card md:hidden">
      {rows.map((h) => (
        <li key={h.symbol}>
          <Link to="/stock/$symbol" params={{ symbol: h.symbol }} className="press flex items-center gap-3 px-4 py-3 active:bg-muted">
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="truncate font-medium" title={h.name}>{h.name}</span>
                <span className="num shrink-0 text-sm text-muted-foreground">{h.code}</span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-sm text-muted-foreground">
                <Quantity shares={h.quantity} market={h.market} />
                <span>・</span>
                <span>
                  現價 <Price value={h.price} market={h.market} className="text-foreground" />
                </span>
                <Pct value={h.day_change_pct} />
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end">
              <Money value={h.market_value} compact className="font-semibold" />
              <span className="flex items-baseline gap-1.5 text-sm">
                <Money value={h.unrealized_pnl} signed tone compact />
                <Pct value={h.unrealized_pnl_pct} glyph={false} decimals={1} />
              </span>
            </div>
            <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  )
}

function HoldingsSkeleton() {
  return (
    <div className="flex flex-col gap-0 overflow-hidden rounded-xl border bg-card" aria-busy="true" aria-label="持股載入中">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="flex items-center gap-4 border-b border-hairline px-4 py-3 last:border-0">
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-20" />
          </div>
          <Skeleton className="h-4 w-24" />
          <Skeleton className="hidden h-4 w-24 md:block" />
          <Skeleton className="hidden h-4 w-24 md:block" />
        </div>
      ))}
    </div>
  )
}
