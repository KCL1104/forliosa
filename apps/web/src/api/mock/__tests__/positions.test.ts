import { describe, expect, it } from "vitest"
import { ApiError, type Transaction } from "../../types"
import { createMockAdapter } from "../adapter"

/** mock 的匯入庫存：和後端同一套代碼與句子（已在帳本、只有總成本、零股、融資、找不到股票、融券）、寫入、以券商為準、整批復原 */
const TW = "acc_01JSINOPAC"
const US = "acc_01JCATHAYUS"
const shot = { media_type: "image/png" as const, data: "AAAA" }
const mk = () => createMockAdapter({ latency: [0, 0] })
/** 全部的交易（一頁最多 200 筆，照 cursor 讀完） */
async function txnsOf(api: ReturnType<typeof mk>, accountId?: string): Promise<Transaction[]> {
  const out: Transaction[] = []
  let cursor: string | undefined
  do {
    const page = await api.listTransactions({ limit: 200, account_id: accountId, cursor })
    out.push(...page.items)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return out
}

describe("mock：讀庫存", () => {
  it("截圖回永豐金證券的庫存畫面：每一種旗標至少一列，預設勾不勾照後端的規則", async () => {
    const api = mk()
    const doc = await api.parsePositions({ account_id: TW, kind: "images", pages: [shot, shot] })
    expect(doc.document_kind).toBe("holdings")
    expect(doc.broker_name).toBe("永豐金證券")
    expect(doc.merged_duplicates).toBe(1)
    const by = (name: string) => doc.rows.find((r) => r.name === name)!
    // 台積電：已在帳本、股數一樣均價不同
    expect(by("台積電").include).toBe(false)
    expect(by("台積電").in_ledger).toMatchObject({ quantity: 1500, currency: "TWD" })
    expect(by("台積電").flags.find((f) => f.code === "in_ledger")!.message).toMatch(/^帳本裡已經有 1,500 股，均價 [\d.]+。$/)
    // 鴻海：股數和均價都一樣
    expect(by("鴻海").flags.find((f) => f.code === "in_ledger")!.message).toBe("帳本裡已經有，股數和均價都一樣。")
    // 中華電：只有總成本、1.5 張
    expect(by("中華電")).toMatchObject({ quantity: 1500, price: 120, price_basis: "total_cost", total_cost: 180000, include: true })
    expect(by("中華電").flags.map((f) => f.code)).toEqual(["not_whole_lots"])
    // 富邦金：融資，照樣勾著
    expect(by("富邦金")).toMatchObject({ quantity: 2000, include: true })
    expect(by("富邦金").flags.map((f) => f.code)).toEqual(["margin"])
    // 找不到、融券：不勾
    expect(by("台光電")).toMatchObject({ symbol: null, include: false })
    expect(by("台光電").flags[0]).toEqual({ code: "unknown_symbol", message: "找不到「台光電」。", severity: "error" })
    expect(by("長榮").flags.map((f) => f.code)).toEqual(["short_sale"])
    expect(by("長榮").include).toBe(false)
  })

  it("貼上的文字：一行一檔（張換成股）；美股沒寫幣別當成美元，別的帳戶也有的標出來；交易明細請改用匯入對帳單", async () => {
    const api = mk()
    const doc = await api.parsePositions({ account_id: TW, kind: "text", text: "0056 元大高股息 2 張 均價 36.5\nAAPL Apple 3 股 均價 190" })
    expect(doc.rows.map((r) => [r.symbol, r.quantity, r.price])).toEqual([["0056.TW", 2000, 36.5], ["AAPL", 3, 190]])
    const aapl = doc.rows[1]!
    expect(aapl.currency).toBe("USD")
    expect(aapl.flags.map((f) => f.code)).toEqual(["currency_guess", "in_other_account"])
    expect(aapl.flags[1]!.message).toMatch(/^「國泰・複委託」帳戶也有 [\d,.]+ 股。$/)
    const trades = await api.parsePositions({ kind: "text", text: "2026/10/13 買進 2330 台積電 1,000 股 1,030" })
    expect(trades).toMatchObject({ document_kind: "trade_records", rows: [], notice: "這是交易明細，不是庫存。請改用「匯入對帳單」。" })
    const nothing = await api.parsePositions({ kind: "text", text: "你好" })
    expect(nothing.notice).toBe("這裡面沒有看到庫存。")
  })

  it("沒有截圖或文字、混在一起、文字裡還有身分證字號：拒絕", async () => {
    const api = mk()
    await expect(api.parsePositions({ kind: "images", pages: [] })).rejects.toMatchObject({ code: "validation_error" })
    await expect(api.parsePositions({ kind: "text", text: "2330", pages: [shot] })).rejects.toMatchObject({ code: "validation_error" })
    await expect(api.parsePositions({ kind: "text", text: "身分證字號 A123456789" })).rejects.toMatchObject({ code: "unmasked_pii" })
  })
})

describe("mock：匯入的開關（`?import=`，和後端的 IMPORT_STATEMENTS 一樣）", () => {
  it.each([
    ["all（預設）", undefined, true, true],
    ["admins", "admins" as const, true, false],
    ["off", "off" as const, false, false],
  ])("%s：/me 的 plan.statement_import 與兩種讀檔照開關，沒開放的 403 import_not_enabled", async (_label, importStatements, admin, member) => {
    for (const [isAdmin, open] of [[true, admin], [false, member]] as const) {
      const api = createMockAdapter({ latency: [0, 0], importStatements, discussion: { admin: isAdmin } })
      expect((await api.getMe()).plan?.statement_import).toBe(open)
      const read = api.parsePositions({ account_id: TW, kind: "text", text: "0056 元大高股息 2 張 均價 36.5" })
      const statement = api.parseStatement({ account_id: TW, kind: "images", pages: [shot] })
      if (open) {
        await expect(read).resolves.toMatchObject({ document_kind: "holdings" })
        await expect(statement).resolves.toMatchObject({ document_kind: "app_screenshot" })
      } else {
        await expect(read).rejects.toMatchObject({ status: 403, code: "import_not_enabled", message: "這個帳號還不能匯入庫存。" })
        await expect(statement).rejects.toMatchObject({ status: 403, code: "import_not_enabled", message: "這個帳號還不能匯入對帳單。" })
      }
    }
  })
})

describe("mock：寫入庫存", () => {
  it("每一檔一筆買進（手續費 0）；只給總成本的照總成本 ÷ 股數；整批復原", async () => {
    const api = mk()
    const res = await api.commitPositions({
      account_id: TW,
      trade_date: "2026-11-10",
      rows: [
        { symbol: "2412.TW", quantity: 1500, total_cost: 180000 },
        { symbol: "0056.TW", quantity: 350, price: 36.82, trade_date: "2026-10-20" },
      ],
    })
    expect(res.created).toHaveLength(2)
    expect(res.replaced).toEqual([])
    const txns = (await txnsOf(api, TW)).filter((t) => t.import_batch_id === res.batch_id)
    const cht = txns.find((t) => t.symbol === "2412.TW")!
    expect(cht).toMatchObject({ type: "buy", quantity: 1500, price: 120, amount: 180000, fee: 0, tax: 0, trade_date: "2026-11-10", source: "import" })
    expect(txns.find((t) => t.symbol === "0056.TW")!.trade_date).toBe("2026-10-20")
    await api.deleteTransactionBatch(res.batch_id)
    expect((await txnsOf(api, TW)).some((t) => t.import_batch_id === res.batch_id)).toBe(false)
  })

  it("已在帳本又沒有以券商為準：那一列寫不進去，整批都不寫；dry_run 說以券商為準會刪掉幾筆", async () => {
    const api = mk()
    const before = (await txnsOf(api, TW)).length
    const rows = [{ symbol: "2330.TW", quantity: 1500, price: 612.4 }, { symbol: "2412.TW", quantity: 1000, price: 120 }]
    const err = await api.commitPositions({ account_id: TW, rows }).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe("batch_rejected")
    expect((err as ApiError).extra.rows).toEqual([{ index: 0, code: "in_ledger", message: "帳本裡已經有 1,500 股。勾「以券商為準」才會換掉，不然這一列不要匯入。" }])
    expect((await txnsOf(api, TW)).length).toBe(before)
    const check = await api.checkPositions({ account_id: TW, rows: [{ ...rows[0]!, replace: true }, rows[1]!] })
    expect(check.ok).toBe(true)
    expect(check.rows[0]!.in_ledger).toMatchObject({ quantity: 1500 })
    expect(check.replaced[0]!.symbol).toBe("2330.TW")
    expect(check.replaced[0]!.deleted).toBeGreaterThan(1)
    // 日期在未來：那一列的 bad_date
    const future = await api.checkPositions({ account_id: TW, trade_date: "2099-01-01", rows: [rows[1]!] })
    expect(future.rows[0]!.flags.map((f) => f.code)).toEqual(["bad_date"])
  })

  it("以券商為準：只刪這個帳戶裡這一檔的紀錄（別的股票、別的帳戶不動），換成一筆；復原只刪這次的買進，舊紀錄不回來", async () => {
    const api = mk()
    const all = () => txnsOf(api)
    const start = await all()
    const old2330 = start.filter((t) => t.account_id === TW && t.symbol === "2330.TW")
    const others = start.filter((t) => !(t.account_id === TW && t.symbol === "2330.TW") && t.source !== "auto")
    const res = await api.commitPositions({ account_id: TW, rows: [{ symbol: "2330.TW", quantity: 1500, price: 612.4, replace: true }] })
    expect(res.replaced).toEqual([{ symbol: "2330.TW", deleted: old2330.length }])
    const after = await all()
    const now2330 = after.filter((t) => t.account_id === TW && t.symbol === "2330.TW" && t.source !== "auto")
    expect(now2330.map((t) => [t.type, t.quantity, t.price, t.fee])).toEqual([["buy", 1500, 612.4, 0]])
    for (const t of others) expect(after.some((x) => x.id === t.id), `${t.symbol} ${t.id}`).toBe(true)
    expect(after.some((t) => t.account_id === US)).toBe(true)
    await api.deleteTransactionBatch(res.batch_id)
    const undone = await all()
    expect(undone.filter((t) => t.account_id === TW && t.symbol === "2330.TW" && t.source !== "auto")).toEqual([])
  })

  it("以券商為準也清掉這個帳戶這一檔的略過紀錄（和後端、刪除這檔一樣）：刪掉的自動股利照新的持股再記；別檔的略過紀錄不動", async () => {
    const api = mk()
    const autos = (await txnsOf(api, TW)).filter((t) => t.source === "auto")
    const target = autos[0]!
    const other = autos.find((t) => t.symbol !== target.symbol)!
    expect(other).toBeDefined()
    // 使用者刪掉兩檔的自動股利：之後不再產生
    await api.deleteTransaction(target.id)
    await api.deleteTransaction(other.id)
    const gone = (t: Transaction) => (x: Transaction) => x.source === "auto" && x.symbol === t.symbol && x.trade_date === t.trade_date
    expect((await txnsOf(api, TW)).some(gone(target))).toBe(false)
    // 以券商為準換掉 target 那一檔，買進日期在那次除息之前：那次股利照券商的股數重新自動入帳
    await api.commitPositions({ account_id: TW, rows: [{ symbol: target.symbol!, quantity: 1000, price: 100, trade_date: "2024-01-02", replace: true }] })
    const after = await txnsOf(api, TW)
    expect(after.find(gone(target))).toMatchObject({ source: "auto", quantity: 1000 })
    // 別檔的略過紀錄還在
    expect(after.some(gone(other))).toBe(false)
  })
})
