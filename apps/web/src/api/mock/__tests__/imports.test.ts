import { describe, expect, it } from "vitest"
import { ApiError, type ImportCandidate } from "../../types"
import { createMockAdapter } from "../adapter"

/** mock 的匯入對帳單：和後端同一套代碼（每一種檢查結果）、dry_run、全部或全不的寫入、整批復原 */
const TW = "acc_01JSINOPAC"
const page = { media_type: "image/jpeg" as const, data: "AAAA", text: "客戶姓名：〔已遮蔽〕" }
const mk = () => createMockAdapter({ latency: [0, 0] })

describe("mock：讀對帳單", () => {
  it("PDF 回 10 月的月對帳單，每一種檢查結果至少一列；預設不勾的照規則", async () => {
    const api = mk()
    const doc = await api.parseStatement({ account_id: TW, kind: "pdf", pages: [page, page] })
    expect(doc.document_kind).toBe("monthly_statement")
    expect(doc.broker_name).toBe("永豐金證券")
    const codes = new Set(doc.rows.flatMap((r) => r.flags.map((f) => f.code)))
    for (const code of [
      "unknown_symbol", "ambiguous_symbol", "amount_mismatch", "fee_out_of_range", "tax_out_of_range", "side_inconsistent", "not_trading_day",
      "outside_period", "price_far_from_close", "oversell", "duplicate", "possible_duplicate", "dividend_auto", "short_sale", "day_trade", "margin",
      "currency_mismatch", "fractional_tw_qty", "unreadable",
    ]) {
      expect(codes, code).toContain(code)
    }
    const byCode = (code: string) => doc.rows.filter((r) => r.flags.some((f) => f.code === code))
    for (const code of ["unknown_symbol", "oversell", "duplicate", "day_trade", "unreadable", "dividend_auto", "short_sale"]) {
      expect(byCode(code).every((r) => !r.include), code).toBe(true)
    }
    for (const code of ["margin", "amount_mismatch", "not_trading_day", "outside_period"]) expect(byCode(code).every((r) => r.include), code).toBe(true)
    expect(byCode("oversell")[0]!.flags.find((f) => f.code === "oversell")!.message).toBe("賣出 2,000 股・當時只有 1,000 股")
    expect(doc.totals_check).toEqual({ ok: false, diff: -12450 })
    expect(doc.embedded_instructions).toHaveLength(1)
  })

  it("截圖回三筆、沒有問題；送出的文字裡還有身分證字號就拒絕（塗黑的自我檢查）；一次最多 20 頁", async () => {
    const api = mk()
    const shot = await api.parseStatement({ kind: "images", pages: [{ media_type: "image/jpeg", data: "AAAA" }] })
    expect(shot.rows).toHaveLength(3)
    expect(shot.rows.every((r) => r.include && r.flags.length === 0)).toBe(true)
    await expect(api.parseStatement({ kind: "pdf", pages: [{ ...page, text: "身分證字號：A123456789" }] })).rejects.toMatchObject({ code: "unmasked_pii" })
    await expect(api.parseStatement({ kind: "images", pages: Array(21).fill(page) })).rejects.toMatchObject({ status: 413 })
  })

  it("取消：AbortSignal 中斷時丟 AbortError", async () => {
    const api = createMockAdapter({ latency: [10, 10] })
    const ac = new AbortController()
    const p = api.parseStatement({ kind: "images", pages: [page] }, { signal: ac.signal })
    ac.abort()
    await expect(p).rejects.toMatchObject({ name: "AbortError" })
  })
})

describe("mock：一次寫入多筆、整批復原", () => {
  const buy = (over: Partial<ImportCandidate> = {}): ImportCandidate => ({
    account_id: TW, symbol: "2603.TW", type: "buy", trade_date: "2026-10-07", quantity: 1000, price: 200, amount: null, fee: 285, tax: 0, is_day_trade: false, note: "", ...over,
  })

  it("dry_run：同一批裡先買後賣不算賣超；賣得比買的多是 error；補上買進就好了", async () => {
    const api = mk()
    const sell = buy({ type: "sell", trade_date: "2026-10-13", quantity: 2000, tax: 1200 })
    const bad = await api.checkTransactionBatch({ account_id: TW, origin: "import", rows: [buy(), sell] })
    expect(bad.ok).toBe(false)
    expect(bad.rows[1]!.flags.map((f) => [f.code, f.severity])).toContainEqual(["oversell", "error"])
    const good = await api.checkTransactionBatch({ account_id: TW, origin: "import", rows: [buy(), buy({ trade_date: "2026-10-08" }), sell] })
    expect(good.ok).toBe(true)
  })

  it("有一列不行就一列都不寫（422 batch_rejected 帶 rows）；寫進去的是「匯入」、同一個批次；整批復原", async () => {
    const api = mk()
    const before = (await api.listTransactions({ limit: 200 })).items.length
    const sell = buy({ type: "sell", trade_date: "2026-10-13", quantity: 2000, tax: 1200 })
    const err = await api.createTransactionBatch({ account_id: TW, origin: "import", rows: [buy(), sell] }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 422, code: "batch_rejected" })
    expect(err.extra.rows).toEqual([{ index: 1, code: "oversell", message: "賣出 2,000 股・當時只有 1,000 股" }])
    expect((await api.listTransactions({ limit: 200 })).items.length).toBe(before)

    const res = await api.createTransactionBatch({ account_id: TW, origin: "import", rows: [buy(), buy({ trade_date: "2026-10-08" }), sell] })
    expect(res.created).toHaveLength(3)
    const all = (await api.listTransactions({ limit: 200, account_id: TW })).items
    const mine = all.filter((t) => res.created.includes(t.id))
    expect(mine.every((t) => t.source === "import" && t.import_batch_id === res.batch_id && t.note === "")).toBe(true)
    expect(await api.deleteTransactionBatch(res.batch_id)).toEqual({ batch_id: res.batch_id, deleted: 3 })
    expect((await api.listTransactions({ limit: 200 })).items.some((t) => res.created.includes(t.id))).toBe(false)
  })

  it("整批復原：之後自己記的賣出用到這批買進就擋下來（ledger_inconsistent）", async () => {
    const api = mk()
    const res = await api.createTransactionBatch({ account_id: TW, origin: "import", rows: [buy({ trade_date: "2026-10-07" })] })
    await api.createTransaction({ account_id: TW, symbol: "2603.TW", type: "sell", trade_date: "2026-11-02", quantity: 1000, price: 210 })
    await expect(api.deleteTransactionBatch(res.batch_id)).rejects.toMatchObject({ status: 422, code: "ledger_inconsistent" })
  })
})
