import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import { useAccounts, useMe } from "@/api/queries"
import { Masked } from "@/components/finance"
import { Button } from "@/components/ui/button"
import { formatDateShort, formatMoney, formatNumber, formatPrice, formatQuantity, MINUS } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import type { Draft } from "./types"

const VERBS: Record<string, string> = {
  buy: "買進",
  sell: "賣出",
  cash_dividend: "股利入帳",
  stock_dividend: "配股入帳",
  deposit: "存入現金",
  withdrawal: "提出現金",
  fee: "費用",
  tax: "稅",
  interest: "利息入帳",
}
const CASH_TYPES = new Set(["deposit", "withdrawal", "fee", "tax", "interest"])

interface Props {
  draft: Draft
  onSign: () => void
  onUndo: () => void
  onRevise: (patch: { quantity?: number; price?: number; trade_date?: string; account_id?: string; amount?: number }) => void
  onDiscard: () => void
  focused?: boolean
}

/**
 * 交易草稿（紫色虛線、尚未生效）。
 * 「怎麼算的 ⌄」展開稅費規則；「修改」原地改股數、價格、日期；方形「簽名｜確認入帳」才會真的入帳。
 * 簽名後格子留下使用者的簽名（文楷），草稿變成實線。
 */
export function DraftCard({ draft, onSign, onUndo, onRevise, onDiscard, focused }: Props) {
  const privacy = usePrefs((s) => s.privacyMode)
  const me = useMe()
  const accounts = useAccounts()
  const [editing, setEditing] = useState(false)
  const ref = useRef<HTMLElement>(null)
  const titleId = useId()
  const { input, instrument, preview, status } = draft
  const isDividend = input.type === "cash_dividend"
  // 後端 AI 也會起草配股與現金類交易（存入、提出、費用、稅、利息）
  const isCash = CASH_TYPES.has(input.type)
  const verb = VERBS[input.type] ?? "交易"
  const currency = instrument.currency
  const signed = status === "signed"
  const discarded = status === "discarded"
  const total = preview ? Math.abs(preview.net_cash) : null
  const account = accounts.data?.find((a) => a.id === input.account_id)
  const sameCurrency = (accounts.data ?? []).filter((a) => a.currency === currency)
  const signature = (me.data?.display_name ?? "我").slice(0, 1)

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [focused])

  const money = (n: number) => (privacy ? <Masked /> : formatMoney(n, { currency, bare: true }))

  if (discarded) {
    return <p className="mt-3 text-sm text-ink-2">已捨棄這份草稿（{verb}{isCash ? "" : ` ${instrument.name}`}）。</p>
  }

  return (
    <article
      ref={ref}
      aria-labelledby={titleId}
      className={cn(
        "note-in mt-4 border bg-ai-wash",
        signed ? "border-solid border-ai-rule" : "border-dashed border-ai-rule",
        focused && !signed && "outline-2 outline-offset-2 outline-ai",
      )}
    >
      <header className="border-b border-rule px-4 pt-3.5 pb-3">
        <h3 id={titleId} className="flex items-baseline gap-2 text-lg font-bold text-ai">
          {verb}
          {!isCash && ` ${instrument.name}`}
          {!isCash && <span className="num text-sm font-normal">{instrument.code}</span>}
          <span className="sr-only">{signed ? "，已入帳" : "，草稿，尚未入帳"}</span>
        </h3>
        <p className="mt-0.5 text-sm text-ink-2">
          {isDividend ? "入帳日" : isCash ? "日期" : "成交日"} {formatDateShort(input.trade_date)}
          {account && <span>・{account.name}</span>}
        </p>
      </header>

      {editing && !signed ? (
        <EditFields draft={draft} accounts={sameCurrency} onRevise={onRevise} />
      ) : (
        <dl className="grid grid-cols-2">
          {isCash ? (
            <>
              <Cell label="金額" value={preview ? money(preview.gross) : "…"} />
              <Cell label="稅與費用" value={preview ? money(preview.tax + preview.fee) : "…"} right />
            </>
          ) : isDividend ? (
            <>
              <Cell label="股利總額" value={input.amount != null ? money(input.amount) : "—"} />
              <Cell label="二代健保" value={preview ? money(preview.health_insurance) : "…"} right />
              <Cell label="預扣稅" value={preview ? money(preview.tax) : "…"} />
              <Cell label="手續費" value={preview ? money(preview.fee) : "…"} right />
            </>
          ) : (
            <>
              <Cell label="股數" value={privacy ? <Masked /> : input.quantity !== null ? `${formatNumber(input.quantity, 0)} 股` : "—"} />
              <Cell
                label={input.type === "stock_dividend" ? "每股配股（元）" : "成交價"}
                value={input.price != null ? `${input.type === "stock_dividend" ? "" : "@"}${formatPrice(input.price, instrument.market)}` : "—"}
                right
              />
              <Cell label="手續費" value={preview ? money(preview.fee) : "…"} />
              <Cell label={currency === "USD" ? "稅" : "證交稅"} value={preview ? money(preview.tax) : "…"} right />
            </>
          )}
          <div className="col-span-2 flex items-center justify-between border-b border-rule px-4 py-3">
            <dt className="font-bold text-ink">{isDividend ? "實拿" : input.type === "sell" ? "實收" : isCash ? "金額" : "合計"}</dt>
            <dd className="num text-xl font-bold text-ai" aria-live="polite">
              {status === "loading" || total === null ? (
                <span className="text-base font-normal text-ink-2">計算中…</span>
              ) : privacy ? (
                <Masked />
              ) : (
                formatMoney(total, { currency })
              )}
            </dd>
          </div>
        </dl>
      )}

      {draft.notes.length > 0 && !signed && (
        <ul className="flex flex-col gap-1 border-b border-rule px-4 py-2.5 text-sm text-ink">
          {draft.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {status === "error" && (
        <p role="alert" className="border-b border-rule px-4 py-2.5 text-sm text-ink">
          {draft.error}
        </p>
      )}

      <footer className="flex items-center gap-2.5 py-3 pr-3 pl-4">
        <details className="group mr-auto min-w-0">
          <summary className="inline-flex cursor-pointer list-none items-center gap-0.5 text-sm text-ai underline underline-offset-3 [&::-webkit-details-marker]:hidden">
            怎麼算的
            <ChevronDownIcon aria-hidden className="size-3.5 transition-transform group-open:rotate-180" />
          </summary>
          <ul className="mt-2 flex max-w-[22rem] flex-col gap-1 text-sm text-ink">
            {!isDividend && preview && input.quantity !== null && input.price !== null && (
              <li className="num">
                成交金額 {privacy ? "••••" : formatMoney(preview.gross, { currency, bare: true })}
                {" = "}
                {privacy ? "••••" : formatNumber(input.quantity, 0)} 股 × {formatPrice(input.price, instrument.market)}
              </li>
            )}
            {(preview?.rules ?? []).map((r) => (
              <li key={r}>{r}</li>
            ))}
            {preview && (
              <li className="num text-ink-2">
                {input.type === "buy" ? `應付 = 成交金額 + 手續費 + 稅` : isDividend ? "實拿 = 股利 − 預扣稅 − 二代健保 − 手續費" : `應收 = 成交金額 ${MINUS} 手續費 ${MINUS} 稅`}
              </li>
            )}
          </ul>
        </details>
        {signed ? (
          <Button variant="outline" size="sm" className="h-9" onClick={onUndo}>
            復原
          </Button>
        ) : editing ? (
          <>
            <Button variant="ghost" size="sm" className="h-9" onClick={onDiscard}>
              捨棄
            </Button>
            <Button variant="outline" size="sm" className="h-9" onClick={() => setEditing(false)}>
              完成
            </Button>
          </>
        ) : (
          <Button variant="outline" size="sm" className="h-9" onClick={() => setEditing(true)} disabled={status === "loading"}>
            修改
          </Button>
        )}
        <SignBox signed={signed} signature={signature} disabled={status !== "pending"} onSign={onSign} signedAt={draft.signedAt} />
      </footer>
    </article>
  )
}

function Cell({ label, value, right }: { label: string; value: React.ReactNode; right?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 border-b border-rule px-4 py-2.5", !right && "border-r")}>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="num text-base font-medium text-ai">{value}</dd>
    </div>
  )
}

/** 方形簽名格：按下才入帳；簽名後留下使用者的字（文楷，由左往右寫出） */
function SignBox({ signed, signature, disabled, onSign, signedAt }: { signed: boolean; signature: string; disabled: boolean; onSign: () => void; signedAt?: string }) {
  if (signed) {
    const time = signedAt ? new Date(signedAt).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Taipei" }) : ""
    return (
      <span className="sign-box" data-signed role="img" aria-label={`已簽名入帳 ${time}`}>
        <span className="sign-write font-ai text-2xl leading-none text-ink">{signature}</span>
        <small className="num text-xs font-normal text-ink-2">{time} 入帳</small>
      </span>
    )
  }
  return (
    <button type="button" className="sign-box disabled:opacity-50" aria-label="簽名：確認入帳" disabled={disabled} onClick={onSign}>
      <small className="text-xs font-normal opacity-85">簽名</small>
      確認入帳
    </button>
  )
}

function EditFields({
  draft,
  accounts,
  onRevise,
}: {
  draft: Draft
  accounts: { id: string; name: string }[]
  onRevise: Props["onRevise"]
}) {
  const { input } = draft
  const isDividend = input.type === "cash_dividend"
  const [qty, setQty] = useState(String(input.quantity ?? ""))
  const [price, setPrice] = useState(String(input.price ?? ""))
  const [amount, setAmount] = useState(String(input.amount ?? ""))
  const [date, setDate] = useState(input.trade_date)
  const commit = () => {
    const q = Number(qty.replace(/,/g, ""))
    const p = Number(price.replace(/,/g, ""))
    const a = Number(amount.replace(/,/g, ""))
    onRevise({
      ...(isDividend ? (a > 0 ? { amount: a } : {}) : { ...(q > 0 ? { quantity: q } : {}), ...(p > 0 ? { price: p } : {}) }),
      ...(date ? { trade_date: date } : {}),
    })
  }
  const field = "num h-10 w-full rounded-sm border border-ctl bg-raised px-2.5 text-base text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ai"
  return (
    <div className="grid grid-cols-2 gap-3 border-b border-rule px-4 py-3">
      {isDividend ? (
        <label className="flex flex-col gap-1 text-sm text-ink-2">
          股利總額
          <input className={field} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} onBlur={commit} />
        </label>
      ) : (
        <>
          <label className="flex flex-col gap-1 text-sm text-ink-2">
            股數
            <input className={field} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} onBlur={commit} />
          </label>
          <label className="flex flex-col gap-1 text-sm text-ink-2">
            成交價
            <input className={field} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} onBlur={commit} />
          </label>
        </>
      )}
      <label className="flex flex-col gap-1 text-sm text-ink-2">
        {isDividend ? "入帳日" : "成交日"}
        <input className={field} type="date" value={date} onChange={(e) => setDate(e.target.value)} onBlur={commit} />
      </label>
      {accounts.length > 1 && (
        <label className="flex flex-col gap-1 text-sm text-ink-2">
          帳戶
          <select className={field} value={input.account_id} onChange={(e) => onRevise({ account_id: e.target.value })}>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {!isDividend && Number(qty) > 0 && (
        <p className="col-span-2 text-sm text-ink-2">= {formatQuantity(Number(qty), "lot", draft.instrument.market)}</p>
      )}
    </div>
  )
}
