import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowDownIcon, ArrowLeftRightIcon, ArrowUpIcon, ChevronDownIcon, EllipsisIcon, PinIcon } from "lucide-react"
import { Fragment, useMemo, useState, type ReactNode } from "react"
import { useHoldings, useIntraday, useWatchlist } from "@/api/queries"
import type { Holding, WatchItem } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { Masked, Pct } from "@/components/finance"
import { inText } from "@/lib/cjk"
import { DemoTag } from "@/components/section"
import { Sparkline } from "@/components/sparkline"
import { EmptyState, ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { direction, formatMoney, formatPercent, formatPrice, formatQuantity, toneClass } from "@/lib/format"
import { codeOf, formatQuote, marketOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { unpricedHoldings } from "@/lib/ledger-display"
import { ClosedRounds } from "./ClosedRounds"
import { RecurringMark } from "./RecurringMark"
import { useActivePlans } from "./use-active-plans"
import { COLUMN_HINT, useLedgerPrefs, type HoldingColumn } from "./ledger-prefs"
import { useColumnLabel } from "./use-column-label"
import { useReadOnly } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { useStartReduce } from "@/pages/transactions/use-start-reduce"
import { useCanImport } from "@/pages/transactions/import/access"
import { textAction } from "@/components/text-action"
import { useUsClosesServed } from "@/pages/stock/text"
import { ROW_MENU_BUTTON, SymbolRecords } from "./SymbolRecords"

type SortKey = "value" | "day_pct" | "day_change" | "pnl" | "unrealized" | "unrealized_pct" | "name"

/**
 * 持倉：桌面表格（預設 名稱・收盤價・均價（同一格兩行）・今日漲跌・今日損益・損益・市值；可自訂、可排序）；
 * 手機兩行列（左名稱、代號・股數；右收盤價、今日漲跌或報酬率——按表頭切換）。展開一檔：均價・持有・成本一行，再來是每一筆買賣
 */
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
        // 「損益」欄照金額排（同一個數字，但是自己的排序鍵：和「未實現損益」欄一起開著時只標一欄）
        case "pnl":
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

/**
 * 沒有價格的持股，照成本算。美股的收盤（Databento）只抓有人觀察或持有的代號，所以美股寫「還沒有收盤價」；其他（台股）照舊。
 * 不說「約 10 分鐘內補上」：這裡看不出是剛記進帳本、還是資料源不認得這個代號（一直補不上），做不到的時間不承諾。
 * 後端關掉美股收盤時（顯名清單沒有 Databento）美股也照舊寫「沒有報價」。
 */
function UnpricedNote({ rows }: { rows: Holding[] }) {
  const served = useUsClosesServed()
  const list = unpricedHoldings(rows)
  if (list.length === 0) return null
  const us = served ? list.filter((h) => h.market === "US") : []
  const other = list.filter((h) => !us.includes(h))
  const names = (hs: Holding[]) => inText(hs.map((h) => h.name).join("、"), "start")
  return (
    <>
      {other.length > 0 && <p className="mt-2.5 text-base text-ink">{names(other)}沒有報價，照成本算。</p>}
      {us.length > 0 && <p className="mt-2.5 text-base text-ink">{names(us)}還沒有收盤價，先照成本算。</p>}
    </>
  )
}

function EmptyLedger() {
  const ask = useAskAi()
  const readOnly = useReadOnly()
  const canImport = useCanImport()
  const openImport = useUi((s) => s.openImport)
  if (readOnly) return <EmptyState title="目前沒有持股" />
  // 空狀態兩條路：自己填，或跟 AI 說一句；開了匯入的帳號多一個文字連結（先選匯入庫存或對帳單；已經有持股的話匯入庫存最快）
  // 樣子是一張還沒寫的帳頁（2026-11-20）：印好的持倉表頭（和有持股時同一排欄位）→ 這段空狀態 → 兩條空白的格線往下淡出。
  // 只有空的表格線，沒有假資料；表頭與空白線只是畫面（aria-hidden），螢幕報讀器只讀空狀態
  return (
    <div>
      <div aria-hidden className="form-head grid h-10 grid-cols-[minmax(0,1fr)_repeat(5,auto)] items-end gap-x-10 pb-2 text-right max-md:hidden">
        <span className="text-left">名稱</span>
        <span>收盤價・均價</span>
        <span>今日漲跌</span>
        <span>今日損益</span>
        <span>損益</span>
        <span>市值・佔比</span>
      </div>
      <div aria-hidden className="form-head flex h-11 items-end justify-between pb-2 md:hidden">
        <span>持有 0 檔</span>
        <span>收盤價・今日漲跌</span>
      </div>
      <EmptyLedgerState canImport={canImport} onImport={() => openImport()} ask={ask} />
      <div aria-hidden className="[mask-image:linear-gradient(to_bottom,#000_10%,transparent)]">
        <div className="h-[72px] border-b border-rule lg:h-[60px]" />
        <div className="h-[72px] border-b border-rule lg:h-[60px]" />
      </div>
    </div>
  )
}

function EmptyLedgerState({ canImport, onImport, ask }: { canImport: boolean; onImport: () => void; ask: ReturnType<typeof useAskAi> }) {
  return (
    <EmptyState
      flush
      className="pt-5"
      title="帳本還是空的"
      description="自己填第一筆，或跟 AI 說一句。"
      action={
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
          <Button onClick={() => ask.action("form")}>記第一筆</Button>
          <Button variant="outline" onClick={() => ask.submit("買 0050 2 張 52.4")}>
            試試「買 0050 2 張 52.4」
          </Button>
          {canImport && (
            <button type="button" onClick={onImport} className={textAction}>
              匯入庫存或對帳單
            </button>
          )}
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
  pnl: "pnl",
  value: "value",
  unrealized: "unrealized",
  unrealized_pct: "unrealized_pct",
}
const WIDTH: Record<HoldingColumn, string> = {
  price: "w-[150px]",
  day_pct: "w-[140px]",
  day_change: "w-[150px]",
  pnl: "w-[150px]",
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
  const stackDay = stacksDay(columns)
  const sortButton = (key: SortKey, text: string, className?: string) => {
    const active = sort.key === key
    return (
      <button
        type="button"
        onClick={() => onSort({ key, dir: active && sort.dir === "desc" ? "asc" : "desc" })}
        className={cn(
          "inline-flex h-8 items-center justify-end gap-0.5 rounded-sm px-1 hover:text-ink pointer-coarse:h-11 pointer-coarse:min-w-11",
          active && "text-ink",
          className,
        )}
      >
        {text}
        {/* 排序方向用箭頭（▲▼ 是價格漲跌的符號，不拿來表示排序） */}
        {active && (sort.dir === "desc" ? <ArrowDownIcon aria-hidden className="size-3.5" /> : <ArrowUpIcon aria-hidden className="size-3.5" />)}
      </button>
    )
  }
  const stackAvg = stacksAvg(columns)
  const header = (c: HoldingColumn) => {
    const key = SORTABLE[c]
    const active = key && sort.key === key
    // 均價沒有自己一欄時寫在收盤價下面一行：表頭和「市值・佔比」同一個寫法
    const text = c === "price" && stackAvg ? `${label("price")}・${label("avg_cost")}` : label(c)
    return (
      <th
        key={c}
        scope="col"
        // 數字欄之間至少留 12px（pl-3）：欄寬被擠到只剩內容寬時，數字也不會連在一起
        className={cn("h-10 pl-3 text-right @max-[52rem]:w-px", WIDTH[c], stackDay && c === "day_pct" && "@max-[52rem]:hidden")}
        aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
        title={c === "price" && stackAvg ? COLUMN_HINT.avg_cost : COLUMN_HINT[c]}
      >
        {key ? sortButton(key, text, "-mr-1") : text}
        {/* 窄的時候今日漲跌併進這一格：表頭也多一個「漲跌」可以照漲跌幅排。主欄更窄（< 46rem）時只在正照它排的時候出現，省下名稱的寬度 */}
        {stackDay && c === "day_change" && (
          <span className={cn("@min-[52rem]:hidden", sort.key !== "day_pct" && "@max-[46rem]:hidden")}>
            <span aria-hidden>・</span>
            {sortButton("day_pct", "漲跌", "-mx-1")}
            {sort.key === "day_pct" && <span className="sr-only">{sort.dir === "desc" ? "（照漲跌由大到小排）" : "（照漲跌由小到大排）"}</span>}
          </span>
        )}
      </th>
    )
  }
  const go = (symbol: string) => void navigate({ to: "/stock/$symbol", params: { symbol } })
  const plans = useActivePlans()
  const [open, toggle] = useOpenRows()
  return (
    // 欄位跟著容器的寬度排（@container，不是視窗）：主欄窄於 52rem（開著 AI 面板、視窗不到約 1350px；平板）時見 stacksDay
    <div className="@container max-md:hidden">
      {/* data-holdings-focus：刪除一檔之後那一列不在了，焦點回到這張表裡第一個可以按的（DeleteHoldingDialog 的 afterDeleteFocus） */}
      <table className="w-full border-collapse" aria-label="持倉" data-holdings-focus>
        <thead className="form-head">
          <tr>
            <th scope="col" className="h-10 text-left">
              名稱
            </th>
            {columns.map(header)}
            {/* 最右邊：動作選單（查看別人的資產時沒有）＋展開每一筆買賣 */}
            {/* 兩顆 36px 的鈕（觸控 44px）放在格子裡面，不用負的右邊距伸出表格（滑過的底色不超過表格的右緣） */}
            <th scope="col" className={readOnly ? "w-10 pointer-coarse:w-11" : "w-[76px] pointer-coarse:w-[92px]"}>
              <span className="sr-only">動作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => (
            <Fragment key={h.symbol}>
              <tr className="ruled-row cursor-pointer" onClick={() => go(h.symbol)}>
                <th scope="row" className={NAME_CELL}>
                  {/* 名稱是連到個股頁的連結；定期定額標記是另一個連結（到設定），所以不包在一起 */}
                  <span className="flex min-w-0 items-center gap-1.5 text-lg leading-snug font-medium">
                    <Link to="/stock/$symbol" params={{ symbol: h.symbol }} title={h.name} className="min-w-0 rounded-sm hover:underline @max-[52rem]:truncate" onClick={(e) => e.stopPropagation()}>
                      {h.name}
                    </Link>
                    {pinned.includes(h.symbol) && <PinIcon aria-label="已釘選" className="size-3.5 shrink-0 fill-ink-2 text-ink-2" />}
                    {plans.get(h.symbol) && <RecurringMark plans={plans.get(h.symbol)!} className="-my-1" />}
                  </span>
                  <span className="num block text-sm text-ink-2 @max-[52rem]:truncate">
                    {h.code} ・ <QtyText h={h} />
                  </span>
                </th>
                {columns.map((c) => (
                  <td key={c} className={cn("num pl-3 text-right text-lg whitespace-nowrap", stackDay && c === "day_pct" && "@max-[52rem]:hidden")}>
                    <Cell c={c} h={h} maxWeight={maxWeight} stackDay={stackDay} stackAvg={stackAvg} />
                  </td>
                ))}
                <td className="text-right" onClick={(e) => e.stopPropagation()}>
                  <span className="flex items-center justify-end">
                    {!readOnly && <RowMenu h={h} />}
                    <ExpandButton h={h} open={open.has(h.symbol)} onToggle={() => toggle(h.symbol)} />
                  </span>
                </td>
              </tr>
              {open.has(h.symbol) && (
                <tr>
                  <td id={recordsId(h)} colSpan={columns.length + 2} className="border-b border-rule pb-3 pl-6">
                    <CostLine h={h} />
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
    </div>
  )
}

/**
 * 主欄窄的時候（< 52rem，1280px 開著 AI 面板是 758px）放不下六欄數字：「今日漲跌」併進「今日損益」那一格的第二行
 * （金額一行、百分比一行，和「損益」「市值・佔比」同一個樣子），兩欄都開著才併。寬的時候照常分兩欄。
 * 這時數字欄只佔自己需要的寬度，名稱欄拿剩下的、放不下就截斷（滑過看全名），列高維持 60px。
 */
const stacksDay = (columns: HoldingColumn[]) => columns.includes("day_pct") && columns.includes("day_change")

/**
 * 均價預設寫在收盤價下面一行（產品負責人 2026-11-17：「好像應該要幫我列出平均成本價？」）：13px 淡墨「均價 612.5」，
 * 和「損益」「市值・佔比」的第二行同一個樣子，列高不變。「自訂」裡打開「均價」那一欄時，收盤價下面不再重複。
 */
const stacksAvg = (columns: HoldingColumn[]) => !columns.includes("avg_cost")

/** 均價：和收盤價同一套價格寫法（算出來的數字不藏精度，最多 2 位）；美股前面寫 US$（價格是美元，帳本的金額才是新台幣） */
const avgCostText = (h: Holding) => `${h.market === "US" ? "US$" : ""}${formatPrice(h.avg_cost, h.market, h.type)}`

/** 名稱欄（列標題）：窄的時候 max-width 0，讓名稱欄不撐寬表格，拿數字欄剩下的寬度 */
const NAME_CELL = "h-[60px] py-1.5 pr-3 text-left font-normal @max-[52rem]:max-w-0"

/**
 * 這一檔的動作：加碼、減少持股、全部賣出（賣出不用開表單：只填股數，用最新的收盤價記）；一條格線隔開，最後是「刪除這檔」
 * （產品負責人 2026-11-17：記錯、匯入錯的整檔刪掉，不記成賣出；確認框見 `DeleteHoldingDialog`）。刪除不用紅色（紅色是「漲」），
 * 和群組成員的「移出群組」同一個寫法：放在最後、上面一條格線。
 */
function RowMenu({ h }: { h: Holding }) {
  const openTradeForm = useUi((s) => s.openTradeForm)
  const openDelete = useUi((s) => s.openDeleteHolding)
  const reduce = useStartReduce()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label={`${h.name}的動作`}
            className={ROW_MENU_BUTTON}
          />
        }
      >
        <EllipsisIcon aria-hidden className="size-5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuItem onClick={() => openTradeForm({ symbol: h.code })}>加碼</DropdownMenuItem>
        <DropdownMenuItem onClick={() => reduce(h.symbol)}>減少持股</DropdownMenuItem>
        <DropdownMenuItem onClick={() => reduce(h.symbol, true)}>全部賣出</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => openDelete(h.symbol)}>刪除這檔</DropdownMenuItem>
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

/**
 * 展開這一檔的每一筆買賣（日期、股數、價格、金額、買進後漲跌；每一筆可以修改、刪除）。
 * 滑過是 `bg-sel`：按鈕在格線列裡，列滑過時已經是 `--hov`（和「⋯」的 `ROW_MENU_BUTTON` 同一個理由）。
 */
function ExpandButton({ h, open, onToggle, className }: { h: Holding; open: boolean; onToggle: () => void; className?: string }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={recordsId(h)}
      aria-label={open ? `收起${h.name}的每一筆買賣` : `展開${h.name}的每一筆買賣`}
      onClick={onToggle}
      className={cn("press grid size-9 place-items-center rounded-sm text-ink-2 hover:bg-sel hover:text-ink pointer-coarse:size-11", className)}
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

function Cell({ c, h, maxWeight, stackDay = false, stackAvg = false }: { c: HoldingColumn; h: Holding; maxWeight: number; stackDay?: boolean; stackAvg?: boolean }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number, signed = false) => (privacy ? <Masked /> : formatMoney(n, { signed, bare: true }))
  // 沒有報價（商用模式的美股）：今日與未實現不是真的 0，顯示「—」
  const unpriced = h.price === null
  switch (c) {
    case "price": {
      const close = unpriced ? (
        <Dash />
      ) : (
        <>
          {h.currency === "USD" && <span className="mr-0.5 text-sm text-ink-2">US$</span>}
          {formatQuote(h.price, h.market, h.type)}
        </>
      )
      if (!stackAvg) return close
      // 收盤價一行、均價一行（沒有收盤價時均價照樣寫：成本是知道的）；隱私模式只遮均價，收盤價是公開的
      return (
        <span className="flex flex-col items-end">
          <span className="leading-tight">{close}</span>
          <span className="mt-0.5 text-sm leading-tight text-ink-2">
            均價 {privacy ? <Masked /> : avgCostText(h)}
          </span>
        </span>
      )
    }
    case "day_pct":
      return unpriced ? <Dash /> : <Pct value={h.day_change_pct} />
    case "day_change":
      if (unpriced) return <Dash />
      return stackDay ? (
        <span className="flex flex-col items-end">
          <span className={cn("leading-tight", toneClass(direction(h.day_change)))}>{money(h.day_change, true)}</span>
          <Pct value={h.day_change_pct} className="mt-0.5 text-sm leading-tight @min-[52rem]:hidden" />
        </span>
      ) : (
        <span className={toneClass(direction(h.day_change))}>{money(h.day_change, true)}</span>
      )
    case "pnl":
      // 金額一行、報酬率一行（和「市值・佔比」同一個樣子）；隱私模式只遮金額，百分比照常
      return unpriced ? (
        <Dash />
      ) : (
        <span className="flex flex-col items-end">
          <span className={cn("leading-tight", toneClass(direction(h.unrealized_pnl)))}>{money(h.unrealized_pnl, true)}</span>
          <Pct value={h.unrealized_pnl_pct} className="mt-0.5 text-sm leading-tight" />
        </span>
      )
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
      // 自己一欄時和收盤價那一欄同一個樣子：美股的 US$ 小一號、淡墨
      return privacy ? (
        <Masked />
      ) : (
        <>
          {h.market === "US" && <span className="mr-0.5 text-sm text-ink-2">US$</span>}
          {formatPrice(h.avg_cost, h.market, h.type)}
        </>
      )
    case "unrealized":
      return unpriced ? <Dash /> : <span className={toneClass(direction(h.unrealized_pnl))}>{money(h.unrealized_pnl, true)}</span>
    case "unrealized_pct":
      return unpriced ? <Dash /> : <Pct value={h.unrealized_pnl_pct} />
  }
}

/**
 * 展開一檔時最上面一行（桌面與手機都有）：均價・持有・成本（產品負責人 2026-11-17：「持倉也要顯示全部的均價（也一樣把手續費幫我算進去）」）。
 * 和個股頁「我的部位」同樣的名稱與寫法（13px 淡墨的名稱、15px 500 的數字）。
 * 後端的 `avg_cost`（原幣，美股是美元）＝目前持股的成本 ÷ 股數，`cost_basis`（新台幣，各筆買進當天的匯率）＝目前持股的成本：
 * 都含買進時填的手續費（沒填的存 0，不自動估）；賣出照成本法（預設移動平均、可換先進先出）扣掉賣掉那幾股的成本，
 * 現金股利不扣成本、配股與分割只加股數（均價跟著變低），減資退款扣成本。
 * 「含手續費」只在後端說這一批持股的成本裡真的有手續費時才寫（`fees_in_cost` > 0；2026-11-17 審查）：後端照帳本算
 * （每個帳戶各自、照成本法，當沖、減資的捨去、出清都和均價同一套），前端不自己重算——原本照日期走一遍交易，
 * 兩個帳戶、先進先出、當沖、減資時會在不含手續費的均價旁寫「含手續費」。沒填的以 0 計，不寫一個不存在的費用。
 * 和持倉同一份資料，展開的那一刻就定了，不等下面每一筆讀完（原本晚出現，整行往右跳、手機上換行）。
 * 隱私模式三個數字都遮（股數照帳本的規則也遮）。
 */
function CostLine({ h }: { h: Holding }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const withFee = (h.fees_in_cost ?? 0) > 0
  const hide = (s: string) => (privacy ? <Masked /> : s)
  // 窄的時候（手機、開著 AI 面板）下面每一筆是沒有表頭的格線列：這一行自己底下也畫一條，不和第一筆黏在一起（和 SymbolRecords 同一個 43rem 斷點）
  return (
    <div className="@container">
      <dl aria-label={`${h.name}的均價與成本`} className="num flex flex-wrap items-baseline gap-x-5 gap-y-1 py-2.5 text-base @max-[43rem]:border-b @max-[43rem]:border-rule">
        <CostItem
          label="均價"
          value={
            <>
              {hide(avgCostText(h))}
              {/* 真的空白（不是只有邊距）：複製出來、報讀器念起來是「692.61 含手續費」 */}
              {withFee && (
                <>
                  {" "}
                  <span className="ml-0.5 text-sm font-normal text-ink-2">含手續費</span>
                </>
              )}
            </>
          }
        />
        <CostItem label="持有" value={hide(formatQuantity(h.quantity, unit, h.market))} />
        <CostItem label="成本" value={hide(formatMoney(h.cost_basis))} />
      </dl>
    </div>
  )
}

function CostItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 whitespace-nowrap">
      <dt className="print-label text-sm">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  )
}

function WatchBody({ items, columns, loading }: { items?: WatchItem[]; columns: number; loading: boolean }) {
  const navigate = useNavigate()
  const visible = useLedgerPrefs((s) => s.columns)
  const stackDay = stacksDay(visible)
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
              <th scope="row" className={NAME_CELL}>
                <div className="flex items-center justify-between gap-4 pr-1">
                  <Link to="/stock/$symbol" params={{ symbol: w.symbol }} title={w.name} className="group block min-w-0 rounded-sm whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    <span className="block text-lg leading-snug font-medium group-hover:underline @max-[52rem]:truncate">{w.name}</span>
                    <span className="num block text-sm text-ink-2 @max-[52rem]:truncate">{codeOf(w.symbol)} ・ 觀察中</span>
                  </Link>
                  <Sparkline
                    className="@max-[46rem]:hidden"
                    values={w.sparkline.map((p) => p.price)}
                    baseline={w.sparkline_interval === "1d" ? null : (w.quote?.reference_price ?? w.quote?.prev_close ?? null)}
                    tone="ink"
                    label={`${w.name}今日走勢：${d === "up" ? "上漲" : d === "down" ? "下跌" : "平盤"}`}
                  />
                </div>
              </th>
              {visible.map((c) => (
                <td key={c} className={cn("num pl-3 text-right text-lg whitespace-nowrap", stackDay && c === "day_pct" && "@max-[52rem]:hidden")}>
                  {c === "price" ? (
                    <>
                      {/* 沒有收盤價時只寫「—」，不寫「US$—」 */}
                      {market === "US" && w.quote && <span className="mr-0.5 text-sm text-ink-2">US$</span>}
                      {formatQuote(w.quote?.price, market)}
                    </>
                  ) : c === "day_pct" ? (
                    <Pct value={w.quote?.change_pct ?? null} />
                  ) : c === "day_change" && stackDay ? (
                    // 窄的時候「今日漲跌」併進這一欄：觀察的股票沒有損益，只有漲跌
                    <Pct value={w.quote?.change_pct ?? null} className="@min-[52rem]:hidden" />
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

/** 手機：兩行列。右下那一行是今日漲跌或報酬率（表頭的 `PhoneLineToggle` 切換） */
function HoldingsList({ rows, pinned }: { rows: Holding[]; pinned: string[] }) {
  const watch = useWatchlist()
  const readOnly = useReadOnly()
  const plans = useActivePlans()
  const label = useColumnLabel()
  const pnl = useLedgerPrefs((s) => s.phoneLine === "pnl")
  const [open, toggle] = useOpenRows()
  return (
    <div className="md:hidden">
      <div className="form-head flex h-11 items-end justify-between pb-2">
        <span>持有 {rows.length} 檔</span>
        <PhoneLineToggle />
      </div>
      <ul aria-label="持倉" data-holdings-focus>
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
                {/* 表頭是切換鈕，螢幕報讀器在每一列也聽得到這個數字是什麼 */}
                <span className="sr-only">{pnl ? label("pnl") : label("day_pct")}</span>
                {h.price === null ? <Dash /> : <Pct value={pnl ? h.unrealized_pnl_pct : h.day_change_pct} />}
              </span>
              <ExpandButton h={h} open={open.has(h.symbol)} onToggle={() => toggle(h.symbol)} className="relative z-10 col-start-3 row-span-2 row-start-1 ml-1 self-center" />
            </div>
            {open.has(h.symbol) && (
              <div id={recordsId(h)} className="border-b border-rule pb-3">
                <CostLine h={h} />
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

/**
 * 手機持倉的表頭「收盤價・今日漲跌」本身是切換鈕（產品負責人 2026-11-17 選 A）：按一下變「收盤價・損益」，
 * 每一列右下那一行換成這一檔的報酬率（和桌面「損益」欄的第二行同一個數字、同一個 ▲▼ 與漲跌色），再按一下換回來。
 * 版面與列高不變；記在這台瀏覽器（`ledger-prefs` 的 `phoneLine`）。隱私模式照常顯示百分比。
 * 看得出能按：右邊一個 ⇄，放在下面每一列展開鈕的那一欄（同寬、同一個右緣），字的右緣就對齊收盤價那一欄。
 * 按鈕和表頭一樣高（44px，往下蓋到表頭的雙線，雙線不接收點按）；名稱是看得到的字＋「（改看損益）」。
 */
function PhoneLineToggle() {
  const pnl = useLedgerPrefs((s) => s.phoneLine === "pnl")
  const toggle = useLedgerPrefs((s) => s.togglePhoneLine)
  const label = useColumnLabel()
  const [now, next] = pnl ? [label("pnl"), label("day_pct")] : [label("day_pct"), label("pnl")]
  return (
    <button type="button" onClick={toggle} className="press -mb-2 flex h-11 items-end rounded-sm pb-2 hover:text-ink">
      <span className="num">
        {label("price")}・{now}
      </span>
      <span className="sr-only">（改看{next}）</span>
      {/* 和 ExpandButton 同寬（觸控 44px、滑鼠 36px）、同一個左距 */}
      <span aria-hidden className="ml-1 grid h-5 w-9 place-items-center pointer-coarse:w-11">
        <ArrowLeftRightIcon className="size-4" />
      </span>
    </button>
  )
}

function WatchRowMobile({ w }: { w: WatchItem }) {
  const market = marketOf(w.symbol)
  // 自選本身就帶盤中點；沒有時改抓 intraday
  const fallback = useIntraday(w.symbol, w.sparkline.length < 2)
  const values = w.sparkline.length >= 2 ? w.sparkline.map((p) => p.price) : (fallback.data?.points ?? []).map((p) => p.price)
  return (
    <li>
      <Link to="/stock/$symbol" params={{ symbol: w.symbol }} className="ruled-row grid h-[72px] grid-cols-[1fr_76px_96px] content-center gap-x-3 gap-y-0.5">
        <span className="truncate text-lg leading-6 font-medium">{w.name}</span>
        <Sparkline className="col-start-2 row-span-2 row-start-1 self-center" width={76} height={32} values={values} baseline={w.sparkline_interval === "1d" ? null : (w.quote?.reference_price ?? w.quote?.prev_close ?? null)} tone="ink" label={`${w.name}今日走勢`} />
        <span className="num col-start-3 row-start-1 text-right text-lg leading-6">
          {market === "US" && w.quote && "US$"}
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
