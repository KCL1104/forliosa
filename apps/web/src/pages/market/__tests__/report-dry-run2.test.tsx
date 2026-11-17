import { cleanup, render, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import type { MarketReport, ReportFootnote } from "@/api/types"
import { ReportCalendar } from "@/pages/market/reports/ReportCalendar"
import { ReportSources } from "@/pages/market/reports/ReportSources"

/**
 * 第二次試跑（2026-11-17）：手機上行事曆的長標題不能把「資料」擠成直排；資料註腳的名稱本身就帶日期，不再接一次日期
 * （「…第 1 版 11/17・11/17」）。報導註腳照樣接發布時間。
 */
afterEach(cleanup)

describe("行事曆段標", () => {
  it("長標題換行，「資料」不縮", () => {
    const { container } = render(
      <ReportCalendar calendar={{ title: "盤後與下個交易日行事曆（11/17–11/18）", groups: [], empty_text: null, source_labels: [] }} />,
    )
    const header = container.querySelector("header")!
    expect(header.querySelector("h3")!.className).toContain("min-w-0")
    expect(within(header).getByText("資料").className).toContain("shrink-0")
  })
})

describe("出處的日期", () => {
  const notes: ReportFootnote[] = [
    { n: 1, kind: "data", label: "臺灣證券交易所〈每日收盤行情-大盤統計資訊〉（2026），依政府資料開放授權條款第 1 版 11/17", outlet: null, url: null, date_label: "11/17" },
    { n: 2, kind: "data", label: "Forliosa 規則計算 11/17", outlet: null, url: null, date_label: "11/17" },
    { n: 3, kind: "filing", label: "公開資訊觀測站〈重大訊息〉11/17", outlet: null, url: null, date_label: "11/17" },
    { n: 4, kind: "web", label: "三大法人賣超台股547.25億元", outlet: "中央社", url: "https://www.cna.com.tw/news/afe/202611170159.aspx", date_label: "11/17 15:08" },
  ]
  const report = { footnotes: notes, sources: { data: [], web: [], disagreements: [], manual: [] } } as unknown as MarketReport

  it("資料與重大訊息只出現一次日期，報導照樣接發布時間", () => {
    const { container } = render(<ReportSources report={report} />)
    const items = container.querySelectorAll("li")
    for (const i of [0, 1, 2]) {
      expect(items[i]!.textContent!.match(/11\/17/g)).toHaveLength(1)
      expect(items[i]!.textContent).not.toContain("・11/17")
    }
    expect(items[3]!.textContent).toContain("中央社・")
    expect(items[3]!.textContent).toContain("・11/17 15:08")
  })
})
