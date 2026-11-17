import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Holding, Transaction } from "@/api/types"
import { formatMoney, formatPrice, formatQuantity } from "@/lib/format"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { COLUMN_HINT, DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"
import { buyAverage } from "../symbol-records"
import { LOT_AVG_HINT, ROW_MENU_BUTTON } from "../SymbolRecords"

/**
 * 持倉表的均價（產品負責人 2026-11-17：「好像應該要幫我列出平均成本價？」「每次買進都要顯示出買進均價（手續費幫我算進去），
 * 持倉也要顯示全部的均價（也一樣把手續費幫我算進去），然後右邊那三個點點的 hover 好像超過整個框框了」；
 * 「如果沒有填手續費就用 0 去計算吧」）：
 * - 收盤價那一格的第二行是 13px 淡墨「均價 692.61」，表頭「收盤價・均價」；「自訂」打開「均價」那一欄時不重複。
 * - 展開一檔：最上面一行「均價 692.61 含手續費・持有・成本」，桌面與手機都有。「含手續費」只在後端說目前持股的成本裡有手續費時寫
 *   （`Holding.fees_in_cost` > 0；2026-11-17 審查：前端自己重播會在兩個帳戶、先進先出、當沖、減資時寫錯），展開的那一刻就定了。
 * - 每一筆買進：價格下面一行「均價」＝（股數 × 成交價＋這一筆的手續費）÷ 股數；沒填手續費就是成交價。
 * - 每一列的「⋯」與展開鈕整顆在列裡面（不用負的右邊距），觸控 44px；滑過是 `bg-sel`（比列的 hover 深一階，看得到）。
 */
beforeAll(() => {
  window.scrollTo = () => {}
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
const resetPrefs = () => {
  localStorage.removeItem("forliosa:ledger")
  useLedgerPrefs.setState({ columns: DEFAULT_COLUMNS, showTrend: true, pinned: [], showClosed: false, phoneLine: "day" })
  usePrefs.setState({ privacyMode: false, quantityUnit: "lot" })
}
beforeEach(() => act(resetPrefs))
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(resetPrefs)
})

const T = { timeout: 8000 }
function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}
async function holdingsTable() {
  const table = await screen.findByRole("table", { name: "持倉" }, T)
  await within(table).findByRole("link", { name: "台積電" }, T)
  return table
}
const headerNames = (table: HTMLElement) => within(table).getAllByRole("columnheader").map((th) => th.textContent?.trim())
function cellOf(table: HTMLElement, name: string, header: string) {
  const idx = headerNames(table).indexOf(header)
  expect(idx).toBeGreaterThan(0)
  const row = within(table).getAllByRole("row").find((r) => within(r).queryByRole("link", { name }))!
  return within(row).getAllByRole("cell")[idx - 1]!
}
/** 收盤價那一格的第二行（13px 淡墨） */
const avgLine = (cell: HTMLElement) => cell.querySelector<HTMLElement>(".text-sm.text-ink-2.leading-tight")
const byCode = async (code: string) => (await api.getHoldings()).find((h) => h.code === code)!

/** 展開一檔（桌面的表或手機的清單），回傳每一筆買賣的清單 */
async function expand(root: HTMLElement, name: string) {
  const user = userEvent.setup({ pointerEventsCheck: 0 })
  await user.click(within(root).getByRole("button", { name: `展開${name}的每一筆買賣` }))
  const list = await within(root).findByRole("list", { name: `${name}的每一筆買賣` }, T)
  await within(list).findAllByRole("listitem", {}, T)
  return list
}
/** 展開那一檔最上面的一行 */
const costLine = (root: HTMLElement, name: string) => within(root).getByLabelText(`${name}的均價與成本`)
const itemOf = (line: HTMLElement, label: string) => within(line).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement
/** 一筆的「價格・均價」那一格（寬的版面）與手機的第二行（股數 × 價格、均價） */
const priceCell = (li: HTMLElement) => li.querySelector<HTMLElement>("span.flex.flex-col.items-end")!
const phoneLine = (li: HTMLElement) => li.querySelector<HTMLElement>("span.flex.flex-wrap.gap-x-3")!
const lotAvg = (el: HTMLElement) => [...el.querySelectorAll<HTMLElement>("span")].find((s) => s.textContent?.startsWith("均價")) ?? null

describe("持倉表：收盤價下面一行是均價", { timeout: 20_000 }, () => {
  it("預設就有：表頭「收盤價・均價」（滑過寫算法）；第二行「均價 692.61」13px 淡墨、和收盤價同一套價格寫法；沒有另外一欄「均價」", async () => {
    const tsmc = await byCode("2330")
    renderApp("/")
    const table = await holdingsTable()
    const names = headerNames(table)
    expect(names[1]).toBe("收盤價・均價")
    expect(names).not.toContain("均價")
    expect(within(table).getAllByRole("columnheader")[1]).toHaveAttribute("title", COLUMN_HINT.avg_cost)
    // 算法寫清楚：含填了的手續費，沒填的以 0 計（不說成一定有手續費）
    expect(COLUMN_HINT.avg_cost).toContain("手續費")
    expect(COLUMN_HINT.avg_cost).toContain("沒填的以 0 計")

    const cell = cellOf(table, "台積電", "收盤價・均價")
    const line = avgLine(cell)!
    // 均價這類算出來的數字不藏精度（692.6087 → 692.61），和收盤價同一個 formatPrice
    expect(line).toHaveTextContent(/^均價 692\.61$/)
    expect(line.textContent).toBe(`均價 ${formatPrice(tsmc.avg_cost, tsmc.market, tsmc.type)}`)
    expect(line).toHaveClass("mt-0.5", "text-sm", "leading-tight", "text-ink-2")
    // 第一行是收盤價（和原本一樣）；整格是 .num（等寬數字）；報讀器念「1,085 均價 692.61」（名稱就在字裡）
    expect(cell).toHaveClass("num")
    expect(cell.textContent).toBe(`1,085均價 692.61`)
  })

  it("美股：第二行寫 US$、2 位小數（收盤價那一行的 US$ 照舊）；ETF 也照傳進來的種類算位數", async () => {
    const nvda = await byCode("NVDA")
    const tw50 = await byCode("0050")
    renderApp("/")
    const table = await holdingsTable()
    await within(table).findByRole("link", { name: "NVIDIA" }, T)
    const cell = cellOf(table, "NVIDIA", "收盤價・均價")
    expect(avgLine(cell)!.textContent).toBe(`均價 US$${formatPrice(nvda.avg_cost, "US")}`)
    expect(cell.textContent).toMatch(/^US\$212\.30均價 US\$27\.46$/)
    expect(avgLine(cellOf(table, "元大台灣50", "收盤價・均價"))!.textContent).toBe(`均價 ${formatPrice(tw50.avg_cost, "TWSE", "etf")}`)
  })

  it("「自訂」打開「均價」那一欄：收盤價下面不再重複、表頭變回「收盤價」；那一欄和收盤價同一個寫法（美股的 US$ 小一號）", async () => {
    act(() => useLedgerPrefs.getState().toggleColumn("avg_cost"))
    renderApp("/")
    const table = await holdingsTable()
    await within(table).findByRole("link", { name: "NVIDIA" }, T)
    const names = headerNames(table)
    expect(names[1]).toBe("收盤價")
    expect(names).toContain("均價")
    const price = cellOf(table, "台積電", "收盤價")
    expect(price.textContent).toBe("1,085")
    expect(price).not.toHaveTextContent("均價")
    expect(cellOf(table, "台積電", "均價").textContent).toBe("692.61")
    const us = cellOf(table, "NVIDIA", "均價")
    expect(us.textContent).toMatch(/^US\$27\.46$/)
    expect(within(us).getByText("US$")).toHaveClass("text-sm", "text-ink-2")

    // 再關掉：回到第二行
    act(() => useLedgerPrefs.getState().toggleColumn("avg_cost"))
    expect(headerNames(table)[1]).toBe("收盤價・均價")
    expect(avgLine(cellOf(table, "台積電", "收盤價・均價"))).toHaveTextContent("均價 692.61")
  })

  it("隱私模式：均價遮起來（自己的成本），收盤價照常（公開的價格）", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const table = await holdingsTable()
    const cell = cellOf(table, "台積電", "收盤價・均價")
    expect(cell).toHaveTextContent("1,085")
    const line = avgLine(cell)!
    expect(line).toHaveTextContent(/^均價/)
    expect(within(line).getByLabelText("已隱藏")).toBeInTheDocument()
    expect(cell).not.toHaveTextContent("692")
  })

  it("沒有收盤價的持股：收盤價是「—」，均價照寫（成本是知道的）", async () => {
    const list = (await api.getHoldings()).map((h): Holding =>
      h.code === "AAPL" ? { ...h, price: null, prev_close: null, price_date: null, day_change: 0, day_change_pct: null, unrealized_pnl: 0, unrealized_pnl_pct: null } : h,
    )
    vi.spyOn(api, "getHoldings").mockResolvedValue(list)
    renderApp("/")
    const table = await holdingsTable()
    await within(table).findByRole("link", { name: "Apple" }, T)
    const cell = cellOf(table, "Apple", "收盤價・均價")
    expect(within(cell).getByTitle("沒有報價")).toHaveTextContent("—")
    expect(avgLine(cell)!.textContent).toBe("均價 US$143.41")
  })
})

describe("展開一檔：均價・持有・成本一行", { timeout: 20_000 }, () => {
  it("桌面：展開台積電，最上面是「均價 692.61 含手續費・持有 1 張 500 股・成本 NT$1,038,913」，在每一筆買賣前面", async () => {
    const tsmc = await byCode("2330")
    renderApp("/")
    const table = await holdingsTable()
    const records = await expand(table, "台積電")
    const line = costLine(records.closest("td")!, "台積電")
    expect(line.tagName).toBe("DL")
    // 順序：均價在最前面（負責人要的是均價）
    expect(within(line).getAllByRole("term").map((dt) => dt.textContent)).toEqual(["均價", "持有", "成本"])
    // 示範帳本的兩筆買進都有手續費（162、251），後端（示範是 mock）回 fees_in_cost 413：「含手續費」13px 淡墨，跟在均價後面
    expect(tsmc.fees_in_cost).toBe(162 + 251)
    expect(within(line).getByText("含手續費")).toHaveClass("text-sm", "text-ink-2")
    expect(itemOf(line, "均價").textContent).toBe("692.61 含手續費")
    expect(itemOf(line, "持有").textContent).toBe(formatQuantity(tsmc.quantity, "lot", "TWSE"))
    expect(itemOf(line, "持有").textContent).toBe("1 張 500 股")
    expect(itemOf(line, "成本").textContent).toBe(formatMoney(tsmc.cost_basis))
    expect(itemOf(line, "成本")).toHaveTextContent(/^NT\$1,038,913$/)
    // 均價 × 股數 ＝ 成本（台股，同一個幣別）；成本＝兩筆的成交金額加上兩筆的手續費
    expect(Math.round(tsmc.avg_cost * tsmc.quantity)).toBe(Math.round(tsmc.cost_basis))
    expect(tsmc.cost_basis).toBe(500 * 815 + 162 + 1000 * 631 + 251)
    // 在每一筆買賣的前面；名稱是淡墨 13px，數字等寬
    expect(line.compareDocumentPosition(records) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(line).getByText("均價", { selector: "dt" })).toHaveClass("text-sm", "text-ink-2")
    expect(line).toHaveClass("num")
    // 以股顯示的偏好照樣用
    act(() => usePrefs.setState({ quantityUnit: "share" }))
    expect(itemOf(line, "持有").textContent).toBe("1,500 股")
  })

  it("手機：展開美股 NVIDIA，均價寫 US$、成本是新台幣（帳本的金額），股數是美股的股", async () => {
    const nvda = await byCode("NVDA")
    renderApp("/")
    const phone = await screen.findByRole("list", { name: "持倉" }, T)
    await within(phone).findByRole("link", { name: "NVIDIA" }, T)
    const records = await expand(phone, "NVIDIA")
    const line = costLine(records.closest("li")!, "NVIDIA")
    expect(itemOf(line, "持有").textContent).toBe("40 股")
    expect(nvda.fees_in_cost).toBeGreaterThan(0)
    expect(itemOf(line, "均價").textContent).toBe(`US$${formatPrice(nvda.avg_cost, "US")} 含手續費`)
    expect(itemOf(line, "成本").textContent).toBe(formatMoney(nvda.cost_basis))
    // 窄的時候下面每一筆沒有表頭：這一行自己底下有一條格線（和每一筆買賣同一個 43rem 斷點）
    expect(line).toHaveClass("@max-[43rem]:border-b", "@max-[43rem]:border-rule")
    // 手機的列本身不變：收盤價一行、今日漲跌一行，沒有均價
    const row = within(phone).getByRole("link", { name: "NVIDIA" }).closest("li")!.firstElementChild as HTMLElement
    expect(row).not.toHaveTextContent("均價")
  })

  it("隱私模式：均價、股數、成本都遮起來（股數照帳本的規則也遮），「含手續費」照常", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const table = await holdingsTable()
    const records = await expand(table, "台積電")
    const line = costLine(records.closest("td")!, "台積電")
    for (const label of ["持有", "均價", "成本"]) expect(within(itemOf(line, label)).getByLabelText("已隱藏")).toBeInTheDocument()
    expect(line).not.toHaveTextContent(/\d/)
    expect(within(line).getByText("含手續費")).toBeInTheDocument()
  })

  it("「含手續費」展開的那一刻就定了，不等下面每一筆讀完（原本晚出現，整行往右跳、手機上換行）", async () => {
    // 每一筆買賣一直讀不完：上面那一行照樣完整（含「含手續費」），下面是骨架
    vi.spyOn(api, "listTransactions").mockReturnValue(new Promise(() => {}))
    renderApp("/")
    const table = await holdingsTable()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.click(within(table).getByRole("button", { name: "展開台積電的每一筆買賣" }))
    const box = within(table).getByLabelText("台積電的紀錄載入中").closest("td")!
    const line = costLine(box, "台積電")
    expect(itemOf(line, "均價").textContent).toBe("692.61 含手續費")
    expect(itemOf(line, "成本")).toHaveTextContent(/^NT\$1,038,913$/)
  })

  it("後端說成本裡沒有手續費（fees_in_cost 0）就不寫，即使下面有一筆填了手續費的買進（兩個帳戶，填了手續費的那個已經全部賣掉）", async () => {
    // 審查的例子：帳戶 A 買 1000 股 @100、手續費 40；帳戶 B 買 1000 股 @120、沒填；A 全部賣掉。後端：均價 120、不含手續費
    const base = await byCode("2330")
    const holding: Holding = { ...base, quantity: 1000, avg_cost: 120, cost_basis: 120000, fees_in_cost: 0, account_ids: ["acc_B"] }
    vi.spyOn(api, "getHoldings").mockResolvedValue([holding])
    const row = (p: Partial<Transaction>): Transaction => ({
      id: "t", account_id: "acc_A", symbol: "2330.TW", type: "buy", trade_date: "2026-01-02", quantity: 1000, price: 100, amount: 100000,
      fee: 0, tax: 0, health_insurance: 0, currency: "TWD", is_day_trade: false, note: "", source: "manual", created_at: "2026-01-02T00:00:00Z", ...p,
    })
    const items = [
      row({ id: "3", type: "sell", trade_date: "2026-03-02", price: 130, amount: 130000, created_at: "2026-03-02T00:00:00Z" }),
      row({ id: "2", account_id: "acc_B", trade_date: "2026-02-02", price: 120, amount: 120000, created_at: "2026-02-02T00:00:00Z" }),
      row({ id: "1", fee: 40 }),
    ]
    vi.spyOn(api, "listTransactions").mockResolvedValue({ items, next_cursor: null })
    renderApp("/")
    const table = await holdingsTable()
    const records = await expand(table, "台積電")
    const line = costLine(records.closest("td")!, "台積電")
    expect(itemOf(line, "均價").textContent).toBe("120")
    expect(line).not.toHaveTextContent("手續費")
    // 那一筆自己的均價照樣含它的手續費（(1000 × 100＋40) ÷ 1000）
    expect(within(records).getAllByRole("listitem").map((li) => lotAvg(priceCell(li))?.textContent ?? null)).toEqual([null, "均價 120", "均價 100.04"])

    // 舊的後端沒有 fees_in_cost：不寫（不暗示一個不知道的費用）
    cleanup()
    const { fees_in_cost: _drop, ...old } = holding
    vi.spyOn(api, "getHoldings").mockResolvedValue([old as Holding])
    renderApp("/")
    const again = await holdingsTable()
    const records2 = await expand(again, "台積電")
    expect(costLine(records2.closest("td")!, "台積電")).not.toHaveTextContent("手續費")
  })
})

describe("每一筆買進的均價（含這一筆的手續費）", { timeout: 20_000 }, () => {
  it("桌面：表頭「價格・均價」（滑過寫算法）；台積電兩筆：815 下面「均價 815.32」（(500 × 815＋162) ÷ 500）、631 下面「均價 631.25」", async () => {
    renderApp("/")
    const table = await holdingsTable()
    const records = await expand(table, "台積電")
    const box = records.closest("td")!
    const head = within(box).getByText("價格・均價")
    expect(head).toHaveAttribute("title", LOT_AVG_HINT)
    expect(LOT_AVG_HINT).toContain("沒填手續費以 0 計")
    const [first, second] = within(records).getAllByRole("listitem")
    const cell = priceCell(first!)
    expect(cell).toHaveClass("num")
    expect(cell.firstElementChild!.textContent).toBe("815")
    const avg = lotAvg(cell)!
    expect(avg.textContent).toBe("均價 815.32")
    expect(avg).toHaveClass("text-sm", "text-ink-2", "whitespace-nowrap")
    expect(lotAvg(priceCell(second!))!.textContent).toBe("均價 631.25")
    // 金額照舊是成交金額（不含手續費）
    expect(first).toHaveTextContent("NT$407,500")
    // 報讀器念得到名稱：「815 均價 815.32」
    expect(cell.textContent).toBe("815均價 815.32")
  })

  it("手機的兩行版面：第二行「500 股 × 815」「均價 815.32」各自不斷開（放不下時均價整段換行）", async () => {
    renderApp("/")
    const phone = await screen.findByRole("list", { name: "持倉" }, T)
    await within(phone).findByRole("link", { name: "台積電" }, T)
    const records = await expand(phone, "台積電")
    const line = phoneLine(within(records).getAllByRole("listitem")[0]!)
    const parts = [...line.children].map((c) => c.textContent)
    expect(parts).toEqual(["500 股 × 815", "均價 815.32"])
    for (const c of line.children) expect(c).toHaveClass("whitespace-nowrap")
    expect(line).toHaveClass("text-sm", "text-ink-2", "flex-wrap")
  })

  it("美股：價格與手續費都是美元，「均價 US$274.55」（(4 × 273.80＋3) ÷ 4，兩位小數）", async () => {
    renderApp("/")
    const table = await holdingsTable()
    await within(table).findByRole("link", { name: "NVIDIA" }, T)
    const records = await expand(table, "NVIDIA")
    const li = within(records).getAllByRole("listitem")[0]!
    expect(priceCell(li).firstElementChild!.textContent).toBe("US$273.80")
    expect(lotAvg(priceCell(li))!.textContent).toBe("均價 US$274.55")
    expect(lotAvg(phoneLine(li))!.textContent).toBe("均價 US$274.55")
  })

  it("隱私模式：每一筆的價格與均價都遮（「均價」兩個字留著），日期、類型照常", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const table = await holdingsTable()
    const records = await expand(table, "台積電")
    const li = within(records).getAllByRole("listitem")[0]!
    const avg = lotAvg(priceCell(li))!
    expect(avg).toHaveTextContent(/^均價/)
    expect(within(avg).getByLabelText("已隱藏")).toBeInTheDocument()
    expect(priceCell(li)).not.toHaveTextContent(/\d/)
    expect(lotAvg(phoneLine(li))).toHaveTextContent(/^均價/)
    expect(phoneLine(li)).not.toHaveTextContent(/\d/)
    expect(li).toHaveTextContent("買進")
  })
})

describe("算法（buyAverage）", () => {
  const txn = (p: Partial<Transaction>): Transaction => ({
    id: "t", account_id: "a", symbol: "2330.TW", type: "buy", trade_date: "2026-01-02", quantity: 1000, price: 100, amount: 100000,
    fee: 0, tax: 0, health_insurance: 0, currency: "TWD", is_day_trade: false, note: "", source: "manual", created_at: "2026-01-02T00:00:00Z", ...p,
  })
  it("買進：(股數 × 成交價＋手續費) ÷ 股數；沒填手續費（存 0）就是成交價；美股照美元算；賣出、缺股數或價格是 null", () => {
    expect(buyAverage(txn({ quantity: 500, price: 815, fee: 162 }))).toBeCloseTo(815.324, 9)
    expect(buyAverage(txn({ quantity: 1000, price: 631, fee: 0 }))).toBe(631)
    expect(buyAverage(txn({ quantity: 4, price: 273.8, fee: 3, currency: "USD" }))).toBeCloseTo(274.55, 9)
    expect(formatPrice(buyAverage(txn({ quantity: 4, price: 273.8, fee: 3 })), "US")).toBe("274.55")
    // 零股：手續費佔的比例大，均價看得出差異
    expect(formatPrice(buyAverage(txn({ quantity: 3, price: 1085, fee: 1 })), "TWSE", "stock")).toBe("1,085.33")
    expect(buyAverage(txn({ type: "sell", quantity: 100, price: 1000, fee: 20 }))).toBeNull()
    expect(buyAverage(txn({ quantity: null }))).toBeNull()
    expect(buyAverage(txn({ price: null }))).toBeNull()
  })
})

/** 往上到那一列（tr／li）為止，沒有任何一層用負的右邊距把按鈕推出去 */
const NEG_RIGHT = /(^|\s)-m[rxe]-/
function insideRow(button: HTMLElement) {
  for (let el: HTMLElement | null = button; el && !["TR", "LI"].includes(el.tagName); el = el.parentElement) expect(el.className).not.toMatch(NEG_RIGHT)
}

describe("「⋯」與展開鈕整顆在列裡面（滑過的底色不超出框線）", { timeout: 20_000 }, () => {
  it("持倉表每一列的「⋯」、展開鈕，與展開後每一筆的「⋯」：沒有負的右邊距；觸控 44px；動作那一欄在觸控裝置上放得下兩顆 44px", async () => {
    expect(ROW_MENU_BUTTON).not.toMatch(NEG_RIGHT)
    // 觸控 44px：每一筆的最後一欄只有 40px，不能被擠小（shrink-0）
    expect(ROW_MENU_BUTTON).toContain("pointer-coarse:size-11")
    expect(ROW_MENU_BUTTON).toContain("shrink-0")
    // 滑過看得到方塊：列滑過時是 --hov，按鈕用深一階的 --sel（不是同一個 hover:bg-hov）
    expect(ROW_MENU_BUTTON.split(" ")).toContain("hover:bg-sel")
    expect(ROW_MENU_BUTTON).not.toContain("hover:bg-hov")
    renderApp("/")
    const table = await holdingsTable()
    const records = await expand(table, "台積電")
    const rowMenu = within(table).getByRole("button", { name: "台積電的動作" })
    expect(rowMenu.className).toBe(ROW_MENU_BUTTON)
    insideRow(rowMenu)
    const collapse = within(table).getByRole("button", { name: "收起台積電的每一筆買賣" })
    insideRow(collapse)
    expect(collapse).toHaveClass("pointer-coarse:size-11", "hover:bg-sel")
    expect(collapse).not.toHaveClass("hover:bg-hov")
    // 兩顆都在格線列裡（列滑過是 --hov）
    expect(rowMenu.closest("tr")).toHaveClass("ruled-row")
    for (const b of within(records).getAllByRole("button", { name: /的動作$/ })) {
      expect(b.className).toBe(ROW_MENU_BUTTON)
      insideRow(b)
    }
    const actions = table.querySelector<HTMLElement>("thead th:last-child")!
    expect(actions).toHaveTextContent("動作")
    expect(actions).toHaveClass("w-[76px]", "pointer-coarse:w-[92px]")
  })

  it("手機：每一列的展開鈕、表頭的切換鈕、展開後每一筆的「⋯」也一樣", async () => {
    renderApp("/")
    const phone = await screen.findByRole("list", { name: "持倉" }, T)
    await within(phone).findByRole("link", { name: "台積電" }, T)
    const records = await expand(phone, "台積電")
    const collapse = within(phone).getByRole("button", { name: "收起台積電的每一筆買賣" })
    insideRow(collapse)
    expect(collapse).toHaveClass("hover:bg-sel")
    for (const b of within(records).getAllByRole("button", { name: /的動作$/ })) insideRow(b)
    const toggle = screen.getByRole("button", { name: /（改看損益）$/ })
    expect(toggle.className).not.toMatch(NEG_RIGHT)
  })
})

/** 最後跑：會在示範帳本裡新增交易（同一個檔案的 mock 狀態是共用的） */
describe("沒填手續費（以 0 計）", { timeout: 20_000 }, () => {
  it("新買一檔、沒填手續費：那一筆的均價就是成交價；展開那一行不寫「含手續費」；再買一筆填了手續費，才寫，整體均價含那一筆的手續費；賣出那一筆不寫均價", async () => {
    await api.createTransaction({ account_id: "acc_01JSINOPAC", symbol: "2382.TW", type: "buy", trade_date: "2026-11-02", quantity: 1000, price: 300 })
    const created = (await api.listTransactions({ symbol: "2382.TW", limit: 10 })).items
    expect(created.map((t) => t.fee)).toEqual([0])
    expect((await byCode("2382")).avg_cost).toBe(300)

    renderApp("/")
    let table = await holdingsTable()
    await within(table).findByRole("link", { name: "廣達" }, T)
    expect(avgLine(cellOf(table, "廣達", "收盤價・均價"))!.textContent).toBe("均價 300")
    let records = await expand(table, "廣達")
    const li = within(records).getAllByRole("listitem")[0]!
    expect(priceCell(li).firstElementChild!.textContent).toBe("300")
    expect(lotAvg(priceCell(li))!.textContent).toBe("均價 300")
    let line = costLine(records.closest("td")!, "廣達")
    expect(itemOf(line, "均價").textContent).toBe("300")
    expect(line).not.toHaveTextContent("手續費")
    cleanup()

    await api.createTransaction({ account_id: "acc_01JSINOPAC", symbol: "2382.TW", type: "buy", trade_date: "2026-11-03", quantity: 1000, price: 310, fee: 100 })
    await api.createTransaction({ account_id: "acc_01JSINOPAC", symbol: "2382.TW", type: "sell", trade_date: "2026-11-04", quantity: 500, price: 320 })
    renderApp("/")
    table = await holdingsTable()
    await within(table).findByRole("link", { name: "廣達" }, T)
    records = await expand(table, "廣達")
    const [sell, buy2, buy1] = within(records).getAllByRole("listitem")
    expect(sell).toHaveTextContent("賣出")
    expect(lotAvg(priceCell(sell!))).toBeNull()
    expect(lotAvg(phoneLine(sell!))).toBeNull()
    expect(lotAvg(priceCell(buy2!))!.textContent).toBe("均價 310.1")
    expect(lotAvg(priceCell(buy1!))!.textContent).toBe("均價 300")
    line = costLine(records.closest("td")!, "廣達")
    // 移動平均賣掉四分之一：成本裡的手續費也剩 75
    expect((await byCode("2382")).fees_in_cost).toBe(75)
    expect(within(line).getByText("含手續費")).toBeInTheDocument()
    // 移動平均：(300,000＋310,100) ÷ 2,000 ＝ 305.05，賣掉 500 股之後均價不變
    expect(itemOf(line, "均價").textContent).toBe("305.05 含手續費")
    expect(itemOf(line, "持有").textContent).toBe("1 張 500 股")
  })
})
