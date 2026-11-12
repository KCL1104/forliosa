import { useInfiniteQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { FilterIcon, PlusIcon, Trash2Icon, XIcon } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { useAccounts, useDeleteTransaction } from "@/api/queries"
import type { Account, Transaction, TransactionQuery, TransactionType } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { useUi } from "@/app/ui-store"
import { Masked, SourceTag } from "@/components/finance"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState } from "@/components/states"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Drawer, DrawerContent, DrawerFooter, DrawerHeader, DrawerTitle } from "@/components/ui/drawer"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsDesktop } from "@/hooks/use-media-query"
import { formatDateShort, formatMoney, formatPrice, formatQuantity, MASK } from "@/lib/format"
import { isAutoSource, SOURCE_TAG, TYPE_LABEL } from "@/lib/labels"
import { codeOf, marketOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { GroupedVirtuoso } from "react-virtuoso"
import { usePrefs } from "@/stores/prefs"
import { useReadOnly } from "@/api/view-as"

type Period = "month" | "year" | "all"
const PERIODS: { value: Period; label: string }[] = [
  { value: "month", label: "近 1 個月" },
  { value: "year", label: "今年" },
  { value: "all", label: "全部" },
]
const TYPE_FILTERS: TransactionType[] = ["buy", "sell", "cash_dividend", "stock_dividend", "split", "deposit", "withdrawal", "interest", "fee"]

interface Filters {
  account?: string
  type?: TransactionType
  period: Period
}

function periodRange(p: Period, today: string): Pick<TransactionQuery, "from" | "to"> {
  if (p === "all") return {}
  if (p === "year") return { from: `${today.slice(0, 4)}-01-01` }
  const d = new Date(`${today}T00:00:00Z`)
  d.setUTCMonth(d.getUTCMonth() - 1)
  return { from: d.toISOString().slice(0, 10) }
}

const GRID = "lg:grid-cols-[88px_76px_minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.9fr)_40px]"

/** 交易：由新到舊、月份分組、虛擬化無限載入；點一筆可以編輯 */
export function TransactionsView({ symbol }: { symbol?: string }) {
  const readOnly = useReadOnly()
  const accounts = useAccounts()
  const ask = useAskAi()
  const isDesktop = useIsDesktop()
  const navigate = useNavigate()
  const [filters, setFilters] = useState<Filters>({ period: "all" })
  const [sheetOpen, setSheetOpen] = useState(false)
  const query: TransactionQuery = { account_id: filters.account, type: filters.type, symbol, ...periodRange(filters.period, appToday()), limit: 60 }

  const list = useInfiniteQuery({
    queryKey: ["transactions", "list", query],
    queryFn: ({ pageParam }) => api.listTransactions({ ...query, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data])
  const { groups, groupCounts } = useMemo(() => {
    const groups: string[] = []
    const groupCounts: number[] = []
    for (const t of items) {
      const month = t.trade_date.slice(0, 7)
      if (groups.at(-1) !== month) {
        groups.push(month)
        groupCounts.push(0)
      }
      groupCounts[groupCounts.length - 1]! += 1
    }
    return { groups, groupCounts }
  }, [items])
  const activeCount = (filters.account ? 1 : 0) + (filters.type ? 1 : 0) + (filters.period !== "all" ? 1 : 0)
  const accountMap = new Map((accounts.data ?? []).map((a) => [a.id, a]))
  const filterControls = <FilterControls filters={filters} setFilters={setFilters} accounts={accounts.data ?? []} />

  return (
    <div className="flex flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        {isDesktop ? filterControls : (
          <Button variant="outline" size="sm" onClick={() => setSheetOpen(true)}>
            <FilterIcon />
            篩選{activeCount > 0 && `（${activeCount}）`}
          </Button>
        )}
        {symbol && (
          <button
            type="button"
            onClick={() => void navigate({ to: "/", search: { view: "transactions" }, replace: true })}
            className="press inline-flex h-8 items-center gap-1.5 rounded-sm border border-ink px-2.5 text-sm pointer-coarse:h-10"
            aria-label={`取消只看 ${codeOf(symbol)}`}
          >
            只看 {codeOf(symbol)}
            <XIcon aria-hidden className="size-3.5" />
          </button>
        )}
        {!readOnly && (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => ask.action("trade")}>
            <PlusIcon />
            記一筆
          </Button>
        )}
      </div>
      {!isDesktop && (
        <Drawer open={sheetOpen} onOpenChange={setSheetOpen}>
          <DrawerContent>
            <DrawerHeader className="text-left">
              <DrawerTitle className="text-lg font-bold">篩選交易</DrawerTitle>
            </DrawerHeader>
            <div className="flex flex-col gap-4 px-4">{filterControls}</div>
            <DrawerFooter className="safe-bottom flex-row">
              <Button variant="outline" className="flex-1" onClick={() => setFilters({ period: "all" })}>
                清除
              </Button>
              <Button className="flex-1" onClick={() => setSheetOpen(false)}>
                套用
              </Button>
            </DrawerFooter>
          </DrawerContent>
        </Drawer>
      )}

      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isLoading ? (
        <ListSkeleton />
      ) : items.length === 0 ? (
        activeCount > 0 || symbol ? (
          <EmptyState
            title="沒有符合條件的交易"
            description="換個帳戶、類型或期間看看。"
            action={
              <Button variant="outline" size="sm" onClick={() => setFilters({ period: "all" })}>
                清除篩選
              </Button>
            }
          />
        ) : (
          <EmptyState
            title="還沒有交易紀錄"
            description="跟 AI 說一句「買 0050 2 張 52.4」就能記下第一筆；之後匯入對帳單（M3）也會出現在這裡。"
            action={<Button onClick={() => ask.action("trade")}>記第一筆交易</Button>}
          />
        )
      ) : (
        <div>
          <div className={cn("hidden h-10 items-end gap-3 border-b border-rule pb-2 text-sm text-ink-2 lg:grid", GRID)}>
            <span>日期</span>
            <span>類型</span>
            <span>商品</span>
            <span className="text-right">數量 × 價格</span>
            <span className="text-right">金額</span>
            <span className="text-right">稅費</span>
            <span>帳戶</span>
            <span className="sr-only">動作</span>
          </div>
          <GroupedVirtuoso
            useWindowScroll
            groupCounts={groupCounts}
            // 以交易 id 當 key：刪除一筆後，列的狀態（例如開著的確認框）不會被下一筆沿用
            computeItemKey={(index) => items[index]?.id ?? index}
            increaseViewportBy={400}
            endReached={() => list.hasNextPage && !list.isFetchingNextPage && void list.fetchNextPage()}
            groupContent={(gi) => (
              <div className="flex h-11 items-end border-b border-rule bg-paper pb-1.5 text-sm font-bold text-ink-2">
                {groups[gi]!.replace("-", " 年 ").replace(/ 0?(\d+)$/, " $1")} 月
              </div>
            )}
            itemContent={(index) => {
              const t = items[index]!
              return <TxnRow txn={t} account={accountMap.get(t.account_id)} />
            }}
            components={{
              Footer: () =>
                list.isFetchingNextPage ? (
                  <div className="py-3 text-sm text-ink-2">載入更多…</div>
                ) : !list.hasNextPage ? (
                  <div className="py-3 text-sm text-ink-2">共 {items.length} 筆，已經是最早的紀錄。</div>
                ) : null,
            }}
          />
        </div>
      )}
    </div>
  )
}

function FilterControls({ filters, setFilters, accounts }: { filters: Filters; setFilters: (f: Filters) => void; accounts: Account[] }) {
  return (
    <>
      <Select
        value={filters.account ?? "all"}
        onValueChange={(v) => setFilters({ ...filters, account: v === "all" ? undefined : (v as string) })}
        items={[{ value: "all", label: "全部帳戶" }, ...accounts.map((a) => ({ value: a.id, label: a.name }))]}
      >
        <SelectTrigger size="sm" className="min-w-36 max-lg:w-full" aria-label="帳戶">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部帳戶</SelectItem>
          {accounts.map((a) => (
            <SelectItem key={a.id} value={a.id}>
              {a.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={filters.type ?? "all"}
        onValueChange={(v) => setFilters({ ...filters, type: v === "all" ? undefined : (v as TransactionType) })}
        items={[{ value: "all", label: "全部類型" }, ...TYPE_FILTERS.map((t) => ({ value: t, label: TYPE_LABEL[t] }))]}
      >
        <SelectTrigger size="sm" className="min-w-32 max-lg:w-full" aria-label="交易類型">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部類型</SelectItem>
          {TYPE_FILTERS.map((t) => (
            <SelectItem key={t} value={t}>
              {TYPE_LABEL[t]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <RangeChips label="期間" value={filters.period} options={PERIODS} onChange={(p) => setFilters({ ...filters, period: p })} />
    </>
  )
}

/** 現金流方向：買進、提出、費用為流出 */
function cashSign(t: Transaction): number {
  return ["buy", "withdrawal", "fee", "tax"].includes(t.type) ? -1 : ["split", "stock_dividend", "capital_reduction"].includes(t.type) ? 0 : 1
}

function TxnRow({ txn: t, account }: { txn: Transaction; account?: Account }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const remove = useDeleteTransaction()
  const openTradeForm = useUi((s) => s.openTradeForm)
  const [confirm, setConfirm] = useState(false)
  // 查看別人的資產（唯讀）：列不能點開編輯，也沒有刪除
  const readOnly = useReadOnly()
  const market = t.symbol ? marketOf(t.symbol) : t.currency === "USD" ? "US" : "TWSE"
  const name = t.symbol ? codeOf(t.symbol) : "現金"
  const sign = cashSign(t)
  const net = sign === 0 ? null : sign * t.amount
  const costs = t.fee + t.tax + t.health_insurance
  const qtyText =
    t.type === "split" ? `1 股 → ${t.quantity} 股` : t.quantity !== null ? `${formatQuantity(t.quantity, unit, market)}${t.price !== null ? ` × ${formatPrice(t.price, market)}` : ""}` : ""
  const auto = t.source === "auto"
  const tag = SOURCE_TAG[t.source]

  return (
    <>
      <div
        role={readOnly ? undefined : "button"}
        tabIndex={readOnly ? undefined : 0}
        aria-label={readOnly ? undefined : `編輯 ${formatDateShort(t.trade_date)} ${TYPE_LABEL[t.type]} ${t.symbol ? name : ""}${tag ? `（${tag.label}）` : ""}`}
        onClick={() => !readOnly && openTradeForm({ edit: t })}
        onKeyDown={(e) => {
          if (readOnly || e.target !== e.currentTarget) return
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            openTradeForm({ edit: t })
          }
        }}
        className={cn("ruled-row group grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 py-2.5 text-base focus-visible:outline-offset-[-2px]", !readOnly && "cursor-pointer", GRID)}
      >
        <span className="num hidden text-ink-2 lg:block">{formatDateShort(t.trade_date)}</span>
        <span className={cn("hidden lg:block", t.type === "buy" || t.type === "sell" ? "font-medium" : "text-ink-2")}>{TYPE_LABEL[t.type]}</span>
        <span className="min-w-0">
          <span className="flex items-center gap-2">
            <span className={cn("lg:hidden", t.type === "buy" || t.type === "sell" ? "font-medium" : "text-ink-2")}>{TYPE_LABEL[t.type]}</span>
            {t.symbol ? (
              <Link to="/stock/$symbol" params={{ symbol: t.symbol }} onClick={(e) => e.stopPropagation()} className="num truncate font-medium hover:underline">
                {name}
              </Link>
            ) : (
              <span className="truncate text-ink-2">{t.note || "現金"}</span>
            )}
            <SourceTag source={t.source} />
          </span>
          <span className="num block truncate text-sm text-ink-2 lg:hidden">
            {formatDateShort(t.trade_date)}・{privacy ? MASK : qtyText}
          </span>
          {/* 自動入帳的備註寫著持有股數：隱私模式不顯示 */}
          {t.note && t.symbol && !(privacy && isAutoSource(t.source)) && <span className="hidden truncate text-sm text-ink-2 lg:block">{t.note}</span>}
        </span>
        <span className="num hidden truncate text-right text-ink-2 lg:block">{privacy ? <Masked /> : qtyText}</span>
        <span className="num text-right font-medium">
          {net === null ? <span className="text-ink-2">—</span> : privacy ? <Masked /> : formatMoney(net, { currency: t.currency, signed: true })}
          <span className="block text-sm font-normal text-ink-2 lg:hidden">{costs > 0 && !privacy ? `稅費 ${formatMoney(costs, { currency: t.currency })}` : account?.name}</span>
        </span>
        <span className="num hidden text-right text-ink-2 lg:block">{costs > 0 ? privacy ? <Masked /> : formatMoney(costs, { currency: t.currency }) : "—"}</span>
        <span className="hidden truncate text-sm text-ink-2 lg:block" title={account?.name}>
          {account?.name}
        </span>
        <span className="hidden justify-end lg:flex">
          {!readOnly && <Button
            variant="ghost"
            size="icon-sm"
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
            aria-label={`刪除 ${formatDateShort(t.trade_date)} 的${TYPE_LABEL[t.type]}`}
            onClick={(e) => {
              e.stopPropagation()
              setConfirm(true)
            }}
          >
            <Trash2Icon />
          </Button>}
        </span>
      </div>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除這筆交易？</AlertDialogTitle>
            <AlertDialogDescription>
              {formatDateShort(t.trade_date)} {TYPE_LABEL[t.type]} {t.symbol ? name : ""}。刪除後持股、損益與績效會重新計算
              {auto ? "，這筆股利之後也不會再自動入帳。" : "。"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setConfirm(false)
                remove.mutate(t.id, {
                  onSuccess: () => toast.success("已刪除這筆交易"),
                  onError: (err) => toast.error("刪除失敗", { description: err.message }),
                })
              }}
            >
              刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function ListSkeleton() {
  return (
    <div aria-busy="true" aria-label="交易紀錄載入中">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="flex h-14 items-center gap-4 border-b border-rule">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-10" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
    </div>
  )
}
