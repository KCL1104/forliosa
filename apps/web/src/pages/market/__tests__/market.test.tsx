import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import { buildMarketOverview } from "@/api/mock/market-overview"
import type { ForliosaApi, MarketOverview } from "@/api/types"
import { DOCK_TABS, NAV_ITEMS } from "@/app/nav"
import { createAppRouter } from "@/router"
import { DISCLAIMER } from "@/lib/disclaimer"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 市場頁（`/market`）：指數、AI 收盤重點、類股、排行、美股、重大訊息；都是收盤後的資料，沒有的區塊不出現。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null, ownerId: null })
beforeEach(() => act(resetAi))
afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
  act(resetAi)
})

const T = { timeout: 6000 }

function mount(options: MockOptions = {}, overview?: (o: MarketOverview) => MarketOverview) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  if (overview) vi.spyOn(api, "getMarketOverview").mockImplementation(async () => overview(buildMarketOverview(false)))
  return adapter
}

function renderApp(path = "/market") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe("導覽", () => {
  it("頂部列與手機底部列都是「帳本・市場・群組・討論」", () => {
    expect(NAV_ITEMS.map((n) => n.label)).toEqual(["帳本", "市場", "群組", "討論"])
    expect(DOCK_TABS.map((n) => n.label)).toEqual(["帳本", "市場", "群組", "討論"])
    const market = NAV_ITEMS.find((n) => n.to === "/market")!
    expect(market.match("/market")).toBe(true)
    expect(market.match("/")).toBe(false)
  })

  it("在市場頁時導覽標示「市場」，分頁標題是「市場｜Forliosa」", async () => {
    mount()
    renderApp()
    expect(await screen.findByRole("heading", { level: 1, name: "市場" }, T)).toBeInTheDocument()
    const navs = screen.getAllByRole("navigation", { name: "主要" })
    for (const nav of navs) expect(within(nav).getByRole("link", { name: "市場" })).toHaveAttribute("aria-current", "page")
    expect(document.title).toBe("市場｜Forliosa")
  })
})

describe("市場頁的內容", () => {
  it("指數帶自己的日期與漲跌；沒有期貨授權時沒有台指期", async () => {
    mount()
    renderApp()
    const list = await screen.findByRole("list", { name: "指數與匯率" }, T)
    const items = within(list).getAllByRole("listitem")
    expect(items.map((li) => li.querySelector("p")!.textContent)).toEqual(["加權指數", "櫃買指數", "美元兌新台幣"])
    expect(items[0]).toHaveTextContent("27,270.34")
    expect(items[0]).toHaveTextContent("318.55")
    expect(items[0]).toHaveTextContent("1.18%")
    expect(items[0]).toHaveTextContent("11/12")
    expect(items[2]).toHaveTextContent("31.437")
    // 標題旁寫資料日期，不是「即時」
    expect(screen.getByText("11/12 收盤")).toBeInTheDocument()
    expect(screen.queryByText(/即時/)).toBeNull()
  })

  it("AI 收盤重點是鉛筆字（.ai-voice），每一點列出依據的報導並連到原文", async () => {
    mount()
    renderApp()
    const section = (await screen.findByRole("heading", { name: "收盤重點" }, T)).closest("section")!
    expect(within(section).getByText(/AI 整理/)).toBeInTheDocument()
    const voices = section.querySelectorAll(".ai-voice")
    expect(voices).toHaveLength(5) // 一句標題＋四點
    expect(voices[0]).toHaveTextContent("加權指數收漲 1.18%，半導體類股領漲")
    const links = within(section).getAllByRole("link")
    expect(links.length).toBeGreaterThanOrEqual(4)
    for (const a of links) {
      expect(a).toHaveAttribute("target", "_blank")
      expect(a).toHaveAttribute("rel", "noopener noreferrer")
    }
    expect(within(section).getByText(DISCLAIMER.ai)).toHaveAttribute("data-disclaimer", "ai")
  })

  it("沒有 AI 整理時整塊不出現，其他區塊照常", async () => {
    mount({}, (o) => ({ ...o, summary: null }))
    renderApp()
    expect(await screen.findByRole("heading", { name: "類股" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "收盤重點" })).toBeNull()
    expect(document.querySelector(".ai-voice")).toBeNull()
  })

  it("類股由高到低（32 類：沒有電子工業合計與 4 個舊的綜合類）；只放得下一欄時先列頭尾各 5 個，按了才列出全部", async () => {
    mount()
    renderApp()
    const section = (await screen.findByRole("heading", { name: "類股" }, T)).closest("section")!
    // 托盤的 meta：日期與上漲、下跌的類股數（照清單算）
    expect(within(section).getByText("11/12・上漲 16・下跌 16")).toBeInTheDocument()
    // 量不到寬度（測試環境）＝一欄：漲最多與跌最多的各 5 個
    const head = within(section).getAllByRole("listitem")
    expect(head).toHaveLength(10)
    expect(head[0]).toHaveTextContent("半導體")
    expect(head[0]).toHaveTextContent("3.12%")
    expect(head.at(-1)).toHaveTextContent("玻璃陶瓷")
    const toggle = within(section).getByRole("button", { name: "全部 32 個類股" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(toggle)
    expect(within(section).getByRole("button", { name: "只看漲跌最多的" })).toHaveAttribute("aria-expanded", "true")
    const rows = within(section).getAllByRole("listitem")
    expect(rows).toHaveLength(32)
    expect(rows[0]).toHaveTextContent("半導體")
    expect(rows.at(-1)).toHaveTextContent("玻璃陶瓷")
    for (const name of ["電子工業", "機電", "塑膠化工", "水泥窯製", "化學生技醫療"]) expect(within(section).queryByText(name)).toBeNull()
  })

  it("排行三張表：每一列連到個股頁；成交量以張為單位", async () => {
    mount()
    renderApp()
    const section = (await screen.findByRole("heading", { name: "排行" }, T)).closest("section")!
    expect(within(section).getByText(/檔普通股，不含 ETF/)).toBeInTheDocument()
    const lists = within(section).getAllByRole("list")
    expect(lists).toHaveLength(3)
    const gainers = within(lists[0]!).getAllByRole("link")
    expect(gainers[0]).toHaveAttribute("href", "/stock/2330.TW")
    expect(gainers[0]).toHaveTextContent("台積電")
    expect(gainers[0]).toHaveTextContent("1,085")
    expect(gainers[0]).toHaveTextContent("4.83%")
    const losers = within(lists[1]!).getAllByRole("link")
    expect(losers[0]).toHaveTextContent("環球晶")
    const volume = within(lists[2]!).getAllByRole("link")
    expect(volume[0]).toHaveTextContent("張")
    // ETF 不在排行裡
    expect(within(section).queryByText("元大台灣50")).toBeNull()
    // 窄畫面的選項
    const chips = within(section).getByRole("radiogroup", { name: "排行的種類" })
    expect(within(chips).getByRole("radio", { name: "漲幅" })).toHaveAttribute("aria-checked", "true")
    fireEvent.click(within(chips).getByRole("radio", { name: "成交量" }))
    expect(within(chips).getByRole("radio", { name: "成交量" })).toHaveAttribute("aria-checked", "true")
  })

  it("重大訊息先列 6 則，按了再看其餘；每一列連到那一檔的事件分頁", async () => {
    mount()
    renderApp()
    const section = (await screen.findByRole("heading", { name: "重大訊息" }, T)).closest("section")!
    expect(within(section).getByText(/共 428 則$/)).toBeInTheDocument()
    // 交易日：只有那一天，每一列只有時間、沒有日期
    expect(within(section).getAllByRole("link")[0]?.textContent).toMatch(/^\d{2}:\d{2}/)
    expect(within(section).getAllByRole("link")).toHaveLength(6)
    expect(within(section).getAllByRole("link")[0]).toHaveAttribute("href", "/stock/2330.TW?tab=events")
    fireEvent.click(within(section).getByRole("button", { name: "再看 6 則" }))
    expect(within(section).getAllByRole("link")).toHaveLength(12)
    expect(within(section).getByRole("button", { name: "收起來" })).toBeInTheDocument()
  })

  it("週末：重大訊息往前一起列到最後一個交易日，標題寫期間、每一列多一行日期（產品負責人 2026-11-15）", async () => {
    mount({}, (o) => ({
      ...o,
      announcements: {
        date: "2026-11-14", start_date: "2026-11-13", total: 3,
        items: [
          { symbol: "6488.TWO", code: "6488", name: "環球晶", title: "週六的公告", date: "2026-11-14", time: "07:00", url: null },
          { symbol: "2330.TW", code: "2330", name: "台積電", title: "週五傍晚的公告", date: "2026-11-13", time: "17:30", url: null },
          { symbol: "2317.TW", code: "2317", name: "鴻海", title: "週五早上的公告", date: "2026-11-13", time: "09:20", url: null },
        ],
      },
    }))
    renderApp()
    const section = (await screen.findByRole("heading", { name: "重大訊息" }, T)).closest("section")!
    expect(within(section).getByText("11/13–11/14・共 3 則")).toBeInTheDocument()
    const links = within(section).getAllByRole("link")
    expect(links.map((l) => l.textContent)).toEqual([
      expect.stringMatching(/^11\/1407:00環球晶/),
      expect.stringMatching(/^11\/1317:30台積電/),
      expect.stringMatching(/^11\/1309:20鴻海/),
    ])
  })

  it("什麼資料都沒有：只有一個空狀態", async () => {
    mount({}, () => ({ as_of: null, indices: [], summary: null, sectors: null, movers: null, announcements: null, is_demo: false, notes: ["還沒有資料"], sources: [] }))
    renderApp()
    expect(await screen.findByText("還沒有資料", {}, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "排行" })).toBeNull()
    expect(screen.queryByText(/收盤$/)).toBeNull()
  })

  it("示範資料（個人模式）標示「示範資料」，並有台指期", async () => {
    mount({ policy: "personal" })
    renderApp()
    const list = await screen.findByRole("list", { name: "指數與匯率" }, T)
    expect(within(list).getAllByRole("listitem")).toHaveLength(4)
    expect(within(list).getByText("台指期近月")).toBeInTheDocument()
    expect(screen.getAllByText("示範資料").length).toBeGreaterThan(0)
  })

  it("載入失敗：錯誤狀態與重新載入", async () => {
    mount()
    vi.spyOn(api, "getMarketOverview").mockRejectedValue(new Error("boom"))
    renderApp()
    expect(await screen.findByRole("alert", {}, T)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新載入" })).toBeInTheDocument()
  })
})

describe("美股（產品負責人 2026-11-15）", () => {
  it("示範資料：SPY、DIA、ONEQ 是台北日期之前最後一個美股交易日（紐約）的收盤，20 個點的小圖；5 則 GDELT 新聞；頁尾有 Databento 與 GDELT", () => {
    const o = buildMarketOverview(false)
    expect(o.us?.date).toBe("2026-11-11")
    expect(o.us?.items.map((i) => [i.symbol, i.tracks, i.unit, i.date])).toEqual([
      ["SPY", "S&P 500", "美元", "2026-11-11"],
      ["DIA", "道瓊工業指數", "美元", "2026-11-11"],
      ["ONEQ", "那斯達克綜合指數", "美元", "2026-11-11"],
    ])
    for (const i of o.us!.items) {
      expect(i.sparkline).toHaveLength(20)
      expect(i.sparkline.at(-1)).toEqual({ t: i.date, v: i.value })
      expect(i.sparkline.at(-2)!.v).toBeCloseTo(i.value! - i.change!, 2)
    }
    expect(o.us!.news).toHaveLength(5)
    for (const n of o.us!.news) {
      expect(n).toMatchObject({ category: "media", source: "GDELT" })
      expect(n.url).toMatch(/^https:\/\/example\.com\//)
      expect(Date.parse(n.published_at)).toBeLessThan(Date.parse("2026-11-12T13:30:00+08:00"))
    }
    expect(o.sources).toContain("Databento〈US Equities Summary（EQUS.SUMMARY，Nasdaq NLS Plus 官方合併收盤）〉（2026），資料由 Databento 提供")
    expect(o.sources.some((s) => s.startsWith("The GDELT Project"))).toBe(true)
    // 週一（台北）看到的是上週五（紐約）的收盤
    expect(buildMarketOverview(false, "2026-11-16").us?.date).toBe("2026-11-13")
  })

  it("在排行之後、重大訊息之前；標題旁寫紐約的日期「11/11 收盤（美東）」，不寫「今日」", async () => {
    mount()
    renderApp()
    const section = (await screen.findByRole("heading", { name: "美股" }, T)).closest("section")!
    const order = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)
    expect(order.indexOf("美股")).toBe(order.indexOf("排行") + 1)
    expect(order.indexOf("重大訊息")).toBe(order.indexOf("美股") + 1)
    expect(within(section).getByText("11/11 收盤（美東）")).toBeInTheDocument()
    expect(section).not.toHaveTextContent(/今日|即時/)
  })

  it("三檔 ETF：代號、追蹤哪個指數（不寫成指數本身）、US$ 收盤價、▲▼ 漲跌與幅度；每一列連到個股頁", async () => {
    mount()
    renderApp()
    const list = await screen.findByRole("list", { name: "美股 ETF" }, T)
    const links = within(list).getAllByRole("link")
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/stock/SPY", "/stock/DIA", "/stock/ONEQ"])
    const [spy, dia, oneq] = links as [HTMLElement, HTMLElement, HTMLElement]
    expect(spy).toHaveTextContent("SPY")
    expect(spy).toHaveTextContent("SPDR S&P 500 ETF Trust")
    expect(spy).toHaveTextContent("追蹤 S&P 500")
    expect(spy).toHaveTextContent("US$683.41")
    expect(spy).toHaveTextContent("▲4.12")
    expect(spy).toHaveTextContent("0.61%")
    expect(spy).toHaveTextContent("上漲")
    expect(dia).toHaveTextContent("追蹤道瓊工業指數")
    expect(dia).toHaveTextContent("US$471.86")
    expect(dia).toHaveTextContent("▼1.37")
    expect(dia).toHaveTextContent("下跌")
    expect(oneq).toHaveTextContent("追蹤那斯達克綜合指數")
    expect(oneq).toHaveTextContent("US$87.94")
    // 走勢小圖每一檔兩張（窄與寬各一），只給眼睛看
    expect(spy.querySelectorAll("svg")).toHaveLength(2)
    for (const svg of spy.querySelectorAll("svg")) expect(svg.closest("[aria-hidden]")).not.toBeNull()
    // 日期都一樣時每一格不再寫日期
    expect(within(list).queryByText(/收盤（美東）/)).toBeNull()
  })

  it("美股新聞：媒體・相對時間，標題連到原文、另開新視窗", async () => {
    mount()
    renderApp()
    const list = await screen.findByRole("list", { name: "新聞" }, T)
    const rows = within(list).getAllByRole("listitem")
    expect(rows).toHaveLength(5)
    expect(rows[0]).toHaveTextContent("Demo Wire・7 小時前")
    const links = within(list).getAllByRole("link")
    expect(links[0]).toHaveTextContent("Wall Street closes mixed as tech gains offset industrials (sample)")
    expect(links[0]).toHaveAttribute("href", "https://example.com/demo-news/us-market-1")
    for (const a of links) {
      expect(a).toHaveAttribute("target", "_blank")
      expect(a).toHaveAttribute("rel", "noopener noreferrer")
    }
  })

  it("頁尾的資料來源列出 Databento 與 GDELT", async () => {
    mount()
    renderApp()
    await screen.findByRole("heading", { name: "美股" }, T)
    fireEvent.click(screen.getByRole("button", { name: "資料來源與授權" }))
    expect(screen.getByText("Databento〈US Equities Summary（EQUS.SUMMARY，Nasdaq NLS Plus 官方合併收盤）〉（2026）")).toBeInTheDocument()
    expect(screen.getByText(/^The GDELT Project〈GDELT DOC 2\.0 新聞索引〉/)).toBeInTheDocument()
  })

  it("某一檔的收盤日期和其他檔不同：那一格自己寫日期", async () => {
    mount({}, (o) => ({ ...o, us: { ...o.us!, items: o.us!.items.map((i) => (i.symbol === "ONEQ" ? { ...i, date: "2026-11-10" } : i)) } }))
    renderApp()
    const list = await screen.findByRole("list", { name: "美股 ETF" }, T)
    const links = within(list).getAllByRole("link")
    expect(links[2]).toHaveTextContent("11/10 收盤（美東）")
    expect(links[0]).not.toHaveTextContent("收盤（美東）")
  })

  it("沒有收盤價只有新聞：只列新聞，標題旁不寫日期", async () => {
    mount({}, (o) => ({ ...o, us: { date: null, items: [], news: o.us!.news } }))
    renderApp()
    const section = (await screen.findByRole("heading", { name: "美股" }, T)).closest("section")!
    expect(within(section).queryByRole("list", { name: "美股 ETF" })).toBeNull()
    expect(within(section).queryByText(/收盤（美東）/)).toBeNull()
    expect(within(within(section).getByRole("list", { name: "美股新聞" })).getAllByRole("link")).toHaveLength(5)
  })

  it("有收盤價沒有新聞：只列三檔 ETF", async () => {
    mount({}, (o) => ({ ...o, us: { ...o.us!, news: [] } }))
    renderApp()
    const section = (await screen.findByRole("heading", { name: "美股" }, T)).closest("section")!
    expect(within(section).getAllByRole("link")).toHaveLength(3)
    expect(within(section).queryByRole("heading", { name: "新聞" })).toBeNull()
  })

  it("沒有美股（null，或舊版後端沒有這個欄位）：整塊不出現，其他區塊照常", async () => {
    mount({}, (o) => ({ ...o, us: null }))
    renderApp()
    expect(await screen.findByRole("heading", { name: "排行" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "美股" })).toBeNull()
    cleanup()
    mount({}, ({ us: _us, ...o }) => o)
    renderApp()
    expect(await screen.findByRole("heading", { name: "排行" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "美股" })).toBeNull()
    expect(screen.queryByText(/收盤（美東）/)).toBeNull()
  })

  it("台股都沒有、只有美股：不是空狀態，列出美股", async () => {
    mount({}, (o) => ({ as_of: null, indices: [], summary: null, sectors: null, movers: null, announcements: null, us: o.us, is_demo: false, notes: [], sources: o.sources }))
    renderApp()
    expect(await screen.findByRole("heading", { name: "美股" }, T)).toBeInTheDocument()
    expect(screen.queryByText("還沒有資料")).toBeNull()
  })
})

describe("托盤（產品負責人 2026-11-21：方向 C 的結構，頁面只有標籤和數字）", () => {
  const sectors = (values: [string, number][]) => ({ date: "2026-11-12", items: values.map(([name, change_pct]) => ({ name, index_name: `${name}類指數`, close: 100, change_pct })) })

  it("每一塊是一盤；底色照出現的順序輪流 1→2→3，相鄰的兩盤不同色", async () => {
    mount()
    renderApp()
    await screen.findByRole("heading", { name: "重大訊息" }, T)
    const trays = Array.from(document.querySelectorAll<HTMLElement>("section.tray"))
    expect(trays.map((t) => t.querySelector("h2")!.textContent)).toEqual(["指數與匯率", "收盤重點", "類股", "排行", "美股", "重大訊息"])
    expect(trays.map((t) => t.dataset.tint)).toEqual(["1", "2", "3", "1", "2", "3"])
  })

  it("沒有收盤重點：類股接在指數後面，底色照樣輪流（類股是 2）", async () => {
    mount({}, (o) => ({ ...o, summary: null }))
    renderApp()
    await screen.findByRole("heading", { name: "重大訊息" }, T)
    const trays = Array.from(document.querySelectorAll<HTMLElement>("section.tray"))
    expect(trays.map((t) => [t.querySelector("h2")!.textContent, t.dataset.tint])).toEqual([
      ["指數與匯率", "1"], ["類股", "2"], ["排行", "3"], ["美股", "1"], ["重大訊息", "2"],
    ])
  })

  it("頁面沒有說明句：沒有頁首的一句話、沒有「以 0 為中線」「由漲到跌」這類說明", async () => {
    mount()
    renderApp()
    await screen.findByRole("heading", { name: "重大訊息" }, T)
    const main = document.getElementById("main")!
    expect(main).not.toHaveTextContent(/以 0 為中線|由漲到跌|由高到低|個類股有|收漲 ▲/)
  })

  it("類股全部上漲、全部下跌、有持平：meta 照清單算（下跌 0 也寫），持平的有才寫", async () => {
    mount({}, (o) => ({ ...o, sectors: sectors([["半導體", 0.02], ["航運", 0.01], ["食品", 0.001]]) }))
    renderApp()
    let section = (await screen.findByRole("heading", { name: "類股" }, T)).closest("section")!
    expect(within(section).getByText("11/12・上漲 3・下跌 0")).toBeInTheDocument()
    expect(section.querySelectorAll('[data-bar="down"]')).toHaveLength(0)
    cleanup()
    mount({}, (o) => ({ ...o, sectors: sectors([["半導體", -0.001], ["航運", -0.01], ["食品", 0]]) }))
    renderApp()
    section = (await screen.findByRole("heading", { name: "類股" }, T)).closest("section")!
    expect(within(section).getByText("11/12・上漲 0・下跌 2・持平 1")).toBeInTheDocument()
    expect(section.querySelectorAll('[data-bar="up"]')).toHaveLength(0)
    // 11 個以下不收合
    expect(within(section).queryByRole("button", { name: /全部/ })).toBeNull()
  })

  it("類股的名稱很長也不截斷", async () => {
    const long = "其他電子與資訊服務與數位雲端合計"
    mount({}, (o) => ({ ...o, sectors: sectors([[long, 0.01], ["航運", -0.01]]) }))
    renderApp()
    const section = (await screen.findByRole("heading", { name: "類股" }, T)).closest("section")!
    const name = within(section).getByText(long)
    expect(name.className).not.toMatch(/truncate/)
  })

  it("托盤夠寬時分欄（最多三欄），每欄一張中線橫條、共用同一個比例", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 1000, height: 0, top: 0, left: 0, right: 1000, bottom: 0, x: 0, y: 0, toJSON: () => ({}) })
    mount()
    renderApp()
    const section = (await screen.findByRole("heading", { name: "類股" }, T)).closest("section")!
    const lists = within(section).getAllByRole("list")
    expect(lists.map((l) => within(l).getAllByRole("listitem").length)).toEqual([11, 11, 10])
    expect(within(section).queryByRole("button", { name: /全部/ })).toBeNull()
    // 第一欄的半導體（▲3.12%，最大）佔滿半邊；第三欄的玻璃陶瓷（▼1.87%）照同一個比例，不是佔滿
    const bar = (l: HTMLElement, n: number) => within(l).getAllByRole("listitem")[n]!.querySelector<HTMLElement>("[data-bar]")!.style.getPropertyValue("--bar")
    expect(bar(lists[0]!, 0)).toBe("50%")
    expect(parseFloat(bar(lists[2]!, 9))).toBeCloseTo((0.0187 / 0.0312) * 50, 2)
  })

  it("排行的表名寫實際的列數：跌幅只有 6 檔是「跌幅前 6」；一檔都沒有時只寫種類和「沒有下跌的股票」", async () => {
    mount()
    renderApp()
    let section = (await screen.findByRole("heading", { name: "排行" }, T)).closest("section")!
    const lists = within(section).getAllByRole("list")
    expect(lists.map((l) => l.getAttribute("aria-labelledby")).map((id) => document.getElementById(id!)!.textContent)).toEqual(["漲幅前 10", "跌幅前 6", "成交量前 10"])
    expect(within(lists[1]!).getAllByRole("link")).toHaveLength(6)
    // 範圍寫在托盤的 meta，不是遠處的註腳
    expect(section.querySelector("header")).toHaveTextContent("11/12・16 檔普通股，不含 ETF")
    cleanup()
    mount({}, (o) => ({ ...o, movers: { ...o.movers!, losers: [] } }))
    renderApp()
    section = (await screen.findByRole("heading", { name: "排行" }, T)).closest("section")!
    expect(document.getElementById("market-movers-losers")).toHaveTextContent(/^跌幅$/)
    expect(within(section).getByText("沒有下跌的股票")).toBeInTheDocument()
    expect(within(section).queryByText(/跌幅前/)).toBeNull()
  })

  it("美股的日期寫在托盤的 meta（紐約的日期）", async () => {
    mount()
    renderApp()
    const section = (await screen.findByRole("heading", { name: "美股" }, T)).closest("section")!
    expect(section.querySelector("header")).toHaveTextContent("11/11 收盤（美東）")
  })
})

describe("查看別人的資產時", () => {
  it("市場頁照常可看（沒有個人資料），mock 也不擋", async () => {
    const adapter = mount()
    const o = await adapter.getMarketOverview()
    expect(o.indices.length).toBeGreaterThan(0)
  })
})
