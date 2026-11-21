import { render, screen, within } from "@testing-library/react"
import { act } from "react"
import { beforeEach, describe, expect, it } from "vitest"
import { CentreBars, type CentreBarRow } from "@/components/centre-bars"
import { Tray } from "@/components/tray"
import { centreBars } from "@/lib/centre-bars"
import { usePrefs } from "@/stores/prefs"

beforeEach(() => {
  act(() => usePrefs.setState({ privacyMode: false, compactNumbers: true, colorConvention: "tw" }))
})

/** 螢幕閱讀器念得到的字：跳過 aria-hidden 的整棵子樹（sr-only 的字照樣算） */
function spoken(el: Element): string {
  let out = ""
  for (const node of Array.from(el.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) out += node.textContent ?? ""
    else if (node instanceof Element && node.getAttribute("aria-hidden") !== "true") out += spoken(node)
  }
  return out
}

/** 每一列的橫條：方向與長度（--bar 是橫條佔整條軌道的百分比；半邊是 50%） */
function bars(container: HTMLElement) {
  return Array.from(container.querySelectorAll("li")).map((li) => {
    const bar = li.querySelector<HTMLElement>("[data-bar]")
    return bar ? { side: bar.dataset.bar, width: bar.style.getPropertyValue("--bar"), cls: bar.className } : null
  })
}

describe("centreBars：所有列共用一個比例，中線固定在正中間", () => {
  it("全部上漲：最大的佔滿半邊，其他照比例", () => {
    expect(centreBars([400, 200, 100])).toEqual([
      { side: "up", share: 1 },
      { side: "up", share: 0.5 },
      { side: "up", share: 0.25 },
    ])
  })
  it("全部下跌：一樣照絕對值的比例，方向是 down", () => {
    expect(centreBars([-0.01, -0.04])).toEqual([
      { side: "down", share: 0.25 },
      { side: "down", share: 1 },
    ])
  })
  it("有漲有跌：兩邊用同一個比例（跌最多的佔滿，漲的照它算）", () => {
    expect(centreBars([3000, -6000, 1500])).toEqual([
      { side: "up", share: 0.5 },
      { side: "down", share: 1 },
      { side: "up", share: 0.25 },
    ])
  })
  it("0 是持平、沒有長度；全部是 0 時不會除以 0", () => {
    expect(centreBars([0, 5])).toEqual([
      { side: "flat", share: 0 },
      { side: "up", share: 1 },
    ])
    expect(centreBars([0, 0])).toEqual([
      { side: "flat", share: 0 },
      { side: "flat", share: 0 },
    ])
    expect(centreBars([Number.NaN, -2])).toEqual([
      { side: "flat", share: 0 },
      { side: "down", share: 1 },
    ])
  })
  it("分欄時傳整份清單的 scale：這一欄照全部的比例；scale 比這幾列小時不用（不會超出半邊）", () => {
    expect(centreBars([-0.01, -0.02], 0.04)).toEqual([
      { side: "down", share: 0.25 },
      { side: "down", share: 0.5 },
    ])
    expect(centreBars([8, 4], 2)).toEqual([
      { side: "up", share: 1 },
      { side: "up", share: 0.5 },
    ])
  })
})

const HOLDINGS: CentreBarRow[] = [
  { id: "2330", label: "台積電", short: "2330", value: 12340 },
  { id: "0050", label: "元大台灣50", short: "0050", value: -6170 },
  { id: "VT", label: "Vanguard Total World Stock ETF", short: "VT", value: 0 },
]

describe("<CentreBars>", () => {
  it("金額：橫條的方向與長度、漲跌色、+／−", () => {
    const { container } = render(<CentreBars rows={HOLDINGS} unit="money" />)
    const [a, b, c] = bars(container)
    expect(a).toMatchObject({ side: "up", width: "50%" })
    expect(a!.cls).toContain("left-1/2")
    expect(a!.cls).toContain("bg-rise/65")
    expect(b).toMatchObject({ side: "down", width: "25%" })
    expect(b!.cls).toContain("right-1/2")
    expect(b!.cls).toContain("bg-fall/65")
    expect(c).toBeNull()
    expect(screen.getByText("+NT$12,340")).toHaveClass("text-rise")
    expect(screen.getByText("−NT$6,170")).toHaveClass("text-fall")
    // 每一列都有中線（0 的那一列也有）
    expect(container.querySelectorAll("[data-zero-line]")).toHaveLength(3)
  })

  it("全部下跌：橫條都在左半邊", () => {
    const { container } = render(
      <CentreBars
        unit="pct"
        rows={[
          { id: "a", label: "航運業", value: -0.031 },
          { id: "b", label: "鋼鐵工業", value: -0.0124 },
        ]}
      />,
    )
    expect(bars(container).map((x) => x?.side)).toEqual(["down", "down"])
    expect(bars(container)[0]!.width).toBe("50%")
    expect(bars(container)[1]!.width).toBe("20%")
  })

  it("螢幕閱讀器：每列念全名、數字、方向；不念代號、▲▼ 與橫條", () => {
    render(<CentreBars rows={HOLDINGS} unit="money" label="今日損益" />)
    const list = screen.getByRole("list", { name: "今日損益" })
    const items = within(list).getAllByRole("listitem")
    expect(items.map(spoken)).toEqual(["台積電+NT$12,340獲利", "元大台灣50−NT$6,170虧損", "Vanguard Total World Stock ETFNT$0持平"])
  })

  it("窄的時候換成代號：代號只給眼睛（滑過看全名），全名變成只給螢幕閱讀器；名稱不截斷", () => {
    render(<CentreBars rows={HOLDINGS} unit="money" />)
    const code = screen.getByText("0050")
    expect(code).toHaveAttribute("aria-hidden", "true")
    expect(code).toHaveAttribute("title", "元大台灣50")
    expect(code).toHaveClass("hidden", "@max-2xs:inline")
    const name = screen.getByText("元大台灣50")
    expect(name).toHaveClass("@max-2xs:sr-only")
    expect(name.className).not.toMatch(/truncate|text-ellipsis|line-clamp/)
  })

  it("漲跌幅：▲▼ 不念，念「上漲／下跌」；百分比不受隱私模式影響", () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    render(
      <CentreBars
        unit="pct"
        rows={[
          { id: "a", label: "半導體業", value: 0.0215 },
          { id: "b", label: "航運業", value: -0.031 },
        ]}
      />,
    )
    expect(screen.getAllByRole("listitem").map(spoken)).toEqual(["半導體業2.15%上漲", "航運業3.10%下跌"])
    expect(screen.getAllByRole("listitem")[0]!.textContent).toContain("▲2.15%")
  })

  it("金額在隱私模式遮蔽", () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    render(<CentreBars rows={HOLDINGS.slice(0, 1)} unit="money" />)
    expect(screen.queryByText("+NT$12,340")).toBeNull()
    expect(screen.getByLabelText("已隱藏")).toBeInTheDocument()
  })

  it("沒有列時什麼都不畫", () => {
    const { container } = render(<CentreBars rows={[]} unit="pct" />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe("<Tray>", () => {
  it("section＋h2 名詞標題＋meta＋動作；section 以標題命名", () => {
    render(
      <Tray title="今日損益" meta="11/20 收盤" action={<button type="button">全部</button>} tint={2}>
        <p>內容</p>
      </Tray>,
    )
    const region = screen.getByRole("region", { name: "今日損益" })
    expect(region.tagName).toBe("SECTION")
    expect(region).toHaveClass("tray")
    expect(region).toHaveAttribute("data-tint", "2")
    expect(within(region).getByRole("heading", { level: 2, name: "今日損益" })).toBeInTheDocument()
    expect(within(region).getByText("11/20 收盤")).toHaveClass("text-ink-2")
    expect(within(region).getByRole("button", { name: "全部" })).toBeInTheDocument()
  })

  it("標題列的每一塊都可以縮、動作最多和托盤一樣寬（分頁列不會把托盤撐出畫面）", () => {
    render(
      <Tray title="走勢" action={<div role="tablist" aria-label="區間" />}>
        <p>內容</p>
      </Tray>,
    )
    const heading = screen.getByRole("heading", { name: "走勢" })
    expect(heading).toHaveClass("min-w-0")
    expect(heading.parentElement).toHaveClass("min-w-0", "flex-wrap")
    const action = screen.getByRole("tablist").parentElement!
    expect(action).toHaveClass("min-w-0", "max-w-full")
    expect(heading.contains(screen.getByRole("tablist"))).toBe(false)
  })

  it("預設底色是 1；titleHidden 時標題只給螢幕閱讀器", () => {
    render(
      <Tray title="總資產" titleHidden>
        <p>NT$4,107,724</p>
      </Tray>,
    )
    const region = screen.getByRole("region", { name: "總資產" })
    expect(region).toHaveAttribute("data-tint", "1")
    expect(screen.getByRole("heading", { name: "總資產" })).toHaveClass("sr-only")
  })
})
