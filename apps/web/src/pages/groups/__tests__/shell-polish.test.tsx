import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import { api } from "@/api"
import type { Group } from "@/api/types"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { DateCell } from "@/components/date-cell"
import { DividendsView } from "@/pages/ledger/DividendsView"
import { trendMissingReason } from "@/pages/ledger/trend-reason"
import { Profile } from "@/pages/settings/Profile"
import { FeedTab } from "../tabs/FeedTab"
import { RankingTab } from "../tabs/RankingTab"

/**
 * 外殼與帳本／群組的潤飾：來源只在頁尾出現一次、排行的總報酬是一欄主數字（不是小字第二行）、
 * 動態的動作有看得到的字、帳本清單第一欄是聯絡簿的日期格（日期＋星期）、
 * 走勢的原因只說後端講過的、簽名格只在改過之後出現。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  // jsdom 沒有 matchMedia：一律當手機（< 1024px）
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => cleanup())

const T = { timeout: 4000 }
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

function renderInRouter(ui: React.ReactNode) {
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(
    <QueryClientProvider client={client()}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}

describe("群組排行", () => {
  let family: Group
  beforeAll(async () => {
    family = await api.getGroup("grp_family")
  })

  it("資料來源不逐條列在排行下面，而是登記到頁尾（展開才看到）", async () => {
    const board = await api.getLeaderboard("grp_family", "day")
    expect(board.sources.length).toBeGreaterThan(0)
    const user = userEvent.setup()
    renderInRouter(
      <SourcesProvider>
        <RankingTab group={family} />
        <SourcesFooter />
      </SourcesProvider>,
    )
    await screen.findByRole("table", { name: "今日排行" }, T)
    // 原文的顯名聲明不再直接出現在畫面上
    expect(document.body.textContent).not.toContain(board.sources[0]!)
    const toggle = await screen.findByRole("button", { name: /資料來源與授權/ }, T)
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    await user.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByRole("link", { name: "完整顯名聲明" })).toHaveAttribute("href", "/data-sources")
    expect(screen.getAllByText(/臺灣證券交易所/).length).toBeGreaterThan(0)
  })

  it("手機排行：每一列都有期間報酬與總報酬兩個數字（總報酬不是小字第二行）", async () => {
    renderInRouter(<RankingTab group={family} />)
    const list = await screen.findByRole("list", { name: "今日排行" }, T)
    const dad = await within(list).findByText("爸爸", undefined, T)
    const row = dad.closest("li")!
    expect(within(row).getByText("今日報酬")).toBeInTheDocument()
    expect(within(row).getByText("總報酬（含股利）")).toBeInTheDocument()
    // 兩個數字都有 ▲▼（色弱可辨），而且是同一列的兩欄
    expect(row.textContent!.match(/[▲▼]/g)?.length).toBe(2)
  })
})

describe("群組動態", () => {
  it("加表情和留言一樣有看得到的字，名稱與看得到的字一致", async () => {
    const family = await api.getGroup("grp_family")
    renderInRouter(<FeedTab group={family} />)
    const list = await screen.findByRole("list", { name: "動態" }, T)
    const add = (await within(list).findAllByRole("button", { name: "加表情" }, T))[0]!
    expect(add.textContent).toContain("表情")
  })
})

describe("聯絡簿的日期格", () => {
  it("日期（墨色）＋星期（.weekday），2026-11-12 是星期四", () => {
    render(<DateCell date="2026-11-12" />)
    const cell = document.querySelector(".date-cell")!
    expect(cell.textContent).toBe("11/12（四）")
    expect(cell.querySelector(".weekday")!.textContent).toBe("（四）")
  })

  it("股利的已入帳清單：每一列的第一欄都是日期格", async () => {
    renderInRouter(<DividendsView />)
    const received = await screen.findByRole("region", { name: "2026 年" }, { timeout: 8000 })
    const rows = within(received).getAllByRole("listitem")
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) expect(row.firstElementChild).toHaveClass("date-cell")
  })
})

describe("帳本主數字列：走勢畫不出來的原因", () => {
  it("只說後端 notes 講過的原因；沒講就不寫", () => {
    expect(trendMissingReason(["AAPL：美股目前沒有可商用的行情來源，不提供價格資料，含美股時無法計算績效", "資料累積中：自 2026-10-01 起存檔"])).toBe("含美股，算不出來")
    expect(trendMissingReason(["資料累積中：自 2026-10-01 起存檔"])).toBe("資料還不夠")
    expect(trendMissingReason([])).toBeNull()
    expect(trendMissingReason(["其他說明"])).toBeNull()
  })
})

describe("設定：顯示名稱", () => {
  it("沒改名字時沒有「儲存」；改了才出現簽名格，清空時不能按", async () => {
    const user = userEvent.setup()
    renderInRouter(<Profile />)
    const input = await screen.findByLabelText("顯示名稱", undefined, T)
    expect(screen.queryByRole("button", { name: "儲存" })).toBeNull()
    await user.type(input, "2")
    expect(screen.getByRole("button", { name: "儲存" })).toBeEnabled()
    await user.clear(input)
    expect(screen.getByRole("button", { name: "儲存" })).toBeDisabled()
  })
})
