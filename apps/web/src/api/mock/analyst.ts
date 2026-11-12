/**
 * 法人觀點（示範）：`GET/POST /instruments/{symbol}/analyst-views` 的行為（api-contract「法人觀點與美股基本面」）。
 * - 同一檔當天全體共用一份：GET 讀快取（沒有＝`none`），POST 觸發搜尋（`pending`），一段時間後 GET 變 `ready`。
 * - 2330：今天已經有人查過，GET 直接回 3 筆；2881：查完是空的（近期查無法人報導）；2409：這次查不到（`unavailable`）；
 *   其他個股：POST 後回 1–2 筆。
 * 機構名稱、評等與目標價都是**版面示意**（「外資券商 A」「示範報導」、example.com 連結），不是任何真實機構的意見。
 */
import { ApiError, type AnalystView, type AnalystViews } from "../types"
import { findInstrument } from "./instruments"
import { addDays, MOCK_TODAY, rng, twTick } from "./market"

export const ANALYST_DISCLAIMER = "以下為媒體報導的第三方觀點，可能不完整或未經授權轉載，非 Forliosa 建議。"

/** 依升降單位取整（美股取到 0.01） */
function roundTarget(price: number, us: boolean): number {
  if (us) return Math.round(price * 100) / 100
  const tick = twTick(price)
  return Math.round(Math.round(price / tick) * tick * 100) / 100
}

function view(symbol: string, p: Omit<AnalystView, "currency" | "url" | "source_title"> & { n: number }): AnalystView {
  const spec = findInstrument(symbol)!
  const { n, ...rest } = p
  return {
    ...rest,
    currency: spec.currency,
    source_title: `示範報導：${p.institution} 給${spec.name}「${p.rating_text}」評等`,
    url: `https://example.com/news/${spec.code.toLowerCase()}-${n}`,
  }
}

/** 2330：三筆，多空並陳（調升、維持、調降） */
function tsmcViews(): AnalystView[] {
  return [
    view("2330.TW", { n: 1, institution: "外資券商 A", action: "調升", rating_text: "加碼", target_price: 1350, date: addDays(MOCK_TODAY, -2) }),
    view("2330.TW", { n: 2, institution: "本土投顧 B", action: "維持", rating_text: "優於大盤", target_price: 1280, date: addDays(MOCK_TODAY, -7) }),
    view("2330.TW", { n: 3, institution: "外資券商 C", action: "調降", rating_text: "中立", target_price: 1150, date: addDays(MOCK_TODAY, -15) }),
  ]
}

/** 其他個股：1–2 筆（依代號固定） */
function generatedViews(symbol: string): AnalystView[] {
  const spec = findInstrument(symbol)!
  const r = rng(`analyst:${symbol}`)
  const us = spec.market === "US"
  const count = r() < 0.5 ? 1 : 2
  const first = view(symbol, {
    n: 1, institution: us ? "外資券商 D" : "本土投顧 E", action: "首評", rating_text: us ? "Overweight" : "優於大盤",
    target_price: roundTarget(spec.price * (1.08 + r() * 0.1), us), date: addDays(MOCK_TODAY, -3),
  })
  if (count === 1) return [first]
  return [
    first,
    view(symbol, { n: 2, institution: "外資券商 F", action: "維持", rating_text: us ? "Neutral" : "中立", target_price: roundTarget(spec.price * (0.95 + r() * 0.08), us), date: addDays(MOCK_TODAY, -11) }),
  ]
}

interface Entry {
  status: "pending" | "ready" | "unavailable"
  readyAt: number
  final: AnalystViews
}

export interface AnalystStore {
  get(symbol: string): AnalystViews
  request(symbol: string): AnalystViews
}

/** `delayMs`：POST 之後多久變成 `ready`（測試用 0＝立即） */
export function createAnalystStore(opts: { delayMs?: number; now?: () => number } = {}): AnalystStore {
  const delay = opts.delayMs ?? 2600
  const now = opts.now ?? (() => Date.now())
  const asOf = (time: string) => `${MOCK_TODAY}T${time}:00+08:00`
  const expires = (time: string) => `${addDays(MOCK_TODAY, 1)}T${time}:00+08:00`
  const entries = new Map<string, Entry>([
    ["2330.TW", { status: "ready", readyAt: 0, final: { status: "ready", symbol: "2330.TW", as_of: asOf("09:12"), expires_at: expires("09:12"), items: tsmcViews(), disclaimer: ANALYST_DISCLAIMER, notes: [] } }],
  ])
  const known = (symbol: string) => {
    const spec = findInstrument(symbol)
    if (!spec) throw new ApiError(404, "not_found", "找不到商品")
    return spec.symbol
  }
  const current = (symbol: string): AnalystViews => {
    const e = entries.get(symbol)
    if (!e) return { status: "none", symbol, disclaimer: ANALYST_DISCLAIMER }
    if (e.status === "pending" && now() >= e.readyAt) e.status = e.final.status as Entry["status"]
    return e.status === "pending" ? { status: "pending", symbol, disclaimer: ANALYST_DISCLAIMER, notes: [] } : e.final
  }
  return {
    get: (symbol) => current(known(symbol)),
    request(symbol) {
      const s = known(symbol)
      const cur = current(s)
      // 今天已經有一份（或正在查）：共用，不重查
      if (cur.status !== "none") return cur
      const t = new Date(now() + 8 * 3600_000).toISOString().slice(11, 16)
      // 後端：查不到時 notes 寫 10 分鐘後可以再查（過了之後 GET 回 none，畫面重新出現查詢按鈕；mock 不模擬這一段）
      const retryAt = new Date(now() + 8 * 3600_000 + delay + 10 * 60_000).toISOString().slice(11, 16)
      const final: AnalystViews =
        s === "2409.TW"
          ? { status: "unavailable", symbol: s, as_of: null, expires_at: expires(t), items: [], disclaimer: ANALYST_DISCLAIMER, notes: [`${retryAt} 之後可以再查一次。`] }
          : { status: "ready", symbol: s, as_of: asOf(t), expires_at: expires(t), items: s === "2881.TW" ? [] : generatedViews(s), disclaimer: ANALYST_DISCLAIMER, notes: [] }
      entries.set(s, { status: "pending", readyAt: now() + delay, final })
      return current(s)
    },
  }
}
