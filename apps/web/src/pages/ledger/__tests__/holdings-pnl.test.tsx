import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Holding } from "@/api/types"
import { formatMoney, formatPercent } from "@/lib/format"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { ALL_COLUMNS, DEFAULT_COLUMNS, migrateLedgerPrefs, useLedgerPrefs, type HoldingColumn } from "../ledger-prefs"

/**
 * 持倉表預設多一欄「損益」（產品負責人 2026-11-16 選 A）：未實現損益的金額，下面一行報酬率；
 * 「未實現損益」「報酬率」仍是「自訂」裡各自的欄位。存在瀏覽器裡的舊預設換成新預設，自己選過的照舊。
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
  usePrefs.setState({ privacyMode: false })
}
beforeEach(() => act(resetPrefs))
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(resetPrefs)
})

const OLD_DEFAULT: HoldingColumn[] = ["price", "day_pct", "day_change", "value"]

describe("欄位設定：預設多了「損益」，舊的設定怎麼換", () => {
  it("新的預設是 收盤價・今日漲跌・今日損益・損益・市值；「損益」排在今日損益後面、市值前面；還原預設也是這一組", () => {
    expect(DEFAULT_COLUMNS).toEqual(["price", "day_pct", "day_change", "pnl", "value"])
    expect(ALL_COLUMNS.indexOf("pnl")).toBe(ALL_COLUMNS.indexOf("day_change") + 1)
    expect(ALL_COLUMNS.indexOf("pnl")).toBe(ALL_COLUMNS.indexOf("value") - 1)
    // 「未實現損益」「報酬率」還是可以各自打開
    expect(ALL_COLUMNS).toEqual(expect.arrayContaining(["unrealized", "unrealized_pct"]))
    act(() => useLedgerPrefs.setState({ columns: ["price"] }))
    act(() => useLedgerPrefs.getState().reset())
    expect(useLedgerPrefs.getState().columns).toEqual(DEFAULT_COLUMNS)
  })

  it("勾選「損益」：插在今日損益和市值中間（照欄位的順序），不是加在最後", () => {
    act(() => useLedgerPrefs.setState({ columns: OLD_DEFAULT }))
    act(() => useLedgerPrefs.getState().toggleColumn("pnl"))
    expect(useLedgerPrefs.getState().columns).toEqual(DEFAULT_COLUMNS)
  })

  it("第 1 版還是當時的預設（沒動過）→ 換成新的預設；其他設定（走勢圖、釘選、已出清）照舊", () => {
    const v1 = { columns: OLD_DEFAULT, showTrend: false, pinned: ["2330.TW"], showClosed: true }
    expect(migrateLedgerPrefs(v1, 1)).toEqual({ ...v1, columns: DEFAULT_COLUMNS })
    // 順序不同也是同一組
    expect(migrateLedgerPrefs({ ...v1, columns: ["value", "price", "day_change", "day_pct"] }, 1)).toEqual({ ...v1, columns: DEFAULT_COLUMNS })
  })

  it("自己選過欄位的照舊（少一欄、多一欄都算自己選的）；已經是第 2 版的不動", () => {
    for (const columns of [
      ["price", "day_pct", "value"],
      ["price", "day_pct", "day_change", "value", "unrealized", "unrealized_pct"],
      ["price", "avg_cost", "unrealized"],
    ]) {
      const v1 = { columns, showTrend: true, pinned: [], showClosed: false }
      expect(migrateLedgerPrefs(v1, 1)).toEqual(v1)
    }
    // 第 2 版還是舊的那四欄：是自己把「損益」關掉的，不再加回去
    const v2 = { columns: OLD_DEFAULT, showTrend: true, pinned: [], showClosed: false }
    expect(migrateLedgerPrefs(v2, 2)).toEqual(v2)
  })

  it("從瀏覽器讀回來（zustand persist 第 1 版 → 第 2 版）：舊預設換成新預設、自己選過的照舊", async () => {
    localStorage.setItem("forliosa:ledger", JSON.stringify({ state: { columns: OLD_DEFAULT, showTrend: true, pinned: ["2317.TW"], showClosed: false }, version: 1 }))
    await act(() => useLedgerPrefs.persist.rehydrate())
    expect(useLedgerPrefs.getState().columns).toEqual(DEFAULT_COLUMNS)
    expect(useLedgerPrefs.getState().pinned).toEqual(["2317.TW"])
    // 存回去的是第 2 版
    expect(JSON.parse(localStorage.getItem("forliosa:ledger")!).version).toBe(2)

    const custom: HoldingColumn[] = ["price", "day_pct", "value", "unrealized"]
    localStorage.setItem("forliosa:ledger", JSON.stringify({ state: { columns: custom, showTrend: true, pinned: [], showClosed: false }, version: 1 }))
    await act(() => useLedgerPrefs.persist.rehydrate())
    expect(useLedgerPrefs.getState().columns).toEqual(custom)
  })
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

/** 示範帳本的持股，Apple 改成還沒有收盤價（商用模式的美股剛記進帳本時就是這樣） */
async function holdingsWithUnpriced(): Promise<Holding[]> {
  const list = await api.getHoldings()
  return list.map((h) => (h.code === "AAPL" ? { ...h, price: null, prev_close: null, price_date: null, day_change: 0, day_change_pct: null, unrealized_pnl: 0, unrealized_pnl_pct: null } : h))
}

async function holdingsTable() {
  const table = await screen.findByRole("table", { name: "持倉" }, T)
  await within(table).findByRole("link", { name: "台積電" }, T)
  return table
}
const headerNames = (table: HTMLElement) => within(table).getAllByRole("columnheader").map((th) => th.textContent?.trim())
/** 這一列某一欄的格子（第一欄是名稱，是列標題，不算在 cell 裡） */
function cellOf(table: HTMLElement, name: string, header: string) {
  const idx = headerNames(table).indexOf(header)
  expect(idx).toBeGreaterThan(0)
  const row = within(table).getAllByRole("row").find((r) => within(r).queryByRole("link", { name }))!
  return within(row).getAllByRole("cell")[idx - 1]!
}
/** 持股那幾列的順序（第一個 tbody；觀察清單是第二個） */
const rowOrder = (table: HTMLElement) =>
  within(table.querySelector("tbody")!)
    .getAllByRole("rowheader")
    .map((th) => th.querySelector("a")?.textContent)
    .filter((n): n is string => !!n)

describe("持倉表的「損益」欄", { timeout: 20_000 }, () => {
  it("預設就有：在今日損益後面、市值・佔比前面；一格是金額（正負號、漲跌色）＋下一行報酬率（▲▼）", async () => {
    const holdings = await api.getHoldings()
    renderApp("/")
    const table = await holdingsTable()
    const names = headerNames(table)
    const at = names.indexOf("損益")
    expect(at).toBeGreaterThan(0)
    expect(names[at + 1]).toBe("市值・佔比")
    // 前一欄是今日損益（收盤價不是今天的時候寫「11/13 損益」；jsdom 沒有容器查詢，窄的時候才出現的「・漲跌」也算在文字裡）
    expect(names[at - 1]).toMatch(/^(今日|當日|\d+\/\d+ )損益(・漲跌)?$/)
    // 「損益」和主數字的「總損益（含股利）」對不起來：表頭滑過寫清楚算法
    expect(within(table).getAllByRole("columnheader")[at]).toHaveAttribute("title", expect.stringContaining("不含股利"))

    const tsmc = holdings.find((h) => h.code === "2330")!
    expect(tsmc.unrealized_pnl).toBeGreaterThan(0)
    const cell = cellOf(table, "台積電", "損益")
    const amount = formatMoney(tsmc.unrealized_pnl, { signed: true, bare: true })
    expect(amount.startsWith("+")).toBe(true)
    expect(within(cell).getByText(amount)).toHaveClass("text-rise")
    const pct = within(cell).getByText(formatPercent(tsmc.unrealized_pnl_pct, { signed: false }))
    // 報酬率和個股頁、今日漲跌同一個寫法：▲ 加百分比（不帶正負號）、漲跌色、小一號
    const pctBox = pct.closest(".num")!
    expect(pctBox).toHaveClass("text-rise", "text-sm")
    expect(pctBox).toHaveTextContent("▲")
    expect(within(cell).getByText("上漲")).toHaveClass("sr-only")

    // 賠錢的那一檔：−金額、▼、跌的顏色
    const loser = holdings.find((h) => h.price !== null && h.unrealized_pnl < 0)!
    const lossCell = cellOf(table, loser.name, "損益")
    expect(within(lossCell).getByText(formatMoney(loser.unrealized_pnl, { signed: true, bare: true }))).toHaveClass("text-fall")
    expect(lossCell).toHaveTextContent("▼")
  })

  it("美股：金額和「未實現損益」欄一樣（帳本的金額都是新台幣，不寫 US$）；兩欄的數字一致", async () => {
    act(() => useLedgerPrefs.setState({ columns: ALL_COLUMNS }))
    renderApp("/")
    const table = await holdingsTable()
    await within(table).findByRole("link", { name: "NVIDIA" }, T)
    for (const name of ["NVIDIA", "台積電"]) {
      const pnl = cellOf(table, name, "損益")
      expect(pnl.textContent).toBe(`${cellOf(table, name, "未實現損益").textContent}${cellOf(table, name, "報酬率").textContent}`)
      expect(pnl.textContent).not.toContain("US$")
    }
  })

  it("按表頭「損益」照未實現損益的金額排（大到小，再按一次小到大）；和「未實現損益」一起開著時只標「損益」那一欄", async () => {
    act(() => useLedgerPrefs.setState({ columns: ALL_COLUMNS }))
    const holdings = await api.getHoldings()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const table = await holdingsTable()
    const byPnl = [...holdings].sort((a, b) => b.unrealized_pnl - a.unrealized_pnl).map((h) => h.name)

    await user.click(within(table).getByRole("button", { name: "損益" }))
    const header = within(table).getAllByRole("columnheader").find((th) => th.textContent?.trim() === "損益")!
    expect(header).toHaveAttribute("aria-sort", "descending")
    expect(rowOrder(table)).toEqual(byPnl)
    const unrealized = within(table).getAllByRole("columnheader").find((th) => th.textContent?.trim() === "未實現損益")!
    expect(unrealized).not.toHaveAttribute("aria-sort")

    await user.click(within(table).getByRole("button", { name: "損益" }))
    expect(header).toHaveAttribute("aria-sort", "ascending")
    expect(rowOrder(table)).toEqual([...byPnl].reverse())
  })

  it("沒有收盤價的持股：「損益」是一個「—」，沒有金額、沒有報酬率", async () => {
    const list = await holdingsWithUnpriced()
    vi.spyOn(api, "getHoldings").mockResolvedValue(list)
    renderApp("/")
    const table = await holdingsTable()
    await within(table).findByRole("link", { name: "Apple" }, T)
    const cell = cellOf(table, "Apple", "損益")
    expect(cell.textContent).toBe("—")
    expect(within(cell).getByTitle("沒有報價")).toBeInTheDocument()
  })

  it("隱私模式：金額遮起來，報酬率照常（百分比不是金額）", async () => {
    const holdings = await api.getHoldings()
    const tsmc = holdings.find((h) => h.code === "2330")!
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/")
    const table = await holdingsTable()
    const cell = cellOf(table, "台積電", "損益")
    expect(within(cell).getByLabelText("已隱藏")).toBeInTheDocument()
    expect(cell).not.toHaveTextContent(formatMoney(tsmc.unrealized_pnl, { signed: true, bare: true }))
    expect(cell).toHaveTextContent(formatPercent(tsmc.unrealized_pnl_pct, { signed: false }))
  })

  it("主欄窄的時候（< 52rem）：今日漲跌併進今日損益那一格的第二行（兩欄都開著才併；用容器查詢，寬的時候照常分兩欄）", async () => {
    renderApp("/")
    let table = await holdingsTable()
    const names = headerNames(table)
    const dayPct = within(table).getAllByRole("columnheader")[names.findIndex((n) => /漲跌$/.test(n ?? "") && !/損益/.test(n ?? ""))]!
    expect(dayPct).toHaveClass("@max-[52rem]:hidden")
    const dayLabel = names.find((n) => /^(今日|當日|\d+\/\d+ )損益・漲跌$/.test(n ?? ""))!
    const day = cellOf(table, "台積電", dayLabel)
    // 窄的時候才出現的第二行（寬的時候藏起來）
    const second = day.querySelector(".text-sm")
    expect(second).toHaveClass("@min-[52rem]:hidden")
    expect(second).toHaveTextContent("▲")
    // 數字欄之間至少 12px（寬窄都一樣），窄的時候只佔自己需要的寬度
    expect(day).toHaveClass("pl-3")
    expect(dayPct).toHaveClass("pl-3", "@max-[52rem]:w-px")
    // 名稱欄拿剩下的寬度，放不下就截斷、滑過看全名（列高不變）
    const nameCell = within(table).getByRole("link", { name: "台積電" }).closest("th")!
    expect(nameCell).toHaveClass("@max-[52rem]:max-w-0")
    expect(within(table).getByRole("link", { name: "台積電" })).toHaveAttribute("title", "台積電")
    expect(within(table).getByRole("link", { name: "台積電" })).toHaveClass("@max-[52rem]:truncate")

    // 只開今日損益：不用併，也沒有第二行
    cleanup()
    act(() => useLedgerPrefs.setState({ columns: ["price", "day_change", "pnl", "value"] }))
    renderApp("/")
    table = await holdingsTable()
    const only = cellOf(table, "台積電", headerNames(table).find((n) => /損益$/.test(n ?? "") && n !== "損益")!)
    expect(only.querySelector(".text-sm")).toBeNull()
    expect(within(table).getAllByRole("columnheader").some((th) => th.className.includes("@max-[52rem]:hidden"))).toBe(false)
    expect(within(table).queryByRole("button", { name: "漲跌" })).toBeNull()
  })

  it("主欄窄的時候也能照漲跌幅排：今日損益的表頭多一個「漲跌」；最窄（< 46rem）時只在正照它排的時候出現", async () => {
    const holdings = await api.getHoldings()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const table = await holdingsTable()
    const button = within(table).getByRole("button", { name: "漲跌" })
    const wrap = button.parentElement!
    // 寬的時候藏起來（有自己的「今日漲跌」欄）；最窄的時候沒有照它排就藏起來，省下名稱的寬度
    expect(wrap).toHaveClass("@min-[52rem]:hidden", "@max-[46rem]:hidden")
    expect(button.closest("th")!.textContent).toMatch(/損益・漲跌$/)

    await user.click(button)
    const byPct = [...holdings].sort((a, b) => (b.day_change_pct ?? 0) - (a.day_change_pct ?? 0)).map((h) => h.name)
    expect(rowOrder(table)).toEqual(byPct)
    // 正照它排：最窄的時候也看得到（箭頭、墨色），螢幕閱讀器讀得到排序方向
    expect(wrap).not.toHaveClass("@max-[46rem]:hidden")
    expect(wrap).toHaveClass("@min-[52rem]:hidden")
    expect(within(table).getByRole("button", { name: "漲跌" })).toHaveClass("text-ink")
    expect(within(wrap).getByText("（照漲跌由大到小排）")).toHaveClass("sr-only")
    // 「今日損益」那一格自己沒有標排序（照的是漲跌，不是金額）
    expect(button.closest("th")).not.toHaveAttribute("aria-sort")

    await user.click(within(table).getByRole("button", { name: "漲跌" }))
    expect(rowOrder(table)).toEqual([...byPct].reverse())
    expect(within(wrap).getByText("（照漲跌由小到大排）")).toHaveClass("sr-only")
  })
})

/**
 * 手機持倉列右下那一行（產品負責人 2026-11-17 選 A）：表頭「收盤價・今日漲跌」是切換鈕，按一下變「收盤價・損益」，
 * 每一列的今日漲跌換成這一檔的報酬率（和桌面「損益」欄的第二行同一個數字）；版面不變、記在這台瀏覽器；桌面不受影響。
 */
async function phoneList() {
  const list = await screen.findByRole("list", { name: "持倉" }, T)
  await within(list).findByRole("link", { name: "台積電" }, T)
  return list
}
const DAY_WORD = "(今日|當日|\\d+/\\d+ )"
const dayToggle = () => screen.getByRole("button", { name: new RegExp(`^收盤價・${DAY_WORD}漲跌\\s*（改看損益）$`) })
const pnlToggle = () => screen.getByRole("button", { name: new RegExp(`^收盤價・損益\\s*（改看${DAY_WORD}漲跌）$`) })
/** 這一列收盤價下面那一行（看得到的百分比＋只給螢幕報讀器的欄名） */
function phoneLineOf(list: HTMLElement, name: string) {
  const row = within(list).getByRole("link", { name }).closest("li")!.firstElementChild as HTMLElement
  const line = row.querySelector<HTMLElement>(":scope > .col-start-2")
  expect(line).not.toBeNull()
  return line!
}
const pctText = (v: number | null) => formatPercent(v === null ? null : Math.abs(v), { signed: false })
const stored = () => JSON.parse(localStorage.getItem("forliosa:ledger") ?? "null") as { state: Record<string, unknown>; version: number } | null

describe("手機持倉：表頭切換今日漲跌與報酬率", { timeout: 20_000 }, () => {
  it("預設是今日漲跌；按表頭換成報酬率（▲▼、漲跌色），再按一次換回來；記在這台瀏覽器；桌面的表不變", async () => {
    const holdings = await api.getHoldings()
    const tsmc = holdings.find((h) => h.code === "2330")!
    const loser = holdings.find((h) => h.price !== null && h.unrealized_pnl_pct !== null && h.unrealized_pnl_pct < 0)!
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const list = await phoneList()
    const table = await holdingsTable()
    // 觀察清單的表頭（同一張表的第二個 tbody）比持股晚一點進來：等它出現再記下桌面的表頭，之後才比得起來
    await within(table).findByRole("columnheader", { name: /^觀察/ }, { timeout: 5000 })
    const desktopHeads = headerNames(table)

    // 真的按鈕、和表頭一樣高（44px）；名稱是看得到的字＋要換成什麼
    const toggle = dayToggle()
    expect(toggle.tagName).toBe("BUTTON")
    expect(toggle).toHaveAttribute("type", "button")
    expect(toggle).toHaveClass("h-11")
    expect(within(toggle).getByText(/（改看損益）/)).toHaveClass("sr-only")
    let line = phoneLineOf(list, "台積電")
    expect(line).toHaveTextContent(pctText(tsmc.day_change_pct))
    expect(within(line).getByText(new RegExp(`^${DAY_WORD}漲跌$`))).toHaveClass("sr-only")

    await user.click(toggle)
    expect(pnlToggle()).toBe(toggle)
    line = phoneLineOf(list, "台積電")
    expect(line).not.toHaveTextContent(pctText(tsmc.day_change_pct))
    const pct = within(line).getByText(pctText(tsmc.unrealized_pnl_pct)).closest(".num")!
    expect(pct).toHaveClass("text-rise")
    expect(pct).toHaveTextContent("▲")
    expect(within(line).getByText("損益")).toHaveClass("sr-only")
    const lossLine = phoneLineOf(list, loser.name)
    expect(lossLine).toHaveTextContent(`▼${pctText(loser.unrealized_pnl_pct)}`)
    expect(within(lossLine).getByText(pctText(loser.unrealized_pnl_pct)).closest(".num")).toHaveClass("text-fall")
    // 每一列的數字和桌面「損益」欄的第二行一樣
    expect(cellOf(table, "台積電", "損益")).toHaveTextContent(pctText(tsmc.unrealized_pnl_pct))
    expect(stored()).toMatchObject({ version: 2, state: { phoneLine: "pnl", columns: DEFAULT_COLUMNS } })
    expect(headerNames(table)).toEqual(desktopHeads)

    await user.click(pnlToggle())
    expect(dayToggle()).toBe(toggle)
    expect(phoneLineOf(list, "台積電")).toHaveTextContent(pctText(tsmc.day_change_pct))
    expect(stored()?.state.phoneLine).toBe("day")
  })

  it("沒有收盤價的持股：兩種都只有「—」", async () => {
    vi.spyOn(api, "getHoldings").mockResolvedValue(await holdingsWithUnpriced())
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderApp("/")
    const list = await phoneList()
    await within(list).findByRole("link", { name: "Apple" }, T)
    expect(within(phoneLineOf(list, "Apple")).getByTitle("沒有報價")).toBeInTheDocument()
    await user.click(dayToggle())
    const line = phoneLineOf(list, "Apple")
    expect(within(line).getByTitle("沒有報價")).toBeInTheDocument()
    expect(line).not.toHaveTextContent("%")
  })

  it("隱私模式：報酬率照常顯示（百分比不是金額），股數遮起來", async () => {
    const tsmc = (await api.getHoldings()).find((h) => h.code === "2330")!
    act(() => usePrefs.setState({ privacyMode: true }))
    act(() => useLedgerPrefs.setState({ phoneLine: "pnl" }))
    renderApp("/")
    const list = await phoneList()
    pnlToggle()
    expect(phoneLineOf(list, "台積電")).toHaveTextContent(`▲${pctText(tsmc.unrealized_pnl_pct)}`)
    const row = within(list).getByRole("link", { name: "台積電" }).closest("li")!
    expect(within(row).getAllByLabelText("已隱藏").length).toBeGreaterThan(0)
  })

  it("從瀏覽器讀回來：舊的設定（第 1、2 版）沒有這一項 → 今日漲跌，其他設定照舊；存了「損益」→ 一打開就是報酬率", async () => {
    const custom: HoldingColumn[] = ["price", "day_pct", "value"]
    localStorage.setItem("forliosa:ledger", JSON.stringify({ state: { columns: custom, showTrend: false, pinned: ["2317.TW"], showClosed: true }, version: 2 }))
    await act(() => useLedgerPrefs.persist.rehydrate())
    expect(useLedgerPrefs.getState()).toMatchObject({ phoneLine: "day", columns: custom, showTrend: false, pinned: ["2317.TW"], showClosed: true })

    localStorage.setItem("forliosa:ledger", JSON.stringify({ state: { columns: OLD_DEFAULT, showTrend: true, pinned: [], showClosed: false }, version: 1 }))
    await act(() => useLedgerPrefs.persist.rehydrate())
    expect(useLedgerPrefs.getState()).toMatchObject({ phoneLine: "day", columns: DEFAULT_COLUMNS })

    localStorage.setItem("forliosa:ledger", JSON.stringify({ state: { columns: DEFAULT_COLUMNS, showTrend: true, pinned: [], showClosed: false, phoneLine: "pnl" }, version: 2 }))
    await act(() => useLedgerPrefs.persist.rehydrate())
    expect(useLedgerPrefs.getState().phoneLine).toBe("pnl")
    renderApp("/")
    const tsmc = (await api.getHoldings()).find((h) => h.code === "2330")!
    const list = await phoneList()
    pnlToggle()
    expect(phoneLineOf(list, "台積電")).toHaveTextContent(pctText(tsmc.unrealized_pnl_pct))
  })

  it("存的值不認得（手改過）：當成今日漲跌，按一下換成報酬率", () => {
    act(() => useLedgerPrefs.setState({ phoneLine: "weird" as never }))
    act(() => useLedgerPrefs.getState().togglePhoneLine())
    expect(useLedgerPrefs.getState().phoneLine).toBe("pnl")
  })
})
