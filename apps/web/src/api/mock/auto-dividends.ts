import type { Account, DividendRecord, Transaction, TransactionSource } from "../types"
import { USER_RECORD_WINDOW_DAYS } from "@/lib/ledger-display"
import { ARCHIVE_START } from "./commercial"
import { computePreview } from "./fees"
import { findInstrument } from "./instruments"
import { addDays, dividendRecords } from "./market"

/**
 * 股利自動入帳（與後端 `apps/api/src/forliosa/services/auto_dividends.py` 相同的規則，docs/handoff.md §3.0）：
 * - 只有台股（上市、上櫃）：依除息預告在**除息日**記一筆 `source: "auto"` 的現金股利，股數＝該帳戶除息日前一天收盤的持股；
 *   金額 = 股數 × 每股（元以下捨去），二代健保照一般規則估算。金額為 0 或還沒到除息日的不記；美股仍要自己記。
 * - 只記持股的帳戶：只記快照日之後的除息日。
 * - 使用者自己記的（manual／import／ai_draft）同類股利優先：同帳戶同商品、日期在除息日起 120 天內，就不產生（已有的會移除）。
 * - 使用者改過的（`auto_edited`）不再碰；刪掉的記一筆「略過」，之後不再產生。
 * 示範資料沒有配股（`stock_dividend` 都是 0），mock 只處理現金股利。
 */

/** 使用者自己的紀錄：優先於自動入帳 */
const USER_SOURCES: ReadonlySet<TransactionSource> = new Set(["manual", "import", "ai_draft"])

/** 「略過」的鍵：帳戶＋商品＋除息日＋種類 */
export function skipKey(t: Pick<Transaction, "account_id" | "symbol" | "trade_date" | "type">): string {
  return `${t.account_id}|${t.symbol}|${t.trade_date}|${t.type === "stock_dividend" ? "stock" : "cash"}`
}

/**
 * 除息預告：台股、有除息日、現金股利 > 0，由舊到新。
 * 預告來自自建存檔（`TWT48U_ALL`、`tpex_exright_prepost`），所以只有存檔起點之後的除息日（兩種資料政策相同）。
 */
export function exDividendNotices(symbol: string): DividendRecord[] {
  const spec = findInstrument(symbol)
  if (!spec || spec.market === "US") return []
  return dividendRecords(spec)
    .filter((d) => d.ex_dividend_date !== null && d.ex_dividend_date >= ARCHIVE_START && d.cash_dividend > 0)
    .sort((a, b) => a.ex_dividend_date!.localeCompare(b.ex_dividend_date!))
}

/**
 * 使用者自己記的股利代表哪些除息日：每筆紀錄（日期 d）代表 `e ≤ d ≤ e + 120 天` 中最近的除息日 e；
 * 有每股金額時優先挑每股金額相同的（季配息的四月入帳與七月入帳才不會混在一起）。
 */
export function coveredByUser(rows: Transaction[], notices: DividendRecord[]): Set<string> {
  const out = new Set<string>()
  for (const t of rows) {
    if (t.type !== "cash_dividend") continue
    let candidates = notices.filter((e) => e.ex_dividend_date! <= t.trade_date && t.trade_date <= addDays(e.ex_dividend_date!, USER_RECORD_WINDOW_DAYS))
    if (candidates.length === 0) continue
    if (t.price) {
      const same = candidates.filter((e) => Math.abs(e.cash_dividend - t.price!) <= 0.001)
      if (same.length > 0) candidates = same
    }
    out.add(candidates.reduce((a, b) => (b.ex_dividend_date! > a.ex_dividend_date! ? b : a)).ex_dividend_date!)
  }
  return out
}

const shares = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 })

/** 備註：「除息前一日持有 1,500 股 × 每股現金股利 5 元；發放日 2026-10-09」（與後端相同） */
export function cashNote(qty: number, perShare: number, paymentDate: string | null): string {
  const note = `除息前一日持有 ${shares.format(qty)} 股 × 每股現金股利 ${perShare} 元`
  return paymentDate ? `${note}；發放日 ${paymentDate}` : note
}

/** 除息日前一天收盤的持股（不含自動入帳的列） */
function heldBefore(rows: Transaction[], day: string): number {
  let q = 0
  for (const x of rows) {
    if (x.trade_date >= day) continue
    if (x.type === "buy") q += x.quantity ?? 0
    else if (x.type === "sell") q -= x.quantity ?? 0
    else if (x.type === "split") q *= x.quantity ?? 1
    else if (x.type === "capital_reduction") q -= q * (x.quantity ?? 0)
    else if (x.type === "stock_dividend") q += Math.floor(q * ((x.price ?? 0) / 10))
  }
  return q
}

export interface AutoDividendContext {
  accounts: Account[]
  /** 已略過的股利（`skipKey`） */
  skips: ReadonlySet<string>
  /** 只記持股的帳戶的快照日 */
  snapshotAsOf?: (accountId: string) => string | undefined
  today: string
}

const COMPARED = ["quantity", "price", "amount", "fee", "tax", "health_insurance", "note"] as const

/** 重算應有的自動入帳股利，新增／更新／移除 `source: "auto"` 的列；回傳新的交易清單（依日期排序） */
export function syncAutoDividends(txns: Transaction[], ctx: AutoDividendContext): Transaction[] {
  const keep = txns.filter((t) => t.source !== "auto")
  const existing = new Map(txns.filter((t) => t.source === "auto").map((t) => [skipKey(t), t]))
  const out = [...keep]
  for (const account of ctx.accounts) {
    const asOf = account.tracking_mode === "holdings" ? ctx.snapshotAsOf?.(account.id) : undefined
    const symbols = new Set(keep.filter((t) => t.account_id === account.id && t.symbol).map((t) => t.symbol!))
    for (const symbol of [...symbols].sort()) {
      const notices = exDividendNotices(symbol)
      if (notices.length === 0) continue
      const rows = keep.filter((t) => t.account_id === account.id && t.symbol === symbol)
      const covered = coveredByUser(rows.filter((t) => USER_SOURCES.has(t.source)), notices)
      for (const e of notices) {
        const ex = e.ex_dividend_date!
        if (ex > ctx.today || (asOf !== undefined && ex <= asOf) || covered.has(ex)) continue
        const key = `${account.id}|${symbol}|${ex}|cash`
        if (ctx.skips.has(key)) continue
        const qty = heldBefore(rows, ex)
        if (qty <= 0) continue
        const p = computePreview({ account_id: account.id, symbol, type: "cash_dividend", trade_date: ex, quantity: qty, price: e.cash_dividend }, account, findInstrument(symbol))
        if (p.gross <= 0) continue
        const values = { quantity: qty, price: e.cash_dividend, amount: p.gross, fee: 0, tax: p.tax, health_insurance: p.health_insurance, note: cashNote(qty, e.cash_dividend, e.payment_date) }
        const prev = existing.get(key)
        if (prev) {
          existing.delete(key)
          out.push(COMPARED.every((k) => prev[k] === values[k]) ? prev : { ...prev, ...values })
          continue
        }
        out.push({
          id: `txn_auto_${ex.replaceAll("-", "")}_${symbol.replace(/\W/g, "").toLowerCase()}_${account.id.toLowerCase()}`,
          account_id: account.id, symbol, type: "cash_dividend", trade_date: ex, ...values,
          currency: account.currency, is_day_trade: false, source: "auto", created_at: `${ex}T18:00:00+08:00`,
        })
      }
    }
  }
  return out.sort((a, b) => (a.trade_date === b.trade_date ? a.id.localeCompare(b.id) : a.trade_date.localeCompare(b.trade_date)))
}
