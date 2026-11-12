import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { NewsItem } from "@/api/types"
import { mediaNews, officialNews, outletLabel, relativeTime } from "@/lib/news"
import { NewsCoverage } from "../NewsCoverage"

function withQueries(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const NOW = new Date("2026-11-12T13:30:00+08:00")

afterEach(() => {
  vi.restoreAllMocks()
})

describe("新聞報導的顯示規則", () => {
  it("相對時間：分鐘、小時、天，7 天以上與只有日期時顯示日期", () => {
    expect(relativeTime("2026-11-12T13:29:40+08:00", NOW)).toBe("剛剛")
    expect(relativeTime("2026-11-12T13:12:00+08:00", NOW)).toBe("18 分鐘前")
    expect(relativeTime("2026-11-12T10:30:00+08:00", NOW)).toBe("3 小時前")
    expect(relativeTime("2026-11-10T09:00:00+08:00", NOW)).toBe("2 天前")
    expect(relativeTime("2026-11-02T09:00:00+08:00", NOW)).toBe("11/2")
    expect(relativeTime("2026-11-12T00:00:00+08:00", NOW, true)).toBe("今天")
    expect(relativeTime("2026-11-09T00:00:00+08:00", NOW, true)).toBe("11/9")
  })
  it("公告與新聞報導分開；Yahoo股市保留原始媒體", () => {
    const items: NewsItem[] = [
      { published_at: "2026-11-11T17:30:00+08:00", title: "公告", source: "公告", url: "https://mops.twse.com.tw/", category: "material_info" },
      { published_at: "2026-11-12T08:00:00+08:00", title: "舊", source: "GDELT", outlet: "中央社", url: "https://www.cna.com.tw/a", category: "media" },
      { published_at: "2026-11-12T10:00:00+08:00", title: "新", source: "Yahoo股市", outlet: "MoneyDJ", url: "https://tw.stock.yahoo.com/news/a", category: "media" },
    ]
    expect(officialNews(items).map((n) => n.title)).toEqual(["公告"])
    expect(mediaNews(items).map((n) => n.title)).toEqual(["新", "舊"])
    expect(outletLabel(items[2]!)).toBe("MoneyDJ（Yahoo股市）")
    expect(outletLabel(items[1]!)).toBe("中央社")
  })
})

describe("總覽的「新聞報導」", () => {
  it("媒體・時間＋原標題連到原文（另開新視窗、noopener）；8 則後「顯示更多」；引用 GDELT", async () => {
    const tsmc = await api.getInstrument("2330.TW")
    withQueries(<NewsCoverage inst={tsmc} />)
    const section = await screen.findByRole("region", { name: "新聞報導" }, { timeout: 3000 })
    const links = within(section).getAllByRole("link").filter((a) => !a.getAttribute("href")?.includes("gdeltproject"))
    expect(links).toHaveLength(8)
    for (const a of links) {
      expect(a).toHaveAttribute("target", "_blank")
      expect(a.getAttribute("rel")).toContain("noopener")
      expect(a.getAttribute("rel")).toContain("noreferrer")
    }
    expect(section.querySelector("img")).toBeNull()
    expect(within(section).getAllByText("示範財經日報").length).toBeGreaterThan(0)
    expect(within(section).getByText("1 小時前")).toBeInTheDocument()
    const gdelt = within(section).getByRole("link", { name: /The GDELT Project/ })
    expect(gdelt).toHaveAttribute("href", "https://www.gdeltproject.org/")
    fireEvent.click(within(section).getByRole("button", { name: /顯示更多/ }))
    const all = within(section).getAllByRole("link").filter((a) => !a.getAttribute("href")?.includes("gdeltproject"))
    expect(all).toHaveLength(12)
    expect(within(section).queryByRole("button", { name: /顯示更多/ })).toBeNull()
    expect(section.textContent).toContain("AI 網路搜尋")
  })
  it("請求失敗時顯示錯誤與重試，不說成「沒有報導」", async () => {
    const tsmc = await api.getInstrument("2330.TW")
    const spy = vi.spyOn(api, "getNews").mockRejectedValueOnce(new Error("network"))
    withQueries(<NewsCoverage inst={tsmc} />)
    const alert = await screen.findByRole("alert", undefined, { timeout: 3000 })
    expect(alert.textContent).toContain("新聞報導沒有載入")
    expect(screen.queryByText(/最近沒有找到/)).toBeNull()
    fireEvent.click(within(alert).getByRole("button", { name: /重新載入/ }))
    // 重試時先回到載入中，成功後才是清單（區塊重新掛上，所以重新找）
    await screen.findAllByText("示範財經日報", undefined, { timeout: 3000 })
    expect(within(screen.getByRole("region", { name: "新聞報導" })).queryByRole("alert")).toBeNull()
    expect(spy).toHaveBeenCalledTimes(2)
  })
  it("沒有報導時說明，不留空白", async () => {
    const honhai = await api.getInstrument("2317.TW")
    withQueries(<NewsCoverage inst={honhai} />)
    expect(await screen.findByText(/最近沒有找到鴻海的媒體報導/, undefined, { timeout: 3000 })).toBeInTheDocument()
  })
})
