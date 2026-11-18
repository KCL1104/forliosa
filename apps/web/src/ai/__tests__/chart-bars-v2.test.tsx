import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import { barScale, foldPlan, SPLIT_BARS } from "@/ai/bars-layout"
import { ChartCard } from "@/ai/ChartCard"
import type { AiChart, AiChartBar } from "@/ai/remote"

/**
 * 市場報告 v2（2026-11-18）的橫條：基準虛線（F1）、窄的主欄收合中間幾列（F2）、右側欄、分組小標、零軸位置、
 * 32 類在寬的主欄排兩欄、期間切換（C3）。數字都是伺服器寫好的字，前端只排版。
 */
afterEach(cleanup)

const base = (p: Partial<AiChart>): AiChart => ({
  id: "G",
  kind: "bars",
  title: "圖",
  unit: "pct",
  currency: null,
  x: "category",
  range: null,
  series: [],
  notes: [],
  sources: [],
  is_demo: false,
  ...p,
})
const move = (label: string, v: number, sub: string | null = null, extra: Partial<AiChartBar> = {}): AiChartBar => ({
  label,
  value: v,
  display: `${v > 0 ? "▲" : "▼"}${Math.abs(v * 100).toFixed(2)}%`,
  tone: v > 0 ? "rise" : "fall",
  sub,
  ...extra,
})
const figureOf = (title: string) => screen.getByText(title).closest("figure")!
const barRows = (fig: HTMLElement) => [...fig.querySelectorAll<HTMLElement>("li")].filter((li) => li.querySelector("[data-bar-tone]"))
const nameOf = (row: HTMLElement) => row.querySelector(".truncate")!.textContent

describe("零軸與收合（純函式）", () => {
  it("有正有負：零軸依兩邊最大值的比例放，兩邊各至少 25%；只有負的在右邊、只有正的在左邊；基準線也算進去", () => {
    expect(barScale([0.01, -0.03])).toEqual({ axis: 75, k: 2500 })
    // 跌的一邊很小也留 25%
    const s = barScale([0.03, -0.001])
    expect(s.axis).toBe(25)
    expect(s.k).toBeCloseTo(2500)
    expect(barScale([-0.02, -0.01])).toEqual({ axis: 100, k: 5000 })
    expect(barScale([10, 5])).toEqual({ axis: 0, k: 10 })
    // 全部是跌、基準是 −3%：比例照基準線算，線才畫得進橫條欄
    expect(barScale([-0.01, -0.02, -0.03]).k).toBeCloseTo(100 / 0.03)
  })

  it("收合：前 head、keep、後 tail 看得到；只收一列的地方照樣列出；不用收時是 null", () => {
    const bars = Array.from({ length: 32 }, (_, i) => move(i === 22 ? "半導體" : `類${i}`, 0.02 - i * 0.001))
    const shown = foldPlan(bars, { head: 5, tail: 5, keep: ["半導體"] })!
    expect(shown.filter(Boolean)).toHaveLength(11)
    expect(shown.slice(0, 5).every(Boolean)).toBe(true)
    expect(shown[22]).toBe(true)
    expect(shown.slice(27).every(Boolean)).toBe(true)
    expect(shown[5]).toBe(false)
    // 半導體在第 6 列：它前面只收一列（第 5 列）就照樣列出
    const near = bars.map((b, i) => (i === 6 ? { ...b, label: "半導體" } : { ...b, label: `類${i}` }))
    expect(foldPlan(near, { head: 5, tail: 5, keep: ["半導體"] })![5]).toBe(true)
    expect(foldPlan(bars.slice(0, 10), { head: 5, tail: 5, keep: [] })).toBeNull()
    expect(foldPlan(bars, null)).toBeNull()
  })
})

describe("基準虛線（F1）", () => {
  const g15 = base({
    id: "G15",
    title: "規模與風格指數漲跌（11/17）",
    bench: { value: -0.0231, label: "加權 ▼2.31%" },
    bars: [
      move("臺灣50", -0.0225, null, { group: "大小型股" }),
      move("中型100", -0.0213, null, { group: "大小型股" }),
      move("電子工業", -0.0271, null, { group: "電子與非電子" }),
      move("金融保險", -0.0035, "權重約 9%", { group: "電子與非電子" }),
      move("櫃買指數", -0.0392, null, { group: "高股息與上櫃" }),
    ],
  })

  it("每一列在橫條欄畫一段鉛筆灰虛線，位置照同一個比例；上面一行標「加權 ▼2.31%」；第二行的字鋪紙色", () => {
    render(<ChartCard chart={g15} />)
    const fig = figureOf("規模與風格指數漲跌（11/17）")
    // 全部是跌：零軸在右邊，比例照最大的 3.92%
    const x = 100 - 0.0231 * (100 / 0.0392)
    const segs = fig.querySelectorAll<HTMLElement>("[data-bench-line]")
    // 5 列橫條＋3 行分組小標，每一列一段，接成一條
    expect(segs).toHaveLength(8)
    for (const seg of segs) {
      expect(seg.style.gridColumn).toBe("2 / 3")
      expect(seg).toHaveAttribute("aria-hidden", "true")
      const line = seg.firstElementChild as HTMLElement
      expect(line.className).toContain("border-dashed")
      expect(line.className).toContain("border-chart-bench")
      expect(Number.parseFloat(line.style.left)).toBeCloseTo(x, 3)
    }
    const label = fig.querySelector<HTMLElement>("[data-bench-label]")!
    expect(label).toHaveTextContent("加權 ▼2.31%")
    expect(Number.parseFloat(label.style.left)).toBeCloseTo(x, 3)
    expect(label.className).toContain("bg-paper")
    expect(within(fig).getByText("權重約 9%").className).toContain("bg-paper")
  })

  it("分組換了就插一行 12px 淡墨小標", () => {
    render(<ChartCard chart={g15} />)
    const fig = figureOf("規模與風格指數漲跌（11/17）")
    const groups = [...fig.querySelectorAll<HTMLElement>("[data-bar-group]")]
    expect(groups.map((g) => g.textContent)).toEqual(["大小型股", "電子與非電子", "高股息與上櫃"])
    expect(groups[0]!.className).toContain("text-xs")
    expect(groups[0]!.className).toContain("text-ink-2")
    // 小標在那一組的第一列前面
    const items = [...fig.querySelectorAll<HTMLElement>("li")]
    expect(items.indexOf(groups[1]!) + 1).toBe(items.findIndex((li) => li.textContent?.startsWith("電子工業")))
  })

  it("沒有基準線的圖照舊：沒有虛線、沒有頂端那一列", () => {
    render(<ChartCard chart={base({ title: "沒有基準", bars: [move("a", 0.01), move("b", -0.01)] })} />)
    const fig = figureOf("沒有基準")
    expect(fig.querySelector("[data-bench-line]")).toBeNull()
    expect(fig.querySelectorAll("li")).toHaveLength(2)
  })
})

describe("收合中間幾列（F2）與兩欄排", () => {
  const names = [
    "居家生活",
    "食品",
    "建材營造",
    "生技醫療",
    "汽車",
    "油電燃氣",
    "紡織纖維",
    "金融保險",
    "航運",
    "電器電纜",
    "鋼鐵",
    "水泥",
    "造紙",
    "觀光餐旅",
    "其他",
    "電子通路",
    "通信網路",
    "橡膠",
    "貿易百貨",
    "其他電子",
    "數位雲端",
    "運動休閒",
    "半導體",
    "化學",
    "綠能環保",
    "塑膠",
    "電機機械",
    "電腦及週邊設備",
    "光電",
    "資訊服務",
    "電子零組件",
    "玻璃陶瓷",
  ]
  const g2 = base({
    id: "G2",
    title: "上市類股指數漲跌（11/17）",
    bench: { value: -0.0231, label: "加權 ▼2.31%" },
    fold: { head: 5, tail: 5, keep: ["半導體"] },
    bars: names.map((n, i) => move(n, 0.0126 - i * 0.0034, i === 22 ? "漲 18・跌 71・主要由台積電構成（約 77%）" : `漲 ${i}・跌 ${40 - i}`)),
  })

  it("窄的主欄：前 5、半導體、後 5 看得到，中間是「⋯ 另 17 類」「⋯ 另 4 類」；寬的主欄全部列出", () => {
    render(<ChartCard chart={g2} />)
    const fig = figureOf("上市類股指數漲跌（11/17）")
    const rows = barRows(fig)
    expect(rows).toHaveLength(32)
    const folded = rows.filter((r) => r.dataset.fold === "hidden")
    expect(folded).toHaveLength(21)
    // 收起來的列只在主欄 < 768px 時藏起來（容器查詢；和兩欄排同一個門檻，672–767px 不會整串單欄列出）
    for (const r of folded) expect(r.className).toContain("@max-3xl:hidden")
    const visible = rows.filter((r) => r.dataset.fold !== "hidden").map(nameOf)
    expect(visible).toEqual([...names.slice(0, 5), "半導體", ...names.slice(27)])
    const gaps = [...fig.querySelectorAll<HTMLElement>("[data-bar-gap]")]
    expect(gaps.map((g) => g.textContent)).toEqual(["⋯ 另 17 類", "⋯ 另 4 類"])
    for (const g of gaps) expect(g.className).toContain("@3xl:hidden")
    // 收起來的列也接著虛線：線不斷
    expect(gaps[0]!.querySelector("[data-bench-line]")).not.toBeNull()
  })

  it("「全部 32 類」展開：每一列都看得到、「⋯ 另 N 類」拿掉、按鈕變「收起」；寬的主欄沒有這個按鈕", () => {
    render(<ChartCard chart={g2} />)
    const fig = figureOf("上市類股指數漲跌（11/17）")
    const toggle = within(fig).getByRole("button", { name: "全部 32 類" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    expect(toggle.className).toContain("@3xl:hidden")
    for (const id of toggle.getAttribute("aria-controls")!.split(" ")) expect(document.getElementById(id)?.tagName).toBe("UL")
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(toggle).toHaveTextContent("收起")
    for (const r of barRows(fig)) expect(r.className).not.toContain("@max-3xl:hidden")
    for (const g of fig.querySelectorAll<HTMLElement>("[data-bar-gap]")) expect(g.className).toMatch(/(^|\s)hidden(\s|$)/)
    fireEvent.click(toggle)
    expect(within(fig).getByRole("button", { name: "全部 32 類" })).toBeInTheDocument()
  })

  it("按「收起」把圖捲回畫面（收掉約 1,000px，讀者不會被留在圖下面）；展開時不捲；減少動態時不用平滑捲動", () => {
    const calls: { el: Element; opts: unknown }[] = []
    const proto = Element.prototype as unknown as { scrollIntoView?: (o?: unknown) => void }
    const before = proto.scrollIntoView
    const media = window.matchMedia
    proto.scrollIntoView = function (this: Element, opts?: unknown) {
      calls.push({ el: this, opts })
    }
    try {
      render(<ChartCard chart={g2} />)
      const fig = figureOf("上市類股指數漲跌（11/17）")
      const toggle = within(fig).getByRole("button", { name: "全部 32 類" })
      fireEvent.click(toggle)
      expect(calls).toHaveLength(0)
      fireEvent.click(toggle)
      expect(calls).toHaveLength(1)
      expect(calls[0]!.el).toBe(fig)
      expect(calls[0]!.opts).toEqual({ block: "nearest", behavior: "smooth" })
      window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
      fireEvent.click(toggle)
      fireEvent.click(toggle)
      expect(calls).toHaveLength(2)
      expect(calls[1]!.opts).toEqual({ block: "nearest", behavior: "auto" })
    } finally {
      proto.scrollIntoView = before
      window.matchMedia = media
    }
  })

  it(`超過 ${SPLIT_BARS} 條：分成兩個清單（寬的主欄並排、窄的上下接著），名稱欄同寬、比例相同；下半欄的頂端列只在並排時出現`, () => {
    render(<ChartCard chart={g2} />)
    const fig = figureOf("上市類股指數漲跌（11/17）")
    const lists = fig.querySelectorAll<HTMLElement>("ul[data-chart-bars]")
    expect(lists).toHaveLength(2)
    expect(lists[0]!.parentElement!.className).toContain("@3xl:grid-cols-2")
    expect(lists[0]!.style.gridTemplateColumns).toBe(lists[1]!.style.gridTemplateColumns)
    expect(lists[0]!.style.gridTemplateColumns).toMatch(/^minmax\(0(px)?, ?[\d.]+em\)/)
    expect(barRows(lists[0]!)).toHaveLength(16)
    expect(barRows(lists[1]!)).toHaveLength(16)
    const heads = [...lists].map((l) => l.firstElementChild as HTMLElement)
    expect(heads[0]!.className).not.toContain("hidden")
    expect(heads[1]!.className).toContain("hidden")
    expect(heads[1]!.className).toContain("@3xl:grid")
    // 上半欄最後一列在上下接著的時候要有格線，並排時才拿掉
    const lastTop = lists[0]!.lastElementChild as HTMLElement
    expect(lastTop.className).toContain("@3xl:border-b-0")
    expect(lastTop.className).toContain("border-b")
  })
})

describe("右側欄（較前一日）與墨色的橫條", () => {
  const g8 = base({
    id: "G8",
    title: "上市類股成交金額比重（11/17）",
    aside_label: "較前一日",
    bars: [
      { label: "半導體", value: 0.409, display: "40.9%", tone: "ink", sub: "成交值最大：台積電 1,355 億元・▼2.03%", aside: "+2.2" },
      { label: "塑膠", value: 0.046, display: "4.6%", tone: "ink", sub: "成交值最大：南亞 327 億元，占這一類 82%・▼4.56%", aside: "+0.9" },
      { label: "其餘 24 類", value: 0.101, display: "10.1%", tone: "pencil", sub: "合計", aside: "−1.9" },
    ],
  })

  it("右邊多一欄 13px 淡墨等寬數字，欄名只在頂端寫一次；比重是墨色，不用漲跌色", () => {
    render(<ChartCard chart={g8} />)
    const fig = figureOf("上市類股成交金額比重（11/17）")
    const list = fig.querySelector<HTMLElement>("ul[data-chart-bars]")!
    expect(list.style.gridTemplateColumns.split(" minmax").length).toBe(4)
    const visibleLabels = within(fig)
      .getAllByText("較前一日", { exact: true })
      .filter((el) => !el.classList.contains("sr-only"))
    expect(visibleLabels).toHaveLength(1)
    expect(visibleLabels[0]!.closest("li")).toBe(list.firstElementChild)
    const asides = [...fig.querySelectorAll<HTMLElement>("[data-bar-aside]")]
    expect(asides.map((a) => a.textContent)).toEqual(["較前一日 +2.2", "較前一日 +0.9", "較前一日 −1.9"])
    expect(asides[0]!.className).toContain("text-ink-2")
    expect(asides[0]!.className).toContain("num")
    // 欄名對螢幕報讀器在每一列都念一次（看得到的只在頂端）
    expect(asides[0]!.querySelector(".sr-only")).toHaveTextContent("較前一日")
    expect(within(fig).getByText("40.9%")).toHaveClass("text-ink")
    const rows = barRows(fig)
    expect(rows[0]!.querySelector("[data-bar-tone]")!.className).toContain("bg-ink/35")
    expect(rows[2]!.querySelector("[data-bar-tone]")!.className).toContain("bg-chart-bench/55")
  })

  it("上櫃法人（億元）：買超墨色、賣超鉛筆灰，數字一律墨色", () => {
    const g16 = base({
      id: "G16",
      title: "上櫃三大法人",
      unit: "yi",
      estimate: true,
      bars: [
        { label: "通信網路", value: 19.9, display: "+19.9 億元", tone: "ink" },
        { label: "電子零組件", value: -10, display: "−10.0 億元", tone: "pencil" },
      ],
      reference: { label: "上櫃三大法人合計（估算）", display: "買超 50.3 億元" },
    })
    render(<ChartCard chart={g16} />)
    const fig = figureOf("上櫃三大法人")
    expect(within(fig).getByText("−10.0 億元")).toHaveClass("text-ink")
    expect(barRows(fig)[1]!.querySelector("[data-bar-tone]")!.className).toContain("bg-chart-bench/55")
    expect(within(fig).getByText(/^上櫃三大法人合計（估算）/)).toHaveTextContent("買超 50.3 億元")
  })
})

describe("期間切換（C3）", () => {
  const day = [move("食品", 0.0048, "漲 8・跌 14"), move("半導體", -0.0216, "漲 18・跌 71")]
  const week = [move("半導體", 0.031), move("食品", -0.012)]
  const g2 = base({
    id: "G2",
    title: "上市類股指數漲跌（11/17）",
    bars: day,
    bench: { value: -0.0231, label: "加權 ▼2.31%" },
    notes: ["虛線是加權指數同一期間的漲跌：1 類高於加權指數、1 類低於。", "每列第二行是這一類上市普通股的上漲、下跌家數。"],
    reference: { label: "上市普通股", display: "上漲 234・下跌 789・平盤 61 家" },
    views: [
      { key: "1d", label: "1 日", title: "上市類股指數漲跌（11/17）", bars: day, bench: { value: -0.0231, label: "加權 ▼2.31%" }, notes: [] },
      {
        key: "1w",
        label: "近 1 週",
        title: "上市類股指數漲跌（11/10 收盤至 11/17）",
        bars: week,
        bench: { value: 0.012, label: "加權 ▲1.20%" },
        notes: ["虛線是加權指數同一期間的漲跌：1 類高於加權指數、1 類低於。"],
      },
      { key: "since", label: "11/12 起", bars: week, bench: null, notes: [] },
    ],
  })

  it("圖上方一組選項（選取語法 b）；換期間時整組橫條、基準線與說明跟著換，依那一期排序；那一天的市場寬度只放在 1 日", () => {
    render(<ChartCard chart={g2} />)
    const fig = figureOf("上市類股指數漲跌（11/17）")
    const group = within(fig).getByRole("radiogroup", { name: "上市類股指數漲跌（11/17）的期間" })
    const options = within(group).getAllByRole("radio")
    expect(options.map((o) => o.textContent)).toEqual(["1 日", "近 1 週", "11/12 起"])
    expect(options[0]).toHaveAttribute("aria-checked", "true")
    expect(barRows(fig).map(nameOf)).toEqual(["食品", "半導體"])
    expect(within(fig).getByText(/^上市普通股/)).toBeInTheDocument()
    expect(within(fig).getByText("每列第二行是這一類上市普通股的上漲、下跌家數。")).toBeInTheDocument()

    fireEvent.click(options[1]!)
    expect(within(group).getByRole("radio", { name: "近 1 週" })).toHaveAttribute("aria-checked", "true")
    // 標題跟著換成這一期的起訖（一週的漲跌不會掛在一天的日期下面）；選項的名稱照舊
    expect(fig.querySelector("figcaption")).toHaveTextContent("上市類股指數漲跌（11/10 收盤至 11/17）")
    expect(fig).toHaveAccessibleName("上市類股指數漲跌（11/10 收盤至 11/17）")
    expect(group).toHaveAccessibleName("上市類股指數漲跌（11/17）的期間")
    expect(barRows(fig).map(nameOf)).toEqual(["半導體", "食品"])
    expect(fig.querySelector("[data-bench-label]")).toHaveTextContent("加權 ▲1.20%")
    expect(within(fig).queryByText(/^上市普通股/)).toBeNull()
    expect(within(fig).queryByText("每列第二行是這一類上市普通股的上漲、下跌家數。")).toBeNull()
    expect(within(fig).queryByText("漲 8・跌 14")).toBeNull()

    // 沒有基準線的那一期：沒有虛線；舊的資料沒有那一期的標題時沿用圖的標題
    fireEvent.click(within(group).getByRole("radio", { name: "11/12 起" }))
    expect(fig.querySelector("[data-bench-line]")).toBeNull()
    expect(fig.querySelector("figcaption")).toHaveTextContent("上市類股指數漲跌（11/17）")

    fireEvent.click(within(group).getByRole("radio", { name: "1 日" }))
    expect(within(fig).getByText(/^上市普通股/)).toBeInTheDocument()
  })

  it("只有一個期間時沒有選項", () => {
    render(<ChartCard chart={{ ...g2, views: [g2.views![0]!] }} />)
    expect(within(figureOf("上市類股指數漲跌（11/17）")).queryByRole("radiogroup")).toBeNull()
  })
})
