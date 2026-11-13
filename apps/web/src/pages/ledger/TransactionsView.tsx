import { useInfiniteQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { Trash2Icon, XIcon } from "lucide-react"
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
import { DateCell } from "@/components/date-cell"
import { useReadOnly } from "@/api/view-as"
import { useSymbolNames } from "./use-symbol-names"

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

/*
 * 欄位跟著容器的寬度排（@container），不是視窗：桌面開著 AI 面板時，內容只有 620–930px。
 * 第一欄一定是聯絡簿的日期格（日期＋星期，右邊一條格線）。
 * - 窄（< 672px，手機）：日期格｜類型 名稱／代號・數量 × 價格／來源標示＋備註｜金額／稅費（沒有稅費時是帳戶）
 * - 中（≥ 672px）：日期｜類型｜商品｜數量｜價格｜金額｜刪除；稅費（或帳戶）在金額下面一行
 * - 寬（≥ 896px）：日期｜類型｜商品｜帳戶｜數量｜價格｜金額｜稅費｜刪除
 * 商品是兩行：名稱；代號＋來源標示＋備註。第二行可以延伸到數量、價格欄的下面，備註不截斷、放不下就換行。
 */
const GRID =
  "grid grid-cols-[3.25rem_minmax(0,1fr)_auto] gap-x-3 @2xl:grid-cols-[96px_64px_minmax(0,1fr)_100px_72px_124px_32px] @4xl:grid-cols-[96px_64px_minmax(0,1fr)_100px_100px_72px_124px_76px_32px]"

/** 空狀態是這個分段的最後一塊：下面那條線由頁尾（資料來源）的上緣格線提供，不重複畫一條、中間夾一段空白 */
const LAST = "border-b-0 pb-0"

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
  const names = useSymbolNames()
  const filterControls = <FilterControls filters={filters} setFilters={setFilters} accounts={accounts.data ?? []} />

  return (
    <div className="@container flex flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        {isDesktop ? filterControls : (
          <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={() => setSheetOpen(true)}>
            篩選{activeCount > 0 && `（${activeCount}）`}
          </Button>
        )}
        {symbol && (
          <button
            type="button"
            onClick={() => void navigate({ to: "/", search: { view: "transactions" }, replace: true })}
            // 篩選中＝選取語法 (b)；再按一次（或按 ×）取消
            aria-pressed="true"
            title="取消篩選"
            className="press sel-chip inline-flex h-8 items-center gap-1.5 rounded-sm px-2.5 text-sm text-ink-2 pointer-coarse:h-11"
          >
            只看 {codeOf(symbol)}
            <XIcon aria-hidden className="size-3.5" />
          </button>
        )}
      </div>
      {!isDesktop && (
        <Drawer open={sheetOpen} onOpenChange={setSheetOpen}>
          <DrawerContent>
            <DrawerHeader>
              <DrawerTitle>篩選交易</DrawerTitle>
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
            className={LAST}
            title="沒有符合條件的交易"
            description="換個帳戶、類型或期間看看。"
            action={
              <Button variant="outline" size="sm" className="pointer-coarse:h-11" onClick={() => setFilters({ period: "all" })}>
                清除篩選
              </Button>
            }
          />
        ) : readOnly ? (
          // 查看模式：唯讀，沒有記帳動作也沒有 AI
          <EmptyState className={LAST} title="沒有交易紀錄" />
        ) : (
          <EmptyState
            className={LAST}
            title="還沒有交易紀錄"
            description="自己填第一筆，或跟 AI 說一句「買 0050 2 張 52.4」。"
            action={
              <Button variant="outline" onClick={() => ask.action("form")}>
                記第一筆交易
              </Button>
            }
          />
        )
      ) : (
        <div>
          <div className={cn("form-head h-10 items-end pb-2 @max-2xl:hidden", GRID)}>
            <span>日期</span>
            <span>類型</span>
            <span>商品</span>
            <span className="@max-4xl:hidden">帳戶</span>
            <span className="text-right">數量</span>
            <span className="text-right">價格</span>
            <span className="text-right">金額</span>
            <span className="text-right @max-4xl:hidden">稅費</span>
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
              return <TxnRow txn={t} account={accountMap.get(t.account_id)} name={t.symbol ? names.get(t.symbol) : undefined} />
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
        <SelectTrigger size="sm" className="min-w-36 max-lg:w-full pointer-coarse:data-[size=sm]:h-11" aria-label="帳戶">
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
        <SelectTrigger size="sm" className="min-w-32 max-lg:w-full pointer-coarse:data-[size=sm]:h-11" aria-label="交易類型">
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

function TxnRow({ txn: t, account, name }: { txn: Transaction; account?: Account; name?: string }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const remove = useDeleteTransaction()
  const openTradeForm = useUi((s) => s.openTradeForm)
  const [confirm, setConfirm] = useState(false)
  // 查看別人的資產（唯讀）：列不能點開編輯，也沒有刪除
  const readOnly = useReadOnly()
  const market = t.symbol ? marketOf(t.symbol) : t.currency === "USD" ? "US" : "TWSE"
  const code = t.symbol ? codeOf(t.symbol) : null
  // 名稱＋代號：查得到名稱時「聯發科 2454」，查不到只有代號
  const label = code ? (name ? `${name} ${code}` : code) : "現金"
  const sign = cashSign(t)
  const net = sign === 0 ? null : sign * t.amount
  const costs = t.fee + t.tax + t.health_insurance
  const qty = t.type === "split" ? `1 股 → ${t.quantity} 股` : t.quantity !== null ? formatQuantity(t.quantity, unit, market) : ""
  const price = t.type !== "split" && t.quantity !== null && t.price !== null ? formatPrice(t.price, market) : ""
  const tag = SOURCE_TAG[t.source]
  const auto = t.source === "auto"
  // 自動入帳的備註寫著持有股數：隱私模式不顯示。現金列（沒有代號）的備註就是第一行的名稱
  const note = t.symbol && t.note && !(privacy && isAutoSource(t.source)) ? t.note : ""
  const strong = t.type === "buy" || t.type === "sell"

  return (
    <>
      <div
        role={readOnly ? undefined : "button"}
        tabIndex={readOnly ? undefined : 0}
        aria-label={readOnly ? undefined : `編輯 ${formatDateShort(t.trade_date)} ${TYPE_LABEL[t.type]} ${t.symbol ? label : ""}${tag ? `（${tag.label}）` : ""}`}
        onClick={() => !readOnly && openTradeForm({ edit: t })}
        onKeyDown={(e) => {
          if (readOnly || e.target !== e.currentTarget) return
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            openTradeForm({ edit: t })
          }
        }}
        className={cn("ruled-row group min-h-14 items-baseline py-2.5 text-base focus-visible:outline-offset-[-2px]", !readOnly && "cursor-pointer", GRID)}
      >
        {/* 日期格跟著容器：窄版兩行（日期／星期），中、寬版一行 */}
        <DateCell date={t.trade_date} stacked className="row-span-3 justify-start pt-[calc(0.625rem+2px)] @2xl:hidden" />
        <DateCell date={t.trade_date} inline className="row-span-3 justify-start leading-6 @max-2xl:hidden" />
        <span className={cn("@max-2xl:hidden", strong ? "font-medium" : "text-ink-2")}>{TYPE_LABEL[t.type]}</span>
        {/* 第一行：名稱（連到個股頁）。窄版把類型放在名稱前面 */}
        <span className="flex min-w-0 items-baseline gap-2">
          <span className={cn("shrink-0 @2xl:hidden", strong ? "font-medium" : "text-ink-2")}>{TYPE_LABEL[t.type]}</span>
          {t.symbol ? (
            // 名稱連結在整列的「編輯」按鈕裡：可點範圍上下各加 10px（44px），不改版面；截斷放在裡面那層，才不會把加大的範圍裁掉
            <Link
              to="/stock/$symbol"
              params={{ symbol: t.symbol }}
              onClick={(e) => e.stopPropagation()}
              title={name ?? undefined}
              className="relative min-w-0 font-medium before:absolute before:inset-x-0 before:-inset-y-2.5 before:content-[''] hover:underline"
            >
              <span className="block truncate">{name ?? code}</span>
            </Link>
          ) : (
            <span className="min-w-0 truncate text-ink-2">{t.note || "現金"}</span>
          )}
        </span>
        <span className="truncate text-sm text-ink-2 @max-4xl:hidden" title={account?.name}>
          {account?.name}
        </span>
        <span className="num text-right text-ink-2 @max-2xl:hidden">{qty ? privacy ? <Masked /> : qty : ""}</span>
        <span className="num text-right text-ink-2 @max-2xl:hidden">{price ? privacy ? <Masked /> : price : ""}</span>
        <span className="num text-right font-medium whitespace-nowrap">
          {net === null ? <span className="font-normal text-ink-2">—</span> : privacy ? <Masked /> : formatMoney(net, { currency: t.currency, signed: true })}
        </span>
        <span className="num text-right text-ink-2 @max-4xl:hidden">{costs > 0 ? privacy ? <Masked /> : formatMoney(costs, { currency: t.currency }) : "—"}</span>
        <span className="row-span-3 flex justify-end self-center @max-2xl:hidden">
          {!readOnly && (
            <Button
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
            </Button>
          )}
        </span>
        {/*
          第二行：代號（窄版接著「數量 × 價格」）＋來源標示＋備註，都是行內的字，放不下就照文字換行（不截斷）。
          窄版：這個包裝是 display: contents，代號那一段在第二行、標示與備註在第三行（整列寬）；
          中、寬版：一段，從商品欄延伸到價格欄的下面。
        */}
        {(code || qty || tag || note) && (
          <span className="contents text-sm text-ink-2 @2xl:col-start-3 @2xl:col-end-6 @2xl:row-start-2 @2xl:block @4xl:col-end-7">
            {(code || qty) && (
              <span className="num col-start-2 row-start-2 min-w-0 @2xl:mr-2">
                {code && <span>{code}</span>}
                {qty && (
                  <span className="@2xl:hidden">
                    {code && " ・ "}
                    {/* 很窄的手機上放不下時，「數量 × 價格」整段換到下一行，不從中間斷開 */}
                    <span className="whitespace-nowrap">{privacy ? MASK : price ? `${qty} × ${price}` : qty}</span>
                  </span>
                )}
              </span>
            )}
            {(tag || note) && (
              <span className="col-start-2 col-end-4 row-start-3 min-w-0 [overflow-wrap:anywhere] @max-2xl:mt-0.5 @2xl:inline">
                <SourceTag source={t.source} className={note ? "mr-2" : undefined} />
                {note && <span>{note}</span>}
              </span>
            )}
          </span>
        )}
        {/* 金額下面一行（窄、中版）：稅費；沒有稅費時是帳戶 */}
        {(costs > 0 || account?.name) && (
          <span className="num col-start-3 row-start-2 text-right text-sm whitespace-nowrap text-ink-2 @2xl:col-start-6 @4xl:hidden">
            {costs > 0 && !privacy ? `稅費 ${formatMoney(costs, { currency: t.currency })}` : account?.name}
          </span>
        )}
      </div>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除這筆交易？</AlertDialogTitle>
            <AlertDialogDescription>
              {formatDateShort(t.trade_date)} {TYPE_LABEL[t.type]} {t.symbol ? label : ""}。刪除後持股、損益與績效會重新計算
              {auto ? "，這筆股利之後也不會再自動入帳。" : "。"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
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
