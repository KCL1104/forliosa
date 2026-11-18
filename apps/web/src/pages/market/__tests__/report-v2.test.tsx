import { cleanup, fireEvent, render, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import type { ReportBlock, ReportSection as Spec, ReportTable as TableSpec } from "@/api/types"
import { ReportSection } from "@/pages/market/reports/ReportSection"
import { ReportTable } from "@/pages/market/reports/ReportTable"

/**
 * 市場報告 v2（2026-11-18）的表：熱度格（F3：伺服器決定階數，前端只上色）、同一個 `tab_group` 的表在窄的主欄一次看一張（C8）。
 */
afterEach(cleanup)

const col = (key: string, label: string, align: "left" | "right" = "right") => ({ key, label, align, num: align === "right" })
const table = (t: Partial<TableSpec> & Pick<TableSpec, "id" | "title" | "columns" | "rows">): TableSpec => ({
  rule: null, fold_after: null, empty_text: null, note: null, source_labels: [], ...t,
})

describe("熱度格（F3）", () => {
  const top10 = table({
    id: "T2_top10",
    title: "市值前 10 的大方向（11/17）",
    columns: [col("stock", "股票", "left"), col("d1", "1 日"), col("w1", "近 1 週"), col("m1", "近 1 月")],
    rows: [
      { cells: { stock: { text: "加權指數", sub: "40,092.11" }, d1: { text: "▼2.31%", tone: "fall", heat: "fall1" }, w1: { text: "▼6.13%", tone: "fall", heat: "fall2" }, m1: { text: "—" } } },
      { cells: { stock: { text: "聯發科（2454）", sub: "3,840.00" }, d1: { text: "▲1.19%", tone: "rise", heat: "rise1" }, w1: { text: "▲5.20%", tone: "rise", heat: "rise2" }, m1: { text: "—" } } },
      { cells: { stock: { text: "鴻海（2317）", sub: "219.00" }, d1: { text: "▲0.23%", tone: "rise" }, w1: { text: "—" }, m1: { text: "—" } } },
    ],
    note: "個股的近 1 週 11/19 起才有。",
  })

  it("heat 的格子鋪漲跌色 6%／12% 的底（globals.css 的 heat-*），字照樣是漲跌色；沒有 heat 的格子沒有底；存檔不夠的是「—」", () => {
    const { container } = render(<ReportTable table={top10} />)
    const cell = (text: string) => within(container).getByText(text).closest("td")!
    expect(cell("▼2.31%").className).toContain("heat-fall-1")
    expect(cell("▼2.31%")).toHaveAttribute("data-heat", "fall1")
    expect(cell("▼6.13%").className).toContain("heat-fall-2")
    expect(cell("▲1.19%").className).toContain("heat-rise-1")
    expect(cell("▲5.20%").className).toContain("heat-rise-2")
    expect(cell("▲0.23%").className).not.toMatch(/heat-/)
    expect(cell("▲0.23%")).not.toHaveAttribute("data-heat")
    expect(within(container).getByText("▲5.20%")).toHaveClass("text-rise")
    expect(within(container).getAllByText("—")).toHaveLength(4)
    expect(within(container).getByText("個股的近 1 週 11/19 起才有。")).toBeInTheDocument()
  })

  it("有熱度格的表：右對齊的格子（含表頭）右邊留一點空，同一欄有底色、沒底色的數字對齊；沒有熱度格的表照舊", () => {
    const { container } = render(<ReportTable table={top10} />)
    for (const el of container.querySelectorAll("th, td")) {
      const right = el.className.includes("text-right")
      expect(el.className.includes("pr-1.5")).toBe(right)
    }
    cleanup()
    const plain = table({ id: "T", title: "排行", columns: [col("stock", "股票", "left"), col("pct", "漲跌幅")], rows: [{ cells: { stock: { text: "台積電" }, pct: { text: "▲1.00%", tone: "rise" } } }] })
    const { container: c2 } = render(<ReportTable table={plain} />)
    expect(c2.querySelector("td.pr-1\\.5, th.pr-1\\.5")).toBeNull()
  })

  it("伺服器給了認不得的 heat：不上色", () => {
    const odd = table({ ...top10, rows: [{ cells: { stock: { text: "x" }, d1: { text: "▲9.00%", heat: "rise9" as never } } }] })
    const { container } = render(<ReportTable table={odd} />)
    expect(within(container).getByText("▲9.00%").closest("td")!.className).not.toMatch(/heat-/)
  })
})

describe("表格分頁（C8）", () => {
  const RULE = "範圍：市值前 200 名或 300 億元以上；排除創新板、全額交割、處置股"
  const movers = (id: string, title: string, label: string, n: number): ReportBlock => ({
    type: "table",
    table: table({
      id, title, rule: RULE, tab_group: "movers", tab_label: label,
      columns: [col("stock", "股票", "left"), col("pct", "漲跌幅")],
      rows: Array.from({ length: n }, (_, i) => ({ cells: { stock: { text: `${label}股${i + 1}` }, pct: { text: "▲1.00%" } } })),
    }),
  })
  const section = (blocks: ReportBlock[]): Spec => ({ key: "stocks", title: "權值股與個股", origin: "data", origin_label: "資料", collapsed_mobile: false, blocks })
  const top10: ReportBlock = { type: "table", table: table({ id: "T2_top10", title: "市值前 10 的大方向", columns: [col("stock", "股票", "left")], rows: [{ cells: { stock: { text: "加權指數" } } }] }) }

  it("相鄰、同一組的表收成一組：上面一組選項（窄的主欄），一次只顯示選的那一張；寬的主欄（≥ 896px）並排 1:1:1.4", () => {
    const { container } = render(
      <ReportSection section={section([top10, movers("T2_gainers", "漲幅前 5", "漲幅", 5), movers("T2_losers", "跌幅前 5", "跌幅", 5), movers("T2_value", "成交值前 10", "成交值", 10)])} open collapsible={false} onToggle={() => {}} />,
    )
    const group = container.querySelector<HTMLElement>("[data-table-tabs='movers']")!
    const chips = within(group).getByRole("radiogroup", { name: "排行" })
    expect(chips.className).toContain("@4xl:hidden")
    expect(within(chips).getAllByRole("radio").map((r) => r.textContent)).toEqual(["漲幅", "跌幅", "成交值"])
    const panels = [...group.querySelectorAll<HTMLElement>("[data-tab-panel]")]
    expect(panels.map((p) => p.dataset.tabPanel)).toEqual(["T2_gainers", "T2_losers", "T2_value"])
    const hidden = (p: HTMLElement) => /(^|\s)hidden(\s|$)/.test(p.className)
    expect(panels.map(hidden)).toEqual([false, true, true])
    for (const p of panels) expect(p.className).toContain("@4xl:grid")
    expect(panels[0]!.parentElement!.className).toContain("@4xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)]")
    // 並排時各表的標題列等高：父層兩列（標題｜表），每一張表用 subgrid 對齊，標題換成兩行的那一張表頭也對齊
    expect(panels[0]!.parentElement!.className).toContain("@4xl:grid-rows-[auto_1fr]")
    for (const p of panels) {
      expect(p.className).toContain("@4xl:grid-rows-subgrid")
      expect(p.querySelector("figure")!.className).toContain("@4xl:grid-rows-subgrid")
      expect(p.querySelector("figure")!.children).toHaveLength(2)
    }

    fireEvent.click(within(chips).getByRole("radio", { name: "跌幅" }))
    expect(within(chips).getByRole("radio", { name: "跌幅" })).toHaveAttribute("aria-checked", "true")
    expect(panels.map(hidden)).toEqual([true, false, true])
    // 不在組裡的表照舊
    expect(container.querySelector("[data-table='T2_top10']")!.closest("[data-table-tabs]")).toBeNull()
  })

  it("幾張表的規則一樣時只寫一次：在選項下面、緊接著表，前面是這一組的名稱（不會被讀成上一張表的附註）", () => {
    const { container } = render(
      <ReportSection section={section([top10, movers("T2_gainers", "漲幅前 5", "漲幅", 5), movers("T2_losers", "跌幅前 5", "跌幅", 5)])} open collapsible={false} onToggle={() => {}} />,
    )
    const group = container.querySelector<HTMLElement>("[data-table-tabs='movers']")!
    const rules = group.querySelectorAll<HTMLElement>("[data-tabs-rule]")
    expect(rules).toHaveLength(1)
    expect(rules[0]!.textContent).toBe(`排行${RULE}`)
    expect(within(rules[0]!).getByText("排行").className).toContain("text-ink")
    expect(container.textContent!.split(RULE)).toHaveLength(2)  // the tables themselves no longer repeat it
    const order = [...group.children].map((el) => (el.getAttribute("role") === "radiogroup" ? "chips" : el.hasAttribute("data-tabs-rule") ? "rule" : "tables"))
    expect(order).toEqual(["chips", "rule", "tables"])
  })

  it("融資增加｜減少是另一組（「融資增減」）；一組只有一張時照一般的表畫，沒有選項", () => {
    const margin = (id: string, label: string): ReportBlock => ({
      type: "table",
      table: table({ id, title: `融資${label}前 5`, rule: null, tab_group: "margin", tab_label: label, columns: [col("stock", "股票", "left")], rows: [{ cells: { stock: { text: `${label}股` } } }] }),
    })
    const { container } = render(<ReportSection section={section([margin("T10_up", "增加"), margin("T10_down", "減少"), movers("T2_gainers", "漲幅前 5", "漲幅", 5)])} open collapsible={false} onToggle={() => {}} />)
    expect(within(container).getByRole("radiogroup", { name: "融資增減" })).toBeInTheDocument()
    // 只有一張的 movers：沒有選項，表照常顯示（規則也照常寫在表頭）
    expect(within(container).queryByRole("radiogroup", { name: "排行" })).toBeNull()
    expect(container.querySelector("[data-table='T2_gainers']")).not.toBeNull()
    expect(within(container.querySelector<HTMLElement>("[data-table='T2_gainers']")!).getByText(RULE)).toBeInTheDocument()
  })
})
