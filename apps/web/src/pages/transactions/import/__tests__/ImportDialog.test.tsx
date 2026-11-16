import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { toast, Toaster } from "sonner"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { ApiError, type StatementImport } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { createAppRouter } from "@/router"

/**
 * 匯入對帳單的畫面：PDF 的解密與畫圖、截圖的解碼在 jsdom 裡做不到（沒有 canvas），換成假的；
 * 讀檔、驗算、寫入、復原走 mock 的 API（和後端同一套代碼）。
 */
const pdfCalls: (string | undefined)[] = []
vi.mock("../prepare-pdf", async (orig) => {
  const real = await orig<typeof import("../prepare-pdf")>()
  return {
    ...real,
    // 密碼是假的身分證字號 A123456789：沒給是「需要密碼」、給錯是「密碼不對」
    openPdf: vi.fn(async (_file: Blob, password?: string) => {
      pdfCalls.push(password)
      if (!password) throw new real.PdfPasswordError("need")
      if (password !== "A123456789") throw new real.PdfPasswordError("incorrect")
      return { numPages: 2, loadingTask: { destroy: async () => {} } }
    }),
    preparePdf: vi.fn(async () => ({
      pages: [
        { media_type: "image/jpeg", data: "AAAA", text: "客戶姓名：〔已遮蔽〕" },
        { media_type: "image/jpeg", data: "BBBB", text: "2026/10/13 長榮" },
      ],
      masked: 6,
      scannedPages: 0,
    })),
  }
})
vi.mock("../prepare-image", async (orig) => ({
  ...(await orig<typeof import("../prepare-image")>()),
  prepareImage: vi.fn(async () => [{ media_type: "image/jpeg", data: "CCCC" }]),
}))

const T = { timeout: 8000 }
let desktop = false

beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  Element.prototype.setPointerCapture ??= () => {}
  Element.prototype.releasePointerCapture ??= () => {}
  Element.prototype.hasPointerCapture ??= () => false
  window.matchMedia = ((query: string) => ({
    matches: desktop && query.includes("min-width: 1024px"), media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  // sonner 的通知是全域的：上一個測試的「已匯入」不要留到下一個
  toast.dismiss()
  act(() => useUi.getState().closeImport())
  vi.restoreAllMocks()
  pdfCalls.length = 0
  desktop = false
})

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: ["/"] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  )
}

async function openImport() {
  renderApp()
  await screen.findByText("總資產", {}, T)
  act(() => useUi.getState().openImport())
  return screen.findByRole("dialog", { name: "匯入對帳單" }, T)
}

const fileInput = (dialog: HTMLElement) => dialog.querySelector<HTMLInputElement>("input[type=file]")!
const pdfFile = () => new File(["%PDF-1.7 synthetic"], "202610對帳單.pdf", { type: "application/pdf" })
const pngFile = () => new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])], "成交明細.png", { type: "image/png" })

describe("匯入對帳單", () => {
  it("有密碼的 PDF：密碼不對 → 對的 → 讀成確認表 → 簽名匯入；密碼不會送到伺服器", async () => {
    desktop = true
    const parse = vi.spyOn(api, "parseStatement")
    const user = userEvent.setup()
    const dialog = await openImport()
    await user.upload(fileInput(dialog), pdfFile())
    const pw = await within(dialog).findByLabelText("PDF 密碼", {}, T)
    expect(within(dialog).getByText(/通常是身分證字號，英文大寫。/)).toBeInTheDocument()
    await user.type(pw, "A000000000")
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    expect(await within(dialog).findByText("密碼不對", {}, T)).toBeInTheDocument()
    // 試密碼的時候密碼欄一直在（不會消失再出現）；打錯時整串選起來，直接重打
    expect(pw).toBeInTheDocument()
    expect(pw).toHaveAttribute("aria-invalid", "true")
    await user.clear(pw)
    await user.type(pw, "A123456789{Enter}")
    // 密碼對了就直接開始讀（不用再按一次）
    expect(await within(dialog).findByText("正在讀 2 頁…", {}, T)).toBeInTheDocument()
    const sign = await within(dialog).findByRole("button", { name: /^簽名：匯入 \d+ 筆$/ }, { timeout: 10_000 })
    expect(pdfCalls).toEqual([undefined, "A000000000", "A123456789"])
    expect(parse).toHaveBeenCalledTimes(1)
    const body = parse.mock.calls[0]![0]
    expect(body.kind).toBe("pdf")
    expect(body.pages).toHaveLength(2)
    expect(JSON.stringify(body)).not.toContain("A123456789")
    // 確認表：整份核對、每一列的問題
    expect(within(dialog).getByText("比對帳單的合計少 NT$12,450，可能漏讀了。")).toBeInTheDocument()
    expect(within(dialog).getByText("檔案裡有一段像指令的文字，沒有照做。")).toBeInTheDocument()
    expect(within(dialog).getByText("找不到「台積」。")).toBeInTheDocument()
    expect(within(dialog).getByText("賣出 2,000 股，超過當時持有的 1,000 股。")).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "略過 3 筆股利、1 筆融券" })).toBeInTheDocument()
    const count = Number(sign.getAttribute("aria-label")!.match(/\d+/)![0])
    // 取消勾選一列：簽名格的數字跟著變
    await user.click(within(dialog).getByRole("checkbox", { name: "匯入：10/2 買進 中華電" }))
    expect(within(dialog).getByRole("button", { name: `簽名：匯入 ${count - 1} 筆` })).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: `簽名：匯入 ${count - 1} 筆` }))
    expect(await screen.findByText(`已匯入 ${count - 1} 筆`, {}, T)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "匯入對帳單" })).toBeNull(), T)
  }, 30_000)

  it("賣超：「補一筆買進」只補一次；補的那一筆沒填日期與價格就不能簽名", async () => {
    desktop = true
    const user = userEvent.setup()
    const dialog = await openImport()
    await user.upload(fileInput(dialog), pdfFile())
    await user.type(await within(dialog).findByLabelText("PDF 密碼", {}, T), "A123456789{Enter}")
    await within(dialog).findByRole("button", { name: /^簽名：匯入 \d+ 筆$/ }, { timeout: 10_000 })
    await user.click(within(dialog).getByRole("button", { name: "補一筆買進" }))
    expect(within(dialog).queryByRole("button", { name: "補一筆買進" })).toBeNull()
    // 補的那一筆預設勾著：日期、價格空著，簽名時停下來
    const sign = within(dialog).getByRole("button", { name: /^簽名：匯入 \d+ 筆$/ })
    await user.click(sign)
    expect(await within(dialog).findByText("有 1 筆還沒填好。", {}, T)).toBeInTheDocument()
    expect(within(dialog).getByText("請選日期、請輸入價格。")).toBeInTheDocument()
  }, 30_000)

  it("截圖（手機的抽屜）：「截圖會整張送給 AI 讀。」→ 三筆 → 匯入 → 復原整批", async () => {
    const user = userEvent.setup()
    const dialog = await openImport()
    await user.upload(fileInput(dialog), pngFile())
    expect(await within(dialog).findByText("截圖會整張送給 AI 讀。", {}, T)).toBeInTheDocument()
    await within(dialog).findByText("1 張", {}, T)
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    const sign = await within(dialog).findByRole("button", { name: "簽名：匯入 3 筆" }, { timeout: 10_000 })
    // 手機是一列一筆的清單：「修改」打開欄位
    await user.click(within(dialog).getByRole("button", { name: /^修改第 1 筆/ }))
    expect(within(dialog).getByLabelText("股數")).toBeInTheDocument()
    await user.click(sign)
    expect(await screen.findByText("已匯入 3 筆", {}, T)).toBeInTheDocument()
    const txns = await api.listTransactions({ limit: 200 })
    const imported = txns.items.filter((t) => t.source === "import")
    expect(imported.length).toBeGreaterThanOrEqual(3)
    await user.click(screen.getByRole("button", { name: "復原" }))
    expect(await screen.findByText("已復原這次匯入", {}, T)).toBeInTheDocument()
  }, 30_000)

  it("庫存畫面：直接說還不能匯入，給「換一個檔案」", async () => {
    const doc: StatementImport = {
      document_kind: "holdings_snapshot", broker_name: "", period: null, rows: [], printed_totals: null, totals_check: null,
      unreadable: [], embedded_instructions: [], model_used: "claude-haiku-5-5", retried: false,
    }
    vi.spyOn(api, "parseStatement").mockResolvedValue(doc)
    const user = userEvent.setup()
    const dialog = await openImport()
    await user.upload(fileInput(dialog), pngFile())
    await within(dialog).findByText("1 張", {}, T)
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    expect(await within(dialog).findByText(/^這是庫存畫面，沒有買進日期，還不能匯入。/, {}, T)).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "換一個檔案" }))
    expect(await within(dialog).findByRole("button", { name: "選檔案" }, T)).toBeInTheDocument()
  })

  it("今天的份數用完（429）：照伺服器的句子說，檔案還在", async () => {
    vi.spyOn(api, "parseStatement").mockRejectedValue(new ApiError(429, "ai_import_daily_limit", "今天已經匯入 10 份，明天再匯入。"))
    const user = userEvent.setup()
    const dialog = await openImport()
    await user.upload(fileInput(dialog), pngFile())
    await within(dialog).findByText("1 張", {}, T)
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    expect(await within(dialog).findByText("今天已經匯入 10 份，明天再匯入。", {}, T)).toBeInTheDocument()
    expect(within(dialog).getByText("成交明細.png")).toBeInTheDocument()
  })

  it("一次只能一份 PDF，或最多 5 張截圖，不能混在一起", async () => {
    const user = userEvent.setup()
    const dialog = await openImport()
    await user.upload(fileInput(dialog), [pdfFile(), pngFile()])
    expect(await within(dialog).findByText("一次匯入一份 PDF，或最多 5 張截圖，不能混在一起。", {}, T)).toBeInTheDocument()
  })
})
