import type { Account, ImportCandidate, ImportFlag, ImportRow, Market, StatementImport, TransactionType } from "@/api/types"
import { formatMoney } from "@/lib/format"
import { marketOf } from "@/lib/tick"
import { parseNumber } from "../quantity-input"

/**
 * 確認表的資料與規則（不碰畫面，測試得到）：
 * - 伺服器回的每一列（`ImportRow`）變成可以改的 `DraftRow`；改過的格子記下來（鉛筆變墨水）。
 * - 股利、融券（`dividend_auto`、`short_sale`）不進表格，收成「略過 N 筆股利、N 筆融券」。
 * - 重新驗算（dry_run，`check_batch`）只算帳本：賣超、重複、帳目、這一列本身寫不進去的原因。這些換成新的；
 *   讀檔時才算得出來的（沒讀清楚、找不到股票、金額、手續費、稅、日期、價格、當沖、融資、幣別）留著，
 *   除非使用者改了相關的格子（改了股數或價格，「股數 × 價格和成交金額差」就拿掉）。
 * - 換帳戶時，賣超、重複照新的帳戶重算；伺服器預設不勾的（賣超、重複）新出現時，使用者沒自己動過勾選的列跟著不勾。
 */

/** 不匯入、收在「略過」裡的 */
export const SKIPPED_CODES: ReadonlySet<string> = new Set(["dividend_auto", "short_sale"])
/** 旁邊可以選股票的 */
export const PICK_SYMBOL_CODES: ReadonlySet<string> = new Set(["unknown_symbol", "ambiguous_symbol"])
/** 重新驗算（`check_batch`）會再算一次的：每次都換成新的（`unknown_symbol` 兩邊都有，照讀檔時的留著，選了股票才拿掉） */
const LEDGER_CODES: ReadonlySet<string> = new Set([
  "oversell", "duplicate", "possible_duplicate", "ledger_inconsistent",
  "validation_error", "invalid_row", "bad_date", "account_mismatch", "unsupported_type",
])
/** 帳本的檢查裡，伺服器預設不勾的（和後端 `services/imports.py` 的 EXCLUDED 相同） */
const UNTICK_CODES: ReadonlySet<string> = new Set(["oversell", "duplicate", "possible_duplicate", "ledger_inconsistent"])
/** 伺服器預設不勾的全部代碼（和後端的 EXCLUDED 相同；另外任何 `severity: "error"` 也不勾） */
const EXCLUDED_CODES: ReadonlySet<string> = new Set([
  ...UNTICK_CODES, "unknown_symbol", "ambiguous_symbol", "dividend_auto", "short_sale", "day_trade", "currency_mismatch", "fractional_tw_qty", "unreadable",
])
/** 讀檔時的旗標：改了哪幾格就算處理過（重新驗算時拿掉） */
const RESOLVED_BY: Readonly<Record<string, readonly (keyof EditableFields)[]>> = {
  unreadable: ["qty", "price", "date", "type"],
  amount_mismatch: ["qty", "price"],
  fractional_tw_qty: ["qty"],
  price_far_from_close: ["price", "date", "symbol"],
  fee_out_of_range: ["fee"],
  tax_out_of_range: ["tax", "type"],
  side_inconsistent: ["type", "tax"],
  not_trading_day: ["date"],
  outside_period: ["date"],
}
/** 標籤（不是要處理的問題）：小一號淡墨 */
export const NOTE_CODES: ReadonlySet<string> = new Set(["margin", "day_trade"])

export const isSkipped = (row: ImportRow) => row.flags.some((f) => SKIPPED_CODES.has(f.code))

/** 選到的股票（找不到、對到好幾檔時使用者自己選的；其他列從代號推） */
export interface PickedSymbol {
  symbol: string
  code: string
  name: string
  market: Market
}

export interface DraftRow {
  /** 伺服器的 row_id；「補一筆買進」加的是 `added_N` */
  id: string
  include: boolean
  symbol: PickedSymbol | null
  /** 對帳單上寫的名稱（找不到股票時顯示在訊息裡） */
  readName: string
  type: "buy" | "sell"
  date: string
  qty: string
  price: string
  fee: string
  tax: string
  /** 對帳單上的價金：股數、價格沒改過才照送（改過就讓伺服器重算股數 × 價格） */
  amount: number | null
  isDayTrade: boolean
  /** 讀出來的幣別（TWD／USD 才照送；複委託的新台幣金額由伺服器判斷） */
  currency: "TWD" | "USD" | null
  flags: ImportFlag[]
  /** 使用者改過的欄位（顯示成墨色；整列改過的話「沒讀清楚」拿掉） */
  edited: ReadonlySet<keyof EditableFields>
  /** 選過股票（「找不到」「對到好幾檔」拿掉） */
  picked: boolean
  /** 「補一筆買進」加的列 */
  added: boolean
  /** 使用者自己勾過或取消過（之後的驗算不再替他改勾選） */
  includeSet: boolean
}

export type EditableFields = Pick<DraftRow, "date" | "type" | "qty" | "price" | "fee" | "tax" | "symbol">

/** 數字放進輸入框：加千分位（3,000、1,450、130.5），小數照原樣 */
const numText = (n: number | null | undefined) =>
  n === null || n === undefined || !Number.isFinite(n) ? "" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(n)

/** 代號推出顯示用的股票（`2317.TW` → 2317；名稱用對帳單上的） */
export function symbolFromCode(symbol: string | null, name: string): PickedSymbol | null {
  if (!symbol) return null
  const market = marketOf(symbol)
  return { symbol, code: symbol.replace(/\.(TW|TWO)$/, ""), name, market }
}

export function toDraftRow(row: ImportRow): DraftRow {
  const c = row.candidate
  return {
    id: row.row_id,
    include: row.include,
    symbol: symbolFromCode(c.symbol, row.raw.name || c.symbol || ""),
    readName: row.raw.name || row.raw.symbol_code || "",
    type: c.type === "sell" ? "sell" : "buy",
    date: c.trade_date,
    qty: numText(c.quantity),
    price: numText(c.price),
    fee: numText(c.fee ?? 0),
    tax: numText(c.tax ?? 0),
    amount: c.amount ?? null,
    isDayTrade: !!c.is_day_trade,
    currency: c.currency === "TWD" || c.currency === "USD" ? c.currency : null,
    flags: row.flags,
    edited: new Set(),
    picked: false,
    added: false,
    includeSet: false,
  }
}

/** 改一格：記下改了哪一格；股數或價格改了，對帳單的價金就不再照送 */
export function editRow(row: DraftRow, patch: Partial<EditableFields>): DraftRow {
  const edited = new Set(row.edited)
  for (const k of Object.keys(patch) as (keyof EditableFields)[]) edited.add(k)
  const next: DraftRow = { ...row, ...patch, edited }
  if ("qty" in patch || "price" in patch) next.amount = null
  if ("symbol" in patch) {
    next.picked = true
    next.flags = next.flags.filter((f) => !PICK_SYMBOL_CODES.has(f.code))
  }
  return next
}

/** 「補一筆買進」：賣超那一列的股票、差的股數；日期與價格要自己填（日期一定要在那筆賣出以前） */
export function shortfallRow(sell: DraftRow, id: string): DraftRow | null {
  const m = sell.flags.find((f) => f.code === "oversell")?.message ?? ""
  // 伺服器的標籤：「賣出 2,000 股・當時只有 1,000 股」
  const nums = [...m.matchAll(/([\d,]+(?:\.\d+)?)\s*股/g)].map((x) => Number(x[1]!.replace(/,/g, "")))
  const sold = parseNumber(sell.qty) ?? nums[0] ?? 0
  const held = nums.length >= 2 ? nums[1]! : 0
  const missing = sold - held
  if (!sell.symbol || !(missing > 0)) return null
  return {
    id,
    include: true,
    symbol: sell.symbol,
    readName: sell.symbol.name,
    type: "buy",
    date: "",
    qty: numText(missing),
    price: "",
    fee: "",
    tax: "",
    amount: null,
    isDayTrade: false,
    currency: sell.currency,
    flags: [],
    edited: new Set(["qty", "date", "price"]),
    picked: true,
    added: true,
    includeSet: true,
  }
}

export interface RowErrors {
  symbol?: string
  date?: string
  qty?: string
  price?: string
  fee?: string
  tax?: string
}

/** 勾著的列在簽名前要過的基本檢查（伺服器另外驗算一次） */
export function rowErrors(row: DraftRow, today: string): RowErrors {
  const e: RowErrors = {}
  if (!row.symbol) e.symbol = "請選股票"
  if (!row.date) e.date = "請選日期"
  else if (row.date > today) e.date = "不能是未來的日期"
  const q = parseNumber(row.qty)
  if (q === null || !(q > 0)) e.qty = "請輸入股數"
  const p = parseNumber(row.price)
  if (p === null || !(p > 0)) e.price = "請輸入價格"
  for (const k of ["fee", "tax"] as const) {
    if (!row[k].trim()) continue
    const n = parseNumber(row[k])
    if (n === null || !Number.isFinite(n) || n < 0) e[k] = "請填數字"
  }
  return e
}

export const hasErrors = (e: RowErrors) => Object.values(e).some(Boolean)

/** 送出去的候選交易（`source` 由伺服器寫成 import；不寫備註：AI 對話讀得到備註） */
export function toCandidate(row: DraftRow, accountId: string): ImportCandidate {
  const fee = parseNumber(row.fee)
  const tax = parseNumber(row.tax)
  return {
    account_id: accountId,
    symbol: row.symbol?.symbol ?? null,
    type: row.type as TransactionType,
    trade_date: row.date,
    quantity: parseNumber(row.qty),
    price: parseNumber(row.price),
    amount: row.amount,
    fee: fee ?? 0,
    tax: tax ?? 0,
    is_day_trade: row.isDayTrade,
    ...(row.currency ? { currency: row.currency } : {}),
    note: "",
  }
}

/** 合計：買進＝價金＋手續費＋稅；賣出＝價金－手續費－稅（價金沒照送時是股數 × 價格） */
export function rowTotal(row: DraftRow): number | null {
  const q = parseNumber(row.qty)
  const p = parseNumber(row.price)
  const gross = row.amount ?? (q !== null && p !== null ? Math.round(q * p * 100) / 100 : null)
  if (gross === null) return null
  const fee = parseNumber(row.fee) ?? 0
  const tax = parseNumber(row.tax) ?? 0
  return row.type === "buy" ? gross + fee + tax : gross - fee - tax
}

/** 讀檔時的旗標，使用者已經處理了（選了股票、改了相關的格子） */
function resolved(row: DraftRow, code: string): boolean {
  if (row.picked && PICK_SYMBOL_CODES.has(code)) return true
  return (RESOLVED_BY[code] ?? []).some((k) => row.edited.has(k))
}

/**
 * 重新驗算的結果併進來：帳本的（賣超、重複、寫不進去的原因）換成這次的；讀檔時才算得出來的留著，處理過的拿掉。
 */
export function mergeFlags(row: DraftRow, fresh: ImportFlag[]): ImportFlag[] {
  const kept = row.flags.filter((f) => !LEDGER_CODES.has(f.code) && !resolved(row, f.code))
  const codes = new Set(kept.map((f) => f.code))
  return [...kept, ...fresh.filter((f) => !codes.has(f.code))]
}

/**
 * 驗算後的勾選：新出現伺服器預設不勾的帳本問題（賣超、重複），使用者又沒自己動過勾選，就跟伺服器一樣不勾。
 */
export function includeAfterCheck(row: DraftRow, merged: ImportFlag[]): boolean {
  if (!row.include || row.includeSet) return row.include
  return !newFlagCodes(row.flags, merged).some((c) => UNTICK_CODES.has(c))
}

/**
 * 換了帳戶（讀檔時照另一個帳戶算的）：沒勾的列上，照舊帳戶算的帳本句子拿掉；只因為這些句子才沒勾的列
 * （使用者也沒自己動過勾選）重新勾上，和勾著的列一起照新帳戶驗算。
 */
export function forAccountSwitch(rows: DraftRow[]): DraftRow[] {
  return rows.map((r) => {
    if (r.include) return r
    const flags = r.flags.filter((f) => !LEDGER_CODES.has(f.code))
    if (flags.length === r.flags.length) return r
    const onlyBooks = r.flags.some((f) => UNTICK_CODES.has(f.code)) && !flags.some((f) => EXCLUDED_CODES.has(f.code) || f.severity === "error")
    return { ...r, flags, include: !r.includeSet && onlyBooks }
  })
}

/** 這一次驗算多出來、使用者還沒看過的旗標（有的話先停下來給他看，不直接寫入） */
export function newFlagCodes(before: ImportFlag[], after: ImportFlag[]): string[] {
  const seen = new Set(before.map((f) => f.code))
  return after.filter((f) => !seen.has(f.code)).map((f) => f.code)
}

/** 收起來的那一行：「略過 3 筆股利、1 筆融券」 */
export function skippedSummary(rows: ImportRow[]): string | null {
  const dividends = rows.filter((r) => r.flags.some((f) => f.code === "dividend_auto")).length
  const shorts = rows.filter((r) => r.flags.some((f) => f.code === "short_sale")).length
  const parts = [dividends ? `${dividends} 筆股利` : "", shorts ? `${shorts} 筆融券` : ""].filter(Boolean)
  return parts.length ? `略過 ${parts.join("、")}` : null
}

/** 整份核對的標籤（對帳單沒有印合計時不寫；2026-11-22 起是標籤，不是句子） */
export function totalsLine(doc: Pick<StatementImport, "totals_check">, currency: "TWD" | "USD" = "TWD"): string | null {
  const t = doc.totals_check
  if (!t || t.ok === null) return null
  if (t.ok || !t.diff) return "合計相符"
  const amount = formatMoney(Math.abs(t.diff), { currency })
  return t.diff < 0 ? `比對帳單合計少 ${amount}・可能漏讀` : `比對帳單合計多 ${amount}・可能重複讀`
}

/** 庫存畫面（請改用匯入庫存，2026-11-17）、不是交易紀錄：不出表格，直接寫 */
export function unsupportedLine(doc: Pick<StatementImport, "document_kind" | "rows" | "notice">): string | null {
  const own = defaultUnsupported(doc)
  // 伺服器寫了就用它的（同一件事只有一種說法）
  return own && doc.notice ? doc.notice : own
}

function defaultUnsupported(doc: Pick<StatementImport, "document_kind" | "rows">): string | null {
  if (doc.document_kind === "holdings_snapshot") return "這是庫存畫面・改用匯入庫存"
  if (doc.document_kind === "not_a_trade_record") return "沒有買賣紀錄"
  if (doc.rows.length === 0) return "沒有讀到買賣"
  return null
}

/** 去掉公司名稱的尾巴，比對券商：「永豐金證券股份有限公司」和帳戶的「永豐金證券」、「永豐」都算同一家 */
const brokerKey = (s: string) => s.replace(/股份有限公司|有限公司|綜合證券|證券|金控|公司|\s/g, "")

/**
 * 先選好的帳戶：券商相同、幣別也相同的（台股對帳單不選同一家的美元複委託帳戶）；對不到券商就照原本的，
 * 但原本的幣別不對時，改成第一個幣別相同的帳戶。`currency`：這份對帳單的幣別（不知道就不看幣別）。
 */
export function accountForBroker(accounts: Account[], broker: string, fallback: string, currency?: "TWD" | "USD" | null): string {
  const key = brokerKey(broker)
  const pool = currency ? accounts.filter((a) => a.currency === currency) : accounts
  const hit = key
    ? pool.find((a) => {
        const k = brokerKey(a.broker || a.name)
        return k && (k.includes(key) || key.includes(k))
      })
    : undefined
  if (hit) return hit.id
  if (currency && !pool.some((a) => a.id === fallback)) return pool[0]?.id ?? fallback
  return fallback
}

/** 這份對帳單的幣別：要匯入的列（股利、融券以外）多數是哪一種；讀不出來是 null */
export function statementCurrency(doc: Pick<StatementImport, "rows">): "TWD" | "USD" | null {
  let twd = 0
  let usd = 0
  for (const r of doc.rows) {
    if (isSkipped(r)) continue
    const c = r.candidate.symbol ? (marketOf(r.candidate.symbol) === "US" ? "USD" : "TWD") : r.candidate.currency
    if (c === "TWD") twd++
    else if (c === "USD") usd++
  }
  return twd === 0 && usd === 0 ? null : usd > twd ? "USD" : "TWD"
}
