import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useMemo, useRef, useState } from "react"
import { flushSync } from "react-dom"
import { api, appToday } from "@/api"
import { useCommitPositions } from "@/api/queries"
import { ApiError, type Account, type BatchRejectedRow, type PositionRow, type PositionsCommitResult, type PositionsImport } from "@/api/types"
import { DateField } from "@/components/date-field"
import { FieldError, FormField as Row } from "@/components/form-field"
import { SymbolPicker } from "@/components/symbol-picker"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { formatDateShort, formatMoney, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { AccountSelect } from "../TradeForm"
import { PICK_SYMBOL_CODES, type PickedSymbol } from "./flags"
import { bodyClass, footerClass } from "./layout"
import { replacedText } from "./undo-store"
import {
  applyCheck,
  checkable,
  costTotals,
  currencyOf,
  editPosition,
  estimateHint,
  hasEstimates,
  hasPositionErrors,
  inLedgerLine,
  isEstimatedDate,
  isShortSale,
  namedReplaced,
  POSITION_NOTE_CODES,
  positionErrors,
  priceText,
  replacedIncomeText,
  replacedRecordsText,
  setInclude,
  setReplace,
  toCommitRow,
  toDraftPosition,
  totalCost,
  totalText,
  type DraftPosition,
  type PositionErrors,
  type PositionField,
} from "./positions"

/**
 * 匯入庫存的確認表（DESIGN.md〈匯入庫存〉）：和匯入對帳單同一種草稿語法——石墨淡底、石墨灰虛線、AI 讀的數字是鉛筆的石墨灰，
 * 改過的格子變墨色；算出來的那一格（給的是總成本時的均價、給的是均價時的總成本）是淡墨。
 * 一列一檔：勾選・股票・股數・均價・總成本・買進日期。最上面是帳戶與整批的買進日期（每一檔記成那一天、照券商均價的買進：
 * 均價到那天收盤的漲跌算進那一天的報酬，那一天之前沒有走勢）。沒勾的列退回紙色（不在草稿裡）。
 * 已在帳本的那一檔預設不勾，下面一行寫帳本裡有多少，旁邊「以券商為準」（勾了才匯入，換掉那一檔的舊紀錄——股利、賣出也是）。
 * 簽名格「匯入 N 檔」：先重新檢查（dry_run），有新的問題就停下來；沒有就一次寫入（全部或全不）。
 */

export interface ReplacedName {
  name: string
  deleted: number
}

/** 這一列的名稱（還沒選股票時是畫面上寫的；都沒有時是「第 3 檔」） */
const rowName = (d: DraftPosition, n: number) => d.symbol?.name ?? (d.readName || `第 ${n} 檔`)

export function PositionsReview({
  doc,
  accounts,
  initialAccountId,
  sheet,
  restartLabel,
  onDone,
  onCancel,
  onRestart,
}: {
  doc: PositionsImport
  accounts: Account[]
  /** 先選好的帳戶（畫面上的券商對到的）；和讀的時候檢查的帳戶不同時，一打開就照它重新檢查 */
  initialAccountId: string
  sheet: boolean
  restartLabel: string
  onDone: (result: PositionsCommitResult, count: number, replaced: ReplacedName[]) => void
  onCancel: () => void
  onRestart: () => void
}) {
  const commit = useCommitPositions()
  const [accountId, setAccountId] = useState(initialAccountId)
  const [batchDate, setBatchDate] = useState(doc.trade_date)
  const [rows, setRows] = useState<DraftPosition[]>(() => doc.rows.filter((r) => !isShortSale(r)).map(toDraftPosition))
  const [showErrors, setShowErrors] = useState(false)
  const recheckOnMount = initialAccountId !== doc.account_id
  const [busy, setBusy] = useState<"checking" | "saving" | "recheck" | null>(recheckOnMount ? "recheck" : null)
  const [notice, setNotice] = useState<string | null>(null)
  /** 表上的「已在帳本」是照哪個帳戶算的 */
  const checkedFor = useRef(doc.account_id)
  /** 最新一次檢查（換帳戶換得快時，舊的結果不寫回表格） */
  const checkSeq = useRef(0)
  const skipped = useMemo(() => doc.rows.filter(isShortSale), [doc.rows])
  const included = rows.filter((r) => r.include)
  const today = appToday()
  const dateHintId = useId()
  // 資產組成原型：伺服器有給估計的買入日（舊版伺服器沒有，照舊整批一個日期）
  const estimates = hasEstimates(rows)

  const patch = (id: string, p: Partial<Pick<DraftPosition, PositionField>>) => setRows((rs) => rs.map((r) => (r.id === id ? editPosition(r, p) : r)))
  const onInclude = (id: string, on: boolean) => setRows((rs) => rs.map((r) => (r.id === id ? setInclude(r, on) : r)))
  const onReplace = (id: string, on: boolean) => setRows((rs) => rs.map((r) => (r.id === id ? setReplace(r, on) : r)))

  /**
   * 重新檢查（dry_run，不呼叫 AI）：送出檢查得了的每一列（沒勾的也送，才知道換了帳戶、換了股票之後在不在帳本）。
   * 結果併進表格；檢查途中自己又改了的列，只更新帳本那一行。回傳檢查結果變了的列數、勾著卻寫不進去的列數、怪不到哪一列的問題。
   */
  const recheck = async (list: DraftPosition[], account: string, date: string): Promise<{ changed: number; blocking: number; problems: string[]; stale?: boolean }> => {
    const seq = ++checkSeq.current
    const sent = list.filter(checkable)
    const accountChanged = account !== checkedFor.current
    const check = sent.length ? await api.checkPositions({ account_id: account, trade_date: date, rows: sent.map((d) => toCommitRow(d, date, doc.trade_date)) }) : { rows: [], problems: [] }
    if (seq !== checkSeq.current) return { changed: 0, blocking: 0, problems: [], stale: true }
    checkedFor.current = account
    const result = applyCheck(list, sent, check, accountChanged)
    const before = new Map(list.map((d) => [d.id, d]))
    const after = new Map(result.rows.map((d) => [d.id, d]))
    setRows((rs) =>
      rs.map((r) => {
        const out = after.get(r.id)
        if (!out) return r
        if (r === before.get(r.id)) return out
        // 檢查途中又改了這一列：保留改的，只換帳本那一行。新出現在帳本的照樣不勾；換了帳戶時，檢查途中勾的以券商為準
        // 是對舊的帳戶勾的，拿掉（新的帳戶也有這一檔就連勾選一起，讓使用者對新的帳戶重新勾）；不在帳本了就沒有東西可換
        const reset = !!out.inLedger && (!r.inLedger || accountChanged)
        return { ...r, inLedger: out.inLedger, ...(reset ? { include: false, replace: false } : !out.inLedger ? { replace: false } : {}) }
      }),
    )
    return { changed: result.changed, blocking: result.blocking, problems: check.problems.map((p) => p.message) }
  }

  const recheckSilently = (list: DraftPosition[], account: string) => {
    setBusy("recheck")
    void recheck(list, account, batchDate)
      .catch(() => undefined)
      .finally(() => setBusy((b) => (b === "recheck" ? null : b)))
  }
  // 畫面上的券商對到另一個帳戶：一打開就照那個帳戶重新檢查
  useEffect(() => {
    if (!recheckOnMount) return
    const t = window.setTimeout(() => recheckSilently(rows, initialAccountId), 0)
    return () => window.clearTimeout(t)
    // 只在第一次打開時
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 選了另一檔股票：照那一檔重新檢查在不在帳本
  const pickSymbol = (id: string, symbol: PickedSymbol) => {
    const next = rows.map((r) => (r.id === id ? editPosition(r, { symbol }) : r))
    setRows(next)
    recheckSilently(next, accountId)
  }

  const sign = async () => {
    const bad = included.filter((d) => hasPositionErrors(positionErrors(d, batchDate, today)))
    const first = bad[0]
    // 點名第一檔（「台光電還沒填好。」）；手機的欄位要等錯誤畫出來才在，所以先畫完，再把焦點移過去、捲到畫面中間
    const name = first ? rowName(first, rows.indexOf(first) + 1) : ""
    flushSync(() => {
      setShowErrors(true)
      setNotice(first ? (bad.length > 1 ? `${name}等 ${bad.length} 檔還沒填好。` : `${name}還沒填好。`) : null)
    })
    if (included.length === 0) return
    if (first) {
      const e = positionErrors(first, batchDate, today)
      const field = e.symbol ? "symbol" : e.qty ? "qty" : e.price ? "price" : e.total ? "total" : "date"
      const el = document.getElementById(field === "date" && !first.date ? "pos-batch-date" : `pos-${field}-${first.id}`)
      el?.scrollIntoView({ block: "center" })
      el?.focus({ preventScroll: true })
      return
    }
    setBusy("checking")
    try {
      const check = await recheck(rows, accountId, batchDate)
      if (check.stale) return
      if (check.changed) {
        setNotice(`有 ${check.changed} 檔的檢查結果變了，看過再按一次。`)
        return
      }
      if (check.blocking) {
        setNotice(`有 ${check.blocking} 檔不能匯入。取消勾選，或改好再按一次。`)
        return
      }
      if (check.problems.length) {
        setNotice(check.problems.join(" "))
        return
      }
      setBusy("saving")
      const result = await commit.mutateAsync({ account_id: accountId, trade_date: batchDate, rows: included.map((d) => toCommitRow(d, batchDate, doc.trade_date)) })
      onDone(result, included.length, namedReplaced(result.replaced, included))
    } catch (e) {
      const failing = e instanceof ApiError && Array.isArray(e.extra.rows) ? (e.extra.rows as BatchRejectedRow[]) : null
      if (failing?.length) {
        // 有一檔不行就一檔都不寫（也不刪）：原因寫在那幾列下面，表格留著讓你改
        const byId = new Map(failing.filter((f) => f.index !== null).map((f) => [included[f.index!]?.id, f]))
        const whole = failing.filter((f) => f.index === null).map((f) => f.message)
        setRows((rs) =>
          rs.map((r) => {
            const f = byId.get(r.id)
            if (!f) return r
            return r.flags.some((x) => x.code === f.code) ? r : { ...r, flags: [...r.flags, { code: f.code, message: f.message, severity: "error" }] }
          }),
        )
        setNotice([byId.size ? `有 ${byId.size} 檔不能匯入，所以這次什麼都沒有寫進帳本。改好再按一次。` : "這次什麼都沒有寫進帳本。", ...whole].join(" "))
      } else {
        setNotice(`沒有匯入成功，表格還在。${e instanceof Error && e.message ? e.message : ""}`)
      }
    } finally {
      setBusy(null)
    }
  }

  const facts = [doc.broker_name, `讀到 ${doc.rows.length} 檔`, doc.merged_duplicates > 0 ? `重疊的 ${doc.merged_duplicates} 列只算一次` : ""].filter(Boolean).join("・")
  const totals = costTotals(rows)
  const replacing = dedupeReplacing(included)
  const errorsOf = (d: DraftPosition): PositionErrors => (showErrors && d.include ? positionErrors(d, batchDate, today) : {})
  const rowProps = { batchDate, onPatch: patch, onPick: pickSymbol, onInclude, onReplace }

  return (
    <>
      <div className={bodyClass(sheet)}>
        <div className="flex flex-col gap-2.5 pb-4">
          {/* 帳戶與日期並排（手機也是：表格在下面，上面不要佔掉半個畫面；手機的日期寫短一點） */}
          <div className={cn("grid gap-x-3 gap-y-3 sm:max-w-xl sm:gap-x-5", accounts.length > 1 && "grid-cols-2")}>
            {accounts.length > 1 && (
              <Row label="匯入到哪個帳戶">
                <AccountSelect
                  accounts={accounts}
                  value={accountId}
                  onChange={(id) => {
                    setAccountId(id)
                    recheckSilently(rows, id)
                  }}
                />
              </Row>
            )}
            <Row label="買進日期" htmlFor="pos-batch-date">
              <DateField
                id="pos-batch-date"
                value={batchDate}
                onChange={setBatchDate}
                max={today}
                describedBy={dateHintId}
                invalid={showErrors && !batchDate}
                // 手機和帳戶並排時寫短、不放圖示（320 寬也放得下「11/12（四）」）
                format={sheet && accounts.length > 1 ? shortDate : undefined}
                icon={!(sheet && accounts.length > 1)}
              />
            </Row>
          </div>
          <p id={dateHintId} className="text-sm text-ink-2">
            {/* 資產組成原型：伺服器估了買入日時照實說估到幾檔（`estimateHint`）；舊版伺服器照原本那一句 */}
            {estimateHint(rows) ?? "損益照券商均價算；均價到這天收盤的漲跌會算進這天的報酬，這天之前沒有走勢。每一檔也可以改日期。"}
          </p>
          <p className="num text-sm text-ink-2">{facts}</p>
          {doc.unreadable.length > 0 && <p className="text-base text-ink">沒讀清楚：{doc.unreadable.join("、")}。</p>}
          {doc.embedded_instructions.length > 0 && (
            <div>
              <p className="text-base text-ink">截圖或文字裡有一段像指令的字，沒有照做。</p>
              {doc.embedded_instructions.map((q) => (
                <p key={q} className="mt-1 line-clamp-2 text-sm break-all text-ink-2">
                  「{q}」
                </p>
              ))}
            </div>
          )}
        </div>

        <div className="border border-dashed border-ai-rule bg-ai-wash" aria-busy={busy === "recheck" || undefined}>
          {sheet ? (
            <ul aria-label="讀出來的持股">
              {rows.map((d, i) => (
                <MobileRow key={d.id} row={d} n={i + 1} errors={errorsOf(d)} {...rowProps} />
              ))}
            </ul>
          ) : (
            <table className="w-full table-fixed border-collapse text-md">
              <caption className="sr-only">讀出來的持股：勾選的會匯入，每一檔記成一筆買進</caption>
              <colgroup>
                {/* 勾選欄 56px：pl-3 之後還有 44px，觸控的平板（桌面版面）也按得到整格 */}
                <col className="w-14" />
                <col />
                <col className="w-[7rem]" />
                <col className="w-[7rem]" />
                <col className="w-[8.5rem]" />
                {/* 資產組成原型：「估計 2024/8/14」比較長，日期欄寬一點 */}
                <col className={estimates ? "w-[10rem]" : "w-[8.5rem]"} />
              </colgroup>
              <thead className="sticky top-0 z-10 bg-ai-wash">
                <tr className="form-head text-left text-sm text-ink-2">
                  <th scope="col" className="py-2 pl-3 font-normal">
                    <span className="sr-only">匯入</span>
                  </th>
                  <th scope="col" className="px-1.5 py-2 font-normal">股票</th>
                  <th scope="col" className="px-1.5 py-2 text-right font-normal">股數</th>
                  <th scope="col" className="px-1.5 py-2 text-right font-normal">均價</th>
                  <th scope="col" className="px-1.5 py-2 text-right font-normal">總成本</th>
                  <th scope="col" className="py-2 pr-3 pl-6 font-normal">買進日期</th>
                </tr>
              </thead>
              {rows.map((d, i) => (
                <DesktopRow key={d.id} row={d} n={i + 1} errors={errorsOf(d)} {...rowProps} />
              ))}
              <tfoot>
                <tr className="border-t border-ai-rule">
                  <td />
                  <td className="px-1.5 py-2.5 text-sm text-ink-2">
                    勾選的 <span className="num">{included.length}</span> 檔
                  </td>
                  <td colSpan={3} className="num px-1.5 py-2.5 text-right font-bold text-ai">
                    <Totals totals={totals} />
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          )}
          {sheet && (
            <p className="num flex items-baseline justify-between gap-3 border-t border-ai-rule px-3 py-2.5 text-sm text-ink-2">
              勾選的 {included.length} 檔
              <span className="text-base font-bold text-ai">
                <Totals totals={totals} />
              </span>
            </p>
          )}
        </div>

        {skipped.length > 0 && <Skipped rows={skipped} />}
      </div>

      <div className={footerClass(sheet)}>
        {replacing.length > 0 && (
          <p className="w-full text-base text-ink">
            以券商為準會刪掉{replacedText(replacing)}舊紀錄{replacedIncomeText(replacing) ? `，連同${replacedIncomeText(replacing)}` : ""}（定期定額不動），復原時也不會回來。
          </p>
        )}
        {notice && (
          <p role="alert" className="w-full text-base font-medium text-ink">
            {notice}
          </p>
        )}
        <button type="button" onClick={onRestart} className={cn(textAction, "text-sm text-ink-2 hover:text-ink")}>
          {restartLabel}
        </button>
        <div className="ml-auto flex items-center gap-2.5">
          <Button type="button" variant="outline" onClick={onCancel}>
            取消
          </Button>
          <button
            type="button"
            className="sign-box w-auto min-w-[76px] px-3 disabled:bg-hov disabled:text-ink-2 disabled:inset-ring disabled:inset-ring-rule disabled:after:opacity-0"
            aria-label={`簽名：匯入 ${included.length} 檔`}
            disabled={included.length === 0 || busy !== null}
            onClick={() => void sign()}
          >
            <small className="text-xs font-normal opacity-85">{busy === "checking" ? "檢查中" : busy === "saving" ? "寫入中" : "簽名"}</small>
            <span className="num whitespace-nowrap">匯入 {included.length} 檔</span>
          </button>
        </div>
      </div>
    </>
  )
}

/** 以券商為準要換掉的（同一檔好幾列只算一次）：名稱與帳本裡的紀錄筆數（其中幾筆股利、幾筆賣出） */
function dedupeReplacing(rows: DraftPosition[]): (ReplacedName & { dividends: number; sells: number })[] {
  const seen = new Map<string, ReplacedName & { dividends: number; sells: number }>()
  for (const d of rows)
    if (d.replace && d.symbol && d.inLedger && !seen.has(d.symbol.symbol))
      seen.set(d.symbol.symbol, { name: d.symbol.name, deleted: d.inLedger.records, dividends: d.inLedger.dividends, sells: d.inLedger.sells })
  return [...seen.values()]
}

function Totals({ totals }: { totals: { TWD: number; USD: number } }) {
  const parts = [totals.TWD || !totals.USD ? formatMoney(totals.TWD) : null, totals.USD ? formatMoney(totals.USD, { currency: "USD" }) : null].filter(Boolean)
  return (
    <span className="inline-flex flex-col items-end">
      {parts.map((p) => (
        <span key={p}>{p}</span>
      ))}
    </span>
  )
}

// ── 一列 ─────────────────────────────────────────────────

interface RowProps {
  row: DraftPosition
  n: number
  errors: PositionErrors
  batchDate: string
  onPatch: (id: string, p: Partial<Pick<DraftPosition, PositionField>>) => void
  onPick: (id: string, symbol: PickedSymbol) => void
  onInclude: (id: string, on: boolean) => void
  onReplace: (id: string, on: boolean) => void
}

/** AI 讀的是鉛筆（石墨灰），使用者改過的是墨水 */
const tone = (d: DraftPosition, k: PositionField) => (d.edited.has(k) ? "text-ink" : "text-ai")
const nameOf = (d: DraftPosition) => d.symbol?.name ?? (d.readName || "沒有股票")
const fmtTotal = (d: DraftPosition) => {
  const t = totalCost(d)
  return t === null ? "—" : formatMoney(t, { currency: currencyOf(d) })
}

/** 短日期：今年的「11/12（四）」，別年的「2025/11/12」（不放星期，窄的格子也放得下） */
function shortDate(v: string): string {
  return v.slice(0, 4) === appToday().slice(0, 4) ? formatDateShort(v) : `${v.slice(0, 4)}/${formatDateShort(v, false)}`
}
/** 更短的（手機一列裡的「・11/5 買進」）：今年的不寫年 */
const dayText = (v: string) => (v.slice(0, 4) === appToday().slice(0, 4) ? formatDateShort(v, false) : `${v.slice(0, 4)}/${formatDateShort(v, false)}`)

/** 沒勾的列退回紙色（不在草稿裡、不會寫入），字是淡墨；勾著的留在石墨淡底上。字的對比都在 4.5:1 以上 */
const offRow = "bg-paper"

const cellInput =
  "num h-9 w-full min-w-0 rounded-sm border border-transparent bg-transparent px-1.5 text-md outline-none transition-colors hover:border-ctl focus-visible:border-ink focus-visible:bg-raised aria-invalid:border-ink aria-invalid:bg-raised pointer-coarse:h-11 pointer-coarse:text-[1rem]"

function DesktopRow({ row: d, n, errors, batchDate, onPatch, onPick, onInclude, onReplace }: RowProps) {
  const nth = `第 ${n} 檔的`
  const off = !d.include
  const errorText = Object.values(errors).filter(Boolean)
  const hasNotes = d.flags.length > 0 || errorText.length > 0 || !!d.inLedger
  return (
    <tbody className={cn("border-b border-rule last:border-b-0", off && cn(offRow, "[&_input]:text-ink-2"))}>
      <tr className="align-middle">
        <td className="py-1.5 pl-3">
          <IncludeBox row={d} onInclude={onInclude} />
        </td>
        <td className="px-1.5 py-1.5">
          <StockCell row={d} n={n} invalid={!!errors.symbol} onPick={onPick} />
        </td>
        <NumCell row={d} field="qty" value={d.qty} label={`${nth}股數`} placeholder="股數" invalid={!!errors.qty} onPatch={onPatch} />
        <NumCell row={d} field="price" value={priceText(d)} label={`${nth}均價`} placeholder="均價" invalid={!!errors.price} onPatch={onPatch} derived={d.basis !== "price"} />
        <NumCell row={d} field="total" value={totalText(d)} label={`${nth}總成本`} placeholder="總成本" invalid={!!errors.total} onPatch={onPatch} derived={d.basis !== "total"} />
        <td className="py-1.5 pr-2 pl-5">
          <RowDate row={d} batchDate={batchDate} label={`${nth}買進日期`} invalid={!!errors.date} onPatch={onPatch} compact />
        </td>
      </tr>
      {hasNotes && (
        <tr>
          <td />
          <td colSpan={5} className="px-1.5 pb-2.5">
            <Notes row={d} errors={errorText} onPick={onPick} onReplace={onReplace} />
          </td>
        </tr>
      )}
    </tbody>
  )
}

function MobileRow({ row: d, n, errors, batchDate, onPatch, onPick, onInclude, onReplace }: RowProps) {
  const [editing, setEditing] = useState(false)
  const nth = `第 ${n} 檔的`
  const off = !d.include
  const errorText = Object.values(errors).filter(Boolean)
  const open = editing || errorText.length > 0
  const price = priceText(d)
  return (
    <li className={cn("flex gap-1 border-b border-rule py-2.5 pr-3 pl-1 last:border-b-0", off && offRow)}>
      <IncludeBox row={d} onInclude={onInclude} />
      <div className="min-w-0 flex-1 pt-2.5">
        {/* 名稱不截斷（太長就換行，代號跟在後面）：要靠名稱核對每一列。「已在帳本」不放這裡——下面那一句已經說了 */}
        <div className="flex items-baseline justify-between gap-3">
          <p className={cn("min-w-0 text-lg font-medium break-words", off ? "text-ink-2" : d.symbol ? tone(d, "symbol") : "text-ink-2")}>
            {nameOf(d)}
            {d.symbol && <span className="num ml-1.5 text-sm font-normal whitespace-nowrap text-ink-2">{d.symbol.code}</span>}
          </p>
          <p className={cn("num shrink-0 text-base font-bold", off ? "text-ink-2" : "text-ai")}>{fmtTotal(d)}</p>
        </div>
        <div className="flex items-center justify-between gap-3">
          <p className={cn("num text-md", off ? "text-ink-2" : "text-ai")}>
            {d.qty ? `${d.qty} 股` : "—"}・均價 {price || "—"}
            {d.date && d.date !== batchDate && !isEstimatedDate(d) ? `・${dayText(d.date)} 買進` : ""}
            {/* 資產組成原型：估計的買入日自己一行（「・」不會掛在行尾），算出來的是淡墨 */}
            {isEstimatedDate(d) && <span className="block text-sm text-ink-2">估計 {dayText(d.date)} 買進</span>}
          </p>
          {!open && (
            <button type="button" onClick={() => setEditing(true)} className={cn(textAction, "shrink-0")} aria-label={`修改第 ${n} 檔：${nameOf(d)}`}>
              修改
            </button>
          )}
        </div>
        {/* 沒填好的格子：原因只寫在欄位下面（欄位一定是打開的），這裡不再寫一次；打開時「選一檔」就是上面的股票欄位 */}
        {(d.flags.length > 0 || d.inLedger) && (
          <div className="mt-2">
            <Notes row={d} errors={[]} onPick={onPick} onReplace={onReplace} pick={!open} />
          </div>
        )}
        {open && (
          // 360 寬以下一欄一格（日期放得下）；以上兩欄
          <div className="mt-3 grid grid-cols-1 gap-x-3 gap-y-3 pb-1 min-[360px]:grid-cols-2">
            <div className="min-[360px]:col-span-2">
              <MobileField label="股票" id={`pos-symbol-${d.id}`} error={errors.symbol}>
                <StockCell row={d} n={n} invalid={!!errors.symbol} onPick={onPick} boxed />
              </MobileField>
            </div>
            <MobileField label="股數" id={`pos-qty-${d.id}`} error={errors.qty}>
              <Input id={`pos-qty-${d.id}`} inputMode="decimal" autoComplete="off" value={d.qty} onChange={(e) => onPatch(d.id, { qty: e.target.value })} aria-invalid={!!errors.qty || undefined} className="num" />
            </MobileField>
            <MobileField label="買進日期" id={`pos-date-${d.id}`} error={errors.date}>
              <RowDate row={d} batchDate={batchDate} label={`${nth}買進日期`} invalid={!!errors.date} onPatch={onPatch} />
            </MobileField>
            <MobileField label="均價" id={`pos-price-${d.id}`} error={errors.price}>
              <Input
                id={`pos-price-${d.id}`}
                inputMode="decimal"
                autoComplete="off"
                value={price}
                onChange={(e) => onPatch(d.id, { price: e.target.value })}
                aria-invalid={!!errors.price || undefined}
                className={cn("num", d.basis !== "price" && "text-ink-2")}
              />
            </MobileField>
            <MobileField label="總成本" id={`pos-total-${d.id}`} error={errors.total}>
              <Input
                id={`pos-total-${d.id}`}
                inputMode="decimal"
                autoComplete="off"
                value={totalText(d)}
                onChange={(e) => onPatch(d.id, { total: e.target.value })}
                aria-invalid={!!errors.total || undefined}
                className={cn("num", d.basis !== "total" && "text-ink-2")}
              />
            </MobileField>
            <button type="button" onClick={() => setEditing(false)} className={cn(textAction, "self-start justify-self-start min-[360px]:col-span-2")}>
              完成
            </button>
          </div>
        )}
      </div>
    </li>
  )
}

function MobileField({ label, id, error, children }: { label: string; id: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="print-label text-sm">
        {label}
      </label>
      {children}
      {error && <FieldError>{error}</FieldError>}
    </div>
  )
}

/**
 * 勾選：看得到的是 18px 的格子，可按範圍 44px。已在帳本的那一檔，勾了就是以券商為準（會刪掉舊紀錄）：
 * 名稱照實說（「匯入並以券商為準：台積電，刪掉 15 筆紀錄（含 3 筆股利）」），說明指到帳本那一句
 */
function IncludeBox({ row: d, onInclude }: { row: DraftPosition; onInclude: RowProps["onInclude"] }) {
  const h = d.inLedger
  return (
    <label className="grid size-11 shrink-0 cursor-pointer place-items-center">
      <input
        type="checkbox"
        checked={d.include}
        onChange={(e) => onInclude(d.id, e.target.checked)}
        aria-label={h ? `匯入並以券商為準：${nameOf(d)}，刪掉 ${replacedRecordsText(h)}` : `匯入：${nameOf(d)}${d.symbol ? "" : "（還沒選股票）"}`}
        aria-describedby={h ? ledgerLineId(d) : undefined}
        className="size-[18px] cursor-pointer accent-[var(--act)]"
      />
    </label>
  )
}

const ledgerLineId = (d: DraftPosition) => `pos-ledger-${d.id}`

/** 數字格：AI 讀的是鉛筆、改過的是墨水，算出來的（`derived`）是淡墨 */
function NumCell({
  row: d,
  field,
  value,
  label,
  placeholder,
  invalid,
  onPatch,
  derived,
}: {
  row: DraftPosition
  field: "qty" | "price" | "total"
  value: string
  label: string
  placeholder: string
  invalid: boolean
  onPatch: RowProps["onPatch"]
  derived?: boolean
}) {
  return (
    <td className="px-0.5 py-1.5">
      <input
        id={`pos-${field}-${d.id}`}
        inputMode="decimal"
        autoComplete="off"
        value={value}
        onChange={(e) => onPatch(d.id, { [field]: e.target.value })}
        aria-label={label}
        aria-invalid={invalid || undefined}
        placeholder={placeholder}
        className={cn(cellInput, "text-right placeholder:text-ink-2/70", derived ? "text-ink-2" : tone(d, field))}
      />
    </td>
  )
}

/**
 * 這一列的買進日期：沒改過的跟著整批（淡墨），改過的是墨色；選回整批的日期就又跟著整批。
 * 表格裡（`compact`）和手機的半欄都寫短、不放圖示（手機半欄在 360 寬只有約 100px）
 */
function RowDate({ row: d, batchDate, label, invalid, onPatch, compact }: { row: DraftPosition; batchDate: string; label: string; invalid: boolean; onPatch: RowProps["onPatch"]; compact?: boolean }) {
  // 資產組成原型：沒改過的估計寫「估計 2024/8/14」，算出來的（和跟著整批的一樣）是淡墨；改過就是墨色、不再寫估計
  const estimated = isEstimatedDate(d)
  const own = !!d.date && !estimated
  return (
    <DateField
      id={`pos-date-${d.id}`}
      value={d.date || batchDate}
      onChange={(date) => onPatch(d.id, { date: date === batchDate ? "" : date })}
      label={estimated ? `${label}（估計）` : label}
      invalid={invalid}
      icon={false}
      placeholder="選日期"
      format={estimated ? (v) => `估計 ${shortDate(v)}` : shortDate}
      className={compact ? cn(cellInput, "px-1.5", own ? "text-ink" : "text-ink-2") : own ? undefined : "text-ink-2"}
    />
  )
}

/** 股票：按一下換一檔（找不到、對到好幾檔時是「選股票」，先用畫面上的名稱搜） */
function StockCell({ row: d, n, invalid, onPick, boxed }: { row: DraftPosition; n: number; invalid: boolean; onPick: RowProps["onPick"]; boxed?: boolean }) {
  const [open, setOpen] = useState(false)
  const id = `pos-symbol-${d.id}`
  const trigger = d.symbol ? (
    <PopoverTrigger
      id={id}
      aria-label={`第 ${n} 檔的股票：${d.symbol.name} ${d.symbol.code}${d.inLedger ? "（已在帳本）" : ""}，按一下換一檔`}
      className={cn(
        "flex w-full min-w-0 flex-col items-start rounded-sm border text-left outline-none focus-visible:border-ink",
        boxed ? "h-11 justify-center border-input bg-raised px-3" : "justify-center border-transparent px-1.5 py-0.5 hover:border-ctl pointer-coarse:min-h-11",
      )}
    >
      <span className={cn("w-full truncate leading-snug", d.include ? tone(d, "symbol") : "text-ink-2")}>{d.symbol.name}</span>
      <span className="flex items-center gap-1.5 text-sm leading-tight text-ink-2">
        <span className="num">{d.symbol.code}</span>
        {!boxed && d.inLedger && <span className="status-tag">已在帳本</span>}
      </span>
    </PopoverTrigger>
  ) : (
    <PopoverTrigger
      id={id}
      aria-invalid={invalid || undefined}
      aria-label={`第 ${n} 檔的股票：還沒選${d.readName ? `（畫面上寫「${d.readName}」）` : ""}`}
      // 表格裡往右挪 4px：觸控時文字動作左右多出的可按範圍（10px）才不會蓋到左邊勾選格的 44px
      className={cn(textAction, "font-medium", boxed ? "h-11" : "ml-1")}
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
          initialQuery={d.symbol ? "" : d.readName}
          label={`第 ${n} 檔的股票`}
          onChange={(i) => {
            if (!i) return
            onPick(d.id, { symbol: i.symbol, code: i.code, name: i.name, market: i.market })
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

/**
 * 那一列下面的句子：帳本那一行＋「以券商為準」；伺服器的句子（要處理的 15px 墨色，融資、別的帳戶也有是 13px 淡墨）；
 * 找不到股票旁邊「選一檔」；沒填好的格子
 */
function Notes({
  row: d,
  errors,
  onPick,
  onReplace,
  pick = true,
}: {
  row: DraftPosition
  errors: string[]
  onPick: RowProps["onPick"]
  onReplace: RowProps["onReplace"]
  /** 句子旁邊的「選一檔」（手機打開欄位時不放：股票欄位就在下面） */
  pick?: boolean
}) {
  const seen = new Set<string>()
  const flags = d.flags.filter((f) => (seen.has(f.code) ? false : (seen.add(f.code), true)))
  const ledger = inLedgerLine(d)
  return (
    <ul className="flex flex-col gap-1">
      {ledger && d.inLedger && (
        <li className="flex flex-col gap-0.5">
          <span id={ledgerLineId(d)} className="text-base text-ink">
            {ledger}
          </span>
          <label className="flex min-h-9 w-fit cursor-pointer items-center gap-2.5 text-base pointer-coarse:min-h-11">
            <input type="checkbox" checked={d.replace} onChange={(e) => onReplace(d.id, e.target.checked)} className="size-[18px] shrink-0 cursor-pointer accent-[var(--act)]" />
            <span>
              <span className="font-medium text-ink">以券商為準</span>
              <span className="text-ink-2">：刪掉帳本裡這一檔的 {replacedRecordsText(d.inLedger)}，換成這一筆</span>
            </span>
          </label>
        </li>
      )}
      {flags.map((f) => {
        const note = POSITION_NOTE_CODES.has(f.code)
        return (
          <li key={f.code} className={cn("flex flex-wrap items-baseline gap-x-3", note ? "text-sm text-ink-2" : "text-base text-ink", f.severity === "error" && "font-medium")}>
            <span>{f.message}</span>
            {pick && PICK_SYMBOL_CODES.has(f.code) && !d.symbol && <PickInline row={d} onPick={onPick} />}
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

/** 訊息旁邊的「選一檔」（表格那一格也可以選；這裡是句子旁邊多一個入口） */
function PickInline({ row: d, onPick }: { row: DraftPosition; onPick: RowProps["onPick"] }) {
  const [open, setOpen] = useState(false)
  const labelId = useId()
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger className={cn(textAction, "font-normal")} aria-describedby={labelId}>
        選一檔
      </PopoverTrigger>
      <span id={labelId} className="sr-only">
        {d.readName ? `畫面上寫「${d.readName}」` : ""}
      </span>
      <PopoverContent align="start" className="w-80">
        <SymbolPicker
          value={null}
          initialQuery={d.readName}
          label="選一檔股票"
          onChange={(i) => {
            if (!i) return
            onPick(d.id, { symbol: i.symbol, code: i.code, name: i.name, market: i.market })
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

/** 「略過 1 檔融券」：預設收著；打開是一行一檔（不能勾） */
function Skipped({ rows }: { rows: PositionRow[] }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className="mt-4">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="inline-flex min-h-9 items-center gap-1 text-md text-ink-2 underline decoration-ctl underline-offset-4 hover:text-ink hover:decoration-ink pointer-coarse:min-h-11"
      >
        略過 {rows.length} 檔融券
        <ChevronDownIcon aria-hidden className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul id={id} className="mt-1 border-t border-rule">
          {rows.map((r) => (
            <li key={r.row_id} className="flex flex-wrap items-baseline gap-x-3 border-b border-rule py-2 text-md">
              <span className="text-ink">{r.name}</span>
              {r.quantity !== null && <span className="num text-ink-2">{formatNumber(r.quantity)} 股</span>}
              <span className="w-full text-sm text-ink-2 sm:ml-auto sm:w-auto">{r.flags.find((f) => f.code === "short_sale")?.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
