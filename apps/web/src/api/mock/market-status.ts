import type { MarketStatus, TwClose } from "../types"
import { addDays, MOCK_AS_OF, MOCK_TODAY, nextTradingDay, parseDay } from "./market"

/**
 * mock 的 `GET /meta/market-status`（台股）。示範資料的報價都是 MOCK_TODAY（11/12 四）的收盤價：
 * - `closed`（預設）：今天就是 11/12、已經收盤、收盤價已經進來 → 價格只標「收盤價・11/12（四）」，沒有說明。
 * - `open`：下一個交易日（11/13 五）盤中 → 「盤中不更新・到證交所看即時報價 ↗」
 * - `pending`：下一個交易日剛收盤（13:40）→ 上市「今天的收盤價預計下午 2:00–2:30 更新」、上櫃「…今晚 8:30–11:45 更新」
 * - `evening`：同一天晚上 9 點，上市下午那一批沒有進來 → 兩個市場都等晚上那一批（「今天的預計今晚 11:45 前更新」）
 * - `night`：隔天（11/14 六）凌晨 2 點，11/13 的還沒進來 → 上市「11/13 的收盤價還沒公布，預計清晨 5:20–5:45 更新」、
 *   上櫃晚上與半夜那兩批都過了「11/13 的收盤價還沒公布」
 * 網址 `?market=open|pending|evening|night|closed` 切換，記在 sessionStorage（和 `?policy=`、`?mock=` 同一種做法；`?market=closed` 切回）。
 * 不是 `closed` 時整個示範的「今天」與「現在」都跟著那個時刻（`mockToday`、`mockMarketNow`）：
 * 相對日期（「1 天前」「N 小時前」）、本週事項、討論的發言時間都跟著走，畫面上不會同時出現「今天是 11/12」和「11/12 是上一個收盤日」。
 * 預計更新的時間窗（`tw.closes`）由這個時刻算（`mockCloses`），和後端一樣：時間窗過了還沒進來，就換下一個來源的時間窗。
 */
export type MockMarket = "closed" | "open" | "pending" | "evening" | "night"
const MARKETS: readonly MockMarket[] = ["closed", "open", "pending", "evening", "night"]

/** 最後一個收盤日之後的下一個交易日（示範資料：11/13 五） */
const NEXT_DAY = nextTradingDay(addDays(MOCK_TODAY, 1))

/** 每個情境的「現在」（台北時間） */
const NOW: Record<MockMarket, string> = {
  closed: MOCK_AS_OF,
  open: `${NEXT_DAY}T10:30:00+08:00`,
  pending: `${NEXT_DAY}T13:40:00+08:00`,
  evening: `${NEXT_DAY}T21:00:00+08:00`,
  night: `${addDays(NEXT_DAY, 1)}T02:00:00+08:00`,
}

/** 示範的「今天」（台北時間的日期）：`closed` 是最後一個收盤日，其他是那個情境的「現在」那天 */
export function mockToday(market: MockMarket = "closed"): string {
  return NOW[market].slice(0, 10)
}

/** 和上面的狀態對得起來的「現在」（台北時間） */
export function mockMarketNow(market: MockMarket = "closed"): Date {
  return new Date(NOW[market])
}

const isWeekday = (day: string) => ![0, 6].includes(parseDay(day).getUTCDay())

/**
 * 一個市場收盤價進來的時間窗，依序（和後端 `forliosa.closes.WINDOWS` 一樣，來源都開著時；時間是 2026-11 實測的）：
 * - 上市：證交所在政府資料開放平臺登記的下載網址（下午）→ 永豐 shioaji-data（晚上，晚到的日子到半夜）→ 證交所 OpenAPI（隔天清晨）
 * - 上櫃：永豐 shioaji-data 與櫃買中心 OpenAPI（晚上）→ shioaji-data 晚到的日子（半夜）
 * `[距離交易日幾天, 開始, 結束]`
 */
const WINDOWS: Record<TwClose["market"], [number, string, string][]> = {
  TWSE: [
    [0, "14:00", "14:30"],
    [0, "20:30", "23:45"],
    [1, "00:00", "01:30"],
    [1, "05:20", "05:45"],
  ],
  TPEX: [
    [0, "20:30", "23:45"],
    [1, "00:00", "01:30"],
  ],
}

/**
 * `tw.closes`：`session` 是最近一個收盤價該進來的交易日（交易日 13:30 以後是今天，否則往前找）；
 * 示範資料只存到 `latest`（11/12），比 `session` 舊就是在等，時間窗取還沒過去的第一個。
 */
export function mockCloses(now: Date, latest: string = MOCK_TODAY): TwClose[] {
  const t = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
  const p = Object.fromEntries(t.formatToParts(now).map((x) => [x.type, x.value]))
  const today = `${p.year}-${p.month}-${p.day}`
  let session = isWeekday(today) && `${p.hour}:${p.minute}` >= "13:30" ? today : addDays(today, -1)
  while (!isWeekday(session)) session = addDays(session, -1)
  return (["TWSE", "TPEX"] as const).map((market) => {
    const stored = latest >= session
    const next = stored
      ? undefined
      : WINDOWS[market].map(([d, from, to]) => [`${addDays(session, d)}T${from}:00+08:00`, `${addDays(session, d)}T${to}:00+08:00`] as const).find(([, to]) => Date.parse(to) > now.getTime())
    return { market, session, stored, latest, interim: false, expected_from: next?.[0] ?? null, expected_to: next?.[1] ?? null }
  })
}

export function mockMarketStatus(market: MockMarket): MarketStatus {
  const now = mockMarketNow(market)
  const date = mockToday(market)
  return { tw: { date, is_trading_day: isWeekday(date), is_open: market === "open", open: "09:00", close: "13:30", closes: mockCloses(now) } }
}

export function readMockMarket(): MockMarket {
  if (typeof window === "undefined") return "closed"
  const known = (v: string | null): v is MockMarket => !!v && (MARKETS as readonly string[]).includes(v)
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("market")
    if (known(fromUrl)) {
      window.sessionStorage.setItem("forliosa:market", fromUrl)
      return fromUrl
    }
    const saved = window.sessionStorage.getItem("forliosa:market")
    if (known(saved)) return saved
  } catch {
    // sessionStorage 不可用：用預設
  }
  return "closed"
}
