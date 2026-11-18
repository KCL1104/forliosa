import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { useAi } from "@/ai/store"
import { api } from "@/api"
import { createMockAdapter, type MockOptions } from "@/api/mock/adapter"
import type { ForliosaApi } from "@/api/types"
import { createAppRouter } from "@/router"

vi.mock("@/pages/stock/PriceChart", () => ({ PriceChart: () => null }))

/**
 * 群組頻道的推播開關（2026-11-18 產品負責人選 A）：每個頻道只有四個——交易動態、盤前（盤前重點＋昨日你的群組）、盤後、
 * 週報（市場週報＋這週的群組週報）；所有群組都一樣，只有擁有者能改。群組「報告」分頁：今天的盤前重點出來了、最新的日報是
 * 前一個交易日的，那一則就是「昨日你的群組」。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
const resetAi = () => useAi.setState({ panelOpen: true, quietPanelOpen: false, mobileOpen: false, threadId: null, threads: [], drafts: {}, focusDraftId: null, ownerId: null })
beforeEach(() => act(resetAi))
afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
  act(resetAi)
})

const T = { timeout: 6000 }

function mount(options: MockOptions = {}) {
  const adapter = createMockAdapter({ latency: [0, 0], ...options })
  const spies = {} as Record<keyof ForliosaApi, ReturnType<typeof vi.spyOn>>
  for (const key of Object.keys(adapter) as (keyof ForliosaApi)[]) {
    const fn = adapter[key]
    if (typeof fn === "function") spies[key] = vi.spyOn(api as unknown as Record<string, (...args: unknown[]) => unknown>, key).mockImplementation(fn as (...args: unknown[]) => unknown)
  }
  return spies
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

const SWITCH_NAMES = ["交易動態", "盤前（交易日 7:30）", "盤後（交易日 16:00）", "週報（週日 18:00）"]

/** 一個頻道裡的開關（照畫面順序）是四個開關裡的哪一個；不是四個之一的寫「?」 */
const switchNames = (section: HTMLElement) =>
  within(section)
    .getAllByRole("switch")
    .map((sw) => SWITCH_NAMES.find((name) => within(section).queryByRole("switch", { name }) === sw) ?? "?")

describe("頻道的四個開關（2026-11-18 產品負責人選 A）", () => {
  it("對全站公開：交易動態、盤前、盤後、週報四列（各一行說明），沒有重複的「日報」「市場週報」；擁有者改了送出", async () => {
    const user = userEvent.setup()
    const spies = mount({ reports: "public" })
    renderApp("/groups/grp_family?tab=channels")
    const discord = (await screen.findByRole("heading", { name: "Discord" }, T)).closest("section")!
    const pre = await within(discord).findByRole("switch", { name: "盤前（交易日 7:30）" }, T)
    expect(switchNames(discord)).toEqual(SWITCH_NAMES)
    expect(pre).toHaveAttribute("aria-checked", "false")
    expect(within(discord).getByRole("switch", { name: "交易動態" })).toHaveAttribute("aria-checked", "true")
    expect(within(discord).getByRole("switch", { name: "盤後（交易日 16:00）" })).toHaveAttribute("aria-checked", "false")
    expect(within(discord).getByRole("switch", { name: "週報（週日 18:00）" })).toHaveAttribute("aria-checked", "true")
    for (const line of [
      "成員的買賣，交易建立 15 分鐘後送出。",
      "盤前重點，加上昨日你的群組（加值群組）。",
      "盤後重點。",
      "市場週報，加上這週的群組週報。",
      "推到頻道的是文字與連結，報告本文人人相同。",
    ]) {
      expect(within(discord).getByText(line)).toBeInTheDocument()
    }
    for (const gone of ["日報", "市場週報（週日 18:00）", "盤前重點（交易日 7:30）", "週報"]) {
      expect(within(discord).queryByRole("switch", { name: gone })).toBeNull()
    }
    await user.click(pre)
    await waitFor(() => expect(spies.patchDiscord).toHaveBeenCalledWith("grp_family", { notify_premarket: true }), T)
    await waitFor(() => expect(within(discord).getByRole("switch", { name: "盤前（交易日 7:30）" })).toHaveAttribute("aria-checked", "true"), T)
  })

  it("試跑期間（只有站方管理員看得到報告）：照樣四列，說明盤前、週報先只送群組的部分", async () => {
    mount()
    renderApp("/groups/grp_family?tab=channels")
    const discord = (await screen.findByRole("heading", { name: "Discord" }, T)).closest("section")!
    await within(discord).findByRole("switch", { name: "交易動態" }, T)
    expect(switchNames(discord)).toEqual(SWITCH_NAMES)
    expect(within(discord).getByText("市場報告還沒開放：盤前、週報先只送群組的部分，盤後先不送。")).toBeInTheDocument()
  })

  it("免費群組也是同樣四列（沒有另外的「日報」）", async () => {
    mount({ reports: "public" })
    renderApp("/groups/grp_friends?tab=channels")
    const telegram = (await screen.findByRole("heading", { name: "Telegram" }, T)).closest("section")!
    await within(telegram).findByRole("switch", { name: "週報（週日 18:00）" }, T)
    expect(switchNames(telegram)).toEqual(SWITCH_NAMES)
  })

  it("不是擁有者：看得到，不能改", async () => {
    mount({ reports: "public" })
    renderApp("/groups/grp_friends?tab=channels")
    const telegram = (await screen.findByRole("heading", { name: "Telegram" }, T)).closest("section")!
    const weekly = await within(telegram).findByRole("switch", { name: "週報（週日 18:00）" }, T)
    expect(weekly).toHaveAttribute("aria-disabled", "true")
  })

  it("設定 Discord：表單也是四個開關（交易動態、週報開，盤前、盤後關），一起送出", async () => {
    const user = userEvent.setup()
    const spies = mount({ reports: "public" })
    renderApp("/groups/grp_hiking?tab=channels")
    const input = await screen.findByLabelText("Webhook 網址", undefined, T)
    const form = input.closest("form")!
    const labels = within(form).getAllByRole("switch").map((s) => s.closest("label")!.textContent)
    expect(labels).toEqual(["送交易動態", "送盤前", "送盤後", "送週報"])
    await user.click(within(form).getAllByRole("switch")[1]!)
    await user.type(input, "https://discord.com/api/webhooks/123/abcDEF")
    await user.click(within(form).getByRole("button", { name: "儲存並送測試訊息" }))
    await waitFor(() => expect(spies.putDiscord).toHaveBeenCalledWith("grp_hiking", {
      webhook_url: "https://discord.com/api/webhooks/123/abcDEF", notify_trades: true, notify_premarket: true, notify_close: false, notify_weekly: true,
    }), T)
  })
})

describe("換一個 webhook", () => {
  it("表單的四個開關照現在的值（收著時改過的也算），不會把剛打開的盤前改回去", async () => {
    const user = userEvent.setup()
    const spies = mount({ reports: "public" })
    renderApp("/groups/grp_family?tab=channels")
    const discord = (await screen.findByRole("heading", { name: "Discord" }, T)).closest("section")!
    await user.click(await within(discord).findByRole("switch", { name: "盤前（交易日 7:30）" }, T))
    await waitFor(() => expect(within(discord).getByRole("switch", { name: "盤前（交易日 7:30）" })).toHaveAttribute("aria-checked", "true"), T)
    await user.click(within(discord).getByRole("button", { name: "換一個 webhook" }))
    const form = (await within(discord).findByLabelText("Webhook 網址", undefined, T)).closest("form")!
    expect(within(form).getAllByRole("switch").map((s) => s.getAttribute("aria-checked"))).toEqual(["true", "true", "false", "true"])
    await user.type(within(form).getByLabelText("Webhook 網址"), "https://discord.com/api/webhooks/123/abcDEF")
    await user.click(within(form).getByRole("button", { name: "儲存並送測試訊息" }))
    await waitFor(() => expect(spies.putDiscord).toHaveBeenCalledWith("grp_family", expect.objectContaining({ notify_premarket: true, notify_weekly: true })), T)
  })
})

describe("群組的報告分頁：昨日你的群組", () => {
  it("今天的盤前重點出來了、最新的日報是前一個交易日的：那一則叫「昨日你的群組」，旁邊連到盤前重點", async () => {
    mount({ reports: "public", market: "open" })
    renderApp("/groups/grp_family?tab=digests")
    const heading = await screen.findByRole("heading", { level: 2, name: "昨日你的群組" }, T)
    const article = heading.closest("article")!
    expect(within(article).getByText(/^11\/12（四）・/)).toBeInTheDocument()
    expect(within(article).getByRole("link", { name: "盤前重點 11/13（五） →" })).toHaveAttribute("href", "/market/reports/mrp_premarket_20261113")
    // 較早的日報照舊寫日期
    expect(screen.getByRole("heading", { level: 2, name: "11/11（三） 日報" })).toBeInTheDocument()
  })

  it("日報就是今天的（收盤後）：照舊寫「11/12（四） 日報」", async () => {
    mount({ reports: "public" })
    renderApp("/groups/grp_family?tab=digests")
    expect(await screen.findByRole("heading", { level: 2, name: "11/12（四） 日報" }, T)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { level: 2, name: "昨日你的群組" })).toBeNull()
  })
})
