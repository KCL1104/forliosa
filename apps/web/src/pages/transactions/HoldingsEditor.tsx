import { useQuery } from "@tanstack/react-query"
import { XIcon } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { qk, usePutHoldings } from "@/api/queries"
import type { Account, HoldingsSnapshot, Instrument } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { ErrorState, SkeletonLines } from "@/components/states"
import { SymbolPicker } from "@/components/symbol-picker"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { otherUnit, parseNumber, quantityError, sharesText, toShares } from "./quantity-input"
import { StampLine } from "./TradeForm"

/**
 * 只記持股的帳戶：一次填好目前的持股（產品負責人 2026-11-14 決定 2-1，畫面照「記一筆」）。
 * 一列一檔：股票、張數（或股數）、均價；「再加一檔」多一列；「存成持股」以快照覆蓋（`PUT /accounts/{id}/holdings`）。
 * 打開時帶入這個帳戶現在的持股，可以改股數、均價或移除一列。存好之後的通知附「復原」（把原本的快照存回去）。
 *
 * 快照日：股數或股票有變就是今天（快照日當天以前的交易不算、自動入帳的股利從隔天起）；只改均價時沿用原本的日期，
 * 已經入帳的股利不受影響。快照之後帳上又有變動（減少持股、配股）時，帶入的是現在的持股，不是舊的快照。
 */
interface Line {
  id: number
  instrument: Instrument | null
  qty: string
  cost: string
}

type Position = HoldingsSnapshot["holdings"][number]

interface Current {
  snapshot: HoldingsSnapshot
  /** 帶入的那幾列（快照，或快照之後有變動時是現在的持股）；從某一檔進來而那一檔還沒有時，最後多一列沒有數字的 */
  lines: { instrument: Instrument; quantity: number | null; avg_cost: number | null }[]
  /** 帶入的就是快照本身（沒有之後的變動） */
  fromSnapshot: boolean
}

const MAX_LINES = 200
/** 新增的列從這裡編號（帶入的列是 0、1、2…） */
const FIRST_NEW_ID = 10_000
const key = (p: Position) => `${p.symbol}|${p.quantity}`
const sameSet = (a: string[], b: string[]) => a.length === b.length && [...a].sort().join("\n") === [...b].sort().join("\n")
const round2 = (n: number) => Math.round(n * 100) / 100

async function loadCurrent(account: Account, initialSymbol?: string): Promise<Current> {
  const [snapshot, holdings] = await Promise.all([api.getAccountHoldings(account.id), api.getHoldings(account.id)])
  const held = new Map(holdings.map((h) => [h.symbol, h]))
  const fromSnapshot = holdings.length === snapshot.holdings.length && snapshot.holdings.every((s) => held.get(s.symbol)?.quantity === s.quantity)
  const lines: Current["lines"] = fromSnapshot
    ? snapshot.holdings.map((s) => ({ instrument: held.get(s.symbol)!, quantity: s.quantity, avg_cost: s.avg_cost }))
    : holdings.map((h) => ({ instrument: h, quantity: h.quantity, avg_cost: round2(h.avg_cost) }))
  // 從個股頁、持倉的「加碼」進來的那一檔還沒有：多一列、選好
  if (initialSymbol && !lines.some((l) => l.instrument.code === initialSymbol || l.instrument.symbol === initialSymbol)) {
    const i = await api.getInstrument(initialSymbol).catch(() => null)
    if (i && i.currency === account.currency) lines.push({ instrument: i, quantity: null, avg_cost: null })
  }
  return { snapshot, lines, fromSnapshot }
}

export function HoldingsEditor({
  account,
  accountField,
  initialSymbol,
  onDone,
  sheet = false,
}: {
  account: Account
  /** 帳戶選單（有好幾個帳戶時；換成逐筆交易的帳戶就回到記買進） */
  accountField?: React.ReactNode
  initialSymbol?: string
  onDone: () => void
  sheet?: boolean
}) {
  const unitPref = usePrefs((s) => s.quantityUnit)
  const put = usePutHoldings()
  const current = useQuery({
    queryKey: [...qk.snapshot(account.id), "editor", initialSymbol ?? ""],
    queryFn: () => loadCurrent(account, initialSymbol),
    staleTime: 0,
    gcTime: 0,
  })
  const nextId = useRef(FIRST_NEW_ID)
  const formRef = useRef<HTMLFormElement>(null)
  const [submitted, setSubmitted] = useState(false)
  const isUS = account.currency === "USD"
  const inLots = unitPref === "lot" && !isUS
  const lotsOf = (l: Line) => inLots && l.instrument?.market !== "US"
  const qtyLabel = inLots ? "張數" : "股數"

  // 讀到的持股就是一開始的每一列；動過之後換成 `edited`
  const initial = useMemo((): Line[] | null => {
    if (!current.data) return null
    const rows = current.data.lines.map((l, id): Line => {
      const lots = inLots && l.instrument.market !== "US"
      return { id, instrument: l.instrument, qty: l.quantity ? sharesText(l.quantity, lots) : "", cost: l.avg_cost === null ? "" : String(l.avg_cost) }
    })
    return rows.length ? rows : [{ id: 0, instrument: null, qty: "", cost: "" }]
  }, [current.data, inLots])
  const [edited, setEdited] = useState<Line[] | null>(null)
  const lines = edited ?? initial

  // 從某一檔進來時焦點在那一檔的數量；沒有任何持股時在股票搜尋；其他時候不搶焦點（手機不會一打開就跳出鍵盤）
  useEffect(() => {
    if (!initial) return
    const focusOn = initialSymbol ? initial.find((l) => l.instrument?.code === initialSymbol || l.instrument?.symbol === initialSymbol) : undefined
    const t = window.setTimeout(() => {
      const form = formRef.current
      const target = focusOn ? form?.querySelector<HTMLInputElement>(`#hold-qty-${focusOn.id}`) : !initial[0]?.instrument ? form?.querySelector<HTMLInputElement>("[cmdk-input]") : null
      target?.focus({ preventScroll: !focusOn })
    }, 80)
    return () => window.clearTimeout(t)
  }, [initial, initialSymbol])

  if (current.isError) {
    return (
      <div className="flex flex-col gap-4 px-4 pb-6 sm:px-6">
        {accountField}
        <ErrorState flush title="持股沒有讀到" error={current.error} onRetry={() => void current.refetch()} />
      </div>
    )
  }
  if (!lines || !current.data) {
    return (
      <div className="flex flex-col gap-4 px-4 pb-6 sm:px-6">
        {accountField}
        <SkeletonLines rows={3} className="py-2" />
      </div>
    )
  }

  const { snapshot, fromSnapshot } = current.data
  const isEmpty = (l: Line) => !l.instrument && !l.qty.trim() && !l.cost.trim()
  const filled = lines.filter((l) => !isEmpty(l))
  // 一列都沒填、本來也沒有持股：第一列要選股票（本來有持股的話，全部移除就是清空）
  const nothing = filled.length === 0 && snapshot.holdings.length === 0
  const errorOf = (l: Line, i: number) => {
    if (isEmpty(l)) return { stock: nothing && i === 0 ? "請選擇股票或 ETF" : null, qty: null, cost: null }
    const c = parseNumber(l.cost)
    return {
      stock: l.instrument ? null : "請選擇股票或 ETF",
      qty: quantityError(l.qty, lotsOf(l), l.instrument?.market === "US" || isUS),
      cost: c === null || c < 0 ? "請輸入均價" : null,
    }
  }
  const invalid = lines.some((l, i) => Object.values(errorOf(l, i)).some(Boolean))
  const update = (fn: (ls: Line[]) => Line[]) => setEdited((ls) => fn(ls ?? lines))
  const setLine = (id: number, patch: Partial<Line>) => update((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)))
  const taken = (except: number) => new Set(lines.filter((l) => l.id !== except && l.instrument).map((l) => l.instrument!.symbol))

  const addLine = () => {
    const id = nextId.current++
    update((ls) => [...ls, { id, instrument: null, qty: "", cost: "" }])
    setSubmitted(false)
    requestAnimationFrame(() => formRef.current?.querySelector<HTMLInputElement>(`[data-line="${id}"] [cmdk-input]`)?.focus())
  }
  const removeLine = (id: number) => {
    const blank = { id: nextId.current++, instrument: null, qty: "", cost: "" }
    update((ls) => {
      const rest = ls.filter((l) => l.id !== id)
      return rest.length ? rest : [blank]
    })
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (invalid) return
    const holdings: Position[] = filled.map((l) => ({ symbol: l.instrument!.symbol, quantity: toShares(l.qty, lotsOf(l))!, avg_cost: parseNumber(l.cost)! }))
    const before = snapshot.holdings
    const exact = (p: Position) => `${key(p)}|${p.avg_cost}`
    // 什麼都沒改：不用存
    if (fromSnapshot && sameSet(holdings.map(exact), before.map(exact))) {
      onDone()
      return
    }
    // 只改均價：沿用原本的快照日（股數沒變，已經入帳的股利不動）
    const asOf = fromSnapshot && snapshot.as_of && sameSet(holdings.map(key), before.map(key)) ? snapshot.as_of : appToday()
    try {
      await put.mutateAsync({ id: account.id, body: { as_of: asOf, holdings } })
    } catch (err) {
      toast.error("沒有存成功，內容還在。", { description: err instanceof Error ? err.message : undefined })
      return
    }
    toast.success(holdings.length ? `已存成持股：${holdings.length} 檔` : "已清空持股", {
      description: <StampLine />,
      action: {
        label: "復原",
        onClick: () =>
          void put.mutateAsync({ id: account.id, body: { as_of: snapshot.as_of ?? asOf, holdings: before } }).then(
            () => toast("已復原持股"),
            () => toast.error("沒有復原成功，持股維持剛才存的內容。"),
          ),
      },
    })
    onDone()
  }

  return (
    <form ref={formRef} onSubmit={(e) => void submit(e)} noValidate className={cn("flex flex-col gap-4 px-4 sm:px-6", sheet ? "pb-0" : "pb-4 sm:pb-6")}>
      {accountField}

      <div className="flex flex-col gap-3">
        {lines.map((l, i) => {
          const err = submitted ? errorOf(l, i) : { stock: null, qty: null, cost: null }
          const lots = lotsOf(l)
          const unit = lots ? "張數" : "股數"
          const who = l.instrument ? l.instrument.name : `第 ${i + 1} 檔`
          const first = i === 0
          const removable = lines.length > 1 || !isEmpty(l)
          return (
            // 桌面一檔一行（股票｜張數｜均價｜×）；手機兩行：股票（× 疊在這一行的右邊），下面張數｜均價；第二檔起上面一條格線
            <div
              key={l.id}
              data-line={l.id}
              className={cn(
                "grid grid-cols-2 items-start gap-x-2 gap-y-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_2.75rem]",
                i > 0 && "max-sm:border-t max-sm:border-rule max-sm:pt-3",
              )}
            >
              <div className={cn("col-span-2 col-start-1 row-start-1 flex min-w-0 flex-col gap-1.5 sm:col-span-1", removable && "max-sm:pr-12")}>
                {first && <span className="text-sm font-medium">股票</span>}
                {l.instrument ? (
                  <p className="flex h-10 min-w-0 items-center pointer-coarse:h-11">
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="truncate text-md font-medium">{l.instrument.name}</span>
                      <span className="num shrink-0 text-sm text-ink-2">{l.instrument.code}</span>
                    </span>
                  </p>
                ) : (
                  <SymbolPicker
                    value={null}
                    label={`${who}的股票`}
                    invalid={!!err.stock}
                    onChange={(inst) => setLine(l.id, { instrument: inst })}
                    accept={(inst) => inst.currency === account.currency && !taken(l.id).has(inst.symbol)}
                    rejectReason={(inst) => (inst.currency !== account.currency ? "幣別不同" : "已經在上面")}
                  />
                )}
                {err.stock && <FieldError>{err.stock}</FieldError>}
              </div>
              <Cell label={qtyLabel} id={`hold-qty-${l.id}`} first={first} error={err.qty} note={otherUnit(toShares(l.qty, lots), lots, !lots && l.instrument?.market === "US")}>
                <Input
                  id={`hold-qty-${l.id}`}
                  inputMode="decimal"
                  autoComplete="off"
                  aria-label={`${who}的${unit}`}
                  placeholder={first ? (lots ? "例如 1" : "例如 1000") : unit}
                  value={l.qty}
                  onChange={(e) => setLine(l.id, { qty: e.target.value })}
                  aria-invalid={!!err.qty}
                  className="num"
                />
              </Cell>
              <Cell label={`均價${isUS ? "（美元）" : ""}`} id={`hold-cost-${l.id}`} first={first} error={err.cost}>
                <Input
                  id={`hold-cost-${l.id}`}
                  inputMode="decimal"
                  autoComplete="off"
                  enterKeyHint="done"
                  aria-label={`${who}的均價`}
                  placeholder={first ? "每股均價" : "均價"}
                  value={l.cost}
                  onChange={(e) => setLine(l.id, { cost: e.target.value })}
                  aria-invalid={!!err.cost}
                  className="num"
                />
              </Cell>
              {/* 桌面：× 自己一欄；手機：疊在股票那一行的右邊。第一列有標籤，往下對齊輸入框 */}
              {removable && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`移除${who}`}
                  onClick={() => removeLine(l.id)}
                  className={cn("max-sm:col-start-2 max-sm:row-start-1 max-sm:justify-self-end", first && "mt-[1.625rem]")}
                >
                  <XIcon aria-hidden />
                </Button>
              )}
            </div>
          )
        })}
      </div>

      {lines.length < MAX_LINES && (
        <button type="button" onClick={addLine} className="inline-flex min-h-9 items-center self-start text-base underline decoration-ctl underline-offset-3 hover:decoration-ink pointer-coarse:min-h-11">
          再加一檔
        </button>
      )}

      {/* 動作列只有一行；手機抽屜貼在捲動區的底部（一條格線，不加陰影），持股多也看得到「存成持股」 */}
      <div className={cn("flex gap-2 pt-1", sheet ? "safe-bottom sticky bottom-0 z-10 -mx-4 border-t border-rule bg-popover px-4 py-3 sm:-mx-6 sm:px-6" : "justify-end")}>
        <Button type="button" variant="outline" className="max-sm:flex-1 sm:min-w-24" onClick={onDone}>
          取消
        </Button>
        <Button type="submit" variant="sign" className="max-sm:flex-1 sm:min-w-28" disabled={put.isPending}>
          {put.isPending ? "儲存中…" : "存成持股"}
        </Button>
      </div>
    </form>
  )
}

/** 一檔裡的一格：第一列才有看得見的標籤（其他列的名字在輸入框的 aria-label） */
function Cell({ label, id, first, error, note, children }: { label: string; id: string; first: boolean; error?: string | null; note?: string | null; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
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
