import type { MarketStatus } from "../types"
import { addDays, MOCK_AS_OF, MOCK_TODAY, nextTradingDay } from "./market"

/**
 * mock 的 `GET /meta/market-status`（台股）。示範資料的報價都是 MOCK_TODAY（11/12 四）的收盤價：
 * - `closed`（預設）：今天就是 11/12、已經收盤、收盤價已經進來 → 價格只標「收盤價・11/12（四）」，沒有說明。
 * - `open`：下一個交易日（11/13 五）盤中 → 「盤中不更新・到證交所看即時報價 ↗」
 * - `pending`：下一個交易日收盤後、當天的收盤價還沒公布 → 「今天的收盤價還沒公布」
 * 網址 `?market=open|pending|closed` 切換，記在 sessionStorage（和 `?policy=`、`?mock=` 同一種做法；`?market=closed` 切回）。
 * `open`／`pending` 時整個示範的「今天」與「現在」都是那個交易日（`mockToday`、`mockMarketNow`）：
 * 相對日期（「1 天前」「N 小時前」）、本週事項、討論的發言時間都跟著走，畫面上不會同時出現「今天是 11/12」和「11/12 是上一個收盤日」。
 */
export type MockMarket = "closed" | "open" | "pending"

/** 最後一個收盤日之後的下一個交易日（示範資料：11/13 五） */
const NEXT_DAY = nextTradingDay(addDays(MOCK_TODAY, 1))

/** 示範的「今天」（台北時間的日期）：`closed` 是最後一個收盤日，`open`／`pending` 是它的下一個交易日 */
export function mockToday(market: MockMarket = "closed"): string {
  return market === "closed" ? MOCK_TODAY : NEXT_DAY
}

export function mockMarketStatus(market: MockMarket): MarketStatus {
  return { tw: { date: mockToday(market), is_trading_day: true, is_open: market === "open", open: "09:00", close: "13:30" } }
}

/** 和上面的狀態對得起來的「現在」（台北時間） */
export function mockMarketNow(market: MockMarket = "closed"): Date {
  return new Date(market === "closed" ? MOCK_AS_OF : `${NEXT_DAY}T${market === "open" ? "10:30" : "15:10"}:00+08:00`)
}

export function readMockMarket(): MockMarket {
  if (typeof window === "undefined") return "closed"
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("market")
    if (fromUrl === "open" || fromUrl === "pending" || fromUrl === "closed") {
      window.sessionStorage.setItem("forliosa:market", fromUrl)
      return fromUrl
    }
    const saved = window.sessionStorage.getItem("forliosa:market")
    if (saved === "open" || saved === "pending") return saved
  } catch {
    // sessionStorage 不可用：用預設
  }
  return "closed"
}
