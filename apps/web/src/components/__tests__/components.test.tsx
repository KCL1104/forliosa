import { render, screen } from "@testing-library/react"
import { act } from "react"
import { beforeEach, describe, expect, it } from "vitest"
import { Chop } from "@/components/chop"
import { Money, Pct, Quantity } from "@/components/finance"
import { MASK, MINUS } from "@/lib/format"
import { usePrefs } from "@/stores/prefs"

beforeEach(() => {
  act(() => usePrefs.setState({ privacyMode: false, compactNumbers: true, quantityUnit: "lot", colorConvention: "tw" }))
})

describe("<Pct>", () => {
  it("上漲：▲＋紅漲色 class＋螢幕閱讀器文字", () => {
    const { container } = render(<Pct value={0.014} />)
    expect(container.textContent).toContain("▲")
    expect(container.textContent).toContain("+1.40%")
    expect(container.firstElementChild).toHaveClass("text-rise")
    expect(screen.getByText("上漲")).toHaveClass("sr-only")
  })
  it("下跌：▼＋跌色", () => {
    const { container } = render(<Pct value={-0.0185} />)
    expect(container.textContent).toContain("▼")
    expect(container.textContent).toContain(`${MINUS}1.85%`)
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
    expect(screen.getByText("+1.24%")).toBeInTheDocument()
  })
  it("股數依偏好顯示張／股", () => {
    render(<Quantity shares={1500} market="TWSE" />)
    expect(screen.getByText("1 張 500 股")).toBeInTheDocument()
  })
})

describe("<Chop>", () => {
  it("章使用 .chop 樣式，press 時加上蓋章動畫", () => {
    render(<Chop press>已入帳</Chop>)
    const el = screen.getByText("已入帳")
    expect(el).toHaveClass("chop")
    expect(el).toHaveClass("chop-press")
  })
})
