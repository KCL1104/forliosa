import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useMemo, useRef, useState } from "react"
import { api, appToday } from "@/api"
import { useCreateTransactionBatch } from "@/api/queries"
import { ApiError, type Account, type BatchRejectedRow, type ImportFlag, type StatementImport, type TransactionBatchResult } from "@/api/types"
import { DateField } from "@/components/date-field"
import { FieldError, FormField as Row } from "@/components/form-field"
import { SymbolPicker } from "@/components/symbol-picker"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { formatDateLong, formatDateShort, formatMoney, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { AccountSelect } from "../TradeForm"
import { bodyClass, footerClass } from "./layout"
import {
  editRow,
  hasErrors,
  isSkipped,
  mergeFlags,
  newFlagCodes,
  NOTE_CODES,
  PICK_SYMBOL_CODES,
  rowErrors,
  rowTotal,
  shortfallRow,
  skippedSummary,
  toCandidate,
  toDraftRow,
  totalsLine,
  type DraftRow,
  type EditableFields,
  type RowErrors,
} from "./flags"

/**
 * 確認表（DESIGN.md〈匯入對帳單〉）：AI 讀出來的是草稿，畫成草稿卡的樣子——石墨淡底、石墨灰虛線、數字是鉛筆的石墨灰；
 * 使用者改過的格子變成墨色。一列一筆：勾選、日期、買／賣、股票、股數、價格、手續費、稅、合計，每一格都能改；
 * 有問題的那一列下面直接寫伺服器的句子（找不到股票旁邊可以選、賣超旁邊有「補一筆買進」）。
 * 最上面是整份的核對（合計、沒讀清楚、像指令的文字）；股利與融券不匯入，收成一行「略過 N 筆股利」。
 * 簽名格「匯入 N 筆」：先重新驗算（dry_run），有新的問題就停下來給你看；沒有就一次寫入（全部或全不）。
 */

const today = () => appToday()
const currencyOf = (r: DraftRow) => (r.symbol?.market === "US" ? "USD" : "TWD")
const fmtTotal = (r: DraftRow) => {
  const t = rowTotal(r)
  return t === null ? "—" : formatMoney(t, { currency: currencyOf(r) })
}
const describe = (r: DraftRow) =>
  [r.date ? formatDateShort(r.date, false) : "", r.type === "sell" ? "賣出" : "買進", r.symbol?.name ?? r.readName].filter(Boolean).join(" ")

export function ReviewTable({
  doc,
  accounts,
  initialAccountId,
  recheckOnMount = false,
  sheet,
  onDone,
  onCancel,
  onRestart,
}: {
  doc: StatementImport
  accounts: Account[]
  initialAccountId: string
  /** 讀檔時驗算用的帳戶和這裡先選好的不同（對帳單上的券商對到別的帳戶）：一打開就照這個帳戶重新驗算 */
  recheckOnMount?: boolean
  sheet: boolean
  onDone: (result: TransactionBatchResult, count: number) => void
  onCancel: () => void
  onRestart: () => void
}) {
  const create = useCreateTransactionBatch()
  const [accountId, setAccountId] = useState(initialAccountId)
  const [rows, setRows] = useState<DraftRow[]>(() => doc.rows.filter((r) => !isSkipped(r)).map(toDraftRow))
  const [showErrors, setShowErrors] = useState(false)
  const [busy, setBusy] = useState<"checking" | "saving" | "recheck" | null>(recheckOnMount ? "recheck" : null)
  const [notice, setNotice] = useState<string | null>(null)
  const added = useRef(0)
  /** 已經「補一筆買進」的賣出（同一筆不再補第二次） */
  const [shortfallFor, setShortfallFor] = useState<ReadonlySet<string>>(new Set())
  const tableRef = useRef<HTMLDivElement>(null)
  const skipped = useMemo(() => doc.rows.filter(isSkipped), [doc.rows])
  const included = rows.filter((r) => r.include)
  const t = today()

  const patch = (id: string, p: Partial<EditableFields>) => setRows((rs) => rs.map((r) => (r.id === id ? editRow(r, p) : r)))
  const setInclude = (id: string, include: boolean) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, include } : r)))

  /**
   * 重新驗算勾著的列（dry_run）：旗標併進表格。回傳多出新問題的列數、伺服器說寫不進去的列數（`severity: "error"`）、
   * 怪不到哪一列的問題
   */
  const recheck = async (list: DraftRow[], account: string): Promise<{ changed: number; blocking: number; problems: string[] }> => {
    const sent = list.filter((r) => r.include)
    if (sent.length === 0) return { changed: 0, blocking: 0, problems: [] }
    const check = await api.checkTransactionBatch({ account_id: account, origin: "import", rows: sent.map((r) => toCandidate(r, account)) })
    const fresh = new Map(check.rows.map((x) => [x.index, x.flags]))
    let changed = 0
    let blocking = 0
    const next = new Map<string, ImportFlag[]>()
    sent.forEach((r, i) => {
      const got = fresh.get(i) ?? []
      const merged = mergeFlags(r, got)
      if (newFlagCodes(r.flags, merged).length) changed++
      if (got.some((f) => f.severity === "error")) blocking++
      next.set(r.id, merged)
    })
    setRows((rs) => rs.map((r) => (next.has(r.id) ? { ...r, flags: next.get(r.id)! } : r)))
    const problems = (check.problems ?? []).map((p) => p.message)
    if (check.ok === false && blocking === 0 && problems.length === 0) problems.push("帳本現在對不上，這一批寫不進去。")
    return { changed, blocking, problems }
  }

  // 換了帳戶（或一打開時券商對到別的帳戶）：賣超、重複要照那個帳戶重算
  const recheckSilently = (account: string) => {
    setBusy("recheck")
    void recheck(rows, account)
      .catch(() => undefined)
      .finally(() => setBusy(null))
  }
  useEffect(() => {
    if (!recheckOnMount) return
    const t = window.setTimeout(() => {
      void recheck(rows, initialAccountId)
        .catch(() => undefined)
        .finally(() => setBusy(null))
    }, 0)
    return () => window.clearTimeout(t)
    // 只在第一次打開時
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const addShortfall = (sell: DraftRow) => {
    const id = `added_${++added.current}`
    const buy = shortfallRow(sell, id)
    if (!buy || shortfallFor.has(sell.id)) return
    setShortfallFor((xs) => new Set(xs).add(sell.id))
    setRows((rs) => {
      const i = rs.findIndex((r) => r.id === sell.id)
      return [...rs.slice(0, i), buy, ...rs.slice(i)]
    })
    requestAnimationFrame(() => document.getElementById(`imp-date-${id}`)?.focus())
  }

  const sign = async () => {
    setShowErrors(true)
    setNotice(null)
    if (included.length === 0) return
    const bad = included.filter((r) => hasErrors(rowErrors(r, t)))
    if (bad.length) {
      setNotice(`有 ${bad.length} 筆還沒填好。`)
      const first = bad[0]!
      const e = rowErrors(first, t)
      const field = e.symbol ? "symbol" : e.date ? "date" : e.qty ? "qty" : e.price ? "price" : e.fee ? "fee" : "tax"
      document.getElementById(`imp-${field}-${first.id}`)?.focus()
      return
    }
    setBusy("checking")
    try {
      const check = await recheck(rows, accountId)
      if (check.changed) {
        setNotice(`有 ${check.changed} 筆的檢查結果變了，看過再按一次。`)
        return
      }
      if (check.blocking) {
        setNotice(`有 ${check.blocking} 筆不能匯入。取消勾選，或改好再按一次。`)
        return
      }
      if (check.problems.length) {
        setNotice(check.problems.join(" "))
        return
      }
      setBusy("saving")
      const result = await create.mutateAsync({ account_id: accountId, origin: "import", rows: included.map((r) => toCandidate(r, accountId)) })
      onDone(result, included.length)
    } catch (e) {
      const failing = e instanceof ApiError && Array.isArray(e.extra.rows) ? (e.extra.rows as BatchRejectedRow[]) : null
      if (failing?.length) {
        // 有一筆不行就一筆都不寫：把原因寫在那幾列下面，表格留著讓你改；怪不到哪一列的寫在下面
        const byId = new Map(failing.filter((f) => f.index !== null).map((f) => [included[f.index!]?.id, f]))
        const whole = failing.filter((f) => f.index === null).map((f) => f.message)
        setRows((rs) =>
          rs.map((r) => {
            const f = byId.get(r.id)
            if (!f) return r
            const flags = r.flags.some((x) => x.code === f.code) ? r.flags : [...r.flags, { code: f.code, message: f.message, severity: "error" }]
            return { ...r, flags }
          }),
        )
        setNotice([byId.size ? `有 ${byId.size} 筆不能匯入，所以這次一筆都沒有寫進帳本。改好再按一次。` : "這次一筆都沒有寫進帳本。", ...whole].join(" "))
      } else {
        setNotice(`沒有匯入成功，表格還在。${e instanceof Error && e.message ? e.message : ""}`)
      }
    } finally {
      setBusy(null)
    }
  }

  const totals = totalsLine(doc)
  const period = doc.period?.from && doc.period?.to ? `${formatDateLong(doc.period.from).replace(/（.）/, "")}–${formatDateShort(doc.period.to, false)}` : null
  const facts = [doc.broker_name, period, `讀到 ${doc.rows.length} 筆`].filter(Boolean).join("・")

  return (
    <>
      <div className={bodyClass(sheet)}>
        <div className="flex flex-col gap-2.5 pb-4">
          {accounts.length > 1 && (
            <Row label="匯入到哪個帳戶" className="sm:max-w-xs">
              <AccountSelect
                accounts={accounts}
                value={accountId}
                onChange={(id) => {
                  setAccountId(id)
                  recheckSilently(id)
                }}
              />
            </Row>
          )}
          <p className="num text-sm text-ink-2">{facts}</p>
          {totals && <p className="text-base text-ink">{totals}</p>}
          {doc.unreadable.length > 0 && <p className="text-base text-ink">沒讀清楚：{doc.unreadable.join("、")}。</p>}
          {(doc.problems ?? []).map((p) => (
            <p key={p.code + p.message} className="text-base text-ink">
              {p.message}
            </p>
          ))}
          {doc.embedded_instructions.length > 0 && (
            <div>
              <p className="text-base text-ink">檔案裡有一段像指令的文字，沒有照做。</p>
              {doc.embedded_instructions.map((q) => (
                <p key={q} className="mt-1 line-clamp-2 text-sm break-all text-ink-2">
                  「{q}」
                </p>
              ))}
            </div>
          )}
        </div>

        <div ref={tableRef} className="border border-dashed border-ai-rule bg-ai-wash" aria-busy={busy === "recheck" || undefined}>
          {sheet ? (
            <ul aria-label="讀出來的交易">
              {rows.map((r, i) => (
                <MobileRow key={r.id} row={r} n={i + 1} errors={showErrors && r.include ? rowErrors(r, t) : {}} onPatch={patch} onInclude={setInclude} onShortfall={shortfallFor.has(r.id) ? undefined : addShortfall} />
              ))}
            </ul>
          ) : (
            <table className="w-full table-fixed border-collapse text-md">
              <caption className="sr-only">讀出來的交易：勾選的會匯入</caption>
              <colgroup>
                <col className="w-11" />
                <col className="w-[7rem]" />
                <col className="w-[4.75rem]" />
                <col />
                <col className="w-[6.5rem]" />
                <col className="w-[6.25rem]" />
                <col className="w-[5.25rem]" />
                <col className="w-[5rem]" />
                <col className="w-[7.5rem]" />
              </colgroup>
              {/* 表頭跟著捲動停在上面（30 列時往下捲還看得到哪一欄是什麼） */}
              <thead className="sticky top-0 z-10 bg-ai-wash">
                <tr className="form-head text-left text-sm text-ink-2">
                  <th scope="col" className="py-2 pl-3 font-normal">
                    <span className="sr-only">匯入</span>
                  </th>
                  <th scope="col" className="px-1.5 py-2 font-normal">日期</th>
                  <th scope="col" className="px-1.5 py-2 font-normal">買／賣</th>
                  <th scope="col" className="px-1.5 py-2 font-normal">股票</th>
                  <th scope="col" className="px-1.5 py-2 text-right font-normal">股數</th>
                  <th scope="col" className="px-1.5 py-2 text-right font-normal">價格</th>
                  <th scope="col" className="px-1.5 py-2 text-right font-normal">手續費</th>
                  <th scope="col" className="px-1.5 py-2 text-right font-normal">稅</th>
                  <th scope="col" className="py-2 pr-3 pl-1.5 text-right font-normal">合計</th>
                </tr>
              </thead>
              {rows.map((r, i) => (
                <DesktopRow key={r.id} row={r} n={i + 1} errors={showErrors && r.include ? rowErrors(r, t) : {}} onPatch={patch} onInclude={setInclude} onShortfall={shortfallFor.has(r.id) ? undefined : addShortfall} />
              ))}
            </table>
          )}
        </div>

        {skipped.length > 0 && <Skipped rows={skipped} />}
      </div>

      <div className={footerClass(sheet)}>
        {notice && (
          <p role="alert" className="w-full text-base font-medium text-ink">
            {notice}
          </p>
        )}
        <button type="button" onClick={onRestart} className={cn(textAction, "text-sm text-ink-2 hover:text-ink")}>
          換一個檔案
        </button>
        <div className="ml-auto flex items-center gap-2.5">
          <Button type="button" variant="outline" onClick={onCancel}>
            取消
          </Button>
          <button
            type="button"
            className="sign-box w-auto min-w-[76px] px-3 disabled:bg-rule disabled:text-ink-2 disabled:after:opacity-0"
            aria-label={`簽名：匯入 ${included.length} 筆`}
            disabled={included.length === 0 || busy !== null}
            onClick={() => void sign()}
          >
            <small className="text-xs font-normal opacity-85">{busy === "checking" ? "驗算中" : busy === "saving" ? "寫入中" : "簽名"}</small>
            <span className="num whitespace-nowrap">匯入 {included.length} 筆</span>
          </button>
        </div>
      </div>
    </>
  )
}

// ── 一列 ─────────────────────────────────────────────────

interface RowProps {
  row: DraftRow
  n: number
  errors: RowErrors
  onPatch: (id: string, p: Partial<EditableFields>) => void
  onInclude: (id: string, include: boolean) => void
  /** 「補一筆買進」（已經補過的那一列沒有） */
  onShortfall?: (row: DraftRow) => void
}

/** AI 讀的是鉛筆（石墨灰），使用者改過的是墨水 */
const tone = (r: DraftRow, k: keyof EditableFields) => (r.edited.has(k) ? "text-ink" : "text-ai")

const cellInput =
  "num h-9 w-full min-w-0 rounded-sm border border-transparent bg-transparent px-1.5 text-md outline-none transition-colors hover:border-ctl focus-visible:border-ink focus-visible:bg-raised aria-invalid:border-ink aria-invalid:bg-raised pointer-coarse:h-11 pointer-coarse:text-[1rem]"

function DesktopRow({ row: r, n, errors, onPatch, onInclude, onShortfall }: RowProps) {
  const nth = `第 ${n} 筆的`
  const off = !r.include
  const errorText = Object.values(errors).filter(Boolean)
  return (
    <tbody className={cn("border-b border-rule last:border-b-0", off && "[&_input]:text-ink-2 [&_select]:text-ink-2")}>
      <tr className="align-middle">
        <td className="py-1.5 pl-3">
          <IncludeBox row={r} onInclude={onInclude} />
        </td>
        <td className="px-0.5 py-1.5">
          {/* 和記一筆同一個月曆；表格裡只寫「10/1（四）」，不放圖示 */}
          <DateField
            id={`imp-date-${r.id}`}
            value={r.date}
            onChange={(date) => onPatch(r.id, { date })}
            label={`${nth}日期`}
            invalid={!!errors.date}
            icon={false}
            placeholder="選日期"
            format={(v) => formatDateShort(v)}
            className={cn(cellInput, "px-1.5", tone(r, "date"))}
          />
        </td>
        <td className="px-0.5 py-1.5">
          <SideSelect row={r} label={`${nth}買賣`} onPatch={onPatch} />
        </td>
        <td className="px-1.5 py-1.5">
          <StockCell row={r} n={n} invalid={!!errors.symbol} onPatch={onPatch} />
        </td>
        <NumCell row={r} field="qty" label={`${nth}股數`} invalid={!!errors.qty} onPatch={onPatch} />
        <NumCell row={r} field="price" label={`${nth}價格`} invalid={!!errors.price} onPatch={onPatch} />
        <NumCell row={r} field="fee" label={`${nth}手續費`} invalid={!!errors.fee} onPatch={onPatch} />
        <NumCell row={r} field="tax" label={`${nth}稅`} invalid={!!errors.tax} onPatch={onPatch} />
        <td className={cn("num py-1.5 pr-3 pl-1.5 text-right font-bold whitespace-nowrap", off ? "text-ink-2" : "text-ai")}>{fmtTotal(r)}</td>
      </tr>
      {(r.flags.length > 0 || errorText.length > 0) && (
        <tr>
          <td />
          <td colSpan={8} className="px-1.5 pb-2.5">
            <Flags row={r} errors={errorText} onShortfall={onShortfall} onPatch={onPatch} />
          </td>
        </tr>
      )}
    </tbody>
  )
}

function MobileRow({ row: r, n, errors, onPatch, onInclude, onShortfall }: RowProps) {
  const [editing, setEditing] = useState(r.added)
  const nth = `第 ${n} 筆的`
  const off = !r.include
  const errorText = Object.values(errors).filter(Boolean)
  // 有沒填好的格子時直接打開欄位
  const open = editing || errorText.length > 0
  return (
    <li className="flex gap-1 border-b border-rule py-2.5 pr-3 pl-1 last:border-b-0">
      <IncludeBox row={r} onInclude={onInclude} />
      <div className="min-w-0 flex-1 pt-2.5">
        <div className="flex items-baseline justify-between gap-3">
          <p className={cn("min-w-0 truncate text-lg font-medium", off ? "text-ink-2" : r.symbol ? tone(r, "symbol") : "text-ink-2")}>
            {r.symbol ? r.symbol.name : r.readName || "沒有股票"}
            {r.symbol && <span className="num ml-1.5 text-sm font-normal text-ink-2">{r.symbol.code}</span>}
          </p>
          <p className={cn("num shrink-0 text-base font-bold", off ? "text-ink-2" : "text-ai")}>{fmtTotal(r)}</p>
        </div>
        <p className={cn("num mt-0.5 text-md", off ? "text-ink-2" : "text-ai")}>
          {r.date ? formatDateShort(r.date) : "還沒選日期"}・{r.type === "sell" ? "賣出" : "買進"}・{r.qty ? `${r.qty} 股` : "—"} × {r.price || "—"}
        </p>
        {/* 「修改」和手續費同一行（30 列的對帳單在手機上不要長得太多） */}
        <div className="flex items-center justify-between gap-3">
          <p className="num text-sm text-ink-2">
            手續費 {r.fee || "0"}・稅 {r.tax || "0"}
          </p>
          {!open && (
            <button type="button" onClick={() => setEditing(true)} className={cn(textAction, "shrink-0")} aria-label={`修改第 ${n} 筆：${describe(r)}`}>
              修改
            </button>
          )}
        </div>
        {(r.flags.length > 0 || errorText.length > 0) && (
          <div className="mt-2">
            <Flags row={r} errors={errorText} onShortfall={onShortfall} onPatch={onPatch} />
          </div>
        )}
        {open ? (
          <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-3 pb-1">
            <MobileField label="日期" id={`imp-date-${r.id}`} error={errors.date}>
              <DateField id={`imp-date-${r.id}`} value={r.date} onChange={(date) => onPatch(r.id, { date })} label={`${nth}日期`} invalid={!!errors.date} icon={false} format={(v) => formatDateShort(v)} />
            </MobileField>
            <MobileField label="買／賣" id={`imp-side-${r.id}`}>
              <SideSelect row={r} label={`${nth}買賣`} onPatch={onPatch} boxed />
            </MobileField>
            <div className="col-span-2">
              <MobileField label="股票" id={`imp-symbol-${r.id}`} error={errors.symbol}>
                <StockCell row={r} n={n} invalid={!!errors.symbol} onPatch={onPatch} boxed />
              </MobileField>
            </div>
            {(["qty", "price", "fee", "tax"] as const).map((f) => (
              <MobileField key={f} label={FIELD_LABEL[f]} id={`imp-${f}-${r.id}`} error={errors[f]}>
                <Input
                  id={`imp-${f}-${r.id}`}
                  inputMode="decimal"
                  autoComplete="off"
                  value={r[f]}
                  onChange={(e) => onPatch(r.id, { [f]: e.target.value })}
                  aria-invalid={!!errors[f] || undefined}
                  className="num"
                />
              </MobileField>
            ))}
            {!r.added && (
              <button type="button" onClick={() => setEditing(false)} className={cn(textAction, "col-span-2 self-start")}>
                完成
              </button>
            )}
          </div>
        ) : null}
      </div>
    </li>
  )
}

const FIELD_LABEL = { qty: "股數", price: "價格", fee: "手續費", tax: "稅" } as const

function MobileField({ label, id, error, children }: { label: string; id: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error && <FieldError>{error}</FieldError>}
    </div>
  )
}

/** 勾選：看得到的是 18px 的格子，可按範圍 44px */
function IncludeBox({ row: r, onInclude }: { row: DraftRow; onInclude: (id: string, include: boolean) => void }) {
  return (
    <label className="grid size-11 shrink-0 cursor-pointer place-items-center">
      <input
        type="checkbox"
        checked={r.include}
        onChange={(e) => onInclude(r.id, e.target.checked)}
        aria-label={`匯入：${describe(r)}`}
        className="size-[18px] cursor-pointer accent-[var(--act)]"
      />
    </label>
  )
}

function SideSelect({ row: r, label, onPatch, boxed }: { row: DraftRow; label: string; onPatch: RowProps["onPatch"]; boxed?: boolean }) {
  return (
    <select
      id={boxed ? `imp-side-${r.id}` : undefined}
      value={r.type}
      onChange={(e) => onPatch(r.id, { type: e.target.value as "buy" | "sell" })}
      aria-label={label}
      className={cn(
        boxed
          ? "h-10 w-full rounded-sm border border-input bg-raised px-2.5 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:h-11 pointer-coarse:text-[1rem]"
          : cn(cellInput, "px-1"),
        tone(r, "type"),
      )}
    >
      <option value="buy">買進</option>
      <option value="sell">賣出</option>
    </select>
  )
}

function NumCell({ row: r, field, label, invalid, onPatch }: { row: DraftRow; field: "qty" | "price" | "fee" | "tax"; label: string; invalid: boolean; onPatch: RowProps["onPatch"] }) {
  return (
    <td className="px-0.5 py-1.5">
      <input
        id={`imp-${field}-${r.id}`}
        inputMode="decimal"
        autoComplete="off"
        value={r[field]}
        onChange={(e) => onPatch(r.id, { [field]: e.target.value })}
        aria-label={label}
        aria-invalid={invalid || undefined}
        // 沒讀到的格子：看得出要填（表格裡的格子平常沒有框）
        placeholder={field === "qty" ? "股數" : field === "price" ? "價格" : "0"}
        className={cn(cellInput, "text-right placeholder:text-ink-2/70", tone(r, field))}
      />
    </td>
  )
}

/** 股票：按一下換一檔（找不到、對到好幾檔時是「選股票」，先用對帳單上的名稱搜） */
function StockCell({ row: r, n, invalid, onPatch, boxed }: { row: DraftRow; n: number; invalid: boolean; onPatch: RowProps["onPatch"]; boxed?: boolean }) {
  const [open, setOpen] = useState(false)
  const id = `imp-symbol-${r.id}`
  const trigger = r.symbol ? (
    <PopoverTrigger
      id={id}
      aria-label={`第 ${n} 筆的股票：${r.symbol.name} ${r.symbol.code}，按一下換一檔`}
      className={cn(
        "flex w-full min-w-0 flex-col items-start rounded-sm border text-left outline-none focus-visible:border-ink",
        boxed ? "h-11 justify-center border-input bg-raised px-3" : "border-transparent px-1.5 py-0.5 hover:border-ctl",
      )}
    >
      <span className={cn("w-full truncate leading-snug", tone(r, "symbol"))}>{r.symbol.name}</span>
      <span className="num text-sm leading-tight text-ink-2">{r.symbol.code}</span>
    </PopoverTrigger>
  ) : (
    <PopoverTrigger
      id={id}
      aria-invalid={invalid || undefined}
      aria-label={`第 ${n} 筆的股票：還沒選${r.readName ? `（對帳單上寫「${r.readName}」）` : ""}`}
      className={cn(textAction, "font-medium", boxed && "h-11")}
    >
      選股票
    </PopoverTrigger>
  )
  return (
    <Popover open={open} onOpenChange={setOpen}>
      {trigger}
      <PopoverContent align="start" className="w-80">
        <SymbolPicker
          value={null}
          initialQuery={r.symbol ? "" : r.readName}
          label={`第 ${n} 筆的股票`}
          onChange={(i) => {
            if (!i) return
            onPatch(r.id, { symbol: { symbol: i.symbol, code: i.code, name: i.name, market: i.market } })
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

/** 那一列下面的句子：要處理的是 15px 墨色，標籤（融資、當沖）是 13px 淡墨；旁邊放得到的動作 */
function Flags({ row: r, errors, onShortfall, onPatch }: { row: DraftRow; errors: string[]; onShortfall: RowProps["onShortfall"]; onPatch: RowProps["onPatch"] }) {
  const seen = new Set<string>()
  const flags = r.flags.filter((f) => (seen.has(f.code) ? false : (seen.add(f.code), true)))
  return (
    <ul className="flex flex-col gap-1">
      {flags.map((f) => {
        const note = NOTE_CODES.has(f.code)
        return (
          <li key={f.code} className={cn("flex flex-wrap items-baseline gap-x-3", note ? "text-sm text-ink-2" : "text-base text-ink", f.severity === "error" && "font-medium")}>
            <span>{f.message}</span>
            {f.code === "oversell" && r.symbol && onShortfall && (
              <button type="button" onClick={() => onShortfall(r)} className={cn(textAction, "font-normal")}>
                補一筆買進
              </button>
            )}
            {PICK_SYMBOL_CODES.has(f.code) && !r.symbol && <PickInline row={r} onPatch={onPatch} />}
          </li>
        )
      })}
      {errors.length > 0 && (
        <li>
          <FieldError>{errors.join("、")}。</FieldError>
        </li>
      )}
    </ul>
  )
}

/** 訊息旁邊的「選股票」（表格那一格也可以選；這裡是句子旁邊多一個入口，看到問題就能處理） */
function PickInline({ row: r, onPatch }: { row: DraftRow; onPatch: RowProps["onPatch"] }) {
  const [open, setOpen] = useState(false)
  const labelId = useId()
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger className={cn(textAction, "font-normal")} aria-describedby={labelId}>
        選一檔
      </PopoverTrigger>
      <span id={labelId} className="sr-only">
        {r.readName ? `對帳單上寫「${r.readName}」` : ""}
      </span>
      <PopoverContent align="start" className="w-80">
        <SymbolPicker
          value={null}
          initialQuery={r.readName}
          label="選一檔股票"
          onChange={(i) => {
            if (!i) return
            onPatch(r.id, { symbol: { symbol: i.symbol, code: i.code, name: i.name, market: i.market } })
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

/** 「略過 3 筆股利、1 筆融券」：預設收著；打開是一行一筆（不能勾） */
function Skipped({ rows }: { rows: StatementImport["rows"] }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const summary = skippedSummary(rows)
  if (!summary) return null
  return (
    <div className="mt-4">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="inline-flex min-h-9 items-center gap-1 text-md text-ink-2 underline decoration-ctl underline-offset-4 hover:text-ink hover:decoration-ink pointer-coarse:min-h-11"
      >
        {summary}
        <ChevronDownIcon aria-hidden className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul id={id} className="mt-1 border-t border-rule">
          {rows.map((r) => {
            const c = r.candidate
            const what = c.type === "cash_dividend" ? "現金股利" : c.type === "stock_dividend" ? "配股" : c.type === "sell" ? "融券賣出" : "融券"
            const amount = c.amount ? formatMoney(c.amount) : c.quantity ? `${formatNumber(c.quantity)} 股` : ""
            return (
              <li key={r.row_id} className="flex flex-wrap items-baseline gap-x-3 border-b border-rule py-2 text-md">
                <span className="num text-ink-2">{formatDateShort(c.trade_date)}</span>
                <span className="text-ink">{r.raw.name || c.symbol}</span>
                <span className="text-ink-2">{what}</span>
                {amount && <span className="num text-ink">{amount}</span>}
                <span className="w-full text-sm text-ink-2 sm:ml-auto sm:w-auto">{r.flags.find((f) => f.code === "dividend_auto" || f.code === "short_sale")?.message}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
