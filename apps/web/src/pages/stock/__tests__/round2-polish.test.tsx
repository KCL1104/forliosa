import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { api } from "@/api"
import { KeyGrid, NotYet, type KeyItem } from "../tabs/kit"
import { ValuationTab } from "../tabs/ValuationTab"
import { marketLine } from "../text"

function withQueries(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const T = { timeout: 8000 }
const items = (n: number, wide: number[] = []): KeyItem[] => Array.from({ length: n }, (_, i) => ({ label: `項目${i + 1}`, value: String(i + 1), wide: wide.includes(i) }))
const cellsOf = (container: HTMLElement) => [...container.querySelectorAll("dl > div")].map((c) => c.className)

describe("鍵值格：最後一列不留孤格", () => {
  it("桌面 3 欄剩 1 格：最後 4 格兩兩一列（6 條軌各佔 3），不是一格撐滿整個版心", () => {
    const { container } = render(<KeyGrid items={items(7)} />)
    expect(container.querySelector("dl")!.className).toContain("lg:grid-cols-6")
    const cells = cellsOf(container)
    expect(cells.slice(0, 3).every((c) => c.includes("lg:col-span-2"))).toBe(true)
    expect(cells.slice(3).every((c) => c.includes("lg:col-span-3"))).toBe(true)
    expect(cells.some((c) => c.includes("lg:col-span-6"))).toBe(false)
    // 手機 2 欄：7 是單數，最後一格撐滿那一列
    expect(cells.at(-1)).toContain("max-lg:col-span-2")
    expect(cells.slice(0, -1).some((c) => c.includes("max-lg:col-span-2"))).toBe(false)
  })
  it("桌面剩 2 格：最後 2 格各佔一半；剛好整除時不改", () => {
    const five = cellsOf(render(<KeyGrid items={items(5)} />).container)
    expect(five.slice(3).every((c) => c.includes("lg:col-span-3"))).toBe(true)
    expect(five.slice(0, 3).every((c) => c.includes("lg:col-span-2"))).toBe(true)
    const six = cellsOf(render(<KeyGrid items={items(6)} />).container)
    expect(six.every((c) => c.includes("lg:col-span-2") && !c.includes("max-lg:col-span-2"))).toBe(true)
  })
  it("手機：`wide` 的格子前面落單的那一格撐滿，不在左邊留空洞", () => {
    // arrange 會把 wide 往後挪到偶數位置；最後剩下單數時（wide 在最後）前一格撐滿
    const cells = cellsOf(render(<KeyGrid items={items(4, [3])} />).container)
    // 3 個普通格＋1 個 wide：第 3 格落單 → 撐滿；wide 自己一列
    expect(cells[2]).toContain("max-lg:col-span-2")
    expect(cells[3]).toContain("max-lg:col-span-2")
  })
})

describe("空狀態（全站同一種）", () => {
  it("上下實線、15px 墨色 600 標題、淡墨原因、最多一個動作；不用虛線", () => {
    const { container } = render(
      <NotYet title="這段期間還沒有成交資料" action={<button type="button">看 5 日走勢</button>}>
        官方開放資料只有當天的收盤。
      </NotYet>,
    )
    const box = container.firstElementChild!
    expect(box.className).toContain("border-y")
    expect(box.className).toContain("border-rule")
    expect(box.className).not.toContain("dashed")
    const title = screen.getByText("這段期間還沒有成交資料")
    expect(title.className).toContain("text-base")
    expect(title.className).toContain("font-semibold")
    expect(title.className).toContain("text-ink")
    expect(screen.getByText("官方開放資料只有當天的收盤。").className).toContain("text-ink-2")
    expect(screen.getAllByRole("button")).toHaveLength(1)
  })
})

describe("麵包屑的市場與產業", () => {
  it("台股照產業別；ETF 寫 ETF；美股只在對得到台股產業別時寫中文，其他只寫「美股」", async () => {
    expect(marketLine(await api.getInstrument("2330.TW"))).toBe("上市・半導體業")
    expect(marketLine(await api.getInstrument("0050.TW"))).toBe("上市・ETF")
    expect(marketLine(await api.getInstrument("AAPL"))).toBe("美股")
    expect(marketLine(await api.getInstrument("NVDA"))).toBe("美股・半導體業")
    expect(marketLine(await api.getInstrument("VOO"))).toBe("美股・ETF")
  })
})

describe("估值分頁", { timeout: 20_000 }, () => {
  it("沒有報價（商用模式的美股）：一個空狀態，不重複「沒有可商用的來源」，也沒有殖利率走勢", async () => {
    const aapl = await api.getInstrument("AAPL")
    const { container } = withQueries(<ValuationTab inst={aapl} position={null} noQuote />)
    expect(await screen.findByText("沒有報價，算不出估值", undefined, T)).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/可商用/)
    expect(screen.queryByRole("region", { name: "殖利率走勢" })).toBeNull()
  })
  it("術語說明收在「怎麼看 ⌄」：預設收著，按了才打開；每股金額寫「元」，倍數價依升降單位", async () => {
    const inst = await api.getInstrument("2330.TW")
    withQueries(<ValuationTab inst={inst} position={null} />)
    const river = await screen.findByRole("region", { name: "本益比河流圖" }, T)
    const explainer = within(river).getByText(/每條帶是/)
    expect(explainer.closest("[hidden]")).not.toBeNull()
    const toggle = within(river).getByRole("button", { name: /^怎麼看/ })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(explainer.closest("[hidden]")).toBeNull()
    // 算法說明（後端的 notes）也在裡面，不在圖下常駐
    expect(within(river).getByText(/EPS = 收盤價 ÷ 本益比/)).toBeInTheDocument()
    const yieldPanel = screen.getByRole("region", { name: "殖利率走勢" })
    expect(within(yieldPanel).getByText(/近 12 個月現金股利 ÷ 收盤價/).closest("[hidden]")).not.toBeNull()
    const now = screen.getByRole("region", { name: "現在的本益比" })
    expect(within(now).getByText(/^\d+\.\d\d 元$/)).toBeInTheDocument()
    expect(now.textContent).not.toMatch(/NT\$/)
    // 各倍數的股價：≥ 500 元的價位沒有小數（837，不是 836.8）
    const levels = within(now).getAllByRole("cell").map((c) => c.textContent!.replace(/,/g, ""))
    for (const v of levels) if (Number(v) >= 500) expect(v).toMatch(/^\d+$/)
  })
})
