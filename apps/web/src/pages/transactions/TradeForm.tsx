import { useQuery } from "@tanstack/react-query"
import { Command as CommandPrimitive } from "cmdk"
import { XIcon } from "lucide-react"
import { useEffect, useId, useMemo, useState } from "react"
import { toast } from "sonner"
import { api } from "@/api"
import { useAccounts, useCreateTransaction, useDeleteTransaction, useInstrumentSearch } from "@/api/queries"
import type { Account, Instrument, TradePreview, TransactionInput, TransactionType } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { Chop } from "@/components/chop"
import { RangeChips } from "@/components/charts/chart-kit"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsDesktop } from "@/hooks/use-media-query"
import { formatMoney, formatQuantity, todayInTaipei } from "@/lib/format"
import { TYPE_LABEL } from "@/lib/labels"
import { cn } from "@/lib/utils"
import { FormField as Row } from "@/components/form-field"
import { usePrefs } from "@/stores/prefs"


type MainType = "buy" | "sell" | "cash_dividend" | "other"
const MAIN_TYPES: { value: MainType; label: string }[] = [
  { value: "buy", label: "買進" },
  { value: "sell", label: "賣出" },
  { value: "cash_dividend", label: "股利" },
  { value: "other", label: "其他" },
]
const OTHER_TYPES: TransactionType[] = ["stock_dividend", "split", "capital_reduction", "deposit", "withdrawal", "fee", "tax", "interest"]
const CASH_TYPES: TransactionType[] = ["deposit", "withdrawal", "fee", "tax", "interest"]

/** 掛在 AppShell：依裝置用 Dialog（桌面）或 Vaul Drawer（手機） */
export function TradeFormHost() {
  const { open, symbol } = useUi((s) => s.tradeForm)
  const close = useUi((s) => s.closeTradeForm)
  const isDesktop = useIsDesktop()
  const title = "記一筆交易"
  const description = "填好數量與價格後，右側會即時試算手續費與稅。"

  if (isDesktop) {
    return (
      <Dialog open={open} onOpenChange={(o) => !o && close()}>
        <DialogContent className="max-h-[calc(100dvh-4rem)] gap-0 overflow-y-auto p-0 sm:max-w-[760px]">
          <DialogHeader className="border-b px-6 pt-5 pb-4">
            <DialogTitle className="text-lg font-semibold">{title}</DialogTitle>
            <DialogDescription className="text-md">{description}</DialogDescription>
          </DialogHeader>
          {open && <TradeForm initialSymbol={symbol} onDone={close} layout="split" />}
        </DialogContent>
      </Dialog>
    )
  }
  return (
    <Drawer open={open} onOpenChange={(o) => !o && close()} repositionInputs={false}>
      <DrawerContent className="max-h-[92dvh]">
        <DrawerHeader className="pb-2 text-left">
          <DrawerTitle className="text-lg font-semibold">{title}</DrawerTitle>
          <DrawerDescription className="text-md">{description}</DrawerDescription>
        </DrawerHeader>
        <div className="overflow-y-auto overscroll-contain">{open && <TradeForm initialSymbol={symbol} onDone={close} layout="stack" />}</div>
      </DrawerContent>
    </Drawer>
  )
}

interface FormState {
  accountId: string
  mainType: MainType
  otherType: TransactionType
  symbol: Instrument | null
  date: string
  qtyText: string
  qtyUnit: "lot" | "share"
  priceText: string
  amountText: string
  dayTrade: boolean
  note: string
}

function parseNum(s: string): number | null {
  const n = Number(s.replace(/[,\s]/g, ""))
  return s.trim() === "" || Number.isNaN(n) ? null : n
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function TradeForm({ initialSymbol, onDone, layout }: { initialSymbol?: string; onDone: () => void; layout: "split" | "stack" }) {
  const accounts = useAccounts()
  const unitPref = usePrefs((s) => s.quantityUnit)
  const create = useCreateTransaction()
  const remove = useDeleteTransaction()
  const [f, setF] = useState<FormState>({
    accountId: "",
    mainType: "buy",
    otherType: "deposit",
    symbol: null,
    date: todayInTaipei(),
    qtyText: "",
    qtyUnit: unitPref,
    priceText: "",
    amountText: "",
    dayTrade: false,
    note: "",
  })
  const [submitted, setSubmitted] = useState(false)
  const set = (patch: Partial<FormState>) => setF((s) => ({ ...s, ...patch }))

  // 預先帶入的代號（帳戶未選時預設第一個）
  useEffect(() => {
    if (!initialSymbol) return
    void api.getInstrument(initialSymbol).then((i) => setF((s) => (s.symbol ? s : { ...s, symbol: i })))
  }, [initialSymbol])

  const accountId = f.accountId || accounts.data?.[0]?.id || ""
  const account = accounts.data?.find((a) => a.id === accountId)
  const type: TransactionType = f.mainType === "other" ? f.otherType : f.mainType
  const isCash = CASH_TYPES.includes(type)
  const isUS = account?.currency === "USD" || f.symbol?.market === "US"
  const qty = parseNum(f.qtyText)
  const shares = qty === null ? null : f.qtyUnit === "lot" && !isUS && (type === "buy" || type === "sell") ? qty * 1000 : qty
  const price = parseNum(f.priceText)
  const amount = parseNum(f.amountText)

  const body: TransactionInput | null = useMemo(() => {
    if (!account) return null
    if (isCash) return amount && amount > 0 ? { account_id: account.id, symbol: null, type, trade_date: f.date, quantity: null, price: null, amount } : null
    if (!f.symbol || !shares || shares <= 0) return null
    if ((type === "buy" || type === "sell" || type === "cash_dividend") && (!price || price <= 0)) return null
    return {
      account_id: account.id,
      symbol: f.symbol.symbol,
      type,
      trade_date: f.date,
      quantity: shares,
      price,
      is_day_trade: type === "sell" ? f.dayTrade : false,
      note: f.note,
    }
  }, [account, isCash, amount, type, f.date, f.symbol, shares, price, f.dayTrade, f.note])

  const debounced = useDebounced(body)
  const preview = useQuery({
    queryKey: ["preview", debounced],
    queryFn: () => api.previewTransaction(debounced!),
    enabled: !!debounced,
    staleTime: 60_000,
  })

  const errors = {
    symbol: !isCash && !f.symbol ? "請選擇股票或 ETF" : null,
    qty: !isCash && (!shares || shares <= 0) ? "請輸入數量" : !isCash && shares !== null && !Number.isInteger(shares) && !isUS ? "台股股數必須是整數" : null,
    price: !isCash && ["buy", "sell", "cash_dividend"].includes(type) && (!price || price <= 0) ? "請輸入價格" : null,
    amount: isCash && (!amount || amount <= 0) ? "請輸入金額" : null,
  }
  const hasError = Object.values(errors).some(Boolean) || !account

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (hasError || !body) return
    create.mutate(body, {
      onSuccess: (txn) => {
        const what = isCash
          ? `${TYPE_LABEL[type]} ${formatMoney(txn.amount, { currency: account!.currency })}`
          : `${TYPE_LABEL[type]} ${f.symbol!.name} ${formatQuantity(txn.quantity ?? 0, unitPref, f.symbol!.market)}`
        toast.success(`已記錄：${what}`, {
          description: <StampLine />,
          action: {
            label: "復原",
            onClick: () =>
              remove.mutate(txn.id, {
                onSuccess: () => toast("已復原這筆交易"),
                onError: () => toast.error("復原失敗，請到交易紀錄手動刪除"),
              }),
          },
        })
        onDone()
      },
      onError: (err) => toast.error("儲存失敗，表單內容仍保留", { description: err instanceof Error ? err.message : undefined }),
    })
  }

  if (accounts.isLoading) return <div className="p-6"><Skeleton className="h-64 w-full" /></div>
  if (accounts.data?.length === 0)
    return (
      <div className="flex flex-col gap-2 p-6 text-md">
        <p className="font-medium">還沒有券商帳戶</p>
        <p className="text-muted-foreground">先到「設定」新增一個帳戶（例如「永豐－一般」），手續費折扣才能算對。</p>
      </div>
    )

  const unitHint = !isUS && (type === "buy" || type === "sell") && shares ? formatQuantity(shares, "lot", "TWSE") : null

  return (
    <form onSubmit={submit} noValidate className={cn("grid", layout === "split" ? "grid-cols-[minmax(0,1fr)_260px]" : "grid-cols-1")}>
      <div className="flex flex-col gap-4 px-4 py-4 sm:px-6">
        <Row label="類型">
          <RangeChips label="交易類型" value={f.mainType} options={MAIN_TYPES} onChange={(v) => set({ mainType: v })} />
          {f.mainType === "other" && (
            <Select
              value={f.otherType}
              onValueChange={(v) => set({ otherType: v as TransactionType })}
              items={OTHER_TYPES.map((t) => ({ value: t, label: TYPE_LABEL[t] }))}
            >
              <SelectTrigger className="mt-2 w-40" aria-label="其他交易類型">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OTHER_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {TYPE_LABEL[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Row>

        <div className="grid gap-4 sm:grid-cols-2">
          <Row label="帳戶">
            <AccountSelect accounts={accounts.data ?? []} value={accountId} onChange={(id) => set({ accountId: id })} />
          </Row>
          <Row label="日期" htmlFor="trade-date">
            <Input id="trade-date" type="date" value={f.date} max={todayInTaipei()} onChange={(e) => set({ date: e.target.value })} />
          </Row>
        </div>

        {!isCash && (
          <Row label="股票" error={submitted ? errors.symbol : null}>
            <SymbolPicker value={f.symbol} onChange={(i) => set({ symbol: i })} invalid={submitted && !!errors.symbol} />
          </Row>
        )}

        {isCash ? (
          <Row label={`金額（${account?.currency === "USD" ? "美元" : "新台幣"}）`} htmlFor="trade-amount" error={submitted ? errors.amount : null}>
            <Input id="trade-amount" inputMode="decimal" enterKeyHint="done" value={f.amountText} onChange={(e) => set({ amountText: e.target.value })} placeholder="例如 100000" aria-invalid={submitted && !!errors.amount} />
          </Row>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <Row
              label={type === "split" ? "每 1 股變成幾股" : type === "capital_reduction" ? "每 1 股減少幾股" : type === "cash_dividend" || type === "stock_dividend" ? "除息日持有股數" : "數量"}
              htmlFor="trade-qty"
              error={submitted ? errors.qty : null}
              hint={unitHint && f.qtyUnit === "lot" ? `= ${formatNumberSafe(shares)} 股` : unitHint ?? undefined}
            >
              <div className="flex gap-2">
                <Input
                  id="trade-qty"
                  inputMode="decimal"
                  enterKeyHint="next"
                  value={f.qtyText}
                  onChange={(e) => set({ qtyText: e.target.value })}
                  placeholder={f.qtyUnit === "lot" && !isUS ? "例如 1" : "例如 1000"}
                  aria-invalid={submitted && !!errors.qty}
                />
                {!isUS && (type === "buy" || type === "sell") && (
                  <RangeChips
                    label="數量單位"
                    value={f.qtyUnit}
                    options={[{ value: "lot", label: "張" }, { value: "share", label: "股" }]}
                    onChange={(v) => set({ qtyUnit: v })}
                    className="shrink-0 rounded-md border px-0.5"
                  />
                )}
              </div>
            </Row>
            {type !== "split" && type !== "capital_reduction" && (
              <Row
                label={type === "cash_dividend" ? "每股現金股利（元）" : type === "stock_dividend" ? "每股股票股利（元）" : `成交價（${isUS ? "美元" : "元"}）`}
                htmlFor="trade-price"
                error={submitted ? errors.price : null}
              >
                <Input id="trade-price" inputMode="decimal" enterKeyHint="done" value={f.priceText} onChange={(e) => set({ priceText: e.target.value })} placeholder={isUS ? "例如 268.42" : "例如 1085"} aria-invalid={submitted && !!errors.price} />
              </Row>
            )}
          </div>
        )}

        {type === "sell" && !isUS && (
          <label className="inline-flex cursor-pointer items-center gap-2 text-md select-none">
            <input type="checkbox" className="size-4 accent-[var(--primary)]" checked={f.dayTrade} onChange={(e) => set({ dayTrade: e.target.checked })} />
            這筆是當沖（證交稅 0.15%）
          </label>
        )}

        <Row label="備註（選填）" htmlFor="trade-note">
          <Input id="trade-note" value={f.note} maxLength={200} onChange={(e) => set({ note: e.target.value })} placeholder="例如：定期定額、加碼" />
        </Row>
      </div>

      <aside
        aria-label="稅費試算"
        aria-live="polite"
        className={cn("flex flex-col gap-3 bg-muted/60 px-4 py-4 sm:px-6", layout === "split" ? "border-l" : "border-t")}
      >
        <div className="flex items-center gap-2">
          <h3 className="text-md font-semibold">稅費試算</h3>
          <Chop tone="muted">預估</Chop>
        </div>
        <PreviewBody preview={preview.data} loading={preview.isFetching && !preview.data} ready={!!debounced} currency={account?.currency ?? "TWD"} type={type} />
        <div className="mt-auto flex gap-2 pt-2">
          <Button type="button" variant="outline" className="flex-1" onClick={onDone}>
            取消
          </Button>
          <Button type="submit" className="flex-1" disabled={create.isPending}>
            {create.isPending ? "儲存中…" : "儲存"}
          </Button>
        </div>
      </aside>
    </form>
  )
}

function formatNumberSafe(n: number | null) {
  return n === null ? "" : new Intl.NumberFormat("zh-TW").format(n)
}

function PreviewBody({ preview, loading, ready, currency, type }: { preview?: TradePreview; loading: boolean; ready: boolean; currency: "TWD" | "USD"; type: TransactionType }) {
  if (!ready) return <p className="text-md text-muted-foreground">填完數量與價格後，會自動試算手續費、證交稅與實際收付金額。</p>
  if (loading || !preview) return <div className="flex flex-col gap-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /><Skeleton className="h-4 w-3/5" /></div>
  const rows: [string, number][] = [
    [type === "cash_dividend" ? "股利金額" : "成交金額", preview.gross],
    ["手續費", preview.fee],
    ["證交稅", preview.tax],
    ...(preview.health_insurance ? ([["二代健保", preview.health_insurance]] as [string, number][]) : []),
  ]
  return (
    <div className="flex flex-col gap-3">
      <dl className="flex flex-col gap-1.5 text-md">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="num">{formatMoney(v, { currency })}</dd>
          </div>
        ))}
        <div className="mt-1 flex items-baseline justify-between gap-3 border-t pt-2">
          <dt className="font-medium">{preview.net_cash < 0 ? "應付" : "實收"}</dt>
          <dd className="num text-lg font-semibold">{formatMoney(Math.abs(preview.net_cash), { currency })}</dd>
        </div>
      </dl>
      {preview.rules.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-sm text-muted-foreground">
          {preview.rules.map((r) => (
            <li key={r}>・{r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Sonner 通知裡的「已入帳」章：儲存成功時蓋下 */
function StampLine() {
  return (
    <span className="mt-1 inline-flex items-center gap-2 text-sm">
      <Chop press>已入帳</Chop>
      <span className="text-muted-foreground">持股與績效已更新</span>
    </span>
  )
}


function AccountSelect({ accounts, value, onChange }: { accounts: Account[]; value: string; onChange: (id: string) => void }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as string)} items={accounts.map((a) => ({ value: a.id, label: a.name }))}>
      <SelectTrigger className="w-full" aria-label="券商帳戶">
        <SelectValue placeholder="選擇帳戶" />
      </SelectTrigger>
      <SelectContent>
        {accounts.map((a) => (
          <SelectItem key={a.id} value={a.id}>
            {a.name}
            <span className="text-xs text-muted-foreground">{a.currency === "USD" ? "美元" : "新台幣"}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** 代號搜尋（cmdk，支援中文股名） */
function SymbolPicker({ value, onChange, invalid }: { value: Instrument | null; onChange: (i: Instrument | null) => void; invalid?: boolean }) {
  const [q, setQ] = useState("")
  const search = useInstrumentSearch(q)
  const listId = useId()
  if (value) {
    return (
      <div className="flex h-10 items-center gap-2 rounded-md border border-input bg-card px-3">
        <span className="num font-semibold">{value.code}</span>
        <span className="min-w-0 flex-1 truncate">{value.name}</span>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="改選其他股票" onClick={() => onChange(null)}>
          <XIcon />
        </Button>
      </div>
    )
  }
  const results = search.data ?? []
  return (
    <CommandPrimitive shouldFilter={false} label="搜尋股票" className="relative">
      <CommandPrimitive.Input
        value={q}
        onValueChange={setQ}
        placeholder="代號或名稱，例如 2330、台積"
        aria-invalid={invalid}
        aria-controls={listId}
        className={cn(
          "h-10 w-full rounded-md border border-input bg-card px-3 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-md pointer-coarse:text-base",
          invalid && "border-destructive",
        )}
        autoComplete="off"
        enterKeyHint="search"
      />
      {q.trim() && (
        <CommandPrimitive.List id={listId} className="mt-1 max-h-56 overflow-y-auto rounded-md border bg-popover p-1 shadow-md">
          {!search.isFetching && results.length === 0 && (
            <CommandPrimitive.Empty className="px-2 py-3 text-md text-muted-foreground">找不到「{q.trim()}」</CommandPrimitive.Empty>
          )}
          {results.map((i) => (
            <CommandPrimitive.Item
              key={i.symbol}
              value={i.symbol}
              onSelect={() => {
                onChange(i)
                setQ("")
              }}
              className="flex min-h-10 cursor-pointer items-center gap-3 rounded-sm px-2 text-md data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
            >
              <span className="num w-14 shrink-0 font-semibold">{i.code}</span>
              <span className="min-w-0 flex-1 truncate">{i.name}</span>
              <span className="text-xs text-muted-foreground">{i.market === "US" ? "美股" : i.market === "TPEX" ? "上櫃" : "上市"}</span>
            </CommandPrimitive.Item>
          ))}
        </CommandPrimitive.List>
      )}
    </CommandPrimitive>
  )
}
