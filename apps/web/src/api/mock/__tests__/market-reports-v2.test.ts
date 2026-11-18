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

  it("段落：隔夜要聞、今天市場在看什麼、昨日台股全貌（資料段）、昨日籌碼（手機收合）、今日圖", () => {
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
    expect(yesterday.collapsed_mobile).toBe(false)
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
