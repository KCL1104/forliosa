import type { Holding, MarketStatus, TwClose } from "@/api/types"
import { formatDateShort, TZ } from "@/lib/format"
import { usTradeDate } from "@/lib/labels"

/**
 * 收盤價的標示（見 api-contract「收盤價的標示與盤中狀態」）。
 * Forliosa 沒有盤中即時報價：價格都是收盤後公布的收盤價。畫面上要看得出來「這不是即時價格」——
 * 價格標「收盤價・日期」，盤中、或該進來的收盤價還沒進來時，多一行說明（還沒進來時寫預計幾點更新：
 * 時間窗由後端依開著的資料來源給，`market-status` 的 `tw.closes`）；其他時候不加說明。
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

/** 上市、上櫃（`market-status` 的 `tw.closes` 一個市場一筆） */
export type TwBoard = TwClose["market"]
export const BOARD_NAME: Record<TwBoard, string> = { TWSE: "上市", TPEX: "上櫃" }
const BOARDS: readonly TwBoard[] = ["TWSE", "TPEX"]

/** 某個市場的收盤狀態；舊版後端沒有 `closes`、或沒給市場時 undefined（照舊的判斷：今天收盤後就是還沒公布） */
export function twClose(market: MarketStatus["tw"] | null | undefined, board: TwBoard | null | undefined): TwClose | undefined {
  return board ? market?.closes?.find((c) => c.market === board) : undefined
}

/**
 * 三種狀態（台股與台股 ETF）：
 * - `open`：盤中（交易日 09:00–13:30），手上的還是之前的收盤價
 * - `pending`：該進來的收盤價還沒進來。有 `tw.closes` 時看這個市場（上市／上櫃）的 `stored`——
 *   半夜 12 點以後、隔天開盤前也算（11/16 的收盤價清晨才進來時，不能看起來像已經是最新的）；
 *   舊版後端沒有 `closes`：今天是交易日、13:30 以後
 * - `settled`：其他——最新的收盤價已經進來、今天不是交易日（假日、週末）而且沒有欠著的收盤價、或還沒開盤。不加說明
 * 市場狀態還沒載入（或載入失敗）時當成 `settled`：寧可不說，也不亂說。
 * `board` 是這個價格的市場（上市 TWSE、上櫃 TPEX；台股 ETF 跟著它掛牌的市場）。
 */
export type CloseState = "open" | "pending" | "settled"

export function closeState(market: MarketStatus["tw"] | null | undefined, asOf: string | null | undefined, now: Date, board?: TwBoard | null): CloseState {
  const day = closeDay(asOf)
  if (!market || !day) return "settled"
  // 收盤價的日期就是今天（或更新）：最新的已經進來了
  if (day >= market.date) return "settled"
  if (market.is_open) return "open"
  const close = twClose(market, board)
  // 這一檔的日期比該進來的那一天舊、而且那一天的還沒存：在等。已經存了還是舊的（停牌、沒有成交）就不說——
  // 只存了晚上的暫時收盤價時（`interim`）例外：那一批沒有 ETF，舊的還在等官方檔（後端給官方檔的時間窗）
  if (close) return (!close.stored || close.interim) && day < close.session ? "pending" : "settled"
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

// ── 預計更新的時間 ──────────────────────────────────────────────────

interface Clock {
  day: string
  h: number
  m: number
  ms: number
}

function clockOf(iso: string | null | undefined): Clock | null {
  if (!iso || Number.isNaN(Date.parse(iso))) return null
  const { day, time } = taipei(iso)
  const [h, m] = time.split(":").map(Number)
  return { day, h: h!, m: m!, ms: Date.parse(iso) }
}

type Period = "半夜" | "凌晨" | "清晨" | "早上" | "中午" | "下午" | "晚上"
function period(h: number): Period {
  if (h < 3) return "半夜"
  if (h < 5) return "凌晨"
  if (h < 7) return "清晨"
  if (h < 12) return "早上"
  if (h < 13) return "中午"
  if (h < 18) return "下午"
  return "晚上"
}

/** 12 小時制：「2:00」「11:45」「12:05」 */
const hm = (c: Clock) => `${c.h % 12 || 12}:${String(c.m).padStart(2, "0")}`

function nextDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number)
  return new Date(Date.UTC(y!, m! - 1, d! + 1)).toISOString().slice(0, 10)
}

/** 那個時刻是「哪一天的哪一段」：今天「下午」「今晚」「清晨」；明天「明天清晨」「明晚」；今晚過了 12 點就是「半夜」「凌晨」；更遠寫日期 */
function when(c: Clock, today: string): string {
  const p = period(c.h)
  if (c.day === today) return p === "晚上" ? "今晚" : p
  if (c.day === nextDay(today)) return p === "晚上" ? "明晚" : p === "半夜" || p === "凌晨" ? p : `明天${p}`
  return `${formatDateShort(c.day, false)} ${p}`
}

/**
 * 預計進來的時間窗（後端的 `expected_from`／`expected_to`，依目前開著的來源與現在的時間）寫成字：
 * - `full`：「下午 2:00–2:30」「今晚 8:30–11:45」「半夜 12:00–1:30」「清晨 5:20–5:45」「明天清晨 5:20–5:45」「今晚 11:30 到半夜 1:30」；
 *   已經在時間窗裡：「下午 2:30 前」（開始的時間已經過了，不再寫）
 * - `short`（帳本兩個市場並列時）：窄的時間窗（一小時內）寫「下午 2:30 前」，寬的只寫「今晚」
 * 時間窗已經過了（後端還沒換成下一個來源）：null——不寫一個已經過去的時間。
 */
export function expectedWindow(close: Pick<TwClose, "expected_from" | "expected_to"> | null | undefined, now: Date): { full: string; short: string } | null {
  const from = clockOf(close?.expected_from)
  const to = clockOf(close?.expected_to)
  if (!from || !to || to.ms < now.getTime()) return null
  const today = taipei(now).day
  const until = `${when(to, today)} ${hm(to)} 前`
  if (from.ms <= now.getTime()) return { full: until, short: until }
  const samePart = from.day === to.day && period(from.h) === period(to.h)
  const full = samePart ? `${when(from, today)} ${hm(from)}–${hm(to)}` : `${when(from, today)} ${hm(from)} 到${when(to, today)} ${hm(to)}`
  return { full, short: samePart && to.ms - from.ms <= 60 * 60_000 ? until : when(from, today) }
}

/** 「預計下午 2:00–2:30 更新」「預計下午 2:30 前更新」「預計今晚更新」：數字和字之間空一格 */
const expectUpdate = (when: string) => `預計${when}${/\d$/.test(when) ? " " : ""}更新`

/** 「今天的」或「11/16 的」：在等的是哪一天的收盤價 */
function whichDay(session: string | null | undefined, today: string): string {
  return !session || session >= today ? "今天的" : `${formatDateShort(session, false)} 的`
}

/**
 * 價格下面那一行說明（`settled` 沒有）。不重複日期——上面一行已經寫了「收盤價・11/12（四）」；
 * 漲跌旁另外標那是哪一天的漲跌（`dayWord`）。
 * - 盤中：「盤中不更新」
 * - 在等：「今天的收盤價預計下午 2:00–2:30 更新」「今天的收盤價預計今晚 8:30–11:45 更新」；
 *   半夜以後在等前一個交易日的：「11/16 的收盤價還沒公布，預計清晨 5:20–5:45 更新」；
 *   不知道什麼時候（舊版後端、時間窗過了）：「今天的收盤價還沒公布」「11/16 的收盤價還沒公布」
 */
export function closeNote(state: CloseState, asOf: string | null | undefined, close?: TwClose | null, now: Date = new Date()): string | null {
  if (!closeDay(asOf) || state === "settled") return null
  if (state === "open") return "盤中不更新"
  const which = whichDay(close?.session, taipei(now).day)
  const w = expectedWindow(close, now)
  if (!w) return `${which}收盤價還沒公布`
  return which === "今天的" ? `今天的收盤價${expectUpdate(w.full)}` : `${which}收盤價還沒公布，${expectUpdate(w.full)}`
}

// ── 帳本、市場頁：上市與上櫃一起 ─────────────────────────────────────

/** 一個市場的收盤價是哪一天（帳本：持股的 `price_date`；市場頁：後端存到的那天） */
export interface BoardDay {
  board: TwBoard
  day: string
  /** 帳本：這個市場最舊的持股日期（和 `day` 一樣時可省略）。只存了晚上的暫時收盤價時用來看 ETF 是不是還在等 */
  oldest?: string
}

/**
 * 帳本裡上市、上櫃各自的收盤日：有價格的台股持股的 `price_date`，每個市場取最新的那天
 * （一檔停牌不影響整個市場）；舊版後端沒有 `price_date` 時用 `as_of` 的台北日期。沒有台股持股時是空的。
 * `oldest` 是最舊的那天：晚上先進來的暫時收盤價沒有 ETF，那時候 ETF 的價格還是前一天的（`closeLine`）。
 */
export function ledgerBoardDays(holdings: readonly Pick<Holding, "market" | "price" | "price_date">[] | null | undefined, asOf: string | null | undefined): BoardDay[] {
  const fallback = closeDay(asOf)
  const out: BoardDay[] = []
  for (const board of BOARDS) {
    const days = (holdings ?? []).filter((h) => h.market === board && h.price !== null).map((h) => h.price_date ?? fallback).filter((d): d is string => !!d)
    if (!days.length) continue
    const day = days.reduce((a, b) => (b > a ? b : a))
    const oldest = days.reduce((a, b) => (b < a ? b : a))
    out.push(oldest === day ? { board, day } : { board, day, oldest })
  }
  return out
}

/**
 * 一個市場「還在等的那一檔」的日期：只存了晚上的暫時收盤價（`interim`）時是最舊的持股日期——那一批沒有 ETF，
 * ETF 還是前一天的價格、還在等官方檔；其他時候是最新的那天（停牌的一檔不算在等）
 */
function waitingDay(market: MarketStatus["tw"] | null | undefined, b: BoardDay): string {
  return twClose(market, b.board)?.interim && b.oldest ? b.oldest : b.day
}

/**
 * 帳本主數字旁那一行（市場頁標題旁的說明也是）：
 * - `label`：「11/13 收盤」；兩個市場的日期不同時「上市 11/16・上櫃 11/13 收盤」；盤中「11/12 收盤・盤中不更新」
 * - `note`（只在有市場在等時）：帳本裡的市場都在等同一個時間窗（包括只有上市的帳本）——「今天的預計下午 2:00–2:30 更新」
 *   「11/16 的預計清晨 5:20–5:45 更新」「今天的還沒公布」；只有一個市場在等——「上櫃預計今晚 8:30–11:45 更新」；
 *   兩個市場的時間窗不同——「上市預計下午 2:30 前更新・上櫃預計今晚更新」
 * - `day`：「今日」損益、「今日漲跌」的那個詞：每個市場的收盤日都是今天才寫「今日」；都是同一天寫那天（「11/12」）；
 *   上市、上櫃的日期不同時寫「當日」（每一檔是它自己那天的漲跌）
 * `boards` 是空的（還不知道持股）時照 `asOf` 一個日期判斷：有 `closes` 時哪個市場在等就說哪個。
 */
export function closeLine(
  market: MarketStatus["tw"] | null | undefined,
  boards: readonly BoardDay[],
  asOf: string | null | undefined,
  now: Date,
  today: string,
): { label: string; note: string | null; day: string } {
  if (boards.length === 0) {
    const day = closeDay(asOf)
    const word = dayWord(asOf, today)
    if (!day) return { label: "", note: null, day: word }
    const base = `${formatDateShort(day, false)} 收盤`
    const closes = market?.closes
    if (!market || !closes) {
      const state = closeState(market, asOf, now)
      return { label: state === "open" ? `${base}・盤中不更新` : base, note: state === "pending" ? "今天的還沒公布" : null, day: word }
    }
    if (day >= market.date) return { label: base, note: null, day: word }
    if (market.is_open) return { label: `${base}・盤中不更新`, note: null, day: word }
    const waiting = closes.filter((c) => !c.stored && day < c.session)
    return { label: base, note: waiting.length ? pendingNote(waiting, waiting.length, now, today) : null, day: word }
  }
  const days = boards.map((b) => b.day)
  const same = days.every((d) => d === days[0])
  const base = same ? `${formatDateShort(days[0]!, false)} 收盤` : `${boards.map((b) => `${BOARD_NAME[b.board]} ${formatDateShort(b.day, false)}`).join("・")} 收盤`
  // 只存了晚上的暫時收盤價、ETF 還是前一天的：每一檔是它自己那天的漲跌，寫「當日」，不寫「今日」
  const lagging = boards.some((b) => waitingDay(market, b) !== b.day)
  const day = lagging ? "當日" : days.every((d) => d === today) ? "今日" : same ? formatDateShort(days[0]!, false) : "當日"
  if (!market) return { label: base, note: null, day }
  if (market.is_open && days.some((d) => d < market.date)) return { label: `${base}・盤中不更新`, note: null, day }
  const waiting = boards
    .filter((b) => closeState(market, `${waitingDay(market, b)}T13:30:00+08:00`, now, b.board) === "pending")
    .map((b) => twClose(market, b.board) ?? { market: b.board })
  return { label: base, note: waiting.length ? pendingNote(waiting, boards.length, now, today) : null, day }
}

/** 在等的一個市場：`TwClose`；舊版後端沒有 `closes` 時只知道是哪個市場 */
type Waiting = TwClose | { market: TwBoard }
const info = (c: Waiting): TwClose | undefined => ("session" in c ? c : undefined)

/** `closeLine` 的 `note`：`waiting` 是在等的市場，`boards` 是這一頁有幾個市場 */
function pendingNote(waiting: readonly Waiting[], boards: number, now: Date, today: string): string {
  const which = (c: Waiting) => whichDay(info(c)?.session, today)
  const text = (c: Waiting, short: boolean) => {
    const w = expectedWindow(info(c), now)
    return w ? expectUpdate(short ? w.short : w.full) : "還沒公布"
  }
  const key = (c: Waiting) => `${which(c)}|${text(c, false)}`
  // 每個市場都在等、而且是同一天、同一個時間窗（包括只有一個市場）：不寫市場的名稱
  if (waiting.length === boards && waiting.every((c) => key(c) === key(waiting[0]!))) return `${which(waiting[0]!)}${text(waiting[0]!, false)}`
  // 只有一個市場在等（另一個已經進來了）
  if (waiting.length === 1) {
    const c = waiting[0]!
    return which(c) === "今天的" ? `${BOARD_NAME[c.market]}${text(c, false)}` : `${BOARD_NAME[c.market]} ${which(c)}收盤${text(c, false)}`
  }
  // 兩個市場的時間窗不同：短的寫法並列
  const days = new Set(waiting.map(which))
  const lead = days.size === 1 && which(waiting[0]!) !== "今天的" ? `${which(waiting[0]!)}收盤：` : ""
  return lead + waiting.map((c) => `${BOARD_NAME[c.market]}${text(c, true)}`).join("・")
}

/**
 * 市場頁指數那一排下面的一行：上市個股的收盤價已經進來、加權指數還沒有時（證交所下午的指數檔被擋、或晚上那一批——
 * 它沒有指數），寫指數預計什麼時候進來：「加權指數預計明天清晨 5:20–5:45 更新」，半夜以後
 * 「加權指數 11/16 的收盤預計清晨 5:20–5:45 更新」，不知道時「加權指數還沒更新」。上市個股也還在等時不寫（標題旁已經說了）。
 * `close` 是上市那一筆（`tw.closes` 的 TWSE）；舊版後端沒有 `index`：null。
 */
export function indexNote(close: TwClose | null | undefined, now: Date): string | null {
  const index = close?.index
  if (!close || !index || index.stored || !close.stored) return null
  const which = whichDay(close.session, taipei(now).day)
  const w = expectedWindow(index, now)
  if (!w) return "加權指數還沒更新"
  return which === "今天的" ? `加權指數${expectUpdate(w.full)}` : `加權指數 ${which}收盤${expectUpdate(w.full)}`
}

/**
 * 「今日」損益、「今日漲跌」的那個「今日」：收盤價的日期就是今天才寫「今日」，否則寫那個日期（「11/12」）。
 * `today` 是台北時間的今天（`market-status` 的 `tw.date`）。
 */
export function dayWord(asOf: string | null | undefined, today: string): string {
  const day = closeDay(asOf)
  return !day || day === today ? "今日" : formatDateShort(day, false)
}

/**
 * 收盤價進來了沒有：和上一次的 `tw.closes` 比，任何一個市場的 `latest`（存到哪一天）、`interim`（官方檔覆蓋了暫時的）變了，
 * 或 `stored` 從還沒變成有了，就重新讀帳本、報價與市場頁（`useCloseRefresh`）。
 * 13:30 換成等今天的（`session` 往前、`stored` 變回 false）不算：資料沒有變。第一次（`prev` 還沒有）也不算。
 */
export function closesChanged(prev: readonly TwClose[] | null | undefined, next: readonly TwClose[] | null | undefined): boolean {
  if (!prev || !next) return false
  return next.some((n) => {
    const p = prev.find((c) => c.market === n.market)
    if (!p) return false
    return p.latest !== n.latest || p.interim !== n.interim || (!p.stored && n.stored && p.session === n.session)
  })
}

/** 這個時刻在紐約是不是正好 16:00:00（美股的報價一律標在紐約 16:00 收盤） */
function isUsCloseStamp(asOf: string | null | undefined): boolean {
  if (!asOf || Number.isNaN(Date.parse(asOf))) return false
  const hms = new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(new Date(asOf))
  return hms === "16:00:00"
}

/**
 * 帳本只有美股有價格時，那是紐約哪一天的收盤（YYYY-MM-DD）；否則 null，照台股的寫法（`closeState`、`dayWord`）。
 * 後端（與 mock）的 `summary.as_of`：只要有一檔不是美股的持股有價格，就是台股的收盤時刻；只有美股時是紐約 16:00——
 * 在台北已經是隔天清晨，不能拿台北的日期說「11/14 收盤・盤中不更新」或「今日」。
 * 日期取美股持股 `price_date` 最大的那天；舊版後端沒有這個欄位時由 `as_of` 換算。
 * 持股還沒載入（或載入失敗）時看 `as_of` 本身：美股的報價一律是紐約 16:00:00，`as_of` 正好是那個時刻才當成美股的收盤。
 * 不看 `allocation.by_market`——沒有價格的持股在那裡以成本計；全部都沒有價格時 `as_of` 是「現在」，換成紐約的日期可能是週日。
 */
export function ledgerUsCloseDay(
  summary: { as_of?: string | null } | null | undefined,
  holdings: readonly Pick<Holding, "market" | "price" | "price_date">[] | null | undefined,
): string | null {
  if (!holdings) return isUsCloseStamp(summary?.as_of) ? usTradeDate(null, summary?.as_of) : null
  const priced = holdings.filter((h) => h.price !== null)
  if (priced.length === 0 || priced.some((h) => h.market !== "US")) return null
  const days = priced.map((h) => h.price_date).filter((d): d is string => !!d)
  return days.length > 0 ? days.reduce((a, b) => (b > a ? b : a)) : usTradeDate(null, summary?.as_of)
}

/**
 * 「今日漲跌」→「11/12 漲跌」：把標籤開頭的「今日」換成收盤價的日期（日期和後面的字之間空一格）；
 * 上市、上櫃日期不同時是「當日漲跌」（字和字之間不空格）
 */
export function withDayWord(label: string, word: string): string {
  if (word === "今日" || !label.startsWith("今日")) return label
  const rest = label.slice(2)
  return rest ? `${word}${/\d$/.test(word) ? " " : ""}${rest}` : word
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
