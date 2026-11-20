import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Quote } from "@/api/types"
import { limitTrack, quoteLimits } from "@/lib/limit-track"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import { LimitTrack } from "../LimitTrack"

// 走勢圖（lightweight-charts）在 jsdom 沒有 canvas 可以畫
vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => <div data-testid="price-chart" /> }))

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
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(() => usePrefs.setState({ privacyMode: false }))
})

const T = { timeout: 8000 }

/** 台積電 11/12：參考價 1,035、漲停 1,135、跌停 932，最低 1,015、最高 1,095，收 1,085 */
const TSMC = { close: 1085, reference: 1035, up: 1135, down: 932, low: 1015, high: 1095 }
const pos = (v: number) => (v - 932) / (1135 - 932)

describe("limitTrack：跌停在 0、漲停在 1", () => {
  it("一般的一天：收盤、參考價、當天的範圍照比例放", () => {
    const g = limitTrack(TSMC)!
    expect(g.close).toBeCloseTo(pos(1085))
    expect(g.reference).toBeCloseTo(pos(1035))
    // 參考價永遠在正中間附近（漲跌停是參考價的 ±10%，往內取到升降單位）
    expect(Math.abs(g.reference - 0.5)).toBeLessThan(0.02)
    expect(g.band).toEqual({ from: pos(1015), to: pos(1095) })
    expect(g.at).toBeNull()
  })

  it("收在漲停：點在右端，標記 up；範圍到右端", () => {
    const g = limitTrack({ ...TSMC, close: 1135, high: 1135 })!
    expect(g.close).toBe(1)
    expect(g.at).toBe("up")
    expect(g.band!.to).toBe(1)
  })

  it("收在跌停：點在左端，標記 down", () => {
    const g = limitTrack({ ...TSMC, close: 932, low: 932, high: 1040 })!
    expect(g.close).toBe(0)
    expect(g.at).toBe("down")
    expect(g.band!.from).toBe(0)
  })

  it("收盤等於參考價（平盤）：點和參考價的刻度在同一個位置，不是漲停也不是跌停", () => {
    const g = limitTrack({ ...TSMC, close: 1035, low: 1030, high: 1040 })!
    expect(g.close).toBe(g.reference)
    expect(g.at).toBeNull()
  })

  it("一字漲停（最低＝最高＝收盤＝漲停）：範圍是一個點，照樣畫", () => {
    const g = limitTrack({ ...TSMC, close: 1135, low: 1135, high: 1135 })!
    expect(g.band).toEqual({ from: 1, to: 1 })
    expect(g.at).toBe("up")
  })

  it("ETF 的 0.05 檔（浮點誤差）也算收在漲停", () => {
    // 0050 參考價 71.85 → 漲停 79.00（71.85 × 1.1 = 79.035，往下取到 0.05）
    const g = limitTrack({ close: 79.0, reference: 71.85, up: 79.0, down: 64.7 })!
    expect(g.at).toBe("up")
  })

  it("資料對不起來就不畫：漲停不高於跌停、參考價不在中間、收盤落在漲跌停外、缺值或 0", () => {
    expect(limitTrack({ ...TSMC, up: 932, down: 1135 })).toBeNull()
    expect(limitTrack({ ...TSMC, reference: 1200 })).toBeNull()
    expect(limitTrack({ ...TSMC, close: 1200 })).toBeNull()
    expect(limitTrack({ ...TSMC, close: 900 })).toBeNull()
    expect(limitTrack({ ...TSMC, reference: 0 })).toBeNull()
    expect(limitTrack({ ...TSMC, close: Number.NaN })).toBeNull()
  })

  it("最低、最高缺一個、或和收盤矛盾（最低比收盤高）：不畫範圍，其他照畫", () => {
    expect(limitTrack({ ...TSMC, low: null })!.band).toBeNull()
    expect(limitTrack({ ...TSMC, high: undefined })!.band).toBeNull()
    expect(limitTrack({ ...TSMC, low: 1090 })!.band).toBeNull()
    expect(limitTrack({ ...TSMC, low: 1100, high: 1090 })!.band).toBeNull()
  })
})

describe("quoteLimits：美股沒有漲跌停；後端說沒有就是沒有", () => {
  const quote = (o: Partial<Quote>): Quote => ({
    symbol: "2330.TW", price: 1085, prev_close: 1035, change: 50, change_pct: 0.0483, open: 1035, high: 1095, low: 1015, volume: 1,
    as_of: null, is_realtime: false, is_demo: false, source: "test", ...o,
  })
  it("美股：null（不管報價帶了什麼）", () => {
    expect(quoteLimits(quote({ symbol: "AAPL", limit_up: null, limit_down: null }), 266.1, "US", "stock")).toBeNull()
    expect(quoteLimits(quote({ symbol: "AAPL" }), 266.1, "US", "stock")).toBeNull()
  })
  it("後端有給：照後端的（除權息日的官方值，不是自己算的）", () => {
    expect(quoteLimits(quote({ reference_price: 425.5, limit_up: 468, limit_down: 383.5 }), 425.5, "TWSE", "stock")).toEqual({ up: 468, down: 383.5 })
  })
  it("後端給 null（國外成分 ETF、新上市前五日沒有漲跌停）：沒有軌道，不用參考價 ±10% 補", () => {
    expect(quoteLimits(quote({ reference_price: 26.55, limit_up: null, limit_down: null }), 26.55, "TPEX", "etf")).toBeNull()
  })
  it("舊版後端（報價沒有這兩個欄位）：用參考價 ±10% 算", () => {
    expect(quoteLimits(quote({}), 1035, "TWSE", "stock")).toEqual({ up: 1135, down: 932 })
  })
  it("還沒有報價：null", () => {
    expect(quoteLimits(undefined, null, "TWSE", "stock")).toBeNull()
  })
})

describe("LimitTrack：只有名詞與數字", () => {
  it("跌停、參考價、漲停三個標籤；收盤的點標「收 1,085」；範圍標「最低 1,015・最高 1,095」", () => {
    const { container } = render(<LimitTrack {...TSMC} market="TWSE" type="stock" />)
    const dl = container.querySelector("dl")!
    const pairs = [...dl.querySelectorAll("div")].map((d) => [d.querySelector("dt")!.textContent, d.querySelector("dd")!.textContent])
    expect(pairs).toEqual([
      ["跌停", "932"],
      ["參考價", "1,035"],
      ["漲停", "1,135"],
    ])
    expect(container.querySelector("[data-close-label]")!.textContent).toBe("收 1,085")
    expect(container.querySelector("[data-band-label]")!.textContent).toBe("最低 1,015・最高 1,095")
    // 沒有說明句：圖裡、標籤裡都沒有句號（螢幕閱讀器那一句除外）
    const visible = [...container.querySelectorAll("[data-close-label],[data-band-label],dl")].map((n) => n.textContent).join("")
    expect(visible).not.toMatch(/[。，]/)
    // 點與刻度的位置照比例；圖是 aria-hidden
    expect((container.querySelector("[data-close]") as HTMLElement).style.left).toBe(`${+(pos(1085) * 100).toFixed(3)}%`)
    expect(container.querySelector("[data-close]")!.closest("[aria-hidden]")).not.toBeNull()
  })

  it("顏色不代表意思：點、範圍、刻度都不用紅綠", () => {
    const { container } = render(<LimitTrack {...TSMC} close={1135} high={1135} market="TWSE" type="stock" />)
    for (const el of container.querySelectorAll("[data-close],[data-band],[data-ref-tick]")) {
      expect(el.className).not.toMatch(/rise|fall/)
    }
  })

  it("收在漲停：點在右端（標籤靠右，不超出），螢幕閱讀器念「漲停」", () => {
    const { container } = render(<LimitTrack {...TSMC} close={1135} high={1135} market="TWSE" type="stock" />)
    expect((container.querySelector("[data-close]") as HTMLElement).style.left).toBe("100%")
    const label = container.querySelector("[data-close-label]") as HTMLElement
    expect(label.style.left).toBe("100%")
    expect(label.style.transform).toBe("translateX(-100%)")
    expect(container.querySelector(".sr-only")!.textContent).toContain("收盤 1,135，漲停")
  })

  it("收在跌停：點在左端（標籤靠左），螢幕閱讀器念「跌停」", () => {
    const { container } = render(<LimitTrack {...TSMC} close={932} low={932} market="TWSE" type="stock" />)
    const label = container.querySelector("[data-close-label]") as HTMLElement
    expect(label.style.left).toBe("0%")
    expect(container.querySelector(".sr-only")!.textContent).toContain("收盤 932，跌停")
  })

  it("平盤：點就在參考價的刻度上", () => {
    const { container } = render(<LimitTrack {...TSMC} close={1035} low={1030} high={1040} market="TWSE" type="stock" />)
    expect((container.querySelector("[data-close]") as HTMLElement).style.left).toBe((container.querySelector("[data-ref-tick]") as HTMLElement).style.left)
  })

  it("沒有最低最高：不畫範圍也沒有範圍的標籤；最低＝最高時寫一個數字", () => {
    const none = render(<LimitTrack {...TSMC} low={null} high={null} market="TWSE" type="stock" />)
    expect(none.container.querySelector("[data-band]")).toBeNull()
    expect(none.container.querySelector("[data-band-label]")).toBeNull()
    none.unmount()
    const flat = render(<LimitTrack {...TSMC} close={1135} low={1135} high={1135} market="TWSE" type="stock" />)
    expect(flat.container.querySelector("[data-band-label]")!.textContent).toBe("最低＝最高 1,135")
  })

  it("ETF 照 ETF 的升降單位印（0.05 檔兩位小數）", () => {
    const { container } = render(<LimitTrack close={72.4} reference={71.85} up={79.0} down={64.7} low={71.6} high={72.6} market="TWSE" type="etf" />)
    expect([...container.querySelectorAll("dd")].map((d) => d.textContent)).toEqual(["64.70", "71.85", "79.00"])
    expect(container.querySelector("[data-close-label]")!.textContent).toBe("收 72.40")
  })

  it("資料對不起來：整個不畫", () => {
    const { container } = render(<LimitTrack {...TSMC} close={1300} market="TWSE" type="stock" />)
    expect(container.firstChild).toBeNull()
  })
})

function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}
const priceTray = async () => (await screen.findByRole("region", { name: "收盤價" }, T)) as HTMLElement

describe("個股頁的收盤價托盤", () => {
  it("台股：名稱與代號是 h1；收盤價托盤裡有漲跌停軌道（標題「漲跌停」）", async () => {
    renderApp("/stock/2330.TW")
    expect(await screen.findByRole("heading", { level: 1, name: "台積電 2330" }, T)).toBeInTheDocument()
    const tray = await priceTray()
    expect(await within(tray).findByRole("heading", { name: "漲跌停" }, T)).toBeInTheDocument()
    expect(tray.querySelector("[data-limit-track]")).not.toBeNull()
    // 價格那一行只有收盤價・日期與參考價；漲停、跌停的數字在軌道上，不在那一行再寫一次
    expect(tray.textContent).toContain("參考價 1,035")
    expect(tray.textContent).not.toContain("漲停 1,135・跌停 932")
  })

  it("美股：沒有漲跌停軌道，寫「昨收」", async () => {
    renderApp("/stock/AAPL")
    const tray = await priceTray()
    await within(tray).findByText(/昨收/, undefined, T)
    expect(tray.querySelector("[data-limit-track]")).toBeNull()
    expect(within(tray).queryByRole("heading", { name: "漲跌停" })).toBeNull()
  })

  it("後端說沒有漲跌停（null）的台股：沒有軌道，也不在價格那一行補一個 ±10%", async () => {
    const getQuote = api.getQuote
    vi.spyOn(api, "getQuote").mockImplementation(async (symbol) => {
      const q = await getQuote(symbol)
      return symbol === "2330.TW" ? { ...q, limit_up: null, limit_down: null } : q
    })
    renderApp("/stock/2330.TW")
    const tray = await priceTray()
    await within(tray).findByText(/參考價/, undefined, T)
    expect(tray.querySelector("[data-limit-track]")).toBeNull()
    expect(tray.textContent).not.toMatch(/漲停|跌停/)
  })

  it("收在漲停：價格旁標「漲停」，軌道的點在右端", async () => {
    const getQuote = api.getQuote
    vi.spyOn(api, "getQuote").mockImplementation(async (symbol) => {
      const q = await getQuote(symbol)
      return symbol === "2330.TW" ? { ...q, price: 1135, high: 1135, change: 100, change_pct: 100 / 1035 } : q
    })
    renderApp("/stock/2330.TW")
    const tray = await priceTray()
    expect(await within(tray).findByText("漲停", { selector: ".demo-tag" }, T)).toBeInTheDocument()
    await vi.waitFor(() => expect((tray.querySelector("[data-close]") as HTMLElement | null)?.style.left).toBe("100%"), T)
  })
})

describe("我的持有", () => {
  it("持有中：托盤標題「我的持有」，有「明細」", async () => {
    renderApp("/stock/2330.TW")
    const tray = await screen.findByRole("region", { name: "我的持有" }, T)
    expect(within(tray).getByRole("button", { name: "明細" })).toHaveAttribute("aria-expanded", "false")
    expect(within(tray).getByText("未實現")).toBeInTheDocument()
  })

  it("隱私模式：同一行標籤，股數、均價與金額遮掉、百分比照常；沒有說明句、沒有「明細」", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/stock/2330.TW")
    const tray = await screen.findByRole("region", { name: "我的持有" }, T)
    for (const label of ["持有", "均價", "未實現"]) expect(within(tray).getByText(label)).toBeInTheDocument()
    expect(within(tray).getAllByLabelText("已隱藏").length).toBeGreaterThanOrEqual(3)
    expect(tray.textContent).toMatch(/▲\d/)
    expect(tray.textContent).not.toMatch(/NT\$\d|1 張 500 股|692\.61|隱私模式開啟/)
    expect(within(tray).queryByRole("button", { name: "明細" })).toBeNull()
  })

  it("沒有持有、也沒有出清過：沒有「我的持有」托盤", async () => {
    renderApp("/stock/2308.TW")
    await priceTray()
    await screen.findByRole("heading", { level: 1, name: /台達電/ }, T)
    expect(screen.queryByRole("region", { name: /的持有$/ })).toBeNull()
  })
})
