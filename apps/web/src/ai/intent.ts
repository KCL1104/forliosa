/**
 * 記帳指令解析（M4 之前的規則版 AI）。
 * 把「買 0050 2 張 52.4」「賣 2330 100 股 2400」「00878 配息 1,100」這類一句話
 * 轉成結構化的意圖；不認得的句子一律當成提問，不猜。
 * 商品名稱／代號的實際對應（2330 → 2330.TW）由呼叫端用搜尋 API 完成。
 */

export type TradeSide = "buy" | "sell"

export type Intent =
  | {
      kind: "trade"
      side: TradeSide
      /** 代號（2330、0050、NVDA）或中文名稱（台積電） */
      target: string
      quantity: number
      /** 沒寫「張」或「股」時為 null，由呼叫端依市場決定（台股預設張、美股股） */
      unit: "lot" | "share" | null
      /** 沒寫價格時為 null（以最新收盤價估算，草稿上會說明） */
      price: number | null
      /** YYYY-MM-DD；沒寫為 null（今天） */
      date: string | null
    }
  | { kind: "dividend"; target: string; amount: number; date: string | null }
  | { kind: "lookup"; target: string }
  | { kind: "question"; text: string }
  | { kind: "empty" }

const FULL_WIDTH = /[！-～]/g

/** 全形轉半形、去掉數字裡的千分位逗號、CJK 與數字之間補空白 */
export function normalize(input: string): string {
  return input
    .replace(FULL_WIDTH, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/\u3000/g, " ")
    .replace(/(\d),(?=\d{3}(?!\d))/g, "$1")
    .replace(/([一-鿿])(?=[0-9A-Za-z@$])/g, "$1 ")
    .replace(/([0-9A-Za-z])(?=[一-鿿])/g, "$1 ")
    .replace(/\s+/g, " ")
    .trim()
}

const CODE = /^(?:\d{4,6}[A-Z]?|[A-Z]{1,5})$/
const NUMBER = /^\d+(?:\.\d+)?$/
const BUY = /^(?:買進|買入|買)$/
const SELL = /^(?:賣出|賣掉|賣)$/
const DIVIDEND_WORDS = /(配息|股利|現金股利|領息|股息|入帳)/
const FILLERS = new Set(["我", "幫我", "記", "記一筆", "了", "在", "以", "價格", "成交價", "每股", "共", "總共", "收到", "領到", "的", "元", "塊"])

function isCjkName(token: string): boolean {
  return /^[一-鿿A-Za-z0-9-]+$/.test(token) && /[一-鿿]/.test(token) && !/[張股元]$/.test(token)
}

/** 日期：今天、昨天、前天、11/10、2026-11-10、11月10日 */
function takeDate(tokens: string[], today: string): string | null {
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i]!
    let date: string | null = null
    if (t === "今天" || t === "今日") date = today
    else if (t === "昨天" || t === "昨日") date = shift(today, -1)
    else if (t === "前天") date = shift(today, -2)
    else {
      const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t)
      const md = /^(\d{1,2})\/(\d{1,2})$/.exec(t)
      if (iso) date = `${iso[1]}-${iso[2]!.padStart(2, "0")}-${iso[3]!.padStart(2, "0")}`
      else if (md) date = `${today.slice(0, 4)}-${md[1]!.padStart(2, "0")}-${md[2]!.padStart(2, "0")}`
    }
    if (date) {
      tokens.splice(i, 1)
      return date
    }
  }
  return null
}

function shift(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function tokenize(text: string): string[] {
  return normalize(text)
    .replace(/(\d+)\s*月\s*(\d+)\s*[日號]/g, (_, m: string, d: string) => `${m}/${d}`)
    .replace(/[，,。！？?、;；:：]/g, " ")
    .replace(/@\s*/g, " @")
    .replace(/(\d)\s*(張|股|元|塊)/g, "$1 $2")
    .replace(/\$\s*(\d)/g, "@$1")
    .split(" ")
    .map((t) => t.trim())
    .filter(Boolean)
}

export function parseIntent(input: string, today: string): Intent {
  const raw = input.trim()
  if (!raw) return { kind: "empty" }
  const looksLikeQuestion = /[?？嗎呢]$|^(為什麼|怎麼|多少|哪|什麼|是否|會不會|能不能|可以)/.test(raw)
  const tokens = tokenize(raw)
  const date = takeDate(tokens, today)

  // ── 買賣 ──
  const sideIdx = tokens.findIndex((t) => BUY.test(t) || SELL.test(t) || /^(買進|買入|買|賣出|賣)/.test(t))
  if (sideIdx !== -1 && !looksLikeQuestion) {
    const head = tokens[sideIdx]!
    const side: TradeSide = /^賣/.test(head) ? "sell" : "buy"
    // 「買台積電」黏在一起時拆開
    const rest = head.replace(/^(買進|買入|賣出|賣掉|買|賣)/, "")
    const after = [...(rest ? [rest] : []), ...tokens.slice(sideIdx + 1), ...tokens.slice(0, sideIdx)].filter((t) => !FILLERS.has(t))
    let target: string | null = null
    let quantity: number | null = null
    let unit: "lot" | "share" | null = null
    let price: number | null = null
    const bare: number[] = []
    for (let i = 0; i < after.length; i++) {
      const t = after[i]!
      const next = after[i + 1]
      if (t.startsWith("@") && NUMBER.test(t.slice(1))) {
        price = Number(t.slice(1))
      } else if (NUMBER.test(t) && (next === "張" || next === "股")) {
        quantity = Number(t)
        unit = next === "張" ? "lot" : "share"
        i++
      } else if (NUMBER.test(t) && (next === "元" || next === "塊")) {
        price = Number(t)
        i++
      } else if (!target && CODE.test(t.toUpperCase()) && !(NUMBER.test(t) && t.length < 4)) {
        target = t.toUpperCase()
      } else if (NUMBER.test(t)) {
        bare.push(Number(t))
      } else if (!target && isCjkName(t)) {
        target = t
      }
    }
    if (quantity === null && bare.length > 0) quantity = bare.shift()!
    if (price === null && bare.length > 0) price = bare.shift()!
    if (target && quantity !== null && quantity > 0) {
      return { kind: "trade", side, target, quantity, unit, price: price !== null && price > 0 ? price : null, date }
    }
  }

  // ── 股利入帳 ──
  if (DIVIDEND_WORDS.test(raw) && !looksLikeQuestion) {
    const rest = tokens.filter((t) => !DIVIDEND_WORDS.test(t) && !FILLERS.has(t))
    let target: string | null = null
    let amount: number | null = null
    for (const t of rest) {
      if (!target && CODE.test(t.toUpperCase()) && !(NUMBER.test(t) && t.length < 4)) target = t.toUpperCase()
      else if (NUMBER.test(t) && amount === null) amount = Number(t)
      else if (!target && isCjkName(t)) target = t
    }
    if (target && amount !== null && amount > 0) return { kind: "dividend", target, amount, date }
  }

  // ── 只輸入代號或名稱：查股票 ──
  if (tokens.length === 1 && !looksLikeQuestion) {
    const t = tokens[0]!
    if (CODE.test(t.toUpperCase()) || (isCjkName(t) && t.length <= 8)) return { kind: "lookup", target: CODE.test(t.toUpperCase()) ? t.toUpperCase() : t }
  }

  return { kind: "question", text: raw }
}

/** 意圖的股數：張 × 1,000；美股或寫「股」就是股數 */
export function sharesOf(quantity: number, unit: "lot" | "share" | null, isUS: boolean): number {
  if (isUS) return quantity
  // 沒寫單位：1,000 以上視為股數（「買 0050 2000 52.4」），以下視為張數（「買 0050 2 52.4」）。草稿上會寫清楚，簽名前可以改。
  const resolved = unit ?? (quantity >= 1000 ? "share" : "lot")
  return resolved === "lot" ? Math.round(quantity * 1000) : Math.round(quantity)
}
