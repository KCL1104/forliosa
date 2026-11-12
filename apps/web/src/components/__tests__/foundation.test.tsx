import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { act, fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import { DayOfMonthPicker } from "@/components/day-picker"
import { ScrollRow } from "@/components/scroll-row"
import { RangeChips, Segmented } from "@/components/segmented"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { Button } from "@/components/ui/button"
import { useSourceNote } from "@/hooks/use-source-note"
import { dedupeSources, toSourceNote } from "@/lib/sources"

const TWSE_PRICE = "臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版"
const TWSE_VALUATION = "臺灣證券交易所〈上市個股日本益比、殖利率及股價淨值比〉（2026），依政府資料開放授權條款第 1 版"
const WIKI = "維基百科〈中文維基百科條目（開頭節錄）〉（2026），依 CC BY-SA 4.0 節錄（不改寫）"

/** 只有一個根路由的 router（SourcesFooter 的 Link 需要 router context） */
function renderInRouter(ui: React.ReactNode) {
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(<RouterProvider router={router as never} />)
}

describe("toSourceNote：後端的顯名聲明拆成名稱與授權（不改寫）", () => {
  it("「X〈Y〉（年），依 Z」", () => {
    expect(toSourceNote(TWSE_PRICE)).toEqual({ name: "臺灣證券交易所〈上市個股日成交資訊〉（2026）", licence: "政府資料開放授權條款第 1 版" })
    expect(toSourceNote(WIKI)).toEqual({ name: "維基百科〈中文維基百科條目（開頭節錄）〉（2026）", licence: "CC BY-SA 4.0 節錄（不改寫）" })
  })
  it("沒有「依」的結尾（SEC）與括號裡的授權", () => {
    expect(toSourceNote("美國證券交易委員會（SEC）〈EDGAR 公司申報清單（submissions）〉（2026），美國政府公開資料")).toEqual({
      name: "美國證券交易委員會（SEC）〈EDGAR 公司申報清單（submissions）〉（2026）",
      licence: "美國政府公開資料",
    })
    expect(toSourceNote("臺灣證券交易所 OpenAPI（政府資料開放授權條款第 1 版）")).toEqual({ name: "臺灣證券交易所 OpenAPI", licence: "政府資料開放授權條款第 1 版" })
  })
  it("認不出授權時整句是名稱；物件原樣通過", () => {
    expect(toSourceNote("AI 網路搜尋補充（只取搜尋結果的標題、媒體、時間與連結）")).toEqual({ name: "AI 網路搜尋補充（只取搜尋結果的標題、媒體、時間與連結）" })
    const n = { name: "GDELT", licence: "GDELT 使用條款", href: "https://www.gdeltproject.org/" }
    expect(toSourceNote(n)).toBe(n)
  })
  it("以名稱＋授權去重，保留先出現的順序，後來的連結補上", () => {
    const a = toSourceNote(TWSE_PRICE)
    const b = toSourceNote(TWSE_VALUATION)
    expect(dedupeSources([[a, b], [a, { ...a, href: "https://example.org" }], [{ name: a.name }]])).toEqual([{ ...a, href: "https://example.org" }, b, { name: a.name }])
  })
})

/** 一頁：三個區塊登記來源（其中兩個重複），一個可以拿掉 */
function Page() {
  const [chips, setChips] = useState(true)
  return (
    <SourcesProvider>
      <Section sources={[TWSE_PRICE]} />
      <Section sources={[TWSE_PRICE, TWSE_VALUATION]} />
      {chips && <Section sources={[WIKI]} />}
      <button type="button" onClick={() => setChips(false)}>
        拿掉簡介
      </button>
      <SourcesFooter />
    </SourcesProvider>
  )
}
function Section({ sources }: { sources: string[] }) {
  useSourceNote(sources)
  return null
}

describe("<SourcesFooter>：頁尾一次列出、去重、收合", () => {
  afterEach(() => localStorage.clear())
  it("收合的揭示按鈕；展開後依授權分組、去重，最後連到完整顯名聲明", async () => {
    renderInRouter(<Page />)
    const toggle = await screen.findByRole("button", { name: "資料來源與授權" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("臺灣證券交易所〈上市個股日成交資訊〉（2026）")).not.toBeVisible()
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(screen.getAllByText("臺灣證券交易所〈上市個股日成交資訊〉（2026）")).toHaveLength(1)
    expect(screen.getByText("臺灣證券交易所〈上市個股日本益比、殖利率及股價淨值比〉（2026）")).toBeVisible()
    // 同一個授權只寫一次
    expect(screen.getAllByText("政府資料開放授權條款第 1 版")).toHaveLength(1)
    expect(screen.getByText("CC BY-SA 4.0 節錄（不改寫）")).toBeVisible()
    expect(screen.getByRole("link", { name: "完整顯名聲明" })).toHaveAttribute("href", "/data-sources")
  })
  it("區塊卸載時它的來源也拿掉", async () => {
    renderInRouter(<Page />)
    fireEvent.click(await screen.findByRole("button", { name: "資料來源與授權" }))
    expect(screen.getByText("維基百科〈中文維基百科條目（開頭節錄）〉（2026）")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "拿掉簡介" }))
    expect(screen.queryByText("維基百科〈中文維基百科條目（開頭節錄）〉（2026）")).toBeNull()
  })
  it("沒有 provider 時 useSourceNote 不做事，頁尾只是一個連到聲明頁的連結", async () => {
    renderInRouter(
      <>
        <Section sources={[TWSE_PRICE]} />
        <SourcesFooter />
      </>,
    )
    expect(await screen.findByRole("link", { name: "資料來源與授權" })).toHaveAttribute("href", "/data-sources")
    expect(screen.queryByRole("button", { name: "資料來源與授權" })).toBeNull()
  })
})

describe("<ScrollRow>：只有被遮住的那一邊淡出", () => {
  // jsdom 沒有版面：用 data-sw／data-cw 假裝內容寬與可見寬
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", { configurable: true, get() { return Number((this as HTMLElement).dataset.sw ?? 0) } })
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get() { return Number((this as HTMLElement).dataset.cw ?? 0) } })
  })
  it("傳下 role 與 aria-label；開頭在最左邊時只有右邊淡出，捲到底只有左邊", () => {
    render(
      <ScrollRow role="tablist" aria-label="個股資料" data-sw="600" data-cw="300">
        <button type="button" role="tab" aria-selected="true">
          總覽
        </button>
      </ScrollRow>,
    )
    const row = screen.getByRole("tablist", { name: "個股資料" })
    expect(row).toHaveClass("scroll-row")
    expect(row).not.toHaveAttribute("data-overflow-start")
    expect(row).toHaveAttribute("data-overflow-end")
    act(() => {
      row.scrollLeft = 300
      fireEvent.scroll(row)
    })
    expect(row).toHaveAttribute("data-overflow-start")
    expect(row).not.toHaveAttribute("data-overflow-end")
  })
  it("放得下時兩邊都不淡出", () => {
    render(
      <ScrollRow aria-label="區間" data-sw="200" data-cw="300">
        <span>1月</span>
      </ScrollRow>,
    )
    const row = screen.getByLabelText("區間")
    expect(row).not.toHaveAttribute("data-overflow-start")
    expect(row).not.toHaveAttribute("data-overflow-end")
  })
})

describe("選取語法與簽名格按鈕", () => {
  it("分段、區間、日期格都用選取語法 (b)", () => {
    render(
      <>
        <Segmented label="帳本內容" value="a" onChange={() => {}} options={[{ value: "a", label: "持倉" }, { value: "b", label: "交易" }]} />
        <RangeChips label="區間" value="1M" onChange={() => {}} options={[{ value: "1M", label: "1月" }, { value: "6M", label: "6月" }]} />
        <DayOfMonthPicker value={[6]} onChange={() => {}} />
      </>,
    )
    expect(screen.getByRole("tab", { name: "持倉" })).toHaveClass("sel-chip")
    expect(screen.getByRole("radio", { name: "1月" })).toHaveClass("sel-chip")
    expect(screen.getByRole("radio", { name: "1月" })).toHaveAttribute("aria-checked", "true")
    expect(screen.getByRole("radiogroup", { name: "區間" })).toHaveClass("scroll-row")
    expect(screen.getByRole("button", { name: "6 日" })).toHaveClass("sel-chip")
  })
  it("sign：直角、墨色底、內縮細框、粗體", () => {
    render(<Button variant="sign">建立群組</Button>)
    const b = screen.getByRole("button", { name: "建立群組" })
    expect(b).toHaveClass("rounded-none", "bg-act", "text-act-fg", "font-bold", "after:inset-0.75", "after:opacity-40", "h-10", "px-5")
    expect(b).not.toHaveClass("rounded-sm")
  })
})
