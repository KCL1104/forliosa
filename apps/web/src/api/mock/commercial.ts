import type { Candle } from "../types"
import type { MockInstrumentSpec } from "./instruments"
import { addDays, dailyCandles, MOCK_TODAY, parseDay } from "./market"

/**
 * mock 的資料政策（與後端 `DATA_POLICY` 對應）：
 * - `commercial`（預設，和後端一樣）：沒有示範標記（`is_demo: false`）；存檔不足的地方回空資料＋`notes`，
 *   文字與後端相同（apps/api/src/forliosa/services/coverage.py）。
 * - `personal`：舊的示範資料（全部標示 `is_demo`），網址 `?policy=personal` 切換。
 * mock 本身仍是瀏覽器裡產生的模擬數字；設定頁「關於資料」會說明。
 */
export type MockPolicy = "commercial" | "personal"

/** 示範的「自建存檔」從這天開始：之前的日線、本益比、籌碼與績效都沒有 */
export const ARCHIVE_START = "2026-06-01"
/** 美股收盤價（Databento EQUS.SUMMARY）從這天開始：新追蹤的美股回補到這一天（和後端 `us_prices.FIRST_DAY` 相同） */
export const US_ARCHIVE_START = "2024-07-01"
/**
 * Yahoo 的歷史日線回補（正式環境開著，`PRICE_HISTORY_SOURCE=yahoo`）：存檔開始以前五年的台股日線。
 * mock 拿它當記一筆的「參考收盤」（`GET /instruments/{symbol}/close` 的 `reference: true`；產品負責人 2026-11-17），
 * 也拿來算存檔開始以前的績效、報酬與群組排行（產品負責人 2026-11-18；回應多一句 `referenceNote`、`reference_until`）。
 */
export const BACKFILL_START = "2021-11-12"
/** 和後端 `services.reference_close.REFERENCE_NOTE` 相同 */
export const REFERENCE_NOTE = "非官方資料"
/** 和後端 `services.reference_close.reference_note` 相同：這一天（含）以前用參考價計算 */
export const referenceNote = (until: string) => `${ymd(until)} 以前・參考價`
/** 和後端 `services.reference_close.price_only_note` 相同：股票基準在存檔開始以前沒有除息資料，只算價格 */
export const priceOnlyNote = (name: string, until: string) => `${name}在 ${ymd(until)} 以前只算價格，不含股利`
/** 和後端 `datapolicy` 的 `yahoo-history` 標示相同（資料來源頁尾） */
export const YAHOO_HISTORY_LABEL = "存檔開始以前的歷史日線（非官方資料）"

/** 和後端 `coverage.ymd` 一樣：說明裡的日期寫成 2026/06/01 */
export const ymd = (iso: string) => iso.replaceAll("-", "/")
export const accumulatingNote = (since = ARCHIVE_START) => `資料從 ${ymd(since)} 開始`
/** 和後端 `coverage.NO_DATA_NOTE` 相同：這一檔一筆資料都還沒有（例如剛加入、還沒抓到收盤價的美股） */
export const NO_DATA_NOTE = "還沒有資料"
export const INTRADAY_NOTE = "沒有盤中走勢，價格是收盤後公布的收盤價"
export const TWSE_CHIPS_NOTE = "上市股票沒有逐檔三大法人資料；外資持股只公布前 20 名"
/** 名列外資持股前 20 名的上市股票：同樣說明為什麼沒有三大法人，但不含外資持股那一句 */
export const TWSE_INST_NOTE = "上市股票沒有逐檔三大法人資料"
export const TOP20_NOTE = "外資持股只公布前 20 名，這檔只有名列前 20 名的日子才有外資持股比"
export const INDEX_NOTE = "沒有 發行量加權股價報酬指數 的資料，不能比較"
/** 美股的估值：沒有本益比、股價淨值比的來源（SEC 的 EPS 只在財務分頁） */
export const US_VALUATION_NOTE = "美股沒有本益比區間（沒有美股的估值資料）"

// ── 美股收盤價（商用模式；產品負責人 2026-11-15，Databento） ─────────────
/**
 * 商用模式哪些美股有收盤價：內建清單的美股（AAPL、NVDA、VOO、QQQ，以及市場頁的 SPY、DIA、ONEQ）。
 * 只有 SEC 代號表認得的美股（MSFT、TSLA、T…）模擬「剛加入、還沒抓到收盤價」：`/quote` 404（`has_quote` 照合約仍是 true）。
 */
export const hasUsCloses = (s: MockInstrumentSpec) => s.market === "US" && s.listing !== "sec"

/** 台北日期 `today` 之前的最後一個美股交易日（紐約日期；示範資料只排除週末）：美股收盤時台北已經是隔天早上 */
export function usSessionBefore(today: string): string {
  let d = addDays(today, -1)
  while ([0, 6].includes(parseDay(d).getUTCDay())) d = addDays(d, -1)
  return d
}

/** 示範資料最新的美股交易日（紐約）：示範的「今天」11/12（四）之前的 11/11（三） */
export const US_SESSION = usSessionBefore(MOCK_TODAY)

/**
 * 那一天紐約 16:00 收盤是台北的幾點（+08:00，和後端 `iso_taipei(us_close_dt(d))` 相同）：
 * 冬令時間是隔天 05:00、夏令時間是隔天 04:00。
 */
export function usCloseAt(day: string): string {
  const nyHour = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", hourCycle: "h23" })
  // 夏令（UTC−4）的 16:00 是 20:00Z，冬令（UTC−5）是 21:00Z
  const utc = [20, 21].map((h) => new Date(`${day}T${h}:00:00Z`)).find((t) => Number(nyHour.format(t)) === 16) ?? new Date(`${day}T21:00:00Z`)
  return `${new Date(utc.getTime() + 8 * 3_600_000).toISOString().slice(0, 19)}+08:00`
}

/** 最新美股收盤的時間（台北）：11/11 紐約 16:00＝11/12 05:00 */
export const US_AS_OF = usCloseAt(US_SESSION)

const usCache = new Map<string, Candle[]>()
/**
 * 商用模式的美股日線：示範日線往前挪一個交易日，最後一根（＝示範報價）落在紐約的 `US_SESSION`，不是台北的今天。
 * 個人模式（示範資料）照舊用 `dailyCandles`。
 */
export function usCandles(spec: MockInstrumentSpec): Candle[] {
  const hit = usCache.get(spec.symbol)
  if (hit) return hit
  const raw = dailyCandles(spec)
  const out = raw.slice(1).map((c, i) => ({ ...c, t: raw[i]!.t }))
  usCache.set(spec.symbol, out)
  return out
}

export function readMockPolicy(): MockPolicy {
  if (typeof window === "undefined") return "commercial"
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("policy")
    if (fromUrl === "commercial" || fromUrl === "personal") {
      window.sessionStorage.setItem("forliosa:policy", fromUrl)
      return fromUrl
    }
    if (window.sessionStorage.getItem("forliosa:policy") === "personal") return "personal"
  } catch {
    // sessionStorage 不可用：用預設
  }
  return "commercial"
}
