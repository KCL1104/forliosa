import { cleanup, render, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import type { ReportBlock, ReportSection as Spec } from "@/api/types"
import { ReportSection } from "@/pages/market/reports/ReportSection"

/**
 * 段標旁的來歷（試跑 2026-11-17）：有伺服器的表或圖的段寫「資料」，段裡的 AI 文字在開始的地方另外標
 * 「AI 依資料與報導整理」；只有 AI 文字的段才在段標寫 AI。舊版本伺服器把這種段寫成 AI，前端照區塊自己判斷。
 */
afterEach(cleanup)

const table: ReportBlock = {
  type: "table",
  table: {
    id: "T_evening", title: "昨晚才到的資料（11/16）", rule: null,
    columns: [{ key: "item", label: "項目", align: "left", num: false }, { key: "value", label: "數字", align: "right", num: true }],
    rows: [{ cells: { item: { text: "P/C 未平倉比" }, value: { text: "53.79%" } } }],
    fold_after: null, empty_text: null, note: null, source_labels: [],
  },
}
const text: ReportBlock = { type: "text", paragraphs: [{ sentences: [{ text: "台指選擇權 P/C 未平倉比 11/16 為 53.79%。", cites: [1] }] }] }
const section = (blocks: ReportBlock[], origin: Spec["origin"], origin_label: Spec["origin_label"]): Spec => ({
  key: "evening", title: "昨晚才到的資料", origin, origin_label, collapsed_mobile: false, blocks,
})
const mount = (s: Spec) => render(<ReportSection section={s} open collapsible={false} onToggle={() => {}} />).container

describe("段的來歷", () => {
  it("表格加上 AI 文字：段標寫「資料」，AI 文字開始的地方標 AI（舊的版本寫成 AI 也一樣）", () => {
    for (const label of ["AI 依資料與報導整理", "資料"] as const) {
      const el = mount(section([table, text], "ai", label))
      const header = el.querySelector("header")!
      expect(within(header).getByText("資料")).toBeInTheDocument()
      expect(within(header).queryByText("AI 依資料與報導整理")).toBeNull()
      const mark = within(el).getByText("AI 依資料與報導整理")
      // 標記在表格之後、AI 文字之前
      const tableEl = el.querySelector("table")!
      expect(tableEl.compareDocumentPosition(mark) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(mark.compareDocumentPosition(el.querySelector(".ai-voice")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      cleanup()
    }
  })

  it("只有 AI 文字：段標寫 AI，不另外標", () => {
    const el = mount(section([text], "ai", "AI 依資料與報導整理"))
    expect(within(el.querySelector("header")!).getByText("AI 依資料與報導整理")).toBeInTheDocument()
    expect(within(el).getAllByText("AI 依資料與報導整理")).toHaveLength(1)
  })

  it("只有資料：段標寫「資料」", () => {
    const el = mount(section([table], "data", "資料"))
    expect(within(el.querySelector("header")!).getByText("資料")).toBeInTheDocument()
    expect(within(el).queryByText("AI 依資料與報導整理")).toBeNull()
  })
})
