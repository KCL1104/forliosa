import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { api } from "@/api"
import type { NavPoint } from "@/api/types"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { chartDays, formatNav, formatPremium, premiumParts, spanLabel } from "@/lib/etf-nav"
import { EtfNavSection } from "../EtfNavSection"

function withQueries(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const ATTRIBUTION = "金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（2026），依政府資料開放授權條款第 1 版"
/** 頁尾列出的名稱（授權另外分組） */
const SOURCE_NAME = "金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（2026）"

/** 個股頁的樣子：SourcesProvider 包住區塊，頁尾一個「資料來源與授權」（頁尾的連結需要 router） */
function withSourcesFooter(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree: createRootRoute({
      component: () => (
        <SourcesProvider>
          {ui}
          <SourcesFooter />
        </SourcesProvider>
      ),
    }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  })
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}
const TRACKING = "追蹤誤差不提供：標的指數的每日資料沒有開放授權。"

async function section(symbol: string) {
  const inst = await api.getInstrument(symbol)
  withQueries(<EtfNavSection inst={inst} />)
  return screen.findByRole("region", { name: "淨值與折溢價" }, { timeout: 3000 })
}

describe("折溢價的說法與淨值的位數", () => {
  it("溢價／折價／平價用文字分辨，不加正負號或 ▲▼", () => {
    expect(formatPremium(0.0042)).toBe("溢價 0.42%")
    expect(formatPremium(-0.0031)).toBe("折價 0.31%")
    expect(formatPremium(0.00002)).toBe("平價")
    expect(formatPremium(null)).toBe("—")
    expect(premiumParts(-0.012)).toEqual({ word: "折價", value: "1.20%" })
  })
  it("淨值照公布的位數（2–4 位小數）", () => {
    expect(formatNav(101.04)).toBe("101.04")
    expect(formatNav(26.4989)).toBe("26.4989")
    expect(formatNav(10.5)).toBe("10.50")
    expect(formatNav(1234.5)).toBe("1,234.50")
  })
})

describe("走勢的標題與缺口", () => {
  const pt = (t: string, premium_pct = 0.001): NavPoint => ({ t, nav: 100, close: 100.1, premium_pct })
  const points = [pt("2026-10-29"), pt("2026-10-30"), pt("2026-11-09"), pt("2026-11-10")]

  it("點數照實寫成「有資料的交易日」並附起訖日；有缺口時說出缺幾天", () => {
    expect(spanLabel(points, [])).toBe("4 個有資料的交易日（10/29–11/10）")
    const gap = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    expect(spanLabel(points, gap)).toBe("4 個有資料的交易日（10/29–11/10），中間 5 個交易日沒有資料")
  })

  it("缺的交易日放進圖的資料、值是 null，線在那裡斷開", () => {
    const days = chartDays(points, ["2026-11-02", "2026-11-03"])
    expect(days.map((d) => d.t)).toEqual(["2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-09", "2026-11-10"])
    expect(days.map((d) => d.premium_pct)).toEqual([0.001, 0.001, null, null, 0.001, 0.001])
    expect(days[2]!.point).toBeUndefined()
    expect(days[4]!.point).toEqual(points[2])
  })

  it("0050 存檔停了 5 天：標題與圖的說明都寫出缺口", async () => {
    const inst = await api.getInstrument("0050.TW")
    const overview = await api.getOverview("0050.TW")
    const nav = overview.etf_nav!
    const gap = nav.history.slice(20, 25).map((p) => p.t)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(["overview", "0050.TW"], {
      ...overview,
      etf_nav: { ...nav, history: nav.history.filter((p) => !gap.includes(p.t)), history_missing: gap },
    })
    render(<QueryClientProvider client={client}><EtfNavSection inst={inst} /></QueryClientProvider>)
    const s = await screen.findByRole("region", { name: "淨值與折溢價" })
    expect(within(s).getByText(/^55 個有資料的交易日（.+），中間 5 個交易日沒有資料$/)).toBeInTheDocument()
    expect(within(s).getByRole("img", { name: /^55 個有資料的交易日（.+），中間 5 個交易日沒有資料的折溢價：/ })).toBeInTheDocument()
    expect(within(s).getByText(/逐日數字（55 天）/)).toBeInTheDocument()
  })
})

describe("總覽的「淨值與折溢價」", () => {
  it("0050：同一天的淨值、收盤、折溢價；滿 20 天畫走勢；追蹤誤差說明；顯名聲明在頁尾；不用漲跌色", async () => {
    const inst = await api.getInstrument("0050.TW")
    withSourcesFooter(<EtfNavSection inst={inst} />)
    const s = await screen.findByRole("region", { name: "淨值與折溢價" }, { timeout: 3000 })
    const terms = within(s).getAllByRole("term").map((t) => t.textContent)
    expect(terms).toEqual(["淨值（11/12）", "收盤（11/12）", "折溢價（11/12）"])
    const values = within(s).getAllByRole("definition").map((d) => d.textContent)
    expect(values[1]).toBe("72.40")
    expect(values[2]).toMatch(/^(溢價|折價) \d\.\d\d%$|^平價$/)
    // 點數是有資料的交易日，附起訖日（不寫「近 60 個交易日」）
    expect(within(s).getByRole("img", { name: /^60 個有資料的交易日（\d+\/\d+–11\/12）的折溢價：/ })).toBeInTheDocument()
    expect(within(s).getByText(/^60 個有資料的交易日（\d+\/\d+–11\/12）$/)).toBeInTheDocument()
    expect(s.textContent).toContain(TRACKING)
    // 顯名聲明不在區塊裡寫成一段，登記到頁尾的「資料來源與授權」（依授權分組）
    expect(s.textContent).not.toContain(ATTRIBUTION)
    expect(s.textContent).not.toContain("資料來源")
    fireEvent.click(screen.getByRole("button", { name: /資料來源與授權/ }))
    expect(screen.getByText(SOURCE_NAME)).toBeInTheDocument()
    expect(screen.getAllByText("政府資料開放授權條款第 1 版").length).toBeGreaterThan(0)
    expect(s.textContent).not.toContain("資料累積中")
    expect(s.textContent).not.toMatch(/[▲▼]/)
    expect(s.innerHTML).not.toMatch(/text-(rise|fall)|--(rise|fall)/)
    expect(within(s).getByText(/逐日數字（60 天）/)).toBeInTheDocument()
  })

  it("00878：存檔不到 20 天，不畫走勢、照後端 notes 寫資料累積中", async () => {
    const s = await section("00878.TW")
    expect(s.textContent).toContain("資料累積中：淨值自 2026-11-03 起存檔")
    expect(within(s).queryByRole("img")).toBeNull()
    expect(within(s).getAllByRole("term").map((t) => t.textContent)).toContain("折溢價（11/12）")
  })

  it("00679B：淨值是前一個營業日的，兩個日期都寫出來，折溢價用同一天", async () => {
    const s = await section("00679B.TWO")
    const terms = within(s).getAllByRole("term").map((t) => t.textContent)
    expect(terms).toEqual(["淨值（11/11）", "收盤（11/12）", "折溢價（11/11）"])
    expect(s.textContent).toContain("最新的淨值是 11/11、收盤是 11/12；折溢價用兩者都有的 11/11 計算")
    expect(within(s).getAllByRole("definition")[0]!.textContent).toMatch(/^\d+\.\d{4}$/) // 四位小數照公布
  })

  it("資料集沒有的 ETF（例如期貨信託 ETF）：空狀態照後端 notes 說明，仍寫追蹤誤差", async () => {
    const inst = await api.getInstrument("0056.TW")
    const overview = await api.getOverview("0056.TW")
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    const note = "〈證券投資信託基金每日淨值〉沒有這檔 ETF 的淨值"
    client.setQueryData(["overview", "0056.TW"], {
      ...overview,
      etf_nav: { nav: null, nav_date: null, currency: null, fund_name: null, close: null, close_date: null, premium_pct: null,
                 premium_date: null, history: [], history_start: null, history_missing: [], notes: [note], sources: [] },
    })
    render(<QueryClientProvider client={client}><EtfNavSection inst={inst} /></QueryClientProvider>)
    const s = await screen.findByRole("region", { name: "淨值與折溢價" })
    expect(s.textContent).toContain(note)
    expect(s.textContent).toContain(TRACKING)
    expect(within(s).queryByRole("term")).toBeNull()
  })

  it("總覽的鍵值帶（band）：淨值與折溢價已在鍵值格，這裡只放走勢、說明與逐日數字", async () => {
    const inst = await api.getInstrument("0050.TW")
    withQueries(<EtfNavSection inst={inst} variant="band" />)
    const s = await screen.findByRole("region", { name: "折溢價走勢" }, { timeout: 3000 })
    expect(s.querySelector("#ov-premium")).not.toBeNull()
    expect(within(s).queryByRole("term")).toBeNull()
    expect(within(s).getByRole("img", { name: /的折溢價：/ })).toBeInTheDocument()
    expect(s.textContent).toContain(TRACKING)
    expect(within(s).getByText(/逐日數字（60 天）/)).toBeInTheDocument()
  })

  it("股票沒有這一塊", async () => {
    const inst = await api.getInstrument("2330.TW")
    const { container } = withQueries(<EtfNavSection inst={inst} />)
    await new Promise((r) => setTimeout(r, 600))
    expect(container.textContent).toBe("")
  })
})
