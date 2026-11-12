import { describe, expect, it } from "vitest"
import type { AnalystView, AnalystViews } from "@/api/types"
import { createMockAdapter } from "@/api/mock/adapter"
import {
  ANALYST_INITIAL,
  ANALYST_TIMEOUT_MS,
  analystReducer,
  formatTarget,
  nextPoll,
  phaseOf,
  ratingLine,
  viewDate,
  visibleViews,
  type AnalystEvent,
  type AnalystState,
} from "@/lib/analyst-views"

const item = (p: Partial<AnalystView> = {}): AnalystView => ({
  institution: "外資券商 A", action: "調升", rating_text: "加碼", target_price: 1350, currency: "TWD",
  date: "2026-11-10", source_title: "報導標題", url: "https://example.com/a", ...p,
})
const ready = (items: AnalystView[]): AnalystViews => ({ status: "ready", symbol: "2330.TW", as_of: "2026-11-12T09:12:00+08:00", items, disclaimer: "第三方觀點", notes: [] })
const run = (events: AnalystEvent[], from: AnalystState = ANALYST_INITIAL) => events.reduce(analystReducer, from)

describe("法人觀點的狀態", () => {
  it("回應對應到畫面：none／pending／ready（有、沒有）／unavailable", () => {
    expect(phaseOf({ status: "none" })).toBe("none")
    expect(phaseOf({ status: "pending" })).toBe("searching")
    expect(phaseOf(ready([item()]))).toBe("ready")
    expect(phaseOf(ready([]))).toBe("empty")
    expect(phaseOf({ status: "unavailable", notes: ["查不到"] })).toBe("unavailable")
  })

  it("展開 → GET none → 按查詢 → POST pending（搜尋中）→ 輪詢 ready", () => {
    let s = run([{ type: "load" }])
    expect(s).toMatchObject({ phase: "loading", inFlight: "get" })
    s = run([{ type: "loaded", data: { status: "none" }, at: 0 }], s)
    expect(s).toMatchObject({ phase: "none", inFlight: null })
    s = run([{ type: "search", at: 1000 }], s)
    expect(s).toMatchObject({ phase: "searching", inFlight: "post", searchStartedAt: 1000 })
    s = run([{ type: "searched", data: { status: "pending" }, at: 1500 }], s)
    expect(s).toMatchObject({ phase: "searching", inFlight: null })
    expect(nextPoll(s, 2000)).toBe("poll")
    s = run([{ type: "load" }], s)
    expect(s).toMatchObject({ phase: "searching", inFlight: "get" })
    expect(nextPoll(s, 2000)).toBeNull()
    s = run([{ type: "loaded", data: ready([item()]), at: 4000 }], s)
    expect(s).toMatchObject({ phase: "ready", searchStartedAt: null })
    expect(nextPoll(s, 5000)).toBeNull()
  })

  it("剛按下查詢時共用快取還是 none：繼續等，不退回查詢按鈕；輪詢偶發失敗也繼續等", () => {
    const searching = run([{ type: "search", at: 0 }, { type: "searched", data: { status: "pending" }, at: 10 }])
    expect(run([{ type: "load" }, { type: "loaded", data: { status: "none" }, at: 20 }], searching).phase).toBe("searching")
    expect(run([{ type: "load" }, { type: "failed", during: "get", message: "網路" }], searching)).toMatchObject({ phase: "searching", inFlight: null })
  })

  it("別人剛觸發（GET 回 pending）也輪詢，太久就停在錯誤、可以重試", () => {
    const s = run([{ type: "load" }, { type: "loaded", data: { status: "pending" }, at: 5_000 }])
    expect(s).toMatchObject({ phase: "searching", searchStartedAt: 5_000 })
    expect(nextPoll(s, 5_000 + ANALYST_TIMEOUT_MS + 1)).toBe("timeout")
    expect(run([{ type: "timeout" }], s)).toMatchObject({ phase: "error", error: { during: "get", code: "timeout" } })
    // 不在搜尋中時逾時沒有作用
    const empty = run([{ type: "loaded", data: ready([]), at: 0 }])
    expect(analystReducer(empty, { type: "timeout" })).toBe(empty)
  })

  it("失敗：GET 失敗可重試；POST 額度用完是錯誤；AI 暫停（503）是安靜的查不到", () => {
    expect(run([{ type: "load" }, { type: "failed", during: "get", message: "伺服器暫時沒有回應" }])).toMatchObject({ phase: "error", error: { during: "get" } })
    const none = run([{ type: "load" }, { type: "loaded", data: { status: "none" }, at: 0 }])
    expect(run([{ type: "search", at: 1 }, { type: "failed", during: "post", message: "今天的提問數已達上限", code: "ai_daily_limit" }], none)).toMatchObject({
      phase: "error",
      error: { during: "post", code: "ai_daily_limit" },
    })
    expect(run([{ type: "search", at: 1 }, { type: "failed", during: "post", message: "AI 暫時無法使用", code: "ai_unavailable" }], none)).toMatchObject({ phase: "unavailable" })
  })

  it("重複的請求不會疊加：GET 進行中再 load、POST 進行中再 search 都不變", () => {
    const loading = run([{ type: "load" }])
    expect(analystReducer(loading, { type: "load" })).toBe(loading)
    const posting = run([{ type: "search", at: 1 }])
    expect(analystReducer(posting, { type: "search", at: 2 })).toBe(posting)
  })
})

describe("法人觀點的顯示", () => {
  it("最多 5 筆、新到舊，沒有日期或來源的不列", () => {
    const rows = visibleViews([
      item({ date: "2026-10-01" }),
      item({ date: "2026-11-10" }),
      item({ date: "", institution: "沒日期" }),
      item({ url: "", institution: "沒來源" }),
      ...["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"].map((date) => item({ date })),
    ])
    expect(rows).toHaveLength(5)
    expect(rows.map((r) => r.date)).toEqual(["2026-11-10", "2026-11-04", "2026-11-03", "2026-11-02", "2026-11-01"])
    expect(rows.some((r) => r.institution === "沒日期" || r.institution === "沒來源")).toBe(false)
  })
  it("目標價照原文、等寬：台股依升降單位＋元，美股 US$ 兩位；評等照抄、日期跨年寫年份", () => {
    expect(formatTarget(1350, "TWD")).toBe("1,350 元")
    expect(formatTarget(236.5, "TWD")).toBe("236.5 元")
    expect(formatTarget(310, "USD")).toBe("US$310.00")
    expect(formatTarget(null, "TWD")).toBe("—")
    expect(ratingLine({ action: "調升", rating_text: "加碼" })).toBe("調升「加碼」")
    expect(ratingLine({ action: "首評", rating_text: "Overweight" })).toBe("首評「Overweight」")
    expect(viewDate("2026-11-10", "2026-11-12")).toBe("11/10")
    expect(viewDate("2025-12-30", "2026-01-05")).toBe("2025/12/30")
  })
})

describe("mock：法人觀點（GET/POST /instruments/{symbol}/analyst-views）", () => {
  it("2330 直接有 3 筆；其他先 none，POST 後 ready 1–2 筆；2881 查無報導；2409 查不到", async () => {
    const api = createMockAdapter({ latency: [0, 0], analystDelayMs: 0 })
    const tsmc = await api.getAnalystViews("2330.TW")
    expect(tsmc).toMatchObject({ status: "ready", symbol: "2330.TW" })
    expect(tsmc.items).toHaveLength(3)
    expect(tsmc.disclaimer).toMatch(/非 Forliosa 建議/)
    for (const v of tsmc.items!) expect(v).toMatchObject({ currency: "TWD", url: expect.stringMatching(/^https:\/\/example\.com\//) })
    // 新到舊
    expect(tsmc.items!.map((v) => v.date)).toEqual([...tsmc.items!.map((v) => v.date)].sort().reverse())

    expect(await api.getAnalystViews("2454.TW")).toMatchObject({ status: "none" })
    await api.requestAnalystViews("2454.TW")
    const mtk = await api.getAnalystViews("2454.TW")
    expect(mtk.status).toBe("ready")
    expect(mtk.items!.length).toBeGreaterThanOrEqual(1)
    expect(mtk.items!.length).toBeLessThanOrEqual(2)

    await api.requestAnalystViews("2881.TW")
    expect(await api.getAnalystViews("2881.TW")).toMatchObject({ status: "ready", items: [] })
    await api.requestAnalystViews("2409.TW")
    expect(await api.getAnalystViews("2409.TW")).toMatchObject({ status: "unavailable" })
    const us = await api.requestAnalystViews("NVDA")
    expect(us.items?.[0]?.currency).toBe("USD")
  })
  it("POST 之後先是 pending，時間到才 ready；同一天再 POST 共用同一份", async () => {
    const api = createMockAdapter({ latency: [0, 0], analystDelayMs: 60_000 })
    expect(await api.requestAnalystViews("2317.TW")).toMatchObject({ status: "pending" })
    expect(await api.getAnalystViews("2317.TW")).toMatchObject({ status: "pending" })
    expect(await api.requestAnalystViews("2317.TW")).toMatchObject({ status: "pending" })
    // 已經有一份的（2330）POST 不重查
    expect((await api.requestAnalystViews("2330.TW")).items).toHaveLength(3)
  })
})
