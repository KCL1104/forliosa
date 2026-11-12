import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { api } from "@/api"
import { formatNav, formatPremium, premiumParts } from "@/lib/etf-nav"
import { EtfNavSection } from "../EtfNavSection"

function withQueries(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const ATTRIBUTION = "金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（2026），依政府資料開放授權條款第 1 版"
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

describe("總覽的「淨值與折溢價」", () => {
  it("0050：同一天的淨值、收盤、折溢價；滿 20 天畫走勢；追蹤誤差說明；顯名聲明；不用漲跌色", async () => {
    const s = await section("0050.TW")
    const terms = within(s).getAllByRole("term").map((t) => t.textContent)
    expect(terms).toEqual(["淨值（11/12）", "收盤（11/12）", "折溢價（11/12）"])
    const values = within(s).getAllByRole("definition").map((d) => d.textContent)
    expect(values[1]).toBe("72.40")
    expect(values[2]).toMatch(/^(溢價|折價) \d\.\d\d%$|^平價$/)
    expect(within(s).getByRole("img", { name: /近 60 個交易日的折溢價/ })).toBeInTheDocument()
    expect(s.textContent).toContain(TRACKING)
    expect(s.textContent).toContain(ATTRIBUTION)
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
      etf_nav: { nav: null, nav_date: null, currency: null, fund_name: null, close: 36.12, close_date: "2026-11-12", premium_pct: null,
                 premium_date: null, history: [], history_start: null, notes: [note], sources: [] },
    })
    render(<QueryClientProvider client={client}><EtfNavSection inst={inst} /></QueryClientProvider>)
    const s = await screen.findByRole("region", { name: "淨值與折溢價" })
    expect(s.textContent).toContain(note)
    expect(s.textContent).toContain(TRACKING)
    expect(within(s).queryByRole("term")).toBeNull()
  })

  it("股票沒有這一塊", async () => {
    const inst = await api.getInstrument("2330.TW")
    const { container } = withQueries(<EtfNavSection inst={inst} />)
    await new Promise((r) => setTimeout(r, 600))
    expect(container.textContent).toBe("")
  })
})
