import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { Concentration } from "@/api/types"
import { useViewAs, type ViewAsTarget } from "@/api/view-as"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"

/**
 * 帳本「配置」分段（產品負責人 2026-11-18，全部照建議）：第 4 個分段、圓環＋百分比清單、分組切換、帳戶選單、集中度、
 * 自己設的上限（桌面在集中度下面展開、手機是抽屜）、隱私模式遮金額、唯讀查看看得到不能改、持倉表頭的一行事實。
 */
let desktop = false
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  // 桌面（≥ 1024px）或手機，由每個測試決定
  window.matchMedia = ((query: string) => ({
    matches: desktop && query.includes("min-width: 1024px"), media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
beforeEach(() => {
  desktop = false
})
afterEach(async () => {
  vi.restoreAllMocks()
  cleanup()
  useViewAs.getState().set(null)
  act(() => usePrefs.setState({ privacyMode: false }))
  await api.putAllocationLimits({ holding: null, industry: null }).catch(() => undefined)
})

const T = { timeout: 5000 }
const DAD: ViewAsTarget = {
  delegation_id: "dlg_dad",
  owner: { user_id: "usr_dad", display_name: "爸爸", avatar_url: null },
  scope: "accounts",
  accounts: [{ id: "acc_dad_yuanta", name: "元大・爸爸" }],
}

function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}
const list = (name = "持股比例（每一檔）") => screen.findByRole("list", { name }, T)

describe("配置分段", () => {
  it("第 4 個分段；預設依每一檔，清單印出每一塊的百分比與金額；集中度只寫事實（沒設上限就沒有標示）", async () => {
    renderApp("/?view=allocation")
    const tabs = await screen.findByRole("tablist", { name: "帳本內容" }, T)
    expect(within(tabs).getByRole("tab", { name: "配置" })).toHaveAttribute("aria-selected", "true")
    expect(within(tabs).getByRole("tab", { name: "配置" })).toHaveAttribute("aria-keyshortcuts", "4")
    const rows = within(await list()).getAllByRole("listitem")
    // 9 檔：前 5 檔有顏色，其餘併成「其他 4 檔」
    expect(rows).toHaveLength(6)
    expect(rows[0]).toHaveTextContent("台積電")
    expect(rows[0]).toHaveTextContent("39.6%")
    expect(rows[0]).toHaveTextContent("NT$1,627,500")
    expect(rows[5]).toHaveTextContent("其他 4 檔")
    const groups = screen.getByRole("radiogroup", { name: "分組" })
    expect(within(groups).getAllByRole("radio").map((r) => r.textContent)).toEqual(["每一檔", "產業", "市場", "帳戶", "幣別", "類型"])
    expect(within(groups).getByRole("radio", { name: "每一檔" })).toHaveAttribute("aria-checked", "true")
    const stats = screen.getByLabelText("集中度")
    expect(stats).toHaveTextContent("最大一檔39.6%台積電")
    expect(stats).toHaveTextContent("前 5 大78.4%共 9 檔")
    expect(stats).toHaveTextContent("最大產業56.3%半導體業")
    expect(screen.queryByText(/超過/)).toBeNull()
    expect(screen.getByText("沒有設定")).toBeInTheDocument()
    // 圓環只是幫忙看：對螢幕報讀器隱藏
    expect(screen.getByTestId("allocation-donut")).toHaveAttribute("aria-hidden", "true")
  })

  it("「其他」點開看裡面有哪些；換成產業：ETF 收在一列、底下是類別，ETF 不算產業", async () => {
    renderApp("/?view=allocation")
    await list()
    const other = screen.getByRole("button", { name: /^其他 4 檔/ })
    await userEvent.click(other)
    expect(other).toHaveAttribute("aria-expanded", "true")
    const kids = within(screen.getByRole("list", { name: "其他 4 檔裡面" })).getAllByRole("listitem")
    expect(kids).toHaveLength(4)
    expect(kids.map((li) => li.textContent)).toEqual([expect.stringMatching(/^聯發科2454/), expect.stringMatching(/^NVIDIANVDA/), expect.stringMatching(/^Vanguard/), expect.stringMatching(/^AppleAAPL/)])
    await userEvent.click(screen.getByRole("radio", { name: "產業" }))
    const rows = within(await list("持股比例（產業）")).getAllByRole("listitem")
    expect(rows[0]).toHaveTextContent("半導體業")
    expect(rows[0]).toHaveTextContent("台積電、環球晶、聯發科")
    expect(screen.getByRole("button", { name: /^ETF/ })).toHaveAttribute("aria-expanded", "true")
    expect(within(screen.getByRole("list", { name: "ETF裡面" })).getByText("國內股票型")).toBeInTheDocument()
    expect(screen.getByText("美股半導體")).toBeInTheDocument()
    expect(screen.getByText("ETF 不算進產業，也不拆成分股。")).toBeInTheDocument()
  })

  it("只看一個帳戶：數字換成那個帳戶的（和持股一樣）", async () => {
    renderApp("/?view=allocation")
    await list()
    await userEvent.click(screen.getByRole("combobox", { name: "帳戶" }))
    await userEvent.click(await screen.findByRole("option", { name: "國泰・複委託" }, T))
    await waitFor(() => expect(within(screen.getByRole("list", { name: "持股比例（每一檔）" })).getAllByRole("listitem")).toHaveLength(3), T)
    const holdings = await api.getHoldings("acc_01JCATHAYUS")
    const total = holdings.reduce((s, h) => s + h.market_value, 0)
    const top = [...holdings].sort((a, b) => b.market_value - a.market_value)[0]!
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent(`${((top.market_value / total) * 100).toFixed(1)}%`)
    expect(screen.getByText(/^美股依匯率 \d+\.\d{2} 換成新台幣。$/)).toBeInTheDocument()
  })

  it("美股的匯率是後端給的、而且只在這個範圍裡有美元持股時才寫（只有台股的帳戶不寫）", async () => {
    renderApp("/?view=allocation")
    await list()
    const whole = await api.getAllocation()
    expect(screen.getByText(`美股依匯率 ${whole.fx.USD!.toFixed(2)} 換成新台幣。`)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("combobox", { name: "帳戶" }))
    await userEvent.click(await screen.findByRole("option", { name: "永豐・一般" }, T))
    await waitFor(() => expect(screen.queryByText(/美股依匯率/)).toBeNull(), T)
    expect((await api.getAllocation("acc_01JSINOPAC")).fx).toEqual({})
  })

  it("每一檔的說明寫「最大產業不含 ETF」（手機的集中度格子沒地方寫）", async () => {
    renderApp("/?view=allocation")
    await list()
    expect(screen.getByText("最大產業不含 ETF。ETF 算一檔，不拆成分股。")).toBeInTheDocument()
  })

  it("最大一檔是 ETF、超過的是別的個股：「超過上限」不接在 ETF 底下，放在你設定的上限那裡", async () => {
    await api.putAllocationLimits({ holding: 0.3, industry: null })
    const real = await api.getAllocation()
    const etfTop: Concentration = {
      ...real.concentration,
      top_holding: { symbol: "0050.TW", name: "元大台灣50", weight: 0.45, is_etf: true },
      limits: { holding: 0.3, industry: null },
      over_limits: [{ kind: "holding", key: "2330.TW", label: "台積電", weight: 0.32, limit: 0.3 }],
    }
    vi.spyOn(api, "getAllocation").mockResolvedValue({ ...real, concentration: etfTop })
    renderApp("/?view=allocation")
    await list()
    const top = screen.getByText("最大一檔").closest("div")!
    expect(top).toHaveTextContent("元大台灣50")
    expect(top).not.toHaveTextContent(/超過/)
    // 手機：清單下面「你設定的上限」那一列
    const row = screen.getByText("你設定的上限").parentElement!
    expect(row).toHaveTextContent("1 檔超過上限")
    expect(row).toHaveTextContent("1 檔超過你設定的 30%")
  })

  it("最大產業空白：持股不全是 ETF 時寫「沒有產業資料」，不寫「都是 ETF」", async () => {
    const real = await api.getAllocation()
    vi.spyOn(api, "getAllocation").mockResolvedValue({ ...real, concentration: { ...real.concentration, top_industry: null, etf_weight: 0.6 } })
    renderApp("/?view=allocation")
    await list()
    const cell = screen.getByText("最大產業").closest("div")!
    expect(cell).toHaveTextContent("沒有產業資料")
    expect(cell).not.toHaveTextContent("都是 ETF")
  })

  it("沒有持股：給下一步（記一筆、匯入）；只看某個帳戶時可以回到全部帳戶", async () => {
    const real = await api.getAllocation()
    const none = { ...real, market_value: 0, groups: { holding: [], industry: [], market: [], account: [], currency: [], type: [] } }
    vi.spyOn(api, "getAllocation").mockResolvedValue(none)
    renderApp("/?view=allocation")
    expect(await screen.findByText("目前沒有持股", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("記下持股後，這裡會列出每一檔佔多少。")).toBeInTheDocument()
    expect(within(document.getElementById("ledger-view")!).getByRole("button", { name: "記一筆" })).toBeInTheDocument()
    await userEvent.click(screen.getByRole("combobox", { name: "帳戶" }))
    await userEvent.click(await screen.findByRole("option", { name: "永豐・一般" }, T))
    expect(await screen.findByText("這個帳戶沒有持股", undefined, T)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "看全部帳戶" }))
    expect(await screen.findByText("目前沒有持股", undefined, T)).toBeInTheDocument()
  })

  it("隱私模式：看不到任何金額，百分比照常", async () => {
    act(() => usePrefs.setState({ privacyMode: true }))
    renderApp("/?view=allocation")
    const ul = await list()
    expect(ul.textContent).not.toMatch(/NT\$/)
    expect(ul.textContent).toContain("39.6%")
    expect(screen.getByTestId("allocation-donut").textContent).not.toMatch(/\d{1,3},\d{3}/)
  })

  it("桌面：在集中度下面設定上限；超過才標「超過你設定的 30%」（墨色細框，不用紅綠）；比例條多一條直線；清除上限", async () => {
    desktop = true
    renderApp("/?view=allocation")
    await list()
    await userEvent.click(screen.getByRole("button", { name: "設定上限" }))
    const form = screen.getByRole("region", { name: "設定上限" })
    const holding = within(form).getByLabelText(/單一個股/)
    expect(holding).toHaveFocus()
    // 欄位名稱帶「百分比」（畫面上的 % 是字尾）
    expect(holding).toHaveAccessibleName(/單一個股（百分比）/)
    await userEvent.type(within(form).getByLabelText(/單一產業/), "0.3")
    await userEvent.click(within(form).getByRole("button", { name: "儲存" }))
    // 錯的欄位連到錯誤訊息，焦點移到第一個錯的欄位
    const alert = within(form).getByRole("alert")
    expect(alert).toHaveTextContent("上限要在 1% 到 100% 之間")
    const industryInput = within(form).getByLabelText(/單一產業/)
    expect(industryInput).toHaveAttribute("aria-describedby", alert.id)
    expect(industryInput).toHaveFocus()
    expect(holding).not.toHaveAttribute("aria-describedby")
    await userEvent.clear(industryInput)
    await userEvent.type(holding, "300")
    await userEvent.click(within(form).getByRole("button", { name: "儲存" }))
    expect(within(form).getByRole("alert")).toHaveTextContent("上限要在 1% 到 100% 之間")
    expect(holding).toHaveFocus()
    await userEvent.clear(holding)
    await userEvent.type(holding, "30")
    await userEvent.type(within(form).getByLabelText(/單一產業/), "50")
    await userEvent.click(within(form).getByRole("button", { name: "儲存" }))
    await waitFor(() => expect(screen.queryByRole("region", { name: "設定上限" })).toBeNull(), T)
    expect(await screen.findByText("超過你設定的 30%", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("超過你設定的 50%")).toBeInTheDocument()
    const tag = screen.getByText("超過你設定的 30%").closest("span.border-ink")!
    expect(tag.className).not.toMatch(/rise|fall|red|green/)
    expect(screen.getByText(/直線是你設定的單一個股上限 30%/)).toBeInTheDocument()
    expect(within(screen.getAllByRole("listitem")[0]!).getByText("超過上限")).toBeInTheDocument()
    expect(await api.getAllocation()).toMatchObject({ concentration: { limits: { holding: 0.3, industry: 0.5 } } })
    // 「修改」是展開／收合：再按一次收起來，aria-controls 指到編輯區
    const edit = screen.getByRole("button", { name: "修改" })
    await userEvent.click(edit)
    expect(edit).toHaveAttribute("aria-expanded", "true")
    expect(edit).toHaveAttribute("aria-controls", screen.getByRole("region", { name: "設定上限" }).id)
    await userEvent.click(edit)
    expect(screen.queryByRole("region", { name: "設定上限" })).toBeNull()
    expect(edit).toHaveAttribute("aria-expanded", "false")
    // 清除
    await userEvent.click(screen.getByRole("button", { name: "修改" }))
    await userEvent.click(screen.getByRole("button", { name: "清除上限" }))
    await waitFor(() => expect(screen.queryByText(/超過你設定的/)).toBeNull(), T)
    expect((await api.getAllocation()).concentration.limits).toEqual({ holding: null, industry: null })
  })

  it("手機：清單下面一列「你設定的上限」，修改在抽屜裡", async () => {
    await api.putAllocationLimits({ holding: 0.3, industry: null })
    renderApp("/?view=allocation")
    await list()
    expect(await screen.findByText("超過上限 30%", undefined, T)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "修改" }))
    const sheet = await screen.findByRole("dialog", undefined, T)
    expect(within(sheet).getByText("設定上限")).toBeInTheDocument()
    // 打開時焦點在第一格（和記一筆一樣），不留在後面的「修改」上
    await waitFor(() => expect(within(sheet).getByLabelText(/單一個股/)).toHaveFocus(), T)
    expect(within(sheet).getByLabelText(/單一個股/)).toHaveValue("30")
    expect(within(sheet).getByLabelText(/單一產業/)).toHaveValue("")
  })

  it("查看別人的資產（唯讀）：看得到配置與授權者的上限，不能改", async () => {
    useViewAs.getState().set(DAD)
    renderApp("/?view=allocation")
    await list()
    expect(screen.getByText("爸爸設定的上限")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /設定上限|修改/ })).toBeNull()
  })
})

describe("帳本到配置", () => {
  it("集中度只在配置分段：持倉上面不再有一行「最大一檔」（產品負責人 2026-11-19 選 B，首屏給持倉）", async () => {
    renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    expect(await screen.findByRole("table", { name: "持倉" }, T)).toBeInTheDocument()
    expect(screen.queryByText("最大一檔")).toBeNull()
    expect(screen.queryByRole("link", { name: "看配置" })).toBeNull()
  })

  it("數字鍵 4 切到配置", async () => {
    const router = renderApp("/")
    await screen.findByRole("tablist", { name: "帳本內容" }, T)
    fireEvent.keyDown(document.body, { key: "4" })
    await waitFor(() => expect((router.state.location.search as { view?: string }).view).toBe("allocation"))
  })
})
