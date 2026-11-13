import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { displayHost, fiscalYearEnd, formatCapital } from "@/lib/company"
import { AboutCompany } from "../AboutCompany"
import { RelatedStocks } from "../RelatedStocks"

// 測試不掛路由：頁尾「資料來源與授權」用的 PlainLink（不標 aria-current 的站內連結）也換成一般連結
vi.mock("@/app/links", () => ({
  PlainLink: ({ children, to, ...rest }: { children: React.ReactNode; to: string } & Record<string, unknown>) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}))
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to, params, ...rest }: { children: React.ReactNode; to: string; params?: { symbol: string } } & Record<string, unknown>) => (
    <a href={params ? to.replace("$symbol", params.symbol) : to} {...rest}>
      {children}
    </a>
  ),
}))

function withQueries(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

/** 個股頁的樣子：區塊在 SourcesProvider 裡，頁尾一個「資料來源與授權」（Link 已經 mock 成 <a>） */
function withSourcesFooter(ui: React.ReactNode) {
  return withQueries(
    <SourcesProvider>
      {ui}
      <SourcesFooter />
    </SourcesProvider>,
  )
}

describe("「關於」的格式", () => {
  it("實收資本額、網址、會計年度", () => {
    expect(formatCapital(259323700670)).toBe("2,593.24 億元")
    expect(formatCapital(96211690)).toBe("9,621 萬元")
    expect(displayHost("https://www.tccgroupholdings.com/tw/")).toBe("www.tccgroupholdings.com/tw")
    expect(fiscalYearEnd("09-26")).toBe("9 月 26 日")
  })
})

describe("總覽的「相關股票」", () => {
  it("一列 4 格：代號、名稱、收盤、漲跌（▲▼）與挑選理由，連到個股頁；不畫小走勢；基準不寫「持有本股」；來源在頁尾", async () => {
    const tsmc = await api.getInstrument("2330.TW")
    withSourcesFooter(<RelatedStocks inst={tsmc} />)
    const section = await screen.findByRole("region", { name: "相關股票" }, { timeout: 3000 })
    const items = within(section).getAllByRole("listitem")
    expect(items).toHaveLength(4)
    const first = within(items[0]!).getByRole("link")
    expect(first).toHaveAttribute("href", "/stock/0050.TW")
    expect(first.textContent).toContain("元大台灣50")
    expect(first.textContent).toContain("你的比較基準")
    expect(section.textContent).not.toContain("持有本股")
    expect(within(items[1]!).getByRole("link").textContent).toContain("台積電是其法人董事及大股東")
    expect(within(section).queryAllByRole("img")).toHaveLength(0) // 數字寫在格子裡，不畫裝飾性的小走勢
    expect(section.textContent).toMatch(/[▲▼]/)
    // 資料的說明（關係企業依哪個月的明細）留在格子下面；資料來源不在區塊裡
    expect(section.textContent).toContain("關係企業依董監事持股餘額明細")
    expect(section.textContent).not.toContain("資料來源")
    fireEvent.click(screen.getByRole("button", { name: /資料來源與授權/ }))
    expect(screen.getByText(/〈上市公司董事、監察人持股餘額明細資料〉/)).toBeInTheDocument()
  })
  it("少於 2 格就不顯示（美股）", async () => {
    const aapl = await api.getInstrument("AAPL")
    const { container } = withQueries(<RelatedStocks inst={aapl} />)
    await new Promise((r) => setTimeout(r, 600))
    expect(container.textContent).toBe("")
  })
})

describe("總覽的「關於〈公司〉」", () => {
  it("維基百科節錄（標「節錄」、條目與 CC BY-SA 4.0 連結）＋兩欄官方資料＋資料日期；來源在頁尾", async () => {
    const tsmc = await api.getInstrument("2330.TW")
    withSourcesFooter(<AboutCompany inst={tsmc} />)
    const section = await screen.findByRole("region", { name: "關於「台積電」" }, { timeout: 3000 })
    expect(within(section).getByText("節錄")).toBeInTheDocument()
    const article = within(section).getByRole("link", { name: /維基百科「台積電」條目/ })
    expect(article).toHaveAttribute("href", "https://zh.wikipedia.org/zh-tw/%E5%8F%B0%E7%A9%8D%E9%9B%BB")
    expect(within(section).getByRole("link", { name: /CC BY-SA 4.0/ })).toHaveAttribute("href", expect.stringContaining("creativecommons.org/licenses/by-sa/4.0"))
    const terms = within(section).getAllByRole("term").map((t) => t.textContent)
    expect(terms).toEqual(expect.arrayContaining(["產業別", "成立日期", "上市日期", "總部", "網站", "實收資本額", "董事長", "總經理", "簽證會計師事務所", "股務代理"]))
    expect(section.textContent).toContain("成立 39 年")
    expect(section.textContent).toContain("總裁: 魏哲家")
    expect(within(section).getByRole("link", { name: /www\.tsmc\.com/ })).toHaveAttribute("target", "_blank")
    expect(section.textContent).toContain("資料日期：2026/11/11")
    expect(section.textContent).not.toContain("資料來源")
    fireEvent.click(screen.getByRole("button", { name: /資料來源與授權/ }))
    expect(screen.getByText("臺灣證券交易所〈上市公司基本資料〉（2026）")).toBeInTheDocument()
  })
  it("沒有條目時是 AI 依公開資料整理的簡介（模型寫的字：紫色楷體）", async () => {
    const gw = await api.getInstrument("6488.TWO")
    withQueries(<AboutCompany inst={gw} />)
    const section = await screen.findByRole("region", { name: "關於「環球晶」" }, { timeout: 3000 })
    expect(within(section).getByText("AI 依公開資料整理")).toBeInTheDocument()
    expect(section.querySelector(".ai-voice")).not.toBeNull()
    expect(within(section).getAllByRole("term").map((t) => t.textContent)).toContain("上櫃日期")
  })
})
