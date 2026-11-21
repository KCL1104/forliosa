import { useQuery } from "@tanstack/react-query"
import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import { api } from "@/api"
import { useAccounts, useMe } from "@/api/queries"
import { Masked } from "@/components/finance"
import { Button } from "@/components/ui/button"
import { formatDateShort, formatMoney, formatNumber, formatPercent, formatPrice, formatQuantity } from "@/lib/format"
import { usd } from "@/lib/labels"
import { typeFromCode } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import type { Draft } from "./types"

/**
 * 成交價和那天的收盤價差這麼多（10%，台股一天的漲跌幅上限）以上時，草稿上多寫一行（多半是打錯價格或日期）：
 * 那一行在合計的上面、差多少是粗體，焦點先到「修改」（不是簽名格；2026-11-21 評論）
 */
const FAR_FROM_CLOSE = 0.1

/** 和收盤價差很多的那一行：前半是哪一天、哪一種收盤價與價格（「比 11/12 收盤價 72.40」），後半是差多少（「低 27.6%」，粗體） */
interface FarFromClose {
  base: string
  gap: string
}

/**
 * 成交價和那天的收盤價差很多時的一行事實（產品負責人 2026-11-21；不寫建議）：「比 11/12 收盤價 72.40 低 27.6%」。
 * 美股寫紐約的交易日與 US$（「比 11/13（美東）收盤價 US$356.27 高 12.3%」）；存檔以前的日子是 Yahoo 參考價，寫「參考收盤」。
 * 收盤價和記一筆的「那天收盤」同一個查詢（`getDailyClose`，同一個快取）；那天沒有收盤價（假日、還沒收盤、太早）就不寫。
 */
function useFarFromClose(draft: Draft): FarFromClose | null {
  const { input, instrument } = draft
  const priced = (input.type === "buy" || input.type === "sell") && input.price != null && input.price > 0
  const q = useQuery({
    enabled: priced && draft.status !== "signed" && draft.status !== "discarded",
    queryKey: ["daily-close", instrument.symbol, input.trade_date],
    queryFn: () => api.getDailyClose(instrument.symbol, input.trade_date),
    staleTime: Infinity,
    retry: false,
  })
  const close = q.data?.close
  if (!priced || close == null || close <= 0) return null
  const diff = input.price! / close - 1
  if (Math.abs(diff) < FAR_FROM_CLOSE) return null
  const us = instrument.market === "US"
  const day = `${formatDateShort(q.data?.date ?? input.trade_date, false)}${us ? "（美東）" : " "}`
  const what = q.data?.reference ? "參考收盤" : "收盤價"
  const price = us ? usd(close) : formatPrice(close, instrument.market, typeFromCode(instrument.code))
  return { base: `比 ${day}${what} ${price}`, gap: `${diff < 0 ? "低" : "高"} ${formatPercent(Math.abs(diff), { decimals: 1, signed: false })}` }
}

/** 已經把焦點移到「修改」的草稿（每份草稿只移一次：重開對話、換頁回來時不再搶焦點） */
const focusedFar = new Set<string>()
/** 「剛出現」的草稿：建立後這麼久以內才移焦點（重新整理後還原的舊草稿不搶焦點） */
const FRESH_MS = 5 * 60_000

/**
 * 焦點可不可以移到草稿卡上：使用者正在別的輸入框打字（裡面有字）、或焦點在另一個對話框裡時不搶。
 * 剛送出的輸入框是空的，焦點在 body 或面板裡的按鈕上，都可以移。
 */
function canTakeFocus(target: HTMLElement): boolean {
  const a = document.activeElement
  if (!(a instanceof HTMLElement) || a === document.body) return true
  if ((a instanceof HTMLInputElement || a instanceof HTMLTextAreaElement) && a.value.trim() !== "") return false
  if (a.isContentEditable) return false
  const dialog = a.closest('[role="dialog"], [role="alertdialog"]')
  return !dialog || dialog.contains(target)
}

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
 * 交易草稿（石墨灰虛線、尚未生效）。
 * 「怎麼算的 ⌄」展開稅費規則；「修改」原地改股數、價格、日期；方形「簽名｜確認入帳」才會真的入帳。
 * 簽名後格子留下使用者名字的第一個字（墨色 Noto Sans：這是使用者的字，不是模型寫的），草稿變成實線。
 * 成交價和那天的收盤價差 10% 以上：那一行事實在格子與合計之間（差多少是粗體），草稿剛出現時焦點移到「修改」，
 * 按 Enter 是修改、不是簽名（`修改` 的說明念那一行）。
 */
export function DraftCard({ draft, onSign, onUndo, onRevise, onDiscard, focused }: Props) {
  const privacy = usePrefs((s) => s.privacyMode)
  const me = useMe()
  const accounts = useAccounts()
  const [editing, setEditing] = useState(false)
  const ref = useRef<HTMLElement>(null)
  const titleId = useId()
  const howId = useId()
  const farId = useId()
  const editRef = useRef<HTMLButtonElement>(null)
  const [howOpen, setHowOpen] = useState(false)
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
  const farFromClose = useFarFromClose(draft)
  const far = farFromClose !== null && !signed
  // 買賣的手續費（與賣出的交易稅）：不自動算（2026-11-14），但卡片上一定有這一格（2026-11-21）——沒填（試算也是 0）就寫「沒填」，
  // 合計就是不含它的金額；填了、或試算裡有（定期定額的扣款）寫金額，和合計同一個數字
  const trade = input.type === "buy" || input.type === "sell"
  const feeValue = (given: number | null | undefined, computed: number | undefined) =>
    given == null && !computed ? <span className="font-normal text-ink-2">沒填</span> : money(given ?? computed ?? 0)

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [focused])

  // 和收盤價差很多：草稿剛出現時焦點先到「修改」（每份草稿一次；剛建立的才移，使用者在別處打字時不搶）
  useEffect(() => {
    if (!far || editing || status !== "pending" || focusedFar.has(draft.id)) return
    const born = Date.parse(draft.createdAt)
    if (!Number.isFinite(born) || Date.now() - born > FRESH_MS) return
    const el = editRef.current
    if (!el || !canTakeFocus(el)) return
    focusedFar.add(draft.id)
    el.focus()
  }, [far, editing, status, draft.id, draft.createdAt])

  // 美股的金額每一格都寫 US$（只有「實拿」有幣別的話，2.60 看不出是哪一種錢）；新台幣照舊不加
  const money = (n: number) => (privacy ? <Masked /> : formatMoney(n, { currency, bare: currency !== "USD" }))

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
        <div className="flex items-start justify-between gap-3">
          <h3 id={titleId} className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-lg font-bold text-ai [overflow-wrap:anywhere]">
            {verb}
            {!isCash && ` ${instrument.name}`}
            {!isCash && <span className="num text-sm font-normal">{instrument.code}</span>}
            <span className="sr-only">{signed ? "，已入帳" : "，草稿，尚未入帳"}</span>
          </h3>
          {/* 「草稿」標記（標題已經念了「草稿，尚未入帳」）：卡片前面不再寫「幫你寫好了」這類句子 */}
          {!signed && (
            <span aria-hidden className="status-tag mt-1 shrink-0 border-ai-rule text-ai">
              草稿
            </span>
          )}
        </div>
        {/* 帳戶名稱是使用者自己取的（可能含「・」「－」）：和日期之間用空白分開，不再接一個分隔符號 */}
        <p className="mt-0.5 flex flex-wrap gap-x-3 text-sm text-ink-2">
          <span>
            {isDividend ? "入帳日" : isCash ? "日期" : "成交日"} {formatDateShort(input.trade_date)}
          </span>
          {account && <span>{account.name}</span>}
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
              {/* 稅與費用不逐項列在卡片上（產品負責人 2026-11-14）：只有總額和「實拿」，明細在「怎麼算的」裡 */}
              <Cell label="股利總額" value={input.amount != null ? money(input.amount) : "—"} />
              <Cell label="稅與費用" value={preview ? money(preview.health_insurance + preview.tax + preview.fee) : "…"} right />
            </>
          ) : (
            <>
              <Cell label="股數" value={privacy ? <Masked /> : input.quantity !== null ? `${formatNumber(input.quantity, 0)} 股` : "—"} />
              {/* 和「2,000 股」同一套語法：值後面接單位（台股「52.40 元」、美股「182.30 美元」） */}
              <Cell
                label={input.type === "stock_dividend" ? "每股配股（元）" : "成交價"}
                value={
                  input.price == null
                    ? "—"
                    : input.type === "stock_dividend"
                      ? formatPrice(input.price, instrument.market)
                      : `${formatPrice(input.price, instrument.market, typeFromCode(instrument.code))} ${currency === "USD" ? "美元" : "元"}`
                }
                right
              />
              {/* 手續費與稅不自動算（2026-11-14），但一定看得到有沒有算進去（2026-11-21）：買進一格手續費，賣出多一格交易稅 */}
              {trade &&
                (input.type === "sell" ? (
                  <>
                    <Cell label="手續費" value={feeValue(input.fee, preview?.fee)} />
                    <Cell label="交易稅" value={feeValue(input.tax, preview?.tax)} right />
                  </>
                ) : (
                  <Cell label="手續費" value={feeValue(input.fee, preview?.fee)} wide />
                ))}
            </>
          )}
        </dl>
      )}

      {/* 和那天的收盤價差 10% 以上：格子和合計之間一行事實，差多少是粗體（只有事實，不寫「請確認」）。修改時也在，改了價格馬上重算 */}
      {farFromClose && !signed && (
        <p id={farId} className="num border-b border-rule px-4 py-2.5 text-base text-ink" data-far-from-close>
          {farFromClose.base} <b className="font-bold">{farFromClose.gap}</b>
        </p>
      )}

      {!(editing && !signed) && (
        <dl className="flex items-center justify-between border-b border-rule px-4 py-3">
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

      {/* 「怎麼算的」展開的清單在按鈕列下面、佔滿卡片寬：放在同一列會把簽名格擠扁（320 寬只剩 31px；2026-11-14 第七次評分） */}
      <footer className="flex items-center gap-2.5 py-3 pr-3 pl-4">
        <button
          type="button"
          aria-expanded={howOpen}
          aria-controls={howId}
          onClick={() => setHowOpen(!howOpen)}
          className="mr-auto inline-flex min-h-9 min-w-0 items-center gap-0.5 text-sm text-ai underline underline-offset-3 pointer-coarse:min-h-11"
        >
          怎麼算的
          <ChevronDownIcon aria-hidden className={cn("size-3.5 transition-transform", howOpen && "rotate-180")} />
        </button>
        {signed ? (
          <Button variant="outline" size="sm" className="h-9 pointer-coarse:h-11" onClick={onUndo}>
            復原
          </Button>
        ) : editing ? (
          <>
            <Button variant="ghost" size="sm" className="h-9 pointer-coarse:h-11" onClick={onDiscard}>
              捨棄
            </Button>
            <Button variant="outline" size="sm" className="h-9 pointer-coarse:h-11" onClick={() => setEditing(false)}>
              完成
            </Button>
          </>
        ) : (
          <Button
            ref={editRef}
            variant="outline"
            size="sm"
            className="h-9 pointer-coarse:h-11"
            onClick={() => setEditing(true)}
            disabled={status === "loading"}
            aria-describedby={far ? farId : undefined}
          >
            修改
          </Button>
        )}
        <SignBox signed={signed} signature={signature} disabled={status !== "pending"} onSign={onSign} signedAt={draft.signedAt} />
      </footer>
      {howOpen && (
        <ul id={howId} className="flex flex-col gap-1 border-t border-rule px-4 py-2.5 text-sm text-ink">
          {!isDividend && preview && input.quantity !== null && input.price !== null && (
            <li className="num">
              成交金額 {privacy ? "••••" : formatMoney(preview.gross, { currency, bare: true })}
              {" = "}
              {privacy ? "••••" : formatNumber(input.quantity, 0)} 股 × {formatPrice(input.price, instrument.market)}
            </li>
          )}
          {/* 股利的預扣稅、二代健保照常自動扣；買賣的手續費與交易稅在卡片上（上面的格子），這裡不再列一次 */}
          {preview && isDividend && (
            <li className="num">
              {`預扣稅 ${privacy ? "••••" : formatMoney(preview.tax, { currency, bare: true })}、二代健保 ${privacy ? "••••" : formatMoney(preview.health_insurance, { currency, bare: true })}`}
            </li>
          )}
          {(preview?.rules ?? []).map((r) => (
            <li key={r}>{r}</li>
          ))}
          {preview && isDividend && <li className="num text-ink-2">實拿 = 股利 − 預扣稅 − 二代健保</li>}
        </ul>
      )}
    </article>
  )
}

function Cell({ label, value, right, wide }: { label: string; value: React.ReactNode; right?: boolean; wide?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 border-b border-rule px-4 py-2.5", wide ? "col-span-2" : !right && "border-r")}>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="num text-base font-medium text-ai">{value}</dd>
    </div>
  )
}

/** 方形簽名格：按下才入帳；簽名後留下使用者的字（墨色，由左往右寫出） */
function SignBox({ signed, signature, disabled, onSign, signedAt }: { signed: boolean; signature: string; disabled: boolean; onSign: () => void; signedAt?: string }) {
  if (signed) {
    const time = signedAt ? new Date(signedAt).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Taipei" }) : ""
    return (
      <span className="sign-box" data-signed role="img" aria-label={`已簽名入帳 ${time}`}>
        <span className="sign-write text-2xl leading-none font-medium text-ink">{signature}</span>
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
  const field = "num h-10 w-full rounded-sm border border-ctl bg-raised px-2.5 text-base text-ink outline-none pointer-coarse:text-[1rem] focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-offset-1 focus-visible:outline-ai"
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
