import { Link } from "@tanstack/react-router"
import { XIcon } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { useAccounts, useCreateTransaction, useDeleteTransaction, useHoldings, useQuote } from "@/api/queries"
import type { Instrument, TransactionInput } from "@/api/types"
import type { TradePrefill } from "@/app/ui-store"
import { FieldError, FormField as Row } from "@/components/form-field"
import { SymbolPicker } from "@/components/symbol-picker"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { defaultAccount } from "@/lib/default-account"
import { formatPrice, formatQuantity } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { AccountSelect, StampLine } from "./TradeForm"

/**
 * 記一筆（預設的輸入方式；產品負責人 2026-11-14：照 Google 財經新增持股的做法，原本的表單太複雜）：
 * 選一檔 → 股數、買進日期、買進價格 →「新增」。同一檔分好幾次買的，按「再加一筆買進」多一列。
 * 沒有類型、備註與稅費試算：手續費照帳戶設定的費率算進成本，不另外顯示。
 * 賣出、股利與其他類型走完整表單（下面的文字連結）。
 */
interface Lot {
  id: number
  qty: string
  date: string
  price: string
}

const MAX_LOTS = 12
/** 台股的數量太細：以張填時最多小數第三位（1 股），以股填時要是整數 */
const tooFine = (text: string, inLots: boolean): boolean => {
  const t = text.replace(/[,\s]/g, "")
  return inLots ? /\.\d{4,}$/.test(t) : /\.\d*[1-9]\d*$/.test(t)
}
const num = (s: string): number | null => {
  const n = Number(s.replace(/[,\s]/g, ""))
  return s.trim() === "" || Number.isNaN(n) ? null : n
}

export function QuickAdd({ initialSymbol, onDone, onFull, sheet = false }: { initialSymbol?: string; onDone: () => void; onFull: (symbol?: string, prefill?: TradePrefill) => void; sheet?: boolean }) {
  const accounts = useAccounts()
  const holdings = useHoldings()
  const create = useCreateTransaction()
  const remove = useDeleteTransaction()
  const unitPref = usePrefs((s) => s.quantityUnit)
  const nextId = useRef(1)
  const formRef = useRef<HTMLFormElement>(null)
  const [accountId, setAccountId] = useState("")
  const [symbol, setSymbol] = useState<Instrument | null>(null)
  const [lots, setLots] = useState<Lot[]>(() => [{ id: 0, qty: "", date: appToday(), price: "" }])
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)

  // 打開時焦點放在股票搜尋（Google 財經也是先選股票）；從個股頁帶入那一檔時放在數量
  useEffect(() => {
    const t = window.setTimeout(() => {
      const target = formRef.current?.querySelector<HTMLInputElement>(initialSymbol ? "#lot-qty-0" : "[cmdk-input]")
      target?.focus({ preventScroll: true })
    }, 80)
    return () => window.clearTimeout(t)
  }, [initialSymbol])

  useEffect(() => {
    if (!initialSymbol) return
    let alive = true
    void api.getInstrument(initialSymbol).then((i) => alive && setSymbol((s) => s ?? i)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [initialSymbol])

  // 帳戶沒動過時跟著股票走：這一檔持有的帳戶 → 同幣別 → 第一個（Apple 不會記進新台幣帳戶）
  const account = accounts.data?.find((a) => a.id === accountId) ?? defaultAccount(accounts.data, symbol, holdings.data)
  const quote = useQuote(symbol?.symbol ?? "", !!symbol)
  const isUS = symbol?.market === "US" || account?.currency === "USD"
  const inLots = unitPref === "lot" && !isUS
  const shares = (l: Lot) => {
    const q = num(l.qty)
    // 張換股取整：2.006 × 1000 在浮點數是 2005.9999…，不取整會被說「不是整數」
    return q === null ? null : inLots ? Math.round(q * 1000) : q
  }
  const errorOf = (l: Lot) => {
    const s = shares(l)
    const p = num(l.price)
    return {
      qty: !s || s <= 0 ? `請輸入${inLots ? "張數" : "股數"}` : !isUS && tooFine(l.qty, inLots) ? (inLots ? "張數最多寫到小數第三位（1 股）" : "台股股數必須是整數") : null,
      price: !p || p <= 0 ? "請輸入價格" : null,
    }
  }
  const invalid = !symbol || !account || lots.some((l) => Object.values(errorOf(l)).some(Boolean))
  const setLot = (id: number, patch: Partial<Lot>) => setLots((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)))

  if (accounts.data && accounts.data.length === 0) {
    return (
      <div className="flex flex-col gap-1 px-4 pb-6 sm:px-6">
        <p className="text-base">還沒有券商帳戶，先到設定建立一個。</p>
        <Link to="/settings" onClick={onDone} className={cn(buttonVariants({ variant: "outline" }), "mt-2 self-start")}>
          到設定
        </Link>
      </div>
    )
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (invalid || !symbol || !account) return
    setBusy(true)
    const created: string[] = []
    let total = 0
    try {
      for (const l of lots) {
        const body: TransactionInput = { account_id: account.id, symbol: symbol.symbol, type: "buy", trade_date: l.date, quantity: shares(l), price: num(l.price), note: "" }
        // 走 useCreateTransaction：存好之後持股、總資產、交易清單會重抓（直接呼叫 api 的話帳本不會動，2026-11-14 評分）
        created.push((await create.mutateAsync(body)).id)
        total += shares(l) ?? 0
      }
    } catch (err) {
      toast.error(created.length ? `只記了 ${created.length} 筆，其餘沒有存成功，內容還在。` : "沒有存成功，內容還在。", { description: err instanceof Error ? err.message : undefined })
      // 已經存進去的那幾列拿掉，留下還沒存的，改完可以再按一次
      setLots((ls) => ls.slice(created.length))
      setBusy(false)
      return
    }
    toast.success(`已記錄：買進 ${symbol.name} ${formatQuantity(total, unitPref, symbol.market)}${created.length > 1 ? `（${created.length} 筆）` : ""}`, {
      description: <StampLine />,
      action: {
        label: "復原",
        onClick: () =>
          void Promise.all(created.map((id) => remove.mutateAsync(id))).then(
            () => toast(created.length > 1 ? "已復原這幾筆交易" : "已復原這筆交易"),
            () => toast.error("沒有復原成功。到「紀錄」刪掉這幾筆。"),
          ),
      },
    })
    onDone()
  }

  const addLot = () => {
    const id = nextId.current++
    setLots((ls) => [...ls, { id, qty: "", date: ls.at(-1)?.date ?? appToday(), price: "" }])
    setSubmitted(false)
    requestAnimationFrame(() => formRef.current?.querySelector<HTMLInputElement>(`#lot-qty-${id}`)?.focus())
  }

  const qtyLabel = inLots ? "張數" : "股數"
  // 完整表單：帳戶與第一筆已經填的數量、價格、日期一起帶過去
  const toFull = (
    <button
      type="button"
      onClick={() => {
        const first = lots[0]
        onFull(symbol?.code, { accountId: account?.id, quantity: (first && shares(first)) || undefined, price: (first && num(first.price)) || undefined, date: first?.date })
      }}
      className="inline-flex min-h-9 items-center text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink pointer-coarse:min-h-11"
    >
      賣出、股利或其他
    </button>
  )
  return (
    <form ref={formRef} onSubmit={(e) => void submit(e)} noValidate className={cn("flex flex-col gap-4 px-4 sm:px-6", sheet ? "pb-0" : "pb-4 sm:pb-6")}>
      {(accounts.data?.length ?? 0) > 1 && (
        <Row label="帳戶" className="sm:max-w-xs">
          <AccountSelect accounts={accounts.data ?? []} value={account?.id ?? ""} onChange={setAccountId} />
        </Row>
      )}
      <Row label="股票" error={submitted && !symbol ? "請選擇股票或 ETF" : null}>
        <SymbolPicker value={symbol} onChange={setSymbol} invalid={submitted && !symbol} />
        {symbol && quote.data && (
          <p className="num mt-1 text-sm text-ink-2">
            收盤 {formatPrice(quote.data.price, symbol.market, symbol.type)}
            {quote.data.as_of ? `（${quote.data.as_of.slice(5, 10).replace("-", "/")}）` : ""}
          </p>
        )}
      </Row>

      <div className="flex flex-col gap-3">
        {lots.map((l, i) => {
          const err = submitted ? errorOf(l) : { qty: null, price: null }
          const nth = lots.length > 1 ? `第 ${i + 1} 筆的` : ""
          const s = shares(l)
          // 另一種單位的換算（「2 張」「2,000 股」）：只在有幫助的時候寫在欄位下面
          const other = !s || isUS ? null : inLots ? `${new Intl.NumberFormat("zh-TW").format(s)} 股` : s >= 1000 && s % 1000 === 0 ? `${s / 1000} 張` : null
          return (
            // 手機一筆排兩行：股數｜價格，下面是日期（有好幾筆時右邊是移除）；第二筆起上面加一條格線分開
            <div
              key={l.id}
              className={cn(
                "grid grid-cols-2 items-start gap-x-2 gap-y-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)_auto]",
                i > 0 && "max-sm:border-t max-sm:border-rule max-sm:pt-3",
              )}
            >
              <Cell label={qtyLabel} id={`lot-qty-${l.id}`} first={i === 0} error={err.qty} note={other}>
                <Input
                  id={`lot-qty-${l.id}`}
                  inputMode="decimal"
                  autoComplete="off"
                  aria-label={`${nth}${qtyLabel}`}
                  // 第二筆起沒有看得見的標籤（捲動後第一列的標籤也不在畫面上）：提示字直接寫欄位名稱
                  placeholder={i === 0 ? (inLots ? "例如 1" : "例如 1000") : qtyLabel}
                  value={l.qty}
                  onChange={(e) => setLot(l.id, { qty: e.target.value })}
                  aria-invalid={!!err.qty}
                  className="num"
                />
              </Cell>
              <Cell label="買進日期" id={`lot-date-${l.id}`} first={i === 0} className={cn("max-sm:order-3", lots.length === 1 && "max-sm:col-span-2")}>
                <Input id={`lot-date-${l.id}`} type="date" aria-label={`${nth}買進日期`} value={l.date} max={appToday()} onChange={(e) => setLot(l.id, { date: e.target.value })} />
              </Cell>
              <Cell label={`買進價格${isUS ? "（美元）" : ""}`} id={`lot-price-${l.id}`} first={i === 0} error={err.price}>
                <Input
                  id={`lot-price-${l.id}`}
                  inputMode="decimal"
                  autoComplete="off"
                  enterKeyHint="done"
                  aria-label={`${nth}買進價格`}
                  placeholder="每股價格"
                  value={l.price}
                  onChange={(e) => setLot(l.id, { price: e.target.value })}
                  aria-invalid={!!err.price}
                  className="num"
                />
              </Cell>
              {lots.length > 1 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`移除第 ${i + 1} 筆`}
                  // 第一列有標籤：往下對齊輸入框；手機上排在這一筆的最後、靠右
                  className={cn("max-sm:order-4 max-sm:self-end max-sm:justify-self-end", i === 0 && "sm:mt-[1.625rem]")}
                  onClick={() => setLots((ls) => ls.filter((x) => x.id !== l.id))}
                >
                  <XIcon aria-hidden />
                </Button>
              )}
            </div>
          )
        })}
      </div>

      {(lots.length < MAX_LOTS || sheet) && (
        <div className="flex flex-wrap items-center justify-between gap-x-4">
          {lots.length < MAX_LOTS && (
            <button type="button" onClick={addLot} className="inline-flex min-h-9 items-center text-base underline decoration-ctl underline-offset-3 hover:decoration-ink pointer-coarse:min-h-11">
              再加一筆買進
            </button>
          )}
          {/* 手機：放在捲動區裡，固定的動作列只留取消／新增一行（鍵盤打開時欄位才看得到） */}
          {sheet && toFull}
        </div>
      )}

      {/* 手機抽屜：動作列貼在捲動區的底部（一條格線，不加陰影），再加幾筆也看得到「新增」 */}
      <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-3 pt-1", sheet && "safe-bottom sticky bottom-0 z-10 -mx-4 border-t border-rule bg-popover px-4 py-3 sm:-mx-6 sm:px-6")}>
        {!sheet && toFull}
        <div className={cn("flex gap-2 max-sm:w-full", !sheet && "ml-auto")}>
          <Button type="button" variant="outline" className="max-sm:flex-1 sm:min-w-24" onClick={onDone}>
            取消
          </Button>
          <Button type="submit" variant="sign" className="max-sm:flex-1 sm:min-w-28" disabled={busy}>
            {busy ? "新增中…" : "新增"}
          </Button>
        </div>
      </div>
    </form>
  )
}

/** 一筆買進裡的一格：第一筆才有看得見的標籤（其他筆的名字在輸入框的 aria-label） */
function Cell({ label, id, first, error, note, className, children }: { label: string; id: string; first: boolean; error?: string | null; note?: string | null; className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      {first && (
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
      )}
      {children}
      {error ? <FieldError>{error}</FieldError> : note ? <p className="num text-sm text-ink-2">{note}</p> : null}
    </div>
  )
}
