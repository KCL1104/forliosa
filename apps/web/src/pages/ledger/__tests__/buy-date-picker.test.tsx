import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import type { Candle, Transaction } from "@/api/types"
import { usePrefs } from "@/stores/prefs"
import { BuyDatePicker } from "../BuyDatePicker"
import { readoutLine } from "../buy-date-text"

/** 選買入日的對話框（資產組成原型）：直接畫，日線走 mock 的 `getHistory(…, { asTraded: true })` */
beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  act(() => usePrefs.setState({ privacyMode: false }))
})

const T = { timeout: 8000 }
const lotOf = (over: Partial<Transaction>): Transaction => ({
  id: "txn_x", account_id: "acc_01JSINOPAC", symbol: "2454.TW", type: "buy", trade_date: "2025-12-06", quantity: 200, price: 488, amount: 97_600,
  fee: 0, tax: 0, health_insurance: 0, currency: "TWD", is_day_trade: false, note: "", source: "import", created_at: "2025-12-06T10:00:00+08:00",
  date_basis: "import_day", estimated_date: null, imported_on: "2025-12-06", ...over,
})
function open(lot: Transaction, name = "聯發科", market: "TWSE" | "US" = "TWSE") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <BuyDatePicker lot={lot} name={name} market={market} type="stock" open onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
  return screen.findByRole("dialog", { name: `${name}的買入日` }, T)
}

describe("選買入日", () => {
  it("帳本上的日期那天沒有收盤（星期六匯入）：打開時不會先準備好改日期；前一個收盤日標「目前的日期」並說明", async () => {
    const dialog = await open(lotOf({}))
    await within(dialog).findByRole("group", { name: /^價格走勢/ }, T)
    expect(within(dialog).getByRole("button", { name: "改日期" })).toBeDisabled()
    expect(within(dialog).queryByRole("button", { name: /^改成 / })).toBeNull()
    const readout = dialog.querySelector<HTMLElement>("[data-picker-readout]")!
    expect(within(readout).getByText("目前的日期")).toBeInTheDocument()
    expect(readout.textContent).toContain("2025/12/5")
    expect(within(readout).getByText("帳本上記的是 2025/12/6，那天沒有收盤，這是前一個交易日。")).toBeInTheDocument()
  })

  it("#16a 美股（歷史只從 2024/7/1 開始）：找不到時照實寫有資料的期間，不寫「五年內」；3 年、5 年和 1 年一樣時不放", async () => {
    // VOO 的成本 100（比 2024/7 以後的最低價低很多）：找不到
    const dialog = await open(lotOf({ symbol: "VOO", price: 100, currency: "USD", imported_on: "2025-11-29", trade_date: "2025-11-29" }), "Vanguard S&P 500 ETF", "US")
    await within(dialog).findByRole("group", { name: /^價格走勢/ }, T)
    expect(within(dialog).getByText(/^2024\/7\/1 – 2025\/11\/2\d 的股價都沒有經過成本 US\$100\.00。$/)).toBeInTheDocument()
    expect(dialog.textContent).not.toContain("五年")
    const chips = within(dialog).getByRole("radiogroup", { name: "走勢的長度" })
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["1年", "3年"])
  })

  it("匯入以前有股票分割（pick_from）：之前的日子不在圖上、不能選，資料說明一行講事實", async () => {
    // 0050 2025/6/18 一拆四；2026/11/12 匯入
    const dialog = await open(lotOf({ symbol: "0050.TW", price: 60, trade_date: "2026-03-02", estimated_date: "2026-03-02", date_basis: "estimated", imported_on: "2026-11-12" }), "元大台灣50")
    await within(dialog).findByRole("group", { name: /^價格走勢/ }, T)
    expect(within(dialog).getByText("2025/6/18 股票分割，之前的日子不能選")).toBeInTheDocument()
    // 圖從分割那天開始：只剩 1 年、3 年（3 年就是全部）
    const chips = within(dialog).getByRole("radiogroup", { name: "走勢的長度" })
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["1年", "3年"])
    act(() => within(chips).getByRole("radio", { name: "3年" }).click())
    expect(dialog.querySelector("svg[role=img]")!.getAttribute("aria-label")).toMatch(/^收盤價走勢，2025\/06\/18 到 2026\/11\/12/)
    for (const c of dialog.querySelectorAll<SVGCircleElement>("[data-candidate]")) expect(c.dataset.candidate! >= "2025-06-18").toBe(true)
  })

  it("沒有分割、減資、配股：不寫那一行", async () => {
    const dialog = await open(lotOf({ symbol: "6488.TWO", price: 580, trade_date: "2025-07-02", estimated_date: "2025-07-02", date_basis: "estimated", imported_on: "2025-11-29" }), "環球晶")
    await within(dialog).findByRole("group", { name: /^價格走勢/ }, T)
    expect(dialog.textContent).not.toContain("之前的日子不能選")
  })

  it("台股有五年的資料：1年・3年・5年都放", async () => {
    const dialog = await open(lotOf({ symbol: "6488.TWO", price: 580, trade_date: "2025-07-02", estimated_date: "2025-07-02", date_basis: "estimated", imported_on: "2025-11-29" }), "環球晶")
    const chips = await within(dialog).findByRole("radiogroup", { name: "走勢的長度" }, T)
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["1年", "3年", "5年"])
  })
})

describe("#16b／#16c 讀數下面那一句（readoutLine）", () => {
  const k = (t: string, l: number, h: number, c: number): Candle => ({ t, o: c, h, l, c, v: 0 })
  const price = (p: number) => String(p)
  const base = { cost: 580, costText: "580", price, lotDate: "2025-07-03", initialIdx: 99, privacy: false }

  it("當天經過成本（估計就是照這個找的）：寫那天的最低–最高，不寫收盤差幾 %", () => {
    const candles = [k("2025-07-01", 560, 570, 565), k("2025-07-02", 545, 612, 550)]
    expect(readoutLine(candles, 1, base)).toEqual({ text: "這天股價在 545–612 之間，經過你的成本 580。", strong: false })
  })

  it("跳空越過成本：寫前一天與這天的價格", () => {
    const up = [k("2025-07-01", 560, 570, 565), k("2025-07-02", 590, 600, 595)]
    expect(readoutLine(up, 1, base)!.text).toBe("前一天最高 570，這天最低 590，跳空越過你的成本 580。")
    const down = [k("2025-07-01", 590, 600, 595), k("2025-07-02", 560, 570, 565)]
    expect(readoutLine(down, 1, base)!.text).toBe("前一天最低 590，這天最高 570，跳空越過你的成本 580。")
  })

  it("沒有經過、收盤差 3% 以上：照實說差多少（15px 墨色）；差不多時一句淡墨", () => {
    const far = [k("2025-05-06", 540, 560, 550), k("2025-05-07", 530, 540, 536)]
    expect(readoutLine(far, 1, base)).toEqual({ text: "這天收盤 536，和你的成本 580 差 7.6%。", strong: true })
    const near = [k("2025-05-07", 583, 595, 590), k("2025-05-08", 582, 590, 585)]
    expect(readoutLine(near, 1, base)).toEqual({ text: "這天收盤和你的成本 580 差 0.9%。", strong: false })
  })

  it("帳本上的日期沒有收盤（選的是前一個收盤日）：照實說", () => {
    const candles = [k("2025-11-27", 600, 620, 610), k("2025-11-28", 600, 620, 610)]
    expect(readoutLine(candles, 1, { ...base, lotDate: "2025-11-29", initialIdx: 1 })!.text).toBe("帳本上記的是 2025/11/29，那天沒有收盤，這是前一個交易日。")
  })

  it("隱私模式：什麼都不寫（收盤加差幾 % 就算得出成本）", () => {
    const candles = [k("2025-05-07", 530, 540, 536)]
    expect(readoutLine(candles, 0, { ...base, privacy: true })).toBeNull()
  })
})
