import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Command as CommandPrimitive } from "cmdk"
import { SearchIcon, XIcon } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { useAccounts, useCreateTransaction, useDeleteTransaction, useHoldings, useInstrumentSearch, useQuote, useWatchlist } from "@/api/queries"
import type { Account, Holding, Instrument, Market, TransactionInput } from "@/api/types"
import type { TradePrefill } from "@/app/ui-store"
import { DateField } from "@/components/date-field"
import { Pct, Price } from "@/components/finance"
import { FieldError, FormField as Row } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { defaultAccount } from "@/lib/default-account"
import { formatDateShort, formatPrice, formatQuantity } from "@/lib/format"
import { marketTag } from "@/lib/labels"
import { marketOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { otherUnit, parseNumber as num, quantityError, toShares } from "./quantity-input"
import { AccountSelect, StampLine } from "./TradeForm"

/**
 * 記一筆（預設的輸入方式；產品負責人 2026-11-14 第二次：照 Google 財經新增持有資產的做法，分兩步）：
 * ① 選股票：搜尋框，沒打字時列出持有的與觀察清單（現價、漲跌），一打字換成搜尋結果；這一步「新增」不能按。
 * ② 選好的股票（現價、漲跌、✕ 回到第一步）→ 每一筆的股數、買進日期（月曆，一開始空白、一定要選）、買進價格。
 *    選了日期，價格下面寫「那天收盤 1,085」，點一下才填進去（只用自己存檔的官方收盤，Yahoo 回補的日線不進帳本）。
 *    同一檔分好幾次買的，按「再加一筆買進」多一列（日期一樣空白）。
 * 沒有類型、備註與手續費：手續費與稅不自動算（2026-11-14），填的價格就是成本；賣出、股利與其他類型走完整表單。
 * 「只記持股」的帳戶取消了（2026-11-14）：每一筆買進都有日期。
 */
interface Lot {
  id: number
  qty: string
  date: string
  price: string
}

const MAX_LOTS = 12
const newLot = (id: number): Lot => ({ id, qty: "", date: "", price: "" })

export function QuickAdd({
  initialSymbol,
  initialAccountId,
  onDone,
  onFull,
  sheet = false,
}: {
  /** 從個股頁、持倉的「加碼」打開：直接到第二步 */
  initialSymbol?: string
  /** 先選好的帳戶 */
  initialAccountId?: string
  onDone: () => void
  onFull: (symbol?: string, prefill?: TradePrefill) => void
  sheet?: boolean
}) {
  const accounts = useAccounts()
  const holdings = useHoldings()
  const [symbol, setSymbol] = useState<Instrument | null>(null)
  const [opening, setOpening] = useState(!!initialSymbol)
  const [accountId, setAccountId] = useState(initialAccountId ?? "")
  /** 從第二步按 ✕ 回來：焦點放回搜尋框 */
  const [returned, setReturned] = useState(false)

  useEffect(() => {
    if (!initialSymbol) return
    let alive = true
    void api
      .getInstrument(initialSymbol)
      .then((i) => alive && setSymbol((s) => s ?? i))
      .catch(() => undefined)
      .finally(() => alive && setOpening(false))
    return () => {
      alive = false
    }
  }, [initialSymbol])

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
  // 帳戶沒動過時跟著股票走：這一檔持有的帳戶 → 同幣別 → 第一個（Apple 不會記進新台幣帳戶）
  const account = accounts.data?.find((a) => a.id === accountId) ?? defaultAccount(accounts.data, symbol, holdings.data)

  if (opening) return <OpeningSkeleton sheet={sheet} />
  if (!symbol) return <PickStep autoFocus onPick={setSymbol} onDone={onDone} onFull={() => onFull(undefined, { accountId: account?.id })} sheet={sheet} refocus={returned} />
  return (
    <DetailsStep
      key={symbol.symbol}
      symbol={symbol}
      accounts={accounts.data ?? []}
      account={account}
      onAccountChange={setAccountId}
      onClear={() => {
        setSymbol(null)
        setReturned(true)
      }}
      onDone={onDone}
      onFull={onFull}
      sheet={sheet}
    />
  )
}

// ── 第一步：選股票 ─────────────────────────────────────────

interface Choice {
  symbol: string
  code: string
  name: string
  market: Market
  tag: string
  price: number | null
  pct: number | null
  /** 持倉列已經是商品資料；觀察清單只有代號與名稱，選了才去讀 */
  instrument?: Instrument
}

const fromHolding = (h: Holding): Instrument => ({ symbol: h.symbol, code: h.code, name: h.name, market: h.market, type: h.type, currency: h.currency, industry: null })

function PickStep({
  onPick,
  onDone,
  onFull,
  sheet,
  autoFocus,
  refocus,
}: {
  onPick: (i: Instrument) => void
  onDone: () => void
  onFull: () => void
  sheet: boolean
  autoFocus?: boolean
  refocus?: boolean
}) {
  const [q, setQ] = useState("")
  const [active, setActive] = useState("")
  const [loading, setLoading] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const query = q.trim()
  const holdings = useHoldings()
  const watch = useWatchlist()
  const search = useInstrumentSearch(q)
  const results = query ? (search.data ?? []) : []
  const quoted = results.filter((i) => i.has_quote !== false).map((i) => i.symbol)
  const quotes = useQuery({
    enabled: quoted.length > 0,
    queryKey: ["quotes", quoted.join(",")],
    queryFn: () => api.getQuotes(quoted),
    staleTime: 60_000,
    retry: false,
  })

  // 打開時（從第二步回來時也是）焦點在搜尋框；等對話框或抽屜的動畫開始，iOS 才會叫出鍵盤
  useEffect(() => {
    if (!autoFocus && !refocus) return
    const t = window.setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 80)
    return () => window.clearTimeout(t)
  }, [autoFocus, refocus])

  const held = new Map<string, Holding>()
  for (const h of holdings.data ?? []) if (!held.has(h.symbol)) held.set(h.symbol, h)
  const heldChoices: Choice[] = [...held.values()].map((h) => ({
    symbol: h.symbol, code: h.code, name: h.name, market: h.market, tag: marketTag(h), price: h.price, pct: h.day_change_pct, instrument: fromHolding(h),
  }))
  const watchChoices: Choice[] = (watch.data ?? [])
    .filter((w) => !held.has(w.symbol))
    .map((w) => {
      const market = marketOf(w.symbol)
      return { symbol: w.symbol, code: w.symbol, name: w.name, market, tag: marketTag({ market }), price: w.quote?.price ?? null, pct: w.quote?.change_pct ?? null }
    })
  const quoteOf = new Map((quotes.data ?? []).map((x) => [x.symbol, x]))
  const resultChoices: Choice[] = results.map((i) => ({
    symbol: i.symbol, code: i.code, name: i.name, market: i.market, tag: marketTag(i), price: quoteOf.get(i.symbol)?.price ?? null, pct: quoteOf.get(i.symbol)?.change_pct ?? null, instrument: i,
  }))
  const groups: { heading: string; items: Choice[] }[] = query
    ? [{ heading: "搜尋結果", items: resultChoices }]
    : [
        { heading: "持有的", items: heldChoices },
        { heading: "觀察清單", items: watchChoices },
      ].filter((g) => g.items.length > 0)
  const all = groups.flatMap((g) => g.items)
  // 非同步的清單：選取不在清單裡時改選第一個，打完代號直接按 Enter 就能選；
  // 還在查新的字時清單是上一次的結果，不預先選取（Enter 不會選到上一次的第一檔）
  const stale = !!query && search.isPlaceholderData
  const selected = stale ? "" : all.some((c) => c.symbol === active) ? active : (all[0]?.symbol ?? "")

  const choose = async (c: Choice) => {
    if (c.instrument) return onPick(c.instrument)
    setLoading(c.symbol)
    try {
      onPick(await api.getInstrument(c.symbol))
    } catch {
      toast.error(`讀不到 ${c.name} 的資料，再試一次。`)
      setLoading(null)
    }
  }

  return (
    <div className={cn("flex flex-col px-4 sm:px-6", !sheet && "pb-4 sm:pb-6")}>
      <CommandPrimitive shouldFilter={false} value={selected} onValueChange={setActive} label="選一檔股票" className="flex flex-col">
        <div className="relative">
          <SearchIcon aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-2" />
          <CommandPrimitive.Input
            ref={inputRef}
            value={q}
            onValueChange={setQ}
            placeholder="代號或名稱，例如 2330、台積"
            aria-controls={listId}
            autoComplete="off"
            enterKeyHint="search"
            className="h-11 w-full rounded-sm border border-input bg-raised pr-3 pl-9 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-md pointer-coarse:text-[1rem]"
          />
        </div>
        <CommandPrimitive.List
          id={listId}
          className={cn(
            "mt-2 overscroll-contain",
            !sheet && "h-[min(20rem,calc(100dvh-20rem))] overflow-y-auto",
            "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-sm [&_[cmdk-group-heading]]:text-ink-2",
          )}
        >
          {query && !search.isFetching && results.length === 0 && (
            <CommandPrimitive.Empty className="px-2 py-4 text-base text-ink">找不到「{query}」。試試代號，或公司名稱的前兩個字。</CommandPrimitive.Empty>
          )}
          {groups.map((g) => (
            <CommandPrimitive.Group key={g.heading} heading={g.heading}>
              {g.items.map((c) => (
                <CommandPrimitive.Item
                  key={c.symbol}
                  value={c.symbol}
                  disabled={loading !== null}
                  onSelect={() => void choose(c)}
                  className="flex min-h-12 cursor-pointer items-center gap-3 rounded-sm px-2 py-1.5 data-[disabled=true]:cursor-wait data-[selected=true]:bg-hov pointer-coarse:min-h-14"
                >
                  <span className="num w-14 shrink-0 font-semibold">{c.code}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{c.name}</span>
                    <span className="block text-xs text-ink-2">{loading === c.symbol ? "讀取中…" : c.tag}</span>
                  </span>
                  {c.price !== null && (
                    <span className="flex shrink-0 flex-col items-end">
                      <Price value={c.price} market={c.market} className="text-md" />
                      {c.pct !== null && <Pct value={c.pct} className="text-sm" />}
                    </span>
                  )}
                </CommandPrimitive.Item>
              ))}
            </CommandPrimitive.Group>
          ))}
        </CommandPrimitive.List>
      </CommandPrimitive>
      <Footer sheet={sheet} onCancel={onDone} toFull={<ToFull onClick={onFull} />} />
    </div>
  )
}

// ── 第二步：股數、買進日期、買進價格 ───────────────────────────

function DetailsStep({
  symbol,
  accounts,
  account,
  onAccountChange,
  onClear,
  onDone,
  onFull,
  sheet,
}: {
  symbol: Instrument
  accounts: Account[]
  account: Account | undefined
  onAccountChange: (id: string) => void
  onClear: () => void
  onDone: () => void
  onFull: (symbol?: string, prefill?: TradePrefill) => void
  sheet: boolean
}) {
  const create = useCreateTransaction()
  const remove = useDeleteTransaction()
  const unitPref = usePrefs((s) => s.quantityUnit)
  const quote = useQuote(symbol.symbol, symbol.has_quote !== false)
  const nextId = useRef(1)
  const formRef = useRef<HTMLFormElement>(null)
  const [lots, setLots] = useState<Lot[]>(() => [newLot(0)])
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)
  const isUS = symbol.market === "US" || account?.currency === "USD"
  const inLots = unitPref === "lot" && !isUS
  const today = appToday()
  const shares = (l: Lot) => toShares(l.qty, inLots)
  const errorOf = (l: Lot) => {
    const p = num(l.price)
    return {
      qty: quantityError(l.qty, inLots, isUS),
      date: !l.date ? "請選買進日期" : l.date > today ? "不能選未來的日期" : null,
      price: !p || p <= 0 ? "請輸入價格" : null,
    }
  }
  const invalid = !account || lots.some((l) => Object.values(errorOf(l)).some(Boolean))
  const setLot = (id: number, patch: Partial<Lot>) => setLots((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)))

  // 選好股票時焦點放在第一筆的股數
  useEffect(() => {
    const t = window.setTimeout(() => formRef.current?.querySelector<HTMLInputElement>("#lot-qty-0")?.focus({ preventScroll: true }), 80)
    return () => window.clearTimeout(t)
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (invalid || !account) {
      // 焦點移到第一個有錯的欄位
      const first = lots.find((l) => Object.values(errorOf(l)).some(Boolean))
      if (first) {
        const err = errorOf(first)
        const id = err.qty ? `lot-qty-${first.id}` : err.date ? `lot-date-${first.id}` : `lot-price-${first.id}`
        document.getElementById(id)?.focus()
      }
      return
    }
    setBusy(true)
    const created: string[] = []
    let total = 0
    try {
      for (const l of lots) {
        const body: TransactionInput = { account_id: account.id, symbol: symbol.symbol, type: "buy", trade_date: l.date, quantity: shares(l), price: num(l.price), note: "" }
        // 走 useCreateTransaction：存好之後持股、總資產、交易清單會重抓
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
    setLots((ls) => [...ls, newLot(id)])
    setSubmitted(false)
    requestAnimationFrame(() => formRef.current?.querySelector<HTMLInputElement>(`#lot-qty-${id}`)?.focus())
  }

  const qtyLabel = inLots ? "張數" : "股數"
  const priceLabel = `買進價格${isUS ? "（美元）" : ""}`
  const q = quote.data
  return (
    <form ref={formRef} onSubmit={(e) => void submit(e)} noValidate className={cn("flex flex-col gap-4 px-4 sm:px-6", !sheet && "pb-4 sm:pb-6")}>
      {/* 選好的股票：和搜尋框同一個位置；✕ 回到第一步 */}
      <div role="group" aria-label="選好的股票" className="flex min-h-14 items-center gap-3 rounded-sm border border-input bg-raised py-2 pr-1.5 pl-3">
        <div className="min-w-0 flex-1">
          <p className="flex min-w-0 items-baseline gap-2">
            <span className="num shrink-0 font-semibold">{symbol.code}</span>
            <span className="truncate">{symbol.name}</span>
          </p>
          <p className="num text-xs text-ink-2">
            {marketTag(symbol)}
            {q?.as_of ? `・${formatDateShort(q.as_of, false)} 收盤` : ""}
          </p>
        </div>
        {q && (
          <span className="flex shrink-0 flex-col items-end">
            <Price value={q.price} market={symbol.market} className="text-md font-medium" />
            {q.change_pct !== null && <Pct value={q.change_pct} className="text-sm" />}
          </span>
        )}
        <Button type="button" variant="ghost" size="icon" aria-label="改選其他股票" onClick={onClear} className="shrink-0">
          <XIcon aria-hidden />
        </Button>
      </div>

      {accounts.length > 1 && (
        <Row label="帳戶" className="sm:max-w-xs">
          <AccountSelect accounts={accounts} value={account?.id ?? ""} onChange={onAccountChange} />
        </Row>
      )}

      <div className="flex flex-col gap-3">
        {lots.map((l, i) => {
          const err = submitted ? errorOf(l) : { qty: null, date: null, price: null }
          const nth = lots.length > 1 ? `第 ${i + 1} 筆的` : ""
          const first = i === 0
          return (
            // 手機一筆排兩行：股數｜價格，下面是日期（有好幾筆時右邊是移除）；第二筆起上面加一條格線分開
            <div
              key={l.id}
              className={cn(
                "grid grid-cols-2 items-start gap-x-2 gap-y-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)_auto]",
                i > 0 && "max-sm:border-t max-sm:border-rule max-sm:pt-3",
              )}
            >
              <Cell label={qtyLabel} id={`lot-qty-${l.id}`} first={first} error={err.qty} note={otherUnit(shares(l), inLots, isUS)}>
                <Input
                  id={`lot-qty-${l.id}`}
                  inputMode="decimal"
                  autoComplete="off"
                  aria-label={`${nth}${qtyLabel}`}
                  // 第二筆起沒有看得見的標籤：提示字直接寫欄位名稱
                  placeholder={first ? (inLots ? "例如 1" : "例如 1000") : qtyLabel}
                  value={l.qty}
                  onChange={(e) => setLot(l.id, { qty: e.target.value })}
                  aria-invalid={!!err.qty}
                  className="num"
                />
              </Cell>
              <Cell label="買進日期" id={`lot-date-${l.id}`} first={first} error={err.date} className={cn("max-sm:order-3", lots.length === 1 && "max-sm:col-span-2")}>
                <DateField id={`lot-date-${l.id}`} label={`${nth}買進日期`} value={l.date} onChange={(date) => setLot(l.id, { date })} invalid={!!err.date} />
              </Cell>
              <Cell
                label={priceLabel}
                id={`lot-price-${l.id}`}
                first={first}
                error={err.price}
                extra={l.date && <CloseHint instrument={symbol} date={l.date} price={l.price} onFill={(price) => setLot(l.id, { price })} />}
              >
                <Input
                  id={`lot-price-${l.id}`}
                  inputMode="decimal"
                  autoComplete="off"
                  enterKeyHint="done"
                  aria-label={`${nth}買進價格`}
                  placeholder={first ? "每股價格" : "價格"}
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
                  className={cn("max-sm:order-4 max-sm:self-end max-sm:justify-self-end", first && "sm:mt-[1.625rem]")}
                  onClick={() => setLots((ls) => ls.filter((x) => x.id !== l.id))}
                >
                  <XIcon aria-hidden />
                </Button>
              )}
            </div>
          )
        })}
      </div>

      {lots.length < MAX_LOTS && (
        <button type="button" onClick={addLot} className={cn(textAction, "self-start text-base")}>
          再加一筆買進
        </button>
      )}

      <Footer
        sheet={sheet}
        onCancel={onDone}
        busy={busy}
        canSubmit
        toFull={
          <ToFull
            onClick={() => {
              // 完整表單：帳戶與第一筆已經填的數量、價格、日期一起帶過去
              const l = lots[0]
              onFull(symbol.code, { accountId: account?.id, quantity: (l && shares(l)) || undefined, price: (l && num(l.price)) || undefined, date: l?.date || undefined })
            }}
          />
        }
      />
    </form>
  )
}

/**
 * 選了日期之後價格欄下面的「11/12 收盤 1,085」：點一下填進價格（實際成交價常常不同，所以不自動填）。
 * 只用自己存檔的官方收盤；那天沒有（假日、存檔開始以前、沒有報價來源）就不顯示。
 */
function CloseHint({ instrument, date, price, onFill }: { instrument: Instrument; date: string; price: string; onFill: (price: string) => void }) {
  const q = useQuery({
    enabled: instrument.has_quote !== false,
    queryKey: ["daily-close", instrument.symbol, date],
    queryFn: () => api.getDailyClose(instrument.symbol, date),
    staleTime: Infinity,
    retry: false,
  })
  const close = q.data?.close
  if (close === null || close === undefined) return null
  const text = formatPrice(close, instrument.market, instrument.type)
  const label = `${formatDateShort(date, false)} 收盤 ${text}`
  if (num(price) === close) return <p className="num text-sm text-ink-2">{label}</p>
  return (
    <button type="button" onClick={() => onFill(String(close))} aria-label={`用 ${label} 填入價格`} className={cn(textAction, "num self-start text-sm text-ink-2 hover:text-ink")}>
      {label}
    </button>
  )
}

/** 一筆買進裡的一格：第一筆才有看得見的標籤（其他筆的名字在輸入框的 aria-label） */
function Cell({
  label,
  id,
  first,
  error,
  note,
  extra,
  className,
  children,
}: {
  label: string
  id: string
  first: boolean
  error?: string | null
  note?: string | null
  extra?: React.ReactNode
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      {first && (
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
      )}
      {children}
      {error ? <FieldError>{error}</FieldError> : note ? <p className="num text-sm text-ink-2">{note}</p> : null}
      {extra}
    </div>
  )
}

function ToFull({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex min-h-9 items-center text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink pointer-coarse:min-h-11"
    >
      賣出、股利或其他
    </button>
  )
}

/** 動作列：第一步的「新增」不能按（還沒選股票）。手機抽屜裡貼在捲動區底部（一條格線，不加陰影） */
function Footer({ sheet, onCancel, toFull, canSubmit = false, busy = false }: { sheet: boolean; onCancel: () => void; toFull: React.ReactNode; canSubmit?: boolean; busy?: boolean }) {
  return (
    <div className={cn("mt-4 flex flex-wrap items-center gap-x-4 gap-y-2", sheet && "safe-bottom sticky bottom-0 z-10 -mx-4 border-t border-rule bg-popover px-4 py-3")}>
      {toFull}
      <div className={cn("ml-auto flex gap-2", sheet && "w-full")}>
        <Button type="button" variant="outline" className={cn(sheet ? "flex-1" : "min-w-24")} onClick={onCancel}>
          取消
        </Button>
        <Button type={canSubmit ? "submit" : "button"} variant="sign" className={cn(sheet ? "flex-1" : "min-w-28")} disabled={!canSubmit || busy}>
          {busy ? "新增中…" : "新增"}
        </Button>
      </div>
    </div>
  )
}

function OpeningSkeleton({ sheet }: { sheet: boolean }) {
  return (
    <div className={cn("flex flex-col gap-4 px-4 sm:px-6", !sheet && "pb-4 sm:pb-6")} aria-busy="true">
      <Skeleton className="h-14 w-full" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
    </div>
  )
}
