import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import { api } from "@/api"
import type { Group } from "@/api/types"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { EmptyState, ErrorState } from "@/components/states"
import { DateCell } from "@/components/date-cell"
import { DividendsView } from "@/pages/ledger/DividendsView"
import { trendMissingReason } from "@/pages/ledger/trend-reason"
import { Profile } from "@/pages/settings/Profile"
import { FeedTab } from "../tabs/FeedTab"
import { RankingTab } from "../tabs/RankingTab"

/**
 * 外殼與帳本／群組的潤飾：來源只在頁尾出現一次、排行的期間報酬是主數字（名次依它排，表頭有排序箭頭）、
 * 總報酬是一般的一欄（不是小字第二行）、自己的那一列用字標示（不用底色）、
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

  it("名次依期間報酬排：期間欄是主數字，表頭帶 aria-sort 與箭頭；總報酬是一般字級、不排序", async () => {
    renderInRouter(<RankingTab group={family} />)
    const table = await screen.findByRole("table", { name: "今日排行" }, T)
    const period = within(table).getByRole("columnheader", { name: "今日報酬" })
    expect(period).toHaveAttribute("aria-sort", "descending")
    // 排序用箭頭圖示，不用 ▲▼（那是漲跌的符號）
    expect(period.querySelector("svg")).not.toBeNull()
    expect(period.textContent).not.toMatch(/[▲▼]/)
    const total = within(table).getByRole("columnheader", { name: "總報酬（含股利）" })
    expect(total).not.toHaveAttribute("aria-sort")
    expect(total.querySelector("svg")).toBeNull()
    // 每一列：期間報酬那一格比總報酬那一格大而且粗；兩格都有 ▲▼
    const dad = (await within(table).findByText("爸爸", undefined, T)).closest("tr")!
    const cells = within(dad).getAllByRole("cell")
    const [periodCell, totalCell] = [cells.at(-2)!, cells.at(-1)!]
    expect(periodCell).toHaveClass("text-xl", "font-semibold")
    expect(totalCell).toHaveClass("text-base")
    expect(totalCell).not.toHaveClass("font-semibold")
    expect(periodCell.textContent).toMatch(/[▲▼]/)
    expect(totalCell.textContent).toMatch(/[▲▼]/)
    // 期間報酬由高到低（算不出來的排最後）
    const values = within(table)
      .getAllByRole("row")
      // 有名次的列（對照的列沒有名次）
      .filter((r) => /^\d+$/.test(within(r).queryAllByRole("cell")[0]?.textContent ?? ""))
      .map((r) => within(r).getAllByRole("cell").at(-2)!.textContent ?? "")
      .filter((t) => /%/.test(t))
      .map((t) => Number(t.replace(/[^\d.]/g, "")) * (t.includes("▼") ? -1 : 1))
    expect(values.length).toBeGreaterThan(1)
    expect([...values].sort((a, b) => b - a)).toEqual(values)
  })

  it("不排名次的群組：沒有名次欄，期間欄沒有 aria-sort 與箭頭", async () => {
    const friends = await api.getGroup("grp_friends")
    renderInRouter(<RankingTab group={friends} />)
    const table = await screen.findByRole("table", { name: "今日排行" }, T)
    expect(within(table).queryByRole("columnheader", { name: "名次" })).toBeNull()
    const period = within(table).getByRole("columnheader", { name: "今日報酬" })
    expect(period).not.toHaveAttribute("aria-sort")
    expect(period.querySelector("svg")).toBeNull()
  })

  it("自己的那一列用字標示（名字加粗＋「（你）」），不用淡墨底——那是 hover 的樣子", async () => {
    renderInRouter(<RankingTab group={family} />)
    const table = await screen.findByRole("table", { name: "今日排行" }, T)
    const me = (await within(table).findByText("（你）", undefined, T)).closest("tr")!
    expect(me.className).not.toMatch(/bg-hov/)
    expect(within(me).getByText("示範使用者")).toHaveClass("font-bold")
    const dad = within(table).getByText("爸爸")
    expect(dad).not.toHaveClass("font-bold")
    // 手機的清單也一樣
    const list = screen.getByRole("list", { name: "今日排行" })
    const mine = within(list).getByText("（你）").closest("li")!
    expect(mine.className).not.toMatch(/bg-hov/)
  })
})

describe("群組動態", () => {
  it("加表情和留言一樣有看得到的字，名稱與看得到的字一致", async () => {
    const family = await api.getGroup("grp_family")
    renderInRouter(<FeedTab group={family} />)
    const list = await screen.findByRole("list", { name: "動態" }, T)
    const add = (await within(list).findAllByRole("button", { name: "加表情" }, T))[0]!
    expect(add.textContent).toContain("表情")
    // 有字的按鈕前面不放裝飾圖示
    expect(add.querySelector("svg")).toBeNull()
    const comments = within(list).getAllByRole("button", { name: /^留言/ })[0]!
    expect(comments.querySelector("svg")).toBeNull()
    expect(comments).toHaveAttribute("aria-expanded", "false")
  })
})

describe("空狀態與錯誤：全站同一種樣子", () => {
  it("上下實線格線、沒有虛線與外框；標題 15px 600；錯誤可以重試，按鈕沒有圖示", async () => {
    const user = userEvent.setup()
    let retried = 0
    render(
      <>
        <EmptyState title="還沒有週報" description="每週六晚上整理。" />
        <ErrorState error={new Error("x")} onRetry={() => retried++} />
      </>,
    )
    const empty = screen.getByText("還沒有週報").parentElement!
    const alert = screen.getByRole("alert")
    for (const box of [empty, alert]) {
      expect(box).toHaveClass("border-y", "border-rule")
      expect(box.className).not.toMatch(/dashed|rounded|bg-/)
    }
    expect(screen.getByText("還沒有週報")).toHaveClass("text-base", "font-semibold", "text-ink")
    // 原因是要讀的句子：15px 墨色（淡墨小字只給日期、單位這類標註）
    expect(screen.getByText("每週六晚上整理。")).toHaveClass("text-base", "text-ink")
    const retry = within(alert).getByRole("button", { name: "重新載入" })
    expect(retry.querySelector("svg")).toBeNull()
    await user.click(retry)
    expect(retried).toBe(1)
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
    expect(trendMissingReason(["AAPL：美股沒有報價，含美股的績效算不出來", "資料從 2026/10/01 開始；持股期間有幾天沒有收盤價，績效算不出來"])).toBe("含美股，新台幣帳戶的在績效")
    expect(trendMissingReason(["資料從 2026/10/01 開始"])).toBe("資料還不夠")
    // 舊版後端的寫法也認得（前後端分開部署）
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
