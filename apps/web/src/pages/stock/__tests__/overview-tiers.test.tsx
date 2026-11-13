import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { monthTicks } from "../month-ticks"
import { OverviewTab } from "../tabs/OverviewTab"
import { TabLead } from "../tabs/kit"
import { labelsCollide, sourceNotes, valuationSpan, withFigures, withoutKind } from "../text"

/** 個股頁的樣子：區塊在 SourcesProvider 裡，頁尾一個「資料來源與授權」；Link 需要 router */
function renderPage(ui: React.ReactNode) {
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

const T = { timeout: 8000 }

// 整個總覽一次載入十幾個查詢：全部測試一起跑時比較慢，給長一點的時間
describe("總覽的三層", { timeout: 20_000 }, () => {
  afterEach(() => vi.restoreAllMocks())
  it("第一層：一條鍵值帶；估值位置只說一次，規則句是墨色 Noto Sans（不是紫色楷體），刻度尺不用 ▼△", async () => {
    const inst = await api.getInstrument("2330.TW")
    const position = await api.getPosition("2330.TW")
    renderPage(<OverviewTab inst={inst} position={position} />)
    const band = await screen.findByRole("region", { name: "關鍵數據" }, T)
    // 商用模式的本益比存檔從 6/1 才開始（示範序列每週一點，第一點是 6/5）：期間照實際寫，不說「5 年」，尺下放「資料累積中」
    const sentence = await within(band).findByText(/比 \d+\/\d+ 以來/, undefined, T)
    expect(sentence.closest(".ai-voice")).toBeNull()
    expect(sentence.className).toContain("text-ink")
    expect(band.textContent).not.toContain("5 年")
    expect(within(band).getByText(/^資料累積中/)).toBeInTheDocument()
    // 百分位只說一次（不在格子、刻度或別的句子重複）
    // 月營收與籌碼各自載入：兩個都出現了再檢查
    await within(band).findByText("10 月營收", undefined, T)
    await within(band).findByText("融資餘額", undefined, T)
    expect(band.textContent!.match(/\d+% 的日子/g)).toHaveLength(1)
    expect(band.textContent).not.toMatch(/[▼△▲]/)
    expect(band.querySelector(".ai-voice")).toBeNull()
    // 月營收、籌碼併進同一張鍵值格；連續成長併在年增那一格；報價下方已有的參考價、漲跌停不重複
    const terms = within(band).getAllByRole("term").map((t) => t.textContent)
    expect(terms).toEqual(expect.arrayContaining(["開盤", "股價淨值比", "10 月營收", "營收年增", "融資餘額", "千張大戶"]))
    expect(terms).not.toContain("本益比")
    expect(terms).not.toContain("參考價")
    expect(terms).not.toContain("漲停 / 跌停")
    expect(within(band).getByText(/^連 \d+ 個月$/)).toBeInTheDocument()
    // 每股金額有單位
    const value = (term: string) => within(band).getByText(term).nextElementSibling?.textContent
    expect(value("近四季 EPS")).toMatch(/^\d+(\.\d+)? 元$/)
    expect(value("最近現金股利")).toMatch(/^\d+(\.\d+)? 元$/)
    // 持有時：成本在尺上（隱私模式關閉）；尺是 aria-hidden，成本另外寫在句子裡給螢幕報讀器
    const cost = within(band).getAllByText(/^你的成本 \d+\.\d 倍/)
    expect(cost.some((n) => n.closest("[aria-hidden]"))).toBe(true)
    expect(cost.some((n) => n.className.includes("sr-only") && !n.closest("[aria-hidden]"))).toBe(true)
    expect(within(band).getByText(/^\d+\/\d+ 以來最低 \d+\.\d 倍、最高 \d+\.\d 倍。$/)).toHaveClass("sr-only")
  })

  it("第一層：本益比有值時，估值序列自己的 EPS 決定虧損與否（overview 沒有 EPS 也不會說成虧損）", async () => {
    const inst = await api.getInstrument("2330.TW")
    const real = await api.getOverview("2330.TW")
    vi.spyOn(api, "getOverview").mockResolvedValue({ ...real, eps_ttm: null })
    renderPage(<OverviewTab inst={inst} position={null} />)
    const band = await screen.findByRole("region", { name: "關鍵數據" }, T)
    await within(band).findByText(/比 \d+\/\d+ 以來/, undefined, T)
    expect(band.textContent).not.toContain("虧損")
  })

  it("第二層：接下來與公告合併成一張依日期排的表，第一欄是聯絡簿的日期格", async () => {
    const inst = await api.getInstrument("2330.TW")
    renderPage(<OverviewTab inst={inst} position={null} />)
    const events = await screen.findByRole("region", { name: "事件" }, T)
    const rows = await within(events).findAllByRole("listitem", undefined, T)
    expect(rows.length).toBeGreaterThan(3)
    const cells = rows.map((r) => r.querySelector(".date-cell"))
    expect(cells.every(Boolean)).toBe(true)
    expect(cells[0]!.querySelector(".weekday")?.textContent).toMatch(/^（.）$/)
    // 有官方公告（連到原文）也有接下來的事
    expect(events.textContent).toContain("重大訊息")
    expect(events.textContent).toMatch(/\d+ 天後/)
    // 依日期排：往下越來越晚（跨年的 1/8 在 12/11 之後）
    const order = rows.map((r) => r.textContent!.match(/天(前|後)/)?.[1] === "前")
    expect(order.indexOf(false)).toBeGreaterThan(0)
    expect(order.slice(order.indexOf(false)).every((past) => !past)).toBe(true)
    // 沒有另外的「接下來」「公告」兩個區塊
    expect(screen.queryByRole("region", { name: "接下來" })).toBeNull()
    expect(screen.queryByRole("region", { name: "公告" })).toBeNull()
    // 標題不重複類別欄：「除息｜每股 5 元」，不是「除息｜除息 每股 5 元」
    for (const r of rows) {
      const [kind, title] = [r.children[1]!.textContent!, r.children[2]!.firstChild!.textContent!]
      if (kind) expect(title.startsWith(kind)).toBe(false)
    }
  })

  it("第二層（美股）：SEC 申報也是官方公告，10-K 在事件表裡；空狀態不寫台股的「90 天」", async () => {
    const inst = await api.getInstrument("AAPL")
    renderPage(<OverviewTab inst={inst} position={null} />)
    const events = await screen.findByRole("region", { name: "事件" }, T)
    const rows = await within(events).findAllByRole("listitem", undefined, T)
    expect(rows.some((r) => r.textContent!.includes("10-K"))).toBe(true)
    expect(events.textContent).not.toContain("90 天")
    expect(events.textContent).not.toContain("目前沒有已公告")
    // 第一層：美股沒有行情時只剩近四季 EPS——不畫只有一格的鍵值格，也不在分頁列下面單獨留一條兩條線夾著的細帶：
    // 併進「關於」的鍵值格（排在會計年度結束後面、曾用名稱前面），數字還在、寫法一樣（US$）
    const about = await screen.findByRole("region", { name: "關於「Apple」" }, T)
    const eps = await within(about).findByText("近四季 EPS", undefined, T)
    expect(eps.tagName).toBe("DT")
    expect(eps.parentElement!.textContent).toMatch(/^近四季 EPSUS\$\d+\.\d\d$/)
    const terms = within(about).getAllByRole("term").map((t) => t.textContent)
    expect(terms.indexOf("近四季 EPS")).toBe(terms.indexOf("會計年度結束") + 1)
    expect(terms.indexOf("曾用名稱")).toBe(terms.indexOf("近四季 EPS") + 1)
    // 六格：兩欄排滿，沒有落單的一格
    expect(terms).toHaveLength(6)
    expect(screen.queryByRole("region", { name: "關鍵數據" })).toBeNull()
    expect(document.body.textContent!.match(/近四季 EPS/g)).toHaveLength(1)
  })

  it("第三層與頁尾：新聞先 3 則；各區塊不寫授權段落，整頁只有一個「資料來源與授權」", async () => {
    const inst = await api.getInstrument("2330.TW")
    renderPage(<OverviewTab inst={inst} position={null} />)
    const news = await screen.findByRole("region", { name: "新聞報導" }, T)
    await within(news).findAllByRole("link", undefined, T)
    expect(within(news).getAllByRole("link")).toHaveLength(3)
    expect(within(news).getByRole("button", { name: /看更多/ })).toBeInTheDocument()
    await screen.findByRole("region", { name: "相關股票" }, T)
    await screen.findByRole("region", { name: "關於「台積電」" }, T)
    expect(document.body.textContent).not.toContain("資料來源：")
    expect(document.body.textContent).not.toContain("依政府資料開放授權條款第 1 版")
    const footer = screen.getAllByRole("button", { name: /資料來源與授權/ })
    expect(footer).toHaveLength(1)
    fireEvent.click(footer[0]!)
    // 各區塊的來源是各自的查詢載入後才登記的（籌碼、月營收＋顯名聲明清單各自回來），每一筆都要等，不能假設已經到齊
    expect(await screen.findByText("臺灣證券交易所〈上市公司基本資料〉（2026）", undefined, T)).toBeInTheDocument()
    expect(await screen.findByRole("link", { name: /The GDELT Project/ }, T)).toHaveAttribute("href", "https://www.gdeltproject.org/")
    // 鍵值帶顯示的籌碼與月營收也要顯名：融資融券、集保股權分散、月營收（shioaji-data）
    await screen.findByText("臺灣集中保管結算所〈集保戶股權分散表〉（2026）", undefined, T)
    expect(await screen.findByText("臺灣證券交易所〈集中市場融資融券餘額〉（2026）", undefined, T)).toBeInTheDocument()
    expect(await screen.findByText(/^永豐金證券 shioaji-data.*〈公司基本資料、每日收盤與市值、月營收、季報〉（2026）$/, undefined, T)).toBeInTheDocument()
  })

  it("ETF：鍵值格只有 ETF 有的欄位（淨值、折溢價、殖利率…），沒有本益比、股價淨值比、EPS 這些「—」", async () => {
    const inst = await api.getInstrument("0050.TW")
    renderPage(<OverviewTab inst={inst} position={null} />)
    const band = await screen.findByRole("region", { name: "關鍵數據" }, T)
    await within(band).findByText("淨值（11/12）", undefined, T)
    const terms = within(band).getAllByRole("term").map((t) => t.textContent)
    // 折溢價那格比較長，排第三（手機上自己佔一列）
    expect(terms.slice(0, 3)).toEqual(["淨值（11/12）", "殖利率", "折溢價（11/12）"])
    expect(within(band).getByText("折溢價（11/12）").parentElement!.className).toContain("max-lg:col-span-2")
    for (const stockOnly of ["本益比", "股價淨值比", "近四季 EPS", "營收年增"]) expect(terms).not.toContain(stockOnly)
    expect(within(band).getAllByRole("definition").map((d) => d.textContent)).not.toContain("—")
    // 折溢價走勢接在格子下面（標題安靜，h3 接在鍵值帶的 h2 底下）
    expect(within(band).getByRole("region", { name: "折溢價走勢" })).toBeInTheDocument()
    expect(within(band).getByRole("heading", { level: 2, name: "關鍵數據" })).toBeInTheDocument()
  })

  it("ETF（00679B）：沒有值的欄位不列，一格「—」都沒有", async () => {
    const inst = await api.getInstrument("00679B.TWO")
    renderPage(<OverviewTab inst={inst} position={null} />)
    const band = await screen.findByRole("region", { name: "關鍵數據" }, T)
    await within(band).findAllByRole("definition", undefined, T)
    const values = within(band).getAllByRole("definition").map((d) => d.textContent)
    expect(values.length).toBeGreaterThan(3)
    expect(values).not.toContain("—")
    // 沒有殖利率時，手機上佔滿一列的折溢價不在淨值旁邊留空洞：它前面的格子是偶數個
    const cells = [...band.querySelectorAll("dl > div")]
    const wide = cells.findIndex((c) => c.className.includes("max-lg:col-span-2"))
    expect(wide).toBeGreaterThan(0)
    expect(wide % 2).toBe(0)
  })
})

describe("規則句與來源的小工具", () => {
  it("分頁第一行是墨色 Noto Sans，不是紫色楷體", () => {
    render(<TabLead>本益比 20.8 倍。</TabLead>)
    const p = screen.getByText("本益比 20.8 倍。")
    expect(p.className).not.toContain("ai-voice")
    expect(p.className).toContain("text-ink")
  })

  it("規則句（例如「為什麼」那一行）只把帶單位的數字標成 600（期間參數、門檻不算），文字不變", () => {
    const { container } = render(<p>{withFigures("成交量是近 20 日均量的 2.1 倍，漲 4.83%，超過 ±3%")}</p>)
    expect(container.textContent).toBe("成交量是近 20 日均量的 2.1 倍，漲 4.83%，超過 ±3%")
    expect([...container.querySelectorAll(".font-semibold")].map((n) => n.textContent)).toEqual(["2.1 倍", "4.83%"])
  })

  it("估值序列的期間：不滿 5 年寫實際起點（跨年寫年份），滿了才寫「過去 5 年」", () => {
    expect(valuationSpan([{ t: "2026-06-01" }], "2026-11-12")).toEqual({ label: "6/1 以來", full: false })
    expect(valuationSpan([{ t: "2025-06-02" }], "2026-11-12")).toEqual({ label: "2025/6/2 以來", full: false })
    expect(valuationSpan([{ t: "2021-11-15" }], "2026-11-12")).toEqual({ label: "過去 5 年", full: true })
  })

  it("刻度尺的標籤：照尺的寬度換算像素範圍判斷會不會疊在一起", () => {
    // 2317：現在在 54%、成本低於最低（在 0）。手機的尺約 353px，長標籤會撞到「現在」；桌面 1072px 不會
    const now = { pos: 0.54, text: "現在" }
    const cost = { pos: 0, text: "你的成本 10.1 倍，低於 6/1 以來最低" }
    expect(labelsCollide(now, cost, 353)).toBe(true)
    expect(labelsCollide(now, cost, 1072)).toBe(false)
    // 短標籤、兩點離得遠：不撞
    expect(labelsCollide({ pos: 0.9, text: "現在" }, { pos: 0.3, text: "你的成本 18.2 倍" }, 353)).toBe(false)
  })

  it("事件的標題不重複類別", () => {
    expect(withoutKind("除息 每股 5 元", "除息", "2026Q2 現金股利")).toEqual({ title: "每股 5 元", kind: "除息" })
    expect(withoutKind("2026Q3 法說會", "法說會", null)).toEqual({ title: "2026Q3", kind: "法說會" })
    expect(withoutKind("股利發放", "股利發放", "2026Q2 現金股利入帳")).toEqual({ title: "2026Q2 現金股利入帳", kind: "股利發放" })
    expect(withoutKind("股利發放", "股利發放", null)).toEqual({ title: "股利發放", kind: null })
    expect(withoutKind("10-K 年度報告", "年報", null)).toEqual({ title: "10-K 年度報告", kind: "年報" })
  })

  it("後端的顯名聲明 → 頁尾的來源：網址拆成連結，文字不改寫", () => {
    expect(sourceNotes(["The GDELT Project〈GDELT DOC 2.0 新聞索引〉（2026），依 GDELT 使用條款引用：https://www.gdeltproject.org/"])).toEqual([
      { name: "The GDELT Project〈GDELT DOC 2.0 新聞索引〉（2026）", licence: "GDELT 使用條款引用", href: "https://www.gdeltproject.org/" },
    ])
    expect(sourceNotes(["臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版"])).toEqual([
      { name: "臺灣證券交易所〈上市個股日成交資訊〉（2026）", licence: "政府資料開放授權條款第 1 版" },
    ])
    expect(sourceNotes(null)).toEqual([])
  })
})

describe("估值圖的月份刻度", () => {
  const weekly = (from: string, weeks: number) =>
    Array.from({ length: weeks }, (_, i) => new Date(Date.parse(`${from}T00:00:00Z`) + i * 7 * 86_400_000).toISOString().slice(0, 10))

  it("每個月第一個點一個刻度，不跳過某個月、不重複", () => {
    const { ticks, format } = monthTicks(weekly("2026-06-05", 24), 8)
    expect(ticks.map(format)).toEqual(["2026/06", "2026/07", "2026/08", "2026/09", "2026/10", "2026/11"])
  })

  it("放不下時每 3／6／12 個月一個，對齊日曆", () => {
    const five = weekly("2021-11-12", 261)
    const narrow = monthTicks(five, 4)
    expect(narrow.ticks.map(narrow.format)).toEqual(["2022", "2024", "2026"])
    const wide = monthTicks(five, 12)
    expect(wide.ticks.map(wide.format)).toEqual(["2022/01", "2022/07", "2023/01", "2023/07", "2024/01", "2024/07", "2025/01", "2025/07", "2026/01", "2026/07"])
    const labels = wide.ticks.map(wide.format)
    expect(new Set(labels).size).toBe(labels.length)
  })

  it("只有一個月的資料時用頭尾兩天", () => {
    const { ticks, format } = monthTicks(["2026-11-03", "2026-11-10", "2026-11-17"], 6)
    expect(ticks.map(format)).toEqual(["11/3", "11/17"])
  })
})
