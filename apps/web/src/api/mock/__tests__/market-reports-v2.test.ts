import { describe, expect, it } from "vitest"
import type { AiChart } from "@/ai/remote"
import { buildMockReport } from "@/api/mock/market-reports"
import type { MarketReport, ReportTable } from "@/api/types"

/**
 * mock 的市場報告照 v2（2026-11-18）的段落與區塊排（和後端 `assemble.py` 一樣）：盤前多「昨日台股全貌」與「昨日籌碼」、
 * 盤後類股段 G17→G15→G2→G8、週報「類股一週與大方向」；拿掉的重複（D6）不再出現。數字是假的，但彼此對得上。
 */
const layout = (r: MarketReport) =>
  r.sections.map((s) => [s.key, s.blocks.map((b) => (b.type === "chart" ? b.chart.id : b.type === "table" ? b.table.id : b.type))] as const)
const chartOf = (r: MarketReport, id: string): AiChart => {
  for (const s of r.sections) for (const b of s.blocks) if (b.type === "chart" && b.chart.id === id) return b.chart
  throw new Error(`no chart ${id}`)
}
const tableOf = (r: MarketReport, id: string): ReportTable => {
  for (const s of r.sections) for (const b of s.blocks) if (b.type === "table" && b.table.id === id) return b.table
  throw new Error(`no table ${id}`)
}
const allIds = (r: MarketReport) => layout(r).flatMap(([, ids]) => ids)
const num = (s: string) => Number(s.replace(/[^\d.−-]/g, "").replace("−", "-"))

describe("盤前重點", () => {
  const r = buildMockReport("premarket", "2026-11-12")

  it("段落：隔夜要聞、今天市場在看什麼、昨日台股全貌（資料段，手機收合）、昨日籌碼（手機收合）、今日圖", () => {
    expect(layout(r)).toEqual([
      ["overnight", ["text", "G6"]],
      ["watch", ["items"]],
      ["yesterday", ["note", "G17", "G15", "G2", "G2_otc", "G8"]],
      ["chips", ["text", "G7", "T7", "G16", "T10_up", "T10_down"]],
      ["chart_of_day", ["G5"]],
    ])
    const yesterday = r.sections.find((s) => s.key === "yesterday")!
    expect(yesterday.title).toBe("昨日台股全貌（11/11）")
    expect(yesterday.origin).toBe("data")
    // 2026-11-27：前一天的盤後重點已經給過這幾張圖，盤前在手機上先收著
    expect(yesterday.collapsed_mobile).toBe(true)
    const chips = r.sections.find((s) => s.key === "chips")!
    expect(chips.title).toBe("昨日籌碼（晚間公布）")
    expect(chips.collapsed_mobile).toBe(true)
  })

  it("拿掉的重複：沒有「昨晚才到的資料」表、只有一張圖的「圖」段、G4；今日圖選單只剩 G5", () => {
    expect(allIds(r)).not.toContain("T-evening")
    expect(allIds(r)).not.toContain("G4")
    expect(r.sections.some((s) => s.key === "charts" || s.key === "evening")).toBe(false)
    expect(chartOf(r, "G5").title).toMatch(/^權值前 5 檔(一個月|近 \d+ 個交易日)比較（至 11\/11）$/)
  })

  it("G2 盤前寫上市寬度；類股內的上漲、下跌家數加總等於上市的上漲、下跌家數", () => {
    const g2 = chartOf(r, "G2")
    expect(g2.reference?.label).toBe("上市普通股")
    const [, up, down] = g2.reference!.display.match(/上漲 (\d+)・下跌 (\d+)/)!
    let ups = 0
    let downs = 0
    for (const b of g2.bars!) {
      const m = b.sub!.match(/^漲 (\d+)・跌 (\d+)/)!
      ups += Number(m[1])
      downs += Number(m[2])
    }
    expect(ups).toBe(Number(up))
    expect(downs).toBe(Number(down))
    expect(g2.fold).toEqual({ head: 5, tail: 5, keep: ["半導體"] })
    expect(g2.bench?.label).toMatch(/^加權 [▲▼]/)
    // 期間：1 日、近 1 週、存檔不到一個月時是「10/26 起」
    expect(g2.views!.map((v) => v.label)).toEqual(["1 日", "近 1 週", "10/26 起"])
    expect(g2.views![0]!.bars).toEqual(g2.bars)
  })

  it("無 AI 的資料版：沒有今天市場在看什麼與今日圖，昨日籌碼只有資料", () => {
    const data = buildMockReport("premarket", "2026-11-12", { ai: false, edition: "data" })
    expect(layout(data).map(([k]) => k)).toEqual(["overnight", "yesterday", "chips"])
    expect(layout(data).find(([k]) => k === "chips")![1]).toEqual(["G7", "T7", "G16", "T10_up", "T10_down"])
  })
})

describe("盤後重點", () => {
  const r = buildMockReport("close", "2026-11-11", { tables: true })

  it("類股段 AI → G17 → G15 → G2 → G8（手機不收合）；權值股段 G3 → T2_top10 → 排行三張；籌碼段最後是 G16；上櫃段 T5 → G2_otc", () => {
    const l = Object.fromEntries(layout(r))
    expect(l.sectors).toEqual(["text", "G17", "G15", "G2", "G8"])
    expect(r.sections.find((s) => s.key === "sectors")!.collapsed_mobile).toBe(false)
    expect(l.stocks).toEqual(["text", "G3", "T2_top10", "T2_gainers", "T2_losers", "T2_value"])
    expect(l.chips).toEqual(["text", "note", "T7", "G16"])
    expect(l.otc).toEqual(["T5_top10", "T5_gainers", "T5_losers", "G2_otc"])
    expect(l.chart_of_day).toEqual(["G5"])
    expect(allIds(r)).not.toContain("T6")
    expect(allIds(r)).not.toContain("G4")
    // 盤後的數字欄已有市場寬度：G2 不寫 reference
    expect(chartOf(r, "G2").reference ?? null).toBeNull()
  })

  it("15:55 那一版沒有期交所與上櫃（T7、G16、G2_otc）", () => {
    const early = buildMockReport("close", "2026-11-11")
    expect(allIds(early)).not.toEqual(expect.arrayContaining(["T7"]))
    for (const id of ["T7", "G16", "G2_otc", "T5_gainers"]) expect(allIds(early)).not.toContain(id)
  })

  it("T2_top10 v2：第一列是加權指數（沒有連結），欄是 1 日｜近 1 週｜近 1 月，沒有點數貢獻欄；個股存檔不夠的是「—」並寫哪天起才有", () => {
    const t = tableOf(r, "T2_top10")
    expect(t.columns.map((c) => c.label)).toEqual(["股票", "1 日", "近 1 週", "近 1 月"])
    expect(t.rows[0]!.cells.stock!.text).toBe("加權指數")
    expect(t.rows[0]!.href).toBeNull()
    expect(t.rows).toHaveLength(11)
    expect(t.rows.slice(1).every((row) => row.cells.m1!.text === "—" && !row.cells.m1!.heat)).toBe(true)
    expect(t.note).toBe("個股的近 1 月 11/25 起才有（存檔從 10/26 開始）。")
    // 熱度格照門檻：1 日 1%／3%
    for (const row of t.rows) {
      const c = row.cells.d1!
      const v = Math.abs(num(c.text)) / 100
      expect(c.heat ?? null).toBe(v < 0.01 ? null : `${c.tone}${v >= 0.03 ? 2 : 1}`)
    }
  })

  it("排行三張是同一組分頁（漲幅｜跌幅｜成交值），規則相同", () => {
    const tabs = ["T2_gainers", "T2_losers", "T2_value"].map((id) => tableOf(r, id))
    expect(tabs.map((t) => [t.tab_group, t.tab_label])).toEqual([["movers", "漲幅"], ["movers", "跌幅"], ["movers", "成交值"]])
    expect(new Set(tabs.map((t) => t.rule)).size).toBe(1)
    expect([tableOf(r, "T5_gainers"), tableOf(r, "T5_losers")].map((t) => t.tab_group)).toEqual(["otc_movers", "otc_movers"])
  })

  it("G17 的估算加總對得上官方漲跌；拉低與拉高的類股最多各 5 類，其餘合計是鉛筆灰", () => {
    const g17 = chartOf(r, "G17")
    const [, official, sum] = g17.reference!.display.match(/^(.+?) 點・32 類估算加總 (.+?) 點$/)!
    expect(Math.abs(num(official!) - num(sum!))).toBeLessThanOrEqual(1.5)
    const bars = g17.bars!
    expect(bars.at(-1)!.label).toMatch(/^其餘 \d+ 類$/)
    expect(bars.at(-1)!.tone).toBe("pencil")
    expect(bars.filter((b) => b.tone === "rise").length).toBeLessThanOrEqual(5)
    expect(bars.filter((b) => b.tone === "fall").length).toBeLessThanOrEqual(5)
    expect(g17.estimate).toBe(true)
  })

  it("G8 比重加總 100%、墨色、右側欄是較前一日的百分點；G16 墨／鉛筆灰；G15 三組、有基準線", () => {
    const g8 = chartOf(r, "G8")
    expect(g8.bars!.reduce((a, b) => a + b.value, 0)).toBeCloseTo(1, 6)
    expect(g8.aside_label).toBe("較前一日")
    expect(g8.bars!.every((b) => /^([+−]\d+\.\d|0\.0)$/.test(b.aside!))).toBe(true)
    expect(new Set(g8.bars!.map((b) => b.tone))).toEqual(new Set(["ink", "pencil"]))
    const g16 = chartOf(r, "G16")
    expect(g16.unit).toBe("yi")
    expect(g16.bars!.every((b) => b.tone === (b.value >= 0 ? "ink" : "pencil"))).toBe(true)
    const g15 = chartOf(r, "G15")
    expect([...new Set(g15.bars!.map((b) => b.group))]).toEqual(["大小型股", "電子與非電子", "高股息與上櫃"])
    expect(g15.bench).toBeTruthy()
  })

  it("官方指數檔沒進來：類股段只有 Forliosa 自己算的 G17（估算加總，沒有官方漲跌）與 G8", () => {
    const missing = buildMockReport("close", "2026-11-04", { indexMissing: true })
    expect(Object.fromEntries(layout(missing)).sectors).toEqual(["text", "G17", "G8"])
    expect(chartOf(missing, "G17").reference!.label).toBe("估算加總")
  })
})

describe("市場週報", () => {
  const r = buildMockReport("weekly", "2026-11-15")

  it("「多期間報酬」併進「類股一週與大方向」：AI → G17 → T3（9 個指數）→ G2（近 1 週｜存檔起）→ G8；G5 改到本週圖", () => {
    const l = Object.fromEntries(layout(r))
    expect(l.returns).toBeUndefined()
    expect(r.sections.find((s) => s.key === "sectors_week")!.title).toBe("類股一週與大方向")
    expect(l.sectors_week).toEqual(["text", "G17", "T3", "G2", "G8"])
    // 每一段都和盤後一樣 AI 文字在前（不用先捲過 1,700–2,000px 的表）
    expect(l.stocks_week).toEqual(["text", "G3", "T2_top10", "T2_gainers", "T2_losers", "T2_value"])
    expect(l.chips_week).toEqual(["text", "G7", "T9", "G16", "T10_up", "T10_down"])
    expect(l.global_week).toEqual(["text", "G6"])
    expect(l.chart_of_day).toEqual(["G5"])
    const t3 = tableOf(r, "T3")
    expect(t3.rows.map((row) => row.cells.name!.text)).toEqual(["加權指數", "報酬指數", "櫃買指數", "臺灣50", "中型100", "小型股300", "電子工業", "未含電子", "金融保險"])
    expect(t3.columns.map((c) => c.label)).toEqual(["指數", "1 週", "10/26 起"])
    expect(chartOf(r, "G2").views!.map((v) => v.label)).toEqual(["近 1 週", "10/26 起"])
    expect(chartOf(r, "G8").aside_label).toBe("較前一週")
    expect(tableOf(r, "T2_top10").columns.map((c) => c.label)).toEqual(["股票", "週漲跌", "近 1 月"])
    expect(tableOf(r, "T2_top10").rule).toMatch(/；底色只分兩階（週漲跌：2%、5%；近 1 月：4%、10%）$/)
    expect(tableOf(r, "T9").columns.map((c) => c.label)).toEqual(["項目", "本週收", "週變化"])
    // 期間切換的每一組有自己的標題：一週的漲跌不會掛在別的期間下面
    const g2 = chartOf(r, "G2")
    expect(g2.views![0]!.title).toBe(g2.title)
    expect(g2.views![1]!.title).toMatch(/^上市類股指數漲跌（10\/26 收盤至 \d+\/\d+）$/)
    expect(tableOf(r, "T2_value").tab_label).toBe("週成交值")
    expect(tableOf(r, "T10_up").columns.map((c) => c.label)).toEqual(["股票", "融資餘額（張）", "週增減（張）"])
  })

  it("G2 的基準線和 T3 的加權指數一週是同一個數", () => {
    expect(chartOf(r, "G2").bench!.label).toBe(`加權 ${tableOf(r, "T3").rows[0]!.cells.w1!.text}`)
  })
})

describe("A1：新圖的說明不寫評價字", () => {
  it("沒有強勢、弱勢、偏高、偏低、資金流向", () => {
    for (const r of [buildMockReport("premarket", "2026-11-12"), buildMockReport("close", "2026-11-11", { tables: true }), buildMockReport("weekly", "2026-11-15")]) {
      for (const s of r.sections)
        for (const b of s.blocks) {
          const text = b.type === "chart" ? [b.chart.title, ...b.chart.notes, ...(b.chart.views ?? []).flatMap((v) => v.notes)].join("") : b.type === "table" ? [b.table.title, b.table.rule, b.table.note].join("") : ""
          expect(text).not.toMatch(/強勢|弱勢|偏高|偏低|資金流向/)
        }
    }
  })

  it("融資表沒有漲跌幅欄", () => {
    const r = buildMockReport("premarket", "2026-11-12")
    for (const id of ["T10_up", "T10_down"]) expect(tableOf(r, id).columns.map((c) => c.key)).toEqual(["stock", "balance", "change"])
  })
})

describe("重點的欄位與趨勢圖（2026-11-27）", () => {
  const close = buildMockReport("close", "2026-11-11", { tables: true })
  const pre = buildMockReport("premarket", "2026-11-12")
  const rows = (r: MarketReport) => (r.brief ?? []).map((row) => [row.key, row.label, row.origin])
  const text = (r: MarketReport, key: string) => r.brief!.find((row) => row.key === key)!.paragraph.sentences.map((x) => x.text).join("")

  it("盤後：為什麼、貢獻、位置、量、籌碼；位置與量是規則算的", () => {
    expect(rows(close)).toEqual([
      ["why", "為什麼", "ai"], ["drivers", "貢獻", "ai"], ["position", "位置", "rules"], ["volume", "量", "rules"], ["chips", "籌碼", "ai"],
    ])
    expect(text(close, "position")).toMatch(/收在 5 日線(與 10 日線)?之[上下]/)
    expect(text(close, "volume")).toMatch(/^上市 [\d,]+ 億元，(比前一日[多少] [\d,]+ 億元|和前一日相近)，是 5 日均量的 \d+%。$/)
    // 點數貢獻是估算，句子裡要標出來
    expect(text(close, "drivers")).toMatch(/^.+類約 [+−][\d,]+ 點（估算[^）]*）、.+類約 [+−][\d,]+ 點（估算[^）]*）。$/)
    // 半導體連同它的集中度一起寫
    expect(text(close, "drivers")).toContain("半導體類約 +83 點（估算；主要由台積電構成，約 77%）")
  })

  it("盤前：隔夜、為什麼、排定、位置、籌碼；位置寫前一個交易日收在哪", () => {
    expect(rows(pre).map(([, label]) => label)).toEqual(["隔夜", "為什麼", "排定", "位置", "籌碼"])
    expect(text(pre, "position")).toMatch(/^加權指數 11\/11 收 [\d,.]+ 點（[▲▼][\d.]+%），在 5 日線/)
  })

  it("資料版只有規則算的幾列：沒有為什麼，盤後也沒有籌碼", () => {
    const data = buildMockReport("close", "2026-11-11", { ai: false, edition: "data" })
    expect(rows(data)).toEqual([["drivers", "貢獻", "rules"], ["position", "位置", "rules"], ["volume", "量", "rules"]])
    // 下午自己加總的數字是估算：差距不到 3% 不寫成數字，比例前面加「約」
    expect(text(data, "volume")).toMatch(/^上市約 [\d,]+ 億元（估算），(比前一日[多少] [\d,]+ 億元|和前一日相近)，約是 5 日均量的 \d+%。$/)
    expect(rows(buildMockReport("premarket", "2026-11-12", { ai: false, edition: "data" })).map(([key]) => key)).toEqual(["overnight", "scheduled", "position", "chips"])
  })

  it("重點的每一句都有出處，號碼從 1 開始、照出現的順序；3 個重點不在頁面上，所以不編號", () => {
    const cites = close.brief!.flatMap((row) => row.paragraph.sentences.flatMap((x) => x.cites))
    expect(close.brief!.every((row) => row.paragraph.sentences.every((x) => x.cites.length > 0))).toBe(true)
    expect(cites[0]).toBe(1)
    expect(cites.every((n) => close.footnotes.some((f) => f.n === n))).toBe(true)
    expect(close.highlights.every((p) => p.sentences.every((x) => x.cites.length === 0))).toBe(true)
  })

  it("趨勢圖：加權指數是一條連續的線，最後一點是數字欄的收盤；5 日線、10 日線是收盤的平均，各自從第 5、10 天開始", () => {
    const trend = close.trend!
    expect(trend.series.map((x) => [x.name, x.role ?? null])).toEqual([["加權指數", null], ["5 日線", "average"], ["10 日線", "average"]])
    const [index, ma5, ma10] = trend.series.map((x) => x.points) as [AiChart["series"][number]["points"], AiChart["series"][number]["points"], AiChart["series"][number]["points"]]
    expect(index[index.length - 1]!.v).toBe(num(close.numbers.find((n) => n.key === "taiex")!.value))
    expect(ma5).toHaveLength(index.length - 4)
    expect(ma10).toHaveLength(index.length - 9)
    expect(ma5[0]!.t).toBe(index[4]!.t)
    const mean = (n: number) => index.slice(-n).reduce((a, q) => a + q.v, 0) / n
    expect(ma5[ma5.length - 1]!.v).toBeCloseTo(mean(5), 1)
    expect(ma10[ma10.length - 1]!.v).toBeCloseTo(mean(10), 1)
    // 「位置」那一列和圖是同一份數字
    const last = index[index.length - 1]!.v
    const side = (avg: number) => (last >= avg ? "之上" : "之下")
    expect(text(close, "position")).toContain(side(mean(5)) === side(mean(10)) ? `收在 5 日線與 10 日線${side(mean(5))}` : `收在 5 日線${side(mean(5))}、10 日線${side(mean(10))}`)
    // 相鄰兩天的漲跌不會亂跳（每天都在 ±2% 以內）
    for (let i = 1; i < index.length; i++) expect(Math.abs(index[i]!.v / index[i - 1]!.v - 1)).toBeLessThan(0.02)
  })

  it("加權指數的圖只出現一次：在重點下面，不在「今天發生什麼」；盤前的趨勢圖畫到前一個交易日", () => {
    expect(allIds(close)).not.toContain("G1")
    expect(layout(close).find(([k]) => k === "what_happened")![1]).toEqual(["text"])
    const points = pre.trend!.series[0]!.points
    expect(points[points.length - 1]!.t).toBe("2026-11-11")
    // 資料版的「今天發生什麼」原本只有那張圖：圖移走以後沒有這一段
    expect(layout(buildMockReport("close", "2026-11-11", { ai: false, edition: "data" })).map(([k]) => k)).not.toContain("what_happened")
  })

  it("官方加權指數沒進來：沒有趨勢圖、沒有位置那一列；存檔第一天的盤前也沒有圖", () => {
    const missing = buildMockReport("close", "2026-11-04", { indexMissing: true })
    expect(missing.trend ?? null).toBeNull()
    expect(rows(missing).map(([key]) => key)).not.toContain("position")
    expect(buildMockReport("premarket", "2026-10-26").trend ?? null).toBeNull()
  })

  it("週報照舊是 3–5 個重點，沒有欄位與趨勢圖", () => {
    const weekly = buildMockReport("weekly", "2026-11-15")
    expect(weekly.brief ?? null).toBeNull()
    expect(weekly.trend ?? null).toBeNull()
    expect(weekly.highlights.length).toBeGreaterThanOrEqual(3)
  })
})
