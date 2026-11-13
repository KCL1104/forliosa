import type { MarketStatus } from "../types"
import { addDays, MOCK_AS_OF, MOCK_TODAY } from "./market"

/**
 * mock 的 `GET /meta/market-status`（台股）。示範資料的報價都是 MOCK_TODAY（11/12 四）的收盤價：
 * - `closed`（預設）：今天就是 11/12、已經收盤、收盤價已經進來 → 價格只標「收盤價・11/12（四）」，沒有說明。
 * - `open`：隔天（11/13 五）盤中 → 「盤中不更新：這是 11/12（四）的收盤價。」
 * - `pending`：隔天收盤後、當天的收盤價還沒公布 → 「今天的收盤價還沒公布，這是 11/12（四）的收盤價。」
 * 網址 `?market=open|pending|closed` 切換，記在 sessionStorage（和 `?policy=`、`?mock=` 同一種做法；`?market=closed` 切回）。
 */
export type MockMarket = "closed" | "open" | "pending"

const NEXT_DAY = addDays(MOCK_TODAY, 1)

export function mockMarketStatus(market: MockMarket): MarketStatus {
  const closed = market === "closed"
  return { tw: { date: closed ? MOCK_TODAY : NEXT_DAY, is_trading_day: true, is_open: market === "open", open: "09:00", close: "13:30" } }
}

/** 和上面的狀態對得起來的「現在」（台北時間） */
export function mockMarketNow(market: MockMarket): Date {
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
