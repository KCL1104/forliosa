import type { Account, ImportCandidate, ImportFlag, ImportRow, Market, StatementImport, TransactionType } from "@/api/types"
import { formatMoney } from "@/lib/format"
import { marketOf } from "@/lib/tick"
import { parseNumber } from "../quantity-input"

/**
 * 確認表的資料與規則（不碰畫面，測試得到）：
 * - 伺服器回的每一列（`ImportRow`）變成可以改的 `DraftRow`；改過的格子記下來（鉛筆變墨水）。
 * - 股利、融券（`dividend_auto`、`short_sale`）不進表格，收成「略過 N 筆股利、N 筆融券」。
 * - 簽名前重新驗算（dry_run）：伺服器算得出來的旗標換成新的；只有讀檔時才知道的（沒讀清楚、找不到股票、當沖、融資、幣別）
 *   留著，除非使用者已經處理了（選了股票、改過那一列）。
 */

/** 不匯入、收在「略過」裡的 */
export const SKIPPED_CODES: ReadonlySet<string> = new Set(["dividend_auto", "short_sale"])
/** 旁邊可以選股票的 */
export const PICK_SYMBOL_CODES: ReadonlySet<string> = new Set(["unknown_symbol", "ambiguous_symbol"])
/** 只有讀檔時才知道、重新驗算不會再算一次的 */
const READ_ONLY_CODES: ReadonlySet<string> = new Set(["unreadable", "unknown_symbol", "ambiguous_symbol", "day_trade", "margin", "currency_mismatch"])
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
  flags: ImportFlag[]
  /** 使用者改過的欄位（顯示成墨色；整列改過的話「沒讀清楚」拿掉） */
  edited: ReadonlySet<keyof EditableFields>
  /** 選過股票（「找不到」「對到好幾檔」拿掉） */
  picked: boolean
  /** 「補一筆買進」加的列 */
  added: boolean
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
    flags: row.flags,
    edited: new Set(),
    picked: false,
    added: false,
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
  // 伺服器的句子：「賣出 2,000 股，超過當時持有的 1,000 股。」
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
    qty: String(missing),
    price: "",
    fee: "",
    tax: "",
    amount: null,
    isDayTrade: false,
    flags: [],
    edited: new Set(["qty", "date", "price"]),
    picked: true,
    added: true,
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

/**
 * 重新驗算的結果併進來：伺服器算得出來的換成新的；只有讀檔時才知道的留著——
 * 選過股票就拿掉「找不到／對到好幾檔」，整列改過（股數、價格、日期、買賣）就拿掉「沒讀清楚」。
 */
export function mergeFlags(row: DraftRow, fresh: ImportFlag[]): ImportFlag[] {
  const fixed = (["qty", "price", "date", "type"] as const).some((k) => row.edited.has(k))
  const kept = row.flags.filter((f) => READ_ONLY_CODES.has(f.code) && !(row.picked && PICK_SYMBOL_CODES.has(f.code)) && !(fixed && f.code === "unreadable"))
  const codes = new Set(kept.map((f) => f.code))
  return [...kept, ...fresh.filter((f) => !codes.has(f.code))]
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

/** 整份核對的一句話（對帳單沒有印合計時不說） */
export function totalsLine(doc: Pick<StatementImport, "totals_check">, currency: "TWD" | "USD" = "TWD"): string | null {
  const t = doc.totals_check
  if (!t || t.ok === null) return null
  if (t.ok || !t.diff) return "和對帳單的合計相符。"
  const amount = formatMoney(Math.abs(t.diff), { currency })
  return t.diff < 0 ? `比對帳單的合計少 ${amount}，可能漏讀了。` : `比對帳單的合計多 ${amount}，可能有一列讀了兩次。`
}

/** 庫存畫面、不是交易紀錄：第一版不能匯入，直接說 */
export function unsupportedLine(doc: Pick<StatementImport, "document_kind" | "rows">): string | null {
  if (doc.document_kind === "holdings_snapshot") return "這是庫存畫面，沒有買進日期，還不能匯入。請改用對帳單或成交明細。"
  if (doc.document_kind === "not_a_trade_record") return "這個檔案裡沒有買賣紀錄。"
  if (doc.rows.length === 0) return "這個檔案裡沒有讀到買賣。"
  return null
}

/** 去掉公司名稱的尾巴，比對券商：「永豐金證券股份有限公司」和帳戶的「永豐金證券」、「永豐」都算同一家 */
const brokerKey = (s: string) => s.replace(/股份有限公司|有限公司|綜合證券|證券|金控|公司|\s/g, "")

/** 對帳單上有券商名稱時，先選好券商相同的帳戶；沒有或對不到就照原本的 */
export function accountForBroker(accounts: Account[], broker: string, fallback: string): string {
  const key = brokerKey(broker)
  if (!key) return fallback
  const hit = accounts.find((a) => {
    const k = brokerKey(a.broker || a.name)
    return k && (k.includes(key) || key.includes(k))
  })
  return hit?.id ?? fallback
}
