import type { Currency, ImportFlag, LedgerHolding, PositionRow, PositionsCommitCheck, PositionsCommitRow, PositionsReplaced } from "@/api/types"
import { formatMoney, formatNumber } from "@/lib/format"
import { parseNumber } from "../quantity-input"
import { PICK_SYMBOL_CODES, symbolFromCode, type PickedSymbol } from "./flags"

/**
 * 匯入庫存的確認表（產品負責人 2026-11-17，四項照建議；不碰畫面，測試得到）：
 * - 伺服器回的每一列（`PositionRow`）變成可以改的 `DraftPosition`：股票、股數、均價或總成本（二選一，另一格照它算）、
 *   這一列自己的買進日期（空的就是整批的日期）。
 * - 已在帳本（這個帳戶現在有這一檔）預設不匯入；「以券商為準」和勾選綁在一起：勾了才匯入、匯入時換掉那一檔的舊紀錄。
 *   以券商為準是對一個帳戶、一檔股票勾的：換了帳戶或股票就拿掉，對新的帳戶重新勾。
 *   帳本那一行（「帳本裡已經有 1,500 股，均價 585.27。」）照 `in_ledger` 的數字寫，換帳戶、改了股數或均價都跟著變。
 * - 重新檢查（`POST /imports/positions/commit` 的 dry_run）：換帳戶、改了股票或日期之後、簽名之前；不呼叫 AI。
 * - 寫入：每一檔一筆買進，手續費 0（券商的均價多半已含手續費），帳本的均價就等於券商的。
 */

export type PositionField = "symbol" | "qty" | "price" | "total" | "date"

export interface DraftPosition {
  /** 伺服器的 row_id */
  id: string
  include: boolean
  symbol: PickedSymbol | null
  /** 畫面上寫的名稱（找不到股票時用來搜尋） */
  readName: string
  qty: string
  /** 均價（每股成本）：`basis` 是 price 時是使用者或券商給的，不然照總成本 ÷ 股數算 */
  price: string
  /** 總成本：`basis` 是 total 時是給的，不然照股數 × 均價算 */
  total: string
  basis: "price" | "total"
  /** 這一列自己的買進日期；空字串＝整批的日期 */
  date: string
  /** 以券商為準：換掉這個帳戶裡這一檔的舊紀錄 */
  replace: boolean
  /** 這個帳戶現在已經有這一檔（重新檢查時更新） */
  inLedger: LedgerHolding | null
  /** 伺服器的句子（`in_ledger` 不放在這裡：照 `inLedger` 的數字寫） */
  flags: ImportFlag[]
  /** 使用者改過的格子（鉛筆變墨水） */
  edited: ReadonlySet<PositionField>
  /** 使用者自己勾過或取消過（之後的檢查不再替他改勾選） */
  includeSet: boolean
  /**
   * 估計的買入日（資產組成原型；伺服器的 `estimated_date`）：**只是建議**（產品負責人 2026-11-21）。這一列的日期照舊跟著整批
   * （預設匯入那天），日期旁邊寫「估計 2024/8/14」＋「套用」，按了才改成那天（`applyEstimate`）。
   * 估計是伺服器照讀到的股票與成本算的：改了股票、股數、均價或總成本就拿掉（變成 null，`editPosition`）。
   * null：估不到（五年內股價都沒有經過均價，原因在 `no_crossing` 旗標）或改過股票、成本；undefined：舊版伺服器，照舊整批一個日期
   */
  estimate?: string | null
  /** 按過「套用」（改了股票或成本、估計拿掉時清掉）：日期還是估計的那天時，送出去是 `estimated` */
  applied: boolean
}

/** 重新檢查（dry_run）會再算一次的：每次換成新的 */
const CHECK_CODES: ReadonlySet<string> = new Set([
  "unknown_symbol", "bad_date", "validation_error", "invalid_row", "account_mismatch", "unsupported_type", "oversell", "duplicate", "possible_duplicate", "ledger_inconsistent",
  // 資產組成原型：日期早於匯入以前最近一次分割、減資、配股；估計不是估得到的日子
  "before_share_change", "bad_estimated_date",
])
/** 讀的時候才算得出來的旗標：改了哪幾格就算處理過，直接拿掉 */
const RESOLVED_BY: Readonly<Record<string, readonly PositionField[]>> = {
  unreadable: ["symbol", "qty", "price", "total"],
  cost_mismatch: ["qty", "price", "total"],
  value_mismatch: ["qty"],
  unit_fixed: ["qty"],
  fractional_tw_qty: ["qty"],
  not_whole_lots: ["qty"],
  currency_mismatch: ["symbol", "price", "total"],
  currency_guess: ["symbol", "price", "total"],
  same_symbol_twice: ["symbol"],
  in_other_account: ["symbol"],
  bad_date: ["date"],
  before_share_change: ["date"],
  // 「沒辦法估買入日」是照讀到的股票與成本說的
  no_crossing: ["symbol", "qty", "price", "total"],
}
/** 估計的買入日是照這幾格算的（伺服器讀的時候）：改了就不算數 */
const ESTIMATE_INPUTS: readonly PositionField[] = ["symbol", "qty", "price", "total"]
/** 和後端的 EXCLUDED 相同：預設不勾（任何 error 也不勾） */
const EXCLUDED_CODES: ReadonlySet<string> = new Set(["unknown_symbol", "ambiguous_symbol", "unreadable", "fractional_tw_qty", "currency_mismatch", "short_sale", "in_ledger"])
/** 標籤（不是要處理的問題）：小一號淡墨 */
export const POSITION_NOTE_CODES: ReadonlySet<string> = new Set(["margin", "in_other_account", "no_crossing"])

export const isShortSale = (row: PositionRow) => row.flags.some((f) => f.code === "short_sale")

const numText = (n: number | null | undefined, digits = 6) =>
  n === null || n === undefined || !Number.isFinite(n) ? "" : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(n)

export function toDraftPosition(row: PositionRow): DraftPosition {
  const byTotal = row.price_basis === "total_cost" && row.total_cost !== null
  return {
    id: row.row_id,
    include: row.include,
    symbol: symbolFromCode(row.symbol, row.name),
    readName: row.raw.name || row.raw.symbol_code || row.name,
    qty: numText(row.quantity),
    price: byTotal ? "" : numText(row.price),
    total: byTotal ? numText(row.total_cost) : "",
    basis: byTotal ? "total" : "price",
    // 估計的買入日只是建議：日期照舊跟著整批，按「套用」才改
    date: "",
    replace: false,
    inLedger: row.in_ledger,
    flags: row.flags.filter((f) => f.code !== "in_ledger"),
    edited: new Set(),
    includeSet: false,
    ...(row.estimated_date !== undefined ? { estimate: row.estimated_date } : {}),
    applied: false,
  }
}

/** 這一列的日期是套用的估計（畫面寫「估計 2024/8/14」）：按過「套用」、日期還是那天、估計還在（沒改過股票或成本） */
export const isEstimatedDate = (d: Pick<DraftPosition, "estimate" | "date" | "applied">) => d.applied && typeof d.estimate === "string" && d.date === d.estimate

/** 日期旁邊要建議的估計買入日：有估計、而且這一列現在的日期（空的就是整批的）不是那天；不用建議是 null */
export function suggestedDate(d: Pick<DraftPosition, "estimate" | "date">, batchDate: string): string | null {
  return typeof d.estimate === "string" && (d.date || batchDate) !== d.estimate ? d.estimate : null
}

/** 套用估計的買入日：這一列的日期改成那天（和自己改日期一樣，日期的問題拿掉）；沒有估計時不動 */
export function applyEstimate(d: DraftPosition): DraftPosition {
  if (typeof d.estimate !== "string") return d
  return { ...editPosition(d, { date: d.estimate }), applied: true }
}

export const currencyOf = (d: Pick<DraftPosition, "symbol">): Currency => (d.symbol?.market === "US" ? "USD" : "TWD")
const isTw = (d: Pick<DraftPosition, "symbol">) => !!d.symbol && d.symbol.market !== "US"

/** 每股成本（均價）：給的是總成本時照總成本 ÷ 股數 */
export function unitPrice(d: DraftPosition): number | null {
  if (d.basis === "price") return parseNumber(d.price)
  const q = parseNumber(d.qty)
  const t = parseNumber(d.total)
  return q && t !== null ? t / q : null
}

/** 總成本：給的是均價時照股數 × 均價（四捨五入到分） */
export function totalCost(d: DraftPosition): number | null {
  if (d.basis === "total") return parseNumber(d.total)
  const q = parseNumber(d.qty)
  const p = parseNumber(d.price)
  return q !== null && p !== null ? Math.round(q * p * 100) / 100 : null
}

/** 輸入框裡的字：給的那一格照原樣，另一格是算出來的（均價最多 4 位小數、總成本到分） */
export const priceText = (d: DraftPosition) => (d.basis === "price" ? d.price : numText(unitPrice(d), 4))
export const totalText = (d: DraftPosition) => (d.basis === "total" ? d.total : numText(totalCost(d), 2))

/** 改一格：改了均價就照均價、改了總成本就照總成本；讀的時候的問題，改了相關的格子就拿掉 */
export function editPosition(d: DraftPosition, patch: Partial<Pick<DraftPosition, PositionField>>): DraftPosition {
  const edited = new Set(d.edited)
  const keys = Object.keys(patch) as PositionField[]
  for (const k of keys) edited.add(k)
  const next: DraftPosition = { ...d, ...patch, edited }
  if ("price" in patch) next.basis = "price"
  if ("total" in patch) next.basis = "total"
  next.flags = d.flags.filter((f) => !(RESOLVED_BY[f.code] ?? []).some((k) => keys.includes(k)) && !(keys.includes("symbol") && PICK_SYMBOL_CODES.has(f.code)))
  if ("symbol" in patch && patch.symbol?.symbol !== d.symbol?.symbol) {
    // 換了一檔：帳本裡有沒有要重新檢查，以券商為準先拿掉
    next.inLedger = null
    next.replace = false
  }
  // 估計的買入日是照原本的股票與成本算的：改了就拿掉（不再建議、不會送成估計的）；套用過的日期回到整批的日期
  const changed = (k: PositionField) => (k === "symbol" ? patch.symbol?.symbol !== d.symbol?.symbol : patch[k] !== d[k])
  if (typeof d.estimate === "string" && ESTIMATE_INPUTS.some((k) => k in patch && changed(k))) {
    next.estimate = null
    next.applied = false
    if (isEstimatedDate(d) && !("date" in patch)) next.date = ""
  }
  return next
}

/** 勾選：已在帳本的那一檔，勾了就是以券商為準（不換掉的話伺服器不收：會變成兩倍） */
export function setInclude(d: DraftPosition, include: boolean): DraftPosition {
  return { ...d, include, replace: d.inLedger ? include : false, includeSet: true }
}

/** 以券商為準：和勾選綁在一起 */
export function setReplace(d: DraftPosition, replace: boolean): DraftPosition {
  return { ...d, replace, include: replace, includeSet: true }
}

/** 以券商為準會刪掉的：「15 筆紀錄（含 3 筆股利、1 筆賣出）」（股利與賣出的損益也跟著不見，要說出來） */
export function replacedRecordsText(h: LedgerHolding): string {
  const income = [h.dividends ? `${formatNumber(h.dividends)} 筆股利` : "", h.sells ? `${formatNumber(h.sells)} 筆賣出` : ""].filter(Boolean)
  return `${formatNumber(h.records)} 筆紀錄${income.length ? `（含 ${income.join("、")}）` : ""}`
}

/** 以券商為準一起刪掉的收入：「領過的股利、賣出的損益」；都沒有是空字串 */
export function replacedIncomeText(list: Pick<LedgerHolding, "dividends" | "sells">[]): string {
  const dividends = list.some((h) => h.dividends > 0)
  const sells = list.some((h) => h.sells > 0)
  return [dividends ? "領過的股利" : "", sells ? "賣出的損益" : ""].filter(Boolean).join("、")
}

/** 帳本那一行：股數和均價都一樣時直說（和伺服器讀的時候同一句） */
export function inLedgerLine(d: DraftPosition): string | null {
  const h = d.inLedger
  if (!h) return null
  const q = parseNumber(d.qty)
  const p = unitPrice(d)
  const same = q === h.quantity && p !== null && Math.abs(h.avg_cost - p) <= Math.max(0.01, p * 0.0005)
  if (same) return "帳本裡已經有，股數和均價都一樣。"
  const avg = h.avg_cost >= 10 ? Math.round(h.avg_cost * 100) / 100 : h.avg_cost
  return `帳本裡已經有 ${numText(h.quantity)} 股，均價 ${numText(avg, 4)}。`
}

export interface PositionErrors {
  symbol?: string
  qty?: string
  price?: string
  total?: string
  date?: string
}

/** 勾著的列在簽名前要過的基本檢查（伺服器另外再檢查一次） */
export function positionErrors(d: DraftPosition, batchDate: string, today: string): PositionErrors {
  const e: PositionErrors = {}
  if (!d.symbol) e.symbol = "請選股票"
  const q = parseNumber(d.qty)
  if (q === null || !(q > 0)) e.qty = "請輸入股數"
  else if (isTw(d) && !Number.isInteger(q)) e.qty = "台股的股數要是整數"
  if (d.basis === "price") {
    const p = parseNumber(d.price)
    if (p === null || !(p > 0)) e.price = "請輸入均價"
  } else {
    const t = parseNumber(d.total)
    if (t === null || !(t > 0)) e.total = "請輸入總成本"
  }
  const date = d.date || batchDate
  if (!date) e.date = "請選日期"
  else if (date > today) e.date = "不能是未來的日期"
  return e
}

export const hasPositionErrors = (e: PositionErrors) => Object.values(e).some(Boolean)

/** 檢查得了的列（有股票、股數與成本）：dry_run 只送這些 */
export function checkable(d: DraftPosition): boolean {
  const q = parseNumber(d.qty)
  const c = d.basis === "price" ? parseNumber(d.price) : parseNumber(d.total)
  return !!d.symbol && q !== null && q > 0 && c !== null && c > 0
}

/**
 * 送出去的一列：給的是總成本就送總成本（帳本的總成本和券商一樣），日期和整批不同才送。
 * 日期怎麼來的（伺服器給過 `estimated_date` 的列才送；舊版伺服器不送）：
 * - `estimated`：按過「套用」、日期還是估計的那天、之後沒改過股票或成本；
 * - `import_day`：跟著整批的日期，而且整批的日期是匯入那天（`importDay`，伺服器給的預設日期）——有沒有估計都一樣；
 * - 其他都是 `picked`（自己改過這一列的日期，或把整批改成別天）。
 * 有估計時照樣送 `estimated_date`（估計拿掉了是 null）。
 */
export function toCommitRow(d: DraftPosition, batchDate: string, importDay: string = batchDate): PositionsCommitRow {
  const row: PositionsCommitRow = { symbol: d.symbol!.symbol, quantity: parseNumber(d.qty)!, currency: currencyOf(d) }
  if (d.basis === "total") row.total_cost = parseNumber(d.total)!
  else row.price = parseNumber(d.price)!
  if (d.date && d.date !== batchDate) row.trade_date = d.date
  if (d.replace) row.replace = true
  // 資產組成原型：日期怎麼來的，帳本之後可以在走勢圖上改
  if (d.estimate !== undefined) {
    row.date_basis = isEstimatedDate(d) ? "estimated" : !d.date && batchDate === importDay ? "import_day" : "picked"
    row.estimated_date = d.estimate
  }
  return row
}

/** 整批日期下面那一句（照實說：每一檔是一筆普通買進，均價到那天收盤的漲跌全部算在那一天） */
export const BATCH_DATE_HINT = "均價到這天收盤的漲跌算進這天的報酬，這天之前沒有走勢。"

/**
 * 整批日期下面那一句：有估計的買入日可以套用時多說估計是什麼（估計是從今天往回找「最近一次」經過均價的那一天；
 * 「按「套用」才會用」不寫，「套用」就在每一列）。舊版伺服器、估不到的、改過股票或成本的都沒有建議，只有原本那一句。
 */
export function dateHint(rows: readonly Pick<DraftPosition, "estimate">[]): string {
  const suggests = rows.some((d) => typeof d.estimate === "string")
  return suggests ? `${BATCH_DATE_HINT}估計買入日是股價最近一次經過均價的那一天。` : BATCH_DATE_HINT
}

/**
 * 重新檢查的結果併進來（`sent`：送出去的列，順序和 `check.rows` 一樣）。
 * - 帳本那一檔：換成這次的 `in_ledger`。新出現的（換了帳戶、換了股票）一律不勾、不換掉（伺服器不收不換掉的）；
 *   不在帳本了的，以券商為準拿掉，使用者沒自己動過勾選、也沒有別的問題的列重新勾上。
 * - `accountChanged`：「別的帳戶也有」是照舊的帳戶算的，拿掉。以券商為準是對舊的帳戶勾的：新的帳戶也有這一檔時，
 *   不勾、不換掉（兩個帳戶都有也一樣），讓使用者對新的帳戶重新勾；沒送出去的列也拿掉以券商為準（和它綁著的勾選一起）。
 * 回傳新的表、檢查結果變了的列數（新的錯誤、勾選變了）、勾著卻寫不進去的列數。
 */
export function applyCheck(
  rows: DraftPosition[],
  sent: DraftPosition[],
  check: Pick<PositionsCommitCheck, "rows">,
  accountChanged: boolean,
): { rows: DraftPosition[]; changed: number; blocking: number } {
  const fresh = new Map(sent.map((d, i) => [d.id, check.rows.find((r) => r.index === i)]))
  let changed = 0
  let blocking = 0
  const next = rows.map((d) => {
    const base = accountChanged ? d.flags.filter((f) => f.code !== "in_other_account") : d.flags
    if (!fresh.has(d.id)) return accountChanged ? { ...d, flags: base, inLedger: null, replace: false, include: d.replace ? false : d.include } : d
    const got = fresh.get(d.id)
    const freshFlags = (got?.flags ?? []).filter((f) => f.code !== "in_ledger")
    const kept = base.filter((f) => !CHECK_CODES.has(f.code))
    const codes = new Set(kept.map((f) => f.code))
    const flags = [...kept, ...freshFlags.filter((f) => !codes.has(f.code))]
    const inLedger = got?.in_ledger ?? null
    let { include, replace } = d
    if (inLedger && (!d.inLedger || accountChanged)) {
      include = false
      replace = false
    } else if (!inLedger && d.inLedger) {
      replace = false
      if (!d.includeSet && !include) include = !flags.some((f) => EXCLUDED_CODES.has(f.code) || f.severity === "error")
    }
    const newErrors = freshFlags.some((f) => f.severity === "error" && !d.flags.some((g) => g.code === f.code))
    if (include !== d.include || replace !== d.replace || newErrors || !!inLedger !== !!d.inLedger) changed++
    if (include && freshFlags.some((f) => f.severity === "error")) blocking++
    return { ...d, flags, inLedger, include, replace }
  })
  return { rows: next, changed, blocking }
}

/** 勾著的列的成本合計（新台幣、美元分開） */
export function costTotals(rows: DraftPosition[]): { TWD: number; USD: number } {
  const out = { TWD: 0, USD: 0 }
  for (const d of rows) {
    if (!d.include) continue
    const t = totalCost(d)
    if (t !== null) out[currencyOf(d)] += t
  }
  return { TWD: Math.round(out.TWD * 100) / 100, USD: Math.round(out.USD * 100) / 100 }
}

/** 「NT$1,288,687」「US$2,420.25」，兩種都有時用頓號連起來 */
export function costTotalsText(t: { TWD: number; USD: number }): string {
  const parts = [t.TWD || !t.USD ? formatMoney(t.TWD) : "", t.USD ? formatMoney(t.USD, { currency: "USD" }) : ""].filter(Boolean)
  return parts.join("、")
}

/** 伺服器回的 `replaced`（代號）配上名稱 */
export function namedReplaced(replaced: PositionsReplaced[], rows: DraftPosition[]): { name: string; deleted: number }[] {
  return replaced.map((r) => ({ name: rows.find((d) => d.symbol?.symbol === r.symbol)?.symbol?.name ?? r.symbol, deleted: r.deleted }))
}
