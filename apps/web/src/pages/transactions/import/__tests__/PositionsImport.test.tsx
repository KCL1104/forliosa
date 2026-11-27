import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { toast, Toaster } from "sonner"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import type { PositionsCommitCheck, PositionsCommitInput, Transaction, User } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { createAppRouter } from "@/router"

/**
 * 匯入庫存（2026-11-17）與看得到的「匯入」入口：截圖的解碼在 jsdom 裡做不到（沒有 canvas），換成假的；
 * 讀、檢查、寫入、復原走 mock 的 API（和後端同一套代碼與句子）。mock 的帳本在同一個檔案的測試之間是共用的。
 */
vi.mock("../prepare-image", async (orig) => ({
  ...(await orig<typeof import("../prepare-image")>()),
  prepareImage: vi.fn(async () => [{ media_type: "image/jpeg", data: "CCCC" }]),
}))

// 數字動畫（NumberFlow 是 web component）在 jsdom 裡更新數字會丟錯：匯入之後總資產會變，換成一般的字
vi.mock("@number-flow/react", () => ({
  default: ({ value, format, locales }: { value: number; format?: Intl.NumberFormatOptions; locales?: string }) => <span>{new Intl.NumberFormat(locales, format).format(value)}</span>,
}))

const T = { timeout: 8000 }
/** 簽名之後先重新檢查（dry_run）再寫入，mock 兩次都重播整本帳本（前面的測試匯入過、估計日期往前推之後更重）：CI 上會超過 8 秒 */
const COMMIT = { timeout: 20_000 }
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
  toast.dismiss()
  act(() => useUi.getState().closeImport())
  vi.restoreAllMocks()
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

/** 對話框出現時內容可能還沒畫好（CI 上忙的時候拿到 null）：等上傳欄位出現 */
const fileInput = (dialog: HTMLElement) =>
  waitFor(() => {
    const el = dialog.querySelector<HTMLInputElement>("input[type=file]")
    if (!el) throw new Error("還沒有上傳欄位")
    return el
  }, T)
const pngFile = (name = "庫存.png") => new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])], name, { type: "image/png" })

async function allTxns(): Promise<Transaction[]> {
  const out: Transaction[] = []
  let cursor: string | undefined
  do {
    const page = await api.listTransactions({ limit: 200, cursor })
    out.push(...page.items)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return out
}

/** 帳本工具列的「匯入」（桌面和手機各一顆，jsdom 沒有 CSS 兩顆都在：按第一顆）→ 選擇 */
async function openFromToolbar(user: ReturnType<typeof userEvent.setup>) {
  renderApp()
  // 帳本出來了（主數字的標籤與走勢的圖例都寫「總資產」）
  await screen.findAllByText("總資產", {}, T)
  const buttons = await screen.findAllByRole("button", { name: "匯入" }, T)
  await user.click(buttons[0]!)
  return screen.findByRole("dialog", { name: "匯入" }, T)
}

describe("匯入庫存", () => {
  it("工具列的「匯入」→ 選匯入庫存 → 截圖 → 確認表 → 換成券商 → 簽名 → 已匯入 → 復原先問一次（舊紀錄不會回來）", async () => {
    desktop = true
    const parse = vi.spyOn(api, "parsePositions")
    const commit = vi.spyOn(api, "commitPositions")
    const user = userEvent.setup()
    const chooser = await openFromToolbar(user)
    // 兩個選擇：匯入庫存（現有持股，最快）在上面
    const choices = within(chooser).getAllByRole("button").filter((b) => /匯入(庫存|對帳單)/.test(b.textContent ?? ""))
    expect(choices.map((b) => b.textContent)).toEqual([expect.stringMatching(/^匯入庫存現有持股，最快/), expect.stringMatching(/^匯入對帳單交易明細/)])
    await user.click(choices[0]!)
    const dialog = await screen.findByRole("dialog", { name: "匯入庫存" }, T)
    // 按過的那一列不在了：焦點移到新的第一個控制項（「截圖｜貼上文字」選中的那一個）
    await waitFor(() => expect(within(dialog).getByRole("tab", { name: "截圖" })).toHaveFocus(), T)
    await user.upload(await fileInput(dialog), [pngFile("庫存1.png"), pngFile("庫存2.png")])
    expect(await within(dialog).findByText("截圖會整張送給 AI 讀。", {}, T)).toBeInTheDocument()
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "開始讀" })).toBeEnabled(), T)
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    const sign = await within(dialog).findByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }, { timeout: 20_000 })
    expect(parse.mock.calls[0]![0]).toMatchObject({ kind: "images" })
    expect(parse.mock.calls[0]![0].pages).toHaveLength(2)

    // 確認表：整批的買進日期、重疊的列只算一次；機制的說明（均價到那天收盤的漲跌算進那一天的報酬）收在「日期怎麼算」
    expect(within(dialog).getByLabelText("買進日期")).toBeInTheDocument()
    expect(within(dialog).queryByText(/均價到.*收盤的漲跌/)).toBeNull()
    const how = within(dialog).getByRole("button", { name: "日期怎麼算" })
    expect(how).toHaveAttribute("aria-expanded", "false")
    await user.click(how)
    // 資產組成原型：伺服器估了買入日（只是建議），多一行估計是什麼；有估不到的列，多一行「—」是什麼（舊版伺服器只有買進日，見下面）
    expect(within(dialog).getByText("均價到那天收盤的漲跌算進那天的報酬，那天之前沒有走勢。")).toBeInTheDocument()
    expect(within(dialog).getByText("股價最近一次經過均價的那一天。")).toBeInTheDocument()
    expect(within(dialog).getByText("股價沒有經過均價，估不到。")).toBeInTheDocument()
    expect(within(dialog).getByText(/永豐金證券・讀到 7 檔・重疊的 1 列只算一次/)).toBeInTheDocument()
    // 已在帳本：沒有勾選框（不把刪掉舊紀錄藏在勾選裡），下面一格帳本的股數與均價（標籤）＋「保留帳本｜換成券商」，預設保留
    expect(within(dialog).queryByRole("checkbox", { name: /台積電/ })).toBeNull()
    const tsmc = within(dialog).getByRole("radiogroup", { name: "台積電：保留帳本或換成券商" })
    expect(within(tsmc).getByRole("radio", { name: "保留帳本" })).toBeChecked()
    const swap = within(tsmc).getByRole("radio", { name: "換成券商" })
    expect(swap).not.toBeChecked()
    // 會刪幾筆：選之前只給報讀器（念在「換成券商」上），選了才看得到
    expect(swap).toHaveAccessibleDescription(/^會刪 \d+ 筆(（含 .+）)?$/)
    expect(within(dialog).getByText(/^會刪 \d+ 筆/, { selector: `#${swap.getAttribute("aria-describedby")}` })).toHaveClass("sr-only")
    expect(within(dialog).queryByText("已在帳本")).toBeNull()
    expect(within(dialog).getByText(/^已在帳本 1,500 股・均價 [\d.]+$/)).toBeInTheDocument()
    expect(within(dialog).getByText("已在帳本・股數和均價相同")).toBeInTheDocument()
    // 名稱是這一列最主要的字：墨色（沒勾的列也是）
    expect(within(dialog).getByText("台積電", { selector: "button span" })).toHaveClass("text-ink", "text-base")
    // 融資不寫句子：代號旁的「融資」
    expect(within(dialog).queryByText("融資・當成一般持股匯入")).toBeNull()
    expect(within(dialog).getByText("融資")).toHaveClass("status-tag")
    // 只有總成本：均價是算出來的；找不到、融券
    expect(within(dialog).getByRole("textbox", { name: "第 4 檔的均價" })).toHaveValue("120")
    expect(within(dialog).getByRole("textbox", { name: "第 4 檔的總成本" })).toHaveValue("180,000")
    expect(within(dialog).getByText("找不到「台光電」")).toBeInTheDocument()
    expect(within(dialog).getByRole("checkbox", { name: "匯入：台光電（還沒選股票）" })).not.toBeChecked()
    expect(within(dialog).getByRole("button", { name: "略過 1 檔融券" })).toBeInTheDocument()
    const count = Number(sign.getAttribute("aria-label")!.match(/\d+/)![0])

    // 換成券商：選了就匯入，旁邊寫會刪幾筆（墨色標籤），動作列照實說舊紀錄會刪掉、復原也不會回來
    await user.click(swap)
    expect(swap).toBeChecked()
    expect(within(dialog).getByText(/^會刪 \d+ 筆/, { selector: `#${swap.getAttribute("aria-describedby")}` })).not.toHaveClass("sr-only")
    expect(within(dialog).getByText(/^換成券商會刪掉台積電 \d+ 筆舊紀錄(，連同(領過的股利|賣出的損益|領過的股利、賣出的損益))?（定期定額不動），復原時也不會回來。$/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: `簽名：匯入 ${count + 1} 檔` }))
    expect(await screen.findByText(`已匯入 ${count + 1} 檔`, {}, COMMIT)).toBeInTheDocument()
    expect(screen.getByText(/^換成券商刪掉了台積電 \d+ 筆舊紀錄。/)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "匯入庫存" })).toBeNull(), T)

    // 送出去的：每一檔一筆，只給總成本的送總成本，台積電 replace
    const body = commit.mock.calls[0]![0]
    // 資產組成原型：沒按「套用」，每一檔都跟著整批的日期（匯入那天，`import_day`）——中華電估不到（null），台積電的估計照樣帶著
    expect(body.rows.find((r) => r.symbol === "2412.TW")).toEqual({ symbol: "2412.TW", quantity: 1500, total_cost: 180000, currency: "TWD", date_basis: "import_day", estimated_date: null })
    expect(body.rows.find((r) => r.symbol === "2330.TW")).toEqual({ symbol: "2330.TW", quantity: 1500, price: 612.4, currency: "TWD", replace: true, date_basis: "import_day", estimated_date: "2023-05-08" })
    const mine = (await allTxns()).filter((t) => t.source === "import" && t.symbol === "2330.TW")
    expect(mine.map((t) => [t.quantity, t.price, t.fee])).toEqual([[1500, 612.4, 0]])

    // 復原：先問一次，照實說舊紀錄回不來
    await user.click(screen.getByRole("button", { name: "復原" }))
    const confirm = await screen.findByRole("alertdialog", {}, T)
    expect(within(confirm).getByText(/換成券商刪掉的舊紀錄（台積電 \d+ 筆）不會回來：復原之後，這個帳戶裡就沒有台積電了，要的話得自己再記。/)).toBeInTheDocument()
    await user.click(within(confirm).getByRole("button", { name: "復原" }))
    expect(await screen.findByText("已復原這次匯入", {}, T)).toBeInTheDocument()
    expect((await allTxns()).some((t) => t.source === "import" && t.symbol === "2330.TW")).toBe(false)
  }, 60_000)

  it("貼上文字：送出前在這台裝置上先塗掉個資；交易明細 → 改用匯入對帳單", async () => {
    desktop = true
    const parse = vi.spyOn(api, "parsePositions")
    const user = userEvent.setup()
    renderApp()
    await screen.findAllByText("總資產", {}, T)
    act(() => useUi.getState().openImport("positions"))
    const dialog = await screen.findByRole("dialog", { name: "匯入庫存" }, T)
    await user.click(within(dialog).getByRole("tab", { name: "貼上文字" }))
    const box = within(dialog).getByLabelText("庫存的文字")
    await user.click(box)
    await user.paste("身分證字號：A123456789\n0056 元大高股息 2 張 均價 36.5")
    expect(within(dialog).getByText("送出前會先塗掉 1 處個資。")).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    await within(dialog).findByRole("button", { name: "簽名：匯入 1 檔" }, { timeout: 20_000 })
    const sent = parse.mock.calls[0]![0]
    expect(sent.kind).toBe("text")
    expect(sent.text).toContain("〔已遮蔽〕")
    expect(JSON.stringify(sent)).not.toContain("A123456789")
    // 換一段：交易明細
    await user.click(within(dialog).getByRole("button", { name: "改貼別的文字" }))
    await user.click(within(dialog).getByRole("tab", { name: "貼上文字" }))
    await user.click(within(dialog).getByLabelText("庫存的文字"))
    await user.paste("2026/10/13 買進 2330 台積電 1,000 股 1,030")
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    expect(await within(dialog).findByText("這是交易明細・改用匯入對帳單", {}, T)).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "改用匯入對帳單" }))
    expect(await screen.findByRole("dialog", { name: "匯入對帳單" }, T)).toBeInTheDocument()
  }, 45_000)

  it("手機：工具列的「匯入」→ 抽屜裡選匯入庫存 → 一列一檔（修改打開欄位）→ 匯入", async () => {
    const user = userEvent.setup()
    const chooser = await openFromToolbar(user)
    await user.click(within(chooser).getByRole("button", { name: /^匯入庫存/ }))
    const sheet = await screen.findByRole("dialog", { name: "匯入庫存" }, T)
    await user.upload(await fileInput(sheet), pngFile())
    await waitFor(() => expect(within(sheet).getByRole("button", { name: "開始讀" })).toBeEnabled(), T)
    await user.click(within(sheet).getByRole("button", { name: "開始讀" }))
    const sign = await within(sheet).findByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }, { timeout: 20_000 })
    expect(within(sheet).getByRole("list", { name: "讀出來的持股" })).toBeInTheDocument()
    // 資產組成原型：估計的買入日是那一檔第二行下面的建議，按「套用」才改（第二行下面寫「估計 2023/5/8 買進」）
    expect(within(sheet).getByText("估計買入日 2023/5/8")).toBeInTheDocument()
    await user.click(within(sheet).getByRole("button", { name: "套用第 1 檔的估計買入日 2023/5/8" }))
    expect(within(sheet).getByText("估計 2023/5/8 買進")).toBeInTheDocument()
    expect(within(sheet).queryByText("估計買入日 2023/5/8")).toBeNull()
    await user.click(within(sheet).getByRole("button", { name: "修改第 3 檔：富邦金" }))
    expect(within(sheet).getByLabelText("均價")).toHaveValue("88.6")
    await waitFor(() => expect(sign).toBeEnabled(), T)
    await user.click(sign)
    expect(await screen.findByText(/^已匯入 \d+ 檔$/, {}, COMMIT)).toBeInTheDocument()
  }, 45_000)
})

describe("匯入庫存：換帳戶、沒填好的列", () => {
  /** 讀一張截圖到確認表（桌面或手機） */
  async function readToReview(user: ReturnType<typeof userEvent.setup>) {
    const chooser = await openFromToolbar(user)
    await user.click(within(chooser).getByRole("button", { name: /^匯入庫存/ }))
    const dialog = await screen.findByRole("dialog", { name: "匯入庫存" }, T)
    await user.upload(await fileInput(dialog), pngFile())
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "開始讀" })).toBeEnabled(), T)
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    await within(dialog).findByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }, { timeout: 20_000 })
    return dialog
  }

  /** 檢查（dry_run）先停著，測試決定什麼時候回來；回來的是「台積電在這個帳戶有 N 股」 */
  function holdCheck(quantity: number) {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const spy = vi.spyOn(api, "checkPositions").mockImplementation(async (body: PositionsCommitInput) => {
      await gate
      return {
        dry_run: true, ok: true, trade_date: body.trade_date ?? "2026-11-17", replaced: [], problems: [],
        rows: body.rows.map((r, index) => ({
          index, flags: [],
          in_ledger: r.symbol === "2330.TW" ? { quantity, avg_cost: 500, currency: "TWD" as const, records: 2, dividends: 1, sells: 0 } : null,
        })),
      } satisfies PositionsCommitCheck
    })
    return { spy, release }
  }

  async function pickAccount(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement, name: RegExp) {
    await user.click(within(dialog).getByRole("combobox", { name: "券商帳戶" }))
    await user.click(await screen.findByRole("option", { name }, T))
  }

  it("換成券商只對選的那個帳戶：換到也有這一檔的帳戶就回到保留帳本（檢查途中選的也一樣），要對新的帳戶重新選", async () => {
    desktop = true
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const dialog = await readToReview(user)
    const choice = () => within(dialog).getByRole("radiogroup", { name: "台積電：保留帳本或換成券商" })
    const swap = () => within(choice()).getByRole("radio", { name: "換成券商" })
    const keep = () => within(choice()).getByRole("radio", { name: "保留帳本" })
    const count = () => Number(within(dialog).getByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }).getAttribute("aria-label")!.match(/\d+/)![0])
    const before = count()

    // 在「永豐・一般」選了換成券商（多匯入一檔），再換到「國泰・複委託」（也有台積電）
    await user.click(swap())
    expect(swap()).toBeChecked()
    expect(count()).toBe(before + 1)
    let held = holdCheck(300)
    await pickAccount(user, dialog, /國泰・複委託/)
    await act(async () => held.release())
    await within(dialog).findByText("已在帳本 300 股・均價 500", {}, T)
    expect(held.spy.mock.calls[0]![0]).toMatchObject({ account_id: "acc_01JCATHAYUS" })
    expect(keep()).toBeChecked()
    expect(swap()).not.toBeChecked()
    expect(within(dialog).queryByText(/^換成券商會刪掉/)).toBeNull()
    // 新的帳戶的刪除照實說：含股利
    expect(swap()).toHaveAccessibleDescription("會刪 2 筆（含 1 筆股利）")
    held.spy.mockRestore()

    // 換回「永豐・一般」，檢查還沒回來時選了換成券商（畫面上還是國泰的那一格）：回來之後也回到保留帳本
    held = holdCheck(1500)
    await pickAccount(user, dialog, /永豐・一般/)
    await user.click(swap())
    expect(swap()).toBeChecked()
    await act(async () => held.release())
    await within(dialog).findByText("已在帳本 1,500 股・均價 500", {}, T)
    expect(keep()).toBeChecked()
    expect(swap()).not.toBeChecked()
    // 對這個帳戶重新選：就照選的；方向鍵也可以切換（radiogroup）
    swap().focus()
    await user.keyboard("{ArrowLeft}")
    expect(keep()).toBeChecked()
    await waitFor(() => expect(keep()).toHaveFocus(), T)
    await user.keyboard("{ArrowRight}")
    expect(swap()).toBeChecked()
    expect(within(dialog).getByText("會刪 2 筆（含 1 筆股利）")).not.toHaveClass("sr-only")
    expect(within(dialog).getByText("換成券商會刪掉台積電 2 筆舊紀錄，連同領過的股利（定期定額不動），復原時也不會回來。")).toBeInTheDocument()
  }, 60_000)

  it("手機：按簽名時有沒填好的列——點名那一檔、焦點移到那一格；同一個錯誤只寫一次", async () => {
    const user = userEvent.setup()
    const sheet = await readToReview(user)
    await user.click(within(sheet).getByRole("checkbox", { name: "匯入：台光電（還沒選股票）" }))
    await user.click(within(sheet).getByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }))
    expect(await within(sheet).findByText("台光電還沒填好。", {}, T)).toBeInTheDocument()
    expect(document.activeElement).toHaveAccessibleName("第 6 檔的股票：還沒選（畫面上寫「台光電」）")
    // 原因寫在欄位下面一次；句子旁邊的「選一檔」不放（股票欄位就在那裡）
    expect(within(sheet).getAllByText(/請選股票/)).toHaveLength(1)
    expect(within(sheet).queryByRole("button", { name: "選一檔" })).toBeNull()
  }, 45_000)
})

describe("匯入的入口", () => {
  it("記一筆第一步的「匯入庫存或對帳單」、AI 輸入框的「＋」都打開同一個選擇", async () => {
    desktop = true
    const user = userEvent.setup()
    renderApp()
    await screen.findAllByText("總資產", {}, T)
    act(() => useUi.getState().openTradeForm())
    await user.click(await screen.findByRole("button", { name: "匯入庫存或對帳單" }, T))
    expect(await screen.findByRole("dialog", { name: "匯入" }, T)).toBeInTheDocument()
    act(() => useUi.getState().closeImport())
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "匯入" })).toBeNull(), T)
    await user.click(screen.getByRole("button", { name: "記一筆或匯入" }))
    await user.click(await screen.findByRole("menuitem", { name: "匯入庫存或對帳單" }, T))
    const chooser = await screen.findByRole("dialog", { name: "匯入" }, T)
    await user.click(within(chooser).getByRole("button", { name: /^匯入對帳單/ }))
    expect(await screen.findByRole("dialog", { name: "匯入對帳單" }, T)).toBeInTheDocument()
  }, 30_000)

  it("沒開放匯入的帳號：工具列沒有「匯入」", async () => {
    const me = await api.getMe()
    vi.spyOn(api, "getMe").mockResolvedValue({ ...me, plan: { ...me.plan!, statement_import: false } } as User)
    renderApp()
    await screen.findAllByText("總資產", {}, T)
    await screen.findAllByRole("button", { name: "記一筆" }, T)
    expect(screen.queryByRole("button", { name: "匯入" })).toBeNull()
  })
})

describe("匯入庫存：估計的買入日（資產組成原型）", () => {
  async function readShot(user: ReturnType<typeof userEvent.setup>) {
    renderApp()
    await screen.findAllByText("總資產", {}, T)
    act(() => useUi.getState().openImport("positions"))
    const dialog = await screen.findByRole("dialog", { name: "匯入庫存" }, T)
    await user.upload(await fileInput(dialog), pngFile())
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "開始讀" })).toBeEnabled(), T)
    await user.click(within(dialog).getByRole("button", { name: "開始讀" }))
    await within(dialog).findByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }, { timeout: 20_000 })
    return dialog
  }

  it("估計只是建議：日期照整批（匯入那天），日期下面「估計 2023/5/8」＋「套用」；按了才改成那天、送 estimated；估不到的是「估計 —」", async () => {
    desktop = true
    // 這個測試只看送出去的內容，所以寫入停著不回來。原本讓它真的寫（mock 重播整本帳本），測試結束時還在跑；
    // 跑完會呼叫全域的 closeImport()，把下一個測試剛打開的匯入視窗關掉——慢的 CI 機器上，下一個測試就等不到上傳欄位
    const commit = vi.spyOn(api, "commitPositions").mockImplementation(() => new Promise(() => {}))
    const user = userEvent.setup()
    const dialog = await readShot(user)
    const batch = within(dialog).getByLabelText("買進日期")
    // 第 1 檔（台積電）：日期跟著整批，不寫「估計」；日期那一欄下面是建議
    const date1 = within(dialog).getByRole("button", { name: /^第 1 檔的買進日期：/ })
    expect(date1).toHaveClass("text-ink-2")
    expect(date1.textContent).not.toMatch(/估計/)
    expect(within(dialog).getByText("估計 2023/5/8")).toHaveClass("num")
    const apply = within(dialog).getByRole("button", { name: "套用第 1 檔的估計買入日 2023/5/8" })
    expect(apply).toHaveTextContent(/^套用$/)
    // 中華電：五年內股價都沒有經過均價，沒有建議；日期下面「估計 —」，不寫原因的句子（「—」是什麼收在「日期怎麼算」）
    expect(within(dialog).queryByText(/估不到買入日/)).toBeNull()
    const cannot = within(dialog).getByText("估不到")
    expect(cannot).toHaveClass("sr-only")
    expect(cannot.parentElement).toHaveTextContent(/^估計 —估不到$/)
    expect(within(dialog).queryByRole("button", { name: /^套用第 4 檔/ })).toBeNull()

    // 套用：這一列的日期改成估計的那天（墨色、寫「估計 2023/5/8」），建議不再出現；整批的日期不動
    await user.click(apply)
    const applied = within(dialog).getByRole("button", { name: /^第 1 檔的買進日期（估計）：2023\/5\/8（/ })
    expect(applied).toHaveTextContent("估計 2023/5/8")
    expect(applied).toHaveClass("text-ink")
    expect(within(dialog).queryByRole("button", { name: /^套用第 1 檔/ })).toBeNull()
    expect(batch).not.toHaveTextContent("2023")

    // 送出去：台積電（已在帳本，選換成券商）是 estimated＋那一天
    await user.click(within(dialog).getAllByRole("radio", { name: "換成券商" })[0]!)
    await user.click(within(dialog).getByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }))
    await waitFor(() => expect(commit).toHaveBeenCalled(), COMMIT)
    expect(commit.mock.calls[0]![0].rows.find((r) => r.symbol === "2330.TW")).toMatchObject({ trade_date: "2023-05-08", date_basis: "estimated", estimated_date: "2023-05-08" })
  }, 45_000)

  it("舊版伺服器（沒有 estimated_date）：整批一個日期，「日期怎麼算」只有買進日", async () => {
    desktop = true
    const real = api.parsePositions.bind(api)
    vi.spyOn(api, "parsePositions").mockImplementation(async (body, opts) => {
      const doc = await real(body, opts)
      return { ...doc, rows: doc.rows.map(({ estimated_date: _e, ...r }) => ({ ...r, flags: r.flags.filter((f) => f.code !== "no_crossing") })) }
    })
    const user = userEvent.setup()
    const dialog = await readShot(user)
    await user.click(within(dialog).getByRole("button", { name: "日期怎麼算" }))
    expect(within(dialog).getByText("均價到那天收盤的漲跌算進那天的報酬，那天之前沒有走勢。")).toBeInTheDocument()
    expect(within(dialog).queryByText("股價最近一次經過均價的那一天。")).toBeNull()
    expect(within(dialog).queryByText(/^估計/)).toBeNull()
    expect(within(dialog).queryByText("估不到")).toBeNull()
    expect(within(dialog).queryByRole("button", { name: /^套用/ })).toBeNull()
    // 送出去的列不帶日期的來由（舊版伺服器不認得 date_basis、estimated_date）。
    // 同一個檔案前面的測試可能已經匯入過這幾檔（都「已在帳本」、預設保留）：選一個「換成券商」，一定有東西可以送
    await user.click(within(dialog).getAllByRole("radio", { name: "換成券商" })[0]!)
    // 看按下簽名時的重新檢查（dry_run，和寫入同一個 `toCommitRow`）：一按就送，不用等 mock 重播整本帳本再寫入
    // （CI 上那一段曾經超過 8 秒）。檢查停著不回來：後面什麼都不寫，測試結束時沒有還在跑的寫入
    const check = vi.spyOn(api, "checkPositions").mockImplementation(() => new Promise(() => {}))
    await user.click(within(dialog).getByRole("button", { name: /^簽名：匯入 \d+ 檔$/ }))
    await waitFor(() => expect(check).toHaveBeenCalled(), T)
    const rows = check.mock.calls[0]![0].rows
    expect(rows.length).toBeGreaterThan(0)
    for (const r of rows) {
      expect(r).not.toHaveProperty("date_basis")
      expect(r).not.toHaveProperty("estimated_date")
    }
  }, 45_000)
})
