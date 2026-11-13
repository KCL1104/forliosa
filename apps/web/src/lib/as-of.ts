import type { MarketStatus } from "@/api/types"
import { formatDateShort, TZ } from "@/lib/format"

/**
 * 收盤價的標示（見 api-contract「收盤價的標示與盤中狀態」）。
 * Forliosa 沒有盤中即時報價：價格都是收盤後公布的收盤價。畫面上要看得出來「這不是即時價格」——
 * 價格標「收盤價・日期」，盤中、或收盤後今天的收盤價還沒公布時，多一行說明；其他時候不加說明。
 * 這裡都是純函式（不讀時鐘、不打 API）：現在的時間由呼叫的人給。
 */

/** 台北時間的日期（YYYY-MM-DD）與時刻（HH:mm） */
function taipei(at: string | Date): { day: string; time: string } {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(typeof at === "string" ? new Date(at) : at)
      .map((x) => [x.type, x.value]),
  )
  return { day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` }
}

/** 收盤價所屬的交易日（台北時間的日期）；沒有或看不懂時是 null */
export function closeDay(asOf: string | null | undefined): string | null {
  if (!asOf || Number.isNaN(Date.parse(asOf))) return null
  return taipei(asOf).day
}

/**
 * 三種狀態（台股與台股 ETF）：
 * - `open`：盤中（交易日 09:00–13:30），手上的還是之前的收盤價
 * - `pending`：今天是交易日、已經收盤（13:30 起），但今天的收盤價還沒公布
 * - `settled`：其他——最新的收盤價已經進來、今天不是交易日（假日、週末）、或還沒開盤。不加說明
 * 市場狀態還沒載入（或載入失敗）時當成 `settled`：寧可不說，也不亂說。
 */
export type CloseState = "open" | "pending" | "settled"

export function closeState(market: MarketStatus["tw"] | null | undefined, asOf: string | null | undefined, now: Date): CloseState {
  const day = closeDay(asOf)
  if (!market || !day) return "settled"
  // 收盤價的日期就是今天（或更新）：最新的已經進來了
  if (day >= market.date) return "settled"
  if (market.is_open) return "open"
  const clock = taipei(now)
  if (market.is_trading_day && clock.day === market.date && clock.time >= market.close) return "pending"
  return "settled"
}

/** 「11/12（四）」 */
const dayText = (asOf: string | null | undefined) => {
  const day = closeDay(asOf)
  return day ? formatDateShort(day) : ""
}

/** 價格的標示：「收盤價・11/12（四）」 */
export function closeLabel(asOf: string | null | undefined): string {
  const day = dayText(asOf)
  return day ? `收盤價・${day}` : "收盤價"
}

/** 價格下面那一行說明（`settled` 沒有）：盤中不更新／今天的收盤價還沒公布 */
export function closeNote(state: CloseState, asOf: string | null | undefined): string | null {
  const day = dayText(asOf)
  if (!day || state === "settled") return null
  return state === "open" ? `盤中不更新：這是 ${day}的收盤價。` : `今天的收盤價還沒公布，這是 ${day}的收盤價。`
}

/** 帳本主數字旁的時間：「11/12 收盤・盤中不更新」「11/12 收盤・今天的還沒公布」「11/13 收盤」 */
export function ledgerAsOf(state: CloseState, asOf: string | null | undefined): string {
  const day = closeDay(asOf)
  if (!day) return ""
  const base = `${formatDateShort(day, false)} 收盤`
  return state === "open" ? `${base}・盤中不更新` : state === "pending" ? `${base}・今天的還沒公布` : base
}

/**
 * 「今日」損益、「今日漲跌」的那個「今日」：收盤價的日期就是今天才寫「今日」，否則寫那個日期（「11/12」）。
 * `today` 是台北時間的今天（`market-status` 的 `tw.date`）。
 */
export function dayWord(asOf: string | null | undefined, today: string): string {
  const day = closeDay(asOf)
  return !day || day === today ? "今日" : formatDateShort(day, false)
}

/** 「今日漲跌」→「11/12 漲跌」：把標籤開頭的「今日」換成收盤價的日期（日期和後面的字之間空一格） */
export function withDayWord(label: string, word: string): string {
  if (word === "今日" || !label.startsWith("今日")) return label
  const rest = label.slice(2)
  return rest ? `${word} ${rest}` : word
}

/**
 * 證交所「基本市況報導」的個股頁：只是給使用者按的連結（另開新視窗），本站不擷取那個網站。
 * 網址格式（產品負責人 2026-11-13 提供）：`detail-item?id=<tse|otc>_<代號>.tw&ex=<tse|otc>&lang=zhHant`，上市是 tse、上櫃是 otc。
 */
export function twseLiveQuoteUrl(code: string, market: "TWSE" | "TPEX"): string {
  const ex = market === "TPEX" ? "otc" : "tse"
  return `https://mis.twse.com.tw/stock/detail-item?id=${ex}_${encodeURIComponent(code)}.tw&ex=${ex}&lang=zhHant`
}

/** 美股等其他市場的報價時間：「11/12 05:00 收盤」（台北時間） */
export function asOfLabel(iso: string | null | undefined): string {
  if (!iso) return ""
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("zh-TW", { timeZone: TZ, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })
      .formatToParts(new Date(iso))
      .map((p) => [p.type, p.value]),
  )
  return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute} 收盤`
}
