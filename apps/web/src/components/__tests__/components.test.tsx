import { render, screen } from "@testing-library/react"
import { act } from "react"
import { beforeEach, describe, expect, it } from "vitest"
import { DemoTag } from "@/components/section"
import { Segmented } from "@/components/segmented"
import { Sparkline } from "@/components/sparkline"
import { FlowPct, Money, Pct, Price, PriceChange, Quantity } from "@/components/finance"
import { MASK } from "@/lib/format"
import { usePrefs } from "@/stores/prefs"

beforeEach(() => {
  act(() => usePrefs.setState({ privacyMode: false, compactNumbers: true, quantityUnit: "lot", colorConvention: "tw" }))
})

describe("<Pct>", () => {
  it("上漲：▲＋紅漲色 class＋螢幕閱讀器文字", () => {
    const { container } = render(<Pct value={0.014} />)
    expect(container.textContent).toContain("▲")
    expect(container.textContent).toContain("1.40%")
    expect(container.textContent).not.toContain("+")
    expect(container.firstElementChild).toHaveClass("text-rise")
    expect(screen.getByText("上漲")).toHaveClass("sr-only")
  })
  it("下跌：▼＋跌色", () => {
    const { container } = render(<Pct value={-0.0185} />)
    expect(container.textContent).toContain("▼")
    expect(container.textContent).toContain("▼1.85%")
    expect(container.firstElementChild).toHaveClass("text-fall")
  })
})

describe("<Money> 與隱私模式", () => {
  it("一般顯示完整金額", () => {
    render(<Money value={123_456_789_012} />)
    expect(screen.getByText("NT$123,456,789,012")).toBeInTheDocument()
  })
  it("compact 時縮寫，title 保留完整數字", () => {
    render(<Money value={3_284_500} compact />)
    expect(screen.getByText("NT$328.45 萬")).toHaveAttribute("title", "NT$3,284,500")
  })
  it("隱私模式遮蔽金額與股數，但百分比照常", () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    render(
      <div>
        <Money value={40_320} />
        <Quantity shares={1500} market="TWSE" />
        <Pct value={0.0124} />
      </div>,
    )
    expect(screen.getAllByLabelText("已隱藏")).toHaveLength(2)
    expect(screen.getAllByText(MASK)).toHaveLength(2)
    expect(screen.getByText("1.24%")).toBeInTheDocument()
  })
  it("股數依偏好顯示張／股", () => {
    render(<Quantity shares={1500} market="TWSE" />)
    expect(screen.getByText("1 張 500 股")).toBeInTheDocument()
  })
})

describe("<DemoTag>", () => {
  it("示範資料是細框小字（資料狀態），可滑過說明", () => {
    render(<DemoTag />)
    const el = screen.getByText("示範資料")
    expect(el).toHaveClass("demo-tag")
    expect(el).toHaveAttribute("title")
  })
})

describe("<Segmented>", () => {
  it("tablist 語意、選取中的分段可 Tab，數字跟在標籤後", () => {
    render(<Segmented label="帳本內容" value="holdings" onChange={() => {}} options={[{ value: "holdings", label: "持倉", count: 7 }, { value: "transactions", label: "交易" }]} />)
    expect(screen.getByRole("tablist", { name: "帳本內容" })).toBeInTheDocument()
    const tab = screen.getByRole("tab", { name: /持倉/ })
    expect(tab).toHaveAttribute("aria-selected", "true")
    expect(tab).toHaveAttribute("tabindex", "0")
    expect(screen.getByRole("tab", { name: "交易" })).toHaveAttribute("tabindex", "-1")
  })
})

describe("<Sparkline>", () => {
  it("有基準線時畫虛線，少於兩點顯示「—」", () => {
    const { container } = render(<Sparkline values={[1, 2, 1.5]} baseline={1.2} tone="up" label="今日走勢" />)
    expect(screen.getByRole("img", { name: "今日走勢" })).toBeInTheDocument()
    expect(container.querySelector('path[stroke-dasharray]')).not.toBeNull()
    expect(render(<Sparkline values={[1]} label="x" />).container.textContent).toBe("—")
  })
})

describe("可為 null 的欄位（CONTRACT_NOTES）", () => {
  it("沒有昨收時漲跌顯示「—」，不顯示 NaN", () => {
    const { container } = render(<PriceChange change={null} pct={null} market="TWSE" />)
    expect(container.textContent).toBe("—")
    expect(render(<Price value={null} market="TWSE" />).container.textContent).toBe("—")
    expect(render(<FlowPct value={null} />).container.textContent).toBe("—")
  })
})
