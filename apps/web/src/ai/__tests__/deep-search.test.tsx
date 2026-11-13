import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it } from "vitest"
import { api } from "@/api"
import type { Instrument } from "@/api/types"
import { Composer } from "@/ai/Composer"
import { Conversation } from "@/ai/Conversation"
import { buildLocalDeepReport, deepSearchCost, deepSearchHint, deepTarget } from "@/ai/deep-search"
import { threadFromServer, type ThreadDetail } from "@/ai/remote"
import type { useAiRunner } from "@/ai/runner"
import { useAi } from "@/ai/store"
import type { Thread } from "@/ai/types"

/**
 * 深度搜尋：輸入框的切換鈕（開著時多一句話、送出後關掉）、那一題在對話裡的標示、對話紀錄帶回來的 mode，
 * 以及 mock 模式的示範整理（兩三句、短標題、每點一行、附來源）。
 */
const withQuery = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})
afterEach(() => {
  cleanup()
  useAi.getState().setDeepNext(false)
})

describe("輸入框的「深度搜尋」", () => {
  it("是一顆文字的切換鈕（沒有圖示）；開著時輸入框下面多一句話，關掉就沒有", () => {
    withQuery(<Composer variant="panel" placeholder="提出問題" onSubmit={() => undefined} onForm={() => undefined} />)
    const toggle = screen.getByRole("button", { name: "深度搜尋" })
    expect(toggle).toHaveAttribute("aria-pressed", "false")
    expect(toggle.querySelector("svg")).toBeNull()
    expect(screen.queryByText(/用掉 5 題/)).toBeNull()
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-pressed", "true")
    expect(useAi.getState().deepNext).toBe(true)
    const hint = screen.getByText("多查幾輪資料，寫成一份整理，用掉 5 題。")
    expect(hint).toHaveClass("text-base", "text-ink")
    // 畫面上的鍵盤提示縮成「Enter 送出」（旁邊放不下整句）；螢幕閱讀器讀到的還是完整的一句
    expect(screen.getByText("Enter 送出")).toHaveAttribute("aria-hidden", "true")
    expect(screen.getByRole("textbox", { name: "提出問題或下指令" })).toHaveAccessibleDescription("Enter 送出，Shift+Enter 換行")
    fireEvent.click(toggle)
    expect(screen.queryByText(/用掉 5 題/)).toBeNull()
  })

  it("手機的一行輸入框：切換鈕在輸入框下面，44px 高", () => {
    withQuery(<Composer variant="screen" placeholder="搜尋或提問" onSubmit={() => undefined} onForm={() => undefined} />)
    const toggle = screen.getByRole("button", { name: "深度搜尋" })
    expect(toggle).toHaveClass("h-11")
    expect(toggle.closest("form")).toBeNull()
    fireEvent.click(toggle)
    expect(screen.getByText("多查幾輪資料，寫成一份整理，用掉 5 題。")).toBeInTheDocument()
  })

  it("一次算幾題聽後端的；後端說沒有深度搜尋（null）時不放切換鈕", () => {
    expect(deepSearchCost(undefined)).toBe(5)
    expect(deepSearchCost({})).toBe(5)
    expect(deepSearchCost({ deep_search_cost: 3 })).toBe(3)
    expect(deepSearchCost({ deep_search_cost: null })).toBeNull()
    expect(deepSearchHint(3)).toBe("多查幾輪資料，寫成一份整理，用掉 3 題。")
  })
})

describe("對話裡的標示", () => {
  const runner = {} as ReturnType<typeof useAiRunner>
  const at = "2026-11-12T10:00:00+08:00"

  it("深度搜尋的那一題，問句下面一行淡墨的「深度搜尋」；一般的問題沒有", () => {
    const thread: Thread = {
      id: "t1",
      title: "t",
      updatedAt: at,
      messages: [
        { id: "u1", role: "user", text: "深入研究台積電", mode: "deep", at },
        { id: "a1", role: "ai", model: true, text: "整理好了。", at },
        { id: "u2", role: "user", text: "那鴻海呢", at },
      ],
    }
    withQuery(<Conversation thread={thread} runner={runner} />)
    const label = screen.getByText("深度搜尋")
    expect(label).toHaveClass("text-sm", "text-ink-2")
    expect(label.closest("p")).toHaveTextContent("深入研究台積電")
    expect(screen.getByText("那鴻海呢").closest("p")).not.toHaveTextContent("深度搜尋")
  })

  it("從後端載入的對話帶著 mode", () => {
    const detail: ThreadDetail = {
      id: "th_1",
      title: "研究台積電",
      model: "claude-haiku-5-5",
      created_at: at,
      updated_at: at,
      messages: [
        { id: "1", turn_id: "trn_1", role: "user", text: "深入研究台積電", mode: "deep", citations: [], drafts: [], tools: [], error: null, at },
        { id: "2", turn_id: "trn_1", role: "ai", text: "整理", citations: [], drafts: [], tools: [], error: null, at },
        { id: "3", turn_id: "trn_2", role: "user", text: "那鴻海呢", mode: null, citations: [], drafts: [], tools: [], error: null, at },
      ],
    }
    const { thread } = threadFromServer(detail)
    expect(thread.messages.map((m) => m.mode)).toEqual(["deep", undefined, undefined])
  })
})

describe("mock 模式的示範整理", () => {
  const resolve = async (target: string): Promise<Instrument | null> => {
    const hits = await api.searchInstruments(target)
    return hits.find((i) => i.code === target || i.name === target) ?? hits[0] ?? null
  }

  it("問句裡的那一檔：代號優先，其次是拿掉雜字之後的名稱", () => {
    expect(deepTarget("深入研究台積電")).toBe("台積電")
    expect(deepTarget("幫我研究 2317 的風險")).toBe("2317")
    expect(deepTarget("分析 NVDA 最近怎麼樣")).toBe("NVDA")
    expect(deepTarget("研究一下")).toBeNull()
  })

  it("兩三句開頭、最多三個短標題、每點一行用「・」開頭，消息那幾點附來源；沒有 Markdown 符號", async () => {
    const report = await buildLocalDeepReport("深入研究台積電", { api, resolve })
    const blocks = report.text.split("\n\n")
    expect(blocks[0]).toMatch(/^台積電（2330）/)
    expect(blocks[0]).toContain("這份整理用的是示範資料。")
    const groups = blocks.slice(1)
    expect(groups.length).toBeGreaterThanOrEqual(2)
    expect(groups.length).toBeLessThanOrEqual(3)
    for (const g of groups) {
      const [title, ...points] = g.split("\n")
      expect(title!.length).toBeLessThanOrEqual(8)
      expect(title).not.toMatch(/[・：#*]/)
      expect(points.length).toBeGreaterThan(0)
      expect(points.every((p) => p.startsWith("・") && p.endsWith("。"))).toBe(true)
    }
    expect(report.text).not.toMatch(/\*\*|^#|`/m)
    expect(report.text.split("\n").filter((l) => l.startsWith("・")).length).toBeLessThanOrEqual(8)
    expect(report.citations.length).toBeGreaterThan(0)
    expect(report.citations.every((c) => !!c.url && !!c.title)).toBe(true)
  })

  it("問句裡沒有股票：在個股頁就用那一檔，否則說要寫上是哪一檔，不編內容", async () => {
    const onPage = await buildLocalDeepReport("深入研究一下", { api, resolve, fallback: "2317.TW" })
    expect(onPage.text).toMatch(/^鴻海（2317）/)
    const nothing = await buildLocalDeepReport("深入研究一下", { api, resolve: async () => null })
    expect(nothing).toEqual({ text: "示範資料只能整理個股。問的時候寫上是哪一檔，例如「深入研究台積電」。", citations: [] })
  })
})
