import type { Account, SharedHolding, Transaction, UserRef } from "../types"
import { syncAutoDividends } from "./auto-dividends"
import { computePreview } from "./fees"
import { findInstrument } from "./instruments"
import { closeOn, MOCK_TODAY, nextTradingDay } from "./market"

/**
 * 示範群組裡的其他人（M5）。
 * - 爸爸有完整的帳本（兩個帳戶）：授權唯讀查看、他的動態與分享內容都從這本帳算出來，彼此一致。
 * - 其他成員只有分享出去會用到的數字（報酬率、持股權重、金額、最近的買賣）。
 * 名稱是示範用的稱呼，不是真實的人。
 */
export const PEOPLE = {
  dad: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null },
  mom: { user_id: "usr_mom", display_name: "媽媽", avatar_url: null },
  sis: { user_id: "usr_sis", display_name: "姊姊", avatar_url: null },
  bro: { user_id: "usr_bro", display_name: "阿弟", avatar_url: null },
  kai: { user_id: "usr_kai", display_name: "阿凱", avatar_url: null },
  yun: { user_id: "usr_yun", display_name: "小芸", avatar_url: null },
  ming: { user_id: "usr_ming", display_name: "志明", avatar_url: null },
  wang: { user_id: "usr_wang", display_name: "王叔叔", avatar_url: null },
  lin: { user_id: "usr_lin", display_name: "林老師", avatar_url: null },
  chen: { user_id: "usr_chen", display_name: "陳同學", avatar_url: null },
} satisfies Record<string, UserRef>

export const DAD_ACCOUNTS: Account[] = [
  {
    id: "acc_dad_yuanta", name: "元大－爸爸", broker: "元大證券", currency: "TWD",
    fee_rate: 0.001425, fee_discount: 0.6, min_fee: 20, min_fee_odd_lot: 1,
    tracking_mode: "transactions", created_at: "2024-01-05T10:00:00+08:00",
  },
  {
    id: "acc_dad_fubon", name: "富邦－退休金", broker: "富邦證券", currency: "TWD",
    fee_rate: 0.001425, fee_discount: 0.5, min_fee: 20, min_fee_odd_lot: 1,
    tracking_mode: "transactions", created_at: "2024-02-01T10:00:00+08:00",
  },
]

let seq = 0
function trade(side: "buy" | "sell", account: Account, symbol: string, day: string, qty: number, note = "", createdAt?: string): Transaction {
  const spec = findInstrument(symbol)!
  const d = nextTradingDay(day)
  const price = closeOn(spec, d)
  const p = computePreview({ account_id: account.id, symbol, type: side, trade_date: d, quantity: qty, price }, account, spec)
  seq += 1
  return {
    id: `txn_dad_${String(seq).padStart(4, "0")}`, account_id: account.id, symbol, type: side, trade_date: d, quantity: qty, price,
    amount: p.gross, fee: p.fee, tax: p.tax, health_insurance: 0, currency: "TWD", is_day_trade: false, note, source: "manual",
    created_at: createdAt ?? `${d}T19:30:00+08:00`,
  }
}
function deposit(account: Account, day: string, amount: number): Transaction {
  seq += 1
  return {
    id: `txn_dad_${String(seq).padStart(4, "0")}`, account_id: account.id, symbol: null, type: "deposit", trade_date: day, quantity: null, price: null,
    amount, fee: 0, tax: 0, health_insurance: 0, currency: "TWD", is_day_trade: false, note: "", source: "manual", created_at: `${day}T10:00:00+08:00`,
  }
}

/** 爸爸的帳本：元大（個股）＋富邦（退休金，高股息 ETF 與 0050 定期定額）。最近 90 天有買賣，動態與合併規則看得到 */
export function seedDadTransactions(): Transaction[] {
  seq = 0
  const [yuanta, fubon] = DAD_ACCOUNTS as [Account, Account]
  const t: Transaction[] = [
    deposit(yuanta, "2024-01-05", 3_000_000),
    deposit(fubon, "2024-02-01", 2_000_000),
    trade("buy", yuanta, "2330.TW", "2024-01-15", 1000),
    trade("buy", yuanta, "2881.TW", "2024-03-04", 5000),
    trade("buy", fubon, "0056.TW", "2024-03-18", 10000),
    trade("buy", yuanta, "2317.TW", "2024-06-03", 3000),
    trade("buy", fubon, "00878.TW", "2024-09-02", 8000),
    trade("buy", yuanta, "2330.TW", "2025-04-09", 1000),
    trade("buy", yuanta, "2454.TW", "2025-07-01", 200),
    // 最近 90 天：每月 6 日兩個帳戶都扣 0050（同一天同一檔 → 動態合併成一則）
    ...["2026-09-07", "2026-10-06", "2026-11-06"].flatMap((d) => [
      trade("buy", fubon, "0050.TW", d, 150, "定期定額", `${d}T09:05:00+08:00`),
      trade("buy", yuanta, "0050.TW", d, 50, "定期定額", `${d}T09:05:30+08:00`),
    ]),
    trade("sell", yuanta, "2317.TW", "2026-10-20", 1000, "", "2026-10-20T13:50:00+08:00"),
    trade("buy", yuanta, "2308.TW", "2026-10-27", 1000, "", "2026-10-27T20:12:00+08:00"),
    trade("buy", yuanta, "2330.TW", MOCK_TODAY, 500, "", `${MOCK_TODAY}T11:02:00+08:00`),
  ]
  t.sort((a, b) => (a.trade_date === b.trade_date ? a.id.localeCompare(b.id) : a.trade_date.localeCompare(b.trade_date)))
  return syncAutoDividends(t, { accounts: DAD_ACCOUNTS, skips: new Set(), today: MOCK_TODAY })
}

/** 只用在分享投影的原始交易（成員的全部帳戶） */
export interface RawTrade {
  txn_id: string
  side: "buy" | "sell"
  symbol: string
  trade_date: string
  quantity: number
  price: number
  currency: "TWD" | "USD"
  created_at: string
}

export interface PeriodReturns {
  day: number | null
  month: number | null
  year: number | null
  total: number | null
}

/** 沒有完整帳本的成員：分享出去會用到的數字 */
export interface StaticProfile {
  returns: PeriodReturns
  holdings: SharedHolding[]
  amounts: { market_value: number; day_change: number; total_pnl: number }
  trades: RawTrade[]
  /** 週報用的每週報酬（週一的日期 → 報酬） */
  weeks: Record<string, number | null>
}

function raw(user: string, side: "buy" | "sell", symbol: string, day: string, quantity: number, time = "20:10", price?: number): RawTrade {
  const spec = findInstrument(symbol)!
  const d = nextTradingDay(day)
  return {
    txn_id: `txn_${user}_${d}_${symbol}_${side}_${quantity}`, side, symbol, trade_date: d, quantity,
    price: price ?? closeOn(spec, d), currency: spec.currency, created_at: `${d}T${time}:00+08:00`,
  }
}
const h = (symbol: string, weight: number): SharedHolding => ({ symbol, name: findInstrument(symbol)!.name, weight })

export const STATIC_PROFILES: Record<string, StaticProfile> = {
  usr_mom: {
    returns: { day: 0.0041, month: 0.0123, year: 0.0912, total: 0.2215 },
    holdings: [h("0056.TW", 0.38), h("00878.TW", 0.31), h("2881.TW", 0.19), h("2412.TW", 0.12)],
    amounts: { market_value: 1_862_400, day_change: 7_590, total_pnl: 337_800 },
    trades: [raw("mom", "buy", "00878.TW", "2026-11-03", 2000, "21:40")],
    weeks: { "2026-11-02": 0.0062, "2026-10-26": -0.0031 },
  },
  usr_sis: {
    returns: { day: 0.0158, month: 0.0412, year: 0.2236, total: 0.3481 },
    holdings: [h("2330.TW", 0.46), h("2454.TW", 0.22), h("0050.TW", 0.2), h("2603.TW", 0.12)],
    amounts: { market_value: 684_200, day_change: 10_640, total_pnl: 176_700 },
    trades: [
      raw("sis", "buy", "00878.TW", "2026-11-03", 120, "12:31"),
      raw("sis", "sell", "2603.TW", "2026-10-28", 1000, "10:14"),
      raw("sis", "buy", "2454.TW", "2026-10-28", 30, "10:20"),
      raw("sis", "buy", "2454.TW", "2026-10-28", 20, "10:22"),
      raw("sis", "buy", "00878.TW", "2026-10-03", 120, "12:30"),
      // 超過 90 天：不出現在動態
      raw("sis", "buy", "2330.TW", "2026-07-21", 100, "09:40"),
    ],
    weeks: { "2026-11-02": 0.0184, "2026-10-26": 0.0071 },
  },
  usr_bro: {
    // 阿弟什麼都沒開：不會出現在排行、動態、持股，也沒有「未分享」
    returns: { day: -0.0213, month: -0.051, year: 0.0402, total: 0.061 },
    holdings: [h("2603.TW", 0.7), h("2409.TW", 0.3)],
    amounts: { market_value: 120_300, day_change: -2_610, total_pnl: 6_900 },
    trades: [raw("bro", "buy", "2603.TW", "2026-11-10", 1000, "09:15")],
    weeks: { "2026-11-02": -0.0122, "2026-10-26": 0.0012 },
  },
  usr_kai: {
    returns: { day: 0.0203, month: 0.0566, year: 0.3112, total: 0.5524 },
    holdings: [h("2382.TW", 0.33), h("NVDA", 0.29), h("2330.TW", 0.25), h("2308.TW", 0.13)],
    amounts: { market_value: 2_430_000, day_change: 48_330, total_pnl: 864_400 },
    trades: [
      raw("kai", "buy", "2382.TW", "2026-11-11", 2000, "09:32"),
      raw("kai", "buy", "NVDA", "2026-11-06", 10, "22:41", 186.4),
      raw("kai", "sell", "2308.TW", "2026-10-30", 1000, "13:05"),
    ],
    weeks: { "2026-11-02": 0.0233, "2026-10-26": 0.0102 },
  },
  usr_yun: {
    returns: { day: 0.0067, month: 0.0189, year: 0.1288, total: 0.1904 },
    holdings: [h("0050.TW", 0.55), h("2330.TW", 0.3), h("2881.TW", 0.15)],
    amounts: { market_value: 912_000, day_change: 6_070, total_pnl: 145_900 },
    trades: [raw("yun", "buy", "0050.TW", "2026-11-06", 300, "09:01")],
    weeks: { "2026-11-02": 0.0091, "2026-10-26": 0.0044 },
  },
  usr_ming: {
    returns: { day: null, month: null, year: null, total: 0.0815 },
    holdings: [h("AAPL", 0.6), h("0050.TW", 0.4)],
    amounts: { market_value: 410_000, day_change: 0, total_pnl: 30_900 },
    trades: [],
    weeks: { "2026-11-02": null, "2026-10-26": null },
  },
  usr_lin: {
    returns: { day: 0.0034, month: 0.0201, year: 0.1677, total: 0.4012 },
    holdings: [h("2330.TW", 0.5), h("0056.TW", 0.5)],
    amounts: { market_value: 3_120_000, day_change: 10_600, total_pnl: 893_000 },
    trades: [],
    weeks: {},
  },
  usr_chen: {
    returns: { day: 0.0112, month: 0.0275, year: 0.0941, total: 0.1102 },
    holdings: [h("0050.TW", 1)],
    amounts: { market_value: 88_000, day_change: 975, total_pnl: 8_700 },
    trades: [],
    weeks: {},
  },
}
