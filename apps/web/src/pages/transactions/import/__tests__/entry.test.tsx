import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { User, UserPlan } from "@/api/types"
import { Composer } from "@/ai/Composer"
import { type AiUsage } from "@/ai/remote"
import { aiKeys } from "@/ai/remote-hooks"
import { useUi } from "@/app/ui-store"

/**
 * 會員和一般帳號只差每日收盤簡報與問 AI 次數（產品負責人 2026-11-17）：免費帳號也有匯入對帳單與深度搜尋。
 * 匯入的入口照 `/me` 的 `plan.statement_import`（不看 tier）；深度搜尋的切換鈕照 `/ai/usage` 的 `deep_search_cost`（不看 plan）。
 */
const T = { timeout: 8000 }
const FREE: UserPlan = { tier: "free", until: null, deep_search: true, daily_briefing: false, statement_import: true }

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {}
  Element.prototype.setPointerCapture ??= () => {}
  Element.prototype.releasePointerCapture ??= () => {}
  Element.prototype.hasPointerCapture ??= () => false
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  act(() => useUi.getState().closeImport())
})

async function renderComposer(plan: UserPlan | null | undefined, usage?: Partial<AiUsage>) {
  const me: User = await api.getMe()
  vi.spyOn(api, "getMe").mockResolvedValue({ ...me, plan })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // mock 模式不打 `/ai/usage`：直接放進快取，當成後端回的
  if (usage) qc.setQueryData(aiKeys.usage, usage)
  const onForm = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <Composer variant="panel" placeholder="提出問題" onSubmit={() => undefined} onForm={onForm} />
    </QueryClientProvider>,
  )
  return { onForm }
}

describe("免費帳號的匯入對帳單入口（「＋」）", () => {
  it("plan.statement_import 是 true：「＋」是兩項的選單（記一筆、匯入對帳單），匯入那一項打開匯入", async () => {
    const user = userEvent.setup()
    await renderComposer(FREE)
    await user.click(await screen.findByRole("button", { name: "記一筆或匯入對帳單" }, T))
    const menu = await screen.findByRole("menu", undefined, T)
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["記一筆", "匯入對帳單"])
    await user.click(within(menu).getByRole("menuitem", { name: "匯入對帳單" }))
    expect(useUi.getState().importOpen).toBe(true)
  })

  it.each([
    ["false", { ...FREE, statement_import: false }],
    ["沒有這個欄位（舊版後端）", { tier: "free", until: null, deep_search: true, daily_briefing: false } as UserPlan],
  ])("plan.statement_import %s：「＋」直接打開記一筆，沒有匯入", async (_label, plan) => {
    const user = userEvent.setup()
    const { onForm } = await renderComposer(plan)
    const plus = await screen.findByRole("button", { name: "用表單記一筆" }, T)
    expect(screen.queryByRole("button", { name: "記一筆或匯入對帳單" })).toBeNull()
    await user.click(plus)
    expect(onForm).toHaveBeenCalledOnce()
    expect(screen.queryByRole("menu")).toBeNull()
    expect(useUi.getState().importOpen).toBe(false)
  })
})

describe("免費帳號的深度搜尋", () => {
  const usage = (deep_search_cost: number | null): Partial<AiUsage> => ({
    plan: "free", messages_today: 0, daily_message_limit: 3, messages_remaining: 3, deep_search_cost, deep_search_members_only: false,
  })

  it("後端給了題數（預設 3）：切換鈕在，開著時說用掉 3 題", async () => {
    const user = userEvent.setup()
    await renderComposer(FREE, usage(3))
    await user.click(await screen.findByRole("button", { name: "深度搜尋" }, T))
    expect(screen.getByText("多查幾輪資料，寫成一份整理，用掉 3 題。")).toBeInTheDocument()
  })

  it("後端說現在不能用（null：省錢模式或沒開網路搜尋）：沒有切換鈕，也沒有「會員功能」的字", async () => {
    await renderComposer(FREE, usage(null))
    await screen.findByRole("button", { name: "記一筆或匯入對帳單" }, T)
    expect(screen.queryByRole("button", { name: "深度搜尋" })).toBeNull()
    expect(screen.queryByText(/會員/)).toBeNull()
  })
})
