import { Link } from "@tanstack/react-router"
import { EllipsisIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { useAccounts, useDeleteTransaction } from "@/api/queries"
import type { InstrumentType, Market, Transaction } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { Masked, Pct } from "@/components/finance"
import { textAction } from "@/components/text-action"
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
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { formatMoney, formatPrice, formatQuantity } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useStartReduce } from "@/pages/transactions/use-start-reduce"
import { usePrefs } from "@/stores/prefs"
import { buyAverage, DILUTING, recordDate, useSymbolTransactions } from "./symbol-records"

/** 展開後最多列幾筆（新的在前）；更多的到「紀錄」看 */
export const RECORDS_SHOWN = 10
/*
 * 欄位跟著容器的寬度排（@container）：持倉表展開的那一列很寬，個股頁「我的部位」比較窄。
 * - 窄（< 688px）：兩行——日期・類型｜金額；股數 × 價格 均價｜買進後漲跌；最右邊 ⋯（放不下時「均價」整段換到下一行）
 * - 寬（≥ 688px，43rem）：日期｜類型｜帳戶｜股數｜價格・均價｜金額｜買進後漲跌｜⋯
 *   價格那一格兩行（成交價；13px 淡墨「均價 US$274.55」），所以 6.5rem；固定的欄加起來 600px＋7 個 12px 的間隔＝684px，
 *   斷點從 672px 提高到 688px，帳戶那一欄才不會變成負的、把表格撐出去。
 */
const GRID =
  "grid grid-cols-[minmax(0,1fr)_auto_2.5rem] gap-x-3 @[43rem]:grid-cols-[7.5rem_2.5rem_minmax(0,1fr)_5.5rem_6.5rem_7.5rem_5.5rem_2.5rem]"

/** 表頭「價格・均價」滑過的說明（和持倉表的均價同一個算法） */
export const LOT_AVG_HINT = "均價：（股數 × 成交價＋這一筆的手續費）÷ 股數；沒填手續費以 0 計"

/**
 * 一檔股票的每一筆買進與賣出（產品負責人 2026-11-14，參考 Google 財經展開持股看每一批）：
 * 日期、類型、帳戶（不只一個帳戶時）、股數、價格、金額，買進那幾筆再加「買進後漲跌」（今天的收盤價對那一筆的買進價）
 * 與價格下面一行的「均價」（含這一筆的手續費，產品負責人 2026-11-17；`buyAverage`）。金額照舊是成交金額（股數 × 價格）。
 * 配過股、分割過或減資過的那一檔不列漲跌（股價被稀釋，直接比會錯），最下面寫一句。
 * 每一筆的 ⋯：修改（打開完整表單，日期、股數、價格都能改）、刪除（先確認）。查看別人的資產時只能看。
 * `actions`：最下面的「再加一筆買進」「減少持股」（持倉表展開時有；個股頁的標題列已經有這兩顆，不重複），
 * 和那一列最後、淡墨的「刪除這檔」（整檔的紀錄都刪掉，確認框見 `DeleteHoldingDialog`；手機的持倉沒有「⋯」，從這裡刪）。
 * 「只記持股」的帳戶沒有逐筆交易：那個帳戶目前的持股（快照）是一列「持股」，日期是快照的日期、價格是均價；
 * ⋯ 只有「修改」（打開那個帳戶的持股輸入）。
 * 股利不列在這裡（自動入帳，在「紀錄」的股利裡）。
 */
export function SymbolRecords({
  symbol,
  code,
  name,
  market,
  type,
  price,
  held = true,
  actions = false,
  className,
}: {
  symbol: string
  code: string
  name: string
  market: Market
  type?: InstrumentType
  /** 今天的收盤價；沒有報價時是 null（不列買進後漲跌） */
  price: number | null
  /** 現在還持有（「減少持股」才有意義） */
  held?: boolean
  actions?: boolean
  className?: string
}) {
  const q = useSymbolTransactions(symbol)
  const accounts = useAccounts()
  const readOnly = useReadOnly()
  const openTradeForm = useUi((s) => s.openTradeForm)
  const openDeleteHolding = useUi((s) => s.openDeleteHolding)
  const reduce = useStartReduce()
  const remove = useDeleteTransaction()
  // 刪除的確認框放在清單這一層（不放在列裡）：那一列刪掉時確認框不會跟著卸載、關到一半
  const [deleting, setDeleting] = useState<{ t: Transaction; date: string; label: string } | null>(null)
  if (q.isError) {
    return (
      <p className={cn("py-3 text-base text-ink", className)}>
        讀不到這一檔的紀錄。{" "}
        <button type="button" className={textAction} onClick={() => void q.refetch()}>
          再試一次
        </button>
      </p>
    )
  }
  if (!q.data) {
    return (
      <div aria-busy="true" aria-label={`${name}的紀錄載入中`} className={cn("flex flex-col gap-2 py-3", className)}>
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    )
  }
  const all = q.data.items
  const diluted = all.some((t) => DILUTING.has(t.type))
  const trades = all.filter((t) => t.type === "buy" || t.type === "sell")
  // 新的在前；同一天的照建立的先後（後建立的在前）
  const entries = [...trades].sort((x, y) => y.trade_date.localeCompare(x.trade_date) || y.created_at.localeCompare(x.created_at))
  const shown = entries.slice(0, RECORDS_SHOWN)
  const more = entries.length - shown.length + (q.data.more ? 1 : 0)
  const multiAccount = new Set(entries.map((t) => t.account_id)).size > 1
  const accountName = (id: string) => accounts.data?.find((a) => a.id === id)?.name
  const showChange = !diluted && price !== null
  return (
    <div className={cn("@container", className)}>
      {entries.length === 0 ? (
        <p className="py-3 text-base text-ink-2">這一檔還沒有買進或賣出的紀錄。</p>
      ) : (
        <>
          <div aria-hidden className={cn("form-head h-9 items-end pb-1.5 @max-[43rem]:hidden", GRID)}>
            <span>日期</span>
            <span>類型</span>
            <span>{multiAccount ? "帳戶" : ""}</span>
            <span className="text-right">股數</span>
            <span className="text-right" title={LOT_AVG_HINT}>
              價格・均價
            </span>
            <span className="text-right">金額</span>
            <span className="text-right">{showChange ? "買進後漲跌" : ""}</span>
            <span />
          </div>
          <ul aria-label={`${name}的每一筆買賣`}>
            {shown.map((e) => (
              <RecordRow
                key={e.id}
                entry={e}
                market={market}
                type={type}
                price={showChange ? price : null}
                account={multiAccount ? accountName(e.account_id) : undefined}
                readOnly={readOnly}
                onDelete={(t, date, label) => setDeleting({ t, date, label })}
              />
            ))}
          </ul>
        </>
      )}
      {(diluted || more > 0 || (actions && !readOnly)) && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 pt-2">
          {actions && !readOnly && (
            <>
              <button type="button" className={textAction} onClick={() => openTradeForm({ symbol: code })}>
                再加一筆買進
              </button>
              {held && (
                <button type="button" className={textAction} onClick={() => reduce(symbol)}>
                  減少持股
                </button>
              )}
            </>
          )}
          {more > 0 && (
            <Link to="/" search={{ view: "transactions", symbol }} className={textAction}>
              在紀錄裡看全部 {q.data.more ? `${trades.length} 筆以上` : `${trades.length} 筆`}交易
            </Link>
          )}
          {diluted && entries.length > 0 && <span className="text-sm text-ink-2 @[43rem]:ml-auto">配過股或分割過，不列每一筆的漲跌。</span>}
          {/* 最重的動作放最後、淡墨（不用紅色：紅色是「漲」）；寬的時候靠右，和上面每一筆的「⋯」同一邊 */}
          {actions && !readOnly && all.length > 0 && (
            <button
              type="button"
              className={cn(textAction, "text-ink-2 hover:text-ink", !(diluted && entries.length > 0) && "@[43rem]:ml-auto")}
              onClick={() => openDeleteHolding(symbol)}
            >
              刪除這檔
            </button>
          )}
        </div>
      )}
      <AlertDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除這筆{deleting?.label}？</AlertDialogTitle>
            <AlertDialogDescription>
              {deleting?.date} {deleting?.label}。刪除後持股、損益與績效會重新計算。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!deleting) return
                const { t, date, label } = deleting
                setDeleting(null)
                remove.mutate(t.id, {
                  onSuccess: () => toast.success(`已刪除 ${date} 的${label}`),
                  onError: (err) => toast.error("刪除失敗", { description: err.message }),
                })
              }}
            >
              刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function RecordRow({
  entry: e,
  market,
  type,
  price,
  account,
  readOnly,
  onDelete,
}: {
  entry: Transaction
  market: Market
  type?: InstrumentType
  price: number | null
  account?: string
  readOnly: boolean
  onDelete: (t: Transaction, date: string, label: string) => void
}) {
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const quantity = e.quantity
  const unitPrice = e.price
  const qty = quantity !== null ? formatQuantity(quantity, unit, market) : "—"
  const px = unitPrice !== null ? `${market === "US" ? "US$" : ""}${formatPrice(unitPrice, market, type)}` : "—"
  const amount = formatMoney(e.amount, { currency: e.currency })
  const label = e.type === "buy" ? "買進" : "賣出"
  const strong = label !== "賣出"
  // 買進後漲跌：今天的收盤價對那一筆的買進價
  const change = label !== "賣出" && price !== null && unitPrice ? price / unitPrice - 1 : null
  // 買進均價（含這一筆的手續費，沒填以 0 計）：和成交價同一套價格寫法，算出來的數字補到看得出差異（815.32）。
  // 賣出不寫：賣出價扣掉手續費與稅不是「均價」，賣掉賺賠多少在已實現損益
  const avg = buyAverage(e)
  const avgText = avg !== null ? `${market === "US" ? "US$" : ""}${formatPrice(avg, market, type)}` : null
  const date = recordDate(e.trade_date)
  const hide = (s: string) => (privacy ? <Masked /> : s)
  return (
    <li className={cn("ruled-row min-h-12 items-baseline py-2 text-base", GRID)}>
      {/* 窄：第一行日期・類型｜金額，第二行股數 × 價格、均價｜買進後漲跌 */}
      {/* 日期、類型、帳戶各自不斷開：放不下時整段換行，不會把「買進」拆成兩行 */}
      <span className="num flex min-w-0 flex-wrap items-baseline gap-x-2 @[43rem]:hidden">
        <span className="whitespace-nowrap">{date}</span>
        <span className={cn("whitespace-nowrap", strong ? "font-medium" : "text-ink-2")}>{label}</span>
        {account && <span className="truncate text-sm text-ink-2">{account}</span>}
      </span>
      <span className="num text-right font-medium @[43rem]:hidden">{hide(amount)}</span>
      {/* 寬：每一格一欄 */}
      <span className="num @max-[43rem]:hidden">{date}</span>
      <span className={cn("@max-[43rem]:hidden", strong ? "font-medium" : "text-ink-2")}>{label}</span>
      <span className="truncate text-sm text-ink-2 @max-[43rem]:hidden" title={account}>
        {account}
      </span>
      <span className="num text-right @max-[43rem]:hidden">{hide(qty)}</span>
      {/* 價格一格兩行：成交價；買進多一行 13px 淡墨「均價 815.32」（和持倉表收盤價下面那一行同一個樣子）。太長時往左（股數那一格的第二行是空的）伸，不壓到金額 */}
      <span className="num flex flex-col items-end @max-[43rem]:hidden">
        <span>{hide(px)}</span>
        {avgText !== null && <span className="mt-0.5 text-sm leading-tight whitespace-nowrap text-ink-2">均價 {hide(avgText)}</span>}
      </span>
      <span className="num text-right font-medium @max-[43rem]:hidden">{hide(amount)}</span>
      <span className="text-right @max-[43rem]:hidden">{change !== null && <Pct value={change} />}</span>
      <span className="row-span-2 flex justify-end self-center @[43rem]:row-span-1">
        {!readOnly && <RecordMenu t={e} date={date} label={label} onDelete={() => onDelete(e, date, label)} />}
      </span>
      {/* 「股數 × 價格」與「均價 …」各自不斷開：放不下時均價整段換到下一行，不用「・」（換行後會掛在行尾） */}
      <span className="num col-start-1 row-start-2 flex min-w-0 flex-wrap gap-x-3 text-sm text-ink-2 @[43rem]:hidden">
        <span className="whitespace-nowrap">{privacy ? <Masked /> : `${qty} × ${px}`}</span>
        {avgText !== null && <span className="whitespace-nowrap">均價 {hide(avgText)}</span>}
      </span>
      <span className="col-start-2 row-start-2 text-right text-sm @[43rem]:hidden">{change !== null && <Pct value={change} />}</span>
    </li>
  )
}

/**
 * 每一筆的「⋯」：整個按鈕（滑過的底色、焦點框）都在這一列裡面——不再用負的右邊距把圖示推到列的右緣
 * （2026-11-17 負責人：「三個點點的 hover 好像超過整個框框了」：底色比列與表格的右緣多出 8px）。
 * 觸控裝置 44px（比最後一欄的 40px 寬：`shrink-0` 不被擠回 40px，靠右對齊所以往左多佔一點間隔，右緣還是對齊列的右緣）。
 * 滑過是 `bg-sel`（比列的 `--hov` 深一階，和群組成員列的「⋯」、secondary 按鈕同一個慣例）：按鈕在格線列裡，滑過按鈕時
 * 整列也是 `--hov`，用同一個顏色就看不出按鈕的方塊（2026-11-17 審查）。
 */
export const ROW_MENU_BUTTON =
  "press grid size-9 shrink-0 place-items-center rounded-sm text-ink-2 hover:bg-sel hover:text-ink aria-expanded:bg-sel aria-expanded:text-ink pointer-coarse:size-11"

/** 一筆的動作：修改（完整表單，日期也能改）、刪除（確認框在清單那一層） */
function RecordMenu({ t, date, label, onDelete }: { t: Transaction; date: string; label: string; onDelete: () => void }) {
  const openTradeForm = useUi((s) => s.openTradeForm)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<button type="button" aria-label={`${date} ${label}的動作`} className={ROW_MENU_BUTTON} />}>
        <EllipsisIcon aria-hidden className="size-5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuItem onClick={() => openTradeForm({ edit: t })}>修改</DropdownMenuItem>
        <DropdownMenuItem onClick={onDelete}>刪除</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
