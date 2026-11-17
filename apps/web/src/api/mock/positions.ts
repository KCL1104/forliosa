import type { Account, Currency, ImportFlag, LedgerHolding, PositionRaw, PositionRow, PositionsImport, Transaction } from "../types"
import { INSTRUMENTS, findInstrument, type MockInstrumentSpec } from "./instruments"
import { replay } from "./ledger"

/**
 * 匯入庫存的 mock（和後端 `services/positions_import.py` 同一套代碼與句子，只做示範用得到的部分）：
 * - 截圖：不管上傳什麼，回一張永豐金證券 app 的庫存畫面（已在帳本、股數和均價都一樣、只有總成本、零股、融資、
 *   找不到股票、融券各一列；兩張截圖重疊的一列合併）。「已在帳本」照目前的帳本即時算。
 * - 貼上的文字：一行一檔，照「代號 名稱 股數（或 N 張） 均價 [總成本]」讀；讀不到就說「這裡面沒有看到庫存。」
 */

const n0 = (n: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(n)
const r4 = (n: number) => Math.round(n * 10000) / 10000
const flag = (code: string, message: string, severity: "error" | "warning" = "warning"): ImportFlag => ({ code, message, severity })
const num = (s: string | undefined): number | null => {
  if (!s) return null
  const n = Number(s.replace(/[,\s]/g, ""))
  return Number.isFinite(n) ? Math.abs(n) : null
}

/** 和後端相同：不預設勾選的代碼（另外任何 error 也不勾） */
const EXCLUDED = new Set(["unknown_symbol", "ambiguous_symbol", "unreadable", "fractional_tw_qty", "currency_mismatch", "short_sale", "in_ledger"])

/** AI 照抄的一列（全部是字串） */
export interface ReadPosition {
  symbol_code: string
  name: string
  kind?: "cash" | "margin" | "short" | "other"
  quantity: string
  quantity_unit: "lots" | "shares"
  avg_cost?: string
  total_cost?: string
  market_price?: string
  market_value?: string
  currency?: "TWD" | "USD" | "not_shown"
  page?: number
}

/** 帳戶現在的持股（股數 > 0）：帳本的股數、均價（含買進手續費）、這一檔在這個帳戶的紀錄筆數（其中幾筆股利、幾筆賣出） */
export function heldIn(txns: Transaction[], accountId: string, today: string): Map<string, LedgerHolding> {
  const state = replay(txns, today, accountId)
  const out = new Map<string, LedgerHolding>()
  for (const p of state.positions.values()) {
    if (p.qty <= 0.0001) continue
    const spec = findInstrument(p.symbol)
    const mine = txns.filter((t) => t.account_id === accountId && t.symbol === p.symbol)
    out.set(p.symbol, {
      quantity: p.qty,
      avg_cost: r4(p.cost / p.qty),
      currency: spec?.currency ?? "TWD",
      records: mine.length,
      dividends: mine.filter((t) => t.type === "cash_dividend" || t.type === "stock_dividend").length,
      sells: mine.filter((t) => t.type === "sell").length,
    })
  }
  return out
}

/** 代號優先；只有名稱時找名稱一樣的（好幾檔是「對到好幾檔」） */
function resolve(code: string, name: string): { spec?: MockInstrumentSpec; flag?: ImportFlag } {
  const c = code.trim().toUpperCase()
  if (c) {
    const spec = /^[A-Z.]+$/.test(c) ? findInstrument(c) : (findInstrument(`${c}.TW`) ?? findInstrument(`${c}.TWO`))
    if (spec) {
      if (name && spec.market !== "US" && !spec.name.includes(name) && !name.includes(spec.name)) {
        return { spec, flag: flag("ambiguous_symbol", `代號 ${spec.code} 是${spec.name}，畫面上寫的是「${name}」。`, "error") }
      }
      return { spec }
    }
  }
  const n = name.trim()
  if (n) {
    const hits = INSTRUMENTS.filter((i) => i.name === n || (n.length >= 2 && i.name.startsWith(n)))
    if (hits.length === 1) return { spec: hits[0] }
    if (hits.length > 1) return { flag: flag("ambiguous_symbol", `「${n}」對得到好幾檔，選一檔。`, "error") }
  }
  return { flag: flag("unknown_symbol", `找不到「${n || c}」。`, "error") }
}

interface Ctx {
  account: Account
  accounts: Account[]
  held: Map<string, Map<string, LedgerHolding>>
}

/** 和後端的 `build_row` 一樣：張換成股、均價或總成本 ÷ 股數、讀檔、幣別、帳本的旗標 */
function buildRow(ctx: Ctx, x: ReadPosition, i: number): PositionRow & { key: string | null } {
  const flags: ImportFlag[] = []
  const add = (f: ImportFlag) => {
    if (!flags.some((g) => g.code === f.code)) flags.push(f)
  }
  const kind = x.kind ?? "cash"
  const printed = x.currency ?? "not_shown"
  const { spec, flag: symbolFlag } = resolve(x.symbol_code, x.name)
  const tw = spec ? spec.currency === "TWD" : printed !== "USD"
  const lots = x.quantity_unit === "lots" && tw
  const rawQty = num(x.quantity)
  const qty = rawQty === null ? null : lots ? rawQty * 1000 : rawQty
  const avg = num(x.avg_cost)
  const total = num(x.total_cost)
  const basis = avg ? "average_cost" : total && qty ? "total_cost" : null
  const price = avg ? avg : total && qty ? Math.round((total / qty) * 1e8) / 1e8 : null
  const currency: Currency = spec ? spec.currency : printed === "USD" ? "USD" : printed === "TWD" ? "TWD" : ctx.account.currency
  const raw: PositionRaw = {
    symbol_code: x.symbol_code, name: x.name, kind, quantity: x.quantity, quantity_unit: x.quantity_unit, avg_cost: x.avg_cost ?? "",
    total_cost: x.total_cost ?? "", market_price: x.market_price ?? "", market_value: x.market_value ?? "", currency: printed, page: x.page ?? 1,
    raw_line: [x.symbol_code, x.name, x.quantity, x.avg_cost, x.total_cost].filter(Boolean).join(" | "),
  }
  const row = {
    row_id: `p${i}`, symbol: spec?.symbol ?? null, name: spec?.name ?? (x.name || x.symbol_code), currency, quantity: qty || null,
    price: price === null ? null : r4(price), price_basis: basis as PositionRow["price_basis"], total_cost: total || null, raw, flags, include: true,
    in_ledger: null as LedgerHolding | null, key: spec && qty && price ? `${spec.symbol}|${kind}|${qty}|${price}` : null,
  }
  if (kind === "short") {
    add(flag("short_sale", "融券的庫存不匯入。"))
    return { ...row, include: false }
  }
  if (kind === "margin") add(flag("margin", "融資的庫存，當成一般持股匯入。"))
  const missing = [...(x.symbol_code || x.name ? [] : ["名稱"]), ...(qty ? [] : ["股數"]), ...(price ? [] : ["成本"])]
  if (missing.length) add(flag("unreadable", `這一列的${missing.join("、")}沒讀清楚。`, "error"))
  if (symbolFlag && (x.symbol_code || x.name)) add(symbolFlag)
  if (spec) {
    if (spec.currency === "USD") {
      if (printed === "TWD") add(flag("currency_mismatch", "美股的成本寫的是新台幣，要改成美元的成本。", "error"))
      else if (printed === "not_shown") add(flag("currency_guess", "畫面上沒寫幣別，當成美元。"))
    } else if (printed === "USD") add(flag("currency_mismatch", "台股的成本寫的是美元。", "error"))
    if (tw && qty !== null && !Number.isInteger(qty)) add(flag("fractional_tw_qty", "台股的股數要是整數。", "error"))
    else if (lots && rawQty !== null && !Number.isInteger(rawQty)) add(flag("not_whole_lots", `畫面上是 ${n0(rawQty)} 張，算成 ${n0(qty ?? 0)} 股；不是整張，確認一下。`))
    if (qty && avg && total) {
      const gross = qty * avg
      if (Math.abs(gross - total) > Math.max(tw ? 1 : 0.02, total * 0.005)) {
        add(flag("cost_mismatch", `股數 × 均價和總成本差 ${n0(Math.round(Math.abs(gross - total) * 100) / 100)}${tw && !lots && Math.abs(gross * 1000 - total) <= total * 0.005 ? "，股數可能是張數（1 張＝1,000 股）" : ""}。`))
      }
    }
    const held = ctx.held.get(ctx.account.id)?.get(spec.symbol)
    if (held) {
      row.in_ledger = held
      const same = qty === held.quantity && price !== null && Math.abs(held.avg_cost - price) <= Math.max(0.01, price * 0.0005)
      add(flag("in_ledger", same ? "帳本裡已經有，股數和均價都一樣。" : `帳本裡已經有 ${n0(held.quantity)} 股，均價 ${n0(held.avg_cost >= 10 ? Math.round(held.avg_cost * 100) / 100 : held.avg_cost)}。`))
    }
    const others = ctx.accounts.filter((a) => a.id !== ctx.account.id && ctx.held.get(a.id)?.has(spec.symbol))
    if (others.length === 1) add(flag("in_other_account", `「${others[0]!.name}」帳戶也有 ${n0(ctx.held.get(others[0]!.id)!.get(spec.symbol)!.quantity)} 股。`))
    else if (others.length > 1) add(flag("in_other_account", `另外 ${others.length} 個帳戶也有這一檔。`))
  }
  return { ...row, include: !flags.some((f) => EXCLUDED.has(f.code) || f.severity === "error") }
}

/** 庫存畫面的示範：兩張截圖（第二張和第一張重疊一列） */
export function holdingsFixture(held: Map<string, LedgerHolding>): ReadPosition[] {
  // 鴻海：帳本裡有多少就照抄（「股數和均價都一樣」）；沒有的話照一般的一列
  const hh = held.get("2317.TW")
  const honHai = hh ? { quantity: String(hh.quantity), avg: String(Math.round(hh.avg_cost * 100) / 100) } : { quantity: "2000", avg: "198.5" }
  return [
    { symbol_code: "2330", name: "台積電", quantity: "1,500", quantity_unit: "shares", avg_cost: "612.4", total_cost: "918,600", currency: "TWD", page: 1 },
    { symbol_code: "2317", name: "鴻海", quantity: honHai.quantity, quantity_unit: "shares", avg_cost: honHai.avg, currency: "TWD", page: 1 },
    { symbol_code: "2881", name: "富邦金", kind: "margin", quantity: "2", quantity_unit: "lots", avg_cost: "88.6", total_cost: "177,200", currency: "TWD", page: 1 },
    { symbol_code: "2412", name: "中華電", quantity: "1.5", quantity_unit: "lots", total_cost: "180,000", currency: "TWD", page: 1 },
    { symbol_code: "0056", name: "元大高股息", quantity: "350", quantity_unit: "shares", avg_cost: "36.82", total_cost: "12,887", currency: "TWD", page: 1 },
    // 第二張截圖：最上面一列和第一張的最後一列重疊
    { symbol_code: "0056", name: "元大高股息", quantity: "350", quantity_unit: "shares", avg_cost: "36.82", total_cost: "12,887", currency: "TWD", page: 2 },
    { symbol_code: "", name: "台光電", quantity: "1", quantity_unit: "lots", avg_cost: "512", total_cost: "512,000", currency: "TWD", page: 2 },
    { symbol_code: "2603", name: "長榮", kind: "short", quantity: "1", quantity_unit: "lots", avg_cost: "201.5", currency: "TWD", page: 2 },
  ]
}

/**
 * 貼上的文字：一行一檔。代號（台股 4–6 碼、美股英文字母）、名稱、股數（寫「張」的乘 1,000）、均價、總成本（選填）。
 * 寫了 US$ 或 USD 的是美元；美股沒寫幣別照後端當成美元（`currency_guess`）。
 */
export function parsePastedHoldings(text: string): ReadPosition[] {
  const out: ReadPosition[] = []
  for (const line of text.split(/\r?\n/)) {
    const s = line.trim()
    if (!s) continue
    const code = /(?:^|\s)(\d{4,6}[A-Z]?|[A-Z]{1,5})(?=\s|$)/.exec(s)?.[1] ?? ""
    const name = /[一-鿿][一-鿿0-9A-Za-z-]*/.exec(s.replace(/[張股均價成本總市值現]+/g, " "))?.[0] ?? ""
    if (!code && !name) continue
    const rest = s.replace(code, " ")
    const nums = [...rest.matchAll(/(\d[\d,]*(?:\.\d+)?)/g)].map((m) => m[1]!)
    if (nums.length === 0) continue
    const usd = /US\$|USD/i.test(s)
    const lots = /\d\s*張/.test(s)
    out.push({
      symbol_code: code, name, quantity: nums[0]!, quantity_unit: lots ? "lots" : "shares", avg_cost: nums[1], total_cost: nums[2],
      currency: usd ? "USD" : /^[A-Z]+$/.test(code) ? "not_shown" : "TWD", page: 1,
    })
  }
  return out
}

/** 讀出來的列 → 回應（合併重疊的列、同一檔兩列以上標出來） */
export function readPositions(read: ReadPosition[], ctx: Ctx & { brokerName: string; today: string }, kind: "images" | "text"): PositionsImport {
  const built = read.map((x, i) => buildRow(ctx, x, i + 1))
  const seen = new Set<string>()
  let merged = 0
  const rows = built.filter((r) => {
    if (r.key === null) return true
    if (seen.has(r.key)) {
      merged++
      return false
    }
    seen.add(r.key)
    return true
  })
  const bySymbol = new Map<string, typeof rows>()
  for (const r of rows) if (r.symbol) bySymbol.set(r.symbol, [...(bySymbol.get(r.symbol) ?? []), r])
  for (const same of bySymbol.values()) {
    if (same.length < 2) continue
    for (const r of same) r.flags.push(flag("same_symbol_twice", `這一檔有 ${same.length} 列，都匯入會加在一起（例如整股和零股分開列）。`))
  }
  const out: PositionRow[] = rows.map(({ key: _key, ...r }, i) => ({ ...r, row_id: `p${i + 1}` }))
  const documentKind = out.length ? "holdings" : "other"
  return {
    account_id: ctx.account.id,
    document_kind: documentKind,
    broker_name: kind === "images" ? ctx.brokerName : "",
    trade_date: ctx.today,
    rows: out,
    merged_duplicates: merged,
    unreadable: [],
    embedded_instructions: [],
    model_used: "claude-haiku-5-5",
    retried: false,
    notice: out.length ? null : "這裡面沒有看到庫存。",
  }
}
