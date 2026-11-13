import type { Briefing, BriefingFacts, BriefingMover, Holding, PortfolioSummary, Quote, UpcomingItem } from "../types"
import { addDays, parseDay } from "./market"

/**
 * 每日收盤簡報的示範資料（mock 模式）。事實的部分和後端同一套規則，從示範帳本算（和帳本頁看到的數字一致）；
 * AI 補充的幾點是固定的示意句與示意來源。只有打開「每日收盤簡報」的人才有。
 */
const MOVERS = 2
const WATCH_MOVE_PCT = 0.03
const WATCH_MAX = 3
const UPCOMING_MAX = 5

/** 往回數第 n 個交易日（示範資料只排除週末） */
function tradingDayBefore(day: string, n: number): string {
  let d = day
  for (let left = n; left > 0; ) {
    d = addDays(d, -1)
    if (![0, 6].includes(parseDay(d).getUTCDay())) left--
  }
  return d
}

const mover = (h: Holding): BriefingMover => ({
  symbol: h.symbol, code: h.code, name: h.name, market: h.market, type: h.type, close: h.price, change_pct: h.day_change_pct, day_change: h.day_change,
})

export function buildFacts(
  summary: PortfolioSummary,
  holdings: Holding[],
  watch: { symbol: string; code: string; name: string; market: Holding["market"]; type: Holding["type"]; quote: Quote | null }[],
  upcoming: UpcomingItem[],
  demo: boolean,
): BriefingFacts {
  const priced = holdings.filter((h) => h.price !== null && h.day_change_pct !== null)
  const held = new Set(holdings.map((h) => h.symbol))
  return {
    market_value: summary.market_value,
    day_change: summary.day_change,
    day_change_pct: summary.day_change_pct,
    holdings: holdings.length,
    unpriced: holdings.filter((h) => h.price === null).length,
    gainers: priced.filter((h) => h.day_change_pct! > 0).sort((a, b) => b.day_change_pct! - a.day_change_pct!).slice(0, MOVERS).map(mover),
    losers: priced.filter((h) => h.day_change_pct! < 0).sort((a, b) => a.day_change_pct! - b.day_change_pct!).slice(0, MOVERS).map(mover),
    watchlist: watch
      .filter((w) => !held.has(w.symbol) && w.quote?.change_pct != null && Math.abs(w.quote.change_pct) >= WATCH_MOVE_PCT)
      .sort((a, b) => Math.abs(b.quote!.change_pct!) - Math.abs(a.quote!.change_pct!))
      .slice(0, WATCH_MAX)
      .map((w) => ({ symbol: w.symbol, code: w.code, name: w.name, market: w.market, type: w.type, close: w.quote!.price, change_pct: w.quote!.change_pct })),
    upcoming: upcoming.slice(0, UPCOMING_MAX).map((u) => ({ date: u.date, type: u.type, symbol: u.symbol, title: u.title, amount_estimate: u.amount_estimate })),
    is_demo: demo,
  }
}

/** AI 補充的示意句：講漲最多與跌最多的那一檔（來源是示意的） */
function points(facts: BriefingFacts): Briefing["points"] {
  const out: Briefing["points"] = []
  const up = facts.gainers[0]
  const down = facts.losers[0]
  if (up) out.push({ text: `${up.name}公布上月營收，年增兩成，買盤集中在電子權值股。`, sources: [{ url: "https://example.com/news/briefing-1", title: `${up.name}營收年增兩成`, outlet: "示範通訊社" }] })
  if (down) out.push({ text: `${down.name}法說會下修本季出貨展望，法人轉為賣超。`, sources: [{ url: "https://example.com/news/briefing-2", title: `${down.name}下修出貨展望`, outlet: "示範日報" }, { url: "https://example.com/news/briefing-3", title: "法人賣超名單", outlet: "示範財經網" }] })
  return out
}

/**
 * mock 的簡報清單：最新一則（收盤日）加前兩個交易日。舊的兩則用同一份事實、金額照比例縮小一點（只是讓列表有東西），
 * 預設都看過了；最新一則還沒看。
 */
export function createMockBriefings(day: string, facts: () => BriefingFacts) {
  const read = new Set<string>()
  const id = (d: string) => `brf_${d.replaceAll("-", "")}`
  const older = (n: number, scale: number): Briefing => {
    const d = tradingDayBefore(day, n)
    const f = facts()
    return {
      id: id(d), date: d, created_at: `${d}T22:20:00+08:00`, read: true,
      facts: { ...f, market_value: Math.round(f.market_value * scale), day_change: Math.round(-f.day_change * 0.4), day_change_pct: f.day_change_pct === null ? null : -f.day_change_pct * 0.4, gainers: f.losers.slice(0, 1).map((m) => ({ ...m, change_pct: m.change_pct === null ? null : Math.abs(m.change_pct) })), losers: f.gainers.slice(0, 1).map((m) => ({ ...m, change_pct: m.change_pct === null ? null : -Math.abs(m.change_pct) * 0.5 })), watchlist: [], upcoming: [] },
      points: [],
    }
  }
  const latest = (): Briefing => {
    const f = facts()
    return { id: id(day), date: day, created_at: `${day}T22:20:00+08:00`, read: read.has(id(day)), facts: f, points: points(f) }
  }
  return {
    latest,
    list: (limit = 14): Briefing[] => [latest(), older(1, 0.979), older(2, 0.985)].slice(0, limit),
    markRead: (briefingId: string): boolean => {
      const known = [id(day), id(tradingDayBefore(day, 1)), id(tradingDayBefore(day, 2))].includes(briefingId)
      if (known) read.add(briefingId)
      return known
    },
  }
}
