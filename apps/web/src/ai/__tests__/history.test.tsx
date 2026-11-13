import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { HistoryList } from "@/ai/HistoryList"
import { useAi } from "@/ai/store"
import type { Thread } from "@/ai/types"

// 刪除後的「復原」是 Sonner 通知的動作：把通知的參數接下來，測試直接按「復原」
const toasts = vi.hoisted(() => [] as { title: string; opts?: { action?: { label: string; onClick: () => void } } }[])
vi.mock("sonner", () => ({
  toast: Object.assign((title: string, opts?: (typeof toasts)[number]["opts"]) => toasts.push({ title, opts }), { error: vi.fn(), success: vi.fn() }),
}))

const at = "2026-11-12T20:00:00+08:00"
const mine: Thread = { id: "thr_mine", title: "我自己問過的問題", updatedAt: at, messages: [{ id: "m1", role: "user", text: "我自己問過的問題", at }] }

const view = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HistoryList onReplay={() => undefined} />
    </QueryClientProvider>,
  )

describe("紀錄：發起新對話是一般按鈕；刪除對話有「復原」；沒有示範的 AI 任務", () => {
  afterEach(() => {
    toasts.length = 0
    act(() => useAi.setState({ threads: [], drafts: {}, threadId: null, hiddenThreadIds: [] }))
  })

  it("發起新對話是按鈕（不是標題）；沒有「AI 任務」區塊與示範說明", () => {
    view()
    expect(screen.getByRole("button", { name: "發起新對話" })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "發起新對話" })).not.toBeInTheDocument()
    expect(screen.queryByText("AI 任務")).not.toBeInTheDocument()
    expect(screen.queryByText(/示範資料，排程還沒開放/)).not.toBeInTheDocument()
  })

  it("刪除自己的對話 → 通知「已刪除對話」附「復原」→ 按下放回原位", () => {
    act(() => useAi.setState({ threads: [mine], threadId: null }))
    view()
    const list = screen.getByRole("list", { name: "對話" })
    expect(within(list).getAllByRole("listitem")[0]!.textContent).toContain("我自己問過的問題")
    fireEvent.click(screen.getByRole("button", { name: "刪除對話「我自己問過的問題」" }))
    expect(useAi.getState().threads).toHaveLength(0)
    expect(screen.queryByText("我自己問過的問題")).not.toBeInTheDocument()
    const t = toasts.at(-1)!
    expect(t.title).toBe("已刪除對話")
    expect(t.opts?.action?.label).toBe("復原")
    act(() => t.opts!.action!.onClick())
    expect(useAi.getState().threads.map((x) => x.id)).toEqual(["thr_mine"])
    expect(within(screen.getByRole("list", { name: "對話" })).getAllByRole("listitem")[0]!.textContent).toContain("我自己問過的問題")
  })

  it("示範紀錄：刪除先藏起來，復原再出現", () => {
    view()
    const name = "刪除對話「00878 下次除息能領多少？」"
    fireEvent.click(screen.getByRole("button", { name }))
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument()
    act(() => toasts.at(-1)!.opts!.action!.onClick())
    expect(screen.getByRole("button", { name })).toBeInTheDocument()
  })
})
