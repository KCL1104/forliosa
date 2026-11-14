/**
 * 示範資料：ETF 淨值與盤後折溢價（`overview.etf_nav`，後端 apps/api/src/forliosa/services/etf_nav.py）。
 * 淨值由示範收盤價與一條平穩的折溢價序列反推，數字是模擬的；規則與後端相同：
 * - 折溢價 = 同一天的收盤價 ÷ 淨值 − 1；`premium_date` 是兩者都有的最近一天。
 * - 0050：存檔約 3 個月（畫走勢）；00878：存檔 8 天（資料累積中）；00679B：海外債券 ETF，淨值是前一個營業日的，
 *   最新收盤是今天，折溢價用前一天算；00999（壓力測試）與 00687B（上櫃債券 ETF）不在資料集裡。
 */
import type { EtfNav, NavPoint } from "../types"
import { sourceOf } from "./attributions"
import { ymd } from "./commercial"
import type { MockInstrumentSpec } from "./instruments"
import { dailyCandles, MOCK_TODAY, rng, tradingDays } from "./market"

export const NAV_SOURCE_KEY = "sfb-opendata/nav"
export const NAV_NOT_IN_DATASET_NOTE = "〈證券投資信託基金每日淨值〉沒有這檔 ETF 的淨值"
const HISTORY_POINTS = 60
const MIN_POINTS = 20

interface Scenario {
  /** 第一筆淨值存檔的日期 */
  start: string
  /** 淨值晚一個營業日（海外標的） */
  lag?: boolean
  /** 折溢價的平均與波動（比率） */
  mean: number
  spread: number
  /** 淨值的小數位（官方公布的位數） */
  decimals: number
}

const SCENARIOS: Record<string, Scenario | "missing"> = {
  "0050.TW": { start: "2026-08-17", mean: 0.0009, spread: 0.0016, decimals: 2 },
  "00878.TW": { start: "2026-11-03", mean: 0.0011, spread: 0.0009, decimals: 2 },
  "00679B.TWO": { start: "2026-09-14", lag: true, mean: 0.0055, spread: 0.0028, decimals: 4 },
  "00999.TW": "missing",
  // 多數上櫃債券 ETF 不在〈證券投資信託基金每日淨值〉裡（2026-11-12 實測）
  "00687B.TWO": "missing",
}
const DEFAULT_SCENARIO: Scenario = { start: "2026-09-01", mean: 0.0012, spread: 0.0014, decimals: 2 }

/** 〈證券投資信託基金每日淨值〉的基金名稱（2026-11-12 的原文） */
const FUND_NAMES: Record<string, string> = {
  "0050.TW": "元大台灣卓越50基金",
  "006208.TW": "富邦台灣釆吉50基金",
  "0056.TW": "元大台灣高股息基金",
  "00878.TW": "國泰台灣高股息傘型基金之台灣ESG永續高股息ETF基金",
  "00919.TW": "群益台灣精選高息ETF基金",
  "006201.TWO": "元大富櫃50基金",
  "00679B.TWO": "元大美國政府20年期(以上)債券基金",
}

const round = (n: number, d: number) => Math.round(n * 10 ** d) / 10 ** d

export function buildEtfNav(spec: MockInstrumentSpec): EtfNav | null {
  if (spec.market === "US" || spec.type !== "etf") return null
  const priceKey = spec.market === "TPEX" ? "tpex-openapi/price" : "twse-openapi/price"
  const scenario = SCENARIOS[spec.symbol] ?? DEFAULT_SCENARIO
  // 沒有淨值：所有數字都是 null（收盤價也不給，和後端一樣）、沒有要顯名的資料集
  const empty: EtfNav = {
    nav: null, nav_date: null, currency: null, fund_name: null, close: null, close_date: null,
    premium_pct: null, premium_date: null, history: [], history_start: null, history_missing: [], notes: [NAV_NOT_IN_DATASET_NOTE], sources: [],
  }
  if (scenario === "missing") return empty

  const closes = new Map(dailyCandles(spec).map((c) => [c.t, c.c]))
  const days = tradingDays(160).filter((d) => d >= scenario.start)
  const navDays = scenario.lag ? days.slice(0, -1) : days
  // 平穩的折溢價：均值回歸的隨機序列（AR(1)），只是讓示範走勢像樣
  const r = rng(`nav:${spec.symbol}`)
  let x = 0
  const points: NavPoint[] = []
  for (const t of navDays) {
    x = 0.72 * x + (r() - 0.5) * 1.1
    const close = closes.get(t)
    if (close === undefined) continue
    const nav = round(close / (1 + scenario.mean + scenario.spread * x), scenario.decimals)
    points.push({ t, nav, close, premium_pct: round(close / nav - 1, 6) })
  }
  const last = points.at(-1)
  if (!last) return empty
  const history = points.slice(-HISTORY_POINTS)
  return {
    nav: last.nav,
    nav_date: last.t,
    currency: "TWD",
    fund_name: FUND_NAMES[spec.symbol] ?? `${spec.name}基金`,
    close: spec.price,
    close_date: MOCK_TODAY,
    premium_pct: last.premium_pct,
    premium_date: last.t,
    history,
    history_start: points[0]!.t,
    // 示範存檔每個交易日都有（缺口的畫法見 EtfNavSection 的測試）
    history_missing: [],
    notes: points.length < MIN_POINTS ? [`淨值資料從 ${ymd(points[0]!.t)} 開始`] : [],
    sources: [sourceOf(NAV_SOURCE_KEY), sourceOf(priceKey)],
  }
}
