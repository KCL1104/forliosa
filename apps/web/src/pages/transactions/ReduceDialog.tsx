import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { useAccounts, useCreateTransaction, useDeleteTransaction, useHoldings, useQuote } from "@/api/queries"
import type { Holding } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { FieldError, FormField as Row } from "@/components/form-field"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsDesktop } from "@/hooks/use-media-query"
import { formatDateShort, formatPrice, formatQuantity } from "@/lib/format"
import { usePrefs } from "@/stores/prefs"
import { AccountSelect, StampLine } from "./TradeForm"

/**
 * 減少持股（產品負責人 2026-11-14：只需要記買進，賣出不用特別去記帳）。
 * 賣了之後在那一檔按「減少持股」或「全部賣出」：只填股數。日期是今天、價格用最新的收盤價，
 * 手續費與稅照帳戶的費率算——記成一筆賣出，所以已實現損益和績效照常算得出來。
 * 要指定日期或成交價，按「改日期或價格」到完整表單。
 */
const TITLE = "減少持股"
const DESCRIPTION = "填賣出的股數；用最新的收盤價記成一筆賣出。"

export function ReduceHost() {
  const { open, symbol, all } = useUi((s) => s.reduce)
  const close = useUi((s) => s.closeReduce)
  const isDesktop = useIsDesktop()
  // 「全部賣出」是最不可逆的一個：標題直接說（2026-11-14 第六次評分）
  const title = all ? "全部賣出" : TITLE
  const body = open && symbol ? <ReduceForm key={`${symbol}:${all ? "all" : "some"}`} symbol={symbol} all={!!all} onDone={close} /> : null
  if (isDesktop) {
    return (
      <Dialog open={open} onOpenChange={(o) => !o && close()}>
        <DialogContent className="gap-0 p-0 sm:max-w-[440px]">
          <DialogHeader className="px-6 pt-5 pb-4">
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="sr-only">{DESCRIPTION}</DialogDescription>
          </DialogHeader>
          {body}
        </DialogContent>
      </Dialog>
    )
  }
  return (
    <Drawer open={open} onOpenChange={(o) => !o && close()} repositionInputs={false}>
      <DrawerContent className="data-[vaul-drawer-direction=bottom]:max-h-[92dvh]">
        <DrawerHeader className="pb-2">
          <DrawerTitle>{title}</DrawerTitle>
          <DrawerDescription className="sr-only">{DESCRIPTION}</DrawerDescription>
        </DrawerHeader>
        <div className="overflow-y-auto overscroll-contain">{body}</div>
      </DrawerContent>
    </Drawer>
  )
}

const num = (s: string): number | null => {
  const n = Number(s.replace(/[,\s]/g, ""))
  return s.trim() === "" || Number.isNaN(n) ? null : n
}

function ReduceForm({ symbol, all, onDone }: { symbol: string; all: boolean; onDone: () => void }) {
  const holdings = useHoldings()
  const accounts = useAccounts()
  const quote = useQuote(symbol)
  const create = useCreateTransaction()
  const remove = useDeleteTransaction()
  const openTradeForm = useUi((s) => s.openTradeForm)
  const unitPref = usePrefs((s) => s.quantityUnit)
  const holding = holdings.data?.find((h) => h.symbol === symbol)
  const accountIds = holding?.account_ids ?? []
  const [accountId, setAccountId] = useState("")
  const account = accountIds.includes(accountId) ? accountId : accountIds[0]
  // 分在好幾個帳戶時，要知道選的那個帳戶有幾股
  const perAccount = useQuery({
    enabled: accountIds.length > 1 && !!account,
    queryKey: ["holdings", "reduce", account, symbol],
    queryFn: async () => (await api.getHoldings(account!)).find((h: Holding) => h.symbol === symbol)?.quantity ?? 0,
  })
  const held = accountIds.length > 1 ? perAccount.data : holding?.quantity
  const isUS = holding?.market === "US"
  // 以張填：偏好是張、而且持股剛好是整張。有零股（例如 1 張 500 股）就改收股數，「全部」填的是 1500 而不是 1.5
  const inLots = unitPref === "lot" && !isUS && (held == null || held % 1000 === 0)
  // 還沒動過輸入框（null）時：「全部賣出」先填成全部（換帳戶時跟著換），否則是空的
  const [typed, setTyped] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const qty = typed ?? (all && held != null ? String(inLots ? held / 1000 : held) : "")
  const setQty = setTyped

  if (holdings.isLoading || (accountIds.length > 1 && perAccount.isLoading)) {
    return (
      <div className="px-4 pb-6 sm:px-6">
        <Skeleton className="h-24 w-full rounded-sm" />
      </div>
    )
  }
  const toFull = () => {
    onDone()
    openTradeForm({ symbol: holding?.code ?? symbol, full: true, sell: true })
  }
  if (!holding || !held) {
    return (
      <div className="flex flex-col gap-3 px-4 pb-6 sm:px-6">
        <p className="text-base">帳本裡沒有這一檔的持股。</p>
        <Button variant="outline" className="self-start" onClick={onDone}>
          關閉
        </Button>
      </div>
    )
  }

  const shares = (() => {
    const q = num(qty)
    return q === null ? null : inLots ? Math.round(q * 1000) : q
  })()
  const price = quote.data?.price ?? null
  const qtyLabel = inLots ? "張數" : "股數"
  const allText = formatQuantity(held, unitPref, holding.market)
  const heldInField = `${new Intl.NumberFormat("zh-TW").format(inLots ? held / 1000 : held)} ${inLots ? "張" : "股"}`
  const error =
    !shares || shares <= 0
      ? `請輸入${qtyLabel}`
      : !isUS && (inLots ? /\.\d{4,}$/.test(qty.trim()) : !Number.isInteger(shares))
        ? inLots
          ? "張數最多寫到小數第三位（1 股）"
          : "台股股數必須是整數"
        : shares > held
          ? `最多 ${heldInField}`
          : null
  // 欄位下面的換算：填的是張就寫股數、填的是股就寫成幾張幾股（和「記一筆」一樣）
  const converted = !shares || shares <= 0 || isUS ? null : inLots ? `${new Intl.NumberFormat("zh-TW").format(shares)} 股` : shares >= 1000 ? formatQuantity(shares, "lot", holding.market) : null

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (error || !shares || price === null || !account) return
    create.mutate(
      { account_id: account, symbol, type: "sell", trade_date: appToday(), quantity: shares, price, note: "" },
      {
        onSuccess: (txn) => {
          toast.success(`已記錄：賣出 ${holding.name} ${formatQuantity(shares, unitPref, holding.market)}`, {
            description: <StampLine />,
            action: {
              label: "復原",
              onClick: () =>
                void remove.mutateAsync(txn.id).then(
                  () => toast("已復原這筆交易"),
                  () => toast.error("沒有復原成功。到「紀錄」刪掉這一筆。"),
                ),
            },
          })
          onDone()
        },
        onError: (err) => toast.error("沒有存成功，內容還在。", { description: err instanceof Error ? err.message : undefined }),
      },
    )
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 px-4 pb-4 sm:px-6 sm:pb-6">
      <p className="text-base">
        {holding.name} <span className="num text-sm text-ink-2">{holding.code}</span>
        <span className="num ml-3 text-ink-2">持有 {allText}</span>
      </p>
      {accountIds.length > 1 && (
        <Row label="帳戶">
          <AccountSelect accounts={(accounts.data ?? []).filter((a) => accountIds.includes(a.id))} value={account ?? ""} onChange={setAccountId} />
        </Row>
      )}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="reduce-qty" className="text-sm font-medium">
          賣出的{qtyLabel}
        </label>
        <div className="flex gap-2">
          <Input
            id="reduce-qty"
            inputMode="decimal"
            autoComplete="off"
            autoFocus={!all}
            enterKeyHint="done"
            placeholder={inLots ? "例如 1" : "例如 1000"}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            aria-invalid={submitted && !!error}
            className="num flex-1"
          />
          <Button type="button" variant="outline" onClick={() => setQty(String(inLots ? held / 1000 : held))}>
            全部
          </Button>
        </div>
        {submitted && error ? <FieldError>{error}</FieldError> : converted ? <p className="num text-sm text-ink-2">{converted}</p> : null}
      </div>
      {quote.isLoading ? (
        <Skeleton className="h-6 w-56 rounded-sm" />
      ) : price !== null ? (
        <p className="text-base">
          用{quote.data?.as_of ? ` ${formatDateShort(quote.data.as_of.slice(0, 10), false)} ` : "最新"}的收盤價 <span className="num">{formatPrice(price, holding.market, holding.type)}</span> 記成賣出。
        </p>
      ) : (
        <p className="text-base">這一檔沒有收盤價，請到完整表單填成交價。</p>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <button
          type="button"
          onClick={toFull}
          className="mr-auto inline-flex min-h-9 items-center text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink pointer-coarse:min-h-11"
        >
          改日期或價格
        </button>
        <div className="flex gap-2 max-sm:w-full">
          <Button type="button" variant="outline" className="max-sm:flex-1 sm:min-w-24" onClick={onDone}>
            取消
          </Button>
          <Button type="submit" variant="sign" className="max-sm:flex-1 sm:min-w-28" disabled={create.isPending || price === null}>
            {create.isPending ? "記錄中…" : shares === held ? "全部賣出" : "賣出"}
          </Button>
        </div>
      </div>
    </form>
  )
}
