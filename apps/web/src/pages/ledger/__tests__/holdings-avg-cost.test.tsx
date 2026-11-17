import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Holding } from "@/api/types"
import { formatMoney, formatPrice, formatQuantity } from "@/lib/format"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { COLUMN_HINT, DEFAULT_COLUMNS, useLedgerPrefs } from "../ledger-prefs"

/**
 * 持倉表預設列出均價（產品負責人 2026-11-17：「好像應該要幫我列出平均成本價？」）：
 * 收盤價那一格的第二行是 13px 淡墨「均價 692.61」，表頭「收盤價・均價」；「自訂」打開「均價」那一欄時不重複。
 * 展開一檔：最上面一行「持有・均價・成本（含買進手續費）」，桌面與手機都有。
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

describe("持倉表：收盤價下面一行是均價", { timeout: 20_000 }, () => {
  it("預設就有：表頭「收盤價・均價」（滑過寫算法）；第二行「均價 692.61」13px 淡墨、和收盤價同一套價格寫法；沒有另外一欄「均價」", async () => {
    const tsmc = await byCode("2330")
    renderApp("/")
    const table = await holdingsTable()
    const names = headerNames(table)
    expect(names[1]).toBe("收盤價・均價")
    expect(names).not.toContain("均價")
    expect(within(table).getAllByRole("columnheader")[1]).toHaveAttribute("title", COLUMN_HINT.avg_cost)
    expect(COLUMN_HINT.avg_cost).toContain("含買進手續費")

    const cell = cellOf(table, "台積電", "收盤價・均價")
    const line = avgLine(cell)!
    // 均價這類算出來的數字不藏精度（692.6087 → 692.61），和收盤價同一個 formatPrice
    expect(line).toHaveTextContent(/^均價 692\.61$/)
    expect(line.textContent).toBe(`均價 ${formatPrice(tsmc.avg_cost, tsmc.market, tsmc.type)}`)
    expect(line).toHaveClass("mt-0.5", "text-sm", "leading-tight", "text-ink-2")
    // 第一行是收盤價（和原本一樣）；整格是 .num（等寬數字）
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

/** 展開那一檔最上面的一行 */
const costLine = (root: HTMLElement, name: string) => within(root).getByLabelText(`${name}的持有與成本`)
const itemOf = (line: HTMLElement, label: string) => within(line).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement

describe("展開一檔：持有・均價・成本一行", { timeout: 20_000 }, () => {
  it("桌面：展開台積電，最上面是「持有 1 張 500 股・均價 692.61・成本 NT$1,038,913 含買進手續費」，在每一筆買賣前面", async () => {
    const tsmc = await byCode("2330")
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const table = await holdingsTable()
    await user.click(within(table).getByRole("button", { name: "展開台積電的每一筆買賣" }))
    const records = await within(table).findByRole("list", { name: "台積電的每一筆買賣" }, T)
    const box = records.closest("td")!
    const line = costLine(box, "台積電")
    expect(line.tagName).toBe("DL")
    expect(itemOf(line, "持有").textContent).toBe(formatQuantity(tsmc.quantity, "lot", "TWSE"))
    expect(itemOf(line, "持有").textContent).toBe("1 張 500 股")
    expect(itemOf(line, "均價").textContent).toBe("692.61")
    expect(itemOf(line, "成本").textContent).toBe(`${formatMoney(tsmc.cost_basis)}含買進手續費`)
    expect(itemOf(line, "成本")).toHaveTextContent(/^NT\$1,038,913/)
    expect(within(line).getByText("含買進手續費")).toHaveClass("text-sm", "text-ink-2")
    // 均價 × 股數 ＝ 成本（台股，同一個幣別）
    expect(Math.round(tsmc.avg_cost * tsmc.quantity)).toBe(Math.round(tsmc.cost_basis))
    // 在每一筆買賣的前面；label 是淡墨 13px，數字等寬
    expect(line.compareDocumentPosition(records) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(line).getByText("均價", { selector: "dt" })).toHaveClass("text-sm", "text-ink-2")
    expect(line).toHaveClass("num")
    // 以股顯示的偏好照樣用
    act(() => usePrefs.setState({ quantityUnit: "share" }))
    expect(itemOf(line, "持有").textContent).toBe("1,500 股")
  })

  it("手機：展開美股 NVIDIA，均價寫 US$、成本是新台幣（帳本的金額），股數是美股的股", async () => {
    const nvda = await byCode("NVDA")
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const phone = await screen.findByRole("list", { name: "持倉" }, T)
    await within(phone).findByRole("link", { name: "NVIDIA" }, T)
    await user.click(within(phone).getByRole("button", { name: "展開NVIDIA的每一筆買賣" }))
    const records = await within(phone).findByRole("list", { name: "NVIDIA的每一筆買賣" }, T)
    const line = costLine(records.closest("li")!, "NVIDIA")
    expect(itemOf(line, "持有").textContent).toBe("40 股")
    expect(itemOf(line, "均價").textContent).toBe(`US$${formatPrice(nvda.avg_cost, "US")}`)
    expect(itemOf(line, "成本").textContent).toBe(`${formatMoney(nvda.cost_basis)}含買進手續費`)
    // 窄的時候下面每一筆沒有表頭：這一行自己底下有一條格線
    expect(line).toHaveClass("@max-2xl:border-b", "@max-2xl:border-rule")
    // 手機的列本身不變：收盤價一行、今日漲跌一行，沒有均價
    const row = within(phone).getByRole("link", { name: "NVIDIA" }).closest("li")!.firstElementChild as HTMLElement
    expect(row).not.toHaveTextContent("均價")
  })

  it("隱私模式：股數、均價、成本都遮起來（股數照帳本的規則也遮），「含買進手續費」照常", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const table = await holdingsTable()
    await user.click(within(table).getByRole("button", { name: "展開台積電的每一筆買賣" }))
    const records = await within(table).findByRole("list", { name: "台積電的每一筆買賣" }, T)
    const line = costLine(records.closest("td")!, "台積電")
    for (const label of ["持有", "均價", "成本"]) expect(within(itemOf(line, label)).getByLabelText("已隱藏")).toBeInTheDocument()
    expect(line).not.toHaveTextContent(/\d/)
    expect(line).toHaveTextContent("含買進手續費")
  })
})
